# fastp工具Skill

## 1. 工具基本信息

**工具名称**: fastp
**工具版本**: 0.23.4
**工具分类**: 数据预处理类
**工具描述**: 快速的质控和过滤工具，支持多线程，可生成HTML质控报告，适用于各种测序数据的质量控制和预处理
**工具来源**: https://github.com/OpenGene/fastp
**Docker镜像**: opengene/fastp:0.23.4

## 2. 输入参数规范

### 2.1 必需参数

| 参数名称 | 短参数 | 长参数 | 参数类型 | 参数说明 | 默认值 | 是否支持通配符 | 取值 |
|---------|--------|--------|---------|---------|--------|----------------|------|
| 输入R1文件 | -i | --in1 | 文件路径 | 输入的FASTQ文件（单端或双端的R1） | 无 | 支持 | 必填 |
| 输入R2文件 | -I | --in2 | 文件路径 | 输入的FASTQ文件（双端的R2） | 无 | 支持 | 必填 |

### 2.2 可选参数

| 参数名称 | 短参数 | 长参数 | 参数类型 | 参数说明 | 默认值 | 推荐值范围 | 取值 |
|---------|--------|--------|---------|---------|--------|------------|------|
| 输出R1文件 | -o | --out1 | 文件路径 | 输出的FASTQ文件（单端或双端的R1） | clean_1.fq.gz | - | 推荐 |
| 输出R2文件 | -O | --out2 | 文件路径 | 输出的FASTQ文件（双端的R2） | clean_2.fq.gz | - | 推荐 |
| 接头检测 | -d | --detect_adapter_for_pe | 布尔值 | 自动检测双端数据的接头序列 | false | true | 推荐 |
| 前端裁剪 | --cut_front | - | 整数 | 从5'端裁剪的碱基数 | 0 | 0-10 | 推荐 |
| 后端裁剪 | --cut_tail | - | 整数 | 从3'端裁剪的碱基数 | 0 | 0-10 | 推荐 |
| 滑动窗口质量 | --cut_window_size | - | 整数 | 滑动窗口大小 | 4 | 1-10 | 可选 |
| 滑动窗口质量阈值 | --cut_mean_quality | - | 整数 | 滑动窗口的平均质量阈值 | 20 | 15-30 | 推荐 |
| 质量阈值 | --qualified_quality_phred | - | 整数 | 合格的质量分数（Phred值） | 15 | 10-30 | 可选 |
| 最小长度 | --length_required | - | 整数 | 过滤后序列的最小长度 | 15 | 10-50 | 推荐 |
| 低复杂度过滤 | --low_complexity_filter | - | 整数 | 低复杂度过滤的阈值（0-100） | 0 | 0-50 | 可选 |
| 多线程 | -w | --thread | 整数 | 线程数 | 4 | 1-16 | 推荐 |
| 压缩级别 | -z | --compression | 整数 | 输出文件的压缩级别（1-9） | 4 | 1-9 | 可选 |
| 过表达序列过滤 | --overrepresentation_analysis | - | 布尔值 | 执行过表达序列分析 | false | true | 可选 |
| 过表达序列阈值 | --overrepresentation_sampling | - | 整数 | 过表达序列分析的采样数 | 20000 | 10000-100000 | 可选 |
| 接头文件 | -a | --adapter_sequence | 字符串 | 接头序列 | "" | - | 可选 |
| 接头文件R2 | -A | --adapter_sequence_r2 | 字符串 | R2的接头序列 | "" | - | 可选 |
| 接头前导序列 | --trim_front1 | - | 整数 | R1前端裁剪的碱基数 | 0 | 0-20 | 可选 |
| 接头前导序列R2 | --trim_front2 | - | 整数 | R2前端裁剪的碱基数 | 0 | 0-20 | 可选 |
| 接头尾随序列 | --trim_tail1 | - | 整数 | R1后端裁剪的碱基数 | 0 | 0-20 | 可选 |
| 接头尾随序列R2 | --trim_tail2 | - | 整数 | R2后端裁剪的碱基数 | 0 | 0-20 | 可选 |
| 接头滑动窗口 | --trim_window_size | - | 整数 | 接头检测的滑动窗口大小 | 5 | 3-10 | 可选 |
| 接头匹配阈值 | --trim_match_ratio | - | 浮点数 | 接头匹配的比例阈值 | 0.6 | 0.4-0.8 | 可选 |

## 3. 输出文件定义

### 3.1 标准输出文件

| 输出名称 | 文件类型 | 文件格式 | 文件命名规则 | 说明 |
|---------|---------|---------|-------------|------|
| o1 | 质控报告 | HTML | {prefix}_fastp.html | 详细的质控报告，包含数据统计和图表 |
| o2 | 质控数据 | JSON | {prefix}_fastp.json | 质控报告的JSON格式数据，便于程序处理 |
| out1 | 处理后序列 | FASTQ.gz | {prefix}_clean_1.fq.gz | 处理后的R1文件 |
| out2 | 处理后序列 | FASTQ.gz | {prefix}_clean_2.fq.gz | 处理后的R2文件 |

