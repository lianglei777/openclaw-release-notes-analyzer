---
name: openclaw-release-analyzer
description: This skill should be used when analyzing OpenClaw GitHub releases, release notes, version comparisons, upgrade impact, bug fixes, new features, plugin-system changes, API/SDK changes, security fixes, performance/stability changes, beta/prerelease previews, or OpenClaw upgrade recommendations.
---

# OpenClaw Release Analyzer

## Overview

Analyze OpenClaw release notes and GitHub release metadata to help developers understand what changed between versions and decide whether to upgrade. Focus on bug fixes, new features, plugin-system impact, API/SDK impact, security fixes, performance/stability changes, breaking-change risk, and scenario-based upgrade recommendations.

**Output language**: the report is generated in the language matching the user's input. Technical proper nouns (OpenClaw, API, SDK, CLI, hook, manifest, plugin, etc.) are always kept in English for clarity.

## Use Cases

Invoke this skill for requests such as:

- Analyze the latest OpenClaw release.
- Compare two OpenClaw versions.
- Summarize changes across a version range.
- Check whether an OpenClaw update includes important bug fixes or features.
- Evaluate upgrade impact for plugin developers, API/SDK users, security-sensitive users, stability-sensitive users, or ordinary users.
- Preview newer beta, alpha, or release-candidate versions without treating them as default upgrade targets.
- Inspect OpenClaw release notes for plugin, API, SDK, security, performance, or breaking-change signals.

## Default Behavior

- Analyze `openclaw/openclaw` unless a different repository is explicitly requested.
- **Always verify GitHub token before any API call.** The script checks token validity via `/rate_limit`; token can be provided via `--github-token` or the `GITHUB_TOKEN` environment variable.
- **Token valid** → automatically enter **LLM-enhanced diff analysis mode** (significantly more accurate than rule-based analysis).
- **Token invalid or missing** → automatically fall back to **rule-based analysis only**, print a warning to stderr, and mark the report data source as "rule-based only".
- Always start each analysis run by fetching the latest release metadata and release notes from GitHub Releases API.
- Always write the fetched data into a fresh local snapshot before analysis.
- Always analyze the freshly written local snapshot for the current run; do not analyze directly from repeated API reads.
- Do not offer or use alternate data-source modes such as offline local-file input, cache reuse, `--use-cache`, or manual `--refresh` switching.
- Treat non-draft, non-prerelease releases as stable releases.
- By default, compare the latest stable release against the previous stable release.
- Mention beta/prerelease versions newer than the latest stable only as forward-looking previews.
- Do not scan the user's local project unless explicitly requested and authorized.
- Separate facts from inference and uncertainty.
- Include per-release-note interpretation with impact audience, risk level, confidence, and suggested actions.
- Avoid claiming internal refactors affect developers unless public surface changes are evidenced.

## File Locations (Snapshots vs. Reports)

**Intermediate Artifacts (snapshots, LLM prompts, base analysis):**
- All intermediate files are stored in the **platform cache directory**:
  - **Windows**: `%LOCALAPPDATA%\openclaw-release-analyzer\snapshots`
  - **Linux/macOS**: `~/.cache/openclaw-release-analyzer/snapshots`
- **Never** written into the skill installation directory. If `--snapshot-dir` points inside the skill directory, the script automatically falls back to the platform cache directory.
- Intermediate artifact types and lifecycle:
  - `*-release-notes.md`: Raw GitHub API snapshot. Retains the most recent 20 versions to avoid repeated API fetches.
  - `*-analysis-data.json`: Master analysis data for LLM (release notes + commits + diff stats). Step-internal, cleaned after report generation.
  - `*-base-analysis.json`: Rule-based analysis results (step-internal, cleaned after report generation).
  - `*-llm-results.json`: LLM analysis results (retained for 7 days to allow re-running report generation).
