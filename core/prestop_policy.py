"""PreStopPolicy：Checker 内部的确定性过程预检策略。

PreStopPolicy 是纯规则组件，不调用 LLM，不生成最终答案。
它由 Reviewer/Checker 在调用 LLM 审查前执行，只检查 Maker draft 的过程是否完整：
- 触发关键医疗场景时，必需工具是否被调用
- action_signal 是否存在且包含 proposed_action
- 高置信回答是否有 evidence 支撑

它不判断最终医学结论是否安全；最终输出内容安全由 SafetyGate 负责。
它保持为独立模块，是为了方便单元测试和后续替换为 Signal Catalog 规则源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence


class PreStopStatus:
    """PreStopPolicy 的三种结果。"""

    PASS = "PASS"
    REPAIR = "REPAIR"
    FORCED_SAFE = "FORCED_SAFE"


class PreStopIssueType:
    """PreStopPolicy 的问题类型。"""

    MISSING_REQUIRED_TOOL = "MISSING_REQUIRED_TOOL"
    MISSING_ACTION_SIGNAL = "MISSING_ACTION_SIGNAL"
    MISSING_PROPOSED_ACTION = "MISSING_PROPOSED_ACTION"
    EVIDENCE_GAP = "EVIDENCE_GAP"


@dataclass(frozen=True)
class PreStopIssue:
    """单个过程问题。"""

    type: str
    description: str
    missing_tools: List[str] = field(default_factory=list)
    rule_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为纯 dict，便于写入 rounds_log / trace。"""
        return {
            "type": self.type,
            "description": self.description,
            "missing_tools": self.missing_tools,
            "rule_name": self.rule_name,
        }


@dataclass(frozen=True)
class PreStopRule:
    """required-tool 规则。

    patterns 命中 user_query 或 route_decision.triggers 后，required_tools
    中的工具必须出现在 tool_trace 里。
    """

    name: str
    patterns: Sequence[str]
    required_tools: Sequence[str]
    repair_instruction: str

    def matches(self, user_query: str, triggers: Sequence[str]) -> bool:
        """检查规则是否命中 query 或 Router triggers。"""
        haystacks = [user_query, *triggers]
        return any(
            pattern and pattern in haystack
            for haystack in haystacks
            for pattern in self.patterns
        )


