"""PreStopPolicy 单元测试。

覆盖 v3.3 的确定性过程检查：
- required tools 漏调拦截
- action_signal 完整性检查
- 高置信但无 evidence 的可修复问题
- 安全流程缺口拦截
- 等价检索工具 any-of 规则

PreStopPolicy 不调用 LLM，不依赖真实 Agent。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.prestop_policy import (
    PreStopIssueType,
    PreStopRejectType,
    PreStopPolicy,
    PreStopStatus,
)


def test_before_final_repairs_when_symptom_required_tool_missing():
    policy = PreStopPolicy()

    result = policy.before_final(
        user_query="我胸痛呼吸困难，需要怎么办",
        tool_trace=[],
    )

    assert result.status == PreStopStatus.REPAIR
    assert result.phase == "before_final"
    assert result.issues[0].type == PreStopIssueType.SAFETY_PROCESS_GAP
    assert result.issues[0].audit_scope == "safety_process"
    assert result.issues[0].missing_tools == ["assess_risk"]
    assert result.reject_type == PreStopRejectType.SAFETY_PROCESS_GAP
    assert "assess_risk" in result.repair_message


def test_before_final_passes_when_required_tool_called_successfully():
    policy = PreStopPolicy()

    result = policy.before_final(
        user_query="我胸痛呼吸困难，需要怎么办",
        tool_trace=[
            {"name": "assess_risk", "arguments": {}, "success": True},
        ],
    )

    assert result.status == PreStopStatus.PASS


def test_before_final_ignores_failed_required_tool_call():
    policy = PreStopPolicy()

    result = policy.before_final(
        user_query="我胸痛",
        tool_trace=[
            {"name": "assess_risk", "arguments": {}, "success": False},
        ],
    )

    assert result.status == PreStopStatus.REPAIR
    assert result.issues[0].missing_tools == ["assess_risk"]


def test_before_review_repairs_missing_urgency():
    policy = PreStopPolicy()

    result = policy.before_review(
        user_query="普通健康科普",
        tool_trace=[],
        evidence=[],
        urgency=None,
        draft_answer="draft",
    )

    assert result.status == PreStopStatus.REPAIR
    assert result.issues[0].type == PreStopIssueType.MISSING_URGENCY


def test_before_review_passes_when_urgency_derived_from_legacy_action_signal():
    """With evidence_strength removed, PreStopPolicy only checks urgency presence.

    High-confidence-without-evidence is now the Checker LLM's responsibility,
    not PreStopPolicy's deterministic precheck.
    """
    policy = PreStopPolicy()

    result = policy.before_review(
        user_query="普通健康科普",
        tool_trace=[],
        evidence=[],
        action_signal={
            "result": "结论",
            "confidence": 0.9,
            "proposed_action": "observe",
            "evidence": [],
        },
        draft_answer="draft",
    )

    assert result.status == PreStopStatus.PASS


def test_before_review_passes_with_low_confidence_without_evidence():
    policy = PreStopPolicy()

    result = policy.before_review(
        user_query="普通健康科普",
        tool_trace=[],
        evidence=[],
        action_signal={
            "result": "结论",
            "confidence": 0.5,
            "proposed_action": "observe",
            "evidence": [],
        },
        draft_answer="draft",
    )

    assert result.status == PreStopStatus.PASS


def test_route_triggers_can_activate_required_tool_rule():
    policy = PreStopPolicy()

    result = policy.before_final(
        user_query="请问怎么办",
        route_decision={"triggers": ["安全红线: 胸痛"]},
        tool_trace=[],
    )

    assert result.status == PreStopStatus.REPAIR
    assert result.issues[0].missing_tools == ["assess_risk"]


def test_before_final_requires_drug_safety_lookup_for_medication_question():
    policy = PreStopPolicy()

    result = policy.before_final(
        user_query="布洛芬和华法林能一起吃吗？",
        tool_trace=[],
    )

    assert result.status == PreStopStatus.REPAIR
    assert result.issues[0].type == PreStopIssueType.SAFETY_PROCESS_GAP
    assert result.issues[0].missing_tools == ["drug_safety_lookup"]


def test_before_final_requires_lab_reference_lookup_for_lab_report_question():
    policy = PreStopPolicy()

    result = policy.before_final(
        user_query="尿酸 520 的化验单严重吗？",
        tool_trace=[],
    )

    assert result.status == PreStopStatus.REPAIR
    assert result.issues[0].type == PreStopIssueType.TOOL_GAP
    assert result.issues[0].missing_tools == ["lab_reference_lookup"]


def test_before_final_requires_safety_process_for_mental_health_crisis():
    policy = PreStopPolicy()

    result = policy.before_final(
        user_query="我最近不想活了，想伤害自己",
        tool_trace=[],
    )

    assert result.status == PreStopStatus.REPAIR
    assert result.reject_type == PreStopRejectType.SAFETY_PROCESS_GAP
    assert result.issues[0].type == PreStopIssueType.SAFETY_PROCESS_GAP
    assert result.issues[0].missing_tools == ["assess_risk"]


def test_before_final_requires_any_retrieval_tool_for_guideline_question():
    policy = PreStopPolicy()

    result = policy.before_final(
        user_query="高血压最新指南推荐什么治疗方案？",
        tool_trace=[],
    )

    assert result.status == PreStopStatus.REPAIR
    assert result.issues[0].type == PreStopIssueType.TOOL_GAP
    assert result.issues[0].missing_tools == ["guideline_search", "medical_kb_search"]


def test_before_final_passes_when_any_retrieval_tool_called():
    policy = PreStopPolicy()

    result = policy.before_final(
        user_query="高血压最新指南推荐什么治疗方案？",
        tool_trace=[
            {"name": "medical_kb_search", "arguments": {}, "success": True},
        ],
    )

    assert result.status == PreStopStatus.PASS
