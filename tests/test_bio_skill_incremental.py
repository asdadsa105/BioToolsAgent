import json
import unittest
from pathlib import Path
from text_ingestion.document_loader import load_documents
from bio_skill_kg.builder import build_graph, merge_graphs, summary, load_aliases
from import_bio_skill_neo4j import load_graph, make_node_batches, make_edge_batches

ROOT=Path(__file__).resolve().parents[1]
SKILLS=ROOT/'examples'/'bio_skills'


class IncrementalGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bwa=build_graph(load_documents(SKILLS/'bwa_skill.md'))
        cls.bcftools=build_graph(load_documents(SKILLS/'bcftools_skill.md'))
        cls.annovar=build_graph(load_documents(SKILLS/'annovar_skill.md'))
        cls.bedtools=build_graph(load_documents(SKILLS/'bedtools_skill.md'))

    def _node(self,graph,nid):
        return next(n for n in graph['nodes'] if n['id']==nid)

    def test_stub_replaced_when_full_skill_arrives(self):
        placeholder=self._node(self.bwa,'tool:bcftools')
        self.assertTrue(placeholder['properties']['stub'])
        merged=merge_graphs(self.bwa,self.bcftools)
        full=self._node(merged,'tool:bcftools')
        self.assertFalse(full['properties']['stub'])
        self.assertEqual(full['properties']['version'],'1.17')
        self.assertTrue(any(e['source']=='tool:bwa' and e['target']=='tool:bcftools'
                            for e in merged['edges']))

    def test_two_documents_connect_same_tool(self):
        g=merge_graphs(merge_graphs(self.bwa,self.bcftools),self.annovar)
        self.assertEqual(sum(n['id']=='tool:bcftools' for n in g['nodes']),1)
        paths={(e['source'],e['type'],e['target']) for e in g['edges']}
        self.assertIn(('tool:bcftools','DOCUMENTED_DOWNSTREAM','tool:annovar'),paths)
        self.assertIn(('tool:bcftools','RECOMMENDED_BEFORE','tool:annovar'),paths)
        self.assertFalse(self._node(g,'tool:annovar')['properties']['stub'])

    def test_sequence_matches_all_at_once(self):
        sequence=merge_graphs(merge_graphs(merge_graphs(self.bwa,self.bcftools),self.annovar),self.bedtools)
        together=build_graph(sum((load_documents(SKILLS/f) for f in ('bwa_skill.md','bcftools_skill.md','annovar_skill.md','bedtools_skill.md')),[]))
        self.assertEqual(summary(sequence)['nodes'],summary(together)['nodes'])
        self.assertEqual(summary(sequence)['edges'],summary(together)['edges'])
        self.assertEqual(set(n['id'] for n in sequence['nodes']), set(n['id'] for n in together['nodes']))

    def test_repeated_import_is_idempotent(self):
        once=merge_graphs(self.bwa,self.bcftools)
        twice=merge_graphs(once,self.bcftools)
        self.assertEqual(once,twice)

    def test_legacy_v1_graph_can_upgrade(self):
        v1=dict(self.bwa)
        v1['schema']='BioSkillKG-v1'
        v1.pop('metadata',None)
        upgraded=merge_graphs(v1,self.bcftools)
        self.assertEqual(upgraded['schema'],'BioSkillKG-v2')
        self.assertFalse(self._node(upgraded,'tool:bcftools')['properties']['stub'])

    def test_aliases_only_use_explicit_dictionary(self):
        aliases=load_aliases()
        self.assertEqual(aliases['burrows-wheeler aligner'],'bwa')
        self.assertEqual(aliases['bedtools2'],'bedtools')
        self.assertNotIn('hisat2', aliases)

    def test_original_sources_retained(self):
        combined=merge_graphs(self.bwa,self.bcftools)
        source=next(e for e in combined['edges'] if e['source']=='tool:bwa' and e['target']=='tool:bcftools')
        self.assertIn('bwa_skill.md',source['properties']['source_files'])
        self.assertIn('bwa_skill.md §6.2',source['properties']['source_sections'])

    def test_neo4j_payload_clears_stale_stub(self):
        combined=merge_graphs(self.bwa,self.bcftools)
        prepared=make_node_batches(combined)
        full=next(row for row in prepared['Tool'] if row['id']=='tool:bcftools')
        self.assertIs(full['props']['stub'],False)
        self.assertEqual(full['props']['id'],'tool:bcftools')
        self.assertGreater(len(make_edge_batches(combined)),1)

    def test_conflict_review_and_explicit_policy(self):
        original=build_graph(load_documents(SKILLS/'bcftools_skill.md'))
        changed=json.loads(json.dumps(original))
        for n in changed['nodes']:
            if n['id']=='tool:bcftools':
                n['properties']['version']='9.99'
        keep=merge_graphs(original,changed)
        override=merge_graphs(original,changed,conflict_policy='prefer-incoming')
        self.assertEqual(self._node(keep,'tool:bcftools')['properties']['version'],'1.17')
        self.assertEqual(self._node(override,'tool:bcftools')['properties']['version'],'9.99')
        self.assertTrue(any(r.get('field')=='version' for r in keep['review']))


if __name__=='__main__':
    unittest.main()
