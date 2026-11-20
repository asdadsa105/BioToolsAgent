"""Attach preserved MD source evidence, parameters, resource requirements, commands.

Evidence is copied from the graph. This is NOT execution or independent software validation.
"""
from __future__ import annotations
from .graph import Graph,json_value


def op_evidence(graph:Graph,op_id):
    p=graph.get(op_id);tool_id,tool=graph.available_tool_info(op_id)
    scenarios=json_value(p.get('scenarios_json'),[])
    params=json_value(p.get('parameters_json'),[])
    full_tool_params=json_value(tool.get('parameters_json'),[])
    resources=json_value(tool.get('resource_requirements_json'),[])
    # Avoid treating human-readable evidence as a verified executable command.
    commands=[]
    for quote in p.get('evidence_quotes',[]):
        if isinstance(quote,str) and ('\n' in quote or quote.lstrip().startswith(('bcftools ','samtools ','bwa ','java ','fastp ','bedtools ','picard ', 'table_annovar.pl', 'annotate_variation.pl'))):
            commands.append({'text':quote,'origin':'operation evidence quote'})
    for s in scenarios:
        for key in ('command','command_template','command_example','command_examples','recommended_command','example'):
            raw=s.get(key) if isinstance(s,dict) else None
            if raw:
                if isinstance(raw,list):commands.extend({'text':str(x),'origin':'scenario '+str(s.get('name',''))} for x in raw)
                else:commands.append({'text':str(raw),'origin':'scenario '+str(s.get('name',''))})
    # Keep distinct commands without synthesizing any missing flags.
    dedup={}
    for c in commands:dedup.setdefault(c['text'],c)
    return {'operation_id':op_id,'operation':p.get('name'),
            'operation_description':p.get('description'),
            'task_names':[graph.get(tid).get('name','') for tid in graph.op_tasks.get(op_id,[])],
            'tool_id':tool_id,'tool':tool.get('name'),'tool_version':tool.get('version'),
            'docker_image':tool.get('docker_image'),
            'inputs':graph.operation_ports(op_id,'input'),
            'outputs':graph.operation_ports(op_id,'output'),
            'operation_parameters':params,'tool_parameters':full_tool_params,
            'commands_from_md':list(dedup.values()),
            'scenarios':scenarios,
            'resources':resources,
            'resource_reference_markdown':tool.get('resource_reference_markdown'),
            'resource_summary':{
                'cpu_cores_min':tool.get('cpu_cores_min'),
                'cpu_cores_recommended':tool.get('cpu_cores_recommended'),
                'memory_gb_min':tool.get('memory_gb_min'),
                'memory_gb_recommended':tool.get('memory_gb_recommended')},
            'source_files':p.get('source_files',[]),'source_sections':p.get('source_sections',[]),
            'evidence_quotes':p.get('evidence_quotes',[]),
            'evidence_status':p.get('validation_status','unknown'),
            'source_claim':'MD extracted, not runtime-tested'}


def enrich_paths(graph,paths):
    result=[]
    for path in paths:
        item=dict(path)
        item['step_details']=[op_evidence(graph,oid) for oid in path['steps']]
        for link in item['links']:
            # Pull graph-edge citations only for formally mapped DataTypes.
            if link['status']!='curated':continue
            pe=next((e for e in graph.from_node(link['from'],'PRODUCES') if e.target==link['produced_type']),None)
            re=next((e for e in graph.from_node(link['to'],'REQUIRES_INPUT') if e.target==link['required_type']),None)
            link['graph_evidence']={
                'producer_edge':{'relation':'PRODUCES','source_sections':pe.properties.get('source_sections',[]),
                                 'evidence_quotes':pe.properties.get('evidence_quotes',[])} if pe else None,
                'consumer_edge':{'relation':'REQUIRES_INPUT','source_sections':re.properties.get('source_sections',[]),
                                 'evidence_quotes':re.properties.get('evidence_quotes',[])} if re else None}
        result.append(item)
    return result


