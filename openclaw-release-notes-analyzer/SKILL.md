---
name: openclaw-release-notes-analyzer
description: 本 Skill 用于分析 OpenClaw GitHub release、release notes、版本对比、升级影响、bug fix、新增 feature、插件系统变化、API/SDK 变化、安全修复、性能/稳定性变化、beta/prerelease 预览，以及 OpenClaw 升级建议。
---

# OpenClaw Release Notes Analyzer

## 概述

分析 OpenClaw release notes 和 GitHub release metadata，帮助开发者了解版本间变化并判断是否升级。重点关注 bug fix、新增 feature、插件系统影响、API/SDK 影响、安全修复、性能/稳定性变化、breaking-change 风险，以及场景化升级建议。

**输出语言**：本 Skill 固定输出中文报告。技术专有名词（OpenClaw, API, SDK, CLI, hook, manifest, plugin 等）保持英文以确保语义准确。

## 适用场景

在以下场景中调用本 Skill：

- 分析最新 OpenClaw release
- 对比两个 OpenClaw 版本
- 汇总某个版本范围内的变化
- 检查 OpenClaw 更新是否包含重要 bug fix 或 feature
- 评估升级对插件开发者、API/SDK 使用者、安全敏感用户、稳定性敏感用户或普通用户的影响
- 预览较新的 beta、alpha 或 release-candidate 版本，但不将其作为默认升级目标
- 检查 OpenClaw release notes 中的插件、API、SDK、安全、性能或 breaking-change 信号

## 默认行为

- 默认分析 `openclaw/openclaw`。
- **在任何 API 调用之前，始终验证 GitHub token。** 脚本通过 `/rate_limit` 接口验证 token 有效性；token 可通过 `--github-token` 参数或 `GITHUB_TOKEN` 环境变量提供。
- **Token 有效** → 自动进入 **LLM 增强 diff 分析模式**（相比纯规则分析，准确度显著提升）。
- **Token 无效或缺失** → **报错停止，不生成报告**。本 Skill 要求 LLM 分析作为必需步骤，不允许回退到仅规则分析。
- 每次分析开始时，先从 GitHub Releases API 获取最新的 release metadata 和 release notes。
- 分析前始终将获取的数据写入新的本地 snapshot。
- 始终基于刚写入的本地 snapshot 进行分析，不要直接从重复 API 读取中分析。
- 不提供或使用替代数据源模式，如离线本地文件输入、缓存复用、`--use-cache` 或手动 `--refresh` 切换。
- 将非 draft、非 prerelease 的 release 视为稳定版本。
- 默认比较最新稳定版本与上一个稳定版本。
- 仅将比最新稳定版本更新的 beta/prerelease 版本作为前瞻性预览提及。
- 除非用户明确请求并授权，否则不扫描用户本地项目。
- 区分事实、推断和不确定性。
- 每条 release note 都附带解读：影响受众、风险等级、置信度和建议操作。
- 除非有公开 surface 变更的证据，否则不要断言内部重构会影响开发者。

## 文件位置（Snapshots vs. Reports）

**中间产物（snapshots、LLM prompts、基础分析）：**
- 所有中间文件存储在**平台缓存目录**：
  - **Windows**：`%LOCALAPPDATA%\openclaw-release-notes-analyzer\snapshots`
  - **Linux/macOS**：`~/.cache/openclaw-release-notes-analyzer/snapshots`
- **绝不**写入 skill 安装目录。如果 `--snapshot-dir` 指向 skill 目录内部，脚本自动回退到平台缓存目录。
- 中间产物类型和生命周期：
  - `*-release-notes.md`：原始 GitHub API snapshot。保留最近 20 个版本以避免重复 API 获取。
  - `*-analysis-data.json`：LLM 主分析数据（release notes + commits + diff stats）。步骤内部文件，报告生成后清理。
  - `*-base-analysis.json`：规则分析结果（步骤内部文件，报告生成后清理）。
  - `*-llm-results.json`：LLM 分析结果（保留 7 天以支持重新生成报告）。
- **自动缓存一致性验证**（Optimization #7 — 缓存自动一致性检查）：
  - 每次加载缓存 snapshot 时，脚本在使用数据前运行多层一致性检查。
  - **结构完整性**：验证 frontmatter 包含所有必需字段（`repo`、`target_version`、`fetched_at`、`scoped_releases`、`release_payload_base64` 等），且正文包含每个 scoped release 的章节。
  - **Payload 一致性**：验证 `release_payload_base64` 正确解码、包含所有 scoped releases，且目标版本存在。
  - **时效性检查**：将缓存数据与实时 GitHub API 数据对比——检测是否有更新的稳定版本可用（`--latest` 模式下）、目标版本是否已不存在，或 `published_at` 是否已变更（表明 release 被编辑过）。
  - **LLM 结果一致性**：在应用缓存的 `llm-results.json` 前，验证文件为有效 JSON、不早于其关联 snapshot，且引用的版本存在于 snapshot 中。
  - 如果任何 **error 级别**检查失败，脚本自动丢弃不一致的缓存并从 GitHub 重新获取。**Warning 级别**问题（例如 snapshot 超过 7 天）报告到 stderr 但不阻止缓存使用。
- Snapshots**不是最终交付物**，可随时安全删除。
- 使用 `--clean-cache` 进行手动一次性清理。

**分析报告（最终交付物）：**
- 如果用户指定了输出路径（例如 "输出到 /path/to/report.md"），通过 `--output <path>` 传入。
- **如果用户没有指定输出路径**，报告默认写入**当前工作目录**，文件名为 `{snapshot_stem}-analysis.md`（例如 `openclaw-openclaw-v1.3.0-release-notes-analysis.md`）。
- 运行脚本前，`cd` 到用户当前工作区目录，使报告默认落在那里。
- **分析完成后，你必须清楚告知用户两件事：(1) 生成报告的绝对文件路径，以及 (2) 中间数据写入的 snapshot 缓存目录。** 使用表格格式以清晰展示：

```
| 类型 | 路径 |
|------|------|
| 最终报告 | <absolute-path-to-report> |
| 中间缓存 | <platform-cache-dir> |
```

## 工作流程

### 1. 输出语言

本 Skill 固定生成中文报告，技术专有名词保持英文。

