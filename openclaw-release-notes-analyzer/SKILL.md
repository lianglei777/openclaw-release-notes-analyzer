---
name: openclaw-release-notes-analyzer
description: 本 Skill 用于分析 OpenClaw GitHub release、release notes、版本对比、升级影响、bug fix、新增 feature、插件系统变化、API/SDK 变化、安全修复、性能/稳定性变化、beta/prerelease 预览，以及 OpenClaw 升级建议。
---

# OpenClaw Release Notes Analyzer

分析 `openclaw/openclaw` GitHub releases 和 release notes，生成中文升级影响报告。技术专有名词（OpenClaw, API, SDK, CLI, hook, manifest, plugin 等）保持英文。

## 核心约束

- 默认仓库：`openclaw/openclaw`。
- 输出固定为中文报告；`--lang` 仅保留向后兼容，实际输出始终为中文。
- 在任何 GitHub API 请求之前，必须验证 GitHub token。token 来源顺序：`--github-token` 参数 -> `GITHUB_TOKEN` 环境变量 -> 无。
- token 有效时，使用 LLM 增强 diff 分析；token 缺失或无效时立即停止，不生成报告，不提供纯规则分析选项。
- 每次分析都先从 GitHub Releases API 获取最新 metadata 和 release notes，写入新的本地 snapshot，再基于该 snapshot 分析。
- 不使用离线文件输入、缓存复用、`--use-cache` 或手动 `--refresh` 模式。
- 稳定版定义为 GitHub `draft == false` 且 `prerelease == false`。
- 默认目标是最新稳定版，默认对比基线是上一个稳定版。
- 仅将比最新稳定版更新的 beta/prerelease 作为前瞻预览，不作为默认升级目标。
- 除非用户明确要求并授权，否则不要扫描用户本地项目。
- 区分事实、推断和不确定性；没有公开 surface 证据时，不要断言内部重构会影响开发者。

## 数据和输出位置

中间产物写入平台缓存目录：

- Windows: `%LOCALAPPDATA%\openclaw-release-notes-analyzer\snapshots`
- Linux/macOS: `~/.cache/openclaw-release-notes-analyzer/snapshots`

中间产物包括 release snapshot、analysis data、base analysis、LLM results 和 chunk files。它们不是最终交付物，可清理；不要写入 skill 安装目录。若 `--snapshot-dir` 指向 skill 目录内部，脚本会回退到平台缓存目录。

最终报告规则：

- 用户指定输出路径时，传入 `--output <path>`。
- 用户未指定输出路径时，不传 `--output`；脚本默认写入当前工作目录，文件名为 `{snapshot_stem}-analysis.md`。
- 运行脚本前先 `cd` 到用户当前工作区根目录，确保默认报告输出到工作区。
- 完成后回复用户时，必须同时给出最终报告绝对路径和 snapshot 缓存目录：

```markdown
| 类型 | 路径 |
|------|------|
| 最终报告 | <absolute-path-to-report> |
| 中间缓存 | <platform-cache-dir> |
```

## 判断分析范围

按用户请求选择范围：

- 未提供版本号：分析最新稳定版。
- 提及一个版本：分析该目标版本。
- 提及两个版本：执行版本对比，例如 `v1.2.3` 到 `v1.3.0`。
- 提供起止版本或范围表达式：分析版本范围。
- 明确询问 beta、alpha、rc、prerelease 或 preview：做 prerelease 预览。
- 明确要求项目级兼容分析：获得授权后检查本地项目相关文件。

## 标准执行流程

使用 `scripts/analyze_openclaw_release.py`。所有命令先切到用户工作区根目录：

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" <args>
```

常用启动命令（token 有效时会进入准备分析数据模式）：

```bash
# 最新稳定版
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh --github-token <token>

# 指定目标版本
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v2026.5.28 --lang zh --github-token <token>

# 版本范围
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --from v2026.5.01 --to v2026.5.28 --lang zh --github-token <token>
```

脚本会验证 token、刷新 snapshot、准备 LLM 分析数据，并根据输出信号进入后续步骤。

## LLM 增强分析

LLM 分析是必需步骤。脚本负责获取 release notes、commits 和目录级 diff 统计；AI agent 负责读取脚本生成的 chunk/data 文件，生成结构化 LLM JSON，再让脚本应用结果并渲染报告。

常见三步：

1. 准备分析数据：
   ```bash
   cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v2026.5.28 --prepare-analysis-data --github-token <token>
   ```
   脚本在写入完成后会输出 `DATA_VERIFIED: 1`。如果未看到此信号，说明文件可能未正确落盘，应停止后续步骤并排查。
2. 读取脚本输出的 `CHUNK_0` 或 chunk 文件，按 LLM 输出格式生成 JSON，并写入脚本输出的 `LLM_RESULTS_TARGET`。
   如果主路径写入失败（例如 Windows 深层路径不可靠），使用 `FALLBACK_LLM_RESULTS_TARGET`（系统临时目录）作为备用位置。
   不要将 LLM 结果写入 `user-workspace-root`，避免污染用户项目目录。
   写入后建议验证文件真实存在且非空，再继续下一步。
3. 生成报告：
   ```bash
   cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v2026.5.28 --apply-llm-results --github-token <token>
   ```

如果输出 `CHUNKING_REQUIRED: 1`，按分块流程处理，不要跳过或手动合并 chunks。完整 LLM JSON schema、chunking、merge 和大上下文处理协议见 `references/llm-workflow.md`。

## 报告内容要求

报告重点关注：

- plugin system: plugin API, lifecycle hooks, manifest schema, loader, registry, runtime
- API/SDK: public methods, package exports, TypeScript types, deprecations, migration notes
- security: CVE, auth, token, permission, dependency vulnerabilities
- performance/stability: crash, hang, deadlock, race, memory leak, startup speed, latency
- breaking/migration/config/CLI/dependency/docs/known issues

默认报告使用当前 renderer 的 LLM-driven 结构，包括执行摘要、开发者结论、主题概览、渐进式修复检测、累积 breaking change 分析、代码证据链、未记录变更、兼容性风险、测试建议、事实/推断/不确定项、原始 release notes 索引和附录明细。分类规则、公开 surface 判断、升级建议标签和完整报告结构见 `references/analysis-rules.md`。

## 项目扫描规则

除非用户明确要求项目级兼容分析，否则不要检查本地项目文件。获得授权后，仅检查相关文件：

- `package.json` 和 lockfiles
- `openclaw.config.*`
- plugin manifests
- 可能导入 OpenClaw APIs 的源文件

避免 `.env`、凭证、secrets、private keys 和无关文件。

## 按需加载引用

- 需要 LLM schema、chunking、大上下文处理、merge 细节：读取 `references/llm-workflow.md`。
- 需要命令矩阵、Windows 路径细节、文件写入规范、故障排除：读取 `references/execution-guide.md`。
- 需要分类关键词、公开 surface、升级建议、报告结构和决策规则：读取 `references/analysis-rules.md`。
