import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from bio_skill_kg.auto_builder import build_graph_from_extractions, load_data_type_ontology
from bio_skill_kg.builder import merge_graphs
from bio_skill_kg.semantic_normalization import semantic_facets
from check_bioskill_ports import inspect_graph

class Document:
    file_path='generic_skill.md'
    doc_id='abc'
    content='**工具名称**: generic-tool\n## Usage\ncommand example\nSorted BAM input\nNew marked alignment BAM\nNew metrics data TXT\n'


def extraction(inputs, outputs):
    return {'tool':{'name':'generic-tool'},'resources':[],'tool_parameters':[],
            'operations':[{'name':'generic-op','description':'generic-op','task_name':'processing',
                           'inputs':inputs,'outputs':outputs,'parameters':[],
                           'evidence_quote':'command example'}],
            'data_types':[],'tool_relations':[],'quality_controls':[],'review':[]}

def port(name, fmt, description, quote):
    return {'data_type':name,'description':description,'formats':[fmt],'evidence_quote':quote}

class GenericSemanticTests(unittest.TestCase):
    def build(self, ontology=None):
        data=extraction([port('序列比对结果','BAM','已排序 BAM 输入','Sorted BAM input')],
                        [port('标记重复后的序列比对结果','BAM','新标记重复后 BAM','New marked alignment BAM'),
                         port('全新统计结果','TXT','新的数据质量统计表','New metrics data TXT')])
        return build_graph_from_extractions([Document()],[data],ontology=ontology)

    def test_states_differ_and_unsorted_does_not_imply_sorted(self):
        self.assertEqual(semantic_facets('BAM','unsorted BAM',['BAM'])['sorting_state'],'unsorted')
        self.assertEqual(semantic_facets('BAM','sorted BAM',['BAM'])['sorting_state'],'sorted')

    def test_unmapped_evidence_ports_are_retained_without_false_workflow_edges(self):
        g=self.build()
        op=next(n for n in g['nodes'] if n['id']=='op:generic-op')
        ins=json.loads(op['properties']['input_specs_json'])
        outs=json.loads(op['properties']['output_specs_json'])
        self.assertEqual(ins[0]['data_type_id'],'data:aligned_reads_bam_sorted')
        self.assertEqual(len(outs),2)
        self.assertTrue(all(o['resolution_status']=='pending_review' for o in outs))
        self.assertTrue(all(o.get('candidate_type_id') for o in outs))
        self.assertFalse(any(e['source']=='op:generic-op' and e['type']=='PRODUCES' for e in g['edges']))
        audit=inspect_graph(g)
        self.assertEqual(audit['total_ports'],3)
        self.assertEqual(audit['pending_ports'],2)
        self.assertFalse(audit['publish_ready'])

    def test_approved_new_type_is_reused_without_editing_builder(self):
        ontology=load_data_type_ontology()
        ontology['duplicate_marked_bam']={
          'name':'标记重复后的序列比对结果','description':'标记重复后的 BAM 比对结果',
          'formats':['BAM'],'parent':'aligned_reads_bam','aliases':[]}
        graph=self.build(ontology=ontology)
        op=next(n for n in graph['nodes'] if n['id']=='op:generic-op')
        outs=json.loads(op['properties']['output_specs_json'])
        self.assertEqual(outs[0]['data_type_id'],'data:duplicate_marked_bam')
        self.assertEqual(outs[0]['resolution_status'],'curated')
        self.assertIn(('op:generic-op','PRODUCES','data:duplicate_marked_bam'),
                      {(e['source'],e['type'],e['target']) for e in graph['edges']})
        self.assertEqual(inspect_graph(graph)['pending_ports'],1)

    def test_repeated_import_stays_idempotent(self):
        graph=self.build()
        self.assertEqual(merge_graphs(graph,graph),graph)

    def test_candidate_is_safely_promoted_in_merge(self):
        initial=self.build()
        ontology=load_data_type_ontology()
        ontology['duplicate_marked_bam']={
          'name':'标记重复后的序列比对结果','description':'标记重复后的 BAM 比对结果',
          'formats':['BAM'],'parent':'aligned_reads_bam','aliases':[]}
        upgraded=merge_graphs(initial,self.build(ontology=ontology))
        op=next(n for n in upgraded['nodes'] if n['id']=='op:generic-op')
        outputs=json.loads(op['properties']['output_specs_json'])
        duplicate=[x for x in outputs if x['raw_data_type']=='标记重复后的序列比对结果']
        self.assertEqual(len(duplicate),1)
        self.assertEqual(duplicate[0]['resolution_status'],'curated')

if __name__=='__main__':unittest.main()
