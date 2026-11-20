# BioSkillKG（当前整理版：v5.2）

本目录是 SciToolAgent 项目中的独立生物信息学工具知识图谱构建模块。当前正式保留的图谱由以下四份 Skill Markdown 构建：

- `examples/bio_skills/annovar_skill.md`
- `examples/bio_skills/bcftools_skill.md`
- `examples/bio_skills/bedtools_skill.md`
- `examples/bio_skills/bwa_skill.md`

## 1. 当前正式图谱

最新图谱统一保存在：

```text
data/bio_skill_kg/
├── bio_skill_graph.json          # 当前正式图谱（BioSkillKG-v2）
├── bio_skill_build_report.json   # 构建报告
├── bio_skill_review.json         # 待人工审核事项
├── extracted_skills/             # 四份 MD 的最新抽取结果
└── extraction_cache/             # 当前 Prompt v1.6 的缓存
```

当前验收版本：`BioSkillKG v5.2`

| 指标 | 数量 |
|---|---:|
| 节点 | 99 |
| 关系 | 150 |
| Tool | 21 |
| DataType | 34 |
| FileFormat | 15 |
| Operation | 15 |
| Task | 14 |
| Review | 4 |

构建报告记录的 Prompt 版本为 `bioskillkg-extract-v1.6`，语义归一化版本为 `bioskillkg-semantic-normalization-v5.2`。

这四条待审核事项主要涉及 bedtools 参数证据和泛化统计结果语义。它们保留在 `bio_skill_review.json` 中，不会被静默丢弃或强行映射。

## 2. 目录与文件职责

### BioSkillKG 构图代码

```text
bio_skill_kg/
├── llm_extractor.py          # DeepSeek 抽取、Prompt、缓存与场景/端口抽取
├── extraction_schema.json    # LLM 输出结构约束
├── validator.py              # Schema 与原文证据验证
├── auto_builder.py           # 抽取结果归一化并构建节点、关系
├── builder.py                # 图谱结构、增量合并与冲突审核
├── data_types.json           # DataType 规范本体
├── ontology_aliases.json     # DataType 别名
├── file_formats.json         # 文件格式本体
├── tool_aliases.json         # 工具名称别名
└── profiles.json             # 仅供旧规则模式兼容；LLM 自动构图模式不读取
```

### 主要入口

- `build_bio_skill_kg.py`：从 Markdown 构建或更新 BioSkillKG。
- `import_bio_skill_neo4j.py`：将当前 JSON 图谱导入 Neo4j。
- `neo4j_bioskill_queries.cypher`：常用 Neo4j 查询。
- `README_BioSkillKG.md`：本说明。

## 3. 安装构图依赖

在项目根目录执行：

```bat
conda activate SciToolAgent
python -m pip install -r requirements-bioskill-llm.txt
```

LLM 构图需要 DeepSeek API Key。可复制 `.env.example` 为 `.env`，并填写：

```dotenv
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

也可以沿用项目根目录 `example.env`，运行命令时通过 `--env-file example.env` 指定。分发包中的 `example.env` 是脱敏模板，需要自行填入凭据。

## 4. 重新构建四份 MD

### 4.1 复用缓存构建

默认缓存位置为 `data/bio_skill_kg/extraction_cache/`。如果 Markdown、模型和 Prompt 版本没有变化，可以复用缓存：

```bat
python build_bio_skill_kg.py ^
  --input examples/bio_skills ^
  --output data/bio_skill_kg/bio_skill_graph.json ^
  --llm ^
  --env-file .env
```

### 4.2 强制重新调用模型

如果修改了 Skill 文档，或希望忽略缓存重新抽取：

```bat
python build_bio_skill_kg.py ^
  --input examples/bio_skills ^
  --output data/bio_skill_kg/bio_skill_graph.json ^
  --llm ^
  --env-file .env ^
  --force-extract
```

### 4.3 从零重建

如需完全根据四份 MD 重建，而不是与现有图谱增量合并：

```bat
python build_bio_skill_kg.py ^
  --input examples/bio_skills ^
  --output data/bio_skill_kg/bio_skill_graph.json ^
  --llm ^
  --env-file .env ^
  --fresh ^
  --confirm-reset
