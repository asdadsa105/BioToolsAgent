"""Local Qwen3-Reranker for Operation-level ranking; never executes a tool.

Uses the official Qwen3-Reranker yes/no *next token logits* recipe, NOT
text generation or an untrained generic embedding. Only Hugging Face-format
weights on the local filesystem are accepted (no automatic network fetch).
"""
from __future__ import annotations

import gc
import math
from pathlib import Path
from typing import Callable, Sequence

from .graph import Graph, json_value

DEFAULT_MODEL_PATH = r'D:\qwen3_reranker'
TASK_INSTRUCTION = (
    'Given a scientific workflow planning request, identify operations useful '
    'for the requested subtask, including required upstream transformations. '
    'Evaluate task relevance, not validated input/output compatibility or execution readiness.'
)
PREFIX = (
    '<|im_start|>system\n'
    'Judge whether the Document meets the requirements based on the Query and the Instruct provided. '
    'Note that the answer can only be "yes" or "no".'
    '<|im_end|>\n<|im_start|>user\n'
)
SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


def validate_local_model_path(model_path: str) -> Path:
    """Guard against surprising HF downloads or trying to load a GGUF as HF."""
    p = Path(model_path).expanduser()
    if not p.is_dir():
        raise FileNotFoundError(
            f'本地 Qwen 模型目录不存在：{model_path}。'
            ' 请检查 --qwen-model 参数；远程服务器上不能直接使用 Windows D: 路径。'
        )
    if not (p / 'config.json').is_file():
        raise FileNotFoundError(
            f'{p} 内没有 config.json；本模块需要 Hugging Face Transformers 格式，'
            '如果下载的是 GGUF 或 Ollama 文件，需要先换成相应格式。'
        )
    if not any(p.glob('*.safetensors')) and not any(p.glob('pytorch_model*.bin')):
        raise FileNotFoundError(
            f'{p} 中没有 safetensors/bin 权重文件。'
            ' 请确认模型下载完整，且传入的是模型根目录。'
        )
    if not (p / 'tokenizer.json').is_file() and not (p / 'tokenizer.model').is_file():
        raise FileNotFoundError(f'{p} 中没有 tokenizer.json 或 tokenizer.model，无法进行本地推理。')
    return p


def operation_document(graph: Graph, operation_id: str) -> str:
    """Produce a source-grounded candidate description with scenario and I/O state."""
    op = graph.get(operation_id)
    if not op:
        raise ValueError(f'Unknown Operation: {operation_id}')
    _, tool = graph.available_tool_info(operation_id)
    tasks = [graph.get(task).get('name', '') for task in graph.op_tasks.get(operation_id, [])]
    scenarios = json_value(op.get('scenarios_json'), [])
    scenario_names = [f"{s.get('name', '')}: {s.get('description', '')}" for s in scenarios if isinstance(s, dict)]
    def ports(direction: str) -> str:
        result = []
        for p in graph.operation_ports(operation_id, direction):
            if not (p.get('required', True) or direction == 'output'):
                continue
            d = p.get('data_type') or p.get('description') or ''
            desc = p.get('description') or ''
            fmt = ','.join(str(f) for f in (p.get('formats') or []))
            facets = p.get('semantic_facets') or {}
            status = p.get('resolution_status') or 'unknown'
            result.append(f'{d}; 描述:{desc}; 格式:{fmt}; 状态:{facets}; 类型审核:{status}')
        return ' | '.join(result)
    return '\n'.join([
        f"工具: {tool.get('name', '')}",
        f"操作: {op.get('name', '')} ({operation_id})",
        f"功能: {op.get('description', '')}",
        f"任务: {'; '.join(tasks)}",
        f"使用场景: {'; '.join(scenario_names[:4])}",
        f"必需输入: {ports('input')}",
        f"输出: {ports('output')}",
    ])[:3200]


def query_facets(question: str, parsed: dict | None, max_subgoals: int = 3) -> list[str]:
    """Use each subgoal separately so a low-similarity prerequisite can score."""
    facets = [str(question).strip()]
    if parsed:
        for s in list(parsed.get('subgoals') or [])[:max(0, max_subgoals)]:
            s = str(s).strip()
            if s and s not in facets:
                facets.append(s)
    return facets


