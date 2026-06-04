"""医疗 Agent 工具层包。

本包承载 v3 架构中的可执行工具与工具数据结构。
包入口只导出轻量数据结构，具体工具请从各自模块导入，避免循环依赖。
"""

from .specs import EvidenceRecord, ToolResult, ToolSpec

__all__ = ["EvidenceRecord", "ToolResult", "ToolSpec"]
