# Medical Maker-Checker Agent v3 架构方案

面向 Agent 岗位面试的最终方向：不是把项目做成固定医疗工作流，而是做成一个保留 Agent 自主性、同时具备证据链、运行时约束、独立审查和评估体系的医疗 Maker-Checker Agent。

---

## 0. 最终结论

最终主链路应该保持简洁：

```text
User Query
  ↓
Router
  - 只输出 simple / maker_checker
  ↓
Maker Agent
  - progressive skill loading
  - ReAct-like tool calling
  - structured tool results
  - RAG evidence synthesis
  ↓
Checker Agent
  - deterministic precheck: PreStopPolicy
    - required-tool check
    - evidence-required check
    - 不依赖 Maker 自报
  - LLM adversarial audit
    - tool path audit
    - evidence audit
    - medical safety audit
  ↓
SafetyGate
  - deterministic final guard
  ↓
LeadAgent
  - expression polishing only
```

这版架构的关键取舍是：

```text
Skills 负责渐进式披露和方法论提醒。
Checker 负责两阶段审查：PreStopPolicy 做确定性预检，LLM Checker 做语义审计。
```

也就是说：

```text
Maker 可以自己选择加载哪些 SKILL.md；
但 Checker 内部的 PreStopPolicy 不相信 Maker 选了什么 Skill。
```

这里的“选择加载”不是通过一个普通 `load_skill` tool 完成，而是 AgentLoop 内部的上下文加载步骤。这样既保留了 Claude Skills 风格的 progressive disclosure，又避免把医疗安全建立在 LLM 自报之上，也避免把 Skill 文档加载误记为医学工具调用。

---

## 1. 为什么不能做成医疗工作流

这个项目服务的是 Agent 岗位面试，不应该展示成：

```text
用户问题 -> 分类 -> 固定调用 A/B/C -> 模板回答
```

那更像 workflow、RAG QA 或规则引擎，不像 Agent 项目。

医疗健康问题天然开放，用户可能问：

| 类型 | 示例 | 需要能力 |
|---|---|---|
| 健康科普 | 多喝水有什么好处？CT 和 MRI 区别？ | health education |
| 身体不适 | 胸痛喘不上气怎么办？跑步后膝盖疼怎么办？ | symptom triage |
| 用药安全 | 布洛芬和某药能一起吃吗？漏服怎么办？ | medication safety |
| 检查报告 | 尿酸 520 严重吗？白细胞偏高怎么办？ | lab report interpretation |
| 生活方式 | 高血压能喝咖啡吗？熬夜后怎么调整？ | lifestyle coaching |
| 慢病管理 | 糖尿病日常饮食怎么安排？ | chronic care |
| 循证研究 | 某病最新指南怎么说？ | evidence research |
| 心理安全 | 我不想活了怎么办？ | mental health safety |
| 行政流程 | 挂什么科？医保怎么报销？ | admin / routing |

固定工作流会很快变窄。正确方向是：

```text
让 Maker 自主判断要做什么；
让运行时约束 Maker 不能漏掉必须做的安全动作。
```

这就是 bounded agency：有边界的自主 Agent。

---

## 2. 当前系统的真实问题

### 2.1 Router 不是主要问题

当前 Router 只输出：

```python
RouteDecision:
    mode: simple | maker_checker
    reason: str
    triggers: list[str]
    source: rule | semantic | llm
    degraded: bool
```

这个边界是对的。Router 不应该输出 intent、skills、tools、required capabilities、risk_level 或 confidence。

Router 的职责只是监督等级选择：

```text
simple:
  低风险、明确科普、非个人医疗决策

maker_checker:
  高风险、个人医疗意图、用药、报告、治疗决策、不确定问题
```

如果 Router 决定具体 skill/tool，Maker 会退化成执行器，项目会更像 workflow。

### 2.2 当前 Skills 实际上是 Tools

现在 `.claude/skills/` 里的内容本质是 function tools：

```text
assess-risk            -> 风险评估函数
analyze-symptoms       -> 症状分析函数
search-knowledge       -> KB 检索函数
clinical-guideline     -> 指南检索函数
recommend-lifestyle    -> 生活方式建议函数
deep-research          -> 深度搜索函数
disease-code           -> ICD 查询函数
search-history         -> 记忆检索函数
search-similar-cases   -> 相似病例检索函数
```

主要问题：

- 一个函数里同时做规则、RAG、文本格式化
- 返回大段 `answer` 文本，下游很难审计
- LLM 没调关键函数时，系统没有阻止机制
- Reviewer 主要看最终答案，没有审查 tool path
- RAG 结果没有稳定 metadata，无法做 citation、freshness、retrieval eval

### 2.3 当前 AgentLoop 是裸 ReAct-like loop

当前 `core/agent_loop.py` 的核心流程是：

```text
LLM -> tool calls -> execute tools -> append observations -> LLM -> final
```

ReAct-like loop 适合医疗开放问题，因为模型可以根据上一步工具结果决定下一步要不要继续查证。问题不是用了 ReAct，而是只有 ReAct，没有硬约束。

比如症状问题如果没有调用风险评估工具，系统仍然可能生成最终答案。v3 要解决的就是这个漏洞。

### 2.4 当前 RAG 不够像简历亮点

当前 RAG 更多是“搜索知识库并拼接文本”。面试里这不够强。

RAG 应该升级为：

```text
retrieval -> evidence records -> answer grounding -> checker audit -> eval metrics
```

这会比“我接了 Milvus”更能体现 Agent/RAG 工程深度。

---

## 3. 最终架构

```text
User Query
    |
    v
Router
    - simple / maker_checker only
    |
    v
Maker Agent
    - receives user_query + route_decision
    - reads Skill Index first
    - AgentLoop injects selected SKILL.md
    - performs ReAct-like tool calling
    - collects structured ToolResult + RAG evidence
    - produces draft_answer + action_signal + trace
    |
    v
Checker Agent
    - deterministic precheck: PreStopPolicy
      - 输入: user_query, route_decision.triggers, tool_trace, evidence, action_signal
      - 检查 required tools 和 evidence 充分性
      - 不通过: 返回 REJECT / NEED_MORE_TOOL_USE，不调用 LLM
    - LLM adversarial review
      - independent process-aware audit
      - evidence audit
      - medical safety audit
    |
    v
SafetyGate  (输出警察)
    - deterministic output guard
    - 只检查"说出口的话是否安全"
    - 不通过: OVERRIDE 硬覆盖
    |
    v
LeadAgent
    - expression only
    |
    v
Final Answer
```

注意：这里没有单独的 `Skill Resolver` 或 `QuerySignalExtractor` pipeline 节点。Skill 加载是 Maker 内部的 agentic 行为；安全约束由 Checker 内部的 PreStopPolicy 独立执行。PreStopPolicy 是独立代码模块，但不是独立 pipeline 节点。

---

## 4. 术语边界

### 4.1 Skills

Skills 是给 Maker/Checker 看的领域方法论，不是可执行函数，也不是安全硬约束唯一来源。

推荐形态：

```text
skills/
  symptom_triage/SKILL.md
  medication_safety/SKILL.md
  lab_report/SKILL.md
  health_education/SKILL.md
  lifestyle_chronic_care/SKILL.md
  evidence_research/SKILL.md
```

`SKILL.md` 使用 Markdown，因为 Markdown 最适合 progressive disclosure：

```markdown
---
id: symptom_triage
description: 用户描述身体不适、症状、是否严重、是否需要就医时使用
when_to_load:
  - 用户描述个人症状
  - 用户询问是否严重
  - 用户询问是否需要就医
suggested_tools:
  - risk_rule_check
  - symptom_pattern_match
  - medical_kb_search
  - guideline_search
  - ask_followup
---

# Symptom Triage

## When To Use

用户描述个人身体不适、症状、是否严重、是否需要就医。

## Checklist

- 先识别红旗症状
- 关注持续时间、严重程度、进展性
- 关注特殊人群
- 信息不足时追问，高风险时不要等待完整信息

## Red Lines

- 不做确定诊断
- 不给处方剂量
- 不忽略红旗症状
```

Frontmatter 只做 Skill Index 和工具提示，不作为 PreStopPolicy 的唯一硬约束来源。硬约束放在 Checker 内部持有的独立 policy 中。

### 4.2 Tools

Tools 是可执行函数/API。它们应该原子化、结构化、可审计：

```python
ToolResult:
    tool_name: str
    success: bool
    data: dict
    evidence: list[dict]
    error: str | None
    latency_ms: int
```

Tool 不直接写最终用户答案。Tool 返回事实、规则结果、检索证据、计算结果。

`load_skill` 不属于这里的 Tools。它不是医学工具，不返回医学事实，不进入 tool_trace，也不作为 evidence。Skill 文档加载是 AgentLoop 内部的上下文管理能力。

