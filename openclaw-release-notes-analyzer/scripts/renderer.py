"""Report rendering module for the OpenClaw Release Notes Analyzer.

Contains all Markdown report generation functions, including the main
render_report() function and all rendering helpers.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import CATEGORY_PRIMARY_ORDER
from i18n import T, _zh
from models import (
    ChangeAnalysis,
    LLMCompatibilityRisk,
    LLMFullReport,
    LLMNoteAnalysis,
    ProgressiveFix,
    Release,
    Theme,
    VersionEvolution,
)


def stable_releases(releases: Sequence[Release]) -> List[Release]:
    return [release for release in releases if release.is_stable]

def first_sentences(text: str, limit: int) -> List[str]:
    text = re.sub(r"\s+", " ", text)
    chunks = re.split(r"(?<=[.!?。！？])\s+", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()][:limit]


def newer_prereleases(releases: Sequence[Release], latest_stable: Release) -> List[Release]:
    stable_date = parse_date(latest_stable.published_at)
    return [
        r for r in releases
        if not r.draft and not r.is_stable and parse_date(r.published_at) > stable_date
    ]


def parse_date(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def recommendation(categories: Dict[str, List[str]], target: Release, strings: T) -> Tuple[str, str]:
    if not target.is_stable:
        return strings["defer_upgrade"], strings["reason_prerelease"]
    has_security = bool(categories["security"])
    has_stability = bool(categories["performance"])
    has_breaking = bool(categories["breaking"])
    has_public_surface = bool(categories["plugin"] or categories["api_sdk"])
    has_feature_or_fix = bool(categories["feature"] or categories["fix"])

    if has_security:
        return strings["recommend_upgrade"], strings["reason_security"]
    if has_breaking or has_public_surface:
        return strings["upgrade_with_caution"], strings["reason_breaking"]
    if has_stability:
        return strings["recommend_upgrade"], strings["reason_stability"]
    if has_feature_or_fix:
        return strings["conditional_upgrade"], strings["reason_feature_fix"]
    return strings["insufficient_data"], strings["reason_insufficient"]


# ---------------------------------------------------------------------------

# Rendering helpers
# ---------------------------------------------------------------------------





def build_appendix_ids(analyses: Sequence[ChangeAnalysis], limit: Optional[int] = None) -> Dict[str, str]:
    displayed = analyses if limit is None else analyses[:limit]
    appendix_ids: Dict[str, str] = {}
    for sequence, item in enumerate(displayed, start=1):
        appendix_ids[item.raw_text] = f"R-{sequence:03d}"
    return appendix_ids


def release_note_text(item: ChangeAnalysis, lang: str) -> str:
    # Always show original English text in the release note index section;
    # Chinese interpretation belongs in the appendix detail area instead.
    return item.raw_text


def release_note_tags(item: ChangeAnalysis, appendix_id: str, strings: T, lang: str) -> str:
    # Order: appendix_id → categories → risk
    # Tag labels follow the report language so they read consistently with the rest of the report.
    risk_icon = "🔴" if item.risk_level == "high" else ("⚠️" if item.risk_level == "medium" else "🟢")
    tags = [f"[`{appendix_id}`](#appendix-{appendix_id.lower()})"]
    tags.extend(f"`[{category_text(category, lang)}]`" for category in item.categories)
    tags.append(f"`[{risk_icon} {risk_text(item.risk_level, strings)}]`")
    return " ".join(tags)


def render_release_note_index_item(item: ChangeAnalysis, appendix_id: str, strings: T, lang: str) -> str:
    return f"- {release_note_text(item, lang)} - {release_note_tags(item, appendix_id, strings, lang)}"


def render_release_note_index(analyses: Sequence[ChangeAnalysis], appendix_ids: Dict[str, str], strings: T, lang: str) -> str:
    if not analyses:
        return strings["no_change_items"]
    return "\n".join(
        render_release_note_index_item(item, appendix_ids.get(item.raw_text, "R-???"), strings, lang)
        for item in analyses
    )






def render_prereleases(prereleases: Sequence[Release], include_beta: bool, strings: T) -> str:
    if not prereleases:
        return strings["no_prerelease"]
    th_ver = strings["th_version"]
    th_date = strings["th_publish_date"]
    th_desc = strings["th_description"]
    rows = [f"| {th_ver} | {th_date} | {th_desc} |", "|---|---|---|"]
    for release in prereleases[:8]:
        detail = first_sentences(release.body, 1)
        desc = (detail[0] if detail else strings["no_summary"])[:120]
        pub = release.published_at or strings["unknown"]
        rows.append(f"| `{release.tag_name}` | {pub} | {desc} |")
    note = strings["prerelease_included_note"] if include_beta else strings["prerelease_preview_note"]
    return note + "\n\n" + "\n".join(rows)


def risk_text(risk: str, strings: T) -> str:
    return strings.get(f"risk_{risk}", risk)


def confidence_text(confidence: str, strings: T) -> str:
    return strings.get(f"confidence_{confidence}", confidence)


CATEGORY_LABELS = {
    "zh": {
        "breaking": "破坏性/兼容性风险",
        "security": "安全/认证/凭据",
        "dependency": "依赖/运行时",
        "migration": "迁移",
        "plugin": "插件",
        "api_sdk": "API/SDK",
        "cli": "CLI",
        "config": "配置",
        "performance": "性能/稳定性",
        "fix": "修复",
        "feature": "新增能力",
        "docs": "文档/测试/质量保障",
        "known_issue": "已知问题",
        "other": "其他",
    },
}


def category_text(category: str, lang: str) -> str:
    labels = CATEGORY_LABELS["zh"]
    return labels.get(category, category.replace("_", "/"))








def report_scope_note(total: int, rendered: int, lang: str) -> str:
    if rendered == total:
        return f"- 完整解读覆盖率：{total}/{total} 条（完整逐条解读见附录，无省略）。"
    return f"- 完整解读覆盖率：{rendered}/{total} 条（当前仅展示部分条目）。"



def _infer_theme(categories: Dict[str, List[str]], lang: str) -> str:
    counts = {k: len(v) for k, v in categories.items() if v}
    if not counts:
        return "变化较少，难以判断核心主题"
    theme_candidates = [
        ("security", "安全加固为主", 3),
        ("breaking", "兼容性调整为主", 2),
        ("migration", "迁移与废弃项为主", 2),
        ("plugin", "插件系统更新为主", 2),
        ("api_sdk", "API/SDK 更新为主", 2),
        ("config", "配置与部署调整为主", 2),
        ("cli", "CLI 与工具链更新为主", 2),
        ("dependency", "依赖与运行时调整为主", 2),
        ("performance", "性能与稳定性优化为主", 1.5),
        ("fix", "Bug 修复与稳定性改进为主", 1),
        ("feature", "新功能增强为主", 1),
        ("docs", "文档与质量保障更新为主", 0.5),
    ]
    best_score = 0.0
    best_theme = ""
    for cat, label, weight in theme_candidates:
        score = counts.get(cat, 0) * weight
        if score > best_score:
            best_score = score
            best_theme = label
    return best_theme


def _infer_magnitude(total: int, high_risk: int, lang: str) -> str:
    if total < 10 and high_risk == 0:
        return "小"
    if total > 40 or high_risk >= 3:
        return "大"
    return "中等"


def render_executive_summary(
    analyses: Sequence[ChangeAnalysis],
    categories: Dict[str, List[str]],
    label: str,
    reason: str,
    target: Release,
    lang: str,
    strings: T,
) -> str:
    if not analyses:
        return "## 执行摘要\n\n未识别到可分析的 release note 条目。"
        return "## Executive Summary\n\nNo analyzable release note items found."
    high = len([a for a in analyses if a.risk_level == "high"])
    medium = len([a for a in analyses if a.risk_level == "medium"])
    low = len(analyses) - high - medium
    theme = _infer_theme(categories, lang)
    magnitude = _infer_magnitude(len(analyses), high, lang)
    top_items = analyses[:5]
    lines = [
        "## 执行摘要",
        "",
        f"**升级建议**：{label}",
        "",
        f"**核心主题**：{theme}",
        "",
        f"**变化量级**：{magnitude}（共 {len(analyses)} 条可分析变更，高风险 {high} 条、中风险 {medium} 条、低风险 {low} 条）",
        "",
        f"**建议理由**：{reason}",
        "",
        "**最关键变化**：",
    ]
    for idx, item in enumerate(top_items, 1):
        appendix_id = f"R-{idx:03d}"
        anchor = appendix_id.lower()
        risk_icon = "🔴" if item.risk_level == "high" else ("⚠️" if item.risk_level == "medium" else "🟢")
        cat_labels = " / ".join(category_text(cat, lang) for cat in item.categories[:2])
        lines.append(f"{idx}. [`{appendix_id}`](#appendix-{anchor}) {item.raw_text} — `[{cat_labels}]` `{risk_icon}`")
    lines.append("")
    if not target.is_stable:
        lines.append("**一句话判断**：目标版本为 prerelease，不建议用于生产环境。如需提前验证新特性，可在隔离环境试用。")
    elif high > 0 and (categories.get("breaking") or categories.get("migration")):
        lines.append("**一句话判断**：本版包含明确的兼容性风险信号，不建议直接升级。建议先对照下方「兼容性风险」确认影响范围，再决定排期。")
    elif high > 0 and categories.get("security"):
        lines.append("**一句话判断**：本版包含安全相关修复，建议优先评估受影响范围。如果当前部署涉及相关认证或权限链路，应在测试环境验证后尽快升级。")
    elif categories.get("plugin") or categories.get("api_sdk"):
        lines.append("**一句话判断**：本版对开发者可见表面有实质性更新，插件和 SDK 使用者建议重点核对兼容性。普通用户可根据自身需要决定是否跟进。")
    else:
        lines.append("**一句话判断**：本版变化风险较低，主要面向特定模块的功能增强或修复。如果新增能力或修复命中当前使用场景，可在常规升级窗口处理。")
    return "\n".join(lines)


def plugin_dev_relevance(item: ChangeAnalysis) -> int:
    score = item.priority
    important_categories = {"plugin", "api_sdk", "breaking", "config", "cli", "dependency", "migration", "security"}
    score += sum(12 for category in item.categories if category in important_categories)
    component_text = f"{item.component} {item.raw_text}".lower()
    keywords = {
        "plugin", "plugins", "channel", "channels", "account", "accounts", "auth", "oauth",
        "secret", "secrets", "gateway", "config", "manifest", "hook", "sdk", "cli", "doctor",
        "update", "telegram", "discord", "feishu", "slack", "provider",
    }
    score += sum(8 for keyword in keywords if keyword in component_text)
    if item.risk_level == "high":
        score += 18
    elif item.risk_level == "medium":
        score += 8
    return score


def filter_plugin_dev_relevant(analyses: Sequence[ChangeAnalysis]) -> List[ChangeAnalysis]:
    selected: List[ChangeAnalysis] = []
    for item in analyses:
        component_text = f"{item.component} {item.raw_text}".lower()
        has_direct_signal = any(
            category in item.categories
            for category in ["plugin", "api_sdk", "breaking", "config", "cli", "dependency", "migration", "security"]
        )
        has_keyword_signal = any(
            token in component_text
            for token in [
                "plugin", "channel", "account", "auth", "oauth", "secret", "gateway", "config",
                "manifest", "hook", "sdk", "cli", "doctor", "update", "telegram", "discord",
                "feishu", "slack", "provider",
            ]
        )
        if has_direct_signal or has_keyword_signal:
            selected.append(item)
    return sorted(selected, key=plugin_dev_relevance, reverse=True)


def top_changes_for_plugin_devs(analyses: Sequence[ChangeAnalysis], limit: int = 10) -> List[ChangeAnalysis]:
    return filter_plugin_dev_relevant(analyses)[:limit]


def developer_facing_conclusion(analyses: Sequence[ChangeAnalysis], lang: str, strings: T) -> str:
    relevant = filter_plugin_dev_relevant(analyses)
    if not relevant:
        return strings["no_relevant_changes"]

    has_breaking = any("breaking" in item.categories or "migration" in item.categories for item in relevant)
    security_count = len([i for i in relevant if "security" in i.categories])
    plugin_count = len([i for i in relevant if "plugin" in i.categories])
    api_count = len([i for i in relevant if "api_sdk" in i.categories])
    config_count = len([i for i in relevant if "config" in i.categories])

    top_components: List[str] = []
    for item in relevant:
        comp = item.component or ""
        if comp and comp not in top_components and comp != "General":
            top_components.append(comp)
        if len(top_components) >= 3:
            break

    if has_breaking:
        comps = "、".join(top_components[:2]) if top_components else "核心模块"
        return f"这是一版带兼容性包袱的更新，{comps} 存在 breaking change，不建议直接升级。先对照下方「风险点」确认你的插件接口、配置和依赖是否受影响，再决定排期。"
    if security_count >= 3:
        return "这是一版以安全收紧为主的补丁，认证、凭据和权限链路有多处调整。只要你用了 OAuth、SecretRef 或第三方 channel，升级前就值得逐条核对，别漏掉隐性授权变化。"
    if plugin_count >= 2 or api_count >= 2:
        comps = "、".join(top_components[:2]) if top_components else "插件与 SDK"
        return f"这版对开发者比较友好，{comps} 有实质性更新，没有明显的兼容性陷阱。建议先看「Top 10 变更」，再挑你关心的接口和工具链验证一遍即可。"
    if config_count >= 2:
        return "这版主要是配置结构和部署行为的调整，对已有插件代码影响不大，但运行时的配置加载路径可能有变化，建议重点核对 config 相关条目。"
    return "这版变动对插件 / channel 开发者有一定参考价值，建议优先浏览下方的「Top 变更」和「风险点」，再判断是否需要立即跟进。"


def render_compatibility_risks(analyses: Sequence[ChangeAnalysis], strings: T, lang: str) -> str:
    relevant = filter_plugin_dev_relevant(analyses)
    risky = [
        item for item in relevant
        if item.risk_level in {"high", "medium"} or any(cat in item.categories for cat in ["breaking", "migration", "dependency", "security"])
    ][:6]
    if not risky:
        return "- 暂未识别到明确的兼容性风险点。"

    def describe_risk(item: ChangeAnalysis) -> str:
        text = item.raw_text.lower()
        component = item.component or ("通用")

        if "breaking" in item.categories or "migration" in item.categories:
            if "codex" in text or "app-server" in text:
                return f"**{component}**：Codex 相关线程或上下文管理方式有变，如果之前依赖了旧版隐藏历史恢复机制，升级后可能丢失会话状态。"
            if "sdk" in text or "subpath" in text or "alias" in text:
                return f"**{component}**：SDK 子路径或包别名有调整，引用旧路径的插件可能直接解析失败，需要改 import。"
            return f"**{component}**：存在明确的 breaking change 或迁移要求，升级前必须确认现有代码、配置或依赖是否仍在支持范围内。"

        if "security" in item.categories:
            if "env" in text or "secretref" in text or "credential" in text:
                return f"**{component}**：凭据解析规则收紧，之前可能自动生效的环境变量或隐式授权现在需要显式配置，否则接口调用会因认证失败而中断。"
            if "oauth" in text or "auth" in text:
                return f"**{component}**：OAuth 或账号认证逻辑有变，现有 auth profile 可能失效或需要重新走授权流程。"
            if "sandbox" in text or "windows" in text:
                return f"**{component}**：沙箱或文件系统绑定策略收紧，Windows 下的凭据目录访问可能受限，容器或自定义 HOME 场景需特别留意。"
            return f"**{component}**：安全策略调整，权限边界或默认行为可能变化，确认现有部署是否仍满足新的安全假设。"

        if "dependency" in item.categories:
            return f"**{component}**：依赖版本有升级或替换，如果锁文件或构建镜像没同步更新，安装或启动阶段可能报错。"

        if "config" in item.categories:
            return f"**{component}**：配置结构或默认值有调整，老配置可能仍能解析但行为不同，建议用真实环境做一次配置校验。"

        return f"**{component}**：{item.interpretation}"

    lines: List[str] = []
    seen_texts: set[str] = set()
    for item in risky:
        desc = describe_risk(item)
        if desc not in seen_texts:
            seen_texts.add(desc)
            lines.append(f"- {desc}")

    return "\n".join(lines)


def render_suggested_test_points(analyses: Sequence[ChangeAnalysis], lang: str) -> str:
    relevant = filter_plugin_dev_relevant(analyses)
    if not relevant:
        return "- 暂无明确测试点，建议至少回归主要 channel 收发链路。"
    suggestions: List[str] = []
    text = " ".join(item.raw_text.lower() for item in relevant[:12])
    if any(token in text for token in ["account", "auth", "oauth", "secret", "credential"]):
        suggestions.append("回归账号登录、OAuth、SecretRef/凭据读取与默认账号解析。")
    if any(token in text for token in ["plugin", "manifest", "hook", "sdk"]):
        suggestions.append("验证插件安装、manifest 解析、hook 执行与 SDK 类型/子路径引用。")
    if any(token in text for token in ["cli", "doctor", "update", "config"]):
        suggestions.append("回归 doctor / update / config validate 等 CLI 命令在真实配置下的输出与修复流程。")
    if any(token in text for token in ["channel", "telegram", "discord", "feishu", "gateway"]):
        suggestions.append("验证 channel 启动、消息收发、热重载、重启恢复与默认路由是否保持稳定。")
    if any(token in text for token in ["dependency", "node", "runtime", "pnpm"]):
        suggestions.append("确认 Node.js / 依赖版本要求满足升级前提，并验证安装链路。")
    if not suggestions:
        suggestions.append("至少验证插件加载、channel 收发、配置校验、升级/回滚四条主链路。")
    return "\n".join(f"- {item}" for item in suggestions[:5])


# ---------------------------------------------------------------------------
# Thematic clustering rendering (new)
# ---------------------------------------------------------------------------

def _risk_sort_key(theme: Theme) -> Tuple[int, int]:
    """Sort themes: high risk first, then by note count descending."""
    risk_rank = {"high": 0, "medium": 1, "low": 2}
    return (risk_rank.get(theme.risk_level, 2), -len(theme.note_ids))


def render_themes_overview(
    themes: Sequence[Theme],
    analyses_map: Dict[str, ChangeAnalysis],
    lang: str,
) -> str:
    """Render a thematic overview of all changes.

    Groups related release notes into semantic themes so the reader gets
    a structured summary instead of 460 fragmented bullet points.
    """
    if not themes:
        return "- 暂无主题聚类数据。"

    sorted_themes = sorted(themes, key=_risk_sort_key)
    lines: List[str] = []

    lines.append("## 变更主题概览")
    lines.append("")
    lines.append(f"本次更新可归纳为 **{len(themes)}** 个主题，按风险等级排序：")
    lines.append("")
    lines.append("| 主题 | 条目数 | 风险 | 关联 Commit | 概括 |")
    lines.append("|---|---|---|---|---|")
    for theme in sorted_themes:
        risk_icon = "🔴" if theme.risk_level == "high" else ("⚠️" if theme.risk_level == "medium" else "🟢")
        commit_str = " ".join(f"`{c[:7]}`" for c in theme.related_commits[:3]) if theme.related_commits else "-"
        # Overview uses summary only; impact is shown in the deep-dive section
        summary = theme.summary or "-"
        note_count = len(theme.note_ids)
        lines.append(f"| **{theme.theme_name}** | {note_count} | {risk_icon} {theme.risk_level} | {commit_str} | {summary} |")

    # Add high-risk theme quick summary
    high_risk_themes = [t for t in sorted_themes if t.risk_level == "high"]
    if high_risk_themes:
        lines.append("")
        lines.append("**需要重点关注的高风险主题**：")
        for theme in high_risk_themes:
            impact = theme.impact or theme.summary or ""
            lines.append(f"- **{theme.theme_name}**：{impact}")

    return "\n".join(lines)


def render_progressive_fixes(
    fixes: Sequence[ProgressiveFix],
    lang: str,
) -> str:
    """Render progressive fix chains detected across multiple versions.

    Shows how the same issue was addressed incrementally across releases.
    """
    if not fixes:
        return "- 未检测到渐进式修复链。"

    lines: List[str] = []
    lines.append("## 渐进式修复检测")
    lines.append("")
    lines.append(f"检测到 **{len(fixes)}** 个跨版本的渐进式修复链：")
    lines.append("")
    for idx, fix in enumerate(fixes, 1):
        status_label = {
            "fully_fixed": ("已完全修复", "Fully Fixed"),
            "partially_fixed": ("仍部分修复", "Partially Fixed"),
            "mitigated": ("仅缓解", "Mitigated"),
        }.get(fix.final_status, (fix.final_status, fix.final_status))

        lines.append(f"### PF-{idx:02d}：{fix.issue_description or '未命名问题'}")
        lines.append("")
        lines.append(f"**最终状态**：{status_label[0]}")
        if fix.affected_components:
            lines.append(f"**受影响组件**：{', '.join(fix.affected_components)}")
        lines.append("")
        lines.append("| 阶段 | 版本 | 修复内容 | 完整度 |")
        lines.append("|---|---|---|---|")
        completeness_label = {
            "mitigation": "缓解",
            "partial": "部分修复",
            "complete": "完整修复",
        }

        for stage_idx, stage in enumerate(fix.stages, 1):
            ver = stage.get("source_version", "-")
            desc = stage.get("fix_description", "-")
            comp = stage.get("completeness", "")
            comp_text = completeness_label.get(comp, comp)
            lines.append(f"| {stage_idx} | `{ver}` | {desc} | {comp_text} |")

        if fix.impact_assessment:
            lines.append("")
            lines.append(f"**影响评估**：{fix.impact_assessment}")
        lines.append("")

    return "\n".join(lines)


def render_version_evolution(
    evolutions: Sequence[VersionEvolution],
    lang: str,
) -> str:
    """Render cumulative breaking change analysis across version ranges.

    Highlights cases where individual versions appear low-risk but the
    aggregate impact across the upgrade path is high.
    """
    if not evolutions:
        return "- 未检测到累积 Breaking Change 风险。"

    lines: List[str] = []
    lines.append("## 累积 Breaking Change 分析")
    lines.append("")
    lines.append(f"检测到 **{len(evolutions)}** 个版本演进模式，单版本风险可能被低估：")
    lines.append("")
    for idx, evo in enumerate(evolutions, 1):
        risk_icon_ind = "🔴" if evo.individual_risk == "high" else ("⚠️" if evo.individual_risk == "medium" else "🟢")
        risk_icon_cum = "🔴" if evo.cumulative_risk == "high" else ("⚠️" if evo.cumulative_risk == "medium" else "🟢")

        lines.append(f"### VE-{idx:02d}：{evo.description or '未命名演进'}")
        lines.append("")
        vers = " → ".join(f"`{v}`" for v in evo.affected_versions)
        lines.append(f"**涉及版本**：{vers}")
        lines.append(f"**单版本风险**：{risk_icon_ind} {evo.individual_risk}　**累积风险**：{risk_icon_cum} {evo.cumulative_risk}")
        if evo.affected_components:
            lines.append(f"**受影响组件**：{', '.join(evo.affected_components)}")
        lines.append("")
        if evo.risk_escalation_reason:
            lines.append(f"**风险升级原因**：{evo.risk_escalation_reason}")
            lines.append("")
        if evo.migration_advice:
            lines.append(f"**迁移建议**：{evo.migration_advice}")
        lines.append("")

    return "\n".join(lines)


def render_themed_deep_dive(
    themes: Sequence[Theme],
    analyses: Sequence[ChangeAnalysis],
    detailed_notes: Sequence[LLMNoteAnalysis],
    lang: str,
    strings: T,
) -> str:
    """Render detailed analysis for high and medium risk themes.

    Unlike the old component-based grouping, this groups by functional theme
    so related changes (e.g., all Gemini ID normalizations) are analyzed together.
    """
    if not themes:
        return "- 暂无足够变更数据可供深度分析。"

    # Only expand high/medium risk themes
    risky_themes = [t for t in themes if t.risk_level in ("high", "medium")]
    risky_themes = sorted(risky_themes, key=_risk_sort_key)

    if not risky_themes:
        return "- 本次无高风险或中风险主题需要展开分析。"

    analysis_map = {f"R-{i+1:03d}": a for i, a in enumerate(analyses)}
    detailed_map = {dn.note_id: dn for dn in detailed_notes if dn.note_id}

    blocks: List[str] = []
    for theme in risky_themes[:12]:
        risk_icon = "🔴" if theme.risk_level == "high" else "⚠️"

        note_descs: List[str] = []
        for nid in theme.note_ids[:20]:
            analysis = analysis_map.get(nid)
            if analysis:
                text = analysis.raw_text
                note_risk = "🔴" if analysis.risk_level == "high" else ("⚠️" if analysis.risk_level == "medium" else "🟢")
                note_descs.append(f"- [`{nid}`](#appendix-{nid.lower()}) {note_risk} {text}")

        # Build affected files display
        files_str = ""
        if theme.affected_files:
            file_list = ", ".join(f"`{f}`" for f in theme.affected_files[:5])
            files_str = f"\n\n**受影响文件**：{file_list}"
        # Build commit evidence
        commit_str = ""
        if theme.related_commits:
            commit_list = ", ".join(f"`{c[:7]}`" for c in theme.related_commits)
            commit_str = f"\n\n**关联 Commit**：{commit_list}"
        # Navigation links to appendix detailed notes
        nav_links: List[str] = []
        for nid in theme.note_ids:
            if nid in detailed_map:
                nav_links.append(f"- [`{nid}`](#appendix-{nid.lower()})")

        nav_section = ""
        if nav_links[:15]:
            nav_section = "\n\n**相关详细分析**：\n" + "\n".join(nav_links[:15])
            if len(nav_links) > 15:
                nav_section += f"\n- ... 及其他 {len(nav_links) - 15} 条"

        desc_text = "\n".join(note_descs) if note_descs else ("- 暂无关联条目数据")

        block = (
            f"### {theme.theme_name}（{len(theme.note_ids)} 条）\n\n"
            f"**概括**：{theme.summary or '-'}\n\n"
            f"**影响**：{theme.impact or '详见具体条目'}\n\n"
            f"**风险等级**：{risk_icon} {theme.risk_level}\n\n"
            f"**AI 判断依据**：{theme.reasoning or '基于 release note 文本分析'}"
            f"{files_str}{commit_str}\n\n"
            f"**涉及条目**：\n{desc_text}{nav_section}"
        )
        blocks.append(block)

    header = "## 高风险主题详解"
    return header + "\n\n" + "\n\n---\n\n".join(blocks)


def render_code_evidence(
    detailed_notes: Sequence[LLMNoteAnalysis],
    analyses: Sequence[ChangeAnalysis],
    lang: str,
) -> str:
    """Render a table showing note-to-commit associations and code evidence.

    Based on per-note analysis data (detailed_notes) rather than theme-level
    aggregation for accurate note-to-commit mapping.
    """
    if not detailed_notes:
        return "- 暂无代码关联数据。"

    # Build note_id -> ChangeAnalysis mapping
    analysis_map = {f"R-{i+1:03d}": a for i, a in enumerate(analyses)}
    detailed_map = {dn.note_id: dn for dn in detailed_notes if dn.note_id}

    rows = []
    for nid, detail in detailed_map.items():
        if not detail.matched_commits and not detail.reasoning and not detail.affected_files:
            continue

        analysis = analysis_map.get(nid)
        raw_text = analysis.raw_text if analysis else ""

        commit_links = " ".join(f"`{c[:7]}`" for c in detail.matched_commits) if detail.matched_commits else "-"
        file_links = " ".join(f"`{f}`" for f in detail.affected_files[:3]) if detail.affected_files else "-"
        reasoning = detail.reasoning or ""
        if reasoning:
            reasoning = reasoning.replace("\n", "<br>")

        rows.append((nid, raw_text, commit_links, file_links, reasoning))

    if not rows:
        return "- 暂无 commit 关联证据。"

    lines = [
        "## 代码变更证据链",
        "",
        "| Note ID | Release Note 摘要 | 关联 Commit | 改动文件 | 推理依据 |",
        "|---|---|---|---|---|",
    ]
    for nid, raw, commits, files, reasoning in rows[:25]:
        lines.append(f"| [`{nid}`](#appendix-{nid.lower()}) | {raw} | {commits} | {files} | {reasoning or '-'} |")

    return "\n".join(lines)


def render_shadow_changes(
    shadow_changes: Sequence[Dict[str, Any]],
    lang: str,
) -> str:
    """Render undocumented modifications found in commits but not in release notes."""
    if not shadow_changes:
        return "- 未发现未在 release notes 中提及的代码变更。"

    lines: List[str] = []
    lines.append("## 未记录变更提示")
    lines.append("")
    lines.append("以下代码变更在 commit 中有体现，但在 release notes 中未明确提及：")
    lines.append("")
    for idx, sc in enumerate(shadow_changes, 1):
        desc = sc.get("description", "")
        commits = sc.get("evidence_commits", [])
        commit_str = " ".join(f"`{c[:7]}`" for c in commits) if commits else "-"
        lines.append(f"{idx}. {desc}（证据 commit: {commit_str}）")
    return "\n".join(lines)


def render_per_note_analysis(
    analyses: Sequence[ChangeAnalysis],
    strings: T,
    lang: str,
    limit: Optional[int] = None,
) -> str:
    """Render detailed per-note analysis for LLM-enhanced or high-risk items only.

    Instead of dumping all 460 notes, we only show notes that have actual
    LLM enrichment (commit associations, code evidence) or are high-risk.
    """
    if not analyses:
        return strings["no_change_items"]

    # Filter: only LLM-enhanced or high-risk notes
    eligible = [
        a for a in analyses
        if a.llm_enhanced or a.risk_level == "high" or a.affected_files or a.code_evidence
    ]
    if not eligible:
        return "- 本次无 LLM 增强的高风险条目，逐条明细已省略。详见上方主题概览。"
        return "- No LLM-enhanced high-risk items this time; per-note details omitted. See thematic overview above."

    # Sort by priority, cap at 40
    eligible = sorted(eligible, key=lambda a: a.priority, reverse=True)
    max_items = limit if limit is not None else 40
    displayed = eligible[:max_items]

    appendix_ids = build_appendix_ids(analyses)
    blocks: List[str] = [
        f"- 以下展示 **{len(displayed)}** 条有 LLM 代码关联或高风险的条目（共 {len(analyses)} 条）。"
    ]
    field_header = "字段"
    value_header = "内容"
    raw_release_label = "原始 Release Note"

    for item in displayed:
        categories = ", ".join(category_text(cat, lang) for cat in item.categories)
        audience = ", ".join(item.audience)
        actions = "<br>".join(f"• {action}" for action in item.action_items)
        appendix_id = appendix_ids.get(item.raw_text, "R-???")
        appendix_anchor = appendix_id.lower()
        raw_text = release_note_text(item, lang).replace("|", "\\|")
        component = (item.component or "General").replace("|", "\\|")
        interpretation = item.interpretation.replace("\n", "<br>")
        # Build table rows
        rows = [
            f"| {field_header} | {value_header} |",
            "|---|---|",
            f"| {strings['component_label']} | {component} |",
            f"| {strings['release_label']} | `{item.release_tag}` |",
            f"| {strings['risk_label']} | {risk_text(item.risk_level, strings)} |",
            f"| {strings['confidence_label']} | {confidence_text(item.confidence, strings)} |",
            f"| {strings['categories_label']} | {categories} |",
            f"| {strings['audience_label']} | {audience} |",
        ]
        # Add affected files row if LLM-enhanced
        if item.affected_files:
            files_str = ", ".join(f"`{f}`" for f in item.affected_files[:8])
            if len(item.affected_files) > 8:
                files_str += f" 等 {len(item.affected_files) - 8} 个文件"
            label_af = strings.get("affected_files_label", "受影响文件")
            rows.append(f"| {label_af} | {files_str} |")
        # Add code evidence row if present
        if item.code_evidence:
            evidence = item.code_evidence.replace("|", "\\|").replace("\n", "<br>")
            label_ce = strings.get("code_evidence_label", "代码证据")
            rows.append(f"| {label_ce} | `{evidence}` |")
        # Add LLM reasoning row if present
        if item.llm_reasoning:
            reasoning = item.llm_reasoning.replace("|", "\\|").replace("\n", "<br>")
            label_lr = "AI 推理过程"
            rows.append(f"| {label_lr} | {reasoning} |")
        rows.extend([
            f"| {raw_release_label} | {raw_text} |",
            f"| {strings['change_interpretation']} | {interpretation} |",
            f"| {strings['action_label']} | {actions} |",
        ])
        blocks.append(
            f"<a id=\"appendix-{appendix_anchor}\"></a>\n"
            f"#### {appendix_id}\n\n"
            + "\n".join(rows)
        )

    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# LLM-output rendering helpers (new architecture)
# ---------------------------------------------------------------------------

def _render_executive_summary_from_llm(
    es: Any,
    lang: str,
) -> str:
    """Render executive summary directly from LLM output."""
    if not es or not isinstance(es, dict):
        return "## 执行摘要\n\n（LLM 未提供执行摘要）"

    rec = es.get("recommendation", "")
    theme = es.get("theme", "")
    magnitude = es.get("magnitude", "")
    reason = es.get("reason", "")
    top_changes = es.get("top_changes", [])
    one_liner = es.get("one_liner", "")

    lines = ["## 执行摘要", ""]
    if rec:
        lines.append(f"**升级建议**：{rec}")
        lines.append("")
    if theme:
        lines.append(f"**核心主题**：{theme}")
        lines.append("")
    if magnitude:
        lines.append(f"**变化量级**：{magnitude}")
        lines.append("")
    if reason:
        lines.append(f"**建议理由**：{reason}")
        lines.append("")
    if top_changes:
        lines.append("**最关键变化**：")
        for idx, tc in enumerate(top_changes[:5], 1):
            nid = tc.get("note_id", "")
            text = tc.get("text") or tc.get("description", "")
            risk = tc.get("risk", "low")
            risk_icon = "🔴" if risk == "high" else ("⚠️" if risk == "medium" else "🟢")
            anchor = f"appendix-{nid.lower()}" if nid else ""
            nid_link = f"[`{nid}`](#{anchor})" if nid else f"`{nid}`"
            lines.append(f"{idx}. {nid_link} {text} — {risk_icon}")
        lines.append("")
    if one_liner:
        lines.append(f"**一句话判断**：{one_liner}")
    return "\n".join(lines)


def _render_compatibility_risks_from_llm(
    risks: Sequence[LLMCompatibilityRisk],
    lang: str,
) -> str:
    """Render compatibility risks as a structured table."""
    if not risks:
        return "- 暂未识别到明确的兼容性风险点。"

    lines = [
        "| 组件 | 风险描述 |",
        "|---|---|",
    ]
    seen: set[str] = set()
    for r in risks:
        key = f"{r.component}:{r.description}"
        if key in seen:
            continue
        seen.add(key)
        comp = r.component or ("通用")
        desc = r.description or "-"
        lines.append(f"| **{comp}** | {desc} |")

    return "\n".join(lines)


def _render_test_points_from_llm(
    points: Sequence[str],
    lang: str,
) -> str:
    """Render test points directly from LLM output."""
    if not points:
        return "- 暂无明确测试点。"
    return "\n".join(f"- {p}" for p in points[:8])


def _render_detailed_notes_from_llm(
    notes: Sequence[LLMNoteAnalysis],
    lang: str,
    analyses: Sequence[ChangeAnalysis],
) -> str:
    """Render detailed note analysis directly from LLM output."""
    if not notes:
        return "- 暂无 LLM 逐条分析数据。"

    # Build note_id -> ChangeAnalysis mapping for raw_text lookup
    analysis_map = {a.note_id: a for a in analyses if a.note_id}

    field_header = "字段"
    value_header = "内容"
    raw_label = "原始 Release Note"

    # Row labels keyed by language
    _lbl = {
        "component": "组件",
        "risk_level": "风险等级",
        "categories": "分类",
        "audience": "影响对象",
        "commits": "关联 Commit",
        "files": "受影响文件",
        "reasoning": "AI 推理过程",
        "interpretation": "变更解读",
        "actions": "建议动作",
    }

    def lbl(key: str) -> str:
        return _lbl.get(key, key)

    blocks: List[str] = []

    for item in notes[:80]:
        nid = item.note_id or "R-???"
        categories = ", ".join(item.categories) if item.categories else "-"
        audience = ", ".join(item.audience) if item.audience else "-"
        actions = "<br>".join(f"• {a}" for a in item.action_items) if item.action_items else "-"
        commits = " ".join(f"`{c[:7]}`" for c in item.matched_commits) if item.matched_commits else "-"
        files = " ".join(f"`{f}`" for f in item.affected_files[:5]) if item.affected_files else "-"

        # Look up raw release note text from ChangeAnalysis
        raw_text = "-"
        if nid in analysis_map:
            raw_text = analysis_map[nid].raw_text.replace("|", "\\|").replace("\n", "<br>")

        rows = [
            f"| {field_header} | {value_header} |",
            "|---|---|",
            f"| Note ID | [`{nid}`](#appendix-{nid.lower()}) |",
            f"| {lbl('component')} | {item.component or '-'} |",
            f"| {lbl('risk_level')} | {item.risk_level} |",
            f"| {lbl('categories')} | {categories} |",
            f"| {lbl('audience')} | {audience} |",
        ]
        if item.matched_commits:
            rows.append(f"| {lbl('commits')} | {commits} |")
        if item.affected_files:
            rows.append(f"| {lbl('files')} | {files} |")
        if item.reasoning:
            reasoning = item.reasoning.replace("|", "\\|").replace("\n", "<br>")
            rows.append(f"| {lbl('reasoning')} | {reasoning} |")
        rows.extend([
            f"| {raw_label} | {raw_text} |",
            f"| {lbl('interpretation')} | {item.interpretation.replace(chr(124), chr(92)+chr(124)).replace(chr(10), '<br>') if item.interpretation else '-'} |",
            f"| {lbl('actions')} | {actions} |",
        ])
        blocks.append(
            f"<a id=\"appendix-{nid.lower()}\"></a>\n"
            f"#### {nid}\n\n"
            + "\n".join(rows)
        )

    count = len(notes[:80])
    header = "## 附录：LLM 增强逐条明细"
    intro = f"以下展示 **{count}** 条经 LLM 深度分析的条目。这些条目覆盖高风险主题、有代码关联证据或有隐藏破坏性变更的 note。"
    return header + "\n\n" + intro + "\n\n" + "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------

def render_report(
    repo: str,
    target: Release,
    compare: Optional[Release],
    scoped: Sequence[Release],
    releases: Sequence[Release],
    include_beta: bool,
    lang: str,
    data_source: str = "GitHub Releases API snapshot",
    snapshot_file: Optional[str] = None,
    output_file: Optional[str] = None,
    analyses: Optional[List[ChangeAnalysis]] = None,
    categories: Optional[Dict[str, List[str]]] = None,
    llm_report: Optional[LLMFullReport] = None,
) -> str:

    if analyses is None:
        raise ValueError("analyses is required; pass pre-computed analyses from the caller")
    if categories is None:
        raise ValueError("categories is required; pass pre-computed categories from the caller")

    has_llm = llm_report is not None and (
        llm_report.themes
        or llm_report.detailed_notes
        or llm_report.executive_summary.recommendation
        or llm_report.progressive_fixes
        or llm_report.version_evolution
        or llm_report.shadow_changes
        or llm_report.compatibility_risks
        or llm_report.test_points
        or llm_report.developer_conclusion
    )

    strings = _zh()
    appendix_ids = build_appendix_ids(analyses)
    for key in list(categories):
        categories[key] = [item.raw_text for item in analyses if key in item.categories]

    stable = stable_releases(releases)
    latest_stable = stable[0] if stable else target
    prereleases = newer_prereleases(releases, latest_stable)
    title_compare = compare.tag_name if compare else strings["no_baseline"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def f(key: str) -> str:
        return strings.get(key, key)

    src_links = "\n".join(
        f"- [{r.tag_name}]({r.html_url})" for r in scoped if r.html_url
    ) or f"- {strings['unknown']}"

    target_url = target.html_url or strings["unknown"]
    snapshot_display = snapshot_file or strings["unknown"]

    # Build analyses map for theme rendering
    analyses_map = {a.raw_text: a for a in analyses}

    # P1-4: Build included releases table when scoped has more than 1 release
    included_releases_section = ""
    if len(scoped) > 1:
        included_versions = "\n".join(
            f"| `{r.tag_name}` | {r.published_at[:10] if r.published_at else strings['unknown']} | {f('stable') if r.is_stable else f('prerelease_beta')} |"
            for r in scoped
        )
        included_releases_section = f"""
