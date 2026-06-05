"""Generator repair profile 测试。

验证 Maker 的推理预算策略：
- Round 1 默认使用 generator fast/non-thinking profile
- Checker / PreStop REJECT 触发 regenerate 后，repair round 临时切到 generator_repair
- 测试注入 fake llm_client 时不会误触真实 API
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.generator import GeneratorAgent
from config import get_llm_config


class FakeRepairClient:
    """用于标记 repair profile 的 fake LLM client。"""

    def __init__(self, profile: str):
        self.profile = profile


class RecordingGenerator(GeneratorAgent):
    """覆盖 generate，避免运行真实 AgentLoop。"""

    async def generate(self, user_query: str):
        return {
            "user_query": user_query,
            "answer": "ok",
            "action_signal": {},
            "evidence_records": [],
            "process_trace": {
                "llm_profile": self.config.get("llm_profile"),
                "client_profile": getattr(self.llm_client, "profile", "external"),
            },
        }


def test_generator_default_profile_is_non_thinking():
    """Round 1 generator 应关闭 thinking；max_tokens 可被本地 .env 覆盖。"""

    config = get_llm_config("generator")

    assert config["disable_thinking"] is True
    assert isinstance(config["max_tokens"], int)
    assert config.get("extra_body")


def test_generator_repair_profile_allows_thinking():
    """repair profile 默认保留 thinking，作为被 Checker 触发的强修复预算。"""

    config = get_llm_config("generator_repair")

    assert config["disable_thinking"] is False
    assert config["max_tokens"] == 3000
    assert "extra_body" not in config


@pytest.mark.asyncio
async def test_regenerate_temporarily_switches_to_repair_profile(monkeypatch):
    """regenerate 应临时切到 generator_repair，结束后恢复原 profile。"""

    import agents.generator as generator_module

    monkeypatch.setattr(generator_module, "LLMClient", lambda profile: FakeRepairClient(profile))
    agent = RecordingGenerator(agent_id="generator-repair-test", llm_client=object())
    agent._external_llm_client = False

    result = await agent.regenerate(
        "原始问题",
        challenges=[{"type": "EVIDENCE_GAP", "description": "证据不足"}],
    )

    assert result["user_query"] == "原始问题"
    assert result["process_trace"]["llm_profile"] == "generator_repair"
    assert result["process_trace"]["client_profile"] == "generator_repair"
    assert result["process_trace"]["repair_profile"] == "generator_repair"
    assert agent.config["llm_profile"] == "generator"
