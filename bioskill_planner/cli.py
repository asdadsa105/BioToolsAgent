"""Standalone planner CLI. Existing graph creation and execution agent stay untouched."""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from .graph import Graph
from .index import SemanticIndex,VectorEncoder
from .query import heuristic_parse,parse_with_deepseek,match_input_types
from .retrieve import retrieve_operations,expand_candidates,retrieve_datatypes
from .jev import rerank_operations
from .qwen_reranker import DEFAULT_MODEL_PATH, rerank_operations_qwen, score_pairs_local
from .workflow import WorkflowSearch
from .evidence import enrich_paths,render_markdown

DEFAULT_GRAPH='data/bio_skill_kg/v56_picard_fresh_test/all7_fresh.json'


def load_env_file(path):
    if not path:return
    try:from dotenv import load_dotenv
    except ImportError as exc:raise RuntimeError('pip install python-dotenv for --env-file') from exc
    if not Path(path).exists():raise FileNotFoundError(path)
    load_dotenv(path,override=False)


def load_graph(args):
    if args.source=='json':return Graph.from_json(args.graph)
    return Graph.from_neo4j(args.namespace,args.database)


def choose_goals(graph,index,parser,candidates,explicit_goals,device='cpu',n=3):
    if explicit_goals:
        invalid=[x for x in explicit_goals if x not in graph.operations]
        if invalid:raise ValueError('Unknown --goal-op: '+', '.join(invalid))
        return explicit_goals
    # Prioritize final named subgoal; the whole query is a fallback.
    end=(parser.get('target_descriptions') or parser.get('subgoals') or [parser['original']])[-1]
    encoder=VectorEncoder(index.backend,index.model,device,dimensions=index.metadata['dimension'])
    scores={}
    for r in index.search(end,encoder,k=max(n*6,15),allowed_views={'purpose','scenario','io'}):
        if r['id'] in graph.operations:scores[r['id']]=max(scores.get(r['id'],-1),r['score'])
    # Reranked candidates first only if their semantics also match the target.
    picked=sorted((c['operation_id'] for c in candidates if c['operation_id'] in scores),key=lambda x:-scores[x])[:n]
    return picked or [c['operation_id'] for c in candidates[:n]]


def candidate_list(candidates, expanded):
    """Start with BGE-ranked candidates, then append deterministic graph neighbors."""
    score_map={c['operation_id']:c['score'] for c in candidates}
    ids=list(dict.fromkeys([c['operation_id'] for c in candidates] + sorted(expanded)))
    return [{'operation_id':oid,'score':score_map.get(oid,0.0)} for oid in ids]


def build_parser():
    p=argparse.ArgumentParser(description='BioSkillKG planning-only vector retrieval and workflow search')
    sub=p.add_subparsers(dest='action',required=True)
    for name in ('index','query'):
        s=sub.add_parser(name)
        s.add_argument('--source',choices=['json','neo4j'],default='json')
        s.add_argument('--graph',default=DEFAULT_GRAPH)
        s.add_argument('--namespace',default='BioSkillV56PicardFreshTest')
        s.add_argument('--database',default=os.getenv('NEO4J_DATABASE','neo4j'))
        s.add_argument('--index-dir',default='data/bio_skill_kg/planner_index')
        s.add_argument('--device',default='auto',help='auto/cpu/cuda; auto selects CUDA when present')
        s.add_argument('--env-file',help='Optional user-supplied env file, never bundled')
        if name=='index':
            s.add_argument('--backend',default='bge-m3',choices=['bge-m3','lexical'])
            s.add_argument('--model',default='BAAI/bge-m3')
            s.add_argument('--batch-size',type=int,default=16)
        else:
            s.add_argument('--question',required=True)
            s.add_argument('--parser',choices=['heuristic','deepseek'],default='heuristic')
            s.add_argument('--jev',choices=['off','shadow','rerank','filter'],default='off',help='Legacy TypeSafe API (optional)')
            s.add_argument('--qwen',choices=['off','shadow','rerank'],default='off',help='Local Qwen3 reranker: off/shadow/rerank')
            s.add_argument('--qwen-model',default=None,help='Local HF-format Qwen3 model directory, e.g. D:\\qwen3_reranker')
            s.add_argument('--qwen-device',choices=['auto','cuda','cpu'],default='auto')
            s.add_argument('--qwen-batch-size',type=int,default=1)
            s.add_argument('--qwen-max-length',type=int,default=2048)
            s.add_argument('--qwen-subgoal-limit',type=int,default=3)
            s.add_argument('--qwen-weight',type=float,default=0.20,help='Additive priority bonus [0..1] on graph search score, only in rerank mode')
            s.add_argument('--goal-op',action='append',default=[],help='Operation id; repeat for multiple goals')
            s.add_argument('--input-type',action='append',default=[],help='Initial DataType ID; repeat for multiple inputs')
            s.add_argument('--top-k',type=int,default=12)
            s.add_argument('--max-steps',type=int,default=6)
            s.add_argument('--output',help='Write Markdown report to file')
            s.add_argument('--json-output',help='Write detailed machine-readable report')
    check=sub.add_parser('qwen-check',help='Test locally downloaded Qwen3-Reranker without BGE, DeepSeek or Jev')
    check.add_argument('--qwen-model',default=os.getenv('QWEN_RERANKER_PATH',DEFAULT_MODEL_PATH))
    check.add_argument('--qwen-device',choices=['auto','cuda','cpu'],default='auto')
    check.add_argument('--qwen-batch-size',type=int,default=1)
    check.add_argument('--qwen-max-length',type=int,default=2048)
    return p


