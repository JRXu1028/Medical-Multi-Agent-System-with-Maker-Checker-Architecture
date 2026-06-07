"""Progressive Skill Index 单元测试。

覆盖 v3.2 的 SKILL.md 文档层：
- 解析 YAML frontmatter
- 渲染紧凑 Skill Index
- 批量加载完整 SKILL.md 上下文

这些测试只使用临时目录，不依赖真实 LLM 或 legacy `.claude/skills`。
"""

import sys
from pathlib import Path
from contextlib import contextmanager
import shutil
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.skill_index import (
    SkillDocLoader,
    dedupe_preserve_order,
    normalize_string_list,
    parse_skill_doc,
    split_frontmatter,
)


@contextmanager
def local_temp_dir():
    """在 repo 内创建临时目录，避免 Windows 系统 Temp 权限问题。"""
    root = Path(__file__).parent.parent / "_tmp_test_skill_index" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def write_skill(root: Path, skill_id: str, body: str = "# Body\nChecklist") -> Path:
    """在临时目录写入一个最小 SKILL.md。"""
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"""---
id: {skill_id}
description: Test skill {skill_id}
when_to_load:
  - when needed
suggested_tools:
  - medical_kb_search
---
{body}
""",
        encoding="utf-8",
    )
    return skill_md


def test_parse_skill_doc_reads_frontmatter_and_body():
    with local_temp_dir() as tmp_path:
        skill_md = write_skill(tmp_path, "symptom_triage", "# Symptom\n- red flags")

        doc = parse_skill_doc(skill_md)

        assert doc is not None
        assert doc.id == "symptom_triage"
        assert doc.description == "Test skill symptom_triage"
        assert doc.when_to_load == ["when needed"]
        assert doc.suggested_tools == ["medical_kb_search"]
        assert "red flags" in doc.body


def test_skill_doc_loader_discovers_and_renders_index():
    with local_temp_dir() as tmp_path:
        write_skill(tmp_path, "symptom_triage")
        write_skill(tmp_path, "medication_safety")

        loader = SkillDocLoader(tmp_path)
        docs = loader.discover()
        index = loader.render_index()

        assert sorted(docs.keys()) == ["medication_safety", "symptom_triage"]
        assert "symptom_triage" in index
        assert "medical_kb_search" in index
        assert "# Body" not in index  # index 只暴露紧凑描述，不暴露完整 Markdown


def test_render_skill_context_loads_requested_skills_once():
    with local_temp_dir() as tmp_path:
        write_skill(tmp_path, "symptom_triage", "# Symptom Triage\n完整方法论")

        loader = SkillDocLoader(tmp_path)
        context, loaded_ids = loader.render_skill_context(
            ["symptom_triage", "missing", "symptom_triage"]
        )

        assert loaded_ids == ["symptom_triage"]
        assert "完整方法论" in context
        assert context.count("## Skill: symptom_triage") == 1
        assert "不是可执行工具" in context


def test_split_frontmatter_handles_missing_frontmatter():
    metadata, body = split_frontmatter("# Plain Markdown")

    assert metadata is None
    assert body == "# Plain Markdown"


def test_normalize_string_list_and_dedupe_helpers():
    assert normalize_string_list("a") == ["a"]
    assert normalize_string_list(["a", 2, ""]) == ["a", "2"]
    assert normalize_string_list(None) == []
    assert dedupe_preserve_order(["a", "b", "a", "", "b"]) == ["a", "b"]


def test_real_skill_docs_are_compact_methodology_docs():
    root = Path(__file__).parent.parent
    loader = SkillDocLoader(root / "skills")

    docs = loader.discover(refresh=True)

    expected = {
        "symptom_triage",
        "emergency_red_flags",
        "mental_health_safety",
        "clarifying_questions",
        "care_navigation",
        "medication_safety",
        "drug_interaction",
        "renal_liver_dose_safety",
        "pregnancy_pediatric_safety",
        "geriatric_safety",
        "lab_report",
        "imaging_report",
        "ecg_vital_signs",
        "guideline_research",
        "evidence_comparison",
        "source_quality_appraisal",
        "health_education",
        "preventive_care",
        "medical_device_explainer",
        "chronic_care",
        "lifestyle_coaching",
        "nutrition_weight_management",
        "rehabilitation_exercise_safety",
        "memory_personalization",
    }
    assert expected.issubset(set(docs.keys()))
    assert len(expected) == 24

    for doc in docs.values():
        assert doc.description
        assert doc.when_to_load
        assert doc.body
        # SKILL.md 只做方法论和建议工具，不承载 PreStopPolicy 硬约束。
        raw = Path(doc.path).read_text(encoding="utf-8")
        assert "required_tools" not in raw
        assert "runtime_constraints" not in raw


def test_real_skill_context_can_batch_load_multiple_docs():
    root = Path(__file__).parent.parent
    loader = SkillDocLoader(root / "skills")

    context, loaded_ids = loader.render_skill_context(
        ["symptom_triage", "guideline_research"]
    )

    assert loaded_ids == ["symptom_triage", "guideline_research"]
    assert "Skill: symptom_triage" in context
    assert "Skill: guideline_research" in context
    assert "不是可执行工具" in context
