#!/usr/bin/env python3
"""Promote a reviewed semantic concept to reusable DataType registry.

No LLM inference, no automatic approvals, no Neo4j writes. Run on a COPY of
ontology first; inspect diff before replacing production registry.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description='Register an approved DataType once for all future MDs')
    p.add_argument('--ontology',type=Path,default=Path('bio_skill_kg/data_types.json'))
    p.add_argument('--output',type=Path,required=True,help='New output registry path, not the input file')
    p.add_argument('--key',required=True,help='Unique canonical ID suffix, e.g. duplicate_marked_bam')
    p.add_argument('--name',required=True,help='Reviewed canonical name')
    p.add_argument('--description',required=True,help='Reviewed semantic meaning and constraints')
    p.add_argument('--formats',nargs='+',required=True,help='One or more formats (BAM, TXT, ...)')
    p.add_argument('--parent',default=None,help='An existing parent type key; optional')
    p.add_argument('--alias',action='append',default=[],help='Explicit confirmed synonym, repeatable')
    args=p.parse_args()
    if args.output.resolve()==args.ontology.resolve():
        p.error('Output must be a NEW file; inspect diff before replacing ontology')
    if not re.fullmatch(r'[a-z][a-z0-9_]*',args.key):
        p.error('--key must match [a-z][a-z0-9_]*')
    registry=json.loads(args.ontology.read_text(encoding='utf-8'))
    if args.key in registry:
        p.error('Existing key; use a different key or manually review the current record')
    if args.parent and args.parent not in registry:
        p.error(f'Unknown parent {args.parent}')
    known_names={s.casefold() for v in registry.values() for s in [v.get('name',''),*(v.get('aliases',[]) or [])]}
    if args.name.casefold() in known_names or any(x.casefold() in known_names for x in args.alias):
        p.error('Duplicate name/alias already in registry; use the existing type instead')
    if args.parent:
        allowed=set(registry[args.parent].get('formats',[]))
        if allowed and not set(args.formats)<=allowed:
            p.error(f'New formats {args.formats} are incompatible with parent allowed formats {sorted(allowed)}')
    row={'name':args.name,'description':args.description,'formats':sorted(set(args.formats)), 'aliases':sorted(set([args.name]+args.alias))}
    if args.parent:row['parent']=args.parent
    registry[args.key]=row
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Registered data:{args.key} in {args.output}. Not installed and no graph modified.')
if __name__=='__main__': main()
