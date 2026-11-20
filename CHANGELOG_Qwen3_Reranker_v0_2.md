# SciToolAgent / BioSkillKG Planner v0.2 修改记录

本轮基于用户最新上传的 `BiotoolsAgent.zip`：

1. 新增本地 `Qwen3-Reranker` 评分后端：以 Operation 为基本单位，评估完整任务与最多 3 个子任务；使用 Hugging Face Transformers 官方 yes/no logits 方式生成 [0,1] 分数。
2. 新增 CLI `qwen-check`、`--qwen off/shadow/rerank`、模型本地路径、CUDA/CPU 设备、批处理、最大长度、子任务数量与融合权重配置。
3. 在已有 BGE-M3 召回、图谱扩展之后接入 Qwen；评分仅调整搜索优先级，保留路径完整性和 `pending_review`/外部输入检查。
4. 增加报告中的 Qwen 调用/应用状态、相关性排序和 JSON 审计分数；原 Jev 参数保持兼容但与 Qwen 互斥。
5. 新增自动化测试，模拟本地 Qwen 评分（无需下载模型权重），覆盖排序、shadow、安全性、CLI 输出和缺失模型路径提示。
6. **未修改** `bio_skill_kg/`、`build_bio_skill_kg.py`、任何原有构图/导入脚本，也不修改已有向量索引；没有执行科研工具。
7. 已运行 `python -m unittest discover -s tests -p 'test_*.py'`：**97 项通过**。
8. 交付 ZIP 中**排除用户上传的真实 `example.env` 和 IDE/pycache 文件**，提供空值 `example.env.template`，避免 API Key 外泄。原电脑上的 `example.env` 可继续使用，解压后自行复制。

## 未在此环境实际运行

- 用户 Windows `D:\qwen3_reranker` 目录的真实权重加载与 RTX 4090 性能；需运行 `qwen-check`。
- 用户 TypeSafe / DeepSeek 在线 API 与 Neo4j 在线实例；本轮主要是集成与离线可重复测试。
- 原始 Markdown 文件/构图逻辑改动：无。
