#!/usr/bin/env python3
"""Check BioSkillKG ports before publishing to Neo4j. No network or writes to graph.

Pending ports are *retained* in input/output_specs_json but intentionally have no
production REQUIRES_INPUT/PRODUCES edge. Their existence blocks strict publish.
"""
from __future__ import annotations
import argparse
import collections
import json
from pathlib import Path
from bio_skill_kg.semantic_normalization import semantic_facets


def inspect_graph(graph: dict) -> dict:
    ids = {n['id'] for n in graph.get('nodes', [])}
    relations = {(x['source'], x['type'], x['target']) for x in graph.get('edges', [])}
    candidate_groups = collections.defaultdict(lambda: {'count': 0, 'operations': set(), 'names': set(), 'formats': set(), 'suggested_parents': set()})
    issues, counts = [], collections.Counter()
    for n in graph.get('nodes', []):
        if n.get('label') != 'Operation':
            continue
        op = n['id']
        props = n.get('properties', {})
        for side, relation in [('input', 'REQUIRES_INPUT'), ('output', 'PRODUCES')]:
            raw = props.get(f'{side}_specs_json') or '[]'
            try:
                ports = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(ports, list):
                    raise ValueError('not a list')
            except (ValueError, TypeError) as e:
                issues.append({'severity': 'ERROR', 'operation': op, 'direction': side, 'reason': f'INVALID_JSON: {e}'})
                continue
            def legacy_signature(item):
                return (str(item.get('raw_data_type') or item.get('data_type') or ''),
                        str(item.get('scenario_id') or ''),str(item.get('role') or ''),
                        str(item.get('evidence_quote') or ''))
            seen_signatures = {legacy_signature(x) for x in ports if isinstance(x, dict)}
            # v5.4 stored unknown ports ONLY in unresolved_*_specs_json;
            # do not mistakenly approve that legacy partial graph.
            legacy_raw = props.get(f'unresolved_{side}_specs_json') or '[]'
            try:
                legacy = json.loads(legacy_raw) if isinstance(legacy_raw, str) else legacy_raw
                if not isinstance(legacy, list):raise ValueError('not a list')
            except (ValueError, TypeError) as exc:
                issues.append({'severity':'ERROR','operation':op,'direction':side,'reason':f'INVALID_LEGACY_JSON: {exc}'})
                legacy = []
            for record in legacy:
                if not isinstance(record, dict) or legacy_signature(record) in seen_signatures:
                    continue
                counts['total_ports'] += 1
                counts['pending_ports'] += 1
                issues.append({'severity':'ERROR','operation':op,'direction':side,
                               'reason':'LEGACY_PENDING_PORT_MISSING_FROM_MAIN_SPECS',
                               'raw_data_type':record.get('raw_data_type') or record.get('data_type')})
            for port in ports:
                counts['total_ports'] += 1
                if not isinstance(port, dict):
                    issues.append({'severity': 'ERROR', 'operation': op, 'direction': side, 'reason': 'PORT_NOT_OBJECT'})
                    continue
                data_id = port.get('data_type_id')
                pending = port.get('resolution_status') == 'pending_review' or not data_id
                if pending:
                    counts['pending_ports'] += 1
                    cid = port.get('candidate_type_id') or 'unknown_candidate'
                    grp = candidate_groups[cid]
                    grp['count'] += 1
                    grp['operations'].add(op)
                    grp['names'].add(str(port.get('raw_data_type') or port.get('data_type') or ''))
                    grp['formats'].update(str(x) for x in port.get('formats', []) or [])
                    if port.get('suggested_parent_type_key'):
                        grp['suggested_parents'].add(port['suggested_parent_type_key'])
                    if data_id:
                        issues.append({'severity': 'ERROR', 'operation': op, 'direction': side, 'reason': 'PENDING_HAS_CANONICAL_ID', 'candidate': cid})
                else:
                    counts['curated_ports'] += 1
                    facets = port.get('semantic_facets') or semantic_facets(
                        port.get('raw_data_type') or port.get('data_type') or '',
                        port.get('description') or '', port.get('formats') or [])
                    if data_id == 'data:aligned_reads_bam' and (
                        facets.get('sorting_state') or facets.get('processing_states')):
                        issues.append({'severity':'ERROR','operation':op,'direction':side,
                                       'reason':'SEMANTIC_STATE_DOWNGRADED_TO_GENERIC_BAM',
                                       'state':facets})
                    if data_id not in ids or (op, relation, data_id) not in relations:
                        issues.append({'severity': 'ERROR', 'operation': op, 'direction': side, 'reason': 'MISSING_FORMAL_TYPE_OR_EDGE', 'data_type_id': data_id})
    candidates = [{"candidate_type_id": k, "count": v['count'],
                   "names": sorted(v['names']), "formats": sorted(v['formats']),
                   "operations": sorted(v['operations']),
                   "suggested_parent_type_keys": sorted(v['suggested_parents'])}
                  for k,v in sorted(candidate_groups.items())]
    return {'total_ports': counts['total_ports'], 'curated_ports': counts['curated_ports'],
            'pending_ports': counts['pending_ports'], 'errors': issues,
            'candidates': candidates, 'publish_ready': counts['pending_ports'] == 0 and not issues}


def main():
    p=argparse.ArgumentParser(description='Audit all Operation I/O ports, block incomplete publish')
    p.add_argument('--graph',required=True, type=Path)
    p.add_argument('--report',type=Path,default=None)
    p.add_argument('--strict',action='store_true',help='Return exit code 2 if unresolved or malformed ports')
    a=p.parse_args()
    report=inspect_graph(json.loads(a.graph.read_text(encoding='utf-8-sig')))
    print(json.dumps({k:v for k,v in report.items() if k!='candidates'},ensure_ascii=False,indent=2))
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Report:',a.report)
    if a.strict and not report['publish_ready']:
        raise SystemExit(2)
if __name__=='__main__':
    main()
