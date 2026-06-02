# Analysis Rules

Use this file for classification, public-surface judgment, upgrade recommendations, and report structure.

## Table of Contents

- [Release Selection](#release-selection)
- [Classification Dimensions](#classification-dimensions)
- [Rule Baseline Architecture](#rule-baseline-architecture)
- [Priority Order](#priority-order)
- [Public Surface Impact](#public-surface-impact)
- [Recommendation Labels](#recommendation-labels)
- [Audience-Specific Guidance](#audience-specific-guidance)
- [Report Structure](#report-structure)
- [Facts, Inferences, and Uncertainties](#facts-inferences-and-uncertainties)

## Release Selection

- Stable release: GitHub `draft == false` and `prerelease == false`.
- Prerelease: GitHub `prerelease == true`, or tag/name contains `alpha`, `beta`, `rc`, `preview`, or `next`.
- Default target: latest stable release.
- Default comparison baseline: previous stable release.
- Newer prereleases are listed as beta/prerelease previews, never default upgrade targets.

## Classification Dimensions

Use these categories for note tagging, priority sorting, risk evaluation, test suggestions, and appendix interpretation.

### Plugin System

Keywords and signals:

`plugin`, `plugins`, `manifest`, `hook`, `hooks`, `lifecycle`, `loader`, `registry`, `runtime`, `extension`, `extensions`, `sandbox`, `capability`, `capabilities`, `@openclaw/`.

### API / SDK

Keywords and signals:

`api`, `sdk`, `public api`, `method`, `signature`, `parameter`, `return`, `type`, `typescript`, `export`, `package`, `deprecated`, `deprecation`, `migration`, `migrate`, `breaking`, `compatibility`, `OpenClawAPI`, `peerDependencies`.

### Security

Keywords and signals:

`security`, `vulnerability`, `cve`, `cwe`, `cvss`, `auth`, `authentication`, `authorization`, `token`, `permission`, `sandbox`, `escape`, `xss`, `csrf`, `rce`, `remote code execution`, `injection`, `secret`, `credential`, `affected version`, `affected versions`.

### Performance / Stability

Keywords and signals:

`performance`, `perf`, `optimize`, `optimization`, `speed`, `latency`, `memory`, `leak`, `crash`, `hang`, `deadlock`, `race`, `stability`, `reliability`, `timeout`, `freeze`, `startup`, `benchmark`, `data loss`.

### Breaking Change

Keywords and signals:

`breaking`, `breaking change`, `incompatible`, `removed`, `remove`, `renamed`, `rename`, `migration`, `migrate`, `deprecated`, `deprecation`, `requires node`, `minimum node`, `node.js`, `config`, `schema`, `cli`, `flag`, `rollback`, `downgrade`.

Semantic patterns:

- `no longer \w+`
- `requires \w+ [\d\.\+]+`
- `dropped (support|the|compatibility|for)`
- `removed (the )?[\w-]+ (option|flag|command|method|api)`

### Feature

`feature`, `add`, `added`, `new`, `support`, `introduce`, `introduced`, `enable`, `enhancement`, `improvement`.

### Bug Fix

`fix`, `fixed`, `bug`, `resolve`, `resolved`, `patch`, `correct`, `regression`, `issue`, `known issue`.

### CLI

`cli`, `command`, `flag`, `option`, `argument`, `subcommand`, `bash`, `shell`, `terminal`, `stdout`, `stderr`.

### Config

`config`, `configuration`, `setting`, `option`, `default`, `schema`, `openclaw.config`, `.openclawrc`, `manifest.json`.

### Dependency

`dependency`, `dependencies`, `peer dependency`, `peerDependencies`, `require`, `package.json`, `npm`, `yarn`, `pnpm`, `lockfile`, `install`, `uninstall`, `version`.

### Migration

`migration`, `migrate`, `upgrade guide`, `breaking change`, `deprecated`, `deprecation`, `breaking`, `incompatible`, `before you upgrade`, `migration guide`, `upgrade notes`.

### Docs

`docs`, `documentation`, `readme`, `changelog`, `guide`, `tutorial`, `example`, `demo`.

### Known Issue

`known issue`, `known issues`, `limitation`, `workaround`, `not supported`, `deprecated`, `upcoming`, `planned`.

### Chinese Keywords

- Feature: 新增, 新功能, 添加, 支持, 特性, 改进
- Fix: 修复, bug, 问题, 修正, 补丁
- Breaking: 破坏性变更, breaking, 不兼容, 移除, 重命名, 迁移, 废弃
- Security: 安全, 漏洞, cve, 认证, 授权, 权限
- Performance: 性能, 优化, 速度, 延迟, 内存, 泄漏, 崩溃, 卡顿, 稳定性
- Plugin: 插件, hook, 生命周期, manifest, 扩展
- API/SDK: api, sdk, 公共接口, 方法, 签名, 参数, 类型, 导出, 废弃, 迁移
- CLI: 命令行, cli, 命令, flag, 参数
- Config: 配置, config, 配置文件, 默认配置, schema
- Dependency: 依赖, dependencies, 版本要求, package.json
- Migration: 迁移, 升级指南, breaking change, 废弃
- Docs: 文档, docs, readme, 指南
- Known issue: 已知问题, 限制, 已知限制

## Rule Baseline Architecture

The rule analyzer is a baseline only. LLM analysis performs the final semantic classification and report judgment.

### Stage 1: Keyword Recall

- `classify_text()` scores release note items using English and Chinese keyword lists.
- English keywords use word-boundary matching where appropriate.
- Chinese keywords use direct substring matching.
- Weighting:
  - Phrases or terms at least 15 characters: weight 3.
  - Terms 6-14 characters: weight 2.
  - Terms under 6 characters: weight 1.
  - Chinese terms at least 3 characters: weight 2; shorter terms: weight 1.
- Markdown section context can add category weight, especially for headings such as `Breaking Changes`.
- Categories below the threshold are discarded.

### Stage 2: Explicit Signal Verification

Apply category-specific validators after keyword recall. Validators use:

- `negative_tokens`: patterns known to create false positives.
- `strong_tokens`: confirming patterns for the category.

Categories that need explicit verification:

- `breaking`
- `security`
- `dependency`
- `migration`
- `plugin`
- `api_sdk`
- `cli`
- `config`

### Stage 3: Internal QA Downgrade

If a note is only about tests, fixtures, harnesses, coverage, or QA lab changes, remove high-sensitivity categories such as `plugin`, `api_sdk`, `security`, and `breaking` unless a public-surface signal is explicit. Downgrade such items to `docs` or low-risk support context.

### Risk Evaluation

- `breaking`, `migration`, `dependency`: high when runtime removal or hard migration signals exist; otherwise medium.
- `security`: high when CVE, credential, permission, auth bypass, or exploit signal exists; otherwise medium.
- `plugin`, `api_sdk`, `cli`, `config`: medium only when signature, removal, behavior, default, or compatibility changes exist; otherwise low.
- `performance`: medium for crash, deadlock, data loss, memory leak, or reliability regressions; otherwise low.
- `feature`, `fix`, `docs`, `known_issue`: usually low unless connected to a higher-priority category.

## Priority Order

Analyze and explain in this order:

1. Plugin-system impact.
2. API/SDK impact.
3. Security fixes.
4. Performance and stability fixes.
5. Breaking changes, migration, dependency, CLI, and config risks.
6. General features and bug fixes.
7. Docs, known issues, and low-risk support changes.

## Public Surface Impact

Treat these as developer-visible public surface changes:

- Public API method names, signatures, parameters, and return values.
- CLI commands, flags, behavior, and output format.
- Config schema, defaults, required fields, and config file behavior.
- Plugin manifest fields, lifecycle hooks, loader behavior, runtime behavior, and registry contracts.
- SDK package exports, types, documentation usage, examples, and deprecation notices.
- Required runtime versions such as Node.js version requirements.
- Auth, token, permission, sandbox, or credential behavior that affects deployed users.

Do not automatically mark these as public-surface impact:

- Internal refactors.
- Private variable or function renames.
- Test-only changes.
- Fixtures, harnesses, coverage, or QA lab changes.
- Internal algorithm optimization without documented behavior change.
- Build tooling changes with no runtime or public API impact.

## Recommendation Labels

### 建议升级

Use when the release includes:

- Security fix relevant to deployed users.
- CVE or vulnerability fix.
- Crash, deadlock, data loss, memory leak, or severe stability fix.
- Important bug fix affecting common workflows.
- Low-risk release with high-value feature.

### 谨慎升级

Use when the release includes:

- Breaking change.
- Public API or SDK change.
- Plugin manifest or hook contract change.
- Config schema/default behavior change.
- CLI command/flag/output change.
- Runtime or dependency requirement change.
- Cross-version cumulative risk that requires migration planning.

### 暂缓升级

Use when:

- No meaningful benefit for the user's scenario.
- Only docs/test/internal changes are visible.
- Target is a prerelease and the user asks about production use.
- Important risks exist without urgent benefit.
- Release data is unclear enough that an upgrade decision would be premature.

### 仅特定场景建议升级

Use when changes mainly benefit one group, such as plugin developers, API users, security-sensitive users, or stability-sensitive users.

### 信息不足，建议进一步分析

Use when release notes are missing, vague, malformed, unavailable, or insufficient to support a reliable conclusion.

## Audience-Specific Guidance

Always consider:

- Plugin developers: hooks, manifests, lifecycle APIs, loader/runtime behavior, registry contracts, compatibility statements.
- API/SDK users: public APIs, package exports, TypeScript types, deprecations, migration notes.
- Security-sensitive users: CVE, vulnerability, auth, token, permission, and affected versions.
- Stability-sensitive users: crash, hang, deadlock, memory leak, data loss, high-load behavior.
- Ordinary users: visible features, common bug fixes, upgrade simplicity, known risks.

## Report Structure

The current LLM-driven renderer uses this structure:

1. Report header: title, repository, target version, compare version, generated timestamp.
2. Version information: target version, publish date, status, compare version, analyzed release count, data source, snapshot file, report file.
3. Included Releases: only when `scoped releases > 1`.
4. Executive Summary: recommendation, core theme, magnitude, reason, top changes, one-line verdict.
5. Developer Conclusion: one concise conclusion for plugin/channel/API developers.
6. Thematic Overview: 8-15 semantic themes sorted by risk and note count.
7. Progressive Fix Detection: only meaningful for multi-release analysis; show fix chains when found.
8. Cumulative Breaking Change Analysis: only meaningful for multi-release analysis; explain cumulative upgrade risk.
9. High-Risk Theme Details: deep dive for high/medium themes, capped to the highest-risk themes.
10. Code Change Evidence: note-to-commit association table.
11. Shadow Changes: public-surface commits without matching release notes.
12. Compatibility Risks: risks relevant to plugin/channel/API users.
13. Suggested Test Points: actionable regression tests derived from detected signals.
14. Beta / Prerelease Preview.
15. Facts, Inferences, and Uncertainties: transparent separation of source facts, analytical judgments, and unresolved uncertainty.
16. References.
17. Original Release Notes (Enhanced Index): original notes with IDs, categories, and risk tags.
18. Appendix: LLM enhanced per-note details for high-risk, commit-linked, or hidden-breaking notes.

Classification dimensions such as CLI, Config, Dependency, Migration, Docs, and Known Issue are not automatically standalone top-level report sections. Surface them through summary, themes, compatibility risks, suggested tests, original note tags, and appendix details.

## Facts, Inferences, and Uncertainties

Facts:

- GitHub release metadata.
- Release note text.
- Explicit release labels such as draft/prerelease.
- Explicit commit messages and changed file paths supplied by the script.
- Snapshot and report paths.

Inferences:

- Category classification.
- Upgrade recommendation.
- Public-surface impact.
- Theme clustering.
- Commit-to-note semantic association.
- Progressive fix chains and cumulative breaking-change risk.

Uncertainties:

- Ambiguous release notes.
- Missing migration guidance.
- Incomplete commit evidence.
- Low-confidence category matches.
- Compatibility impacts not explicitly stated.
- Local project impact when no local scan was requested or authorized.
