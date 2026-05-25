"""Core data models for the OpenClaw Release Analyzer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Release:
    tag_name: str
    name: str
    body: str
    html_url: str
    published_at: str
    prerelease: bool
    draft: bool

    @property
    def normalized_tag(self) -> str:
        return normalize_version(self.tag_name)

    @property
    def is_stable(self) -> bool:
        return not self.draft and not self.prerelease and not is_prerelease_name(self.tag_name, self.name)


@dataclass
class ChangeAnalysis:
    release_tag: str
    raw_text: str
    primary_category: str
    categories: List[str]
    component: str
    interpretation: str
    risk_level: str
    audience: List[str]
    action_items: List[str]
    confidence: str
    priority: int
    # LLM diff-analysis enrichment
    affected_files: List[str] = field(default_factory=list)
    llm_enhanced: bool = False
    code_evidence: str = ""
    llm_reasoning: str = ""
    note_id: str = ""


def normalize_version(value: str) -> str:
    value = (value or "").strip()
    return value[1:] if value.lower().startswith("v") else value


def version_key(value: str) -> Tuple[int, int, int, str]:
    text = normalize_version(value)
    match = re.search(r"(\d+)\.(\d+)\.(\d+)(?:[-+.]?(.+))?", text)
    if not match:
        return (0, 0, 0, text)
    major, minor, patch, suffix = match.groups()
    return (int(major), int(minor), int(patch), suffix or "")


@dataclass
class CommitInfo:
    """A simplified commit entry from GitHub Compare API."""
    sha: str
    message: str
    author_name: str
    changed_files: List[str] = field(default_factory=list)
    relevance_score: int = 0


@dataclass
class Theme:
    """A semantic cluster of related release notes, produced by LLM thematic analysis."""
    theme_id: str
    theme_name: str
    note_ids: List[str] = field(default_factory=list)
    raw_texts: List[str] = field(default_factory=list)
    primary_category: str = "other"
    risk_level: str = "low"
    summary: str = ""
    impact: str = ""
    related_commits: List[str] = field(default_factory=list)
    affected_files: List[str] = field(default_factory=list)
    confidence: str = "medium"
    has_hidden_breaking: bool = False
    hidden_risks: str = ""
    reasoning: str = ""


@dataclass
class LLMExecutiveSummary:
    """Executive summary produced entirely by LLM semantic analysis."""
    recommendation: str = ""
    theme: str = ""
    magnitude: str = ""
    reason: str = ""
    top_changes: List[Dict[str, Any]] = field(default_factory=list)
    one_liner: str = ""


@dataclass
class LLMCompatibilityRisk:
    """A single compatibility risk entry produced by LLM."""
    component: str = ""
    description: str = ""


@dataclass
class LLMNoteAnalysis:
    """Per-note deep analysis produced entirely by LLM."""
    note_id: str = ""
    component: str = ""
    categories: List[str] = field(default_factory=list)
    risk_level: str = "low"
    interpretation: str = ""
    action_items: List[str] = field(default_factory=list)
    audience: List[str] = field(default_factory=list)
    matched_commits: List[str] = field(default_factory=list)
    affected_files: List[str] = field(default_factory=list)
    has_hidden_breaking: bool = False
    reasoning: str = ""


@dataclass
class ProgressiveFix:
    """A progressive fix chain detected across multiple versions.

    Represents an issue that was addressed incrementally across releases,
    e.g., partial mitigation in v1 → refinement in v2 → complete fix in v3.
    """
    fix_id: str = ""
    issue_description: str = ""
    stages: List[Dict[str, Any]] = field(default_factory=list)
    final_status: str = ""  # "fully_fixed", "partially_fixed", "mitigated"
    impact_assessment: str = ""
    affected_components: List[str] = field(default_factory=list)


@dataclass
class VersionEvolution:
    """Cumulative breaking change assessment across a version range.

    Captures cases where individual versions appear low-risk but the
    aggregate impact across the upgrade path is high.
    """
    evolution_id: str = ""
    description: str = ""
    affected_versions: List[str] = field(default_factory=list)
    individual_risk: str = "low"  # per-version risk
    cumulative_risk: str = "low"  # aggregate risk across the range
    risk_escalation_reason: str = ""  # why cumulative > individual
    related_themes: List[str] = field(default_factory=list)
    affected_components: List[str] = field(default_factory=list)
    migration_advice: str = ""


@dataclass
class LLMFullReport:
    """Complete analysis report produced by LLM.

    When LLM analysis is available, the renderer uses these fields directly
    instead of falling back to rule-based templates.
    """
    executive_summary: LLMExecutiveSummary = field(default_factory=LLMExecutiveSummary)
    developer_conclusion: str = ""
    themes: List[Theme] = field(default_factory=list)
    detailed_notes: List[LLMNoteAnalysis] = field(default_factory=list)
    compatibility_risks: List[LLMCompatibilityRisk] = field(default_factory=list)
    test_points: List[str] = field(default_factory=list)
    shadow_changes: List[Dict[str, Any]] = field(default_factory=list)
    # Cross-version upgrade analysis (optimizations #3 and #4)
    progressive_fixes: List[ProgressiveFix] = field(default_factory=list)
    version_evolution: List[VersionEvolution] = field(default_factory=list)


def is_prerelease_name(*values: str) -> bool:
    text = " ".join(v or "" for v in values).lower()
    return any(token in text for token in ["alpha", "beta", "-rc", ".rc", "rc.", "preview", "next"])
