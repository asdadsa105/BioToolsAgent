#!/usr/bin/env python3
"""Rebuild a CLEAN BioSkillKG from validated extraction JSON, without LLM calls.

Rationale: append-only MERGE cannot remove stale unresolved port properties or
obsolete edges after ontology changes. Rebuild from source extracts in a
separate staging output, inspect, then choose whether to publish.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from text_ingestion.document_loader import load_documents
from bio_skill_kg.auto_builder import (build_graph_from_extractions, load_data_type_ontology,
                                       load_ontology_aliases, load_file_format_ontology, synchronize_curated_ontology)
from bio_skill_kg.builder import load_aliases, merge_graphs
from build_bio_skill_kg import write_json_atomic
from check_bioskill_ports import inspect_graph


def locate_extraction(doc, locations: list[Path]) -> Path:
    stem = Path(doc.file_path).stem
    filename = Path(doc.file_path).name
    found = []
    for directory in locations:
        if not directory.is_dir():
            continue
        found += [p for p in directory.glob(f'{stem}*.json') if p.is_file()]
    found = sorted(set(found))
    if not found:
        raise FileNotFoundError(f'Missing extraction for {filename}; expected {stem}*.json in {locations}. First run LLM build for this MD.')
    # Prioritize verified v5.4 inputs over older raw caches; otherwise newest.
    verified = [p for p in found if p.name == stem + '_v54.json']
    return verified[0] if verified else max(found, key=lambda p:p.stat().st_mtime)


def main():
    p=argparse.ArgumentParser(description='Re-normalize existing MD extractions with current version of the ontology')
    p.add_argument('--input',default='examples/bio_skills',help='MD file or directory')
    p.add_argument('--extractions',action='append',default=[],help='Extraction folder; repeatable')
    p.add_argument('--output',required=True, type=Path,help='NEW staging output; must not overwrite existing file')
    p.add_argument('--base',type=Path,default=None,help='Previously verified BASELINE graph without the incoming MD; allows replay even if old source MDs are unavailable')
    p.add_argument('--ontology',default=None)
    p.add_argument('--ontology-aliases',default=None)
    p.add_argument('--strict-ports',action='store_true')
    args=p.parse_args()
    if args.output.exists():
        p.error('Refusing existing --output; use a new staging filename to avoid accidental destructive overwrite')
    extraction_dirs=[Path(x) for x in args.extractions] if args.extractions else [
        Path('data/bio_skill_kg/v54_clean/verified_extractions'),Path('data/bio_skill_kg/extracted_skills')]
    docs=load_documents(args.input)
    extractions=[]
    sources={}
    for doc in docs:
        path=locate_extraction(doc,extraction_dirs)
        ext=json.loads(path.read_text(encoding='utf-8-sig'))
        if ext.get('metadata',{}).get('file') and ext['metadata']['file'] != Path(doc.file_path).name:
            p.error(f'Extraction file mismatch: {path} vs {doc.file_path}')
        cached_doc_id = ext.get('metadata', {}).get('doc_id')
        if cached_doc_id and cached_doc_id != doc.doc_id:
            p.error(f'Cached extraction is STALE for {doc.file_path}: {cached_doc_id} != {doc.doc_id}; re-extract the changed MD')
        extractions.append(ext)
        sources[Path(doc.file_path).name]=str(path)
    graph=build_graph_from_extractions(docs,extractions,aliases=load_aliases(),
        ontology=load_data_type_ontology(args.ontology),
        ontology_aliases=load_ontology_aliases(args.ontology_aliases),
        file_formats=load_file_format_ontology())
    if args.base:
        original=json.loads(args.base.read_text(encoding='utf-8-sig'))
        already=set(original.get('metadata',{}).get('documents',{}))
        collisions=already & {Path(x.file_path).name for x in docs}
        if collisions:
            p.error(f'Baseline already contains incoming documents {sorted(collisions)}. Use a clean pre-import baseline or rebuild all documents from cached extractions.')
        graph=merge_graphs(original,graph)
    # Reconcile legacy canonical labels/descriptions with the current ontology;
    # preserve document-specific provenance claims and existing edges.
    meta_updates=synchronize_curated_ontology(graph, load_data_type_ontology(args.ontology))
    print('Ontology metadata updated:',meta_updates)
    audit=inspect_graph(graph)
    print('Docs:',len(docs),'Nodes:',len(graph['nodes']),'Edges:',len(graph['edges']),
          'Curated ports:',audit['curated_ports'],'Pending:',audit['pending_ports'])
    if args.strict_ports and not audit['publish_ready']:
        p.error(f"Cannot write strict graph: {audit['pending_ports']} pending ports, {len(audit['errors'])} structural errors")
    write_json_atomic(args.output,graph)
    write_json_atomic(args.output.with_name(args.output.stem+'_port_audit.json'),audit)
    write_json_atomic(args.output.with_name(args.output.stem+'_extraction_sources.json'),sources)
    print('Saved staging graph:',args.output)
    print('Neo4j has NOT been modified')
if __name__=='__main__': main()
