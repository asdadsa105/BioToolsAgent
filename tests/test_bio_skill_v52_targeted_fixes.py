import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from text_ingestion.document_loader import load_documents
from bio_skill_kg.llm_extractor import apply_source_grounded_completions, merge_chunk_results
from bio_skill_kg.auto_builder import (
    build_graph_from_extractions,
    load_data_type_ontology,
    load_ontology_aliases,
    load_file_format_ontology,
    _resolve_data_type_keys,
)


class BioSkillKGv52TargetedFixTests(unittest.TestCase):
    def source(self, filename):
        return load_documents(ROOT / "examples" / "bio_skills" / filename)[0]

    def test_new_aliases_resolve_to_existing_curated_datatypes(self):
        ontology = load_data_type_ontology()
        aliases = load_ontology_aliases()
        formats = load_file_format_ontology()
        cases = [
            ("二进制变异检测结果", "二进制格式变异文件", ["BCF"], "variant_calls"),
            ("质量分布图", "质量分布图表(depth_distribution.pdf)", ["PDF"], "quality_distribution_plot"),
            ("至少50%重叠的交集区域", "至少50%重叠的交集", ["BED"], "intersected_regions"),
        ]
        for name, description, fmts, expected in cases:
            with self.subTest(name=name):
                resolved, is_format = _resolve_data_type_keys(
                    name, description, fmts, ontology, aliases, formats
                )
                self.assertEqual(resolved, [expected])
                self.assertFalse(is_format)

    def test_gtcheck_duplicate_sample_list_port_merges_and_inherits_scenario(self):
        doc = self.source("bcftools_skill.md")
        command = (
            "bcftools gtcheck \\\n"
            "  -g input.vcf.gz \\\n"
            "  -s samples.txt \\\n"
            "  -o genotype_check.txt"
        )
        extraction = {"operations": [{
            "name": "bcftools gtcheck",
            "evidence_quote": command,
            "inputs": [
                {"data_type": "变异检测结果", "role": "variant_data", "flag": "-g",
                 "required": True, "scenario_id": None, "formats": ["VCF_GZ"],
                 "evidence_quote": "-g input.vcf.gz"},
                {"data_type": "样本列表", "role": "sample_list", "flag": "-s",
                 "required": False, "scenario_id": None, "formats": ["TXT"],
                 "evidence_quote": "-s samples.txt"},
            ],
            "outputs": [{"data_type": "基因型检查结果", "role": "genotype_check_output",
                         "flag": "-o", "required": False, "scenario_id": "genotype_check",
                         "formats": ["TXT"], "evidence_quote": "-o genotype_check.txt"}],
            "parameters": [], "scenarios": [],
        }]}
        fixed = apply_source_grounded_completions(extraction, doc.content, "bcftools_skill.md")
        op = fixed["operations"][0]
        sample_ports = [x for x in op["inputs"] if x.get("role") == "sample_list"]
        variant_ports = [x for x in op["inputs"] if x.get("role") == "variant_data"]
        self.assertEqual(len(sample_ports), 1)
        self.assertEqual(sample_ports[0].get("scenario_id"), "genotype_check")
        self.assertIs(sample_ports[0].get("required"), True)
        self.assertEqual(len(variant_ports), 1)
        self.assertEqual(variant_ports[0].get("scenario_id"), "genotype_check")

    def test_chunk_merge_deduplicates_scenario_less_and_scenario_scoped_same_port(self):
        quote = "bcftools gtcheck -g input.vcf.gz -s samples.txt -o genotype_check.txt"
        merged = merge_chunk_results([
            {"operations": [{"name": "bcftools gtcheck", "evidence_quote": quote,
              "inputs": [{"data_type": "样本列表", "role": "sample_list", "flag": "-s",
                          "required": False, "scenario_id": None, "evidence_quote": "-s samples.txt"}],
              "outputs": [], "parameters": [], "scenarios": []}]},
            {"operations": [{"name": "bcftools gtcheck", "evidence_quote": quote,
              "inputs": [{"data_type": "样本列表", "role": "sample_list", "flag": "-s",
                          "required": True, "scenario_id": "genotype_check",
                          "scenario_name": "基因型检查", "evidence_quote": quote}],
              "outputs": [], "parameters": [], "scenarios": []}]},
        ])
        ports = merged["operations"][0]["inputs"]
        self.assertEqual(len(ports), 1)
        self.assertEqual(ports[0].get("scenario_id"), "genotype_check")
        self.assertIs(ports[0].get("required"), True)

    def test_final_graph_has_bcf_plot_and_intersection50_mappings(self):
        bcftools_doc = self.source("bcftools_skill.md")
        bedtools_doc = self.source("bedtools_skill.md")
        bcf_quote = "| BCF | 支持 | .bcf | 二进制格式变异文件 |"
        plot_command = "bcftools plot \\\n  -d depth:1,100 \\\n  -o depth_distribution.pdf \\\n  input.vcf.gz"
        plot_quote = "质量分布图表(depth_distribution.pdf)"
        intersect_command = (
            "bedtools intersect \\\n"
            "  -a regions1.bed \\\n"
            "  -b regions2.bed \\\n"
            "  -f 0.5 \\\n"
            "  -o intersection_50.bed"
        )
        intersect_quote = "- 至少50%重叠的交集(intersection_50.bed)"
        bcftools_extraction = {
            "tool": {"name": "bcftools"}, "resources": [], "tool_parameters": [],
            "data_types": [{"name": "二进制变异检测结果", "description": "二进制格式变异文件",
                            "formats": ["BCF"], "format_evidence": [{"format": "BCF", "evidence_quote": bcf_quote}],
                            "evidence_quote": bcf_quote}],
            "operations": [{"name": "bcftools plot", "description": "生成质量分布图",
                            "task_name": "变异质量可视化", "evidence_quote": plot_command,
                            "inputs": [{"data_type": "变异检测结果", "role": "input_variants",
                                        "required": True, "formats": ["VCF_GZ"],
                                        "format_evidence": [{"format": "VCF_GZ", "evidence_quote": "input.vcf.gz"}],
                                        "evidence_quote": "input.vcf.gz"}],
                            "outputs": [{"data_type": "质量分布图", "description": "质量分布图表(depth_distribution.pdf)",
                                         "role": "plot_output", "flag": "-o", "flag_evidence_quote": plot_command,
                                         "required": True, "formats": ["PDF"],
                                         "format_evidence": [{"format": "PDF", "evidence_quote": "depth_distribution.pdf"}],
                                         "evidence_quote": plot_quote}],
                            "parameters": [], "scenarios": []}],
            "tool_relations": [], "quality_controls": [], "review": [],
        }
        bedtools_extraction = {
            "tool": {"name": "bedtools"}, "resources": [], "tool_parameters": [],
            "data_types": [],
            "operations": [{"name": "bedtools intersect", "description": "计算两个区域文件的交集",
                            "task_name": "基因组区域交集分析", "evidence_quote": intersect_command,
                            "inputs": [
                                {"data_type": "基因组区域数据", "role": "regions_a", "flag": "-a", "required": True,
                                 "scenario_id": "region_intersection", "formats": ["BED"],
                                 "format_evidence": [{"format": "BED", "evidence_quote": "两个BED格式的基因组区域文件"}],
                                 "evidence_quote": "两个BED格式的基因组区域文件"},
                                {"data_type": "基因组区域数据", "role": "regions_b", "flag": "-b", "required": True,
                                 "scenario_id": "region_intersection", "formats": ["BED"],
                                 "format_evidence": [{"format": "BED", "evidence_quote": "两个BED格式的基因组区域文件"}],
                                 "evidence_quote": "两个BED格式的基因组区域文件"},
                            ],
                            "outputs": [{"data_type": "至少50%重叠的交集区域", "description": "至少50%重叠的交集",
                                         "role": "intersection_50", "flag": "-o", "flag_evidence_quote": intersect_command,
                                         "condition": "使用 -f 0.5 指定最小重叠比例时",
                                         "scenario_id": "region_intersection", "formats": ["BED"],
                                         "format_evidence": [{"format": "BED", "evidence_quote": intersect_quote}],
                                         "evidence_quote": intersect_quote}],
                            "parameters": [], "scenarios": []}],
            "tool_relations": [], "quality_controls": [], "review": [],
        }
        graph = build_graph_from_extractions(
            [bcftools_doc, bedtools_doc], [bcftools_extraction, bedtools_extraction]
        )
        nodes = {n["id"]: n for n in graph["nodes"]}
        edges = {(e["source"], e["type"], e["target"]) for e in graph["edges"]}
        self.assertIn(("data:variant_calls", "HAS_FORMAT", "format:BCF"), edges)
        self.assertIn(("op:bcftools_plot", "PRODUCES", "data:quality_distribution_plot"), edges)
        self.assertIn(("op:bedtools_intersect", "PRODUCES", "data:intersected_regions"), edges)
        plot_specs = json.loads(nodes["op:bcftools_plot"]["properties"]["output_specs_json"])
        self.assertEqual(plot_specs[0]["data_type_id"], "data:quality_distribution_plot")
        intersect_specs = json.loads(nodes["op:bedtools_intersect"]["properties"]["output_specs_json"])
        self.assertTrue(any(x.get("role") == "intersection_50" and
                            x.get("data_type_id") == "data:intersected_regions" and
                            x.get("condition") == "使用 -f 0.5 指定最小重叠比例时"
                            for x in intersect_specs))


if __name__ == "__main__":
    unittest.main()