### 4.3 RAG Evidence

RAG 不返回自然语言答案，而是返回 evidence records：

```python
evidence = {
    "id": "...",
    "title": "...",
    "source": "...",
    "organization": "...",
    "year": 2024,
    "snippet": "...",
    "score": 0.82,
    "evidence_type": "guideline",
    "citation": "..."
}
```

第一版只保留能自动填充、可验证的字段。不要第一版就加 `coverage`、`conflicts`、`missing_evidence` 这类需要医学判断才能可靠填充的字段。

### 4.4 Checker Precheck / PreStopPolicy（Checker 内部确定性预检）

PreStopPolicy 是 Checker 内部的代码层硬约束，不是 prompt，也不是 LLM reviewer。它回答的是 Checker 审查前最便宜、最确定的问题：这个 draft 有没有明显的过程缺口？

它只审 Maker 的**过程**——"你查够了吗？"——不审结论本身的内容安全性：

```text
- required tools 是否被调用（症状类 → risk_rule_check，用药类 → drug_safety_lookup 等）
- Maker 是否声称高置信但没有收集到任何 evidence
- action_signal 是否存在
```

不通过时：Checker 直接返回 **REJECT / NEED_MORE_TOOL_USE**（退回 Maker 补调工具，最多一次），且这一轮不调用 LLM Checker。返修后 Reviewer.review() 会重新从 PreStopPolicy 开始检查；仍不满足时，由 Orchestrator 走 **FORCED_SAFE**。

PreStopPolicy 可以使用 `user_query`、`route_decision.triggers`、`tool_trace`、`evidence`、`action_signal`，但不使用 Maker 自报的 `selected_skills` 作为硬约束来源。

工程边界：

```text
core/prestop_policy.py
  只保存规则和纯函数检查逻辑，方便单元测试

agents/reviewer.py
  持有 PreStopPolicy
  在 review() 的第一阶段调用
  预检失败时直接返回结构化 REJECT

pipeline/orchestrator.py
  不理解 PreStop 规则
  只根据 Checker verdict 决定是否让 Maker 返修
```

### 4.5 SafetyGate（输出警察）

SafetyGate 是确定性代码，**只审最终结论**——"你说出口的话安全吗？"——不审过程：

```text
- query 含高危症状但 proposed_action 不是 urgent_care
- action_signal 缺失（Checker precheck 已返修一次还缺 → 直接覆盖）
- Checker 标记了 SAFETY_RISK 或 OUTPUT_BOUNDARY
```

不通过时：**OVERRIDE**（硬改 proposed_action 为 urgent_care，不修、不退回）。

两者不交叉检查同一件事。`evidence 为空 + 高置信` 只在 Checker precheck 处理（过程问题，可修），SafetyGate 不重复。

---

## 5. AgentLoop 设计

### 5.1 保留 ReAct-like loop

第一版不强行上完整 PAOR：

```text
Plan -> Act -> Observe -> Reflect
```

医疗问题需要根据工具结果逐步决策。比如用户说“肚子疼、呕吐、头晕”，Maker 可能先做风险规则检查，再根据风险结果决定是否需要指南、追问或直接升级就医建议。

推荐 loop：

```text
Maker sees user_query + Skill Index
-> AgentLoop runs SkillSelectionPass
-> AgentLoop injects selected SKILL.md
-> LLM decides tool call
-> execute tool
-> observe structured ToolResult
-> LLM decides next tool or final
-> Maker draft/action_signal/evidence
-> Checker.review()
   -> PreStopPolicy.before_review checks process completeness
   -> if PASS: LLM Checker reviews semantics/evidence/safety
```

### 5.2 Progressive Skill Loading

Maker 第一轮只看到 Skill Index：

```text
symptom_triage:
  description: 症状、身体不适、是否就医

medication_safety:
  description: 用药、相互作用、漏服、副作用

lab_report:
  description: 检查报告、化验单、指标异常
```

如果 Maker 判断需要某些 Skills，它不是调用普通工具，而是在第一轮结构化输出中声明：

```json
{
  "requested_skills": ["symptom_triage", "medication_safety"],
  "reason": "用户同时询问胸痛和用药相互作用，需要症状分诊和用药安全方法论"
}
```

AgentLoop 读取 `requested_skills`，再把对应完整 `SKILL.md` 批量注入上下文。

这一步是 Agent 自主行为，不是 Router 决策，也不是 workflow 固定步骤。

第一版建议使用“首轮批量加载 + 中途可补”的策略：

```text
1. Maker 第一轮读取 user_query + Skill Index
2. Maker 一次性声明需要加载 0 个或多个 Skills
3. 系统批量注入这些 SKILL.md
4. Maker 进入正常 tool-calling loop
5. 如果中途发现明显缺少方法论，再允许一次 supplemental skill selection
```

这样能保留 progressive disclosure，又避免每加载一个 Skill 都多一次 LLM round-trip。

### 5.3 Skill Loading 是 AgentLoop 内部机制

`load_skill` 不应该作为 LLM 可见的普通工具出现。原因：

```text
- 它不是医学工具，不返回医学事实
- 它不应该进入 tool_trace
- 它不应该计入 max_tool_calls
- 它不应该被 Checker 当作证据
- 它不应该影响 PreStopPolicy 的 required-tool 判断
```

因此第一版不要在 `ToolSpec` 中加入 `tool_type: data | context`。更清晰的实现是：

```python
SkillSelectionResult:
    requested_skills: list[str]
    reason: str

AgentLoop:
    load_skill_context(skill_ids: list[str]) -> list[SkillDoc]
```

含义：

```text
普通 Tool:
  risk_rule_check
  medical_kb_search
  drug_safety_lookup
  返回 ToolResult，作为 observation 进入对话

Skill loading:
  读取 SKILL.md
  由 AgentLoop 注入 system/context
  只记录 loaded_skills，不记录为 tool_call
```

这点实现上很重要：Skill loading 只是让 Maker 获得更多方法论上下文，不是 tool execution。

### 5.4 PreStopPolicy 的落点

统一叫 `PreStopPolicy`，但第一版不把它做成独立 pipeline 节点，也不把它暴露成普通 tool。它运行在 `Reviewer.review()` 内部，是 Checker 的第一阶段：

```text
Maker draft/action_signal/evidence 生成后
-> Reviewer.review()
   -> PreStopPolicy.before_review()
      - required-tool 检查
      - action_signal/proposed_action 检查
      - evidence 为空 + 高置信检查
   -> 预检失败: 直接返回 REJECT / NEED_MORE_TOOL_USE，不调用 LLM
   -> 预检通过: 调用 LLM Checker 做语义审计
```

第一版保留 `before_final()` 作为纯规则 API 和未来 AgentLoop interrupt 的预留点，但暂不在 AgentLoop 内部拦截 final。原因是当前最小可落地实现应该先保证 Reviewer 内部预检闭环，而不是过早改造 AgentLoop 的 stop hook。

Maker draft 生成后，Reviewer 先执行 deterministic precheck：

```python
precheck = prestop_policy.before_review(
    user_query=user_query,
    route_decision=route_decision,
    tool_trace=tool_trace,
    evidence=evidence,
    action_signal=action_signal,
    draft_answer=draft_answer,
)
if not precheck.passed:
    return {
        "verdict": "REJECT",
        "reject_type": "NEED_MORE_TOOL_USE",
        "prestop_result": precheck.to_dict(),
        "challenges": prestop_challenges(precheck),
    }
```

每次 Maker 返修后，`Reviewer.review()` 会重新跑同一个 precheck。第二次仍不满足，就 forced safe：
```text
目前信息不足，无法给出具体医学判断；如存在胸痛、呼吸困难、意识改变等高危症状，请及时线下就医或急诊。
```

这就是 v3 的核心技术点：
```text
不是 prompt 建议模型调用工具；
而是 Checker 在调用 LLM 前用 runtime policy 保证关键工具和证据契约不能被跳过。
```
---

## 6. Skills 设计

第一阶段做 6 个 compact Skills：

| Skill | 适用场景 | 说明 |
|---|---|---|
| health_education | 医学科普、健康知识、检查原理 | 低风险科普表达 |
| symptom_triage | 身体不适、症状、是否就医 | 强调红旗症状和就医边界 |
| medication_safety | 相互作用、漏服、副作用、禁忌 | 强调用药安全边界 |
| lab_report | 化验单、体检指标、影像报告 | 强调参考范围和上下文不足 |
| lifestyle_chronic_care | 饮食、运动、睡眠、慢病日常管理 | 强调生活方式不是治疗替代 |
| evidence_research | 指南、专家共识、研究证据 | 强调证据来源和时效性 |

第二阶段再补：

| Skill | 说明 |
|---|---|
| mental_health_safety | 自杀、自伤、严重心理危机 |
| admin_routing | 挂号、科室、医保等非诊疗问题 |
| checker_adversarial | Checker 专用审查 checklist |