`--lang` 参数已废弃，保留仅用于向后兼容，实际输出始终为中文。

### 2. 确定分析范围

根据用户请求确定分析范围：

- 最新稳定版分析：未提供版本号。
- 单目标版本：用户提及一个版本。
- 版本对比：用户提及两个版本，例如 `v1.2.3` 到 `v1.3.0`。
- 版本范围：起始/终止版本或范围表达式。
- Beta 预览：用户明确询问 beta、alpha、rc、prerelease 或 preview 版本。
- 项目级兼容分析：仅当用户明确要求检查本地项目时。

### 3. GitHub Token 验证（任何 API 调用之前）

脚本在每次运行时自动验证 GitHub token，**在任何 API 请求之前**：

1. **Token 解析顺序**：`--github-token` CLI 参数 → `GITHUB_TOKEN` 环境变量 → 无。
2. **Token 验证**：调用 `GET /rate_limit` 验证 token 是否有效且未过期。
3. **Token 有效**（stderr 输出 `TOKEN_STATUS: valid`）：
   - 脚本以 **完整 LLM 增强 diff 分析** 作为默认模式继续运行。
   - 在默认模式（Mode C）下，脚本自动生成 LLM prompt 并发出就绪信号（`LLM_PROMPTS_READY: N`），然后退出，由调用方 AI agent 执行 LLM 分析步骤。
4. **Token 无效或缺失**（stderr 输出 `TOKEN_STATUS: invalid`）：
   - 向 stderr 打印错误信息。
   - **立即报错退出，不生成任何报告**。LLM 增强分析是强制要求，不允许无 token 运行。

如果用户提供的 token 验证失败，告知用户 token 无效，并要求提供有效的 GitHub token 后再重新执行分析。不提供"继续仅规则分析"的选项。

### 4. 分析前刷新 Snapshot

每次运行使用固定的数据流：

1. 从 GitHub Releases API 获取最新匹配的 release metadata 和 release notes。
2. 将获取的数据写入本地 snapshot，存储在**平台缓存目录**：
   - **Windows**：`%LOCALAPPDATA%\openclaw-release-notes-analyzer\snapshots`
   - **Linux/macOS**：`~/.cache/openclaw-release-notes-analyzer/snapshots`
   - 仅在明确需要时通过 `--snapshot-dir` 覆盖。
3. 从磁盘重新加载 snapshot。
4. **验证缓存一致性**（自动执行，无需用户操作）。在使用任何缓存 snapshot 或 LLM 结果之前，脚本会执行结构完整性、payload 一致性、时效性和 LLM 结果对齐检查。如果任何检查以 error 级别失败，缓存文件将被丢弃并自动重新获取数据。
5. 仅基于验证通过的 snapshot 内容生成分析报告。

Snapshots 是中间缓存数据——它们存放在系统缓存目录中，可随时安全删除。**Snapshots 不是最终交付物。** 分析报告是用户唯一关心的文件。

**报告输出位置规则：**
- 如果用户指定了输出路径 → 通过 `--output <path>` 传入。
- 如果用户**没有**指定输出路径 → **不要传入 `--output`**；脚本自动将报告写入当前工作目录（`Path.cwd()` / `{snapshot_stem}-analysis.md`）。
- **始终先 `cd` 到用户当前工作区根目录再运行脚本**，使默认输出落在工作区目录，而非 skill 目录或 `snapshots/` 子目录。

除非用户明确要求项目级兼容检查，否则保持分析范围以 release note 为主。不要引入离线文件、缓存复用或多数据源选择模式。

### 5. LLM Commit-Message Bridge 分析（Token 依赖的默认模式）

当有效的 GitHub token 可用且存在 compare baseline（例如 `--compare v1.2.3 --target v1.3.0`）时，脚本**自动**使用 **commit-message-bridge** 方法增强分析。该方法修复了旧的按组件路径匹配策略的根本缺陷（该策略为每个组都生成了无关的 `.gitignore`/`.npmrc` diff），通过向 LLM 提供：

- **所有 release notes**（含规则预分类）
- **版本间的所有 commits**（含提交消息和变更文件路径）
- **目录级代码变更统计**（非原始 patch 转储）

然后 LLM 使用 commit message 作为自然桥梁，在 release notes 和 commits 之间执行**语义关联**——这是只有 LLM 才能准确完成的任务。

**LLM 分析是强制步骤，不可跳过**。即使 trivial release 也必须经过 LLM 分析，以确保分析质量的一致性。

**为什么选择 commit-message bridge 而非路径匹配 diff？**

| 旧方法 | Commit-message bridge |
|--------|----------------------|
| 脚本决定 "Plugin 组 → plugins/ 目录文件" | LLM 读取 commit message 并自行决定关联 |
| 27 个独立 prompt，每个带 2-5 个文件 | 单个综合 prompt，包含所有 commits + notes |
| 所有组都收到 `.gitignore`、`.npmrc`（无关） | Commits 按相关性评分；noise 文件被降级 |
| LLM 被迫将 `.gitignore` 变更解释为 plugin API 证据 | LLM 可以诚实地说 "此 note 没有匹配的 commit" |
| 无跨 note 交叉验证 | LLM 看到所有 notes + 所有 commits，可检测 shadow changes |

**Token 控制策略：**
- Commits 通过消息关键词模式（plugin、API、security、breaking 等）和文件路径信号**按相关性评分**
- 仅触及 noise 文件（`.gitignore`、docs、CI configs）的 commits **被降级和去优先**
- 包含评分最高的 commits（最多 80 个）；总分析数据上限约 120K 字符
- 默认不需要外部 LLM SDK——LLM 分析由调用方 AI agent（如 Claude Code）使用生成的分析数据执行。或者，脚本可以扩展内置 LLM API 客户端以支持独立运行。

**LLM 分析执行策略：**

- **单次综合分析（默认）。** 读取 `analysis-data.json` 文件一次，在单个 prompt 中喂给 LLM，收集结构化 JSON 输出。这让 LLM 获得全局上下文以进行跨 note 验证和 shadow-change 检测。
- **自动分块分析（大型 release）。** 当分析数据超过 token 阈值（约 80K tokens）时，脚本**自动拆分**为 chunks。分析处理器（AI agent 或内置客户端）逐块处理，然后脚本**自动合并**结果。处理器**不决定**拆分策略——脚本决定。
- **禁止：** 引入外部 LLM SDK、产生生命周期超过 skill 调用的未跟踪后台进程、在非指定缓存目录外写入中间文件、要求用户提供 API key、或手动编写 Python 脚本伪造 LLM 结果。

