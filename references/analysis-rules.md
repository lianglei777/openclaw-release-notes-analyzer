# OpenClaw Release Analyzer — Analysis Rules

## Stable Release Rules

- Stable release: GitHub `draft == false` and `prerelease == false`.
- Prerelease: GitHub `prerelease == true`, or tag/name contains `alpha`, `beta`, `rc`, `preview`, or `next`.
- Default target: latest stable release.
- Default comparison baseline: previous stable release.
- Newer prereleases are listed as beta/prerelease previews, never as default upgrade targets.

## Classification Keywords

### Plugin System

`plugin`, `plugins`, `manifest`, `hook`, `hooks`, `lifecycle`, `loader`, `registry`, `runtime`, `extension`, `extensions`, `sandbox`, `capability`, `capabilities`, `@openclaw/`.

### API / SDK

`api`, `sdk`, `public api`, `method`, `signature`, `parameter`, `return`, `type`, `typescript`, `export`, `package`, `deprecated`, `deprecation`, `migration`, `migrate`, `breaking`, `compatibility`, `OpenClawAPI`, `peerDependencies`.

### Security

`security`, `vulnerability`, `cve`, `cwe`, `cvss`, `auth`, `authentication`, `authorization`, `token`, `permission`, `sandbox`, `escape`, `xss`, `csrf`, `rce`, `remote code execution`, `injection`, `secret`, `credential`, `affected version`, `affected versions`.

### Performance / Stability

`performance`, `perf`, `optimize`, `optimization`, `speed`, `latency`, `memory`, `leak`, `crash`, `hang`, `deadlock`, `race`, `stability`, `reliability`, `timeout`, `freeze`, `startup`, `benchmark`, `data loss`.

### Breaking Change

`breaking`, `breaking change`, `incompatible`, `removed`, `remove`, `renamed`, `rename`, `migration`, `migrate`, `deprecated`, `deprecation`, `requires node`, `minimum node`, `node.js`, `config`, `schema`, `cli`, `flag`, `rollback`, `downgrade`.

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


For Chinese release notes:
- 新增, 新功能, 添加, 支持, 特性, 改进 (feature)
- 修复, bug, 问题, 修正, 补丁 (fix)
- 破坏性变更, breaking, 不兼容, 移除, 重命名, 迁移, 废弃 (breaking)
- 安全, 漏洞, cve, 认证, 授权, 权限 (security)
- 性能, 优化, 速度, 延迟, 内存, 泄漏, 崩溃, 卡顿, 稳定性 (performance)
- 插件, hook, 生命周期, manifest, 扩展 (plugin)
- api, sdk, 公共接口, 方法, 签名, 参数, 类型, 导出, 废弃, 迁移 (api_sdk)
- 命令行, cli, 命令, flag, 参数 (cli)
- 配置, config, 配置文件, 默认配置, schema (config)
- 依赖, dependencies, 版本要求, package.json (dependency)
- 迁移, 升级指南, breaking change, 废弃 (migration)
- 文档, docs, readme, 指南 (docs)
- 已知问题, 限制, 已知限制 (known_issue)



## Priority Order

1. Plugin-system impact.
2. API/SDK impact.
3. Security fixes.
4. Performance and stability fixes.
5. Breaking changes and migration risks.
6. General features and bug fixes.

## Recommendation Decision Rules

### Recommend Upgrade / 建议升级

Use when the release includes at least one of:

- Security fix relevant to deployed users.
- CVE or vulnerability fix.
- Crash, deadlock, data-loss, memory-leak, or severe stability fix.
- Important bug fix affecting common workflows.
- Low-risk release with high-value feature.

### Upgrade with Caution / 谨慎升级

Use when the release includes at least one of:

- Breaking change.
- Public API or SDK change.
- Plugin manifest or hook contract change.
- Config schema/default behavior change.
- CLI command/flag/output change.
- Runtime or dependency requirement change.

### Defer Upgrade / 暂缓升级

Use when:

- No meaningful changes for the user's scenario.
- Only documentation/test/internal changes are visible.
- The target is a prerelease and the user asks about production use.
- Important risks exist but no urgent benefit is identified.

### Conditional Upgrade / 仅特定场景建议升级

Use when changes primarily benefit one group, such as plugin developers, API users, security-sensitive users, or stability-sensitive users.

### Insufficient Data / 信息不足，建议进一步分析

Use when release notes are missing, vague, malformed, or unavailable.

## Facts, Inferences, Uncertainties

- Facts: release notes text, GitHub metadata, explicit release labels, explicit PR/issue links.
- Inferences: likely impact derived from keywords and documented changed areas.
- Uncertainties: ambiguous release notes, missing migration details, unclear compatibility, unavailable compare data.

## Report Structure Guidance

### Fixed Output Sections

Treat the following as the current default report layout:

- Overall Conclusion
- Included Releases (only when more than one release is analyzed)
- Version Information
- Key Changes Summary
- Plugin System Impact
- API / SDK Impact
- Security Fixes
- Performance and Stability
- Upgrade Action Checklist (only when corresponding signals are detected)
- Scenario-Based Recommendations
- Beta / Prerelease Preview
- Facts, Inferences, and Uncertainties
- References
- Appendix: Complete Per-Release-Note Details

### Classification Dimensions

The following categories are used for classification, prioritization, checklist generation, and appendix interpretation. They are not separate top-level sections in the current default report layout unless the implementation is explicitly expanded later:

- CLI
- Config
- Dependency
- Migration
- Docs
- Known Issue

When these categories are detected, surface them through the existing summary, impact, checklist, risk, and appendix sections rather than promising standalone headings.

## Report Template (English)


