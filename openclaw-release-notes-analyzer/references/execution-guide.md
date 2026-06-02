# Execution Guide

Use this file for concrete commands, file-writing rules, platform details, and troubleshooting.

## Table of Contents

- [Paths](#paths)
- [Token Handling](#token-handling)
- [Common Commands](#common-commands)
- [LLM Three-Step Flow](#llm-three-step-flow)
- [File-Writing Rules](#file-writing-rules)
- [Windows Notes](#windows-notes)
- [Output Contract](#output-contract)
- [Troubleshooting](#troubleshooting)

## Paths

Determine these before running commands:

- `user-workspace-root`: the user's current project/workspace directory.
- `skill-dir`: the directory containing `scripts/analyze_openclaw_release.py`.
- `snapshot-dir`: the platform cache directory unless explicitly overridden.

Always run analyzer commands from `user-workspace-root`:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" <args>
```

This keeps default reports in the user's workspace, not in the skill directory or snapshot directory.

## Token Handling

Token source order:

1. `--github-token <token>`
2. `GITHUB_TOKEN`
3. none

The script validates the token through GitHub `/rate_limit` before any other API request.

- `TOKEN_STATUS: valid`: continue.
- `TOKEN_STATUS: invalid`, missing token, or `Bad credentials`: stop and ask the user for a valid GitHub token. Do not offer rule-only analysis.

## Common Commands

Latest stable release:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh --github-token <token>
```

Target version:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v2026.5.28 --lang zh --github-token <token>
```

Version comparison:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v2026.5.28 --compare v2026.5.01 --lang zh --github-token <token>
```

Version range:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --from v2026.5.01 --to v2026.5.28 --lang zh --github-token <token>
```

Include prerelease preview:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --include-beta --lang zh --github-token <token>
```

Explicit report path:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --latest --lang zh --output "<path-to-report.md>" --github-token <token>
```

Manual cache cleanup:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --clean-cache
```

## LLM Three-Step Flow

Prepare data:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v2026.5.28 --prepare-analysis-data --github-token <token>
```

Expected output signals:

```text
ANALYSIS_DATA_READY: 1
DATA_VERIFIED: 1
CHUNKING_REQUIRED: 0
CHUNK_0: <snapshot-dir>/<repo>-<target>-analysis-chunk-000.json
LLM_RESULTS_TARGET: <snapshot-dir>/<repo>-<target>-llm-results.json
FALLBACK_LLM_RESULTS_TARGET: <temp-dir>/openclaw-release-notes-analyzer-llm-results.json
```

You must see `DATA_VERIFIED: 1` before proceeding. If it is missing, the files may not have been written correctly; stop and investigate.

Write LLM result to the emitted `LLM_RESULTS_TARGET`. After writing, verify the file exists and is non-empty before proceeding.

Apply LLM result:

```bash
cd "<user-workspace-root>" && python "<skill-dir>/scripts/analyze_openclaw_release.py" --target v2026.5.28 --apply-llm-results --github-token <token>
```

If the user specified output, append `--output "<path>"` to the apply step.

## File-Writing Rules

Preferred LLM result location:

- Write to the exact path printed as `LLM_RESULTS_TARGET`.
- This path should normally be in `%LOCALAPPDATA%\openclaw-release-notes-analyzer\snapshots` or `~/.cache/openclaw-release-notes-analyzer/snapshots`.

Fallback:

- If writing to `LLM_RESULTS_TARGET` fails, write to `FALLBACK_LLM_RESULTS_TARGET` (system temp directory).
- The script's auto-discovery checks the temp directory fallback automatically.
- Do not write LLM results to `user-workspace-root`; it pollutes the user's project directory.

Forbidden:

- Do not write intermediate files inside the skill installation directory.
- Do not pass large JSON via `python -c`; command-line length limits can cause `ENAMETOOLONG`.
- Do not use Node.js or unrelated tools to write LLM result files.
- Do not handcraft fake LLM results to bypass analysis.

## Windows Notes

| Situation | Correct handling |
|---|---|
| Paths contain spaces | Wrap paths in double quotes. |
| Backslashes may be escaped | Prefer `/` in command arguments, or double backslashes in literal strings. |
| `%LOCALAPPDATA%` in Bash | Use `$LOCALAPPDATA` in Git Bash/Cygwin, or write the full path. |
| Write tool unreliable on deep paths | On Windows, writing to `%LOCALAPPDATA%` via some tools may silently fail. Write to a shallow temp path first, then Bash `cp` to the target. |
| Write to cache path fails | Write to `FALLBACK_LLM_RESULTS_TARGET` (system temp dir) instead, or use Bash `cp` from a temp file. |

## Output Contract

After analysis, tell the user:

```markdown
| 类型 | 路径 |
|------|------|
| 最终报告 | <absolute-report-path> |
| 中间缓存 | <snapshot-cache-dir> |
```

Also mention if:

- token validation failed,
- LLM chunking was required,
- a fallback LLM result path was used,
- report generation failed or no report was produced.

## Troubleshooting

| Symptom | Likely cause | Recovery |
|---|---|---|
| `Bad credentials` or `TOKEN_STATUS: invalid` | Token is missing, invalid, or expired | Stop and ask for a valid GitHub token. |
| `ANALYSIS_DATA_READY: 1` present but `DATA_VERIFIED: 1` missing | File write failed silently (common on Windows with deep paths like `%LOCALAPPDATA%`) | Re-run `--prepare-analysis-data`; if it persists, write LLM results to `FALLBACK_LLM_RESULTS_TARGET` and rerun `--apply-llm-results`. |
| Prepare output paths printed but files do not exist | Same as above — script printed target paths before write completed | Verify file existence with `ls` or `test -f` before continuing. Do not trust stdout paths alone. |
| `LLM results file not found` | Result was not written, written to the wrong path, or deleted by cleanup before apply | Check `LLM_RESULTS_TARGET`; if uncertain, write to `FALLBACK_LLM_RESULTS_TARGET` and rerun `--apply-llm-results`. |
| `ENAMETOOLONG` | Large JSON was embedded in a command | Stop using command-line JSON. Write JSON to a file. |
| `CHUNKING_REQUIRED: 1` | Data exceeds single-chunk threshold | Follow `references/llm-workflow.md`; process all chunks and run the merge command. |
| Report appears in wrong directory | Script was run from the skill directory or snapshot directory | Rerun from `user-workspace-root`; avoid `--output` unless user requested a path. |
| Snapshot cache looks stale | Consistency validation should refresh automatically | Rerun normally; use `--clean-cache` only when manual cleanup is requested or clearly helpful. |