**工作流：**

1. **准备分析数据** — 以数据准备模式运行脚本。它获取 release notes、规则分析结果、commits 和 diff 统计，然后写入一个主数据文件：
   ```bash
   cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --prepare-analysis-data --lang zh
   ```
   脚本输出两种信号模式之一：

   **模式 A — 单 chunk（小型/中型 release）：**
   ```
   ANALYSIS_DATA_READY: 1
   DATA: <snapshot-dir>/<repo>-<target>-analysis-data.json
   BASE_ANALYSIS: <path-to-base-analysis.json>
   CHUNKING_REQUIRED: 0
   ESTIMATED_TOKENS: 45000
   ```

   **模式 B — 多 chunks（大型 release，>80K tokens）：**
   ```
   ANALYSIS_DATA_READY: 1
   DATA: <snapshot-dir>/<repo>-<target>-analysis-data.json
   BASE_ANALYSIS: <path-to-base-analysis.json>
   CHUNKING_REQUIRED: 1
   ESTIMATED_TOKENS: 145000
   CHUNK_COUNT: 3
   CHUNK_0: <snapshot-dir>/<repo>-<target>-analysis-chunk-000.json
   CHUNK_1: <snapshot-dir>/<repo>-<target>-analysis-chunk-001.json
   CHUNK_2: <snapshot-dir>/<repo>-<target>-analysis-chunk-002.json
   MERGE_COMMAND: --merge-chunk-results
   ```

   当看到 **CHUNKING_REQUIRED: 1** 时，跳到步骤 2b（分块分析）。否则跳到步骤 2a（单块分析）。

   `analysis-data.json` 包含三个部分：
   - `release_notes`：所有 notes，含 ID、原始文本和 `source_version`（该 note 来源的 release tag，例如 `v2026.4.12`）。分析版本范围时，`source_version` 让 LLM 能识别每个变更由哪个中间版本引入、检测跨版本的渐进式修复，并推理升级路径依赖。
   - `commits`：评分最高的相关 commits（sha、message、author、changed files、relevance score）
   - `code_changes`：目录级统计 + 变更最多的文件（不含原始 patches）

2a. **执行 LLM 分析（单 chunk）** — 读取 `analysis-data.json` 并在单个 prompt 中喂给 LLM。Prompt 指示 LLM 分四个阶段工作：
   - **Phase 1 — 主题聚类**：按功能意图将 release notes 分组成 8–15 个语义主题。每个主题包含：主题名称、涉及的 note ID、整体风险、摘要、影响、相关 commits、受影响文件和推理依据。
   - **Phase 2 — 跨版本分析**（当 `source_version` 跨越多个 release 时）：
     - **渐进式修复检测（Optimization #3）**：识别跨越多个版本的 bug/issue 修复链——例如 v1 引入临时缓解、v2 提供部分修复、v3 完成修复。输出每条链的阶段（note_id、source_version、fix_description、completeness）和最终状态。
     - **累积 Breaking Change 分析（Optimization #4）**：评估单个版本看似低风险，但整个升级路径的累积影响是否很高。输出 `individual_risk` 与 `cumulative_risk` 对比，并给出具体的 `risk_escalation_reason`，解释为什么一次性跨多个版本升级比逐步升级更危险。
     - **版本范围标注**：识别每个主题由哪个中间版本引入，并在主题推理中标注版本范围依赖。
   - **Phase 3 — 选择性逐条增强**：仅对高风险 note 或有直接 commit 匹配的 note 进行深度逐条分析。
   - **Phase 4 — Shadow Change 检测**：识别修改了公开 surface 但没有对应 release note 的 commits。

   请求结构化输出（JSON 对象，顶层字段如下）：


   ```json
   {
     "themes": [
       {
         "theme_id": "T-01",
         "theme_name": "Gemini ID Normalization Migration",
         "note_ids": ["R-012", "R-013", "R-095"],
         "primary_category": "config",
         "risk_level": "low",
         "summary": "Replace all retired Gemini 3 Pro Preview IDs with 3.1 Pro Preview",
         "impact": "Config auto-migrates; no manual intervention needed",
         "related_commits": ["abc1234"],
         "affected_files": ["src/providers/google/catalog.ts"],
         "confidence": "high",
         "has_hidden_breaking": false,
         "hidden_risks": "",
         "reasoning": "Commit abc1234 message 'normalize retired Gemini 3 Pro Preview ids' directly corresponds; changed file src/providers/google/catalog.ts is the core Gemini provider config"
       }
     ],
     "detailed_notes": [
       {
         "note_id": "R-001",
         "component": "Plugins/doctor",
         "categories": ["breaking", "plugin", "dependency"],
         "risk_level": "high",
         "interpretation": "doctor --fix now drops stale npm records for shadow bundled plugins. If you previously relied on doctor to fix plugin issues, the registry state may change after upgrade — verify plugins still load correctly.",
         "action_items": ["Run openclaw doctor --fix and observe plugin cleanup", "Verify critical plugins load correctly after upgrade"],
         "audience": ["Plugin developers", "Ops engineers"],
         "matched_commits": ["def5678"],
         "affected_files": ["src/plugins/doctor.ts"],
         "has_hidden_breaking": false,
         "reasoning": "Commit def5678 message 'fix(doctor): drop stale npm records' directly matches the note"
       }
     ],
     "shadow_changes": [
       {
         "description": "Commit ghi9012 added an OAuth callback interface not mentioned in release notes",
         "evidence_commits": ["ghi9012"]
       }
     ],
     "progressive_fixes": [
       {
         "fix_id": "PF-01",
         "issue_description": "Feishu auth token refresh failure under specific conditions",
         "stages": [
           {"note_id": "R-015", "source_version": "v2026.4.10", "fix_description": "Added token refresh retry attempts", "completeness": "mitigation"},
           {"note_id": "R-042", "source_version": "v2026.4.11", "fix_description": "Fixed race condition in refresh logic", "completeness": "partial"},
           {"note_id": "R-089", "source_version": "v2026.4.12", "fix_description": "Refactored Feishu auth module to eliminate token refresh issues", "completeness": "complete"}
         ],
         "final_status": "fully_fixed",
         "impact_assessment": "Upgrading from v2026.4.10 to v2026.4.12 fully resolves this issue; intermediate versions may still experience intermittent auth failures",
         "affected_components": ["Feishu", "Auth"]
       }
     ],
     "version_evolution": [
       {
         "evolution_id": "VE-01",
         "description": "Feishu authentication interface underwent three consecutive adjustments",
         "affected_versions": ["v2026.4.10", "v2026.4.11", "v2026.4.12"],
         "individual_risk": "low",
         "cumulative_risk": "high",
         "risk_escalation_reason": "v2026.4.10 deprecated the old QR binding, v2026.4.11 changed the default auth flow, v2026.4.12 fully removed QR support. Individually each is a gradual adjustment, but jumping from v0 to v3 requires handling deprecation notice, behavior change, and API removal all at once, with no intermediate migration buffer",
         "related_themes": ["T-01"],
         "affected_components": ["Feishu", "Auth"],
         "migration_advice": "Recommended stepwise upgrade: first upgrade to v2026.4.11 to complete manual configuration migration, verify it works, then upgrade to v2026.4.12. Do not skip intermediate versions."
       }
     ]
   }
   ```

   Theme 字段：
   - `theme_id`: T-01, T-02, ...
   - `theme_name`: 简洁的功能主题名（15 字以内），避免模糊的如 "Other Changes"
   - `note_ids`: 属于该主题的 Note ID 列表
   - `primary_category`: 主类别（breaking/security/plugin/api_sdk/cli/config/dependency/performance/fix/feature/docs/other）
   - `risk_level`: 整体主题风险（high/medium/low）
   - `summary`: 做了什么（50 字以内）
   - `impact`: 对用户意味着什么（50 字以内）
   - `related_commits`: 直接对应此主题的 Commit SHA（最多 3 个）
   - `affected_files`: 涉及的关键文件路径（最多 5 个）
   - `confidence`: high=直接 commit 证据；medium=间接推断；low=推测
   - `has_hidden_breaking`: 布尔值 — 仅当 commit 证据揭示出 release notes **未披露**的 breaking change 时为 true
   - `hidden_risks`: 字符串 — hidden risks 的具体描述，如无则填 `""`
   - `reasoning`: 判断依据 — 必须引用具体的 commit message 片段和文件路径

   Detailed note 字段（仅针对高风险或有 commit 匹配的 notes）：
   - `note_id`、`component`、`categories`、`risk_level`、`interpretation`、`action_items`、`audience`、`matched_commits`、`affected_files`、`has_hidden_breaking`、`reasoning`
   - `interpretation` 必须回答：WHAT changed, WHAT is the impact, WHAT to do about it。不使用模板。

   Shadow changes 字段：
   - `description`: 发现的无文档记录的变更描述
   - `evidence_commits`: 支持此发现的 Commit SHA 列表

