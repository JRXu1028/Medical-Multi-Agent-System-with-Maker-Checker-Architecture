"""Clinical Guideline legacy skill wrapper。

这个文件仍然暴露旧架构需要的 clinical_guideline 函数名，
但内部已经委托给 v3 tools.guideline_search。
这样旧 AgentLoop 可以继续工作，RAG 指南结果也升级为结构化 evidence records。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from loguru import logger

from tools.guideline_search import guideline_search


async def clinical_guideline(query: str, max_results: int = 1) -> Dict[str, Any]:
    """检索临床指南，兼容旧字段并新增 evidence。"""
    logger.info(
        "Searching clinical guideline via v3 tool: query={}, max_results={}",
        query,
        max_results,
    )

    tool_result = await guideline_search(query=query, max_results=max_results)
    evidence = tool_result.get("evidence", []) if tool_result.get("success") else []
    first = evidence[0] if evidence else {}

    return {
        # 旧字段：Generator / Reviewer 现有逻辑仍可读取。
        "answer": format_guideline_evidence(evidence, query),
        "guideline_title": first.get("title", ""),
        "organization": first.get("organization") or "",
        "year": first.get("year") or "",
        "source": first.get("source") or "not_found",
        # 新字段：结构化证据，供 v3 后处理审计。
        "evidence": evidence,
        "total_found": len(evidence),
        "query": query,
        "tool_result": tool_result,
    }


def format_guideline_evidence(evidence: List[Dict[str, Any]], query: str) -> str:
    """把指南 evidence 简短格式化为 observation 文本。"""
    if not evidence:
        return f"未找到“{query}”的相关临床指南。"

    lines: List[str] = ["【临床指南证据】"]
    for index, item in enumerate(evidence, 1):
        title = item.get("title") or "未命名指南"
        organization = item.get("organization") or "未知机构"
        year = item.get("year") or "未知年份"
        snippet = item.get("snippet") or ""
        citation = item.get("citation") or item.get("source") or "local_medical_kb"

        lines.append(f"{index}. {title}")
        lines.append(f"发布机构: {organization}")
        lines.append(f"发布年份: {year}")
        lines.append(f"来源: {citation}")
        lines.append(f"内容: {snippet}")
        lines.append("")

    return "\n".join(lines).strip()


def clinical_guideline_sync(query: str, max_results: int = 1) -> Dict[str, Any]:
    """同步包装，供脚本调试或旧调用方使用。"""
    return asyncio.run(clinical_guideline(query, max_results))
