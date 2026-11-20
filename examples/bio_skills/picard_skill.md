# Picard工具Skill

## 1. 工具基本信息

**工具名称**: Picard
**工具版本**: 2.27.5
**工具分类**: 数据处理类
**工具描述**: 用于处理高通量测序数据的Java工具集，提供标记重复序列、排序、格式转换等多种功能，是GATK分析流程的重要组成部分
**工具来源**: https://github.com/broadinstitute/picard
**Docker镜像**: broadinstitute/picard:2.27.5

## 2. 输入参数规范

### 2.1 必需参数

| 参数名称 | 短参数 | 长参数 | 参数类型 | 参数说明 | 默认值 | 是否支持通配符 | 取值 |
|---------|--------|--------|---------|---------|--------|----------------|------|
| 命令 | - | - | 字符串 | Picard工具命令(MarkDuplicates/SortSam等) | 无 | 不支持 | 必填 |
| 输入文件 | I | INPUT | 文件路径 | 输入文件路径 | 无 | 支持 | 必填 |
| 输出文件 | O | OUTPUT | 文件路径 | 输出文件路径 | 无 | 支持 | 必填 |

### 2.2 可选参数

| 参数名称 | 短参数 | 长参数 | 参数类型 | 参数说明 | 默认值 | 推荐值范围 | 取值 |
|---------|--------|--------|---------|---------|---------|------------|------|
| 参考基因组 | R | REFERENCE_SEQUENCE | 文件路径 | 参考基因组FASTA文件 | 无 | - | 可选 |
| 内存分配 | - | J | 字符串 | JVM内存分配(如-Xmx8G) | - | - | 推荐 |
| 线程数 | - | MAX_RECORDS_IN_RAM | 整数 | 内存中最大记录数 | 500000 | 100000-2000000 | 可选 |
| 排序顺序 | SO | SORT_ORDER | 字符串 | 排序顺序(Coordinate/Queryname等) | Coordinate | Coordinate | 可选 |
| 重复标记 | M | METRICS_FILE | 文件路径 | 重复序列统计文件 | 无 | - | 推荐 |
| 光学重复 | OR | OPTICAL_DUPLICATE_PIXEL_DISTANCE | 整数 | 光学重复像素距离 | 100 | 100-2500 | 可选 |
| 创建索引 | CREATE_INDEX | - | 布尔值 | 是否创建索引 | false | true | 推荐 |
| 验证字符串ency | VALIDATION_STRINGENCY | - | 字符串 | 验证严格性(STRICT/LENIENT/SILENT) | STRICT | LENIENT | 可选 |
| 压缩级别 | COMPRESSION_LEVEL | - | 整数 | 输出压缩级别(0-9) | 5 | 0-9 | 可选 |
| 临时目录 | TMP_DIR | - | 文件路径 | 临时文件目录 | java.io.tmpdir | - | 可选 |

## 3. 输出文件定义

### 3.1 标准输出文件

| 输出名称 | 文件类型 | 文件格式 | 文件命名规则 | 说明 |
|---------|---------|---------|-------------|------|
| o1 | 处理后文件 | BAM/SAM | 根据命令和参数 | 处理后的序列比对文件 |
| o2 | 统计文件 | TXT | {prefix}_metrics.txt | 各种统计信息文件 |
| o3 | 索引文件 | BAI | {input}.bai | 生成的索引文件 |
| o4 | 报告文件 | HTML | {prefix}_report.html | 可视化报告文件 |

### 3.2 日志文件

| 日志文件 | 日志格式 | 日志内容 |
|---------|---------|----------|
| picard.log | 文本 | 执行过程的详细日志，包含参数信息和处理进度 |

## 4. 资源需求配置

### 4.1 CPU需求
- **最小**: 1核
- **推荐**: 4核
- **最大**: 16核

### 4.2 内存需求
- **最小**: 4GB
- **推荐**: 16GB
- **最大**: 64GB

### 4.3 磁盘需求
- **临时空间**: 输入文件大小的2倍
- **输出空间**: 输入文件大小的1.5倍

### 4.4 运行时间预估
| 命令 | 数据规模 | 预估运行时间 |
|------|---------|------------|
| MarkDuplicates | 10G BAM | 30-60分钟 |
| SortSam | 10G BAM | 15-30分钟 |
| AddOrReplaceReadGroups | 10G BAM | 5-15分钟 |
| CollectWgsMetrics | 10G BAM | 20-40分钟 |