2b. **执行 LLM 分析（分块 — 大型 release）** — 当信号显示 `CHUNKING_REQUIRED: 1` 时，依次处理每个 chunk：

   对每个 chunk 文件（例如 `chunk-000.json`、`chunk-001.json`、...）：
   - 读取 chunk 文件
   - 用同样的四阶段 prompt 喂给 LLM
   - 将 LLM 输出保存到对应的 chunk 结果文件：
     ```
     <snapshot-dir>/<repo>-<target>-llm-results-chunk-000.json
     <snapshot-dir>/<repo>-<target>-llm-results-chunk-001.json
     ...
     ```

   每个 chunk 结果仅包含 `themes` 和 `detailed_notes`（以及该 chunk 中发现的任何 `compatibility_risks`/`test_points`/`shadow_changes`）。脚本的合并步骤合成最终的 `executive_summary` 和 `developer_conclusion`。

   **不要询问用户是否使用分块。** 脚本已经决定了。你的角色是按脚本拆分的方式逐块执行分析。

3a. **写入 LLM 结果（单 chunk）** — 将 LLM 输出保存到：
   ```
   <snapshot-dir>/<repo>-<target>-llm-results.json
   ```

3b. **合并 Chunk 结果（分块）** — 所有 chunks 处理完成后，运行：
   ```bash
   cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --merge-chunk-results --lang zh
   ```
   脚本发现所有 `*-llm-results-chunk-*.json` 文件，通过以下方式合并：
   - 按 `theme_id` 合并 `theme.note_ids`
   - 按 `note_id` 去重 `detailed_notes`
   - 合并 `compatibility_risks`、`test_points`、`shadow_changes`（按 description 去重）
   - 从合并后的 themes 合成 `executive_summary`
   - 将最终结果写入：
     ```
     <snapshot-dir>/<repo>-<target>-llm-results.json
     ```

4. **生成增强报告** — 使用 LLM 结果运行脚本：
   ```bash
   cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --apply-llm-results "<snapshot-dir>/<repo>-<target>-llm-results.json" --lang zh
   ```
   脚本复用步骤 1 的缓存 snapshot 和基础分析 — **无需重复 GitHub API 调用**。

   **缓存清理**在最终报告生成后自动进行：步骤内部文件（`*-analysis-data.json`、`*-base-analysis.json`、`*-analysis-chunk-*.json`）被立即删除。脚本还在每次启动时执行惰性清理：删除超过 7 天的 `*-llm-results.json` 文件，且仅保留最近 20 个 `*-release-notes.md` snapshot。

**强制 LLM 分析**：LLM 分析是本 Skill 的必需步骤，不可跳过、不可回退。如果 LLM 分析失败或 chunk 结果不完整，必须修复问题后重新执行，不允许输出无 LLM 增强的报告。

**默认模式快捷方式**：如果 snapshot 目录中已存在上次运行留下的 `llm-results.json` 文件，默认命令（`--target ... --compare ...`）会自动检测并应用它，无需 `--apply-llm-results`。在应用缓存的 LLM 结果之前，脚本验证其与关联 snapshot 的一致性（有效 JSON、不早于 snapshot）。如果一致性检查失败，缓存结果将被丢弃并准备新的分析数据。