Skills 的作用：

```text
降低 Maker 思考遗忘率；
提供领域 checklist；
提供 red lines；
提供常用 tool hints；
支持 progressive disclosure。
```

Skills 不负责：

```text
执行代码；
替 Router 分流；
作为 Checker precheck 的唯一硬约束来源。
```

### 6.1 SkillLoader 改造边界

当前 `core/skill_loader.py` 实际加载的是 `.claude/skills/*/script/*.py` 里的可执行函数。它是 legacy function-tool loader，不是真正的 Skill 文档加载器。

v3 不建议把两种职责继续塞进同一个 loader。应该拆成：

```text
core/skill_index.py:
  加载 skills/*/SKILL.md
  解析 frontmatter
  构建 Skill Index
  按 skill_id 返回 Markdown body

core/skill_loader.py:
  暂时保留为 legacy loader
  只负责旧 .claude/skills function tools
  后续随 tools/ 迁移逐步废弃
```

这样可以保证：

```text
SkillDocLoader 只处理方法论文档；
ToolRegistry 只处理可执行工具；
AgentLoop 负责把选中的 SkillDoc 注入上下文。
```

不要让 `SkillLoader` 同时做 Markdown 方法论加载和 Python function tool 注册，否则 v3 会重新退回 skills/tools 混乱。

---

## 7. Tools 设计与目录迁移

### 7.1 推荐 Tools

第一阶段：

| Tool | 来源 | 目标 |
|---|---|---|
| risk_rule_check | 从 `assess-risk` 拆出 | 只做红旗/风险规则，不做 RAG 和答案生成 |
| symptom_pattern_match | 从 `analyze-symptoms` 拆出 | 只做症状模式识别 |
| medical_kb_search | 从 `search-knowledge` 改造 | 返回 evidence records |
| guideline_search | 从 `clinical-guideline` 改造 | 返回指南/共识 evidence |
| lab_reference_lookup | 新增 | 常见指标解释和参考范围 |
| drug_safety_lookup | 新增 | 药物相互作用、禁忌、特殊人群 |
| calculator | 新增 | BMI、单位换算、基础计算 |
| ask_followup | 新增 | 生成澄清问题，不是最终回答 |

第二阶段：

| Tool | 目标 |
|---|---|
| web_research_search | 医学 Web 检索 |
| evidence_rerank | 对 evidence records 重排 |
| icd10_lookup | ICD-10 查询 |
| memory_context_lookup | 只返回上下文，不作为医学证据 |

### 7.2 Tools 为什么要搬目录

最终应该搬。因为 `.claude/skills/*/script/*.py` 看起来是 Skills，实际上是 Tools。

对面试项目来说，目录结构本身就是架构表达：

```text
skills/      -> SKILL.md，方法论和渐进式披露
tools/       -> 可执行函数/API
knowledge/   -> RAG、Milvus、证据归一化
core/        -> agent loop、tool registry、PreStopPolicy、trace
agents/      -> maker、checker、lead
pipeline/    -> router、orchestrator、safety gate
```

### 7.3 为什么不要立刻硬搬全部文件

不建议一开始直接把 `.claude/skills` 全删掉：

- 当前 `SkillLoader` 和测试可能依赖 `.claude/skills` 的扫描路径
- 一次性移动文件会制造大量 import/path 变化
- v3 第一优先级是结构化 ToolResult、RAG evidence、PreStopPolicy、Checker audit
- 先做兼容层，可以让新旧系统并行验证

推荐迁移方式：

```text
Step 1:
  新建 maker-checker/tools/
  定义 ToolSpec、ToolResult、ToolRegistry
  旧 .claude/skills 继续作为 legacy

Step 2:
  从旧 script 里抽逻辑到 tools/
  旧 script 改成 thin wrapper，调用新 tools/

Step 3:
  AgentLoop 改为只读 ToolRegistry
  Skills 改为真正的 SKILL.md 方法论文档

Step 4:
  删除或归档 .claude/skills legacy tools
```

---

## 8. RAG v3

RAG 是这个项目必须重点改的部分，也是简历里最值得写的部分。

### 8.1 RAG 目标

从：

```python
{
    "answer": "格式化文本...",
    "total_found": 3
}
```

变成：

```python
{
    "query": "...",
    "evidence": [
        {
            "id": "guideline_hypertension_2024_001",
            "title": "2024 Hypertension Guideline",
            "source": "local_kb",
            "organization": "example_org",
            "year": 2024,
            "snippet": "...",
            "score": 0.82,
            "evidence_type": "guideline",
            "citation": "..."
        }
    ]
}
```

只做能可靠自动填充的字段。暂时不做：

```text
coverage
conflicts
missing_evidence
```

这些可以在第二阶段由 Checker 作为审查判断输出，而不是由检索器假装知道。

### 8.2 RAG 服务边界

建议在 `knowledge/` 下新增 evidence service：

```text
knowledge/
  milvus_kb.py
  evidence_service.py
```

职责：

- query normalization
- Milvus semantic search
- metadata filter
- score threshold
- evidence record normalization
- source/year/type/citation extraction

第二阶段再加：

- BM25 + dense hybrid retrieval
- reranker
- web research evidence
- claim-evidence alignment
- stale evidence warning

### 8.3 RAG 与 Maker/Checker 的关系

Maker 使用 evidence 写答案：

```text
关键医学 claim 应来自 evidence 或 risk rule。
没有 evidence 时，只能输出低置信、科普或追问。
```

Checker 审查 evidence：

```text
- evidence 是否存在
- evidence 是否支持关键 claim
- evidence 是否过旧
- evidence 是否来自 memory_context
- confidence 是否和 evidence 匹配
```

Memory 永远不能当医学证据：

```text
MemoryContext != Medical Evidence
```

---

## 9. Checker Precheck / PreStopPolicy

PreStopPolicy 是 Checker 的第一阶段，不是独立 Agent，也不是和 Checker 平级的 pipeline 节点。它解决的问题是：

```text
Maker 没调必须工具就想 final。
或者 Maker 声称高置信但根本没收集 evidence。
```

Checker 被设计成 two-stage auditor：

```text
Stage 1: deterministic precheck
  组件: PreStopPolicy
  成本: 0 token
  职责: 拦截漏调 required tools、action_signal 缺失、高置信无证据等确定性过程缺口

Stage 2: LLM adversarial review
  组件: Reviewer/Checker LLM
  成本: 需要 LLM 调用
  职责: 审查 evidence 是否支撑 claim、工具参数是否合理、是否有医疗安全语义问题
```

PreStopPolicy 只审过程，不审结论内容。结论内容的安全性由 SafetyGate 负责：

```text
PreStopPolicy → evidence 为空 + 高置信 → Checker 直接 REJECT（过程问题，可返修）
SafetyGate    → 高危症状 + action 不匹配   → OVERRIDE（输出问题，直接改）
```

它不是 Router，也不是 Skill Resolver；它是 Checker 内部的 deterministic precheck。

```text
Router:
  判断监督等级 simple / maker_checker

Maker:
  自主加载 Skills、自主调用 tools

Checker:
  PreStopPolicy 先做零 token 过程预检
  LLM Checker 再做语义审计

SafetyGate:
  只审最终输出安全
```

### 9.1 输入

```python
PreStopInput:
    user_query: str
    route_decision: RouteDecision | None
    tool_trace: list[ToolResult]
    evidence: list[dict]
    action_signal: ActionSignal | None
    draft_answer: str | None
```

可以使用 `route_decision.triggers` 作为辅助信号，但不依赖 Maker 的 `selected_skills`。

### 9.2 检查点

第一版实际使用 `before_review()`：

```python
PreStopPolicy.before_review(
    user_query,
    route_decision,
    tool_trace,
    evidence,
    action_signal,
    draft_answer,
) -> PreStopResult
```

`before_review()` 内部会复用 `before_final()` 的 required-tool 检查，因此外部调用方不需要先跑一遍 `before_final()`。

职责边界：

| Phase | 时机 | 可用数据 | 检查内容 |
|---|---|---|---|
| before_final | 未来 AgentLoop stop hook 预留 | user_query, route_decision, tool_trace | required tools 是否漏调 |
| before_review | Reviewer.review() 内部，LLM Checker 调用前 | draft_answer, evidence, action_signal, tool_trace | required tools、evidence 充分性（为空+高置信 → REJECT）、action_signal 存在性 |

注意：`before_review` 中 evidence 为空+高置信的检查只在 Checker precheck 阶段处理（过程问题，可修）。SafetyGate 不重复此检查。

### 9.3 规则示例

