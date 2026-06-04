"""Agent 运行轨迹 JSONL 记录器。

v3.5 的 trace 目标是让一次 Maker-Checker 运行可以被离线审计：
Router 怎么分流、Maker 加载了哪些 Skills、调用了哪些 Tools、收集了哪些 evidence、
Checker 的 precheck/LLM audit 和 SafetyGate 最终如何处理。
本模块只做序列化和写入，不依赖 LLM、Milvus 或具体 Agent 类。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AgentTraceRecord:
    """单轮端到端 Agent 运行轨迹。"""

    trace_id: str
    user_query: str
    route: Optional[Dict[str, Any]] = None
    loaded_skills: List[str] = field(default_factory=list)
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    prestop_result: Optional[Dict[str, Any]] = None
    checker_verdict: Optional[Dict[str, Any]] = None
    safety_gate: Optional[Dict[str, Any]] = None
    final_action: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为可 JSON 序列化的 dict。"""

        return {
            "trace_id": self.trace_id,
            "user_query": self.user_query,
            "route": _safe_json(self.route),
            "loaded_skills": list(self.loaded_skills),
            "tool_trace": _safe_json(self.tool_trace),
            "evidence": _safe_json(self.evidence),
            "prestop_result": _safe_json(self.prestop_result),
            "checker_verdict": _safe_json(self.checker_verdict),
            "safety_gate": _safe_json(self.safety_gate),
            "final_action": self.final_action,
            "metadata": _safe_json(self.metadata),
        }


class TraceWriter:
    """向 JSONL 文件追加写入 AgentTraceRecord。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, record: AgentTraceRecord | Dict[str, Any]) -> None:
        """写入单条 trace，父目录不存在时自动创建。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = record.to_dict() if isinstance(record, AgentTraceRecord) else record
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_safe_json(payload), ensure_ascii=False))
            handle.write("\n")

    def read_all(self) -> List[Dict[str, Any]]:
        """读取当前 JSONL 文件中的全部 trace，测试和调试使用。"""

        if not self.path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    records.append(json.loads(stripped))
        return records


def _safe_json(value: Any) -> Any:
    """把常见 Python 对象转换成 JSON 友好结构。

    这里刻意保持保守：优先使用对象自身的 to_dict，其次处理 dataclass/list/dict，
    最后再转成字符串，避免 trace 写入因为某个复杂对象失败。
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _safe_json(value.to_dict())
    if is_dataclass(value):
        return _safe_json(asdict(value))
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(item) for item in value]
    return str(value)
