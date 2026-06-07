"""影像报告参考查询工具。

imaging_reference_lookup 查询 CT、MRI、超声、X 光等影像报告术语、
常见发现和复查边界，并以 ToolResult + EvidenceRecord 返回。
"""

from __future__ import annotations

from typing import Any, Dict

from knowledge.evidence_service import get_evidence_service
from tools.specs import ToolResult, ToolSpec


IMAGING_REFERENCE_LOOKUP_SPEC = ToolSpec(
    name="imaging_reference_lookup",
    description="查询 CT、MRI、超声、X 光等影像报告术语和复查边界相关证据。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "影像报告文字、检查类型或影像术语"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 5},
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
    category="imaging_reference",
)


async def imaging_reference_lookup(query: str, max_results: int = 5) -> Dict[str, Any]:
    """查询影像报告相关证据并返回标准 ToolResult dict。"""

    augmented_query = f"{query} 影像报告 CT MRI 超声 X线 结节 复查 随访"
    try:
        service = get_evidence_service()
        search_fn = getattr(service, "advanced_search", service.search)
        records = search_fn(
            query=augmented_query,
            top_k=max_results,
            filter_type=None,
            evidence_type="imaging_reference",
        )
        return ToolResult(
            tool_name=IMAGING_REFERENCE_LOOKUP_SPEC.name,
            success=True,
            data={
                "query": query,
                "augmented_query": augmented_query,
                "total_found": len(records),
            },
            evidence=records,
        ).to_dict()
    except Exception as exc:  # pragma: no cover - 真实知识库异常由集成测试覆盖
        return ToolResult(
            tool_name=IMAGING_REFERENCE_LOOKUP_SPEC.name,
            success=False,
            data={"query": query, "augmented_query": augmented_query, "total_found": 0},
            error=str(exc),
        ).to_dict()
