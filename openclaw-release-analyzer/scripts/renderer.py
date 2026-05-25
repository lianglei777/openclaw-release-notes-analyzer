"""Report rendering module for the OpenClaw Release Analyzer.

Contains all Markdown report generation functions, including the main
render_report() function and all rendering helpers.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import CATEGORY_PRIMARY_ORDER
from i18n import T, _en, _zh, translate_release_note_zh
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





def build_analysis_lookup(analyses: Sequence[ChangeAnalysis]) -> Dict[str, ChangeAnalysis]:
    return {item.raw_text: item for item in analyses}


def build_appendix_ids(analyses: Sequence[ChangeAnalysis], limit: Optional[int] = None) -> Dict[str, str]:
    displayed = analyses if limit is None else analyses[:limit]
    appendix_ids: Dict[str, str] = {}
    for sequence, item in enumerate(displayed, start=1):
        appendix_ids[item.raw_text] = f"R-{sequence:03d}"
    return appendix_ids


def brief_change_summary(item: ChangeAnalysis, lang: str) -> str:
    focus_zh = "常规升级验证"
    if "breaking" in item.categories or "migration" in item.categories:
        focus_zh = "兼容性、迁移步骤和旧用法回归"
    elif "security" in item.categories:
        focus_zh = "认证、权限、凭据或安全边界"
    elif "dependency" in item.categories:
        focus_zh = "依赖版本、安装链路、构建镜像或 CI/CD 运行时"
    elif "plugin" in item.categories:
        focus_zh = "插件 manifest、hook、加载顺序或扩展契约"
    elif "api_sdk" in item.categories:
        focus_zh = "API/SDK 导出、类型定义或封装层兼容性"
    elif "cli" in item.categories:
        focus_zh = "CLI 参数、子命令、输出格式或脚本兼容性"
    elif "config" in item.categories:
        focus_zh = "配置 schema、默认值或环境变量约定"
    elif "performance" in item.categories:
        focus_zh = "关键路径性能、稳定性或启动行为"
    elif "fix" in item.categories:
        focus_zh = "受影响流程的旧问题复现和修复确认"
    elif "feature" in item.categories:
        focus_zh = "是否需要新增能力及对应集成成本"

    if lang == "zh":
        return f"影响 {item.component}，重点关注{focus_zh}。"

    focus_en = focus_zh
    return f"Affects {item.component}; review {focus_en}."


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






def scenario_advice(kind: str, categories: Dict[str, List[str]], strings: T) -> str:
    dispatch = {
        "plugin": (strings["adv_plugin_has_signal"], strings["adv_plugin_no_signal"]),
        "api_sdk": (strings["adv_api_has_signal"], strings["adv_api_no_signal"]),
        "security": (strings["adv_security_has_signal"], strings["adv_security_no_signal"]),
        "performance": (strings["adv_perf_has_signal"], strings["adv_perf_no_signal"]),
        "ordinary": (None, None),
    }
    has_signal_map = {
        "plugin": bool(categories["plugin"] or categories["breaking"]),
        "api_sdk": bool(categories["api_sdk"] or categories["breaking"]),
        "security": bool(categories["security"]),
        "performance": bool(categories["performance"]),
        "ordinary": bool(categories["feature"] or categories["fix"]),
    }
    has_signal = has_signal_map.get(kind, False)
    if kind == "ordinary":
        if has_signal:
            return strings["adv_feature_fix"]
        return strings["adv_insufficient"]
    return dispatch.get(kind, ("", ""))[0 if has_signal else 1]


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
    "en": {
        "breaking": "Breaking/compatibility risk",
        "security": "Security/auth/credentials",
        "dependency": "Dependency/runtime",
        "migration": "Migration",
        "plugin": "Plugin",
        "api_sdk": "API/SDK",
        "cli": "CLI",
        "config": "Configuration",
        "performance": "Performance/stability",
        "fix": "Fix",
        "feature": "Feature",
        "docs": "Docs/tests/QA",
        "known_issue": "Known issue",
        "other": "Other",
    },
}


def category_text(category: str, lang: str) -> str:
    labels = CATEGORY_LABELS.get(lang, CATEGORY_LABELS["en"])
    return labels.get(category, category.replace("_", "/"))








def report_scope_note(total: int, rendered: int, lang: str) -> str:
    if lang == "zh":
        if rendered == total:
            return f"- 完整解读覆盖率：{total}/{total} 条（完整逐条解读见附录，无省略）。"
        return f"- 完整解读覆盖率：{rendered}/{total} 条（当前仅展示部分条目）。"
    if rendered == total:
        return f"- Per-note interpretation coverage: {total}/{total} items (complete details in appendix, no omissions)."
    return f"- Per-note interpretation coverage: {rendered}/{total} items shown."



def render_analytical_summary(analyses: Sequence[ChangeAnalysis], categories: Dict[str, List[str]], lang: str) -> str:

    if not analyses:
        return "- 未发现可分析的 release note 条目。" if lang == "zh" else "- No analyzable release note items found."
    high = [a for a in analyses if a.risk_level == "high"]
    medium = [a for a in analyses if a.risk_level == "medium"]
    top_components: List[str] = []
    for item in analyses:
        if item.component not in top_components and item.component != "General":
            top_components.append(item.component)
        if len(top_components) >= 5:
            break
    if lang == "zh":
        lines = [
            f"- 本次共识别 {len(analyses)} 条可分析 release note，其中高风险 {len(high)} 条、中风险 {len(medium)} 条、低风险 {len(analyses) - len(high) - len(medium)} 条。",
            report_scope_note(len(analyses), len(analyses), lang),
            "- 下方“原始 Release Notes（增强标注）”按官方 release notes 原始顺序展示，每条附带分类、风险与附录编号。",
        ]

        if top_components:
            lines.append(f"- 变化最集中的模块包括：{', '.join(top_components)}。")

        if categories["breaking"] or categories["dependency"]:
            lines.append("- 升级前最需要优先确认的是 breaking change、运行时/依赖要求和迁移相关条目，而不是只看新增功能。")
        if categories["plugin"] or categories["api_sdk"]:
            lines.append("- 插件、API/SDK、CLI 或配置相关变化属于开发者可见表面，相关团队应单独做兼容性验证。")
        if categories["security"]:
            lines.append("- 安全相关条目需要区分真正漏洞修复与认证/权限行为调整，并确认当前部署是否受影响。")
        if categories["performance"]:
            lines.append("- 性能和稳定性条目建议用回归、压力或启动测试验证实际收益。")
        return "\n".join(lines)
    lines = [
        f"- Identified {len(analyses)} analyzable release note items: {len(high)} high-risk and {len(medium)} medium-risk.",
    ]
    if top_components:
        lines.append(f"- Most affected components: {', '.join(top_components)}.")
    if categories["breaking"] or categories["dependency"]:
        lines.append("- Prioritize breaking changes, runtime/dependency requirements, and migration items before focusing on new features.")
    if categories["plugin"] or categories["api_sdk"]:
        lines.append("- Plugin, API/SDK, CLI, and configuration changes are developer-visible surfaces and need compatibility validation.")
    if categories["security"]:
        lines.append("- Security-related items should be reviewed to distinguish direct vulnerability fixes from auth/permission behavior changes.")
    if categories["performance"]:
        lines.append("- Performance and stability items should be validated with regression, stress, or startup tests.")
    return "\n".join(lines)


def _infer_theme(categories: Dict[str, List[str]], lang: str) -> str:
    counts = {k: len(v) for k, v in categories.items() if v}
    if not counts:
        return "变化较少，难以判断核心主题" if lang == "zh" else "Insufficient changes to determine a dominant theme"
    theme_candidates = [
        ("security", "安全加固为主" if lang == "zh" else "Security hardening", 3),
        ("breaking", "兼容性调整为主" if lang == "zh" else "Compatibility adjustments", 2),
        ("migration", "迁移与废弃项为主" if lang == "zh" else "Migration and deprecations", 2),
        ("plugin", "插件系统更新为主" if lang == "zh" else "Plugin system updates", 2),
        ("api_sdk", "API/SDK 更新为主" if lang == "zh" else "API/SDK updates", 2),
        ("config", "配置与部署调整为主" if lang == "zh" else "Configuration and deployment adjustments", 2),
        ("cli", "CLI 与工具链更新为主" if lang == "zh" else "CLI and tooling updates", 2),
        ("dependency", "依赖与运行时调整为主" if lang == "zh" else "Dependency and runtime adjustments", 2),
        ("performance", "性能与稳定性优化为主" if lang == "zh" else "Performance and stability improvements", 1.5),
        ("fix", "Bug 修复与稳定性改进为主" if lang == "zh" else "Bug fixes and stability improvements", 1),
        ("feature", "新功能增强为主" if lang == "zh" else "New feature enhancements", 1),
        ("docs", "文档与质量保障更新为主" if lang == "zh" else "Documentation and QA updates", 0.5),
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
    if lang == "zh":
        if total < 10 and high_risk == 0:
            return "小"
        if total > 40 or high_risk >= 3:
            return "大"
        return "中等"
    if total < 10 and high_risk == 0:
        return "Small"
    if total > 40 or high_risk >= 3:
        return "Large"
    return "Medium"


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
        if lang == "zh":
            return "## 执行摘要\n\n未识别到可分析的 release note 条目。"
        return "## Executive Summary\n\nNo analyzable release note items found."
    high = len([a for a in analyses if a.risk_level == "high"])
    medium = len([a for a in analyses if a.risk_level == "medium"])
    low = len(analyses) - high - medium
    theme = _infer_theme(categories, lang)
    magnitude = _infer_magnitude(len(analyses), high, lang)
    top_items = analyses[:5]
    if lang == "zh":
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
    else:
        lines = [
            "## Executive Summary",
            "",
            f"**Recommendation**: {label}",
            "",
            f"**Dominant Theme**: {theme}",
            "",
            f"**Magnitude**: {magnitude} ({len(analyses)} analyzable changes: {high} high-risk, {medium} medium-risk, {low} low-risk)",
            "",
            f"**Rationale**: {reason}",
            "",
            "**Most Critical Changes**:",
        ]
        for idx, item in enumerate(top_items, 1):
            appendix_id = f"R-{idx:03d}"
            anchor = appendix_id.lower()
            risk_icon = "🔴" if item.risk_level == "high" else ("⚠️" if item.risk_level == "medium" else "🟢")
            cat_labels = " / ".join(category_text(cat, lang) for cat in item.categories[:2])
            lines.append(f"{idx}. [`{appendix_id}`](#appendix-{anchor}) {item.raw_text} — `[{cat_labels}]` `{risk_icon}`")
        lines.append("")
        if not target.is_stable:
            lines.append("**One-line Judgment**: Target is a prerelease; not recommended for production. Use an isolated environment if you want to preview new features.")
        elif high > 0 and (categories.get("breaking") or categories.get("migration")):
            lines.append("**One-line Judgment**: This release carries explicit compatibility risk signals. Do not upgrade blindly—review the Compatibility Risks section first.")
        elif high > 0 and categories.get("security"):
            lines.append("**One-line Judgment**: Security-related fixes are present. Prioritize assessing whether your deployment is affected, then validate in pre-production before rollout.")
        elif categories.get("plugin") or categories.get("api_sdk"):
            lines.append("**One-line Judgment**: Developer-visible surfaces have substantive updates. Plugin and SDK users should review compatibility carefully. Ordinary users can defer based on need.")
        else:
            lines.append("**One-line Judgment**: Changes are low-risk, mainly feature enhancements or fixes for specific modules. Upgrade during your regular window if the changes affect your workflows.")
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

    if lang == "zh":
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

    if has_breaking:
        comps = ", ".join(top_components[:2]) if top_components else "core modules"
        return f"This release carries compatibility baggage: {comps} contain breaking changes. Don't upgrade blindly—check the risk points below against your plugin interfaces, config, and dependencies first."
    if security_count >= 3:
        return "This is a security-hardening release with multiple auth, credential, and permission adjustments. If you use OAuth, SecretRef, or third-party channels, review each item before upgrading so you don't miss implicit grant changes."
    if plugin_count >= 2 or api_count >= 2:
        comps = ", ".join(top_components[:2]) if top_components else "plugins and SDK"
        return f"Developer-friendly release with substantive updates in {comps}. No obvious compatibility traps; skim the Top 10, then validate the interfaces and tooling you care about."
    if config_count >= 2:
        return "Mainly config and deployment behavior changes. Existing plugin code is likely unaffected, but runtime config loading paths may shift—double-check the config items below."
    return "Worth a look for plugin/channel developers. Start with the Top changes and risk points, then decide whether to upgrade now or defer."


def render_top_changes_for_plugin_devs(analyses: Sequence[ChangeAnalysis], strings: T, lang: str) -> str:
    top = top_changes_for_plugin_devs(analyses)
    if not top:
        return f"- {strings['no_relevant_changes']}"
    lines: List[str] = []
    for item in top:
        categories = " / ".join(category_text(cat, lang) for cat in item.categories[:3])
        risk = risk_text(item.risk_level, strings)
        lines.append(f"- {release_note_text(item, lang)} ({categories}; {risk})")
    return "\n".join(lines)


def render_developer_impact_analysis(analyses: Sequence[ChangeAnalysis], lang: str, strings: T) -> str:
    relevant = filter_plugin_dev_relevant(analyses)
    if not relevant:
        return f"- {strings['no_relevant_changes']}"

    def summarize_category(category: str, label_zh: str, label_en: str) -> Optional[str]:
        matched = [item for item in relevant if category in item.categories][:3]
        if not matched:
            return None
        comps: List[str] = []
        for item in matched:
            comp = item.component or ""
            if comp and comp not in comps and comp != "General":
                comps.append(comp)
        comp_str = "、".join(comps[:2]) if comps else ("多个模块" if lang == "zh" else "multiple modules")
        texts = [item.raw_text for item in matched]

        if lang == "zh":
            if category == "plugin":
                if any("install" in t or "uninstall" in t for t in texts):
                    return f"- **{label_zh}**：{comp_str} 涉及插件安装/卸载和依赖清理逻辑，如果你维护或分发插件，需要确认生命周期行为是否有变化。"
                return f"- **{label_zh}**：{comp_str} 有插件面更新，建议确认 hook、manifest 或 SDK 子路径引用是否正常。"
            if category == "api_sdk":
                if any("auth" in t or "OAuth" in t for t in texts):
                    return f"- **{label_zh}**：{comp_str} 调整了认证和 OAuth 流程，API 调用方式可能不变，但凭据获取路径需要重新验证。"
                return f"- **{label_zh}**：{comp_str} 的 SDK 或 API 契约可能有调整，关注类型定义和子路径别名变化。"
            if category == "config":
                return f"- **{label_zh}**：{comp_str} 的配置加载或默认值有变化，部署前建议用真实配置跑一次 validate。"
            if category == "cli":
                return f"- **{label_zh}**：{comp_str} 的 CLI 行为有调整，doctor / update 等命令的输出或修复策略可能不同。"
            if category == "security":
                return f"- **{label_zh}**：{comp_str} 收紧了安全策略，特别是凭据解析和权限边界，升级前核对现有账号和授权配置是否仍然成立。"
            return f"- **{label_zh}**：{comp_str} 有相关变更，建议查看具体条目。"
        else:
            if category == "plugin":
                if any("install" in t or "uninstall" in t for t in texts):
                    return f"- **{label_en}**: {comp_str} touches plugin install/uninstall and dependency cleanup. If you maintain or distribute plugins, verify lifecycle behavior."
                return f"- **{label_en}**: {comp_str} has plugin-surface updates; confirm hook, manifest, or SDK subpath imports still work."
            if category == "api_sdk":
                if any("auth" in t or "OAuth" in t for t in texts):
                    return f"- **{label_en}**: {comp_str} adjusted auth and OAuth flows. API call patterns may be unchanged, but credential resolution paths need re-validation."
                return f"- **{label_en}**: {comp_str} SDK or API contracts may have shifted; watch for type changes and subpath aliases."
            if category == "config":
                return f"- **{label_en}**: {comp_str} changed config loading or defaults. Run validate against realistic configs before deploying."
            if category == "cli":
                return f"- **{label_en}**: {comp_str} CLI behavior changed; doctor/update output or repair strategy may differ."
            if category == "security":
                return f"- **{label_en}**: {comp_str} tightened security policy, especially credential parsing and permission boundaries. Verify existing accounts and auth configs still hold."
            return f"- **{label_en}**: {comp_str} has relevant changes; review the specific items."

    buckets = [
        ("security", "认证与凭据", "Auth & Credentials"),
        ("plugin", "插件与扩展", "Plugins & Extensions"),
        ("api_sdk", "API / SDK", "API / SDK"),
        ("config", "配置与部署", "Config & Deployment"),
        ("cli", "CLI / 工具链", "CLI / Tooling"),
    ]

    lines: List[str] = []
    for cat, label_zh, label_en in buckets:
        summary = summarize_category(cat, label_zh, label_en)
        if summary:
            lines.append(summary)

    return "\n".join(lines) if lines else f"- {strings['no_relevant_changes']}"


def render_compatibility_risks(analyses: Sequence[ChangeAnalysis], strings: T, lang: str) -> str:
    relevant = filter_plugin_dev_relevant(analyses)
    risky = [
        item for item in relevant
        if item.risk_level in {"high", "medium"} or any(cat in item.categories for cat in ["breaking", "migration", "dependency", "security"])
    ][:6]
    if not risky:
        return "- 暂未识别到明确的兼容性风险点。" if lang == "zh" else "- No clear compatibility risks were identified."

    def describe_risk(item: ChangeAnalysis) -> str:
        text = item.raw_text.lower()
        component = item.component or ("通用" if lang == "zh" else "General")

        if lang == "zh":
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

        else:
            if "breaking" in item.categories or "migration" in item.categories:
                if "codex" in text or "app-server" in text:
                    return f"**{component}**: Codex thread/context management changed. If you relied on the old hidden-history recovery mechanism, session state may be lost after upgrade."
                if "sdk" in text or "subpath" in text or "alias" in text:
                    return f"**{component}**: SDK subpath or package alias adjusted; plugins importing the old path may fail to resolve and need import updates."
                return f"**{component}**: Explicit breaking change or migration requirement. Confirm existing code, config, and dependencies are still supported before upgrading."

            if "security" in item.categories:
                if "env" in text or "secretref" in text or "credential" in text:
                    return f"**{component}**: Credential resolution tightened. Previously auto-recognized env vars or implicit grants now require explicit configuration, or auth will fail."
                if "oauth" in text or "auth" in text:
                    return f"**{component}**: OAuth or account auth logic changed; existing auth profiles may expire or need re-authorization."
                if "sandbox" in text or "windows" in text:
                    return f"**{component}**: Sandbox or filesystem bind policy tightened. Credential directory access on Windows may be restricted; watch container or custom HOME setups."
                return f"**{component}**: Security policy adjusted; permission boundaries or default behavior may shift. Verify existing deployments still meet the new security assumptions."

            if "dependency" in item.categories:
                return f"**{component}**: Dependencies upgraded or replaced. If lockfiles or build images aren't updated, install or startup may fail."

            if "config" in item.categories:
                return f"**{component}**: Config structure or defaults changed. Old configs may still parse but behave differently; validate in a realistic environment."

            return f"**{component}**: {item.interpretation}"

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
        return "- 暂无明确测试点，建议至少回归主要 channel 收发链路。" if lang == "zh" else "- No explicit test points detected; at minimum, regression-test key channel send/receive flows."
    suggestions: List[str] = []
    text = " ".join(item.raw_text.lower() for item in relevant[:12])
    if any(token in text for token in ["account", "auth", "oauth", "secret", "credential"]):
        suggestions.append("回归账号登录、OAuth、SecretRef/凭据读取与默认账号解析。" if lang == "zh" else "Regression-test account login, OAuth, SecretRef/credential loading, and default-account resolution.")
    if any(token in text for token in ["plugin", "manifest", "hook", "sdk"]):
        suggestions.append("验证插件安装、manifest 解析、hook 执行与 SDK 类型/子路径引用。" if lang == "zh" else "Validate plugin install, manifest parsing, hook execution, and SDK type/subpath imports.")
    if any(token in text for token in ["cli", "doctor", "update", "config"]):
        suggestions.append("回归 doctor / update / config validate 等 CLI 命令在真实配置下的输出与修复流程。" if lang == "zh" else "Regression-test doctor / update / config validate flows with realistic configs and repair paths.")
    if any(token in text for token in ["channel", "telegram", "discord", "feishu", "gateway"]):
        suggestions.append("验证 channel 启动、消息收发、热重载、重启恢复与默认路由是否保持稳定。" if lang == "zh" else "Test channel startup, message send/receive, hot reload, restart recovery, and default routing stability.")
    if any(token in text for token in ["dependency", "node", "runtime", "pnpm"]):
        suggestions.append("确认 Node.js / 依赖版本要求满足升级前提，并验证安装链路。" if lang == "zh" else "Confirm Node.js / dependency requirements and validate install-time behavior.")
    if not suggestions:
        suggestions.append("至少验证插件加载、channel 收发、配置校验、升级/回滚四条主链路。" if lang == "zh" else "At minimum, validate plugin loading, channel delivery, config validation, and upgrade/rollback flows.")
    return "\n".join(f"- {item}" for item in suggestions[:5])


def render_ignorable_changes(analyses: Sequence[ChangeAnalysis], lang: str) -> str:
    relevant = filter_plugin_dev_relevant(analyses)
    relevant_texts = {item.raw_text for item in relevant}
    others = [item for item in analyses if item.raw_text not in relevant_texts and item.risk_level == "low"][:5]
    if not others:
        return "- 本次低相关低风险条目不多，建议仍快速浏览增强标注原文。" if lang == "zh" else "- There are not many low-risk peripheral items this time; still skim the enhanced original notes."
    if lang == "zh":
        return "\n".join(f"- {item.component or '通用'}：当前对插件 / channel 开发决策帮助有限，可放到第二轮阅读。" for item in others)
    return "\n".join(f"- {item.component or 'General'}: likely peripheral to plugin/channel upgrade decisions; defer to a second pass if needed." for item in others)


def _component_analysis_text(
    component: str,
    items: Sequence[ChangeAnalysis],
    all_categories: Sequence[str],
    lang: str,
) -> str:
    cats = set(all_categories)
    texts = [i.raw_text.lower() for i in items]
    has_breaking = "breaking" in cats or "migration" in cats
    has_security = "security" in cats
    has_plugin = "plugin" in cats
    has_api = "api_sdk" in cats
    has_config = "config" in cats
    has_cli = "cli" in cats
    has_dep = "dependency" in cats
    has_perf = "performance" in cats
    count = len(items)
    if lang == "zh":
        parts = []
        if has_breaking:
            parts.append(f"{component} 存在明确的兼容性变更信号")
            if has_security:
                parts.append("，且与安全策略收紧同时出现")
            parts.append(f"。这 {count} 条变化需要一起看，因为它们可能构成一套配套的接口或行为调整")
            if any("removed" in t or "remove" in t for t in texts):
                parts.append("，特别是涉及移除或废弃的条目，需要确认现有代码是否仍在支持范围内")
            parts.append("。")
        elif has_security:
            parts.append(f"{component} 的安全面有集中调整。这 {count} 条变化围绕认证、权限或凭据管理展开")
            if has_config:
                parts.append("，且伴随配置层面的调整")
            parts.append("。建议优先判断当前部署是否落在受影响范围内，而不是只看功能变化。")
        elif has_plugin and has_api:
            parts.append(f"{component} 的插件系统和 API/SDK 同时出现变更，推断是对开发者扩展面的一次配套调整。这 {count} 条变化中，插件侧的变化决定了扩展契约，API/SDK 侧的变化决定了集成方式")
            if has_config:
                parts.append("，配置调整则影响运行时加载行为")
            parts.append("。建议同时验证插件和调用端。")
        elif has_plugin:
            parts.append(f"{component} 的插件面有 {count} 条更新。这些变化集中在插件的生命周期、加载机制或扩展能力上")
            if any("manifest" in t for t in texts):
                parts.append("，其中涉及 manifest 的条目尤为关键，因为它决定了插件能否被正确识别和加载")
            parts.append("。自定义插件较多的团队需要把兼容性验证放进升级 checklist。")
        elif has_api:
            parts.append(f"{component} 的 API/SDK 有 {count} 条更新。这些变化影响公共接口、类型定义或导出结构")
            if any("deprecated" in t or "deprecate" in t for t in texts):
                parts.append("，其中包含的弃用提示需要特别关注，因为弃用项通常会在后续版本中转为 breaking change")
            parts.append("。如果你有二次封装或外部集成，建议核对关键调用路径。")
        elif has_config:
            parts.append(f"{component} 的配置层有 {count} 条调整。这类变化的风险不在文案本身，而在于旧配置在目标版本中是否仍被接受、以及默认值的变化是否会改变运行时行为")
            if has_dep:
                parts.append("；同时伴随依赖或运行时调整，需要确认部署环境是否满足新要求")
            parts.append("。")
        elif has_cli:
            parts.append(f"{component} 的 CLI 面有 {count} 条调整。命令参数、子命令、输出格式或退出码的变化最容易连带影响自动化脚本和运维流程")
            if any("doctor" in t or "update" in t for t in texts):
                parts.append("，doctor / update 等诊断命令的修复策略变化尤其值得回归验证")
            parts.append("。")
        elif has_dep:
            parts.append(f"{component} 的依赖或运行时有 {count} 条调整。这类变化更像是环境前提的改动，需要先确认 Node.js、包管理器、锁文件、构建镜像和 CI/CD 运行时是否满足新的要求，否则升级可能卡在安装、构建或启动阶段。")
        elif has_perf:
            parts.append(f"{component} 有 {count} 条性能或稳定性相关更新。这类变化通常属于正向收益，但对高负载、长连接或关键路径敏感的场景，仍建议用现网相近流量做一次回归确认，避免收益伴随行为变化。")
        else:
            parts.append(f"{component} 有 {count} 条变更，主要面向功能增强或问题修复。这些变化的风险较低，是否值得升级主要取决于你是否需要这部分能力。")
        return "".join(parts)
    parts = []
    if has_breaking:
        parts.append(f"{component} shows explicit compatibility change signals")
        if has_security:
            parts.append(", coinciding with security policy tightening")
        parts.append(f". These {count} changes should be reviewed together as they may represent a coordinated set of interface or behavior adjustments")
        if any("removed" in t or "remove" in t for t in texts):
            parts.append("; items involving removal or deprecation require confirming whether existing code remains within the supported range")
        parts.append(".")
    elif has_security:
        parts.append(f"{component} has concentrated security adjustments. These {count} changes revolve around authentication, permissions, or credential management")
        if has_config:
            parts.append(", accompanied by configuration-layer changes")
        parts.append(". Prioritize assessing whether your current deployment falls within the affected scope rather than focusing only on functional changes.")
    elif has_plugin and has_api:
        parts.append(f"Both plugin system and API/SDK changes appear in {component}, suggesting a coordinated adjustment to the developer extension surface. Among these {count} changes, plugin-side items determine the extension contract while API/SDK-side items determine integration patterns")
        if has_config:
            parts.append(", and configuration adjustments affect runtime loading behavior")
        parts.append(". Validate both plugin and caller sides together.")
    elif has_plugin:
        parts.append(f"{component} has {count} plugin-surface updates, concentrated on plugin lifecycle, loading mechanisms, or extension capabilities")
        if any("manifest" in t for t in texts):
            parts.append("; manifest-related items are particularly critical as they determine whether plugins can be correctly discovered and loaded")
        parts.append(". Teams with many custom plugins should include compatibility validation in their upgrade checklist.")
    elif has_api:
        parts.append(f"{component} has {count} API/SDK updates affecting public interfaces, type definitions, or export structures")
        if any("deprecated" in t or "deprecate" in t for t in texts):
            parts.append("; deprecation notices deserve special attention as deprecated items typically become breaking changes in subsequent releases")
        parts.append(". If you have wrappers or external integrations, review key call paths before upgrading.")
    elif has_config:
        parts.append(f"{component} has {count} configuration-layer adjustments. The risk here is not the text itself but whether old configs are still accepted in the target version and whether default value changes alter runtime behavior")
        if has_dep:
            parts.append("; combined with dependency/runtime changes, confirm that the deployment environment meets new requirements")
        parts.append(".")
    elif has_cli:
        parts.append(f"{component} has {count} CLI changes. Command arguments, subcommands, output format, or exit code changes most easily cascade into automation scripts and operational workflows")
        if any("doctor" in t or "update" in t for t in texts):
            parts.append("; repair strategy changes in diagnostic commands like doctor/update particularly warrant regression validation")
        parts.append(".")
    elif has_dep:
        parts.append(f"{component} has {count} dependency or runtime adjustments. These are more like environment prerequisite changes: confirm Node.js, package manager, lockfile, build images, and CI/CD runtime meet new requirements before upgrading, or the upgrade may fail at install, build, or startup time.")
    elif has_perf:
        parts.append(f"{component} has {count} performance or stability updates. These are generally positive, but for high-load, long-connection, or critical-path-sensitive scenarios, still recommend regression confirmation with production-like traffic to ensure gains don't come with behavior changes.")
    else:
        parts.append(f"{component} has {count} changes, mainly feature enhancements or bug fixes. These carry low risk; whether to upgrade depends on whether you need these capabilities.")
    return "".join(parts)


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
        return "- 暂无主题聚类数据。" if lang == "zh" else "- No thematic clustering data available."

    sorted_themes = sorted(themes, key=_risk_sort_key)
    lines: List[str] = []

    if lang == "zh":
        lines.append("## 变更主题概览")
        lines.append("")
        lines.append(f"本次更新可归纳为 **{len(themes)}** 个主题，按风险等级排序：")
        lines.append("")
        lines.append("| 主题 | 条目数 | 风险 | 关联 Commit | 概括 |")
        lines.append("|---|---|---|---|---|")
    else:
        lines.append("## Thematic Overview")
        lines.append("")
        lines.append(f"This release can be summarized in **{len(themes)}** themes, sorted by risk:")
        lines.append("")
        lines.append("| Theme | Items | Risk | Related Commits | Summary |")
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
        if lang == "zh":
            lines.append("**需要重点关注的高风险主题**：")
        else:
            lines.append("**High-risk themes requiring attention**:")
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
        return "- 未检测到渐进式修复链。" if lang == "zh" else "- No progressive fix chains detected."

    lines: List[str] = []
    if lang == "zh":
        lines.append("## 渐进式修复检测")
        lines.append("")
        lines.append(f"检测到 **{len(fixes)}** 个跨版本的渐进式修复链：")
        lines.append("")
    else:
        lines.append("## Progressive Fix Detection")
        lines.append("")
        lines.append(f"Detected **{len(fixes)}** progressive fix chain(s) across versions:")
        lines.append("")

    for idx, fix in enumerate(fixes, 1):
        status_label = {
            "fully_fixed": ("已完全修复", "Fully Fixed"),
            "partially_fixed": ("仍部分修复", "Partially Fixed"),
            "mitigated": ("仅缓解", "Mitigated"),
        }.get(fix.final_status, (fix.final_status, fix.final_status))

        if lang == "zh":
            lines.append(f"### PF-{idx:02d}：{fix.issue_description or '未命名问题'}")
            lines.append("")
            lines.append(f"**最终状态**：{status_label[0]}")
            if fix.affected_components:
                lines.append(f"**受影响组件**：{', '.join(fix.affected_components)}")
            lines.append("")
            lines.append("| 阶段 | 版本 | 修复内容 | 完整度 |")
            lines.append("|---|---|---|---|")
        else:
            lines.append(f"### PF-{idx:02d}: {fix.issue_description or 'Unnamed Issue'}")
            lines.append("")
            lines.append(f"**Final Status**: {status_label[1]}")
            if fix.affected_components:
                lines.append(f"**Affected Components**: {', '.join(fix.affected_components)}")
            lines.append("")
            lines.append("| Stage | Version | Fix Description | Completeness |")
            lines.append("|---|---|---|---|")

        completeness_label = {
            "mitigation": ("缓解", "Mitigation"),
            "partial": ("部分修复", "Partial"),
            "complete": ("完整修复", "Complete"),
        }

        for stage_idx, stage in enumerate(fix.stages, 1):
            ver = stage.get("source_version", "-")
            desc = stage.get("fix_description", "-")
            comp = stage.get("completeness", "")
            comp_text = completeness_label.get(comp, (comp, comp))[0 if lang == "zh" else 1]
            lines.append(f"| {stage_idx} | `{ver}` | {desc} | {comp_text} |")

        if fix.impact_assessment:
            if lang == "zh":
                lines.append("")
                lines.append(f"**影响评估**：{fix.impact_assessment}")
            else:
                lines.append("")
                lines.append(f"**Impact Assessment**: {fix.impact_assessment}")
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
        return "- 未检测到累积 Breaking Change 风险。" if lang == "zh" else "- No cumulative breaking change risks detected."

    lines: List[str] = []
    if lang == "zh":
        lines.append("## 累积 Breaking Change 分析")
        lines.append("")
        lines.append(f"检测到 **{len(evolutions)}** 个版本演进模式，单版本风险可能被低估：")
        lines.append("")
    else:
        lines.append("## Cumulative Breaking Change Analysis")
        lines.append("")
        lines.append(f"Detected **{len(evolutions)}** version evolution pattern(s) where per-version risk may be underestimated:")
        lines.append("")

    for idx, evo in enumerate(evolutions, 1):
        risk_icon_ind = "🔴" if evo.individual_risk == "high" else ("⚠️" if evo.individual_risk == "medium" else "🟢")
        risk_icon_cum = "🔴" if evo.cumulative_risk == "high" else ("⚠️" if evo.cumulative_risk == "medium" else "🟢")

        if lang == "zh":
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
        else:
            lines.append(f"### VE-{idx:02d}: {evo.description or 'Unnamed Evolution'}")
            lines.append("")
            vers = " → ".join(f"`{v}`" for v in evo.affected_versions)
            lines.append(f"**Versions**: {vers}")
            lines.append(f"**Individual Risk**: {risk_icon_ind} {evo.individual_risk}　**Cumulative Risk**: {risk_icon_cum} {evo.cumulative_risk}")
            if evo.affected_components:
                lines.append(f"**Affected Components**: {', '.join(evo.affected_components)}")
            lines.append("")
            if evo.risk_escalation_reason:
                lines.append(f"**Risk Escalation Reason**: {evo.risk_escalation_reason}")
                lines.append("")
            if evo.migration_advice:
                lines.append(f"**Migration Advice**: {evo.migration_advice}")
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
        return "- 暂无足够变更数据可供深度分析。" if lang == "zh" else "- Insufficient change data for deep-dive analysis."

    # Only expand high/medium risk themes
    risky_themes = [t for t in themes if t.risk_level in ("high", "medium")]
    risky_themes = sorted(risky_themes, key=_risk_sort_key)

    if not risky_themes:
        return "- 本次无高风险或中风险主题需要展开分析。" if lang == "zh" else "- No high or medium risk themes require detailed analysis."

    analysis_map = {f"R-{i+1:03d}": a for i, a in enumerate(analyses)}
    detailed_map = {dn.note_id: dn for dn in detailed_notes if dn.note_id}

    blocks: List[str] = []
    for theme in risky_themes[:8]:
        risk_icon = "🔴" if theme.risk_level == "high" else "⚠️"

        note_descs: List[str] = []
        for nid in theme.note_ids[:8]:
            analysis = analysis_map.get(nid)
            if analysis:
                text = analysis.raw_text
                note_risk = "🔴" if analysis.risk_level == "high" else ("⚠️" if analysis.risk_level == "medium" else "🟢")
                note_descs.append(f"- [`{nid}`](#appendix-{nid.lower()}) {note_risk} {text}")

        # Build affected files display
        files_str = ""
        if theme.affected_files:
            file_list = ", ".join(f"`{f}`" for f in theme.affected_files[:5])
            if lang == "zh":
                files_str = f"\n\n**受影响文件**：{file_list}"
            else:
                files_str = f"\n\n**Affected files**: {file_list}"

        # Build commit evidence
        commit_str = ""
        if theme.related_commits:
            commit_list = ", ".join(f"`{c[:7]}`" for c in theme.related_commits)
            if lang == "zh":
                commit_str = f"\n\n**关联 Commit**：{commit_list}"
            else:
                commit_str = f"\n\n**Related commits**: {commit_list}"

        # Navigation links to appendix detailed notes
        nav_links: List[str] = []
        for nid in theme.note_ids:
            if nid in detailed_map:
                nav_links.append(f"- [`{nid}`](#appendix-{nid.lower()})")

        nav_section = ""
        if nav_links[:5]:
            if lang == "zh":
                nav_section = "\n\n**相关详细分析**：\n" + "\n".join(nav_links[:5])
            else:
                nav_section = "\n\n**Related Detailed Analysis**:\n" + "\n".join(nav_links[:5])
            if len(nav_links) > 5:
                nav_section += f"\n- ... 及其他 {len(nav_links) - 5} 条" if lang == "zh" else f"\n- ... and {len(nav_links) - 5} more"

        desc_text = "\n".join(note_descs) if note_descs else ("- 暂无关联条目数据" if lang == "zh" else "- No associated items available")

        if lang == "zh":
            block = (
                f"### {theme.theme_name}（{len(theme.note_ids)} 条）\n\n"
                f"**概括**：{theme.summary or '-'}\n\n"
                f"**影响**：{theme.impact or '详见具体条目'}\n\n"
                f"**风险等级**：{risk_icon} {theme.risk_level}\n\n"
                f"**AI 判断依据**：{theme.reasoning or '基于 release note 文本分析'}"
                f"{files_str}{commit_str}\n\n"
                f"**涉及条目**：\n{desc_text}{nav_section}"
            )
        else:
            block = (
                f"### {theme.theme_name} ({len(theme.note_ids)} items)\n\n"
                f"**Summary**: {theme.summary or '-'}\n\n"
                f"**Impact**: {theme.impact or 'See individual items'}\n\n"
                f"**Risk Level**: {risk_icon} {theme.risk_level}\n\n"
                f"**AI Rationale**: {theme.reasoning or 'Based on release note text analysis'}"
                f"{files_str}{commit_str}\n\n"
                f"**Related Items**:\n{desc_text}{nav_section}"
            )
        blocks.append(block)

    header = "## 高风险主题详解" if lang == "zh" else "## High-Risk Theme Details"
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
        return "- 暂无代码关联数据。" if lang == "zh" else "- No code association data available."

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
        return "- 暂无 commit 关联证据。" if lang == "zh" else "- No commit association evidence available."

    if lang == "zh":
        lines = [
            "## 代码变更证据链",
            "",
            "| Note ID | Release Note 摘要 | 关联 Commit | 改动文件 | 推理依据 |",
            "|---|---|---|---|---|",
        ]
    else:
        lines = [
            "## Code Change Evidence",
            "",
            "| Note ID | Note Summary | Related Commits | Changed Files | Rationale |",
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
        return "- 未发现未在 release notes 中提及的代码变更。" if lang == "zh" else "- No undocumented code changes found."

    lines: List[str] = []
    if lang == "zh":
        lines.append("## 未记录变更提示")
        lines.append("")
        lines.append("以下代码变更在 commit 中有体现，但在 release notes 中未明确提及：")
        lines.append("")
    else:
        lines.append("## Shadow Changes")
        lines.append("")
        lines.append("The following code changes are present in commits but not explicitly mentioned in release notes:")
        lines.append("")

    for idx, sc in enumerate(shadow_changes, 1):
        desc = sc.get("description", "")
        commits = sc.get("evidence_commits", [])
        commit_str = " ".join(f"`{c[:7]}`" for c in commits) if commits else "-"
        if lang == "zh":
            lines.append(f"{idx}. {desc}（证据 commit: {commit_str}）")
        else:
            lines.append(f"{idx}. {desc} (evidence: {commit_str})")

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
        if lang == "zh":
            return "- 本次无 LLM 增强的高风险条目，逐条明细已省略。详见上方主题概览。"
        return "- No LLM-enhanced high-risk items this time; per-note details omitted. See thematic overview above."

    # Sort by priority, cap at 40
    eligible = sorted(eligible, key=lambda a: a.priority, reverse=True)
    max_items = limit if limit is not None else 40
    displayed = eligible[:max_items]

    appendix_ids = build_appendix_ids(analyses)
    if lang == "zh":
        blocks: List[str] = [
            f"- 以下展示 **{len(displayed)}** 条有 LLM 代码关联或高风险的条目（共 {len(analyses)} 条）。"
        ]
    else:
        blocks: List[str] = [
            f"- Showing **{len(displayed)}** items with LLM code associations or high risk (out of {len(analyses)} total)."
        ]

    field_header = "字段" if lang == "zh" else "Field"
    value_header = "内容" if lang == "zh" else "Value"
    raw_release_label = "原始 Release Note" if lang == "zh" else "Raw Release Note"

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
                files_str += f" (+{len(item.affected_files) - 8} more)" if lang == "en" else f" 等 {len(item.affected_files) - 8} 个文件"
            label_af = strings.get("affected_files_label", "Affected Files" if lang == "en" else "受影响文件")
            rows.append(f"| {label_af} | {files_str} |")
        # Add code evidence row if present
        if item.code_evidence:
            evidence = item.code_evidence.replace("|", "\\|").replace("\n", "<br>")
            label_ce = strings.get("code_evidence_label", "Code Evidence" if lang == "en" else "代码证据")
            rows.append(f"| {label_ce} | `{evidence}` |")
        # Add LLM reasoning row if present
        if item.llm_reasoning:
            reasoning = item.llm_reasoning.replace("|", "\\|").replace("\n", "<br>")
            label_lr = "AI 推理过程" if lang == "zh" else "LLM Reasoning"
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
        return "## 执行摘要\n\n（LLM 未提供执行摘要）" if lang == "zh" else "## Executive Summary\n\n(LLM did not provide an executive summary)"

    rec = es.get("recommendation", "")
    theme = es.get("theme", "")
    magnitude = es.get("magnitude", "")
    reason = es.get("reason", "")
    top_changes = es.get("top_changes", [])
    one_liner = es.get("one_liner", "")

    if lang == "zh":
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
    else:
        lines = ["## Executive Summary", ""]
        if rec:
            lines.append(f"**Recommendation**: {rec}")
            lines.append("")
        if theme:
            lines.append(f"**Dominant Theme**: {theme}")
            lines.append("")
        if magnitude:
            lines.append(f"**Magnitude**: {magnitude}")
            lines.append("")
        if reason:
            lines.append(f"**Rationale**: {reason}")
            lines.append("")
        if top_changes:
            lines.append("**Most Critical Changes**:")
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
            lines.append(f"**One-line Judgment**: {one_liner}")
    return "\n".join(lines)


def _render_compatibility_risks_from_llm(
    risks: Sequence[LLMCompatibilityRisk],
    lang: str,
) -> str:
    """Render compatibility risks as a structured table."""
    if not risks:
        return "- 暂未识别到明确的兼容性风险点。" if lang == "zh" else "- No clear compatibility risks were identified."

    if lang == "zh":
        lines = [
            "| 组件 | 风险描述 |",
            "|---|---|",
        ]
    else:
        lines = [
            "| Component | Risk Description |",
            "|---|---|",
        ]

    seen: set[str] = set()
    for r in risks:
        key = f"{r.component}:{r.description}"
        if key in seen:
            continue
        seen.add(key)
        comp = r.component or ("通用" if lang == "zh" else "General")
        desc = r.description or "-"
        lines.append(f"| **{comp}** | {desc} |")

    return "\n".join(lines)


def _render_test_points_from_llm(
    points: Sequence[str],
    lang: str,
) -> str:
    """Render test points directly from LLM output."""
    if not points:
        return "- 暂无明确测试点。" if lang == "zh" else "- No explicit test points identified."
    return "\n".join(f"- {p}" for p in points[:8])


def _render_detailed_notes_from_llm(
    notes: Sequence[LLMNoteAnalysis],
    lang: str,
    analyses: Sequence[ChangeAnalysis],
) -> str:
    """Render detailed note analysis directly from LLM output."""
    if not notes:
        return "- 暂无 LLM 逐条分析数据。" if lang == "zh" else "- No LLM per-note analysis available."

    # Build note_id -> ChangeAnalysis mapping for raw_text lookup
    analysis_map = {a.note_id: a for a in analyses if a.note_id}

    field_header = "字段" if lang == "zh" else "Field"
    value_header = "内容" if lang == "zh" else "Value"
    raw_label = "原始 Release Note" if lang == "zh" else "Raw Release Note"
    blocks: List[str] = []

    for item in notes[:40]:
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
            f"| 组件 | {item.component or '-'} |",
            f"| 风险等级 | {item.risk_level} |",
            f"| 分类 | {categories} |",
            f"| 影响对象 | {audience} |",
        ]
        if item.matched_commits:
            rows.append(f"| 关联 Commit | {commits} |")
        if item.affected_files:
            rows.append(f"| 受影响文件 | {files} |")
        if item.reasoning:
            reasoning = item.reasoning.replace("|", "\\|").replace("\n", "<br>")
            rows.append(f"| AI 推理过程 | {reasoning} |")
        rows.extend([
            f"| {raw_label} | {raw_text} |",
            f"| 变更解读 | {item.interpretation.replace(chr(124), chr(92)+chr(124)).replace(chr(10), '<br>') if item.interpretation else '-'} |",
            f"| 建议动作 | {actions} |",
        ])
        blocks.append(
            f"<a id=\"appendix-{nid.lower()}\"></a>\n"
            f"#### {nid}\n\n"
            + "\n".join(rows)
        )

    count = len(notes[:40])
    if lang == "zh":
        header = "## 附录：LLM 增强逐条明细"
        intro = f"以下展示 **{count}** 条经 LLM 深度分析的条目。这些条目覆盖高风险主题、有代码关联证据或有隐藏破坏性变更的 note。"
    else:
        header = "## Appendix: LLM-Enhanced Per-Note Details"
        intro = f"Showing **{count}** LLM-deep-analyzed items covering high-risk themes, code-associated evidence, or hidden breaking changes."

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

    strings = _zh() if lang == "zh" else _en()
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
        themes_overview = "- 暂无主题聚类数据。" if lang == "zh" else "- No thematic clustering data available."
        progressive_fixes_section = "- 未检测到渐进式修复链。" if lang == "zh" else "- No progressive fix chains detected."
        version_evolution_section = "- 未检测到累积 Breaking Change 风险。" if lang == "zh" else "- No cumulative breaking change risks detected."
        deep_dive_section = "- 暂无深度分析数据。" if lang == "zh" else "- No deep-dive data available."
        code_evidence_section = "- 暂无代码关联证据。" if lang == "zh" else "- No code association evidence available."
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

## {'面向开发者的结论' if lang == 'zh' else 'Developer Conclusion'}

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

## {('原始 Release Notes（增强标注）' if lang == 'zh' else 'Original Release Notes (Enhanced Index)')}

{render_release_note_index(analyses, appendix_ids, strings, lang)}

---

{appendix_section}

---

*{f('footer')}*
"""

