"""Hybrid rank aggregation plus graph-neighbor expansion for Operation candidates."""
from __future__ import annotations
from collections import defaultdict
import re
from .graph import Graph
from .index import SemanticIndex, VectorEncoder, lexical_tokens


def retrieve_operations(graph:Graph,index:SemanticIndex,parsed,top_k=12, per_view_k=20,device='cpu'):
    encoder=VectorEncoder(index.backend,'BAAI/bge-m3' if index.backend=='bge-m3' else index.model,device,
                          dimensions=index.metadata['dimension'])
    if index.backend=='bge-m3':encoder.model=index.model
    texts=[parsed['original']]+parsed.get('subgoals',[])+parsed.get('target_descriptions',[])
    texts=list(dict.fromkeys(t for t in texts if t.strip()))
    scores=defaultdict(float);details=defaultdict(list)
    weights={'purpose':1.0,'scenario':.85,'io':.8,'datatype':.35,'tool':.3}
    for text in texts:
        rows=index.search(text,encoder,k=per_view_k*3,allowed_views={'purpose','scenario','io'})
        for rank,row in enumerate(rows):
            if row['id'] not in graph.operations:continue
            qtokens=set(lexical_tokens(text)); dtokens=set(lexical_tokens(row['text']))
            overlap=len(qtokens & dtokens)/max(1,len(qtokens))
            value=(.85*max(0.,row['score']) + .15*overlap)*weights[row['view']]
            # Max per subgoal avoids one long question swamping an essential subtask.
            scores[row['id']]=max(scores[row['id']],value)
            details[row['id']].append({'query':text,'view':row['view'],'similarity':row['score']})
    question=parsed['original'].casefold()
    for oid,n in graph.operations.items():
        op=n['properties'];tool_id,tool=graph.available_tool_info(oid)
        opname=str(op.get('name','')).casefold();toolname=str(tool.get('name','')).casefold()
        exact= bool(opname and opname in question) or bool(opname and ' '+opname+' ' in ' '+question+' ')
        if exact:
            scores[oid]=max(scores[oid],1.3)
            details[oid].append({'query':question,'view':'exact_operation_name','similarity':1.0})
        # Unqualified names such as 'sort' must not be matched within unrelated words.
        if toolname and toolname in question and opname and opname in question:
            scores[oid]=max(scores[oid],1.5)
    ranked=sorted(scores,key=lambda x:(-scores[x],x))[:top_k]
    return [{'operation_id':oid,'score':round(scores[oid],5),'matched':details[oid][:5]} for oid in ranked]


def expand_candidates(graph:Graph,candidate_ids,max_hops=1,max_operations=60):
    """Expand only using verified formal type links; include documentary tool hints separately."""
    chosen=set(candidate_ids);frontier=set(chosen)
    for _ in range(max_hops):
        expanded=set()
        for op_id in frontier:
            for other in graph.operations:
                if other==op_id or other in chosen:continue
                if graph.has_type_link(op_id,other) or graph.has_type_link(other,op_id):
                    expanded.add(other)
        for op in sorted(expanded):
            if len(chosen)>=max_operations:break
            chosen.add(op)
        frontier=expanded
        if not frontier or len(chosen)>=max_operations:break
    hints=[]
    by_tool={graph.op_tool.get(op) for op in chosen}
    for e in graph.edges:
        if e.relation in {'DOCUMENTED_DOWNSTREAM','DOCUMENTED_PREREQUISITE','RECOMMENDED_BEFORE','PARTIALLY_ALTERNATIVE_TO'} and (e.source in by_tool or e.target in by_tool):
            hints.append({'from':e.source,'relation':e.relation,'to':e.target,'evidence':e.properties.get('evidence_quotes',[]),
                          'status':'documentary_only'})
    return sorted(chosen),hints


def retrieve_datatypes(graph:Graph,index:SemanticIndex,description,top_k=5,device='cpu'):
    """Suggest datatype IDs semantically; suggestions are NEVER silently treated as supplied inputs."""
    if not description.strip():return []
    encoder=VectorEncoder(index.backend,index.model,device,dimensions=index.metadata['dimension'])
    return [{'datatype_id':row['id'],'name':graph.get(row['id']).get('name'),'score':round(row['score'],5),
             'status':'suggestion_not_approved'}
            for row in index.search(description,encoder,k=top_k,allowed_views={'datatype'}) if row['id'] in graph.datatypes]
