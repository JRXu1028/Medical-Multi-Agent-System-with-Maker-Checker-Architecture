"""本地 JSONL 记忆存储。

本文件只负责持久化和读取 MemoryRecord，不做医学判断，也不调用 LLM。
长期记忆默认按 user_id 隔离，避免跨用户泄漏；所有记录都标记为“不可作为医学证据”。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_MEMORY_PATH = Path("memory/data/user_memory.jsonl")


@dataclass(frozen=True)
class MemoryRecord:
    """一条用户记忆。

    memory_type 示例：preference、medical_context、safety_note、session_summary。
    sensitivity 示例：normal、health、safety。记忆只用于上下文，不允许进入 EvidenceRecord。
    """

    id: str
    user_id: str
    content: str
    memory_type: str = "preference"
    sensitivity: str = "normal"
    source: str = "user_consent"
    created_at: str = field(default_factory=lambda: _utc_now())
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        user_id: str,
        content: str,
        memory_type: str = "preference",
        sensitivity: str = "normal",
        source: str = "user_consent",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "MemoryRecord":
        """创建带随机 id 的 MemoryRecord。"""

        return cls(
            id=f"mem-{uuid.uuid4().hex}",
            user_id=user_id,
            content=content,
            memory_type=memory_type,
            sensitivity=sensitivity,
            source=source,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSONL 友好的 dict。"""

        return {
            "id": self.id,
            "user_id": self.user_id,
            "content": self.content,
            "memory_type": self.memory_type,
            "sensitivity": self.sensitivity,
            "source": self.source,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "not_medical_evidence": True,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRecord":
        """从 dict 恢复 MemoryRecord。"""

        return cls(
            id=str(data.get("id", "")),
            user_id=str(data.get("user_id", "")),
            content=str(data.get("content", "")),
            memory_type=str(data.get("memory_type", "preference")),
            sensitivity=str(data.get("sensitivity", "normal")),
            source=str(data.get("source", "user_consent")),
            created_at=str(data.get("created_at") or _utc_now()),
            metadata=dict(data.get("metadata", {}) or {}),
        )


class LocalMemoryStore:
    """最小可测试的本地 JSONL 记忆存储。"""

    def __init__(self, path: str | Path = DEFAULT_MEMORY_PATH) -> None:
        self.path = Path(path)

    def append(self, record: MemoryRecord) -> None:
        """追加写入一条记忆。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False))
            handle.write("\n")

    def list_user_records(self, user_id: str) -> List[MemoryRecord]:
        """读取指定用户的全部记忆。"""

        if not self.path.exists():
            return []
        records: List[MemoryRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = MemoryRecord.from_dict(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
                if record.user_id == user_id:
                    records.append(record)
        return records


def _utc_now() -> str:
    """返回稳定 ISO 时间戳。"""

    return datetime.now(timezone.utc).isoformat()