```

覆盖前构建脚本会备份现有目标图谱。缓存仍可复用；需要重新请求模型时，再添加 `--force-extract`。

构建后检查：

```bat
type data\bio_skill_kg\bio_skill_build_report.json
type data\bio_skill_kg\bio_skill_review.json
```

## 5. 测试与 Neo4j 导入

运行项目测试：

```bat
python -m unittest discover -s tests -v
```

只运行 BioSkillKG 测试：

```bat
python -m unittest discover -s tests -p "test_bio_skill*.py" -v
```

先做 Neo4j 导入预检查，不连接数据库：

```bat
python import_bio_skill_neo4j.py --dry-run
```

导入当前正式图谱：

```bat
python import_bio_skill_neo4j.py --database neo4j
```

导入器默认读取 `data/bio_skill_kg/bio_skill_graph.json`。Neo4j 连接信息通过环境变量设置：

```bat
set NEO4J_URI=bolt://localhost:7687
set NEO4J_USER=neo4j
set NEO4J_DATABASE=neo4j
```

如果没有设置 `NEO4J_PASSWORD`，脚本会在终端中提示输入密码。

建议将 BioSkillKG 导入专用 Neo4j Instance。导入脚本采用 MERGE，不会自动删除数据库中不再出现在 JSON 的旧节点或关系。

## 6. Operation 输入输出结构

图谱保留五类节点：

- Tool
- Operation
- Task
- DataType
- FileFormat

Operation 节点除传统关系外，还保存三个 JSON 字符串属性：

- `input_specs_json`：输入端口、角色、CLI flag、必需性、数量约束、场景与证据。
- `output_specs_json`：输出端口、格式、条件、场景与证据。
- `scenarios_json`：同一 Operation 的不同执行场景。

例如，`bedtools intersect` 的 `-a` 和 `-b` 都可以连接同一个 `genomic_regions` DataType，但作为不同端口分别保存在 `input_specs_json` 中。Neo4j 关系可能合并为一条 `REQUIRES_INPUT`，端口级信息仍保存在 Operation 属性中。

## 7. Neo4j 常用查询

### 查看全部工具及其操作

```cypher
MATCH p=(t:BioSkillEntity:Tool)-[:HAS_OPERATION]->(o:BioSkillEntity:Operation)
RETURN p;
```

### 查看某个 Operation 的输入、输出和场景属性

```cypher
MATCH (o:BioSkillEntity:Operation)
WHERE o.name = 'bedtools intersect'
RETURN
  o.name,
  o.input_specs_json,
  o.output_specs_json,
  o.scenarios_json;
```

### 查看工具之间的已记录关系

```cypher
MATCH (a:BioSkillEntity:Tool)-[r]->(b:BioSkillEntity:Tool)
WHERE type(r) IN [
  'DOCUMENTED_DOWNSTREAM',
  'DOCUMENTED_PREREQUISITE',
  'RECOMMENDED_BEFORE',
  'PARTIALLY_ALTERNATIVE_TO'
]
RETURN a.canonical_name, type(r), b.canonical_name,
       r.source_files, r.evidence_quotes;
```

### 查看 DataType 与文件格式

```cypher
MATCH (d:BioSkillEntity:DataType)-[:HAS_FORMAT]->(f:BioSkillEntity:FileFormat)
RETURN d.id, d.name, collect(f.name) AS formats
ORDER BY d.id;
```

## 8. 质量边界与注意事项

1. LLM 抽取结果必须经过原文证据验证；`bio_skill_review.json` 中的候选项需要人工确认。
2. `DOCUMENTED_DOWNSTREAM`、`DOCUMENTED_PREREQUISITE` 和 `RECOMMENDED_BEFORE` 表示 MD 中记载的工具关联，不自动等同于已经验证的可执行工作流。
3. DataType 表示数据内容语义；FileFormat 表示文件格式。不能仅凭扩展名推断 DataType。
4. 相同 DataType 的多个输入端口可能在关系层合并；检查具体参数角色时，应读取 Operation 的 `input_specs_json`。
5. `profiles.json` 仅为旧规则构图模式保留。使用 `--llm` 的自动构图流程不依赖它，也不需要为每份 MD 手工编写 profile。

## 9. 与 SciToolAgent 其他模块的边界

本次整理没有修改以下 Agent 调用、问答、检索和工具执行模块：

- `app/`
- `app_scitoolagent_with_evidence.py`
- `ToolsAgent/`
- `scripts/`
- `KG/storage_graph_bge_m3/`
- `KG/storage_graph_bge_m3_workspace/`
- `kg_fusion/`
- `kg_management/`
- `text_ingestion/`
- `unified_services.py`
- 原有 SciToolKG 的导入、增量构图与检索代码

BioSkillKG 是独立的构图与 Neo4j 可视化图谱。当前整理不代表已经把 BioSkillKG 自动接入 Agent Planner 或问答检索链路。
