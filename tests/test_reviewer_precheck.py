"""Reviewer precheck 单元测试。

本文件验证 v3.3 的关键架构调整：
PreStopPolicy 不再由 Orchestrator 直接调用，而是作为 Reviewer/Checker
内部的 deterministic precheck。预检失败时，Reviewer 应直接返回 REJECT，
并且不进入 LLM 审查阶段。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.reviewer import ReviewerAgent


class NoLlmReviewer(ReviewerAgent):
    """如果 precheck 失败后仍进入 LLM loop，测试应立即失败。"""

    async def run_loop(self, input_data):
        raise AssertionError("precheck 失败时不应调用 LLM Reviewer")


@pytest.mark.asyncio
async def test_reviewer_precheck_rejects_without_llm_when_required_tool_missing():
    reviewer = NoLlmReviewer(agent_id="reviewer-precheck-test", llm_client=object())

    result = await reviewer.review({
        "user_query": "我胸痛呼吸困难，现在怎么办？",
        "answer": "建议先观察。",
        "action_signal": {
            "result": "建议观察",
            "confidence": 0.5,
            "proposed_action": "observe",
            "evidence": ["mock evidence"],
        },
        "process_trace": {"tool_trace": []},
        "evidence_records": [],
    })

    assert result["verdict"] == "REJECT"
    assert result["reject_type"] == "SAFETY_PROCESS_GAP"
    assert result["review_stage"] == "precheck"
    assert result["prestop_result"]["status"] == "REPAIR"
    assert result["prestop_result"]["issues"][0]["type"] == "SAFETY_PROCESS_GAP"
    assert result["prestop_result"]["issues"][0]["missing_tools"] == ["assess_risk"]
    assert "assess_risk" in result["challenges"][0]["suggested_fix"]


def test_reviewer_precheck_passes_when_required_tool_called():
    reviewer = ReviewerAgent(agent_id="reviewer-precheck-pass-test", llm_client=object())

    precheck = reviewer._run_prestop_precheck({
        "user_query": "我胸痛呼吸困难，现在怎么办？",
        "answer": "已完成风险评估。",
        "action_signal": {
            "result": "建议及时就医",
            "confidence": 0.5,
            "proposed_action": "urgent_care",
            "evidence": ["risk rule evidence"],
        },
        "process_trace": {
            "tool_trace": [
                {"name": "assess_risk", "arguments": {}, "success": True},
            ],
        },
        "evidence_records": [],
    })

    assert precheck.passed
    assert precheck.phase == "before_review"
