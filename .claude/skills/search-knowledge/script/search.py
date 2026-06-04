"""Search Knowledge legacy skill wrapper。

这个文件仍然暴露旧架构需要的 search_knowledge 函数名，
但内部已经委托给 v3 tools.medical_kb_search。
这样 SkillLoader 不需要立刻大改，同时 RAG 输出升级为结构化 evidence records。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from loguru import logger

from tools.medical_kb_search import medical_kb_search


async def search_knowledge(query: str, max_results: int = 5) -> Dict[str, Any]:
    """检索医学知识库，兼容旧字段并新增 evidence。"""
    logger.info(
        "Searching medical knowledge via v3 tool: query={}, max_results={}",
        query,
        max_results,
    )

    tool_result = await medical_kb_search(query=query, max_results=max_results)
    evidence = tool_result.get("evidence", []) if tool_result.get("success") else []

    return {
        # 旧字段：继续给 Agent observation 一段可读摘要，避免现有 prompt 完全失效。
        "answer": format_evidence(evidence, query),
        "total_found": len(evidence),
        "query": query,
        # 新字段：给 Maker/Checker 后处理使用的结构化证据。
        "evidence": evidence,
        "tool_result": tool_result,
    }


def format_evidence(evidence: List[Dict[str, Any]], query: str) -> str:
    """把结构化 evidence 简短格式化为 observation 文本。"""
    if not evidence:
        return f"未找到关于“{query}”的相关医学知识。"

    lines: List[str] = []
    for index, item in enumerate(evidence, 1):
        title = item.get("title") or "未命名证据"
        snippet = item.get("snippet") or ""
        citation = item.get("citation") or item.get("source") or "local_medical_kb"
        score = item.get("score", 0)

        lines.append(f"【证据 {index}】{title}")
        lines.append(str(snippet))
        lines.append(f"来源: {citation}")
        if isinstance(score, (int, float)) and score > 0:
            lines.append(f"相关度: {score:.2%}")
        lines.append("")

    return "\n".join(lines).strip()


def search_knowledge_sync(query: str, max_results: int = 5) -> Dict[str, Any]:
    """同步包装，供脚本调试或旧调用方使用。"""
    return asyncio.run(search_knowledge(query, max_results))


if __name__ == "__main__":
    test_query = "高血压的治疗方法"
    result = asyncio.run(search_knowledge(test_query))
    print(result["answer"])
    print(f"evidence_count={len(result['evidence'])}")
