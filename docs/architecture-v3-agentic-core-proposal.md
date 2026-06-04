# Medical Maker-Checker Agent v3 架构方案

面向 Agent 岗位面试的最终方向：不是把项目做成固定医疗工作流，而是做成一个有约束、有证据、有审查、有评估的医疗 Agent runtime。

---

## 0. 最终结论

这个项目应该保留外层框架：

```text
Router -> Simple / Maker-Checker -> SafetyGate -> LeadAgent
```

其中 Router 只做 `simple | maker_checker` 分流，SafetyGate 只做确定性兜底。真正需要重构的是中间的 Agent 内核：

```text
Maker Agent
  = ReAct-like tool calling
  + compact Skills
  + structured Tools
  + evidence-based RAG
  + PreStop required-tool check

Checker Agent
  = independent adversarial auditor
  + tool path audit
  + evidence audit
  + medical safety audit
```

最终项目主线可以概括为：

```text
Medical Maker-Checker Agent
= ReAct-like Agent Loop
+ Structured Medical Tools
+ Evidence-based RAG
+ Required-tool Guardrails
+ Process-aware Checker
+ SafetyGate
+ Eval / Trace Framework
```

这不是死 workflow。Maker 仍然自主判断问题类型、自主选择工具、自主综合证据；系统只是保证它不能跳过医疗场景里的关键检查。

---

## 1. 为什么不能做成医疗工作流

这个项目要服务 Agent 岗位面试，不能展示成：

```text
用户问题 -> 分类 -> 固定调用几个函数 -> 模板回答
```

那更像 RAG QA、规则引擎或业务工作流，不像 Agent 项目。Agent 岗位更关心：

- LLM 如何在开放问题下选择工具
- agent loop 如何防止工具漏调
- RAG 如何从“搜到一段话”变成可审计证据
- 多 Agent 如何互审
- guardrails 如何进入运行时
- 如何用 eval 证明改动有效

医疗健康问题本身也非常开放。用户可能问：

| 问题类型 | 示例 | 需要能力 |
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

因此不能把系统限制成“症状 -> 风险 -> 指南 -> 回答”这条固定链。正确方向是：

```text
让 Maker 自主判断要做什么；
让运行时约束 Maker 不能漏掉必须做的安全动作。
```

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

如果 Router 决定具体 skill/tool，Maker 就会退化成执行器，项目会变成 workflow。Router 的职责只是监督等级选择：

```text
simple: 低风险、明确科普、非个人医疗决策
maker_checker: 高风险、个人医疗意图、用药、报告、治疗决策、不确定问题
```

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

问题不是名字，而是职责混在一起：

- 一个函数里同时做规则、RAG、文本格式化
- 返回大段 `answer` 文本，下游很难审计
- LLM 没调关键函数时，系统没有阻止机制
- Reviewer 只看答案质量，不审查工具路径
- RAG 结果没有稳定 metadata，无法做 freshness、citation、retrieval eval

### 2.3 当前 AgentLoop 是裸 ReAct-like loop

当前 `core/agent_loop.py` 的核心流程是：

```text
LLM -> tool calls -> execute tools -> append observations -> LLM -> final
```

这个方向本身没有错。ReAct-like loop 适合医疗这种开放问题，因为模型可以根据上一步工具结果决定下一步要不要继续查证。

真正的问题是：只有 loop，没有运行时约束。比如症状问题如果没有调用风险评估工具，系统仍然可能生成最终答案。

### 2.4 当前 RAG 不够像简历亮点

当前 RAG 更多是“搜索知识库并拼接文本”。面试里这不够强。RAG 应该成为可审计证据基础设施：

```text
retrieval -> evidence records -> answer grounding -> checker audit -> eval metrics
```

这会比“我接了 Milvus”更像一个 Agent/RAG 工程项目。

---

## 3. 最终架构

```text
User Query
    |
    v
Router
    - only simple / maker_checker
    |
    v
Maker Agent
    - reads user query
    - chooses relevant compact Skills
    - calls structured Tools through ReAct-like loop
    - collects evidence records from RAG/tools
    - produces draft answer + action_signal + trace
    |
    v
PreStop Check
    - required tools called?
    - evidence exists when needed?
    - action_signal exists?
    - high-risk output downgraded?
    |
    v
Checker Agent
    - audits tool path
    - audits evidence
    - audits medical safety
    - challenges or rejects unsafe/unsupported drafts
    |
    v
SafetyGate
    - deterministic final hard guard
    |
    v
LeadAgent
    - expression polishing only
    |
    v
Final Answer
```

