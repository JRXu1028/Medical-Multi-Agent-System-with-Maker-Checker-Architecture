"""
Skill Loader & Registry 测试 —— 证明"自研 Skill 系统"的每一层。

覆盖:
  扫描 .claude/skills
  解析 SKILL.md YAML frontmatter
  加载 Python 函数
  转成 OpenAI tools 格式
  执行同步/异步 skill
"""

import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from core.skill_loader import parse_skill_md, load_skill_function, discover_skills
from core.skill_registry import SkillRegistry, SkillParameter


# ============================================================================
# 测试：parse_skill_md — 解析 SKILL.md YAML frontmatter
# ============================================================================

class TestParseSkillMd:
    """解析 SKILL.md 的 YAML frontmatter。"""

    def test_parses_valid_frontmatter(self):
        content = "---\nname: test-skill\ndescription: A test skill\n---\n# Body"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            path = f.name
        try:
            meta = parse_skill_md(Path(path))
            assert meta is not None
            assert meta["name"] == "test-skill"
            assert meta["description"] == "A test skill"
        finally:
            Path(path).unlink()

    def test_returns_none_for_no_frontmatter(self):
        content = "# Just a heading\nNo frontmatter here"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            path = f.name
        try:
            meta = parse_skill_md(Path(path))
            assert meta is None
        finally:
            Path(path).unlink()

    def test_missing_file_returns_none(self):
        assert parse_skill_md(Path("/nonexistent/path.md")) is None


# ============================================================================
# 测试：load_skill_function — 动态加载 Python 函数
# ============================================================================

class TestLoadSkillFunction:
    """从 skills/<name>/script/<name>.py 中加载函数。"""

    def test_loads_real_assess_risk(self):
        root = Path(__file__).parent.parent
        func = load_skill_function(
            "assess-risk", "risk", "assess_risk",
            project_root=root
        )
        assert func is not None
        assert callable(func)
        import inspect
        assert inspect.iscoroutinefunction(func)  # async function


# ============================================================================
# 测试：discover_skills — 扫描目录发现所有 skills
# ============================================================================

class TestDiscoverSkills:
    """扫描 .claude/skills 目录。"""

    def test_discovers_all_skills(self):
        root = Path(__file__).parent.parent
        skills = discover_skills(root)
        assert len(skills) >= 5  # 至少有 5 个 skills
        # 每个 skill 必须有这些键
        for s in skills:
            assert "name" in s
            assert "function_name" in s
            assert "function" in s
            assert "metadata" in s
            assert callable(s["function"])

    def test_finds_assess_risk(self):
        root = Path(__file__).parent.parent
        skills = discover_skills(root)
        names = [s["name"] for s in skills]
        assert "assess-risk" in names

    def test_finds_clinical_guideline(self):
        root = Path(__file__).parent.parent
        skills = discover_skills(root)
        names = [s["name"] for s in skills]
        assert "clinical-guideline" in names


# ============================================================================
# 测试：SkillRegistry — 注册、执行、OpenAI 格式转换
# ============================================================================

class TestSkillRegistry:
    """SkillRegistry: register(), execute(), to_openai_format()。"""

    def test_register_and_get(self):
        reg = SkillRegistry()
        reg.register("test", lambda x: x, "test skill", [])
        assert reg.get("test") is not None
        assert reg.get("nonexistent") is None

    def test_to_openai_format(self):
        reg = SkillRegistry()
        reg.register(
            "diagnose",
            lambda symptoms: f"analysis of {symptoms}",
            "Analyze patient symptoms",
            [
                SkillParameter("symptoms", "string", "Symptom description", required=True),
                SkillParameter("age", "number", "Patient age", required=False),
            ]
        )
        tools = reg.to_openai_format()
        assert len(tools) == 1
        tool = tools[0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "diagnose"
        assert tool["function"]["description"] == "Analyze patient symptoms"
        # 验证参数格式
        params = tool["function"]["parameters"]
        assert params["type"] == "object"
        assert "symptoms" in params["properties"]
        assert params["properties"]["symptoms"]["type"] == "string"
        assert "symptoms" in params["required"]

    def test_execute_sync_skill(self):
        reg = SkillRegistry()
        reg.register(
            "greet",
            lambda greeting_name: f"Hello {greeting_name}",
            "Greet someone",
            [SkillParameter("greeting_name", "string", "Name to greet", required=True)]
        )
        import asyncio
        result = asyncio.run(reg.execute("greet", greeting_name="World"))
        assert "Hello World" in str(result)

    def test_execute_skill_not_found(self):
        reg = SkillRegistry()
        import asyncio
        result = asyncio.run(reg.execute("nonexistent", x=1))
        assert result["success"] is False
        assert "Skill not found" in result["error"]

    def test_registry_empty_initially(self):
        reg = SkillRegistry()
        assert len(reg.get_all()) == 0

    def test_multiple_skills(self):
        reg = SkillRegistry()
        reg.register("s1", lambda: "a", "skill 1", [])
        reg.register("s2", lambda: "b", "skill 2", [])
        assert len(reg.get_all()) == 2
        tools = reg.to_openai_format()
        assert len(tools) == 2

    def test_execute_async_skill(self):
        reg = SkillRegistry()
        async def async_skill(query: str):
            return {"answer": f"Result for {query}"}
        reg.register(
            "search",
            async_skill,
            "Search knowledge base",
            [SkillParameter("query", "string", "Search query", required=True)]
        )
        import asyncio
        result = asyncio.run(reg.execute("search", query="test"))
        assert result["answer"] == "Result for test"