### 3.2 日志文件

| 日志文件 | 日志格式 | 日志内容 |
|---------|---------|----------|
| fastp.log | 文本 | 执行过程的详细日志，包含参数信息、处理进度和统计数据 |

## 4. 资源需求配置

### 4.1 CPU需求
- **最小**: 1核
- **推荐**: 4核
- **最大**: 8核

### 4.2 内存需求
- **最小**: 1GB
- **推荐**: 4GB
- **最大**: 8GB

### 4.3 磁盘需求
- **临时空间**: 输入数据大小的2倍
- **输出空间**: 输入数据大小的1.5倍

### 4.4 运行时间预估
| 数据规模 | 预估运行时间 |
|---------|------------|
| 1G数据 | 5-10分钟 |
| 10G数据 | 30-60分钟 |
| 50G数据 | 2-4小时 |

## 5. 数据类型兼容性

### 5.1 输入数据类型

| 数据类型 | 支持情况 | 格式要求 | 说明 |
|---------|---------|---------|------|
| FASTQ | 支持 | .fq, .fastq, .fq.gz, .fastq.gz | 单端或双端测序数据 |
| FASTA | 不支持 | - | 不支持FASTA格式 |
| BAM/SAM | 不支持 | - | 不支持比对数据 |
| 其他格式 | 不支持 | - | 只支持FASTQ格式 |

### 5.2 输出数据类型

| 数据类型 | 格式 | 说明 |
|---------|------|------|
| FASTQ.gz | 压缩FASTQ | 处理后的序列数据 |
| HTML | 网页格式 | 质控报告 |
| JSON | 结构化数据 | 质控数据 |

## 6. 依赖关系约束

### 6.1 前置工具
- **必需前置工具**: 无
- **推荐前置工具**: 无

### 6.2 后置工具

| 工具名称 | 工具分类 | 适用场景 |
|---------|---------|----------|
| bwa | 序列比对类 | 基因组比对 |
| hisat2 | 序列比对类 | RNA-seq比对 |
| star | 序列比对类 | RNA-seq比对 |
| bowtie2 | 序列比对类 | ChIP-seq比对 |
| minimap2 | 序列比对类 | 长读长比对 |

### 6.3 互斥工具
- **互斥工具**: fastqc (功能部分重叠，推荐使用fastp)
- **替代工具**: trimmomatic, cutadapt

## 7. 使用场景模板

### 7.1 场景1: RNA-seq数据质控

**适用场景**: 转录组测序数据的质量控制和预处理
**输入数据**: 双端FASTQ文件
**推荐参数**:
```bash
fastp \
  --in1 {input_r1} \
  --in2 {input_r2} \
  --out1 {output_r1} \
  --out2 {output_r2} \
  --detect_adapter_for_pe \
  --cut_front 10 \
  --cut_tail 10 \
  --cut_mean_quality 20 \
  --length_required 36 \
  --thread 4 \
  --compression 4 \
  --html {prefix}_fastp.html \
  --json {prefix}_fastp.json
```
**预期输出**:
- 处理后的双端FASTQ文件
- HTML质控报告，包含接头检测结果
- 过滤掉低质量和短序列

### 7.2 场景2: WGS数据质控

**适用场景**: 全基因组测序数据的质量控制
**输入数据**: 双端FASTQ文件
**推荐参数**:
```bash
fastp \
  --in1 {input_r1} \
  --in2 {input_r2} \
  --out1 {output_r1} \
  --out2 {output_r2} \
  --detect_adapter_for_pe \
  --cut_front 5 \
  --cut_tail 5 \
  --cut_mean_quality 20 \
  --length_required 50 \
  --low_complexity_filter 30 \
  --thread 8 \
  --compression 4 \
  --html {prefix}_fastp.html \
  --json {prefix}_fastp.json
```
**预期输出**:
- 处理后的双端FASTQ文件
- 详细的质控报告，包含复杂度分析
- 过滤掉低质量、短序列和低复杂度序列

### 7.3 场景3: ChIP-seq数据质控

**适用场景**: 染色质免疫沉淀测序数据的质量控制
**输入数据**: 双端FASTQ文件
**推荐参数**:
```bash
fastp \
  --in1 {input_r1} \
  --in2 {input_r2} \
  --out1 {output_r1} \
  --out2 {output_r2} \
  --detect_adapter_for_pe \
  --cut_front 15 \
  --cut_tail 5 \
  --cut_mean_quality 20 \
  --length_required 20 \
  --thread 4 \
  --compression 4 \
  --html {prefix}_fastp.html \
  --json {prefix}_fastp.json
```
**预期输出**:
- 处理后的双端FASTQ文件
- 质控报告，重点关注接头和低质量碱基
- 保留足够长度的序列用于后续比对