**LLM 驱动的报告架构**：在新架构中，脚本是数据管道，LLM 执行所有语义分析。脚本不会将 LLM 结果与规则模板合并。相反，LLM 输出完整的报告章节（executive summary、themes、detailed notes、compatibility risks、test points、shadow changes），脚本直接渲染它们。这消除了模板偏见并最大化分析深度。

**禁止规则分析回退**：本 Skill 不允许以任何理由回退到无 LLM 增强的规则分析模式。无论 release 大小、token 状态或任何其他条件，LLM 分析都是强制要求。

**版本大小感知**：当 release 规模较小时，脚本仍准备 LLM 分析数据，但不会进入分块模式。小型 release 的 LLM 分析在单个 prompt 中完成，无需分块。

### 5.1 大上下文处理协议

本协议定义分析数据超过 LLM 上下文限制时的标准行为。**脚本做出所有拆分和合并决策；你只需执行。**

**触发条件：**
- 当 `ESTIMATED_TOKENS` 超过 `CHUNKING_THRESHOLD_TOKENS`（80,000）时，脚本自动进入分块模式。
- 脚本输出 `CHUNKING_REQUIRED: 1` 并列出所有 `CHUNK_N` 文件。

**核心原则：主 AI agent 串行分析每个 chunk。**

不要使用子 agent、后台 agent 或任何并行执行机制进行 chunk 分析。主 agent 读取每个 chunk，分析它，将结果写入磁盘，然后继续下一个 chunk。这种方式：
- **通用**：适用于任何支持文件 I/O 的 AI 环境（Claude Code、Cursor、GitHub Copilot Chat 等）。
- **可靠**：不存在 agent 间通信失败导致的数据丢失。
- **上下文安全**：每个 chunk 独立分析；结果持久化到磁盘，不在上下文中累积。

**分析工作流（串行执行）：**

对每个 chunk 文件（`chunk-000.json`、`chunk-001.json`、...）：

1. 使用 `Read` 工具**读取** chunk 文件。
2. 使用标准四阶段 prompt（主题聚类、选择性逐条增强、shadow change 检测）将 chunk 数据**分析**给 LLM。
3. 将完整 JSON 结果**写入**对应的 chunk 结果文件：
   ```
   <snapshot-dir>/<repo>-<target>-llm-results-chunk-000.json
   <snapshot-dir>/<repo>-<target>-llm-results-chunk-001.json
   ...
   ```
4. **验证**文件写入成功（非空、有效 JSON）。
5. **继续**下一个 chunk。不要同时启动多个 chunk。

**结果验证清单：**

写入每个 chunk 结果后：
- 文件必须非空。
- 文件必须包含可被 `json.loads()` 解析的有效 JSON。
- JSON 必须至少包含一个 `themes` 数组（如果该 chunk 没有可主题分组的 notes，可为空）。

**JSON 安全规则（关键）：**

写入 chunk 结果前，确保所有字符串字段——特别是 `interpretation`、`reasoning`、`summary`、`impact` 和 `hidden_risks`——不包含未转义的双引号字符（`"` 或 `"` 或 `"`）。这些字符会破坏 JSON 解析。可以：
- 在字符串字段内引用时使用单引号或角引号（`'...'`、`《...》`），或
- 使用 `json.dumps()`（通过 Python 脚本）保证正确转义。

**缓存清理规则：**

开始 chunk 分析前，检查是否存在之前运行遗留的过期 `*-llm-results-chunk-*.json` 或 `*-llm-results.json` 文件。如果 `analysis-data.json` 已刷新（比较时间戳），**删除旧的 chunk 结果**以防止合并步骤混入新旧数据。脚本的 `--prepare-analysis-data` 步骤不会自动清理旧结果——你需要手动执行或验证时效性。

**Chunk 清单：**

注意预期的 chunk 数量（来自脚本输出的 `CHUNK_COUNT`）与成功保存的 chunk 文件数量。在所有预期的 chunk 结果文件都存在之前，不要调用 `--merge-chunk-results`。

**效率指南：**

为最小化总执行时间：
1. **写入后不要重新读取 chunk 文件** — Edit/Write 工具的成功保证写入已完成。
2. **跨 chunks 复用 theme ID** — 如果一个主题（例如 "Codex app-server"）出现在多个 chunks 中，在所有 chunks 中使用相同的 `theme_id`（例如 "T-07"）。合并步骤按 `theme_id` 合并 `note_ids`，避免重复主题。
3. **对低风险主题省略冗长 reasoning** — 对于 `risk_level: "low"` 的主题，1 句话的 `reasoning` 已足够。
4. **Write 后立即验证 JSON** — 每个 chunk 写入后立即运行 `json.loads()` 检查（耗时 1 秒），而不是在合并时才发现错误（会浪费数分钟的重新分析时间）。
5. **如果合并因 JSON 错误失败**：仅修复损坏的 chunk 文件并重新运行 `--merge-chunk-results`。不要重新分析任何 chunk。

**上下文安全保证：**

- 每个 chunk 分析是自包含的：chunk 数据（约 20-40KB JSON）+ 分析 prompt（约 2KB）+ 输出（约 10-30KB JSON）可舒适地放入标准上下文窗口。
- chunk 结果写入磁盘后，不再需要在上下文中保留。主 agent 以干净的状态继续下一个 chunk。
- `--merge-chunk-results` 步骤是**纯 Python 脚本操作**（JSON 解析、去重、合并），不调用 LLM，消耗零 LLM 上下文。
- 即使 8 个 chunks，任何单点的总上下文占用都远低于 100KB。

**禁止行为（严格，违反任何一条都会导致分析报告失去价值）：**
- 不要问用户 "要拆分吗？" 或 "多少个 chunks？" — 脚本已经决定了。
- 不要修改 chunk 文件或编写自己的拆分逻辑。
- 不要跳过 chunks 或手动合并它们。
- **绝对禁止**编写 Python 脚本、Bash 脚本或任何其他自动化工具来伪造、模拟或替代 LLM 分析结果。包括但不限于：基于规则生成假 theme、假 detailed_notes、假 compatibility_risks；从 base-analysis.json 直接转换格式冒充 LLM 输出；使用模板填充冒充语义分析。
- 不要修改 chunk 结果中的 JSON 字段名或数据格式来 "让它们工作"。
- 当 chunk 缺少匹配的 commits 时，不要编造数据——诚实地报告未找到匹配。
- 不要使用子 agent、后台 agent 或并行 agent 调用进行 chunk 分析。