## 5. 数据类型兼容性

### 5.1 输入数据类型

| 数据类型 | 支持情况 | 格式要求 | 说明 |
|---------|---------|---------|------|
| BAM | 支持 | .bam | 二进制比对文件 |
| SAM | 支持 | .sam | 文本比对文件 |
| CRAM | 支持 | .cram | 压缩比对文件 |
| FASTQ | 支持 | .fq, .fastq | 序列文件(部分命令) |
| VCF | 支持 | .vcf | 变异文件(部分命令) |

### 5.2 输出数据类型

| 数据类型 | 格式 | 说明 |
|---------|------|------|
| BAM | 二进制格式 | 主要输出格式 |
| SAM | 文本格式 | 可选输出格式 |
| CRAM | 压缩格式 | 可选输出格式 |
| TXT | 文本格式 | 统计信息文件 |
| HTML | 网页格式 | 报告文件 |

## 6. 依赖关系约束

### 6.1 前置工具
- **必需前置工具**: 无
- **推荐前置工具**: bwa, samtools（生成输入BAM文件）

### 6.2 后置工具

| 工具名称 | 工具分类 | 适用场景 |
|---------|---------|----------|
| GATK | 变异检测类 | 变异检测和重校准 |
| samtools | 数据处理类 | 进一步处理BAM文件 |
| bcftools | 变异检测类 | VCF文件处理 |

### 6.3 互斥工具
- **互斥工具**: 无
- **替代工具**: sambamba（部分功能可替代）

## 7. 使用场景模板

### 7.1 场景1: 标记重复序列

**适用场景**: 检测和标记PCR重复序列
**输入数据**: 已排序的BAM文件
**推荐参数**:
```bash
java -Xmx16G -jar picard.jar MarkDuplicates \
  INPUT=sorted.bam \
  OUTPUT=dedup.bam \
  METRICS_FILE=duplicate_metrics.txt \
  OPTICAL_DUPLICATE_PIXEL_DISTANCE=2500 \
  CREATE_INDEX=true
```
**预期输出**:
- 标记重复后的BAM文件(dedup.bam)
- 重复序列统计文件(duplicate_metrics.txt)
- BAM索引文件(dedup.bam.bai)

### 7.2 场景2: 添加读取组信息

**适用场景**: 为BAM文件添加或替换读取组信息
**输入数据**: BAM文件
**推荐参数**:
```bash
java -Xmx8G -jar picard.jar AddOrReplaceReadGroups \
  INPUT=input.bam \
  OUTPUT=rg_added.bam \
  RGID=sample1 \
  RGLB=library1 \
  RGPL=ILLUMINA \
  RGPU=unit1 \
  RGSM=sample1 \
  CREATE_INDEX=true
```
**预期输出**:
- 添加读取组后的BAM文件(rg_added.bam)
- BAM索引文件(rg_added.bam.bai)

### 7.3 场景3: 计算全基因组测序指标

**适用场景**: 计算全基因组测序的覆盖度和质量指标
**输入数据**: 已标记重复的BAM文件，参考基因组
**推荐参数**:
```bash
java -Xmx8G -jar picard.jar CollectWgsMetrics \
  INPUT=dedup.bam \
  OUTPUT=wgs_metrics.txt \
  REFERENCE_SEQUENCE=reference.fasta \
  INCLUDE_BQ_HISTOGRAM=true
```
**预期输出**:
- 全基因组测序指标文件(wgs_metrics.txt)
- 包含覆盖度、质量分布等详细信息

## 8. 质量控制指标

### 8.1 输入数据要求

| 指标 | 要求 | 说明 |
|------|------|------|
| 文件完整性 | 完整 | 输入文件不能损坏 |
| 格式正确 | 标准格式 | 符合SAM/BAM/CRAM格式规范 |
| 排序状态 | 已排序 | 某些命令要求输入文件已排序 |
| 参考基因组 | 一致 | 与比对时使用的参考基因组一致 |

### 8.2 输出质量检查

| 检查项目 | 检查方法 | 合格标准 |
|---------|---------|----------|
| 文件完整性 | samtools quickcheck | 无错误报告 |
| 索引存在 | 文件系统检查 | 对应索引文件存在且大小合理 |
| 统计信息 | 查看metrics文件 | 统计数据合理 |
| 读取组信息 | samtools view -H | 包含正确的读取组信息 |
| 重复率 | 查看duplicate metrics | 重复率在合理范围内(<30%) |

