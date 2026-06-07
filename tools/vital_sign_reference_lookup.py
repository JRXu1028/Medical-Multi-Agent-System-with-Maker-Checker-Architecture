"""生命体征和心电图参考查询工具。

vital_sign_reference_lookup 查询血压、血氧、心率、体温、心电图文字
等生命体征相关证据，并以 ToolResult + EvidenceRecord 返回。
"""

from __future__ import annotations

from typing import Any, Dict

from knowledge.evidence_service import get_evidence_service
from tools.specs import ToolResult, ToolSpec


VITAL_SIGN_REFERENCE_LOOKUP_SPEC = ToolSpec(
    name="vital_sign_reference_lookup",
    description="查询血压、血氧、心率、体温、心电图等生命体征读数和风险边界证据。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "生命体征读数、心电图文字或相关症状"},
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
    category="vital_sign_reference",
)


async def vital_sign_reference_lookup(query: str, max_results: int = 5) -> Dict[str, Any]:
    """查询生命体征和心电图相关证据并返回标准 ToolResult dict。"""

    augmented_query = f"{query} 血压 血氧 心率 体温 心电图 房颤 ST段 风险边界"
    try:
        service = get_evidence_service()
        search_fn = getattr(service, "advanced_search", service.search)
        records = search_fn(
            query=augmented_query,
            top_k=max_results,
            filter_type=None,
            evidence_type="vital_sign_reference",
        )
        return ToolResult(
            tool_name=VITAL_SIGN_REFERENCE_LOOKUP_SPEC.name,
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
            tool_name=VITAL_SIGN_REFERENCE_LOOKUP_SPEC.name,
            success=False,
            data={"query": query, "augmented_query": augmented_query, "total_found": 0},
            error=str(exc),
        ).to_dict()
