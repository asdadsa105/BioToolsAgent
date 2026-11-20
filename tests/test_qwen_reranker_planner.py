"""Local-Qwen adapter regression without downloading/loading model weights."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bioskill_planner.graph import Graph
from bioskill_planner.qwen_reranker import (
    operation_document, query_facets, rerank_operations_qwen,
    validate_local_model_path, score_pairs_local,
)
from bioskill_planner.cli import main

GRAPH = Path(__file__).resolve().parents[1] / 'data/bio_skill_kg/v56_picard_fresh_test/all7_fresh.json'


class QwenRerankerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = Graph.from_json(GRAPH)

    def setUp(self):
        self.candidates = [
            {'operation_id': 'op:samtools_index', 'score': 0.73},
            {'operation_id': 'op:sortsam', 'score': 0.71},
            {'operation_id': 'op:markduplicates', 'score': 0.50},
        ]
        self.parsed = {
            'subgoals': ['对 BAM 排序', '标记 PCR 重复'],
            'input_descriptions': ['未排序BAM'],
        }

    def test_operation_document_has_provenance_content_and_port_status(self):
        text = operation_document(self.graph, 'op:markduplicates')
        self.assertIn('MarkDuplicates', text)
        self.assertIn('已排序BAM', text)
        self.assertIn('pending_review', text)
        self.assertNotIn('java -Xmx', text)

    def test_query_facets_preserves_subgoals(self):
        result = query_facets('用户问题', self.parsed)
        self.assertEqual(result, ['用户问题', '对 BAM 排序', '标记 PCR 重复'])

    def test_qwen_shadow_evaluates_but_does_not_reorder(self):
        calls = []
        def fake_score(model_path, pairs, **kwargs):
            calls.extend(pairs)
            # each of 3 candidates gets original + 2 subgoal queries
            return [0.1,0.1,0.1, 0.4,0.6,0.6, 0.2,0.95,0.99]
        ranked,meta = rerank_operations_qwen(
            self.graph,'用户问题',self.parsed,self.candidates,
            mode='shadow',model_path='not-real',scorer=fake_score)
        self.assertEqual(ranked, self.candidates)
        self.assertEqual(len(calls),9)
        self.assertEqual(meta['ranked_operation_ids'][0],'op:markduplicates')
        self.assertEqual(meta['scores']['op:markduplicates'],0.99)
        self.assertFalse(meta['applied'])

    def test_qwen_rerank_returns_order_and_never_drops_prerequisites(self):
        def scorer(*args,**kwargs):
            return [0.1,0.1,0.1, 0.4,0.6,0.6, 0.2,0.95,0.99]
        ranked,meta = rerank_operations_qwen(
            self.graph,'用户问题',self.parsed,self.candidates,
            mode='rerank',model_path='not-real',scorer=scorer)
        self.assertEqual([c['operation_id'] for c in ranked],
                         ['op:markduplicates','op:sortsam','op:samtools_index'])
        self.assertTrue(meta['applied'])
        self.assertEqual(len(ranked),len(self.candidates))

    def test_qwen_bad_scores_fail_loudly(self):
        with self.assertRaisesRegex(ValueError,'评分'):
            rerank_operations_qwen(
                self.graph,'用户问题',self.parsed,self.candidates,
                mode='rerank',scorer=lambda *a,**k:[0.5])
        with self.assertRaisesRegex(ValueError,'无效'):
            rerank_operations_qwen(
                self.graph,'用户问题',self.parsed,self.candidates,
                mode='rerank',scorer=lambda *a,**k:[float('nan')]*9)

    def test_path_validation_offline_and_no_download(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(FileNotFoundError,'config.json'):
                validate_local_model_path(folder)
            root=Path(folder)
            (root/'config.json').write_text('{}')
            (root/'tokenizer.json').write_text('{}')
            (root/'model.safetensors').write_text('fake weights')
            self.assertEqual(validate_local_model_path(folder),root)

    def test_qwen_cli_shadow_and_rerank_use_local_adapter_and_json_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('bioskill_planner.cli.rerank_operations_qwen') as mocked:
                def use_test_scorer(graph,question,parsed,candidates,**kwargs):
                    return rerank_operations_qwen(
                        graph,question,parsed,candidates,**kwargs,
                        scorer=lambda m,pairs,**k: [0.99 if 'MarkDuplicates' in doc else 0.10
                          for _,doc in pairs]
                    )
                mocked.side_effect=use_test_scorer
                idx=Path(folder)/'idx'
                self.assertEqual(main(['index','--backend','lexical',
                    '--graph',str(GRAPH),'--index-dir',str(idx)]),0)
                out_shadow=Path(folder)/'shadow.json'
                base=['query','--graph',str(GRAPH),'--index-dir',str(idx),
                      '--question','我有未排序BAM，先去重再计算WGS指标',
                      '--goal-op','op:collectwgsmetrics',
                      '--input-type','data:aligned_reads_bam_unsorted',
                      '--qwen-model','test-model',
                      '--output',str(Path(folder)/'out.md')]
                self.assertEqual(main(base+['--qwen','shadow','--json-output',str(out_shadow)]),0)
                shadow=json.loads(out_shadow.read_text(encoding='utf-8'))
                self.assertTrue(shadow['qwen']['called'])
                self.assertFalse(shadow['qwen']['applied'])
                self.assertTrue(shadow['qwen']['scores'])
                self.assertEqual(shadow['jev']['mode'],'off')
                self.assertFalse(shadow['execution_performed'])
                out_rerank=Path(folder)/'rerank.json'
                self.assertEqual(main(base+['--qwen','rerank','--json-output',str(out_rerank)]),0)
                rerank=json.loads(out_rerank.read_text(encoding='utf-8'))
                self.assertTrue(rerank['qwen']['applied'])
                self.assertGreater(rerank['effective_operation_scores']['op:markduplicates'],
                    shadow['effective_operation_scores']['op:markduplicates'])
                self.assertEqual(rerank['workflows'][0]['steps'],shadow['workflows'][0]['steps'])
                self.assertIn('pending_review',{x['status'] for x in rerank['workflows'][0]['links']})
                self.assertIn('Qwen3-Reranker', (Path(folder)/'out.md').read_text(encoding='utf-8'))

    def test_cli_rejects_both_decision_services(self):
        with tempfile.TemporaryDirectory() as folder:
            idx=Path(folder)/'idx'
            self.assertEqual(main(['index','--backend','lexical','--graph',str(GRAPH),
                                   '--index-dir',str(idx)]),0)
            with self.assertRaisesRegex(ValueError,'one reranker'):
                main(['query','--graph',str(GRAPH),'--index-dir',str(idx),
                      '--question','BAM sort', '--qwen','rerank','--jev','shadow'])

    def test_qwen_check_standalone_without_graph(self):
        with patch('bioskill_planner.cli.score_pairs_local',return_value=[0.98,0.04]) as mocked:
            self.assertEqual(main(['qwen-check','--qwen-model','dummy','--qwen-device','cpu']),0)
            self.assertEqual(mocked.call_count,1)
            self.assertEqual(mocked.call_args.args[0],'dummy')

if __name__ == '__main__':
    unittest.main()