**如果出现问题：**
- **如果 chunk 分析失败**（超时、错误或返回非 JSON）：
  1. **重试**同一个 chunk 一次（重新读取 chunk 文件并重新分析）。
  2. 如果重试也失败：报告具体的 chunk 编号、错误类型，然后**停止**。不要继续处理部分 chunks。
  3. **绝不**对失败的 chunk 默默回退到规则分析或输出无 LLM 增强的报告。**不允许在任何情况下回退到规则分析**。
- **如果 chunk 清单不完整**（已保存 chunk 数量 < `CHUNK_COUNT`）：
  - 不要调用 `--merge-chunk-results`。识别缺失的 chunks，重试它们，仅在清单完整后继续。
- **如果 chunk 结果有冲突的主题**（相同的 `theme_id` 但不同的 `theme_name`）：合并步骤使用第一个遇到的名称；这是可接受的，因为 `theme_id` 是稳定键。
- **如果 `--merge-chunk-results` 失败**：报告错误及具体异常，然后**停止** — 不要尝试手动合并。

**合并后增强协议：**

`--merge-chunk-results` 完成后，脚本自动评估合并后的 `llm-results.json` 质量，并可能发出需要增强的信号。

**合并输出信号：**
- `CHUNK_MERGE_COMPLETE: 1` + `LLM_RESULTS: <path>` → 合并成功，检查是否需要增强
- `ENHANCEMENT_NEEDED: 1` + `ENHANCEMENT_PROMPT: <path>` + `NEEDS_FIELDS: <fields>` → 合并结果需要 LLM 增强

**当 `ENHANCEMENT_NEEDED: 1` 发出时：**

1. 读取增强 prompt 文件（`*-enhancement-prompt.txt`）。它包含：
   - 所有合并主题的摘要（名称、风险、类别、note 数量、摘要）
   - 高风险主题详情和高风险 detailed note 摘要
   - 需要增强的字段列表（例如 `executive_summary.theme`、`developer_conclusion`、`compatibility_risks`、`test_points`）

2. 将增强 prompt 喂给 LLM，请求仅包含需要增强的字段的 JSON 响应：
   ```json
   {
     "executive_summary": { "recommendation": "...", "theme": "...", "magnitude": "...", "reason": "...", "top_changes": [...], "one_liner": "..." },
     "developer_conclusion": "...",
     "compatibility_risks": [{"component": "...", "description": "..."}],
     "test_points": ["..."]
   }
   ```

3. 读取合并后的 `llm-results.json`，用 LLM 生成的内容修补需要增强的字段，然后写回。

4. 调用 `--apply-llm-results` 用增强后的内容重新生成最终报告。

**当 `ENHANCEMENT_NEEDED` 未发出时：**
- 合并结果被视为高质量。直接跳到 `--apply-llm-results`。

**为什么采用这种方式：**
- 纯 Python 合并步骤快速可靠，但无法合成细致的 executive summary。
- 增强 prompt 仅包含主题/note 摘要（不含原始数据），因此 LLM 增强是轻量级单 prompt 操作（约 5K tokens，对比完整分析的 80K+ tokens）。
- AI agent 根据脚本的信号决定是否执行增强，而非手动检查合并文件。

**分析聚焦规则（在不损失准确性的前提下减少每 chunk 时间）：**

每个 chunk 不需要详尽的逐条分析。主题级分析（`summary`、`impact`、`reasoning`）已经覆盖了主题中每条 note 的 "what changed" 和 "what it means"。`detailed_notes` 应仅对真正需要深度的 note 补充信息。

**信号驱动选择** — 仅对满足以下任一条件的 note 输出 `detailed_notes`：
1. `risk_level: "high"`（必须）
2. `has_hidden_breaking: true`（必须 — 风险可能被低估）
3. `primary_category` 为 `security` 或 `breaking`（必须 — 安全关键，无论声明的风险如何）
4. 有直接 `matched_commits` 且 commit message 提供了有意义的证据（可选，但增加分析价值）

**绝不能跳过**：主题级分析仍需处理所有 notes 以进行聚类和风险评估。从 `detailed_notes` 中跳过的 note 仍必须出现在其主题的 `note_ids` 中，并带有准确的 `risk_level` 和 `has_hidden_breaking` 标志。

### 6. 使用内置脚本进行确定性分析

使用 `scripts/analyze_openclaw_release.py` 进行可重复的 release 获取、snapshot 写入、基于 snapshot 的分类、逐条解读、风险评估、建议操作和报告生成。

每个命令都会先刷新 snapshot，然后分析该 snapshot。

示例命令：

```bash
# 关键：始终先 cd 到用户的工作区目录
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" <args>

# 提供 GitHub token（LLM 增强 commit 分析必需）
# 选项 A：通过 CLI 参数
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh --github-token <token>
# 选项 B：通过环境变量
export GITHUB_TOKEN=<token>
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh

# 默认：最新稳定版，输出中文报告，报告写入当前工作目录
# Token 有效 → 自动 LLM 增强分析（commit-message-bridge）
# Token 缺失 → 报错退出，不生成报告
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh --user-query "帮我分析最新版本"

# 显式指定输出路径（仅在用户指定时使用）
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh --output "path/to/report.md"

# 版本对比（自动 LLM 增强，当 token 有效时）
# 步骤 1：脚本准备分析数据并发出 ANALYSIS_DATA_READY 信号
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --lang zh
# 步骤 2：AI agent 读取 analysis-data.json，调用 LLM 进行综合分析，写入 llm-results.json
# 步骤 3：应用 LLM 结果并生成最终报告
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --apply-llm-results "<snapshot-dir>/openclaw-openclaw-v1.3.0-llm-results.json" --lang zh

# 其他模式
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --from v1.1.0 --to v1.3.0 --lang zh
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --include-beta --lang zh

# 手动缓存清理（删除所有缓存 snapshot 和中间文件）
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --clean-cache

```

