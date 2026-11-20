# bcftools工具Skill

## 1. 工具基本信息

**工具名称**: bcftools
**工具版本**: 1.17
**工具分类**: 变异分析类
**工具描述**: 用于处理和分析VCF/BCF文件的工具集，提供排序、过滤、统计、合并、比较等多种功能，是生信分析中处理变异数据的核心工具
**工具来源**: https://github.com/samtools/bcftools
**Docker镜像**: biocontainers/bcftools:v1.17_cv1

## 2. 输入参数规范

### 2.1 必需参数

| 参数名称 | 短参数 | 长参数 | 参数类型 | 参数说明 | 默认值 | 是否支持通配符 | 取值 |
|---------|--------|--------|---------|---------|--------|----------------|------|
| 命令 | - | - | 字符串 | bcftools子命令(view/filter/stats等) | 无 | 不支持 | 必填 |
| 输入文件 | - | - | 文件路径 | 输入VCF/BCF文件路径 | 无 | 支持 | 必填 |

### 2.2 可选参数

| 参数名称 | 短参数 | 长参数 | 参数类型 | 参数说明 | 默认值 | 推荐值范围 | 取值 |
|---------|--------|--------|---------|---------|---------|------------|------|
| 输出文件 | -o | --output | 文件路径 | 输出文件路径 | stdout | - | 推荐 |
| 输入格式 | -f | --format | 字符串 | 输入文件格式 | auto | vcf/bcf/vcf.gz | 可选 |
| 输出格式 | -O | --output-type | 字符串 | 输出文件格式 | v | v/b/z/B | 推荐 |
| 线程数 | -@ | --threads | 整数 | 线程数 | 1 | 1-32 | 推荐 |
| 区域 | -r | --regions | 字符串 | 目标区域(如"chr1:1000-2000") | 无 | - | 可选 |
| 过滤表达式 | -i | --include | 字符串 | 包含变异的过滤表达式 | 无 | - | 可选 |
| 排除表达式 | -e | --exclude | 字符串 | 排除变异的过滤表达式 | 无 | - | 可选 |
| 样本列表 | -s | --samples | 字符串 | 包含的样本列表 | 无 | - | 可选 |
| 参考基因组 | -f | --fasta-ref | 文件路径 | 参考基因组FASTA文件 | 无 | - | 推荐 |
| 索引 | -t | --tidx | 布尔值 | 创建CSI索引 | 0 | 1 | 可选 |
| 压缩级别 | -l | --compression-level | 整数 | 压缩级别(0-9) | 6 | 0-9 | 可选 |

## 3. 输出文件定义

### 3.1 标准输出文件

| 输出名称 | 文件类型 | 文件格式 | 文件命名规则 | 说明 |
|---------|---------|---------|-------------|------|
| o1 | 处理后VCF/BCF | VCF/BCF | {prefix}.vcf/.bcf | 处理后的变异文件 |
| o2 | 统计结果 | TXT | {prefix}.stats | 变异统计结果 |
| o3 | 过滤结果 | VCF/BCF | {prefix}.filtered.vcf/.bcf | 过滤后的变异文件 |
| o4 | 合并结果 | VCF/BCF | {prefix}.merged.vcf/.bcf | 合并后的变异文件 |
| o5 | 比较结果 | VCF/BCF | {prefix}.compare.vcf/.bcf | 变异比较结果 |

### 3.2 日志文件

| 日志文件 | 日志格式 | 日志内容 |
|---------|---------|----------|
| bcftools.log | 文本 | 执行过程的详细日志，包含参数信息和处理进度 |

## 4. 资源需求配置

### 4.1 CPU需求
- **最小**: 1核
- **推荐**: 4核
- **最大**: 32核

### 4.2 内存需求
- **最小**: 1GB
- **推荐**: 8GB
- **最大**: 32GB

### 4.3 磁盘需求
- **临时空间**: 输入文件大小的2倍
- **输出空间**: 输入文件大小的1.5倍

### 4.4 运行时间预估
| 操作类型 | 数据规模 | 预估运行时间 |
|---------|---------|------------|
| 查看 | 100万变异 | 1-2分钟 |
| 过滤 | 100万变异 | 2-5分钟 |
| 统计 | 100万变异 | 5-10分钟 |
| 合并 | 多个文件 | 10-30分钟 |
| 基因型分析 | 100万变异 | 10-20分钟 |

## 5. 数据类型兼容性

### 5.1 输入数据类型

| 数据类型 | 支持情况 | 格式要求 | 说明 |
|---------|---------|---------|------|
| VCF | 支持 | .vcf | 文本格式变异文件 |
| VCF.gz | 支持 | .vcf.gz | 压缩的VCF文件 |
| BCF | 支持 | .bcf | 二进制格式变异文件 |
| FASTA | 支持 | .fa, .fasta | 参考基因组文件 |
| TXT | 支持 | .txt | 样本列表、区域列表等 |

