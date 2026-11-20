import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from text_ingestion.document_loader import load_documents
from bio_skill_kg.llm_extractor import (
    ExtractionChunk,
    apply_source_grounded_completions,
)
from bio_skill_kg.validator import validate_chunk_extraction
from bio_skill_kg.auto_builder import (
    build_graph_from_extractions,
    load_data_type_ontology,
    load_ontology_aliases,
    load_file_format_ontology,
    _resolve_data_type_keys,
)


class BioSkillV51CriticalFixTests(unittest.TestCase):
    def source(self, name):
        return load_documents(ROOT / "examples" / "bio_skills" / name)[0]

    def test_operation_command_can_support_output_flag(self):
        command = "bcftools filter -o filtered.vcf.gz input.vcf.gz"
        text = command + "\n过滤后的变异文件(filtered.vcf.gz)"
        chunk = ExtractionChunk("c1", text, "filter", 0, len(text), 1, 2)
        obj = {
            "tool": {}, "resources": [], "tool_parameters": [],
            "operations": [{
                "name": "bcftools filter", "description": "过滤变异",
                "task_name": "变异过滤", "evidence_quote": command,
                "inputs": [],
                "outputs": [{
                    "data_type": "过滤后变异数据", "formats": ["VCF_GZ"],
                    "flag": "-o", "required": None,
                    "evidence_quote": "过滤后的变异文件(filtered.vcf.gz)",
                }],
                "parameters": [], "scenarios": [],
            }],
            "data_types": [], "tool_relations": [], "quality_controls": [],
        }
        clean, issues = validate_chunk_extraction(obj, chunk, "bcftools_skill.md")
        output = clean["operations"][0]["outputs"][0]
        self.assertEqual(output["flag"], "-o")
        self.assertEqual(output["flag_evidence_quote"], command)
        self.assertFalse(any("端口 flag" in x.get("reason", "") for x in issues))

    def test_bwa_reads_resolve_to_curated_short_reads_type(self):
        ontology = load_data_type_ontology()
        aliases = load_ontology_aliases()
        formats = load_file_format_ontology()
        resolved, is_format = _resolve_data_type_keys(
            "测序读段", "单端或双端测序数据", ["FASTQ", "FASTQ_GZ"],
            ontology, aliases, formats,
        )
        self.assertEqual(resolved, ["short_reads"])
        self.assertFalse(is_format)

    def test_source_grounded_repairs_cover_required_operations(self):
        # ANNOVAR
        annovar = self.source("annovar_skill.md")
        annovar_ex = {"operations": [{
            "name": "annotate_variation.pl", "description": "下载注释数据库",
            "task_name": "下载注释数据库", "evidence_quote":
                "annotate_variation.pl -buildver hg19 -downdb -webfrom annovar refGene humandb/",
            "inputs": [], "outputs": [], "parameters": [], "scenarios": [],
        }]}
        annovar_fixed = apply_source_grounded_completions(annovar_ex, annovar.content, "annovar_skill.md")
        annovar_op = annovar_fixed["operations"][0]
        self.assertTrue(any(x["data_type"] == "ANNOVAR注释数据库" for x in annovar_op["outputs"]))

        # BCFtools gtcheck and view scenario separation
        bcftools = self.source("bcftools_skill.md")
        bcftools_ex = {"operations": [
            {"name": "bcftools gtcheck", "evidence_quote":
             "bcftools gtcheck \\\n  -g input.vcf.gz \\\n  -s samples.txt \\\n  -o genotype_check.txt",
             "inputs": [{"data_type": "变异检测结果", "role": "input_variants", "flag": "-g",
                         "required": True, "formats": ["VCF_GZ"],
                         "evidence_quote": "bcftools gtcheck \\\n  -g input.vcf.gz \\\n  -s samples.txt \\\n  -o genotype_check.txt"}],
             "outputs": [{"data_type": "基因型检查结果", "role": "genotype_check_output", "flag": "-o",
                          "formats": ["TXT"], "evidence_quote": "-o genotype_check.txt"}],
             "parameters": [], "scenarios": []},
            {"name": "bcftools view", "evidence_quote": "bcftools view \\\n  -s sample1,sample2 \\\n  -o samples_subset.vcf.gz \\\n  -O z \\\n  input.vcf.gz",
             "inputs": [], "outputs": [], "parameters": [], "scenarios": []},
        ]}
        bcftools_fixed = apply_source_grounded_completions(bcftools_ex, bcftools.content, "bcftools_skill.md")
        gtcheck = next(x for x in bcftools_fixed["operations"] if x["name"] == "bcftools gtcheck")
        self.assertTrue(any(x.get("role") == "sample_list" and x.get("flag") == "-s"
                            for x in gtcheck["inputs"]))
        view = next(x for x in bcftools_fixed["operations"] if x["name"] == "bcftools view")
        self.assertEqual({x.get("scenario_id") for x in view["outputs"]},
                         {"sample_subset", "single_sample_split"})
        self.assertEqual({x.get("scenario_id") for x in view["inputs"]},
                         {"sample_subset", "single_sample_split"})

        # BEDtools direct genomecov output and documented batch unionbedg scenario
        bedtools = self.source("bedtools_skill.md")
        bedtools_ex = {"operations": [
            {"name": "bedtools genomecov", "evidence_quote":
             "bedtools genomecov \\\n  -ibam alignments.bam \\\n  -bga",
             "inputs": [], "outputs": [], "parameters": [], "scenarios": []},
            {"name": "bedtools unionbedg", "evidence_quote":
             "bedtools unionbedg -i file1.bed file2.bed file3.bed > union.bed",
             "inputs": [], "outputs": [], "parameters": [], "scenarios": []},
        ]}
        bedtools_fixed = apply_source_grounded_completions(bedtools_ex, bedtools.content, "bedtools_skill.md")
        genomecov = next(x for x in bedtools_fixed["operations"] if x["name"] == "bedtools genomecov")
        self.assertEqual(genomecov["outputs"][0]["data_type"], "信号轨道数据")
        self.assertIn("BEDGRAPH", genomecov["outputs"][0]["formats"])
        union = next(x for x in bedtools_fixed["operations"] if x["name"] == "bedtools unionbedg")
        self.assertEqual(union["inputs"][0]["min_occurs"], 2)
        self.assertEqual(union["outputs"][0]["data_type"], "多样本覆盖度结果")

    def test_bwa_all_documented_scenarios_have_read_ports_and_sam_output(self):
        bwa = self.source("bwa_skill.md")
        command = "bwa mem -t 4 reference_index input.fq.gz > output.sam"
        bwa_ex = {"operations": [{
            "name": "bwa mem", "description": "序列比对", "task_name": "序列比对",
            "evidence_quote": command,
            "inputs": [
                {"data_type": "参考基因组索引", "role": "reference_index", "required": True,
                 "formats": [], "evidence_quote": "reference_index"},
                {"data_type": "测序读段", "role": "read1", "required": True,
                 "formats": ["FASTQ_GZ"], "scenario_id": "wgs",
                 "evidence_quote": "sample1_1.fq.gz sample1_2.fq.gz"},
                {"data_type": "测序读段", "role": "read2", "required": True,
                 "formats": ["FASTQ_GZ"], "scenario_id": "wgs",
                 "evidence_quote": "sample1_1.fq.gz sample1_2.fq.gz"},
                {"data_type": "测序读段", "role": "read1", "required": True,
                 "formats": ["FASTQ_GZ"], "scenario_id": "single_end",
                 "evidence_quote": "bwa mem -t 4 reference_index input.fq.gz > output.sam"},
            ],
            "outputs": [], "parameters": [], "scenarios": [],
        }]}
        fixed = apply_source_grounded_completions(bwa_ex, bwa.content, "bwa_skill.md")
        op = fixed["operations"][0]
        input_scenarios = {(x.get("scenario_id"), x.get("role")) for x in op["inputs"]}
        for scenario in ("wgs", "exome", "target_region"):
            self.assertIn((scenario, "read1"), input_scenarios)
            self.assertIn((scenario, "read2"), input_scenarios)
        self.assertIn(("single_end", "read1"), input_scenarios)
        self.assertTrue(any(x.get("scenario_id") == "single_end" and "SAM" in x.get("formats", [])
                            for x in op["outputs"]))

    def test_repaired_graph_has_short_reads_database_and_signal_track_ports(self):
        files = ["annovar_skill.md", "bedtools_skill.md", "bwa_skill.md"]
        docs = [self.source(name) for name in files]
        extractions = []
        for doc, name in zip(docs, files):
            if name == "annovar_skill.md":
                ops = [{"name": "annotate_variation.pl", "description": "下载数据库",
                        "task_name": "下载数据库",
                        "evidence_quote": "annotate_variation.pl -buildver hg19 -downdb -webfrom annovar refGene humandb/",
                        "inputs": [], "outputs": [], "parameters": [], "scenarios": []}]
            elif name == "bedtools_skill.md":
                ops = [{"name": "bedtools genomecov", "description": "覆盖度信号输出",
                        "task_name": "覆盖度分析",
                        "evidence_quote": "bedtools genomecov \\\n  -ibam alignments.bam \\\n  -bga",
                        "inputs": [{"data_type": "序列比对结果", "role": "alignments", "flag": "-ibam",
                                    "required": True, "min_occurs": 1, "max_occurs": 1,
                                    "formats": ["BAM"], "evidence_quote": "bedtools genomecov \\\n  -ibam alignments.bam"}],
                        "outputs": [], "parameters": [], "scenarios": []}]
            else:
                ops = [{"name": "bwa mem", "description": "序列比对", "task_name": "序列比对",
                        "evidence_quote": "bwa mem -t 4 reference_index input.fq.gz > output.sam",
                        "inputs": [{"data_type": "测序读段", "role": "read1", "required": True,
                                    "formats": ["FASTQ_GZ"], "scenario_id": "single_end",
                                    "evidence_quote": "bwa mem -t 4 reference_index input.fq.gz > output.sam"}],
                        "outputs": [], "parameters": [], "scenarios": []}]
            fixed = apply_source_grounded_completions({"operations": ops}, doc.content, name)
            extractions.append({
                "tool": {"name": name.replace("_skill.md", "")},
                "resources": [], "tool_parameters": [], "operations": fixed["operations"],
                "data_types": [], "tool_relations": [], "quality_controls": [], "review": [],
            })
        graph = build_graph_from_extractions(docs, extractions)
        nodes = {x["id"]: x for x in graph["nodes"]}
        self.assertIn("data:short_reads", nodes)
        self.assertIn("data:annotation_database", nodes)
        self.assertIn("data:signal_tracks", nodes)
        operations = {x["id"]: x["properties"] for x in graph["nodes"] if x["label"] == "Operation"}
        bwa_inputs = json.loads(operations["op:bwa_mem"]["input_specs_json"])
        self.assertTrue(any(x.get("data_type_id") == "data:short_reads" for x in bwa_inputs))
        genomecov_outputs = json.loads(operations["op:bedtools_genomecov"]["output_specs_json"])
        self.assertTrue(any(x.get("data_type_id") == "data:signal_tracks" for x in genomecov_outputs))
        annovar_outputs = json.loads(operations["op:annotate_variation.pl"]["output_specs_json"])
        self.assertTrue(any(x.get("data_type_id") == "data:annotation_database" for x in annovar_outputs))


if __name__ == "__main__":
    unittest.main()