**输出行为：**
- 如果省略 `--output` → 报告写入**当前工作目录**，文件名为 `{snapshot_stem}-analysis.md`。
- 如果提供了 `--output <path>` → 报告写入指定路径。
- 脚本完成后向 stdout 打印最终报告路径。
- **分析完成后，你必须在回复中同时包含生成的报告的绝对文件路径和 snapshot 缓存目录。** 使用以下格式：

```
| 类型 | 路径 |
|------|------|
| 最终报告 | C:\Users\...\v2026.5.18-analysis.md |
| 中间缓存 | %LOCALAPPA DATA%\openclaw-release-notes-analyzer\snapshots\  (或 ~/.cache/openclaw-release-notes-analyzer/snapshots/) |
```


### 7. 应用优先级规则

### 6.1 分类维度

分析器现在将变更分类到以下额外维度：
- **CLI**：CLI 命令、flags、options、arguments
- **Config**：配置 schema、默认值、配置文件
- **Dependency**：依赖要求、peerDependencies、Node.js 版本
- **Migration**：破坏性变更、升级指南、迁移说明
- **Docs**：文档更新、指南、教程
- **Known Issue**：已知限制、workarounds、废弃项

### 6.2 中文 Release Notes 支持

分析器现在检测 release notes 中的中文关键词，包括：
- 新增, 新功能, 修复, 安全, 性能, 破坏性变更
- 插件, 配置, 依赖, 迁移, 文档, 已知问题

### 6.3 Conventional Commit 支持

分析器现在识别 Conventional Commit 前缀：
- `feat:`, `fix:`, `perf:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`, `chore:`, `revert:`
- **Breaking 标记**：`feat!:`, `fix!:` 以及任何带 `!` 的前缀自动归类为 `breaking` 变更。

按以下顺序优先分析：

1. 插件系统变更：plugin API、lifecycle hooks、manifest schema、loader、registry、runtime。
2. API/SDK 变更：公共方法、package exports、TypeScript 类型、废弃项、迁移说明。
3. 安全修复：CVE、漏洞、auth、token、permission、依赖安全问题。
4. 性能与稳定性：crash、hang、deadlock、race、memory leak、startup speed、latency、资源使用。
5. 一般 feature 和 bug fix。

### 6.4 规则基线分析架构

规则分析器采用**两级过滤**架构平衡召回率和精确率：

**阶段 1 — 关键词召回（加权宽泛匹配）**
- `classify_text()` 针对所有类别的关键词列表（英文和中文）为每条 release note item 打分。此阶段优先召回率——可能包含假阳性。
- 英文关键词使用词边界保护（`\b`）进行匹配；中文关键词使用直接子串匹配。
- **加权评分**：匹配权重根据词长度和形式有所不同：
  - **短语**（含空格或 ≥15 字符）：权重 **3** — 例如 `"breaking change"`、`"remote code execution"`、`"affected version"` 比孤立单词携带更多信号。
  - **中等长度词**（6-14 字符）：权重 **2** — 例如 `"plugin"`、`"config"`、`"sandbox"`。
  - **短词**（<6 字符）：权重 **1** — 例如 `"api"`、`"fix"`、`"cli"`。
  - 中文词遵循同样原则：≥3 字符的词权重 **2**，更短的权重 **1**。
- **章节上下文加分**：当 `classify_release()` 检测到 item 位于 Markdown 标题下（例如 `## Breaking Changes`）时，匹配的章节类别在 `item_categories()` 中获得 +5 分数奖励。这使标题结构成为强分类信号，即使 item 文本本身模糊。
- **阈值过滤**：`item_categories()` 丢弃总分低于 2 的类别。单个弱短词匹配（分数 1）不足以保留；至少需要中等长度命中（分数 2+）或多个短词命中。

**阶段 2 — 显式信号验证（严格过滤）**
- `item_categories()` 在关键词匹配后应用每个类别的 `has_explicit_xxx_signal()` 验证器。
- 每个验证器使用两种信号：
  - `negative_tokens`：已知会取消该类别的假阳性模式（例如 `"token-efficiency"` 触发 `security` 关键词但被 `has_explicit_security_signal()` 拒绝）。
  - `strong_tokens`：接受该类别的确认信号。
- **语义模式匹配**用于 `breaking`：除 token 列表外，`has_explicit_breaking_signal()` 使用正则模式捕获常见 breaking 表达：
  - `no longer \w+` — 例如 "no longer accepts"、"no longer supports"
  - `requires \w+ [\d\.\+]+` — 例如 "requires node 18+"
  - `dropped (support|the|compatibility|for)` — 例如 "dropped support for legacy API"
  - `removed (the )?[\w-]+ (option|flag|command|method|api)` — 例如 "removed the --debug flag"
- 需要显式验证的类别：`breaking`、`security`、`dependency`、`migration`、`plugin`、`api_sdk`、`cli`、`config`。

**阶段 3 — 内部 QA 降级**
- `is_internal_qa_item()` 检测仅测试、fixture 或 harness-only 的变更，这些变更缺少公开 surface 信号（例如 `coverage`、`qa-lab`、`fixture`）。
- 这些 item 被剥离高敏感度类别（`plugin`、`api_sdk`、`security`、`breaking` 等）并降级为 `docs`，以防止错误的 feature/fix 分类。

**风险评估**
- `risk_level()` 从最终类别和 item 文本推导每条 item 的风险：
  - `breaking`/`migration`/`dependency` → `high`（含 runtime-removal 信号）或 `medium`。
  - `security` → `high`（含 CVE/credential 信号）或 `medium`。
  - `plugin`/`api_sdk`/`cli`/`config` → 仅在存在 breaking/signature/removal/deprecated 信号时为 `medium`；否则纯 feature 或 fix 为 `low`。
  - `performance` → `medium`（含 crash/deadlock 信号）或 `low`。

此架构确保广泛覆盖 release note 信号，同时通过类别特定的守卫控制假阳性。

### 7. 识别公开 Surface 影响

将以下视为开发者可见的公开 surface 变更：

