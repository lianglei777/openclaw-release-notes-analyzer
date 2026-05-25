"""LLM analysis orchestration for the OpenClaw Release Analyzer.

This module handles:
- Commit relevance scoring and selection
- Master analysis data construction (single JSON for LLM)
- LLM result parsing and merging into rule-based analyses
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import (
    COMMIT_RELEVANCE_PATTERNS,
    LLM_RESULTS_TTL_DAYS,
    MAX_ANALYSIS_DATA_CHARS,
    MAX_COMMITS_FOR_ANALYSIS,
    NO_DIFF_COMPONENTS,
    NO_DIFF_KEYWORDS,
    NOISE_FILE_PATTERNS,
    RELEASE_NOTES_MAX_VERSIONS,
)
from models import ChangeAnalysis, CommitInfo, Release, Theme, LLMFullReport, LLMExecutiveSummary, LLMCompatibilityRisk, LLMNoteAnalysis


@dataclass
class LLMResultItem:
    """Single item returned by LLM analysis."""
    raw_text: str
    enhanced_interpretation: str
    risk_level: str
    confidence: str
    affected_files: List[str]
    has_hidden_breaking: bool
    code_evidence: str
    reasoning: str = ""
    suggested_category_correction: str = ""


# ---------------------------------------------------------------------------
# Diff-need detection (preserved from original)
# ---------------------------------------------------------------------------

def _needs_diff(analysis: ChangeAnalysis) -> bool:
    """Return True if this release note likely has meaningful code changes worth inspection."""
    comp = (analysis.component or "").lower()
    text = analysis.raw_text.lower()
    for c in NO_DIFF_COMPONENTS:
        if c.lower() in comp:
            return False
    for kw in NO_DIFF_KEYWORDS:
        if kw in text:
            return False
    cats = set(analysis.categories)
    if cats <= {"docs", "known_issue", "other"}:
        return False
    if cats & {"breaking", "security", "plugin", "api_sdk", "cli", "config", "dependency", "migration"}:
        return True
    return True


# ---------------------------------------------------------------------------
# Commit relevance scoring
# ---------------------------------------------------------------------------

def score_commit_relevance(commit: CommitInfo) -> int:
    """Score a commit's relevance for release-note association.

    Scoring factors:
    - Commit message keyword patterns (from config)
    - Penalty for noise-only commits (docs, config files)
    - Bonus for touching public-surface files
    """
    score = 0
    msg_lower = commit.message.lower()

    # Pattern-based scoring from config
    for pattern, weight in COMMIT_RELEVANCE_PATTERNS:
        if re.search(pattern, msg_lower, re.IGNORECASE):
            score += weight

    # Penalize noise-only commits
    if commit.changed_files:
        noise_count = 0
        total_count = len(commit.changed_files)
        for fname in commit.changed_files:
            if any(re.search(p, fname) for p in NOISE_FILE_PATTERNS):
                noise_count += 1
        if noise_count == total_count and total_count > 0:
            score = max(score - 10, 0)
        elif noise_count > 0:
            score = max(score - 5, 0)

    # Bonus for touching public-surface files
    public_patterns = [
        r"src/plugin[s]?/",
        r"src/api/",
        r"src/cli/",
        r"src/config/",
        r"packages/sdk/",
        r"packages/core/",
        r"package\.json",
    ]
    for fname in commit.changed_files:
        for pattern in public_patterns:
            if re.search(pattern, fname, re.IGNORECASE):
                score += 3
                break

    return score


def select_relevant_commits(
    commits: List[CommitInfo],
    max_commits: int = MAX_COMMITS_FOR_ANALYSIS,
) -> List[CommitInfo]:
    """Select the most relevant commits for LLM analysis."""
    scored = [(c, score_commit_relevance(c)) for c in commits]
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = []
    for commit, score in scored[:max_commits]:
        commit.relevance_score = score
        selected.append(commit)

    return selected


# ---------------------------------------------------------------------------
# Analysis data builder (single master file)
# ---------------------------------------------------------------------------

def build_analysis_data(
    repo: str,
    target: Release,
    compare: Optional[Release],
    analyses: List[ChangeAnalysis],
    commits: List[CommitInfo],
    diff_files: List[Dict[str, Any]],
    lang: str,
) -> Dict[str, Any]:
    """Build a single master analysis data file for LLM comprehensive analysis.

    Unlike the old per-component-prompt approach, this gives the LLM:
    - All release notes (with rule-based pre-classification)
    - All relevant commits (with messages and changed files)
    - Directory-level code change statistics
    - Top changed files summary

    The LLM uses this to perform semantic association between notes and commits.
    """
    # Directory-level stats
    dir_stats: Dict[str, Dict[str, Any]] = {}
    for f in diff_files:
        fname = f.get("filename", "")
        dirname = fname.split("/")[0] if "/" in fname else "root"
        if dirname not in dir_stats:
            dir_stats[dirname] = {"files": 0, "additions": 0, "deletions": 0}
        dir_stats[dirname]["files"] += 1
        dir_stats[dirname]["additions"] += f.get("additions", 0)
        dir_stats[dirname]["deletions"] += f.get("deletions", 0)

    # Sort directories by total changes, keep top 15
    sorted_dirs = sorted(
        dir_stats.items(),
        key=lambda x: x[1]["additions"] + x[1]["deletions"],
        reverse=True,
    )[:15]

    # Release notes: ONLY raw text + ID. No rule-based classification,
    # risk, or interpretation is passed — the LLM performs ALL semantic
    # analysis from scratch to avoid template bias.
    notes_data = []
    for idx, item in enumerate(analyses, 1):
        notes_data.append({
            "id": f"R-{idx:03d}",
            "raw_text": item.raw_text,
        })

    # Commits (top relevant, with file limits)
    commits_data = []
    for c in commits:
        commits_data.append({
            "sha": c.sha,
            "message": c.message,
            "author": c.author_name,
            "changed_files": c.changed_files[:10],
            "relevance_score": c.relevance_score,
        })

    total_add = sum(f.get("additions", 0) for f in diff_files)
    total_del = sum(f.get("deletions", 0) for f in diff_files)

    data = {
        "meta": {
            "repo": repo,
            "target_version": target.tag_name,
            "compare_version": compare.tag_name if compare else "",
            "language": lang,
            "analysis_mode": "commit-message-bridge",
            "notes_total": len(notes_data),
            "commits_included": len(commits_data),
        },
        "release_notes": notes_data,
        "commits": commits_data,
        "code_changes": {
            "total_files_changed": len(diff_files),
            "total_additions": total_add,
            "total_deletions": total_del,
            "by_directory": {k: v for k, v in sorted_dirs},
            "top_files": [
                {
                    "filename": f.get("filename", ""),
                    "status": f.get("status", ""),
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                }
                for f in diff_files[:15]
            ],
        },
        "instructions": _build_llm_instructions(lang),
    }

    # Hard cap on total size
    json_str = json.dumps(data, ensure_ascii=False)
    if len(json_str) > MAX_ANALYSIS_DATA_CHARS:
        overshoot = len(json_str) - MAX_ANALYSIS_DATA_CHARS
        # Rough estimate: remove overshoot/200 commits
        commits_to_remove = min(
            len(commits_data) - 10,
            max(1, overshoot // 200),
        )
        if commits_to_remove > 0 and commits_to_remove < len(commits_data):
            data["commits"] = commits_data[:-commits_to_remove]
        else:
            data["commits"] = commits_data[:10]
        data["code_changes"]["top_files"] = data["code_changes"]["top_files"][:10]
        data["meta"]["size_trimmed"] = True
        data["meta"]["commits_included"] = len(data["commits"])

    return data


def _build_llm_instructions(lang: str) -> str:
    """Build instructions for the LLM comprehensive analysis.

    Architecture principle: The script is a data pipeline ONLY.
    ALL semantic analysis — classification, risk assessment, interpretation,
    theme clustering, commit association, compatibility judgment — is performed
    by the LLM to maximize accuracy and depth.

    The LLM outputs a COMPLETE analysis report in structured JSON.
    The script merely parses and renders it.
    """
    if lang == "zh":
        return (
            "你是一个资深的 OpenClaw release notes 分析师。OpenClaw 是一款插件化 AI 助手框架。\n\n"
            "我会提供三部分原始数据（未经过任何预分析）：\n"
            "1. release_notes: 本次版本的所有 release note（仅原始文本，每条有 ID: R-001, R-002...）\n"
            "2. commits: 版本间的 commit 列表（含 commit message 和改动文件路径）\n"
            "3. code_changes: 代码变更统计摘要（按目录聚合 + 关键文件）\n\n"
            "==== 你的任务 ====\n\n"
            "基于以上原始数据，完成完整的 release analysis。所有分析必须由你自主完成，"
            "不要依赖任何外部预分类。\n\n"
            "==== 第一阶段：主题聚类 ====\n\n"
            "将 release_notes 按语义聚类为 8-15 个主题。聚类标准：\n"
            "- 同一功能模块的同类变更（如所有 Gemini ID 规范化相关条目）\n"
            "- 同一安全修复的多处加固（如 OAuth 相关修复）\n"
            "- 同一依赖升级触发的连锁变更（如 pnpm 11 迁移）\n"
            "- 同一组件的配套调整（如 Feishu 的认证+消息+线程相关变更）\n"
            "- 不要按组件机械分组；按\"功能意图\"分组\n"
            "- 尽量让每个 note 都属于一个主题，不要漏掉\n\n"
            "==== 第二阶段：主题级分析 ====\n\n"
            "对每个主题进行深度分析：\n"
            "- 主题整体风险级别（high/medium/low），以最高风险条目为准\n"
            "- 与主题语义直接对应的 commits（最多 3 个）\n"
            "- 该主题涉及的关键文件路径（最多 5 个）\n"
            "- 是否有隐藏的 breaking change（commit 揭示了 note 未提及的内容）\n"
            "- 判断依据：必须引用具体的 commit message 原文片段和文件路径\n\n"
            "==== 第三阶段：逐条深度分析（仅对高风险/有 commit 匹配的条目）====\n\n"
            "对以下条目做逐条深度分析：\n"
            "1. 主题风险为 high 的所有条目\n"
            "2. 有 matched_commits 的 medium 风险条目\n"
            "3. 有 hidden_breaking 信号的条目\n\n"
            "逐条分析要求：\n"
            "- component: 推断该条目所属的组件/模块\n"
            "- categories: 判断主分类（breaking/security/plugin/api_sdk/cli/config/dependency/performance/fix/feature/docs/other）\n"
            "- risk_level: 独立判断风险级别\n"
            "- interpretation: 写出有深度的变更解读，不要模板化。要回答\"这个变更具体改了什么\"\"对现有用户有什么影响\"\"需要做什么来适配\"\n"
            "- action_items: 给出 2-3 条具体、可操作的建议动作\n"
            "- audience: 判断主要影响哪些人\n"
            "- matched_commits: 直接对应的 commit SHA\n"
            "- affected_files: 受影响文件路径\n"
            "- reasoning: 引用 commit message 原文作为判断依据\n\n"
            "==== 第四阶段：生成完整报告内容 ====\n\n"
            "基于以上分析，生成报告所需的全部章节内容：\n\n"
            "1. 执行摘要（executive_summary）：\n"
            "   - recommendation: 升级建议（建议升级/谨慎升级/暂缓升级）\n"
            "   - theme: 核心主题（15字以内，概括本次更新最大特点）\n"
            "   - magnitude: 变化量级（大/中/小）\n"
            "   - reason: 建议理由（50字以内）\n"
            "   - top_changes: Top 5 最关键变化，每条包含 note_id + text 摘要 + risk + categories\n"
            "   - one_liner: 一句话判断（面向决策者的极简结论）\n\n"
            "2. 开发者结论（developer_conclusion）：\n"
            "   - 面向 Channel/插件开发者的一句话结论（50字以内）\n"
            "   - 要具体，不要模板。例如\"Feishu 认证流程从 QR 扫码改为手动配置，需要重新绑定\"\n\n"
            "3. 兼容性风险（compatibility_risks）：\n"
            "   - 每个高风险主题的兼容性风险描述\n"
            "   - 要具体说明什么会 break、为什么、怎么验证\n"
            "   - 不要写\"存在兼容性风险\"这种空话\n\n"
            "4. 测试建议（test_points）：\n"
            "   - 基于主题分析生成的具体测试点\n"
            "   - 每条测试点要可操作，例如\"用旧版 Feishu QR 配置验证升级后是否需要重新手动配置\"\n\n"
            "5. 未记录变更（shadow_changes）：\n"
            "   - commits 有但 release notes 没提的 public surface 变更\n"
            "   - 忽略纯内部重构、测试、文档类 commit\n\n"
            "==== 输出格式 ====\n\n"
            "JSON 对象，顶层字段如下：\n"
            "{\n"
            '  "executive_summary": {\n'
            '    "recommendation": "建议升级",\n'
            '    "theme": "安全加固与认证重构",\n'
            '    "magnitude": "大",\n'
            '    "reason": "包含多个安全修复和 OAuth 流程调整",\n'
            '    "top_changes": [\n'
            '      {"note_id": "R-001", "text": "Plugins/doctor: drop stale npm install records...", "risk": "high", "categories": ["breaking", "plugin"]}\n'
            '    ],\n'
            '    "one_liner": "本版包含 Feishu 认证流程 breaking change，需要重新配置后再升级。"\n'
            '  },\n'
            '  "developer_conclusion": "这是一版带兼容性包袱的更新，Feishu 认证从 QR 改为手动配置，Plugins/doctor 会清理 stale npm records。升级前先验证配置和插件兼容性。",\n'
            '  "themes": [\n'
            '    {\n'
            '      "theme_id": "T-01",\n'
            '      "theme_name": "Feishu 认证流程重构",\n'
            '      "note_ids": ["R-002", "R-067", "R-385", "R-432"],\n'
            '      "primary_category": "security",\n'
            '      "risk_level": "high",\n'
            '      "summary": "Feishu 默认认证路径从 QR 扫码改为手动 App ID 配置",\n'
            '      "impact": "已绑定 Feishu 的用户需要重新走手动配置流程",\n'
            '      "related_commits": ["abc1234"],\n'
            '      "affected_files": ["src/channels/feishu/auth.ts"],\n'
            '      "confidence": "high",\n'
            '      "has_hidden_breaking": false,\n'
            '      "hidden_risks": "",\n'
            '      "reasoning": "commit abc1234 message \"feat(feishu): switch default auth to manual app id\" 直接对应"\n'
            '    }\n'
            '  ],\n'
            '  "detailed_notes": [\n'
            '    {\n'
            '      "note_id": "R-001",\n'
            '      "component": "Plugins/doctor",\n'
            '      "categories": ["breaking", "plugin", "dependency"],\n'
            '      "risk_level": "high",\n'
            '      "interpretation": "doctor --fix 现在会删除 shadow bundled plugin 的 stale npm records。这意味着如果之前 doctor 修复过插件问题，升级后 registry 状态可能变化，需要验证插件是否正常加载。",\n'
            '      "action_items": ["运行 openclaw doctor --fix 观察是否有插件被清理", "验证关键插件在升级后是否正常加载"],\n'
            '      "audience": ["插件开发者", "运维人员"],\n'
            '      "matched_commits": ["def5678"],\n'
            '      "affected_files": ["src/plugins/doctor.ts"],\n'
            '      "has_hidden_breaking": false,\n'
            '      "reasoning": "commit def5678 message \"fix(doctor): drop stale managed npm install records\" 与 note 直接对应"\n'
            '    }\n'
            '  ],\n'
            '  "compatibility_risks": [\n'
            '    {"component": "Feishu", "description": "QR 扫码绑定失效，需要手动配置 App ID/App Secret。如果生产环境已绑定 Feishu，升级后 channel 会断连，需要提前准备手动配置流程。"}\n'
            '  ],\n'
            '  "test_points": [\n'
            '    "用旧版 Feishu QR 配置验证升级后是否需要重新手动配置",\n'
            '    "运行 openclaw doctor --fix 观察插件清理行为",\n'
            '    "验证插件安装/卸载后 peer dependency 是否正确清理"\n'
            '  ],\n'
            '  "shadow_changes": [\n'
            '    {"description": "commit ghi9012 新增了未在 release notes 中提及的 OAuth 回调接口", "evidence_commits": ["ghi9012"]}\n'
            '  ]\n'
            "}\n\n"
            "关键要求：\n"
            "1) interpretation 必须有深度，回答\"改了什么\"\"有什么影响\"\"怎么办\"三个问题\n"
            "2) 不要写模板化内容（如\"这项更新对 X 发出了兼容性信号\"）\n"
            "3) 保守评估风险——不确定时取更高风险级别\n"
            "4) reasoning 必须引用具体的 commit message 原文片段\n"
            "5) 不要强行关联不相关的 commit\n"
            "6) 不要编造不存在的变更\n"
            "7) 主题名要简洁具体，不要用\"其他变更\"\"杂项\""
        )
    else:
        return (
            "You are a senior OpenClaw release notes analyst. OpenClaw is a plugin-based AI assistant framework.\n\n"
            "I will provide three raw data sections (NO pre-analysis):\n"
            "1. release_notes: All release notes for this version (raw text only, each with an ID: R-001, R-002...)\n"
            "2. commits: Commits between versions (with messages and changed file paths)\n"
            "3. code_changes: Code change statistics (directory-level aggregation + key files)\n\n"
            "==== Your Task ====\n\n"
            "Complete a full release analysis based on the raw data above. ALL analysis must be performed by you; "
            "do not rely on any external pre-classification.\n\n"
            "==== Phase 1: Thematic Clustering ====\n\n"
            "Cluster release_notes into 8-15 semantic themes by functional intent:\n"
            "- Same functional module, same type of change\n"
            "- Same security fix applied in multiple places\n"
            "- Dependency upgrade cascading changes\n"
            "- Coordinated adjustments to the same component\n"
            "- Do NOT group mechanically by component\n"
            "- Include every note in a theme; do not leave notes unclassified\n\n"
            "==== Phase 2: Theme-Level Analysis ====\n\n"
            "For each theme, perform deep analysis:\n"
            "- Overall theme risk level (high/medium/low)\n"
            "- Commits that directly correspond to this theme (max 3)\n"
            "- Key file paths involved (max 5)\n"
            "- Hidden breaking changes (commit reveals something notes didn't mention)\n"
            "- Judgment rationale quoting specific commit message snippets\n\n"
            "==== Phase 3: Per-Note Deep Analysis (high-risk / commit-matched only) ====\n\n"
            "For each note requiring deep analysis:\n"
            "- component: Infer the component/module\n"
            "- categories: Determine primary category\n"
            "- risk_level: Independent risk judgment\n"
            "- interpretation: Write a DEEP analysis. Answer: WHAT changed, WHAT is the impact, WHAT to do about it. NO templates.\n"
            "- action_items: 2-3 specific, actionable recommendations\n"
            "- audience: Who is primarily affected\n"
            "- matched_commits: Directly corresponding commit SHAs\n"
            "- affected_files: Affected file paths\n"
            "- reasoning: Quote commit message snippets as evidence\n\n"
            "==== Phase 4: Generate Complete Report Content ====\n\n"
            "Based on the analysis above, generate ALL report sections:\n\n"
            "1. executive_summary:\n"
            "   - recommendation: Recommend Upgrade / Upgrade with Caution / Defer\n"
            "   - theme: Core theme (within 15 words)\n"
            "   - magnitude: Large / Medium / Small\n"
            "   - reason: Rationale (within 50 words)\n"
            "   - top_changes: Top 5 most critical changes (note_id + text summary + risk + categories)\n"
            "   - one_liner: One-sentence judgment for decision makers\n\n"
            "2. developer_conclusion:\n"
            "   - One-sentence conclusion for channel/plugin developers (within 50 words)\n"
            "   - Be specific, not templated\n\n"
            "3. compatibility_risks:\n"
            "   - Per high-risk theme: specific risk description\n"
            "   - Explain WHAT will break, WHY, and HOW to verify\n"
            "   - No vague statements like \"compatibility risk exists\"\n\n"
            "4. test_points:\n"
            "   - Specific, actionable test items based on theme analysis\n"
            "   - Each test point must be verifiable\n\n"
            "5. shadow_changes:\n"
            "   - Public surface changes present in commits but absent from release notes\n"
            "   - Ignore internal refactoring, tests, docs commits\n\n"
            "==== Output Format ====\n\n"
            "JSON object with these top-level fields:\n"
            "{\n"
            '  "executive_summary": {...},\n'
            '  "developer_conclusion": "...",\n'
            '  "themes": [...],\n'
            '  "detailed_notes": [...],\n'
            '  "compatibility_risks": [...],\n'
            '  "test_points": [...],\n'
            '  "shadow_changes": [...]\n'
            "}\n\n"
            "Critical requirements:\n"
            "1) interpretation must be DEEP — answer WHAT changed, WHAT is the impact, WHAT to do\n"
            "2) NO templated content (e.g., \"this change carries compatibility signals for X\")\n"
            "3) Conservative risk assessment — when uncertain, choose higher risk\n"
            "4) reasoning MUST quote specific commit message snippets\n"
            "5) Do not force associations for unrelated commits\n"
            "6) Do not invent changes\n"
            "7) Theme names must be concise and specific; avoid vague names like \"Other Changes\""
        )


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def write_analysis_data(data: Dict[str, Any], output_path: Path) -> None:
    """Write the analysis data to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_base_analysis(
    analyses: List[ChangeAnalysis],
    output_path: Path,
) -> None:
    """Write rule-based analysis results to a JSON file for later merging."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "release_tag": a.release_tag,
            "raw_text": a.raw_text,
            "primary_category": a.primary_category,
            "categories": a.categories,
            "component": a.component,
            "interpretation": a.interpretation,
            "risk_level": a.risk_level,
            "audience": a.audience,
            "action_items": a.action_items,
            "confidence": a.confidence,
            "priority": a.priority,
        }
        for a in analyses
    ]
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_base_analysis(path: Path) -> List[ChangeAnalysis]:
    """Read rule-based analysis results from a JSON file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("Invalid base analysis file")
    analyses: List[ChangeAnalysis] = []
    for item in payload:
        analyses.append(ChangeAnalysis(
            release_tag=item.get("release_tag", ""),
            raw_text=item.get("raw_text", ""),
            primary_category=item.get("primary_category", "other"),
            categories=item.get("categories", []),
            component=item.get("component", "General"),
            interpretation=item.get("interpretation", ""),
            risk_level=item.get("risk_level", "low"),
            audience=item.get("audience", []),
            action_items=item.get("action_items", []),
            confidence=item.get("confidence", "low"),
            priority=item.get("priority", 0),
        ))
    return analyses


