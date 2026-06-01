"""Configuration constants for the OpenClaw Release Notes Analyzer.

This module contains all tunable constants, keyword lists, patterns,
and budget parameters used across the analyzer.
"""

from __future__ import annotations

import os
import platform
import re
from typing import Dict, List, Tuple

DEFAULT_REPO = "openclaw/openclaw"
API_ROOT = "https://api.github.com"


# ---------------------------------------------------------------------------
# Category keywords
# ---------------------------------------------------------------------------

KEYWORDS = {
    "plugin": [
        "plugin", "plugins", "manifest", "hook", "hooks", "lifecycle", "loader",
        "registry", "runtime", "extension", "extensions", "sandbox", "capability", "capabilities",
        "@openclaw/",
    ],
    "api_sdk": [
        "api", "sdk", "public api", "method", "signature", "parameter", "return",
        "type", "typescript", "export", "package", "deprecated", "deprecation", "migration",
        "migrate", "breaking", "compatibility", "OpenClawAPI",
        "peerDependencies", "peer dependency",
    ],
    "security": [
        "security", "vulnerability", "cve", "cwe", "cvss",
        "auth", "authentication", "authorization",
        "permission", "sandbox", "escape", "xss", "csrf", "rce",
        "remote code execution", "injection", "secret", "credential",
        "affected version", "affected versions", "oauth", "sso",
    ],
    "performance": [
        "performance", "perf", "optimize", "optimization", "speed", "latency", "memory",
        "leak", "crash", "hang", "deadlock", "race", "stability", "reliability", "timeout",
        "freeze", "startup", "benchmark",
        "data loss",
    ],
    "breaking": [
        "breaking", "breaking change", "incompatible", "removed", "remove", "renamed",
        "rename", "migration", "migrate", "deprecated", "deprecation", "requires node",
        "minimum node", "node.js", "config", "schema", "cli", "flag",
        "rollback", "downgrade",
    ],
    "feature": [
        "feature", "add", "added", "new", "support", "introduce", "introduced", "enable",
        "enhancement", "improvement",
    ],
    "fix": [
        "fix", "fixed", "bug", "resolve", "resolved", "patch", "correct", "regression", "issue",
        "known issue",
    ],
    "cli": [
        "cli", "command", "flag", "option", "argument", "subcommand",
        "bash", "shell", "terminal", "stdout", "stderr",
    ],
    "config": [
        "config", "configuration", "setting", "option", "default", "schema",
        "openclaw.config", ".openclawrc", "manifest.json",
    ],
    "dependency": [
        "dependency", "dependencies", "peer dependency", "peerDependencies",
        "require", "package.json", "npm", "yarn", "pnpm", "lockfile",
        "install", "uninstall", "version",
    ],
    "migration": [
        "migration", "migrate", "upgrade guide", "breaking change",
        "deprecated", "deprecation", "breaking", "incompatible",
        "before you upgrade", "migration guide", "upgrade notes",
    ],
    "docs": [
        "docs", "documentation", "readme", "changelog", "guide",
        "tutorial", "example", "demo",
    ],
    "known_issue": [
        "known issue", "known issues", "limitation", "workaround",
        "not supported", "deprecated", "upcoming", "planned",
    ],
}

ZH_KEYWORDS = {
    "plugin": ["插件", "hook", "生命周期", "manifest", "扩展"],
    "api_sdk": ["api", "sdk", "公共接口", "方法", "签名", "参数", "类型", "导出", "废弃", "迁移"],
    "security": ["安全", "漏洞", "cve", "认证", "授权", "权限", "注入", "凭据"],
    "performance": ["性能", "优化", "速度", "延迟", "内存", "泄漏", "崩溃", "卡顿", "稳定性"],
    "breaking": ["破坏性变更", "breaking", "不兼容", "移除", "重命名", "迁移", "废弃", "最低要求"],
    "feature": ["新增", "新功能", "添加", "支持", "特性", "改进"],
    "fix": ["修复", "bug", "问题", "修正", "补丁"],
    "cli": ["命令行", "cli", "命令", "flag", "参数"],
    "config": ["配置", "config", "配置文件", "默认配置", "schema"],
    "dependency": ["依赖", "dependencies", "版本要求", "package.json"],
    "migration": ["迁移", "升级指南", "breaking change", "废弃"],
    "docs": ["文档", "docs", "readme", "指南"],
    "known_issue": ["已知问题", "限制", "已知限制"],
}

