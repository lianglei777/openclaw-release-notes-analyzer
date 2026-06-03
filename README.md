# OpenClaw Release Notes Analyzer

用于分析 [OpenClaw](https://github.com/openclaw/openclaw) GitHub Release Notes 的智能工具。自动获取 release metadata，结合规则基线与 LLM 增强分析，生成中文升级影响报告。

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **Release 自动获取** | 从 GitHub Releases API 拉取 release metadata 和 release notes |
| **规则基线分析** | 基于关键词加权 + 显式信号验证 + 章节上下文的两级过滤架构 |
| **LLM 增强分析** | Commit-message bridge 方法，将 release notes 与 commits 语义关联 |
| **主题聚类** | 将变更聚类为 8-15 个功能主题，按风险排序 |
| **渐进式修复检测** | 识别跨版本的 bug 修复链（缓解 → 部分修复 → 完整修复）|
| **累积 Breaking Change** | 评估版本范围升级的累积风险 |
| **Shadow Change 检测** | 发现修改了公开 surface 但无对应 release note 的 commits |
| **场景化升级建议** | 针对 Plugin 开发者、API/SDK 使用者、安全/稳定性敏感用户分别建议 |
| **中英文支持** | 自动检测中英文关键词进行分类 |
| **Conventional Commit** | 识别 `feat:`、`fix:`、`perf:`、`BREAKING CHANGE:` 等前缀 |
| **自动分块处理** | 大型 release 自动拆分为多个 chunk 分析 |
| **缓存一致性验证** | 加载缓存时自动验证结构完整性、payload 一致性、时效性 |

---

## 环境要求

- Python 3.9+
- 网络可访问 GitHub API
- GitHub Personal Access Token（[如何获取](#github-token)）

> 本项目**无任何第三方 Python 依赖**，仅使用标准库。

---

## 快速开始

```bash
# 设置 GitHub Token
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# 分析最新稳定版
cd openclaw-release-notes-analyzer/scripts
python analyze_openclaw_release.py --latest
```

分析完成后，报告自动写入当前工作目录，文件名格式为 `{repo}-{version}-analysis.md`。

---

## 命令行参数

### 核心参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--latest` | 分析最新稳定 release | `--latest` |
| `--target <版本>` | 指定目标 release 版本 | `--target v1.3.0` |
| `--compare <版本>` | 指定对比的基准版本 | `--compare v1.2.3` |
| `--from <版本>` | 版本范围分析起始版本 | `--from v1.1.0` |
| `--to <版本>` | 版本范围分析终止版本 | `--to v1.3.0` |
| `--include-beta` | 报告中包含 prerelease 预览 | `--include-beta` |

### 认证与输出

| 参数 | 说明 | 示例 |
|------|------|------|
| `--github-token <token>` | GitHub Personal Access Token | `--github-token ghp_xxx` |
| `--repo <owner/name>` | 分析仓库（默认 `openclaw/openclaw`）| `--repo owner/repo` |
| `--output <路径>` | 指定报告输出路径 | `--output ./report.md` |
| `--format <格式>` | 输出格式：`markdown` 或 `json` | `--format json` |
| `--snapshot-dir <目录>` | 自定义缓存目录 | `--snapshot-dir ./cache` |
| `--clean-cache` | 清理所有缓存 | `--clean-cache` |

### LLM 分析控制（高级）

| 参数 | 说明 |
|------|------|
| `--prepare-analysis-data` | 生成分析数据后退出，由外部 AI Agent 执行 LLM 分析 |
| `--apply-llm-results <路径>` | 应用 LLM 分析结果 JSON 并生成最终报告 |
| `--prepare-chunks` | 自动将分析数据拆分为多个 chunks |
| `--merge-chunk-results` | 合并所有 chunk 结果文件 |
| `--recursive-analysis` | 多版本分析使用递归合并聚合策略 |

---

## 使用示例

### 分析最新稳定版

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python analyze_openclaw_release.py --latest
```

### 分析指定版本

```bash
python analyze_openclaw_release.py --target v2026.5.18
```

### 版本对比分析

```bash
# 步骤 1：准备分析数据
python analyze_openclaw_release.py --target v1.3.0 --compare v1.2.3 --prepare-analysis-data

# 步骤 2：将 analysis-data.json 交给 AI Agent 执行 LLM 分析
# AI Agent 分析完成后生成 llm-results.json

# 步骤 3：应用 LLM 结果生成最终报告
python analyze_openclaw_release.py --target v1.3.0 --compare v1.2.3 \
  --apply-llm-results "<snapshot-dir>/openclaw-openclaw-v1.3.0-llm-results.json"
```

> 快捷方式：snapshot 目录中若已存在 `llm-results.json`，直接运行 `--target --compare` 即可自动检测并应用。

### 版本范围分析

```bash
python analyze_openclaw_release.py --from v1.1.0 --to v1.3.0
```

适用于跨越多个版本一次性升级的场景。

### 包含 Prerelease 预览

```bash
python analyze_openclaw_release.py --latest --include-beta
```

---

## 分析模式

| 模式 | 参数 | 适用场景 |
|------|------|---------|
| **单版本分析** | `--latest` 或 `--target` | 了解某个特定版本的更新内容 |
| **版本对比** | `--target` + `--compare` | 计划从旧版升级，评估具体影响范围 |
| **版本范围** | `--from` + `--to` | 跨越多个版本一次性升级，检测渐进式修复链和累积 breaking changes |
| **LLM 增强** | `--prepare-analysis-data` | 数据量较大时，分块由外部 AI Agent 分析 |

---

## 报告结构

生成的 Markdown 报告包含以下章节：

1. **版本信息** — 目标版本、发布日期、状态、分析的 release 数量
2. **Executive Summary（总体结论）** — 升级建议标签、主导主题、变更规模、前 5 个最关键变更、一句话判断
3. **Developer Conclusion（开发者结论）** — 面向 Plugin / Channel 开发者的一句话 verdict
4. **Thematic Overview（变更主题概览）** — 8-15 个语义主题，含 item 数量、风险等级、摘要
5. **Progressive Fix Detection（渐进式修复检测）** — 跨版本逐步修复的完整链条
6. **Cumulative Breaking Change Analysis（累积 Breaking Change 分析）** — 逐版本风险 vs 累积风险对比
7. **High-Risk Theme Details（高风险主题详解）** — 高风险和中风险主题的深度分析
8. **Code Change Evidence（代码变更证据链）** — Note-to-commit 关联表
9. **Shadow Changes（未记录变更提示）** — 修改了公开 surface 但无 release note 的 commits
10. **Compatibility Risks（兼容性与风险点）** — 与 plugin/channel 开发者相关的高/中风险 item
11. **Suggested Test Points（建议验证的测试点）** — 可操作的回归测试建议
12. **Ignorable Changes（可暂时忽略的变更）** — 低风险、低相关性 item
13. **Facts, Inferences, and Uncertainties** — 事实、推断与不确定项
14. **References** — 所有分析的 release 页面链接
15. **Original Release Notes (Enhanced Index)** — 原始 release note 按原始顺序排列，标注附录 ID、类别和风险等级
16. **Appendix: Complete Per-Release-Note Details** — 每条 item 的完整解读表

---

## 项目结构

```
openclaw-release-notes-analyzer/
├── openclaw-release-notes-analyzer/
│   ├── scripts/
│   │   ├── analyze_openclaw_release.py   # 主分析脚本（入口）
│   │   ├── main.py                       # CLI 兼容入口
│   │   ├── config.py                     # 配置常量、关键词、分块参数
│   │   ├── models.py                     # 数据模型（Release、Theme、LLMFullReport 等）
│   │   ├── prompts.py                    # LLM prompt 构建、chunk 管理、结果合并
│   │   ├── renderer.py                   # Markdown 报告渲染
│   │   └── i18n.py                       # 中文国际化字符串
│   ├── references/
│   │   ├── analysis-rules.md             # 分类规则和决策参考
│   │   ├── llm-workflow.md               # LLM schema、chunking、merge 协议
│   │   └── execution-guide.md            # 命令矩阵、路径细节、故障排除
│   └── SKILL.md                          # Claude Code Skill 规范
└── README.md                             # 本文件
```

---

## GitHub Token

### 为什么需要 Token？

GitHub Token 用于认证 API 请求。未认证限制 60 req/h，认证后 5,000 req/h。LLM 增强分析需要额外的 API 调用获取 commits 和 diff 统计。

### 获取 Token

1. 访问 [GitHub Settings -> Developer settings -> Personal access tokens -> Tokens (classic)](https://github.com/settings/tokens)
2. 点击 **Generate new token (classic)**
3. 选择最小权限 `public_repo`（读取公开仓库）
4. 生成后复制 token（以 `ghp_` 开头）

### 传递方式

优先级：`--github-token` CLI 参数 > `GITHUB_TOKEN` 环境变量

```bash
# 方式 1：环境变量（推荐）
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python analyze_openclaw_release.py --latest

# 方式 2：命令行参数
python analyze_openclaw_release.py --latest --github-token ghp_xxxxxxxxxxxx
```

> Token 无效或缺失时，脚本会立即报错退出，不生成报告。

---

## 文件位置

### 最终报告

- 用户指定 `--output <path>` 时：写入指定路径
- 用户未指定时：写入**当前工作目录**，文件名 `{repo}-{target}-analysis.md`

### 中间缓存（Snapshots）

| 平台 | 路径 |
|------|------|
| Windows | `%LOCALAPPDATA%\openclaw-release-notes-analyzer\snapshots` |
| Linux | `~/.cache/openclaw-release-notes-analyzer/snapshots` |
| macOS | `~/.cache/openclaw-release-notes-analyzer/snapshots` |

| 文件类型 | 保留策略 |
|---------|---------|
| Release notes snapshot | 最近 20 个版本 |
| LLM 分析结果 | 7 天 |
| 分析数据、规则分析结果、chunk 文件 | 报告生成后自动删除 |

---

## 升级建议标签

| 标签 | 使用场景 |
|------|---------|
| **建议升级** | 安全修复、严重 bug 修复、crash/deadlock/memory-leak 修复 |
| **谨慎升级** | Breaking changes、API/CLI/配置行为变更 |
| **暂缓升级** | 无实质收益、数据不清晰、不稳定的 prerelease |
| **仅特定场景建议升级** | 变更主要惠及特定群体（plugin 开发者、SDK 使用者等）|
| **信息不足** | Release notes 缺失或模糊 |

---

## 风险等级判定

| 等级 | 触发条件 |
|------|---------|
| **high** | breaking change、security（CVE/credential）、migration、dependency runtime-removal |
| **medium** | plugin/API/cli/config 含 breaking/signature/removal/deprecated 信号；performance 含 crash/deadlock |
| **low** | 纯 feature 或 fix，无公开 surface 变更信号 |

---

## 常见问题

**Q: 没有 GitHub Token 可以运行吗？**

不可以。Token 是必需的，无效或缺失时脚本会立即报错退出。

**Q: 可以分析其他仓库吗？**

可以，通过 `--repo` 参数指定。但分类关键词和风险评估规则针对 OpenClaw 优化，分析其他仓库时准确度可能下降。

**Q: 输出可以改为英文吗？**

目前固定输出中文。`--lang` 参数保留仅用于向后兼容。

**Q: 如何处理 API 速率限制？**

1. 确保使用了有效的 GitHub Token（认证后 5,000 req/h）
2. 等待速率限制重置（通常 1 小时）

**Q: 什么是 Shadow Change？**

指代码中修改了公开 API surface（公共方法、CLI flag、配置 schema 等）但没有在 release notes 中提及的变更。这类变更可能在升级时造成意外影响。

---

## License

MIT
