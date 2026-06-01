#!/usr/bin/env python3
"""Analyze OpenClaw GitHub releases and emit a bilingual Markdown upgrade report."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from config import (
    API_ROOT,
    CONVENTIONAL_COMMIT_RE,
    DEFAULT_REPO,
    FILE_IMPORTANCE_PATTERNS,
    KEYWORDS,
    MAX_DIFF_FILES,
    MAX_PATCH_LINES_PER_FILE,
    MAX_TOTAL_DIFF_CHARS,
    SECTION_HINTS,
    ZH_KEYWORDS,
    SEMANTIC_DEDUP_STOP_WORDS,
    SEMANTIC_DEDUP_MIN_WORDS,
    SEMANTIC_DEDUP_THRESHOLD,
    default_cache_dir,
    LLM_RESULTS_TTL_DAYS,
    RELEASE_NOTES_MAX_VERSIONS,
    RECURSIVE_MERGE_MAX_TOKENS_PER_LEAF,
    RECURSIVE_MERGE_MAX_VERSIONS_PER_LEAF,
    RECURSIVE_MERGE_MAX_DEPTH,
    RECURSIVE_MERGE_MIN_VERSIONS,
)
from i18n import T, _zh
from models import ChangeAnalysis, CommitInfo, Release, Theme, LLMFullReport, normalize_version, version_key
from prompts import (
    analysis_data_path,
    base_analysis_path,
    build_analysis_data,
    build_merge_prompt,
    compress_for_merge,
    confidence_for,
    discover_chunk_results,
    llm_results_path,
    merge_chunk_results,
    parse_llm_results,
    parse_merge_results,
    read_base_analysis,
    select_relevant_commits,
    split_analysis_data_into_chunks,
    should_use_chunking,
    chunk_result_path,
    write_analysis_data,
    write_base_analysis,
)
from renderer import (
    first_sentences,
    newer_prereleases,
    parse_date,
    recommendation,
    render_report,
    stable_releases,
)


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def request_json(url: str, token: Optional[str] = None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "openclaw-release-analyzer-skill",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API request failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API request failed: {exc.reason}") from exc


def get_github_token(args_token: Optional[str]) -> Optional[str]:
    """Get GitHub token from CLI args or GITHUB_TOKEN environment variable."""
    if args_token:
        return args_token
    return os.environ.get("GITHUB_TOKEN")


def verify_github_token(token: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Verify GitHub token validity by calling /rate_limit endpoint.

    Returns (is_valid, error_message_or_none).
    """
    if not token:
        return False, "No GitHub token provided"
    url = f"{API_ROOT}/rate_limit"
    try:
        request_json(url, token)
        return True, None
    except RuntimeError as exc:
        return False, str(exc)


def fetch_releases(repo: str, token: Optional[str]) -> List[Release]:
    url = f"{API_ROOT}/repos/{repo}/releases?per_page=100"
    payload = request_json(url, token)
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected GitHub releases response")
    releases = []
    for item in payload:
        releases.append(
            Release(
                tag_name=item.get("tag_name") or "",
                name=item.get("name") or item.get("tag_name") or "",
                body=item.get("body") or "",
                html_url=item.get("html_url") or "",
                published_at=item.get("published_at") or "",
                prerelease=bool(item.get("prerelease")),
                draft=bool(item.get("draft")),
            )
        )
    return releases


def find_release(releases: Sequence[Release], version: str) -> Optional[Release]:
    wanted = normalize_version(version).lower()
    for release in releases:
        candidates = {normalize_version(release.tag_name).lower(), release.tag_name.lower(), release.name.lower()}
        if wanted in candidates or f"v{wanted}" in candidates:
            return release
    return None

def snapshot_path(snapshot_dir: Path, repo: str, target: Optional[str]) -> Path:
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target or "latest-stable").strip("-") or "latest-stable"
    return snapshot_dir / f"{repo_part}-{target_part}-release-notes.md"


def encode_release_payload(releases: Sequence[Release]) -> str:
    payload = [
        {
            "tag_name": release.tag_name,
            "name": release.name,
            "body": release.body,
            "html_url": release.html_url,
            "published_at": release.published_at,
            "prerelease": release.prerelease,
            "draft": release.draft,
        }
        for release in releases
    ]
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def decode_release_payload(encoded: str) -> List[Release]:
    payload = json.loads(base64.b64decode(encoded.encode("ascii")).decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("Invalid snapshot release payload")
    releases: List[Release] = []
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeError("Invalid snapshot release item")
        releases.append(
            Release(
                tag_name=item.get("tag_name") or "",
                name=item.get("name") or item.get("tag_name") or "",
                body=item.get("body") or "",
                html_url=item.get("html_url") or "",
                published_at=item.get("published_at") or "",
                prerelease=bool(item.get("prerelease")),
                draft=bool(item.get("draft")),
            )
        )
    return releases


def write_release_snapshot(
    path: Path,
    repo: str,
    target: Release,
    compare: Optional[Release],
    scoped: Sequence[Release],
    releases: Sequence[Release],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()
    scoped_tags = ", ".join(release.tag_name for release in scoped)
    frontmatter = [
        "---",
        f"repo: {repo}",
        f"target_version: {target.tag_name}",
        f"compare_version: {compare.tag_name if compare else ''}",
        f"source_url: {target.html_url}",
        "data_source: GitHub Releases API",
        f"fetched_at: {fetched_at}",
        f"release_published_at: {target.published_at}",
        f"release_name: {target.name}",
        f"scoped_releases: {scoped_tags}",
        f"release_payload_base64: {encode_release_payload(releases)}",
        "---",
        "",
    ]
    body_parts: List[str] = []
    for release in scoped:
        body_parts.extend([
            f"# {release.tag_name}",
            "",
            f"Release URL: {release.html_url}",
            f"Published at: {release.published_at}",
            "",
            release.body.strip() or "(No release notes provided.)",
            "",
        ])
    path.write_text("\n".join(frontmatter + body_parts), encoding="utf-8")


def read_release_snapshot(path: Path) -> List[Release]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^release_payload_base64:\s*(\S+)\s*$", text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Snapshot is missing release payload: {path}")
    return decode_release_payload(match.group(1))


# ---------------------------------------------------------------------------
# Cache consistency verification
# ---------------------------------------------------------------------------

@dataclass
class ConsistencyReport:
    """Result of a cache consistency verification check."""

    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _extract_frontmatter(path: Path) -> Dict[str, str]:
    """Extract frontmatter key-value pairs from a snapshot file."""
    text = path.read_text(encoding="utf-8")
    fm_match = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL | re.MULTILINE)
    if not fm_match:
        return {}
    result: Dict[str, str] = {}
    for line in fm_match.group(1).splitlines():
        # Match key: value format (skip list items and nested structures)
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$", line)
        if m:
            result[m.group(1)] = m.group(2).strip()
    return result


def verify_snapshot_structure(path: Path) -> ConsistencyReport:
    """Check snapshot file structure integrity.

    Verifies:
    - File exists and is non-empty
    - Frontmatter contains all required fields
    - Body contains headings for each scoped release
    """
    report = ConsistencyReport()

    if not path.exists():
        report.is_valid = False
        report.errors.append(f"Snapshot file does not exist: {path}")
        return report

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        report.is_valid = False
        report.errors.append(f"Cannot read snapshot file: {exc}")
        return report

    if not text.strip():
        report.is_valid = False
        report.errors.append("Snapshot file is empty")
        return report

    # Check frontmatter presence
    if not text.startswith("---"):
        report.is_valid = False
        report.errors.append("Missing frontmatter delimiter")
        return report

    fm = _extract_frontmatter(path)
    required_fields = [
        "repo", "target_version", "source_url",
        "fetched_at", "release_published_at", "scoped_releases",
        "release_payload_base64",
    ]
    missing = [f for f in required_fields if f not in fm]
    if missing:
        report.is_valid = False
        report.errors.append(f"Missing required frontmatter fields: {', '.join(missing)}")

    # Check that scoped_releases are present in body headings
    scoped_tags_str = fm.get("scoped_releases", "")
    scoped_tags = [t.strip() for t in scoped_tags_str.split(",") if t.strip()]
    for tag in scoped_tags:
        if f"# {tag}" not in text:
            report.is_valid = False
            report.errors.append(f"Missing body section for scoped release: {tag}")

    # Warn if snapshot is very old (> 7 days)
    fetched_at = fm.get("fetched_at", "")
    if fetched_at:
        try:
            fetched_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - fetched_dt).total_seconds() / 86400
            if age_days > 7:
                report.warnings.append(f"Snapshot is {age_days:.1f} days old")
        except ValueError:
            report.warnings.append(f"Cannot parse fetched_at timestamp: {fetched_at}")

    return report


def verify_snapshot_payload(path: Path) -> ConsistencyReport:
    """Check that the base64 payload is consistent with frontmatter metadata.

    Verifies:
    - Payload is decodable
    - Payload contains releases for all scoped tags
    - Payload contains the target version
    """
    report = ConsistencyReport()
    fm = _extract_frontmatter(path)

    target_version = fm.get("target_version", "")
    scoped_tags_str = fm.get("scoped_releases", "")
    scoped_tags = [t.strip() for t in scoped_tags_str.split(",") if t.strip()]

    try:
        releases = read_release_snapshot(path)
    except Exception as exc:
        report.is_valid = False
        report.errors.append(f"Cannot decode release payload: {exc}")
        return report

    if not releases:
        report.is_valid = False
        report.errors.append("Decoded payload contains no releases")
        return report

    payload_tags = {r.tag_name for r in releases}

    # Verify all scoped tags exist in payload
    for tag in scoped_tags:
        if tag not in payload_tags:
            report.is_valid = False
            report.errors.append(f"Scoped release '{tag}' not found in payload")

    # Verify target version exists in payload
    if target_version and target_version not in payload_tags:
        report.is_valid = False
        report.errors.append(f"Target version '{target_version}' not found in payload")

    # Sanity check: payload should have reasonable number of releases
    if len(releases) < len(scoped_tags):
        report.is_valid = False
        report.errors.append(
            f"Payload has fewer releases ({len(releases)}) than scoped tags ({len(scoped_tags)})"
        )

    return report


def verify_snapshot_freshness(
    snapshot_releases: List[Release],
    fresh_releases: List[Release],
    target_tag: str,
    is_latest_mode: bool,
) -> ConsistencyReport:
    """Check if cached snapshot is still fresh compared to live GitHub data.

    Verifies:
    - For --latest mode: cached target is still the latest stable release
    - Target version still exists on GitHub
    - Target published_at hasn't changed
    """
    report = ConsistencyReport()

    if not fresh_releases:
        report.warnings.append("Cannot verify freshness: no live data available")
        return report

    # Find the target in both datasets
    snap_target = find_release(snapshot_releases, target_tag)
    fresh_target = find_release(fresh_releases, target_tag)

    if not snap_target:
        report.is_valid = False
        report.errors.append(f"Target version '{target_tag}' not found in snapshot")
        return report

    if not fresh_target:
        report.is_valid = False
        report.errors.append(
            f"Target version '{target_tag}' no longer exists on GitHub; snapshot is stale"
        )
        return report

    # Check published_at hasn't changed (indicates release was edited/republished)
    if snap_target.published_at != fresh_target.published_at:
        report.is_valid = False
        report.errors.append(
            f"Release {target_tag} published_at changed: "
            f"snapshot={snap_target.published_at}, live={fresh_target.published_at}"
        )

    # For latest mode: check if target is still the latest stable
    if is_latest_mode:
        fresh_stable = stable_releases(fresh_releases)
        if fresh_stable:
            latest_stable = fresh_stable[0]
            if latest_stable.tag_name != target_tag:
                report.is_valid = False
                report.errors.append(
                    f"Newer stable release available: {latest_stable.tag_name} "
                    f"(cached: {target_tag})"
                )

    return report