def render_markdown(report):
    lines=['# BioSkillKG 科研工具工作流规划','',
           '> 仅提供规划和文档证据；未执行科研工具，未独立验证命令或计算资源估计。','',
           '**用户问题：** '+report['question'],'',
           '**检索图谱：** '+report.get('graph_digest','')[:14]+'…','']
    if report.get('parser'):
        p=report['parser'];lines.extend(['**解析目标：** '+ '；'.join(p.get('subgoals',[])),''])
    if report.get('qwen',{}).get('mode','off') != 'off':
        q=report['qwen']
        success=bool(q.get('called') and q.get('scores'))
        state='（已本地评分，并应用于路径优先级）' if q.get('applied') else (
            '（已本地评分；shadow 不改变结果）' if success else '（未获取有效评分）')
        lines+=['**Qwen3-Reranker：** '+q.get('mode','off')+state,'']
        if success:
            rank=q.get('ranked_operation_ids') or []
            lines+=['**Qwen 评分排序（前 10 项，仅表示相关性）：**','']
            for op in rank[:10]:
                lines.append('- '+op+': '+str(round(q['scores'][op],4)))
            lines.append('')
    if report.get('jev'):
        j=report['jev'];lines.append('**Jev：** '+j.get('mode','off')+('（已评分）' if j.get('called') and j.get('scores') else '（未影响排序）'));lines.append('')
    for k,path in enumerate(report.get('workflows',[]),1):
        lines+=['## 候选方案 '+str(k),'','**状态：** '+path['status']+'（不是可以直接执行的证明）','']
        for i,s in enumerate(path['step_details'],1):
            lines+=['### 步骤 '+str(i)+'：'+str(s['tool'])+' / '+str(s['operation']),
                    '- 目标：'+str(s['operation_description']),
                    '- MD 来源：'+('; '.join(s['source_sections'][:4]) or '; '.join(s['source_files']))]
            if s['inputs']:
                lines.append('- 输入：'+'；'.join(str(p.get('data_type'))+' ['+str(p.get('resolution_status'))+']'+('（必需）' if p.get('required',True) else '（可选）') for p in s['inputs']))
            if s['outputs']:
                lines.append('- 输出：'+'；'.join(str(p.get('data_type'))+' ['+str(p.get('resolution_status'))+']' for p in s['outputs']))
            rr=s['resource_summary']
            lines.append(f"- 工具级资源参考：CPU 推荐 {rr.get('cpu_cores_recommended')}; 内存推荐 {rr.get('memory_gb_recommended')} GB（非操作实测）")
            if s['operation_parameters']:
                lines.append('- 操作参数（从 MD 抽取）：'+'；'.join(str(q.get('flag') or q.get('name')) for q in s['operation_parameters'][:15]))
            if s['commands_from_md']:
                lines+=['','**原文命令 / 示例（不保证可以原样执行）：**','','```bash',s['commands_from_md'][0]['text'],'```']
            if s['evidence_quotes']:
                lines+=['','**操作证据摘录：** '+str(s['evidence_quotes'][0])[:600]]
            lines.append('')
        lines.append('**步骤衔接依据：**')
        if not path['links']:lines.append('无已发现的上游操作连接；请核查输入是否由用户提供。')
        for l in path['links']:
            lines.append(f"- {l['from']} → {l['to']}：{l['produced_type']} → {l['required_type']}，状态 {l['status']}")
            a=l['evidence']
            lines.append('  - 上游来源：'+'; '.join(a['producer_source'][:2]))
            lines.append('  - 下游来源：'+'; '.join(a['consumer_source'][:2]))
        if path['missing_requirements']:
            lines+=['','**未满足 / 待确认的输入：**']
            for m in path['missing_requirements']:
                lines.append('- '+str(m.get('operation'))+'：'+str(m.get('input'))+' —— '+str(m.get('reason')))
        if path['warnings']:
            lines+=['','**风险与限定：**']
            lines+=['- '+w for w in path['warnings']]
        lines.append('')
    if not report.get('workflows'):
        lines+=['**尚未检索到足够证据构成候选路径。** 请补充初始数据类型或指定目标 Operation；不推测不存在的工具链。']
    return '\n'.join(lines)+'\n'