@dataclass
class ParsedLLMResults:
    """Container for all LLM analysis outputs.

    Holds:
    - note_results: per-note enhancements mapped by raw_text
    - themes: semantic clusters of related release notes
    - shadow_changes: undocumented modifications found in commits
    """
    note_results: Dict[str, LLMResultItem] = field(default_factory=dict)
    themes: List[Theme] = field(default_factory=list)
    shadow_changes: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Result parsing and merging
# ---------------------------------------------------------------------------

def _parse_note_enhancement(item: Dict[str, Any]) -> Optional[LLMResultItem]:
    """Parse a single note enhancement from LLM output."""
    raw = item.get("note_raw_text", "") or item.get("raw_text", "")
    if not raw:
        return None

    affected = item.get("affected_files", []) or item.get("matched_files", []) or []
    breaking = bool(
        item.get("has_hidden_breaking", False)
        or item.get("is_truly_breaking", False)
    )

    hidden_raw = item.get("hidden_risks", "")
    code_evidence = item.get("code_evidence", "")
    if not code_evidence and hidden_raw:
        if isinstance(hidden_raw, list):
            if hidden_raw != ["none"] and hidden_raw != ["未发现"]:
                code_evidence = "; ".join(
                    str(h) for h in hidden_raw if h not in ("none", "未发现")
                )
        elif isinstance(hidden_raw, str) and hidden_raw.strip():
            code_evidence = hidden_raw.strip()

    return LLMResultItem(
        raw_text=raw,
        enhanced_interpretation=item.get("enhanced_interpretation", ""),
        risk_level=item.get("risk_level", "medium").lower(),
        confidence=item.get("confidence", "medium").lower(),
        affected_files=affected,
        has_hidden_breaking=breaking,
        code_evidence=code_evidence,
        reasoning=item.get("reasoning", ""),
        suggested_category_correction=item.get("suggested_category_correction", ""),
    )