def verify_llm_results_consistency(
    results_path: Path,
    snapshot_path: Path,
) -> ConsistencyReport:
    """Check that LLM results are consistent with the associated snapshot.

    Verifies:
    - Results file exists and is valid JSON
    - Results reference versions that exist in the snapshot
    - Results file is not older than the snapshot
    """
    report = ConsistencyReport()

    if not results_path.exists():
        report.is_valid = False
        report.errors.append(f"LLM results file does not exist: {results_path}")
        return report

    try:
        results_text = results_path.read_text(encoding="utf-8")
        results = json.loads(results_text)
    except json.JSONDecodeError as exc:
        report.is_valid = False
        report.errors.append(f"LLM results file is not valid JSON: {exc}")
        return report
    except Exception as exc:
        report.is_valid = False
        report.errors.append(f"Cannot read LLM results file: {exc}")
        return report

    # Try to extract version references from results
    # The LLM results should contain release_tag references in detailed_notes
    detailed_notes = results.get("detailed_notes", [])
    result_tags: set[str] = set()
    for note in detailed_notes:
        tag = note.get("release_tag", "") if isinstance(note, dict) else ""
        if tag:
            result_tags.add(tag)

    # If no tags found, results might be from a different format — just warn
    if not result_tags:
        report.warnings.append("No version tags found in LLM results; cannot verify version alignment")

    # Check that results are newer than snapshot (results should be generated after snapshot)
    if snapshot_path.exists() and results_path.exists():
        try:
            snap_mtime = snapshot_path.stat().st_mtime
            results_mtime = results_path.stat().st_mtime
            if results_mtime < snap_mtime:
                report.is_valid = False
                report.errors.append(
                    f"LLM results ({results_path.name}) are older than snapshot "
                    f"({snapshot_path.name}); results may be stale"
                )
        except OSError:
            pass

    return report


def run_full_consistency_check(
    snapshot_path: Path,
    args: argparse.Namespace,
    fresh_releases: Optional[List[Release]] = None,
    llm_results_path: Optional[Path] = None,
) -> ConsistencyReport:
    """Run all consistency checks and return a consolidated report.

    Execution order: structure → payload → freshness → llm_results.
    Early failures do not skip later checks; all errors are collected.
    """
    report = ConsistencyReport()

    # 1. Structure check
    struct_report = verify_snapshot_structure(snapshot_path)
    report.errors.extend(struct_report.errors)
    report.warnings.extend(struct_report.warnings)
    if not struct_report.is_valid:
        report.is_valid = False

    # 2. Payload check (only if structure is valid enough to parse)
    if struct_report.is_valid or not any("does not exist" in e for e in struct_report.errors):
        payload_report = verify_snapshot_payload(snapshot_path)
        report.errors.extend(payload_report.errors)
        report.warnings.extend(payload_report.warnings)
        if not payload_report.is_valid:
            report.is_valid = False

    # 3. Freshness check (requires live data)
    is_latest_mode = not args.target and not args.from_version and not args.to_version
    if fresh_releases and snapshot_path.exists():
        try:
            snapshot_releases = read_release_snapshot(snapshot_path)
            target_tag = args.target
            if not target_tag and snapshot_releases:
                # Infer target from snapshot frontmatter
                fm = _extract_frontmatter(snapshot_path)
                target_tag = fm.get("target_version", "")
            if target_tag:
                freshness_report = verify_snapshot_freshness(
                    snapshot_releases, fresh_releases, target_tag, is_latest_mode
                )
                report.errors.extend(freshness_report.errors)
                report.warnings.extend(freshness_report.warnings)
                if not freshness_report.is_valid:
                    report.is_valid = False
        except Exception as exc:
            report.warnings.append(f"Could not verify freshness: {exc}")

    # 4. LLM results consistency check
    if llm_results_path:
        llm_report = verify_llm_results_consistency(llm_results_path, snapshot_path)
        report.errors.extend(llm_report.errors)
        report.warnings.extend(llm_report.warnings)
        if not llm_report.is_valid:
            report.is_valid = False

    return report


def refresh_snapshot_and_load(args: argparse.Namespace) -> Tuple[Release, Optional[Release], List[Release], List[Release], Path]:
    fresh_releases = fetch_releases(args.repo, args.github_token)
    if not fresh_releases:
        raise RuntimeError("No releases returned by GitHub")
    target, compare, scoped = select_scope(args, fresh_releases)
    path = snapshot_path(Path(args.snapshot_dir), args.repo, target.tag_name)
    write_release_snapshot(path, args.repo, target, compare, scoped, fresh_releases)
    snapshot_releases = read_release_snapshot(path)
    snapshot_target, snapshot_compare, snapshot_scoped = select_scope(args, snapshot_releases)
    return snapshot_target, snapshot_compare, snapshot_scoped, snapshot_releases, path


def select_scope(args: argparse.Namespace, releases: Sequence[Release]) -> Tuple[Release, Optional[Release], List[Release]]:
    stable = stable_releases(releases)
    if not stable:
        raise RuntimeError("No stable releases found")

    target = find_release(releases, args.target) if args.target else stable[0]
    if not target:
        # P1-1: List available recent versions when target is not found
        available = [r.tag_name for r in releases[:20]]
        available_str = ", ".join(f"`{t}`" for t in available) if available else "(none)"
        raise RuntimeError(
            f"Target release not found: {args.target}\n"
            f"Available recent releases: {available_str}"
        )

    compare = find_release(releases, args.compare) if args.compare else None

    # P0-2: When both --target and --compare are explicitly provided,
    # analyze the range between them (not just the target alone)
    if args.target and args.compare and compare:
        scoped = releases_between(releases, compare, target)
        return target, compare, scoped

    if args.from_version or args.to_version:
        start = find_release(releases, args.from_version) if args.from_version else stable[-1]
        end = find_release(releases, args.to_version) if args.to_version else target
        if not start or not end:
            # P1-1: List available recent versions when range release is not found
            missing = args.from_version if not start else args.to_version
            available = [r.tag_name for r in releases[:20]]
            available_str = ", ".join(f"`{t}`" for t in available) if available else "(none)"
            raise RuntimeError(
                f"Range release not found: {missing}\n"
                f"Available recent releases: {available_str}"
            )
        scoped = releases_between(releases, start, end)
        return end, start, scoped

    if not compare:
        stables = stable_releases(releases)
        stable_tags = [r.tag_name for r in stables]
        if target.tag_name in stable_tags:
            idx = stable_tags.index(target.tag_name)
            compare = stables[idx + 1] if idx + 1 < len(stables) else None
        else:
            compare = stables[0] if stables else None
    return target, compare, [target]


def releases_between(releases: Sequence[Release], start: Release, end: Release) -> List[Release]:
    ordered = sorted([r for r in releases if r.is_stable], key=lambda r: version_key(r.tag_name))
    start_key = version_key(start.tag_name)
    end_key = version_key(end.tag_name)
    low, high = sorted([start_key, end_key])
    selected = [r for r in ordered if low <= version_key(r.tag_name) <= high]
    return list(reversed(selected))


def classify_text(text: str) -> Dict[str, int]:
    """Score text against keyword lists with weighted matching.

    Weight rules:
    - Phrases (containing space or >=15 chars): weight 3
    - Medium-length terms (6-14 chars): weight 2
    - Short terms (<6 chars): weight 1
    Chinese keywords:
    - Long terms (>=3 chars): weight 2
    - Short terms (1-2 chars): weight 1
    """
    lowered = text.lower()
    result: Dict[str, int] = {}
    for category, words in KEYWORDS.items():
        score = 0
        for w in words:
            if " " in w or len(w) >= 15:
                matches = len(re.findall(r"\b" + re.escape(w) + r"\b", lowered))
                score += matches * 3
            elif len(w) >= 6:
                matches = len(re.findall(r"\b" + re.escape(w) + r"\b", lowered))
                score += matches * 2
            else:
                matches = len(re.findall(r"\b" + re.escape(w) + r"\b", lowered))
                score += matches * 1
        if score:
            result[category] = result.get(category, 0) + score
    # P1-3: Also check Chinese keywords for Chinese release notes
    for category, words in ZH_KEYWORDS.items():
        score = 0
        for w in words:
            if len(w) >= 3:
                matches = len(re.findall(w, lowered))
                score += matches * 2
            else:
                matches = len(re.findall(w, lowered))
                score += matches * 1
        if score:
            result[category] = result.get(category, 0) + score
    return result


def current_section(line: str) -> Optional[str]:
    match = re.match(r"^#{1,6}\s+(.+)$", line.strip())
    if not match:
        return None
    title = re.sub(r"[^a-z0-9\s/-]", " ", match.group(1).lower())
    for category, hints in SECTION_HINTS.items():
        if any(hint in title for hint in hints):
            return category
    return None


def classify_release(release: Release) -> Dict[str, List[str]]:
    categories = {key: [] for key in [
        "feature", "fix", "breaking", "security", "performance",
        "plugin", "api_sdk", "cli", "config", "dependency", "migration",
        "docs", "known_issue", "other"
    ]}
    section: Optional[str] = None
    lines = release.body.splitlines()
    skip_section = False

    for line in lines:
        # P1-3: Try to detect section from Markdown headings (including emoji headings)
        inferred = current_section(line)
        if inferred:
            section = inferred
            skip_section = False
            continue

        # Skip metadata sections (Release verification, artifacts, etc.)
        if _is_skip_section_heading(line):
            skip_section = True
            continue
        if skip_section:
            continue

        stripped = line.strip()
        if not stripped:
            continue

        # P1-3: Check if this is a conventional commit line
        commit_match = CONVENTIONAL_COMMIT_RE.match(stripped)
        if commit_match:
            prefix = commit_match.group(1).lower()
            content = commit_match.group(4).strip()
            is_breaking_prefix = commit_match.group(3) is not None
            # Map conventional commit prefix to category
            prefix_map = {
                "feat": "feature",
                "fix": "fix",
                "perf": "performance",
                "docs": "docs",
                "refactor": "other",
                "test": "other",
                "build": "dependency",
                "ci": "other",
                "chore": "other",
                "revert": "other",
            }
            cat = prefix_map.get(prefix, "other")
            if content not in categories[cat]:
                categories[cat].append(content)
            # Conventional Commit '!' marker (feat!, fix!, etc.) signals breaking change
            if is_breaking_prefix and content not in categories["breaking"]:
                categories["breaking"].append(content)
            # Also check keywords in content
            scores = classify_text(content)
            for key in ["breaking", "security", "plugin", "api_sdk", "cli", "config", "migration"]:
                if scores.get(key) and content not in categories[key]:
                    categories[key].append(content)
            continue

        # P1-3: Handle bullet points and numbered lists
        if not re.match(r"^([-*+] |\d+[.)]\s+)", stripped):
            # P1-3: Check for BREAKING CHANGE: paragraph
            if "BREAKING CHANGE:" in stripped.upper() or "破坏性变更" in stripped:
                if stripped not in categories["breaking"]:
                    categories["breaking"].append(stripped)
            continue

        item = re.sub(r"^([-*+] |\d+[.)]\s+)", "", stripped).strip()
        if not item:
            continue
        resolved_categories = item_categories(item, section)
        assigned = False
        if section and section in categories:
            categories[section].append(item)
            assigned = True
        for key in resolved_categories:
            if key in categories and item not in categories[key]:
                categories[key].append(item)
                assigned = True
        if not assigned:
            categories["other"].append(item)

    if not any(categories.values()) and release.body.strip():
        summary = first_sentences(release.body.strip(), 5)
        if summary:
            categories["other"].extend(summary)
    return categories


# Sections that contain metadata (URLs, verification links, etc.) rather than
# actual changelog entries. Items under these sections are skipped.
_SKIP_SECTION_HEADINGS = frozenset({
    "release verification", "verification", "verify", "checksums",
    "signatures", "artifacts", "downloads", "links", "metadata",
    "release notes source", "references", "credits", "acknowledgments",
})


def _is_skip_section_heading(line: str) -> bool:
    """Return True if the line is a Markdown heading for a metadata section."""
    m = re.match(r"^#{1,3}\s*(.+)$", line.strip())
    if not m:
        return False
    heading = m.group(1).lower().strip()
    # Strip trailing colon or punctuation
    heading = re.sub(r"[:：]\s*$", "", heading)
    return heading in _SKIP_SECTION_HEADINGS


def release_note_items(release: Release) -> List[str]:
    items: List[str] = []
    lines = release.body.splitlines()
    skip_section = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detect section headings; skip items under metadata sections
        if _is_skip_section_heading(stripped):
            skip_section = True
            continue
        # Any heading resets skip (except sub-headings within skip sections)
        if re.match(r"^#{1,3}\s+", stripped):
            skip_section = False
            continue
        if skip_section:
            continue

        commit_match = CONVENTIONAL_COMMIT_RE.match(stripped)
        if commit_match:
            item = commit_match.group(4).strip()
        elif re.match(r"^([-*+] |\d+[.)]\s+)", stripped):
            item = re.sub(r"^([-*+] |\d+[.)]\s+)", "", stripped).strip()
        elif "BREAKING CHANGE:" in stripped.upper() or "破坏性变更" in stripped:
            item = stripped
        else:
            continue
        item = normalize_item_text(item)
        if item and item not in items:
            items.append(item)
    if not items and release.body.strip():
        items.extend(first_sentences(release.body.strip(), 5))
    return items


