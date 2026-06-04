"""药物安全查询工具。

本文件定义 v3.4 的专用医学 Tool：drug_safety_lookup。
它只负责查询药物相互作用、禁忌、特殊人群、漏服/过量边界等证据，
并以 ToolResult + EvidenceRecord 的结构化形式返回，供 Maker 和 Checker 审计。
"""

from __future__ import annotations

from typing import Any, Dict

from knowledge.evidence_service import get_evidence_service
from tools.specs import ToolResult, ToolSpec


DRUG_SAFETY_LOOKUP_SPEC = ToolSpec(
    name="drug_safety_lookup",
    description="查询药物相互作用、禁忌、特殊人群、漏服/过量等用药安全证据。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "药物名称、同服场景、副作用、禁忌或漏服问题",
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
    category="drug_safety",
)


async def drug_safety_lookup(query: str, max_results: int = 5) -> Dict[str, Any]:
    """查询药物安全证据并返回标准 ToolResult dict。"""

    augmented_query = f"{query} 药物相互作用 禁忌 特殊人群 漏服 过量"
    try:
        service = get_evidence_service()
        records = service.search(
            query=augmented_query,
            top_k=max_results,
            filter_type=None,
            evidence_type="drug_safety",
        )

        return ToolResult(
            tool_name=DRUG_SAFETY_LOOKUP_SPEC.name,
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
            tool_name=DRUG_SAFETY_LOOKUP_SPEC.name,
            success=False,
            data={
                "query": query,
                "augmented_query": augmented_query,
                "total_found": 0,
            },
            error=str(exc),
        ).to_dict()
