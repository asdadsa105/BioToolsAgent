# BioSkillKG：Operation 多视角向量检索与只读工作流规划 v0.1

> **本轮只增加向量生成、检索、路径规划及证据汇总。没有修改 `build_bio_skill_kg.py`、`bio_skill_kg/` 的构图规则、Neo4j 导入器，也没有修改原来的 SciToolAgent 工具执行入口。**

## 一、当前实现的架构

```text
已有 Skill MD → [原 v5.6 构图逻辑，原封不动] → BioSkillKG v2 JSON / Neo4j
                                                       │
                                               离线读取 Operation
                                                       │
                                  功能 / 场景 / I/O 三类检索文本
                                                       │
                                       BGE-M3 Embedding → 本地向量索引
                                                       │
用户自然语言问题 → [规则解析或可选 DeepSeek 任务解析] ───┘
             │
      语义召回 + 词项匹配 → 候选 Operation
             │
    Neo4j/JSON 正式类型关系扩展；单独记录文档性工具建议
             │
      [可选 Jev shadow/rerank/filter-safe]：Operation 重排（不删必要前置步骤）
             │
      目标反向追溯：检验 DataType 方向、Format、必需输入、数量和待审核端口
             │
   原 MD 证据补全：Tool / Operation、命令示例、参数、资源、来源章节
             │
      只读 JSON + Markdown 工作流报告（不执行实际科研工具）
```

### 索引对象

- **Operation**：每个 Operation 三条向量（purpose / scenario / io），都带相同 `operation_id`。
- **DataType**：辅助向量，识别自然语言数据语义；**仅生成建议，不自动批准候选、也不凭相似度认定输入已具备**。
- **Tool**：辅助向量，便于处理用户明确指名的工具。
- 命令、参数、算力和证据**不当作主要语义向量**；选中 Operation 后从图谱中按 ID 原样读取。

### 规划的安全边界

- `PRODUCES + REQUIRES_INPUT + IS_SUBTYPE_OF + Format` 组合用于判断数据衔接。
- `DOCUMENTED_*` 与 `RECOMMENDED_BEFORE`、`PARTIALLY_ALTERNATIVE_TO` 只是候选提示，不能直接认定可执行。
- 有相同候选 ID 的 `pending_review` 端口可以显示为**待审核候选连接**，绝不当成正式图谱关系。
- 多输入与数量、参考文件等未满足条件显示为 `missing_requirements`，所有结果 `ready_to_execute=false`。
- 缺少来源证据或无法找到路径时报告不足；不调用 Picard、SAMtools、BWA 等科研工具。

## 二、增加的代码

| 路径 | 作用 |
|---|---|
| `bioskill_planner/graph.py` | JSON/Neo4j **只读**适配、端口状态兼容、方向性类型与格式验证 |
| `bioskill_planner/index.py` | BGE-M3 多视角 Embedding、本地索引、图谱指纹校验 |
| `bioskill_planner/query.py` | 本地任务拆分、可选 DeepSeek 结构化任务解析、保守数据类型匹配 |
| `bioskill_planner/retrieve.py` | Operation 语义/词项混合检索、图谱邻居扩展、DataType 候选检索 |
| `bioskill_planner/jev.py` | Jev Operation 级别适配，支持 off/shadow/rerank/安全 filter |
| `bioskill_planner/workflow.py` | 基于图谱证据的反向依赖搜索、缺失输入与待审核关系识别 |
| `bioskill_planner/evidence.py` | 工作流每步原文命令/参数/工具级资源/来源证据补全 |
| `bioskill_planner/cli.py` | 离线索引生成与规划命令入口 |
| `bioskill_planner_cli.py` | 入口文件（等价于 `python -m bioskill_planner`） |
| `tests/test_bioskill_planner.py` | 本次新增自动化测试 |

## 三、安装（Windows Anaconda Prompt）

进入**解压后、包含 `build_bio_skill_kg.py` 的项目根目录**：

```bat
conda activate SciToolAgent
cd /d D:\gitwork\SciToolAgent_v5_6_clean
pip install -r requirements_bioskill_planner.txt
```

BGE-M3 第一次使用时需要下载/加载模型；如果已下载可通过 `--model` 指定本地模型目录。GPU 可以用 `--device cuda`，也可以使用 `--device auto` 自动选择 CUDA 或 CPU。无需任何 API Key 就能生成本地 BGE-M3 向量（模型文件须已安装或可下载）。

## 四、正式生成 BGE-M3 向量

### 方案 A：从现有 JSON 构建（最简单）

```bat
python bioskill_planner_cli.py index ^
  --source json ^
  --graph data\bio_skill_kg\v56_picard_fresh_test\all7_fresh.json ^
  --backend bge-m3 ^
  --model BAAI/bge-m3 ^
  --device auto ^
  --index-dir data\bio_skill_kg\planner_index_bge
```

生成 `metadata.json` 和 `vectors.npy`，元信息记录操作 ID、视角和数据源图谱 SHA-256 指纹。如果图谱发生变化，查询会阻止使用过期索引；应重新生成。

### 方案 B：直接读取当前 Neo4j 命名空间

无需额外导入数据库，只需要连接到已有 Neo4j：

```bat
set NEO4J_URI=bolt://localhost:7687
set NEO4J_USER=neo4j
set NEO4J_PASSWORD=你自己的Neo4j密码
python bioskill_planner_cli.py index ^
  --source neo4j ^
  --namespace BioSkillV56PicardFreshTest ^
  --database neo4j ^
  --backend bge-m3 ^
  --index-dir data\bio_skill_kg\planner_index_neo4j
```