def normalize_item_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+by\s+@[-\w]+\.?$", ".", text, flags=re.IGNORECASE)
    return text


# ---------------------------------------------------------------------------
# Semantic deduplication for cross-version analysis
# ---------------------------------------------------------------------------

# Pre-compile regexes for performance
_COMMIT_SHA_PREFIX_RE = re.compile(r'^[a-f0-9]{7,}\s*[:,-]\s*')
_AUTHOR_REF_RE = re.compile(r'\s+by\s+@[-\w]+', re.IGNORECASE)
_AT_MENTION_RE = re.compile(r'@\w+')
_URL_RE = re.compile(r'https?://\S+')
_PUNCT_RE = re.compile(r'[^\w\s]')
_WHITESPACE_RE = re.compile(r'\s+')


# Common abbreviations mapped to canonical forms for normalization.
# This prevents the same concept expressed as abbreviation vs full form
# from producing different signatures (e.g. "compat" vs "compatibility").
_ABBREV_MAP: dict[str, str] = {
    "compat": "compatibility",
    "perf": "performance",
    "auth": "authentication",
    "authn": "authentication",
    "authz": "authorization",
    "config": "configuration",
    "dep": "dependency",
    "deps": "dependencies",
    "ref": "reference",
    "refs": "references",
    "init": "initialize",
    "err": "error",
    "msg": "message",
    "param": "parameter",
    "params": "parameters",
    "func": "function",
    "fn": "function",
    "prop": "property",
    "props": "properties",
    "ctx": "context",
    "str": "string",
    "num": "number",
    "bool": "boolean",
    "obj": "object",
    "arr": "array",
    "pkg": "package",
    "lib": "library",
    "mod": "module",
    "util": "utility",
    "utils": "utilities",
    "dir": "directory",
    "dirs": "directories",
    "env": "environment",
    "tmp": "temporary",
    "temp": "temporary",
    "opts": "options",
    "args": "arguments",
    "cli": "command_line_interface",
}


def semantic_dedup_key(text: str) -> str:
    """Generate a normalized semantic signature for cross-version deduplication.

    The signature is built by:
    1. Removing commit-SHA prefixes, author references, URLs, and punctuation.
    2. Lowercasing and splitting into words.
    3. Expanding abbreviations to canonical forms.
    4. Removing stop words.
    5. Keeping words >= 3 chars OR pure numeric tokens (version numbers).
    6. Sorting the remaining words alphabetically and joining with spaces.

    Two release-note items with the same signature are considered semantically
    identical, even if their raw text differs slightly (e.g. due to different
    commit-SHA prefixes, author mentions, or minor wording variations).
    """
    # Remove commit SHA prefix (e.g. "abc1234: fix memory leak")
    text = _COMMIT_SHA_PREFIX_RE.sub('', text)
    # Remove author references
    text = _AUTHOR_REF_RE.sub('', text)
    text = _AT_MENTION_RE.sub('', text)
    # Remove URLs
    text = _URL_RE.sub('', text)
    # Lowercase
    text = text.lower()
    # Remove punctuation, keep only words, spaces, and digits
    text = _PUNCT_RE.sub(' ', text)
    # Normalize whitespace
    text = _WHITESPACE_RE.sub(' ', text).strip()
    # Build word list: keep words >= 3 chars, pure numbers, and abbreviations
    words: list[str] = []
    for w in text.split():
        # Expand known abbreviations
        if w in _ABBREV_MAP:
            w = _ABBREV_MAP[w]
        # Keep if: not a stop word AND (>= 3 chars OR pure numeric)
        if w not in SEMANTIC_DEDUP_STOP_WORDS and (len(w) >= 3 or w.isdigit()):
            words.append(w)
    # Sort to ensure consistent signatures regardless of word order
    return ' '.join(sorted(words))


def items_are_semantically_similar(a: str, b: str, threshold: float = SEMANTIC_DEDUP_THRESHOLD) -> bool:
    """Return True if two release-note items are semantically similar.

    Uses Jaccard similarity on word sets derived from semantic signatures.
    This is more robust than character-level SequenceMatcher for short
    release-note texts where the same change may be described with slightly
    different wording across versions (e.g. cherry-picks with edited
    commit messages, different prefixes, or added author mentions).
    """
    words_a = set(semantic_dedup_key(a).split())
    words_b = set(semantic_dedup_key(b).split())
    # Short signatures are too generic; require minimum word count
    if len(words_a) < SEMANTIC_DEDUP_MIN_WORDS or len(words_b) < SEMANTIC_DEDUP_MIN_WORDS:
        return False
    if not words_a or not words_b:
        return False
    intersection = words_a & words_b
    union = words_a | words_b
    if not union:
        return False
    jaccard = len(intersection) / len(union)
    return jaccard >= threshold


def primary_category(scores: Dict[str, int], section: Optional[str] = None) -> str:
    order = [
        "breaking", "security", "dependency", "migration", "plugin", "api_sdk",
        "cli", "config", "performance", "fix", "feature", "docs", "known_issue",
    ]
    if section and section in order:
        return section
    for key in order:
        if scores.get(key):
            return key
    return "other"


def has_explicit_breaking_signal(item: str) -> bool:
    lowered = item.lower()
    strong_tokens = [
        "breaking change", "breaking:", "incompatible", "removed support", "remove support",
        "removed flag", "removed command", "renamed command", "renamed flag",
        "migration required", "requires node", "minimum node", "no longer supports",
        "schema changed", "schema migration", "require its registered binary",
    ]
    # Semantic pattern matching for common breaking change expressions
    patterns = [
        r"no longer\s+\w+",  # no longer accepts, no longer supports, etc.
        r"requires\s+\w+\s+[\d\.\+]+",  # requires node 18+, requires python 3.10
        r"dropped\s+(support|the|compatibility|for)",  # dropped support, dropped the feature
        r"removed\s+(the\s+)?[\w-]+\s+(option|flag|command|method|api)",
    ]
    has_pattern = any(re.search(p, lowered) for p in patterns)
    return any(token in lowered for token in strong_tokens) or has_pattern or "破坏性变更" in item or "不兼容" in item


def has_explicit_migration_signal(item: str) -> bool:
    lowered = item.lower()
    tokens = [
        "migration required", "migration guide", "upgrade guide", "before you upgrade",
        "no longer", "instead of", "deprecated in favor", "removed support",
    ]
    return any(token in lowered for token in tokens) or "迁移指南" in item or "升级指南" in item


def has_explicit_dependency_signal(item: str) -> bool:
    lowered = item.lower()
    negative_tokens = [
        "benchmark", "coverage", "fixture", "harness", "canary", "qa-lab",
        "presentation capability", "tool fixture", "self-health", "restart readiness",
    ]
    if any(token in lowered for token in negative_tokens):
        return False
    return any(token in lowered for token in [
        "dependency", "dependencies", "peer dependency", "peerdependencies", "minimum node",
        "requires node", "node.js", "package.json", "npm", "yarn", "pnpm", "lockfile",
        "runtime requirement", "build arg", "image build", "apt package", "base image",
    ]) or "依赖" in item or "版本要求" in item


def has_explicit_security_signal(item: str) -> bool:
    lowered = item.lower()
    negative_tokens = ["token-efficiency", "token efficiency", "token count", "token accounting", "token budget"]
    if any(token in lowered for token in negative_tokens):
        return False
    strong_tokens = [
        "security", "vulnerability", "cve", "cwe", "cvss", "credential", "secret",
        "oauth", "sso", "authentication", "authorization", "permission", "sandbox escape",
        "xss", "csrf", "rce", "remote code execution", "injection", "affected version",
        "thumbprint", "certificate", "tls", "fingerprint",
    ]
    return any(token in lowered for token in strong_tokens) or any(token in item for token in ["安全", "漏洞", "认证", "授权", "权限", "凭据", "证书"])


def has_explicit_plugin_signal(item: str) -> bool:
    lowered = item.lower()
    negative_tokens = [
        "qa-lab", "qa suite", "coverage", "fixture", "fixtures", "harness", "canary",
        "benchmark", "runtime parity", "token-efficiency",
    ]
    if any(token in lowered for token in negative_tokens) and "defineToolPlugin" not in item:
        return False
    strong_tokens = [
        "plugin", "plugins", "manifest", "hook", "hooks", "loader", "extension",
        "extensions", "capability", "capabilities", "defineToolPlugin", "plugin-backed",
    ]
    return any(token in lowered for token in strong_tokens) or "插件" in item



def has_explicit_api_sdk_signal(item: str) -> bool:
    lowered = item.lower()
    strong_tokens = [
        "api", "sdk", "public api", "method", "signature", "parameter", "return",
        "typescript", "export", "exports", "openclawapi",
    ]
    return any(token in lowered for token in strong_tokens)


def has_explicit_cli_signal(item: str) -> bool:
    lowered = item.lower()
    strong_tokens = [
        "cli", "command", "subcommand", "flag", "option", "argument",
        "stdout", "stderr", "exit code", "powershell profile", "completion",
        "doctor", "plugins build", "plugins validate", "plugins init", "qa suite",
    ]
    return any(token in lowered for token in strong_tokens) or "命令行" in item


def has_explicit_config_signal(item: str) -> bool:
    lowered = item.lower()
    strong_tokens = [
        "config", "configuration", "setting", "settings", "schema", "env var",
        "environment variable", "default account", "named accounts", "binding", "caFile",
        "openclaw_image_apt_packages", "openclaw_docker_apt_packages",
    ]
    return any(token in lowered for token in strong_tokens) or "配置" in item


def is_internal_qa_item(item: str) -> bool:
    lowered = item.lower()
    internal_tokens = ["qa-lab", "test", "tests", "fixture", "fixtures", "harness", "smoke", "canary", "coverage"]
    public_tokens = ["runtime", "public", "api", "sdk", "cli", "config", "security", "auth", "plugin"]
    return any(token in lowered for token in internal_tokens) and not any(token in lowered for token in public_tokens)


def item_categories(item: str, section: Optional[str] = None) -> List[str]:
    scores = classify_text(item)
    # Section context bonus: items under a ## Breaking Changes heading get
    # a strong signal for that category, even if keyword match is weak.
    if section and section != "other":
        scores[section] = scores.get(section, 0) + 5
    keys = [
        "breaking", "security", "dependency", "migration", "plugin", "api_sdk",
        "cli", "config", "performance", "fix", "feature", "docs", "known_issue",
    ]
    # Threshold filtering: require score >= 2 to avoid weak single-word matches
    found = [key for key in keys if scores.get(key, 0) >= 2]
    if "breaking" in found and not has_explicit_breaking_signal(item):
        found.remove("breaking")
    if "migration" in found and not has_explicit_migration_signal(item):
        found.remove("migration")
    if "dependency" in found and not has_explicit_dependency_signal(item):
        found.remove("dependency")
    if "security" in found and not has_explicit_security_signal(item):
        found.remove("security")
    if "plugin" in found and not has_explicit_plugin_signal(item):
        found.remove("plugin")
    if "api_sdk" in found and not has_explicit_api_sdk_signal(item):
        found.remove("api_sdk")
    if "cli" in found and not has_explicit_cli_signal(item):
        found.remove("cli")
    if "config" in found and not has_explicit_config_signal(item):
        found.remove("config")
    if is_internal_qa_item(item):
        found = [cat for cat in found if cat not in {"plugin", "api_sdk", "cli", "config", "security", "breaking", "migration"}]
        if "docs" not in found:
            found.append("docs")
    if "feature" in found and any(cat in found for cat in ["breaking", "migration", "dependency", "security"]):
        found.remove("feature")
    if "fix" in found and any(cat in found for cat in ["feature", "docs"]) and not any(token in item.lower() for token in ["fix", "fixed", "fixes", "bug", "issue", "resolve", "resolved", "patch"]):
        found.remove("fix")
    return found or ["other"]



