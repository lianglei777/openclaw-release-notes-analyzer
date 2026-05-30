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
from models import (
    ChangeAnalysis, CommitInfo, Release, Theme,
    LLMFullReport, LLMExecutiveSummary, LLMCompatibilityRisk, LLMNoteAnalysis,
    ProgressiveFix, VersionEvolution,
)


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
    scoped_releases: Optional[Sequence[Release]] = None,
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
    for item in analyses:
        notes_data.append({
            "id": item.note_id or "",
            "raw_text": item.raw_text,
            "source_version": item.release_tag,
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

    # Cross-version scope metadata
    meta: Dict[str, Any] = {
        "repo": repo,
        "target_version": target.tag_name,
        "compare_version": compare.tag_name if compare else "",
        "language": lang,
        "analysis_mode": "commit-message-bridge",
        "notes_total": len(notes_data),
        "commits_included": len(commits_data),
    }
    if scoped_releases is not None and len(scoped_releases) > 1:
        meta["is_version_range"] = True
        meta["version_count"] = len(scoped_releases)
        meta["versions_in_scope"] = [r.tag_name for r in scoped_releases]
        # Per-version note counts (helps LLM detect sparse vs dense releases)
        from collections import Counter
        version_counts = Counter(item.release_tag for item in analyses if item.release_tag)
        meta["notes_per_version"] = {
            r.tag_name: version_counts.get(r.tag_name, 0)
            for r in scoped_releases
        }
    else:
        meta["is_version_range"] = False

    data = {
        "meta": meta,
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
    return (
        "你是一个资深的 OpenClaw release notes 分析师。OpenClaw 是一款插件化 AI 助手框架。\n\n"
        "我会提供三部分原始数据（未经过任何预分析）：\n"
        "1. release_notes: 本次分析范围内的所有 release note（仅原始文本，每条有 ID: R-001, R-002...）。"
        "每条 note 都有 source_version 字段，标注该 note 来自哪个 release tag（如 v2026.4.12）。"
        "如果分析范围包含多个版本，source_version 能帮你判断变更是在哪个中间版本引入的。\n"
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
        "==== 跨版本分析（如 source_version 显示多个版本）====\n\n"
        "如果 release_notes 来自多个版本，请在分析中特别关注以下两类跨版本模式：\n\n"
        "**渐进式修复检测（Optimization #3）**：\n"
        "- 识别同一个 bug/问题是否被分多个版本逐步修复\n"
        "- 典型模式：v1 引入临时缓解 → v2 部分修复 → v3 完整修复\n"
        "- 也包含：早期版本引入的问题在后续版本中被修复（regression-fix 链）\n"
        "- 每个渐进式修复链必须标注：问题描述、每个阶段的版本和 note_id、修复完整度（partial/mitigation/complete）、最终状态\n"
        "- 注意：一个 note 可能同时属于某个主题和某个渐进式修复链，这是正常的\n\n"
        "**累积 Breaking Change 分析（Optimization #4）**：\n"
        "- 评估跨版本升级路径上的累积兼容性风险\n"
        "- 核心判断：单个版本看起来低风险，但多个版本的 breaking change 叠加后，整体影响是否被低估\n"
        "- 关注信号：同一组件在多个版本中持续调整接口/行为；早期版本的废弃项在后续版本中真正移除；多个版本的配置变更叠加后需要多次迁移\n"
        "- 必须输出 individual_risk（单版本风险）vs cumulative_risk（累积风险），并解释 risk_escalation_reason\n"
        "- 在 theme 的 reasoning 中标注该主题涉及的版本范围\n\n"
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
        "6. 渐进式修复检测（progressive_fixes，仅在多版本时输出）：\n"
        "   - 每个修复链包含：fix_id、issue_description（问题描述）、stages（阶段列表，每阶段含 note_id/source_version/fix_description/completeness）、final_status、impact_assessment\n"
        "   - completeness 取值：mitigation（缓解）/ partial（部分修复）/ complete（完整修复）\n"
        "   - final_status 取值：fully_fixed（已完全修复）/ partially_fixed（仍部分修复）/ mitigated（仅缓解）\n"
        "   - 如果没有检测到渐进式修复，输出空数组 []\n\n"
        "7. 累积 Breaking Change 分析（version_evolution，仅在多版本时输出）：\n"
        "   - 每个演进条目包含：evolution_id、description（演进描述）、affected_versions（版本范围）、individual_risk（单版本风险）、cumulative_risk（累积风险）、risk_escalation_reason（为什么累积风险更高）、related_themes（关联主题ID）、affected_components、migration_advice\n"
        "   - risk_escalation_reason 是核心字段，必须具体说明为什么\"跨多个版本升级\"比\"逐个版本升级\"更危险\n"
        "   - 例如：\"v2026.4.10 废弃了旧 QR 绑定方式，v2026.4.11 修改了默认 auth 流程，v2026.4.12 完全移除 QR 支持。单个版本看都是渐进式调整，但跨越三个版本直接升级需要同时处理废弃通知、行为变化和接口移除三重影响，且没有中间版本的迁移缓冲\"\n"
        "   - 如果没有检测到累积风险，输出空数组 []\n\n"
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
        '  ],\n'
        '  "progressive_fixes": [\n'
        '    {\n'
        '      "fix_id": "PF-01",\n'
        '      "issue_description": "Feishu 认证在特定场景下 token 刷新失败",\n'
        '      "stages": [\n'
        '        {"note_id": "R-015", "source_version": "v2026.4.10", "fix_description": "增加 token 刷新重试次数", "completeness": "mitigation"},\n'
        '        {"note_id": "R-042", "source_version": "v2026.4.11", "fix_description": "修复 refresh 逻辑中的竞态条件", "completeness": "partial"},\n'
        '        {"note_id": "R-089", "source_version": "v2026.4.12", "fix_description": "重构 Feishu auth 模块，彻底消除 token 刷新问题", "completeness": "complete"}\n'
        '      ],\n'
        '      "final_status": "fully_fixed",\n'
        '      "impact_assessment": "从 v2026.4.10 升级到 v2026.4.12 可完全解决该问题；若停留在中间版本，仍可能遇到偶发认证失败",\n'
        '      "affected_components": ["Feishu", "Auth"]\n'
        '    }\n'
        '  ],\n'
        '  "version_evolution": [\n'
        '    {\n'
        '      "evolution_id": "VE-01",\n'
        '      "description": "Feishu 认证接口经历三次连续调整",\n'
        '      "affected_versions": ["v2026.4.10", "v2026.4.11", "v2026.4.12"],\n'
        '      "individual_risk": "low",\n'
        '      "cumulative_risk": "high",\n'
        '      "risk_escalation_reason": "v2026.4.10 废弃了旧 QR 绑定方式，v2026.4.11 修改了默认 auth 流程，v2026.4.12 完全移除 QR 支持。单个版本看都是渐进式调整，但跨越三个版本直接升级需要同时处理废弃通知、行为变化和接口移除三重影响，且没有中间版本的迁移缓冲",\n'
        '      "related_themes": ["T-01"],\n'
        '      "affected_components": ["Feishu", "Auth"],\n'
        '      "migration_advice": "建议分步升级：先升级到 v2026.4.11 完成手动配置迁移，验证无误后再升级到 v2026.4.12。不要跨两个中间版本直接升级。"\n'
        '    }\n'
        '  ]\n'
        "}\n\n"
        "关键要求：\n"
        "1) interpretation 必须有深度，回答\"改了什么\"\"有什么影响\"\"怎么办\"三个问题\n"
        "2) 不要写模板化内容（如\"这项更新对 X 发出了兼容性信号\"）\n"
        "3) 保守评估风险——不确定时取更高风险级别\n"
        "4) reasoning 必须引用具体的 commit message 原文片段\n"
        "5) 不要强行关联不相关的 commit\n"
        "6) 不要编造不存在的变更\n"
        "7) 主题名要简洁具体，不要用\"其他变更\"\"杂项\"\n"
        "8) progressive_fixes 和 version_evolution 只在分析范围包含多个版本时输出；单版本分析输出空数组 []\n"
        "9) risk_escalation_reason 必须具体，不能写\"多个变更叠加导致风险增加\"这种空话"
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
            "note_id": a.note_id,
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
            note_id=item.get("note_id", ""),
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


def _parse_progressive_fix(item: Dict[str, Any]) -> Optional[ProgressiveFix]:
    """Parse a progressive fix chain from LLM output."""
    fix_id = item.get("fix_id", "")
    if not fix_id:
        return None
    stages = []
    for s in item.get("stages", []):
        if isinstance(s, dict):
            stages.append({
                "note_id": s.get("note_id", ""),
                "source_version": s.get("source_version", ""),
                "fix_description": s.get("fix_description", ""),
                "completeness": s.get("completeness", ""),
            })
    return ProgressiveFix(
        fix_id=fix_id,
        issue_description=item.get("issue_description", ""),
        stages=stages,
        final_status=item.get("final_status", ""),
        impact_assessment=item.get("impact_assessment", ""),
        affected_components=item.get("affected_components", []),
    )


def _parse_version_evolution(item: Dict[str, Any]) -> Optional[VersionEvolution]:
    """Parse a version evolution entry from LLM output."""
    evolution_id = item.get("evolution_id", "")
    if not evolution_id:
        return None
    return VersionEvolution(
        evolution_id=evolution_id,
        description=item.get("description", ""),
        affected_versions=item.get("affected_versions", []),
        individual_risk=item.get("individual_risk", "low").lower(),
        cumulative_risk=item.get("cumulative_risk", "low").lower(),
        risk_escalation_reason=item.get("risk_escalation_reason", ""),
        related_themes=item.get("related_themes", []),
        affected_components=item.get("affected_components", []),
        migration_advice=item.get("migration_advice", ""),
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

        # Parse progressive fixes (optimization #3)
        for pf in payload.get("progressive_fixes", []):
            if isinstance(pf, dict):
                fix = _parse_progressive_fix(pf)
                if fix:
                    report.progressive_fixes.append(fix)

        # Parse version evolution (optimization #4)
        for ve in payload.get("version_evolution", []):
            if isinstance(ve, dict):
                evo = _parse_version_evolution(ve)
                if evo:
                    report.version_evolution.append(evo)

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


def _generate_enhancement_prompt(
    merged: Dict[str, Any],
    themes_map: Dict[str, Dict[str, Any]],
    detailed_map: Dict[str, Dict[str, Any]],
    lang: str = "zh",
) -> str:
    """Generate an enhancement prompt for LLM to improve merged results.

    When the pure-Python merge produces generic executive_summary or empty
    developer_conclusion/compatibility_risks/test_points, this prompt
    provides all theme and note summaries so the LLM can synthesize
    high-quality content without re-analyzing raw data.
    """
    es = merged.get("executive_summary", {})
    dc = merged.get("developer_conclusion", "")
    cr_list = merged.get("compatibility_risks", [])
    tp_list = merged.get("test_points", [])

    # Determine what needs enhancement
    needs = []
    theme_text = es.get("theme", "")
    generic_markers = ["多个", "various", "multiple", "miscellaneous", "杂项", "其他"]
    is_generic_theme = any(m in theme_text for m in generic_markers) or len(theme_text) < 5
    if is_generic_theme:
        needs.append("executive_summary.theme")
    if not es.get("one_liner"):
        needs.append("executive_summary.one_liner")
    if not dc or len(str(dc)) < 15:
        needs.append("developer_conclusion")
    high_risk_themes = [t for t in themes_map.values() if t.get("risk_level") == "high"]
    if not cr_list and high_risk_themes:
        needs.append("compatibility_risks")
    breaking_themes = [t for t in themes_map.values() if t.get("primary_category") in ("breaking", "security")]
    if not tp_list and (breaking_themes or high_risk_themes):
        needs.append("test_points")

    # Build theme summaries
    theme_lines = []
    for tid, t in sorted(themes_map.items()):
        theme_lines.append(
            f"{tid}: {t.get('theme_name', '')} | risk={t.get('risk_level', 'low')} | "
            f"category={t.get('primary_category', 'other')} | notes={len(t.get('note_ids', []))} | "
            f"summary={t.get('summary', '')}"
        )

    # Build high-risk theme details
    hr_lines = []
    for t in sorted(high_risk_themes, key=lambda x: len(x.get("note_ids", [])), reverse=True):
        hr_lines.append(
            f"- {t.get('theme_id', '')} '{t.get('theme_name', '')}': {t.get('impact', '')} "
            f"(commits: {', '.join(t.get('related_commits', []))})"
        )

    # Build detailed note summaries (high risk only)
    dn_lines = []
    for nid, dn in sorted(detailed_map.items()):
        if dn.get("risk_level") == "high":
            interp = dn.get("interpretation", "")
            dn_lines.append(
                f"- {nid} [{dn.get('component', '')}]: {interp[:120]}{'...' if len(interp) > 120 else ''}"
            )

    prompt = (
        "==== 合并后增强任务 ====\n\n"
        f"以下是从 {len(themes_map)} 个 themes 和 {len(detailed_map)} 条详细分析中合并得到的结果。"
        f"合并步骤（纯 Python，无 LLM）已经生成了初步结果，但以下字段需要增强：\n"
        f"需要增强的字段: {', '.join(needs) if needs else 'executive_summary, developer_conclusion, compatibility_risks, test_points'}\n\n"
        "=== Themes 摘要 ===\n"
        + "\n".join(theme_lines)
        + "\n\n=== 高风险 Themes 详情 ===\n"
        + ("\n".join(hr_lines) if hr_lines else "(无)")
        + "\n\n=== 高风险 Detailed Notes 摘要 ===\n"
        + ("\n".join(dn_lines) if dn_lines else "(无)")
        + "\n\n=== 任务 ===\n"
        "请基于以上 themes 和 notes 的摘要信息，生成以下增强内容（JSON 格式）：\n\n"
        "{\n"
        '  "executive_summary": {\n'
        '    "recommendation": "建议升级/谨慎升级/暂缓升级",\n'
        '    "theme": "15字以内的核心主题，要具体不要泛化",\n'
        '    "magnitude": "大/中/小",\n'
        '    "reason": "50字以内的建议理由",\n'
        '    "top_changes": [\n'
        '      {"note_id": "R-xxx", "text": "变化摘要", "risk": "high/medium/low", "categories": ["breaking", "security"]}\n'
        '    ],\n'
        '    "one_liner": "一句话判断"\n'
        '  },\n'
        '  "developer_conclusion": "面向 Channel/插件开发者的一句话结论（50字以内），要具体",\n'
        '  "compatibility_risks": [\n'
        '    {"component": "组件名", "description": "具体的兼容性风险描述"}\n'
        '  ],\n'
        '  "test_points": [\n'
        '    "具体的可操作的测试建议"\n'
        '  ]\n'
        "}\n\n"
        "要求：\n"
        "1. theme 必须具体，不能是\"多个主题变更\"这种泛化描述\n"
        "2. developer_conclusion 必须具体，例如\"Feishu 认证从 QR 改为手动配置，需要重新绑定\"\n"
        "3. compatibility_risks 每条必须说明\"什么会 break、为什么、怎么验证\"\n"
        "4. test_points 每条必须是可操作的验证步骤\n"
        "5. 只输出 JSON，不要 markdown 代码块包裹"
    )
    return prompt


def merge_chunk_results(
    chunk_result_paths: List[Path],
    output_path: Path,
) -> Dict[str, Any]:
    """Merge multiple chunk LLM results into a single llm-results.json.

    Merging rules:
    - themes: Merge by theme_id, union note_ids (remove duplicates).
    - detailed_notes: Merge by note_id, keep first occurrence.
    - compatibility_risks: Concatenate all, remove duplicates by description.
    - test_points: Concatenate all, remove duplicates.
    - shadow_changes: Concatenate all, remove duplicates by description.
    - executive_summary: Generated from first chunk or synthesized from merged themes.
    - developer_conclusion: From first chunk.

    Returns a dict with enhancement info:
    - enhancement_needed: bool
    - enhancement_prompt_path: Path (if enhancement_needed)
    - needs_fields: List[str] (fields that need enhancement)
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

    # Detect language from first chunk's themes
    lang = "zh"
    first_themes = chunks[0].get("themes", [])
    if first_themes and isinstance(first_themes[0], dict):
        tn = first_themes[0].get("theme_name", "")
        # Simple heuristic: if theme name has Chinese characters, use zh
        if not any("一" <= c <= "鿿" for c in tn):
            lang = "en"

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

    # Merge progressive_fixes by fix_id (optimization #3)
    progressive_fixes_map: Dict[str, Dict[str, Any]] = {}
    for chunk in chunks:
        for pf in chunk.get("progressive_fixes", []):
            if not isinstance(pf, dict):
                continue
            fid = pf.get("fix_id", "")
            if not fid:
                continue
            if fid in progressive_fixes_map:
                # Union stages by note_id
                existing_stages = {s.get("note_id", ""): s for s in progressive_fixes_map[fid].get("stages", []) if isinstance(s, dict)}
                for s in pf.get("stages", []):
                    if isinstance(s, dict):
                        nid = s.get("note_id", "")
                        if nid and nid not in existing_stages:
                            existing_stages[nid] = s
                progressive_fixes_map[fid]["stages"] = list(existing_stages.values())
                # Use higher final_status: mitigated < partially_fixed < fully_fixed
                status_rank = {"fully_fixed": 3, "partially_fixed": 2, "mitigated": 1}
                old_status = progressive_fixes_map[fid].get("final_status", "")
                new_status = pf.get("final_status", "")
                if status_rank.get(new_status, 0) > status_rank.get(old_status, 0):
                    progressive_fixes_map[fid]["final_status"] = new_status
                # Union affected_components
                old_comps = set(progressive_fixes_map[fid].get("affected_components", []))
                new_comps = [c for c in pf.get("affected_components", []) if c not in old_comps]
                progressive_fixes_map[fid]["affected_components"] = list(old_comps) + new_comps
            else:
                progressive_fixes_map[fid] = dict(pf)

    # Merge version_evolution by evolution_id (optimization #4)
    version_evolution_map: Dict[str, Dict[str, Any]] = {}
    for chunk in chunks:
        for ve in chunk.get("version_evolution", []):
            if not isinstance(ve, dict):
                continue
            eid = ve.get("evolution_id", "")
            if not eid:
                continue
            if eid in version_evolution_map:
                # Use higher cumulative_risk
                risk_rank = {"high": 3, "medium": 2, "low": 1}
                old_risk = version_evolution_map[eid].get("cumulative_risk", "low")
                new_risk = ve.get("cumulative_risk", "low")
                if risk_rank.get(new_risk, 0) > risk_rank.get(old_risk, 0):
                    version_evolution_map[eid]["cumulative_risk"] = new_risk
                # Union affected_versions
                old_versions = set(version_evolution_map[eid].get("affected_versions", []))
                new_versions = [v for v in ve.get("affected_versions", []) if v not in old_versions]
                version_evolution_map[eid]["affected_versions"] = list(old_versions) + new_versions
                # Union related_themes
                old_themes = set(version_evolution_map[eid].get("related_themes", []))
                new_themes = [t for t in ve.get("related_themes", []) if t not in old_themes]
                version_evolution_map[eid]["related_themes"] = list(old_themes) + new_themes
                # Union affected_components
                old_comps = set(version_evolution_map[eid].get("affected_components", []))
                new_comps = [c for c in ve.get("affected_components", []) if c not in old_comps]
                version_evolution_map[eid]["affected_components"] = list(old_comps) + new_comps
                # Prefer longer risk_escalation_reason
                old_reason = version_evolution_map[eid].get("risk_escalation_reason", "")
                new_reason = ve.get("risk_escalation_reason", "")
                if len(new_reason) > len(old_reason):
                    version_evolution_map[eid]["risk_escalation_reason"] = new_reason
            else:
                version_evolution_map[eid] = dict(ve)

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
        "progressive_fixes": list(progressive_fixes_map.values()),
        "version_evolution": list(version_evolution_map.values()),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    # Check if enhancement is needed and generate enhancement prompt
    enhancement_prompt = _generate_enhancement_prompt(merged, themes_map, detailed_map, lang)
    needs = []
    es = merged.get("executive_summary", {})
    theme_text = es.get("theme", "")
    generic_markers = ["多个", "various", "multiple", "miscellaneous", "杂项", "其他"]
    if any(m in theme_text for m in generic_markers) or len(theme_text) < 5:
        needs.append("executive_summary.theme")
    if not es.get("one_liner"):
        needs.append("executive_summary.one_liner")
    if not developer_conclusion or len(str(developer_conclusion)) < 15:
        needs.append("developer_conclusion")
    hr_themes = [t for t in themes_map.values() if t.get("risk_level") == "high"]
    if not compat_risks and hr_themes:
        needs.append("compatibility_risks")
    br_themes = [t for t in themes_map.values() if t.get("primary_category") in ("breaking", "security")]
    if not test_points and (br_themes or hr_themes):
        needs.append("test_points")

    if needs:
        prompt_path = output_path.with_suffix(".enhancement-prompt.txt")
        prompt_path.write_text(enhancement_prompt, encoding="utf-8")
        return {
            "enhancement_needed": True,
            "enhancement_prompt_path": prompt_path,
            "needs_fields": needs,
        }

    return {"enhancement_needed": False, "needs_fields": []}


# ---------------------------------------------------------------------------
# Recursive merge aggregation: data compression and merge prompts
# ---------------------------------------------------------------------------

def compress_for_merge(report: LLMFullReport) -> Dict[str, Any]:
    """Compress a full LLM analysis report for merge-layer input.

    Tiered compression preserves information needed for cross-group
    association while staying within token budgets:
    - high risk notes: keep complete (may need re-evaluation across groups)
    - medium risk: keep core fields (drop action_items, audience)
    - low risk: minimal (component + categories + risk + brief interpretation)
    - themes / progressive_fixes / version_evolution: keep complete
    - executive_summary / developer_conclusion: discard (root regenerates)
    """
    # Compress detailed_notes by risk level
    compressed_notes: List[Dict[str, Any]] = []
    for dn in report.detailed_notes:
        risk = dn.risk_level.lower()
        base = {
            "note_id": dn.note_id,
            "component": dn.component,
            "categories": dn.categories,
            "risk_level": risk,
        }
        if risk == "high":
            compressed_notes.append({
                **base,
                "interpretation": dn.interpretation,
                "action_items": dn.action_items,
                "audience": dn.audience,
                "matched_commits": dn.matched_commits,
                "affected_files": dn.affected_files,
                "has_hidden_breaking": dn.has_hidden_breaking,
                "reasoning": dn.reasoning,
            })
        elif risk == "medium":
            compressed_notes.append({
                **base,
                "interpretation": dn.interpretation,
                "matched_commits": dn.matched_commits,
                "affected_files": dn.affected_files,
                "reasoning": dn.reasoning,
            })
        else:
            # low: minimal
            interp = dn.interpretation
            if len(interp) > 100:
                interp = interp[:100] + "..."
            compressed_notes.append({
                **base,
                "interpretation": interp,
                "matched_commits": dn.matched_commits,
            })

    # Themes: keep complete
    themes_out = []
    for t in report.themes:
        themes_out.append({
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
        })

    # Progressive fixes: keep complete (core cross-version data)
    pf_out = []
    for pf in report.progressive_fixes:
        pf_out.append({
            "fix_id": pf.fix_id,
            "issue_description": pf.issue_description,
            "stages": pf.stages,
            "final_status": pf.final_status,
            "impact_assessment": pf.impact_assessment,
            "affected_components": pf.affected_components,
        })

    # Version evolution: keep complete
    ve_out = []
    for ve in report.version_evolution:
        ve_out.append({
            "evolution_id": ve.evolution_id,
            "description": ve.description,
            "affected_versions": ve.affected_versions,
            "individual_risk": ve.individual_risk,
            "cumulative_risk": ve.cumulative_risk,
            "risk_escalation_reason": ve.risk_escalation_reason,
            "related_themes": ve.related_themes,
            "affected_components": ve.affected_components,
            "migration_advice": ve.migration_advice,
        })

    # Compatibility risks: keep complete
    cr_out = []
    for cr in report.compatibility_risks:
        cr_out.append({
            "component": cr.component,
            "description": cr.description,
        })

    return {
        "themes": themes_out,
        "detailed_notes": compressed_notes,
        "progressive_fixes": pf_out,
        "version_evolution": ve_out,
        "compatibility_risks": cr_out,
        "shadow_changes": report.shadow_changes,
        "test_points": report.test_points,
    }


def build_merge_prompt(group_a: Dict[str, Any], group_b: Dict[str, Any], lang: str = "zh") -> str:
    """Build a merge-layer prompt for the LLM to combine two analysis results.

    The LLM receives two compressed sub-group results and performs semantic
    merge operations: theme deduplication, progressive fix chain linking,
    cumulative risk assessment, and risk re-evaluation.
    """
    a_json = json.dumps(group_a, ensure_ascii=False, indent=2)
    b_json = json.dumps(group_b, ensure_ascii=False, indent=2)

    return (
        "# OpenClaw Release Analyzer - 跨版本组合并分析\n\n"
        "你正在合并两个相邻版本组的分析结果。这不是从头分析，"
        "而是基于已有的结构化分析结果进行整合、去重和跨组关联发现。\n\n"
        "## 版本组 A\n"
        "```json\n"
        f"{a_json}\n"
        "```\n\n"
        "## 版本组 B\n"
        "```json\n"
        f"{b_json}\n"
        "```\n\n"
        "## 合并任务\n\n"
        "### 1. 主题合并与去重\n"
        "- 对比 A 和 B 的 themes\n"
        "- 如果两个 themes 描述的是同一组件/功能的同一类变更，合并为一个 theme\n"
        "- 合并后：note_ids 取并集、related_commits 取并集、affected_files 取并集\n"
        "- 如果风险级别不同，取更高的级别\n"
        "- 保留未合并的独立 themes\n\n"
        "### 2. 渐进式修复链连接（核心任务）\n"
        "- 检查 A 的 progressive_fixes 中 final_status 不是 'fully_fixed' 的条目\n"
        "- 检查 B 中是否有继续修复同一问题的 notes/themes\n"
        "- 如果找到匹配，将两条链连接为一条更长的链\n"
        "- 更新 final_status、stages（按 source_version 排序）、affected_versions\n"
        "- 如果 A 和 B 各自有独立的修复链，全部保留\n\n"
        "### 3. 累积风险评估（VersionEvolution）\n"
        "- 检查跨越 A 和 B 的同一组件的多个变更\n"
        "- 判断：单独看 A 和 B 各自风险低，但合并后是否风险累积\n"
        "- 典型模式：\n"
        "  - 模式A：v1 废弃接口 → v2 修改默认行为 → v3 移除兼容层\n"
        "  - 模式B：同一组件在多版本中持续调整，每次独立但组合后影响大\n"
        "  - 模式C：配置变更在多个版本中分步实施，跨越升级需要多次迁移\n"
        "- 创建 VersionEvolution 条目，risk_escalation_reason 必须具体说明\n"
        "  为什么'跨组升级'比'逐组升级'更危险\n\n"
        "### 4. Note 风险重评估\n"
        "- 检查所有 high risk notes，确认跨组视角下是否仍然是 high\n"
        "- 检查是否有 medium/low risk notes 在跨组关联后应升级为 high\n\n"
        "### 5. 兼容性风险与 Shadow Changes 合并\n"
        "- 合并 compatibility_risks，按 component 去重\n"
        "- 合并 shadow_changes，按 description 去重\n"
        "- 合并 test_points，去重\n\n"
        "## 输出格式\n\n"
        "输出 JSON，顶层字段如下：\n"
        "{\n"
        '  "executive_summary": {\n'
        '    "recommendation": "建议升级/谨慎升级/暂缓升级",\n'
        '    "theme": "核心主题",\n'
        '    "magnitude": "大/中/小",\n'
        '    "reason": "建议理由",\n'
        '    "top_changes": [...],\n'
        '    "one_liner": "一句话判断"\n'
        '  },\n'
        '  "developer_conclusion": "面向开发者的一句话结论",\n'
        '  "themes": [...],          // 合并后的 themes（完整格式）\n'
        '  "detailed_notes": [...],  // 合并后的 notes（high 完整，medium 核心，low 极简）\n'
        '  "compatibility_risks": [...],\n'
        '  "test_points": [...],\n'
        '  "shadow_changes": [...],\n'
        '  "progressive_fixes": [...],   // 连接后的修复链（完整）\n'
        '  "version_evolution": [...]    // 累积风险评估（完整）\n'
        "}\n\n"
        "关键要求：\n"
        "1) 不要丢失任何 high risk note 的信息\n"
        "2) 保留所有 progressive_fixes 的完整 stages（包括所有 note_id 和 source_version）\n"
        "3) VersionEvolution 的 risk_escalation_reason 必须具体，不能写空话\n"
        "4) 不要编造不存在的关联\n"
        "5) 主题合并时，如果两个 theme 的 note_ids 有重叠但描述不同，不要强行合并\n"
        "6) 如果是根节点合并（只剩两个组），executive_summary 和 developer_conclusion 必须完整生成\n"
        "7) 只输出 JSON，不要 markdown 代码块包裹"
    )
def parse_merge_results(response_text: str) -> LLMFullReport:
    """Parse LLM merge-layer response into LLMFullReport.

    Same format as parse_llm_results. May include executive_summary
    and developer_conclusion when the merge is at the root level.
    """
    text = re.sub(r"^```json\s*", "", response_text)
    text = re.sub(r"\s*```\s*$", "", text)
    payload = json.loads(text)

    report = LLMFullReport()

    if not isinstance(payload, dict):
        return report

    # Parse executive summary (may be present at root merge)
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
    report.test_points = [str(tp) for tp in payload.get("test_points", []) if tp]

    # Parse shadow changes
    report.shadow_changes = [sc for sc in payload.get("shadow_changes", []) if isinstance(sc, dict)]

    # Parse progressive fixes
    for pf in payload.get("progressive_fixes", []):
        if isinstance(pf, dict):
            fix = _parse_progressive_fix(pf)
            if fix:
                report.progressive_fixes.append(fix)

    # Parse version evolution
    for ve in payload.get("version_evolution", []):
        if isinstance(ve, dict):
            evo = _parse_version_evolution(ve)
            if evo:
                report.version_evolution.append(evo)

    return report


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
