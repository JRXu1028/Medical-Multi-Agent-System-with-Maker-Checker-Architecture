"""
Maker-Checker 管道单元测试。
运行: python -m pytest tests/ -v
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from pipeline.action_signal import (
    ActionSignal, ActionType, CONFLICT_PAIRS, RISK_TO_ACTION, CONFIDENCE_BASE
)
from pipeline.safety_gate import SafetyGate, GateResult, apply_gate_override


# ============================================================================
# ActionSignal 测试
# ============================================================================

class TestActionSignal:
    def test_roundtrip(self):
        s = ActionSignal(result="test", evidence=["e1"], confidence=0.8, proposed_action=ActionType.OBSERVE)
        d = s.to_dict()
        s2 = ActionSignal.from_dict(d)
        assert s2.result == "test"
        assert s2.evidence == ["e1"]
        assert s2.confidence == 0.8
        assert s2.proposed_action == ActionType.OBSERVE

    def test_from_partial_dict(self):
        s = ActionSignal.from_dict({})
        assert s.result == ""
        assert s.evidence == []
        assert s.confidence == 0.0

    def test_is_valid(self):
        assert ActionSignal(proposed_action=ActionType.OBSERVE).is_valid
        assert not ActionSignal(proposed_action="invalid").is_valid

    def test_merge_evidence_dedup(self):
        s = ActionSignal(evidence=["a"])
        s.merge_evidence(["a", "b", "c", "b"])
        assert s.evidence == ["a", "b", "c"]

    def test_risk_to_action_mapping(self):
        assert RISK_TO_ACTION["high"] == ActionType.RECOMMEND_URGENT_CARE
        assert RISK_TO_ACTION["low"] == ActionType.OBSERVE

    def test_confidence_base_keys(self):
        for key in ["emergency", "high", "guideline_found", "fallback"]:
            assert key in CONFIDENCE_BASE

    def test_conflict_pairs(self):
        p1 = frozenset({ActionType.RECOMMEND_URGENT_CARE, ActionType.RECOMMEND_SELF_CARE})
        assert p1 in CONFLICT_PAIRS


# ============================================================================
# SafetyGate 测试
# ============================================================================

class TestSafetyGate:
    def test_pass_normal_query(self):
        gate = SafetyGate()
        r = gate.check("头痛怎么办", {"proposed_action": ActionType.OBSERVE, "evidence": ["偏头痛"], "confidence": 0.5})
        assert r.passed

    def test_block_high_risk_symptom(self):
        gate = SafetyGate()
        r = gate.check("我胸痛呼吸困难", {"proposed_action": ActionType.OBSERVE, "evidence": [], "confidence": 0.3})
        assert not r.passed
        assert r.gate == SafetyGate.GATE_HIGH_RISK_SYMPTOM

    def test_pass_high_risk_with_urgent_care(self):
        gate = SafetyGate()
        r = gate.check("我胸痛", {"proposed_action": ActionType.RECOMMEND_URGENT_CARE, "evidence": ["胸痛"], "confidence": 0.9})
        assert r.passed

    def test_block_evidence_missing(self):
        gate = SafetyGate()
        r = gate.check("头痛", {"proposed_action": ActionType.OBSERVE, "evidence": [], "confidence": 0.9})
        assert not r.passed
        assert r.gate == SafetyGate.GATE_EVIDENCE_SUFFICIENCY

    def test_pass_low_confidence_no_evidence(self):
        gate = SafetyGate()
        r = gate.check("头痛", {"proposed_action": ActionType.OBSERVE, "evidence": [], "confidence": 0.5})
        assert r.passed  # low confidence + no evidence is OK

    def test_block_missing_action(self):
        gate = SafetyGate()
        r = gate.check("头痛", {"evidence": ["偏头痛"]})
        assert not r.passed
        assert r.gate == SafetyGate.GATE_FORMAT_COMPLIANCE

    def test_apply_gate_override(self):
        sig = {"proposed_action": ActionType.OBSERVE, "confidence": 0.5}
        ov = apply_gate_override(sig)
        assert ov["proposed_action"] == ActionType.RECOMMEND_URGENT_CARE
        assert ov["confidence"] == "overridden"


# ============================================================================
# Router 测试
# ============================================================================

class TestRouter:
    def test_simple_query(self):
        from pipeline.router import route
        d = route("多喝水有什么好处")
        assert d.is_simple
        assert d.mode == "simple"
        assert d.source in ("rule", "rule_degraded")  # 语义可用=rule，不可用=rule_degraded

    def test_safety_redline_high_risk(self):
        from pipeline.router import route
        d = route("我胸痛呼吸困难")
        assert d.is_maker_checker
        assert "安全红线" in d.reason
        assert len(d.triggers) >= 1

    def test_evidence_need_guideline(self):
        from pipeline.router import route
        d = route("高血压有什么标准治疗指南，需要吃什么药")
        assert d.is_maker_checker
        assert "循证需求" in d.reason

    def test_progression_upgrade(self):
        from pipeline.router import route
        d = route("头痛三天了越来越严重")
        assert d.is_maker_checker
        assert "进展性症状" in d.reason

    def test_safety_redline_drug_risk(self):
        from pipeline.router import route
        d = route("这个药能和降压药一起吃吗")
        assert d.is_maker_checker
        assert "安全红线" in d.reason

    def test_safety_redline_pregnant(self):
        from pipeline.router import route
        d = route("孕妇头痛怎么办")
        assert d.is_maker_checker
        assert "安全红线" in d.reason

    @pytest.mark.parametrize(
        "question",
        [
            "老人有冠心病突然心慌大汗",
            "宝宝持续呕吐尿量减少",
            "这个药漏服后能不能加量",
        ],
    )
    def test_safety_redline_expanded_dimensions(self, question):
        from pipeline.router import route
        d = route(question)
        assert d.is_maker_checker
        assert "安全红线" in d.reason

    @pytest.mark.parametrize(
        "question",
        [
            "心电图报告异常需要怎么处理",
            "这个病的循证证据和临床路径是什么",
            "需要手术还是住院治疗",
        ],
    )
    def test_evidence_expanded_dimensions(self, question):
        from pipeline.router import route
        d = route(question)
        assert d.is_maker_checker
        # 可能触发安全红线(检查词+诊疗意图)或循证需求(诊疗判断)
        assert any(tag in d.reason for tag in ("安全红线", "循证需求"))

    def test_semantic_catches_paraphrase(self):
        """语义层应识别不包含关键词的变体表达。"""
        from pipeline.router import route, _semantic_risk_score
        # 先检查模型是否可用
        score = _semantic_risk_score("测试")
        if score is None:
            import pytest
            pytest.skip("BGE model not available for semantic routing")

        # 模型可用 → 验证语义召回
        d = route("胸口像有块石头压住")
        # 不含规则关键词，但语义上接近高危胸痛/胸闷原型
        assert d.is_maker_checker, f"Expected maker_checker, got {d.mode}: {d.reason}"
        assert d.source == "semantic", f"Expected semantic, got {d.source}"

    def test_semantic_simple_stays_simple(self):
        """低风险健康咨询不应被语义层误升级。"""
        from pipeline.router import route, _semantic_risk_score
        score = _semantic_risk_score("测试")
        if score is None:
            import pytest
            pytest.skip("BGE model not available")
        d = route("多喝水有什么好处")
        assert d.is_simple


# ============================================================================
# Terminal 测试
# ============================================================================

class TestTerminal:
    def test_terminal_constants(self):
        from pipeline.terminal import Terminal
        assert Terminal.NORMAL == "normal"
        assert Terminal.CHALLENGED == "challenged"
        assert Terminal.GATE_OVERRIDE == "gate_override"
        assert Terminal.FORCED_SAFE == "forced_safe"
