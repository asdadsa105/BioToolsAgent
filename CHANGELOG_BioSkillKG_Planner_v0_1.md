# BioSkillKG Planner v0.1：改动说明

## 新增
- `bioskill_planner/`：JSON/Neo4j 只读检索 + Operation 多视角 BGE-M3 向量索引 + 混合召回 + 证据图谱扩展 + Jev Operation 评分重排 + 待审核连接约束搜索 + 命令/算力/原文证据规划报告。
- `bioskill_planner_cli.py`：单独的 `index` / `query` 命令。
- `requirements_bioskill_planner.txt`：独立依赖清单。
- `README_BioSkillKG_Planner_检索与工作流规划_v0_1.md`：完整的 Windows CMD 操作指南。
- `tests/test_bioskill_planner.py`：13 个离线回归测试。

## 保留原样
- `bio_skill_kg/` 全部构图/归一化/LLM 抽取源代码；`build_bio_skill_kg.py`；`import_bioskill_v54_neo4j.py`。
- 原 `scripts/jev_tool_selector.py` 和原 `scripts/retrieve_tool_info.py` 的工具执行管线不受影响。
- 原始图谱 JSON、原 MD 和知识图谱审核流程。

## 实测（当前容器离线）
- `python -m unittest discover -s tests -p 'test_*.py' -q`：88 tests, OK。
- 真实七文档图谱：145 nodes, 244 edges, 28 Operation；生成 137 条索引文本（Operation 三视角 + DataType + Tool）；使用**离线词项特征**作为测试后端。
- 任务「未排序 BAM → 重复标记 → WGS 指标」能够规划：SortSam → MarkDuplicates → CollectWgsMetrics；后一段必须标记 `pending_review`，参考基因组被识别为缺失输入。
- 原始构图文件与上传 ZIP 完全逐字节一致。

## 尚未在当前容器实测
- **真实 BGE-M3 模型推理**（运行环境没有 sentence-transformers 模型及下载条件），需要用户本机按 README 构建索引。
- **Neo4j 现场连接**（运行环境没有用户的实例与认证配置）。
- **DeepSeek / Jev 的联网请求**（用户没有提供密钥；代码按环境变量读取，失败不会触发工具执行）。
- 原来的 Streamlit 界面尚未接入新模块；这是单独、只读的规划检索入口。
