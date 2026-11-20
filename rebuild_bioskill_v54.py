#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fresh BioSkillKG v5.4 rebuild from 5 Markdown skill docs + cached LLM extracts.

Never merges an old graph, calls an LLM, or writes Neo4j.
Requires project bio_skill_kg (v5.3 auto_builder) importable from cwd.
Adds minimal evidence-checked scenarios/format corrections as curated overlays.
"""
from __future__ import annotations

import argparse
import collections
import copy
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from bio_skill_kg.auto_builder import build_graph_from_extractions, load_data_type_ontology
from bio_skill_kg.builder import summary

SKILLS = ('annovar', 'bcftools', 'bedtools', 'bwa', 'samtools')
SOURCES = {
    'samtools_view': 'https://www.htslib.org/doc/samtools-view.html',
    'bedtools_unionbedg': 'https://bedtools.readthedocs.io/en/latest/content/tools/unionbedg.html',
    'bedtools_genomecov': 'https://bedtools.readthedocs.io/en/latest/content/tools/genomecov.html',
    'samtools_sort': 'https://www.htslib.org/doc/samtools-sort.html',
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def require(md: str, quote: str, label: str):
    if quote not in md:
        raise ValueError(f'{label}: MD 缺少规定的原文证据: {quote!r}')


def port(data_type, role, fmt, quote, sid, sname, *, required=True,
         flag=None, min_occurs=1, extra=None, format_quote=None):
    obj = {
        'data_type': data_type, 'role': role, 'formats': [fmt] if fmt else [],
        'evidence_quote': quote, 'scenario_id': sid, 'scenario_name': sname,
        'required': required, 'min_occurs': min_occurs, 'max_occurs': None,
        'flag': flag, 'format_evidence': (
            [{'format': fmt, 'evidence_quote': format_quote or quote}]
            if fmt and (format_quote or quote) else []),
    }
    if extra:
        obj.update(extra)
    return obj


def find_op(extraction, name):
    hits = [o for o in extraction.get('operations', []) if o.get('name') == name]
    if len(hits) != 1:
        raise ValueError(f'Operation {name} should occur once; found {len(hits)}')
    return hits[0]


def curated_overlays(mds: dict[str, str], extracts: dict[str, dict], ontology: dict):
    """Only add/replace a few explicitly reviewed claims. Original JSON is untouched."""
    changes = []

    # 1: evidence-backed SAM->BAM conversion already present in the original MD.
    s = mds['samtools']; e = extracts['samtools']
    cmd = 'samtools view -bS input.sam > output.bam'
    require(s, cmd, 'samtools view conversion')
    view = find_op(e, 'samtools view')
    sid, sname = 'sam_to_bam_conversion', 'SAM转BAM格式转换'
    view.setdefault('inputs', []).append(port(
        '序列比对结果（SAM）', 'input_sam', 'SAM', cmd, sid, sname,
        extra={'sorting_state': 'input_dependent', 'provenance_kind': 'md_example'}))
    view.setdefault('outputs', []).append(port(
        '序列比对结果（BAM）', 'output_bam', 'BAM', cmd, sid, sname,
        extra={'sorting_state': 'preserved_from_input', 'output_channel': 'stdout_redirect',
               'provenance_kind': 'md_example'}))
    view.setdefault('scenarios', []).append({
        'scenario_id': sid, 'name': sname,
        'description': 'SAM转BAM；不推断 BAM 是否已排序',
        'evidence_quote': cmd, 'provenance_kind': 'md_example'})
    changes.append('samtools view 增加 SAM→BAM 独立场景；排序状态保持未知')

    # 1b: samtools sort accepts a BAM even when its sorting state is unknown.
    # Keep the documented 'unsorted BAM' scenario; add a more general coordinate-sort scenario.
    sort_cmd = 'samtools sort -@ 8 -o sorted.bam unsorted.bam'
    require(s, sort_cmd, 'samtools sort example')
    sort_op = find_op(e, 'samtools sort')
    sort_sid, sort_sname = 'general_bam_coordinate_sort', 'BAM坐标排序（通用输入）'
    sort_op.setdefault('inputs', []).append(port(
        '序列比对结果（BAM）', 'input_bam', 'BAM', sort_cmd, sort_sid, sort_sname,
        extra={'sorting_state_required':'any', 'provenance_kind':'curated_external_manual',
               'external_validation_url':SOURCES['samtools_sort']}))
    sort_op.setdefault('outputs', []).append(port(
        '已排序BAM比对结果', 'output_coordinate_sorted_bam', 'BAM', sort_cmd,
        sort_sid, sort_sname, flag='-o',
        extra={'sorting_state':'coordinate_sorted', 'provenance_kind':'curated_external_manual',
               'external_validation_url':SOURCES['samtools_sort']}))
    sort_op.setdefault('scenarios', []).append({
        'scenario_id':sort_sid, 'name':sort_sname,
        'description':'通用 BAM 输入，默认坐标排序输出；不使用 -n/-N/-t 等替代排序模式',
        'evidence_quote':sort_cmd, 'provenance_kind':'curated_external_manual',
        'external_validation_url':SOURCES['samtools_sort']})
    changes.append('samtools sort 增加通用 BAM 坐标排序场景，支持 view 输出接入 sort')

    # 2: flagstat is textual statistics written to standard output without redirection.
    cmd = 'samtools flagstat input.bam'
    stats_table = '| o3 | 统计信息 | TXT | 根据命令 | 各种统计信息文件 |'
    require(s, cmd, 'samtools flagstat'); require(s, stats_table, 'samtools statistics output definition')
    flagstat = find_op(e, 'samtools flagstat')
    flagstat.setdefault('outputs', []).append(port(
        '比对统计结果', 'statistics_stdout', 'TXT', cmd, 'default', 'BAM统计',
        extra={'output_channel':'stdout', 'produces_file_directly':False,
               'format_interpretation':'tabular_plain_text', 'provenance_kind':'curated_from_md_and_manual'},
        format_quote=stats_table))
    changes.append('samtools flagstat 增加 stdout 比对统计结果；不虚构输出文件')

    # 3: unionbedg requires BEDGRAPH, not any .bed file. Result has >=5 columns.
    b = mds['bedtools']; e = extracts['bedtools']
    example = 'bedtools unionbedg -i *_coverage.bed > merged_coverage.bed'
    fmt_quote = '| BEDGRAPH | 支持 | .bedgraph | BEDGRAPH格式的信号文件 |'
    require(b, example, 'bedtools unionbedg'); require(b, fmt_quote, 'bedGraph documentation in MD')
    u = find_op(e, 'bedtools unionbedg')
    if len(u.get('inputs',[]))!=1 or len(u.get('outputs',[]))!=1:
        raise ValueError('Unexpected unionbedg cached I/O structure')
    inp = u['inputs'][0]
    inp.update({
        'data_type':'基因组信号轨道数据', 'description':'多个 BEDGRAPH 格式的覆盖度信号文件；实际内容须为 bedGraph 四列结构',
        'formats':['BEDGRAPH'], 'format_evidence':[{'format':'BEDGRAPH','evidence_quote':fmt_quote}],
        'min_occurs':2, 'max_occurs':None,
        'provenance_kind':'curated_external_manual',
        'external_validation_url':SOURCES['bedtools_unionbedg'],
        'original_claim':'输入区域覆盖度结果/BED；MD 示例使用 .bed 后缀，此后缀不能保证 BEDGRAPH 内容',
        'data_format_rule':'chrom, start, end, value (4 columns)',
    })
    # The cached file name ends .bed, but unionbedg output has 3 + N sample-value columns.
    out = u['outputs'][0]
    out.update({
        'data_type':'多样本覆盖度矩阵', 'description':'3列基因组坐标 + N列样本覆盖度值；并非标准4列 BEDGRAPH',
        'formats': [], 'format_evidence': [],
        'data_layout':'chrom, start, end, value_sample_1, ..., value_sample_N',
        'provenance_kind':'curated_external_manual',
        'external_validation_url':SOURCES['bedtools_unionbedg'],
        'original_claim':'抽取时映射为多样本覆盖度结果/BED；无充分格式依据',
    })
    ontology['multi_sample_coverage_matrix'] = {
        'name':'多样本覆盖度矩阵',
        'description':'bedtools unionbedg 将多个 bedGraph 的区域信号合并为坐标与多样本数值列组成的表格。',
        'formats': [],
        'aliases':['多样本覆盖度矩阵', '多样本 bedGraph 信号合并矩阵'],
    }
    changes.append('bedtools unionbedg 输入纠正为 BEDGRAPH；输出另建多样本覆盖度矩阵')

    # 4: -ibam requires coordinate-sorted BAM per bedtools manual;
    # -bga output is the bedGraph stream BEFORE the MD's awk transform.
    g = find_op(e, 'bedtools genomecov')
    for i in g.get('inputs', []):
        if i.get('role') == 'alignments':
            i.update({'data_type':'已排序BAM比对结果',
                      'description':'-ibam 要求按参考坐标排序的 BAM 文件',
                      'sorting_state_required':'coordinate_sorted',
                      'provenance_kind':'curated_external_manual',
                      'external_validation_url':SOURCES['bedtools_genomecov']})
            changes.append('bedtools genomecov -ibam 输入约束补充为坐标已排序 BAM')
    for o in g.get('outputs',[]):
        if o.get('role') == 'coverage_signal_track':
            o['output_channel'] = 'stdout_before_pipeline_transform'
            o['format_rule'] = 'BEDGRAPH from -bga, before awk'
            o['provenance_kind'] = 'md_example'
            changes.append('bedtools genomecov -bga 输出边限定为 awk 过滤前的 BEDGRAPH 数据')
    return changes


def extract_ports(node, field):
    raw = node.get('properties',{}).get(field)
    if not raw: return []
    try:
        obj = json.loads(raw) if isinstance(raw,str) else raw
        return obj if isinstance(obj,list) else []
    except (ValueError,TypeError):
        return []


def graph_workflows(graph):
    """Candidate only: type ancestor + declared port formats, never assert executable workflow."""
    nd = {n['id']:n for n in graph['nodes']}
    owner = {}
    for e in graph['edges']:
        if e['type']=='HAS_OPERATION':owner[e['target']]=e['source']
    parents = collections.defaultdict(set)
    for e in graph['edges']:
        if e['type']=='IS_SUBTYPE_OF':parents[e['source']].add(e['target'])

    def ancestor_of(child, parent):
        if child==parent:return True
        front={child}; seen=set()
        while front:
            val=front.pop()
            if val in seen: continue
            seen.add(val)
            if parent in parents[val]:return True
            front |= parents[val]-seen
        return False

    def formats(port):
        return set(str(x).upper().replace('.','_') for x in port.get('formats',[]) if x)

    ops = [n for n in graph['nodes'] if n['label']=='Operation']
    rows=[]
    for a in ops:
        for b in ops:
            if a['id']==b['id']: continue
            for p in extract_ports(a,'output_specs_json'):
                for q in extract_ports(b,'input_specs_json'):
                    if not ancestor_of(p['data_type_id'],q['data_type_id']): continue
                    fo,fq=formats(p),formats(q)
                    if not fo or not fq:
                        flag='REVIEW_MISSING_FORMAT'
                    elif not fo.intersection(fq):
                        flag='REJECT_FORMAT_MISMATCH'
                    elif (q.get('min_occurs') or 1)>1:
                        flag='NEEDS_MULTIPLE_INPUTS'
                    elif p.get('output_channel')=='stdout' and q.get('file_path_required'):
                        flag='NEEDS_STREAM_REDIRECTION'
                    else:
                        flag='CANDIDATE_ONLY'
                    rows.append({
                      'upstream':a['properties']['name'],
                      'upstream_tool':owner.get(a['id'],'').removeprefix('tool:'),
                      'out_type':p['data_type_id'],
                      'out_formats':','.join(sorted(fo)),
                      'out_scenario':p.get('scenario_id') or '',
                      'downstream':b['properties']['name'],
                      'downstream_tool':owner.get(b['id'],'').removeprefix('tool:'),
                      'relation_scope':'same_tool' if owner.get(a['id']) == owner.get(b['id']) else 'cross_tool',
                      'in_type':q['data_type_id'],
                      'in_formats':','.join(sorted(fq)),
                      'in_scenario':q.get('scenario_id') or '',
                      'check':flag,
                    })
    return rows


def verify(graph, workflows):
    nodes = {n['id']:n for n in graph['nodes']}
    edges = {(e['source'],e['type'],e['target']) for e in graph['edges']}
    assert len(nodes)==len(graph['nodes']), 'duplicate nodes'
    assert len(edges)==len(graph['edges']), 'duplicate edges'
    assert all(a in nodes and b in nodes for a,_,b in edges), 'broken edge references'
    assert sum(n['label']=='Operation' for n in nodes.values())==21, 'unexpected operation count'
    must = [
        ('op:bwa_mem','PRODUCES','data:aligned_reads_sam'),
        ('op:samtools_view','REQUIRES_INPUT','data:aligned_reads_sam'),
        ('op:samtools_view','PRODUCES','data:aligned_reads_bam'),
        ('op:samtools_view','REQUIRES_INPUT','data:aligned_reads_bam_sorted'),
        ('op:samtools_flagstat','PRODUCES','data:alignment_statistics'),
        ('op:bedtools_genomecov','PRODUCES','data:signal_tracks'),
        ('op:bedtools_genomecov','REQUIRES_INPUT','data:aligned_reads_bam_sorted'),
        ('op:samtools_sort','REQUIRES_INPUT','data:aligned_reads_bam'),
        ('op:bedtools_unionbedg','REQUIRES_INPUT','data:signal_tracks'),
        ('op:bedtools_unionbedg','PRODUCES','data:multi_sample_coverage_matrix'),
    ]
    assert all(x in edges for x in must), 'required graph relations missing: '+str([x for x in must if x not in edges])
    assert ('op:bedtools_unionbedg','REQUIRES_INPUT','data:coverage_result') not in edges
    assert ('op:bedtools_unionbedg','PRODUCES','data:multi_sample_coverage_result') not in edges
    assert ('op:samtools_depth','PRODUCES','data:per_base_depth') in edges
    assert not any(x['upstream']=='samtools depth' and x['downstream']=='bedtools unionbedg' and x['check']!='REJECT_FORMAT_MISMATCH' for x in workflows)
    assert any(x['upstream']=='samtools view' and x['downstream']=='samtools sort' and x['in_scenario']=='general_bam_coordinate_sort' for x in workflows)
    assert any(x['upstream']=='samtools sort' and x['downstream']=='bedtools genomecov' and x['check']=='CANDIDATE_ONLY' for x in workflows)
    assert any(x['upstream']=='bwa mem' and x['downstream']=='samtools view' and x['out_scenario']=='single_end' and x['in_scenario']=='sam_to_bam_conversion' and x['check']=='CANDIDATE_ONLY' for x in workflows)
    assert any(x['upstream']=='bedtools genomecov' and x['downstream']=='bedtools unionbedg' and x['check']=='NEEDS_MULTIPLE_INPUTS' for x in workflows)
    return True


def choose_cached(cache_dir:Path, prefix:str):
    opts=[]
    for p in cache_dir.glob('*.json'):
        try:
            d=read_json(p)
        except (OSError,ValueError):continue
        if d.get('metadata',{}).get('file') == f'{prefix}_skill.md':
            opts.append((p.stat().st_mtime_ns,p,d))
    if not opts:
        raise FileNotFoundError(f'缓存抽取 JSON 缺失: {prefix}_skill.md。请先通过原项目抽取并保存缓存。')
    _,p,d=max(opts,key=lambda x:x[0])
    return p,d


def main():
    ap=argparse.ArgumentParser(description='独立重建 BioSkillKG v5.4，零 LLM 调用，不覆盖旧图。')
    ap.add_argument('--md-dir', type=Path, required=True, help='只需要包含五份 *_skill.md 的文件夹')
    ap.add_argument('--extract-dir',type=Path,default=Path('data/bio_skill_kg/extracted_skills'))
    ap.add_argument('--out-dir',type=Path,default=Path('data/bio_skill_kg/v54_clean'))
    ap.add_argument('--source-graph',type=Path,default=None,help='可选：核对原图 metadata.documents 的 MD SHA256，绝不合并')
    args=ap.parse_args()
    if args.out_dir.resolve()==args.md_dir.resolve() or args.out_dir.resolve()==args.extract_dir.resolve():
        ap.error('输出目录不得覆盖输入目录')
    if (args.out_dir/'bio_skill_graph.json').exists():
        ap.error('目标图谱已经存在。为安全起见请换一个新 --out-dir。')
    docs=[]; ds={}; extracts={}; src={}
    expected_hashes={}
    if args.source_graph and args.source_graph.exists():
        expected_hashes=read_json(args.source_graph).get('metadata',{}).get('documents',{})
    for prefix in SKILLS:
        p=args.md_dir/f'{prefix}_skill.md'
        if not p.is_file():ap.error('缺少文件: '+str(p))
        body=p.read_text(encoding='utf-8-sig')
        sha=hashlib.sha256(body.encode('utf-8')).hexdigest()
        if expected_hashes and expected_hashes.get(p.name) != sha:
            ap.error(f'{p.name} 与原图 SHA256 不匹配；缓存可能过期，先重新抽取或检查文件')
        cp, d=choose_cached(args.extract_dir,prefix)
        if not d.get('operations'):ap.error(f'{cp} 没有 Operation')
        ds[prefix]=body
        docs.append(SimpleNamespace(file_path=str(p),content=body))
        extracts[prefix]=copy.deepcopy(d)
        src[prefix]={'md_path':str(p),'md_sha256':sha,'cache_path':str(cp),'prompt_version':d.get('metadata',{}).get('prompt_version')}
    ontology=copy.deepcopy(load_data_type_ontology())
    changes=curated_overlays(ds,extracts,ontology)
    graph=build_graph_from_extractions(docs,[extracts[x] for x in SKILLS],ontology=ontology)
    # Preserve standard Neo4j importer schema. This object is BUILT FRESH, never merged.
    graph['metadata']['build_variant']='v5.4-clean-from-five-MDs-cached-extractions'
    graph['metadata']['manual_review_sources']=SOURCES
    workflows=graph_workflows(graph)
    verify(graph,workflows)

    args.out_dir.mkdir(parents=True,exist_ok=True)
    for prefix in SKILLS:
        write_json(args.out_dir/'verified_extractions'/f'{prefix}_skill_v54.json',extracts[prefix])
    write_json(args.out_dir/'bio_skill_graph.json',graph)
    write_json(args.out_dir/'bio_skill_review.json',graph['review'])
    report={'build':'v5.4','llm_api_calls':0,'fresh':True,'old_graph_merged':False,
            'graph':summary(graph),'sources':src,'curated_changes':changes,
            'candidate_workflow_count':len(workflows),
            'workflow_checks':dict(collections.Counter(x['check'] for x in workflows)),
            'notes':['同一 Operation 的场景不可混成一次调用',
                     '工作流候选不等于可执行：需检查参数、输入数量、排序/索引状态',
                     'unionbedg 的原 MD 使用 .bed 后缀，已按官方要求解释为 BEDGRAPH 内容；建议修订 MD']}
    write_json(args.out_dir/'build_and_validation_report.json',report)
    with (args.out_dir/'workflow_candidates.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(workflows[0]) if workflows else ['upstream','downstream','check'])
        w.writeheader();w.writerows(workflows)
    print('PASS: fresh v5.4 build from five MD/cached extracts (LLM calls = 0)')
    print('Summary:',json.dumps(summary(graph),ensure_ascii=False))
    print('Workflow check:',report['workflow_checks'])
    print('Output:',args.out_dir)

if __name__=='__main__': main()
