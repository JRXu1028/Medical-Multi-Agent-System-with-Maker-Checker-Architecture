"""Advanced RAG 单元测试。

覆盖 v3 Future 中真正值得落地的 RAG 能力：
- dense + keyword hybrid 检索入口
- RRF / rerank 后的结构化 evidence
- 自动可计算的证据质量摘要
这些测试不依赖真实 Milvus 或 embedding 模型。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge.evidence_service import EvidenceService
from knowledge.rag_retrieval import rerank_evidence, summarize_evidence_quality
from tools.specs import EvidenceRecord


class FakeHybridKnowledgeBase:
    """同时支持 dense search 和 keyword_search 的测试知识库。"""

    def __init__(self):
        self.calls = []

    def search(self, query, top_k=5, filter_type=None):
        self.calls.append(("dense", query, top_k, filter_type))
        return [
            {
                "id": "dense-1",
                "content": "高血压患者需要结合血压水平和心血管风险综合管理。",
                "score": 0.72,
                "metadata": {
                    "doc_id": "dense-hbp",
                    "type": "knowledge",
                    "disease": "高血压",
                    "source": "local_kb",
                    "year": 2023,
                },
            }
        ]

    def keyword_search(self, query, top_k=5, filter_type=None):
        self.calls.append(("keyword", query, top_k, filter_type))
        return [
            {
                "id": "keyword-1",
                "content": "高血压饮食建议包括限盐、控制体重、规律运动。",
                "score": 0.64,
                "metadata": {
                    "doc_id": "keyword-diet",
                    "type": "clinical_guideline",
                    "disease": "高血压饮食",
                    "organization": "指南机构",
                    "source": "local_guideline",
                    "year": 2025,
                },
            }
        ]


def test_advanced_search_uses_hybrid_retrieval_and_rerank():
    service = EvidenceService(kb=FakeHybridKnowledgeBase())

    records = service.advanced_search("高血压 饮食", top_k=2, retrieval_mode="hybrid")

    assert len(records) == 2
    assert {call[0] for call in service.kb.calls} == {"dense", "keyword"}
    assert all("rerank_score" in record.metadata for record in records)
    assert records[0].score >= records[1].score


def test_rerank_keeps_memory_context_from_becoming_medical_evidence():
    records = [
        EvidenceRecord(
            id="memory-1",
            title="用户偏好",
            source="memory",
            snippet="用户偏好低盐饮食。",
            score=0.95,
            evidence_type="memory_context",
        ),
        EvidenceRecord(
            id="guideline-1",
            title="高血压饮食指南",
            source="local_guideline",
            snippet="高血压饮食建议包括限盐和控制体重。",
            score=0.7,
            evidence_type="clinical_guideline",
            year=2025,
            citation="高血压饮食指南 | 2025",
        ),
    ]

    reranked = rerank_evidence(records, "高血压 饮食", top_k=2)

    assert reranked[0].id == "guideline-1"
    assert reranked[-1].evidence_type == "memory_context"


def test_quality_summary_reports_only_machine_checkable_fields():
    records = [
        EvidenceRecord(
            id="g1",
            title="指南",
            source="local_guideline",
            snippet="指南证据",
            score=0.82,
            evidence_type="clinical_guideline",
            year=2025,
            citation="指南 | 2025",
        ),
        EvidenceRecord(
            id="m1",
            title="用户记忆",
            source="memory",
            snippet="用户说自己不喜欢咸食。",
            score=0.2,
            evidence_type="memory_context",
        ),
    ]

    summary = summarize_evidence_quality(records).to_dict()

    assert summary["total"] == 2
    assert summary["evidence_types"]["clinical_guideline"] == 1
    assert summary["memory_context_count"] == 1
    assert summary["low_score_count"] == 1
    assert "coverage" not in summary
    assert "conflicts" not in summary
