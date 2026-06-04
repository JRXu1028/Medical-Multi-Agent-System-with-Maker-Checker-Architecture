"""Checker 语义审计测试。

本文件覆盖 v3.4 的 Checker semantic audit 升级：
- system prompt 使用 5 类 issue taxonomy
- review prompt 显式包含 loaded_skills / tool_trace / evidence_records
- LLM 输出的旧 issue type 会被规范化，方便后续 eval/trace 统计
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.reviewer import CHECKER_ISSUE_TYPES, ReviewerAgent


def test_checker_system_prompt_uses_v3_issue_taxonomy():
    reviewer = ReviewerAgent(agent_id="checker-prompt-test", llm_client=object())

    prompt = reviewer.get_system_prompt()

    for issue_type in CHECKER_ISSUE_TYPES:
        assert issue_type in prompt
    assert "loaded_skills" in prompt
    assert "tool_trace" in prompt
    assert "不生成替代医学答案" in prompt


def test_checker_review_prompt_includes_loaded_skills_tools_and_evidence():
    reviewer = ReviewerAgent(agent_id="checker-render-test", llm_client=object())

    prompt = reviewer._build_review_prompt({
        "user_query": "布洛芬和华法林能一起吃吗？",
        "answer": "建议咨询医生。",
        "loaded_skills": ["medication_safety"],
        "tool_trace": [
            {"name": "drug_safety_lookup", "arguments": {"query": "布洛芬 华法林"}, "success": True}
        ],
        "evidence_records": [
            {"id": "drug-1", "title": "NSAIDs and warfarin", "evidence_type": "drug_safety"}
        ],
        "skill_trace": [{"skill": "drug_safety_lookup", "key_finding": "bleeding risk"}],
        "action_signal": {
            "result": "存在相互作用风险",
            "confidence": 0.7,
            "proposed_action": "consult_doctor",
            "evidence": ["drug evidence"],
        },
        "prestop_result": {"status": "PASS"},
    })

    assert "medication_safety" in prompt
    assert "drug_safety_lookup" in prompt
    assert "NSAIDs and warfarin" in prompt
    assert "loaded_skills" in prompt or "Loaded Skills" in prompt


@pytest.mark.asyncio
async def test_checker_normalizes_legacy_issue_types_in_llm_output():
    reviewer = ReviewerAgent(agent_id="checker-normalize-test", llm_client=object())

    result = await reviewer.post_process_result(
        {},
        """
        {
          "verdict": "CHALLENGE",
          "challenges": [
            {
              "type": "logic_gap",
              "description": "旧类型应被归一化",
              "severity": "medium",
              "suggested_fix": "使用 v3 issue taxonomy"
            }
          ],
          "confidence_adjusted": 0.5
        }
        """,
        tool_results=[],
    )

    assert result["verdict"] == "CHALLENGE"
    assert result["challenges"][0]["type"] == "CONTEXT_GAP"