```markdown
# OpenClaw Release Analysis Report

**Repository**: `openclaw/openclaw`
**Target Version**: `v1.x.x`
**Compare Version**: `v1.y.y`
**Generated at**: YYYY-MM-DD HH:MM:SS

---

## Overall Conclusion

**Recommendation**: Recommend Upgrade / Upgrade with Caution / Defer Upgrade / Conditional Upgrade / Insufficient Data

[2-4 sentences explaining the recommendation]

---

## Included Releases

| Version | Published Date | Status |
|---------|----------------|--------|
| `v1.x.x` | YYYY-MM-DD | Stable |
| `v1.y.y` | YYYY-MM-DD | Stable |

---

## Version Information

| Field | Value |
|-------|-------|
| Target Version | |
| Compare Version | |
| Published Date | |
| Data Source | Fresh GitHub Releases API snapshot |
| Snapshot File | |

---

## Key Changes Summary

### New Features

### Bug Fixes

### Breaking Changes / Upgrade Risks

---

## Plugin System Impact

## API / SDK Impact

## Security Fixes

## Performance and Stability

---

## Upgrade Action Checklist

Based on detected signals, consider the following actions before upgrading:

- **Breaking Changes Found**: Review breaking changes, check compatibility, and prepare migration steps before upgrading.
- **Plugin System Changes**: Review plugin manifest, hook signatures, and test plugin compatibility in target version.
- **API/SDK Changes**: Review public API surface changes, TypeScript types, and update dependent code accordingly.
- **Security Fixes Found**: Prioritize security fixes. Test in non-production environment before production rollout.
- **Configuration Changes**: Review config schema changes and update openclaw.config.* files as needed.
- **Dependency Changes**: Review dependency requirement changes (Node.js version, peerDependencies, etc.).

---

## Scenario-Based Recommendations

### Plugin Developers

### API / SDK Users

### Security-Sensitive Users

### Stability-Sensitive Users

### Ordinary Users

---

## Beta / Prerelease Preview

## Facts, Inferences, and Uncertainties

### Facts
- At the start of this run, release metadata and release notes were fetched from the GitHub Releases API and written to a local snapshot.
- Analysis uses the freshly written snapshot file for this run.
- Stable release is determined by GitHub `prerelease=false` and `draft=false`.
- Target release URL: [URL]

### Inferences
- Classification is based on release note section titles, bullet points, and keyword matching.
- Upgrade recommendation is derived from combined signals across security, stability, plugin system, API/SDK, and breaking-change categories.

### Uncertainties
- Compatibility impacts not explicitly stated in release notes require further inspection of compare diffs, PRs, issues, or source code.
- This report does not scan local project files without explicit user authorization.

## References
- [v1.x.x](URL)

---

## Appendix: Complete Per-Release-Note Details
```

## Report Template (Chinese)

```markdown
# OpenClaw Release 分析报告

**仓库**: `openclaw/openclaw`
**目标版本**: `v1.x.x`
**对比版本**: `v1.y.y`
**生成时间**: YYYY-MM-DD HH:MM:SS

---

## 总体结论

**升级建议**：建议升级 / 谨慎升级 / 暂缓升级 / 仅特定场景建议升级 / 信息不足，建议进一步分析

[2-4 句话说明原因]

---

## 包含的版本列表

| 版本 | 发布日期 | 状态 |
|------|----------|------|
| `v1.x.x` | YYYY-MM-DD | Stable |
| `v1.y.y` | YYYY-MM-DD | Stable |

---

## 版本信息

| 字段 | 值 |
|---|---|
| 目标版本 | |
| 对比版本 | |
| 发布日期 | |
| 数据来源 | Fresh GitHub Releases API snapshot |
| Snapshot File | |

---

## 重点变化摘要

### 新增 Feature

### Bug Fix

### Breaking Change / 升级风险

---

## 插件系统影响

## API / SDK 影响

## 安全修复

## 性能与稳定性

---

## 升级操作检查清单

基于检测到的信号，升级前建议检查以下内容：

- **发现 Breaking Changes**: 建议查看 breaking changes，检查兼容性，并在升级前准备迁移步骤。
- **插件系统变化**: 建议检查插件 manifest、hook 签名，并在目标版本测试插件兼容性。
- **API/SDK 变化**: 建议检查公共 API 表面变化、TypeScript 类型，并相应更新依赖代码。
- **发现安全修复**: 建议优先处理安全修复，在非生产环境测试后再推送到生产环境。
- **配置变化**: 建议检查配置 schema 变化，按需更新 openclaw.config.* 文件。
- **依赖变化**: 建议检查依赖要求变化（Node.js 版本、peerDependencies 等）。

---

## 场景化升级建议

### 插件开发者

### API / SDK 使用者

### 安全敏感用户

### 稳定性敏感用户

### 普通使用者

---

## Beta / Prerelease 前瞻提示

## 事实、推断与不确定项

### 事实
- 每次运行开始时，都会先从 GitHub Releases API 拉取 release metadata 和 release notes，并写入本地 snapshot。
- 本次分析基于当前运行写入的 snapshot 文件完成。

- Stable 判断使用 GitHub `prerelease=false` 且 `draft=false`。
- 目标 release URL: [URL]

### 推断
- 分类基于 release note 标题、项目符号和关键词匹配。
- 升级建议基于安全、稳定性、插件系统、API/SDK、breaking change 等信号综合判断。

### 不确定项
- Release notes 未明确说明的兼容性影响需要进一步查看 compare diff、PR、Issue 或源码。
- 未经用户明确授权，本报告未扫描本地项目代码。

## 参考来源
- [v1.x.x](URL)

---

## 附录：完整 Release Note 解读明细
```

