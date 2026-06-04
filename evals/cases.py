"""统一 EvalCase 数据契约。

v3.5 的评估先解决“所有 eval 用同一套 case schema”这个基础问题。
Router、tool-call、RAG、Checker seeded cases 可以只填自己需要的字段，
但都使用同一个 EvalCase，避免后续测试数据和报告脚本碎片化。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class EvalCase:
    """单条评估样本。

    字段尽量保持朴素、可序列化；没有实现的指标先留空列表，而不是用 LLM 猜测。
    """

    id: str
    query: str
    tags: List[str] = field(default_factory=list)
    expected_route: Optional[str] = None
    expected_tools: List[str] = field(default_factory=list)
    expected_evidence_types: List[str] = field(default_factory=list)
    seeded_errors: List[str] = field(default_factory=list)
    expected_checker_issues: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSONL 友好的 dict。"""

        return {
            "id": self.id,
            "query": self.query,
            "tags": list(self.tags),
            "expected_route": self.expected_route,
            "expected_tools": list(self.expected_tools),
            "expected_evidence_types": list(self.expected_evidence_types),
            "seeded_errors": list(self.seeded_errors),
            "expected_checker_issues": list(self.expected_checker_issues),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvalCase":
        """从 dict 恢复 EvalCase，并对列表字段做防御性归一化。"""

        return cls(
            id=str(data.get("id", "")),
            query=str(data.get("query", "")),
            tags=_as_str_list(data.get("tags", [])),
            expected_route=_optional_str(data.get("expected_route")),
            expected_tools=_as_str_list(data.get("expected_tools", [])),
            expected_evidence_types=_as_str_list(
                data.get("expected_evidence_types", [])
            ),
            seeded_errors=_as_str_list(data.get("seeded_errors", [])),
            expected_checker_issues=_as_str_list(
                data.get("expected_checker_issues", [])
            ),
            metadata=dict(data.get("metadata", {}) or {}),
        )


def load_jsonl(path: str | Path) -> List[EvalCase]:
    """从 JSONL 文件加载 EvalCase 列表，自动跳过空行。"""

    cases: List[EvalCase] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                cases.append(EvalCase.from_dict(json.loads(stripped)))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return cases


def write_jsonl(path: str | Path, cases: Sequence[EvalCase]) -> None:
    """把 EvalCase 写入 JSONL，父目录不存在时自动创建。"""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.to_dict(), ensure_ascii=False))
            handle.write("\n")


def _as_str_list(value: Any) -> List[str]:
    """把任意输入安全归一化为字符串列表。"""

    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, Iterable):
        return []
    return [str(item) for item in value if item is not None]


def _optional_str(value: Any) -> Optional[str]:
    """把空值保留为 None，其余值转成字符串。"""

    if value in (None, ""):
        return None
    return str(value)
