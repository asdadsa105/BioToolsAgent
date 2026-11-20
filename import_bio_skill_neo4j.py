"""Neo4j import of incremental BioSkillKG JSON, without touching SciToolKG.

Default behavior is idempotent MERGE and full property replacement for each
included BioSkillEntity node or relation. No implicit delete operation.
"""
from __future__ import annotations
import argparse
import json
import os
from collections import defaultdict
from getpass import getpass
from pathlib import Path
from bio_skill_kg.builder import LABELS, RELATIONS, summary


def load_graph(path: str | Path) -> dict:
    graph=json.loads(Path(path).read_text(encoding='utf-8'))
    if graph.get('schema') not in {'BioSkillKG-v1','BioSkillKG-v2'}:
        raise ValueError('Not a BioSkillKG graph (requires v1/v2 schema)')
    ids=set()
    for n in graph['nodes']:
        if n['label'] not in LABELS or not isinstance(n['id'],str):
            raise ValueError(f'Invalid node: {n}')
        if n['id'] in ids:
            raise ValueError(f'Duplicate ID {n["id"]}')
        ids.add(n['id'])
        for key,value in n.get('properties',{}).items():
            validate_neo4j_property(key,value)
    edges=set()
    for e in graph['edges']:
        triple=(e['source'],e['type'],e['target'])
        if e['type'] not in RELATIONS or e['source'] not in ids or e['target'] not in ids:
            raise ValueError(f'Invalid edge: {triple}')
        if triple in edges:
            raise ValueError(f'Duplicate edge: {triple}')
        edges.add(triple)
        for key,value in e.get('properties',{}).items():
            validate_neo4j_property(key,value)
    return graph


def validate_neo4j_property(key, value):
    if not isinstance(key,str) or not key:
        raise ValueError('Neo4j property keys must be nonempty strings')
    if value is None or isinstance(value, (str,int,float,bool)):
        return
    if isinstance(value,list) and all(isinstance(x,(str,int,float,bool)) for x in value):
        return
    raise ValueError(f'Unsupported Neo4j property type at {key}: {type(value).__name__}')


def make_node_batches(graph):
    groups=defaultdict(list)
    for n in graph['nodes']:
        # n = row.props removes stale placeholder flags from old imports.
        props={**n.get('properties',{}),'id':n['id']}
        if n['label']=='Tool':
            props['stub']=bool(props.get('stub',False))
        groups[n['label']].append({'id':n['id'],'props':props})
    return groups


def make_edge_batches(graph):
    groups=defaultdict(list)
    for e in graph['edges']:
        groups[e['type']].append({'source':e['source'],'target':e['target'],
                                  'props':dict(e.get('properties',{}))})
    return groups


def main():
    ap=argparse.ArgumentParser(description='Import BioSkillKG v1/v2 into Neo4j')
    ap.add_argument('--graph',default='data/bio_skill_kg/bio_skill_graph.json')
    ap.add_argument('--database',default=os.getenv('NEO4J_DATABASE','neo4j'))
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--batch-size',type=int,default=250)
    args=ap.parse_args()
    if args.batch_size<1:
        ap.error('--batch-size must be >= 1')
    graph=load_graph(args.graph)
    print('Validated graph:',json.dumps(summary(graph),ensure_ascii=False))
    if args.dry_run:
        print('DRY RUN: Neo4j not modified.')
        return
    try:
        from neo4j import GraphDatabase
    except ImportError as e:
        raise SystemExit('Missing Neo4j driver; run: python -m pip install neo4j') from e
    uri=os.getenv('NEO4J_URI','bolt://localhost:7687')
    user=os.getenv('NEO4J_USER','neo4j')
    password=os.getenv('NEO4J_PASSWORD') or getpass('Neo4j password: ')
    node_batches=make_node_batches(graph)
    edge_batches=make_edge_batches(graph)
    with GraphDatabase.driver(uri,auth=(user,password)) as driver:
        driver.verify_connectivity()
        with driver.session(database=args.database) as session:
            session.run('CREATE CONSTRAINT bioskill_id IF NOT EXISTS FOR (n:BioSkillEntity) REQUIRE n.id IS UNIQUE').consume()
            for label, rows in sorted(node_batches.items()):
                if label not in LABELS: raise ValueError(label)
                query=(f'UNWIND $rows AS row '
                       f'MERGE (n:BioSkillEntity {{id:row.id}}) '
                       f'SET n = row.props SET n:{label}')
                for i in range(0,len(rows),args.batch_size):
                    session.run(query,rows=rows[i:i+args.batch_size]).consume()
                print(f'Upserted {label}: {len(rows)}')
            for relation, rows in sorted(edge_batches.items()):
                if relation not in RELATIONS: raise ValueError(relation)
                query=(f'UNWIND $rows AS row '
                       f'MATCH (a:BioSkillEntity {{id:row.source}}) '
                       f'MATCH (b:BioSkillEntity {{id:row.target}}) '
                       f'MERGE (a)-[r:{relation}]->(b) SET r = row.props')
                for i in range(0,len(rows),args.batch_size):
                    session.run(query,rows=rows[i:i+args.batch_size]).consume()
                print(f'Upserted {relation}: {len(rows)}')
            node_count=session.run('MATCH (n:BioSkillEntity) RETURN count(n) AS n').single()['n']
            edge_count=session.run('MATCH (:BioSkillEntity)-[r]->(:BioSkillEntity) RETURN count(r) AS n').single()['n']
            print(f'Neo4j BioSkillKG totals: nodes={node_count}, edges={edge_count}')
    print('Done. Open Neo4j Browser and execute:')
    print("MATCH p=(a:BioSkillEntity:Tool {canonical_name:'bwa'})-[r]->(b:BioSkillEntity:Tool) RETURN p LIMIT 30;")


if __name__ == '__main__':
    main()
