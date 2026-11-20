# BioSkillKG 版本变更记录

## 当前正式版本：v5.2

当前保留的正式图谱由四份 Skill Markdown 构建，文件位于 `data/bio_skill_kg/`。当前构建报告记录 99 个节点、150 条关系和 4 条待人工审核事项。

### v5.2
- 将 BCF 格式映射到已有 `variant_calls` DataType，并建立 `HAS_FORMAT → BCF`。
- 将“质量分布图”映射到 `quality_distribution_plot`。
- 将 50% 重叠交集输出映射到 `intersected_regions`，保留条件信息。
- 去重 `bcftools gtcheck` 的样本列表端口，并统一场景 ID。
- 保留明确区分的同 DataType 多输入端口。

### v5.1
- 为 BWA 补充测序读段输入及单端/双端场景。
- 为 `bcftools gtcheck` 补充样本列表输入。
- 区分 `bcftools view` 的样本子集和单样本拆分场景。
- 保留有命令证据支持的输出参数 `-o`。
- 为 ANNOVAR 数据库下载、bedtools genomecov 和 unionbedg 补充工作流信息。

### v5
- 为 Operation 增加输入端口、输出端口和场景元数据。
- 端口记录 role、flag、required、min/max occurrences、scenario 和 condition。
- Operation 节点保存 `input_specs_json`、`output_specs_json`、`scenarios_json`。
- 跨 Chunk 合并时保留同一 DataType 的不同参数端口。

### v4
- 加强 DataType 与 FileFormat 分离。
- 未知 DataType 不再自动进入正式本体，改为待审核。
- 为每种 FileFormat 单独保存原文证据。
- 改善实体来源章节和描述声明的溯源。

### v3
- 加入 DataType 语义归一化与全局本体。
- 保留跨文档工具连接和证据来源。
- 为多份文档中同一 DataType 的不同描述保存来源声明。

## 兼容说明
- 当前图谱格式仍为 `BioSkillKG-v2`。
- 当前 LLM Prompt：`bioskillkg-extract-v1.6`。
- 当前语义归一化版本：`bioskillkg-semantic-normalization-v5.2`。
- 旧规则模式仍由 `profiles.json` 提供兼容；LLM 自动构图不读取该文件。
