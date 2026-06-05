"""AgentLoop progressive skill loading 测试。

验证 v3.2 SkillSelectionPass：
- 由 AgentLoop 内部执行，不作为普通 tool call
- 可批量加载多个 SKILL.md
- 加载结果进入 system context
- 不计入 max_tool_calls，不进入 tool_trace
"""

import sys
from contextlib import contextmanager
from pathlib import Path
import shutil
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_loop import AgentLoop
from core.llm_client import LLMResponse


@contextmanager
def local_temp_dir():
    """在 repo 内创建临时目录，避免 Windows 系统 Temp 权限问题。"""
    root = Path(__file__).parent.parent / "_tmp_test_agent_loop" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def write_skill(root: Path, skill_id: str, body: str) -> None:
    """写入测试用 SKILL.md。"""
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
id: {skill_id}
description: Test skill {skill_id}
when_to_load:
  - when needed
suggested_tools:
  - search_knowledge
---
{body}
""",
        encoding="utf-8",
    )


class FakeLLMClient:
    """用于 AgentLoop 测试的最小 LLMClient 替身。"""

    def __init__(self, selection_response: str, *, fail_selection: bool = False):
        self.selection_response = selection_response
        self.fail_selection = fail_selection
        self.chat_calls = []
        self.chat_with_tools_calls = []

    async def chat(self, messages, **kwargs):
        self.chat_calls.append({"messages": messages, "kwargs": kwargs})
        if self.fail_selection:
            raise RuntimeError("skill selection unavailable")
        return self.selection_response

    async def chat_with_tools(self, messages, tools=None, **kwargs):
        self.chat_with_tools_calls.append(
            {"messages": messages, "tools": tools, "kwargs": kwargs}
        )
        return LLMResponse(
            content="最终回答",
            tool_calls=[],
            finish_reason="stop",
        )

    def create_tool_message(self, tool_call_id, tool_name, result):
        return {"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": str(result)}


class FakeAgent:
    """只实现 AgentLoop 所需接口的假 Agent。"""

    def __init__(self, llm_client, config):
        self.agent_id = "fake-maker"
        self.llm_client = llm_client
        self.config = config

    def get_system_prompt(self):
        return "你是测试 Maker。"

    def format_user_input(self, input_data):
        return input_data["question"]

    def get_tools_for_llm(self):
        return []

    async def execute_tool(self, tool_name, arguments):
        return {"success": True}

    async def post_process_result(self, result, final_response, tool_results=None):
        result["post_processed"] = True
        result["tool_call_count"] = len(tool_results or [])
        return result


@pytest.mark.asyncio
async def test_skill_selection_pass_loads_skill_context_without_tool_trace():
    with local_temp_dir() as skills_dir:
        write_skill(skills_dir, "symptom_triage", "# Symptom\n完整症状分诊方法论")
        write_skill(skills_dir, "evidence_research", "# Evidence\n完整循证研究方法论")

        llm_client = FakeLLMClient(
            '{"requested_skills": ["symptom_triage", "missing", "symptom_triage"], "reason": "症状问题"}'
        )
        agent = FakeAgent(
            llm_client,
            {
                "progressive_skills_enabled": True,
                "skill_docs_dir": str(skills_dir),
                "temperature": 0.0,
            },
        )
        loop = AgentLoop(max_iterations=2, max_tool_calls=1)

        result = await loop.run(agent, {"question": "我胸痛怎么办"})

        assert result["process_trace"]["loaded_skills"] == ["symptom_triage"]
        assert result["process_trace"]["tool_trace"] == []
        assert "loaded_skills" not in result
        assert "tool_trace" not in result
        assert "skill_trace" not in result
        assert result["tool_call_count"] == 0
        assert loop.tool_call_count == 0
        assert len(llm_client.chat_calls) == 1
        assert len(llm_client.chat_with_tools_calls) == 1

        tool_loop_messages = llm_client.chat_with_tools_calls[0]["messages"]
        skill_context_messages = [
            msg for msg in tool_loop_messages
            if msg["role"] == "system" and "完整症状分诊方法论" in msg["content"]
        ]
        assert skill_context_messages


@pytest.mark.asyncio
async def test_skill_selection_disabled_does_not_call_selection_llm():
    with local_temp_dir() as skills_dir:
        write_skill(skills_dir, "symptom_triage", "# Symptom\n方法论")

        llm_client = FakeLLMClient('{"requested_skills": ["symptom_triage"]}')
        agent = FakeAgent(
            llm_client,
            {
                "progressive_skills_enabled": False,
                "skill_docs_dir": str(skills_dir),
                "temperature": 0.0,
            },
        )
        loop = AgentLoop(max_iterations=1, max_tool_calls=1)

        result = await loop.run(agent, {"question": "我胸痛怎么办"})

        assert result["process_trace"]["loaded_skills"] == []
        assert result["process_trace"]["skill_selection"]["enabled"] is False
        assert llm_client.chat_calls == []
        assert len(llm_client.chat_with_tools_calls) == 1


@pytest.mark.asyncio
async def test_skill_selection_failure_is_recorded_and_main_loop_continues():
    with local_temp_dir() as skills_dir:
        write_skill(skills_dir, "symptom_triage", "# Symptom\n方法论")

        llm_client = FakeLLMClient("{}", fail_selection=True)
        agent = FakeAgent(
            llm_client,
            {
                "progressive_skills_enabled": True,
                "skill_docs_dir": str(skills_dir),
                "temperature": 0.0,
            },
        )
        loop = AgentLoop(max_iterations=1, max_tool_calls=1)

        result = await loop.run(agent, {"question": "我胸痛怎么办"})

        assert result["answer"] == "最终回答"
        assert result["process_trace"]["loaded_skills"] == []
        assert result["process_trace"]["skill_selection"]["error"] == "skill selection unavailable"
        assert len(llm_client.chat_with_tools_calls) == 1


def test_parse_requested_skills_handles_fenced_json():
    raw = """```json
{"requested_skills": ["symptom_triage", "evidence_research"]}
```"""

    assert AgentLoop._parse_requested_skills(raw) == [
        "symptom_triage",
        "evidence_research",
    ]
