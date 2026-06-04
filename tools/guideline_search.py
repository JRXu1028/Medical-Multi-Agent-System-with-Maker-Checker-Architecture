"""临床指南检索工具。

这是 v3 架构中的可执行 Tool：只负责查找指南类证据，
并把结果以 ToolResult + EvidenceRecord 的形式返回。
"""

from __future__ import annotations

from typing import Any, Dict

from knowledge.evidence_service import get_evidence_service
from tools.specs import ToolResult, ToolSpec


GUIDELINE_SEARCH_SPEC = ToolSpec(
    name="guideline_search",
    description="检索临床指南类知识，返回带机构、年份、来源的结构化证据记录。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "疾病、症状或治疗主题"},
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
    category="rag",
)


async def guideline_search(query: str, max_results: int = 3) -> Dict[str, Any]:
    """执行临床指南检索并返回 ToolResult dict。"""
    try:
        service = get_evidence_service()
        records = service.search(
            query=f"{query} 临床指南 诊疗规范",
            top_k=max_results,
            filter_type="clinical_guideline",
            evidence_type="clinical_guideline",
        )

        return ToolResult(
            tool_name=GUIDELINE_SEARCH_SPEC.name,
            success=True,
            data={
                "query": query,
                "total_found": len(records),
            },
            evidence=records,
        ).to_dict()
    except Exception as exc:  # pragma: no cover - 真实知识库异常由集成测试覆盖
        return ToolResult(
            tool_name=GUIDELINE_SEARCH_SPEC.name,
            success=False,
            data={"query": query, "total_found": 0},
            error=str(exc),
        ).to_dict()