@dataclass(frozen=True)
class PreStopResult:
    """PreStopPolicy 单次检查结果。"""

    status: str
    phase: str
    issues: List[PreStopIssue] = field(default_factory=list)
    repair_message: str = ""

    @classmethod
    def pass_(cls, phase: str) -> "PreStopResult":
        """快速构造 PASS 结果。"""
        return cls(status=PreStopStatus.PASS, phase=phase)

    @classmethod
    def repair(
        cls,
        phase: str,
        issues: List[PreStopIssue],
        repair_message: str,
    ) -> "PreStopResult":
        """快速构造 REPAIR 结果。"""
        return cls(
            status=PreStopStatus.REPAIR,
            phase=phase,
            issues=issues,
            repair_message=repair_message,
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为纯 dict，便于管道记录和测试断言。"""
        return {
            "status": self.status,
            "phase": self.phase,
            "issues": [issue.to_dict() for issue in self.issues],
            "repair_message": self.repair_message,
        }

    @property
    def passed(self) -> bool:
        """是否通过。"""
        return self.status == PreStopStatus.PASS


DEFAULT_REQUIRED_TOOL_RULES: List[PreStopRule] = [
    PreStopRule(
        name="symptom_requires_risk_assessment",
        patterns=(
            "胸痛",
            "呼吸困难",
            "昏厥",
            "晕厥",
            "剧烈头痛",
            "单侧无力",
            "意识模糊",
        ),
        required_tools=("assess_risk",),
        repair_instruction="用户包含高风险症状信号，必须先调用 assess_risk 做风险评估。",
    ),
    PreStopRule(
        name="medication_requires_knowledge_check",
        patterns=(
            "一起吃",
            "能同服",
            "相互作用",
            "漏服",
            "副作用",
            "禁忌",
            "过敏",
        ),
        required_tools=("drug_safety_lookup",),
        repair_instruction="用户询问用药安全，必须先调用 drug_safety_lookup 查证药物相互作用、禁忌或漏服边界。",
    ),
    PreStopRule(
        name="lab_report_requires_knowledge_check",
        patterns=(
            "化验单",
            "检查报告",
            "报告",
            "尿酸",
            "白细胞",
            "肌酐",
            "血糖",
            "血脂",
        ),
        required_tools=("lab_reference_lookup",),
        repair_instruction="用户询问报告或化验指标解读，必须先调用 lab_reference_lookup 查证指标含义和参考范围。",
    ),
]


class PreStopPolicy:
    """Reviewer/Checker 调用 LLM 前的确定性过程检查器。"""

    def __init__(
        self,
        required_tool_rules: Optional[Sequence[PreStopRule]] = None,
        high_confidence_threshold: float = 0.7,
    ) -> None:
        self.required_tool_rules = list(
            required_tool_rules
            if required_tool_rules is not None
            else DEFAULT_REQUIRED_TOOL_RULES
        )
        self.high_confidence_threshold = high_confidence_threshold

    def before_final(
        self,
        *,
        user_query: str,
        route_decision: Optional[Any] = None,
        tool_trace: Optional[List[Dict[str, Any]]] = None,
    ) -> PreStopResult:
        """检查 Maker 是否漏调 required tools。

        这是过程检查，不依赖 Maker 自报 selected_skills。
        """
        triggered_rules = self._matched_rules(user_query, route_decision)
        called_tools = self._called_tools(tool_trace or [])

        issues: List[PreStopIssue] = []
        for rule in triggered_rules:
            missing = [
                tool for tool in rule.required_tools
                if tool not in called_tools
            ]
            if not missing:
                continue

            issues.append(
                PreStopIssue(
                    type=PreStopIssueType.MISSING_REQUIRED_TOOL,
                    description=rule.repair_instruction,
                    missing_tools=list(missing),
                    rule_name=rule.name,
                )
            )

        if not issues:
            return PreStopResult.pass_("before_final")

        return PreStopResult.repair(
            phase="before_final",
            issues=issues,
            repair_message=self._build_repair_message(issues),
        )

    def before_review(
        self,
        *,
        user_query: str,
        route_decision: Optional[Any] = None,
        tool_trace: Optional[List[Dict[str, Any]]] = None,
        evidence: Optional[List[Any]] = None,
        action_signal: Optional[Dict[str, Any]] = None,
        draft_answer: Optional[str] = None,
    ) -> PreStopResult:
        """Maker draft 生成后、Checker 前的过程完整性检查。"""
        before_final_result = self.before_final(
            user_query=user_query,
            route_decision=route_decision,
            tool_trace=tool_trace,
        )
        if not before_final_result.passed:
            return before_final_result

        issues: List[PreStopIssue] = []

        if not action_signal:
            issues.append(
                PreStopIssue(
                    type=PreStopIssueType.MISSING_ACTION_SIGNAL,
                    description="Maker 输出缺少 action_signal，无法进入 Checker 审查。",
                )
            )
        elif not action_signal.get("proposed_action"):
            issues.append(
                PreStopIssue(
                    type=PreStopIssueType.MISSING_PROPOSED_ACTION,
                    description="action_signal 缺少 proposed_action，无法进入 Checker 审查。",
                )
            )

        if action_signal:
            confidence = self._safe_float(action_signal.get("confidence"))
            merged_evidence = list(evidence or []) + list(action_signal.get("evidence", []) or [])
            if confidence > self.high_confidence_threshold and not merged_evidence:
                issues.append(
                    PreStopIssue(
                        type=PreStopIssueType.EVIDENCE_GAP,
                        description=(
                            f"Maker 给出高置信度 confidence={confidence}，"
                            "但没有 evidence 支撑，必须补充证据或降低置信度。"
                        ),
                    )
                )

        if not issues:
            return PreStopResult.pass_("before_review")

        return PreStopResult.repair(
            phase="before_review",
            issues=issues,
            repair_message=self._build_repair_message(issues),
        )

    def _matched_rules(
        self,
        user_query: str,
        route_decision: Optional[Any],
    ) -> List[PreStopRule]:
        """查找被 query / route triggers 命中的 required-tool 规则。"""
        triggers = self._route_triggers(route_decision)
        return [
            rule for rule in self.required_tool_rules
            if rule.matches(user_query, triggers)
        ]

    @staticmethod
    def _route_triggers(route_decision: Optional[Any]) -> List[str]:
        """兼容 RouteDecision 对象和 dict。"""
        if route_decision is None:
            return []
        if isinstance(route_decision, dict):
            triggers = route_decision.get("triggers", [])
        else:
            triggers = getattr(route_decision, "triggers", [])
        if not isinstance(triggers, Iterable) or isinstance(triggers, (str, bytes)):
            return []
        return [str(item) for item in triggers]

    @staticmethod
    def _called_tools(tool_trace: List[Dict[str, Any]]) -> set:
        """从 tool_trace 中提取成功调用过的工具名。"""
        called = set()
        for item in tool_trace:
            name = item.get("name")
            if not name:
                continue
            if item.get("success", True) is False:
                continue
            called.add(str(name))
        return called

    @staticmethod
    def _safe_float(value: Any) -> float:
        """把 confidence 安全转换为 float。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _build_repair_message(issues: List[PreStopIssue]) -> str:
        """生成给 Maker.regenerate 使用的修复指令。"""
        lines = [
            "PreStopPolicy 检查发现本轮过程不完整，必须修复后才能进入 Checker："
        ]
        for index, issue in enumerate(issues, 1):
            lines.append(f"{index}. [{issue.type}] {issue.description}")
            if issue.missing_tools:
                lines.append(f"   缺失工具: {', '.join(issue.missing_tools)}")
        return "\n".join(lines)
