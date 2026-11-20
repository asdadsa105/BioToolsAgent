import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from text_ingestion.document_loader import load_documents
from bio_skill_kg.llm_extractor import (ExtractionChunk, validate_chunk_extraction,
                                        split_for_extraction, DeepSeekBioSkillExtractor,
                                        merge_chunk_results)
from bio_skill_kg.validator import validate_extraction_shape
from bio_skill_kg.auto_builder import build_graph_from_extractions
from bio_skill_kg.builder import Graph
from import_bio_skill_neo4j import load_graph, make_node_batches, make_edge_batches


class FakeDocument:
    def __init__(self, path, content):
        self.file_path = str(path)
        self.content = content
        self.doc_id = "fake-doc-id"


class BioSkillLLMPipelineTests(unittest.TestCase):
    def test_evidence_quote_must_exist_in_chunk(self):
        text = "## 7.1 过滤\nbcftools filter 输入VCF文件，输出过滤后VCF文件。"
        chunk = ExtractionChunk("c1", text, "7.1 过滤", 0, len(text), 1, 2)
        obj = {
            "tool_parameters": [],
            "operations": [{
                "name": "bcftools filter", "task_name": "变异过滤",
                "evidence_quote": "bcftools filter 输入VCF文件",
                "inputs": [{"data_type": "变异检测结果", "formats": ["VCF"],
                            "evidence_quote": "输入VCF文件"}],
                "outputs": [{"data_type": "过滤后变异数据", "formats": ["VCF"],
                             "evidence_quote": "输出过滤后VCF文件"}],
                "parameters": []
            }, {
                "name": "bcftools fake", "task_name": "虚构任务",
                "evidence_quote": "This sentence does not exist", "inputs": [], "outputs": []
            }]
        }
        clean, issues = validate_chunk_extraction(obj, chunk, "bcftools_skill.md")
        self.assertEqual(len(clean["operations"]), 1)
        self.assertTrue(any("evidence_quote" in x["reason"] for x in issues))

    def test_extraction_schema_accepts_expected_shape(self):
        sample = {
            "tool": {}, "resources": [],
            "tool_parameters": [{
                "name": "输入文件", "flag": None, "description": "输入VCF/BCF文件",
                "required": True, "default": None, "scope": "tool",
                "evidence_quote": "输入文件路径 | 必填"
            }],
            "operations": [{
                "name": "bcftools filter", "description": "变异过滤", "task_name": "变异过滤",
                "inputs": [], "outputs": [],
                "scenarios": [{"scenario_id": "high_quality_filter", "name": "高质量变异过滤",
                               "description": None, "evidence_quote": "bcftools filter"}],
                "parameters": [{
                    "name": "过滤表达式", "flag": "-i", "description": "包含表达式",
                    "required": False, "default": None, "scope": "operation",
                    "evidence_quote": "-i --include 过滤表达式"
                }],
                "min_input_files": None, "evidence_quote": "bcftools filter"
            }],
            "data_types": [], "tool_relations": [], "quality_controls": []
        }
        validate_extraction_shape(sample)

    def test_chunker_keeps_source_lines(self):
        doc = FakeDocument("large.md", "# A\n" + ("a" * 3000) + "\n## B\n" + ("b" * 3000))
        chunks = split_for_extraction(doc, max_chars=2000, overlap_chars=100)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertGreaterEqual(chunks[0].start_line, 1)
        self.assertGreater(chunks[-1].end_line, chunks[0].start_line)

    def test_deepseek_client_uses_cache_after_first_extraction(self):
        class FakeResponse:
            def raise_for_status(self):
                return None
            def json(self):
                return {"choices": [{"message": {"content": json.dumps({
                    "tool": {"name": "bcftools", "version": "1.17",
                             "evidence_quote": "**工具名称**: bcftools"},
                    "resources": [], "tool_parameters": [],
                    "operations": [{
                        "name": "bcftools filter", "description": "变异过滤",
                        "task_name": "变异过滤", "inputs": [], "outputs": [],
                        "parameters": [], "min_input_files": None,
                        "evidence_quote": "bcftools filter 过滤VCF文件"
                    }],
                    "data_types": [], "tool_relations": [], "quality_controls": []
                }, ensure_ascii=False)}}]}

        class FakeClient:
            calls = 0
            def __init__(self, timeout=None):
                pass
            def post(self, *args, **kwargs):
                FakeClient.calls += 1
                return FakeResponse()
            def close(self):
                pass

        doc = FakeDocument("bcftools_skill.md",
            "**工具名称**: bcftools\n## 7.1 场景\nbcftools filter 过滤VCF文件")
        import httpx
        with tempfile.TemporaryDirectory() as tmp, patch.object(httpx, "Client", FakeClient):
            extractor = DeepSeekBioSkillExtractor("fake-key", "https://api.deepseek.com",
                                                   "deepseek-chat", Path(tmp) / "cache")
            try:
                first = extractor.extract_document(doc)
                second = extractor.extract_document(doc)
                self.assertEqual(len(first["operations"]), 1)
                self.assertEqual(len(second["operations"]), 1)
                self.assertEqual(FakeClient.calls, 1)
                self.assertEqual(extractor.stats["api_calls"], 1)
                self.assertEqual(extractor.stats["cache_hits"], 1)
            finally:
                extractor.close()

    def test_build_graph_from_llm_extraction(self):
        doc_path = ROOT / "examples" / "bio_skills" / "bcftools_skill.md"
        doc = load_documents(doc_path)[0]
        source = "bcftools_skill.md"
        quote_op = "bcftools filter \\\n  -i 'QUAL>30 && DP>10 && AF>0.01 && TYPE=\"snp\"'"
        extraction = {
            "tool": {"name": "bcftools", "version": "1.17"},
            "resources": [], "tool_parameters": [],
            "operations": [{
                "name": "bcftools filter", "description": "过滤VCF变异",
                "task_name": "变异过滤", "min_input_files": 1,
                "evidence_quote": quote_op,
                "_source_file": source, "_source_section": "7.1 场景1: VCF文件过滤",
                "inputs": [{"data_type": "变异检测结果", "formats": ["VCF", "BCF"],
                            "evidence_quote": "**输入数据**: 变异检测生成的VCF文件",
                            "_source_file": source, "_source_section": "7.1 场景1: VCF文件过滤"}],
                "outputs": [{"data_type": "过滤后变异数据", "formats": ["VCF", "BCF"],
                             "evidence_quote": "过滤后的SNV变异文件(filtered_snvs.vcf.gz)",
                             "_source_file": source, "_source_section": "7.1 场景1: VCF文件过滤"}],
                "parameters": [{"name": "过滤表达式", "flag": "-i", "scope": "operation",
                                "evidence_quote": "-i 'QUAL>30 && DP>10 && AF>0.01 && TYPE=\"snp\"'"}]
            }],
            "data_types": [],
            "tool_relations": [{
                "target_tool": "ANNOVAR", "relation_type": "DOCUMENTED_DOWNSTREAM",
                "direction": "focal_to_target",
                "evidence_quote": "| annovar | 变异注释类 | 变异注释 |",
                "_source_file": source, "_source_section": "6.2 后置工具"
            }],
            "quality_controls": [], "review": []
        }
        graph = build_graph_from_extractions([doc], [extraction])
        nodes = {x["id"]: x for x in graph["nodes"]}
        edges = {(x["source"], x["type"], x["target"]) for x in graph["edges"]}
        self.assertIn("op:bcftools_filter", nodes)
        self.assertIn("task:变异过滤", nodes)
        self.assertIn("data:variant_calls", nodes)
        self.assertIn("format:VCF", nodes)
        self.assertIn(("tool:bcftools", "HAS_OPERATION", "op:bcftools_filter"), edges)
        self.assertIn(("op:bcftools_filter", "REQUIRES_INPUT", "data:variant_calls"), edges)
        self.assertIn(("data:filtered_variant_calls", "IS_SUBTYPE_OF", "data:variant_calls"), edges)
        self.assertIn(("tool:bcftools", "DOCUMENTED_DOWNSTREAM", "tool:annovar"), edges)
        self.assertTrue(nodes["tool:annovar"]["properties"]["stub"])
        # The resulting graph remains importable by the existing Neo4j importer.
        graph_path = ROOT / "tests" / "_tmp_llm_graph.json"
        try:
            import json
            graph_path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
            loaded = load_graph(graph_path)
            self.assertTrue(make_node_batches(loaded)["Operation"])
            self.assertTrue(make_edge_batches(loaded))
        finally:
            graph_path.unlink(missing_ok=True)


    def test_chunk_merge_preserves_format_specific_evidence(self):
        merged = merge_chunk_results([
            {"data_types": [{
                "name": "信号数据", "description": "信号轨道数据",
                "formats": ["WIG"],
                "format_evidence": [{"format": "WIG", "evidence_quote": "WIG格式的信号文件"}],
                "evidence_quote": "WIG格式的信号文件",
            }]},
            {"data_types": [{
                "name": "信号数据", "description": "信号轨道数据",
                "formats": ["BEDGRAPH"],
                "format_evidence": [{"format": "BEDGRAPH", "evidence_quote": "BEDGRAPH格式的信号文件"}],
                "evidence_quote": "BEDGRAPH格式的信号文件",
            }]},
        ])
        item = merged["data_types"][0]
        self.assertEqual(item["formats"], ["WIG", "BEDGRAPH"])
        self.assertEqual(
            {x["format"] for x in item["format_evidence"]},
            {"WIG", "BEDGRAPH"},
        )

    def test_chunk_merge_keeps_same_datatype_ports_separate(self):
        quote = "bedtools intersect -a regions1.bed -b regions2.bed > intersection.bed"
        merged = merge_chunk_results([
            {"operations": [{
                "name": "bedtools intersect", "inputs": [{
                    "data_type": "基因组区域数据", "role": "regions_a", "flag": "-a",
                    "scenario_id": "basic_intersection", "evidence_quote": quote,
                    "formats": [],
                }], "outputs": [], "parameters": [], "scenarios": [],
                "evidence_quote": quote,
            }]},
            {"operations": [{
                "name": "bedtools intersect", "inputs": [{
                    "data_type": "基因组区域数据", "role": "regions_b", "flag": "-b",
                    "scenario_id": "basic_intersection", "evidence_quote": quote,
                    "formats": [],
                }], "outputs": [], "parameters": [], "scenarios": [],
                "evidence_quote": quote,
            }]},
        ])
        ports = merged["operations"][0]["inputs"]
        self.assertEqual(len(ports), 2)
        self.assertEqual({x["flag"] for x in ports}, {"-a", "-b"})

    def test_chunk_merge_keeps_scenarios_and_clears_conflicting_global_minimum(self):
        merged = merge_chunk_results([
            {"operations": [{
                "name": "bwa mem", "inputs": [], "outputs": [], "parameters": [],
                "min_input_files": 1,
                "scenarios": [{"scenario_id": "single_end", "name": "单端比对",
                               "evidence_quote": "单端数据比对"}],
                "evidence_quote": "bwa mem",
            }]},
            {"operations": [{
                "name": "bwa mem", "inputs": [], "outputs": [], "parameters": [],
                "min_input_files": 2,
                "scenarios": [{"scenario_id": "paired_end", "name": "双端比对",
                               "evidence_quote": "双端数据比对"}],
                "evidence_quote": "bwa mem",
            }]},
        ])
        operation = merged["operations"][0]
        self.assertIsNone(operation["min_input_files"])
        self.assertEqual({x["scenario_id"] for x in operation["scenarios"]},
                         {"single_end", "paired_end"})
        self.assertTrue(any("min_input_files 不一致" in x["reason"] for x in merged["review"]))

    def test_validator_checks_io_flag_against_port_evidence(self):
        quote = "bedtools intersect -a regions1.bed -b regions2.bed"
        text = f"## 7.1 交集\n{quote}"
        chunk = ExtractionChunk("c1", text, "7.1 交集", 0, len(text), 1, 2)
        obj = {
            "operations": [{
                "name": "bedtools intersect", "task_name": "区域交集",
                "evidence_quote": quote,
                "inputs": [
                    {"data_type": "基因组区域数据", "role": "regions_a", "flag": "-a",
                     "required": True, "min_occurs": 1, "max_occurs": 1,
                     "evidence_quote": quote, "formats": []},
                    {"data_type": "基因组区域数据", "role": "regions_b", "flag": "-b",
                     "required": True, "min_occurs": 1, "max_occurs": 1,
                     "evidence_quote": quote, "formats": []},
                    {"data_type": "基因组区域数据", "role": "bad_port", "flag": "-g",
                     "required": True, "evidence_quote": quote, "formats": []},
                ],
                "outputs": [], "parameters": [], "scenarios": [],
            }]
        }
        clean, issues = validate_chunk_extraction(obj, chunk, "bedtools_skill.md")
        ports = clean["operations"][0]["inputs"]
        self.assertEqual([x["flag"] for x in ports], ["-a", "-b", None])
        self.assertTrue(any("端口 flag" in x["reason"] for x in issues))

    def test_builder_stores_two_ports_and_scenario_metadata(self):
        quote = "bedtools intersect -a regions1.bed -b regions2.bed > intersection.bed"
        scenario_quote = "分析两个基因组区域文件的交集"
        doc = FakeDocument("bedtools_skill.md", (
            "**工具名称**: bedtools\n## 7.1 交集分析\n" + scenario_quote + "\n" + quote
        ))
        extraction = {
            "tool": {"name": "bedtools"}, "resources": [], "tool_parameters": [],
            "data_types": [], "tool_relations": [], "quality_controls": [], "review": [],
            "operations": [{
                "name": "bedtools intersect", "description": "计算基因组区域交集",
                "task_name": "区域交集", "evidence_quote": quote,
                "inputs": [
                    {"data_type": "基因组区域数据", "role": "regions_a", "flag": "-a",
                     "required": True, "min_occurs": 1, "max_occurs": 1,
                     "scenario_id": "basic_intersection", "scenario_name": "基本交集",
                     "formats": [], "evidence_quote": quote},
                    {"data_type": "基因组区域数据", "role": "regions_b", "flag": "-b",
                     "required": True, "min_occurs": 1, "max_occurs": 1,
                     "scenario_id": "basic_intersection", "scenario_name": "基本交集",
                     "formats": [], "evidence_quote": quote},
                ],
                "outputs": [{"data_type": "基因组区域交集结果", "role": "intersection_output",
                             "required": True, "scenario_id": "basic_intersection",
                             "scenario_name": "基本交集", "formats": [],
                             "evidence_quote": quote}],
                "scenarios": [{"scenario_id": "basic_intersection", "name": "基本交集",
                               "description": "分析两个基因组区域文件的交集",
                               "evidence_quote": scenario_quote}],
                "parameters": [], "min_input_files": 2,
            }]
        }
        graph = build_graph_from_extractions([doc], [extraction])
        nodes = {x["id"]: x for x in graph["nodes"]}
        op_props = nodes["op:bedtools_intersect"]["properties"]
        input_specs = json.loads(op_props["input_specs_json"])
        output_specs = json.loads(op_props["output_specs_json"])
        scenarios = json.loads(op_props["scenarios_json"])
        self.assertEqual(len(input_specs), 2)
        self.assertEqual({x["flag"] for x in input_specs}, {"-a", "-b"})
        self.assertEqual(len(output_specs), 1)
        self.assertEqual(scenarios[0]["scenario_id"], "basic_intersection")
        self.assertEqual(op_props["min_input_files"], 2)
        graph_path = ROOT / "tests" / "_tmp_v5_ports_graph.json"
        try:
            graph_path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
            loaded = load_graph(graph_path)
            operation_rows = make_node_batches(loaded)["Operation"]
            self.assertTrue(any(
                row["props"].get("input_specs_json") == op_props["input_specs_json"]
                for row in operation_rows
            ))
        finally:
            graph_path.unlink(missing_ok=True)

    def test_graph_incremental_merge_keeps_distinct_operation_ports(self):
        graph = Graph()
        graph.node("op:bedtools_intersect", "Operation", name="bedtools intersect",
                   input_specs_json=json.dumps([{"data_type_id": "data:genomic_regions",
                                                 "role": "regions_a", "flag": "-a"}], ensure_ascii=False))
        graph.node("op:bedtools_intersect", "Operation", name="bedtools intersect",
                   input_specs_json=json.dumps([{"data_type_id": "data:genomic_regions",
                                                 "role": "regions_b", "flag": "-b"}], ensure_ascii=False))
        props = graph.nodes["op:bedtools_intersect"]["properties"]
        ports = json.loads(props["input_specs_json"])
        self.assertEqual(len(ports), 2)
        self.assertEqual({x["flag"] for x in ports}, {"-a", "-b"})


if __name__ == "__main__":
    unittest.main()