### 8.3 常见错误处理

| 错误类型 | 错误信息 | 解决方案 |
|---------|---------|----------|
| 内存不足 | `java.lang.OutOfMemoryError` | 增加JVM内存分配(-Xmx参数) |
| 文件不存在 | `java.io.FileNotFoundException` | 检查文件路径是否正确 |
| 格式错误 | `SAMFormatException` | 检查输入文件格式是否正确 |
| 验证失败 | `ValidationException` | 降低验证严格性(VALIDATION_STRINGENCY=LENIENT) |
| 权限错误 | `java.io.IOException: Permission denied` | 检查文件和目录权限 |

## 9. 工具执行示例

### 9.1 基本用法

**排序BAM文件**:
```bash
java -Xmx8G -jar picard.jar SortSam \
  INPUT=unsorted.bam \
  OUTPUT=sorted.bam \
  SORT_ORDER=Coordinate \
  CREATE_INDEX=true
```

**合并BAM文件**:
```bash
java -Xmx8G -jar picard.jar MergeSamFiles \
  INPUT=sample1.bam \
  INPUT=sample2.bam \
  OUTPUT=merged.bam \
  CREATE_INDEX=true
```

**提取特定区域**:
```bash
java -Xmx8G -jar picard.jar ViewSam \
  INPUT=input.bam \
  OUTPUT=output.sam \
  REGION=chr1:1000000-2000000
```

### 9.2 高级用法

**批量处理标记重复**:
```bash
for bam in *.bam; do
  base=$(basename $bam .bam)
  java -Xmx16G -jar picard.jar MarkDuplicates \
    INPUT=$bam \
    OUTPUT=${base}_dedup.bam \
    METRICS_FILE=${base}_duplicates.txt \
    CREATE_INDEX=true
done
```

**自定义内存和线程**:
```bash
java -Xmx32G -jar picard.jar MarkDuplicates \
  INPUT=input.bam \
  OUTPUT=output.bam \
  METRICS_FILE=metrics.txt \
  MAX_RECORDS_IN_RAM=1000000 \
  TMP_DIR=/tmp \
  CREATE_INDEX=true
```

**使用管道**:
```bash
samtools view -bS input.sam | \
java -Xmx8G -jar picard.jar SortSam \
  INPUT=/dev/stdin \
  OUTPUT=sorted.bam \
  SORT_ORDER=Coordinate
```

## 10. 工具优势与局限性

### 10.1 优势
- **功能全面**: 提供多种BAM/SAM处理功能
- **可靠性高**: 由Broad Institute维护，质量有保障
- **与GATK集成**: 与GATK分析流程无缝集成
- **详细的统计信息**: 生成全面的质量和性能指标
- **Java实现**: 跨平台兼容性好
- **持续更新**: 定期更新和维护

### 10.2 局限性
- **内存消耗大**: Java实现，内存需求较高
- **执行速度较慢**: 相比C/C++工具，速度较慢
- **命令复杂**: 参数较多，学习曲线较陡
- **临时空间需求**: 处理大文件时需要大量临时空间
- **依赖Java**: 需要Java运行环境

## 11. 版本更新记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 2.27.5 | 2023-02-15 | 修复了一些bug，优化了性能 |
| 2.26.10 | 2022-05-15 | 增加了新的工具和功能 |
| 2.25.6 | 2021-12-01 | 改进了内存使用和错误处理 |
| 2.24.1 | 2021-05-01 | 增加了对Java 11的支持 |
| 2.23.9 | 2020-12-01 | 修复了COVID-19相关工具的问题 |
| 2.20.0 | 2019-10-01 | 重大更新，重新组织了工具结构 |

## 12. 联系方式与支持

**工具维护者**: Broad Institute
**GitHub地址**: https://github.com/broadinstitute/picard
**Bug报告**: https://github.com/broadinstitute/picard/issues
**文档地址**: https://broadinstitute.github.io/picard/

## 13. 引用信息

如果使用Picard工具，请引用Broad Institute和相关文章：

Broad Institute. Picard Toolkit. https://broadinstitute.github.io/picard/

对于特定工具的引用，请参考该工具的文档或相关出版物。