"""Read-only BioSkillKG-v2 graph adapter (JSON or Neo4j namespace snapshot)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


def json_value(value, default=None):
    if value is None: return [] if default is None else default
    if isinstance(value, (list, dict)): return value
    if isinstance(value, str):
        try: return json.loads(value)
        except (ValueError, TypeError): pass
    return [] if default is None else default


def distinct(values):
    return list(dict.fromkeys(v for v in values if v is not None))


@dataclass(frozen=True)
class Edge:
    source: str
    relation: str
    target: str
    properties: dict


class Graph:
    def __init__(self, raw: dict):
        if raw.get('schema') != 'BioSkillKG-v2':
            raise ValueError('Expected BioSkillKG-v2 graph')
        nodes = raw.get('nodes', [])
        self.nodes = {}
        for n in nodes:
            node_id = n['id']
            if node_id in self.nodes: raise ValueError('Duplicate node ID: '+node_id)
            self.nodes[node_id] = n
        self.edges = []
        self.out = defaultdict(list)
        self.ins = defaultdict(list)
        for e in raw.get('edges', []):
            if e['source'] not in self.nodes or e['target'] not in self.nodes:
                raise ValueError('Unresolved edge '+str(e))
            edge = Edge(e['source'], e['type'], e['target'], e.get('properties') or {})
            self.edges.append(edge)
            self.out[edge.source].append(edge)
            self.ins[edge.target].append(edge)
        self.raw = raw
        packed = json.dumps({'nodes': sorted(nodes,key=lambda x:x['id']),
                             'edges': sorted(raw.get('edges',[]),key=lambda x:(x['source'],x['type'],x['target']))},
                            ensure_ascii=False,sort_keys=True,separators=(',',':'))
        self.digest = hashlib.sha256(packed.encode('utf-8')).hexdigest()
        self.operations = {i:n for i,n in self.nodes.items() if n['label']=='Operation'}
        self.datatypes = {i:n for i,n in self.nodes.items() if n['label']=='DataType'}
        self.tools = {i:n for i,n in self.nodes.items() if n['label']=='Tool'}
        self.op_tool = {}
        self.tool_ops = defaultdict(list)
        self.op_tasks = defaultdict(list)
        for e in self.edges:
            if e.relation == 'HAS_OPERATION':
                self.op_tool[e.target] = e.source
                self.tool_ops[e.source].append(e.target)
            if e.relation == 'PERFORMS': self.op_tasks[e.source].append(e.target)
        self._ancestors = {}

    @classmethod
    def from_json(cls,path):
        return cls(json.loads(Path(path).read_text(encoding='utf-8-sig')))

    @classmethod
    def from_neo4j(cls, namespace='BioSkillV56PicardFreshTest',database=None):
        """Fetch a read-only snapshot from one namespace. Labels are validated."""
        if not re.fullmatch(r'BioSkill[A-Za-z0-9_]+',namespace):
            raise ValueError('Unsafe Neo4j namespace')
        try: from neo4j import GraphDatabase
        except ImportError as exc: raise RuntimeError('pip install neo4j to read Neo4j') from exc
        uri=os.getenv('NEO4J_URI','bolt://localhost:7687')
        user=os.getenv('NEO4J_USER','neo4j')
        password=os.getenv('NEO4J_PASSWORD')
        if not password: raise RuntimeError('Set NEO4J_PASSWORD in your environment; no interactive secret prompts')
        with GraphDatabase.driver(uri,auth=(user,password)) as driver:
            driver.verify_connectivity()
            with driver.session(database=database or os.getenv('NEO4J_DATABASE','neo4j')) as session:
                nodes=[]
                for r in session.run(f'MATCH (n:{namespace}) RETURN n.id AS id, labels(n) AS labels, properties(n) AS props'):
                    label=next((l for l in r['labels'] if l in {'Tool','Operation','Task','DataType','FileFormat'}),None)
                    if label: nodes.append({'id':r['id'],'label':label,'properties':{k:v for k,v in r['props'].items() if k!='id'}})
                edges=[]
                for r in session.run(f'MATCH (a:{namespace})-[rel]->(b:{namespace}) RETURN a.id AS source,type(rel) AS relation,b.id AS target,properties(rel) AS props'):
                    edges.append({'source':r['source'],'type':r['relation'],'target':r['target'],'properties':r['props']})
        return cls({'schema':'BioSkillKG-v2','nodes':nodes,'edges':edges,'metadata':{'namespace':namespace}})

    def get(self,node_id): return self.nodes.get(node_id,{}).get('properties',{})

    def from_node(self,node_id,relation=None):
        return [e for e in self.out[node_id] if relation is None or e.relation==relation]

    def to_node(self,node_id,relation=None):
        return [e for e in self.ins[node_id] if relation is None or e.relation==relation]

    def ancestors(self, datatype_id, depth=12):
        if datatype_id in self._ancestors: return self._ancestors[datatype_id]
        seen={datatype_id}; frontier=[datatype_id]
        for _ in range(depth):
            nxt=[]
            for d in frontier:
                for e in self.from_node(d,'IS_SUBTYPE_OF'):
                    if e.target not in seen: seen.add(e.target);nxt.append(e.target)
            if not nxt:break
            frontier=nxt
        self._ancestors[datatype_id]=seen
        return seen

    def compatible(self,produced_type,needed_type, produced_formats=(), needed_formats=()):
        if not produced_type or not needed_type or needed_type not in self.ancestors(produced_type):return False
        left={x.upper() for x in produced_formats if x}
        right={x.upper() for x in needed_formats if x}
        return not left or not right or bool(left & right)

    def operation_ports(self,op_id,direction):
        if direction not in ('input','output'):raise ValueError('input or output')
        ports=json_value(self.get(op_id).get(direction+'_specs_json'),[])
        relation='REQUIRES_INPUT' if direction=='input' else 'PRODUCES'
        edges={e.target for e in self.from_node(op_id,relation)}
        result=[]
        for original in ports:
            port=dict(original)
            # Older builders stored only canonical IDs and formal edges, not
            # resolution_status. Infer ONLY when that formal edge is present.
            if not port.get('resolution_status'):
                if port.get('data_type_id') in edges and port.get('data_type_id') in self.datatypes:
                    port['resolution_status']='curated'
                elif port.get('candidate_type_id'):
                    port['resolution_status']='pending_review'
                else:
                    port['resolution_status']='unknown'
            result.append(port)
        return result

    def input_edges(self,op_id):return self.from_node(op_id,'REQUIRES_INPUT')
    def output_edges(self,op_id):return self.from_node(op_id,'PRODUCES')

    def available_tool_info(self,op_id):
        tool_id=self.op_tool.get(op_id)
        return (tool_id,self.get(tool_id)) if tool_id else (None,{})

    def produce_ports(self,op_id, include_pending=False):
        result=[]
        for port in self.operation_ports(op_id,'output'):
            status=port.get('resolution_status')
            if not include_pending and status!='curated':continue
            result.append(port)
        return result

    def input_scenarios(self,op_id):
        """An operation may describe alternative scenarios; do not AND all variants."""
        ports=self.operation_ports(op_id,'input')
        groups=defaultdict(list)
        for p in ports:
            groups[str(p.get('scenario_id') or '_default')].append(p)
        return list(groups.values()) if groups else [[]]

    def has_type_link(self,source_op,target_op, include_pending=False):
        """Return distinct output/input matches; pending links are candidates, not facts."""
        matches=[];seen=set()
        for made in self.produce_ports(source_op,include_pending=include_pending):
            for need in self.operation_ports(target_op,'input'):
                st1=made.get('resolution_status');st2=need.get('resolution_status')
                if st1==st2=='curated':
                    if not self.compatible(made.get('data_type_id'),need.get('data_type_id'),made.get('formats',[]),need.get('formats',[])):
                        continue
                    status='curated'
                elif include_pending and st1==st2=='pending_review' and made.get('candidate_type_id') and made.get('candidate_type_id')==need.get('candidate_type_id'):
                    l=set(made.get('formats',[]));r=set(need.get('formats',[]))
                    if l and r and not (l&r): continue
                    status='pending_review'
                else:continue
                ident=(made.get('port_id'),need.get('port_id'),status)
                if ident in seen:continue
                seen.add(ident)
                matches.append({'from':source_op,'to':target_op,'status':status,
                                'produced_type':made.get('data_type_id') or made.get('candidate_type_id'),
                                'needed_type':need.get('data_type_id') or need.get('candidate_type_id'),
                                'output_port':made,'input_port':need})
        return matches
