"""v3 structured tools 注册测试。

当前 AgentLoop 仍使用 SkillRegistry 作为 OpenAI function calling 适配层。
本测试保证 tools/ 目录里的现代工具真正暴露给 Maker，而不是只存在于文件系统里。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.generator import GeneratorAgent


def test_generator_registers_modern_structured_tools():
    agent = GeneratorAgent(agent_id="generator-tool-test", llm_client=object())

    registered = agent.skill_registry.get_all()

    assert "drug_safety_lookup" in registered
    assert "lab_reference_lookup" in registered
    assert "memory_context_lookup" in registered
    assert "risk_rule_check" in registered
    assert "imaging_reference_lookup" in registered
    assert "vital_sign_reference_lookup" in registered

    openai_tools = agent.get_tools_for_llm()
    memory_tool = next(
        item for item in openai_tools
        if item["function"]["name"] == "memory_context_lookup"
    )

    assert set(memory_tool["function"]["parameters"]["required"]) == {
        "user_id",
        "query",
    }
