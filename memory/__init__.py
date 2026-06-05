"""医疗 Agent 记忆系统。

Memory 在本项目中只提供用户上下文，不提供医学证据。
长期记忆必须有用户授权；短期记忆只服务当前会话连续性。
"""

from .service import MemoryContextItem, MemoryService, get_memory_service
from .store import LocalMemoryStore, MemoryRecord

__all__ = [
    "LocalMemoryStore",
    "MemoryContextItem",
    "MemoryRecord",
    "MemoryService",
    "get_memory_service",
]
