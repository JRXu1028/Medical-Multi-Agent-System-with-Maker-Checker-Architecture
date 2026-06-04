"""EvidenceService 单元测试。

这些测试使用假知识库，确保 RAG 证据规范化逻辑可独立验证，
不会在单元测试中加载真实 Milvus 或 embedding 模型。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge.evidence_service import EvidenceService


class FakeKnowledgeBase:
    """用于测试 EvidenceService 的最小知识库替身。"""

    def __init__(self):
        self.last_call = None

    def search(self, query, top_k=5, filter_type=None):
        self.last_call = {
            "query": query,
            "top_k": top_k,
            "filter_type": filter_type,
        }
        return [
            {
                "id": 101,
                "content": " 高血压患者应结合血压水平、危险因素和靶器官损害综合评估。 ",
                "score": 0.87654,
                "metadata": {
                    "doc_id": "guideline-hbp",
                    "chunk_id": 2,
                    "type": "clinical_guideline",
                    "disease": "高血压",
                    "organization": "中华医学会",
                    "year": "2024",
                    "source": "local_guideline",
                    "filename": "hypertension.md",
                },
            }
        ]


def test_search_normalizes_raw_kb_result_to_evidence_record():
    kb = FakeKnowledgeBase()
    service = EvidenceService(kb=kb)

    records = service.search(
        "高血压治疗指南",
        top_k=3,
        filter_type="clinical_guideline",
    )

    assert kb.last_call == {
        "query": "高血压治疗指南",
        "top_k": 3,
        "filter_type": "clinical_guideline",
    }
    assert len(records) == 1

    record = records[0]
    assert record.id == "guideline-hbp#2"
    assert record.title == "高血压"
    assert record.organization == "中华医学会"
    assert record.year == 2024
    assert record.score == 0.8765
    assert record.evidence_type == "clinical_guideline"
    assert "中华医学会" in record.citation
    assert "综合评估" in record.snippet


def test_search_as_dicts_keeps_json_serializable_contract():
    service = EvidenceService(kb=FakeKnowledgeBase())

    items = service.search_as_dicts("高血压", top_k=1)

    assert isinstance(items[0], dict)
    assert items[0]["id"] == "guideline-hbp#2"
    assert items[0]["metadata"]["doc_id"] == "guideline-hbp"


def test_empty_query_returns_no_records_without_touching_kb():
    kb = FakeKnowledgeBase()
    service = EvidenceService(kb=kb)

    assert service.search("   ") == []
    assert kb.last_call is None
