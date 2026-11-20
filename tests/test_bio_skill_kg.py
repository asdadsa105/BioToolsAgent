import unittest
from pathlib import Path
from text_ingestion.document_loader import load_documents
from bio_skill_kg.builder import build_graph, summary

BASE=Path(__file__).resolve().parents[1]

class BioSkillKGTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph=build_graph(load_documents(BASE/'examples'/'bio_skills'))
        cls.nodes={n['id']:n for n in cls.graph['nodes']}
        cls.edges={(e['source'],e['type'],e['target']) for e in cls.graph['edges']}

    def test_four_full_tools(self):
        for k in ['bwa','bcftools','bedtools','annovar']:
            self.assertEqual(self.nodes[f'tool:{k}']['label'],'Tool')
            self.assertFalse(self.nodes[f'tool:{k}']['properties'].get('stub',False))

    def test_operations(self):
        for x in ['bcftools_filter','bcftools_stats','bcftools_merge','bcftools_view',
                  'bwa_mem','table_annovar.pl','bedtools_intersect','bedtools_merge','bedtools_coverage']:
            self.assertIn(f'op:{x}',self.nodes)

    def test_filter_semantics(self):
        self.assertIn(('op:bcftools_filter','REQUIRES_INPUT','data:variant_calls'),self.edges)
        self.assertIn(('op:bcftools_filter','PRODUCES','data:filtered_variant_calls'),self.edges)
        self.assertIn(('data:filtered_variant_calls','IS_SUBTYPE_OF','data:variant_calls'),self.edges)

    def test_resource_values(self):
        bwa=self.nodes['tool:bwa']['properties']
        self.assertEqual(bwa['memory_gb_recommended'],16)
        self.assertEqual(bwa['cpu_cores_recommended'],8)

    def test_no_unverified_shortcut(self):
        self.assertNotIn(('op:bwa_mem','PRODUCES','data:variant_calls'),self.edges)

    def test_unique_nodes_and_edges(self):
        self.assertEqual(len(self.nodes),len(self.graph['nodes']))
        self.assertEqual(len(self.edges),len(self.graph['edges']))

if __name__=='__main__': unittest.main()