```python
PreStopRule:
    name: "symptom_requires_risk_check"
    patterns: ["胸痛", "呼吸困难", "昏厥", "剧烈头痛", "单侧无力"]
    required_tools: ["risk_rule_check"]
    repair_instruction: "必须先做风险评估"

PreStopRule:
    name: "medication_requires_drug_safety"
    patterns: ["能一起吃吗", "相互作用", "漏服", "副作用", "禁忌"]
    required_tools: ["drug_safety_lookup"]
    repair_instruction: "必须先查证药物安全信息"

PreStopRule:
    name: "lab_report_requires_reference_lookup"
    patterns: ["化验单", "报告", "尿酸", "白细胞", "肌酐", "血糖"]
    required_tools: ["lab_reference_lookup"]
    repair_instruction: "必须先查证指标参考含义"
```

第一版只做高精度规则，不追求覆盖所有医疗意图。宁可先保证关键风险场景不漏。

### 9.4 行为

```text
PASS:
  继续调用 LLM Checker

REJECT / NEED_MORE_TOOL_USE:
  Checker 不调用 LLM，直接把 PreStopIssue 转成 challenges 退回 Maker

FORCED_SAFE:
  不是 PreStopPolicy 自己执行；由 Orchestrator 在 Checker 连续 REJECT 超过上限后触发
```

### 9.5 下一步改进: Signal Catalog

第一版 PreStopPolicy 可以直接维护少量高精度规则。当前规模下这更简单，也更容易落地。

但需要认识到一个后续风险：同一个医学信号可能会出现在多个地方。

例如“胸痛/呼吸困难是高危症状”：

```text
Router:
  用它判断是否进入 maker_checker

SKILL.md:
  用它提醒 Maker 先识别红旗症状

PreStopPolicy:
  用它检查是否必须调用 risk_rule_check
```

在 6 个 Skills、少量 PreStop rules 的第一版里，这种重复可以接受。它让 Skills 和 PreStopPolicy 保持解耦，安全硬约束不依赖 Maker 加载了哪个 Skill。

当规则数量扩大到 20+、Skills 数量扩大到 20+ 时，可以引入 Signal Catalog：

```text
Signal Catalog = 一份共享的医学信号定义表
```

它统一定义：

```yaml
acute_symptom_signals:
  examples:
    - 胸痛
    - 呼吸困难
    - 昏厥
    - 单侧无力
  route_effect: maker_checker
  prestop_required_tools:
    - risk_rule_check
  related_skills:
    - symptom_triage

medication_safety_signals:
  examples:
    - 能一起吃吗
    - 相互作用
    - 漏服
    - 副作用
  route_effect: maker_checker
  prestop_required_tools:
    - drug_safety_lookup
  related_skills:
    - medication_safety
```

这样 Router、PreStopPolicy、Skill Index 都可以引用同一份 signal 定义，避免三处重复维护。

但 Signal Catalog 不应该第一版就做成独立 pipeline 节点。它只是共享配置/规则源：

```text
当前版本:
  Router rules + PreStopPolicy rules + SKILL.md 分离维护

后续版本:
  Router / PreStopPolicy / Skill Index 共同读取 Signal Catalog
```

面试表达：

> 第一版我故意没有引入 Signal Catalog，因为规则规模还小，过早抽象会让架构变重。但我在设计上预留了它：当规则和 Skills 扩大后，可以把高危症状、用药风险、报告指标等信号统一到 Signal Catalog，由 Router、PreStopPolicy 和 Skill Index 共同引用，解决领域信号重复维护问题。
---

## 10. Checker Agent

Checker 不应该只是“再看一遍答案”。它应该审计 Maker 的过程。

输入：

```python
CheckerInput:
    user_query
    route_decision
    maker_plan
    loaded_skills
    tool_trace
    evidence
    prestop_result
    draft_answer
    action_signal
```

输出：

```python
CheckerResult:
    verdict: PASS | CHALLENGE | REJECT
    issues: list[dict]
    required_repairs: list[str]
    safety_notes: list[str]
```

建议 issue type 收敛为：

```text
TOOL_GAP
EVIDENCE_GAP
SAFETY_RISK
CONTEXT_GAP
OUTPUT_BOUNDARY
```

不要第一版就让 LLM 区分过细的 `insufficient_evidence`、`unsupported_claim`、`stale_evidence`。这些可以作为 issue metadata：

```json
{
  "type": "EVIDENCE_GAP",
  "subtype": "stale_evidence",
  "severity": "medium",
  "message": "引用证据年份较旧，建议降低置信度。"
}
```

Checker 重点审四件事：

1. Tool path 是否合理  
   是否漏掉明显必要工具？工具参数是否合理？

2. Evidence 是否足够  
   关键结论有没有 evidence 支持？是否把低相关结果说成确定结论？

3. Medical safety 是否越界  
   是否漏掉红旗症状？是否给了诊断/处方级建议？

4. Missing context 是否处理  
   信息不足时是追问、降级，还是强行回答？

### 10.1 Checker REJECT 后必须重新经过 Checker precheck

Orchestrator 返修链路必须明确：

```text
Maker draft
  -> Checker.review()
     -> PreStopPolicy.before_review
     -> LLM Checker（如果 precheck 通过）
  -> if REJECT: Maker repair
  -> Checker.review() again
     -> PreStopPolicy.before_review again
     -> LLM Checker / SafetyGate
```

原因：

```text
Checker REJECT 后，Maker 可能补调工具、修改 action_signal、增加 evidence 或改变回答边界。
这些变化都会影响 PreStopPolicy 的判断。
```

PreStopPolicy 是轻量规则检查，没有 LLM 成本，所以每次 `Reviewer.review()` 都应该先重新执行 `before_review`。Orchestrator 不直接调用 PreStopPolicy，也不理解它的规则；它只根据 Checker 返回的 verdict 决定是否让 Maker 返修或进入 forced_safe。

---

## 11. SafetyGate（输出警察）

SafetyGate 保持确定性代码。它不是第三个 LLM Reviewer，也不重复 Checker precheck 的过程检查。

Checker precheck 已经保证了 process 合规（工具调了、证据有了）。SafetyGate 只审一件事：**最终 output 的内容是否安全**。

职责：

- 高危症状但 proposed_action 不是 urgent_care → OVERRIDE
- action_signal 缺失（Checker precheck 修过一次还缺）→ OVERRIDE
- Checker 标记 SAFETY_RISK 或 OUTPUT_BOUNDARY → OVERRIDE
- 最终输出必须包含边界说明和就医建议

不再做的事：

- ~~高置信 medical 建议但 evidence 为空时降级~~ → 已在 Checker precheck 处理（过程问题，可修）
- ~~action_signal 格式合规~~ → 已在 Checker precheck 处理（格式缺失属于过程不完整）

表达方式：

```text
Checker 是智能审计；
PreStopPolicy 是 Checker 的确定性预检 —— "你查够了吗？没查够回去查。"
SafetyGate 是输出警察 —— "你说出口的话安全吗？不安全我替你改。"
```

---

## 12. Memory 暂缓

Memory 放到最后改是正确的。

原因：

- 主干问题是 tools/RAG/loop/checker，不是记忆
- 医疗 memory 涉及隐私、授权、安全
- memory 不能作为医学证据
- 先改 memory 会让架构焦点发散

后续可以做：

```text
short-term memory:
  当前会话摘要、用户已提供事实

long-term memory:
  经用户授权的慢病背景、过敏史、偏好

similar cases:
  只做历史上下文，不支撑医学结论
```

原则：

```text
MemoryContext != Medical Evidence
```

---

## 13. Eval / Trace Framework

v3 必须补评估，否则面试时很难回答“你怎么知道改进有效”。

### 13.1 EvalCase 统一 schema

建议统一 eval 数据结构，避免 Router eval、tool eval、RAG eval、Checker eval 各写一套：

```python
EvalCase:
    id: str
    query: str
    expected_route: str | None
    expected_required_tools: list[str]
    expected_evidence_types: list[str]
    seeded_errors: list[str]
    expected_checker_issues: list[str]
    metadata: dict
```

Router 现有 eval fixture 可以迁移到这个 schema 的子集。

### 13.2 Tool-call eval

第一优先级。目标是验证 PreStopPolicy 是否能拦住漏调。

测试集：

```text
症状类 100 条 -> risk_rule_check recall
用药类 100 条 -> drug_safety_lookup recall
报告类 100 条 -> lab_reference_lookup recall
科普类 100 条 -> 不应强制调用高风险工具
```

指标：

```text
required_tool_recall
unnecessary_tool_call_rate
repair_success_rate
unsafe_final_without_required_tool
```

### 13.3 RAG eval

第二优先级。目标是验证检索质量和答案 grounding。

指标：

```text
Hit@K
MRR
context precision
context recall
faithfulness
citation accuracy
stale_evidence_rate
```

### 13.4 Checker eval

第三优先级。不要一开始做人类标注真实 Maker 输出的端到端 Checker eval，成本太高。

先做 seeded bad cases：

