#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Audit a BioSkillKG JSON against cached per-document LLM extractions.

No LLM calls, no Neo4j writes, no changes to the graph.

Usage (Windows):
  python audit_bioskill_io.py --graph data\bio_skill_kg\bio_skill_graph.json --extractions data\bio_skill_kg\extracted_skills --out data\bio_skill_kg\io_audit.csv
"""
import argparse
import collections
import csv
import json
import pathlib
import sys


def load_json(p):
    with open(p, encoding='utf-8-sig') as f:
        return json.load(f)


def parse_specs(raw):
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def op_key(name):
    return ' '.join(str(name or '').lower().split())


def compact(items, field='data_type'):
    return ' | '.join(sorted({str(x.get(field, '')).strip() for x in items if isinstance(x, dict) and x.get(field)}))


def read_extractions(folder):
    results = {}
    for p in sorted(folder.glob('*.json')):
        try:
            data = load_json(p)
        except Exception as exc:
            print(f'[WARN] Could not load extraction {p}: {exc}', file=sys.stderr)
            continue
        for op in data.get('operations', []):
            key = op_key(op.get('name'))
            if not key:
                continue
            # Deduplicate by operation name; prefer the latest modified cached file.
            if key not in results or p.stat().st_mtime > results[key]['path'].stat().st_mtime:
                results[key] = {'operation': op, 'path': p}
    return results


def main():
    parser = argparse.ArgumentParser(description='Compare BioSkillKG extracted I/O with final graph edges and ports')
    parser.add_argument('--graph', required=True, type=pathlib.Path)
    parser.add_argument('--extractions', required=True, type=pathlib.Path)
    parser.add_argument('--out', default='io_audit.csv', type=pathlib.Path)
    args = parser.parse_args()

    if not args.graph.is_file():
        parser.error(f'Graph not found: {args.graph}')
    if not args.extractions.is_dir():
        parser.error(f'Extraction directory not found: {args.extractions}')

    graph = load_json(args.graph)
    nodes = {node['id']: node for node in graph.get('nodes', [])}
    operations = {op_key(node.get('properties', {}).get('name')): node
                  for node in graph.get('nodes', []) if node.get('label') == 'Operation'}
    edges_by_source = collections.defaultdict(list)
    for e in graph.get('edges', []):
        edges_by_source[e.get('source')].append(e)
    extractions = read_extractions(args.extractions)
    known_documents = set((graph.get('metadata') or {}).get('documents', {}))
    reviews_by_file = collections.Counter(
        item.get('file') or '(unknown)' for item in graph.get('review', []) if isinstance(item, dict)
    )

    rows = []
    keys = sorted(set(operations) | set(extractions))
    for key in keys:
        item = extractions.get(key)
        raw = item['operation'] if item else {}
        node = operations.get(key)
        props = node.get('properties', {}) if node else {}
        raw_inputs = raw.get('inputs', []) or []
        raw_outputs = raw.get('outputs', []) or []
        in_specs = parse_specs(props.get('input_specs_json'))
        out_specs = parse_specs(props.get('output_specs_json'))
        outgoing = edges_by_source.get(node['id'], []) if node else []
        in_edges = [e for e in outgoing if e.get('type') == 'REQUIRES_INPUT']
        out_edges = [e for e in outgoing if e.get('type') == 'PRODUCES']
        def port_signature(port):
            return (str(port.get('scenario_id') or ''), str(port.get('role') or ''))

        def missing_ports(extracted_ports, graph_ports):
            remaining = collections.Counter(port_signature(port) for port in graph_ports)
            missing = []
            for port in extracted_ports:
                sig = port_signature(port)
                if remaining[sig]:
                    remaining[sig] -= 1
                else:
                    missing.append(port)
            return missing

        missing_inputs = missing_ports(raw_inputs, in_specs)
        missing_outputs = missing_ports(raw_outputs, out_specs)
        source_file = (raw.get('_source_file') or props.get('source_file') or
                       (str(item['path'].name).split('_skill_')[0] + '_skill.md' if item else ''))
        issues = []
        if not item:
            issues.append('MISSING_EXTRACTION_FOR_AUDIT')
        if not node:
            issues.append('OPERATION_NOT_IN_GRAPH')
        pending_in = sum(x.get('resolution_status') == 'pending_review' for x in in_specs)
        pending_out = sum(x.get('resolution_status') == 'pending_review' for x in out_specs)
        if pending_in:
            issues.append('PENDING_INPUT_TYPE_REVIEW')
        if pending_out:
            issues.append('PENDING_OUTPUT_TYPE_REVIEW')
        if raw_inputs and not in_edges and not pending_in:
            issues.append('CRITICAL_INPUT_EDGES_MISSING')
        if raw_outputs and not out_edges and not pending_out:
            issues.append('CRITICAL_OUTPUT_EDGES_MISSING')
        if raw_inputs and not in_specs:
            issues.append('INPUT_PORT_DETAILS_MISSING')
        if raw_outputs and not out_specs:
            issues.append('OUTPUT_PORT_DETAILS_MISSING')
        if missing_inputs:
            issues.append('MISSING_INPUT_PORT_MAPPING')
        if missing_outputs:
            issues.append('MISSING_OUTPUT_PORT_MAPPING')
        # These are review hints, not proof of missing data: edges may be merged
        # because two scenario ports share the same canonical DataType.
        if len(raw_inputs) > len(in_specs) and in_specs:
            issues.append('REVIEW_INPUT_PORT_COUNT')
        if len(raw_outputs) > len(out_specs) and out_specs:
            issues.append('REVIEW_OUTPUT_PORT_COUNT')
        if not raw_outputs and not out_edges:
            issues.append('VERIFY_NO_OUTPUT_IN_SOURCE')
        if known_documents and source_file and source_file not in known_documents:
            issues.append('SOURCE_FILE_NOT_IN_GRAPH_METADATA')

        severity = ('CRITICAL' if any(i.startswith('CRITICAL') or i.startswith('MISSING_') or i == 'OPERATION_NOT_IN_GRAPH' for i in issues)
                    else 'REVIEW' if issues else 'OK')
        rows.append({
            'severity': severity,
            'operation': props.get('name') or raw.get('name') or key,
            'source_md': source_file,
            'extraction_found': 'YES' if item else 'NO',
            'raw_inputs_count': len(raw_inputs),
            'raw_outputs_count': len(raw_outputs),
            'raw_input_names': compact(raw_inputs),
            'raw_output_names': compact(raw_outputs),
            'missing_input_ports': ' | '.join((str(p.get('scenario_id') or 'default') + ':' + str(p.get('role') or 'unknown') + ' (' + str(p.get('data_type') or '') + ')') for p in missing_inputs),
            'missing_output_ports': ' | '.join((str(p.get('scenario_id') or 'default') + ':' + str(p.get('role') or 'unknown') + ' (' + str(p.get('data_type') or '') + ')') for p in missing_outputs),
            'graph_input_specs_count': len(in_specs),
            'graph_output_specs_count': len(out_specs),
            'graph_input_edges_count': len(in_edges),
            'graph_output_edges_count': len(out_edges),
            'graph_input_datatypes': ' | '.join(sorted({nodes[e['target']]['properties'].get('name', e['target'])
                                  for e in in_edges if e.get('target') in nodes})),
            'graph_output_datatypes': ' | '.join(sorted({nodes[e['target']]['properties'].get('name', e['target'])
                                   for e in out_edges if e.get('target') in nodes})),
            'issues': ' | '.join(issues) or 'OK',
            'extraction_json': str(item['path']) if item else '',
        })
    rows.sort(key=lambda r: ({'CRITICAL': 0, 'REVIEW': 1, 'OK': 2}[r['severity']], r['source_md'], r['operation']))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['severity', 'operation', 'issues'])
        writer.writeheader()
        writer.writerows(rows)

    count = collections.Counter(r['severity'] for r in rows)
    print(f'Graph: {args.graph} | operation nodes: {len(operations)} | extraction operations: {len(extractions)}')
    print(f'Audit: {count.get("CRITICAL",0)} CRITICAL, {count.get("REVIEW",0)} REVIEW, {count.get("OK",0)} OK')
    print('\nOperations requiring attention:')
    for r in rows:
        if r['severity'] != 'OK':
            print(f'  [{r["severity"]}] {r["operation"]} ({r["source_md"]}): {r["issues"]}')
    print('\nReview entries by MD:')
    for src, n in sorted(reviews_by_file.items()):
        print(f'  {src}: {n}')
    print(f'\nCSV report: {args.out.resolve()}')
    print('\nNOTE: An edge with the right count can still have the WRONG semantic DataType; '
          'review raw_*_names alongside graph_*_datatypes. Similar formats alone do not prove compatibility.')


if __name__ == '__main__':
    main()
