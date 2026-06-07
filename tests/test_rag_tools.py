"""RAG 工具层单元测试。

测试 medical_kb_search / guideline_search 的 ToolResult 契约。
这里注入假 EvidenceService，避免单元测试依赖真实 Milvus 或 embedding 模型。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.specs import EvidenceRecord


class FakeEvidenceService:
    """记录调用参数并返回固定证据的测试替身。"""

    def __init__(self):
        self.last_call = None

    def search(self, query, *, top_k=5, filter_type=None, evidence_type=None):
        self.last_call = {
            "query": query,
            "top_k": top_k,
            "filter_type": filter_type,
            "evidence_type": evidence_type,
        }
        return [
            EvidenceRecord(
                id="e1",
                title="高血压",
                source="local_kb",
                snippet="高血压管理需要综合评估。",
                score=0.91,
                evidence_type=evidence_type or "knowledge",
                year=2024,
            )
        ]


class FailingEvidenceService:
    """模拟底层向量库异常的测试替身。"""

    def search(self, query, *, top_k=5, filter_type=None, evidence_type=None):
        raise RuntimeError("vector store unavailable")


@pytest.mark.asyncio
async def test_medical_kb_search_returns_tool_result(monkeypatch):
    import tools.medical_kb_search as module

    fake_service = FakeEvidenceService()
    monkeypatch.setattr(module, "get_evidence_service", lambda: fake_service)

    result = await module.medical_kb_search("高血压怎么管理", max_results=2)

    assert result["tool_name"] == "medical_kb_search"
    assert result["success"] is True
    assert result["data"]["total_found"] == 1
    assert result["evidence"][0]["title"] == "高血压"
    assert fake_service.last_call == {
        "query": "高血压怎么管理",
        "top_k": 2,
        "filter_type": None,
        "evidence_type": "knowledge",
    }


@pytest.mark.asyncio
async def test_medical_kb_search_handles_service_failure(monkeypatch):
    import tools.medical_kb_search as module

    monkeypatch.setattr(module, "get_evidence_service", lambda: FailingEvidenceService())

    result = await module.medical_kb_search("高血压", max_results=2)

    assert result["tool_name"] == "medical_kb_search"
    assert result["success"] is False
    assert result["evidence"] == []
    assert "vector store unavailable" in result["error"]


@pytest.mark.asyncio
async def test_guideline_search_uses_guideline_filter(monkeypatch):
    import tools.guideline_search as module

    fake_service = FakeEvidenceService()
    monkeypatch.setattr(module, "get_evidence_service", lambda: fake_service)

    result = await module.guideline_search("高血压", max_results=1)

    assert result["tool_name"] == "guideline_search"
    assert result["success"] is True
    assert result["evidence"][0]["evidence_type"] == "clinical_guideline"
    assert fake_service.last_call == {
        "query": "高血压 临床指南 诊疗规范",
        "top_k": 1,
        "filter_type": "clinical_guideline",
        "evidence_type": "clinical_guideline",
    }


@pytest.mark.asyncio
async def test_guideline_search_handles_service_failure(monkeypatch):
    import tools.guideline_search as module

    monkeypatch.setattr(module, "get_evidence_service", lambda: FailingEvidenceService())

    result = await module.guideline_search("高血压", max_results=1)

    assert result["tool_name"] == "guideline_search"
    assert result["success"] is False
    assert result["evidence"] == []
    assert "vector store unavailable" in result["error"]


@pytest.mark.asyncio
async def test_drug_safety_lookup_returns_tool_result(monkeypatch):
    import tools.drug_safety_lookup as module

    fake_service = FakeEvidenceService()
    monkeypatch.setattr(module, "get_evidence_service", lambda: fake_service)

    result = await module.drug_safety_lookup("布洛芬 华法林", max_results=2)

    assert result["tool_name"] == "drug_safety_lookup"
    assert result["success"] is True
    assert result["evidence"][0]["evidence_type"] == "drug_safety"
    assert fake_service.last_call == {
        "query": "布洛芬 华法林 药物相互作用 禁忌 特殊人群 漏服 过量",
        "top_k": 2,
        "filter_type": None,
        "evidence_type": "drug_safety",
    }


@pytest.mark.asyncio
async def test_drug_safety_lookup_handles_service_failure(monkeypatch):
    import tools.drug_safety_lookup as module

    monkeypatch.setattr(module, "get_evidence_service", lambda: FailingEvidenceService())

    result = await module.drug_safety_lookup("布洛芬", max_results=2)

    assert result["tool_name"] == "drug_safety_lookup"
    assert result["success"] is False
    assert result["evidence"] == []
    assert "vector store unavailable" in result["error"]


@pytest.mark.asyncio
async def test_lab_reference_lookup_returns_tool_result(monkeypatch):
    import tools.lab_reference_lookup as module

    fake_service = FakeEvidenceService()
    monkeypatch.setattr(module, "get_evidence_service", lambda: fake_service)

    result = await module.lab_reference_lookup("尿酸 520", max_results=3)

    assert result["tool_name"] == "lab_reference_lookup"
    assert result["success"] is True
    assert result["evidence"][0]["evidence_type"] == "lab_reference"
    assert fake_service.last_call == {
        "query": "尿酸 520 化验指标 参考范围 临床意义 复查",
        "top_k": 3,
        "filter_type": None,
        "evidence_type": "lab_reference",
    }


@pytest.mark.asyncio
async def test_lab_reference_lookup_handles_service_failure(monkeypatch):
    import tools.lab_reference_lookup as module

    monkeypatch.setattr(module, "get_evidence_service", lambda: FailingEvidenceService())

    result = await module.lab_reference_lookup("尿酸", max_results=2)

    assert result["tool_name"] == "lab_reference_lookup"
    assert result["success"] is False
    assert result["evidence"] == []
    assert "vector store unavailable" in result["error"]


@pytest.mark.asyncio
async def test_risk_rule_check_returns_structured_risk_result():
    import tools.risk_rule_check as module

    result = await module.risk_rule_check("我胸痛还呼吸困难，现在怎么办？")

    assert result["tool_name"] == "risk_rule_check"
    assert result["success"] is True
    assert result["data"]["risk_level"] == "high"
    assert "emergency_symptoms" in result["data"]["matched_rules"]
    assert result["evidence"] == []


@pytest.mark.asyncio
async def test_imaging_reference_lookup_returns_tool_result(monkeypatch):
    import tools.imaging_reference_lookup as module

    fake_service = FakeEvidenceService()
    monkeypatch.setattr(module, "get_evidence_service", lambda: fake_service)

    result = await module.imaging_reference_lookup("胸部 CT 肺结节", max_results=2)

    assert result["tool_name"] == "imaging_reference_lookup"
    assert result["success"] is True
    assert result["evidence"][0]["evidence_type"] == "imaging_reference"
    assert fake_service.last_call == {
        "query": "胸部 CT 肺结节 影像报告 CT MRI 超声 X线 结节 复查 随访",
        "top_k": 2,
        "filter_type": None,
        "evidence_type": "imaging_reference",
    }


@pytest.mark.asyncio
async def test_vital_sign_reference_lookup_returns_tool_result(monkeypatch):
    import tools.vital_sign_reference_lookup as module

    fake_service = FakeEvidenceService()
    monkeypatch.setattr(module, "get_evidence_service", lambda: fake_service)

    result = await module.vital_sign_reference_lookup("血氧 92 心率快", max_results=2)

    assert result["tool_name"] == "vital_sign_reference_lookup"
    assert result["success"] is True
    assert result["evidence"][0]["evidence_type"] == "vital_sign_reference"
    assert fake_service.last_call == {
        "query": "血氧 92 心率快 血压 血氧 心率 体温 心电图 房颤 ST段 风险边界",
        "top_k": 2,
        "filter_type": None,
        "evidence_type": "vital_sign_reference",
    }


def load_legacy_module(relative_path: str, module_name: str):
    """按文件路径加载 legacy skill wrapper，避免受包名里的连字符影响。"""
    import importlib.util

    module_path = Path(__file__).parent.parent / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_legacy_search_knowledge_wrapper_returns_evidence(monkeypatch):
    module = load_legacy_module(
        ".claude/skills/search-knowledge/script/search.py",
        "legacy_search_knowledge_test",
    )

    async def fake_medical_kb_search(query, max_results=5):
        return {
            "tool_name": "medical_kb_search",
            "success": True,
            "data": {"query": query, "total_found": 1},
            "evidence": [
                {
                    "id": "e1",
                    "title": "高血压",
                    "source": "local_kb",
                    "snippet": "高血压管理需要综合评估。",
                    "score": 0.9,
                    "evidence_type": "knowledge",
                }
            ],
            "error": None,
            "latency_ms": None,
        }

    monkeypatch.setattr(module, "medical_kb_search", fake_medical_kb_search)
    result = await module.search_knowledge("高血压")

    assert result["total_found"] == 1
    assert result["evidence"][0]["title"] == "高血压"
    assert "高血压管理" in result["answer"]


@pytest.mark.asyncio
async def test_legacy_clinical_guideline_wrapper_keeps_old_fields(monkeypatch):
    module = load_legacy_module(
        ".claude/skills/clinical-guideline/script/guideline.py",
        "legacy_clinical_guideline_test",
    )

    async def fake_guideline_search(query, max_results=1):
        return {
            "tool_name": "guideline_search",
            "success": True,
            "data": {"query": query, "total_found": 1},
            "evidence": [
                {
                    "id": "g1",
                    "title": "高血压诊疗指南",
                    "source": "local_guideline",
                    "organization": "中华医学会",
                    "year": 2024,
                    "snippet": "建议结合心血管风险分层制定治疗方案。",
                    "score": 0.95,
                    "evidence_type": "clinical_guideline",
                }
            ],
            "error": None,
            "latency_ms": None,
        }

    monkeypatch.setattr(module, "guideline_search", fake_guideline_search)
    result = await module.clinical_guideline("高血压")

    assert result["guideline_title"] == "高血压诊疗指南"
    assert result["organization"] == "中华医学会"
    assert result["year"] == 2024
    assert result["evidence"][0]["evidence_type"] == "clinical_guideline"