一句话：Maker 是自主 Agent，Checker 是独立审计 Agent，SafetyGate 是确定性硬防线。

---

## 4. 术语边界

### 4.1 Skills

Skills 是给 Maker/Checker 看的领域方法论，不是可执行函数。

在本项目里，Skills 不需要做成很长的 Claude-style 手册。因为当前模型主要靠 function calling 工作，过长的 Skill 文档会增加一次额外 LLM 决策，反而可能降低稳定性。

推荐形态是 compact Skills：

```yaml
name: symptom_triage
description: 用户描述身体不适、症状、是否就医时使用
when_to_use:
  - 个人症状
  - 是否严重
  - 是否需要就医
must_check:
  - 红旗症状
  - 持续时间
  - 严重程度
  - 特殊人群
required_tools:
  - risk_rule_check
allowed_tools:
  - risk_rule_check
  - symptom_pattern_match
  - medical_kb_search
  - guideline_search
  - ask_followup
red_lines:
  - 不做确定诊断
  - 不给处方剂量
  - 不忽略红旗症状
```

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

### 4.3 RAG

RAG 不是返回一段自然语言答案，而是返回 evidence records。每条 evidence 只包含能自动填充、可验证的字段：

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

不要第一版就加 `coverage`、`conflicts`、`missing_evidence` 这种很难自动可靠填充的字段。它们听起来高级，但如果只能由 LLM 猜，就会变成新的幻觉来源。

### 4.4 Hook / Guardrail

这里的 hook 不需要做成完整平台。第一版只需要一个核心能力：在 Agent 准备结束前拦一次。

```text
PreStop Check:
- 症状类问题是否调用 risk_rule_check
- 用药类问题是否调用 drug_safety_lookup
- 高置信医疗建议是否有 evidence
- 高风险 action_signal 是否正确升级
```

这可以解决当前最大漏洞：LLM 没调用必须工具也能直接结束。

---

## 5. AgentLoop 设计

### 5.1 保留 ReAct-like loop

不建议第一版强行上完整 PAOR：

```text
Plan -> Act -> Observe -> Reflect
```

原因是：医疗问题常常需要根据工具结果逐步判断。比如用户说“肚子疼、呕吐、头晕”，Maker 可能先做风险规则检查，再根据风险结果决定是否需要指南或追问。ReAct-like 的逐步决策更自然。

第一版推荐：

```text
LLM decides tool call
-> execute tool
-> observe structured result
-> LLM decides next tool or final
-> PreStop check before final
-> repair loop if required tool/evidence missing
```

### 5.2 加一个轻量 planning step

可以让 Maker 在第一轮输出一个短 plan，但不要让 plan 变成固定执行图：

```text
Plan 是给模型自己和 Checker看的意图摘要；
不是 workflow engine 的 DAG。
```

示例：

```json
{
  "problem_understanding": "用户询问胸痛和呼吸困难，属于个人症状且可能高风险",
  "likely_skills": ["symptom_triage"],
  "initial_tools": ["risk_rule_check"],
  "answer_strategy": "先排除红旗风险，必要时建议急诊；证据不足时追问"
}
```

### 5.3 PreStop repair loop

当 LLM 想直接 final 时，系统先检查：

```python
if requires_tool("risk_rule_check") and not called("risk_rule_check"):
    append_system_message("必须先调用 risk_rule_check，不能直接回答。")
    continue_loop()
```

这就是 v3 的关键技术点：不是 prompt 建议模型调用，而是 runtime 保证关键工具不被跳过。

最多允许一次 repair，避免无限循环。第二次仍不满足，就降级为安全回答：

```text
目前信息不足，无法给出具体医学判断；如存在高危症状，请及时线下就医。
```

---

## 6. Skills 设计

第一阶段不做几十个 Skills，只做覆盖面最大的 6 个：

