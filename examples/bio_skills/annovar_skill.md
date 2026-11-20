# ANNOVAR工具Skill

## 1. 工具基本信息

**工具名称**: ANNOVAR (ANNOtate VARiation)
**工具版本**: 2021-08-19
**工具分类**: 变异注释类
**工具描述**: 快速高效的基因组变异注释工具，能够对SNP、Indel等变异进行功能注释，提供基因、转录本、蛋白质、调控区域等多层面的注释信息
**工具来源**: https://annovar.openbioinformatics.org/en/latest/
**Docker镜像**: biocontainers/annovar:v20210819_cv1

## 2. 输入参数规范

### 2.1 必需参数

| 参数名称 | 短参数 | 长参数 | 参数类型 | 参数说明 | 默认值 | 是否支持通配符 | 取值 |
|---------|--------|--------|---------|---------|--------|----------------|------|
| 输入文件 | - | - | 文件路径 | 输入VCF文件路径 | 无 | 支持 | 必填 |
| 命令 | - | table_annovar.pl | 字符串 | ANNOVAR注释命令 | 无 | 不支持 | 必填 |
| 数据库目录 | - | --buildver | 字符串 | 参考基因组版本 | 无 | 不支持 | 必填 |
| 操作类型 | - | --operation | 字符串 | 注释操作类型 | 无 | 不支持 | 必填 |
| 输出前缀 | - | --outfile | 字符串 | 输出文件前缀 | 无 | 不支持 | 必填 |

### 2.2 可选参数

| 参数名称 | 短参数 | 长参数 | 参数类型 | 参数说明 | 默认值 | 推荐值范围 | 取值 |
|---------|--------|--------|---------|---------|---------|------------|------|
| 输入格式 | - | --format | 字符串 | 输入文件格式 | vcf4 | vcf4/vcf4old | 可选 |
| 线程数 | - | --thread | 整数 | 线程数 | 1 | 1-32 | 推荐 |
| 注释数据库 | - | --dbtype | 字符串 | 注释数据库类型 | 无 | refGene/ensGene | 推荐 |
| 过滤条件 | - | --filter | 字符串 | 注释过滤条件 | 无 | - | 可选 |
| 注释选项 | - | --otherinfo | 布尔值 | 保留原始VCF中的其他信息 | 0 | 1 | 可选 |
| 数据库路径 | - | --dir | 文件路径 | 注释数据库目录 | $ANNOVAR_DBDIR | - | 推荐 |
| 批处理大小 | - | --batchsize | 整数 | 批处理大小 | 1000 | 100-10000 | 可选 |
| 压缩输出 | - | --gz | 布尔值 | 压缩输出文件 | 0 | 1 | 可选 |

## 3. 输出文件定义

### 3.1 标准输出文件

| 输出名称 | 文件类型 | 文件格式 | 文件命名规则 | 说明 |
|---------|---------|---------|-------------|------|
| o1 | 注释结果 | TXT | {prefix}.{buildver}_multianno.txt | 多数据库注释结果，制表符分隔 |
| o2 | 注释VCF | VCF | {prefix}.{buildver}_multianno.vcf | 注释后的VCF文件 |
| o3 | 过滤结果 | TXT | {prefix}.{buildver}_multianno_filtered.txt | 经过过滤的注释结果 |
| o4 | 统计文件 | TXT | {prefix}.{buildver}_multianno_summary.txt | 注释统计信息 |

### 3.2 日志文件

| 日志文件 | 日志格式 | 日志内容 |
|---------|---------|----------|
| annovar.log | 文本 | 执行过程的详细日志，包含参数信息和处理进度 |

## 4. 资源需求配置

### 4.1 CPU需求
- **最小**: 1核
- **推荐**: 4核
- **最大**: 16核

### 4.2 内存需求
- **最小**: 2GB
- **推荐**: 8GB
- **最大**: 16GB

### 4.3 磁盘需求
- **临时空间**: 输入文件大小的2倍
- **输出空间**: 输入文件大小的3倍（取决于注释数据库的大小）
- **数据库空间**: 约50GB（注释数据库占用空间）

### 4.4 运行时间预估
| 数据规模 | 预估运行时间 |
|---------|------------|
| 10,000个变异 | 5-10分钟 |
| 100,000个变异 | 30-60分钟 |
| 1,000,000个变异 | 2-4小时 |

## 5. 数据类型兼容性

### 5.1 输入数据类型

| 数据类型 | 支持情况 | 格式要求 | 说明 |
|---------|---------|---------|------|
| VCF | 支持 | .vcf, .vcf.gz | 变异检测结果文件 |
| TXT | 支持 | .txt | ANNOVAR输入格式文件 |
| AVCF | 支持 | .avcf | 注释后的VCF文件 |

### 5.2 输出数据类型