```text
漏调 risk_rule_check
drug_safety_lookup 参数错误
答案 claim 无 evidence
引用过旧指南
把 memory 当 evidence
高危症状没有 urgent action
```

指标：

```text
checker_detection_recall
false_challenge_rate
unsafe_pass_rate
```

### 13.5 Trace

每次 Maker-Checker run 记录：

```json
{
  "route": "maker_checker",
  "loaded_skills": ["symptom_triage"],
  "tool_calls": [],
  "evidence": [],
  "prestop_result": "PASS",
  "checker_verdict": "PASS",
  "safety_gate": "pass",
  "final_action": "self_care"
}
```

Trace 是面试亮点：它证明你不仅写了 prompt，还能观测和评估 Agent 行为。

---

## 14. 实施路线

### 14.0 质量保证原则

后续实现不能只追求“能跑”，要同时保证代码质量、功能质量和架构质量。

代码质量：

```text
- 用 dataclass / TypedDict 明确定义 ToolResult、EvidenceRecord、SkillDoc、PreStopResult
- 每个模块只负责一件事：SkillDocLoader 不注册工具，ToolRegistry 不读 SKILL.md
- AgentLoop 不解析医学规则，只执行上下文加载、工具循环和 policy hook
- PreStopPolicy 不调用 LLM，只做确定性检查
- Checker 不修改状态，只输出 verdict 和 issues
```

功能质量：

```text
- 每个阶段都有 unit tests
- AgentLoop 用 fake LLM 测试 skill 批量加载、tool loop、repair loop
- PreStopPolicy 用高风险/低风险样例测试 required-tool recall 和 false positive
- RAG evidence 用固定 KB fixtures 测试字段完整性和检索命中
- Reviewer 测试 precheck 失败时不调用 LLM，Orchestrator 测试 REJECT 后是否重新进入 Checker.review()
```

架构质量：

```text
- Router 仍然只输出 simple / maker_checker
- Skills 只做 progressive disclosure，不承担硬安全来源
- Tools 只返回结构化结果，不生成最终用户答案
- RAG evidence 不依赖自由文本拼接
- PreStopPolicy 作为 Checker 内部 precheck，只审过程（工具是否调用、证据是否收集），不审结论内容
- SafetyGate 只审输出内容（高危症状 action 匹配、安全检查），不重复过程检查
```

### v3.1: Tools + RAG Evidence

本阶段要交付的能力：

- 建立统一的工具输出协议，让每个工具返回可审计的结构化结果。
- 把 RAG 检索结果从自由文本升级为 evidence records，保留 source、year、score、citation 等审计字段。
- 把知识库检索和指南检索从旧 Skill 函数中拆出来，变成真正的 callable tools。
- 保留旧 `.claude/skills` 调用路径，使用 legacy wrapper 平滑迁移，避免一次性重构破坏现有 AgentLoop。
- 让 Maker 能从 `tool_results` 中提取 `evidence_records`，同时保持旧 `ActionSignal.evidence: list[str]` 契约不破。

为什么先做这一阶段：

RAG 是医疗 Agent 简历里最容易被追问的能力。只说“接了 Milvus”不够，必须能说清楚：

```text
retrieval -> evidence record -> Maker grounding -> Checker audit -> eval
```

所以 v3.1 的目标不是“加几个文件”，而是把 RAG 做成可被下游 Agent 审计的证据基础设施。

已实现功能：

- 建立可审计的工具输出契约。
  - 功能：把工具返回值统一为 `ToolResult`，把 RAG 证据统一为 `EvidenceRecord`，让工具输出可以被 Maker、Checker、Eval 复用和审计。
  - 原因：旧系统里 tool/skill 返回自由 dict 或大段 answer 文本，下游很难判断证据来源、年份、分数和类型。
  - 改动文件：`tools/specs.py`、`tools/__init__.py`
  - 质量保证：`tests/test_tool_specs.py`

- 把 RAG 从“搜索后拼文本”升级为“结构化证据基础设施”。
  - 功能：Milvus 原始检索结果会被规范化成包含 `title/source/year/snippet/score/evidence_type/citation` 的 evidence records。
  - 原因：简历和面试里，RAG 的亮点不应只是“接了 Milvus”，而应是“答案可以追溯到证据记录，并能被 Checker 审计”。
  - 取舍：第一版不做 `coverage/conflicts/missing_evidence`，因为这些字段无法由检索器可靠自动填充，容易变成空字段或 LLM 幻觉。
  - 改动文件：`knowledge/evidence_service.py`
  - 质量保证：`tests/test_evidence_service.py`

- 把知识库检索和指南检索拆成真正的 RAG tools。
  - 功能：`medical_kb_search` 和 `guideline_search` 返回 `ToolResult + evidence`，不再把检索、格式化、最终回答混在旧 Skill 函数里。
  - 原因：Tools 应该是可执行 API；Skills 应该是方法论文档。这个拆分是 v3 架构的基础。
  - 改动文件：`tools/medical_kb_search.py`、`tools/guideline_search.py`
  - 质量保证：`tests/test_rag_tools.py`

- 兼容迁移旧 `.claude/skills` 调用路径。
  - 功能：旧 `search_knowledge` / `clinical_guideline` 函数名保留，内部委托给新 RAG tools，同时返回旧字段和新 `evidence/tool_result` 字段。
  - 原因：当前 `core/skill_loader.py` 仍依赖旧目录和旧函数名。直接删除旧 skills 会扩大改动面，容易掩盖行为回归。
  - 改动文件：`.claude/skills/search-knowledge/script/search.py`、`.claude/skills/clinical-guideline/script/guideline.py`
  - 质量保证：`tests/test_rag_tools.py`

- 让 Maker 能消费结构化 RAG 证据。
  - 功能：Maker 从 `tool_results` 中提取 `evidence_records`，同时把 evidence record 压缩成短文本摘要合并进旧 `ActionSignal.evidence`。
  - 原因：下游 Checker 未来需要审计 source/year/score/type；但现有 SafetyGate、Reviewer 和测试仍依赖 `evidence: list[str]`。
  - 兼容策略：`ActionSignal.evidence` 继续保持字符串列表；新增 `action_signal["evidence_records"]` 和顶层 `result["evidence_records"]`。
  - 改动文件：`agents/generator.py`、`agents/evidence_extractor.py`
  - 质量保证：`tests/test_generator_evidence.py`

- 降低 RAG 证据层的依赖耦合。
  - 功能：`knowledge` 包入口改为延迟导入，测试 `EvidenceService` 时不会立刻加载 `pymilvus` 和 embedding 模型。
  - 原因：证据规范化是纯数据转换，单元测试不应该依赖真实向量库环境。
  - 改动文件：`knowledge/__init__.py`
  - 质量保证：`tests/test_evidence_service.py`

- 加强错误路径和可维护性。
  - 功能：RAG tool 在底层检索异常时返回 `success=False`，不会把异常抛穿 AgentLoop；metadata 白名单处标注了未来新增 PMID/DOI/publication_date 时需要同步更新。
  - 原因：工业落地系统必须能在向量库不可用时优雅降级，也要避免 metadata 字段静默丢失无人察觉。
  - 改动文件：`tools/medical_kb_search.py`、`tools/guideline_search.py`、`knowledge/evidence_service.py`
  - 质量保证：`tests/test_rag_tools.py`

- 提升 Router 降级状态的可观测性。
  - 功能：当语义层不可用时，同步 `route()` 能显式返回 `source="rule_degraded"` 和 `degraded=True`。
  - 原因：Router eval/observability 需要知道规则层是在“正常工作”还是“语义层降级后兜底工作”。
  - 改动文件：`pipeline/router.py`
  - 质量保证：`tests/test_router_eval.py`、`tests/test_pipeline.py`

本阶段亮点：

- RAG 不再是“搜索到一段话”，而是带 `source/year/score/citation/evidence_type` 的证据链。
- Tools 和 Skills 的边界开始被拆开：Tools 是可执行 API，Skills 后续会变成 SKILL.md 方法论文档。
- legacy wrapper 让旧 AgentLoop 可以继续运行，新 evidence contract 又能被 Maker/Checker 逐步消费。
- evidence extraction 被抽成纯数据模块，降低 Generator 对 LLMClient、AgentLoop 和 SkillRegistry 的耦合。
- RAG tool 失败时返回 `success=False`，向量库故障不会直接击穿 AgentLoop。

v3.1 测试结果：

```text
pytest -q tests
85 passed, 2 skipped
```

说明：pytest 运行时在 Windows 下产生过 `pytest-cache-files-*` 临时目录和 `.pytest_cache` 写入 warning。这些是测试缓存/临时产物，不属于项目功能文件，应在测试后清理；测试源码本身保留，用作回归保障。

### v3.2: Progressive Skills + ReAct Loop

本阶段要交付的能力：

