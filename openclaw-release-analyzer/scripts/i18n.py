"""Internationalization (i18n) module for the OpenClaw Release Analyzer.

Contains the Chinese string bundle and release-note text translation helpers.
All reports are generated in Chinese with technical proper nouns kept in English.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

T = Dict[str, str]


def _zh() -> T:
    return {
        "report_title": "OpenClaw Release 分析报告",
        "overall_conclusion": "总体结论",
        "recommendation": "升级建议",
        "recommend_upgrade": "建议升级",
        "upgrade_with_caution": "谨慎升级",
        "defer_upgrade": "暂缓升级",
        "conditional_upgrade": "仅特定场景建议升级",
        "insufficient_data": "信息不足，建议进一步分析",
        "version_info": "版本信息",
        "field_target_version": "目标版本",
        "field_compare_version": "对比版本",
        "field_publish_date": "发布日期",
        "field_target_status": "目标状态",
        "field_releases_analyzed": "分析版本数",
        "field_data_source": "数据来源",
        "stable": "Stable",
        "prerelease_beta": "Prerelease/Beta",
        "key_changes": "重点变化摘要",
        "new_features": "新增 Feature",
        "bug_fixes": "Bug Fix",
        "breaking_changes": "Breaking Change / 升级风险",
        "plugin_impact": "插件系统影响",
        "api_sdk_impact": "API / SDK 影响",
        "security_fixes": "安全修复",
        "perf_stability": "性能与稳定性",
        "developer_conclusion": "面向 Channel / 插件开发者的一句话结论",
        "top_changes_for_devs": "本次最值得关注的变更（Top 10）",
        "developer_impact_analysis": "对插件 / Channel 开发者的影响分析",
        "compatibility_risks": "兼容性与风险点",
        "suggested_test_points": "建议验证的测试点",
        "ignorable_changes": "可暂时忽略的变更",
        "no_relevant_changes": "本次版本没有明显聚焦插件 / channel 开发面的高相关条目，建议直接查看增强标注原文与附录做人工判断。",
        "scenario_recommendations": "场景化升级建议",

        "scenario_plugin_dev": "插件开发者",
        "scenario_api_users": "API / SDK 使用者",
        "scenario_security": "安全敏感用户",
        "scenario_stability": "稳定性敏感用户",
        "scenario_ordinary": "普通使用者",
        "beta_preview": "Beta / Prerelease 前瞻提示",
        "facts_inferences": "事实、推断与不确定项",
        "facts_label": "事实",
        "inferences_label": "推断",
        "uncertainties_label": "不确定项",
        "references": "参考来源",
        "empty_feature": "未从 release notes 中识别到明确的新增 feature。",
        "empty_fix": "未从 release notes 中识别到明确的 bug fix。",
        "empty_breaking": "未识别到明确的 breaking change。",
        "empty_plugin": "未识别到明确的插件系统变化。",
        "empty_api_sdk": "未识别到明确的 API/SDK 变化。",
        "empty_security": "未识别到明确的安全修复。",
        "empty_performance": "未识别到明确的性能或稳定性变化。",
        "no_baseline": "未找到对比基线",
        "no_prerelease": "未发现比最新 stable 更新的 beta/prerelease。",
        "prerelease_preview_note": "以下 prerelease 仅作前瞻提示，不作为默认生产升级目标。",
        "prerelease_included_note": "已按请求包含 prerelease 前瞻；生产环境仍需谨慎。",
        "fact_analysis_base": "分析基于 GitHub Releases API 返回的 release metadata 和 release notes。",
        "fact_stable_criteria": "Stable 判断使用 GitHub prerelease=false 且 draft=false。",
        "fact_release_url": "目标 release URL",
        "inference_classification": "分类基于 release note 标题、项目符号和关键词匹配。",
        "inference_recommendation": "升级建议基于安全、稳定性、插件系统、API/SDK、breaking change 等信号综合判断。",
        "uncertainty_compat": "Release notes 未明确说明的兼容性影响需要进一步查看 compare diff、PR、Issue 或源码。",
        "uncertainty_project": "未经用户明确授权，本报告未扫描本地项目代码。",
        "footer": "本报告由 openclaw-release-analyzer skill 生成。分析结果以 OpenClaw 官方 release notes 和文档为准。",

        # token status
        "token_valid_info": "GitHub token 已验证，将启用 LLM 增强的 diff 分析。",
        "token_invalid_warning": "警告：GitHub token 无效或已过期。将仅使用规则分析，结果可能不够准确。",
        "token_missing_warning": "警告：未提供 GitHub token。将仅使用规则分析，结果可能不够准确。可通过 --github-token 传入或设置 GITHUB_TOKEN 环境变量来启用 LLM 增强的 diff 分析。",
        "analysis_mode_rule_only": "GitHub Releases API 快照（仅规则分析，无 LLM diff 增强）",
        "analysis_mode_llm_enhanced": "GitHub Releases API + Compare Diff + LLM 分析",

        "repo": "仓库",
        "generated_at": "生成时间",
        "unknown": "未知",
        "no_summary": "无摘要",

        # scenario advice
        "adv_plugin_has_signal": "建议检查插件 manifest 兼容性、生命周期 hook 签名、loader/registry 契约，并在目标版本测试环境验证插件。",
        "adv_plugin_no_signal": "未识别到明确插件系统变化，通常无需因插件兼容性单独升级。",
        "adv_api_has_signal": "建议检查公共 API 表面、SDK 包导出、TypeScript 类型、弃用提示和迁移说明后再升级。",
        "adv_api_no_signal": "未识别到明确 API/SDK 变化，常规使用风险较低。",
        "adv_security_has_signal": "建议优先评估受影响版本范围，在测试环境验证后尽快升级到生产环境。",
        "adv_security_no_signal": "未识别到明确安全修复；如处于高安全要求场景，建议继续查看官方安全公告。",
        "adv_perf_has_signal": "建议在预生产环境运行回归和压力测试，确认性能/稳定性收益后再升级。",
        "adv_perf_no_signal": "未识别到明确性能或稳定性修复。",
        "adv_feature_fix": "可根据新 feature 或 bug fix 是否影响当前工作流决定是否升级；生产环境建议先测试。",
        "adv_insufficient": "Release notes 信息不足，建议查看原始 release notes 后再决定。",
        # recommendation reasons
        "reason_prerelease": "目标版本是 prerelease，不建议默认用于生产环境。",
        "reason_security": "Release notes 中出现安全相关修复信号，建议尽快评估并升级。",
        "reason_breaking": "发现 breaking change、插件系统或 API/SDK 相关信号，升级前应检查兼容性。",
        "reason_stability": "发现稳定性或性能相关修复，建议在测试环境验证后升级。",
        "reason_feature_fix": "版本包含 feature 或 bug fix，是否升级取决于这些变化是否匹配当前使用场景。",
        "reason_insufficient": "Release notes 信息较少或无法结构化识别，建议查看原始 release notes 以及关联 PR/Issue 获取更多上下文。",
        # table headers
        "th_version": "版本",
        "th_publish_date": "发布日期",
        "th_description": "说明",
        # Included releases section
        "included_releases": "包含的版本列表",
        # Upgrade action checklist
        "upgrade_checklist": "升级操作检查清单",
        "checklist_intro": "基于检测到的信号，升级前建议检查以下内容：",
        "check_breaking": "发现 Breaking Changes",
        "check_breaking_desc": "建议查看 breaking changes，检查兼容性，并在升级前准备迁移步骤。",
        "check_plugin": "插件系统变化",
        "check_plugin_desc": "建议检查插件 manifest、hook 签名，并在目标版本测试插件兼容性。",
        "check_api": "API/SDK 变化",
        "check_api_desc": "建议检查公共 API 表面变化、TypeScript 类型，并相应更新依赖代码。",
        "check_security": "发现安全修复",
        "check_security_desc": "建议优先处理安全修复，在非生产环境测试后再推送到生产环境。",
        "check_config": "配置变化",
        "check_config_desc": "建议检查配置 schema 变化，按需更新 openclaw.config.* 文件。",
        "check_dep": "依赖变化",
        "check_dep_desc": "建议检查依赖要求变化（Node.js 版本、peerDependencies 等）。",
        "analytical_summary": "重点变化分析摘要",
        "per_note_analysis": "附录：LLM 增强逐条明细",

        "change_interpretation": "变更解读",
        "raw_change": "原始变更",
        "categories_label": "分类",
        "risk_label": "风险等级",
        "audience_label": "影响对象",
        "action_label": "建议动作",
        "component_label": "组件",
        "release_label": "所属版本",
        "confidence_label": "AI 分析可信度",
        "affected_files_label": "受影响文件",
        "code_evidence_label": "代码证据",
        "no_change_items": "未发现可分析的 release note 条目。",
        "risk_high": "高风险",
        "risk_medium": "中风险",
        "risk_low": "低风险",
        "confidence_high": "高",
        "confidence_medium": "中",
        "confidence_low": "低",
    }


def i(key: str, strings: T) -> str:
    return strings.get(key, key)


# ---------------------------------------------------------------------------
# Component name translation (Chinese)
# ---------------------------------------------------------------------------

def _translate_component_zh(prefix: str) -> str:
    component_map = {
        "Plugins": "插件",
        "Plugin": "插件",
        "Providers": "提供方",
        "Provider": "提供方",
        "API": "API",
        "SDK": "SDK",
        "CLI": "CLI",
        "Mac app": "Mac 应用",
        "Windows": "Windows",
        "Docs": "文档",
        "Security": "安全",
        "Telemetry": "遥测",
        "Gateway": "网关",
        "Sidecar": "边车",
    }
    parts = [part.strip() for part in prefix.split("/") if part.strip()]
    translated_parts = [component_map.get(part, part) for part in parts]
    return "/".join(translated_parts) if translated_parts else prefix


# ---------------------------------------------------------------------------
# Release-note text translation helpers
# ---------------------------------------------------------------------------

TRANSLATION_PHRASES_ZH: List[Tuple[str, str]] = [
    (r"\badd a bundled\b", "新增内置"),
    (r"\badd bundled\b", "新增内置"),
    (r"\badd support for\b", "新增对……的支持"),
    (r"\badd support\b", "新增支持"),
    (r"\badded support for\b", "新增了对……的支持"),
    (r"\badded support\b", "新增了支持"),
    (r"\badded\b", "新增了"),
    (r"\badd\b", "新增"),
    (r"\bintroduce\b", "引入"),
    (r"\bintroduces\b", "引入了"),
    (r"\bintroduced\b", "引入了"),
    (r"\benable\b", "启用"),
    (r"\benables\b", "使……能够"),
    (r"\benabled\b", "已启用"),
    (r"\ballow\b", "允许"),
    (r"\ballows\b", "允许"),
    (r"\ballowed\b", "允许了"),
    (r"\bfixes\b", "修复了"),
    (r"\bfixed\b", "修复了"),
    (r"\bfix\b", "修复"),
    (r"\bresolve\b", "解决"),
    (r"\bresolved\b", "解决了"),
    (r"\bimprove\b", "改进"),
    (r"\bimproves\b", "改进了"),
    (r"\bimproved\b", "改进了"),
    (r"\bupdate\b", "更新"),
    (r"\bupdates\b", "更新了"),
    (r"\bupdated\b", "更新了"),
    (r"\bupgrade\b", "升级"),
    (r"\bremove\b", "移除"),
    (r"\bremoves\b", "移除"),
    (r"\bremoved\b", "移除了"),
    (r"\bdeprecate\b", "弃用"),
    (r"\bdeprecated\b", "已弃用"),
    (r"\brequire\b", "要求"),
    (r"\brequires\b", "要求"),
    (r"\brequired\b", "必需的"),
    (r"\bdetect\b", "检测"),
    (r"\bdetects\b", "检测到"),
    (r"\bdetected\b", "检测到"),
    (r"\breload\b", "重新加载"),
    (r"\bretry\b", "重试"),
    (r"\brestore\b", "恢复"),
    (r"\brestores\b", "恢复了"),
    (r"\bblock\b", "阻止"),
    (r"\bblocks\b", "阻止"),
    (r"\bpreserve\b", "保留"),
    (r"\bkeep\b", "保持"),
    (r"\bsupport\b", "支持"),
    (r"\bsupports\b", "支持"),
    (r"\bplugin system\b", "插件系统"),
    (r"\bplugin ingress\b", "插件入口"),
    (r"\bplugin\b", "插件"),
    (r"\bplugins\b", "插件"),
    (r"\bprovider\b", "提供方"),
    (r"\bproviders\b", "提供方"),
    (r"\bwebhook ingress\b", "webhook 接入"),
    (r"\bwebhooks\b", "webhook"),
    (r"\bwebhook\b", "webhook"),
    (r"\bshared-secret\b", "共享密钥"),
    (r"\bshared secret\b", "共享密钥"),
    (r"\bendpoint\b", "端点"),
    (r"\bendpoints\b", "端点"),
    (r"\broute\b", "路由"),
    (r"\broutes\b", "路由"),
    (r"\bTaskFlows\b", "TaskFlow"),
    (r"\bTaskFlow\b", "TaskFlow"),
    (r"\bcatalog entries\b", "目录条目"),
    (r"\bonboarding\b", "接入指引"),
    (r"\bguidance\b", "说明"),
    (r"\bauth guidance\b", "认证说明"),
    (r"\bauthentication\b", "认证"),
    (r"\bauthorization\b", "授权"),
    (r"\bauth\b", "认证"),
    (r"\bcredential\b", "凭据"),
    (r"\bcredentials\b", "凭据"),
    (r"\bsecret\b", "密钥"),
    (r"\btoken\b", "token"),
    (r"\bsession\b", "会话"),
    (r"\bsessions\b", "会话"),
    (r"\bruntime\b", "运行时"),
    (r"\bfallback\b", "回退"),
    (r"\bauto-fallback\b", "自动回退"),
    (r"\bconfiguration\b", "配置"),
    (r"\bconfig\b", "配置"),
    (r"\bschema\b", "schema"),
    (r"\bdefault\b", "默认"),
    (r"\bdefaults\b", "默认值"),
    (r"\bloader\b", "加载器"),
    (r"\bloading\b", "加载"),
    (r"\binstall\b", "安装"),
    (r"\bdoctor\b", "doctor"),
    (r"\bmodel\b", "模型"),
    (r"\bmodels\b", "模型"),
    (r"\bimage\b", "图像"),
    (r"\bvideo\b", "视频"),
    (r"\bmusic\b", "音乐"),
    (r"\bmedia\b", "媒体"),
    (r"\bcapability\b", "能力"),
    (r"\bcapabilities\b", "能力"),
    (r"\bcommand\b", "命令"),
    (r"\bcommands\b", "命令"),
    (r"\bpath\b", "路径"),
    (r"\bpaths\b", "路径"),
    (r"\brequest\b", "请求"),
    (r"\brequests\b", "请求"),
    (r"\bresponse\b", "响应"),
    (r"\bheaders\b", "请求头"),
    (r"\bpayload\b", "负载"),
    (r"\bpayloads\b", "负载"),
    (r"\bcross-origin\b", "跨源"),
    (r"\bredirects\b", "重定向"),
    (r"\bredirect\b", "重定向"),
    (r"\bowner\b", "所有者"),
    (r"\bguard\b", "保护机制"),
    (r"\bOpenAI-compatible\b", "兼容 OpenAI"),
]


def _cleanup_translated_zh(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" ,", "，").replace(",", "，")
    text = text.replace(" ;", "；").replace(";", "；")
    text = text.replace(" :", "：")
    text = text.replace(" .", "。")
    text = re.sub(r"\bwith\b", "并附带", text, flags=re.IGNORECASE)
    text = re.sub(r"\bfor\b", "用于", text, flags=re.IGNORECASE)
    text = re.sub(r"\bfrom\b", "从", text, flags=re.IGNORECASE)
    text = re.sub(r"\bthrough\b", "通过", text, flags=re.IGNORECASE)
    text = re.sub(r"\bacross\b", "跨", text, flags=re.IGNORECASE)
    text = re.sub(r"\binto\b", "到", text, flags=re.IGNORECASE)
    text = re.sub(r"\bvia\b", "通过", text, flags=re.IGNORECASE)
    text = re.sub(r"\band\b", "并", text, flags=re.IGNORECASE)
    text = re.sub(r"\bor\b", "或", text, flags=re.IGNORECASE)
    text = re.sub(r"\bso that\b", "以便", text, flags=re.IGNORECASE)
    text = re.sub(r"\bso\b", "因此", text, flags=re.IGNORECASE)
    text = re.sub(r"\bthe\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\ban\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\ba\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ，；。")
    if text and text[-1] not in "。！？":
        text += "。"
    return text


def translate_release_note_zh(item: str) -> str:
    text = item.strip()
    prefix = ""
    body = text
    match = re.match(r"^([^:]{2,90}):\s+(.+)$", text)
    if match:
        prefix = _translate_component_zh(match.group(1).strip())
        body = match.group(2).strip()

    translated = body
    for pattern, target in TRANSLATION_PHRASES_ZH:
        translated = re.sub(pattern, target, translated, flags=re.IGNORECASE)

    translated = _cleanup_translated_zh(translated)
    if prefix:
        return f"{prefix}：{translated}"
    return translated
