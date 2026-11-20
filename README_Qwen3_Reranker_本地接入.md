# BioSkillKG Planner v0.2：Qwen3-Reranker 本地接入

> 本版在你上传的 `BiotoolsAgent.zip` 上修改，只改检索/重排/规划入口及对应报告、测试与文档。**不修改 BioSkillKG 构图、数据类型归一化或 Neo4j 导入逻辑。** 原 Jev 仍可选，但不再需要 TypeSafe API 就能完成重排。

## 1. 本版运行结构

```text
问题 → DeepSeek（或本地规则）任务解析
     → BGE-M3 Operation 多视角召回
     → BioSkillKG JSON / Neo4j 只读扩展
     → Qwen3-Reranker 本地评分 / 重排 [新]
     → 已有工作流路径搜索、DataType / 格式 / pending_review 校验
     → 原 MD 命令、参数、资源与证据补全
     → Markdown + JSON 规划报告
```

注意：系统依然 **仅规划**，不会执行 Picard、samtools 或任何科研工具。`Qwen3-Reranker` 是相关性模型，不是工作流形式验证器：它的分数不能代替图谱类型兼容与来源审核。

## 2. 环境准备（Windows CMD / Anaconda Prompt）

```bat
conda activate SciToolAgent
cd /d D:\gitwork\BiotoolsAgent\BiotoolsAgent
pip install -r requirements_bioskill_planner.txt
pip install -r requirements_qwen_reranker.txt
```

你的 PyTorch 必须有可用的 CUDA；可以先查看：

```bat
python -c "import torch,transformers; print('torch',torch.__version__); print('transformers',transformers.__version__); print('CUDA可用',torch.cuda.is_available())"
```

- 这是 **Transformers** 本地推理方式，使用 Qwen3 官方 yes/no token logits 计算相关性，不使用 `.generate()`。
- 建议 `transformers>=4.51`；本次新增的安装文件 `requirements_qwen_reranker.txt` 已约束版本。
- 若升级依赖破坏原 SciToolAgent 环境，请先备份环境或创建单独 Conda 环境验证。安装本模块无需修改 BGE-M3 向量索引。
- 只支持包含 `config.json`、`tokenizer.json`（或 `tokenizer.model`）及 `.safetensors` / `.bin` 权重的 **Hugging Face 模型文件夹**。GGUF、Ollama、单个 `.pth` 文件不能直接传给本模块。
- 你的模型路径固定为 `D:\qwen3_reranker`（Windows 本机）；若在 Linux 服务器运行，需要传服务器自身的模型目录路径。
- Qwen 使用 `local_files_only=True`，**不会自动联网重新下载本地 Qwen 权重**。BGE-M3/DeepSeek 则按原代码逻辑运行。
- 本版没有在交付 ZIP 中带入你的 API Key：上传包里的 `example.env` 包含真实凭据，因此已排除。请将原来电脑上私有的 `example.env` 自行复制到新项目根目录；不要上传或提交 Git。

## 3. 先独立测试本地 Qwen（不需要 DeepSeek / BGE / Jev）

```bat
python bioskill_planner_cli.py qwen-check ^
  --qwen-model "D:\qwen3_reranker" ^
  --qwen-device cuda ^
  --qwen-batch-size 1
```

成功时打印 `status: ok` 和两个候选的 0～1 评分。标记重复序列的操作应通常比 `bcftools merge` 分数高，但具体评分由本地模型决定，不能预先保证。

若提示 `No module named transformers`，安装本版要求文件；若提示 `KeyError: qwen3`，升级 Transformers；若提示 `config.json` 缺失，检查模型是否在嵌套子文件夹；若提示 CUDA 内存不足，先关闭其他占用显存的程序，并保持 `--qwen-batch-size 1`、必要时减小 `--qwen-max-length`（默认 2048；不能低于 256）。

## 4. 在原工作流中做 Qwen shadow 对照

你已经有 `data\bio_skill_kg\planner_index_bge` 索引，**不必重建向量**。

```bat
python bioskill_planner_cli.py query ^
  --source json ^
  --graph data\bio_skill_kg\v56_picard_fresh_test\all7_fresh.json ^
  --index-dir data\bio_skill_kg\planner_index_bge ^
  --question "我有未排序的BAM文件，希望进行重复标记，然后计算全基因组测序指标" ^
  --parser deepseek ^
  --jev off ^
  --qwen shadow ^
  --qwen-model "D:\qwen3_reranker" ^
  --qwen-device cuda ^
  --qwen-batch-size 1 ^
  --goal-op op:collectwgsmetrics ^
  --input-type data:aligned_reads_bam_unsorted ^
  --env-file example.env ^
  --output data\bio_skill_kg\qwen_shadow_test.md ^
  --json-output data\bio_skill_kg\qwen_shadow_test.json
```

