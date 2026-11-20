import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bio_skill_kg.auto_builder import build_graph_from_extractions
from bio_skill_kg.llm_extractor import ExtractionChunk
from bio_skill_kg.validator import validate_chunk_extraction
from bio_skill_kg.builder import merge_graphs
from import_bio_skill_neo4j import load_graph


class FakeDocument:
    def __init__(self, filename, tool_name):
        self.file_path = str(ROOT / "examples" / "bio_skills" / filename)
        self.content = f"**工具名称**: {tool_name}\n"
        self.doc_id = filename


def extraction(tool_name, *, data_types=None, operations=None):
    return {
        "tool": {"name": tool_name},
        "resources": [],
        "tool_parameters": [],
        "operations": operations or [],
        "data_types": data_types or [],
        "tool_relations": [],
        "quality_controls": [],
        "review": [],
    }


def op(name, inputs=None, outputs=None, quote=None):
    return {
        "name": name,
        "description": name,
        "task_name": f"{name}任务",
        "inputs": inputs or [],
        "outputs": outputs or [],
        "parameters": [],
        "evidence_quote": quote or name,
        "_source_section": "7.1",
    }


def io(name, description, formats, quote):
    return {
        "data_type": name,
        "description": description,
        "formats": formats,
        "evidence_quote": quote,
        "_source_section": "7.1",
    }