| Skill | 适用场景 | 必须工具 |
|---|---|---|
| health_education | 医学科普、健康知识、检查原理 | 无 |
| symptom_triage | 身体不适、症状、是否就医 | risk_rule_check |
| medication_safety | 相互作用、漏服、副作用、禁忌 | drug_safety_lookup |
| lab_report | 化验单、体检指标、影像报告 | lab_reference_lookup |
| lifestyle_chronic_care | 饮食、运动、睡眠、慢病日常管理 | 视情况 |
| evidence_research | 指南、专家共识、研究证据 | guideline_search 或 medical_kb_search |

第二阶段再补：

| Skill | 说明 |
|---|---|
| mental_health_safety | 自杀、自伤、严重心理危机 |
| admin_routing | 挂号、科室、医保等非诊疗问题 |
| checker_adversarial | Checker 专用审查 checklist |

Skills 的作用不是替 Maker 决策，而是降低 Maker 决策时的遗忘率：

```text
Maker 仍然自主选择工具；
Skill 只是提醒 Maker 这个问题领域有哪些红线、必须项和常用工具。
```

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

最终应该搬。因为 `.claude/skills/*/script/*.py` 这个位置会让读代码的人误解：

```text
它看起来是 Skills，实际上是 Tools。
```

对面试项目来说，目录结构本身就是架构表达。把可执行函数放在 `maker-checker/tools/` 下，可以让边界更清楚：

```text
skills/      -> 方法论、checklist、提示词片段
tools/       -> 可执行函数/API
knowledge/   -> RAG、Milvus、证据归一化
core/        -> agent loop、tool registry、guardrails
agents/      -> maker、checker、lead
pipeline/    -> router、orchestrator、safety gate
```

### 7.3 为什么不要立刻硬搬全部文件

不建议一开始直接把 `.claude/skills` 全删掉，原因不是架构上不该搬，而是工程上要降低风险：

- 当前 `SkillLoader` 和测试可能依赖 `.claude/skills` 的扫描路径
- 一次性移动文件会制造大量 import/path 变化，容易掩盖真实行为改动
- v3 最重要的是结构化 ToolResult、RAG evidence、PreStop、Checker audit，不是目录移动本身
- 先做兼容层，可以让新旧系统并行验证

推荐迁移方式：

```text
Step 1:
  新建 maker-checker/tools/
  把新 ToolSpec、ToolResult、registry 放进去
  旧 .claude/skills 继续可用

Step 2:
  从旧 script 里抽逻辑到 tools/
  旧 script 改成 thin wrapper，调用新 tools/

Step 3:
  AgentLoop 改为只读 ToolRegistry
  .claude/skills 不再作为工具来源

Step 4:
  删除或归档 .claude/skills legacy tools
```

这样既承认 tools 应该搬目录，也避免第一天做大规模重命名造成噪音。

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

这些可以在第二阶段由 Checker 作为“审查判断”输出，而不是由检索器假装知道。

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
关键医学 claim 必须来自 evidence 或 risk rule。
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

## 9. Checker Agent

Checker 不应该只是“再看一遍答案”。它应该审计 Maker 的过程。

输入：

