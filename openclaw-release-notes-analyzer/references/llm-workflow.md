# LLM Workflow Reference

Use this file when executing LLM-enhanced analysis, handling chunks, writing LLM results, or merging large release ranges.

## Table of Contents

- [Overview](#overview)
- [Required Phases](#required-phases)
- [Single-Chunk Workflow](#single-chunk-workflow)
- [Multi-Chunk Workflow](#multi-chunk-workflow)
- [Required JSON Shape](#required-json-shape)
- [Field Rules](#field-rules)
- [Forbidden](#forbidden)

## Overview

The analyzer uses commit-message bridge analysis. The script is the deterministic data pipeline; the AI agent performs semantic analysis from the generated JSON data.

Inputs provided to the LLM:

- `release_notes`: raw release note items with IDs and `source_version`.
- `commits`: selected commits with messages, authors, changed files, and relevance scores.
- `code_changes`: directory-level diff statistics and top changed files, not raw patches.

The LLM must connect release notes to commits semantically, detect shadow changes, identify public-surface risk, and produce structured JSON that the script can render.

## Required Phases

### Phase 1: Theme Clustering

Group all release notes into 8-15 semantic themes by functional intent, not by mechanical component path. Every note must appear in some theme through `note_ids`, even if it is not included in `detailed_notes`.

Each theme should include:

- `theme_id`
- `theme_name`
- `note_ids`
- `primary_category`
- `risk_level`
- `summary`
- `impact`
- `related_commits`
- `affected_files`
- `confidence`
- `has_hidden_breaking`
- `hidden_risks`
- `reasoning`

### Phase 2: Cross-Version Analysis

When `source_version` spans multiple releases, analyze:

- Progressive fix chains: mitigation -> partial fix -> complete fix.
- Cumulative breaking changes: low-risk individual changes that become higher-risk across an upgrade path.
- Version range dependency: which intermediate versions introduced or completed each change.

### Phase 3: Selective Per-Note Deep Analysis

Do not deep-analyze every note. Produce `detailed_notes` only when a note matches at least one condition:

- `risk_level` is `high`.
- `has_hidden_breaking` is `true`.
- `primary_category` is `security` or `breaking`.
- A direct `matched_commits` link provides meaningful evidence.

Skipped notes must still be covered by `themes.note_ids`.

### Phase 4: Shadow Change Detection

Detect commits that affect public surface but have no matching release note. Ignore pure internal refactors, docs-only commits, tests, fixtures, and unrelated build noise unless they imply runtime or public API impact.

## Single-Chunk Workflow

Run the script in data preparation mode:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v2026.5.28 --prepare-analysis-data --github-token <token>
```

Expected signals:

```text
ANALYSIS_DATA_READY: 1
CHUNKING_REQUIRED: 0
CHUNK_0: <snapshot-dir>/<repo>-<target>-analysis-chunk-000.json
LLM_RESULTS_TARGET: <snapshot-dir>/<repo>-<target>-llm-results.json
```

Then:

1. Read `CHUNK_0`.
2. Generate the JSON result described below.
3. Write the JSON to `LLM_RESULTS_TARGET`.
4. Run:
   ```bash
   cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v2026.5.28 --apply-llm-results --github-token <token>
   ```

## Multi-Chunk Workflow

When the script reports `CHUNKING_REQUIRED: 1`, process every chunk separately.

Expected signals:

```text
ANALYSIS_DATA_READY: 1
CHUNKING_REQUIRED: 1
CHUNK_COUNT: 3
CHUNK_0: <snapshot-dir>/<repo>-<target>-analysis-chunk-000.json
CHUNK_1: <snapshot-dir>/<repo>-<target>-analysis-chunk-001.json
CHUNK_2: <snapshot-dir>/<repo>-<target>-analysis-chunk-002.json
MERGE_COMMAND: --merge-chunk-results
LLM_RESULTS_TARGET: <snapshot-dir>/<repo>-<target>-llm-results.json
```

For each chunk:

1. Read the chunk file.
2. Produce the same JSON schema as a single-chunk analysis.
3. Write each chunk result to the snapshot directory with this exact pattern:
   ```text
   {repo}-{target}-analysis-result-chunk-{idx:03d}.json
   ```
   Example for chunk 0:
   ```text
   openclaw-openclaw-v2026.5.28-analysis-result-chunk-000.json
   ```

Then run the script merge command indicated by output. The script performs deterministic merge support and can generate enhancement prompts when required.

Do not manually concatenate chunks. Do not skip chunking. Do not decide a custom split strategy; the script decides chunk boundaries.

## Required JSON Shape

The result must be a JSON object. Do not wrap it in Markdown fences.

```json
{
  "executive_summary": {
    "recommendation": "建议升级",
    "theme": "安全加固与认证重构",
    "magnitude": "大",
    "reason": "包含多个安全修复和 OAuth 流程调整",
    "top_changes": [
      {
        "note_id": "R-001",
        "text": "Plugins/doctor: drop stale npm install records",
        "risk": "high",
        "categories": ["breaking", "plugin"]
      }
    ],
    "one_liner": "本版包含认证流程 breaking change，需要重新配置后再升级。"
  },
  "developer_conclusion": "这是一版带兼容性包袱的更新，升级前先验证配置和插件兼容性。",
  "themes": [
    {
      "theme_id": "T-01",
      "theme_name": "Feishu 认证流程重构",
      "note_ids": ["R-002", "R-067"],
      "primary_category": "security",
      "risk_level": "high",
      "summary": "Feishu 默认认证路径发生调整",
      "impact": "已绑定 Feishu 的用户需要重新验证配置",
      "related_commits": ["abc1234"],
      "affected_files": ["src/channels/feishu/auth.ts"],
      "confidence": "high",
      "has_hidden_breaking": false,
      "hidden_risks": "",
      "reasoning": "commit message 与 release note 语义直接对应"
    }
  ],
  "detailed_notes": [
    {
      "note_id": "R-001",
      "component": "Plugins/doctor",
      "categories": ["breaking", "plugin", "dependency"],
      "risk_level": "high",
      "interpretation": "doctor --fix 现在会删除 stale npm records，升级后 registry 状态可能变化。",
      "action_items": [
        "运行 openclaw doctor --fix 观察插件清理行为",
        "验证关键插件升级后仍能加载"
      ],
      "audience": ["插件开发者", "运维人员"],
      "matched_commits": ["def5678"],
      "affected_files": ["src/plugins/doctor.ts"],
      "has_hidden_breaking": false,
      "reasoning": "commit message 直接说明 drop stale managed npm install records"
    }
  ],
  "compatibility_risks": [
    {
      "component": "Feishu",
      "description": "认证配置行为变化，旧配置可能需要重新绑定或迁移。"
    }
  ],
  "test_points": [
    "用旧版配置验证升级后认证流程是否仍可用"
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
      "issue_description": "Feishu auth token refresh failure",
      "stages": [
        {
          "note_id": "R-015",
          "source_version": "v2026.4.10",
          "fix_description": "Added retry attempts",
          "completeness": "mitigation"
        }
      ],
      "final_status": "partially_fixed",
      "impact_assessment": "中间版本仍可能有间歇性失败",
      "affected_components": ["Feishu", "Auth"]
    }
  ],
  "version_evolution": [
    {
      "evolution_id": "VE-01",
      "description": "Feishu authentication interface underwent consecutive adjustments",
      "affected_versions": ["v2026.4.10", "v2026.4.11", "v2026.4.12"],
      "individual_risk": "low",
      "cumulative_risk": "high",
      "risk_escalation_reason": "多个版本分别调整废弃、默认行为和移除兼容层，跨版本直接升级需要同时处理三类迁移。",
      "related_themes": ["T-01"],
      "affected_components": ["Feishu", "Auth"],
      "migration_advice": "建议逐版本升级并在每一步验证认证配置。"
    }
  ]
}
```

## Field Rules

- `recommendation`: use `建议升级`, `谨慎升级`, `暂缓升级`, `仅特定场景建议升级`, or `信息不足，建议进一步分析`.
- `magnitude`: use `大`, `中`, or `小`.
- `risk_level`: use `high`, `medium`, or `low`.
- `confidence`: use `high`, `medium`, or `low`.
- `completeness`: use `mitigation`, `partial`, or `complete`.
- `final_status`: use `fully_fixed`, `partially_fixed`, or `mitigated`.
- `related_commits` and `matched_commits` should contain SHAs only when supported by commit evidence.
- `reasoning` must cite concrete commit-message fragments or file paths when making code-evidence claims.

## Forbidden

- Do not invent commits, files, PRs, CVEs, or migration paths.
- Do not use external LLM SDKs or request the user to provide a separate LLM API key.
- Do not write intermediate files inside the skill installation directory.
- Do not embed large JSON through `python -c`; write JSON to a file.
- Do not use Node.js or unrelated tools to write LLM results.
- Do not produce a report if token validation fails.