| 数据类型 | 格式 | 说明 |
|---------|------|------|
| TXT | 制表符分隔 | 多数据库注释结果 |
| VCF | 文本格式 | 注释后的VCF文件 |
| CSV | 逗号分隔 | 可导出为CSV格式 |

## 6. 依赖关系约束

### 6.1 前置工具
- **必需前置工具**: GATK, Strelka, Mutect2等变异检测工具（生成输入VCF文件）
- **推荐前置工具**: bcftools（VCF文件处理和过滤）

### 6.2 后置工具

| 工具名称 | 工具分类 | 适用场景 |
|---------|---------|----------|
| R | 数据分析类 | 注释结果分析和可视化 |
| maftools | 数据分析类 | MAF文件处理和可视化 |
| Excel | 办公软件 | 手动查看和分析注释结果 |

### 6.3 互斥工具
- **互斥工具**: VEP（功能重叠，可根据需求选择）
- **替代工具**: InterVar, CancerVar（专注于特定类型变异的注释）

## 7. 使用场景模板

### 7.1 场景1: 基本功能注释

**适用场景**: 对变异进行基本的基因功能注释
**输入数据**: 变异检测生成的VCF文件，ANNOVAR注释数据库
**推荐参数**:
```bash
# 下载注释数据库
annotate_variation.pl -buildver hg19 -downdb -webfrom annovar refGene humandb/
annotate_variation.pl -buildver hg19 -downdb -webfrom annovar knownGene humandb/
annotate_variation.pl -buildver hg19 -downdb -webfrom annovar dbsnp138 humandb/

# 运行ANNOVAR注释
table_annovar.pl input.vcf humandb/ \
  --buildver hg19 \
  --outfile annovar_output \
  --remove \
  --protocol refGene,knownGene,dbsnp138 \
  --operation gx,gx,f \
  --thread 4 \
  --otherinfo \
  --nastring .
```
**预期输出**:
- 基本功能注释结果(annovar_output.hg19_multianno.txt)
- 注释后的VCF文件(annovar_output.hg19_multianno.vcf)
- 包含基因、转录本、dbSNP等基本注释信息

### 7.2 场景2: 全面临床注释

**适用场景**: 对变异进行全面的临床相关注释
**输入数据**: 变异检测生成的VCF文件，完整的ANNOVAR注释数据库
**推荐参数**:
```bash
# 下载更多注释数据库
annotate_variation.pl -buildver hg19 -downdb -webfrom annovar 1000g2015aug humandb/
annotate_variation.pl -buildver hg19 -downdb -webfrom annovar exac03 humandb/
annotate_variation.pl -buildver hg19 -downdb -webfrom annovar esp6500siv2_all humandb/
annotate_variation.pl -buildver hg19 -downdb -webfrom annovar clinvar_20210501 humandb/

# 运行全面注释
table_annovar.pl input.vcf humandb/ \
  --buildver hg19 \
  --outfile annovar_clinical \
  --remove \
  --protocol refGene,knownGene,dbsnp138,1000g2015aug_all,exac03,esp6500siv2_all,clinvar_20210501 \
  --operation gx,gx,f,f,f,f,f \
  --thread 8 \
  --otherinfo \
  --nastring .
```
**预期输出**:
- 全面的临床注释结果，包含基因、频率、临床意义等信息
- 注释后的VCF文件，可用于后续分析

### 7.3 场景3: 癌症相关注释

**适用场景**: 对癌症样本的变异进行癌症相关的注释
**输入数据**: 癌症样本的变异检测VCF文件，癌症相关注释数据库
**推荐参数**:
```bash
# 下载癌症相关数据库
annotate_variation.pl -buildver hg19 -downdb -webfrom annovar cosmic70 humandb/
annotate_variation.pl -buildver hg19 -downdb -webfrom annovar kegg_pathway humandb/

# 运行癌症相关注释
table_annovar.pl tumor_variants.vcf humandb/ \
  --buildver hg19 \
  --outfile annovar_cancer \
  --remove \
  --protocol refGene,cosmic70,kegg_pathway,dbsnp138 \
  --operation gx,f,p,f \
  --thread 4 \
  --otherinfo \
  --nastring .
```
**预期输出**:
- 癌症相关注释结果，包含COSMIC数据库信息、通路信息等
- 有助于识别癌症驱动基因和潜在的治疗靶点

## 8. 质量控制指标

### 8.1 输入数据要求

| 指标 | 要求 | 说明 |
|------|------|------|
| VCF文件 | 格式正确 | 输入VCF文件必须符合VCF格式规范 |
| 数据库完整性 | 完整 | 所需的注释数据库必须下载完整 |
| 参考基因组 | 版本匹配 | 注释数据库的参考基因组版本必须与输入VCF一致 |
| 索引文件 | 存在 | 数据库文件必须有对应的索引文件 |

### 8.2 输出质量检查

