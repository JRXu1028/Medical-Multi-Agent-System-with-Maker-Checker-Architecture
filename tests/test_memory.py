"""安全 Memory 单元测试。

测试重点：
- 长期记忆必须有用户授权才能写入
- 记忆按 user_id 隔离
- memory_context_lookup 只返回上下文，不返回医学 evidence
- legacy 短期/长期记忆 wrapper 依赖的接口可用
"""

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.long_term import LongTermMemory
from memory.service import MemoryContextItem, MemoryService
from memory.short_term import ShortTermMemory
from memory.store import LocalMemoryStore


def _memory_path(name: str) -> Path:
    return Path(__file__).parent.parent / "_tmp_test_memory" / f"{name}-{uuid.uuid4().hex}.jsonl"


def test_memory_service_requires_consent_and_scopes_by_user():
    service = MemoryService(store=LocalMemoryStore(_memory_path("consent")))

    denied = service.remember(
        user_id="user-a",
        content="用户有高血压，偏好低盐饮食。",
        consent=False,
        memory_type="medical_context",
        sensitivity="health",
    )
    assert denied.success is False
    assert denied.reason == "consent_required"

    accepted = service.remember(
        user_id="user-a",
        content="用户有高血压，偏好低盐饮食。",
        consent=True,
        memory_type="medical_context",
        sensitivity="health",
    )
    assert accepted.success is True

    assert service.search_context(
        user_id="user-a",
        query="高血压 饮食",
        max_results=3,
    )[0].content.startswith("用户有高血压")
    assert service.search_context(
        user_id="user-b",
        query="高血压 饮食",
        max_results=3,
    ) == []


def test_memory_service_hides_safety_sensitive_records_by_default():
    service = MemoryService(store=LocalMemoryStore(_memory_path("safety")))
    service.remember(
        user_id="user-a",
        content="用户曾表达严重自伤风险，需要优先提供危机支持。",
        consent=True,
        memory_type="safety_note",
        sensitivity="safety",
    )

    assert service.search_context(
        user_id="user-a",
        query="自伤 风险",
        include_sensitive=False,
    ) == []
    assert len(service.search_context(
        user_id="user-a",
        query="自伤 风险",
        include_sensitive=True,
    )) == 1


@pytest.mark.asyncio
async def test_memory_context_lookup_never_returns_evidence(monkeypatch):
    import tools.memory_context_lookup as module

    class FakeMemoryService:
        def search_context(self, **kwargs):
            return [
                MemoryContextItem(
                    id="mem-1",
                    content="用户偏好低盐饮食。",
                    memory_type="preference",
                    sensitivity="normal",
                    score=0.8,
                    created_at="2026-06-05T00:00:00Z",
                    metadata={},
                )
            ]

        def build_context_block(self, items):
            return "Memory Context - not medical evidence"

    monkeypatch.setattr(module, "get_memory_service", lambda: FakeMemoryService())

    result = await module.memory_context_lookup(
        user_id="user-a",
        query="低盐饮食",
    )

    assert result["tool_name"] == "memory_context_lookup"
    assert result["success"] is True
    assert result["evidence"] == []
    assert result["data"]["not_medical_evidence"] is True
    assert result["data"]["memory_context"][0]["not_medical_evidence"] is True


def test_short_term_memory_records_recent_messages():
    memory = ShortTermMemory()
    session_id = f"session-{uuid.uuid4().hex}"

    memory.add_message(session_id, "user", "我刚才问了什么？")
    memory.add_message(session_id, "assistant", "你询问了历史对话。")

    messages = memory.get_recent_messages(session_id, limit=2)

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert all(item["not_medical_evidence"] for item in messages)


def test_long_term_memory_legacy_interface_uses_memory_service():
    service = MemoryService(store=LocalMemoryStore(_memory_path("legacy")))
    memory = LongTermMemory(service=service, user_id="global")

    write_result = memory.add_session_summary(
        user_id="global",
        summary="高血压用户询问低盐饮食和运动安排。",
        consent=True,
    )
    results = memory.search_similar_sessions("高血压 饮食", limit=2)

    assert write_result["success"] is True
    assert len(results) == 1
    assert results[0]["metadata"]["not_medical_evidence"] is True