Neo4j 查询使用**只读** MATCH；不会修改原有节点、关系或命名空间。注意：索引必须与查询时同一图谱快照、同一数据源对应。

## 五、开始科研任务规划

### 先用现有 JSON + BGE-M3

```bat
python bioskill_planner_cli.py query ^
  --source json ^
  --graph data\bio_skill_kg\v56_picard_fresh_test\all7_fresh.json ^
  --index-dir data\bio_skill_kg\planner_index_bge ^
  --question "我有未排序的BAM文件，希望进行重复标记然后计算全基因组测序指标" ^
  --goal-op op:collectwgsmetrics ^
  --input-type data:aligned_reads_bam_unsorted ^
  --jev off ^
  --output data\bio_skill_kg\planner_report.md ^
  --json-output data\bio_skill_kg\planner_report.json
```

`--goal-op` / `--input-type` **不是必需参数**。第一版为了便于审核建议先指定明确目标和初始类型；不指定时用语义和任务解析自动选目标，结果会列出多个候选方案。

### 从 Neo4j 查询

将 `--source json --graph ...` 替换成 `--source neo4j --namespace BioSkillV56PicardFreshTest --database neo4j`，并使用第四节方案 B 的索引路径。

### 接入 DeepSeek 任务解析（可选）

仅在有真实 API Key、并希望提取复杂自然语言约束时使用：

```bat
set DEEPSEEK_API_KEY=你自己的Key
set DEEPSEEK_BASE_URL=https://api.deepseek.com
set DEEPSEEK_MODEL=deepseek-chat
python bioskill_planner_cli.py query ^
  --index-dir data\bio_skill_kg\planner_index_bge ^
  --question "我有未排序BAM，希望去重并做WGS统计" ^
  --parser deepseek ^
  --jev off
```

也可以传 `--env-file 你自己的配置文件`；**压缩包中没有包含 `.env` 或真实密钥**。DeepSeek 在这里仅做任务解析，不能用来虚构图谱连接。

### 接入 Jev（可选）

```bat
set TYPESAFE_API_KEY=你自己的Key
set JEV_MODEL=jev-latest
python bioskill_planner_cli.py query ^
  --index-dir data\bio_skill_kg\planner_index_bge ^
  --question "我有未排序BAM，希望去重并做WGS统计" ^
  --jev shadow
```

- `off`：完全不调用 Jev。
- `shadow`：评分并写入 JSON 报告，不影响排序。
- `rerank`：影响候选优先级，不验证任何工具兼容性。
- `filter`：规划安全模式下**仅重排、不删除**可能的前置 Operation。
- 无 Key 或 API 失败时，自动回到原有候选序列并在报告的 `jev` 字段中说明。

## 六、没有模型或没有密钥时如何先做离线验证？

**这个模式只是测试逻辑，不是 BGE-M3 Embedding 的实际质量证明。**

```bat
python bioskill_planner_cli.py index ^
  --backend lexical ^
  --index-dir data\bio_skill_kg\planner_index_smoke

python bioskill_planner_cli.py query ^
  --index-dir data\bio_skill_kg\planner_index_smoke ^
  --question "我有未排序的BAM，希望进行重复标记然后计算全基因组测序指标" ^
  --goal-op op:collectwgsmetrics ^
  --input-type data:aligned_reads_bam_unsorted ^
  --output data\bio_skill_kg\planner_smoke_report.md ^
  --json-output data\bio_skill_kg\planner_smoke_report.json
```

在原七文档未审核图谱上，预计给出：

`SortSam / samtools sort → MarkDuplicates → CollectWgsMetrics`

其中 MarkDuplicates → CollectWgsMetrics 必须标为 `pending_review`，并提示参考基因组为额外必需输入。候选连接不代表正式 DataType 关系。

## 七、测试与当前限制

```bat
python -m unittest tests.test_bioskill_planner -v
python -m unittest discover -s tests -p "test_*.py" -v
```

本地离线已经验证：Operation 视角索引、索引过期检查、完整真实图谱的类型继承、待审核识别、工作流的缺失参考基因组检测、保留 MD 证据和无工具执行。原项目构图测试也继续执行。

当前第一版有明确边界：

1. 不连接原 Streamlit 页面中的实际执行智能体；CLI 是独立的只读规划入口。
2. 多目标/多分支工作流尚以候选方案表示，复杂条件、样本数、文件存在性不能全部证明；对 `min_occurs>1` 会要求确认文件数量。
3. 无法联网调用 DeepSeek、Jev 或下载 BGE-M3 模型的环境中，只能用词项向量运行离线测试；不能以此宣称真实 BGE-M3/Jev 的检索效果已测量。
4. 原图谱中部分端口仍 `pending_review`。没有替用户注册新类型、没有修改构图规则。
5. 提供的命令示例是 MD 原文，不代表已经在相应软件版本中实测或具有运行安全保证。

## 八、升级约定

Graph 构建逻辑和原执行入口继续保持不动。等新检索准确率及规划效果确认后，再把 `bioskill_planner` 作为独立 Streamlit 页面或 API 接到系统，而不是替换旧的工具执行器。
MD 增量导入和重构图之后，**需要重新构建向量索引**；索引不应在没有图谱指纹检查的情况下复用。
MD 中的命令、资源和证据原样保留；模型的理解和图谱的正式类型关系必须分别标注。