`shadow` **真实加载本地模型并计算分数**，但不修改工作流路径搜索分数。`qwen` 元信息包含 `called`、`scores`、`scores_by_query`、`ranked_operation_ids`、`applied=false`。报告还展示前 10 个 Qwen 相关性排序。

## 5. 开启真实 Qwen 重排

保留上面命令，只需改三个参数：

```text
--qwen rerank
--output data\bio_skill_kg\qwen_rerank_test.md
--json-output data\bio_skill_kg\qwen_rerank_test.json
```

`rerank` 根据 Qwen 的 0～1 评分给工作流搜索的 Operation 增加优先级（默认 `--qwen-weight 0.20`）。**不会删掉任何候选 Operation**，也不会改变 DataType、文件格式、审核状态或必需输入校验。

如希望降低 Qwen 对路径搜索的影响，可设 `--qwen-weight 0.10`；想看纯原排序，使用 `--qwen shadow`。

建议首次用同一道题对比 `--qwen off / shadow / rerank`，比对 JSON：

```bat
python -c "import json; d=json.load(open(r'data\bio_skill_kg\qwen_rerank_test.json',encoding='utf8')); q=d['qwen']; print('Qwen调用:',q['called'],'评分已应用:',q['applied']); print('前8:',[(x,round(q['scores'][x],3)) for x in q['ranked_operation_ids'][:8]]); print('工作流:',[w['steps'] for w in d['workflows']])"
```

## 6. 完全自主的自然语言规划

去掉上面测试中人为限定的 `--goal-op`、`--input-type` 即可，其他参数保留；注意此时测试的内容还包括模型自动选目标，可能得到多个候选目标，需单独评价准确性。

## 7. 新增 CLI 参数

| 参数 | 作用 | 默认值 |
|---|---|---|
| `--qwen` | `off`、`shadow`、`rerank` | `off` |
| `--qwen-model` | 本地 Qwen3 HF 文件夹；可由 `QWEN_RERANKER_PATH` 设置 | `D:\qwen3_reranker` |
| `--qwen-device` | `auto`、`cuda`、`cpu` | `auto` |
| `--qwen-batch-size` | 一次评分的 query/document 对数 | `1` |
| `--qwen-max-length` | Qwen Token 上限（包含指令与 prompt） | `2048` |
| `--qwen-subgoal-limit` | 最多评价几个 DeepSeek 子任务 | `3` |
| `--qwen-weight` | Qwen 影响规划排序的加性权重 | `0.20` |
| `--jev` | 原有 TypeSafe 远程 API（仍保留） | `off` |

**`--qwen` 与 `--jev` 不允许同时启用**，以防止误调用已停用的 TypeSafe 账户。

## 8. 评分含义与限制

- Qwen 按用户完整问题及每个子目标分别打分，对同一 Operation 取这些分数的 **最大值**。这是为了避免必需的前置操作被整个大问题的低语义相似度压制；相应地，也可能让多功能操作的最高分偏高，需要后续实测。
- Qwen 分数来自 yes/no logits 的 softmax，不是正确率，也不等于数据类型匹配成功率。
- `shadow` 与 `rerank` 的不同体现在 `qwen.applied`、`effective_operation_scores`、候选路径评分与可能的最终路径；两者都保留初始 BGE 候选 `candidates` 供对照。
- JSON 图谱 (`--source json`) 与 Neo4j 快照 (`--source neo4j`) 原先均支持；**本轮没有在真实 Neo4j 实例上重新联调**。
- 本轮环境没有你 D 盘的 Qwen 权重，**真实本地模型加载、推理分数及速度需要在你 Windows 4090 环境完成 `qwen-check` 后再确认**；离线自动化测试使用模拟评分器以核对集成路径。
- 这仍然是规划报告生成器，并未增加 DeepSeek 在末端重新润色报告的调用，也不会实际执行科研工具。

## 9. 关键改动文件

```text
bioskill_planner/qwen_reranker.py          新：本地 Qwen 推理 + Operation 候选文本与多子目标评分
bioskill_planner/cli.py                    改：qwen-check / --qwen / 评分接入规划器
bioskill_planner/evidence.py               改：报告中的 Qwen 排名与模式
requirements_qwen_reranker.txt             新：单独推理依赖
README_Qwen3_Reranker_本地接入.md           新：本说明
tests/test_qwen_reranker_planner.py         新：离线、模拟重排与 CLI 集成测试
```

官方模型推理方法参考： https://huggingface.co/Qwen/Qwen3-Reranker-4B （Transformers 与 yes/no logits 部分）。