def _parse_theme(item: Dict[str, Any]) -> Optional[Theme]:
    """Parse a single theme from LLM output."""
    theme_id = item.get("theme_id", "")
    theme_name = item.get("theme_name", "")
    if not theme_id or not theme_name:
        return None

    return Theme(
        theme_id=theme_id,
        theme_name=theme_name,
        note_ids=item.get("note_ids", []),
        raw_texts=item.get("raw_texts", []),
        primary_category=item.get("primary_category", "other"),
        risk_level=item.get("risk_level", "low").lower(),
        summary=item.get("summary", ""),
        impact=item.get("impact", ""),
        related_commits=item.get("related_commits", []),
        affected_files=item.get("affected_files", []),
        confidence=item.get("confidence", "medium").lower(),
        has_hidden_breaking=bool(item.get("has_hidden_breaking", False)),
        hidden_risks=item.get("hidden_risks", ""),
        reasoning=item.get("reasoning", ""),
    )


def _parse_executive_summary(item: Dict[str, Any]) -> LLMExecutiveSummary:
    """Parse executive summary from LLM output."""
    top_changes = item.get("top_changes", [])
    parsed_top: List[Dict[str, Any]] = []
    for tc in top_changes:
        if isinstance(tc, dict):
            parsed_top.append({
                "note_id": tc.get("note_id", ""),
                "text": tc.get("text", ""),
                "risk": tc.get("risk", "low").lower(),
                "categories": tc.get("categories", []),
            })
    return LLMExecutiveSummary(
        recommendation=item.get("recommendation", ""),
        theme=item.get("theme", ""),
        magnitude=item.get("magnitude", ""),
        reason=item.get("reason", ""),
        top_changes=parsed_top,
        one_liner=item.get("one_liner", ""),
    )


