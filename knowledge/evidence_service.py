"""RAG 证据服务。

本模块负责把底层知识库的原始检索结果转换成统一的 EvidenceRecord。
它不生成医学结论，也不拼接最终回答，只提供可审计、可追踪、可测试的证据数据。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from loguru import logger

from tools.specs import EvidenceRecord


DEFAULT_SNIPPET_CHARS = 600


class EvidenceService:
    """知识库检索到证据记录的适配层。

    设计要点：
    - 依赖注入 kb，方便单元测试使用假知识库，避免加载真实 embedding 模型。
    - 只做结构化转换，不做医学判断，避免把 coverage/conflict 这类难验证字段伪装成事实。
    - 保持 metadata 原样透传一部分，给后续 Checker / Eval 留出审计空间。
    """

    def __init__(self, kb: Optional[Any] = None) -> None:
        self._kb = kb

    @property
    def kb(self) -> Any:
        """延迟加载真实知识库，避免导入本模块时立刻加载 embedding 模型。"""
        if self._kb is None:
            from knowledge.milvus_kb import MedicalKnowledgeBase

            self._kb = MedicalKnowledgeBase()
        return self._kb

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filter_type: Optional[str] = None,
        evidence_type: Optional[str] = None,
    ) -> List[EvidenceRecord]:
        """检索知识库并返回结构化证据记录。"""
        normalized_query = (query or "").strip()
        if not normalized_query:
            return []

        raw_docs = self.kb.search(
            query=normalized_query,
            top_k=max(1, int(top_k)),
            filter_type=filter_type,
        )

        records = [
            self._to_evidence_record(
                raw_doc=doc,
                fallback_query=normalized_query,
                fallback_type=evidence_type or self._type_from_filter(filter_type),
            )
            for doc in raw_docs
        ]

        logger.debug(
            "EvidenceService search completed: query={!r}, filter_type={!r}, count={}",
            normalized_query,
            filter_type,
            len(records),
        )
        return records

    def search_as_dicts(
        self,
        query: str,
        *,
        top_k: int = 5,
        filter_type: Optional[str] = None,
        evidence_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """检索并返回纯 dict，供 legacy skill wrapper 和 JSON 序列化使用。"""
        return [
            record.to_dict()
            for record in self.search(
                query,
                top_k=top_k,
                filter_type=filter_type,
                evidence_type=evidence_type,
            )
        ]

    def _to_evidence_record(
        self,
        *,
        raw_doc: Dict[str, Any],
        fallback_query: str,
        fallback_type: str,
    ) -> EvidenceRecord:
        """把 Milvus 原始结果转换为 EvidenceRecord。"""
        metadata = raw_doc.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        doc_id = str(metadata.get("doc_id") or raw_doc.get("id") or fallback_query)
        chunk_id = metadata.get("chunk_id")
        record_id = f"{doc_id}#{chunk_id}" if chunk_id is not None else doc_id

        title = self._title_from_metadata(metadata, fallback_query)
        source = str(metadata.get("source") or "local_medical_kb")
        organization = self._optional_str(metadata.get("organization"))
        year = self._optional_int(metadata.get("year"))
        evidence_type = str(metadata.get("type") or fallback_type or "knowledge")

        snippet = self._trim_snippet(str(raw_doc.get("content") or ""))
        score = self._safe_float(raw_doc.get("score"))

        return EvidenceRecord(
            id=record_id,
            title=title,
            source=source,
            organization=organization,
            year=year,
            snippet=snippet,
            score=score,
            evidence_type=evidence_type,
            citation=self._build_citation(title, organization, year, source),
            metadata=self._compact_metadata(metadata),
        )

    @staticmethod
    def _type_from_filter(filter_type: Optional[str]) -> str:
        """根据知识库 filter_type 给证据一个保守类别。"""
        if filter_type == "clinical_guideline":
            return "clinical_guideline"
        if filter_type:
            return filter_type
        return "knowledge"

    @staticmethod
    def _title_from_metadata(metadata: Dict[str, Any], fallback_query: str) -> str:
        """从 metadata 中抽取人类可读标题。"""
        for key in ("title", "guideline_title", "disease", "name"):
            value = metadata.get(key)
            if value:
                return str(value)

        filename = metadata.get("filename")
        if filename:
            return Path(str(filename)).stem

        return fallback_query

    @staticmethod
    def _trim_snippet(text: str, limit: int = DEFAULT_SNIPPET_CHARS) -> str:
        """限制证据片段长度，避免 observation 把上下文撑爆。"""
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3] + "..."

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        if value in (None, "", "N/A"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_str(value: Any) -> Optional[str]:
        if value in (None, "", "N/A"):
            return None
        return str(value)

    @staticmethod
    def _compact_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """保留轻量 metadata，避免把大文本重复塞进 evidence。

        这里使用显式白名单是有意设计：EvidenceRecord 应保持短小稳定。
        如果后续导入 PMID、DOI、publication_date 等可审计字段，需要在这里
        同步加入白名单，否则会被过滤掉。
        """
        allowed_keys = {
            "doc_id",
            "chunk_id",
            "total_chunks",
            "type",
            "source",
            "filename",
            "disease",
            "organization",
            "year",
        }
        return {key: value for key, value in metadata.items() if key in allowed_keys}

    @staticmethod
    def _build_citation(
        title: str,
        organization: Optional[str],
        year: Optional[int],
        source: str,
    ) -> str:
        """生成简短 citation，供 Maker/Checker 展示和审计。"""
        parts: Iterable[str] = (
            part
            for part in (title, organization, str(year) if year else None, source)
            if part
        )
        return " | ".join(parts)


_evidence_service: Optional[EvidenceService] = None


def get_evidence_service() -> EvidenceService:
    """获取默认 EvidenceService 单例，避免反复加载知识库和 embedding 模型。"""
    global _evidence_service
    if _evidence_service is None:
        _evidence_service = EvidenceService()
    return _evidence_service