- 建立 SKILL.md 方法论文档体系，让 Skills 成为“领域操作手册”，而不是函数工具。
- 给 Maker 一个紧凑 Skill Index，让它先判断需要加载哪些方法论，再进入正式 tool loop。
- 在 AgentLoop 内部实现 `SkillSelectionPass`，批量加载选中的 SKILL.md。
- 保留 ReAct-like tool loop，让 Maker 仍然能根据工具观察结果逐步决策。
- 输出 `loaded_skills` 和 `tool_trace`，为后续 Checker 审查过程路径做准备。

为什么这样做：

如果把 `load_skill` 做成普通 tool，系统会把“加载方法论文档”误记成医学工具调用，污染 tool trace，也会让 `max_tool_calls` 统计失真。

正确做法是：

```text
SkillSelectionPass = AgentLoop 内部 context loading
Tool calling       = Maker 正式执行医学/检索工具
```

这样 Maker 仍然是 Agent，但 SKILL.md 的 progressive disclosure 不会和工具执行混在一起。

实现约束：

```text
Skill loading 不进入 tool_trace
Skill loading 不计入 max_tool_calls
Skill loading 不生成 evidence
Skill loading 不作为 PreStopPolicy 的 required-tool 依据
```

已实现功能：

- 建立 SKILL.md 方法论文档加载体系。
  - 功能：系统可以扫描 `skills/*/SKILL.md`，解析 frontmatter 和 Markdown body，生成紧凑 Skill Index，也可以按需批量加载完整 SKILL.md。
  - 原因：v3 要把 Skills 从“函数工具”还原为“领域方法论”。加载 SKILL.md 是 context 操作，不是 tool execution。
  - 改动文件：`core/skill_index.py`
  - 质量保证：`tests/test_skill_index.py`

- 提供第一批医疗领域方法论 Skills。
  - 功能：新增症状分诊、用药安全、报告解读、健康科普、生活方式/慢病管理、循证研究 6 个 compact SKILL.md。
  - 原因：Maker 面对开放医疗问题时，需要的是“如何思考和选择工具”的领域指导，而不是固定 workflow。
  - 边界：这些 SKILL.md 只包含 `description/when_to_load/suggested_tools` 和 Markdown checklist，不包含 `required_tools` 或 `runtime_constraints`。
  - 改动文件：
    - `skills/symptom_triage/SKILL.md`
    - `skills/medication_safety/SKILL.md`
    - `skills/lab_report/SKILL.md`
    - `skills/health_education/SKILL.md`
    - `skills/lifestyle_chronic_care/SKILL.md`
    - `skills/evidence_research/SKILL.md`
  - 质量保证：`tests/test_skill_index.py`

- 在 AgentLoop 内部实现 progressive skill loading。
  - 功能：正式 ReAct tool loop 前，AgentLoop 会先运行 `SkillSelectionPass`：Maker 读取 Skill Index，只输出 `{"requested_skills": [...]}`；AgentLoop 再批量注入选中的 SKILL.md。
  - 原因：`load_skill` 不应该是普通 tool，否则会污染 tool_trace，也会把“加载方法论文档”误记成医学工具调用。
  - 运行约束：
    - 不进入 `tool_results`
    - 不进入 `tool_trace`
    - 不计入 `max_tool_calls`
    - 不生成 evidence
    - 不作为 PreStopPolicy 的依据
  - 改动文件：`core/agent_loop.py`
  - 质量保证：`tests/test_agent_loop_skill_selection.py`

- 让 Maker 默认启用 progressive skills，并暴露过程追踪字段。
  - 功能：Generator 默认开启 `progressive_skills_enabled=True`，并透传 `loaded_skills` 与 `tool_trace`。
  - 原因：后续 Checker 不应只审最终答案，还要审查 Maker 加载了哪些方法论、调用了哪些工具。
  - 改动文件：`agents/generator.py`
  - 质量保证：`tests/test_agent_loop_skill_selection.py`、现有 Orchestrator / Pipeline 回归测试

- 增强 SkillSelectionPass 的失败观测性。
  - 功能：如果 SkillSelectionPass 调用 LLM 失败，主流程继续进入 ReAct tool loop，同时 `skill_selection.error` 会记录失败原因。
  - 原因：Skill loading 是软增强，失败不应阻断主流程；但后续 trace/eval 需要能看到失败原因。
  - 改动文件：`core/agent_loop.py`
  - 质量保证：`tests/test_agent_loop_skill_selection.py`

本阶段亮点：

- Skills 被还原为 SKILL.md 方法论文档，和 function tools 在架构上分离。
- SkillSelectionPass 是 AgentLoop 内部步骤，不是普通 tool call。
- 一次性批量加载多个 SKILL.md，避免逐个加载带来的多轮 LLM 延迟。
- 四个“不”被测试验证：不进 `tool_trace`、不计入 `max_tool_calls`、不生成 evidence、不作为 PreStopPolicy 的依据。
- SKILL.md 只写 soft guidance 和 red lines，不写 `required_tools/runtime_constraints`，避免软硬约束混淆。
- SkillSelectionPass 失败时不中断主流程，但保留错误信息，为 v3.5 trace/eval 铺路。

v3.2 测试结果：

```text
pytest -q tests
96 passed, 2 skipped
```

### v3.3: Checker Precheck / PreStopPolicy

本阶段要交付的能力：

- 在 Checker 调用 LLM 前增加一个确定性 precheck。
- 对高精度医疗信号做 required-tool 检查，防止 Maker 没调必需工具就 final。
- 检查 draft 是否具备 `action_signal`、`proposed_action` 和证据支撑。
- 发现过程缺口时，Checker 不调用 LLM，直接返回可返修的 `REJECT / NEED_MORE_TOOL_USE`。
- 返修后仍不满足过程约束时，由 Orchestrator 进入 forced_safe。

为什么这样做：

ReAct-like Agent 的问题不是“不会调用工具”，而是“可能漏掉必须调用的工具”。医疗场景不能只靠 prompt 写“请优先调用风险评估”，必须有运行时检查。

PreStopPolicy 的定位是：

```text
PreStopPolicy = Checker 内部 deterministic precheck
LLM Checker   = 语义级 adversarial audit
SafetyGate    = 输出警察
```

PreStopPolicy 只问：

```text
你查够了吗？
关键工具漏了吗？
高置信结论有没有证据？
```

它不问：

```text
最终医学建议内容是否安全？
```

后者仍由 LLM Checker 和 SafetyGate 负责，避免把确定性过程检查和语义安全审计揉在一起。

已实现功能：

- 建立 PreStopPolicy 过程检查器。
  - 功能：提供 `before_final()` 和 `before_review()`；第一版实际使用 `before_review()`，其内部会先执行 required-tool 检查，再检查 action_signal 和 evidence。
  - 原因：当前 AgentLoop 尚未在 LLM final 前提供可中断 repair hook，因此先在 Maker draft 后、LLM Checker 前执行完整过程检查，是最小可落地实现。
  - 改动文件：`core/prestop_policy.py`
  - 质量保证：`tests/test_prestop_policy.py`

- 实现 required-tool 高精度规则。
  - 功能：症状红旗命中时要求 `assess_risk`；用药安全、报告解读先建立 required-tool 规则机制。
  - 原因：v3.3 的重点是把 required-tool 从 prompt 建议升级为 runtime policy；v3.4 再把用药和报告场景切换到专用 `drug_safety_lookup` / `lab_reference_lookup`。
  - 改动文件：`core/prestop_policy.py`
  - 质量保证：`tests/test_prestop_policy.py`

- 实现 evidence/action_signal 过程完整性检查。
  - 功能：缺少 `action_signal`、缺少 `proposed_action`、高置信但无 evidence 时返回可返修问题。
  - 原因：这些是可修复的过程问题，应退回 Maker 补证据或降低置信度，而不是直接由 SafetyGate 覆盖。
  - 改动文件：`core/prestop_policy.py`
  - 质量保证：`tests/test_prestop_policy.py`

- 将 PreStopPolicy 接入 Reviewer。
  - 功能：每次 `Reviewer.review()` 开始时先运行 PreStopPolicy；若预检失败，Reviewer 直接返回 `REJECT / NEED_MORE_TOOL_USE`，不调用 LLM Checker。
  - 原因：Checker 本身就是审查者，PreStopPolicy 是它的确定性预检阶段；这样 Orchestrator 只处理 Checker verdict，不需要理解 PreStop 规则。
  - 改动文件：`agents/reviewer.py`
  - 质量保证：`tests/test_reviewer_precheck.py`

- 简化 Orchestrator 的职责。
  - 功能：Orchestrator 不再直接调用 PreStopPolicy；它只处理 `PASS / CHALLENGE / REJECT`，在 `REJECT` 时让 Maker 返修一次，返修后重新进入 `Reviewer.review()`。
  - 原因：编排器只负责循环控制和终态处理，审查逻辑归 Checker，架构更高内聚低耦合。
  - 改动文件：`pipeline/orchestrator.py`
  - 质量保证：`tests/test_orchestrator.py`