def main(argv=None):
    args=build_parser().parse_args(argv)
    if args.action=='qwen-check':
        texts=[
            'Picard MarkDuplicates: marks PCR duplicate reads in an aligned BAM.',
            'bcftools merge: combines VCF variant files from multiple samples.',
        ]
        question='我有已排序BAM，想标记PCR重复序列'
        values=score_pairs_local(args.qwen_model,[(question,x) for x in texts],
            device=args.qwen_device,batch_size=args.qwen_batch_size,max_length=args.qwen_max_length)
        print(json.dumps({'status':'ok','backend':'qwen3-local','model':args.qwen_model,
            'scores':[{'candidate':s,'score':round(v,6)} for s,v in zip(texts,values)]},ensure_ascii=False,indent=2))
        return 0
    load_env_file(args.env_file)
    if args.action=='query':
        args.qwen_model=args.qwen_model or os.getenv('QWEN_RERANKER_PATH',DEFAULT_MODEL_PATH)
    graph=load_graph(args)
    if args.action=='index':
        index=SemanticIndex.build(graph,args.backend,args.model,args.device,args.batch_size)
        index.save(args.index_dir)
        print(json.dumps({'status':'indexed','backend':args.backend,'model':index.model,
           'operations':len(graph.operations),'views':len(index.entries),'index_dir':args.index_dir,
           'graph_digest':graph.digest[:16]},ensure_ascii=False,indent=2))
        return 0
    index=SemanticIndex.load(args.index_dir,graph)
    parsed=parse_with_deepseek(args.question) if args.parser=='deepseek' else heuristic_parse(args.question)
    candidates=retrieve_operations(graph,index,parsed,top_k=args.top_k,device=args.device)
    expanded,hints=expand_candidates(graph,[c['operation_id'] for c in candidates],max_hops=1)
    # Finish all BGE-M3 inference BEFORE loading the Qwen3 weights onto the GPU.
    # Keep goal detection independent of reranker scores to avoid selecting a
    # prerequisite as a false final goal.
    goals=choose_goals(graph,index,parsed,candidates,args.goal_op,device=args.device)
    datatype_suggestions={phrase:retrieve_datatypes(graph,index,phrase,device=args.device)
                          for phrase in parsed.get('input_descriptions',[])+parsed.get('target_descriptions',[])}
    all_candidates=set(expanded)|set(goals)
    initial=match_input_types(graph,parsed.get('input_descriptions',[]),args.question,allow_guess=True)
    for cid in args.input_type:
        if cid not in graph.datatypes:raise ValueError('Unknown --input-type: '+cid)
        if cid not in [x['type_id'] for x in initial]:initial.append({'type_id':cid,'confidence':'explicit_cli','evidence':'--input-type'})
    if args.jev!='off' and args.qwen!='off':
        raise ValueError('Use one reranker at a time: --jev off --qwen rerank OR --qwen off --jev rerank')
    if not 0 <= args.qwen_weight <= 1:
        raise ValueError('--qwen-weight must be in [0,1]')
    score_map={c['operation_id']:c['score'] for c in candidates}
    rank_input=candidate_list(candidates,all_candidates)
    jev_meta={'mode':'off','called':False,'scores':{},'applied':False}
    qwen_meta={'mode':'off','called':False,'scores':{},'applied':False}
    if args.qwen!='off':
        print(f'[Qwen] 本地模型：{args.qwen_model}; mode={args.qwen}; candidates={len(rank_input)}',flush=True)
        qwen_ranked,qwen_meta=rerank_operations_qwen(graph,args.question,parsed,rank_input,
            mode=args.qwen,model_path=args.qwen_model,device=args.qwen_device,
            batch_size=args.qwen_batch_size,max_length=args.qwen_max_length,
            max_subgoals=args.qwen_subgoal_limit)
        if qwen_meta.get('applied'):
            for item in qwen_ranked:
                op=item['operation_id']
                score_map[op]=round(score_map.get(op,0.) + args.qwen_weight*qwen_meta['scores'][op],6)
        print('[Qwen] '+('重排已应用' if qwen_meta.get('applied') else 'Shadow 分数已生成但未修改优先级'),flush=True)
    elif args.jev!='off':
        jev_ranked,jev_meta=rerank_operations(graph,args.question,rank_input,mode=args.jev)
        if jev_meta.get('applied'):
            for i,c in enumerate(jev_ranked):
                score_map[c['operation_id']]=score_map.get(c['operation_id'],0)+.10*(len(jev_ranked)-i)/max(1,len(jev_ranked))
    planner=WorkflowSearch(graph,all_candidates,score_map,max_steps=args.max_steps,allow_pending=True)
    found=planner.search(goals,available_types=initial,top_n=3)
    report={'datatype_suggestions':datatype_suggestions,'question':args.question,'parser':parsed,'graph_digest':graph.digest,'index_backend':index.backend,
            'candidates':candidates,'expanded_operation_ids':sorted(all_candidates),
            'documentary_hints':hints,'jev':jev_meta,'qwen':qwen_meta,'selected_goals':goals,
            'effective_operation_scores':score_map,
            'resolved_initial_data':initial,'workflows':enrich_paths(graph,found),
            'execution_performed':False}
    markdown=render_markdown(report)
    if args.output:
        p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(markdown,encoding='utf-8')
    else:print(markdown)
    if args.json_output:
        p=Path(args.json_output);p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0