| 检查项目 | 检查方法 | 合格标准 |
|---------|---------|----------|
| 注释完整性 | 统计注释率 | 注释率 > 95% |
| 注释一致性 | 比对不同数据库结果 | 关键注释信息一致 |
| 文件完整性 | 检查文件大小和格式 | 文件大小合理，格式正确 |
| 基因覆盖 | 检查基因注释 | 重要基因变异都有注释 |
| 频率信息 | 检查频率数据库注释 | 常见变异有频率信息 |

### 8.3 常见错误处理

| 错误类型 | 错误信息 | 解决方案 |
|---------|---------|----------|
| 数据库缺失 | `Cannot find database file` | 下载缺失的注释数据库 |
| 版本不匹配 | `Build version not found` | 确保数据库版本与参考基因组一致 |
| 权限错误 | `Permission denied` | 检查文件和目录权限 |
| 内存不足 | `Out of memory` | 减少批处理大小或增加系统内存 |
| 格式错误 | `Invalid VCF format` | 检查并修复输入VCF文件格式 |

## 9. 工具执行示例

### 9.1 基本用法

**基本注释**:
```bash
table_annovar.pl input.vcf humandb/ \
  --buildver hg19 \
  --outfile output \
  --protocol refGene,dbsnp138 \
  --operation gx,f \
  --thread 4
```

**指定输入格式**:
```bash
table_annovar.pl input.vcf humandb/ \
  --buildver hg19 \
  --outfile output \
  --format vcf4 \
  --protocol refGene \
  --operation gx
```

### 9.2 高级用法

**使用多个数据库**:
```bash
table_annovar.pl input.vcf humandb/ \
  --buildver hg19 \
  --outfile comprehensive_output \
  --protocol refGene,knownGene,ensGene,dbsnp138,1000g2015aug_all,exac03,esp6500siv2_all,clinvar_20210501 \
  --operation gx,gx,gx,f,f,f,f,f \
  --thread 8 \
  --otherinfo \
  --nastring .
```

**批量处理**:
```bash
for vcf in *.vcf; do
  base=$(basename $vcf .vcf)
  
  table_annovar.pl $vcf humandb/ \
    --buildver hg19 \
    --outfile ${base}_annovar \
    --protocol refGene,dbsnp138 \
    --operation gx,f \
    --thread 4 \
    --otherinfo
done
```

**过滤注释结果**:
```bash
# 运行注释
table_annovar.pl input.vcf humandb/ \
  --buildver hg19 \
  --outfile filtered_output \
  --protocol refGene,dbsnp138 \
  --operation gx,f \
  --thread 4

# 过滤掉同义突变
awk 'NR==1 || $6 != "synonymous SNV"' filtered_output.hg19_multianno.txt > filtered_nonsynonymous.txt
```

## 10. 工具优势与局限性

### 10.1 优势
- **速度快**: 注释速度快，适合处理大规模变异数据
- **数据库丰富**: 支持多种注释数据库，覆盖基因、频率、临床意义等多个层面
- **灵活性高**: 可以根据需要选择不同的注释数据库和操作类型
- **输出格式友好**: 输出制表符分隔的文本文件，易于查看和处理
- **支持多线程**: 支持并行处理，提高注释速度
- **持续更新**: 定期更新注释数据库和软件功能

### 10.2 局限性
- **数据库下载**: 需要手动下载和更新注释数据库，过程较为繁琐
- **内存需求**: 处理大规模数据时内存需求较高
- **学习曲线**: 命令行参数较多，需要一定学习成本
- **注释深度**: 某些特殊类型变异的注释可能不够深入
- **临床解读**: 仅提供注释信息，不提供临床意义的解读
- **数据库大小**: 完整数据库占用空间较大（约50GB）

## 11. 版本更新记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 2021-08-19 | 2021-08-19 | 增加了新的注释数据库，改进了注释算法 |
| 2020-06-08 | 2020-06-08 | 改进了VCF文件处理，增加了新的数据库支持 |
| 2019-10-24 | 2019-10-24 | 修复了多个bug，改进了注释准确性 |
| 2018-04-16 | 2018-04-16 | 增加了对GRCh38的支持，改进了注释功能 |
| 2016-02-01 | 2016-02-01 | 首次发布支持VCF4.2格式的版本 |

## 12. 联系方式与支持

**工具维护者**: Kai Wang (哈佛医学院)
**官方网站**: https://annovar.openbioinformatics.org/en/latest/
**文档地址**: https://annovar.openbioinformatics.org/en/latest/user-guide/download/
**邮件支持**: wang.kai@mgh.harvard.edu
**GitHub地址**: https://github.com/WGLab/annovar

## 13. 引用信息

如果使用ANNOVAR，请引用以下文章：

Wang, K., Li, M., & Hakonarson, H. (2010). ANNOVAR: functional annotation of genetic variants from high-throughput sequencing data. Nucleic acids research, 38(16), e164-e164.

DOI: https://doi.org/10.1093/nar/gkq603

对于特定数据库的注释，请同时引用相关数据库的出版物。