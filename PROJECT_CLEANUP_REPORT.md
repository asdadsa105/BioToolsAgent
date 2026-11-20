# BiotoolsAgent 精简归档说明（2026-11-20）

本包依据用户上传的 `BiotoolsAgent(1).zip` 整理，仅做文件清理和分发密钥脱敏，**未修改任何 Python 功能源码、知识图谱或已生成向量**。原项目中的工作流规划算法仍是之前的 Qwen 版本，尚未修复此前识别到的多子任务覆盖、min_occurs 等规划问题。

## 删除的内容

- 问答测试**输出**：`neo4j_qwen_test.json/.md`、`data/bio_skill_kg/deepseek_test.json/.md`、`data/bio_skill_kg/jev_shadow_test.json/.md`。
- `.idea/` 等 IDE 本地文件、`__pycache__/` 及 `*.pyc`。
- `data/bio_skill_kg/v56_picard_fresh_test/backups/` 中的重复历史备份；相同内容的 `data/bio_skill_kg/v56_fastp_test/fastp_v56.json` 仍保留。
- `v56_picard_fresh_test/port_check.json` 重复审核快照；对应 `bio_skill_port_audit.json` 保留。
- `SHA256SUMS.txt` 已重新生成，反映本次清理后的文件内容。

## 保留的内容

- 所有 Python 核心源码与 CLI，**包括** `bio_skill_kg/` 构图和归一化模块、`bioskill_planner/` 检索、Qwen 重排和工作流规划模块。
- 所有 `tests/` 自动化回归**测试代码**；它们不是临时问答报告。
- BioSkillKG 所有现存版本的图谱、审核结果、抽取缓存、原始 Skill MD，包括最新七文档图谱 `data/bio_skill_kg/v56_picard_fresh_test/all7_fresh.json`。
- 两套 BGE-M3 索引：`planner_index_bge/vectors.npy` + `metadata.json`，`planner_index_neo4j/vectors.npy` + `metadata.json`，两套文件哈希均与原包相同。
- 旧系统图谱与工作区 `KG/storage_graph_bge_m3/`、`KG/storage_graph_bge_m3_workspace/`，以及 `data/toxin_*.csv`。
- 所有原始说明文档、依赖文件和可复现测试代码。

## 私密配置

包内根目录 `example.env` 为已脱敏模板；清空了非空的 DEEPSEEK_API_KEY, NEO4J_PASSWORD。从自己的私有原文件复制配置到解压后的项目根目录，不要把带有效密钥的压缩包或 `example.env` 上传公开仓库。

## 项目运行提示

本次精简不是重建图谱和索引；只要本机 Neo4j 对应图谱、模型路径与现有元数据保持一致，可直接复用保存的向量。Neo4j 中的数据仍在用户自己的数据库内，ZIP 只是本地图谱快照与工程文件，不会修改 Neo4j 服务器。

清理了 25 个原有文件，清单如下：

- `.idea/.gitignore`
- `.idea/BiotoolsAgent.iml`
- `.idea/deployment.xml`
- `.idea/inspectionProfiles/Project_Default.xml`
- `.idea/inspectionProfiles/profiles_settings.xml`
- `.idea/modules.xml`
- `.idea/workspace.xml`
- `bioskill_planner/__pycache__/__init__.cpython-310.pyc`
- `bioskill_planner/__pycache__/cli.cpython-310.pyc`
- `bioskill_planner/__pycache__/evidence.cpython-310.pyc`
- `bioskill_planner/__pycache__/graph.cpython-310.pyc`
- `bioskill_planner/__pycache__/index.cpython-310.pyc`
- `bioskill_planner/__pycache__/jev.cpython-310.pyc`
- `bioskill_planner/__pycache__/query.cpython-310.pyc`
- `bioskill_planner/__pycache__/qwen_reranker.cpython-310.pyc`
- `bioskill_planner/__pycache__/retrieve.cpython-310.pyc`
- `bioskill_planner/__pycache__/workflow.cpython-310.pyc`
- `data/bio_skill_kg/deepseek_test.json`
- `data/bio_skill_kg/deepseek_test.md`
- `data/bio_skill_kg/jev_shadow_test.json`
- `data/bio_skill_kg/jev_shadow_test.md`
- `data/bio_skill_kg/v56_picard_fresh_test/backups/all7_fresh_20261117_173322_804424.json`
- `data/bio_skill_kg/v56_picard_fresh_test/port_check.json`
- `neo4j_qwen_test.json`
- `neo4j_qwen_test.md`
