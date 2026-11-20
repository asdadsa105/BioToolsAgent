"""Build/update BioSkillKG from Markdown.

Legacy rule mode (no LLM):
  python build_bio_skill_kg.py --input examples/bio_skills

Automated DeepSeek extraction mode:
  python build_bio_skill_kg.py --input examples/bio_skills --llm
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from text_ingestion.document_loader import load_documents
from bio_skill_kg.builder import build_graph, merge_graphs, summary, load_aliases
from bio_skill_kg.auto_builder import (
    build_graph_from_extractions, load_data_type_ontology, load_ontology_aliases, load_file_format_ontology, NORMALIZATION_VERSION, synchronize_curated_ontology,
)
from bio_skill_kg.llm_extractor import DeepSeekBioSkillExtractor, load_llm_config, PROMPT_VERSION
from check_bioskill_ports import inspect_graph


def write_json_atomic(file: Path, content) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f'.{file.name}.', suffix='.tmp', dir=file.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(content, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        os.replace(temp, file)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def report_diff(old: dict | None, merged: dict) -> dict:
    if not old:
        return {'new_nodes':len(merged['nodes']), 'new_edges':len(merged['edges']),
                'enriched_tools':[], 'changed_properties':0,
                'added_review_items':len(merged['review'])}
    old_nodes={x['id']:x for x in old['nodes']}
    new_nodes={x['id']:x for x in merged['nodes']}
    old_edges={(x['source'],x['type'],x['target']) for x in old['edges']}
    new_edges={(x['source'],x['type'],x['target']) for x in merged['edges']}
    old_review={json.dumps(x,sort_keys=True,ensure_ascii=False) for x in old.get('review',[])}
    new_review={json.dumps(x,sort_keys=True,ensure_ascii=False) for x in merged.get('review',[])}
    enriched=[nid for nid in old_nodes.keys() & new_nodes.keys()
              if old_nodes[nid]['label']=='Tool' and old_nodes[nid]['properties'].get('stub',False)
              and not new_nodes[nid]['properties'].get('stub',False)]
    changed=sum(old_nodes[k]['properties'] != new_nodes[k]['properties'] for k in old_nodes.keys() & new_nodes.keys())
    return {'new_nodes':len(new_nodes.keys()-old_nodes.keys()),
            'new_edges':len(new_edges-old_edges),
            'enriched_tools':sorted(enriched), 'changed_properties':changed,
            'added_review_items':len(new_review-old_review)}


def main():
    ap=argparse.ArgumentParser(description='Build/update BioSkillKG from Skill Markdown')
    ap.add_argument('--input',default='examples/bio_skills',help='Single .md file or directory')
    ap.add_argument('--output',default='data/bio_skill_kg/bio_skill_graph.json')
    ap.add_argument('--aliases',default=None,help='JSON file containing explicit Tool name aliases')
    ap.add_argument('--conflict-policy',choices=['keep-existing','prefer-incoming'],
                    default='keep-existing',help='For conflicting nonempty entity properties')
    ap.add_argument('--dry-run',action='store_true',help='Preview graph changes; do not write graph/review/report')
    ap.add_argument('--strict-ports',action='store_true',help='Abort before writing if any port has unknown type or missing formal edge')
    ap.add_argument('--fresh',action='store_true',help='Start a fresh graph; use NEW output path or --confirm-reset')
    ap.add_argument('--confirm-reset',action='store_true',help='Allow overwriting existing graph with --fresh')

    # LLM extraction options. Legacy rule mode remains available for reproducibility.
    ap.add_argument('--llm',action='store_true',help='Use DeepSeek to automatically extract Operation/Task/IO/relations; no per-tool profiles required')
    ap.add_argument('--env-file',default='.env',help='Environment file containing DEEPSEEK_API_KEY')
    ap.add_argument('--model',default=None,help='Override DEEPSEEK_MODEL')
    ap.add_argument('--base-url',default=None,help='Override DEEPSEEK_BASE_URL')
    ap.add_argument('--cache-dir',default='data/bio_skill_kg/extraction_cache',help='LLM chunk cache directory')
    ap.add_argument('--extraction-dir',default='data/bio_skill_kg/extracted_skills',help='Saved intermediate extraction JSON directory')
    ap.add_argument('--chunk-chars',type=int,default=12000,help='Maximum characters per LLM chunk')
    ap.add_argument('--chunk-overlap',type=int,default=300,help='Character overlap when a single Markdown section is split')
    ap.add_argument('--max-output-tokens',type=int,default=6000,help='Maximum model output tokens per chunk')
    ap.add_argument('--force-extract',action='store_true',help='Ignore extraction cache and call DeepSeek again')
    ap.add_argument('--ontology',default=None,help='Optional global DataType vocabulary JSON (defaults to bio_skill_kg/data_types.json)')
    ap.add_argument('--ontology-aliases',default=None,help='Optional global DataType alias JSON')
    ap.add_argument('--file-formats',default=None,help='Optional file-format registry JSON (defaults to bio_skill_kg/file_formats.json)')
    args=ap.parse_args()

    target=Path(args.output).resolve()
    if args.fresh and target.exists() and not args.confirm_reset:
        ap.error('Existing output with --fresh requires --confirm-reset; otherwise use incremental mode')
    if args.chunk_chars < 1000 or args.chunk_overlap < 0 or args.chunk_overlap >= args.chunk_chars:
        ap.error('--chunk-chars must be >= 1000 and 0 <= --chunk-overlap < --chunk-chars')

    aliases=load_aliases(args.aliases)
    docs=load_documents(args.input)
    extraction_stats = None
    extraction_files = []
    extractor = None
    try:
        if args.llm:
            try:
                key, base_url, model = load_llm_config(args.env_file, args.model, args.base_url)
                extractor = DeepSeekBioSkillExtractor(
                    key, base_url, model, Path(args.cache_dir),
                    max_output_tokens=args.max_output_tokens,
                )
            except (ValueError, RuntimeError) as exc:
                ap.error(str(exc))
            extractions=[]
            for index, doc in enumerate(docs, 1):
                print(f'[{index}/{len(docs)}] DeepSeek extracting: {Path(doc.file_path).name}')
                extracted = extractor.extract_document(
                    doc, max_chars=args.chunk_chars, overlap_chars=args.chunk_overlap,
                    force=args.force_extract,
                )
                extractions.append(extracted)
                extraction_files.append({
                    'file': Path(doc.file_path).name,
                    'doc_id': doc.doc_id,
                    'path': str(Path(args.extraction_dir) / f'{Path(doc.file_path).stem}_{doc.doc_id}.json'),
                    'operations': len(extracted.get('operations', [])),
                    'data_types': len(extracted.get('data_types', [])),
                    'tool_relations': len(extracted.get('tool_relations', [])),
                    'review_items': len(extracted.get('review', [])),
                })
            incoming=build_graph_from_extractions(
                docs, extractions, aliases=aliases,
                ontology=load_data_type_ontology(args.ontology),
                ontology_aliases=load_ontology_aliases(args.ontology_aliases),
                file_formats=load_file_format_ontology(args.file_formats),
            )
            extraction_stats = {**extractor.stats, 'model': model, 'prompt_version': PROMPT_VERSION}
        else:
            incoming=build_graph(docs, aliases=aliases)
    finally:
        if extractor is not None:
            extractor.close()

    original=None
    if target.is_file() and not args.fresh:
        original=json.loads(target.read_text(encoding='utf-8'))
        result=merge_graphs(original,incoming,aliases=aliases,
                            conflict_policy=args.conflict_policy)
    else:
        result=incoming

    # Ontology definitions are authoritative only for curated DataType metadata.
    # Keep original per-document claims; don't alter I/O ports or candidate links.
    ontology_updates = (synchronize_curated_ontology(result, load_data_type_ontology(args.ontology))
                        if args.llm else 0)
    port_audit=inspect_graph(result)
    if args.strict_ports and not port_audit['publish_ready']:
        ap.error(f"Refusing graph write: {port_audit['pending_ports']} pending ports, {len(port_audit['errors'])} errors; use a test output without --strict-ports to inspect candidate types")

    report={'input_files':[Path(doc.file_path).name for doc in docs],
            'output':str(target), 'schema':result['schema'],
            'normalization_version': NORMALIZATION_VERSION if args.llm else 'legacy-rule-builder',
            'ontology_metadata_updates': ontology_updates,
            'mode':'llm_incremental' if args.llm else ('fresh' if args.fresh else 'rule_incremental'),
            'graph':summary(result), 'changes':report_diff(original,result),
            'llm':extraction_stats,
            'extraction_files':extraction_files if args.llm else [],
            'port_audit': {k:v for k,v in port_audit.items() if k!='candidates'}}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.dry_run:
        print('DRY RUN: graph, review, report, and extracted-skill files were not written (LLM cache may be populated).')
        return

    if args.llm:
        extraction_dir=Path(args.extraction_dir)
        for doc, extracted in zip(docs, extractions):
            out=extraction_dir/f'{Path(doc.file_path).stem}_{doc.doc_id}.json'
            write_json_atomic(out, extracted)

    if target.exists():
        backup_dir=target.parent/'backups'
        backup_dir.mkdir(parents=True,exist_ok=True)
        timestamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup=backup_dir/f'{target.stem}_{timestamp}.json'
        shutil.copy2(target,backup)
        print(f'Backup created: {backup}')
    write_json_atomic(target,result)
    write_json_atomic(target.with_name('bio_skill_review.json'),result['review'])
    write_json_atomic(target.with_name('bio_skill_port_audit.json'),port_audit)
    write_json_atomic(target.with_name('bio_skill_build_report.json'),report)
    print(f'Saved graph: {target}')
    if args.llm:
        print(f'Saved intermediate extraction JSON files: {args.extraction_dir}')
    print('Original SciToolKG was NOT modified. Neo4j was NOT modified.')


if __name__ == '__main__':
    main()