class SemanticNormalizationTests(unittest.TestCase):
    def graph(self, docs, extractions):
        # FakeDocument instances in these unit tests model already evidence-
        # validated LLM output. Put those exact quotes into the fake source.
        for doc, extracted in zip(docs, extractions):
            if not hasattr(doc, "content"):
                continue
            quotes = []
            def collect(record):
                if not isinstance(record, dict):
                    return
                quote = record.get("evidence_quote")
                if quote:
                    quotes.append(str(quote))
                for item in record.get("format_evidence", []) or []:
                    if isinstance(item, dict) and item.get("evidence_quote"):
                        quotes.append(str(item["evidence_quote"]))
            for key in ("data_types", "tool_parameters", "tool_relations", "quality_controls"):
                for record in extracted.get(key, []) or []:
                    collect(record)
            for operation in extracted.get("operations", []) or []:
                collect(operation)
                for key in ("inputs", "outputs", "parameters"):
                    for record in operation.get(key, []) or []:
                        collect(record)
            doc.content += "\n## 5. Evidence\n" + "\n".join(dict.fromkeys(quotes))
        return build_graph_from_extractions(docs, extractions)

    def nodes(self, graph):
        return {n["id"]: n for n in graph["nodes"]}

    def edges(self, graph):
        return {(e["source"], e["type"], e["target"]) for e in graph["edges"]}


    def test_validator_moves_format_name_into_formats(self):
        text = "VCF 是文本格式变异文件，TXT 用于样本列表。"
        chunk = ExtractionChunk("c1", text, "5. 数据类型", 0, len(text), 1, 1)
        obj = {
            "tool": {},
            "resources": [],
            "tool_parameters": [],
            "operations": [],
            "data_types": [
                {"name": "VCF", "description": "文本格式变异文件",
                 "formats": [], "evidence_quote": "VCF 是文本格式变异文件"},
                {"name": "TXT", "description": "样本列表",
                 "formats": [], "evidence_quote": "TXT 用于样本列表"},
            ],
            "tool_relations": [],
            "quality_controls": [],
        }
        clean, issues = validate_chunk_extraction(obj, chunk, "format.md")
        self.assertEqual(clean["data_types"][0]["formats"], ["VCF"])
        self.assertEqual(clean["data_types"][1]["formats"], ["TXT"])

    def test_validator_drops_unverified_format_but_keeps_record(self):
        text = "BED 格式的基因组区域文件。"
        chunk = ExtractionChunk("c1", text, "5. 数据类型", 0, len(text), 1, 1)
        obj = {
            "tool": {},
            "resources": [],
            "tool_parameters": [],
            "operations": [],
            "data_types": [{
                "name": "基因组区域",
                "description": "BED格式的基因组区域文件",
                "formats": ["BED", "VCF"],
                "evidence_quote": "BED 格式的基因组区域文件",
            }],
            "tool_relations": [],
            "quality_controls": [],
        }
        clean, issues = validate_chunk_extraction(obj, chunk, "format.md")
        self.assertEqual(clean["data_types"][0]["formats"], ["BED"])
        self.assertTrue(any("VCF" in x["reason"] for x in issues))


    def test_validator_recognizes_canonical_format_aliases_in_source(self):
        text = "FASTQ 文件支持 .fq、.fastq、.fq.gz 和 .fastq.gz。"
        chunk = ExtractionChunk("c1", text, "5. 数据类型", 0, len(text), 1, 1)
        obj = {
            "tool": {},
            "resources": [],
            "tool_parameters": [],
            "operations": [],
            "data_types": [{
                "name": "短读长测序数据",
                "description": "单端或双端测序数据",
                "formats": ["FASTQ_GZ"],
                "evidence_quote": "FASTQ 文件支持 .fq、.fastq、.fq.gz 和 .fastq.gz。",
            }],
            "tool_relations": [],
            "quality_controls": [],
        }
        clean, issues = validate_chunk_extraction(obj, chunk, "reads.md")
        self.assertEqual(clean["data_types"][0]["formats"], ["FASTQ_GZ"])

    def test_format_names_are_not_data_types(self):
        doc = FakeDocument("formats.md", "format-probe")
        data_types = [
            {"name": "VCF", "description": "文本格式变异文件", "formats": ["VCF"],
             "evidence_quote": "VCF文本格式变异文件"},
            {"name": "TXT", "description": "样本列表、区域列表等", "formats": ["TXT"],
             "evidence_quote": "TXT样本列表、区域列表等"},
            {"name": "CSV", "description": "可导出为CSV格式", "formats": ["CSV"],
             "evidence_quote": "CSV可导出为CSV格式"},
            {"name": "BAM", "description": "BAM格式的比对文件", "formats": ["BAM"],
             "evidence_quote": "BAM格式的比对文件"},
            {"name": "BED", "description": "BED格式的基因组区域文件", "formats": ["BED"],
             "evidence_quote": "BED格式的基因组区域文件"},
        ]
        graph = self.graph([doc], [extraction("format-probe", data_types=data_types)])
        nodes = self.nodes(graph)
        for forbidden in ["data:vcf", "data:txt", "data:csv", "data:bam", "data:bed"]:
            self.assertNotIn(forbidden, nodes)
        for expected in ["data:variant_calls", "data:sample_list", "data:region_list",
                         "data:aligned_reads_bam", "data:genomic_regions"]:
            self.assertIn(expected, nodes)
        for fmt in ["format:VCF", "format:TXT", "format:CSV", "format:BAM", "format:BED"]:
            self.assertIn(fmt, nodes)
        self.assertEqual(nodes["data:sample_list"]["label"], "DataType")

    def test_bedtools_coverage_splits_bam_and_bed_semantics(self):
        doc = FakeDocument("bedtools.md", "bedtools")
        coverage = op(
            "bedtools coverage",
            inputs=[
                io("基因组区域", "BED格式的基因组区域文件", ["BED"], "输入 BED 区域"),
                io("比对结果", "BAM或BED格式的覆盖文件", ["BAM", "BED"], "输入 BAM 或 BED 覆盖文件"),
            ],
            outputs=[io("覆盖度结果", "区域覆盖度结果", ["BED"], "输出覆盖度结果")],
        )
        graph = self.graph([doc], [extraction("bedtools", operations=[coverage])])
        nodes, edges = self.nodes(graph), self.edges(graph)
        self.assertIn(("op:bedtools_coverage", "REQUIRES_INPUT", "data:aligned_reads_bam"), edges)
        self.assertIn(("op:bedtools_coverage", "REQUIRES_INPUT", "data:genomic_regions"), edges)
        self.assertNotIn("data:bam", nodes)
        self.assertNotIn("data:bed", nodes)
        self.assertNotIn(("data:aligned_reads", "HAS_FORMAT", "format:BED"), edges)
        self.assertIn(("data:aligned_reads_bam", "HAS_FORMAT", "format:BAM"), edges)
        self.assertIn(("data:genomic_regions", "HAS_FORMAT", "format:BED"), edges)


    def test_generic_statistics_name_uses_description_to_disambiguate(self):
        doc = FakeDocument("statistics.md", "stats-tool")
        data_types = [
            {"name": "统计结果", "description": "变异统计结果", "formats": ["TXT"],
             "evidence_quote": "统计结果是变异统计结果"},
            {"name": "统计结果", "description": "运行统计文件", "formats": ["TXT"],
             "evidence_quote": "统计结果是运行统计文件"},
        ]
        graph = self.graph([doc], [extraction("stats-tool", data_types=data_types)])
        nodes = self.nodes(graph)
        self.assertIn("data:variant_statistics", nodes)
        self.assertNotIn("data:tool_statistics", nodes)
        self.assertNotIn("data:统计结果", nodes)

    def test_alignment_family_creates_sam_and_bam_subtypes(self):
        doc = FakeDocument("bwa.md", "bwa")
        data_types = [{
            "name": "序列比对结果",
            "description": "序列比对结果，包含详细的比对信息",
            "formats": ["SAM", "BAM"],
            "evidence_quote": "序列比对结果 SAM/BAM",
        }]
        graph = self.graph([doc], [extraction("bwa", data_types=data_types)])
        nodes, edges = self.nodes(graph), self.edges(graph)
        self.assertIn("data:aligned_reads", nodes)
        self.assertIn("data:aligned_reads_sam", nodes)
        self.assertIn("data:aligned_reads_bam", nodes)
        self.assertIn(("data:aligned_reads_sam", "IS_SUBTYPE_OF", "data:aligned_reads"), edges)
        self.assertIn(("data:aligned_reads_bam", "IS_SUBTYPE_OF", "data:aligned_reads"), edges)
        self.assertNotIn(("data:aligned_reads", "HAS_FORMAT", "format:BED"), edges)

    def test_description_variants_are_preserved_without_false_conflict(self):
        docs = [FakeDocument("a.md", "tool-a"), FakeDocument("b.md", "tool-b")]
        op_a = op("tool-a run", inputs=[io("变异检测结果", "输入VCF文件", ["VCF"], "A input VCF")])
        op_b = op("tool-b run", inputs=[io("变异检测结果", "待合并的VCF文件", ["VCF"], "B input VCF")])
        first = self.graph([docs[0]], [extraction("tool-a", operations=[op_a])])
        second = self.graph([docs[1]], [extraction("tool-b", operations=[op_b])])
        merged = merge_graphs(first, second)
        node = self.nodes(merged)["data:variant_calls"]
        self.assertEqual(node["properties"]["description"], "变异检测流程产生的变异调用数据，可作为过滤、统计、合并、比较和注释等操作的输入。")
        claims = json.loads(node["properties"]["description_claims_json"])
        descriptions = {x["description"] for x in claims}
        sources = {x["source_file"] for x in claims}
        self.assertIn("输入VCF文件", descriptions)
        self.assertIn("待合并的VCF文件", descriptions)
        self.assertIn("a.md", sources)
        self.assertIn("b.md", sources)
        self.assertFalse(any(x.get("field") == "description" for x in merged["review"]))

    def test_annotation_vcf_and_avcf_share_semantic_data_type_but_keep_formats(self):
        doc = FakeDocument("annovar.md", "annovar")
        data_types = [
            {"name": "AVCF", "description": "注释后的VCF文件", "formats": ["AVCF"],
             "evidence_quote": "AVCF注释后的VCF文件"},
            {"name": "注释VCF", "description": "注释后的VCF文件", "formats": ["VCF"],
             "evidence_quote": "注释VCF注释后的VCF文件"},
        ]
        graph = self.graph([doc], [extraction("annovar", data_types=data_types)])
        nodes, edges = self.nodes(graph), self.edges(graph)
        self.assertIn("data:annotated_variants", nodes)
        self.assertNotIn("data:avcf", nodes)
        self.assertIn(("data:annotated_variants", "HAS_FORMAT", "format:AVCF"), edges)
        self.assertIn(("data:annotated_variants", "HAS_FORMAT", "format:VCF"), edges)

    def test_description_claims_are_neo4j_importable_and_incremental_idempotent(self):
        docs = [FakeDocument("a.md", "tool-a"), FakeDocument("b.md", "tool-b")]
        first = self.graph([docs[0]], [extraction("tool-a", operations=[
            op("tool-a run", inputs=[io("变异检测结果", "输入VCF文件", ["VCF"], "A input VCF")])
        ])])
        second = self.graph([docs[1]], [extraction("tool-b", operations=[
            op("tool-b run", inputs=[io("变异检测结果", "待合并的VCF文件", ["VCF"], "B input VCF")])
        ])])
        merged = merge_graphs(first, second)
        twice = merge_graphs(merged, second)
        self.assertEqual(merged, twice)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
            loaded = load_graph(path)
            self.assertTrue(any(n["id"] == "data:variant_calls" for n in loaded["nodes"]))


    def test_unknown_semantic_type_is_quarantined_not_auto_created(self):
        doc = FakeDocument("bedtools.md", "bedtools")
        graph = self.graph([doc], [extraction("bedtools", data_types=[{
            "name": "并集结果",
            "description": "unionbedg 命令输出的结果，具体语义和格式需要核对",
            "formats": ["BED"],
            "evidence_quote": "bedtools unionbedg -i a.bed b.bed > union.bed",
        }])])
        nodes = self.nodes(graph)
        self.assertNotIn("data:并集结果", nodes)
        self.assertTrue(any(
            x.get("candidate_name") == "并集结果"
            and "待审核候选" in x.get("reason", "")
            for x in graph["review"]
        ))

    def test_semantic_aliases_and_new_types_are_normalized(self):
        doc = FakeDocument("mixed.md", "mixed-tool")
        records = [
            {"name": "变异数据", "description": "VCF变异数据", "formats": ["VCF"],
             "evidence_quote": "VCF变异数据"},
            {"name": "合并后的变异", "description": "合并后的VCF变异", "formats": ["VCF_GZ"],
             "evidence_quote": "合并后的变异文件 merged.vcf.gz"},
            {"name": "单样本变异", "description": "单个样本的VCF文件", "formats": ["VCF_GZ"],
             "evidence_quote": "单个样本的VCF文件 sample1.vcf.gz"},
            {"name": "过滤后的注释结果", "description": "经过过滤的注释结果", "formats": ["TXT"],
             "evidence_quote": "过滤后的注释结果 filtered.txt"},
            {"name": "测序读段数据", "description": "FASTQ测序读段", "formats": ["FASTQ_GZ"],
             "evidence_quote": "测序读段数据 reads.fastq.gz"},
            {"name": "多样本覆盖度结果", "description": "多个样本的覆盖度结果", "formats": ["BED"],
             "evidence_quote": "多样本覆盖度结果 coverage_multi.bed"},
            {"name": "差异区域", "description": "基因组差异区域", "formats": ["BED"],
             "evidence_quote": "差异区域 difference.bed"},
            {"name": "带交集计数的区域结果", "description": "交集结果", "formats": ["BED"],
             "evidence_quote": "带交集计数的区域结果 intersection_count.bed"},
            {"name": "带原始区域平均值的合并结果", "description": "合并区域平均值", "formats": ["BED"],
             "evidence_quote": "带原始区域平均值的合并结果 merged_mean.bed"},
            {"name": "带原始区域计数的合并结果", "description": "合并区域计数", "formats": ["BED"],
             "evidence_quote": "带原始区域计数的合并结果 merged_count.bed"},
            {"name": "信号数据", "description": "WIG和BEDGRAPH信号数据", "formats": ["WIG", "BEDGRAPH"],
             "evidence_quote": "WIG格式的信号文件"},
            {"name": "运行日志", "description": "工具运行日志", "formats": ["TXT"],
             "evidence_quote": "运行日志 bedtools.log"},
        ]
        graph = self.graph([doc], [extraction("mixed-tool", data_types=records)])
        nodes = self.nodes(graph)
        expected = [
            "data:variant_calls", "data:merged_variant_calls",
            "data:single_sample_variant_calls", "data:filtered_annotated_variants",
            "data:short_reads", "data:multi_sample_coverage_result",
            "data:difference_regions", "data:counted_intersection_regions",
            "data:mean_aggregated_merged_regions", "data:count_aggregated_merged_regions",
            "data:signal_tracks", "data:execution_log",
        ]
        for node_id in expected:
            self.assertIn(node_id, nodes)
        for forbidden in ["data:变异数据", "data:合并后的变异", "data:信号数据"]:
            self.assertNotIn(forbidden, nodes)

    def test_bwa_read_and_annovar_database_aliases_resolve_to_curated_types(self):
        doc = FakeDocument("bwa_skill.md", "bwa")
        records = [
            {"name": "双端FASTQ文件", "description": "双端原始测序读段", "formats": ["FASTQ_GZ"],
             "evidence_quote": "双端FASTQ文件 input_1.fq.gz input_2.fq.gz"},
            {"name": "完整的ANNOVAR注释数据库", "description": "ANNOVAR注释数据库目录", "formats": [],
             "evidence_quote": "完整的ANNOVAR注释数据库 humandb/"},
        ]
        graph = self.graph([doc], [extraction("bwa", data_types=records)])
        nodes = self.nodes(graph)
        self.assertIn("data:short_reads", nodes)
        self.assertIn("data:annotation_database", nodes)

    def test_format_evidence_is_split_per_format_and_source_section_is_precise(self):
        source = (
            "**工具名称**: bedtools\n"
            "# bedtools工具Skill\n"
            "## 5. 数据类型兼容性\n"
            "### 5.1 WIG信号文件\n"
            "| WIG | 支持 | .wig | WIG格式的信号文件 |\n"
            "### 5.2 BEDGRAPH信号文件\n"
            "| BEDGRAPH | 支持 | .bedgraph | BEDGRAPH格式的信号文件 |\n"
        )
        chunk = ExtractionChunk(
            "c1", source, "5. 数据类型兼容性 / 5.1 输入数据类型", 0, len(source), 1,
            source.count("\n") + 1
        )
        record = {
            "name": "信号数据", "description": "WIG和BEDGRAPH信号文件",
            "formats": ["WIG", "BEDGRAPH"],
            "evidence_quote": "| WIG | 支持 | .wig | WIG格式的信号文件 |",
        }
        clean, issues = validate_chunk_extraction({
            "tool": {}, "resources": [], "tool_parameters": [],
            "operations": [], "data_types": [record],
            "tool_relations": [], "quality_controls": [],
        }, chunk, "bedtools_skill.md")
        format_evidence = clean["data_types"][0]["format_evidence"]
        self.assertEqual([x["format"] for x in format_evidence], ["WIG", "BEDGRAPH"])
        self.assertIn("WIG格式的信号文件", format_evidence[0]["evidence_quote"])
        self.assertIn("BEDGRAPH格式的信号文件", format_evidence[1]["evidence_quote"])

        doc = FakeDocument("bedtools_skill.md", "bedtools")
        doc.content = source
        graph = build_graph_from_extractions(
            [doc],
            [extraction("bedtools", data_types=clean["data_types"])],
        )
        nodes = self.nodes(graph)
        edges_by_format = {
            edge["target"]: edge for edge in graph["edges"]
            if edge["source"] == "data:signal_tracks" and edge["type"] == "HAS_FORMAT"
        }
        self.assertIn("format:WIG", edges_by_format)
        self.assertIn("format:BEDGRAPH", edges_by_format)
        self.assertIn("WIG格式的信号文件", edges_by_format["format:WIG"]["properties"]["evidence_quotes"][0])
        self.assertIn("BEDGRAPH格式的信号文件", edges_by_format["format:BEDGRAPH"]["properties"]["evidence_quotes"][0])
        sections = nodes["data:signal_tracks"]["properties"]["source_sections"]
        self.assertIn(
            "bedtools_skill.md §bedtools工具Skill / 5. 数据类型兼容性 / 5.1 WIG信号文件",
            sections,
        )
        self.assertIn(
            "bedtools_skill.md §bedtools工具Skill / 5. 数据类型兼容性 / 5.2 BEDGRAPH信号文件",
            sections,
        )
        self.assertIn(
            "bedtools_skill.md §bedtools工具Skill / 5. 数据类型兼容性 / 5.1 WIG信号文件",
            edges_by_format["format:WIG"]["properties"]["source_sections"],
        )
        self.assertIn(
            "bedtools_skill.md §bedtools工具Skill / 5. 数据类型兼容性 / 5.2 BEDGRAPH信号文件",
            edges_by_format["format:BEDGRAPH"]["properties"]["source_sections"],
        )

    def test_statistics_outputs_are_separated_by_semantics(self):
        doc = FakeDocument("stats.md", "stats-tool")
        records = [
            {"name": "统计文件", "description": "ANNOVAR注释统计信息 multianno_summary.txt",
             "formats": ["TXT"], "evidence_quote": "注释统计信息 multianno_summary.txt"},
            {"name": "统计结果", "description": "变异统计结果 variants.stats",
             "formats": ["TXT"], "evidence_quote": "变异统计结果 variants.stats"},
            {"name": "详细覆盖度统计", "description": "详细的覆盖度统计 coverage_detail.bed",
             "formats": ["BED"], "evidence_quote": "详细的覆盖度统计 coverage_detail.bed"},
        ]
        graph = self.graph([doc], [extraction("stats-tool", data_types=records)])
        nodes = self.nodes(graph)
        self.assertIn("data:annotation_statistics", nodes)
        self.assertIn("data:variant_statistics", nodes)
        self.assertIn("data:detailed_coverage_statistics", nodes)
        self.assertNotIn("data:统计文件", nodes)
        self.assertNotIn("data:统计结果", nodes)
        self.assertNotIn("data:tool_statistics", nodes)


if __name__ == "__main__":
    unittest.main()
