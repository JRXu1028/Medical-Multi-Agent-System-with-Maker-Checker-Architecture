"""化验指标参考查询工具。

本文件定义 v3.4 的专用医学 Tool：lab_reference_lookup。
它只负责查询常见化验指标含义、参考范围、复查边界和上下文注意事项，
并以 ToolResult + EvidenceRecord 的结构化形式返回，避免 Maker 直接凭空解释报告。
"""

from __future__ import annotations

from typing import Any, Dict

from knowledge.evidence_service import get_evidence_service
from tools.specs import ToolResult, ToolSpec


LAB_REFERENCE_LOOKUP_SPEC = ToolSpec(
    name="lab_reference_lookup",
    description="查询化验指标含义、参考范围、异常解释和复查建议相关证据。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "化验单、检查报告、指标名称或异常数值",
            },
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
    category="lab_reference",
)


async def lab_reference_lookup(query: str, max_results: int = 5) -> Dict[str, Any]:
    """查询化验指标证据并返回标准 ToolResult dict。"""

    augmented_query = f"{query} 化验指标 参考范围 临床意义 复查"
    try:
        service = get_evidence_service()
        records = service.search(
            query=augmented_query,
            top_k=max_results,
            filter_type=None,
            evidence_type="lab_reference",
        )

        return ToolResult(
            tool_name=LAB_REFERENCE_LOOKUP_SPEC.name,
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
            tool_name=LAB_REFERENCE_LOOKUP_SPEC.name,
            success=False,
            data={
                "query": query,
                "augmented_query": augmented_query,
                "total_found": 0,
            },
            error=str(exc),
        ).to_dict()
