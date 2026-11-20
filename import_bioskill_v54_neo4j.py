#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Import a fresh BioSkillKG graph into a completely separate Neo4j label namespace.

Does not MATCH, MERGE, UPDATE or DELETE any :BioSkillEntity nodes of older graph.
In Neo4j Community this provides two separate graph namespaces in a single DB.
"""
from __future__ import annotations

import argparse
import collections
import getpass
import json
import os
import re
from pathlib import Path
from check_bioskill_ports import inspect_graph

LABELS={'Tool','Operation','Task','DataType','FileFormat'}
RELATIONS={
 'HAS_OPERATION','PERFORMS','REQUIRES_INPUT','PRODUCES','HAS_FORMAT',
 'IS_SUBTYPE_OF','RECOMMENDED_BEFORE','DOCUMENTED_DOWNSTREAM',
 'DOCUMENTED_PREREQUISITE','PARTIALLY_ALTERNATIVE_TO'
}


def validate_graph(path):
    graph=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if graph.get('schema')!='BioSkillKG-v2':raise ValueError('Unsupported graph schema')
    nodes=graph.get('nodes',[]);edges=graph.get('edges',[])
    ids=[n['id'] for n in nodes]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate nodes')
    if any(n['label'] not in LABELS for n in nodes):raise ValueError('Unknown node label')
    if any(e['type'] not in RELATIONS or e['source'] not in ids or e['target'] not in ids for e in edges):
        raise ValueError('Bad edge type/reference')
    if len({(e['source'],e['type'],e['target']) for e in edges})!=len(edges):
        raise ValueError('Duplicate edges')
    return graph


def chunks(items,n):
    for i in range(0,len(items),n):yield items[i:i+n]


def main():
    p=argparse.ArgumentParser(description='v5.4 independent Neo4j namespace importer')
    p.add_argument('--graph',type=Path,default=Path('data/bio_skill_kg/v54_clean/bio_skill_graph.json'))
    p.add_argument('--database',default=os.getenv('NEO4J_DATABASE','neo4j'))
    p.add_argument('--namespace',default='BioSkillV54')
    p.add_argument('--batch-size',type=int,default=200)
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--allow-pending-ports',action='store_true',help='Only for isolated test namespaces; do not use for production')
    args=p.parse_args()
    if not re.fullmatch(r'BioSkill[A-Za-z0-9_]+',args.namespace):
        p.error('--namespace must be a BioSkill-prefixed safe Cypher label, such as BioSkillV54')
    if args.batch_size<1:p.error('batch-size must be > 0')
    if args.allow_pending_ports and not args.namespace.lower().endswith('test'):
        p.error('--allow-pending-ports is only permitted for a namespace ending with Test')
    graph=validate_graph(args.graph)
    port_audit=inspect_graph(graph)
    if not port_audit['publish_ready'] and not args.allow_pending_ports:
        p.error(f"Refusing incomplete import: {port_audit['pending_ports']} pending ports, {len(port_audit['errors'])} errors. Run check_bioskill_ports.py; use --allow-pending-ports ONLY for a test namespace.")
    counts_nodes=collections.Counter(x['label'] for x in graph['nodes'])
    counts_edges=collections.Counter(x['type'] for x in graph['edges'])
    print('Validated:',len(graph['nodes']),'nodes,',len(graph['edges']),'edges', 'namespace:',args.namespace)
    print('Nodes:',dict(counts_nodes),'Edges:',dict(counts_edges))
    if args.dry_run:
        print('DRY RUN: no Neo4j connection, no writes')
        return
    try:
        from neo4j import GraphDatabase
    except ImportError as e:
        raise SystemExit('Please install: pip install neo4j') from e
    uri=os.getenv('NEO4J_URI','bolt://localhost:7687')
    user=os.getenv('NEO4J_USER','neo4j')
    password=os.getenv('NEO4J_PASSWORD') or getpass.getpass('Neo4j password: ')
    with GraphDatabase.driver(uri,auth=(user,password)) as driver:
        driver.verify_connectivity()
        with driver.session(database=args.database) as session:
            # The constraint and all MERGEs are ONLY against the new namespace.
            cname='bioskill_v54_id' if args.namespace=='BioSkillV54' else 'bioskill_'+args.namespace.lower()+'_id'
            session.run(f'CREATE CONSTRAINT {cname} IF NOT EXISTS FOR (n:{args.namespace}) REQUIRE n.id IS UNIQUE').consume()
            for label in sorted(LABELS):
                rows=[{'id':n['id'],'props':{**n.get('properties',{}),'id':n['id']}}
                      for n in graph['nodes'] if n['label']==label]
                if not rows:continue
                q=f'UNWIND $rows AS row MERGE (n:{args.namespace} {{id:row.id}}) SET n = row.props SET n:{label}'
                for batch in chunks(rows,args.batch_size):session.run(q,rows=batch).consume()
                print('Upserted',label,len(rows))
            for relation in sorted(RELATIONS):
                rows=[{'source':e['source'],'target':e['target'],
                       'props':e.get('properties',{})} for e in graph['edges'] if e['type']==relation]
                if not rows:continue
                q=(f'UNWIND $rows AS row MATCH (a:{args.namespace} {{id:row.source}}) '
                   f'MATCH (b:{args.namespace} {{id:row.target}}) '
                   f'MERGE (a)-[r:{relation}]->(b) SET r = row.props')
                for batch in chunks(rows,args.batch_size):session.run(q,rows=batch).consume()
                print('Upserted',relation,len(rows))
            actual_nodes=session.run(f'MATCH (n:{args.namespace}) RETURN count(n) AS n').single()['n']
            actual_edges=session.run(f'MATCH (a:{args.namespace})-[r]->(b:{args.namespace}) RETURN count(r) AS n').single()['n']
            print('Done:',actual_nodes,'nodes,',actual_edges,'edges')
            if actual_nodes<len(graph['nodes']) or actual_edges<len(graph['edges']):
                raise RuntimeError('Imported counts smaller than input. Check destination database!')
            if actual_nodes>len(graph['nodes']) or actual_edges>len(graph['edges']):
                print('WARNING: namespace has extra old data. Use a unique --namespace for a fully clean import.')

if __name__=='__main__':main()
