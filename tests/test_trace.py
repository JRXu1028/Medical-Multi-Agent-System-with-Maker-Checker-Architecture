"""v3.5 Agent trace JSONL 测试。

TraceWriter 用于记录 Router、Maker、Checker、SafetyGate 的关键过程字段。
这些测试只验证序列化和读写契约，不依赖真实 LLM 或向量库。
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.trace import AgentTraceRecord, TraceWriter
from tools.specs import EvidenceRecord


def test_trace_writer_roundtrip():
    temp_dir = Path(__file__).parent.parent / "_tmp_test_trace"
    path = temp_dir / f"trace-{uuid.uuid4().hex}.jsonl"
    writer = TraceWriter(path)

    writer.write(
        AgentTraceRecord(
            trace_id="trace-001",
            user_query="布洛芬和华法林能一起吃吗？",
            route={"mode": "maker_checker"},
            loaded_skills=["medication_safety"],
            tool_trace=[{"name": "drug_safety_lookup", "success": True}],
            evidence=[
                EvidenceRecord(
                    id="e1",
                    title="药物相互作用证据",
                    source="local_kb",
                    snippet="需要查证抗凝药与 NSAIDs 的出血风险。",
                    evidence_type="drug_safety",
                )
            ],
            prestop_result={"status": "PASS"},
            checker_verdict={"verdict": "PASS"},
            safety_gate={"approved": True},
            final_action="consult_doctor_if_needed",
        )
    )

    records = writer.read_all()

    assert len(records) == 1
    assert records[0]["trace_id"] == "trace-001"
    assert records[0]["loaded_skills"] == ["medication_safety"]
    assert records[0]["evidence"][0]["evidence_type"] == "drug_safety"


def test_trace_writer_accepts_plain_dict():
    temp_dir = Path(__file__).parent.parent / "_tmp_test_trace"
    path = temp_dir / f"trace-{uuid.uuid4().hex}.jsonl"
    writer = TraceWriter(path)

    writer.write({"trace_id": "dict-trace", "metadata": {"status": "ok"}})
    records = writer.read_all()

    assert records[0]["metadata"]["status"] == "ok"
