"""Tool-agnostic semantic facets and candidate identity for BioSkillKG.

A format is never a sufficient reason to infer an exact semantic type. The
facets below describe source evidence and *cannot* grant tool-chain
compatibility to a candidate or a weakened base type.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


def norm(value: Any) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or ''))).strip().casefold()


def canonical_format(fmt: str) -> str:
    """Normalize extension spelling consistently across documents/candidate IDs."""
    token = str(fmt or '').strip().upper().lstrip('.').replace('.', '_').replace('-', '_')
    return {'FQ':'FASTQ', 'FQ_GZ':'FASTQ_GZ', 'FASTQGZ':'FASTQ_GZ',
            'FASTQ_GZ':'FASTQ_GZ', 'VCF_GZ':'VCF_GZ'}.get(token, token)


def semantic_facets(name: str, description: str = '', formats: list[str] | None = None) -> dict:
    text = norm(f'{name} {description}')
    fmt = sorted({canonical_format(x) for x in (formats or []) if str(x).strip()})
    result: dict = {'formats': fmt}
    # Observe explicit negative evidence before generic substrings (unsorted contains sorted).
    if re.search(r'未(?:经|按[^\s，；。]{0,8})?排序|未排序|unsorted|not\s+sorted', text):
        result['sorting_state'] = 'unsorted'
    elif re.search(r'已排序|排序后|排序的|按[^\s，；。]{0,10}排序|coordinate.sorted|sorted', text):
        result['sorting_state'] = 'sorted'
    # These are distinct lifecycle conditions, not synonyms for sorting.
    processing = []
    tokens = (
        ('duplicate_marked', ('标记重复', '重复标记', 'marked duplicate', 'markduplicates', 'dedup')),
        ('read_groups_added', ('添加读取组', '替换读取组', 'read group added', 'read groups added')),
        ('filtered', ('已过滤', '过滤后', 'filtered')),
        ('merged', ('合并后的', '合并后', 'merged')),
        ('indexed', ('已索引', 'indexed')),
    )
    for key, patterns in tokens:
        if any(token in text for token in patterns):
            processing.append(key)
    if processing:
        result['processing_states'] = processing
    if set(fmt) <= {'FASTQ', 'FASTQ_GZ'} and fmt:
        if any(x in text for x in ('处理后', '质控后', '过滤后', '修剪后', '去接头',
                                    'clean reads', 'cleaned reads', 'trimmed reads',
                                    'preprocessed reads', 'filtered reads')):
            result['read_stage'] = 'processed'
    return result


def candidate_id(name: str, description: str, formats: list[str], facets: dict | None = None) -> str:
    """Stable semantic candidate identity, independent of source/operation/wording in descriptions.

    Facets differentiate genuinely different states; port roles and evidence text
    do not split equivalent types. Still NOT an approval or compatibility edge.
    """
    observed = facets if facets is not None else semantic_facets(name, description, formats)
    stable_facets = {key: value for key, value in observed.items()
                     if key in ('sorting_state', 'processing_states', 'read_stage') and value}
    data = {'name': norm(name),
            'formats': sorted({canonical_format(x) for x in formats}),
            'facets': stable_facets}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return 'candidate:' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def resolve_sequence_read_type(name: str, description: str, formats: list[str], ontology: dict) -> tuple[str | None, bool]:
    """General FASTQ semantic-family resolution, with explicit processing states.

    Return (curated key, belongs_to_family). Unknown modifier remains pending,
    never weakened to generic reads purely on a file extension.
    """
    fmt = {canonical_format(x) for x in formats}
    if not fmt or not fmt <= {'FASTQ', 'FASTQ_GZ'}:
        return None, False
    text = norm(f'{name} {description}')
    reads = any(t in text for t in ('测序', '读段', 'reads', 'fastq', 'fq.gz', 'read1', 'read2', 'r1', 'r2'))
    processed = any(t in text for t in ('处理后序列', '处理后的', '质控后', '过滤后', '修剪后', '去接头',
                                      'clean reads', 'cleaned reads', 'trimmed reads',
                                      'preprocessed reads', 'filtered reads'))
    if not (reads or processed):
        return None, False
    if processed:
        return ('processed_short_reads' if 'processed_short_reads' in ontology else None), True
    # No evidence of processing; plain FASTQ reads can use the general read type.
    return ('short_reads' if 'short_reads' in ontology else None), True


def resolve_quality_control_type(name: str, description: str, formats: list[str], ontology: dict) -> str | None:
    """Evidence-based, tool-agnostic QC report vs machine-readable QC data."""
    fmt = {canonical_format(x) for x in formats}
    text = norm(f'{name} {description}')
    if not any(t in text for t in ('质控', '质量控制', 'quality control', 'qc report', 'qc metrics')):
        return None
    if fmt == {'HTML'} and any(t in text for t in ('报告', 'report', '图表')):
        return 'quality_control_report' if 'quality_control_report' in ontology else None
    if fmt == {'JSON'} and any(t in text for t in ('数据', '统计', '指标', 'metrics', 'statistics', 'report')):
        return 'quality_control_metrics' if 'quality_control_metrics' in ontology else None
    return None


def type_hint(facets: dict, name: str, ontology: dict) -> str | None:
    # Hints are not links. Format alone is not enough: require alignment meaning.
    text = norm(name)
    if 'BAM' in facets.get('formats', []) and any(x in text for x in ('bam', '比对', 'alignment')):
        return 'aligned_reads_bam' if 'aligned_reads_bam' in ontology else None
    return None


def constrained_alignment_key(name: str, description: str, formats: list[str], ontology: dict) -> tuple[str | None, bool]:
    """Return (curated subtype, novel state). Never weaken requirements to BAM."""
    facets = semantic_facets(name, description, formats)
    if 'BAM' not in facets['formats']:
        return None, False
    if 'SAM' in facets['formats'] or 'CRAM' in facets['formats']:
        # Mixed file formats cannot safely inherit BAM-specific constraints.
        return None, bool(facets.get('sorting_state') or facets.get('processing_states'))
    text = norm(f'{name} {description}')
    if not any(x in text for x in ('bam', '比对', 'alignment')):
        return None, False
    processes = set(facets.get('processing_states', []))
    # Specific processing states are not interchangeable with raw BAM or
    # filtered BAM. Even if sorted, a composite state needs independent review.
    novel = processes - {'filtered'}
    if novel:
        return None, True
    if 'filtered' in processes:
        if facets.get('sorting_state'):
            # A composite type requires a verified subtype, not filtered BAM alone.
            return None, True
        return ('aligned_reads_bam_filtered' if 'aligned_reads_bam_filtered' in ontology else None), True
    sort = facets.get('sorting_state')
    if sort:
        key = 'aligned_reads_bam_sorted' if sort == 'sorted' else 'aligned_reads_bam_unsorted'
        return (key if key in ontology else None), True
    return None, False
