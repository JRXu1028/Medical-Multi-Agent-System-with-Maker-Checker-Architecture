"""工具数据结构测试。

验证 v3 ToolResult / EvidenceRecord 的序列化兼容性。
这些结构是 RAG evidence、Maker 后处理、Checker 审查共同依赖的底座。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.specs import EvidenceRecord, ToolResult, ToolSpec


def test_evidence_record_roundtrip_and_brief():
    """EvidenceRecord 应能稳定转 dict 并生成旧版兼容摘要。"""

    record = EvidenceRecord(
        id="doc-1#0",
        title="高血压指南",
        source="local_kb",
        organization="示例机构",
        year="2024",
        snippet="建议结合风险分层进行生活方式干预和药物治疗。",
        score=0.86,
        evidence_type="guideline",
        citation="高血压指南(2024)",
        metadata={"doc_id": "doc-1"},
    )

    restored = EvidenceRecord.from_dict(record.to_dict())

    assert restored == record
    assert "高血压指南" in restored.brief()
    assert "2024" in restored.brief()


def test_tool_result_roundtrip():
    """ToolResult 应保持 data 和 evidence 的结构化信息。"""

    result = ToolResult(
        tool_name="medical_kb_search",
        success=True,
        data={"query": "高血压", "total_found": 1},
        evidence=[
            EvidenceRecord(
                id="doc-1#0",
                title="高血压知识",
                source="local_kb",
                snippet="高血压需要长期管理。",
                score=0.75,
            )
        ],
    )

    restored = ToolResult.from_dict(result.to_dict())

    assert restored.tool_name == "medical_kb_search"
    assert restored.data["total_found"] == 1
    assert restored.evidence[0].title == "高血压知识"


def test_tool_spec_describes_executable_tool_only():
    """ToolSpec 只描述可执行工具，不承担 Skill 文档加载。"""

    spec = ToolSpec(
        name="risk_rule_check",
        description="检查红旗症状和风险等级",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        category="risk",
    )

    assert spec.name == "risk_rule_check"
    assert spec.category == "risk"