## {f('included_releases')}

| {f('field_target_version')} | {f('field_publish_date')} | {f('field_target_status')} |
|---|---|---|
{included_versions}

"""

    if has_llm:
        # === LLM-driven report: all semantic content comes from LLM ===
        executive_summary = _render_executive_summary_from_llm(
            llm_report.executive_summary.__dict__ if llm_report.executive_summary else {}, lang
        )
        developer_conclusion = llm_report.developer_conclusion if llm_report.developer_conclusion else ""
        # Strip redundant inner heading to avoid duplicate "Developer Conclusion" titles
        developer_conclusion = re.sub(r'^#{1,3}\s*开发者结论\s*\n+', '', developer_conclusion, flags=re.IGNORECASE)
        developer_conclusion = re.sub(r'^#{1,3}\s*Developer Conclusion\s*\n+', '', developer_conclusion, flags=re.IGNORECASE)
        themes_overview = render_themes_overview(llm_report.themes, analyses_map, lang)
        progressive_fixes_section = render_progressive_fixes(llm_report.progressive_fixes, lang)
        version_evolution_section = render_version_evolution(llm_report.version_evolution, lang)
        deep_dive_section = render_themed_deep_dive(llm_report.themes, analyses, llm_report.detailed_notes, lang, strings)
        code_evidence_section = render_code_evidence(llm_report.detailed_notes, analyses, lang)
        shadow_section = render_shadow_changes(llm_report.shadow_changes, lang)
        compatibility_section = _render_compatibility_risks_from_llm(llm_report.compatibility_risks, lang)
        test_points_section = _render_test_points_from_llm(llm_report.test_points, lang)
    else:
        # === Rule-based fallback (no LLM or --no-llm) ===
        label, reason = recommendation(categories, target, strings)
        executive_summary = render_executive_summary(
            analyses, categories, label, reason, target, lang, strings
        )
        developer_conclusion = developer_facing_conclusion(analyses, lang, strings)
        themes_overview = "- 暂无主题聚类数据。"
        progressive_fixes_section = "- 未检测到渐进式修复链。"
        version_evolution_section = "- 未检测到累积 Breaking Change 风险。"
        deep_dive_section = "- 暂无深度分析数据。"
        code_evidence_section = "- 暂无代码关联证据。"
        shadow_section = render_shadow_changes([], lang)
        compatibility_section = render_compatibility_risks(analyses, strings, lang)
        test_points_section = render_suggested_test_points(analyses, lang)

    # Appendix: show LLM detailed_notes when available, otherwise rule-based enhanced notes
    if has_llm and llm_report.detailed_notes:
        appendix_section = _render_detailed_notes_from_llm(llm_report.detailed_notes, lang, analyses)
    else:
        appendix_section = f"""
