"""Generator 结构化证据提取测试。

验证 Maker 后处理可以从 v3 RAG ToolResult 中提取 EvidenceRecord，
同时保留旧的 ActionSignal.evidence 字符串摘要契约。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.evidence_extractor import extract_evidence_records
from agents.generator import GeneratorAgent
from tools.specs import EvidenceRecord


@pytest.mark.asyncio
async def test_post_process_result_extracts_structured_evidence_records():
    # 使用假 LLM client 正常构造 Generator，避免 __new__ 绕过初始化带来的脆弱性。
    agent = GeneratorAgent(agent_id="generator-test", llm_client=object())
    evidence = EvidenceRecord(
        id="g1",
        title="高血压诊疗指南",
        source="local_guideline",
        snippet="建议结合心血管风险分层制定治疗方案。",
        score=0.95,
        evidence_type="clinical_guideline",
        organization="中华医学会",
        year=2024,
    ).to_dict()

    result = await agent.post_process_result(
        {"answer": "建议参考指南并咨询医生。"},
        "建议参考指南并咨询医生。",
        tool_results=[
            {
                "name": "clinical_guideline",
                "arguments": {"query": "高血压"},
                "result": {
                    "guideline_title": "高血压诊疗指南",
                    "organization": "中华医学会",
                    "year": 2024,
                    "evidence": [evidence],
                },
            }
        ],
    )

    assert result["evidence_records"][0]["id"] == "g1"
    assert result["action_signal"]["evidence_records"][0]["title"] == "高血压诊疗指南"
    assert any("高血压诊疗指南" in item for item in result["action_signal"]["evidence"])
    assert all(isinstance(item, str) for item in result["action_signal"]["evidence"])


def test_extract_evidence_records_deduplicates_nested_tool_result():
    evidence = EvidenceRecord(
        id="e1",
        title="医学知识",
        source="local_kb",
        snippet="同一条证据不应重复进入 evidence_records。",
    ).to_dict()

    records = extract_evidence_records(
        [
            {
                "name": "search_knowledge",
                "result": {
                    "evidence": [evidence],
                    "tool_result": {"evidence": [evidence]},
                },
            }
        ]
    )

    assert len(records) == 1
    assert records[0]["id"] == "e1"
