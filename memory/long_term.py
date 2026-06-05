"""长期记忆兼容层。

LongTermMemory 面向 legacy `.claude/skills/search-similar-cases` wrapper，
内部委托给新的 MemoryService。它不会把历史案例作为医学证据，只返回相似上下文。
"""

from __future__ import annotations

from typing import Any, Dict, List

from memory.service import MemoryService, get_memory_service


class LongTermMemory:
    """长期记忆兼容接口。"""

    def __init__(self, service: MemoryService | None = None, user_id: str = "global") -> None:
        self.service = service or get_memory_service()
        self.user_id = user_id
        self.enabled = self.service.enabled

    def add_session_summary(
        self,
        *,
        user_id: str,
        summary: str,
        consent: bool,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """写入一条历史会话摘要。"""

        result = self.service.remember(
            user_id=user_id,
            content=summary,
            consent=consent,
            memory_type="session_summary",
            sensitivity="health",
            metadata=metadata,
        )
        return result.to_dict()

    def search_similar_sessions(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """检索相似历史会话摘要。"""

        items = self.service.search_context(
            user_id=self.user_id,
            query=query,
            max_results=limit,
            include_sensitive=False,
        )
        return [
            {
                "content": item.content,
                "score": item.score,
                "metadata": {
                    **item.metadata,
                    "timestamp": item.created_at,
                    "not_medical_evidence": True,
                },
            }
            for item in items
        ]