### 5.2 输出数据类型

| 数据类型 | 格式 | 说明 |
|---------|------|------|
| VCF | 文本格式 | 变异文件 |
| VCF.gz | 压缩文本 | 压缩的变异文件 |
| BCF | 二进制格式 | 二进制变异文件 |
| TXT | 文本格式 | 统计结果、日志等 |
| CSV | 逗号分隔 | 可导出为CSV格式 |

## 6. 依赖关系约束

### 6.1 前置工具
- **必需前置工具**: 无（可直接处理VCF/BCF文件）
- **推荐前置工具**: GATK, Strelka, Mutect2等变异检测工具（生成输入VCF文件）

### 6.2 后置工具

| 工具名称 | 工具分类 | 适用场景 |
|---------|---------|----------|
| annovar | 变异注释类 | 变异注释 |
| VEP | 变异注释类 | 变异注释 |
| R | 数据分析类 | 结果分析和可视化 |
| IGV | 可视化类 | 变异结果可视化 |
| vcftools | 变异分析类 | 变异分析补充 |

### 6.3 互斥工具
- **互斥工具**: vcftools（功能部分重叠，可根据需求选择）
- **替代工具**: 自定义脚本（可实现部分功能）

## 7. 使用场景模板

### 7.1 场景1: VCF文件过滤

**适用场景**: 过滤VCF文件中的变异，保留符合条件的变异
**输入数据**: 变异检测生成的VCF文件
**推荐参数**:
```bash
# 过滤高质量SNV变异
bcftools filter \
  -i 'QUAL>30 && DP>10 && AF>0.01 && TYPE="snp"' \
  -o filtered_snvs.vcf.gz \
  -O z \
  input.vcf.gz

# 索引输出文件
tabix -p vcf filtered_snvs.vcf.gz
```
**预期输出**:
- 过滤后的SNV变异文件(filtered_snvs.vcf.gz)
- 包含高质量、覆盖度足够的SNV变异
- 索引文件(filtered_snvs.vcf.gz.tbi)

### 7.2 场景2: 变异统计分析

**适用场景**: 对VCF文件中的变异进行统计分析
**输入数据**: 变异检测生成的VCF文件
**推荐参数**:
```bash
# 生成详细的变异统计信息
bcftools stats \
  -s - \
  input.vcf.gz > variants.stats

# 查看统计结果
bcftools stats \
  -s - \
  input.vcf.gz | grep -E "SN|Number of"

# 生成质量分布图
bcftools plot \
  -d depth:1,100 \
  -o depth_distribution.pdf \
  input.vcf.gz
```
**预期输出**:
- 变异统计结果文件(variants.stats)
- 包含变异类型、质量、覆盖度等统计信息
- 质量分布图表(depth_distribution.pdf)

### 7.3 场景3: 多样本VCF文件处理

**适用场景**: 处理包含多个样本的VCF文件
**输入数据**: 多样本变异检测生成的VCF文件
**推荐参数**:
```bash
# 提取特定样本
bcftools view \
  -s sample1,sample2 \
  -o samples_subset.vcf.gz \
  -O z \
  input.vcf.gz

# 按样本拆分VCF文件
bcftools view \
  -s sample1 \
  -o sample1.vcf.gz \
  -O z \
  input.vcf.gz

# 合并多个VCF文件
bcftools merge \
  -o merged.vcf.gz \
  -O z \
  sample1.vcf.gz sample2.vcf.gz
```
**预期输出**:
- 特定样本的VCF文件(samples_subset.vcf.gz)
- 单个样本的VCF文件(sample1.vcf.gz)
- 合并后的VCF文件(merged.vcf.gz)

## 8. 质量控制指标

### 8.1 输入数据要求

| 指标 | 要求 | 说明 |
|------|------|------|
| VCF/BCF文件 | 格式正确 | 输入文件必须符合VCF/BCF格式规范 |
| 索引文件 | 完整 | 输入文件必须有对应的索引文件(.tbi或.csi) |
| 参考基因组 | 与变异一致 | 若使用参考基因组，必须与变异检测时使用的一致 |
| 文件完整性 | 完整 | 输入文件完整，无损坏 |

### 8.2 输出质量检查

| 检查项目 | 检查方法 | 合格标准 |
|---------|---------|----------|
| 文件完整性 | 检查文件大小和格式 | 文件大小合理，格式正确 |
| 索引文件 | 检查索引文件 | 输出文件有对应的索引文件 |
| 变异数量 | 统计变异数量 | 变异数量符合预期 |
| 变异质量 | 查看质量统计 | 变异质量符合预期 |
| 样本信息 | 检查样本信息 | 样本信息完整 |

