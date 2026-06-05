"""用户记忆上下文查询工具。

memory_context_lookup 是可执行 Tool，但它返回的是用户上下文，不是医学证据。
因此 ToolResult.evidence 始终为空，结果只放在 data.memory_context 中，
避免 Checker 或 Maker 把历史偏好、慢病背景误当成医学来源。
"""

from __future__ import annotations

from typing import Any, Dict

from memory.service import get_memory_service
from tools.specs import ToolResult, ToolSpec


MEMORY_CONTEXT_LOOKUP_SPEC = ToolSpec(
    name="memory_context_lookup",
    description="检索用户授权保存的长期记忆上下文；返回内容不能作为医学证据。",
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "用户 ID"},
            "query": {"type": "string", "description": "需要匹配的当前问题或上下文"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 5},
            "include_sensitive": {"type": "boolean"},
        },
        "required": ["user_id", "query"],
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
    category="memory",
)


async def memory_context_lookup(
    user_id: str,
    query: str,
    max_results: int = 5,
    include_sensitive: bool = False,
) -> Dict[str, Any]:
    """查询用户记忆上下文并返回标准 ToolResult dict。"""

    try:
        service = get_memory_service()
        items = service.search_context(
            user_id=user_id,
            query=query,
            max_results=max_results,
            include_sensitive=include_sensitive,
        )
        return ToolResult(
            tool_name=MEMORY_CONTEXT_LOOKUP_SPEC.name,
            success=True,
            data={
                "user_id": user_id,
                "query": query,
                "total_found": len(items),
                "memory_context": [item.to_dict() for item in items],
                "context_block": service.build_context_block(items),
                "not_medical_evidence": True,
            },
            evidence=[],
        ).to_dict()
    except Exception as exc:  # pragma: no cover - 真实存储异常由集成测试覆盖
        return ToolResult(
            tool_name=MEMORY_CONTEXT_LOOKUP_SPEC.name,
            success=False,
            data={
                "user_id": user_id,
                "query": query,
                "total_found": 0,
                "memory_context": [],
                "not_medical_evidence": True,
            },
            evidence=[],
            error=str(exc),
        ).to_dict()