SECTION_HINTS = {
    "feature": [
        "feature", "features", "enhancement", "enhancements", "new", "added", "what's changed",
        "🚀 feature", "🚀 features", "✨", "✨ feature", "✨ features",
        "新增", "新功能", "新特性", "功能新增",
    ],
    "fix": [
        "fix", "fixes", "bug", "bug fixes", "bugfix", "patch",
        "🐛 fix", "🐛 fixes", "🐛 bug", "bug fix",
        "修复", "bug 修复", "问题修复",
    ],
    "breaking": [
        "breaking", "breaking changes", "migration", "upgrade notes",
        "💥 breaking", "⚠️ breaking",
        "破坏性变更", "breaking change", "不兼容", "迁移", "升级注意",
    ],
    "security": [
        "security", "vulnerability", "cve",
        "🔒 security", "🔐",
        "安全", "安全修复", "漏洞修复",
    ],
    "performance": [
        "performance", "stability", "reliability",
        "⚡ performance", "⚡ perf", "🚀",
        "性能", "性能优化", "稳定性",
    ],
    "cli": [
        "cli", "command", "command-line",
        "命令行",
    ],
    "config": [
        "config", "configuration", "setting", "settings",
        "配置",
    ],
    "dependency": [
        "dependency", "dependencies", "requirement", "requirements",
        "依赖",
    ],
    "docs": [
        "doc", "docs", "documentation", "changelog",
        "文档",
    ],
    "known_issue": [
        "known issue", "known issues", "limitation", "limitations",
        "已知问题", "限制",
    ],
}


# ---------------------------------------------------------------------------
# Conventional commit pattern
# ---------------------------------------------------------------------------

CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([\w-]+\))?(!)?:\s+(.+)$",
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Diff analysis configuration
# ---------------------------------------------------------------------------

# Importance scores for files when selecting which diffs to send to LLM.
# Positive = more important for plugin/API/developer impact analysis.
# Negative = less important (tests, docs, CI-only).
FILE_IMPORTANCE_PATTERNS: List[Tuple[str, int]] = [
    (r"src/plugin[s]?/", 10),
    (r"src/hook[s]?/", 10),
    (r"src/api/", 10),
    (r"packages/sdk/", 10),
    (r"packages/core/", 10),
    (r"src/manifest", 8),
    (r"src/loader", 8),
    (r"src/registry", 8),
    (r"src/cli/", 8),
    (r"src/config/", 8),
    (r"packages/cli/", 8),
    (r"package\.json", 10),
    (r"pnpm-lock", 6),
    (r"tsconfig", 5),
    (r"src/gateway", 6),
    (r"src/sidecar", 6),
    (r"src/channel", 6),
    (r"test[s]?/", -5),
    (r"__tests?__/", -5),
    (r"\.test\.", -5),
    (r"\.spec\.", -5),
    (r"e2e/", -4),
    (r"docs?/", -3),
    (r"\.md$", -3),
    (r"\.yml$", -2),
    (r"\.yaml$", -2),
    (r"\.github/", -2),
]

MAX_DIFF_FILES = 25
MAX_PATCH_LINES_PER_FILE = 80
MAX_TOTAL_DIFF_CHARS = 80_000

NO_DIFF_COMPONENTS: set[str] = {
    "Docs", "Tests", "CI/CD", "Internal", "Changelog",
    "README", "Contributing", "License",
}

NO_DIFF_KEYWORDS: set[str] = {
    "docs", "documentation", "readme", "changelog",
    "test", "tests", "testing", "fixture", "fixtures", "mock", "mocks",
    "ci", "github actions", "workflow", ".yml", ".yaml",
    "lint", "format", "formatting", "style", "typo", "spelling",
    "refactor", "internal", "cleanup", "housekeeping",
}

# ---------------------------------------------------------------------------
# Commit-level analysis configuration (replaces component-diff path matching)
# ---------------------------------------------------------------------------

# Maximum commits to include in analysis data.
# Commits are scored by relevance (files touched + message keywords);
# top N are kept to stay within token budgets.
MAX_COMMITS_FOR_ANALYSIS = 80

# Maximum size of the analysis-data.json file in characters.
# This prevents the LLM prompt from growing unbounded.
MAX_ANALYSIS_DATA_CHARS = 120_000

