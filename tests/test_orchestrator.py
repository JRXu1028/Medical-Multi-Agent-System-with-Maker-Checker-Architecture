"""
Orchestrator 单元测试 —— 用 mock Agent 覆盖 5 条路径。

不依赖真实 LLM。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from pipeline.orchestrator import MakerCheckerOrchestrator, Terminal
from pipeline.safety_gate import SafetyGate, GateResult
from pipeline.action_signal import ActionType


# ============================================================================
# Mock Classes — 返回可控的假数据
# ============================================================================

class MockGenerator:
    """返回预置的 action_signal。"""
    def __init__(
        self,
        proposed_action=ActionType.OBSERVE,
        confidence=0.55,
        evidence=None,
        tool_trace=None,
    ):
        self._action = proposed_action
        self._conf  = confidence
        self._ev    = evidence or ["mock_evidence"]
        self._tool_trace = tool_trace or []
        self.regenerate_calls = 0

    async def generate(self, query):
        return {
            "answer": f"mock answer for: {query}",
            "action_signal": {
                "result": "mock conclusion",
                "evidence": self._ev,
                "confidence": self._conf,
                "proposed_action": self._action,
            },
            "skill_trace": [{"skill": "mock_skill", "key_finding": "mock"}],
            "tool_trace": self._tool_trace,
            "evidence_records": [],
        }

    async def regenerate(self, query, challenges):
        self.regenerate_calls += 1
        return await self.generate(query + " (regenerated)")


class RepairingGenerator(MockGenerator):
    """第一次缺少 tool_trace，返修后补上 assess_risk。"""

    async def regenerate(self, query, challenges):
        self.regenerate_calls += 1
        self._tool_trace = [{"name": "assess_risk", "arguments": {}, "success": True}]
        return await self.generate(query + " (prestop repaired)")


class MockReviewer:
    """返回预置的 verdict。"""
    def __init__(self, verdict="PASS", challenges=None):
        self._verdict = verdict
        self._challenges = challenges or []

    async def review(self, gen_output):
        return {
            "verdict": self._verdict,
            "challenges": self._challenges,
            "confidence_adjusted": 0.50,
        }


class PrecheckRejectThenPassReviewer:
    """模拟 Checker precheck 首轮驳回、返修后通过。"""

    def __init__(self):
        self.calls = 0

    async def review(self, gen_output):
        self.calls += 1
        if self.calls == 1:
            return {
                "verdict": "REJECT",
                "reject_type": "NEED_MORE_TOOL_USE",
                "challenges": [{
                    "type": "MISSING_REQUIRED_TOOL",
                    "description": "缺少风险评估工具调用",
                    "suggested_fix": "请补调 assess_risk",
                }],
                "prestop_result": {"status": "REPAIR", "issues": []},
            }
        return {
            "verdict": "PASS",
            "challenges": [],
            "prestop_result": {"status": "PASS", "issues": []},
        }


class AlwaysPrecheckRejectReviewer:
    """模拟 Checker precheck 返修后仍驳回。"""

    async def review(self, gen_output):
        return {
            "verdict": "REJECT",
            "reject_type": "NEED_MORE_TOOL_USE",
            "challenges": [{
                "type": "MISSING_REQUIRED_TOOL",
                "description": "仍缺少风险评估工具调用",
                "suggested_fix": "请补调 assess_risk",
            }],
            "prestop_result": {"status": "REPAIR", "issues": []},
        }


class MockLeadAgent:
    """记录调用并返回固定回答。"""
    def __init__(self):
        self.last_signal = None
        self.last_terminal = None

    async def express(self, user_query, action_signal, terminal="", rounds=None):
        self.last_signal = action_signal
        self.last_terminal = terminal
        return f"[{terminal}] mock final answer"


def _make_gate(**kwargs):
    """创建一个空的、总是 PASS 的 SafetyGate。"""
    return SafetyGate(high_risk_symptoms=frozenset())


def _make_orch(generator, reviewer, gate=None, lead=None):
    return MakerCheckerOrchestrator(
        generator=generator,
        reviewer=reviewer,
        safety_gate=gate or _make_gate(),
        lead_agent=lead or MockLeadAgent(),
        max_retries=1,
    )


# ============================================================================
# 5 条路径测试
# ============================================================================

class TestOrchestratorPaths:

    # 1. PASS → normal .....................................................
    @pytest.mark.asyncio
    async def test_pass_to_normal(self):
        gen  = MockGenerator()
        rev  = MockReviewer(verdict="PASS")
        orch = _make_orch(gen, rev)

        result = await orch.run("test query")
        assert result["terminal"] == Terminal.NORMAL
        assert len(result["rounds"]) == 1
        assert result["rounds"][0]["verdict"] == "PASS"
        assert result["gate_result"]["passed"] is True

    # 2. CHALLENGE → challenged ...........................................
    @pytest.mark.asyncio
    async def test_challenge_to_challenged(self):
        gen  = MockGenerator()
        rev  = MockReviewer(verdict="CHALLENGE", challenges=[
            {"type": "insufficient_evidence", "description": "证据不足", "severity": "medium"}
        ])
        orch = _make_orch(gen, rev)

        result = await orch.run("test")
        assert result["terminal"] == Terminal.CHALLENGED
        # evidence 中应追加 challenge 描述
        signal = result["rounds"][0]["action_signal"]
        assert "证据不足" in str(signal.get("evidence", []))

    # 3. REJECT → regenerate PASS → normal ...............................
    @pytest.mark.asyncio
    async def test_reject_then_pass(self):
        gen  = MockGenerator()
        rev  = MockReviewer()
        # Round 1: REJECT, Round 2: PASS
        rev._verdicts = ["REJECT", "PASS"]
        rev._call_count = 0
        rev._reject_challenges = [{"type": "missed_symptom", "description": "遗漏症状"}]

        async def smart_review(gen_out):
            rev._call_count += 1
            if rev._call_count == 1:
                return {"verdict": "REJECT", "challenges": rev._reject_challenges}
            return {"verdict": "PASS", "challenges": []}

        rev.review = smart_review
        orch = _make_orch(gen, rev)

        result = await orch.run("test")
        assert result["terminal"] == Terminal.NORMAL
        assert len(result["rounds"]) == 2  # Round 1 + Round 2

    # 4. REJECT → REJECT → forced_safe ...................................
    @pytest.mark.asyncio
    async def test_reject_twice_forced_safe(self):
        gen  = MockGenerator()
        rev  = MockReviewer(verdict="REJECT", challenges=[
            {"type": "logic_gap", "description": "逻辑矛盾"}
        ])
        orch = _make_orch(gen, rev)

        result = await orch.run("test")
        assert result["terminal"] == Terminal.FORCED_SAFE
        assert result["gate_result"] is None  # forced_safe 跳过 Gate
        assert result["final_answer"] is not None  # 有兜底回答

    # 5. Gate BLOCK → gate_override .......................................
    @pytest.mark.asyncio
    async def test_gate_override(self):
        gen  = MockGenerator(
            proposed_action=ActionType.OBSERVE,
            tool_trace=[{"name": "assess_risk", "arguments": {}, "success": True}],
        )
        rev  = MockReviewer(verdict="PASS")
        # 创建含高危症状的 Gate，但 query 不含症状则不会触发 → 需要手动构造
        # 直接用真实的 SafetyGate + 高危 query
        gate = SafetyGate()
        lead = MockLeadAgent()
        orch = MakerCheckerOrchestrator(gen, rev, gate, lead, max_retries=1)

        # query 含高危症状 "胸痛" 但 action 是 OBSERVE → Gate BLOCK
        result = await orch.run("我胸痛呼吸困难")
        assert result["terminal"] == Terminal.GATE_OVERRIDE
        assert result["gate_result"]["passed"] is False
        # LeadAgent 收到的 signal 应已被 Gate 覆盖为 urgent_care
        assert lead.last_signal is not None
        assert lead.last_terminal == Terminal.GATE_OVERRIDE

    # 6. Checker precheck REJECT → repaired PASS → normal ..................
    @pytest.mark.asyncio
    async def test_checker_precheck_reject_then_repair_pass(self):
        gen = RepairingGenerator(proposed_action=ActionType.RECOMMEND_URGENT_CARE)
        rev = PrecheckRejectThenPassReviewer()
        orch = _make_orch(gen, rev)

        result = await orch.run("我胸痛呼吸困难")

        assert result["terminal"] == Terminal.NORMAL
        assert gen.regenerate_calls == 1
        assert result["rounds"][0]["verdict"] == "REJECT"
        assert result["rounds"][0]["reject_type"] == "NEED_MORE_TOOL_USE"
        assert result["rounds"][1]["prestop_result"]["status"] == "PASS"

    # 7. Checker precheck REJECT → still missing → forced_safe .............
    @pytest.mark.asyncio
    async def test_checker_precheck_repair_failure_forced_safe(self):
        gen = MockGenerator(proposed_action=ActionType.RECOMMEND_URGENT_CARE)
        rev = AlwaysPrecheckRejectReviewer()
        orch = _make_orch(gen, rev)

        result = await orch.run("我胸痛呼吸困难")

        assert result["terminal"] == Terminal.FORCED_SAFE
        assert gen.regenerate_calls == 1
        assert result["rounds"][0]["verdict"] == "REJECT"
        assert result["rounds"][1]["verdict"] == "REJECT"
        assert result["rounds"][1]["reject_type"] == "NEED_MORE_TOOL_USE"