- 公共 API 方法名、签名、参数、返回值。
- CLI 命令、flags、行为或输出格式。
- 配置 schema、默认值或必填字段。
- Plugin manifest 字段、版本、lifecycle hooks、loader 行为、plugin registry 契约。
- SDK package exports、类型、文档用法、示例或废弃通知。
- 所需的运行时版本，例如 Node.js 版本要求。

不要自动将以下标记为开发者可见：

- 内部重构。
- 私有变量/函数重命名。
- 仅测试变更。
- 无文档行为变更的内部算法优化。
- 无运行时或公共 API 影响的构建工具变更。

### 8. 生成报告

始终使用以下报告结构：

#### 8.1 固定输出章节

这些章节是标准报告布局的组成部分：

- **报告头**：标题、仓库、目标版本、对比版本、生成时间戳。
- **版本信息**：表格包含目标版本、发布日期、状态、对比版本、分析的 release 数量、数据来源、snapshot 文件路径和报告文件路径。
- **包含的 Releases**（仅在 `scoped releases > 1` 时）：表格列出分析范围内的所有 releases，含版本、发布日期和状态。
- **Executive Summary**（总体结论）：升级建议标签、主导主题、变更规模（总 item 数及风险分解）、前 5 个最关键变更（含附录链接和风险图标），以及针对 release 特征定制的一句话判断（prerelease 警告、breaking-change 提醒、安全优先、开发者 surface 更新或低风险例行）。
- **Developer Conclusion**（面向 Channel / 插件开发者的一句话结论）：面向 plugin/channel 开发者的一句话 verdict，基于 breaking changes、安全密度、plugin/API 数量或 config 变更进行条件分支。
- **Thematic Overview**（变更主题概览）：将所有变更语义聚类为 8-15 个功能主题，按风险排序。每个主题显示 item 数量、风险等级、相关 commits 和摘要。
- **Progressive Fix Detection**（渐进式修复检测）：分析版本范围时，展示同一 issue 在多个版本中逐步修复的链条（例如缓解 → 部分修复 → 完整修复）。每条链显示各阶段版本、修复描述和完整度，以及最终状态和影响评估。
- **Cumulative Breaking Change Analysis**（累积 Breaking Change 分析）：分析版本范围时，突出单个版本看似低风险但整个升级路径累积影响很高的情况。展示逐版本风险与累积风险对比，并具体解释为什么跳过中间版本更危险。
- **High-Risk Theme Details**（高风险主题详解）：高风险和中风险主题的深度分析。每个主题扩展为影响描述、受影响文件、相关 commits 和指向附录详细 notes 的导航链接。限于前 8 个风险主题。
- **Code Change Evidence**（代码变更证据链）：note-to-commit 关联表，展示哪些 commits 对应哪些 release notes，含变更文件和推理依据。
- **Shadow Changes**（未记录变更提示）：修改了公开 surface 但没有对应 release note 的 commits。
- **Compatibility Risks**（兼容性与风险点）：与 plugin/channel 开发者相关的高风险和中风险 item，含上下文风险描述（breaking change、安全收紧、依赖变动、配置变更）。
- **Suggested Test Points**（建议验证的测试点）：从检测到的信号（auth、plugin、CLI、channel、dependency）推导的可操作回归测试建议。
- **Ignorable Changes**（可暂时忽略的变更）：低风险、低相关性的 item，可在二次阅读时延后处理。
- **Facts, Inferences, and Uncertainties**：结构化透明性章节。Facts 涵盖 snapshot 来源和版本状态。Inferences 涵盖分类方法、建议推导、主导主题和集中组件信号。Uncertainties 涵盖低置信度 item、缺失的迁移指导、模糊的依赖信号和缺少本地项目扫描。
- **References**：所有分析的 release 页面链接。
- **Original Release Notes (Enhanced Index)**：原始 release note item 按原始顺序排列，每条标注附录 ID、类别和风险等级。
- **Appendix: Complete Per-Release-Note Details**：每条可分析 item 的完整解读表。字段：component、release tag、风险等级、置信度、类别、受众、原始文本、解读、建议操作和相关 item 的交叉引用提示。

#### 8.2 分类维度，默认不作为独立章节

以下类别是用于逐条标记、优先级排序、风险评估和影响解读的分类维度。它们在默认报告布局中**不是**独立的顶层章节：

- CLI
- Config
- Dependency
- Migration
- Docs
- Known Issue

当检测到这些信号时，通过 Executive Summary、Deep Dive、Compatibility Risks 或 Appendix 章节展示它们，而非承诺独立的顶层标题。


## 升级建议标签

| 标签 | 使用场景 |
|------|---------|
| 建议升级 | 安全修复、严重 bug 修复、crash/deadlock/memory-leak 修复，或低风险的重要 feature。 |
| 谨慎升级 | Breaking changes、依赖/运行时要求变更、公共 API 变更、CLI 变更或配置行为变更。 |
| 暂缓升级 | 无实质收益、release 数据不清晰、高风险但不符合用户需求，或生产环境不稳定的 prerelease。 |
| 仅特定场景建议升级 | 变更主要惠及 plugin 开发者、SDK 使用者、安全敏感用户或其他特定群体。 |
| 信息不足，建议进一步分析 | Release notes 缺失、模糊或不足以得出可靠结论。 |

## 场景化升级建议

始终考虑以下用户群体：

- **Plugin 开发者**：关注 hooks、manifests、lifecycle APIs、loader/runtime 行为、registry 契约、兼容性声明。
- **API/SDK 使用者**：关注公共 APIs、package exports、TypeScript 类型、废弃项、迁移说明。
- **安全敏感用户**：关注 CVE/漏洞/auth/token/permission 变更和受影响版本。
- **稳定性敏感用户**：关注 crash、hang、deadlock、memory leak、data loss、性能和高负载行为。
- **普通用户**：关注可见 feature、常见 bug 修复、升级简便性和已知风险。

## 项目扫描规则

除非用户明确要求项目级分析，否则不要检查本地项目文件。获得授权后，仅检查相关文件，如 `package.json`、lockfiles、`openclaw.config.*`、plugin manifests，以及可能导入 OpenClaw APIs 的源文件。避免 `.env`、凭证、secrets、private keys 或无关文件。

## 参考

需要详细的分类关键词、报告模板指导或决策规则时，加载 `references/analysis-rules.md`。
