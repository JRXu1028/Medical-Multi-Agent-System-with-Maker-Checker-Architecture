"""短期会话记忆。

ShortTermMemory 只保存当前会话消息，服务上下文连续性；
它不做长期持久化，也不作为医学证据。
本模块同时兼容 legacy `.claude/skills/search-history` wrapper。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


_SESSION_MESSAGES: Dict[str, List[Dict[str, Any]]] = {}


class ShortTermMemory:
    """进程内短期会话记忆。"""

    def __init__(self, storage_type: str = "memory") -> None:
        self.storage_type = storage_type

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """记录一条会话消息。"""

        if not session_id:
            return
        _SESSION_MESSAGES.setdefault(session_id, []).append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "not_medical_evidence": True,
            }
        )

    def get_recent_messages(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近 N 条消息。"""

        messages = _SESSION_MESSAGES.get(session_id, [])
        return messages[-max(1, int(limit)):]

    def clear(self, session_id: str) -> None:
        """清空某个会话的短期记忆。"""

        _SESSION_MESSAGES.pop(session_id, None)
