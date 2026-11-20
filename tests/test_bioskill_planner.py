"""Offline regression of read-only retrieval and evidence planning (no API keys)."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bioskill_planner.graph import Graph
from bioskill_planner.index import SemanticIndex,VectorEncoder,operation_views
from bioskill_planner.query import heuristic_parse,match_input_types
from bioskill_planner.retrieve import retrieve_operations,expand_candidates
from bioskill_planner.jev import rerank_operations
from bioskill_planner.workflow import WorkflowSearch
from bioskill_planner.evidence import enrich_paths,render_markdown
from bioskill_planner.cli import main

GRAPH=Path(__file__).resolve().parents[1]/'data/bio_skill_kg/v56_picard_fresh_test/all7_fresh.json'

class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph=Graph.from_json(GRAPH)
        cls.index=SemanticIndex.build(cls.graph,backend='lexical')

    def test_loaded_full_graph(self):
        self.assertEqual(len(self.graph.nodes),145)
        self.assertEqual(len(self.graph.operations),28)
        self.assertEqual(len(self.graph.edges),244)

    def test_three_operation_views_and_auxiliary_datatypes(self):
        views=[x['view'] for x in operation_views(self.graph) if x['id']=='op:markduplicates']
        self.assertEqual(set(views),{'purpose','scenario','io'})
        self.assertIn('datatype',[x['view'] for x in self.index.entries])

    def test_index_roundtrip_and_snapshot_safety(self):
        with tempfile.TemporaryDirectory() as folder:
            self.index.save(folder)
            reloaded=SemanticIndex.load(folder,self.graph)
            self.assertEqual(len(reloaded.entries),len(self.index.entries))
            modified=copy.deepcopy(self.graph.raw)
            modified['nodes'][0]['properties']['name']='changed'
            with self.assertRaises(ValueError):SemanticIndex.load(folder,Graph(modified))

    def test_search_retrieves_wgs_and_bam_sorting(self):
        data=heuristic_parse('我有未排序的BAM，希望进行重复标记然后计算全基因组测序指标')
        rows=retrieve_operations(self.graph,self.index,data,top_k=12)
        ops={r['operation_id'] for r in rows}
        self.assertIn('op:collectwgsmetrics',ops)
        self.assertTrue({'op:sortsam','op:samtools_sort'} & ops)

    def test_directional_type_check(self):
        self.assertTrue(self.graph.compatible('data:aligned_reads_bam_sorted','data:aligned_reads_bam',['BAM'],['BAM']))
        self.assertFalse(self.graph.compatible('data:aligned_reads_bam_unsorted','data:aligned_reads_bam_sorted',['BAM'],['BAM']))
        self.assertFalse(self.graph.compatible('data:aligned_reads_bam_sorted','data:aligned_reads_bam_sorted',['BAM'],['SAM']))

    def test_pending_link_not_certified(self):
        self.assertEqual(self.graph.has_type_link('op:markduplicates','op:collectwgsmetrics'),[])
        links=self.graph.has_type_link('op:markduplicates','op:collectwgsmetrics',include_pending=True)
        self.assertTrue(any(x['status']=='pending_review' for x in links))

    def test_sample_workflow_preserves_missing_reference_and_pending(self):
        result=WorkflowSearch(self.graph,set(self.graph.operations),max_steps=6).search(
            ['op:collectwgsmetrics'],['data:aligned_reads_bam_unsorted'])[0]
        self.assertEqual(result['steps'][-1],'op:collectwgsmetrics')
        self.assertIn('op:markduplicates',result['steps'])
        self.assertTrue('op:sortsam' in result['steps'] or 'op:samtools_sort' in result['steps'])
        self.assertIn('pending_review',{e['status'] for e in result['links']})
        self.assertTrue(any('参考基因组' in (m.get('input') or '') for m in result['missing_requirements']))
        self.assertFalse(result['ready_to_execute'])

    def test_bam_initial_type_not_overgeneralized(self):
        unsorted=match_input_types(self.graph,[],question='我有未排序的BAM，希望做重复标记',allow_guess=True)
        self.assertEqual(unsorted[0]['type_id'],'data:aligned_reads_bam_unsorted')
        self.assertFalse(self.graph.compatible(unsorted[0]['type_id'],'data:aligned_reads_bam_sorted'))

    def test_verified_sort_link(self):
        links=self.graph.has_type_link('op:samtools_sort','op:markduplicates')
        self.assertTrue(any(l['status']=='curated' for l in links))

    def test_jev_off_and_missing_key_fail_open(self):
        v=[{'operation_id':'op:markduplicates','score':0.4}]
        self.assertEqual(rerank_operations(self.graph,'duplicate',v,'off')[0],v)
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':''}):
            unchanged,meta=rerank_operations(self.graph,'duplicate',v,'rerank')
        self.assertEqual(unchanged,v)
        self.assertFalse(meta['called'])

    def test_graph_expansion_separate_documentary_hints(self):
        nodes,hints=expand_candidates(self.graph,['op:sortsam'])
        self.assertIn('op:markduplicates',nodes)
        self.assertTrue(all(h['status']=='documentary_only' for h in hints))

    def test_report_contains_citations_and_command_but_no_execution(self):
        results=WorkflowSearch(self.graph,set(self.graph.operations)).search(
            ['op:collectwgsmetrics'],['data:aligned_reads_bam_unsorted'])
        complete=enrich_paths(self.graph,results)
        md=render_markdown({'question':'测试','graph_digest':self.graph.digest,'workflows':complete})
        self.assertIn('picard_skill.md',md)
        self.assertIn('java -Xmx',md)
        self.assertIn('pending_review',md)
        self.assertIn('未执行科研工具',md)

    def test_cli_index_query_offline(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(main(['index','--backend','lexical','--graph',str(GRAPH),'--index-dir',str(Path(d)/'idx')]),0)
            report=Path(d)/'report.json'
            self.assertEqual(main(['query','--graph',str(GRAPH),'--index-dir',str(Path(d)/'idx'),
                '--question','我有未排序BAM，先去重再计算WGS指标',
                '--goal-op','op:collectwgsmetrics','--input-type','data:aligned_reads_bam_unsorted',
                '--output',str(Path(d)/'report.md'),'--json-output',str(report)]),0)
            out=json.loads(report.read_text(encoding='utf8'))
            self.assertEqual(out['selected_goals'],['op:collectwgsmetrics'])
            self.assertFalse(out['execution_performed'])

if __name__=='__main__':unittest.main()