def infer_component(item: str) -> str:
    match = re.match(r"^([A-Za-z0-9_./@+ -]{2,80}?):\s+", item)
    if match:
        return match.group(1).strip()
    lowered = item.lower()
    component_map = [
        ("qa-lab", "QA-Lab"),
        ("docker/podman", "Docker/Podman"),
        ("docker", "Docker/Podman"),
        ("podman", "Docker/Podman"),
        ("gateway/performance", "Gateway/performance"),
        ("gateway", "Gateway"),
        ("plugin", "Plugin system"),
        ("cli", "CLI"),
        ("api", "API/SDK"),
        ("sdk", "API/SDK"),
        ("config", "Configuration"),
        ("node", "Runtime/Dependency"),
        ("sidecar", "Sidecar"),
        ("telegram", "Telegram integration"),
        ("discord", "Discord integration"),
        ("media", "Media pipeline"),
        ("mac app", "Mac app"),
        ("android", "Android"),
        ("proxy", "Proxy"),
        ("skills", "Skills"),
        ("security", "Security"),
    ]
    for token, component in component_map:
        if token in lowered:
            return component
    return "General"



def risk_level(categories: Sequence[str], item: str) -> str:
    lowered = item.lower()
    if any(cat in categories for cat in ["breaking", "migration", "dependency"]):
        if any(token in lowered for token in ["minimum node", "requires node", "breaking", "removed", "incompatible"]):
            return "high"
        return "medium"
    if "security" in categories:
        return "high" if any(token in lowered for token in ["cve", "vulnerability", "credential", "secret", "rce"]) else "medium"
    if any(cat in categories for cat in ["plugin", "api_sdk", "cli", "config"]):
        if any(token in lowered for token in ["signature", "removed", "deprecated", "renamed", "no longer", "dropped"]):
            return "medium"
        if "breaking" in categories or "migration" in categories:
            return "medium"
        return "low"
    if "performance" in categories:
        return "medium" if any(token in lowered for token in ["crash", "deadlock", "data loss", "leak", "hang"]) else "low"
    return "low"


def priority_score(categories: Sequence[str], risk: str) -> int:
    score = {"high": 100, "medium": 60, "low": 20}.get(risk, 10)
    weights = {
        "breaking": 40, "security": 35, "dependency": 30, "migration": 30,
        "plugin": 25, "api_sdk": 25, "cli": 18, "config": 18,
        "performance": 15, "fix": 8, "feature": 6, "known_issue": 12,
        "docs": -10, "other": 0,
    }
    return score + sum(weights.get(cat, 0) for cat in categories)


def audience_for(categories: Sequence[str], component: str, lang: str) -> List[str]:
    labels = {
        "plugin": "插件开发者",
        "api_sdk": "API/SDK 使用者",
        "cli": "CLI 使用者和自动化脚本维护者",
        "config": "配置维护者和自部署用户",
        "dependency": "CI/CD、部署和运行时维护者",
        "security": "安全敏感用户",
        "performance": "稳定性敏感用户",
        "fix": "受相关问题影响的用户",
        "feature": "需要相关新能力的用户",
    }
    audience: List[str] = []
    for cat in ["plugin", "api_sdk", "cli", "config", "dependency", "security", "performance", "fix", "feature"]:
        if cat in categories and labels[cat] not in audience:
            audience.append(labels[cat])
    if not audience:
        audience.append("普通 OpenClaw 用户")
    if component not in ["General", "Security"]:
        audience.append(f"使用 {component} 相关能力的团队")
    return audience[:3]


def interpret_change(item: str, categories: Sequence[str], component: str, lang: str) -> str:
    clean = item.rstrip(".")
    lowered = clean.lower()
    if "security" in categories:
        if any(token in lowered for token in ["cve", "vulnerability", "security fix", "auth", "authentication", "permission", "credential", "token"]):
            return f"这项更新与 {component} 的安全面有关，优先判断你当前版本是否落在受影响范围，以及认证、授权或凭据链路是否会因此变化。若命中生产路径，建议提前验证修复后的访问控制和失败处理。"
        return f"这项更新收紧或调整了 {component} 的安全相关行为。它不一定会直接改变功能结果，但可能影响认证流程、权限边界或默认安全策略，升级前最好核对现网配置是否仍然成立。"
    if "breaking" in categories or "migration" in categories:
        return f"这项更新对 {component} 发出了兼容性或迁移信号。更值得关注的是现有接口、配置、脚本和自动化流程会不会失配；如果依赖旧行为，应该先补齐迁移核对和回归验证，再安排正式升级。"
    if "dependency" in categories:
        return f"这项更新更像是在改动 {component} 的环境前提，而不是单纯新增功能。需要先确认 Node.js、包管理器、锁文件、构建镜像和 CI/CD 运行时是否满足新的依赖要求，否则升级可能卡在安装、构建或启动阶段。"
    if "fix" in categories and any(token in lowered for token in ["stop rejecting", "allow", "validation", "validate", "rejecting"]):
        return f"这项更新是在修正 {component} 的校验或兼容性问题，重点价值是减少误报、误拒绝或本不该失败的场景。若你的团队之前绕过过类似限制，升级后应回归验证原先失败的链路是否已经恢复正常。"
    if "plugin" in categories:
        return f"这项更新会影响 {component} 的插件扩展面。即使不是破坏性变更，也可能波及插件清单、hook、加载顺序或扩展契约；对自定义插件较多的团队，建议把兼容性回归放进升级前检查。"
    if "api_sdk" in categories:
        return f"这项更新直接作用在 {component} 的 API/SDK 表面，调用方式、导出内容、类型定义或封装层都可能受影响。若你们有二次封装或对外集成，升级前最好先核对关键调用路径。"
    if "cli" in categories:
        return f"这项更新主要影响 {component} 的命令行使用方式。需要留意命令参数、子命令、输出格式或退出码是否变化，因为这些细节最容易连带影响自动化脚本和运维流程。"
    if "config" in categories:
        return f"这项更新集中在 {component} 的配置层，通常会影响 schema、默认值、必填项或环境变量约定。真正的风险不在文案本身，而在于旧配置是否还能被接受、以及部署参数是否需要同步调整。"
    if "performance" in categories:
        return f"这项更新偏向 {component} 的性能或稳定性改善，通常属于正向收益。对高负载、长连接或关键路径敏感的场景，仍建议用现网相近流量做一次回归确认，避免收益伴随行为变化。"
    if "fix" in categories:
        return f"这项更新是在修复 {component} 的具体问题。是否值得优先升级，主要取决于你当前是否正被同类缺陷影响；如果问题已命中生产或核心流程，这类版本通常有较高升级价值。"
    if "feature" in categories:
        return f"这项更新为 {component} 增加了新能力或增强了现有能力，更偏向可选收益而不是刚性升级项。如果你正好需要这部分能力，可以评估尽快跟进；否则可放到常规升级窗口处理。"
    if "docs" in categories:
        return f"这项更新主要是补充或修正文档，对运行时风险通常较小。但如果它解释的是新配置、迁移步骤或使用约束，仍值得核对你们当前实践是否与官方说明一致。"
    if "known_issue" in categories:
        return f"这条说明更像是在提示 {component} 仍有已知限制或待解决问题。它未必阻止升级，但会影响你对版本稳定性的预期，适合提前确认是否命中自身场景并准备规避方案。"
    return f"这项更新来自 {component}，但 release note 提供的信息有限。仅凭这条描述还不足以判断升级价值，最好结合关联 PR、Issue 或实际改动范围再决定是否优先跟进。"

