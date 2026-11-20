"""Evidence-constrained backward workflow planning; no executable tool invocation."""
from __future__ import annotations
from dataclasses import dataclass,field
from typing import Optional
from .graph import Graph


@dataclass
class Workflow:
    goal: str
    steps: list=field(default_factory=list)
    links: list=field(default_factory=list)
    inputs: list=field(default_factory=list)
    missing: list=field(default_factory=list)
    warnings: list=field(default_factory=list)
    score: float=0.0

    def as_dict(self):
        return {'goal':self.goal,'steps':self.steps,'links':self.links,'inputs':self.inputs,
                'missing_requirements':self.missing,'warnings':self.warnings,
                'score':round(self.score,4),
                'status': 'candidate_pending_review' if any(e['status']=='pending_review' for e in self.links)
                else ('needs_external_inputs' if self.missing else 'type_connected'),
                'ready_to_execute':False}


class WorkflowSearch:
    def __init__(self,graph:Graph,candidate_ids=None,rank_scores=None,max_steps=6,allow_pending=True):
        self.graph=graph
        self.candidates=set(candidate_ids if candidate_ids is not None else graph.operations)
        self.scores=rank_scores or {}
        self.max_steps=max_steps
        self.allow_pending=allow_pending
        self._output_cache={oid:graph.produce_ports(oid,include_pending=allow_pending) for oid in graph.operations}

    def _link(self,from_id,output_port,to_id,input_port):
        a=output_port;b=input_port
        if a.get('resolution_status')==b.get('resolution_status')=='curated':
            if not self.graph.compatible(a.get('data_type_id'),b.get('data_type_id'),a.get('formats',[]),b.get('formats',[])):
                return None
            status='curated'
        elif (self.allow_pending and a.get('resolution_status')==b.get('resolution_status')=='pending_review'
              and a.get('candidate_type_id') and a.get('candidate_type_id')==b.get('candidate_type_id')):
            if a.get('formats') and b.get('formats') and not set(a['formats'])&set(b['formats']):return None
            status='pending_review'
        else:return None
        return {'from':from_id,'to':to_id,'status':status,
                'produced_type':a.get('data_type_id') or a.get('candidate_type_id'),
                'required_type':b.get('data_type_id') or b.get('candidate_type_id'),
                'produced_format':a.get('formats',[]),'required_format':b.get('formats',[]),
                'evidence':{'producer':a.get('evidence_quotes') or [a.get('evidence_quote')],
                            'consumer':b.get('evidence_quotes') or [b.get('evidence_quote')],
                            'producer_source':a.get('source_sections',[]),
                            'consumer_source':b.get('source_sections',[])}}

    def _matches_available(self,required,inventory):
        if required.get('resolution_status')!='curated':return None
        for source in inventory:
            if source.get('type_id') and self.graph.compatible(source['type_id'],required.get('data_type_id'),source.get('formats',[]),required.get('formats',[])):
                return source
        return None

    def _producers(self,need,target,visiting):
        possible=[]
        for oid in self.candidates:
            if oid in visiting or oid==target:continue
            for p in self._output_cache[oid]:
                link=self._link(oid,p,target,need)
                if link:possible.append((oid,p,link))
        possible.sort(key=lambda x:(x[2]['status']!='curated',-self.scores.get(x[0],0),x[0]))
        return possible[:8]

    def _extend(self,target,inventory,visiting,remaining):
        if target in visiting or remaining<=0:return None
        scenarios=self.graph.input_scenarios(target)
        results=[]
        for ports in scenarios:
            steps=[]; links=[]; missing=[];active=list(inventory)
            success=True
            # Handle every required input of THIS scenario, not all alternative scenarios.
            for port in [p for p in ports if p.get('required',True)]:
                chosen=self._matches_available(port,active)
                if chosen:
                    min_occurs=int(port.get('min_occurs') or 1)
                    if min_occurs>1:
                        missing.append({'operation':target,'input':port.get('data_type'),'reason':f'requires {min_occurs} input files; distinct file count not verified','port_id':port.get('port_id')})
                    continue
                resolved=False
                for provider,output,link in self._producers(port,target,visiting | {target}):
                    if provider in steps:
                        links.append(link);resolved=True;break
                    if len(steps)+1>=remaining:continue
                    sub=self._extend(provider,active,visiting|{target},remaining-len(steps)-1)
                    if sub is None:continue
                    if len(steps)+len(sub.steps)+1>=remaining:continue
                    for s in sub.steps:
                        if s not in steps:steps.append(s)
                    links+=sub.links
                    missing+=sub.missing
                    # Preserve outputs made by all upstream steps.
                    for s in sub.steps:
                        for o in self._output_cache[s]:
                            if o.get('resolution_status')=='curated':
                                active.append({'type_id':o.get('data_type_id'),'formats':o.get('formats',[]),'source_operation':s})
                    links.append(link);resolved=True
                    break
                if not resolved:
                    missing.append({'operation':target,'input':port.get('data_type'),
                                    'status':port.get('resolution_status'),
                                    'port_id':port.get('port_id'),
                                    'formats':port.get('formats',[]),
                                    'reason':'No proven upstream producer or supplied input; external file or review needed'})
            if target not in steps:steps.append(target)
            if len(steps)<=remaining:
                report=Workflow(goal=target,steps=steps,links=links,missing=missing)
                report.score=(sum(self.scores.get(s,0) for s in steps) -
                              1.2*len(missing) - .55*sum(e['status']=='pending_review' for e in links)
                              - .13*len(steps))
                results.append(report)
        if not results:return None
        results.sort(key=lambda x:(len(x.missing),sum(e['status']=='pending_review' for e in x.links),len(x.steps),-x.score))
        return results[0]

    def search(self,goal_ops,available_types=None,top_n=3):
        inventory=[{'type_id':v,'formats':[],'source_operation':None} if isinstance(v,str) else v for v in (available_types or [])]
        paths=[]
        for oid in goal_ops:
            if oid not in self.graph.operations:continue
            plan=self._extend(oid,inventory,set(),self.max_steps)
            if plan:
                plan.inputs=inventory
                if any(l['status']=='pending_review' for l in plan.links):
                    plan.warnings.append('Candidate-only connection based on pending_review ports; not a certified DataType edge.')
                if plan.missing:
                    plan.warnings.append('One or more required inputs are missing or their quantities are unverified.')
                paths.append(plan)
        priority={op:i for i,op in enumerate(goal_ops)}
        paths.sort(key=lambda x:(priority.get(x.goal,999),len(x.missing),sum(l['status']=='pending_review' for l in x.links),-x.score))
        return [x.as_dict() for x in paths[:top_n]]