# Commit message patterns that indicate high relevance for release-note matching.
# Used to score commits when selecting the top N.
COMMIT_RELEVANCE_PATTERNS: List[Tuple[str, int]] = [
    # Plugin / SDK surface
    (r"\bplugin\b|\bplugins\b|\bmanifest\b|\bhook\b|\bhooks\b|\bloader\b|\bregistry\b", 10),
    (r"\bapi\b|\bsdk\b|\bexport\b|\btype\b|\bsignature\b|\bdeprecated\b", 8),
    # CLI / Config
    (r"\bcli\b|\bcommand\b|\bflag\b|\boption\b|\bconfig\b|\bconfiguration\b|\bschema\b", 8),
    # Security
    (r"\bsecurity\b|\bvulnerability\b|\bcve\b|\bauth\b|\bauth(entication|orization)\b|\bcredential\b|\bsecret\b", 10),
    # Breaking / Migration
    (r"\bbreaking\b|\bmigration\b|\bdeprecated\b|\bremove\b|\bremov(e|ed|al)\b|\brename\b|\brequire\b", 9),
    # Dependency / Runtime
    (r"\bdependenc\b|\bpackage\.json\b|\bpeerdependenc\b|\bnode\b|\bruntime\b", 7),
    # Performance / Stability
    (r"\bperf\b|\bperformance\b|\boptimiz\b|\bmemory\b|\bleak\b|\bcrash\b|\bdeadlock\b|\brace\b", 6),
    # Fix
    (r"\bfix\b|\bfixed\b|\bbug\b|\bresolve\b|\bpatch\b|\bregression\b", 4),
    # Feature
    (r"\bfeat\b|\bfeature\b|\badd\b|\bnew\b|\bsupport\b|\benhance\b", 3),
]

# Files that are typically noise for release-note-to-code association.
# Commits touching ONLY these files get a relevance penalty.
NOISE_FILE_PATTERNS: List[str] = [
    r"\.gitignore$",
    r"\.npmrc$",
    r"\.oxfmtrc",
    r"\.oxlintrc",
    r"\.semgrepignore$",
    r"\.editorconfig$",
    r"\.prettierrc",
    r"^\.github/",
    r"^docs?/",
    r"^\.changeset/",
    r"^CHANGELOG",
    r"\.md$",
]



# ---------------------------------------------------------------------------
# Category ordering
# ---------------------------------------------------------------------------

CATEGORY_PRIMARY_ORDER = [
    "breaking", "security", "migration", "dependency", "plugin", "api_sdk",
    "cli", "config", "performance", "fix", "feature", "docs", "known_issue", "other",
]


# ---------------------------------------------------------------------------
# Data partitioning configuration for large analysis datasets
# ---------------------------------------------------------------------------

# When analysis data exceeds the capacity of a single processing unit
# (context window, memory budget, API payload limit), it is automatically
# partitioned into smaller chunks. This supports multiple execution modes:
#
#   Mode A — External AI agent: Script partitions data → AI agent (Claude Code,
#            ChatGPT, custom agent) reads each chunk, performs semantic analysis,
#            writes structured results → Script merges results.
#
#   Mode B — Built-in LLM API: Script partitions data → Script calls LLM API
#            directly for each chunk → Script merges results.
#
#   Mode C — Streaming / pipelining: Script streams chunks to a consumer
#            which processes them incrementally without intermediate files.
#
# The parameters below control the partitioning strategy only. They are
# independent of which execution mode is used.

# Token estimation multiplier for JSON content.
# ~1.3 for mixed CJK+English; adjust for your content language ratio.
TOKENS_PER_CHAR = 1.3

# Maximum tokens per analysis chunk. Should be set based on the target
# processor's capacity minus headroom for instructions and output.
# Examples: 200K context window → 100K safe; 128K → 80K; 32K → 20K.
MAX_TOKENS_PER_CHUNK = 100_000

# Maximum release notes per chunk. Limits partition size to maintain
# consistent analysis depth regardless of total dataset size.
CHUNK_MAX_NOTES = 80

# Maximum commits referenced per chunk. Keeps commit context focused
# on the notes in the same partition.
CHUNK_MAX_COMMITS = 25

# Overlap between adjacent chunks. Duplicates N notes across boundaries
# to preserve semantic continuity (e.g., a theme spanning a boundary).
CHUNK_OVERLAP_NOTES = 5

# When estimated tokens exceed this ratio of MAX_TOKENS_PER_CHUNK,
# automatic partitioning triggers. Default 0.8 (80%) leaves safety margin.
CHUNKING_THRESHOLD_RATIO = 0.8

