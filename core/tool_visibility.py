"""Skill 驱动的工具可见性策略。

本模块实现 Phase D：Tool Visibility Control。Maker 仍然自主选择工具，
但 AgentLoop 不再把所有工具 schema 一次性暴露给 LLM，而是根据本轮
已加载的 SKILL.md 过滤出相关工具，降低 token 成本和误调慢工具的概率。

设计边界：
- 只过滤 OpenAI function schema，不执行工具。
- 没有 loaded skills 时返回原工具列表，避免阻断未知问题。
- 保留 legacy tool 名称和现代 structured tool 名称，支持渐进迁移。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Set


DEFAULT_SKILL_TOOL_MAP: Mapping[str, Set[str]] = {
    "symptom_triage": {"assess_risk", "medical_kb_search", "guideline_search", "analyze_symptoms"},
    "emergency_red_flags": {"assess_risk", "risk_rule_check", "guideline_search", "medical_kb_search"},
    "mental_health_safety": {"assess_risk", "risk_rule_check", "medical_kb_search"},
    "clarifying_questions": {"medical_kb_search", "assess_risk"},
    "care_navigation": {"assess_risk", "medical_kb_search", "guideline_search"},
    "medication_safety": {"drug_safety_lookup", "medical_kb_search", "guideline_search"},
    "drug_interaction": {"drug_safety_lookup", "medical_kb_search", "guideline_search"},
    "renal_liver_dose_safety": {
        "drug_safety_lookup",
        "lab_reference_lookup",
        "renal_liver_dose_lookup",
        "medical_kb_search",
        "guideline_search",
    },
    "pregnancy_pediatric_safety": {"drug_safety_lookup", "medical_kb_search", "guideline_search", "assess_risk"},
    "geriatric_safety": {"assess_risk", "drug_safety_lookup", "medical_kb_search"},
    "lab_report": {"lab_reference_lookup", "medical_kb_search", "guideline_search", "assess_risk"},
    "imaging_report": {"imaging_reference_lookup", "medical_kb_search", "guideline_search"},
    "ecg_vital_signs": {"vital_sign_reference_lookup", "assess_risk", "medical_kb_search", "guideline_search"},
    "guideline_research": {"guideline_search", "medical_kb_search", "deep_research", "clinical_guideline"},
    "evidence_comparison": {"guideline_search", "medical_kb_search", "deep_research", "clinical_guideline"},
    "source_quality_appraisal": {"guideline_search", "medical_kb_search"},
    "health_education": {"medical_kb_search", "search_knowledge"},
    "preventive_care": {"guideline_search", "medical_kb_search"},
    "medical_device_explainer": {"medical_kb_search", "vital_sign_reference_lookup"},
    "chronic_care": {"guideline_search", "medical_kb_search", "recommend_lifestyle", "clinical_guideline"},
    "lifestyle_coaching": {"recommend_lifestyle", "medical_kb_search", "search_knowledge"},
    "nutrition_weight_management": {"recommend_lifestyle", "medical_kb_search", "guideline_search"},
    "rehabilitation_exercise_safety": {"assess_risk", "medical_kb_search", "guideline_search"},
    "memory_personalization": {
        "memory_context_lookup",
        "drug_safety_lookup",
        "medical_kb_search",
        "guideline_search",
    },
}


ALWAYS_VISIBLE_TOOLS: Set[str] = {
    # 保留核心安全和检索工具，避免 resolver 漏选时完全失去兜底能力。
    "assess_risk",
    "medical_kb_search",
}


@dataclass(frozen=True)
class ToolVisibilityResult:
    """工具过滤结果。"""

    tools: List[dict]
    visible_tool_names: List[str]
    hidden_tool_names: List[str]
    policy_version: str = "skill_tool_visibility_v1"

    def to_dict(self) -> Dict[str, object]:
        """转换为 process_trace 可记录的 dict。"""

        return {
            "visible_tool_names": self.visible_tool_names,
            "hidden_tool_names": self.hidden_tool_names,
            "policy_version": self.policy_version,
        }


class ToolVisibilityPolicy:
    """根据 loaded skills 过滤 OpenAI tools。"""

    def __init__(
        self,
        *,
        skill_tool_map: Mapping[str, Set[str]] | None = None,
        always_visible_tools: Iterable[str] | None = None,
    ) -> None:
        self.skill_tool_map = skill_tool_map or DEFAULT_SKILL_TOOL_MAP
        self.always_visible_tools = set(always_visible_tools or ALWAYS_VISIBLE_TOOLS)

    def filter_tools(
        self,
        *,
        tools: Sequence[dict],
        loaded_skills: Sequence[str],
    ) -> ToolVisibilityResult:
        """根据 loaded skills 返回可见工具列表。

        若没有 loaded skills 或没有命中任何工具，返回原工具列表，防止过度过滤。
        """

        all_names = [tool_name(tool) for tool in tools if tool_name(tool)]
        if not loaded_skills:
            return ToolVisibilityResult(
                tools=list(tools),
                visible_tool_names=all_names,
                hidden_tool_names=[],
            )

        allowed = set(self.always_visible_tools)
        for skill_id in loaded_skills:
            allowed.update(self.skill_tool_map.get(skill_id, set()))

        filtered = [
            tool for tool in tools
            if tool_name(tool) in allowed
        ]
        if not filtered:
            return ToolVisibilityResult(
                tools=list(tools),
                visible_tool_names=all_names,
                hidden_tool_names=[],
            )

        visible = [tool_name(tool) for tool in filtered if tool_name(tool)]
        hidden = [name for name in all_names if name not in set(visible)]
        return ToolVisibilityResult(
            tools=filtered,
            visible_tool_names=visible,
            hidden_tool_names=hidden,
        )


def tool_name(tool: dict) -> str:
    """从 OpenAI function schema 中提取工具名。"""

    try:
        return str(tool.get("function", {}).get("name", ""))
    except AttributeError:
        return ""
