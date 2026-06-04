"""Maker 证据提取工具。

本模块只负责从 AgentLoop 收集到的 tool_results 中提取结构化证据，
并把结构化 EvidenceRecord 压缩成旧 ActionSignal.evidence 可用的短文本摘要。
它不依赖 LLMClient、AgentLoop 或 SkillRegistry，便于单元测试和后续复用。
"""

from __future__ import annotations

from typing import Any, Dict, List

from loguru import logger

from tools.specs import EvidenceRecord


def extract_evidence_records(
    tool_results: List[Dict[str, Any]],
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """从 tool 返回值中提取结构化 EvidenceRecord。

    兼容两种形态：
    1. legacy wrapper 顶层返回 {"evidence": [...]}；
    2. wrapper 内部保留 {"tool_result": {"evidence": [...]}}。

    这里仅做数据规范化、容错和去重，不判断医学结论是否成立。
    """
    records: List[Dict[str, Any]] = []
    seen_ids = set()

    for call_record in tool_results:
        result = call_record.get("result", {})
        if not isinstance(result, dict):
            continue

        for item in _iter_raw_evidence_items(result):
            if not isinstance(item, dict):
                continue
            try:
                record = EvidenceRecord.from_dict(item)
            except Exception as exc:
                logger.warning("Skip malformed evidence record: {}", exc)
                continue

            key = _dedupe_key(record)
            if key in seen_ids:
                continue

            seen_ids.add(key)
            records.append(record.to_dict())

            if len(records) >= limit:
                return records

    return records


def merge_evidence_record_summaries(
    evidence: List[str],
    evidence_records: List[Dict[str, Any]],
    *,
    limit: int = 8,
) -> List[str]:
    """把结构化证据压缩成短文本摘要，合并进旧 ActionSignal.evidence。

    SafetyGate 和部分旧逻辑仍读取 evidence: list[str]，所以这里不直接把
    EvidenceRecord dict 塞进去，而是生成可读、可去重的 brief 文本。
    """
    merged = list(evidence)
    seen = set(merged)

    for item in evidence_records:
        try:
            brief = EvidenceRecord.from_dict(item).brief()
        except Exception:
            continue
        if brief and brief not in seen:
            merged.append(brief)
            seen.add(brief)

        if len(merged) >= limit:
            return merged

    return merged


def _iter_raw_evidence_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """收集 wrapper 顶层和 ToolResult 嵌套层的 evidence 候选项。"""
    candidates = []

    top_level_evidence = result.get("evidence")
    if isinstance(top_level_evidence, list):
        candidates.extend(top_level_evidence)

    tool_result = result.get("tool_result")
    if isinstance(tool_result, dict):
        nested_evidence = tool_result.get("evidence")
        if isinstance(nested_evidence, list):
            candidates.extend(nested_evidence)

    return candidates


def _dedupe_key(record: EvidenceRecord) -> str:
    """为 evidence 去重生成稳定 key。"""
    if record.id:
        return record.id
    return f"{record.title}:{record.source}:{record.snippet[:40]}"
