"""Advanced RAG 检索与重排工具函数。

本模块只放纯算法逻辑：Reciprocal Rank Fusion、轻量 query-overlap rerank、
证据质量摘要。它不连接 Milvus，不调用 LLM，因此可以被单元测试稳定覆盖。
设计目标是把 RAG 从“取 top-k 文本”升级为“可融合、可重排、可审计的证据流水线”。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import replace
from datetime import date
from typing import Dict, Iterable, List, Sequence

from tools.specs import EvidenceRecord


EVIDENCE_TYPE_PRIORITY = {
    "clinical_guideline": 0.18,
    "drug_safety": 0.14,
    "lab_reference": 0.12,
    "knowledge": 0.08,
    "memory_context": -0.5,
}


@dataclass(frozen=True)
class EvidenceQualitySummary:
    """自动可计算的证据质量摘要。

    这里不声称 coverage/conflict 这类需要医学判断的字段，只统计机器能稳定得到的信息：
    证据类型、年份、引用覆盖率、低分证据和记忆上下文误用风险。
    """

    total: int
    evidence_types: Dict[str, int]
    newest_year: int | None
    oldest_year: int | None
    citation_coverage: float
    low_score_count: int
    stale_count: int
    memory_context_count: int

    def to_dict(self) -> Dict[str, object]:
        """转换为 JSON 友好 dict，供 ToolResult.data / trace 使用。"""

        return {
            "total": self.total,
            "evidence_types": dict(self.evidence_types),
            "newest_year": self.newest_year,
            "oldest_year": self.oldest_year,
            "citation_coverage": self.citation_coverage,
            "low_score_count": self.low_score_count,
            "stale_count": self.stale_count,
            "memory_context_count": self.memory_context_count,
        }


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[EvidenceRecord]],
    *,
    top_k: int,
    rrf_k: int = 60,
) -> List[EvidenceRecord]:
    """使用 RRF 融合多个检索结果列表。

    RRF 适合把 dense retrieval、keyword retrieval、specialized retrieval 的结果合并，
    不要求不同检索器分数在同一尺度上。
    """

    scores: Dict[str, float] = {}
    records: Dict[str, EvidenceRecord] = {}

    for ranked in ranked_lists:
        for rank, record in enumerate(ranked, 1):
            records.setdefault(record.id, record)
            scores[record.id] = scores.get(record.id, 0.0) + 1.0 / (rrf_k + rank)

    sorted_ids = sorted(scores, key=lambda item_id: scores[item_id], reverse=True)
    fused: List[EvidenceRecord] = []
    for item_id in sorted_ids[:top_k]:
        record = records[item_id]
        fused.append(
            replace(
                record,
                score=round(scores[item_id], 4),
                metadata={
                    **record.metadata,
                    "rrf_score": round(scores[item_id], 4),
                    "base_score": record.score,
                },
            )
        )
    return fused


def rerank_evidence(
    records: Sequence[EvidenceRecord],
    query: str,
    *,
    top_k: int,
) -> List[EvidenceRecord]:
    """对证据做轻量重排。

    第一版不用额外 cross-encoder，避免引入模型加载和 CI 不稳定。
    评分由检索分数、query overlap、证据类型优先级、引用完整性和年份新鲜度组成。
    """

    query_terms = set(tokenize(query))
    ranked = []
    for record in records:
        text = " ".join([record.title, record.snippet, record.source])
        doc_terms = set(tokenize(text))
        overlap = _jaccard(query_terms, doc_terms)
        type_bonus = EVIDENCE_TYPE_PRIORITY.get(record.evidence_type, 0.0)
        citation_bonus = 0.04 if record.citation else 0.0
        freshness_bonus = _freshness_bonus(record.year)
        rerank_score = (
            0.62 * _clamp(record.score)
            + 0.24 * overlap
            + type_bonus
            + citation_bonus
            + freshness_bonus
        )
        ranked.append(
            replace(
                record,
                score=round(rerank_score, 4),
                metadata={
                    **record.metadata,
                    "rerank_score": round(rerank_score, 4),
                    "query_overlap": round(overlap, 4),
                },
            )
        )

    return sorted(ranked, key=lambda item: item.score, reverse=True)[:top_k]


def summarize_evidence_quality(
    records: Sequence[EvidenceRecord],
    *,
    stale_after_years: int = 5,
    low_score_threshold: float = 0.35,
) -> EvidenceQualitySummary:
    """生成自动可验证的证据质量摘要。"""

    total = len(records)
    type_counts: Dict[str, int] = {}
    years: List[int] = []
    citation_count = 0
    low_score_count = 0
    memory_context_count = 0
    current_year = date.today().year

    for record in records:
        type_counts[record.evidence_type] = type_counts.get(record.evidence_type, 0) + 1
        if isinstance(record.year, int):
            years.append(record.year)
        if record.citation:
            citation_count += 1
        if record.score < low_score_threshold:
            low_score_count += 1
        if record.evidence_type == "memory_context":
            memory_context_count += 1

    stale_count = sum(
        1 for year in years if year < current_year - max(1, stale_after_years)
    )

    return EvidenceQualitySummary(
        total=total,
        evidence_types=type_counts,
        newest_year=max(years) if years else None,
        oldest_year=min(years) if years else None,
        citation_coverage=round(citation_count / total, 4) if total else 0.0,
        low_score_count=low_score_count,
        stale_count=stale_count,
        memory_context_count=memory_context_count,
    )


def lexical_score(query: str, text: str) -> float:
    """计算轻量词面相关度，供 keyword_search fallback 使用。"""

    query_terms = set(tokenize(query))
    doc_terms = set(tokenize(text))
    return round(_jaccard(query_terms, doc_terms), 4)


def tokenize(text: str) -> List[str]:
    """中英文混合的轻量 tokenizer。

    中文按连续 2 字符滑窗补充，英文/数字按词切分。它不是 BM25 的完整替代，
    但足够做本项目第一版 keyword signal 和单元测试。
    """

    normalized = (text or "").lower()
    ascii_terms = re.findall(r"[a-z0-9_+-]+", normalized)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    chinese_bigrams = [
        "".join(chinese_chars[index:index + 2])
        for index in range(max(0, len(chinese_chars) - 1))
    ]
    return ascii_terms + chinese_bigrams


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _freshness_bonus(year: int | None) -> float:
    if not isinstance(year, int):
        return 0.0
    age = max(0, date.today().year - year)
    if age <= 2:
        return 0.06
    if age <= 5:
        return 0.03
    return 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(float(value or 0.0), 1.0))
