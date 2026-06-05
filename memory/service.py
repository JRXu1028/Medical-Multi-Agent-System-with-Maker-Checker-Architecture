"""安全记忆服务。

MemoryService 负责长期记忆的授权写入、按用户隔离检索和上下文块生成。
核心安全原则：
- 没有用户授权，不写长期记忆。
- 记忆只作为 user context，不作为医学 evidence。
- 默认不返回 safety 级敏感记忆，除非调用方显式允许。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from knowledge.rag_retrieval import lexical_score
from memory.store import LocalMemoryStore, MemoryRecord


@dataclass(frozen=True)
class MemoryContextItem:
    """检索出的单条记忆上下文。"""

    id: str
    content: str
    memory_type: str
    sensitivity: str
    score: float
    created_at: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 友好 dict。"""

        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type,
            "sensitivity": self.sensitivity,
            "score": self.score,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "not_medical_evidence": True,
        }


@dataclass(frozen=True)
class MemoryWriteResult:
    """记忆写入结果。"""

    success: bool
    record: Optional[MemoryRecord] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 友好 dict。"""

        return {
            "success": self.success,
            "record": self.record.to_dict() if self.record else None,
            "reason": self.reason,
        }


class MemoryService:
    """用户授权的长期记忆服务。"""

    def __init__(
        self,
        store: Optional[LocalMemoryStore] = None,
        *,
        enabled: bool = True,
        require_consent: bool = True,
    ) -> None:
        self.store = store or LocalMemoryStore()
        self.enabled = enabled
        self.require_consent = require_consent

    def remember(
        self,
        *,
        user_id: str,
        content: str,
        consent: bool,
        memory_type: str = "preference",
        sensitivity: str = "normal",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryWriteResult:
        """在用户授权后写入长期记忆。"""

        normalized_user = (user_id or "").strip()
        normalized_content = (content or "").strip()
        if not self.enabled:
            return MemoryWriteResult(False, reason="memory_disabled")
        if not normalized_user:
            return MemoryWriteResult(False, reason="missing_user_id")
        if not normalized_content:
            return MemoryWriteResult(False, reason="empty_content")
        if self.require_consent and not consent:
            return MemoryWriteResult(False, reason="consent_required")

        record = MemoryRecord.create(
            user_id=normalized_user,
            content=normalized_content,
            memory_type=memory_type,
            sensitivity=sensitivity,
            metadata=metadata,
        )
        self.store.append(record)
        return MemoryWriteResult(True, record=record)

    def search_context(
        self,
        *,
        user_id: str,
        query: str,
        max_results: int = 5,
        include_sensitive: bool = False,
    ) -> List[MemoryContextItem]:
        """检索用户长期记忆上下文。"""

        if not self.enabled or not (user_id or "").strip() or not (query or "").strip():
            return []

        candidates: List[MemoryContextItem] = []
        for record in self.store.list_user_records(user_id.strip()):
            if record.sensitivity == "safety" and not include_sensitive:
                continue
            score = lexical_score(query, record.content)
            if score <= 0:
                continue
            candidates.append(
                MemoryContextItem(
                    id=record.id,
                    content=record.content,
                    memory_type=record.memory_type,
                    sensitivity=record.sensitivity,
                    score=score,
                    created_at=record.created_at,
                    metadata=record.metadata,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[: max(1, int(max_results))]

    @staticmethod
    def build_context_block(items: List[MemoryContextItem]) -> str:
        """生成给 Maker 使用的短上下文块，明确声明不能当医学证据。"""

        if not items:
            return ""
        lines = ["[Memory Context - not medical evidence]"]
        for index, item in enumerate(items, 1):
            lines.append(
                f"{index}. ({item.memory_type}, score={item.score:.2f}) {item.content}"
            )
        return "\n".join(lines)


_memory_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """获取默认 MemoryService 单例。"""

    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