## 8. 质量控制指标

### 8.1 输入数据要求

| 指标 | 要求 | 说明 |
|------|------|------|
| 序列质量 | Q20 > 80% | 原始数据质量应在可接受范围内 |
| 序列长度 | ≥ 36bp | 过短的序列不适合后续分析 |
| 接头污染 | 存在接头 | fastp可自动检测和去除接头 |
| 数据量 | ≥ 1M reads | 数据量过小可能导致统计结果不可靠 |

### 8.2 输出质量检查

| 检查项目 | 检查方法 | 合格标准 |
|---------|---------|----------|
| 序列长度分布 | 查看HTML报告 | 主要分布在预期范围内 |
| 碱基质量分布 | 查看HTML报告 | Q20 > 90%, Q30 > 80% |
| GC含量分布 | 查看HTML报告 | 符合物种特征，无异常峰 |
| 接头去除效果 | 查看HTML报告 | 接头含量显著降低 |
| 序列数量变化 | 查看JSON数据 | 过滤后序列数 ≥ 原始的70% |

### 8.3 常见错误处理

| 错误类型 | 错误信息 | 解决方案 |
|---------|---------|----------|
| 文件不存在 | `Error: cannot open input file` | 检查输入文件路径是否正确 |
| 文件格式错误 | `Error: invalid FASTQ format` | 检查输入文件是否为有效的FASTQ格式 |
| 内存不足 | `Error: out of memory` | 增加内存配置或减少线程数 |
| 磁盘空间不足 | `Error: cannot write output file` | 检查输出目录磁盘空间是否足够 |
| 线程数过多 | `Error: too many threads` | 减少线程数，不超过系统可用CPU |

## 9. 工具执行示例

### 9.1 基本用法

**单端数据处理**:
```bash
fastp --in1 input.fq.gz --out1 output.fq.gz --html report.html --json report.json
```

**双端数据处理**:
```bash
fastp --in1 input_1.fq.gz --in2 input_2.fq.gz --out1 output_1.fq.gz --out2 output_2.fq.gz --html report.html --json report.json
```

### 9.2 高级用法

**自动检测接头**:
```bash
fastp --in1 input_1.fq.gz --in2 input_2.fq.gz --out1 output_1.fq.gz --out2 output_2.fq.gz --detect_adapter_for_pe --html report.html
```

**自定义裁剪参数**:
```bash
fastp --in1 input_1.fq.gz --in2 input_2.fq.gz --out1 output_1.fq.gz --out2 output_2.fq.gz --cut_front 10 --cut_tail 5 --cut_mean_quality 20 --length_required 50 --html report.html
```

**多线程处理**:
```bash
fastp --in1 input_1.fq.gz --in2 input_2.fq.gz --out1 output_1.fq.gz --out2 output_2.fq.gz --thread 8 --html report.html
```

## 10. 工具优势与局限性

### 10.1 优势
- **速度快**: 多线程处理，比传统工具快数倍
- **功能全**: 集成了质控、过滤、接头去除等多种功能
- **报告详细**: 生成直观的HTML质控报告
- **自动接头检测**: 无需手动指定接头序列
- **灵活配置**: 丰富的参数选项，适应不同需求

### 10.2 局限性
- **只支持FASTQ格式**: 不支持其他序列格式
- **内存消耗**: 处理大文件时内存消耗较大
- **无参考基因组功能**: 不支持基于参考基因组的质控
- **对长读长数据支持有限**: 主要针对短读长测序数据优化

## 11. 版本更新记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 0.23.4 | 2022-04-15 | 修复了一些bug，优化了性能 |
| 0.23.2 | 2022-01-15 | 增加了对压缩文件的支持 |
| 0.23.0 | 2021-12-01 | 重大更新，增加了许多新功能 |
| 0.22.0 | 2021-08-01 | 优化了接头检测算法 |
| 0.20.0 | 2020-12-01 | 首次发布稳定版本 |

## 12. 联系方式与支持

**工具维护者**: OpenGene团队
**GitHub地址**: https://github.com/OpenGene/fastp
**Bug报告**: https://github.com/OpenGene/fastp/issues
**文档地址**: https://github.com/OpenGene/fastp/blob/master/README.md

## 13. 引用信息

如果使用fastp，请引用以下文章：

Chen, S., Zhou, Y., Chen, Y., & Gu, J. (2018). fastp: an ultra-fast all-in-one FASTQ preprocessor. Bioinformatics, 34(17), i884-i890.

DOI: https://doi.org/10.1093/bioinformatics/bty560