# Partition file naming patterns. These are intermediate artifacts;
# their lifecycle is managed by the script (created on demand, cleaned
# after report generation).
CHUNK_DATA_PATTERN = "{repo}-{target}-analysis-chunk-{idx:03d}.json"
CHUNK_RESULT_PATTERN = "{repo}-{target}-analysis-result-chunk-{idx:03d}.json"

# ---------------------------------------------------------------------------
# Cache and prompt parameters
# ---------------------------------------------------------------------------

LLM_RESULTS_TTL_DAYS = 7
RELEASE_NOTES_MAX_VERSIONS = 20

# ---------------------------------------------------------------------------
# Semantic deduplication settings
# ---------------------------------------------------------------------------

# Stop words removed when building semantic deduplication signatures.
# These are common English and Chinese words that don't help distinguish
# between different changes. Words shorter than this are also removed.
SEMANTIC_DEDUP_STOP_WORDS: set[str] = {
    # English
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "during",
    "before", "after", "above", "below", "between", "among", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "must", "can",
    "this", "that", "these", "those", "i", "you", "he", "she", "it", "we",
    "they", "me", "him", "her", "us", "them", "my", "your", "his", "its",
    "our", "their", "am", "was", "were", "s", "t", "just", "don", "now",
    "ll", "m", "o", "re", "ve", "y", "ma", "d", "ll", "won", "ain",
    # Conventional-commit prefixes (already implied by structure)
    "fix", "feat", "chore", "docs", "refactor", "perf", "test", "build",
    "ci", "style", "revert", "update", "add", "remove", "support",
    "improve", "enhance", "change", "use", "using", "new", "adds",
    "fixes", "updates", "removes", "changed", "improved", "enhanced",
    "supported", "added", "removed", "fixed", "updated",
    # Common verbs/adverbs
    "when", "where", "what", "how", "why", "who", "which", "if", "then",
    "else", "also", "too", "very", "much", "many", "more", "most", "some",
    "any", "all", "none", "no", "not", "only", "just", "still", "already",
    "yet", "even", "so", "such", "than", "as", "like", "per", "via",
    "over", "under", "again", "further", "once", "here", "there", "other",
    "another", "each", "every", "both", "either", "neither", "one", "two",
    "first", "last", "next", "previous", "same", "different",
    # Chinese stop words
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这", "那",
}

# Minimum number of signature words for semantic dedup to trigger.
# Signatures shorter than this are considered too generic and are ignored.
SEMANTIC_DEDUP_MIN_WORDS = 3

# Similarity threshold for semantic dedup (0.0-1.0).
# Two items with similarity >= this value are considered duplicates.
# 0.80 is chosen to catch the same change described with slightly different
# wording (e.g. commit-SHA prefix, author mention, minor wording variation)
# while avoiding false positives for genuinely different changes.
SEMANTIC_DEDUP_THRESHOLD = 0.80


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def default_cache_dir() -> str:
    """Return the platform-standard cache directory for snapshot files.

    On Windows this uses %LOCALAPPDATA%\\openclaw-release-notes-analyzer\\snapshots,
    on Linux/macOS it uses $XDG_CACHE_HOME/openclaw-release-notes-analyzer/snapshots
    (falling back to ~/.cache/openclaw-release-notes-analyzer/snapshots).
    """
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "openclaw-release-notes-analyzer", "snapshots")
    base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return os.path.join(base, "openclaw-release-notes-analyzer", "snapshots")


# ---------------------------------------------------------------------------
# Recursive merge aggregation configuration
# ---------------------------------------------------------------------------

# Maximum tokens per leaf group. Each leaf contains complete notes + commits
# for 1-3 consecutive versions. Should stay well below MAX_TOKENS_PER_CHUNK
# to leave room for the LLM prompt and output.
RECURSIVE_MERGE_MAX_TOKENS_PER_LEAF = 80_000

# Maximum versions per leaf group. Hard cap to prevent any single leaf from
# growing too large even if token budget allows more.
RECURSIVE_MERGE_MAX_VERSIONS_PER_LEAF = 3

# Maximum recursion depth. Prevents runaway recursion if something goes wrong.
RECURSIVE_MERGE_MAX_DEPTH = 10

# Minimum number of versions to trigger recursive merge. For single-version
# or two-version analysis, fall back to standard single-pass LLM analysis.
RECURSIVE_MERGE_MIN_VERSIONS = 3