- **Automatic cache consistency verification** (Optimization #7 — Cache Auto-Consistency Check):
  - Every time a cached snapshot is loaded, the script runs a multi-layer consistency check **before** using the data.
  - **Structure integrity**: Verifies frontmatter has all required fields (`repo`, `target_version`, `fetched_at`, `scoped_releases`, `release_payload_base64`, etc.) and body contains sections for each scoped release.
  - **Payload consistency**: Verifies `release_payload_base64` decodes correctly, contains all scoped releases, and the target version is present.
  - **Freshness check**: Compares cached data against live GitHub API data — detects if a newer stable release is available (in `--latest` mode), if the target version no longer exists, or if `published_at` has changed (indicating the release was edited).
  - **LLM results consistency**: Before applying cached `llm-results.json`, verifies the file is valid JSON, not older than its associated snapshot, and references versions that exist in the snapshot.
  - If any **error-level** check fails, the script automatically discards the inconsistent cache and re-fetches from GitHub. **Warning-level** issues (e.g., snapshot older than 7 days) are reported to stderr but do not block cache usage.
- Snapshots are **not the final deliverable** and can be safely deleted at any time.
- Use `--clean-cache` for manual one-shot cleanup.

**Analysis Reports (final deliverable):**
- If the user specifies an output path (e.g. "输出到 /path/to/report.md"), pass it via `--output <path>`.
- **If the user does NOT specify an output path**, the report defaults to the **current working directory** with the filename `{snapshot_stem}-analysis.md` (e.g. `openclaw-openclaw-v1.3.0-release-notes-analysis.md`).
- Before running the script, `cd` into the user's current workspace directory so the report lands there by default.
- **After the analysis completes, you MUST clearly tell the user BOTH: (1) the absolute file path of the generated report, AND (2) the snapshot cache directory where intermediate data was written.** Use a table format for clarity:

```
| 类型 | 路径 |
|------|------|
| 最终报告 (Report) | <absolute-path-to-report> |
| 中间缓存 (Snapshot) | <platform-cache-dir> |
```

## Workflow

### 1. Detect Output Language

Detect the user's language from the input request:

- If the request contains Chinese characters or is predominantly in Chinese, generate the report in Chinese.
- Otherwise, generate the report in English.
- Technical proper nouns (API, SDK, CLI, plugin, hook, manifest, release note, etc.) are always kept in English regardless of language mode.

Pass the detected language to the script via `--lang en` or `--lang zh`.

### 2. Resolve Analysis Scope

Identify the intended scope from the user request:

- Latest stable analysis: no version provided.
- Single target version: one version mentioned.
- Version comparison: two versions mentioned, such as `v1.2.3` to `v1.3.0`.
- Version range: from/to versions or a range expression.
- Beta preview: user explicitly asks about beta, alpha, rc, prerelease, or preview versions.
- Project-aware compatibility analysis: only when the user explicitly asks to inspect a project.

### 3. GitHub Token Verification (Before Any API Call)

The script automatically verifies the GitHub token on every run, **before** making any API requests:

1. **Token resolution order**: `--github-token` CLI argument → `GITHUB_TOKEN` environment variable → none.
2. **Token validation**: calls `GET /rate_limit` to verify the token is active and not expired.
3. **If token is valid** (`TOKEN_STATUS: valid` printed to stderr):
   - The script proceeds with **full LLM-enhanced diff analysis** as the default mode.
   - In default mode (Mode C), it automatically generates LLM prompts and signals readiness (`LLM_PROMPTS_READY: N`), then exits so the invoking AI agent can perform the LLM analysis step.
4. **If token is invalid or missing** (`TOKEN_STATUS: invalid` printed to stderr):
   - A language-adaptive warning is printed to stderr explaining that only rule-based analysis will be performed and results may be less accurate.
   - `--no-llm` is automatically forced.
   - The report's `data_source` field is set to "rule-based only" for transparency.

If the user explicitly provides a token that fails validation, tell them the token is invalid and ask whether to continue with rule-based-only analysis or provide a corrected token.

### 4. Refresh Snapshot Before Analysis

Use one fixed data flow for every run:

1. Fetch the latest matching release metadata and release notes from GitHub Releases API.
2. Write the fetched data to a local snapshot in the **platform cache directory**:
   - **Windows**: `%LOCALAPPDATA%\openclaw-release-analyzer\snapshots`
   - **Linux/macOS**: `~/.cache/openclaw-release-analyzer/snapshots`
   - Override with `--snapshot-dir` only if explicitly needed.
3. Load the snapshot back from disk.
4. **Verify cache consistency** (automatic, no user action required). Before using any cached snapshot or LLM results, the script performs structure integrity, payload consistency, freshness, and LLM results alignment checks. If any check fails with an error, the cached file is discarded and fresh data is fetched automatically.
5. Generate the analysis report from the verified snapshot content only.

Snapshots are intermediate cache data — they live in the system cache directory and can be safely deleted. **Snapshots are NOT the final deliverable.** The analysis report is the only file the user cares about.

**Report output location rules:**
- If the user specifies an output path → pass it via `--output <path>`.
- If the user does NOT specify an output path → **DO NOT pass `--output`**; the script automatically writes the report to the current working directory (`Path.cwd()` / `{snapshot_stem}-analysis.md`).
- **ALWAYS `cd` into the user's current workspace root before running the script**, so the default output lands in the workspace directory, not in the skill directory or a `snapshots/` subdirectory.

Keep the analysis scope as release-note based unless the user explicitly asks for project-aware compatibility inspection. Do not introduce offline-file, cache-reuse, or multiple source-selection modes.

### 5. LLM-Powered Commit-Message Bridge Analysis (Token-Dependent Default)

When a valid GitHub token is available and a compare baseline exists (e.g., `--compare v1.2.3 --target v1.3.0`), the script **automatically** enhances the analysis with a **commit-message-bridge** approach. This approach fixes the fundamental flaw of the old per-component path-matching strategy (which produced irrelevant `.gitignore`/`.npmrc` diffs for every group) by giving the LLM:

- **All release notes** (with rule-based pre-classification)
- **All commits between versions** (with messages and changed file paths)
- **Directory-level code change statistics** (not raw patch dumps)

The LLM then performs **semantic association** between release notes and commits using commit messages as the natural bridge — a task only an LLM can do accurately.

**When the token is missing or invalid, this step is skipped entirely** and only rule-based analysis is performed. The final report clearly states "rule-based only" in the data source field.

**Why commit-message bridge instead of path-matched diffs?**

| Old approach | Commit-message bridge |
|-------------|----------------------|
| Script decides "Plugin group → plugins/ directory files" | LLM reads commit messages and decides association |
| 27 independent prompts, each with 2–5 files | Single comprehensive prompt with all commits + notes |
| All groups received `.gitignore`, `.npmrc` (irrelevant) | Commits scored by relevance; noise files penalized |
| LLM forced to interpret `.gitignore` changes as plugin API evidence | LLM can say "this note has no matching commit" honestly |
| No cross-note cross-validation | LLM sees all notes + all commits, detects shadow changes |

**Token-control strategy:**
- Commits are **scored by relevance** using message keyword patterns (plugin, API, security, breaking, etc.) and file-path signals
- Commits touching only noise files (`.gitignore`, docs, CI configs) are **penalized and deprioritized**
- Top-scored commits (up to 80) are included; total analysis data is capped at ~120K characters
- No external LLM SDK is required by default — the LLM analysis is performed by the invoking AI agent (e.g., Claude Code) using the generated analysis data. Alternatively, the script can be extended with a built-in LLM API client for standalone execution.

**LLM analysis execution strategy:**

- **Single comprehensive analysis (default).** Read the `analysis-data.json` file once, feed it to the LLM in one prompt, collect the structured JSON output. This gives the LLM global context for cross-note validation and shadow-change detection.
- **Automatic chunked analysis (large releases).** When the analysis data exceeds the token threshold (~80K tokens), the script **automatically splits** it into chunks. The analysis processor (AI agent or built-in client) processes each chunk, then the script **automatically merges** results. The processor does NOT decide the split strategy — the script does.
- **Prohibited:** Introducing external LLM SDKs, spawning untracked background processes that outlive the skill invocation, writing intermediate artifacts outside the designated cache directory, requiring user-provided API keys, or manually writing Python scripts to generate fake LLM results.

**Workflow:**

1. **Prepare Analysis Data** — Run the script in data-preparation mode. It fetches release notes, rule-based analyses, commits, and diff statistics, then writes a single master data file:
   ```bash
   cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --prepare-analysis-data --lang zh
   ```
   The script outputs one of two signal patterns:

   **Pattern A — Single chunk (small/medium release):**
   ```
   ANALYSIS_DATA_READY: 1
   DATA: <snapshot-dir>/<repo>-<target>-analysis-data.json
   BASE_ANALYSIS: <path-to-base-analysis.json>
   CHUNKING_REQUIRED: 0
   ESTIMATED_TOKENS: 45000
   ```

   **Pattern B — Multiple chunks (large release, >80K tokens):**
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

   When you see **CHUNKING_REQUIRED: 1**, proceed to Step 2b (chunked analysis). Otherwise, proceed to Step 2a (single analysis).

   The `analysis-data.json` contains three sections:
   - `release_notes`: All notes with IDs, raw text, and `source_version` (the release tag this note originates from, e.g. `v2026.4.12`). When analyzing a version range, `source_version` enables the LLM to identify which intermediate version introduced each change, detect progressive fixes across versions, and reason about upgrade path dependencies.
   - `commits`: Top relevant commits (sha, message, author, changed files, relevance score)
   - `code_changes`: Directory-level stats + top changed files (no raw patches)

2a. **Perform LLM Analysis (single chunk)** — Read the `analysis-data.json` and feed it to the LLM in a single prompt. The prompt instructs the LLM to work in three phases:
   - **Phase 1 — Thematic Clustering**: Group release notes into 8–15 semantic themes by functional intent. Each theme gets: theme name, involved note IDs, overall risk, summary, impact, related commits, affected files, and reasoning.
   - **Phase 2 — Cross-Version Analysis** (when `source_version` spans multiple releases):
     - **Progressive Fix Detection (Optimization #3)**: Identify bug/issue fix chains that span multiple versions — e.g., v1 introduces a temporary mitigation, v2 provides a partial fix, v3 completes the fix. Output each chain with stages (note_id, source_version, fix_description, completeness) and final status.
     - **Cumulative Breaking Change Analysis (Optimization #4)**: Assess whether individual versions appear low-risk but the aggregate impact across the upgrade path is high. Output `individual_risk` vs `cumulative_risk` with a concrete `risk_escalation_reason` explaining why crossing multiple versions at once is more dangerous than upgrading step-by-step.
     - **Version Range Annotation**: Identify which intermediate version introduced each theme and annotate version-range dependencies in theme reasoning.
   - **Phase 3 — Selective Per-Note Enhancement**: Only high-risk notes or notes with direct commit matches receive deep per-note analysis.
   - **Phase 4 — Shadow Change Detection**: Identify commits that modify public surfaces but have no corresponding release note.

   Request structured output (JSON object with top-level fields):


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

   Theme fields:
   - `theme_id`: T-01, T-02, ...
   - `theme_name`: Concise functional theme name (within 15 words), not vague like "Other Changes"
   - `note_ids`: Note IDs belonging to this theme
   - `primary_category`: Main category (breaking/security/plugin/api_sdk/cli/config/dependency/performance/fix/feature/docs/other)
   - `risk_level`: Overall theme risk (high/medium/low)
   - `summary`: What was done (within 50 words)
   - `impact`: What it means for users (within 50 words)
   - `related_commits`: Commit SHAs directly corresponding to this theme (max 3)
   - `affected_files`: Key file paths involved (max 5)
   - `confidence`: high=direct commit evidence; medium=indirect inference; low=speculation
   - `has_hidden_breaking`: Boolean — true **only** if commit evidence reveals a breaking change the notes did **not** disclose
   - `hidden_risks`: String — specific description of hidden risks, or empty `""` if none
   - `reasoning`: Judgment rationale — must quote specific commit message snippets and file paths

   Detailed note fields (only for high-risk or commit-matched notes):
   - `note_id`, `component`, `categories`, `risk_level`, `interpretation`, `action_items`, `audience`, `matched_commits`, `affected_files`, `has_hidden_breaking`, `reasoning`
   - `interpretation` must answer: WHAT changed, WHAT is the impact, WHAT to do about it. NO templates.

   Shadow changes fields:
   - `description`: What undocumented change was found
   - `evidence_commits`: Commit SHAs supporting this finding

2b. **Perform LLM Analysis (chunked — large releases)** — When `CHUNKING_REQUIRED: 1` is signaled, process each chunk in sequence:

   For each chunk file (e.g., `chunk-000.json`, `chunk-001.json`, ...):
   - Read the chunk file
   - Feed it to the LLM with the same four-phase prompt
   - Save the LLM output to the corresponding chunk result file:
     ```
     <snapshot-dir>/<repo>-<target>-llm-results-chunk-000.json
     <snapshot-dir>/<repo>-<target>-llm-results-chunk-001.json
     ...
     ```

   Each chunk result contains only `themes` and `detailed_notes` (plus any `compatibility_risks`/`test_points`/`shadow_changes` found in that chunk). The script's merge step synthesizes the final `executive_summary` and `developer_conclusion`.

   **Do NOT ask the user whether to use chunks.** The script has already decided. Your role is to execute the chunk-by-chunk analysis exactly as the script has split it.

3a. **Write LLM Results (single chunk)** — Save the LLM output to:
   ```
   <snapshot-dir>/<repo>-<target>-llm-results.json
   ```

3b. **Merge Chunk Results (chunked)** — After all chunks are processed, run:
   ```bash
   cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --merge-chunk-results --lang zh
   ```
   The script discovers all `*-llm-results-chunk-*.json` files, merges them by:
   - Unioning `theme.note_ids` per `theme_id`
   - Deduplicating `detailed_notes` by `note_id`
   - Merging `compatibility_risks`, `test_points`, `shadow_changes` (dedup by description)
   - Synthesizing `executive_summary` from merged themes
   - Writing the final result to:
     ```
     <snapshot-dir>/<repo>-<target>-llm-results.json
     ```

4. **Generate Enhanced Report** — Run the script with the LLM results:
   ```bash
   cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --apply-llm-results "<snapshot-dir>/<repo>-<target>-llm-results.json" --lang zh
   ```
   The script reuses the cached snapshot and base analysis from Step 1 — **no repeated GitHub API calls**.

   **Cache cleanup** happens automatically after the final report is generated: step-internal files (`*-analysis-data.json`, `*-base-analysis.json`, `*-analysis-chunk-*.json`) are removed immediately. The script also performs a lazy cleanup on every startup: `*-llm-results.json` files older than 7 days are purged, and only the most recent 20 `*-release-notes.md` snapshots are retained.

**Fallback**: If LLM analysis is unavailable, fails, or `--no-llm` is specified, the script automatically falls back to rule-based analysis. The report structure remains identical regardless of analysis mode.

**Default mode shortcut**: If an `llm-results.json` file already exists in the snapshot directory from a previous run, the default command (`--target ... --compare ...`) automatically detects and applies it without requiring `--apply-llm-results`. Before applying cached LLM results, the script verifies their consistency with the associated snapshot (valid JSON, not older than snapshot). If the consistency check fails, the cached results are discarded and fresh analysis data is prepared.

**LLM-Driven Report Architecture**: In the new architecture, the script is a data pipeline and the LLM performs ALL semantic analysis. The script does not merge LLM results with rule-based templates. Instead, the LLM outputs complete report sections (executive summary, themes, detailed notes, compatibility risks, test points, shadow changes), and the script renders them directly. This eliminates template bias and maximizes analysis depth.

When `--no-llm` is specified or no valid token is available, the script falls back to the legacy rule-based analysis mode (keyword matching + template filling). The report structure is identical in both modes, but the LLM mode produces significantly more accurate and insightful content.

**Version-Size-Aware LLM Skipping**: When a valid token is available, the script may skip LLM analysis for trivial releases (<10 items, zero high-risk signals, no breaking/security/plugin/API/dependency changes) to avoid unnecessary LLM overhead. Use `--no-llm` to forcefully disable LLM even when a valid token is present.

### 5.1 Large-Context Handling Protocol (大上下文处理协议)

This protocol defines the standard behavior when analysis data exceeds LLM context limits. **The script makes all splitting and merging decisions; you only execute.**

**Trigger condition:**
- When `ESTIMATED_TOKENS` exceeds `CHUNKING_THRESHOLD_TOKENS` (80,000), the script automatically enters chunked mode.
- The script outputs `CHUNKING_REQUIRED: 1` and lists all `CHUNK_N` files.

**Core principle: The main AI agent analyzes each chunk serially.**

Do NOT use sub-agents, background agents, or any parallel execution mechanism for chunk analysis. The main agent reads each chunk, analyzes it, writes the result to disk, and proceeds to the next chunk. This approach is:
- **Universal**: Works in any AI environment (Claude Code, Cursor, GitHub Copilot Chat, etc.) that supports file I/O.
- **Reliable**: No data loss from agent-to-agent communication failures.
- **Context-safe**: Each chunk is analyzed independently; results are persisted to disk and do not accumulate in context.

**Analysis workflow (serial execution):**

For each chunk file (`chunk-000.json`, `chunk-001.json`, ...):

1. **Read** the chunk file using the `Read` tool.
2. **Analyze** the chunk data with the LLM using the standard three-phase prompt (thematic clustering, selective per-note enhancement, shadow change detection).
3. **Write** the complete JSON result to the corresponding chunk result file:
   ```
   <snapshot-dir>/<repo>-<target>-llm-results-chunk-000.json
   <snapshot-dir>/<repo>-<target>-llm-results-chunk-001.json
   ...
   ```
4. **Verify** the file was written successfully (non-empty, valid JSON).
5. **Proceed** to the next chunk. Do NOT start multiple chunks simultaneously.

**Result verification checklist:**

After writing each chunk result:
- The file MUST be non-empty.
- The file MUST contain valid JSON parseable by `json.loads()`.
- The JSON MUST contain at least a `themes` array (may be empty if the chunk has no thematically groupable notes).

**JSON safety rule (CRITICAL):**

Before writing a chunk result, ensure all string fields — especially `interpretation`, `reasoning`, `summary`, `impact`, and `hidden_risks` — do NOT contain unescaped double-quote characters (`"` or `"` or `"`). These characters break JSON parsing. Either:
- Use single quotes or angle quotes (`'...'`, `《...》`) when quoting inside string fields, or
- Use `json.dumps()` (via a Python script) to guarantee proper escaping.

**Cache cleanup rule:**

Before starting chunk analysis, check for stale `*-llm-results-chunk-*.json` or `*-llm-results.json` files from previous runs. If the `analysis-data.json` has been refreshed (compare timestamps), **delete old chunk results** to prevent the merge step from mixing stale and fresh data. The script's `--prepare-analysis-data` step does NOT automatically clean old results — you must do this manually or verify freshness.

**Chunk inventory:**

Maintain awareness of the expected chunk count (from `CHUNK_COUNT` in the script output) vs. successfully saved chunk files. Do NOT invoke `--merge-chunk-results` until all expected chunk result files exist.

**Efficiency guidelines:**

To minimize total execution time:
1. **Do NOT re-read chunk files after writing** — the Edit/Write tool's success guarantees the write succeeded.
2. **Reuse theme IDs across chunks** — if a theme (e.g., "Codex app-server") appears in multiple chunks, use the same `theme_id` (e.g., "T-07") in all chunks. The merge step unions `note_ids` per `theme_id`, avoiding duplicate themes.
3. **Skip verbose reasoning for low-risk themes** — for `risk_level: "low"` themes, a 1-sentence `reasoning` is sufficient.
4. **Validate JSON immediately after Write** — run a `json.loads()` check right after writing each chunk (takes 1 second), rather than discovering the error at merge time (costs minutes of re-analysis).
5. **If merge fails due to JSON error**: Fix only the broken chunk file and re-run `--merge-chunk-results`. Do NOT re-analyze any chunk.

**Context safety guarantee:**

- Each chunk analysis is self-contained: the chunk data (~20–40KB JSON) + analysis prompt (~2KB) + output (~10–30KB JSON) fits comfortably within standard context windows.
- After a chunk result is written to disk, it is no longer needed in context. The main agent proceeds to the next chunk with a clean slate.
- The `--merge-chunk-results` step is a **pure Python script operation** (JSON parsing, deduplication, union) that does NOT invoke the LLM and consumes zero LLM context.
- Even with 8 chunks, the total context footprint at any single point remains well under 100KB.

**Prohibited actions (STRICT):**
- Do NOT ask the user "should I split this?" or "how many chunks?" — the script has already decided.
- Do NOT modify the chunk files or write your own splitting logic.
- Do NOT skip chunks or merge them manually.
- Do NOT write Python scripts (like `generate_llm_results.py`) to fabricate analysis results.
- Do NOT modify the JSON field names or data format in chunk results to "make them work."
- Do NOT invent data when a chunk lacks matching commits — report honestly that no match was found.
- Do NOT use sub-agents, background agents, or parallel agent calls for chunk analysis.

**What to do if a problem occurs:**
- **If a chunk analysis fails** (timeout, error, or returns non-JSON):
  1. Retry the same chunk **once** (re-read the chunk file and re-analyze).
  2. If the retry also fails: Report the specific chunk number, the error type, and **stop**. Do NOT proceed with partial chunks.
  3. **Never** fall back to rule-based analysis for a failed chunk silently. If the user explicitly asks to continue with rule-based fallback, document which chunks were lost in the final report.
- **If chunk inventory is incomplete** (saved chunk count < `CHUNK_COUNT`):
  - Do NOT invoke `--merge-chunk-results`. Identify which chunks are missing, retry them, and only proceed when the inventory is complete.
- **If chunk results have conflicting themes** (same `theme_id` but different `theme_name`): The merge step uses the first encountered name; this is acceptable because `theme_id` is the stable key.
- **If `--merge-chunk-results` fails**: Report the error with the specific exception and **stop** — do not attempt manual merging.

**Post-merge Enhancement Protocol:**

After `--merge-chunk-results` completes, the script automatically evaluates the quality of the merged `llm-results.json` and may signal that enhancement is needed.

**Merge output signals:**
- `CHUNK_MERGE_COMPLETE: 1` + `LLM_RESULTS: <path>` → merge succeeded, check for enhancement
- `ENHANCEMENT_NEEDED: 1` + `ENHANCEMENT_PROMPT: <path>` + `NEEDS_FIELDS: <fields>` → merged results need LLM enhancement

**When `ENHANCEMENT_NEEDED: 1` is signaled:**

1. Read the enhancement prompt file (`*-enhancement-prompt.txt`). It contains:
   - Summaries of all merged themes (name, risk, category, note count, summary)
   - High-risk theme details and high-risk detailed note summaries
   - A list of fields that need enhancement (e.g., `executive_summary.theme`, `developer_conclusion`, `compatibility_risks`, `test_points`)

2. Feed the enhancement prompt to the LLM and request a JSON response with only the fields that need enhancement:
   ```json
   {
     "executive_summary": { "recommendation": "...", "theme": "...", "magnitude": "...", "reason": "...", "top_changes": [...], "one_liner": "..." },
     "developer_conclusion": "...",
     "compatibility_risks": [{"component": "...", "description": "..."}],
     "test_points": ["..."]
   }
   ```

3. Read the merged `llm-results.json`, patch the fields that need enhancement with the LLM-generated content, and write it back.

4. Invoke `--apply-llm-results` to regenerate the final report with the enhanced content.

**When `ENHANCEMENT_NEEDED` is NOT signaled:**
- The merged results are considered high-quality. Proceed directly to `--apply-llm-results`.

**Why this approach:**
- The pure-Python merge step is fast and reliable but cannot synthesize nuanced executive summaries.
- The enhancement prompt contains only theme/note summaries (not raw data), so the LLM enhancement is a lightweight single-prompt operation (~5K tokens vs. the full analysis at 80K+ tokens).
- The AI agent decides whether to perform the enhancement based on the script's signal, not by manually inspecting the merged file.

**Analysis focus rule (to reduce per-chunk time without losing accuracy):**

Each chunk does NOT need exhaustive per-note analysis. Theme-level analysis (`summary`, `impact`, `reasoning`) already covers "what changed" and "what it means" for every note in the theme. `detailed_notes` should only add depth for notes that genuinely need it.

**Signal-driven selection** — output `detailed_notes` ONLY for notes meeting ANY of these criteria:
1. `risk_level: "high"` (mandatory)
2. `has_hidden_breaking: true` (mandatory — risk may be underestimated)
3. `primary_category` is `security` or `breaking` (mandatory — safety-critical regardless of declared risk)
4. Has direct `matched_commits` AND the commit message provides meaningful evidence (optional, but adds analytical value)

**What to NEVER skip**: Theme-level analysis must still process ALL notes for clustering and risk assessment. A note that is skipped from `detailed_notes` must still appear in its theme's `note_ids` with an accurate `risk_level` and `has_hidden_breaking` flag.

### 6. Use the Bundled Script for Deterministic Analysis

Use `scripts/analyze_openclaw_release.py` for repeatable release fetching, snapshot writing, snapshot-based classification, per-note interpretation, risk assessment, suggested actions, and bilingual report generation.

Every command refreshes the snapshot first and then analyzes that snapshot.

Example commands:

```bash
# CRITICAL: Always cd into the user's workspace directory first
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" <args>

# Provide GitHub token (required for LLM-enhanced commit analysis)
# Option A: via CLI argument
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh --github-token <token>
# Option B: via environment variable
export GITHUB_TOKEN=<token>
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh

# Default: latest stable release, auto-detect language, report lands in CWD
# When token is valid → auto LLM-enhanced analysis (commit-message-bridge)
# When token is missing → rule-based analysis with warning
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang auto --user-query "帮我分析最新版本"

# With explicit output path (only when user specifies one)
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh --output "path/to/report.md"

# Version comparison with LLM enhancement (automatic when token is valid)
# Step 1: script prepares analysis data and signals ANALYSIS_DATA_READY
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --lang zh
# Step 2: AI agent reads analysis-data.json, calls LLM for comprehensive analysis, writes llm-results.json
# Step 3: apply LLM results and generate final report
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --apply-llm-results "<snapshot-dir>/openclaw-openclaw-v1.3.0-llm-results.json" --lang zh

# Version comparison (rule-based only — forcefully disable LLM even with valid token)
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v1.3.0 --compare v1.2.3 --no-llm --lang zh

# Other modes
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang en
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --from v1.1.0 --to v1.3.0 --lang en
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --include-beta --lang en

# Manual cache cleanup (removes all cached snapshots and intermediate files)
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --clean-cache

```

**Output behavior:**
- If `--output` is **omitted** → report is written to the **current working directory** as `{snapshot_stem}-analysis.md`.
- If `--output <path>` is provided → report is written to the exact specified path.
- The script prints the final report path to stdout after completion.
- **After the analysis completes, you MUST include BOTH the absolute file path of the generated report AND the snapshot cache directory in your response to the user.** Use this format:

```
| 类型 | 路径 |
|------|------|
| 最终报告 | C:\Users\...\v2026.5.18-analysis.md |
| 中间缓存 | %LOCALAPPA DATA%\openclaw-release-analyzer\snapshots\  (或 ~/.cache/openclaw-release-analyzer/snapshots/) |
```


### 7. Apply Priority Rules

### 6.1 Classification Categories

The analyzer now classifies changes into these additional categories:
- **CLI**: CLI commands, flags, options, arguments
- **Config**: Configuration schema, defaults, config files
- **Dependency**: Dependency requirements, peerDependencies, Node.js version
- **Migration**: Breaking changes, upgrade guides, migration notes
- **Docs**: Documentation updates, guides, tutorials
- **Known Issue**: Known limitations, workarounds, deprecations

### 6.2 Chinese Release Notes Support

The analyzer now detects Chinese keywords in release notes, including:
- 新增, 新功能, 修复, 安全, 性能, 破坏性变更
- 插件, 配置, 依赖, 迁移, 文档, 已知问题

### 6.3 Conventional Commit Support

The analyzer now recognizes Conventional Commit prefixes:
- `feat:`, `fix:`, `perf:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`, `chore:`, `revert:`
- **Breaking markers**: `feat!:`, `fix!:`, and any prefix with `!` are automatically classified as `breaking` changes.

Prioritize analysis in this order:

1. Plugin system changes: plugin API, lifecycle hooks, manifest schema, loader, registry, runtime.
2. API/SDK changes: public methods, package exports, TypeScript types, deprecations, migration notes.
3. Security fixes: CVE, vulnerabilities, auth, token, permission, dependency security issues.
4. Performance and stability: crash, hang, deadlock, race, memory leak, startup speed, latency, resource use.
5. General features and bug fixes.

### 6.4 Rule-Based Baseline Analysis Architecture

The rule-based analyzer uses a **two-stage filtering** architecture to balance recall and precision:

**Stage 1 — Keyword Recall (weighted broad match)**
- `classify_text()` scores each release note item against keyword lists for all categories (English and Chinese). This stage prioritizes recall — it may include false positives.
- Keywords are matched with word-boundary protection for English (`\b`); Chinese keywords use direct substring matching.
- **Weighted scoring**: match weights differ by term length and form:
  - **Phrases** (containing spaces or ≥15 characters): weight **3** — e.g., `"breaking change"`, `"remote code execution"`, `"affected version"` carry more signal than isolated words.
  - **Medium-length terms** (6–14 characters): weight **2** — e.g., `"plugin"`, `"config"`, `"sandbox"`.
  - **Short terms** (<6 characters): weight **1** — e.g., `"api"`, `"fix"`, `"cli"`.
  - Chinese terms follow the same principle: ≥3-character terms weight **2**, shorter terms weight **1**.
- **Section context bonus**: when `classify_release()` detects that an item sits under a Markdown heading (e.g., `## Breaking Changes`), the matching section category receives a +5 score bonus in `item_categories()`. This turns heading structure into a strong classification signal even when the item text itself is ambiguous.
- **Threshold filtering**: `item_categories()` drops categories whose total score falls below 2. A single weak short-word match (score 1) is insufficient to survive; it needs at least a medium-term hit (score 2+) or multiple short-word hits.

**Stage 2 — Explicit Signal Validation (strict filter)**
- `item_categories()` applies per-category `has_explicit_xxx_signal()` validators after keyword matching.
- Each validator uses two signals:
  - `negative_tokens`: known false-positive patterns that disqualify the category (e.g., `"token-efficiency"` triggers `security` keywords but is rejected by `has_explicit_security_signal()`).
  - `strong_tokens`: confirmation signals required to accept the category.
- **Semantic pattern matching** for `breaking`: in addition to token lists, `has_explicit_breaking_signal()` uses regex patterns to catch common breaking expressions:
  - `no longer \w+` — e.g., "no longer accepts", "no longer supports"
  - `requires \w+ [\d\.\+]+` — e.g., "requires node 18+"
  - `dropped (support|the|compatibility|for)` — e.g., "dropped support for legacy API"
  - `removed (the )?[\w-]+ (option|flag|command|method|api)` — e.g., "removed the --debug flag"
- Categories requiring explicit validation: `breaking`, `security`, `dependency`, `migration`, `plugin`, `api_sdk`, `cli`, `config`.

**Stage 3 — Internal QA Downgrade**
- `is_internal_qa_item()` detects test-only, fixture, or harness-only changes that lack public-surface signals (e.g., `coverage`, `qa-lab`, `fixture`).
- These items are stripped of high-sensitivity categories (`plugin`, `api_sdk`, `security`, `breaking`, etc.) and downgraded to `docs` to prevent false feature/fix classifications.

**Risk Assessment**
- `risk_level()` derives per-item risk from final categories and item text:
  - `breaking`/`migration`/`dependency` → `high` (with runtime-removal signals) or `medium`.
  - `security` → `high` (with CVE/credential signals) or `medium`.
  - `plugin`/`api_sdk`/`cli`/`config` → `medium` only if breaking/signature/removal/deprecated signals present; otherwise `low` for pure features or fixes.
  - `performance` → `medium` (with crash/deadlock signals) or `low`.

This architecture ensures broad coverage of release note signals while controlling false positives through category-specific guards.

### 7. Identify Public Surface Impact

Treat these as developer-visible public surface changes:

- Public API method names, signatures, parameters, return values.
- CLI commands, flags, behavior, or output format.
- Configuration schema, defaults, or required fields.
- Plugin manifest fields, versions, lifecycle hooks, loader behavior, plugin registry contracts.
- SDK package exports, types, documented usage, examples, or deprecation notices.
- Required runtime versions such as Node.js version requirements.

Do not automatically label these as developer-visible:

- Internal refactors.
- Private variable/function renames.
- Test-only changes.
- Internal algorithm optimizations without documented behavior changes.
- Build-tool changes without runtime or public API effect.

### 8. Generate the Report

Use this report structure consistently:

#### 8.1 Fixed output sections

These sections are part of the standard report layout:

- **Report header**: title, repository, target version, compare version, generation timestamp.
- **Version information**: table with target version, publish date, status, compare version, number of releases analyzed, data source, snapshot file path, and report file path.
- **Included Releases** (only when `scoped releases > 1`): table listing all releases in the analyzed range with version, publish date, and status.
- **Executive Summary** (总体结论 / 执行摘要): upgrade recommendation label, dominant theme, change magnitude (total items with risk breakdown), top 5 most critical changes with appendix links and risk icons, and a one-line judgment tailored to the release profile (prerelease warning, breaking-change caution, security priority, developer-surface updates, or low-risk routine).
- **Developer Conclusion** (面向 Channel / 插件开发者的一句话结论): a one-sentence verdict for plugin/channel developers, with conditional branching based on breaking changes, security density, plugin/API count, or config changes.
- **Thematic Overview** (变更主题概览): semantic clustering of all changes into 8-15 functional themes, sorted by risk. Each theme shows item count, risk level, related commits, and summary.
- **Progressive Fix Detection** (渐进式修复检测): when analyzing a version range, shows fix chains where the same issue was addressed incrementally across releases (e.g., mitigation → partial fix → complete fix). Each chain displays stages with version, fix description, and completeness level, plus final status and impact assessment.
- **Cumulative Breaking Change Analysis** (累积 Breaking Change 分析): when analyzing a version range, highlights cases where individual versions appear low-risk but the aggregate impact across the upgrade path is high. Shows per-version risk vs. cumulative risk, with a concrete explanation of why skipping intermediate versions is more dangerous.
- **High-Risk Theme Details** (高风险主题详解): deep-dive analysis for high and medium risk themes. Each theme expanded with impact description, affected files, related commits, and navigation links to appendix detailed notes. Limited to top 8 risky themes.
- **Code Change Evidence** (代码变更证据链): note-to-commit association table showing which commits correspond to which release notes, with changed files and reasoning.
- **Shadow Changes** (未记录变更提示): commits that modify public surfaces but have no corresponding release note.
- **Compatibility Risks** (兼容性与风险点): high and medium risk items relevant to plugin/channel developers, with contextual risk descriptions (breaking change, security tightening, dependency shifts, config changes).
- **Suggested Test Points** (建议验证的测试点): actionable regression test recommendations derived from detected signals (auth, plugin, CLI, channel, dependency).
- **Ignorable Changes** (可暂时忽略的变更): low-risk, low-relevance items that can be deferred in a second reading.
- **Facts, Inferences, and Uncertainties**: structured transparency section. Facts cover snapshot provenance and version status. Inferences cover classification method, recommendation derivation, dominant theme, and concentrated component signals. Uncertainties cover low-confidence items, missing migration guidance, ambiguous dependency signals, and the lack of local project scanning.
- **References**: links to all analyzed release pages.
- **Original Release Notes (Enhanced Index)**: raw release note items in original order, each annotated with appendix ID, categories, and risk level.
- **Appendix: Complete Per-Release-Note Details**: full interpretation table for every analyzable item. Fields: component, release tag, risk level, confidence, categories, audience, raw text, interpretation, suggested actions, and cross-reference hints to related items.

#### 8.2 Classification dimensions, not standalone sections by default

The following categories are classification dimensions used for per-note tagging, prioritization, risk assessment, and impact interpretation. They are **not** standalone top-level sections in the default report layout:

- CLI
- Config
- Dependency
- Migration
- Docs
- Known Issue

When these signals are detected, surface them through the Executive Summary, Deep Dive, Compatibility Risks, or Appendix sections rather than promising dedicated top-level headings.


## Upgrade Recommendation Labels

| English | Chinese | When to use |
|--------|---------|-------------|
| Recommend Upgrade | 建议升级 | Security fixes, severe bug fixes, crash/deadlock/memory-leak fixes, or important features with low risk. |
| Upgrade with Caution | 谨慎升级 | Breaking changes, dependency/runtime requirement changes, public API changes, CLI changes, or config behavior changes. |
| Defer Upgrade | 暂缓升级 | No meaningful benefit, unclear release data, high risk without matching user need, or unstable prerelease for production. |
| Conditional Upgrade | 仅特定场景建议升级 | Changes mainly benefit plugin developers, SDK users, security-sensitive users, or another specific group. |
| Insufficient Data | 信息不足，建议进一步分析 | Release notes are missing, ambiguous, or insufficient for a reliable conclusion. |

## Scenario-Based Recommendations

Always consider these user groups:

- Plugin developers: focus on hooks, manifests, lifecycle APIs, loader/runtime behavior, registry contracts, compatibility declarations.
- API/SDK users: focus on public APIs, package exports, TypeScript types, deprecations, migration notes.
- Security-sensitive users: focus on CVE/vulnerability/auth/token/permission changes and affected versions.
- Stability-sensitive users: focus on crash, hang, deadlock, memory leak, data loss, performance, and high-load behavior.
- Ordinary users: focus on visible features, common bug fixes, upgrade simplicity, and known risks.

## Project Scanning Rules

Do not inspect local project files unless the user explicitly requests project-aware analysis. When authorized, inspect only relevant files such as `package.json`, lockfiles, `openclaw.config.*`, plugin manifests, and source files likely to import OpenClaw APIs. Avoid `.env`, credentials, secrets, private keys, or unrelated files.

## References

Load `references/analysis-rules.md` when needing detailed classification keywords, report template guidance, or decision rules.
