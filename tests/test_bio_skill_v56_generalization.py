"""Tool-agnostic v5.6 regression tests: FASTQ states, candidate identity, scenarios."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bio_skill_kg.auto_builder import (
    _resolve_data_type_keys, build_graph_from_extractions,
    load_data_type_ontology, load_ontology_aliases, load_file_format_ontology)
from bio_skill_kg.scenario_parser import source_application_scenarios
from bio_skill_kg.semantic_normalization import candidate_id, semantic_facets
from check_bioskill_ports import inspect_graph


class GeneralizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ontology = load_data_type_ontology()
        cls.aliases = load_ontology_aliases()
        cls.formats = load_file_format_ontology()

    def resolve(self, name, description, formats):
        return _resolve_data_type_keys(name, description, formats,
                                       self.ontology, self.aliases, self.formats)[0]

    def test_plain_fastq_reads_are_approved(self):
        self.assertEqual(self.resolve('测序读段序列', '双端FASTQ测序读段', ['FASTQ', 'FASTQ.gz']), ['short_reads'])

    def test_processed_fastq_is_distinct_curated_subtype(self):
        self.assertEqual(self.resolve('处理后序列', '处理后的R1文件', ['FASTQ.gz']), ['processed_short_reads'])
        self.assertEqual(self.ontology['processed_short_reads']['parent'], 'short_reads')

    def test_qc_html_json_are_distinct(self):
        self.assertEqual(self.resolve('质控报告', '包含过滤结果的报告', ['HTML']), ['quality_control_report'])
        self.assertEqual(self.resolve('质控数据', '机器可读统计数据', ['JSON']), ['quality_control_metrics'])
        self.assertEqual(self.resolve('质控报告', '报告', ['JSON']), [])

    def test_unrelated_fastq_format_only_is_not_autotyped(self):
        self.assertEqual(self.resolve('FASTQ', '仅为文件格式', ['FASTQ']), [])
        self.assertEqual(self.resolve('未知信息', '任意二进制数据', ['FASTQ']), [])

    def test_duplicate_candidate_ids_do_not_depend_on_description_or_role(self):
        one = candidate_id('标记重复后的序列比对结果', 'dedup.bam output', ['BAM'])
        two = candidate_id('标记重复后的序列比对结果', '用于下游指标统计的输入 BAM', ['BAM'])
        self.assertEqual(one, two)
        diff = candidate_id('标记重复后的序列比对结果', 'SAM格式', ['SAM'])
        self.assertNotEqual(one, diff)

    def test_unknown_processing_state_still_pending(self):
        self.assertEqual(self.resolve('纳米孔特殊信号数据', '某类新传感信号', ['FASTQ']), [])

    def test_extracts_three_document_scenarios_with_commands(self):
        content = '''## 7. 使用场景模板
### 7.1 场景1: RNA-seq数据质控
**适用场景**: RNA质控
**输入数据**: 双端FASTQ
**推荐参数**:
```bash
fastp --in1 a.fq.gz --in2 b.fq.gz --cut_front 10
```
**预期输出**:
- 过滤后的FASTQ
### 7.2 场景2: WGS数据质控
**适用场景**: 全基因组质控
```bash
fastp --in1 a.fq.gz --cut_front 5
```
### 7.3 场景3: ChIP-seq数据质控
```bash
fastp --in1 a.fq.gz --cut_front 15
```
'''
        result = source_application_scenarios(content, 'fastp', 'fastp_skill.md')
        self.assertEqual(len(result), 3)
        self.assertEqual(len({s['scenario_id'] for s in result}), 3)
        self.assertEqual([s['name'] for s in result],
                         ['RNA-seq数据质控', 'WGS数据质控', 'ChIP-seq数据质控'])
        self.assertIn('--cut_front 10', result[0]['recommended_command'])
        self.assertEqual(source_application_scenarios(content, 'samtools sort', 'fastp_skill.md'), [])

    def test_candidate_states_still_unique(self):
        self.assertNotEqual(candidate_id('比对结果','已排序BAM', ['BAM']),
                            candidate_id('比对结果','未排序BAM', ['BAM']))


if __name__ == '__main__':
    unittest.main()

class CompatibilityTests(unittest.TestCase):
    def test_subtype_matches_base_without_fake_direct_edge(self):
        from check_bioskill_compatibility import potential_connections
        producer={'id':'op:producer','label':'Operation','properties':{
            'output_specs_json':json.dumps([{'data_type_id':'data:processed_short_reads',
                                             'formats':['FASTQ_GZ'],'resolution_status':'curated','role':'out1'}])}}
        consumer={'id':'op:consumer','label':'Operation','properties':{
            'input_specs_json':json.dumps([{'data_type_id':'data:short_reads',
                                            'formats':['FASTQ','FASTQ_GZ'],'resolution_status':'curated','role':'in1'}])}}
        graph={'nodes':[producer,consumer], 'edges':[
            {'source':'op:producer','type':'PRODUCES','target':'data:processed_short_reads'},
            {'source':'data:processed_short_reads','type':'IS_SUBTYPE_OF','target':'data:short_reads'},
            {'source':'op:consumer','type':'REQUIRES_INPUT','target':'data:short_reads'}]}
        links=potential_connections(graph,'op:producer','op:consumer')
        self.assertEqual(len(links),1)
        self.assertEqual(links[0]['type_match'],'subtype')
        self.assertEqual(links[0]['common_formats'],['FASTQ_GZ'])
        self.assertFalse(links[0]['ready_to_execute'])