```python
CheckerInput:
    user_query
    route_decision
    maker_plan
    tool_trace
    evidence
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

建议 issue type：

```text
missing_required_tool
tool_argument_error
insufficient_evidence
stale_evidence
unsupported_claim
unsafe_action
missing_followup
memory_used_as_evidence
```

Checker 重点审四件事：

1. Tool path 是否正确  
   这个问题是否漏掉了必须工具？工具参数是否合理？

2. Evidence 是否足够  
   关键结论有没有 evidence 支持？是否把低相关结果说成确定结论？

3. Medical safety 是否越界  
   是否漏掉红旗症状？是否给了诊断/处方级建议？

4. Missing context 是否处理  
   信息不足时是追问、降级，还是强行回答？

Orchestrator 行为：

| Verdict | 行为 |
|---|---|
| PASS | 进入 SafetyGate |
| CHALLENGE | 保留回答，但加入不确定性或安全修正 |
| REJECT | 返回 Maker 最多修一次；仍失败则 forced_safe |

---

## 10. SafetyGate

SafetyGate 保持确定性代码。它不是第三个 LLM Reviewer。

职责：

- 高危症状强制升级
- `action_signal` 缺失时兜底
- 高置信医疗建议但 evidence 为空时降级
- Checker 标记 unsafe 时强制安全回答
- 最终输出必须包含边界说明和就医建议

表达方式：

```text
Checker 是智能审计；
SafetyGate 是最后的硬防线。
```

---

## 11. Memory 暂缓

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

---

## 12. Eval / Trace Framework

v3 必须补评估，否则面试时很难回答“你怎么知道改进有效”。

### 12.1 Tool-call eval

目标：验证 required tools 没有漏调。

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

### 12.2 RAG eval

目标：验证检索质量和答案 grounding。

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

可以参考 Ragas 的 context precision、context recall、faithfulness 等指标思路。

### 12.3 Checker eval

构造 seeded bad cases：

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

### 12.4 Trace

每次 Maker-Checker run 记录：

```json
{
  "route": "maker_checker",
  "plan": [],
  "tool_calls": [],
  "evidence": [],
  "prestop_checks": [],
  "checker_verdict": "PASS",
  "safety_gate": "pass",
  "final_action": "self_care"
}
```

Trace 是面试亮点：它证明你不仅写了 prompt，还能观测和评估 Agent 行为。

---

## 13. 实施路线

### v3.1: Tools + RAG evidence

优先做：

- 新增 `tools/`
- 定义 `ToolSpec` / `ToolResult`
- 旧 `.claude/skills` 变成 legacy wrapper
- `search_knowledge` / `clinical_guideline` 改成 evidence records
- 新增 `knowledge/evidence_service.py`
- Generator 从工具结果里抽取 structured evidence

这是第一优先级，因为 RAG 是简历必写点。

### v3.2: ReAct loop + PreStop

优先做：

- 保留现有 ReAct-like loop
- 添加 tool trace
- 添加 required-tool check
- 添加 evidence-required check
- 最多一次 repair loop
- 失败时 forced safe downgrade

### v3.3: Checker process audit

优先做：

- Reviewer 改造为 Checker
- 输入 tool_trace/evidence/action_signal
- 输出 issue type
- Orchestrator 支持 `REJECT -> repair once -> SafetyGate`

### v3.4: Eval / Trace

优先做：

- tool-call eval dataset
- RAG eval dataset
- checker seeded bad cases
- trace jsonl
- 简单 report 脚本

### v3.5: Memory / MCP / advanced RAG

最后再做：

- memory with consent
- memory_context_lookup
- hybrid retrieval
- rerank
- optional MCP wrapping

---

## 14. 推荐目录结构

```text
maker-checker/
├── agents/
│   ├── maker.py                 # new: 原 generator 升级
│   ├── checker.py               # new: 原 reviewer 升级
│   ├── lead.py                  # keep
│   ├── generator.py             # legacy fallback
│   └── reviewer.py              # legacy fallback
├── core/
│   ├── agent_loop.py            # keep and upgrade: ReAct-like + PreStop
│   ├── llm_client.py            # keep
│   ├── tool_registry.py         # new
│   ├── tool_guardrails.py       # new
│   ├── trace.py                 # new
│   └── skill_registry.py        # keep/adapt for compact Skills
├── skills/
│   ├── symptom_triage.md
│   ├── medication_safety.md
│   ├── lab_report.md
│   ├── health_education.md
│   ├── lifestyle_chronic_care.md
│   ├── evidence_research.md
│   └── checker_adversarial.md
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
│   ├── tool_call_cases.jsonl
│   ├── rag_cases.jsonl
│   ├── checker_bad_cases.jsonl
│   └── run_evals.py
└── .claude/
    └── skills/                  # legacy wrappers during migration