- 把 PreStop 结果写入 Checker 返回值和轮次日志。
  - 功能：`reviewer.review()` 返回 `prestop_result`，`rounds_log` 记录该结果；trace/eval 后续可以看到每次过程约束触发原因和修复结果。
  - 原因：后续 v3.5 trace/eval 需要把 deterministic precheck 和 LLM audit 都观测起来。
  - 改动文件：`agents/reviewer.py`、`pipeline/orchestrator.py`
  - 质量保证：`tests/test_reviewer_precheck.py`、`tests/test_orchestrator.py`

本阶段亮点：

- 从“prompt 建议调用工具”升级为“Checker 调 LLM 前零 token 保证 required tools 不漏调”。
- PreStopPolicy 不依赖 Maker 自报的 selected skills，只看 `user_query/route triggers/tool_trace/action_signal/evidence`。
- PreStopPolicy 保持独立可测的规则模块，但生命周期归 Reviewer/Checker 管。
- Orchestrator 不理解 PreStop 规则，只根据 Checker verdict 做 repair / forced_safe。
- 返修路径是可执行的：`Checker precheck REJECT -> Generator.regenerate -> Checker.review again -> LLM Checker / forced_safe`。
- 第一版规则只做高精度场景，避免过早做庞大 Signal Catalog。

v3.3 测试结果：

```text
pytest -q tests
107 passed, 2 skipped
```
### v3.4: Checker Semantic Audit Upgrade

v3.4 不再重复做“Reviewer 改造成 Checker”。v3.3 已经完成 two-stage auditor 主体：

```text
Reviewer.review()
  -> PreStopPolicy deterministic precheck
  -> LLM Checker semantic audit
```

本阶段要交付的能力：

- Checker 不只是“再看一遍答案”，而是审计 Maker 的过程、证据和输出边界。
- LLM Checker 使用统一 issue taxonomy，减少旧 prompt 中维度过散的问题。
- Checker prompt 显式读取 `loaded_skills/tool_trace/evidence_records/action_signal/prestop_result`。
- 用药安全和化验单场景不再只靠 `search_knowledge` 兜底，而是有专用工具。

为什么这样做：

v3.3 解决的是“关键工具漏调时能不能零 token 拦截”。v3.4 解决的是“进入 LLM Checker 后，它到底按什么结构审”。如果 Checker 仍然沿用旧的答案质量维度，它会像普通 reviewer，而不是 process-aware Checker。

已实现功能：

- 升级 Checker system prompt。
  - 功能：将 issue type 收敛为 5 类：`TOOL_GAP`、`EVIDENCE_GAP`、`SAFETY_RISK`、`CONTEXT_GAP`、`OUTPUT_BOUNDARY`。
  - 原因：这些类别既能覆盖工具路径、证据、医疗安全、上下文不足和输出越界，又不会像旧维度那样过细导致 LLM 分类不稳定。
  - 质量保证：`tests/test_checker_semantic_audit.py`

- 让 Checker 显式审查 Maker 的 `loaded_skills`。
  - 功能：审查 prompt 中加入 `Loaded Skills`，并要求和 `Tool Trace`、`Evidence Records` 交叉对比。
  - 原因：v3.2 的 progressive skill loading 不能只是 trace 字段，必须进入 Checker 的审计视野；否则 Maker 加载了错误或不完整的方法论也没人看。
  - 质量保证：`tests/test_checker_semantic_audit.py`

- 增加 `checker_adversarial/SKILL.md`。
  - 功能：补上 Checker 固定审查 playbook，描述审查顺序、issue taxonomy、red lines 和输出纪律。
  - 原因：Maker 的 Skills 是按需加载的领域方法论；Checker 的审查方法论应固定使用，不需要每轮让 Checker 自主选择。
  - 质量保证：`tests/test_skill_index.py`

- 新增 `drug_safety_lookup`。
  - 功能：查询药物相互作用、禁忌、特殊人群、漏服和过量相关证据，并返回结构化 `ToolResult`。
  - 原因：用药安全是医疗 Agent 面试里的关键高风险场景，不能长期用通用 `search_knowledge` 模糊兜底。
  - 质量保证：`tests/test_rag_tools.py`

- 新增 `lab_reference_lookup`。
  - 功能：查询化验指标含义、参考范围、异常解释和复查边界，并返回结构化 `ToolResult`。
  - 原因：检查报告/化验单是用户高频问题，需要可审计的指标证据，而不是 Maker 凭常识解释。
  - 质量保证：`tests/test_rag_tools.py`

- 更新 PreStopPolicy required-tool rules。
  - 功能：用药类规则要求 `drug_safety_lookup`，报告/指标类规则要求 `lab_reference_lookup`。
  - 原因：PreStopPolicy 审计的工具路径要和项目真实工具能力对齐，不能停留在通用知识库查询。
  - 质量保证：`tests/test_prestop_policy.py`

本阶段亮点：

- Checker 从答案 reviewer 升级为 process-aware semantic auditor。
- Deterministic precheck 和 LLM semantic audit 的边界更清楚：前者抓确定性过程缺口，后者审工具路径、证据链和语义安全。
- 用药安全、化验单解读两个高频医疗场景有了专用工具和 required-tool 审计。
- 保留 `reviewer.py / ReviewerAgent` legacy 命名，避免大规模重命名制造无意义 diff；架构语义上它就是 Checker。

v3.4 测试结果：

```text
pytest -q tests\test_checker_semantic_audit.py tests\test_reviewer_precheck.py tests\test_rag_tools.py tests\test_prestop_policy.py
24 passed
```

### v3.5: Eval / Trace

本阶段要交付的能力：

- 统一 EvalCase schema
- tool-call eval fixture
- RAG eval fixture
- checker seeded bad cases fixture
- trace JSONL writer
- 轻量 report 脚本

为什么这样做：

架构升级如果没有 eval，就很难在面试里防守。“我觉得更安全”不够，必须能说明如何测量：required-tool recall、RAG evidence type 命中、Checker seeded bad case 是否能被识别。v3.5 先做稳定数据契约和离线报告，不急着接真实 LLM runner。

已实现功能：

- 建立统一 `EvalCase`。
  - 功能：用同一 schema 表达 query、expected_route、expected_tools、expected_evidence_types、seeded_errors、expected_checker_issues。
  - 原因：tool-call eval、RAG eval、Checker eval 不应该各写一套数据结构，否则后续报告和 runner 会碎片化。
  - 质量保证：`tests/test_eval_cases.py`

- 建立三类 JSONL fixtures。
  - 功能：`tool_call_cases.jsonl` 覆盖 required tools；`rag_cases.jsonl` 覆盖 evidence type；`checker_seeded_cases.jsonl` 覆盖 seeded bad cases。
  - 原因：第一版不做昂贵人工标注，先从确定性最强的 tool-call 和 seeded bad cases 起步。
  - 质量保证：`tests/test_eval_cases.py`

- 增加轻量 report 脚本。
  - 功能：`python -m evals.run_evals ...` 输出样本数、标签分布、期望工具分布、证据类型分布和 Checker issue 分布。
  - 原因：先让 eval 数据可读、可审计，再逐步接真实 agent runner 和指标计算。
  - 质量保证：`tests/test_eval_cases.py`

- 增加 `AgentTraceRecord` 和 `TraceWriter`。
  - 功能：把 route、loaded_skills、tool_trace、evidence、prestop_result、checker_verdict、safety_gate 和 final_action 写成 JSONL。
  - 原因：Maker-Checker 的调试和评估必须能回放过程；只看最终回答无法定位是 Router、Skill loading、Tool path、RAG 还是 Checker 出的问题。
  - 质量保证：`tests/test_trace.py`

本阶段亮点：

- Eval 从“想法”变成可运行 fixture 和报告脚本。
- Trace 是端到端过程字段，不只记录 final answer。
- Checker eval 先采用 seeded bad cases，避免一开始就陷入昂贵且主观的人工标注。
- v3.5 不依赖 LLM/Milvus，能在 CI 或本地快速验证数据契约。

v3.5 测试结果：

```text
pytest -q tests\test_eval_cases.py tests\test_trace.py
5 passed

python -m evals.run_evals evals\tool_call_cases.jsonl evals\rag_cases.jsonl evals\checker_seeded_cases.jsonl
total_cases: 8
```

v3.4 + v3.5 集成测试结果：

```text
pytest -q tests\test_checker_semantic_audit.py tests\test_reviewer_precheck.py tests\test_rag_tools.py tests\test_prestop_policy.py tests\test_eval_cases.py tests\test_trace.py
29 passed
```

### Future: Signal Catalog / Rule Unification