def _parse_compatibility_risk(item: Dict[str, Any]) -> Optional[LLMCompatibilityRisk]:
    """Parse a single compatibility risk from LLM output."""
    desc = item.get("description", "")
    if not desc:
        return None
    return LLMCompatibilityRisk(
        component=item.get("component", ""),
        description=desc,
    )


def _parse_detailed_note(item: Dict[str, Any]) -> Optional[LLMNoteAnalysis]:
    """Parse a single detailed note analysis from LLM output."""
    note_id = item.get("note_id", "")
    if not note_id:
        return None
    return LLMNoteAnalysis(
        note_id=note_id,
        component=item.get("component", ""),
        categories=item.get("categories", []),
        risk_level=item.get("risk_level", "low").lower(),
        interpretation=item.get("interpretation", ""),
        action_items=item.get("action_items", []),
        audience=item.get("audience", []),
        matched_commits=item.get("matched_commits", []),
        affected_files=item.get("affected_files", []),
        has_hidden_breaking=bool(item.get("has_hidden_breaking", False)),
        reasoning=item.get("reasoning", ""),
    )


def parse_llm_results(path: Path) -> LLMFullReport:
    """Read LLM analysis results from a JSON file and return a complete report.

    Supports the new full-report format:
    {
      "executive_summary": {...},
      "developer_conclusion": "...",
      "themes": [...],
      "detailed_notes": [...],
      "compatibility_risks": [...],
      "test_points": [...],
      "shadow_changes": [...]
    }

    Also supports legacy formats for backward compatibility.
    """
    text = path.read_text(encoding="utf-8")
    # LLM may wrap JSON in markdown code blocks
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    payload = json.loads(text)

    report = LLMFullReport()

    if isinstance(payload, dict):
        # Parse executive summary
        es = payload.get("executive_summary", {})
        if isinstance(es, dict):
            report.executive_summary = _parse_executive_summary(es)

        # Parse developer conclusion
        report.developer_conclusion = payload.get("developer_conclusion", "")

        # Parse themes
        for t in payload.get("themes", []):
            if isinstance(t, dict):
                theme = _parse_theme(t)
                if theme:
                    report.themes.append(theme)

        # Parse detailed notes
        for dn in payload.get("detailed_notes", []):
            if isinstance(dn, dict):
                note = _parse_detailed_note(dn)
                if note:
                    report.detailed_notes.append(note)

        # Parse compatibility risks
        for cr in payload.get("compatibility_risks", []):
            if isinstance(cr, dict):
                risk = _parse_compatibility_risk(cr)
                if risk:
                    report.compatibility_risks.append(risk)

        # Parse test points
        report.test_points = [
            str(tp) for tp in payload.get("test_points", [])
            if tp
        ]

        # Parse shadow changes
        report.shadow_changes = [
            sc for sc in payload.get("shadow_changes", [])
            if isinstance(sc, dict)
        ]

        # Legacy fallback: also parse old "note_enhancements" / "notes" fields
        # and convert them into detailed_notes for backward compatibility
        legacy_notes = payload.get("detailed_notes", []) or payload.get("note_enhancements", []) or payload.get("notes", [])
        if not report.detailed_notes:
            for item in legacy_notes:
                if isinstance(item, dict):
                    note_id = item.get("note_id", "")
                    raw = item.get("note_raw_text", "") or item.get("raw_text", "")
                    if note_id or raw:
                        report.detailed_notes.append(LLMNoteAnalysis(
                            note_id=note_id,
                            raw_text=raw,
                            component=item.get("component", ""),
                            categories=item.get("categories", []),
                            risk_level=item.get("risk_level", "low").lower(),
                            interpretation=item.get("enhanced_interpretation", ""),
                            action_items=item.get("action_items", []),
                            audience=item.get("audience", []),
                            matched_commits=item.get("matched_commits", []) or item.get("matched_commits", []),
                            affected_files=item.get("affected_files", []),
                            has_hidden_breaking=bool(item.get("has_hidden_breaking", False)),
                            reasoning=item.get("reasoning", ""),
                        ))

    elif isinstance(payload, list):
        # Very old flat format: convert each item to a detailed_note
        for item in payload:
            if isinstance(item, dict):
                raw = item.get("raw_text", "")
                if raw:
                    report.detailed_notes.append(LLMNoteAnalysis(
                        note_id=item.get("note_id", ""),
                        raw_text=raw,
                        interpretation=item.get("enhanced_interpretation", ""),
                        risk_level=item.get("risk_level", "low").lower(),
                        matched_commits=item.get("matched_commits", []),
                        affected_files=item.get("affected_files", []),
                        has_hidden_breaking=bool(item.get("has_hidden_breaking", False)),
                        reasoning=item.get("reasoning", ""),
                    ))
    else:
        raise RuntimeError(
            "LLM results must be a JSON object with 'executive_summary'/'themes'/"
            "'detailed_notes' fields, or a legacy object/array"
        )

    # Write shadow changes to a sidecar file for manual review
    if report.shadow_changes:
        shadow_path = path.with_suffix(".shadow.json")
        try:
            shadow_path.write_text(
                json.dumps(report.shadow_changes, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    return report


def _merge_interpretations(rule_text: str, llm_text: str, confidence: str) -> str:
    """Merge rule-based and LLM interpretations based on LLM confidence."""
    if confidence == "high":
        return llm_text
    elif confidence == "medium":
        rule_hint = rule_text[:150] + "..." if len(rule_text) > 150 else rule_text
        return f"{llm_text}\n\n[Rule-based reference]: {rule_hint}"
    else:
        llm_hint = llm_text[:150] + "..." if len(llm_text) > 150 else llm_text
        return f"{rule_text}\n\n[LLM supplemental (low confidence)]: {llm_hint}"


def _higher_risk(a: str, b: str) -> str:
    """Return the higher of two risk levels."""
    rank = {"high": 3, "medium": 2, "low": 1}
    return a if rank.get(a, 0) >= rank.get(b, 0) else b


def confidence_for(
    categories: Sequence[str], item: str, llm_enhanced: bool = False
) -> str:
    if llm_enhanced:
        return "high"
    has_component_prefix = bool(re.match(r"^[A-Za-z0-9_.\@+ -]{2,80}:\s+", item))
    if has_component_prefix and categories != ["other"]:
        return "high"
    if categories != ["other"]:
        return "medium"
    return "low"


def enhance_analyses_with_llm(
    analyses: List[ChangeAnalysis],
    llm_results: Dict[str, LLMResultItem],
) -> List[ChangeAnalysis]:
    """Merge LLM analysis results into existing ChangeAnalysis objects.

    Conflict arbitration based on LLM confidence:
    - high:    fully trust LLM (full replacement)
    - medium:  blended merge (LLM interpretation + rule reference; higher risk wins)
    - low:     rule-based priority (rule interpretation + LLM low-confidence hint)

    has_hidden_breaking is always respected regardless of confidence because
    it is a signal that rule-based analysis cannot produce.
    """
    enhanced: List[ChangeAnalysis] = []
    for analysis in analyses:
        llm = llm_results.get(analysis.raw_text)
        if llm and llm.enhanced_interpretation:
            llm_risk = (
                llm.risk_level
                if llm.risk_level in ("high", "medium", "low")
                else analysis.risk_level
            )

            # --- Conflict arbitration: interpretation ---
            new_interpretation = _merge_interpretations(
                analysis.interpretation, llm.enhanced_interpretation, llm.confidence
            )

            # --- Conflict arbitration: risk level ---
            if llm.confidence == "high":
                new_risk = llm_risk
            elif llm.confidence == "medium":
                new_risk = _higher_risk(analysis.risk_level, llm_risk)
            else:
                new_risk = analysis.risk_level

            # has_hidden_breaking is a high-value signal — always upgrade to high
            if llm.has_hidden_breaking and new_risk != "high":
                new_risk = "high"

            new_confidence = confidence_for(
                analysis.categories, analysis.raw_text, llm_enhanced=True
            )

            # Build categories: preserve rule-based, append breaking if LLM discovered it
            new_categories = list(analysis.categories)
            if llm.has_hidden_breaking and "breaking" not in new_categories:
                new_categories.append("breaking")

            # Apply category correction if LLM suggests one
            new_primary_category = analysis.primary_category
            if llm.suggested_category_correction:
                corr = llm.suggested_category_correction.lower().strip()
                if corr and corr not in new_categories:
                    new_categories.append(corr)
                # Upgrade primary_category if the correction is higher priority
                _priority_order = {
                    "breaking": 0, "security": 1, "migration": 2, "dependency": 3,
                    "plugin": 4, "api_sdk": 5, "cli": 6, "config": 7,
                    "performance": 8, "fix": 9, "feature": 10,
                    "docs": 11, "known_issue": 12, "other": 13,
                }
                old_pri = _priority_order.get(analysis.primary_category, 99)
                new_pri = _priority_order.get(corr, 99)
                if new_pri < old_pri:
                    new_primary_category = corr

            enhanced.append(
                ChangeAnalysis(
                    release_tag=analysis.release_tag,
                    raw_text=analysis.raw_text,
                    primary_category=new_primary_category,
                    categories=new_categories,
                    component=analysis.component,
                    interpretation=new_interpretation,
                    risk_level=new_risk,
                    audience=analysis.audience,
                    action_items=analysis.action_items,
                    confidence=new_confidence,
                    priority=analysis.priority
                    + (20 if llm.has_hidden_breaking else 0),
                    affected_files=llm.affected_files,
                    llm_enhanced=True,
                    code_evidence=llm.code_evidence,
                    llm_reasoning=llm.reasoning,
                )
            )
        else:
            # No LLM result for this item — keep rule-based analysis
            enhanced.append(analysis)
    # Re-sort by priority after potential adjustments
    return sorted(enhanced, key=lambda a: a.priority, reverse=True)


def should_use_llm_enhancement(
    analyses: List[ChangeAnalysis],
) -> Tuple[bool, str]:
    """Determine whether LLM enhancement is worthwhile based on rule-based signals.

    Returns (should_use, reason_message).
    """
    total = len(analyses)
    high_risk = sum(1 for a in analyses if a.risk_level == "high")
    has_breaking = any(
        "breaking" in a.categories or "migration" in a.categories for a in analyses
    )
    has_security = any("security" in a.categories for a in analyses)
    has_plugin_api = any(
        "plugin" in a.categories or "api_sdk" in a.categories for a in analyses
    )
    has_dependency = any("dependency" in a.categories for a in analyses)

    if has_breaking or has_security or high_risk > 0:
        return True, "High-signals detected (breaking/security/high-risk)"
    if has_plugin_api or has_dependency:
        return True, "Plugin/API/dependency surface changes detected"
    if total < 10 and high_risk == 0:
        return False, "Small low-risk release — rule-based analysis is sufficient"
    return True, "Standard release with moderate change volume"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def analysis_data_path(snapshot_dir: Path, repo: str, target_tag: str) -> Path:
    """Return the path for the analysis data JSON file."""
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    return snapshot_dir / f"{repo_part}-{target_part}-analysis-data.json"


def llm_results_path(snapshot_dir: Path, repo: str, target_tag: str) -> Path:
    """Return the path for the LLM results JSON file."""
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    return snapshot_dir / f"{repo_part}-{target_part}-llm-results.json"


def base_analysis_path(snapshot_dir: Path, repo: str, target_tag: str) -> Path:
    """Return the path for the base analysis JSON file."""
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    return snapshot_dir / f"{repo_part}-{target_part}-base-analysis.json"


# ---------------------------------------------------------------------------
# Chunked analysis: data splitting and result merging
# ---------------------------------------------------------------------------

from config import (
    CHUNK_MAX_COMMITS,
    CHUNK_MAX_NOTES,
    CHUNK_OVERLAP_NOTES,
    CHUNK_DATA_PATTERN,
    CHUNK_RESULT_PATTERN,
    CHUNKING_THRESHOLD_RATIO,
    MAX_TOKENS_PER_CHUNK,
    TOKENS_PER_CHAR,
)


def estimate_data_tokens(data: Dict[str, Any]) -> int:
    """Estimate token count for analysis data using character-based heuristic.

    Uses config.TOKENS_PER_CHAR (default 1.3) as a conservative multiplier
    for mixed CJK + English JSON content.
    """
    json_str = json.dumps(data, ensure_ascii=False)
    return int(len(json_str) * TOKENS_PER_CHAR)


def should_use_chunking(data: Dict[str, Any]) -> Tuple[bool, int]:
    """Determine whether the analysis data needs chunked processing.

    Returns (needs_chunking, estimated_tokens).
    Chunking is triggered when estimated tokens exceed
    MAX_TOKENS_PER_CHUNK * CHUNKING_THRESHOLD_RATIO.
    """
    tokens = estimate_data_tokens(data)
    threshold = int(MAX_TOKENS_PER_CHUNK * CHUNKING_THRESHOLD_RATIO)
    return tokens > threshold, tokens


def _group_notes_by_component(notes: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Group notes by inferred component to keep related notes together.

    Uses a simple heuristic: notes sharing the first word (e.g., 'Plugins/...')
    or containing the same module keyword are grouped.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for note in notes:
        text = note.get("raw_text", "")
        # Extract component hint from prefix like "Plugins/doctor: ..."
        match = re.match(r"^([A-Za-z0-9_./@+ -]{2,40}?):\s+", text)
        if match:
            key = match.group(1).strip().lower()
        else:
            # Fall back to first significant word
            words = re.findall(r"[a-zA-Z]{3,}", text.lower())
            key = words[0] if words else "general"
        groups.setdefault(key, []).append(note)
    # Sort groups by size (largest first) for stable chunking
    sorted_groups = sorted(groups.values(), key=lambda g: len(g), reverse=True)
    return sorted_groups


def _select_relevant_commits_for_notes(
    notes: List[Dict[str, Any]],
    all_commits: List[Dict[str, Any]],
    max_commits: int = CHUNK_MAX_COMMITS,
) -> List[Dict[str, Any]]:
    """Select commits most relevant to a given set of notes.

    Scoring: keyword overlap between note text and commit message.
    """
    # Build keyword set from notes
    note_text = " ".join(n.get("raw_text", "") for n in notes).lower()
    note_keywords = set(re.findall(r"[a-z]{4,}", note_text))
    note_keywords |= set(re.findall(r"[a-zA-Z]{3,}", note_text))

    scored = []
    for commit in all_commits:
        msg = commit.get("message", "").lower()
        files = " ".join(commit.get("changed_files", [])).lower()
        commit_text = msg + " " + files
        commit_keywords = set(re.findall(r"[a-z]{4,}", commit_text))
        overlap = len(note_keywords & commit_keywords)
        # Boost for exact keyword matches
        bonus = 0
        for kw in note_keywords:
            if kw in commit_text:
                bonus += 1
        score = overlap + bonus
        scored.append((commit, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    selected = [c for c, _ in scored[:max_commits]]
    return selected


def _select_relevant_code_changes(
    notes: List[Dict[str, Any]],
    all_code_changes: Dict[str, Any],
) -> Dict[str, Any]:
    """Filter code change stats to only directories/files relevant to notes."""
    note_text = " ".join(n.get("raw_text", "") for n in notes).lower()
    note_keywords = set(re.findall(r"[a-z]{3,}", note_text))

    # Get directories mentioned in notes (e.g., "src/plugins" -> "src")
    dir_hints = set()
    for kw in note_keywords:
        if kw in ("plugin", "plugins"):
            dir_hints.add("src/plugin")
            dir_hints.add("packages")
        elif kw in ("api", "sdk"):
            dir_hints.add("src/api")
            dir_hints.add("packages/sdk")
        elif kw == "cli":
            dir_hints.add("src/cli")
            dir_hints.add("packages/cli")
        elif kw in ("config", "configuration"):
            dir_hints.add("src/config")
        elif kw in ("security", "auth"):
            dir_hints.add("src")
        elif kw == "gateway":
            dir_hints.add("src/gateway")
        elif kw in ("feishu", "telegram", "discord", "whatsapp", "slack"):
            dir_hints.add("src/channel")

    by_directory = all_code_changes.get("by_directory", {})
    top_files = all_code_changes.get("top_files", [])

    # Keep directories that match hints or have highest change counts
    filtered_dirs = {}
    for dname, stats in by_directory.items():
        if any(hint in dname for hint in dir_hints):
            filtered_dirs[dname] = stats

    # If filtered too aggressively, keep top 5 by change count
    if len(filtered_dirs) < 3:
        sorted_dirs = sorted(
            by_directory.items(),
            key=lambda x: x[1].get("additions", 0) + x[1].get("deletions", 0),
            reverse=True,
        )[:5]
        filtered_dirs = {k: v for k, v in sorted_dirs}

    # Filter top files to those in selected directories
    filtered_files = [
        f for f in top_files
        if any(f.get("filename", "").startswith(d + "/") for d in filtered_dirs)
    ][:10]

    return {
        "total_files_changed": all_code_changes.get("total_files_changed", 0),
        "total_additions": all_code_changes.get("total_additions", 0),
        "total_deletions": all_code_changes.get("total_deletions", 0),
        "by_directory": filtered_dirs,
        "top_files": filtered_files,
    }


def split_analysis_data_into_chunks(
    data: Dict[str, Any],
    output_dir: Path,
    repo: str,
    target_tag: str,
) -> List[Path]:
    """Split analysis data into chunk files for distributed LLM processing.

    Strategy:
    1. Group notes by component to keep semantically related notes together.
    2. Create chunks with at most CHUNK_MAX_NOTES per chunk.
    3. Add CHUNK_OVERLAP_NOTES overlap between adjacent chunks for continuity.
    4. Each chunk gets only commits relevant to its notes (keyword match).
    5. Each chunk gets only code change stats for relevant directories.

    Returns list of written chunk file paths.
    """
    notes = data.get("release_notes", [])
    all_commits = data.get("commits", [])
    all_code_changes = data.get("code_changes", {})
    meta = data.get("meta", {})
    instructions = data.get("instructions", "")

    if not notes:
        # Empty data — write single empty chunk
        path = _chunk_data_path(output_dir, repo, target_tag, 0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return [path]

    # Group notes by component, flatten into ordered list
    groups = _group_notes_by_component(notes)
    ordered_notes: List[Dict[str, Any]] = []
    for group in groups:
        ordered_notes.extend(group)

    # Determine chunk count
    n_notes = len(ordered_notes)
    effective_chunk_size = CHUNK_MAX_NOTES - CHUNK_OVERLAP_NOTES
    n_chunks = max(1, (n_notes + effective_chunk_size - 1) // effective_chunk_size)

    # If small enough for single chunk, don't split
    if n_notes <= CHUNK_MAX_NOTES:
        tokens = estimate_data_tokens(data)
        if tokens <= CHUNKING_THRESHOLD_TOKENS:
            path = _chunk_data_path(output_dir, repo, target_tag, 0)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return [path]

    chunk_paths: List[Path] = []
    for i in range(n_chunks):
        start = i * effective_chunk_size
        end = min(start + CHUNK_MAX_NOTES, n_notes)
        chunk_notes = ordered_notes[start:end]

        # Add overlap from previous chunk (except first)
        if i > 0 and CHUNK_OVERLAP_NOTES > 0:
            overlap_start = max(0, start - CHUNK_OVERLAP_NOTES)
            overlap_notes = ordered_notes[overlap_start:start]
            # Prepend overlap notes, avoiding duplicates
            seen_ids = {n.get("id") for n in chunk_notes}
            for on in overlap_notes:
                if on.get("id") not in seen_ids:
                    chunk_notes.insert(0, on)
                    seen_ids.add(on.get("id"))

        # Select relevant commits for this chunk's notes
        chunk_commits = _select_relevant_commits_for_notes(chunk_notes, all_commits)

        # Select relevant code changes
        chunk_code_changes = _select_relevant_code_changes(chunk_notes, all_code_changes)

        chunk_data = {
            "meta": {
                **meta,
                "chunk_index": i,
                "total_chunks": n_chunks,
                "notes_in_chunk": len(chunk_notes),
                "commits_in_chunk": len(chunk_commits),
                "is_partial": n_chunks > 1,
            },
            "release_notes": chunk_notes,
            "commits": chunk_commits,
            "code_changes": chunk_code_changes,
            "instructions": instructions + _chunk_instructions(i, n_chunks, meta.get("language", "zh")),
        }

        path = _chunk_data_path(output_dir, repo, target_tag, i)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(chunk_data, ensure_ascii=False, indent=2), encoding="utf-8")
        chunk_paths.append(path)

    return chunk_paths


def _chunk_instructions(chunk_index: int, total_chunks: int, lang: str) -> str:
    """Append chunk-specific instructions for the LLM."""
    if lang == "zh":
        return (
            f"\n\n==== 分片分析说明 ====\n"
            f"这是第 {chunk_index + 1}/{total_chunks} 个分析分片。\n"
            f"你的任务是分析本分片中的 release notes 和 commits，输出与本分片相关的 themes 和 detailed_notes。\n"
            f"不需要输出 executive_summary、developer_conclusion、compatibility_risks、test_points、shadow_changes —— "
            f"这些将在所有分片分析完成后由合并步骤统一生成。\n"
            f"如果某个 theme 的 note 分布在多个分片中，每个分片只输出自己拥有的那部分 notes；"
            f"合并步骤会自动整合。\n"
        )
    return (
        f"\n\n==== Chunk Analysis Instructions ====\n"
        f"This is chunk {chunk_index + 1} of {total_chunks}.\n"
        f"Analyze only the release notes and commits in this chunk. Output themes and detailed_notes relevant to this chunk.\n"
        f"DO NOT output executive_summary, developer_conclusion, compatibility_risks, test_points, or shadow_changes — "
        f"these will be generated in a final merge step after all chunks are processed.\n"
        f"If a theme spans multiple chunks, output only the notes present in this chunk; the merge step will unify them.\n"
    )


def _chunk_data_path(output_dir: Path, repo: str, target_tag: str, idx: int) -> Path:
    """Return path for a chunk data file."""
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    filename = CHUNK_DATA_PATTERN.format(repo=repo_part, target=target_part, idx=idx)
    return output_dir / filename


def chunk_result_path(output_dir: Path, repo: str, target_tag: str, idx: int) -> Path:
    """Return path for a chunk analysis result file."""
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    filename = CHUNK_RESULT_PATTERN.format(repo=repo_part, target=target_part, idx=idx)
    return output_dir / filename


def merge_chunk_results(
    chunk_result_paths: List[Path],
    output_path: Path,
) -> None:
    """Merge multiple chunk LLM results into a single llm-results.json.

    Merging rules:
    - themes: Merge by theme_id, union note_ids (remove duplicates).
    - detailed_notes: Merge by note_id, keep first occurrence.
    - compatibility_risks: Concatenate all, remove duplicates by description.
    - test_points: Concatenate all, remove duplicates.
    - shadow_changes: Concatenate all, remove duplicates by description.
    - executive_summary: Generated from first chunk or synthesized from merged themes.
    - developer_conclusion: From first chunk.
    """
    if not chunk_result_paths:
        raise RuntimeError("No chunk result paths provided for merging")

    # Read all chunk results
    chunks: List[Dict[str, Any]] = []
    for path in sorted(chunk_result_paths):
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        payload = json.loads(text)
        if isinstance(payload, dict):
            chunks.append(payload)

    if not chunks:
        raise RuntimeError("No valid chunk results found")

    # Merge themes by theme_id
    themes_map: Dict[str, Dict[str, Any]] = {}
    for chunk in chunks:
        for t in chunk.get("themes", []):
            if not isinstance(t, dict):
                continue
            tid = t.get("theme_id", "")
            if not tid:
                continue
            if tid in themes_map:
                # Union note_ids
                existing = set(themes_map[tid].get("note_ids", []))
                new_ids = [nid for nid in t.get("note_ids", []) if nid not in existing]
                themes_map[tid]["note_ids"].extend(new_ids)
                # Use highest risk
                risk_rank = {"high": 3, "medium": 2, "low": 1}
                old_risk = themes_map[tid].get("risk_level", "low")
                new_risk = t.get("risk_level", "low")
                if risk_rank.get(new_risk, 0) > risk_rank.get(old_risk, 0):
                    themes_map[tid]["risk_level"] = new_risk
                # Union related_commits
                old_commits = set(themes_map[tid].get("related_commits", []))
                new_commits = [c for c in t.get("related_commits", []) if c not in old_commits]
                themes_map[tid]["related_commits"].extend(new_commits)
                # Union affected_files
                old_files = set(themes_map[tid].get("affected_files", []))
                new_files = [f for f in t.get("affected_files", []) if f not in old_files]
                themes_map[tid]["affected_files"].extend(new_files)
            else:
                themes_map[tid] = dict(t)

    # Merge detailed_notes by note_id
    detailed_map: Dict[str, Dict[str, Any]] = {}
    for chunk in chunks:
        for dn in chunk.get("detailed_notes", []):
            if not isinstance(dn, dict):
                continue
            nid = dn.get("note_id", "")
            if nid and nid not in detailed_map:
                detailed_map[nid] = dict(dn)

    # Merge compatibility_risks (dedup by description)
    compat_seen: set[str] = set()
    compat_risks: List[Dict[str, Any]] = []
    for chunk in chunks:
        for cr in chunk.get("compatibility_risks", []):
            if isinstance(cr, dict):
                desc = cr.get("description", "")
                if desc and desc not in compat_seen:
                    compat_seen.add(desc)
                    compat_risks.append(cr)

    # Merge test_points (dedup)
    test_seen: set[str] = set()
    test_points: List[str] = []
    for chunk in chunks:
        for tp in chunk.get("test_points", []):
            s = str(tp)
            if s and s not in test_seen:
                test_seen.add(s)
                test_points.append(s)

    # Merge shadow_changes (dedup by description)
    shadow_seen: set[str] = set()
    shadow_changes: List[Dict[str, Any]] = []
    for chunk in chunks:
        for sc in chunk.get("shadow_changes", []):
            if isinstance(sc, dict):
                desc = sc.get("description", "")
                if desc and desc not in shadow_seen:
                    shadow_seen.add(desc)
                    shadow_changes.append(sc)

    # Executive summary: prefer from first chunk, or synthesize
    first_es = chunks[0].get("executive_summary", {})
    if isinstance(first_es, dict) and first_es.get("top_changes"):
        executive_summary = first_es
    else:
        # Synthesize from merged themes
        high_risk_themes = [t for t in themes_map.values() if t.get("risk_level") == "high"]
        top_changes = []
        for t in sorted(high_risk_themes, key=lambda x: len(x.get("note_ids", [])), reverse=True)[:5]:
            for nid in t.get("note_ids", [])[:1]:
                top_changes.append({
                    "note_id": nid,
                    "text": t.get("summary", ""),
                    "risk": t.get("risk_level", "medium"),
                    "categories": [t.get("primary_category", "other")],
                })
        executive_summary = {
            "recommendation": "谨慎升级" if high_risk_themes else "建议升级",
            "theme": "多个主题变更" if len(themes_map) > 3 else (list(themes_map.values())[0].get("theme_name", "") if themes_map else ""),
            "magnitude": "大" if len(detailed_map) > 100 else "中" if len(detailed_map) > 30 else "小",
            "reason": f"包含 {len(high_risk_themes)} 个高风险主题" if high_risk_themes else "常规更新",
            "top_changes": top_changes,
            "one_liner": "",
        }

    developer_conclusion = chunks[0].get("developer_conclusion", "")

    merged = {
        "executive_summary": executive_summary,
        "developer_conclusion": developer_conclusion,
        "themes": list(themes_map.values()),
        "detailed_notes": list(detailed_map.values()),
        "compatibility_risks": compat_risks,
        "test_points": test_points,
        "shadow_changes": shadow_changes,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def discover_chunk_results(snapshot_dir: Path, repo: str, target_tag: str) -> List[Path]:
    """Discover all chunk result files for a given repo/target.

    Returns sorted list of paths.
    """
    repo_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_tag).strip("-") or "target"
    # Search both current and legacy naming patterns for compatibility
    paths: List[Path] = []
    for pattern in (
        f"{repo_part}-{target_part}-analysis-result-chunk-*.json",
        f"{repo_part}-{target_part}-llm-results-chunk-*.json",
    ):
        paths.extend(snapshot_dir.glob(pattern))
    return sorted(set(paths))
