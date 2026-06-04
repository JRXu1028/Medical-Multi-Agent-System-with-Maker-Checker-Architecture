"""工具层通用数据结构。

本文件定义 v3 架构的最小工具契约：
- EvidenceRecord：RAG 和医学工具返回的可审计证据。
- ToolResult：所有可执行工具的标准返回格式。
- ToolSpec：工具注册和 LLM function calling 所需的元信息。

这些结构只表达数据契约，不包含业务逻辑，从而保持高内聚、低耦合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class EvidenceRecord:
    """一条可审计医学证据。

    字段只保留当前系统能稳定自动填充的信息，避免把 coverage/conflict
    这类需要医学判断的内容伪装成检索器输出。
    """

    id: str
    title: str
    source: str
    snippet: str
    score: float = 0.0
    evidence_type: str = "knowledge"
    organization: Optional[str] = None
    year: Optional[str] = None
    citation: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 友好的 dict，供 Agent/Checker/Trace 使用。"""

        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "organization": self.organization,
            "year": self.year,
            "snippet": self.snippet,
            "score": self.score,
            "evidence_type": self.evidence_type,
            "citation": self.citation,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceRecord":
        """从 dict 恢复 EvidenceRecord，兼容工具返回和测试 fixture。"""

        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            source=str(data.get("source", "")),
            organization=data.get("organization"),
            year=str(data["year"]) if data.get("year") is not None else None,
            snippet=str(data.get("snippet", "")),
            score=float(data.get("score", 0.0) or 0.0),
            evidence_type=str(data.get("evidence_type", "knowledge")),
            citation=data.get("citation"),
            metadata=dict(data.get("metadata", {}) or {}),
        )

    def brief(self) -> str:
        """生成短文本摘要，用于旧版 ActionSignal evidence 字符串兼容。"""

        parts = [self.title or self.id]
        if self.organization:
            parts.append(str(self.organization))
        if self.year:
            parts.append(str(self.year))
        if self.snippet:
            parts.append(self.snippet[:80])
        return " | ".join(part for part in parts if part)


@dataclass
class ToolResult:
    """工具标准返回结果。

    ToolResult 让 AgentLoop、Maker、Checker 不再依赖每个工具自由发挥的
    answer 文本，而是统一消费 data + evidence。
    """

    tool_name: str
    success: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    evidence: List[EvidenceRecord] = field(default_factory=list)
    error: Optional[str] = None
    latency_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 友好的 dict。"""

        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "data": self.data,
            "evidence": [item.to_dict() for item in self.evidence],
            "error": self.error,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolResult":
        """从 dict 恢复 ToolResult，方便兼容 legacy wrapper。"""

        raw_evidence = data.get("evidence", []) or []
        evidence = [
            item if isinstance(item, EvidenceRecord) else EvidenceRecord.from_dict(item)
            for item in raw_evidence
            if isinstance(item, (dict, EvidenceRecord))
        ]
        return cls(
            tool_name=str(data.get("tool_name", "")),
            success=bool(data.get("success", True)),
            data=dict(data.get("data", {}) or {}),
            evidence=evidence,
            error=data.get("error"),
            latency_ms=data.get("latency_ms"),
        )


@dataclass(frozen=True)
class ToolSpec:
    """工具注册元信息。

    ToolSpec 只描述可执行工具，不用于 SKILL.md 方法论文档加载。
    """

    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    category: str = "medical"
    timeout_seconds: int = 30
    cost_level: str = "low"
    implementation: Optional[Callable[..., Any]] = None
