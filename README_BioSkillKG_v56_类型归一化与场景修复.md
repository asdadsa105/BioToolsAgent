# BioSkillKG v5.6：通用数据类型、场景和工具链候选连接修复

本 ZIP **只包含代码补丁**，以 v5.5 通用修复版为基础，不覆盖 `.env`、缓存、现有图谱或 Neo4j。

## 1. 本次修复内容

1. **通用 FASTQ 语义识别**：将有证据的 FASTQ 原始/普通测序读段映射为 `data:short_reads`，有预处理语义的 FASTQ 映射为 `data:processed_short_reads`，后者明确是前者的子类型；不会把任意未知文件只凭 `.fastq.gz` 自动识别为读段数据。
2. **通用 QC 报告识别**：有质控语义且格式匹配的 HTML 质量报告、JSON 质量指标分别复用 `quality_control_report` 与 `quality_control_metrics`，避免因为数据格式相同而误并为同一概念。
3. **候选 ID 稳定性**：同名、同格式、同状态的候选类型不再由于端口描述或来源不同而产生不同 ID；状态/格式不同则仍然区分。此归并只是待审核候选聚合，不会自动创建正式兼容关系。
4. **应用场景自动恢复**：对统一 MD 中第 7 章的 `7.x 场景N` 小节，只要该节代码块确实含有对应 Operation，就保留场景名称、用途、输入说明、预期输出、该场景命令示例和原文来源。不把一个命令的多个应用场景错误拆成多个 Operation。原来的单端/双端执行场景继续保留。
5. **本体元数据同步**：在测试图谱中同步已确认 DataType 的规范描述（保留既有原文证据），解决新的处理后读段子类型与旧版“只限原始读段”的父类型描述矛盾。
6. **子类型兼容链路检查**：新增只读命令 `check_bioskill_compatibility.py`。基于正式关系、IS_SUBTYPE_OF、格式交集及读段角色/单双端模式，报告潜在工具链衔接；**绝不声称这些链路可以直接运行**。

## 2. 安装

先备份当前项目代码，然后解压本 ZIP，按原目录结构覆盖到：

```text
D:\gitwork\SciToolAgent_v5\v5
```

如果实际路径不是这个，请以包含 `build_bio_skill_kg.py` 的目录为准。补丁只是代码修改，不会调用 DeepSeek 或修改 Neo4j。

```bat
conda activate SciToolAgent
cd /d D:\gitwork\SciToolAgent_v5\v5
python -m unittest discover -s tests -p "test_bio_skill*.py" -v
```

离线验证预期：`Ran 64 tests ... OK`。

## 3. 使用已有 fastp 缓存重建干净测试图谱（无 DeepSeek API 调用）

你之前已抽取过 fastp，构建报告中缓存地址在 `data\bio_skill_kg\extracted_skills\fastp_skill_536f4215af3f93d5.json`。**请确认文件仍存在**。不能将 v5.5 的待审核图谱直接追加覆盖，因为旧的 unresolved 数据和候选关系可能残留。应从五文档基线重新合并。

```bat
if not exist data\bio_skill_kg\v56_fastp_test mkdir data\bio_skill_kg\v56_fastp_test

python reconcile_bioskill_from_cache.py ^
  --input examples\bio_skills\fastp_skill.md ^
  --extractions data\bio_skill_kg\extracted_skills ^
  --base data\bio_skill_kg\v54_clean\bio_skill_graph.json ^
  --output data\bio_skill_kg\v56_fastp_test\fastp_v56.json ^
  --strict-ports
```

**输出文件必须是一个此前不存在的新路径**。如果重复测试，请换一个文件名，不要直接覆盖旧文件。无缓存时先按原来 `build_bio_skill_kg.py --llm` 流程对该 MD 抽取一次，再从缓存执行上面的命令。修改 MD 后必须重新提取，不能使用过期缓存。

```bat
python check_bioskill_ports.py ^
  --graph data\bio_skill_kg\v56_fastp_test\fastp_v56.json ^
  --report data\bio_skill_kg\v56_fastp_test\port_check_v56.json ^
  --strict
```

该回归测试预期：在相同原始 fastp 抽取端口下，`total_ports=80`、`curated_ports=80`、`pending_ports=0`、`errors=[]`、`publish_ready=true`；原有五文档节点、关系必须都存在。

如果结果不同，请同时保留构建输出和审计 JSON，不要跳过审核。这个数量只是此次 fastp 基线的预期，不是未来任意 MD 的固定门槛。

## 4. 检查 fastp → BWA 数据衔接

```bat
python check_bioskill_compatibility.py ^
  --graph data\bio_skill_kg\v56_fastp_test\fastp_v56.json ^
  --from-op op:fastp ^
  --to-op op:bwa_mem
```

可以看到 `processed_short_reads` 是 `short_reads` 的子类型，并且有 FASTQ_GZ 格式交集。连接列表只是**可能匹配的端口对**，并非已经满足参考索引、R1/R2 配对、参数、输入文件存在等运行条件。

## 5. 先导入新 Neo4j 测试命名空间

```bat
python import_bioskill_v54_neo4j.py ^
  --graph data\bio_skill_kg\v56_fastp_test\fastp_v56.json ^
  --namespace BioSkillV56FastpTest --dry-run
```

无误后去掉 `--dry-run` 才会连接数据库。**不要使用以前失败/不完整的测试命名空间覆盖结果**。检查三个应用场景：

```cypher
MATCH (o:BioSkillV56FastpTest:Operation {id:'op:fastp'})
RETURN o.name AS op, o.scenarios_json AS scenarios,
       o.input_specs_json AS inputs, o.output_specs_json AS outputs;
```

检查子类型衔接：

```cypher
MATCH (f:BioSkillV56FastpTest:Operation {id:'op:fastp'})-[:PRODUCES]->(made:BioSkillV56FastpTest:DataType)
MATCH (made)-[:IS_SUBTYPE_OF*0..5]->(accepted:BioSkillV56FastpTest:DataType)
MATCH (b:BioSkillV56FastpTest:Operation {id:'op:bwa_mem'})-[:REQUIRES_INPUT]->(accepted)
RETURN DISTINCT f.name AS producer, made.name AS produced_type,
       accepted.name AS accepted_type, b.name AS consumer;
```

**暂时不要更新正式 `BioSkillV54`**：先核对结构、原文证据、全部端口和场景，再决定是否发布。Neo4j 的 MERGE 导入不会删除旧图中的过期关系。

## 6. 本次离线验证与边界

- v5.5 旧 55 项测试 + 9 项新测试，共 **64/64 通过**。
- 使用用户上传的 `fastp_skill.md` 与原 v5.5 fastp 图谱中保存的 **10 个原始端口和原文证据** 还原抽取记录，执行离线重建；得到 **80 已确认 / 0 待审核 / 0 结构错误**。该检验是图谱数据重放，**不是重新调用 DeepSeek**，不证明模型从原文抽取时一定不会遗漏。
- 发现且保留三种应用场景：RNA-seq、WGS、ChIP-seq 质控，以及此前的单端、双端执行模式；保留各自的推荐命令。
- 利用子类型关系验证 `fastp → BWA` 候选衔接，未连接本机 Neo4j 实例。
- 对任意新的、缺少可靠语义依据的类型仍按 `pending_review` 处理；这属于必要的安全门槛，**不能承诺任意未知概念自动获得正确类型或自动组成可执行工具链**。