### 8.3 常见错误处理

| 错误类型 | 错误信息 | 解决方案 |
|---------|---------|----------|
| 索引缺失 | `Could not load index` | 为输入文件创建索引(tabix -p vcf file.vcf.gz) |
| 格式错误 | `Invalid VCF format` | 检查输入文件格式是否正确 |
| 内存不足 | `Out of memory` | 增加系统内存或处理更小的区域 |
| 权限错误 | `Permission denied` | 检查文件和目录权限 |
| 区域错误 | `Invalid region` | 检查区域格式是否正确 |
| 过滤表达式错误 | `Invalid filter expression` | 检查过滤表达式语法是否正确 |

## 9. 工具执行示例

### 9.1 基本用法

**查看VCF文件**:
```bash
bcftools view input.vcf.gz | head -20
```

**过滤变异**:
```bash
bcftools filter \
  -i 'QUAL>30 && DP>10' \
  -o filtered.vcf.gz \
  -O z \
  input.vcf.gz
```

**统计变异**:
```bash
bcftools stats input.vcf.gz > stats.txt
```

### 9.2 高级用法

**复杂过滤条件**:
```bash
bcftools filter \
  -i 'QUAL>30 && DP>10 && (AF>0.01 || FILTER="PASS") && TYPE="snp"' \
  -o high_quality_snps.vcf.gz \
  -O z \
  input.vcf.gz
```

**区域过滤**:
```bash
bcftools view \
  -r chr1:1000000-2000000 \
  -o region_chr1.vcf.gz \
  -O z \
  input.vcf.gz
```

**样本操作**:
```bash
# 提取样本列表
bcftools query -l input.vcf.gz > samples.txt

# 按样本拆分
bcftools view \
  -s @samples.txt \
  -o samples_subset.vcf.gz \
  -O z \
  input.vcf.gz
```

**合并文件**:
```bash
bcftools merge \
  -o merged.vcf.gz \
  -O z \
  --threads 4 \
  sample1.vcf.gz sample2.vcf.gz sample3.vcf.gz
```

**基因型分析**:
```bash
bcftools gtcheck \
  -g input.vcf.gz \
  -s samples.txt \
  -o genotype_check.txt
```

## 10. 工具优势与局限性

### 10.1 优势
- **功能丰富**: 提供多种VCF/BCF文件处理功能
- **性能优异**: 处理速度快，内存使用高效
- **格式支持**: 支持VCF和BCF格式，包括压缩格式
- **灵活的过滤**: 支持复杂的过滤表达式
- **统计功能**: 提供详细的变异统计信息
- **多样本处理**: 支持多样本VCF文件的处理
- **可视化支持**: 提供基本的变异可视化功能
- **持续维护**: 持续更新和维护

### 10.2 局限性
- **学习曲线**: 命令行参数较多，需要一定学习成本
- **可视化功能**: 可视化功能相对简单，复杂可视化需要其他工具
- **资源需求**: 处理大型VCF文件时需要较多计算资源
- **错误处理**: 错误信息有时不够详细
- **功能重叠**: 与vcftools等工具功能部分重叠

## 11. 版本更新记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 1.17 | 2023-02-15 | 增加了新功能，改进了性能和稳定性 |
| 1.16 | 2022-07-22 | 修复了多个bug，改进了内存使用 |
| 1.15 | 2022-01-12 | 增加了新的过滤选项和统计功能 |
| 1.14 | 2021-05-17 | 改进了BCF格式支持，增加了新功能 |
| 1.13 | 2020-10-24 | 修复了多个bug，改进了性能 |
| 1.12 | 2020-03-27 | 增加了新的工具和功能 |
| 1.11 | 2019-08-15 | 改进了多线程性能，增加了新功能 |
| 1.10 | 2019-01-25 | 首次发布支持BCFv2.2格式的版本 |

## 12. 联系方式与支持

**工具维护者**: samtools/bcftools团队
**GitHub地址**: https://github.com/samtools/bcftools
**Bug报告**: https://github.com/samtools/bcftools/issues
**文档地址**: https://samtools.github.io/bcftools/
**邮件列表**: samtools-help@lists.sourceforge.net

## 13. 引用信息

如果使用bcftools，请引用以下文章：

Danecek, P., et al. (2021). Twelve years of SAMtools and BCFtools. Gigascience, 10(2), giab008.

DOI: https://doi.org/10.1093/gigascience/giab008

以及原始发表文章：

Li, H., et al. (2009). The Sequence Alignment/Map format and SAMtools. Bioinformatics, 25(16), 2078-2079.

DOI: https://doi.org/10.1093/bioinformatics/btp352