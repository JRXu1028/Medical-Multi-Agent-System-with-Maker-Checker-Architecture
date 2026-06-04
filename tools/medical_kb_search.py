"""医学知识库检索工具。

这是 v3 架构中的可执行 Tool：输入 query，返回 ToolResult，
其中 evidence 字段是结构化 EvidenceRecord，供 Maker/Checker 审计。
"""

from __future__ import annotations

from typing import Any, Dict

from knowledge.evidence_service import get_evidence_service
from tools.specs import ToolResult, ToolSpec


MEDICAL_KB_SEARCH_SPEC = ToolSpec(
    name="medical_kb_search",
    description="检索本地医学知识库，返回可审计的结构化证据记录。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "用户问题或检索关键词"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
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
    category="rag",
)


async def medical_kb_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """执行医学知识库检索并返回 ToolResult dict。"""
    try:
        service = get_evidence_service()
        records = service.search(
            query=query,
            top_k=max_results,
            filter_type=None,
            evidence_type="knowledge",
        )

        return ToolResult(
            tool_name=MEDICAL_KB_SEARCH_SPEC.name,
            success=True,
            data={
                "query": query,
                "total_found": len(records),
            },
            evidence=records,
        ).to_dict()
    except Exception as exc:  # pragma: no cover - 真实知识库异常由集成测试覆盖
        return ToolResult(
            tool_name=MEDICAL_KB_SEARCH_SPEC.name,
            success=False,
            data={"query": query, "total_found": 0},
            error=str(exc),
        ).to_dict()