def actions_for(categories: Sequence[str], risk: str, component: str, lang: str) -> List[str]:
    actions: List[str] = []
    if any(cat in categories for cat in ["breaking", "migration"]):
        actions.append("先核对迁移说明、废弃项和重命名项，再安排升级验证。")
        actions.append("对依赖旧接口、旧配置或旧脚本的流程做定向回归。")
    if "dependency" in categories:
        actions.append("检查 Node.js、包管理器、锁文件、构建镜像和 CI/CD 运行时版本。")
    if "plugin" in categories:
        actions.append("验证插件 manifest、hook 签名、加载顺序和扩展契约。")
    if "api_sdk" in categories:
        actions.append("检查 API/SDK 导出、类型定义、封装层和弃用提示。")
    if "cli" in categories:
        actions.append("回归测试依赖 CLI 参数、子命令、输出格式或退出码的脚本。")
    if "config" in categories:
        actions.append("逐项比对配置 schema、默认值、必填项和环境变量约定。")
    if "security" in categories:
        actions.append("确认受影响版本范围，并优先在预生产环境验证修复路径。")
    if "performance" in categories:
        actions.append("在关键路径运行回归、压力、启动或长稳测试。")
    if "fix" in categories and not any(cat in categories for cat in ["breaking", "migration", "security", "performance"]):
        actions.append("如果你正受同类问题影响，优先复现旧问题并确认修复是否生效。")
    if not actions:
        actions.append(f"如果依赖 {component} 相关能力，先在非生产环境完成验证再升级。")
    if risk == "high":
        rollback_text = "准备回滚方案，并明确升级失败后的恢复路径。"
        if rollback_text not in actions:
            actions.append(rollback_text)
    deduped: List[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped[:3]



def analyze_change_item(item: str, release: Release, lang: str) -> ChangeAnalysis:
    categories = item_categories(item)
    component = infer_component(item)
    risk = risk_level(categories, item)
    return ChangeAnalysis(
        release_tag=release.tag_name,
        raw_text=item,
        primary_category=categories[0],
        categories=categories,
        component=component,
        interpretation=interpret_change(item, categories, component, lang),
        risk_level=risk,
        audience=audience_for(categories, component, lang),
        action_items=actions_for(categories, risk, component, lang),
        confidence=confidence_for(categories, item),
        priority=priority_score(categories, risk),
    )


# Module-level: statistics from the last analyze_release_notes call
_last_dedup_stats: dict[str, int] = {}


def analyze_release_notes(scoped: Sequence[Release], lang: str) -> List[ChangeAnalysis]:
    """Analyze release notes across a version scope with two-level deduplication.

    Level 1 — Exact text match: items with identical normalized text are
    deduplicated. This catches cherry-picks and verbatim duplicates.

    Level 2 — Semantic signature match: items whose semantic signatures are
    sufficiently similar (>= SEMANTIC_DEDUP_THRESHOLD) are also deduplicated.
    This catches the same change described with slightly different wording
    across versions (e.g. commit messages edited during cherry-pick).
    """
    global _last_dedup_stats

    analyses: List[ChangeAnalysis] = []
    seen_texts: set[str] = set()
    seen_signatures: dict[str, str] = {}  # signature -> canonical text
    exact_dups = 0
    semantic_dups = 0
    total_items = 0

    for release in scoped:
        for item in release_note_items(release):
            total_items += 1

            # Level 1: exact text dedup
            key = item.lower()
            if key in seen_texts:
                exact_dups += 1
                continue

            # Level 2: semantic signature dedup (Jaccard similarity on word sets)
            words = set(semantic_dedup_key(item).split())
            if len(words) >= SEMANTIC_DEDUP_MIN_WORDS:
                is_dup = False
                for existing_sig, existing_text in seen_signatures.items():
                    existing_words = set(existing_sig.split())
                    intersection = words & existing_words
                    union = words | existing_words
                    if union and len(intersection) / len(union) >= SEMANTIC_DEDUP_THRESHOLD:
                        is_dup = True
                        break
                if is_dup:
                    semantic_dups += 1
                    continue
                seen_signatures[semantic_dedup_key(item)] = item

            seen_texts.add(key)
            analyses.append(analyze_change_item(item, release, lang))

    _last_dedup_stats = {
        "total_raw_items": total_items,
        "exact_duplicates": exact_dups,
        "semantic_duplicates": semantic_dups,
        "final_unique_items": len(analyses),
        "dedup_rate": round((exact_dups + semantic_dups) / total_items * 100, 1) if total_items else 0,
    }

    # Print dedup stats to stderr for visibility (especially useful for cross-version analysis)
    if total_items > len(analyses):
        print(
            f"Info: Deduplicated {exact_dups + semantic_dups} items "
            f"({exact_dups} exact, {semantic_dups} semantic) "
            f"out of {total_items} raw items "
            f"→ {len(analyses)} unique ({_last_dedup_stats['dedup_rate']}% dedup rate)",
            file=sys.stderr,
        )

    sorted_analyses = sorted(analyses, key=lambda entry: entry.priority, reverse=True)
    for idx, analysis in enumerate(sorted_analyses, 1):
        analysis.note_id = f"R-{idx:03d}"
    return sorted_analyses

def score_file_importance(filename: str) -> int:
    """Return an importance score for a changed file based on its path."""
    score = 0
    for pattern, weight in FILE_IMPORTANCE_PATTERNS:
        if re.search(pattern, filename, re.IGNORECASE):
            score += weight
    # Files at repo root (package.json, tsconfig.json, etc.) get a small boost
    if "/" not in filename and "." in filename:
        score += 2
    return score


def truncate_patch(patch: str, max_lines: int = MAX_PATCH_LINES_PER_FILE) -> str:
    """Truncate a unified-diff patch to at most max_lines, keeping header context."""
    lines = patch.splitlines()
    if len(lines) <= max_lines:
        return patch
    # Keep first few lines (file header + some context), add ellipsis, keep last few.
    head = max_lines // 2
    tail = max_lines - head - 1
    return "\n".join(lines[:head] + ["... (patch truncated) ..."] + lines[-tail:])


def fetch_compare_diff(repo: str, base: str, head: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch compare data from GitHub API and return a list of file-change dicts.

    Each dict contains:
        - filename: str
        - status: str (added, removed, modified, renamed)
        - additions: int
        - deletions: int
        - patch: str (may be absent for binary files or large diffs)
        - previous_filename: str (for renames)
    """
    url = f"{API_ROOT}/repos/{repo}/compare/{base}...{head}"
    payload = request_json(url, token)
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected GitHub compare response")
    files = payload.get("files", [])
    result: List[Dict[str, Any]] = []
    for f in files:
        result.append({
            "filename": f.get("filename", ""),
            "status": f.get("status", ""),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
            "patch": f.get("patch", ""),
            "previous_filename": f.get("previous_filename", ""),
        })
    return result


def fetch_compare_commits(repo: str, base: str, head: str, token: Optional[str] = None) -> List[CommitInfo]:
    """Fetch commits from GitHub Compare API and return structured commit info.

    Uses the same /compare endpoint as fetch_compare_diff but extracts the
    commit list instead of the file list. This avoids an extra API call.
    """
    url = f"{API_ROOT}/repos/{repo}/compare/{base}...{head}"
    payload = request_json(url, token)
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected GitHub compare response")

    commits: List[CommitInfo] = []
    for c in payload.get("commits", []):
        commit_data = c.get("commit", {})
        # First line of commit message only (subject)
        message = (commit_data.get("message", "") or "").split("\n")[0].strip()
        author = (commit_data.get("author", {}) or {}).get("name", "")
        sha = (c.get("sha", "") or "")[:8]

        # Files changed in this specific commit (from the compare API nested data)
        changed_files: List[str] = []
        for f in c.get("files", []):
            fname = f.get("filename", "")
            if fname and fname not in changed_files:
                changed_files.append(fname)

        commits.append(
            CommitInfo(
                sha=sha,
                message=message,
                author_name=author,
                changed_files=changed_files,
            )
        )

    return commits


def select_important_files(
    files: List[Dict[str, Any]],
    max_files: int = MAX_DIFF_FILES,
    max_chars: int = MAX_TOTAL_DIFF_CHARS,
    max_lines_per_file: int = MAX_PATCH_LINES_PER_FILE,
) -> List[Dict[str, Any]]:
    """Sort files by importance, truncate patches, and stay within character budget."""
    # Score and sort descending
    scored = [(f, score_file_importance(f["filename"])) for f in files]
    scored.sort(key=lambda x: x[1], reverse=True)

    selected: List[Dict[str, Any]] = []
    total_chars = 0
    for f, score in scored:
        if len(selected) >= max_files:
            break
        # Skip files with negative score unless we haven't selected anything yet
        if score < 0 and len(selected) >= 5:
            continue
        patch = f.get("patch", "")
        if patch:
            patch = truncate_patch(patch, max_lines_per_file)
        entry = {
            "filename": f["filename"],
            "status": f["status"],
            "additions": f["additions"],
            "deletions": f["deletions"],
            "patch": patch,
            "previous_filename": f.get("previous_filename", ""),
            "importance_score": score,
        }
        entry_chars = len(json.dumps(entry, ensure_ascii=False))
        if total_chars + entry_chars > max_chars and len(selected) >= 3:
            # Budget exhausted but keep at least 3 files
            break
        selected.append(entry)
        total_chars += entry_chars
    return selected


def _skill_dir() -> Path:
    """Return the skill installation directory."""
    return Path(__file__).resolve().parent.parent


def _is_inside_skill_dir(path: Path) -> bool:
    """Check if a path is inside the skill installation directory."""
    try:
        path.resolve().relative_to(_skill_dir().resolve())
        return True
    except ValueError:
        return False


def _cleanup_transient_files(snapshot_dir: Path, repo: str, target_tag: str) -> None:
    """Remove step-internal transient files after report generation."""
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"

    # Clean up base analysis cache
    base_path = snapshot_dir / f"{repo_part}-{target_part}-base-analysis.json"
    if base_path.exists():
        try:
            base_path.unlink()
        except OSError:
            pass

    # Clean up analysis data file (new single-file mode)
    data_path = snapshot_dir / f"{repo_part}-{target_part}-analysis-data.json"
    if data_path.exists():
        try:
            data_path.unlink()
        except OSError:
            pass

    # Clean up chunk data files
    chunk_pattern = f"{repo_part}-{target_part}-analysis-chunk-*.json"
    for chunk_file in snapshot_dir.glob(chunk_pattern):
        try:
            chunk_file.unlink()
        except OSError:
            pass

    # Clean up legacy per-component prompt files (backward compatibility)
    pattern = f"{repo_part}-{target_part}-*-llm-prompt.json"
    for prompt_file in snapshot_dir.glob(pattern):
        try:
            prompt_file.unlink()
        except OSError:
            pass


def _cleanup_legacy_prompts(snapshot_dir: Path, repo: str, target_tag: str) -> None:
    """Clean up only legacy prompt files, preserving base-analysis and data files.

    Used in --apply-llm-results mode to keep transient files available for
    potential re-runs while removing obsolete legacy artifacts.
    """
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    pattern = f"{repo_part}-{target_part}-*-llm-prompt.json"
    for prompt_file in snapshot_dir.glob(pattern):
        try:
            prompt_file.unlink()
        except OSError:
            pass


def _cleanup_expired_cache(snapshot_dir: Path) -> None:
    """Remove expired cache files on startup (lazy cleanup).

    Retention policy:
    - release-notes.md: keep up to RELEASE_NOTES_MAX_VERSIONS most recent
    - llm-results.json: keep for LLM_RESULTS_TTL_DAYS
    - llm-prompt.json / base-analysis.json: transient, remove on every run
    """
    if not snapshot_dir.exists():
        return

    now = time.time()
    llm_results_ttl = LLM_RESULTS_TTL_DAYS * 86400

    # Clean up stale LLM result files
    for results_file in snapshot_dir.glob("*-llm-results.json"):
        try:
            if now - results_file.stat().st_mtime > llm_results_ttl:
                results_file.unlink()
        except OSError:
            pass

    # Clean up legacy per-component prompt files
    for prompt_file in snapshot_dir.glob("*-llm-prompt.json"):
        try:
            prompt_file.unlink()
        except OSError:
            pass

    # NOTE: analysis-data.json, base-analysis.json, and chunk files are
    # intermediate products tied to a specific snapshot. They are NOT cleaned
    # here unconditionally; they are only removed when the associated snapshot
    # is detected as inconsistent (see _cleanup_transient_files).

    # Keep only the most recent release notes snapshots
    snapshots = sorted(
        snapshot_dir.glob("*-release-notes.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_snapshot in snapshots[RELEASE_NOTES_MAX_VERSIONS:]:
        try:
            old_snapshot.unlink()
        except OSError:
            pass


def _cleanup_all_cache(snapshot_dir: Path) -> int:
    """Remove all cache files (used by --clean-cache)."""
    if not snapshot_dir.exists():
        print(f"Cache directory does not exist: {snapshot_dir}")
        return 0

    count = 0
    for pattern in (
        "*-release-notes.md",
        "*-analysis-data.json",
        "*-analysis-chunk-*.json",
        "*-analysis-result-chunk-*.json",
        "*-llm-results-chunk-*.json",
        "*-llm-prompt.json",
        "*-llm-results.json",
        "*-base-analysis.json",
    ):
        for f in snapshot_dir.glob(pattern):
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
    print(f"Cleaned {count} cached file(s) from {snapshot_dir}")
    return 0


# ---------------------------------------------------------------------------
# Merge categories (existing)
# ---------------------------------------------------------------------------

def merge_categories(classified: Iterable[Dict[str, List[str]]]) -> Dict[str, List[str]]:
    merged = {key: [] for key in [
        "feature", "fix", "breaking", "security", "performance",
        "plugin", "api_sdk", "cli", "config", "dependency", "migration",
        "docs", "known_issue", "other"
    ]}
    for entry in classified:
        for key, values in entry.items():
            for value in values:
                if value not in merged[key]:
                    merged[key].append(value)
    return merged


# ---------------------------------------------------------------------------
# Recursive merge aggregation
# ---------------------------------------------------------------------------

@dataclass
class LeafGroup:
    """A group of consecutive releases to be analyzed as a single leaf node."""
    releases: List[Release]
    analyses: List[ChangeAnalysis]
    commits: List[CommitInfo]
    diff_files: List[Dict[str, Any]]


def _estimate_leaf_tokens(analyses: List[ChangeAnalysis], commits: List[CommitInfo]) -> int:
    """Estimate token count for a leaf group.

    Uses the same heuristic as estimate_data_tokens: characters * TOKENS_PER_CHAR.
    """
    # Approximate notes text
    notes_chars = sum(len(a.raw_text) for a in analyses)
    # Approximate commits text (message + files)
    commits_chars = sum(
        len(c.message) + sum(len(f) for f in c.changed_files)
        for c in commits
    )
    # Meta + instructions overhead
    overhead = 5000
    total = notes_chars + commits_chars + overhead
    return int(total * 1.3)


def build_leaf_groups(
    scoped_releases: List[Release],
    all_analyses: List[ChangeAnalysis],
    all_commits: List[CommitInfo],
    all_diff_files: List[Dict[str, Any]],
) -> List[LeafGroup]:
    """Build leaf groups by token budget (vertical partitioning).

    Strategy:
    - Accumulate versions until adding the next would exceed token budget.
    - Each group contains 1-3 versions (hard cap).
    - Each group gets notes + commits for its version range.
    """
    if not scoped_releases:
        return []

    groups: List[LeafGroup] = []
    current_releases: List[Release] = []

    for i, release in enumerate(scoped_releases):
        # Collect analyses for this release
        release_analyses = [a for a in all_analyses if a.release_tag == release.tag_name]

        # Estimate commits for this release's range
        # For the first release in the group, we need commits from the previous
        # release (or all commits up to this point if it's the first overall)
        if not current_releases:
            # Starting a new group: include all commits up to this release
            # (in practice, commits are fetched per-range, so we use proportional estimate)
            est_commits = len(all_commits) // len(scoped_releases)
        else:
            est_commits = len(all_commits) // len(scoped_releases)

        est_tokens = _estimate_leaf_tokens(release_analyses, [])
        # Add overhead for estimated commits
        est_tokens += est_commits * 300  # ~300 chars per commit

        # Check if adding this release would exceed budget
        current_analyses = [a for a in all_analyses
                           if a.release_tag in {r.tag_name for r in current_releases}]
        current_tokens = _estimate_leaf_tokens(current_analyses, [])
        current_tokens += len(current_releases) * est_commits * 300

        would_exceed = (
            current_tokens + est_tokens > RECURSIVE_MERGE_MAX_TOKENS_PER_LEAF
            and current_releases
        )
        would_exceed_versions = len(current_releases) >= RECURSIVE_MERGE_MAX_VERSIONS_PER_LEAF

        if would_exceed or would_exceed_versions:
            # Finalize current group
            group_releases = current_releases
            group_analyses = [a for a in all_analyses
                             if a.release_tag in {r.tag_name for r in group_releases}]
            # Assign a proportional slice of commits and diff files
            group_commits, group_diffs = _slice_commits_and_diffs(
                group_releases, scoped_releases, all_commits, all_diff_files
            )
            groups.append(LeafGroup(
                releases=group_releases,
                analyses=group_analyses,
                commits=group_commits,
                diff_files=group_diffs,
            ))
            current_releases = [release]
        else:
            current_releases.append(release)

    # Finalize last group
    if current_releases:
        group_analyses = [a for a in all_analyses
                         if a.release_tag in {r.tag_name for r in current_releases}]
        group_commits, group_diffs = _slice_commits_and_diffs(
            current_releases, scoped_releases, all_commits, all_diff_files
        )
        groups.append(LeafGroup(
            releases=current_releases,
            analyses=group_analyses,
            commits=group_commits,
            diff_files=group_diffs,
        ))

    return groups


def _slice_commits_and_diffs(
    group_releases: List[Release],
    all_releases: List[Release],
    all_commits: List[CommitInfo],
    all_diff_files: List[Dict[str, Any]],
) -> Tuple[List[CommitInfo], List[Dict[str, Any]]]:
    """Assign a proportional slice of commits and diff files to a leaf group.

    This is a simple proportional allocation. In practice, commits and diffs
    are fetched per-group via the compare API; this function provides a
    fallback when pre-fetched data is available.
    """
    if not all_releases or not group_releases:
        return [], []

    n_group = len(group_releases)
    n_total = len(all_releases)

    # Proportional slice of commits
    if all_commits:
        n_commits = max(1, len(all_commits) * n_group // n_total)
        # Take from the start of the all_commits list (assumes chronological order)
        # Find the position of group_releases in all_releases
        start_idx = all_releases.index(group_releases[0]) if group_releases[0] in all_releases else 0
        commit_start = start_idx * len(all_commits) // n_total
        commit_end = min(len(all_commits), commit_start + n_commits + 10)
        group_commits = all_commits[commit_start:commit_end]
    else:
        group_commits = []

    # Proportional slice of diff files
    if all_diff_files:
        n_files = max(1, len(all_diff_files) * n_group // n_total)
        start_idx = all_releases.index(group_releases[0]) if group_releases[0] in all_releases else 0
        file_start = start_idx * len(all_diff_files) // n_total
        file_end = min(len(all_diff_files), file_start + n_files + 5)
        group_diffs = all_diff_files[file_start:file_end]
    else:
        group_diffs = []

    return group_commits, group_diffs


def analyze_recursive(
    repo: str,
    scoped_releases: List[Release],
    all_analyses: List[ChangeAnalysis],
    all_commits: List[CommitInfo],
    all_diff_files: List[Dict[str, Any]],
    lang: str,
    github_token: Optional[str],
    snapshot_dir: Path,
) -> Tuple[Optional[LLMFullReport], List[str]]:
    """Perform recursive merge aggregation analysis (external-LLM workflow).

    This function orchestrates the recursive analysis pipeline:
    1. Build leaf groups (vertical partitioning)
    2. Generate leaf analysis data files
    3. Check for cached leaf LLM results
    4. If all leaf results exist: recursively merge them
    5. At each merge level: check for cached merge results, or generate prompts
    6. Return final report + list of missing files (if any)

    Returns (final_report_or_None, missing_files).
    If missing_files is non-empty, the caller should prompt the user to
    run LLM analysis on those files before re-running.
    """
    target_tag = scoped_releases[-1].tag_name if scoped_releases else "unknown"

    # Step 1: Build leaf groups
    leaf_groups = build_leaf_groups(scoped_releases, all_analyses, all_commits, all_diff_files)
    print(
        f"Info: Recursive merge: {len(scoped_releases)} versions → {len(leaf_groups)} leaf groups",
        file=sys.stderr,
    )
    for i, g in enumerate(leaf_groups):
        tags = ", ".join(r.tag_name for r in g.releases)
        print(
            f"  Leaf {i+1}: {tags} ({len(g.analyses)} notes, {len(g.commits)} commits)",
            file=sys.stderr,
        )

    # Step 2: Generate leaf analysis data and check for cached results
    leaf_results: List[LLMFullReport] = []
    missing: List[str] = []

    for i, group in enumerate(leaf_groups):
        target = group.releases[-1]
        compare = group.releases[0]
        all_tags = [r.tag_name for r in scoped_releases]
        group_start_idx = all_tags.index(compare.tag_name) if compare.tag_name in all_tags else -1
        compare_base = scoped_releases[group_start_idx - 1] if group_start_idx > 0 else None

        # Fetch commits/diffs if not pre-fetched
        group_commits = group.commits
        group_diffs = group.diff_files
        if not group_commits and compare_base:
            try:
                raw_commits = fetch_compare_commits(repo, compare_base.tag_name, target.tag_name, github_token)
                group_commits = select_relevant_commits(raw_commits)
            except Exception as exc:
                print(f"Warning: Could not fetch commits for leaf group {i+1}: {exc}", file=sys.stderr)
        if not group_diffs and compare_base:
            try:
                raw_files = fetch_compare_diff(repo, compare_base.tag_name, target.tag_name, github_token)
                group_diffs = select_important_files(raw_files)
            except Exception as exc:
                print(f"Warning: Could not fetch diff for leaf group {i+1}: {exc}", file=sys.stderr)

        # Build and write leaf analysis data
        data = build_analysis_data(
            repo=repo,
            target=target,
            compare=compare_base,
            analyses=group.analyses,
            commits=group_commits,
            diff_files=group_diffs,
            lang=lang,
            scoped_releases=group.releases,
        )
        leaf_data_path = _leaf_data_path(snapshot_dir, repo, target_tag, i)
        write_analysis_data(data, leaf_data_path)
        print(f"  LEAF_DATA[{i+1}]: {leaf_data_path}", file=sys.stderr)

        # Check for cached leaf result
        leaf_result_path = _leaf_result_path(snapshot_dir, repo, target_tag, i)
        if leaf_result_path.exists():
            print(f"  LEAF_RESULT[{i+1}]: {leaf_result_path} (cached)", file=sys.stderr)
            leaf_results.append(parse_llm_results(leaf_result_path))
        else:
            print(f"  LEAF_RESULT[{i+1}]: MISSING — please analyze {leaf_data_path}", file=sys.stderr)
            leaf_results.append(LLMFullReport())
            missing.append(str(leaf_data_path))

    # If any leaf results are missing, we can't proceed
    if missing:
        return None, missing

    # Step 3: Recursive merge with prompt generation for missing merge results
    final_report, merge_missing = _recursive_merge_with_prompts(
        leaf_results, repo, target_tag, snapshot_dir, depth=0, lang=lang
    )
    missing.extend(merge_missing)

    return final_report, missing


def _recursive_merge_with_prompts(
    results: List[LLMFullReport],
    repo: str,
    target_tag: str,
    snapshot_dir: Path,
    depth: int = 0,
    lang: str = "zh",
) -> Tuple[Optional[LLMFullReport], List[str]]:
    """Recursively merge results, generating prompts for missing merge layers.

    Returns (final_report_or_None, missing_files).
    """
    if depth > RECURSIVE_MERGE_MAX_DEPTH:
        raise RuntimeError(f"Recursive merge exceeded max depth ({RECURSIVE_MERGE_MAX_DEPTH})")

    if len(results) == 1:
        return results[0], []

    merged: List[LLMFullReport] = []
    missing: List[str] = []

    for i in range(0, len(results), 2):
        if i + 1 < len(results):
            a, b = results[i], results[i + 1]

            # Skip empty results
            if not a.themes and not b.themes:
                merged.append(LLMFullReport())
                continue
            if not a.themes:
                merged.append(b)
                continue
            if not b.themes:
                merged.append(a)
                continue

            # Check for cached merge result
            merge_result_path = _merge_result_path(snapshot_dir, repo, target_tag, depth, i // 2)
            if merge_result_path.exists():
                print(
                    f"  MERGE_RESULT[d{depth}-{i//2}]: {merge_result_path} (cached)",
                    file=sys.stderr,
                )
                merged.append(parse_merge_results(merge_result_path.read_text(encoding="utf-8")))
                continue

            # Generate merge prompt
            compressed_a = compress_for_merge(a)
            compressed_b = compress_for_merge(b)
            prompt = build_merge_prompt(compressed_a, compressed_b, lang)
            prompt_path = _merge_prompt_path(snapshot_dir, repo, target_tag, depth, i // 2)
            prompt_path.write_text(prompt, encoding="utf-8")
            print(
                f"  MERGE_PROMPT[d{depth}-{i//2}]: {prompt_path} — please analyze and save result to {merge_result_path}",
                file=sys.stderr,
            )

            # Use fallback merge so we can continue checking deeper layers
            merged.append(_fallback_merge(a, b))
            missing.append(str(prompt_path))
        else:
            # Odd node: pass through
            merged.append(results[i])

    # Recurse to next level, combining missing files from all levels
    final_report, deeper_missing = _recursive_merge_with_prompts(
        merged, repo, target_tag, snapshot_dir, depth + 1, lang
    )
    missing.extend(deeper_missing)
    return final_report, missing


def _fallback_merge(a: LLMFullReport, b: LLMFullReport) -> LLMFullReport:
    """Fallback pure-Python merge when LLM merge result is not yet available.

    This produces a best-effort merged result using the same rules as
    merge_chunk_results. When the LLM merge result becomes available,
    it should replace this fallback.
    """
    merged = LLMFullReport()

    # Themes: union by theme_id
    seen_themes: set[str] = set()
    for t in a.themes + b.themes:
        if t.theme_id not in seen_themes:
            merged.themes.append(t)
            seen_themes.add(t.theme_id)

    # Detailed notes: union by note_id
    seen_notes: set[str] = set()
    for n in a.detailed_notes + b.detailed_notes:
        if n.note_id not in seen_notes:
            merged.detailed_notes.append(n)
            seen_notes.add(n.note_id)

    # Progressive fixes: union by fix_id
    seen_fixes: set[str] = set()
    for pf in a.progressive_fixes + b.progressive_fixes:
        if pf.fix_id not in seen_fixes:
            merged.progressive_fixes.append(pf)
            seen_fixes.add(pf.fix_id)

    # Version evolution: union by evolution_id
    seen_evo: set[str] = set()
    for ve in a.version_evolution + b.version_evolution:
        if ve.evolution_id not in seen_evo:
            merged.version_evolution.append(ve)
            seen_evo.add(ve.evolution_id)

    # Compatibility risks: dedup by component
    seen_risks: set[str] = set()
    for cr in a.compatibility_risks + b.compatibility_risks:
        key = f"{cr.component}:{cr.description[:50]}"
        if key not in seen_risks:
            merged.compatibility_risks.append(cr)
            seen_risks.add(key)

    # Test points: dedup
    seen_tp: set[str] = set()
    for tp in a.test_points + b.test_points:
        if tp not in seen_tp:
            merged.test_points.append(tp)
            seen_tp.add(tp)

    # Shadow changes: dedup by description
    seen_shadow: set[str] = set()
    for sc in a.shadow_changes + b.shadow_changes:
        desc = sc.get("description", "")[:50] if isinstance(sc, dict) else str(sc)[:50]
        if desc not in seen_shadow:
            merged.shadow_changes.append(sc)
            seen_shadow.add(desc)

    # Executive summary: prefer non-empty from either side
    if a.executive_summary and a.executive_summary.one_liner:
        merged.executive_summary = a.executive_summary
    elif b.executive_summary and b.executive_summary.one_liner:
        merged.executive_summary = b.executive_summary

    # Developer conclusion: prefer non-empty
    if a.developer_conclusion:
        merged.developer_conclusion = a.developer_conclusion
    elif b.developer_conclusion:
        merged.developer_conclusion = b.developer_conclusion

    return merged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze OpenClaw GitHub releases")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo in owner/name format")
    parser.add_argument("--latest", action="store_true", help="Analyze latest stable release")
    parser.add_argument("--target", help="Target release tag/version")
    parser.add_argument("--compare", help="Compare baseline release tag/version")
    parser.add_argument("--from", dest="from_version", help="Start version for range analysis")
    parser.add_argument("--to", dest="to_version", help="End version for range analysis")
    parser.add_argument("--include-beta", action="store_true", help="Include prerelease preview section")
    parser.add_argument(
        "--lang",
        choices=["zh"],
        default="zh",
        help="(deprecated) Report language is always Chinese.",
    )
    parser.add_argument(
        "--user-query",
        help="P0-3: User's original query text (retained for backward compatibility).",
    )
    parser.add_argument(
        "--github-token",
        help="GitHub token for authenticated API access. Falls back to GITHUB_TOKEN environment variable. "
             "Required for LLM-enhanced diff analysis; without it, only rule-based analysis is performed.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        help="Directory for the freshly fetched release-notes snapshot used by this run. Defaults to the platform cache directory (e.g. ~/.cache/openclaw-release-analyzer/snapshots).",
    )
    parser.add_argument("--output", help="Write Markdown report to file")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format: markdown=full report (default). JSON mode is accepted for CLI compatibility but produces the same Markdown report.",
    )
    # LLM analysis modes (Claude Code orchestrates the LLM call)
    parser.add_argument(
        "--prepare-analysis-data",
        action="store_true",
        help="Generate a single analysis-data.json (release notes + commits + diff summary) and exit. "
             "Claude Code reads this file, performs comprehensive LLM analysis, and writes results back.",
    )
    # Legacy alias for backward compatibility
    parser.add_argument(
        "--generate-llm-prompt",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--apply-llm-results",
        help="Path to LLM analysis results JSON file. Merge these into the report generation.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--prepare-chunks",
        action="store_true",
        help="Auto-split analysis data into chunks if it exceeds token threshold. "
             "Outputs chunk file paths for distributed LLM processing.",
    )
    parser.add_argument(
        "--merge-chunk-results",
        action="store_true",
        help="Discover and merge all chunk result files into a single llm-results.json. "
             "Use after all chunks have been processed by LLM.",
    )
    parser.add_argument(
        "--recursive-analysis",
        action="store_true",
        help="Use recursive merge aggregation for multi-version analysis. "
             "Partitions versions into leaf groups, analyzes each with LLM, "
             "then recursively merges results for cross-version progressive fix "
             "detection and cumulative risk assessment.",
    )
    parser.add_argument(
        "--clean-cache",
        action="store_true",
        help="Remove all cached snapshot and intermediate files, then exit.",
    )

    return parser



def _resolve_lang(args: argparse.Namespace) -> str:
    """Report language is always Chinese."""
    return "zh"


def _build_categories_from_analyses(analyses: List[ChangeAnalysis]) -> Dict[str, List[str]]:
    """Rebuild category mapping from a list of ChangeAnalysis objects."""
    keys = [
        "feature", "fix", "breaking", "security", "performance",
        "plugin", "api_sdk", "cli", "config", "dependency", "migration",
        "docs", "known_issue", "other",
    ]
    categories: Dict[str, List[str]] = {k: [] for k in keys}
    for item in analyses:
        for key in keys:
            if key in item.categories and item.raw_text not in categories[key]:
                categories[key].append(item.raw_text)
    return categories


# ---------------------------------------------------------------------------
# Recursive merge: file path helpers
# ---------------------------------------------------------------------------

def _leaf_data_path(snapshot_dir: Path, repo: str, target_tag: str, idx: int) -> Path:
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    return snapshot_dir / f"{repo_part}-{target_part}-leaf-{idx:03d}-analysis-data.json"


def _leaf_result_path(snapshot_dir: Path, repo: str, target_tag: str, idx: int) -> Path:
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    return snapshot_dir / f"{repo_part}-{target_part}-leaf-{idx:03d}-llm-results.json"


def _merge_prompt_path(snapshot_dir: Path, repo: str, target_tag: str, depth: int, idx: int) -> Path:
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    return snapshot_dir / f"{repo_part}-{target_part}-merge-d{depth}-{idx:03d}-prompt.txt"


def _merge_result_path(snapshot_dir: Path, repo: str, target_tag: str, depth: int, idx: int) -> Path:
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    return snapshot_dir / f"{repo_part}-{target_part}-merge-d{depth}-{idx:03d}-result.json"


def _recursive_final_path(snapshot_dir: Path, repo: str, target_tag: str) -> Path:
    """Path for the final merged recursive analysis result."""
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    return snapshot_dir / f"{repo_part}-{target_part}-recursive-merged.json"


def _load_snapshot_or_fetch(args: argparse.Namespace) -> Tuple[Release, Optional[Release], List[Release], List[Release], Path]:
    """Load existing snapshot if available and consistent, otherwise fetch from GitHub API."""
    snapshot_dir = Path(args.snapshot_dir) if args.snapshot_dir else Path(default_cache_dir())
    # Try to find an existing snapshot for this target
    target_hint = args.target or "latest-stable"
    snapshot_path = snapshot_path_func(snapshot_dir, args.repo, target_hint)

    if snapshot_path.exists():
        # Run consistency checks before trusting cached data
        llm_results = None
        try:
            target_for_path = args.target or target_hint
            llm_results = llm_results_path(snapshot_dir, args.repo, target_for_path)
        except Exception:
            pass

        # Fetch fresh releases for freshness check (lightweight, single API call)
        fresh_releases: Optional[List[Release]] = None
        try:
            fresh_releases = fetch_releases(args.repo, args.github_token)
        except Exception:
            pass

        consistency = run_full_consistency_check(
            snapshot_path, args, fresh_releases=fresh_releases, llm_results_path=llm_results
        )

        if not consistency.is_valid:
            print(f"Warning: Snapshot consistency check failed for {snapshot_path.name}", file=sys.stderr)
            for err in consistency.errors:
                print(f"  [ERROR] {err}", file=sys.stderr)
            for warn in consistency.warnings:
                print(f"  [WARN]  {warn}", file=sys.stderr)
            print("  → Cleaning up stale intermediates and re-fetching from GitHub API...", file=sys.stderr)
            # Infer target tag from snapshot to clean up intermediates
            try:
                fm = _extract_frontmatter(snapshot_path)
                stale_target = fm.get("target_version", "")
                if stale_target:
                    _cleanup_transient_files(snapshot_dir, args.repo, stale_target)
            except Exception:
                pass
            return refresh_snapshot_and_load(args)

        for warn in consistency.warnings:
            print(f"Warning: [Snapshot] {warn}", file=sys.stderr)

        try:
            snapshot_releases = read_release_snapshot(snapshot_path)
            target, compare, scoped = select_scope(args, snapshot_releases)
            print(f"Info: Using consistent cached snapshot: {snapshot_path.name}", file=sys.stderr)
            return target, compare, scoped, snapshot_releases, snapshot_path
        except Exception:
            pass  # fallback to fresh fetch
    return refresh_snapshot_and_load(args)


# Alias for snapshot path calculation used by _load_snapshot_or_fetch
def snapshot_path_func(snapshot_dir: Path, repo: str, target: str) -> Path:
    """Calculate the snapshot path without side effects."""
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target).strip("-") or "latest-stable"
    return snapshot_dir / f"{repo_part}-{target_part}-release-notes.md"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        # Resolve default snapshot directory
        if args.snapshot_dir is None:
            args.snapshot_dir = default_cache_dir()
        snapshot_dir = Path(args.snapshot_dir)

        # Guard: never write intermediate files into the skill directory
        if _is_inside_skill_dir(snapshot_dir):
            fallback = Path(default_cache_dir())
            print(
                f"Warning: snapshot-dir points inside skill installation ({snapshot_dir}). "
                f"Falling back to {fallback}",
                file=sys.stderr,
            )
            snapshot_dir = fallback
            args.snapshot_dir = str(fallback)

        # --clean-cache: remove all cached files and exit
        if args.clean_cache:
            return _cleanup_all_cache(snapshot_dir)

        # Lazy cleanup of expired cache files on every run
        _cleanup_expired_cache(snapshot_dir)

        # -------------------------------------------------------------------
        # Token verification (before any mode logic)
        # -------------------------------------------------------------------
        resolved_token = get_github_token(args.github_token)
        token_valid, token_error = verify_github_token(resolved_token)
        lang = _resolve_lang(args)
        strings = _zh()

        if token_valid:
            args.github_token = resolved_token
            print("TOKEN_STATUS: valid", file=sys.stderr)
            print(f"Info: {strings['token_valid_info']}", file=sys.stderr)
        else:
            print("TOKEN_STATUS: invalid", file=sys.stderr)
            if resolved_token:
                print(f"{strings['token_invalid_warning']} ({token_error})", file=sys.stderr)
            else:
                print(f"{strings['token_missing_warning']}", file=sys.stderr)
            raise RuntimeError(
                "无法继续分析：GitHub token 无效或缺失。"
                "本分析工具要求有效的 GitHub token 来获取 commits 和 diff 数据，"
                "这是 LLM 增强分析的必要前提。"
                "请通过 --github-token 参数或 GITHUB_TOKEN 环境变量提供有效 token。"
            )

        # -------------------------------------------------------------------
        # Internal helper: prepare analysis data (shared by Mode A and Mode C)
        # -------------------------------------------------------------------
        def _run_prepare_analysis_data_mode() -> int:
            target, compare, scoped, releases, snapshot = refresh_snapshot_and_load(args)
            _lang = _resolve_lang(args)

            _cleanup_transient_files(snapshot_dir, args.repo, target.tag_name)

            import concurrent.futures

            def _do_rule_analysis() -> List[ChangeAnalysis]:
                return analyze_release_notes(scoped, _lang)

            def _do_diff_fetch() -> List[Dict[str, Any]]:
                if not compare:
                    return []
                try:
                    all_files = fetch_compare_diff(
                        args.repo, compare.tag_name, target.tag_name, args.github_token
                    )
                    return select_important_files(all_files)
                except Exception as exc:
                    print(f"Warning: Could not fetch compare diff: {exc}", file=sys.stderr)
                    return []

            def _do_commit_fetch() -> List[CommitInfo]:
                if not compare:
                    return []
                try:
                    all_commits = fetch_compare_commits(
                        args.repo, compare.tag_name, target.tag_name, args.github_token
                    )
                    return select_relevant_commits(all_commits)
                except Exception as exc:
                    print(f"Warning: Could not fetch compare commits: {exc}", file=sys.stderr)
                    return []

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                future_analysis = executor.submit(_do_rule_analysis)
                future_diff = executor.submit(_do_diff_fetch)
                future_commits = executor.submit(_do_commit_fetch)
                analyses = future_analysis.result()
                diff_files = future_diff.result()
                commits = future_commits.result()

            # Build single master analysis data file
            data = build_analysis_data(
                args.repo, target, compare, analyses, commits, diff_files, _lang, scoped
            )
            data_path = analysis_data_path(snapshot_dir, args.repo, target.tag_name)
            write_analysis_data(data, data_path)

            base_path = base_analysis_path(snapshot_dir, args.repo, target.tag_name)
            write_base_analysis(analyses, base_path)

            # Auto-evaluate whether chunking is needed
            needs_chunking, est_tokens = should_use_chunking(data)

            if needs_chunking or args.prepare_chunks:
                # Automatic chunking: split data into chunks for distributed processing
                chunk_paths = split_analysis_data_into_chunks(
                    data, snapshot_dir, args.repo, target.tag_name
                )
                print(f"ANALYSIS_DATA_READY: 1")
                print(f"DATA: {data_path}")
                print(f"BASE_ANALYSIS: {base_path}")
                print(f"CHUNKING_REQUIRED: 1")
                print(f"ESTIMATED_TOKENS: {est_tokens}")
                print(f"CHUNK_COUNT: {len(chunk_paths)}")
                for i, cp in enumerate(chunk_paths):
                    print(f"CHUNK_{i}: {cp}")
                print(f"MERGE_COMMAND: --merge-chunk-results")
                # Auto-detect existing chunk results
                existing_results = discover_chunk_results(snapshot_dir, args.repo, target.tag_name)
                if existing_results:
                    print(f"CHUNK_RESULTS_FOUND: {len(existing_results)}")
                    for i, rp in enumerate(existing_results):
                        print(f"CHUNK_RESULT_{i}: {rp}")
            else:
                print(f"ANALYSIS_DATA_READY: 1")
                print(f"DATA: {data_path}")
                print(f"BASE_ANALYSIS: {base_path}")
                print(f"CHUNKING_REQUIRED: 0")
                print(f"ESTIMATED_TOKENS: {est_tokens}")

            # Auto-detect existing llm-results.json from previous run
            results_path = llm_results_path(snapshot_dir, args.repo, target.tag_name)
            if results_path.exists():
                print(f"LLM_RESULTS_CACHED: {results_path}")

            return 0

        # -------------------------------------------------------------------
        # Internal helper: merge chunk results
        # -------------------------------------------------------------------
        def _run_merge_chunk_results_mode() -> int:
            target_for_path = args.target or "latest-stable"
            if target_for_path == "latest-stable" and not args.target:
                try:
                    _releases = fetch_releases(args.repo, args.github_token)
                    _stable = stable_releases(_releases)
                    if _stable:
                        target_for_path = _stable[0].tag_name
                except Exception:
                    pass

            chunk_results = discover_chunk_results(snapshot_dir, args.repo, target_for_path)
            if not chunk_results:
                print(f"Error: No chunk result files found for {args.repo} {target_for_path}", file=sys.stderr)
                print(f"Searched in: {snapshot_dir}", file=sys.stderr)
                return 1

            output_path = llm_results_path(snapshot_dir, args.repo, target_for_path)
            enhancement_info = merge_chunk_results(chunk_results, output_path)
            print(f"CHUNK_MERGE_COMPLETE: 1")
            print(f"LLM_RESULTS: {output_path}")
            if enhancement_info.get("enhancement_needed"):
                print(f"ENHANCEMENT_NEEDED: 1")
                print(f"ENHANCEMENT_PROMPT: {enhancement_info.get('enhancement_prompt_path', '')}")
                print(f"NEEDS_FIELDS: {','.join(enhancement_info.get('needs_fields', []))}")
            return 0

        # -------------------------------------------------------------------
        # Mode A: Prepare analysis data and exit
        # -------------------------------------------------------------------
        if args.prepare_analysis_data or args.generate_llm_prompt or args.prepare_chunks:
            return _run_prepare_analysis_data_mode()

        # -------------------------------------------------------------------
        # Mode A.5: Merge chunk results
        # -------------------------------------------------------------------
        if args.merge_chunk_results:
            return _run_merge_chunk_results_mode()

        # -------------------------------------------------------------------
        # Mode R: Recursive merge aggregation
        # -------------------------------------------------------------------
        if args.recursive_analysis:
            # Load snapshot
            target, compare, scoped, releases, snapshot = refresh_snapshot_and_load(args)
            _lang = _resolve_lang(args)

            # Degenerate case: single version or too few versions
            if len(scoped) < RECURSIVE_MERGE_MIN_VERSIONS:
                print(
                    f"Info: Only {len(scoped)} version(s) in scope; "
                    f"falling back to standard single-pass analysis.",
                    file=sys.stderr,
                )
                # Fall through to standard Mode C / Mode B flow
            else:
                _cleanup_transient_files(snapshot_dir, args.repo, target.tag_name)

                import concurrent.futures

                def _do_rule_analysis() -> List[ChangeAnalysis]:
                    return analyze_release_notes(scoped, _lang)

                def _do_diff_fetch() -> List[Dict[str, Any]]:
                    if not compare:
                        return []
                    try:
                        all_files = fetch_compare_diff(
                            args.repo, compare.tag_name, target.tag_name, args.github_token
                        )
                        return select_important_files(all_files)
                    except Exception as exc:
                        print(f"Warning: Could not fetch compare diff: {exc}", file=sys.stderr)
                        return []

                def _do_commit_fetch() -> List[CommitInfo]:
                    if not compare:
                        return []
                    try:
                        all_commits = fetch_compare_commits(
                            args.repo, compare.tag_name, target.tag_name, args.github_token
                        )
                        return select_relevant_commits(all_commits)
                    except Exception as exc:
                        print(f"Warning: Could not fetch compare commits: {exc}", file=sys.stderr)
                        return []

                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    future_analysis = executor.submit(_do_rule_analysis)
                    future_diff = executor.submit(_do_diff_fetch)
                    future_commits = executor.submit(_do_commit_fetch)
                    analyses = future_analysis.result()
                    diff_files = future_diff.result()
                    commits = future_commits.result()

                # Run recursive analysis
                final_report, missing = analyze_recursive(
                    repo=args.repo,
                    scoped_releases=list(scoped),
                    all_analyses=analyses,
                    all_commits=commits,
                    all_diff_files=diff_files,
                    lang=_lang,
                    github_token=args.github_token,
                    snapshot_dir=snapshot_dir,
                )

                if missing:
                    print(f"\n=== Recursive Analysis: {len(missing)} item(s) need LLM processing ===", file=sys.stderr)
                    for m in missing:
                        print(f"  MISSING: {m}", file=sys.stderr)
                    print(
                        "\nPlease run LLM analysis on the above files and save results to the "
                        "corresponding result paths, then re-run with --recursive-analysis.",
                        file=sys.stderr,
                    )
                    return 1

                if final_report is None:
                    print("Error: Recursive analysis failed to produce a final report.", file=sys.stderr)
                    return 1

                # Save final merged result as the canonical llm-results.json
                final_path = llm_results_path(snapshot_dir, args.repo, target.tag_name)
                final_path.parent.mkdir(parents=True, exist_ok=True)
                # Convert LLMFullReport to dict for serialization
                final_dict = {
                    "executive_summary": {
                        "recommendation": final_report.executive_summary.recommendation,
                        "theme": final_report.executive_summary.theme,
                        "magnitude": final_report.executive_summary.magnitude,
                        "reason": final_report.executive_summary.reason,
                        "top_changes": final_report.executive_summary.top_changes,
                        "one_liner": final_report.executive_summary.one_liner,
                    },
                    "developer_conclusion": final_report.developer_conclusion,
                    "themes": [
                        {
                            "theme_id": t.theme_id,
                            "theme_name": t.theme_name,
                            "note_ids": t.note_ids,
                            "raw_texts": t.raw_texts,
                            "primary_category": t.primary_category,
                            "risk_level": t.risk_level,
                            "summary": t.summary,
                            "impact": t.impact,
                            "related_commits": t.related_commits,
                            "affected_files": t.affected_files,
                            "confidence": t.confidence,
                            "has_hidden_breaking": t.has_hidden_breaking,
                            "hidden_risks": t.hidden_risks,
                            "reasoning": t.reasoning,
                        }
                        for t in final_report.themes
                    ],
                    "detailed_notes": [
                        {
                            "note_id": n.note_id,
                            "component": n.component,
                            "categories": n.categories,
                            "risk_level": n.risk_level,
                            "interpretation": n.interpretation,
                            "action_items": n.action_items,
                            "audience": n.audience,
                            "matched_commits": n.matched_commits,
                            "affected_files": n.affected_files,
                            "has_hidden_breaking": n.has_hidden_breaking,
                            "reasoning": n.reasoning,
                        }
                        for n in final_report.detailed_notes
                    ],
                    "compatibility_risks": [
                        {"component": cr.component, "description": cr.description}
                        for cr in final_report.compatibility_risks
                    ],
                    "test_points": final_report.test_points,
                    "shadow_changes": final_report.shadow_changes,
                    "progressive_fixes": [
                        {
                            "fix_id": pf.fix_id,
                            "issue_description": pf.issue_description,
                            "stages": pf.stages,
                            "final_status": pf.final_status,
                            "impact_assessment": pf.impact_assessment,
                            "affected_components": pf.affected_components,
                        }
                        for pf in final_report.progressive_fixes
                    ],
                    "version_evolution": [
                        {
                            "evolution_id": ve.evolution_id,
                            "description": ve.description,
                            "affected_versions": ve.affected_versions,
                            "individual_risk": ve.individual_risk,
                            "cumulative_risk": ve.cumulative_risk,
                            "risk_escalation_reason": ve.risk_escalation_reason,
                            "related_themes": ve.related_themes,
                            "affected_components": ve.affected_components,
                            "migration_advice": ve.migration_advice,
                        }
                        for ve in final_report.version_evolution
                    ],
                }
                final_path.write_text(json.dumps(final_dict, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"RECURSIVE_MERGE_COMPLETE: 1")
                print(f"LLM_RESULTS: {final_path}")

                # Generate report using the recursive result
                categories = _build_categories_from_analyses(analyses)
                if args.output:
                    output_path = Path(args.output)
                else:
                    output_path = Path.cwd() / f"{snapshot.stem}-analysis.md"

                report = render_report(
                    repo=args.repo,
                    target=target,
                    compare=compare,
                    scoped=scoped,
                    releases=releases,
                    include_beta=args.include_beta,
                    lang=_lang,
                    data_source="Fresh GitHub Releases API + Compare Diff + Recursive LLM Merge Analysis",
                    snapshot_file=str(snapshot),
                    output_file=str(output_path),
                    analyses=analyses,
                    categories=categories,
                    llm_report=final_report,
                )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(report, encoding="utf-8")
                print(str(output_path))
                return 0

        # -------------------------------------------------------------------
        # Mode C: Default — token-aware routing (check BEFORE Mode B)
        # -------------------------------------------------------------------
        # If token is valid, auto-trigger analysis data preparation
        if token_valid and not args.apply_llm_results:
            # Resolve actual target tag for cache path (handles --latest mode)
            target_for_path = args.target
            if not target_for_path:
                try:
                    _releases = fetch_releases(args.repo, args.github_token)
                    _stable = stable_releases(_releases)
                    if _stable:
                        target_for_path = _stable[0].tag_name
                except Exception:
                    pass
            if not target_for_path:
                target_for_path = "latest-stable"

            # Check if cached llm-results.json exists from a previous run
            results_path = llm_results_path(snapshot_dir, args.repo, target_for_path)
            if results_path.exists():
                # Verify LLM results consistency with the associated snapshot
                snapshot_for_results = snapshot_path_func(snapshot_dir, args.repo, target_for_path)
                llm_consistency = verify_llm_results_consistency(results_path, snapshot_for_results)
                if not llm_consistency.is_valid:
                    print(
                        f"Warning: Cached LLM results failed consistency check; discarding.",
                        file=sys.stderr,
                    )
                    for err in llm_consistency.errors:
                        print(f"  [ERROR] {err}", file=sys.stderr)
                    try:
                        results_path.unlink()
                    except OSError:
                        pass
                    # Fall through to prepare fresh analysis data
                    print(
                        "Info: Valid token detected; entering LLM-enhanced analysis mode.",
                        file=sys.stderr,
                    )
                    return _run_prepare_analysis_data_mode()
                for warn in llm_consistency.warnings:
                    print(f"Warning: [LLM Results] {warn}", file=sys.stderr)
                print(
                    f"Info: Found cached LLM results at {results_path}; applying directly.",
                    file=sys.stderr,
                )
                args.apply_llm_results = str(results_path)
                # Continue to Mode B below
            else:
                print(
                    "Info: Valid token detected; entering LLM-enhanced analysis mode.",
                    file=sys.stderr,
                )
                return _run_prepare_analysis_data_mode()

        # -------------------------------------------------------------------
        # Mode B: Apply LLM results and generate final report
        # -------------------------------------------------------------------
        if args.apply_llm_results:
            llm_results_file = Path(args.apply_llm_results)
            if not llm_results_file.exists():
                raise RuntimeError(f"LLM results file not found: {llm_results_file}")

            # P1: Avoid re-fetching from GitHub API — use cached snapshot if available
            target, compare, scoped, releases, snapshot = _load_snapshot_or_fetch(args)
            lang = _resolve_lang(args)

            # Load cached base analysis or recompute
            # Validate that cached base analysis matches current snapshot before reuse
            base_path = base_analysis_path(snapshot_dir, args.repo, target.tag_name)
            analyses: List[ChangeAnalysis] = []
            if base_path.exists():
                cached_analyses = read_base_analysis(base_path)
                cached_tags = {a.release_tag for a in cached_analyses}
                current_tags = {r.tag_name for r in scoped}
                if cached_tags == current_tags:
                    analyses = cached_analyses
                else:
                    print(
                        f"Warning: Cached base analysis tags mismatch "
                        f"(cached: {sorted(cached_tags)}, current: {sorted(current_tags)}); "
                        f"recomputing...",
                        file=sys.stderr,
                    )
                    try:
                        base_path.unlink()
                    except OSError:
                        pass
                    analyses = analyze_release_notes(scoped, lang)
            else:
                analyses = analyze_release_notes(scoped, lang)
            categories = _build_categories_from_analyses(analyses)

            # Parse LLM full report (LLM performs ALL semantic analysis)
            llm_report = parse_llm_results(llm_results_file)

            # Generate report using LLM output directly
            if args.output:
                output_path = Path(args.output)
            else:
                output_path = Path.cwd() / f"{snapshot.stem}-analysis.md"

            report = render_report(
                repo=args.repo,
                target=target,
                compare=compare,
                scoped=scoped,
                releases=releases,
                include_beta=args.include_beta,
                lang=lang,
                data_source="Fresh GitHub Releases API + Compare Diff + LLM analysis",
                snapshot_file=str(snapshot),
                output_file=str(output_path),
                analyses=analyses,
                categories=categories,
                llm_report=llm_report,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")
            print(str(output_path))

            # P1-5: In --apply-llm-results mode, keep transient files for
            # potential re-runs. They are cleaned up by _cleanup_expired_cache
            # on subsequent runs or when the snapshot becomes stale.
            _cleanup_legacy_prompts(snapshot_dir, args.repo, target.tag_name)
            return 0

        # LLM analysis is mandatory. This code path should not be reached
        # because token validation above raises an error when token is invalid.
        raise RuntimeError(
            "无法继续分析：缺少 LLM 分析结果。"
            "本分析工具要求通过 LLM 增强分析来获取高质量的分析结果。"
            "请确保已提供有效的 GitHub token，让脚本进入 LLM 分析数据准备模式，"
            "然后由 AI agent 执行 LLM 分析后再生成报告。"
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
