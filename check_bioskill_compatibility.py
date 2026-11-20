#!/usr/bin/env python3
"""Conservative, subtype-aware potential Operation chains for a local BioSkillKG.

This does not claim executability: parameters, file existence, reference builds,
sorting, sample pairing and application constraints need separate checks.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from bio_skill_kg.semantic_normalization import canonical_format


def _ports(props: dict, direction: str) -> list[dict]:
    raw = props.get(direction + '_specs_json') or '[]'
    try:
        entries = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    return [x for x in entries if isinstance(x, dict) and x.get('resolution_status') != 'pending_review' and x.get('data_type_id')] if isinstance(entries, list) else []


def potential_connections(graph: dict, from_op: str, to_op: str) -> list[dict]:
    nodes = {n.get('id'): n for n in graph.get('nodes', [])}
    if from_op not in nodes or to_op not in nodes:
        raise ValueError('Operation not found; check the exact op:* IDs')
    if nodes[from_op]['label'] != 'Operation' or nodes[to_op]['label'] != 'Operation':
        raise ValueError('Both IDs must be Operation nodes')
    edges = graph.get('edges', [])
    children: dict[str, set[str]] = {}
    formal = {(x['source'], x['type'], x['target']) for x in edges}
    for rel in edges:
        if rel.get('type') == 'IS_SUBTYPE_OF':
            children.setdefault(rel['source'], set()).add(rel['target'])

    def ancestors(node_id: str) -> set[str]:
        known, queue = {node_id}, [node_id]
        while queue:
            nxt = queue.pop()
            for parent in children.get(nxt, ()):  # Traverse source child → parent
                if parent not in known:
                    known.add(parent)
                    queue.append(parent)
        return known

    outputs = _ports(nodes[from_op]['properties'], 'output')
    inputs = _ports(nodes[to_op]['properties'], 'input')

    def read_role(item: dict) -> str | None:
        role = str(item.get('role') or '').lower().replace('-', '_')
        if re.search(r'(?:read|mate|r)_?1$', role):
            return 'read1'
        if re.search(r'(?:read|mate|r)_?2$', role):
            return 'read2'
        return None

    def context_mode(items: list[dict], scenario: str | None) -> str | None:
        roles = {read_role(x) for x in items if x.get('scenario_id') == scenario}
        roles.discard(None)
        if 'read2' in roles:
            return 'paired'
        if 'read1' in roles:
            return 'single'
        return None

    result = []
    for outgoing in outputs:
        out_id = outgoing['data_type_id']
        if (from_op, 'PRODUCES', out_id) not in formal:
            continue
        for incoming in inputs:
            in_id = incoming['data_type_id']
            if (to_op, 'REQUIRES_INPUT', in_id) not in formal or in_id not in ancestors(out_id):
                continue
            # A read1 producer cannot satisfy read2. Do not mix a single-end
            # execution with a paired-end consumer scenario or vice versa.
            out_role, in_role = read_role(outgoing), read_role(incoming)
            if out_role and in_role and out_role != in_role:
                continue
            from_mode = context_mode(outputs, outgoing.get('scenario_id'))
            to_mode = context_mode(inputs, incoming.get('scenario_id'))
            if from_mode and to_mode and from_mode != to_mode:
                continue
            produced = {canonical_format(x) for x in outgoing.get('formats', []) or []}
            accepted = {canonical_format(x) for x in incoming.get('formats', []) or []}
            if produced and accepted and not produced.intersection(accepted):
                continue
            result.append({
                'producer_operation': from_op,
                'consumer_operation': to_op,
                'produced_data_type': out_id,
                'required_data_type': in_id,
                'type_match': 'exact' if out_id == in_id else 'subtype',
                'producer_scenario': outgoing.get('scenario_id'),
                'consumer_scenario': incoming.get('scenario_id'),
                'producer_role': outgoing.get('role'),
                'consumer_role': incoming.get('role'),
                'common_formats': sorted(produced.intersection(accepted)),
                'format_verification': 'overlap' if produced and accepted else 'insufficient_evidence',
                'ready_to_execute': False,
            })
    return result


def main():
    p = argparse.ArgumentParser(description='List subtype-aware potential tool-chain links; never executes commands')
    p.add_argument('--graph', required=True, type=Path)
    p.add_argument('--from-op', required=True)
    p.add_argument('--to-op', required=True)
    args = p.parse_args()
    graph = json.loads(args.graph.read_text(encoding='utf-8-sig'))
    result = potential_connections(graph, args.from_op, args.to_op)
    print(json.dumps({'potential_links':len(result), 'links':result},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