## {f('per_note_analysis')}

{render_per_note_analysis(analyses, strings, lang, None)}
"""

    return f"""# {f('report_title')}


**{f('repo')}**: <https://github.com/{repo}>
**{f('field_target_version')}**: `{target.tag_name}`
**{f('field_compare_version')}**: `{title_compare}`
**{f('generated_at')}**: {now}

---

## {f('version_info')}

| {f('field_target_version')} | `{target.tag_name}` |
|---|---|
| {f('field_publish_date')} | {target.published_at or strings['unknown']} |
| {f('field_target_status')} | {f('stable') if target.is_stable else f('prerelease_beta')} |
| {f('field_compare_version')} | `{title_compare}` |
| {f('field_releases_analyzed')} | {len(scoped)} |
| {f('field_data_source')} | {data_source} |
| Snapshot File | `{snapshot_display}` |
| Report File | `{output_file or strings['unknown']}` |

{included_releases_section}
---

{executive_summary}

---

## 面向开发者的结论

{developer_conclusion}

---

{themes_overview}

---

{progressive_fixes_section}

---

{version_evolution_section}

---

{deep_dive_section}

---

{code_evidence_section}

---

{shadow_section}

---

## {f('compatibility_risks')}

{compatibility_section}

---

## {f('suggested_test_points')}

{test_points_section}

---

## {f('beta_preview')}


{render_prereleases(prereleases, include_beta, strings)}

---

## {f('references')}

{src_links}

---

## 原始 Release Notes（增强标注）

{render_release_note_index(analyses, appendix_ids, strings, lang)}

---

{appendix_section}

---

*{f('footer')}*
"""

