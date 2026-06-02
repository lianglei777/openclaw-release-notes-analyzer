# OpenClaw Release Notes Analyzer

OpenClaw Release Notes Analyzer 是一个用于分析 [OpenClaw](https://github.com/openclaw/openclaw) GitHub Release Notes 的智能工具。它能帮助开发者快速了解版本间的变化，评估升级风险，并给出场景化的升级建议。

**输出语言**：固定输出中文报告。技术专有名词（OpenClaw, API, SDK, CLI, hook, manifest, plugin 等）保持英文。

---

## 目录

- [功能特性](#功能特性)
- [适用场景](#适用场景)
- [安装](#安装)
- [快速开始](#快速开始)
- [命令行参数](#命令行参数)
- [使用示例](#使用示例)
- [分析模式详解](#分析模式详解)
- [报告结构](#报告结构)
- [文件位置](#文件位置)
- [GitHub Token](#github-token)
- [缓存管理](#缓存管理)
- [常见问题](#常见问题)

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **Release 自动获取** | 从 GitHub Releases API 自动拉取最新的 release metadata 和 release notes |
| **规则基线分析** | 基于关键词加权、显式信号验证、章节上下文分类的**两级过滤**架构 |
| **LLM 增强分析** | Commit-message bridge 方法，将 release notes 与 commits 进行语义关联分析 |
| **主题聚类** | 将变更语义聚类为 8-15 个功能主题，按风险排序 |
| **渐进式修复检测** | 识别跨越多个版本的 bug 修复链（缓解 -> 部分修复 -> 完整修复） |
| **累积 Breaking Change 分析** | 评估版本范围升级的累积风险 |
| **Shadow Change 检测** | 发现修改了公开 surface 但没有对应 release note 的 commits |
| **场景化升级建议** | 针对 Plugin 开发者、API/SDK 使用者、安全敏感用户、稳定性敏感用户、普通用户分别给出建议 |
| **中文 Release Notes 支持** | 自动检测中英文关键词进行分类 |
| **Conventional Commit 识别** | 识别 `feat:`, `fix:`, `perf:`, `BREAKING CHANGE:` 等前缀 |
| **自动分块处理** | 大型 release 自动拆分为多个 chunk 分析，突破上下文限制 |
| **缓存一致性验证** | 每次加载缓存时自动验证结构完整性、payload 一致性、时效性 |

---

## 适用场景

- 分析最新 OpenClaw release
- 对比两个 OpenClaw 版本
- 汇总某个版本范围内的所有变化
- 检查更新是否包含重要 bug fix 或 feature
- 评估升级对插件开发者、API/SDK 使用者、安全/稳定性敏感用户的影响
- 预览 beta、alpha、rc 等 prerelease 版本
- 检查 release notes 中的插件、API、SDK、安全、性能或 breaking-change 信号

---

## 安装

### 环境要求

- Python 3.9+
- 网络可访问 GitHub API
- GitHub Token（用于 LLM 增强分析，[如何获取](#github-token)）

### 安装步骤

```bash
# 克隆仓库
git clone <repo-url>
cd openclaw-release-analyzer

# 进入脚本目录
cd openclaw-release-notes-analyzer/scripts

# 安装依赖（本项目无外部依赖，仅需 Python 标准库）
python --version  # 确保 >= 3.9
```

> **注意**：本项目**不依赖任何第三方 Python 包**，仅使用标准库。

---

## 快速开始

### 1. 设置 GitHub Token

```bash
# Linux / macOS
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# Windows (PowerShell)
$env:GITHUB_TOKEN = "ghp_xxxxxxxxxxxx"

# Windows (CMD)
set GITHUB_TOKEN=ghp_xxxxxxxxxxxx
```

### 2. 分析最新稳定版

```bash
python analyze_openclaw_release.py --latest
```

分析完成后，报告会自动写入当前工作目录，文件名格式为 `{repo}-{version}-analysis.md`。

---

## 命令行参数

```
python analyze_openclaw_release.py [选项]
```

### 核心参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--latest` | 分析最新稳定 release | `--latest` |
| `--target <版本>` | 指定目标 release 版本 | `--target v1.3.0` |
| `--compare <版本>` | 指定对比的基准版本 | `--compare v1.2.3` |
| `--from <版本>` | 版本范围分析的起始版本 | `--from v1.1.0` |
| `--to <版本>` | 版本范围分析的终止版本 | `--to v1.3.0` |
| `--include-beta` | 在报告中包含 prerelease 预览章节 | `--include-beta` |

### 认证与 API

| 参数 | 说明 | 示例 |
|------|------|------|
| `--github-token <token>` | GitHub Personal Access Token | `--github-token ghp_xxx` |
| `--repo <owner/name>` | 分析的仓库（默认 `openclaw/openclaw`）| `--repo owner/repo` |

### 输出控制

| 参数 | 说明 | 示例 |
|------|------|------|
| `--output <路径>` | 指定报告输出路径 | `--output ./reports/v1.3.0.md` |
| `--format <格式>` | 输出格式：`markdown` 或 `json`（默认 `markdown`）| `--format json` |
| `--lang <语言>` | 输出语言（保留参数，固定为中文）| `--lang zh` |

### LLM 分析控制（高级）

| 参数 | 说明 |
|------|------|
| `--prepare-analysis-data` | 生成 `analysis-data.json` 后退出，由外部 AI Agent 执行 LLM 分析 |
| `--apply-llm-results <路径>` | 应用 LLM 分析结果 JSON 文件并生成最终报告 |
| `--prepare-chunks` | 自动将分析数据拆分为多个 chunks |
| `--merge-chunk-results` | 合并所有 chunk 结果文件 |
| `--recursive-analysis` | 对多版本分析使用递归合并聚合策略 |

### 缓存管理

| 参数 | 说明 |
|------|------|
| `--snapshot-dir <目录>` | 自定义 snapshot 缓存目录（默认使用平台缓存目录）|
| `--clean-cache` | 清理所有缓存 snapshot 和中间文件 |

---

## 使用示例

### 示例 1：分析最新稳定版（最常用）

```bash
# 方式 A：环境变量传 token
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python analyze_openclaw_release.py --latest

# 方式 B：命令行参数传 token
python analyze_openclaw_release.py --latest --github-token ghp_xxxxxxxxxxxx
```

### 示例 2：分析指定版本

```bash
python analyze_openclaw_release.py --target v2026.5.18
```

### 示例 3：版本对比分析（两个版本之间）

```bash
# 完整 LLM 增强分析流程（三步）

# 步骤 1：准备分析数据
python analyze_openclaw_release.py --target v1.3.0 --compare v1.2.3 --prepare-analysis-data

# 步骤 2：将生成的 analysis-data.json 交给 AI Agent（如 Claude Code）执行 LLM 分析
# AI Agent 分析完成后会生成 llm-results.json

# 步骤 3：应用 LLM 结果生成最终报告
python analyze_openclaw_release.py --target v1.3.0 --compare v1.2.3 \
  --apply-llm-results "<snapshot-dir>/openclaw-openclaw-v1.3.0-llm-results.json"
```

> **快捷方式**：如果 snapshot 目录中已存在上次的 `llm-results.json`，直接运行 `--target --compare` 即可自动检测并应用，无需 `--apply-llm-results`。

### 示例 4：版本范围分析（多个版本）

```bash
python analyze_openclaw_release.py --from v1.1.0 --to v1.3.0
```

适用于一次性跨越多个版本升级的场景，会自动检测渐进式修复链和累积 breaking changes。

### 示例 5：包含 Beta/Prerelease 预览

```bash
python analyze_openclaw_release.py --latest --include-beta
```

在分析最新稳定版的同时，额外展示比稳定版更新的 beta/prerelease 版本作为前瞻性预览。

### 示例 6：指定输出路径

```bash
python analyze_openclaw_release.py --latest --output ./reports/openclaw-latest-analysis.md
```

### 示例 7：JSON 格式输出

```bash
python analyze_openclaw_release.py --latest --format json --output ./reports/openclaw-latest.json
```

### 示例 8：清理缓存

```bash
python analyze_openclaw_release.py --clean-cache
```

---

## 分析模式详解

### 模式 A：单版本分析（`--latest` 或 `--target`）

分析单个 release 的全部变更内容。适用于：

- 了解某个特定版本的更新内容
- 评估是否值得升级到最新版

### 模式 B：版本对比（`--target` + `--compare`）

对比两个版本之间的差异，通过 GitHub Compare API 获取 commits 和 diff 统计，结合 LLM 进行语义关联分析。适用于：

- 计划从旧版本升级到新版本
- 评估升级的具体影响范围

### 模式 C：版本范围（`--from` + `--to`）

分析从起始版本到终止版本之间所有 release 的累积变化。适用于：

- 跨越多个版本的一次性升级
- 需要了解一段时间内的完整变更历史

**特殊能力**：

- **渐进式修复检测**：识别同一 issue 在多个版本中逐步修复的完整链条
- **累积 Breaking Change 分析**：评估单个版本低风险但累积高风险的场景

### 模式 D：LLM 增强分析流程（`--prepare-analysis-data`）

当分析数据量较大时，脚本会自动或手动进入分块模式：

1. **准备分析数据**：脚本获取 release notes、commits、diff 统计，生成 `analysis-data.json`
2. **执行 LLM 分析**：AI Agent 读取数据，执行主题聚类、逐条增强、shadow change 检测
3. **应用结果**：将 LLM 结果合并到报告中

**单 chunk（小型/中型 release）**：

```
ANALYSIS_DATA_READY: 1
DATA: <snapshot-dir>/openclaw-openclaw-v1.3.0-analysis-data.json
BASE_ANALYSIS: <path>
CHUNKING_REQUIRED: 0
ESTIMATED_TOKENS: 45000
```

**多 chunks（大型 release）**：

```
ANALYSIS_DATA_READY: 1
DATA: <snapshot-dir>/openclaw-openclaw-v1.3.0-analysis-data.json
BASE_ANALYSIS: <path>
CHUNKING_REQUIRED: 1
ESTIMATED_TOKENS: 145000
CHUNK_COUNT: 3
CHUNK_0: <snapshot-dir>/openclaw-openclaw-v1.3.0-analysis-chunk-000.json
CHUNK_1: <snapshot-dir>/openclaw-openclaw-v1.3.0-analysis-chunk-001.json
CHUNK_2: <snapshot-dir>/openclaw-openclaw-v1.3.0-analysis-chunk-002.json
MERGE_COMMAND: --merge-chunk-results
```

---

## 报告结构

生成的 Markdown 报告包含以下章节：

### 报告头

- 标题、仓库、目标版本、对比版本、生成时间戳

### 版本信息

- 表格：目标版本、发布日期、状态、对比版本、分析的 release 数量、数据来源、文件路径

### Executive Summary（总体结论）

- **升级建议标签**：建议升级 / 谨慎升级 / 暂缓升级 / 仅特定场景建议升级 / 信息不足
- **主导主题**：本次变更的核心主题
- **变更规模**：总 item 数及风险分解（high/medium/low）
- **前 5 个最关键变更**：含风险图标和附录链接
- **一句话判断**：针对 release 特征的定制 verdict

### Developer Conclusion（开发者结论）

- 面向 Plugin / Channel 开发者的一句话 verdict，基于 breaking changes、安全密度、plugin/API 数量或 config 变更

### Thematic Overview（变更主题概览）

- 将所有变更聚类为 8-15 个语义主题
- 每个主题显示：item 数量、风险等级、相关 commits、摘要

### Progressive Fix Detection（渐进式修复检测）

- 展示同一 issue 在多个版本中逐步修复的链条
- 每个链条显示：各阶段版本、修复描述、完整度、最终状态

### Cumulative Breaking Change Analysis（累积 Breaking Change 分析）

- 评估跨越多个版本升级的累积风险
- 展示逐版本风险 vs 累积风险对比

### High-Risk Theme Details（高风险主题详解）

- 高风险和中风险主题的深度分析
- 包含影响描述、受影响文件、相关 commits

### Code Change Evidence（代码变更证据链）

- Note-to-commit 关联表
- 展示哪些 commits 对应哪些 release notes

### Shadow Changes（未记录变更提示）

- 修改了公开 surface 但没有对应 release note 的 commits

### Compatibility Risks（兼容性与风险点）

- 与 plugin/channel 开发者相关的高风险和中风险 item

### Suggested Test Points（建议验证的测试点）

- 从检测到的信号推导的可操作回归测试建议

### Ignorable Changes（可暂时忽略的变更）

- 低风险、低相关性的 item

### Facts, Inferences, and Uncertainties

- **Facts**：snapshot 来源、版本状态等可验证事实
- **Inferences**：分类方法、建议推导等基于规则的推断
- **Uncertainties**：低置信度 item、缺失的迁移指导等不确定性

### References

- 所有分析的 release 页面链接

### Original Release Notes (Enhanced Index)

- 原始 release note item 按原始顺序排列
- 每条标注附录 ID、类别和风险等级

### Appendix: Complete Per-Release-Note Details

- 每条可分析 item 的完整解读表
- 字段：component、release tag、风险等级、置信度、类别、受众、原始文本、解读、建议操作、交叉引用

---

## 文件位置

### 最终报告

- **用户指定路径**：通过 `--output <path>` 传入
- **用户未指定**：写入**当前工作目录**，文件名 `{repo}-{target}-analysis.md`

### 中间缓存（Snapshots）

所有中间文件存储在**平台缓存目录**，**绝不写入 skill 安装目录**：

| 平台 | 路径 |
|------|------|
| Windows | `%LOCALAPPDATA%\openclaw-release-notes-analyzer\snapshots` |
| Linux | `~/.cache/openclaw-release-notes-analyzer/snapshots` 或 `$XDG_CACHE_HOME/openclaw-release-notes-analyzer/snapshots` |
| macOS | `~/.cache/openclaw-release-notes-analyzer/snapshots` |

**中间文件类型**：

| 文件类型 | 文件名模式 | 保留策略 |
|----------|-----------|----------|
| Release notes snapshot | `*-release-notes.md` | 保留最近 20 个版本 |
| LLM 分析结果 | `*-llm-results.json` | 保留 7 天 |
| 分析数据（临时）| `*-analysis-data.json` | 报告生成后自动删除 |
| 规则分析结果（临时）| `*-base-analysis.json` | 报告生成后自动删除 |
| Chunk 数据（临时）| `*-analysis-chunk-*.json` | 报告生成后自动删除 |
| Chunk 结果（临时）| `*-analysis-result-chunk-*.json` | 报告生成后自动删除 |

---

## GitHub Token

### 为什么需要 Token？

GitHub Token 用于：

1. **认证 API 请求**：GitHub API 有严格的速率限制（未认证 60 req/h，认证后 5,000 req/h）
2. **LLM 增强分析**：获取 commits、diff 统计需要额外的 API 调用
3. **验证权限**：脚本在**任何 API 调用之前**先通过 `/rate_limit` 验证 token 有效性

### 如何获取 Token

1. 访问 [GitHub Settings -> Developer settings -> Personal access tokens -> Tokens (classic)](https://github.com/settings/tokens)
2. 点击 **Generate new token (classic)**
3. 选择权限（最小权限）：
   - `public_repo`：读取公开仓库内容
   - 或者不需要任何特殊 scope（仅读取公开 release 信息）
4. 生成后复制 token（以 `ghp_` 开头）

### Token 传递方式

**优先级**：`--github-token` CLI 参数 > `GITHUB_TOKEN` 环境变量 > 无

```bash
# 方式 1：环境变量（推荐）
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python analyze_openclaw_release.py --latest

# 方式 2：命令行参数
python analyze_openclaw_release.py --latest --github-token ghp_xxxxxxxxxxxx
```

### Token 验证失败

如果 token 无效或缺失，脚本会：

1. 向 stderr 输出 `TOKEN_STATUS: invalid`
2. 打印错误信息
3. **立即报错退出，不生成任何报告**

> **注意**：LLM 增强分析是强制要求，不允许在无 token 时回退到仅规则分析。

---

## 缓存管理

### 自动缓存策略

- **Release notes snapshot**：保留最近 20 个版本，避免重复 API 获取
- **LLM 结果**：保留 7 天，支持重新生成报告
- **临时文件**：报告生成后自动清理

### 缓存一致性验证

每次加载缓存时自动执行多层检查：

1. **结构完整性**：验证 frontmatter 包含所有必需字段
2. **Payload 一致性**：验证 base64 payload 正确解码、包含所有版本
3. **时效性检查**：检测是否有更新的稳定版本、目标版本是否已不存在
4. **LLM 结果一致性**：验证 JSON 有效性、版本对齐

如果任何 **error 级别**检查失败，自动丢弃缓存并重新获取。

### 手动清理

```bash
python analyze_openclaw_release.py --clean-cache
```

此命令会删除所有缓存 snapshot 和中间文件。

---

## 常见问题

### Q: 没有 GitHub Token 可以运行吗？

**不可以**。GitHub Token 是必需的。脚本会在启动时验证 token，无效或缺失时会报错退出。你需要获取一个 GitHub Personal Access Token 后重新运行。

### Q: 分析需要多长时间？

| 场景 | 大致时间 |
|------|---------|
| 单版本、小型 release | 10-30 秒 |
| 单版本、中型 release | 30-60 秒 |
| 版本对比 + LLM 增强 | 1-3 分钟（取决于 LLM 分析速度）|
| 版本范围、多版本 | 2-5 分钟 |
| 大型 release + 分块分析 | 5-15 分钟 |

### Q: 报告可以重复生成吗？

可以。只要 snapshot 和 `llm-results.json` 缓存存在，重新运行相同命令会直接使用缓存，无需再次调用 LLM。

### Q: 可以分析其他仓库吗？

可以，通过 `--repo` 参数指定。但工具的分类关键词和风险评估规则是针对 OpenClaw 项目优化的，分析其他仓库时准确度可能下降。

```bash
python analyze_openclaw_release.py --repo owner/other-repo --latest
```

### Q: 输出可以改为英文吗？

目前固定输出中文。`--lang` 参数已废弃，保留仅用于向后兼容。

### Q: Snapshot 文件可以手动删除吗？

可以。Snapshot 是中间缓存，随时可以安全删除。最终报告是唯一需要保留的交付物。

### Q: 如何处理 API 速率限制？

如果遇到 `HTTP 403 rate limit exceeded`：

1. 确保使用了有效的 GitHub Token（认证后限制为 5,000 req/h）
2. 等待速率限制重置（通常 1 小时）
3. 检查是否在短时间内多次运行分析

### Q: 分析结果中的风险等级是如何确定的？

| 风险等级 | 触发条件 |
|---------|---------|
| **high** | breaking change、security（CVE/credential）、migration、dependency runtime-removal |
| **medium** | plugin/API/cli/config 含 breaking/signature/removal/deprecated 信号；performance 含 crash/deadlock |
| **low** | 纯 feature 或 fix，无公开 surface 变更信号 |

### Q: 什么是 "Shadow Change"？

指代码中修改了公开 API surface（公共方法、CLI flag、配置 schema 等）但没有在 release notes 中提及的变更。这类变更可能在升级时造成意外影响。

---

## 项目结构

```
openclaw-release-analyzer/
├── openclaw-release-notes-analyzer/
│   ├── scripts/
│   │   ├── analyze_openclaw_release.py   # 主分析脚本（入口）
│   │   ├── config.py                     # 配置常量、关键词、分块参数
│   │   ├── models.py                     # 数据模型（Release、Theme、LLMFullReport 等）
│   │   ├── prompts.py                    # LLM prompt 构建、chunk 管理、结果合并
│   │   ├── renderer.py                   # Markdown 报告渲染
│   │   └── i18n.py                       # 国际化字符串
│   ├── references/
│   │   └── analysis-rules.md             # 详细分类规则和决策参考
│   └── SKILL.md                          # Claude Code Skill 规范文档
└── README.md                             # 本文件
```

---

## 升级建议标签说明

| 标签 | 使用场景 |
|------|---------|
| **建议升级** | 安全修复、严重 bug 修复、crash/deadlock/memory-leak 修复，或低风险的重要 feature |
| **谨慎升级** | Breaking changes、依赖/运行时要求变更、公共 API 变更、CLI 变更、配置行为变更 |
| **暂缓升级** | 无实质收益、release 数据不清晰、高风险但不符合用户需求、生产环境不稳定的 prerelease |
| **仅特定场景建议升级** | 变更主要惠及 plugin 开发者、SDK 使用者、安全敏感用户等特定群体 |
| **信息不足** | Release notes 缺失、模糊或不足以得出可靠结论 |

---

## License

[根据项目实际 License 填写]
