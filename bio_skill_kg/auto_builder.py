"""Build BioSkillKG from LLM-extracted, evidence-checked Skill knowledge.

The five-label BioSkillKG schema and incremental Graph merger are retained.
LLM output is treated as candidate data; this module only creates edges for
claims that passed exact evidence-quote validation in llm_extractor.py.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from .builder import (
    Graph, canonical_tool_name, collect_optional_reference_sections,
    collect_resources, field, load_aliases, numbered_section,
)
from .validator import locate_evidence, resolve_format_evidence
from .semantic_normalization import (semantic_facets, candidate_id, type_hint, constrained_alignment_key,
                                     resolve_sequence_read_type, resolve_quality_control_type)

BASE = Path(__file__).resolve().parent
NORMALIZATION_VERSION = "bioskillkg-semantic-normalization-v5.6-semantic-family-and-scenarios"


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip().casefold()


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_.-")
    return value or "unknown"


def load_data_type_ontology(path: str | Path | None = None) -> dict:
    path = Path(path) if path else BASE / "data_types.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("data_types.json 必须是 JSON object")
    return raw



def load_ontology_aliases(path: str | Path | None = None) -> dict[str, str]:
    path = Path(path) if path else BASE / "ontology_aliases.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {_norm(k): str(v) for k, v in raw.items()}


def load_file_format_ontology(path: str | Path | None = None) -> dict:
    path = Path(path) if path else BASE / "file_formats.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("file_formats.json 必须是 JSON object")
    return raw


def _format_token(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().upper()
    value = value.lstrip(".")
    value = re.sub(r"\\s+", "_", value)
    value = re.sub(r"[^A-Z0-9_.+-]+", "_", value)
    value = re.sub(r"\\.+", "_", value)
    return value.strip("_.")


def _format_alias_map(file_formats: dict | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    for canonical, item in (file_formats or {}).items():
        canonical_key = _format_token(canonical)
        result[canonical_key] = canonical_key
        if isinstance(item, dict):
            for alias in item.get("aliases", []):
                result[_format_token(alias)] = canonical_key
    # Common extension aliases are explicit and deterministic.
    result.update({
        "FA": "FASTA",
        "FQ": "FASTQ",
        "FQ_GZ": "FASTQ_GZ",
        "FASTQ_GZ": "FASTQ_GZ",
        "VCF_GZ": "VCF_GZ",
        "GFF3": "GFF3",
    })
    return result


def _format_name(value: str, file_formats: dict | None = None) -> str:
    token = _format_token(value)
    return _format_alias_map(file_formats).get(token, token)


def _ontology_name_map(ontology: dict, aliases: dict[str, str]) -> dict[str, str]:
    result = dict(aliases)
    for key, item in ontology.items():
        result[_norm(key)] = key
        if isinstance(item, dict):
            if item.get("name"):
                result[_norm(item["name"])] = key
            for alias in item.get("aliases", []):
                result[_norm(alias)] = key
    return result


def _is_format_only_name(name: str, formats: list[str], file_formats: dict) -> bool:
    # Do not strip non-ASCII semantic words and mistake a long DataType name
    # like "已排序BAM比对结果" for the format-only token "BAM".
    raw_name = str(name or "").strip()
    if not raw_name or not raw_name.isascii():
        return False
    token = _format_name(raw_name, file_formats)
    known = set(_format_alias_map(file_formats).values())
    listed = {_format_name(x, file_formats) for x in (formats or [])}
    return token in known or (bool(listed) and token in listed)


def _infer_semantic_keys_from_format(name: str, description: str, formats: list[str],
                                     ontology: dict, file_formats: dict) -> list[str]:
    """Infer a conceptual DataType only when source wording identifies it."""
    text = _norm(f"{name} {description}")
    fmt = _format_name(name, file_formats)
    all_formats = {_format_name(x, file_formats) for x in (formats or [])}
    if fmt not in all_formats and fmt:
        all_formats.add(fmt)

    # Specific processed outputs must be tested before generic terms.
    if any(x in text for x in ("过滤后的注释", "过滤后注释", "multianno_filtered")):
        return ["filtered_annotated_variants"]
    if any(x in text for x in ("注释统计", "multianno_summary")):
        return ["annotation_statistics"]
    if any(x in text for x in ("详细的覆盖度统计", "详细覆盖度统计", "coverage_detail")):
        return ["detailed_coverage_statistics"]
    if any(x in text for x in ("多样本覆盖度", "coverage_multi", "merged_coverage")):
        return ["multi_sample_coverage_result"]
    if any(x in text for x in ("带交集计数", "intersection_count")):
        return ["counted_intersection_regions"]
    if any(x in text for x in ("原始区域平均值", "merged_mean")):
        return ["mean_aggregated_merged_regions"]
    if any(x in text for x in ("原始区域计数", "merged_count")):
        return ["count_aggregated_merged_regions"]
    if any(x in text for x in ("差异区域", "difference.bed")):
        return ["difference_regions"]
    if any(x in text for x in ("单个样本的vcf", "单样本变异", "single_sample")):
        return ["single_sample_variant_calls"]
    if any(x in text for x in ("样本子集", "特定样本的vcf", "子集变异")):
        return ["subset_variant_calls"]
    if any(x in text for x in ("注释后的vcf", "注释vcf", "注释结果", "多数据库注释", "注释后的变异")):
        return ["annotated_variants"]
    if any(x in text for x in ("过滤后", "过滤结果", "filtered")):
        return ["filtered_variant_calls"]
    if any(x in text for x in ("合并后的vcf", "合并后的变异", "merged")):
        return ["merged_variant_calls"]
    if any(x in text for x in ("多样本变异", "多样本vcf")):
        return ["multi_sample_variant_calls"]
    if any(x in text for x in ("变异统计", "variants.stats")):
        return ["variant_statistics"]
    if any(x in text for x in ("运行日志", "日志文件", "bedtools.log", "execution log")):
        return ["execution_log"]
    if any(x in text for x in ("基因型检查", "genotype_check")):
        return ["genotype_check_results"]
    if any(x in text for x in ("样本列表", "samples.txt")):
        keys = ["sample_list"]
        if "区域列表" in text:
            keys.append("region_list")
        return keys
    if "区域列表" in text:
        return ["region_list"]
    if any(x in text for x in ("annovar输入", "annovar input")):
        return ["annovar_input_data"]
    if any(x in text for x in ("质量分布图", "depth_distribution", "图表")) and "pdf" in text:
        return ["quality_distribution_plot"]
    if any(x in text for x in ("覆盖度结果", "覆盖度统计")):
        return ["coverage_result"]
    if any(x in text for x in ("高覆盖度区域", "覆盖度高的区域")):
        return ["high_coverage_regions"]
    if any(x in text for x in ("区域交集", "两个区域文件的交集", "intersection.bed")):
        return ["intersected_regions"]
    if any(x in text for x in ("合并后的区域", "合并重叠或相邻的区域", "merged.bed")):
        return ["merged_regions"]
    if any(x in text for x in ("基因组区域", "bed格式的覆盖文件")) and ("BED" in all_formats or fmt == "BED"):
        return ["genomic_regions"]
    if any(x in text for x in ("基因注释", "gff格式")) and ({"GFF", "GFF3"} & all_formats or fmt in {"GFF", "GFF3"}):
        return ["gene_annotations"]
    if any(x in text for x in ("信号文件", "信号轨道", "信号数据", "wig", "bedgraph")) and ({"WIG", "BEDGRAPH"} & all_formats or fmt in {"WIG", "BEDGRAPH"}):
        return ["signal_tracks"]
    if any(x in text for x in ("比对结果", "比对文件", "alignment")):
        keys = []
        if "SAM" in all_formats or fmt == "SAM":
            keys.append("aligned_reads_sam")
        if "BAM" in all_formats or fmt == "BAM":
            keys.append("aligned_reads_bam")
        if keys:
            return keys
    if any(x in text for x in ("参考基因组", "reference genome")) and ({"FASTA", "FA"} & all_formats or fmt in {"FASTA", "FA"}):
        return ["reference_genome"]
    if any(x in text for x in ("测序数据", "测序读段", "测序读长", "fastq")) and ({"FASTQ", "FASTQ_GZ"} & all_formats or fmt in {"FASTQ", "FASTQ_GZ"}):
        return ["short_reads"]
    if any(x in text for x in ("变异", "vcf", "bcf")) and ({"VCF", "VCF_GZ", "BCF"} & all_formats or fmt in {"VCF", "VCF_GZ", "BCF"}):
        return ["variant_calls"]
    if fmt == "AVCF" and "注释" in text:
        return ["annotated_variants"]
    if any(x in text for x in ("工具统计结果", "一般统计结果", "tool statistics")):
        return ["tool_statistics"]
    return []


def _resolve_data_type_keys(name: str, description: str, formats: list[str],
                            ontology: dict, ontology_aliases: dict[str, str],
                            file_formats: dict) -> tuple[list[str], bool]:
    """Resolve only to curated DataType IDs; unknown semantic concepts are quarantined."""
    name_norm = _norm(name)
    is_format = _is_format_only_name(name, formats, file_formats)
    # General semantic families: respect processing state rather than downgrading
    # a processed FASTQ to a raw read simply because the extension matches.
    # Bare format labels still follow the conservative format-only branch below.
    if not is_format:
        read_key, is_read = resolve_sequence_read_type(name, description, formats, ontology)
        if is_read:
            return ([read_key] if read_key else []), False
        qc_key = resolve_quality_control_type(name, description, formats, ontology)
        if qc_key:
            return [qc_key], False
    # Resolve documented alignment states BEFORE generic ontology aliases.
    # This prevents e.g. "序列比对结果" plus "已排序 BAM" becoming generic BAM.
    subtype, constrained = constrained_alignment_key(name, description, formats, ontology)
    if constrained:
        explicit_key = _ontology_name_map(ontology, ontology_aliases).get(name_norm)
        if explicit_key in ontology:
            approved = ontology[explicit_key]
            observed = semantic_facets(name, description, formats)
            canonical = semantic_facets(approved.get("name", ""),
                                         approved.get("description", ""),
                                         approved.get("formats", []))
            required_processing = set(observed.get("processing_states", []))
            approved_processing = set(canonical.get("processing_states", []))
            sort_ok = (not observed.get("sorting_state") or
                       observed["sorting_state"] == canonical.get("sorting_state"))
            allowed_formats = {_format_name(x, file_formats) for x in approved.get("formats", [])}
            seen_formats = {_format_name(x, file_formats) for x in formats}
            if required_processing <= approved_processing and sort_ok and (not allowed_formats or seen_formats <= allowed_formats):
                return [explicit_key], is_format
        return ([subtype] if subtype else []), is_format

    if is_format:
        # A format token alone does not establish a semantic DataType.  Inspect
        # DESCRIPTION (not the format-name itself) for actual content meaning.
        desc = _norm(description)
        concept_clues = ("测序", "读段", "比对", "变异", "基因组", "区域", "覆盖", "注释", "参考序列",
                         "信号", "索引", "统计", "样本列表", "日志", "alignment",
                         "sequencing", "reads", "variant", "genomic", "coverage", "annotation")
        if not any(clue in desc for clue in concept_clues):
            return [], True
        inferred = _infer_semantic_keys_from_format(name, description, formats, ontology, file_formats)
        return [k for k in inferred if k in ontology], True

    semantic_text = _norm(f"{name} {description}")
    # Disambiguate generic statistics/output labels by their actual content.
    if any(x in semantic_text for x in ("multianno_summary", "注释统计信息", "注释统计结果")):
        return (["annotation_statistics"], False) if "annotation_statistics" in ontology else ([], False)
    if any(x in semantic_text for x in ("coverage_detail", "详细的覆盖度统计", "详细覆盖度统计")):
        return (["detailed_coverage_statistics"], False) if "detailed_coverage_statistics" in ontology else ([], False)
    if any(x in semantic_text for x in ("coverage_multi", "多样本覆盖度结果")):
        return (["multi_sample_coverage_result"], False) if "multi_sample_coverage_result" in ontology else ([], False)
    if any(x in semantic_text for x in ("variants.stats", "变异统计")):
        return (["variant_statistics"], False) if "variant_statistics" in ontology else ([], False)
    if any(x in semantic_text for x in ("过滤后的注释", "过滤注释结果", "multianno_filtered")):
        return (["filtered_annotated_variants"], False) if "filtered_annotated_variants" in ontology else ([], False)
    if any(x in semantic_text for x in ("过滤后的snv", "过滤后的变异", "过滤后变异", "filtered_variant")):
        return (["filtered_variant_calls"], False) if "filtered_variant_calls" in ontology else ([], False)
    if any(x in semantic_text for x in ("合并后的vcf", "合并后的变异", "merged_variant")):
        return (["merged_variant_calls"], False) if "merged_variant_calls" in ontology else ([], False)
    if any(x in semantic_text for x in ("注释后的vcf", "注释后的变异", "注释结果")):
        return (["annotated_variants"], False) if "annotated_variants" in ontology else ([], False)
    if any(x in semantic_text for x in ("样本子集", "特定样本的vcf", "子集变异")):
        return (["subset_variant_calls"], False) if "subset_variant_calls" in ontology else ([], False)
    if any(x in semantic_text for x in ("单个样本的vcf", "单样本变异", "single_sample")):
        return (["single_sample_variant_calls"], False) if "single_sample_variant_calls" in ontology else ([], False)
    if any(x in semantic_text for x in ("带交集计数", "intersection_count")):
        return (["counted_intersection_regions"], False) if "counted_intersection_regions" in ontology else ([], False)
    if any(x in semantic_text for x in ("原始区域平均值", "merged_mean")):
        return (["mean_aggregated_merged_regions"], False) if "mean_aggregated_merged_regions" in ontology else ([], False)
    if any(x in semantic_text for x in ("原始区域计数", "merged_count")):
        return (["count_aggregated_merged_regions"], False) if "count_aggregated_merged_regions" in ontology else ([], False)
    if any(x in semantic_text for x in ("差异区域", "difference.bed")):
        return (["difference_regions"], False) if "difference_regions" in ontology else ([], False)
    if any(x in semantic_text for x in ("运行日志", "日志文件", "bedtools.log", "execution log")):
        return (["execution_log"], False) if "execution_log" in ontology else ([], False)

    name_map = _ontology_name_map(ontology, ontology_aliases)
    key = name_map.get(name_norm)
    if key and key in ontology:
        fmts = {_format_name(x, file_formats) for x in (formats or [])}
        # An alias must not override contradictory documented file formats.
        # For example, a future SAM/CRAM "排序后的序列比对结果"
        # must NOT silently resolve to the BAM-only sorted type.
        allowed = {_format_name(x, file_formats) for x in ontology[key].get("formats", [])}
        if fmts and allowed and not fmts <= allowed:
            return [], False
        if key == "aligned_reads":
            children = []
            if "SAM" in fmts:
                children.append("aligned_reads_sam")
            if "BAM" in fmts:
                children.append("aligned_reads_bam")
            if "BED" in fmts:
                children.append("genomic_regions")
            if children:
                return children, False
        return [key], False

    # A vague "statistics"/"merge"/"filter" label is not enough to create a
    # generic node. Only an explicitly named generic tool statistic is retained.
    if "统计" in semantic_text or "statistics" in semantic_text:
        explicit_generic = any(x in semantic_text for x in ("工具统计结果", "一般统计结果", "tool statistics"))
        if explicit_generic and "tool_statistics" in ontology:
            return ["tool_statistics"], False
        return [], False

    # Conservative fallback for an otherwise unknown BAM alignment-state term.
    # Only use this when the extracted record explicitly says BAM, and the
    # source meaning is unambiguous.  Other unknown types remain quarantined.
    if "BAM" in {_format_name(x, file_formats) for x in (formats or [])}:
        if any(x in semantic_text for x in ("比对", "bam", "alignment")):
            if any(x in semantic_text for x in ("未排序", "unsorted")):
                return (["aligned_reads_bam_unsorted"], False) if "aligned_reads_bam_unsorted" in ontology else ([], False)
            if any(x in semantic_text for x in ("过滤后", "已过滤", "filtered")):
                return (["aligned_reads_bam_filtered"], False) if "aligned_reads_bam_filtered" in ontology else ([], False)
            if any(x in semantic_text for x in ("排序后", "已排序", "sorted")):
                return (["aligned_reads_bam_sorted"], False) if "aligned_reads_bam_sorted" in ontology else ([], False)
    # Unknown semantic names are not promoted to formal nodes automatically.
    return [], False


def _add_format_node(graph: Graph, fmt: str, source_file: str, source_section: str,
                     evidence_quote: str, file_formats: dict, status: str) -> str:
    fmt_name = _format_name(fmt, file_formats)
    if not fmt_name:
        return ""
    fmt_meta = file_formats.get(fmt_name, {})
    graph.node(f"format:{fmt_name}", "FileFormat", name=fmt_name,
               description=fmt_meta.get("description"),
               source_file=source_file, source_section=source_section,
               evidence_quote=evidence_quote)
    return f"format:{fmt_name}"


def _add_data_type(graph: Graph, name: str, formats: list[str], source_file: str,
                   source_section: str, evidence_quote: str, ontology: dict,
                   ontology_aliases: dict[str, str], description: str = "",
                   parent_name: str | None = None, status: str = "llm_extracted_evidence_checked",
                   file_formats: dict | None = None,
                   format_evidence: list[dict] | None = None,
                   source_text: str = "") -> list[str]:
    """Add curated semantic DataTypes with format-specific source evidence.

    Unknown concepts are review candidates, never auto-promoted to formal nodes.
    A HAS_FORMAT edge is created only when that exact format has source evidence.
    """
    file_formats = file_formats if file_formats is not None else load_file_format_ontology()
    formats = formats if isinstance(formats, list) else []
    resolved, name_is_format = _resolve_data_type_keys(
        name, description, formats, ontology, ontology_aliases, file_formats
    )

    effective_formats = list(formats)
    if not effective_formats and name_is_format:
        effective_formats = [name]

    evidence_record = {
        "name": name,
        "description": description,
        "evidence_quote": evidence_quote,
        "format_evidence": format_evidence or [],
    }
    evidence_text = source_text or evidence_quote
    verified_formats, per_format_evidence = resolve_format_evidence(
        evidence_record, evidence_text, effective_formats
    )
    evidence_by_format = {
        _format_name(x.get("format", ""), file_formats): x.get("evidence_quote", "")
        for x in per_format_evidence
    }

    # Report every proposed format that could not be grounded independently.
    missing_formats = [
        fmt for fmt in effective_formats
        if _format_name(fmt, file_formats) not in evidence_by_format
    ]
    for fmt in missing_formats:
        graph.review.append({
            "file": source_file, "section": source_section,
            "reason": f"DataType {name} 的格式 {fmt} 缺少独立、可验证的格式证据；未创建 HAS_FORMAT 关系",
            "candidate_name": name,
            "evidence_quote": evidence_quote,
        })

    # Format-only records can create FileFormat nodes, but not DataType nodes
    # unless their description identifies a semantic content concept.
    if not resolved:
        for fmt in verified_formats:
            fmt_quote = evidence_by_format.get(_format_name(fmt, file_formats), "")
            _add_format_node(graph, str(fmt), source_file, source_section,
                             fmt_quote, file_formats, status)
        desc_norm = _norm(description)
        is_format_only_statement = any(
            x in desc_norm for x in ("格式", "file format", "可导出", "支持")
        )
        if name_is_format:
            if description and not is_format_only_statement:
                graph.review.append({
                    "file": source_file, "section": source_section,
                    "reason": f"识别到文件格式 {name}，但无法从描述可靠确定 DataType；仅保留 FileFormat",
                    "evidence_quote": evidence_quote,
                })
        else:
            graph.review.append({
                "file": source_file, "section": source_section,
                "reason": "未匹配到已审核的 DataType 规范实体或别名；已隔离为待审核候选，未创建正式节点",
                "candidate_name": name,
                "candidate_description": description,
                "candidate_formats": verified_formats,
                "evidence_quote": evidence_quote,
            })
        return []

    output_ids: list[str] = []
    for key in resolved:
        item = ontology.get(key, {})
        canonical_name = item.get("name", name)
        canonical_description = item.get("description") or description or None
        node_id = f"data:{key}"
        graph.node(
            node_id, "DataType", name=canonical_name,
            description=canonical_description,
            description_claim=description or canonical_description,
            source_file=source_file, source_section=source_section,
            evidence_quote=evidence_quote,
        )
        output_ids.append(node_id)

        selected_formats = list(verified_formats)
        # Alignment-family records are split into the appropriate format-specific
        # child. BED remains genomic intervals, not an alignment record.
        if key == "aligned_reads_sam":
            selected_formats = [x for x in selected_formats if _format_name(x, file_formats) == "SAM"]
        elif key == "aligned_reads_bam":
            selected_formats = [x for x in selected_formats if _format_name(x, file_formats) == "BAM"]
        elif key == "genomic_regions" and any(
            _format_name(x, file_formats) == "BED" for x in selected_formats
        ):
            selected_formats = [x for x in selected_formats if _format_name(x, file_formats) == "BED"]

        for fmt in selected_formats:
            fmt_key = _format_name(str(fmt), file_formats)
            fmt_quote = evidence_by_format.get(fmt_key, "")
            if not fmt_quote:
                continue
            fmt_section = source_section
            if source_text and fmt_quote:
                fmt_section, _, _ = locate_evidence(source_text, fmt_quote, source_section)
            # Retain the provenance of each format claim on the DataType as well
            # as on its HAS_FORMAT edge; formats may be documented in different sections.
            graph.node(
                node_id, "DataType", name=canonical_name,
                description=canonical_description,
                description_claim=description or canonical_description,
                source_file=source_file, source_section=fmt_section,
                evidence_quote=fmt_quote,
            )
            fmt_id = _add_format_node(
                graph, str(fmt), source_file, fmt_section,
                fmt_quote, file_formats, status,
            )
            if fmt_id:
                graph.edge(
                    node_id, "HAS_FORMAT", fmt_id,
                    source_file, fmt_section,
                    status=status, evidence_quote=fmt_quote,
                )

        parent_key = item.get("parent")
        if parent_name:
            parent_resolved, _ = _resolve_data_type_keys(
                str(parent_name), "", [], ontology, ontology_aliases, file_formats
            )
            if parent_resolved:
                parent_key = parent_resolved[0]
            else:
                graph.review.append({
                    "file": source_file, "section": source_section,
                    "reason": f"DataType {name} 声明的父类型 {parent_name} 未匹配到本体，未创建父子关系",
                    "evidence_quote": evidence_quote,
                })
        if parent_key and parent_key in ontology:
            parent_meta = ontology[parent_key]
            parent_id = f"data:{parent_key}"
            graph.node(
                parent_id, "DataType", name=parent_meta.get("name", parent_key),
                description=parent_meta.get("description"),
                description_claim=parent_meta.get("description"),
                source_file="data_types.json", source_section="global_data_type_ontology",
                evidence_quote="",
            )
            graph.edge(node_id, "IS_SUBTYPE_OF", parent_id,
                       "data_types.json", "global_data_type_ontology",
                       status="curated_ontology", evidence_quote="")

    # Keep the alignment family node when concrete SAM/BAM child nodes are used.
    if any(k in {"aligned_reads_sam", "aligned_reads_bam"} for k in resolved):
        parent_meta = ontology.get("aligned_reads", {})
        parent_id = "data:aligned_reads"
        graph.node(parent_id, "DataType", name=parent_meta.get("name", "序列比对结果"),
                   description=parent_meta.get("description"),
                   description_claim=parent_meta.get("description"),
                   source_file="data_types.json", source_section="global_data_type_ontology",
                   evidence_quote="")
        for key, child_id in zip(resolved, output_ids):
            if key in {"aligned_reads_sam", "aligned_reads_bam"}:
                graph.edge(child_id, "IS_SUBTYPE_OF", parent_id,
                           "data_types.json", "global_data_type_ontology",
                           status="curated_ontology", evidence_quote="")
    return output_ids


def _record_source(record: dict, fallback_file: str, fallback_section: str = "",
                   source_text: str = "") -> tuple[str, str, str]:
    file_name = str(record.get("_source_file") or fallback_file)
    section = str(record.get("_source_section") or fallback_section)
    quote = str(record.get("evidence_quote") or "").strip()
    if source_text and quote:
        section_is_precise = section.count(" / ") <= 4
        line_hint = record.get("_start_line") if section_is_precise else None
        located_section, line_start, line_end = locate_evidence(
            source_text, quote, section, line_hint=line_hint
        )
        if located_section:
            section = located_section
        if line_start is not None:
            record["_source_line_start"] = line_start
            record["_source_line_end"] = line_end
    # Older extraction JSON may contain a concatenation of every section in a
    # chunk. If exact quote lookup failed, avoid preserving the entire heading list.
    if " / " in section and section.count(" / ") > 4:
        section = section.split(" / ")[0]
    return file_name, section, quote


def _public_record(record: dict) -> dict:
    """Remove internal chunk bookkeeping while keeping source evidence."""
    return {k: v for k, v in record.items() if not str(k).startswith("_")}


def _relation_type(value: str) -> str | None:
    normalized = _norm(value).replace(" ", "_").replace("-", "_")
    aliases = {
        "recommended_before": "RECOMMENDED_BEFORE",
        "recommended_prerequisite": "RECOMMENDED_BEFORE",
        "documented_prerequisite": "DOCUMENTED_PREREQUISITE",
        "required_prerequisite": "DOCUMENTED_PREREQUISITE",
        "prerequisite": "DOCUMENTED_PREREQUISITE",
        "documented_downstream": "DOCUMENTED_DOWNSTREAM",
        "downstream": "DOCUMENTED_DOWNSTREAM",
        "partially_alternative_to": "PARTIALLY_ALTERNATIVE_TO",
        "alternative": "PARTIALLY_ALTERNATIVE_TO",
    }
    return aliases.get(normalized)


def _public_record(record: dict) -> dict:
    """Remove internal chunk bookkeeping while keeping source evidence."""
    return {k: v for k, v in record.items() if not str(k).startswith("_")}


def build_graph_from_extractions(documents: list, extractions: list[dict],
                                 aliases: dict[str, str] | None = None,
                                 ontology: dict | None = None,
                                 ontology_aliases: dict[str, str] | None = None,
                                 file_formats: dict | None = None) -> dict:
    """Create a normal BioSkillKG-v2 graph from validated LLM extraction results."""
    if len(documents) != len(extractions):
        raise ValueError("documents and extractions length mismatch")
    aliases = aliases if aliases is not None else load_aliases()
    ontology = ontology if ontology is not None else load_data_type_ontology()
    ontology_aliases = ontology_aliases if ontology_aliases is not None else load_ontology_aliases()
    file_formats = file_formats if file_formats is not None else load_file_format_ontology()
    graph = Graph(aliases=aliases)
    prepared: list[tuple[Any, dict, str, str]] = []

    # Pass 1: create all full Tool nodes before creating any cross-tool edges.
    for doc, extraction in zip(documents, extractions):
        source = Path(doc.file_path).name
        llm_tool = extraction.get("tool", {}) if isinstance(extraction.get("tool"), dict) else {}
        raw_name = field(doc.content, "工具名称") or str(llm_tool.get("name") or "").strip()
        if not raw_name:
            graph.review.append({"file": source, "reason": "MD 和 LLM 抽取结果均缺少工具名称，跳过该文档"})
            continue
        key = canonical_tool_name(raw_name, aliases)
        fingerprint = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()
        graph.documents[source] = fingerprint
        props = {
            "name": raw_name,
            "canonical_name": key,
            "version": field(doc.content, "工具版本") or llm_tool.get("version"),
            "category": field(doc.content, "工具分类") or llm_tool.get("category"),
            "description": field(doc.content, "工具描述") or llm_tool.get("description"),
            "source_url": field(doc.content, "工具来源") or llm_tool.get("source_url"),
            "docker_image": field(doc.content, "Docker镜像") or llm_tool.get("docker_image"),
            "source_file": source,
            "stub": False,
            "aliases": [raw_name],
        }
        props.update(collect_resources(doc.content))
        props.update(collect_optional_reference_sections(doc.content))
        resource_records = extraction.get("resources", [])
        if resource_records:
            props["resource_requirements_json"] = json.dumps([_public_record(x) for x in resource_records], ensure_ascii=False)
        tool_parameters = extraction.get("tool_parameters", [])
        if tool_parameters:
            props["parameters_json"] = json.dumps([_public_record(x) for x in tool_parameters], ensure_ascii=False)
            props["parameter_names"] = [str(x.get("name")) for x in tool_parameters if x.get("name")]
            props["parameter_flags"] = [str(x.get("flag")) for x in tool_parameters if x.get("flag")]
        qcs = extraction.get("quality_controls", [])
        if qcs:
            props["quality_controls_json"] = json.dumps([_public_record(x) for x in qcs], ensure_ascii=False)
            props["quality_control_names"] = [str(x.get("name")) for x in qcs if x.get("name")]
        graph.node(f"tool:{key}", "Tool", **props)
        prepared.append((doc, extraction, key, source))
        for issue in extraction.get("review", []):
            graph.review.append({"file": source, **issue})

    # Pass 2: build DataType vocabulary and operation-level subgraphs.
    for doc, extraction, tool_key, source in prepared:
        tool_id = f"tool:{tool_key}"

        for item in extraction.get("data_types", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            file_name, section, quote = _record_source(item, source, source_text=doc.content)
            _add_data_type(graph, str(item["name"]), item.get("formats", []) or [],
                           file_name, section, quote, ontology, ontology_aliases,
                           description=str(item.get("description") or ""),
                           parent_name=item.get("parent"), file_formats=file_formats,
                           format_evidence=item.get("format_evidence"), source_text=doc.content)

        for op in extraction.get("operations", []):
            if not isinstance(op, dict) or not str(op.get("name") or "").strip():
                graph.review.append({"file": source, "reason": "发现缺少名称的 Operation，未入图"})
                continue
            op_name = re.sub(r"\s+", " ", str(op["name"])).strip()
            file_name, section, quote = _record_source(op, source, source_text=doc.content)
            if not quote:
                graph.review.append({"file": source, "reason": f"Operation {op_name} 缺少证据，未入图"})
                continue
            op_key = _slug(op_name.replace(" ", "_"))
            op_id = f"op:{op_key}"
            params = op.get("parameters", []) if isinstance(op.get("parameters"), list) else []
            param_names = [str(p.get("name")) for p in params if isinstance(p, dict) and p.get("name")]
            param_flags = [str(p.get("flag")) for p in params if isinstance(p, dict) and p.get("flag")]
            min_files = op.get("min_input_files")
            if not isinstance(min_files, int) or min_files < 1:
                min_files = None
            graph.node(
                op_id, "Operation", name=op_name,
                description=op.get("description"),
                min_input_files=min_files,
                parameters_json=json.dumps([_public_record(x) for x in params], ensure_ascii=False) if params else None,
                parameter_names=param_names,
                parameter_flags=param_flags,
                source_file=file_name, source_section=section,
                evidence_quote=quote,
                validation_status="evidence_checked_needs_semantic_review",
            )
            graph.edge(tool_id, "HAS_OPERATION", op_id, file_name, section,
                       status="llm_extracted_evidence_checked", evidence_quote=quote)

            task_name = str(op.get("task_name") or "").strip()
            if task_name:
                task_id = f"task:{_slug(task_name)}"
                graph.node(task_id, "Task", name=task_name, source_file=file_name,
                           source_section=section, evidence_quote=quote)
                graph.edge(op_id, "PERFORMS", task_id, file_name, section,
                           status="llm_extracted_evidence_checked", evidence_quote=quote)
            else:
                graph.review.append({"file": source, "reason": f"Operation {op_name} 未抽取到明确 Task，已保留 Operation"})

            if not op.get("outputs"):
                graph.review.append({
                    "file": source, "section": section,
                    "operation": op_name,
                    "reason": "LLM 原始抽取未提供输出端口；请核对 MD 的输出定义/命令标准输出",
                    "evidence_quote": quote,
                })

            for rel_key, rel_type in [("inputs", "REQUIRES_INPUT"), ("outputs", "PRODUCES")]:
                records = op.get(rel_key, []) if isinstance(op.get(rel_key), list) else []
                port_specs: list[dict] = []
                unresolved_specs: list[dict] = []
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    data_name = str(record.get("data_type") or record.get("name") or "").strip()
                    if not data_name:
                        graph.review.append({"file": source, "reason": f"{op_name} 的 {rel_key} 缺少 data_type"})
                        continue
                    rfile, rsection, rquote = _record_source(record, file_name, section, source_text=doc.content)
                    if not rquote:
                        graph.review.append({"file": source, "reason": f"{op_name} 的数据项 {data_name} 缺少证据，跳过关系"})
                        continue
                    data_ids = _add_data_type(
                        graph, data_name, record.get("formats", []) or [], rfile, rsection,
                        rquote, ontology, ontology_aliases,
                        description=str(record.get("description") or ""),
                        file_formats=file_formats,
                        format_evidence=record.get("format_evidence"),
                        source_text=doc.content,
                    )
                    if not data_ids:
                        # Every evidence-checked port is preserved in the main
                        # specs list, even when it cannot be safely connected
                        # to an existing DataType. No REQUIRES_INPUT/PRODUCES
                        # relation is fabricated for pending candidates.
                        unresolved = _public_record(record)
                        unresolved["raw_data_type"] = data_name
                        unresolved["resolution_status"] = "pending_review"
                        unresolved["semantic_facets"] = semantic_facets(
                            data_name, str(record.get("description") or ""),
                            record.get("formats", []) or [],
                        )
                        unresolved["candidate_type_id"] = candidate_id(
                            data_name, str(record.get("description") or ""),
                            record.get("formats", []) or [], unresolved["semantic_facets"])
                        unresolved["suggested_parent_type_key"] = type_hint(
                            unresolved["semantic_facets"], data_name, ontology)
                        unresolved["source_files"] = [rfile] if rfile else []
                        unresolved["source_sections"] = [f"{rfile} §{rsection}"] if rfile and rsection else []
                        unresolved["evidence_quotes"] = list(dict.fromkeys(
                            [str(x) for x in (unresolved.get("evidence_quotes") or []) if x]
                            + [rquote]))
                        scenario_key = str(unresolved.get("scenario_id") or "default")
                        role_key = str(unresolved.get("role") or unresolved.get("flag") or data_name)
                        unresolved["port_id"] = f"{scenario_key}:{_slug(role_key)}:{unresolved['candidate_type_id']}"
                        unresolved_specs.append(unresolved)
                        port_specs.append(unresolved)
                        graph.review.append({
                            "file": rfile, "section": rsection,
                            "operation": op_name,
                            "direction": rel_key,
                            "candidate_name": data_name,
                            "reason": "Operation 输入输出端口未解析到规范 DataType，原始记录已保留",
                            "evidence_quote": rquote,
                        })
                    for data_id in data_ids:
                        graph.edge(op_id, rel_type, data_id, rfile, rsection,
                                   status="llm_extracted_evidence_checked", evidence_quote=rquote)
                        data_key = data_id.removeprefix("data:")
                        canonical_data = ontology.get(data_key, {}).get("name", data_name)
                        spec = _public_record(record)
                        spec["raw_data_type"] = data_name
                        spec["data_type"] = canonical_data
                        spec["data_type_key"] = data_key
                        spec["data_type_id"] = data_id
                        spec["resolution_status"] = "curated"
                        spec["semantic_facets"] = semantic_facets(
                            data_name, str(record.get("description") or ""),
                            record.get("formats", []) or [],
                        )
                        spec["source_files"] = [rfile] if rfile else []
                        spec["source_sections"] = [f"{rfile} §{rsection}"] if rfile and rsection else []
                        spec["evidence_quotes"] = list(dict.fromkeys(
                            [str(x) for x in (spec.get("evidence_quotes") or []) if x]
                            + ([rquote] if rquote else [])
                        ))
                        # Stable port IDs make same-type ports (e.g. -a and -b)
                        # independently addressable without introducing nodes.
                        scenario_key = str(spec.get("scenario_id") or "default")
                        role_key = str(spec.get("role") or spec.get("flag") or data_key)
                        spec["port_id"] = f"{scenario_key}:{_slug(role_key)}:{data_key}"
                        port_specs.append(spec)
                if port_specs:
                    prop_name = "input_specs_json" if rel_key == "inputs" else "output_specs_json"
                    graph.node(
                        op_id, "Operation",
                        **{prop_name: json.dumps(port_specs, ensure_ascii=False, sort_keys=True)},
                    )
                if unresolved_specs:
                    prop_name = "unresolved_input_specs_json" if rel_key == "inputs" else "unresolved_output_specs_json"
                    graph.node(
                        op_id, "Operation",
                        **{prop_name: json.dumps(unresolved_specs, ensure_ascii=False, sort_keys=True)},
                    )

            # Preserve named usage scenarios independently. When the model
            # attaches scenario IDs only to ports, derive minimal scenario
            # records from those evidence-backed port records as a fallback.
            scenario_records: list[dict] = []
            for scenario in op.get("scenarios", []) if isinstance(op.get("scenarios"), list) else []:
                if not isinstance(scenario, dict):
                    continue
                sfile, ssection, squote = _record_source(scenario, file_name, section, source_text=doc.content)
                scenario_id = str(scenario.get("scenario_id") or "").strip()
                scenario_name = str(scenario.get("name") or scenario.get("scenario_name") or "").strip()
                if not scenario_id or not scenario_name or not squote:
                    graph.review.append({
                        "file": source,
                        "reason": f"Operation {op_name} 的场景缺少 ID、名称或原文证据，未写入 scenarios_json",
                        "scenario_preview": scenario_name[:100],
                    })
                    continue
                scenario_records.append({
                    **_public_record(scenario),
                    "scenario_id": scenario_id,
                    "name": scenario_name,
                    "source_files": [sfile] if sfile else [],
                    "source_sections": [f"{sfile} §{ssection}"] if sfile and ssection else [],
                    "evidence_quotes": list(dict.fromkeys(
                        [str(x) for x in (scenario.get("evidence_quotes") or []) if x]
                        + ([squote] if squote else [])
                    )),
                })

            # Recover explicit Section-7 application scenarios from the source
            # markdown, even if the model only returned execution modes.
            # Do not fabricate additional Operation nodes or scenario-specific ports.
            from .scenario_parser import source_application_scenarios
            for source_scenario in source_application_scenarios(doc.content, op_name, source):
                if any(x.get("scenario_id") == source_scenario["scenario_id"] for x in scenario_records):
                    continue
                scenario_records.append(source_scenario)

            # A scenario may be represented on an IO port even if the model
            # omitted a separate operation.scenarios record in that chunk.
            for prop_name in ("input_specs_json", "output_specs_json"):
                raw_specs = graph.nodes[op_id]["properties"].get(prop_name)
                try:
                    specs = json.loads(raw_specs) if isinstance(raw_specs, str) else []
                except (TypeError, ValueError):
                    specs = []
                for spec in specs if isinstance(specs, list) else []:
                    scenario_id = str(spec.get("scenario_id") or "").strip()
                    if not scenario_id:
                        continue
                    if any(x.get("scenario_id") == scenario_id for x in scenario_records):
                        continue
                    scenario_records.append({
                        "scenario_id": scenario_id,
                        "name": str(spec.get("scenario_name") or scenario_id),
                        "description": None,
                        "source_files": list(spec.get("source_files", [])),
                        "source_sections": list(spec.get("source_sections", [])),
                        "evidence_quotes": list(spec.get("evidence_quotes", [])),
                    })
            if scenario_records:
                graph.node(
                    op_id, "Operation",
                    scenarios_json=json.dumps(scenario_records, ensure_ascii=False, sort_keys=True),
                )

        # Tool-to-tool relationships are only created from explicit documented relations.
        for rel in extraction.get("tool_relations", []):
            if not isinstance(rel, dict):
                continue
            target_name = str(rel.get("target_tool") or "").strip()
            relation = _relation_type(str(rel.get("relation_type") or ""))
            direction = str(rel.get("direction") or "").strip().casefold()
            file_name, section, quote = _record_source(rel, source, source_text=doc.content)
            if not target_name or not relation or not quote:
                graph.review.append({"file": source, "reason": "工具关系缺少目标、合法关系类型或原文证据，未入图"})
                continue
            target_key = canonical_tool_name(target_name, aliases)
            if target_key == tool_key:
                graph.review.append({"file": source, "reason": f"工具关系目标与当前工具相同，忽略: {target_name}"})
                continue
            target_id = f"tool:{target_key}"
            if target_id not in graph.nodes:
                graph.node(target_id, "Tool", name=target_name, canonical_name=target_key,
                           stub=True, aliases=[target_name])
            if relation in {"RECOMMENDED_BEFORE", "DOCUMENTED_PREREQUISITE"}:
                if direction and direction != "target_to_focal":
                    graph.review.append({"file": source, "reason": f"{target_name} 的前置关系方向与关系类型冲突，未入图"})
                    continue
                graph.edge(target_id, relation, tool_id, file_name, section,
                           status="documented_not_validated", evidence_quote=quote)
            elif relation == "DOCUMENTED_DOWNSTREAM":
                if direction and direction != "focal_to_target":
                    graph.review.append({"file": source, "reason": f"{target_name} 的后置关系方向与关系类型冲突，未入图"})
                    continue
                graph.edge(tool_id, relation, target_id, file_name, section,
                           status="documented_not_validated", evidence_quote=quote)
            else:  # PARTIALLY_ALTERNATIVE_TO
                graph.edge(tool_id, relation, target_id, file_name, section,
                           status="documented_not_validated", evidence_quote=quote)

    return graph.to_dict()


def synchronize_curated_ontology(graph: dict, ontology: dict) -> int:
    """Refresh authoritative canonical metadata in a STAGING graph.

    The per-source description_claims_json is retained. This resolves stale
    general type definitions (e.g. short_reads) after an ontology revision.
    This function never changes nodes/relationships or promotes candidates.
    """
    changed = 0
    for node in graph.get('nodes', []):
        if node.get('label') != 'DataType' or not str(node.get('id', '')).startswith('data:'):
            continue
        item = ontology.get(node['id'][5:])
        if not isinstance(item, dict):
            continue
        props = node.get('properties', {})
        for key in ('name', 'description'):
            value = item.get(key)
            if value and props.get(key) != value:
                props[key] = value
                changed += 1
        if item.get('description'):
            props['canonical_definition_source'] = 'data_types.json'
    return changed
