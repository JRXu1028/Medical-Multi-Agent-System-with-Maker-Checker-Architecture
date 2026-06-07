"""确定性风险规则检查工具。

本工具是 legacy `assess_risk` 的现代结构化补充：它不尝试诊断疾病，
只根据用户描述中的高精度红旗信号输出 risk_level、matched_rules 和
recommendation，供 Maker、Checker 和 trace 审计。

注意：risk_rule_check 返回的是规则判断，不是医学文献证据，因此
ToolResult.evidence 为空。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from tools.specs import ToolResult, ToolSpec


@dataclass(frozen=True)
class RiskRule:
    """单条高精度风险规则。"""

    name: str
    patterns: Sequence[str]
    risk_level: str
    recommendation: str

    def matches(self, text: str) -> bool:
        """检查规则是否命中。"""

        return any(pattern.lower() in text for pattern in self.patterns)


RISK_RULES: List[RiskRule] = [
    RiskRule(
        name="emergency_symptoms",
        patterns=("胸痛", "呼吸困难", "昏厥", "晕厥", "意识模糊", "单侧无力", "严重出血", "视力突然丧失"),
        risk_level="high",
        recommendation="存在急症红旗信号，建议立即急诊或联系急救。",
    ),
    RiskRule(
        name="mental_health_crisis",
        patterns=("自杀", "自残", "轻生", "不想活", "伤害自己", "伤害别人", "结束生命"),
        risk_level="high",
        recommendation="存在心理危机或伤害风险，建议立即联系身边可信任的人和当地急救/危机干预资源。",
    ),
    RiskRule(
        name="urgent_vital_signs",
        patterns=("血氧 92", "血氧92", "血压 180", "血压180", "房颤", "心率很快", "心率很慢"),
        risk_level="medium_high",
        recommendation="生命体征或心电信息可能存在风险，建议尽快线下评估；伴随不适时按急症处理。",
    ),
    RiskRule(
        name="special_population",
        patterns=("孕妇", "怀孕", "婴儿", "宝宝", "老人", "老年", "免疫抑制"),
        risk_level="medium",
        recommendation="特殊人群风险判断应更保守，建议结合症状严重程度尽快咨询专业人员。",
    ),
]


RISK_RULE_CHECK_SPEC = ToolSpec(
    name="risk_rule_check",
    description="根据高精度红旗规则检查症状、心理危机、生命体征和特殊人群风险。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "用户原始问题或症状描述"},
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "tool_name": {"type": "string"},
            "success": {"type": "boolean"},
            "data": {"type": "object"},
            "evidence": {"type": "array"},
        },
    },
    category="risk",
)


async def risk_rule_check(query: str) -> Dict[str, Any]:
    """执行确定性风险规则检查。"""

    text = str(query or "").lower()
    matched = [rule for rule in RISK_RULES if rule.matches(text)]
    risk_level = _highest_risk([rule.risk_level for rule in matched])
    recommendation = (
        matched[0].recommendation
        if matched
        else "未命中高精度红旗规则；仍需结合完整症状和临床背景判断。"
    )

    return ToolResult(
        tool_name=RISK_RULE_CHECK_SPEC.name,
        success=True,
        data={
            "query": query,
            "risk_level": risk_level,
            "matched_rules": [rule.name for rule in matched],
            "recommendation": recommendation,
            "not_medical_evidence": True,
        },
        evidence=[],
    ).to_dict()


def _highest_risk(levels: Sequence[str]) -> str:
    """按固定优先级返回最高风险等级。"""

    priority = ["high", "medium_high", "medium", "low"]
    for level in priority:
        if level in levels:
            return level
    return "low"