def score_pairs_local(
    model_path: str,
    pairs: Sequence[tuple[str, str]],
    *, device: str = 'auto', batch_size: int = 1, max_length: int = 2048,
) -> list[float]:
    """P(yes | instructed query/document), as in the official Qwen model card.

    Deliberately no network access: local_files_only=True and a required path.
    """
    path = validate_local_model_path(model_path)
    if not pairs:
        return []
    if batch_size < 1:
        raise ValueError('Qwen batch_size 必须 >= 1')
    if max_length < 256:
        raise ValueError('Qwen max_length 必须 >= 256')
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
    except ImportError as exc:
        raise RuntimeError(
            '缺少 Qwen 推理依赖：pip install -r requirements_qwen_reranker.txt。'
            ' Qwen3 要求 transformers>=4.51.0。'
        ) from exc
    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    if device not in ('cuda', 'cpu'):
        raise ValueError('Qwen device 必须是 auto、cuda 或 cpu')
    if device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('当前 PyTorch 未检测到 CUDA。请安装 CUDA 版 PyTorch，或显式 --qwen-device cpu。')
    if device == 'cpu':
        # A 4B CPU fp32 model can take a lot of RAM; this is an explicit opt-in.
        print('[Qwen] 提示：使用 CPU 加载 4B 模型可能占用大量内存。')
    gc.collect()
    if device == 'cuda':
        torch.cuda.empty_cache()
    try:
        tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
        tokenizer.padding_side = 'left'
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        dtype = torch.bfloat16 if device == 'cuda' else torch.float32
        model = AutoModelForCausalLM.from_pretrained(
            str(path), local_files_only=True, trust_remote_code=False,
            torch_dtype=dtype, low_cpu_mem_usage=True,
        ).to(device).eval()
    except Exception as exc:
        raise RuntimeError(
            f'加载本地 Qwen3-Reranker 失败：{type(exc).__name__}: {exc}. '
            '请检查 transformers>=4.51、权重格式/完整性、PyTorch CUDA 与显存。'
        ) from exc
    try:
        yes = tokenizer('yes', add_special_tokens=False).input_ids
        no = tokenizer('no', add_special_tokens=False).input_ids
        if len(yes) != 1 or len(no) != 1:
            raise ValueError('Qwen3 Reranker 的 yes/no token 不是单 token；请确认加载的是 Qwen3-Reranker 模型。')
        prefix = tokenizer.encode(PREFIX, add_special_tokens=False)
        suffix = tokenizer.encode(SUFFIX, add_special_tokens=False)
        max_text_len = max_length - len(prefix) - len(suffix)
        if max_text_len < 64:
            raise ValueError('max_length 过小，无法容纳 Qwen3 系统提示')
        scores = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start:start + batch_size]
            texts = [f'<Instruct>: {TASK_INSTRUCTION}\n<Query>: {q}\n<Document>: {d}' for q,d in batch]
            tokenized = tokenizer(
                texts, padding=False, truncation=True, max_length=max_text_len,
                add_special_tokens=False,
            )
            input_ids = [prefix + seq + suffix for seq in tokenized['input_ids']]
            inputs = tokenizer.pad({'input_ids': input_ids}, padding=True, return_tensors='pt')
            inputs = {k: v.to(device) for k,v in inputs.items()}
            with torch.inference_mode():
                last_logits = model(**inputs).logits[:, -1, :]
                logits = torch.stack([last_logits[:, no[0]], last_logits[:, yes[0]]], dim=-1)
                batch_scores = torch.softmax(logits.float(), dim=-1)[:, 1].cpu().tolist()
            scores.extend(float(x) for x in batch_scores)
        return scores
    finally:
        del model
        gc.collect()
        if device == 'cuda':
            torch.cuda.empty_cache()


def rerank_operations_qwen(
    graph: Graph, question: str, parsed: dict, candidates: list[dict],
    *, mode: str = 'rerank', model_path: str = DEFAULT_MODEL_PATH,
    device: str = 'auto', batch_size: int = 1, max_length: int = 2048,
    max_subgoals: int = 3,
    scorer: Callable[..., list[float]] | None = None,
) -> tuple[list[dict], dict]:
    """Return sorted Operation entries + audit metadata, without removing any candidates.

    In `shadow`, scores are calculated but the order is left unchanged.
    The optional scorer is used for deterministic offline unit tests.
    """
    if mode not in ('off', 'shadow', 'rerank'):
        raise ValueError('Unknown Qwen mode: ' + mode)
    unchanged = list(candidates)
    if mode == 'off' or not candidates:
        return unchanged, {'mode': mode, 'called': False, 'scores': {}, 'applied': False}
    facets = query_facets(question, parsed, max_subgoals=max_subgoals)
    pairs = [(facet, operation_document(graph, c['operation_id']))
             for c in candidates for facet in facets]
    score_fn = scorer or score_pairs_local
    values = score_fn(model_path, pairs, device=device, batch_size=batch_size, max_length=max_length)
    if len(values) != len(pairs):
        raise ValueError(f'Qwen 返回 {len(values)} 个评分，预期 {len(pairs)} 个')
    if any(not math.isfinite(float(x)) or not (0 <= float(x) <= 1) for x in values):
        raise ValueError('Qwen 返回了无效分数；必须在 [0,1] 内')
    scores = {}
    by_query = {}
    for i,c in enumerate(candidates):
        oid = c['operation_id']
        chunk = [round(float(x), 6) for x in values[i * len(facets):(i+1) * len(facets)]]
        # Max over subgoals ensures relevant prerequisites are not drowned out.
        scores[oid] = max(chunk)
        by_query[oid] = dict(zip(facets, chunk))
    ranked = sorted(candidates, key=lambda c: (-scores[c['operation_id']], -c.get('score', 0), c['operation_id']))
    applied = mode == 'rerank'
    return ranked if applied else unchanged, {
        'mode': mode,
        'called': True,
        'applied': applied,
        'backend': 'qwen3-local',
        'model': model_path,
        'device_requested': device,
        'scores': scores,
        'scores_by_query': by_query,
        'ranked_operation_ids': [c['operation_id'] for c in ranked],
        'candidate_count': len(candidates),
        'pair_count': len(pairs),
        'scoring_note': 'P(yes) via Qwen3 official reranker; not tool-chain validity',
        'note': 'No operations filtered; DataType/format validation remains graph-based',
    }