```

---

## 15. 简历表达

不要写：

```text
实现了一个医疗多 Agent 问答系统。
```

建议写：

```text
构建 Medical Maker-Checker Agent，保留 Router 的 simple/maker_checker 监督分流，Maker Agent 基于 ReAct-like loop 自主调用结构化医学工具并生成证据化回答，Checker Agent 独立审计 tool path、RAG evidence 和 medical safety，结合 PreStop required-tool guardrails 与 deterministic SafetyGate 防止高风险医疗建议漏检和越界。
```

技术 bullet：

- 设计医疗 Agent runtime，将原本混在 `.claude/skills` 中的可执行逻辑拆分为 compact Skills、structured Tools 和 RAG evidence，解决 skills/tools 职责混乱问题。
- 在 ReAct-like tool-calling loop 上加入 PreStop required-tool check，保证症状类问题必须经过风险评估、用药类问题必须经过药物安全检查，避免仅靠 prompt 约束。
- 将 RAG 从自然语言搜索结果升级为 evidence records，支持 source、year、score、evidence_type、citation 等可审计字段，并用于 Checker 的证据充分性审查。
- 构建 process-aware Checker，不生成替代答案，只审查工具路径、证据支撑、风险边界和缺失上下文。
- 建立 tool-call / RAG / Checker / Safety eval 与 trace 机制，用 required_tool_recall、context precision、faithfulness、unsafe_pass_rate 等指标验证改造效果。

---

## 16. 面试讲法

### 16.1 30 秒版本

> 这个项目最初是一个 ReAct-like 医疗 Agent，LLM 自主调用所谓 skills。复盘后我发现最大问题不是模型不会调工具，而是医疗场景不能只靠模型自觉：症状问题可能漏掉风险评估，用药问题可能漏掉药物安全检查，RAG 也可能只返回一段不可审计文本。所以我把它升级成 Medical Maker-Checker Agent：Router 只做 simple/maker_checker 监督分流，Maker 保留自主 tool calling，工具返回结构化结果和 evidence records；在 Agent 结束前做 required-tool 和 evidence 检查；Checker 独立审计 tool path、证据和安全边界，最后 SafetyGate 用确定性规则兜底。

### 16.2 为什么不是 workflow

> 我没有让 Router 输出 intent、skills 或 tools，因为那会把 Maker 变成执行器。Maker 仍然根据用户原问题自主选择工具。系统只声明不变量，比如症状类问题不能跳过 risk_rule_check，用药类问题不能跳过 drug_safety_lookup。这是 bounded agency，不是固定工作流。

### 16.3 为什么保留 ReAct-like loop

> 医疗问题需要根据工具结果逐步决策。完整 PAOR 听起来高级，但第一阶段未必比 ReAct 更稳。所以我保留 ReAct-like loop，只在 final 前加 PreStop guardrail 和 repair loop。这样既保留 Agent 自主性，又补上医疗安全约束。

### 16.4 RAG 为什么是重点

> 简单接 Milvus 只能说明做了检索。我的改造重点是把 RAG 输出变成 evidence records，让 Maker 的关键 claim 有来源，让 Checker 可以审 source、year、score、citation 和 evidence_type，并用 RAG eval 验证检索质量和回答忠实度。

### 16.5 Tools 为什么搬目录但分阶段搬

> `.claude/skills/*/script` 里的代码本质是 tools，最终必须搬到 `tools/`，否则架构表达是错的。但我会分阶段迁移：先建 ToolRegistry 和新 tools 目录，再让旧 skills 变成 wrapper，等 AgentLoop 完全切到 ToolRegistry 后再删除 legacy。这样能避免一次性重命名掩盖行为回归。

---

## 17. 参考方向

这些不是要照搬，而是用来说明本项目的工程判断来源：

- OpenAI Agents SDK：tools、guardrails、tracing
  - https://openai.github.io/openai-agents-python/tools/
  - https://openai.github.io/openai-agents-python/guardrails/
  - https://openai.github.io/openai-agents-python/tracing/
- Claude Code public docs：skills、subagents、hooks、MCP 的工程思想
  - https://docs.claude.com/en/docs/claude-code/skills
  - https://code.claude.com/docs/en/sub-agents
  - https://code.claude.com/docs/en/hooks
  - https://docs.anthropic.com/en/docs/mcp
- LangGraph：stateful agent / graph orchestration / traceable execution
  - https://github.com/langchain-ai/langgraph
- Haystack：RAG pipeline 和 retrieval component 化
  - https://github.com/deepset-ai/haystack
- Ragas：RAG evaluation metrics，例如 context precision、context recall、faithfulness
  - https://docs.ragas.io/
- Phoenix：LLM / RAG tracing and observability
  - https://arize.com/docs/phoenix

本项目的取舍是：不直接做 LangGraph 式固定图，也不照搬 Claude-style 长 Skills；先做一个更适合 DeepSeek/function calling 的轻量医疗 Agent runtime。

---

## 18. 最终主线

从：

```text
LLM-driven tool calling
```

到：

```text
required-tool guarded Agent loop
```

从：

```text
skills as function folders
```

到：

```text
compact Skills + structured Tools
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
PreStop + Checker + SafetyGate + eval
```

这就是 v3 应该做成的样子。
