"""Operation-level Jev adapter, reusing the existing TypeSafe System One protocol.

No tool execution; remote Jev only ranks candidates and can fail open.
"""
from __future__ import annotations
import os
import httpx
from .graph import Graph


def rerank_operations(graph:Graph,query,candidates,mode='off',api_key=None,timeout=45):
    mode=mode.lower()
    if mode not in ('off','shadow','rerank','filter'):raise ValueError('Unknown Jev mode')
    unchanged=list(candidates)
    if mode=='off':return unchanged,{'mode':'off','called':False,'scores':{}}
    key=api_key or os.getenv('TYPESAFE_API_KEY')
    if not key:return unchanged,{'mode':mode,'called':False,'reason':'TYPESAFE_API_KEY not set','scores':{}}
    if not candidates:return unchanged,{'mode':mode,'called':False,'scores':{}}
    state={'task':query,'candidate_operations':[],'connections':[]}
    ids=[c['operation_id'] for c in candidates]
    for oid in ids:
        p=graph.get(oid);tid,t=graph.available_tool_info(oid)
        state['candidate_operations'].append({'id':oid,'tool':t.get('name'),
           'name':p.get('name'),'description':p.get('description'),
           'task_names':[graph.get(tid).get('name') for tid in graph.op_tasks.get(oid,[])],
           'inputs':[{'datatype':x.get('data_type'), 'status':x.get('resolution_status'),'formats':x.get('formats')} for x in graph.operation_ports(oid,'input')],
           'outputs':[{'datatype':x.get('data_type'), 'status':x.get('resolution_status'),'formats':x.get('formats')} for x in graph.operation_ports(oid,'output')]})
    for a in ids:
        for b in ids:
            if a==b:continue
            for link in graph.has_type_link(a,b):
                state['connections'].append({'from':a,'to':b,'data_type':link['produced_type'],'status':'curated'})
    questions={f'op_{i}':{'type':'noul','instructions':(
        f"For the requested planning task, is candidate Operation ID '{oid}' useful either as the target operation "
        "or as a necessary upstream transformation? Consider all input-output types. "
        "Score usefulness only, not correctness or executability. Do not require that it directly produces the final answer.")}
        for i,oid in enumerate(ids)}
    payload={'model':os.getenv('JEV_MODEL','jev-latest'),'state':state,'questions':questions}
    try:
        with httpx.Client(timeout=timeout) as client:
            r=client.post(os.getenv('JEV_API_BASE','https://api.typesafe.ai').rstrip('/')+'/v1/systemone',
                          headers={'Authorization':'Bearer '+key},json=payload)
            if r.status_code >= 400:
                safe_body = r.text.replace(key, "[REDACTED]")
                print(f"[Jev] HTTP {r.status_code}")
                print(f"[Jev] Response: {safe_body[:500]}")
            r.raise_for_status();answer=r.json()['answers']
        scores={oid:float(answer[f'op_{i}']['noul']) for i,oid in enumerate(ids)}
        if any(not (0<=s<=1) for s in scores.values()):raise ValueError('invalid probability')
    except httpx.HTTPStatusError as exc:
        return unchanged, {
            'mode': mode,
            'called': True,
            'reason': (
                f'Jev HTTP {exc.response.status_code}: '
                f'{exc.response.reason_phrase}'
            ),
            'scores': {}
        }

    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return unchanged, {
            'mode': mode,
            'called': True,
            'reason': f'Jev unavailable: {type(exc).__name__}',
            'scores': {}
        }
    if mode=='shadow':return unchanged,{'mode':mode,'called':True,'scores':scores,'applied':False}
    reranked=sorted(candidates,key=lambda x:(-scores[x['operation_id']],-x['score']))
    if mode=='filter':
        # Never prune an Operation outright: graph expansion may need it as a prerequisite.
        # Distinguish user-requested filter mode from the old execution-time hard filtering.
        return reranked,{'mode':mode,'called':True,'scores':scores,'applied':True,
                          'note':'planning-safe filter: rank only; no Operation deleted'}
    return reranked,{'mode':mode,'called':True,'scores':scores,'applied':True}
