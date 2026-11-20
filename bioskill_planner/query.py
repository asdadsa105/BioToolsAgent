"""Parse task questions. DeepSeek is opt-in, with a deterministic no-key fallback."""
from __future__ import annotations
import json,os,re
import httpx
from .graph import Graph


def heuristic_parse(question):
    pieces=[q.strip() for q in re.split(r'[；;，,。\n]|(?:然后)|(?:接着)|(?:并且)|(?:再)',question) if q.strip()]
    if len(pieces)>7: pieces=pieces[:7]
    return {'original':question,'subgoals':pieces or [question],
            'input_descriptions':[],'target_descriptions':[],'constraints':[],
            'parser':'heuristic'}


def parse_with_deepseek(question,api_key=None):
    key=api_key or os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY')
    if not key:raise RuntimeError('Set DEEPSEEK_API_KEY to use --parser deepseek')
    base=(os.getenv('DEEPSEEK_BASE_URL') or 'https://api.deepseek.com').rstrip('/')
    model=os.getenv('DEEPSEEK_MODEL') or 'deepseek-chat'
    payload={'model':model,'temperature':0,'response_format':{'type':'json_object'},'messages':[
        {'role':'system','content':('Extract a research-tool WORKFLOW PLANNING request as JSON. Do not answer or recommend ungrounded tools. '
            'Return keys subgoals (list of short verb phrases), input_descriptions (list of available data descriptions), '
            'target_descriptions (list of desired result descriptions), constraints (list of constraints). '
            'Preserve data formats, sortedness, pairing and sample counts. Use original language.')},
        {'role':'user','content':question}]}
    with httpx.Client(timeout=45) as client:
        r=client.post(base+'/chat/completions',headers={'Authorization':'Bearer '+key},json=payload)
        r.raise_for_status();content=r.json()['choices'][0]['message']['content']
    data=json.loads(content)
    parsed={'original':question,'parser':'deepseek'}
    for k in ['subgoals','input_descriptions','target_descriptions','constraints']:
        val=data.get(k,[])
        parsed[k]=[str(x) for x in val][:12] if isinstance(val,list) else []
    if not parsed['subgoals']:parsed['subgoals']=[question]
    return parsed


def match_input_types(graph:Graph, descriptions,question='',allow_guess=False):
    """Conservative initial type resolution; returns match evidence and ambiguity.

    Type aliases are intentionally small. Missing information is not filled in.
    An unsorted BAM must not be treated as coordinate-sorted BAM.
    """
    found=[]
    for phrase in descriptions:
        s=phrase.casefold()
        candidates=[]
        for node_id,node in graph.datatypes.items():
            name=str(node['properties'].get('name','')).casefold()
            if name and (name in s or (len(s)>3 and s in name)):candidates.append(node_id)
        if 'bam' in s:
            if ('未排序' in s or 'unsorted' in s):candidates=['data:aligned_reads_bam_unsorted']
            elif ('已排序' in s or 'sorted' in s or '排序后' in s):candidates=['data:aligned_reads_bam_sorted']
            elif ('重复标记' in s or '标记重复' in s or 'dedup' in s):
                candidates=[x for x in graph.datatypes if 'duplicate_marked' in x]
            else:candidates=['data:aligned_reads_bam']
        elif ('vcf' in s or 'bcf' in s):
            if '过滤' in s or 'filtered' in s:candidates=['data:filtered_variant_calls']
            else:candidates=['data:variant_calls']
        elif ('fastq' in s or 'fq.gz' in s):
            candidates=['data:short_reads']
        for cid in candidates:
            if cid in graph.datatypes and cid not in [v['type_id'] for v in found]:
                found.append({'type_id':cid,'evidence':phrase,'confidence':'explicit'})
    # Only infer available inputs when user unambiguously claims possession.
    if not descriptions and allow_guess and re.search(r'我有|已有|currently have|i have|provided|input is',question,re.I):
        prefix=re.split(r'希望|想|然后|要做|目标|to perform|want to',question,maxsplit=1)[0]
        found=match_input_types(graph,[prefix])
        for f in found:f['confidence']='heuristic'
    return found
