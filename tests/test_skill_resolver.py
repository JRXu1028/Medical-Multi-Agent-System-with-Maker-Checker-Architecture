"""SkillResolver 单元测试。

覆盖 Phase C 的 Cluster Hybrid Progressive Skill Loading：
- 高风险组合规则能补齐多个关键 Skill
- cluster gating + 轻量检索能保持上下文选择小而相关
- 输出可写入 process_trace
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.skill_index import SkillDocLoader
from core.skill_resolver import SkillResolver


def real_skill_docs():
    """加载真实 skills/ 目录，验证 resolver 与项目 catalog 对齐。"""

    root = Path(__file__).parent.parent
    return SkillDocLoader(root / "skills").discover(refresh=True)


def test_resolver_selects_emergency_skills_for_chest_pain():
    resolver = SkillResolver(max_skills=4)

    result = resolver.resolve(
        user_query="我胸痛还呼吸困难，现在要不要去急诊？",
        skill_docs=real_skill_docs(),
    )

    assert "symptom_triage" in result.selected_skill_ids
    assert "emergency_red_flags" in result.selected_skill_ids
    assert "acute" in result.clusters
    assert len(result.selected_skill_ids) <= 4


def test_resolver_handles_pregnancy_medication_combo():
    resolver = SkillResolver(max_skills=4)

    result = resolver.resolve(
        user_query="孕妇发烧能吃对乙酰氨基酚吗？",
        skill_docs=real_skill_docs(),
    )

    assert "pregnancy_pediatric_safety" in result.selected_skill_ids
    assert "medication_safety" in result.selected_skill_ids
    assert "symptom_triage" in result.selected_skill_ids


def test_resolver_selects_evidence_comparison_for_ct_mri():
    resolver = SkillResolver(max_skills=4)

    result = resolver.resolve(
        user_query="CT 和 MRI 有什么区别？",
        skill_docs=real_skill_docs(),
    )

    assert "evidence_comparison" in result.selected_skill_ids
    assert "imaging_report" in result.selected_skill_ids
    assert len(result.selected_skill_ids) <= 4


def test_resolver_keeps_memory_context_separate():
    resolver = SkillResolver(max_skills=4)

    result = resolver.resolve(
        user_query="我上次说过对青霉素过敏，现在牙疼能吃什么药？",
        skill_docs=real_skill_docs(),
    )

    assert "memory_personalization" in result.selected_skill_ids
    assert "medication_safety" in result.selected_skill_ids
    assert result.to_dict()["resolver_version"] == "cluster_hybrid_v1"