当 Router rules、PreStopPolicy rules、Skills 数量明显增多后再做。

目标：

- 把高危症状、用药风险、报告指标、心理危机等医学信号统一定义
- Router 读取 signal 决定 `simple / maker_checker`
- PreStopPolicy 读取 signal 决定 required tools
- Skill Index 读取 signal 生成 `when_to_load`
- 避免 Router、PreStopPolicy、SKILL.md 三处重复维护同一批医学信号

暂不在第一版实现，避免过早抽象。

### Future: Memory / MCP / Advanced RAG

最后再做：

- memory with consent
- memory_context_lookup
- hybrid retrieval
- rerank
- optional MCP wrapping

---

## 15. 推荐目录结构

```text
maker-checker/
├── agents/
│   ├── maker.py                 # new: 原 generator 升级
│   ├── checker.py               # new: 原 reviewer 升级
│   ├── lead.py                  # keep
│   ├── generator.py             # legacy fallback
│   └── reviewer.py              # legacy fallback
├── core/
│   ├── agent_loop.py            # keep and upgrade: ReAct-like + progressive skills
│   ├── llm_client.py            # keep
│   ├── skill_index.py           # new: SKILL.md index + SkillDocLoader
│   ├── tool_registry.py         # new
│   ├── prestop_policy.py        # new
│   ├── trace.py                 # new
│   ├── skill_registry.py        # legacy/adapt during migration
│   └── skill_loader.py          # legacy function-tool loader; do not use for SKILL.md docs
├── skills/
│   ├── symptom_triage/SKILL.md
│   ├── medication_safety/SKILL.md
│   ├── lab_report/SKILL.md
│   ├── health_education/SKILL.md
│   ├── lifestyle_chronic_care/SKILL.md
│   ├── evidence_research/SKILL.md
│   └── checker_adversarial/SKILL.md
├── tools/
│   ├── __init__.py
│   ├── specs.py
│   ├── risk_rule_check.py
│   ├── symptom_pattern_match.py
│   ├── medical_kb_search.py
│   ├── guideline_search.py
│   ├── lab_reference_lookup.py
│   ├── drug_safety_lookup.py
│   ├── ask_followup.py
│   └── calculator.py
├── knowledge/
│   ├── milvus_kb.py
│   └── evidence_service.py
├── pipeline/
│   ├── router.py                # keep: simple/maker_checker only
│   ├── route_decision.py        # keep
│   ├── orchestrator.py          # adapt Maker/Checker repair loop
│   ├── action_signal.py         # keep/enrich
│   ├── safety_gate.py           # keep deterministic
│   └── terminal.py              # keep
├── evals/
│   ├── cases.py
│   ├── tool_call_cases.jsonl
│   ├── rag_cases.jsonl
│   ├── checker_seeded_cases.jsonl
│   └── run_evals.py
└── .claude/
    └── skills/                  # legacy wrappers during migration
```

---

## 16. 简历表达

不要写：

```text
实现了一个医疗多 Agent 问答系统。
```

建议写：

```text
构建 Medical Maker-Checker Agent，保留 Router 的 simple/maker_checker 监督分流，Maker Agent 通过 progressive SKILL.md loading 和 ReAct-like loop 自主调用结构化医学工具并生成证据化回答；Checker Agent 采用 two-stage auditor 设计，先用 PreStopPolicy 零 token 检查 required tools、action_signal 和证据完整性，不通过则直接退回 Maker 补修，再调用 LLM 做 tool path、RAG evidence 和 medical safety 审计；SafetyGate 只审最终输出安全，不通过则硬覆盖为 urgent_care。
```

技术 bullet：

- 设计 progressive Skills / structured Tools / RAG evidence / two-stage Checker 的 Agent runtime，将原 `.claude/skills` 中混杂的可执行逻辑拆分为方法论、工具和证据。
- 在 ReAct-like tool-calling loop 前加入 `SkillSelectionPass`，使 Maker 先读 Skill Index，再由 AgentLoop 批量注入所需 `SKILL.md`，保留 Agent 自主规划和工具选择能力，同时避免把 Skill 文档加载误记为工具调用。
- 将 PreStopPolicy 收敛为 Checker 内部 deterministic precheck，不依赖 Maker 自报的 selected_skills，而是基于 user_query、route triggers 和 tool_trace 检查 required tools 与证据充分性；预检失败时 Checker 不调用 LLM，直接返回可返修 REJECT。
- 将 SafetyGate 收敛为"输出警察"，不重复 Checker precheck 的过程检查，只审最终结论内容安全（高危症状 action 匹配、Checker 标记的 SAFETY_RISK、输出边界），不通过则硬覆盖为 urgent_care。
- 将 RAG 从自然语言搜索结果升级为 evidence records，支持 source、year、score、evidence_type、citation 等可审计字段，并用于 Checker 的证据审查。
- 构建 process-aware Checker，不生成替代答案，只审查工具路径、证据支撑、风险边界和缺失上下文。
- 建立 tool-call / RAG / seeded Checker eval 与 trace 机制，用 required_tool_recall、context precision、faithfulness、unsafe_pass_rate 等指标验证改造效果。

---

## 17. 面试讲法

### 17.1 30 秒版本

> 这个项目最初是一个 ReAct-like 医疗 Agent，LLM 自主调用所谓 skills。复盘后我发现最大问题不是模型不会调工具，而是医疗场景不能只靠模型自觉：症状问题可能漏掉风险评估，用药问题可能漏掉药物安全检查，RAG 也可能只返回一段不可审计文本。所以我把它升级成 Medical Maker-Checker Agent：Router 只做 simple/maker_checker 监督分流；Maker 通过 progressive SKILL.md loading 自主选择领域方法论；Checker 做成 two-stage auditor，先用 PreStopPolicy 零 token 检查 required tools 和证据完整性，失败就直接退回 Maker，不浪费 LLM 审查；通过后再由 LLM Checker 审计工具路径、证据和安全边界；SafetyGate 只审最终输出安全。

### 17.2 为什么不是 workflow

> 我没有让 Router 输出 intent、skills 或 tools，因为那会把 Maker 变成执行器。Maker 仍然根据用户原问题自主加载 Skills、选择 Tools、综合 evidence。系统只声明不变量，比如症状类高风险表达不能跳过 risk_rule_check，用药安全表达不能跳过 drug_safety_lookup。这是 bounded agency，不是固定工作流。

### 17.3 为什么 Skills 用 Markdown

> Skills 用 Markdown 是为了 progressive disclosure。Maker 第一轮只读 Skill Index，如果需要再加载完整 SKILL.md。Markdown 适合写 checklist、red lines、tool use notes 和领域方法论。但医疗安全硬约束不放在 Skill 激活结果里，而放在 Checker 内部的 PreStopPolicy 中，避免安全性依赖 Maker 自报。

### 17.4 为什么保留 ReAct-like loop

> 医疗问题需要根据工具结果逐步决策。完整 PAOR 听起来高级，但第一阶段未必比 ReAct 更稳。所以我保留 ReAct-like loop，只加入 progressive skill loading、structured ToolResult、Checker precheck 和 repair loop。这样既保留 Agent 自主性，又补上医疗安全约束。

### 17.5 RAG 为什么是重点

> 简单接 Milvus 只能说明做了检索。我的改造重点是把 RAG 输出变成 evidence records，让 Maker 的关键 claim 有来源，让 Checker 可以审 source、year、score、citation 和 evidence_type，并用 RAG eval 验证检索质量和回答忠实度。

### 17.6 Tools 为什么搬目录但分阶段搬

> `.claude/skills/*/script` 里的代码本质是 tools，最终必须搬到 `tools/`，否则架构表达是错的。但我会分阶段迁移：先建 ToolRegistry 和新 tools 目录，再让旧 skills 变成 wrapper，等 AgentLoop 完全切到 ToolRegistry 后再删除 legacy。这样能避免一次性重命名掩盖行为回归。

---

## 18. 最终主线

从：

```text
LLM-driven tool calling
```

到：

```text
progressive skill loading + required-tool guarded Agent loop
```

从：

```text
skills as function folders
```

到：

```text
SKILL.md as domain playbooks + tools as callable APIs
```

从：

```text
RAG as text search answer
```

到：

```text
RAG as auditable evidence records
```

从：

```text
Reviewer 看最终答案
```

到：

```text
Checker 审工具路径、证据链和安全边界
```

从：

```text
Safety 靠 prompt
```

到：

```text
Checker precheck 审过程（可修）+ LLM Checker 审语义 + SafetyGate 审输出（硬改）+ eval
```

这就是 v3 应该做成的样子：Maker 有自主性，Skills 有渐进式披露，Checker 先做确定性过程预检（REJECT/REPAIR），再做 LLM 语义审计；SafetyGate 只做输出硬覆盖（OVERRIDE）；RAG 有证据链，Eval 有指标可验证。



