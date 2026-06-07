# Medical Maker-Checker Agent 项目说明书

这份文档把 v2、v3 和 `skills-tools-research/` 的内容重新整理成一份最终版项目说明。它的目标不是记录每个文件改了什么，而是回答面试官真正会问的问题：

- 这个项目能做什么？
- 为什么这样设计？
- 每个模块怎么工作，字段怎么传递？
- 从 v2 到 v3 每一步为什么要改，怎么改？
- 简历怎么写，面试怎么讲？
- 还有哪些地方值得继续优化？

---

## 1. 项目定位

### 1.1 一句话介绍

这是一个面向医疗健康问答场景的 **Medical Maker-Checker Agent**。系统保留 Agent 的自主规划和工具调用能力，同时用证据链、过程审查、确定性安全门和评估体系约束医疗风险。

主链路：

```text
User Query
  -> Router
  -> Maker Agent
  -> Checker Agent / PreStopPolicy
  -> SafetyGate
  -> ResponseRenderer
  -> Final Answer
```

### 1.2 它不是哪类项目

它不是普通 RAG QA：

```text
用户问题 -> 检索 -> 拼答案
```

也不是固定医疗工作流：

```text
分类 -> 固定调用 A/B/C -> 模板输出
```

它更接近一个有边界的 Agent runtime：

```text
Maker 自主判断、调用工具、综合证据；
Checker 审查工具路径、证据链和医疗安全；
SafetyGate 用确定性规则兜底最终输出。
```

### 1.3 项目目标

项目的目标不是替代医生，而是展示一个医疗 Agent 如何在开放问题中做到：

- 能处理多类型医疗健康问题，而不是只处理单一疾病工作流。
- 能自主调用工具，而不是由 Router 预先指定工具序列。
- 能引用结构化医学证据，而不是凭模型常识回答。
- 能被独立审查，而不是只相信 Maker 自己的输出。
- 能通过 eval 和 trace 解释系统行为，而不是只看最终答案。

---

## 2. 当前功能

### 2.1 支持的问题类型

| 类型 | 示例 | 主要能力 |
|---|---|---|
| 健康科普 | CT 和 MRI 有什么区别？HPV 疫苗有必要吗？ | 健康教育、RAG |
| 症状分诊 | 我胸痛、呼吸困难，现在怎么办？ | 红旗识别、风险评估、安全流程 |
| 用药安全 | 布洛芬和华法林能一起吃吗？ | 药物安全、相互作用、特殊人群 |
| 检查报告 | 尿酸 520 严重吗？肺结节 CT 怎么看？ | 化验/影像/生命体征工具 |
| 慢病管理 | 高血压能喝咖啡吗？糖尿病怎么运动？ | 慢病、生活方式、指南证据 |
| 循证查询 | 某疾病最新指南怎么建议？ | 指南检索、证据比较、来源质量 |
| 心理安全 | 我不想活了怎么办？ | 危机识别、安全建议、边界控制 |
| 个性化上下文 | 我上次说过青霉素过敏，还能用某药吗？ | 授权记忆、上下文检索、证据隔离 |

### 2.2 当前已实现的核心能力

| 能力 | 说明 |
|---|---|
| Router 分流 | 只判断 `simple / maker_checker`，不决定具体 skill/tool，避免 Maker 退化成工作流执行器。 |
| ReAct-like Maker | Maker 在 LLM tool-calling loop 中根据工具观察继续调用工具或生成答案。 |
| 24 个医疗 Skills | 使用 `SKILL.md` 写方法论、checklist、red lines 和 tool notes。 |
| SkillResolver | 本地 `cluster_hybrid_v1` 选择 2-4 个相关 Skills，替代默认 LLM SkillSelection 耗时路径。 |
| Tool Visibility Control | 根据 loaded skills 过滤 Maker 可见工具，减少无关 tool schema 和慢工具误调用。 |
| Structured Tools | 工具统一返回 `ToolResult`，便于 Maker 综合、Checker 审查和 eval 统计。 |
| RAG Evidence | RAG 返回 `EvidenceRecord`，包含 source/year/score/type/citation 等可审计字段。 |
| Advanced RAG | 支持 dense + keyword hybrid retrieval、RRF、轻量 rerank 和 evidence quality summary。 |
| Two-stage Checker | Checker 先做 PreStopPolicy 零 token 预检，再调用 LLM 做语义审计。 |
| SafetyGate | 最终输出安全门，只审“说出口的话是否安全”。 |
| ResponseRenderer | 不再使用 LLM 改写，通过审查时直接返回 Maker 答案，安全终态使用固定模板。 |
| Safe Memory | 支持用户授权记忆、用户隔离和 memory context 检索，memory 不作为医学证据。 |
| Eval / Trace | 提供 tool-call、RAG、Checker、Memory fixtures 和 JSONL trace。 |
| Timing Report | `python main.py` 输出 Router、Maker、Tools、Checker、SafetyGate 等耗时拆解。 |

---

## 3. 总体架构

### 3.1 主流程

```text
User Query
  |
  v
Router
  - 输出 simple / maker_checker
  - 不输出 intent / skill / tool
  |
  v
Maker Agent
  - SkillResolver 选择少量 SKILL.md
  - AgentLoop 注入 skill context
  - ToolVisibilityPolicy 过滤可见工具
  - ReAct-like tool calling
  - 生成 answer + urgency + evidence_records + process_trace
  |
  v
Checker Agent
  - PreStopPolicy: 确定性过程预检
  - LLM Checker: 语义级审查
  - REJECT 时返回 Maker 返修
  |
  v
SafetyGate
  - 最终输出安全检查
  - 高危不匹配时直接 override
  |
  v
ResponseRenderer
  - 通过审查: 直接输出 Maker answer
  - 安全终态: 输出固定安全模板
```

### 3.2 核心设计思想

这套架构的核心不是“多 Agent 数量多”，而是职责分离：

| 组件 | 负责什么 | 不负责什么 |
|---|---|---|
| Router | 监督等级选择 | 不决定具体工具，不输出完整任务规划 |
| Maker | 自主调用工具并生成答案 | 不自证安全，不跳过审查 |
| Skills | 给 Maker 方法论提醒 | 不执行代码，不承载硬约束 |
| Tools | 执行检索、规则、查询 | 不直接生成最终医学答案 |
| RAG | 提供可审计证据 | 不直接声称 coverage/conflict |
| Checker | 审查过程、证据和安全 | 不替 Maker 生成答案 |
| PreStopPolicy | 零 token 拦截确定性过程缺口 | 不做语义医学判断 |
| SafetyGate | 审最终输出动作是否安全 | 不审工具路径 |
| ResponseRenderer | 确定性渲染最终答案 | 不再调用 LLM 改写 |

### 3.3 为什么不是 workflow

如果 Router 输出 intent、skills、tools、required capabilities，那么 Maker 只是在执行 Router 的计划，项目就会变成 workflow。v3 的取舍是：

```text
Router 只决定监督等级；
Maker 自主选择工具；
系统只用 runtime policy 约束关键安全不变量。
```

这叫 bounded agency：保留 Agent 自主性，但不把医疗安全交给模型自觉。

---

## 4. 技术栈

| 技术 | 项目中的用法 |
|---|---|
| Python | 核心工程实现、工具封装、策略检查、eval。 |
| OpenAI-compatible Function Calling | Maker / Checker 调用工具和结构化输出。 |
| ReAct-like Agent Loop | LLM 观察工具结果后继续调用工具或 final。 |
| Markdown Skills | 用 `SKILL.md` 做 progressive disclosure。 |
| SkillResolver | 本地规则 + cluster gating + 轻量检索选择 Skills。 |
| Tool Visibility Policy | 根据 loaded skills 过滤 function schema。 |
| Milvus / pymilvus | 本地医学向量知识库。 |
| Hybrid Retrieval | dense + keyword 检索融合。 |
| Reciprocal Rank Fusion | 融合不同检索器排名。 |
| Lightweight Rerank | 用 query overlap、evidence type、年份和 citation 做轻量重排。 |
| Dataclass Contracts | `ToolResult`、`EvidenceRecord`、`PreStopResult` 等结构化契约。 |
| Deterministic Guardrails | PreStopPolicy 和 SafetyGate 的确定性规则。 |
| JSONL Eval / Trace | 记录和评估 Agent 过程。 |

---

## 5. 核心字段设计

这一节是整个项目的数据契约说明。可以把它理解成 Agent runtime 的“中间协议”：每个模块不是随便传 dict，而是按固定字段传递路由、答案、证据、过程、审查和安全信息。

阅读顺序建议：

```text
RouteDecision     -> Router 的分流结果
MakerOutput       -> Maker 的完整产物
Urgency           -> Maker 对就医紧急度的机器可读表达
EvidenceStrength  -> Maker 对证据充分性的结构化表达
ProcessTrace      -> Maker 的过程记录
ToolResult        -> 每个工具的标准返回值
EvidenceRecord    -> RAG 的标准证据对象
CheckerResult     -> Checker 的审查结果
PreStopResult     -> Checker 第一阶段的确定性预检结果
```

### 5.1 RouteDecision

Router 输出：

```python
RouteDecision = {
    "mode": "simple" | "maker_checker",
    "reason": str,
    "triggers": list[str],
    "source": "rule" | "semantic" | "llm",
    "degraded": bool,
    "degraded_reason": str | None,
}
```

字段解释：

| 字段 | 谁写入 | 谁读取 | 含义 |
|---|---|---|---|
| `mode` | Router | Orchestrator | 决定走快速路径还是 Maker-Checker 路径。 |
| `reason` | Router | 日志、终端、trace | 给人看的路由原因。 |
| `triggers` | Router | PreStopPolicy、trace、eval | 触发路由的信号列表。规则层通常是“标签:命中词”；语义层通常是分数；LLM 层通常是 LLM 判断结果。 |
| `source` | Router | 日志、eval | 谁做出的决策：规则、语义召回、还是 LLM fallback。 |
| `degraded` | Router | 日志、eval | 这次路由是否在降级状态下完成。 |
| `degraded_reason` | Router | 日志、eval | 降级原因，例如 `semantic_unavailable` 或 `llm_unavailable`。 |

重点理解：

```text
source 表示“谁做决策”。
degraded 表示“系统有没有降级”。
```

所以语义层不可用但规则命中了时，应该是：

```python
{
    "mode": "simple",
    "reason": "非个人医疗决策: 低风险健康教育:喝水",
    "triggers": ["低风险健康教育:喝水"],
    "source": "rule",
    "degraded": True,
    "degraded_reason": "semantic_unavailable",
}
```

不是：

```python
{
    "source": "rule_degraded"
}
```

因为 `rule_degraded` 会把“决策来源”和“降级状态”混在一起。

常见例子：

```python
# 例 1：低风险科普，规则层直接判 simple
{
    "mode": "simple",
    "reason": "非个人医疗决策: 低风险健康教育:喝水",
    "triggers": ["低风险健康教育:喝水"],
    "source": "rule",
    "degraded": False,
    "degraded_reason": None,
}

# 例 2：胸痛呼吸困难，规则层直接判 maker_checker
{
    "mode": "maker_checker",
    "reason": "安全红线: 急症症状:胸痛,呼吸困难",
    "triggers": ["急症症状:胸痛,呼吸困难"],
    "source": "rule",
    "degraded": False,
    "degraded_reason": None,
}

# 例 3：规则没命中，但语义召回高风险
{
    "mode": "maker_checker",
    "reason": "语义召回: 净分 0.23",
    "triggers": ["semantic_score=0.23"],
    "source": "semantic",
    "degraded": False,
    "degraded_reason": None,
}

# 例 4：规则和语义都不确定，由 LLM fallback 判 maker_checker
{
    "mode": "maker_checker",
    "reason": "LLM 路由仲裁: 涉及个人医疗决策",
    "triggers": ["llm_mode=maker_checker", "semantic_score=0.05"],
    "source": "llm",
    "degraded": False,
    "degraded_reason": None,
}
```

不加入字段：

```text
intent
skill_ids
required_tools
risk_level
```

原因：

- `intent` 会让 Router 变成业务分类器。
- `skill_ids` 会让 Router 决定 Maker 要加载什么方法论。
- `required_tools` 会让 Router 决定 Maker 要执行什么工具。
- `risk_level` 应由 Maker 调用风险工具或 Checker/SafetyGate 判断，不应由 Router 预判。

Router 保持轻量，Maker 才保留 Agent 自主性。

### 5.2 MakerOutput

Maker 输出应该尽量少、干净、可追溯。旧设计里的 `action_signal` 容易把“答案摘要、动作建议、置信度、证据摘要、证据 ID”混在一起，所以建议收敛为下面这个契约：

```python
MakerOutput = {
    "user_query": str,
    "answer": str,
    "urgency": "emergency" | "urgent" | "routine" | "self_care" | "education_only" | "uncertain",
    "evidence_records": list[EvidenceRecord],
    "process_trace": ProcessTrace,
}
```

字段解释：

| 字段 | 是否干净 | 从哪里来 | 是否一定能得到 | 谁读取 | 含义 |
|---|---|---|---|---|---|
| `user_query` | 干净 | Orchestrator 传入的原始问题 | 一定有 | Checker、TraceWriter | 用于审查和回放，不能被 Maker 改写。 |
| `answer` | 半干净 | LLM 按结构化输出生成 | Maker 成功时一定有；失败时 Orchestrator 进入 forced safe | Checker、SafetyGate、ResponseRenderer | 面向用户的自然语言草稿。下一步建议、解释理由、缺失信息都应该写在这里。 |
| `urgency` | 干净 | 工具结果 + 规则后处理归一化；LLM draft 只能作为弱辅助 | 一定有；兜底为 `uncertain` | Checker、SafetyGate、ResponseRenderer | 给机器读的紧急程度枚举，不承载用户可读解释。 |
| `evidence_records` | 干净 | 从 `ToolResult.evidence` 提取并去重 | 一定有 list；可能为空 | Checker、Eval、TraceWriter | 完整结构化证据。没有证据时为空列表。Checker 直接审查 evidence_records 本身（类型/年份/分数/是否误用 memory），不做二次摘要。 |
| `process_trace` | 干净 | AgentLoop 运行时记录 | 一定有；内部字段可为空 | Checker、PreStopPolicy、Eval、TraceWriter | 记录 Skills、工具调用、工具可见性和选择过程。 |

这里的“LLM 结构化 JSON”和“最终 MakerOutput”不是同一件事。建议分两层：

```text
LLM draft JSON:
  answer

Runtime postprocess:
  urgency
  evidence_records
  process_trace
```

原因是：`answer` 适合让 LLM 表达，里面可以包含下一步建议、理由和不确定性；但 `urgency/evidence_records/process_trace` 关系到安全、证据和审计，必须由工具结果和代码规则归一化，不能只相信 LLM 自报。`evidence_records` 本身就是可审计的——Checker 直接看证据类型/年份/分数，不需要一个派生的 `evidence_strength` 摘要。

一个典型 MakerOutput：

```python
{
    "user_query": "尿酸 520 严重吗？需要复查吗？",
    "answer": "尿酸 520 μmol/L 通常属于偏高，需要结合性别、参考范围、是否有关节红肿热痛、肾功能和既往痛风史判断。建议带着化验单到普通门诊或复诊时评估；如果有关节红肿热痛、肾功能异常或反复升高，应更早就医。",
    "urgency": "routine",
    "evidence_records": [
        {
            "id": "lab_uric_acid_001",
            "title": "尿酸参考范围和高尿酸血症解释",
            "source": "local_kb",
            "year": 2024,
            "snippet": "血尿酸升高需结合性别、饮食、肾功能和痛风症状评估...",
            "score": 0.82,
            "evidence_type": "lab_reference",
            "citation": "local_kb:lab_uric_acid_001",
        }
    ],
    "process_trace": {
        "loaded_skills": ["lab_report", "clarifying_questions"],
        "tool_trace": [{"tool_name": "lab_reference_lookup", "success": True}],
        "tool_summary": [{"tool_name": "lab_reference_lookup", "evidence_count": 1}],
        "skill_selection": {"resolver_version": "cluster_hybrid_v1"},
        "tool_visibility": {"visible_tools": ["lab_reference_lookup", "medical_kb_search"]},
    },
}
```

不再保留顶层 `loaded_skills/tool_trace/skill_trace` 兼容字段，避免字段散落。

也不再保留旧的 `action_signal`，原因是：

```text
result          -> answer 已经表达了结论，重复。
proposed_action -> 语义不够明确，改成 urgency；具体建议写在 answer。
confidence      -> 容易被误解成医学概率，删除。证据质量由 Checker 直接审查 evidence_records。
evidence        -> evidence_records 已经是完整证据，不再复制短摘要。
evidence_ids    -> 第一版不做 claim-level attribution 时可以省略，Checker 直接审 evidence_records。
```

### 5.3 Urgency

`urgency` 是 Maker 输出里给机器读的安全字段。它不放用户可读解释，只回答一个问题：这个回答最终应该被系统当成什么紧急程度处理？

```python
Urgency = "emergency" | "urgent" | "routine" | "self_care" | "education_only" | "uncertain"
```

字段设计：

| 字段 | 是否干净 | 从哪里来 | 是否一定能得到 | 谁读取 | 含义 |
|---|---|---|---|---|---|
| `urgency` | 干净 | 优先由风险工具、PreStop 规则、SafetyGate 风险信号归一化；LLM draft 只能作为辅助 | 一定有；兜底为 `uncertain` | Checker、SafetyGate、Renderer | 统一的行动等级。 |

为什么不放 `next_step / rationale / uncertainties`：

```text
这些都是用户可读内容，应该在 answer 里自然表达；
urgency 只服务 Checker / SafetyGate / Renderer 的机器判断。
```

`urgency` 的枚举值：

| 值 | 含义 | 示例 |
|---|---|---|
| `emergency` | 立即急救/急诊 | 胸痛伴呼吸困难、意识障碍、自杀即刻风险、严重出血等红旗。 |
| `urgent` | 尽快线下评估，但不一定是立即急救 | 高风险用药组合、明显异常生命体征、报告提示需尽快处理。 |
| `routine` | 普通门诊、复查或随访 | 化验指标异常、慢病管理、非急性症状。 |
| `self_care` | 可先自我护理和观察 | 低风险生活方式、轻微症状且无红旗。 |
| `education_only` | 纯科普，不涉及个人医疗决策 | “CT 和 MRI 有什么区别”。 |
| `uncertain` | 信息不足，不能可靠分层 | 缺少核心背景，工具失败，或 Maker 输出不完整。 |

归一化逻辑示例：

```text
1. 如果 risk_rule_check / assess_risk 命中急症红旗:
   urgency = emergency

2. 如果 drug_safety_lookup 返回高风险相互作用或特殊人群高风险:
   urgency = urgent

3. 如果 lab / imaging / vital_sign 工具提示异常但非急症:
   urgency = routine

4. 如果 Router 是 simple，且没有个人医疗决策:
   urgency = education_only

5. 如果工具失败、信息缺失、LLM 没给出可用结构:
   urgency = uncertain
```

胸痛例子：

```python
"urgency": "emergency"
```

### 5.4 ProcessTrace

```python
ProcessTrace = {
    "loaded_skills": list[str],
    "tool_trace": list[dict],
    "tool_summary": list[dict],
    "skill_selection": dict,
    "tool_visibility": dict,
}
```

字段设计：

| 字段 | 谁写入 | 谁读取 | 作用 |
|---|---|---|---|
| `loaded_skills` | AgentLoop | Checker、TraceWriter | 本轮注入给 Maker 的 SKILL.md。 |
| `tool_trace` | AgentLoop | Checker、PreStopPolicy、TraceWriter | Maker 实际调用过的工具路径。 |
| `tool_summary` | AgentLoop | Checker prompt、TraceWriter | 工具调用摘要，比完整 ToolResult 更短。 |
| `skill_selection` | SkillResolver / SkillSelectionPass | Eval、TraceWriter | Skill 选择过程、分数、原因、策略版本。 |
| `tool_visibility` | ToolVisibilityPolicy | Eval、TraceWriter | 本轮 Maker 可见哪些工具、哪些工具被过滤。 |

设计原因：

Checker 不应该只看最终答案，还要看 Maker 是如何得到答案的。

例子：

```python
{
    "loaded_skills": ["medication_safety", "drug_interaction"],
    "tool_trace": [
        {
            "tool_name": "drug_safety_lookup",
            "arguments": {"drug_names": ["布洛芬", "华法林"]},
            "success": True,
            "latency_ms": 42,
        }
    ],
    "tool_summary": [
        {
            "tool_name": "drug_safety_lookup",
            "success": True,
            "evidence_count": 2,
            "error": None,
        }
    ],
    "skill_selection": {
        "strategy": "cluster_hybrid",
        "resolver_version": "cluster_hybrid_v1",
        "selected_skill_ids": ["medication_safety", "drug_interaction"],
        "reasons": ["命中用药安全组合信号", "药物相互作用 cluster"],
    },
    "tool_visibility": {
        "enabled": True,
        "visible_tools": ["drug_safety_lookup", "medical_kb_search", "guideline_search"],
        "hidden_tools": ["deep_research", "lab_reference_lookup"],
    },
}
```

为什么 `loaded_skills` 不和 `urgency` 混在一起：

```text
loaded_skills 是 Maker 的过程；
urgency 是 Maker 的结构化行动等级。
```

Checker 会看两者，但它们不是同一类数据。

### 5.6 ToolResult

```python
ToolResult = {
    "tool_name": str,
    "success": bool,
    "data": dict,
    "evidence": list[EvidenceRecord],
    "error": str | None,
    "latency_ms": int | None,
}
```

字段解释：

| 字段 | 谁写入 | 谁读取 | 含义 |
|---|---|---|---|
| `tool_name` | Tool wrapper | AgentLoop、Checker、TraceWriter | 工具名。 |
| `success` | Tool wrapper | AgentLoop、Checker | 工具是否执行成功。 |
| `data` | Tool | Maker、Checker | 工具返回的结构化事实、规则结果或上下文。 |
| `evidence` | Tool | Maker、Checker、Eval | 医学证据列表。不是所有工具都有 evidence。 |
| `error` | Tool wrapper | AgentLoop、TraceWriter | 失败原因，成功时为空。 |
| `latency_ms` | Tool wrapper | Timing report、TraceWriter | 工具耗时。 |

医学检索工具例子：

```python
{
    "tool_name": "guideline_search",
    "success": True,
    "data": {
        "query": "急性胸痛 指南",
        "total_found": 2,
    },
    "evidence": [
        {
            "id": "guideline_chest_pain_001",
            "title": "急性胸痛评估指南",
            "evidence_type": "guideline",
            "year": 2024,
            "snippet": "急性胸痛应优先排除急性冠脉综合征等危急病因...",
        }
    ],
    "error": None,
    "latency_ms": 128,
}
```

规则工具例子：

```python
{
    "tool_name": "risk_rule_check",
    "success": True,
    "data": {
        "risk_level": "high",
        "matched_rules": ["chest_pain", "shortness_of_breath"],
        "recommendation": "urgent_care",
    },
    "evidence": [],
    "error": None,
    "latency_ms": 3,
}
```

Memory 工具例子：

```python
{
    "tool_name": "memory_context_lookup",
    "success": True,
    "data": {
        "memory_context": ["用户授权记录：青霉素过敏"],
        "not_medical_evidence": True,
    },
    "evidence": [],
    "error": None,
    "latency_ms": 5,
}
```

设计原因：

- 统一工具输出，避免每个工具自由返回 dict。
- 工具失败时返回 `success=False`，不击穿 AgentLoop。
- 医学来源放 `evidence`，用户记忆放 `data.memory_context`。
- 工具只返回事实和证据，不生成最终医学建议。

### 5.7 EvidenceRecord

```python
EvidenceRecord = {
    "id": str,
    "title": str,
    "source": str,
    "organization": str | None,
    "year": int | None,
    "snippet": str,
    "score": float,
    "evidence_type": str,
    "citation": str | None,
    "metadata": dict,
}
```

设计原因：

- Checker 可以审查 evidence 是否存在、是否过旧、是否来自合理来源。
- Eval 可以计算 evidence type 命中、citation coverage、stale rate。
- Maker 的医学 claim 可以追溯到证据。

字段解释：

| 字段 | 含义 | 为什么需要 |
|---|---|---|
| `id` | 证据唯一 ID | Checker、Eval 和未来 claim-evidence map 可以用它追踪证据。 |
| `title` | 文档或证据标题 | 让 Maker/Checker 知道证据来源主题。 |
| `source` | 来源系统或来源类型 | 区分 local_kb、guideline_db、web 等。 |
| `organization` | 发布机构 | 例如 CDC、WHO、中华医学会；没有可为空。 |
| `year` | 年份 | Checker 可以判断证据是否过旧。 |
| `snippet` | 证据片段 | Maker 主要根据它综合答案。 |
| `score` | 检索相关性分数 | Eval 和 rerank 使用。 |
| `evidence_type` | 证据类型 | 区分 guideline、drug_safety、lab_reference、memory_context 等。 |
| `citation` | 引用标识 | 给用户或 trace 展示来源。 |
| `metadata` | 额外字段 | 保存 doc_id、chunk_id、filename 等调试信息。 |

例子：

```python
{
    "id": "drug_warfarin_ibuprofen_001",
    "title": "华法林与 NSAIDs 合用风险",
    "source": "local_kb",
    "organization": "药物安全知识库",
    "year": 2024,
    "snippet": "华法林与非甾体抗炎药合用可能增加出血风险，应咨询医生或药师...",
    "score": 0.87,
    "evidence_type": "drug_safety",
    "citation": "local_kb:drug_warfarin_ibuprofen_001",
    "metadata": {
        "doc_id": "drug_interaction_manual",
        "chunk_id": "001",
    },
}
```

注意：

- `score` 是检索相关性，不是医学结论置信度。
- `year=None` 不代表证据无效，只代表当前知识库没有年份 metadata。
- `memory_context` 不应该作为医学 evidence；如果出现，Checker 应该标记风险。

刻意不做：

```text
coverage
conflicts
missing_evidence
```

原因：这些字段无法由检索器稳定自动填充，容易变成默认值或 LLM 幻觉。第一版只保留机器能稳定计算的字段。

### 5.8 CheckerResult

```python
CheckerResult = {
    "verdict": "PASS" | "CHALLENGE" | "REJECT",
    "issues": list[dict],
    "required_repairs": list[str],
    "safety_notes": list[str],
    "prestop_result": dict | None,
    "review_stage": "precheck" | "llm_audit",
}
```

字段解释：

| 字段 | 谁写入 | 谁读取 | 含义 |
|---|---|---|---|
| `verdict` | Checker | Orchestrator | 审查结论。 |
| `issues` | Checker | Orchestrator、TraceWriter | 发现的问题列表。 |
| `required_repairs` | Checker | Maker.regenerate | 返修时 Maker 必须处理的问题。 |
| `safety_notes` | Checker | SafetyGate、ResponseRenderer | 安全相关提示。 |
| `prestop_result` | PreStopPolicy / Checker | TraceWriter、Eval | 确定性预检结果。 |
| `review_stage` | Checker | TraceWriter、Eval | 是停在 precheck，还是进入了 LLM audit。 |

`verdict` 的含义：

| verdict | 含义 | Orchestrator 怎么处理 |
|---|---|---|
| `PASS` | 可以进入 SafetyGate | 不返修。 |
| `CHALLENGE` | 答案基本可用，但有不确定性或轻微问题 | 进入 SafetyGate，最终渲染时追加不确定性提示。 |
| `REJECT` | 存在必须修复的问题 | 退回 Maker 返修一次；仍失败则 forced safe。 |

issue type 收敛为：

```text
TOOL_GAP
EVIDENCE_GAP
SAFETY_RISK
CONTEXT_GAP
OUTPUT_BOUNDARY
```

设计原因：

- 类别够少，LLM Checker 分类更稳定。
- 覆盖工具路径、证据链、安全、上下文和输出边界。
- 具体问题可以放 `subtype`，不把顶层 taxonomy 搞得过细。

例子：

```python
{
    "verdict": "REJECT",
    "review_stage": "precheck",
    "issues": [
        {
            "type": "TOOL_GAP",
            "severity": "high",
            "message": "用户询问化验单异常，但 Maker 未调用 lab_reference_lookup。",
            "required_tool": "lab_reference_lookup",
        }
    ],
    "required_repairs": ["调用 lab_reference_lookup 后重新生成回答"],
    "safety_notes": [],
    "prestop_result": {
        "passed": False,
        "reject_type": "NEED_MORE_TOOL_USE",
    },
}
```

### 5.9 PreStopResult

```python
PreStopResult = {
    "passed": bool,
    "issues": list[PreStopIssue],
    "reject_type": "NEED_MORE_TOOL_USE" | "NEED_MORE_EVIDENCE" | "SAFETY_PROCESS_GAP" | None,
}
```

字段解释：

| 字段 | 含义 |
|---|---|
| `passed` | 是否通过确定性预检。 |
| `issues` | 触发了哪些确定性问题。 |
| `reject_type` | 如果不通过，属于哪类返修原因。 |

`reject_type` 的含义：

| reject_type | 场景 | Maker 应该怎么修 |
|---|---|---|
| `NEED_MORE_TOOL_USE` | 必需工具漏调，例如报告类未调用 `lab_reference_lookup`。 | 补调工具后重新生成。 |
| `NEED_MORE_EVIDENCE` | 声称高置信但没有 evidence。 | 检索证据或降低置信度。 |
| `SAFETY_PROCESS_GAP` | 高危场景未走安全流程，例如胸痛未风险评估。 | 先调用风险评估/药物安全等工具。 |

例子：

```python
{
    "passed": False,
    "reject_type": "SAFETY_PROCESS_GAP",
    "issues": [
        {
            "rule_name": "high_risk_symptom_requires_risk_assessment",
            "issue_type": "SAFETY_PROCESS_GAP",
            "message": "胸痛/呼吸困难场景必须先进行风险评估。",
            "required_tools": ["assess_risk"],
        }
    ],
}
```

设计原因：

- PreStopPolicy 是 Checker 的第一阶段。
- 它只做零 token 确定性检查。
- 不通过时直接 REJECT，不浪费 LLM Checker 调用。

### 5.10 LLM 输出格式总表

这个项目里不是所有 LLM 调用都输出同一种东西。需要分清：

```text
Router LLM fallback      -> JSON 分类
SkillSelectionPass       -> JSON skill 列表
Maker ReAct loop         -> OpenAI tool_calls 或最终 answer
Maker repair             -> 和 Maker ReAct loop 相同
Checker LLM audit        -> JSON verdict
ResponseRenderer         -> 不调用 LLM
SafetyGate / PreStop     -> 不调用 LLM
SkillResolver 默认路径   -> 不调用 LLM
```

#### 5.10.1 Router LLM fallback

当前代码真实格式：

```json
{
  "mode": "simple",
  "reason": "明确低风险的一般健康科普"
}
```

字段：

| 字段 | 类型 | 必填 | 来源 | 用途 |
|---|---|---|---|---|
| `mode` | `"simple" \| "maker_checker"` | 是 | Router LLM | 转成 `RouteDecision.mode`。 |
| `reason` | `str` | 是 | Router LLM | 转成 `RouteDecision.reason` 的一部分。 |

Router LLM 不输出：

```text
intent
skill_ids
required_tools
risk_level
urgency
```

原因：Router 只负责监督等级，不负责规划 Maker。

解析失败时：

```python
RouteDecision(
    mode="maker_checker",
    source="llm",
    degraded=True,
    degraded_reason="llm_unavailable",
)
```

也就是说，Router LLM 不可靠时 fail-closed，保守进入 Maker-Checker。

#### 5.10.2 SkillSelectionPass LLM fallback

当前默认不走这个 LLM 路径。默认路径是本地 `SkillResolver(cluster_hybrid_v1)`。

只有当 `skill_selection_strategy` 不使用 `cluster_hybrid / resolver` 时，才会回退到 LLM SkillSelectionPass。

当前代码真实格式：

```json
{
  "requested_skills": ["symptom_triage", "emergency_red_flags"],
  "reason": "用户描述胸痛和呼吸困难，需要症状分诊和急症红旗方法论"
}
```

字段：

| 字段 | 类型 | 必填 | 来源 | 用途 |
|---|---|---|---|---|
| `requested_skills` | `list[str]` | 是 | SkillSelection LLM | AgentLoop 加载这些 `SKILL.md`。 |
| `reason` | `str` | 否 | SkillSelection LLM | 写入 trace，便于解释为什么加载。 |

如果不需要加载 Skill：

```json
{
  "requested_skills": [],
  "reason": "无需加载"
}
```

注意：

```text
SkillSelectionPass 不是医学工具调用；
它不进入 tool_trace；
它不计入 max_tool_calls；
它不生成 evidence。
```

#### 5.10.3 Maker LLM tool call

Maker 在 ReAct-like loop 中有两种输出。第一种是请求调用工具。

OpenAI function calling 格式大致是：

```json
{
  "content": null,
  "tool_calls": [
    {
      "id": "call_xxx",
      "type": "function",
      "function": {
        "name": "lab_reference_lookup",
        "arguments": "{\"indicator\":\"尿酸\",\"value\":\"520 μmol/L\"}"
      }
    }
  ],
  "finish_reason": "tool_calls"
}
```

AgentLoop 内部会转成：

```python
ToolCall = {
    "id": "call_xxx",
    "name": "lab_reference_lookup",
    "arguments": {
        "indicator": "尿酸",
        "value": "520 μmol/L",
    },
}
```

字段：

| 字段 | 类型 | 必填 | 来源 | 用途 |
|---|---|---|---|---|
| `function.name` | `str` | 是 | Maker LLM | 决定调用哪个工具。 |
| `function.arguments` | JSON string | 是 | Maker LLM | 工具参数。 |
| `finish_reason` | `"tool_calls"` | 是 | LLM API | AgentLoop 判断继续执行工具。 |

工具调用结果不是 LLM 输出，而是 Tool 输出：

```python
ToolResult = {
    "tool_name": "lab_reference_lookup",
    "success": True,
    "data": {...},
    "evidence": [...],
    "error": None,
    "latency_ms": 42,
}
```

#### 5.10.4 Maker LLM final answer

当前代码真实格式：

```text
尿酸 520 μmol/L 通常属于偏高，需要结合性别、参考范围、症状、肾功能和既往痛风史判断...
```

也就是说，当前 Maker final LLM 主要输出自然语言答案，Agent 后处理再从工具结果中提取：

```text
evidence_records
process_trace
旧 action_signal
```

重新设计后的目标格式：

```json
{
  "answer": "尿酸 520 μmol/L 通常属于偏高，需要结合性别、参考范围、是否有关节红肿热痛、肾功能和既往痛风史判断。建议带着化验单到普通门诊或复诊时评估。"
}
```

字段：

| 字段 | 类型 | 必填 | 来源 | 用途 |
|---|---|---|---|---|
| `answer` | `str` | 是 | Maker LLM | 用户可读答案，包含建议、理由、不确定性和边界说明。 |

Maker LLM final 不应该输出：

```text
urgency
evidence_records
process_trace
```

原因：

```text
urgency          -> 由工具结果和规则归一化。
evidence_records  -> 来自 ToolResult.evidence。
process_trace      -> 来自 AgentLoop runtime。
```

最终 MakerOutput 由运行时合成：

```python
MakerOutput = {
    "user_query": user_query,
    "answer": llm_json["answer"],
    "urgency": normalize_urgency(tool_results, route_decision, llm_json),
    "evidence_records": evidence_records,
    "process_trace": process_trace,
}
```

#### 5.10.5 Maker repair LLM

Checker `REJECT` 后，Maker repair 使用更强或更高推理预算的 LLM profile，但输出格式和 Maker LLM 相同：

```json
{
  "answer": "已根据审查要求补充风险评估和证据后的回答..."
}
```

区别不在输出格式，而在输入 prompt：

```text
原始问题
上一轮 Checker challenges
必须逐条修复的问题
```

repair 后仍然重新经过：

```text
MakerOutput postprocess
Checker PreStopPolicy
Checker LLM audit
SafetyGate
```

#### 5.10.6 Checker LLM audit

Checker LLM 只输出审查结论，不输出替代医学答案。

当前代码真实格式：

```json
{
  "verdict": "REJECT",
  "challenges": [
    {
      "type": "EVIDENCE_GAP",
      "description": "Maker 的关键结论缺少 evidence_records 支撑。",
      "severity": "high",
      "suggested_fix": "补充医学知识库或指南检索证据后重新回答。"
    }
  ],
  "confidence_adjusted": 0.5
}
```

字段：

| 字段 | 类型 | 必填 | 来源 | 用途 |
|---|---|---|---|---|
| `verdict` | `"PASS" \| "CHALLENGE" \| "REJECT"` | 是 | Checker LLM | Orchestrator 决定是否返修。 |
| `challenges` | `list[dict]` | 是 | Checker LLM | 给 Maker repair 的问题列表。 |
| `challenges[].type` | issue type | 是 | Checker LLM | 归类问题。 |
| `challenges[].description` | `str` | 是 | Checker LLM | 问题描述。 |
| `challenges[].severity` | `"low" \| "medium" \| "high"` | 否 | Checker LLM | 问题严重程度，缺失时默认 medium。 |
| `challenges[].suggested_fix` | `str` | 否 | Checker LLM | 返修建议。 |
| `confidence_adjusted` | `float \| null` | 否 | Checker LLM | 旧字段，表示 Checker 对可靠性的调整。已移除，Checker 直接审查 evidence_records。 |

允许的 issue type：

```text
TOOL_GAP
EVIDENCE_GAP
SAFETY_RISK
CONTEXT_GAP
OUTPUT_BOUNDARY
```

解析失败时：

```json
{
  "verdict": "CHALLENGE",
  "challenges": [
    {
      "type": "CONTEXT_GAP",
      "description": "Reviewer 未能生成结构化判决，自动标记为 CHALLENGE。",
      "severity": "medium",
      "suggested_fix": "请 Review 流程重新执行"
    }
  ],
  "confidence_adjusted": 0.5
}
```

为什么 Checker 不输出 answer：

```text
Maker 负责生成；
Checker 负责证伪；
如果 Checker 也生成答案，Maker-Checker 会退化成多 Agent 合成。
```

---

## 6. 模块详细设计

### 6.1 Router

功能：

- 判断问题走 `simple` 还是 `maker_checker`。
- 低风险科普走快速路径。
- 高风险症状、用药、报告、治疗决策、心理危机走 Maker-Checker。

字段：

```python
mode
reason
triggers
source
degraded
degraded_reason
```

为什么只做分流：

如果 Router 同时输出 intent、skill 和 tool，Maker 会退化成固定执行器。当前项目要展示的是 Agent 能自主规划和调用工具，所以 Router 必须轻。

改进路线：

```text
v2: Router 负责 simple / maker_checker，避免所有问题都走对抗循环。
v3: 明确 Router 边界，不输出 skills/tools。
当前: 保留 Router 作为监督等级选择器，triggers 只作为后续审查辅助信号。
```

### 6.2 Maker / GeneratorAgent

功能：

- 接收用户问题和 RouteDecision。
- 加载相关 Skills。
- 在 ReAct-like loop 中自主调用工具。
- 综合 ToolResult 和 EvidenceRecord。
- 输出 MakerOutput。

关键设计：

```text
Maker 有自主性，但不是无约束。
Maker 可以选择工具，但 Checker 会审查它是否漏掉关键工具。
```

为什么保留 ReAct-like loop：

医疗问题常常需要根据工具结果逐步决策。例如症状问题需要先评估风险，再决定是否检索指南或给紧急建议。完整 PAOR 会要求模型在一开始规划完整工具图，对当前项目未必更稳。

改进路线：

```text
v2: Generator 生成答案，Reviewer 审查答案。
v3.1: Maker 输出 evidence_records，答案开始可审计。
v3.8 目标: 移除 action_signal，改为顶层 urgency，删除 evidence_strength。
v3.2: Maker 支持 progressive skill loading。
v3.7: Maker 默认使用本地 SkillResolver 和 Tool Visibility Control。
```

### 6.3 Skills

功能：

- 给 Maker 提供领域方法论。
- 提供 checklist、red lines、tool notes。
- 支持 progressive disclosure。

Skill 不是 Tool：

```text
Skill = 怎么思考
Tool = 怎么执行
```

当前 24 个 Maker-facing Skills：

```text
symptom_triage
emergency_red_flags
mental_health_safety
clarifying_questions
care_navigation
medication_safety
drug_interaction
renal_liver_dose_safety
pregnancy_pediatric_safety
geriatric_safety
lab_report
imaging_report
ecg_vital_signs
guideline_research
evidence_comparison
source_quality_appraisal
health_education
preventive_care
medical_device_explainer
chronic_care
lifestyle_coaching
nutrition_weight_management
rehabilitation_exercise_safety
memory_personalization
```

Checker 专用 Skill：

```text
checker_adversarial
```

为什么不是按疾病建 Skills：

按疾病建 Skill 会很快变成医疗百科，也容易数量膨胀。当前按照“处理方法”划分，例如症状分诊、用药安全、报告解读、证据比较，更适合开放问答和 Agent 工具选择。

改进路线：

```text
早期: .claude/skills 实际是可执行函数。
v3.2: 开始把 Skills 改成 SKILL.md 方法论文档。
skills-tools-research: 调研后设计 24 个不重复 Skills。
v3.7: 删除旧粗粒度 Skills，落地 24 个 Maker-facing Skills。
```

### 6.4 SkillResolver

功能：

- 在 Maker LLM 第一次调用前选择 2-4 个相关 SKILL.md。
- 使用本地策略，不额外调用 LLM。

策略：

```text
hard safety implication rules
+ cluster gating
+ lightweight retrieval top-k
+ max 4 skills
```

输出：

```python
SkillResolution = {
    "selected_skill_ids": list[str],
    "safety_implied_skill_ids": list[str],
    "clusters": list[str],
    "scores": dict[str, float],
    "reasons": list[str],
    "resolver_version": "cluster_hybrid_v1",
}
```

为什么不用纯 LLM 选择：

- 多一次 LLM 调用，慢。
- 对组合风险召回不稳定，例如“孕妇 + 发热 + 用药”可能只选 pregnancy skill，漏掉 medication/symptom。
- 选错 Skill 会增加后续 repair。

为什么不用全量注入：

- 24 个 Skills 全量注入平均约 7550 token proxy。
- 噪音大，工具选择变慢。
- 不能体现 progressive disclosure。

实验结果：

```text
S6_cluster_hybrid:
  avg_recall:          0.951
  avg_precision:       0.861
  safety_full_recall:  0.909
  avg_selected:        2.46
  token_proxy:         817
  p95_latency_ms:      0.081
```

改进路线：

```text
v3.2: LLM SkillSelectionPass 作为起点。
研究阶段: 比较 6 种 progressive loading 策略。
v3.7: 选择 S6 cluster hybrid，默认启用本地 SkillResolver。
```

### 6.5 Tool Visibility Control

功能：

- 根据 loaded skills 过滤 Maker 可见工具。
- Maker 仍自主选工具，但不需要每轮看到所有 function schema。

示例：

| loaded skills | visible tools |
|---|---|
| `health_education` | `medical_kb_search` |
| `symptom_triage`, `emergency_red_flags` | `assess_risk`, `risk_rule_check`, `medical_kb_search`, `guideline_search` |
| `medication_safety`, `drug_interaction` | `drug_safety_lookup`, `medical_kb_search`, `guideline_search` |
| `lab_report` | `lab_reference_lookup`, `medical_kb_search` |
| `guideline_research`, `evidence_comparison` | `guideline_search`, `medical_kb_search`, `deep_research` |

为什么不是 workflow：

系统只是减少工具暴露，不指定工具调用顺序。最终是否调用工具仍由 Maker 在 ReAct-like loop 中决定。

改进路线：

```text
问题: Maker 看到过多工具 schema，LLM 选择成本高，且容易误调 deep_research。
方案: loaded_skills -> visible_tools。
落地: core.tool_visibility.ToolVisibilityPolicy 接入 AgentLoop。
```

### 6.6 Tools

功能：

- 提供可执行 API。
- 返回结构化 ToolResult。
- 不生成最终用户答案。

当前现代 structured tools：

| Tool | 作用 |
|---|---|
| `medical_kb_search` | 医学知识库检索，返回 evidence records。 |
| `guideline_search` | 指南/共识检索。 |
| `drug_safety_lookup` | 药物安全、相互作用、禁忌、特殊人群。 |
| `lab_reference_lookup` | 化验指标含义、参考范围、异常解释。 |
| `memory_context_lookup` | 用户授权 memory context，不作为证据。 |
| `risk_rule_check` | 确定性红旗规则检查。 |
| `imaging_reference_lookup` | 影像报告术语、结节、CT/MRI 等。 |
| `vital_sign_reference_lookup` | 血压、血氧、心率、体温、心电图等。 |

仍保留 legacy wrapper：

```text
assess_risk
analyze_symptoms
recommend_lifestyle
deep_research
disease_code
search_history
search_similar_cases
```

为什么逐步迁移而不是一次性删除：

- 旧 AgentLoop 和测试依赖 `.claude/skills` 扫描路径。
- 一次性移动会制造大量无意义 diff。
- 先用 wrapper 兼容，再逐步把逻辑收敛到 `tools/` 更稳。

改进路线：

```text
早期: skills 文件夹里放 Python 函数，概念混乱。
v3.1: 建立 ToolResult / EvidenceRecord。
v3.4: 新增 drug_safety_lookup 和 lab_reference_lookup。
v3.6: structured tools registration。
v3.7: 新增 risk_rule_check / imaging_reference_lookup / vital_sign_reference_lookup。
```

### 6.7 RAG / EvidenceService

功能：

- 从医学知识库检索证据。
- 归一化为 EvidenceRecord。
- 支持 hybrid retrieval、RRF、轻量 rerank 和 evidence quality summary。

设计原则：

```text
RAG 不直接生成最终答案；
RAG 返回可审计证据；
Maker 基于 evidence 写答案；
Checker 审 evidence 是否支撑 claim。
```

高级 RAG 能力：

| 能力 | 原因 |
|---|---|
| dense retrieval | 语义召回。 |
| keyword retrieval | 药名、指标、年份、缩写等精确命中。 |
| RRF | 融合不同检索器排名，避免分数尺度不一致。 |
| lightweight rerank | 不加载重 reranker，也能按年份、citation、type 提升质量。 |
| quality summary | 给 Checker/Eval 提供新鲜度、citation coverage、stale count 等统计。 |

为什么不做 coverage/conflicts：

这类字段需要医学判断或知识图谱支持，检索器无法可靠自动填充。先做能落地和能测试的字段。

改进路线：

```text
早期: search_knowledge 返回 answer 文本。
v3.1: 返回 EvidenceRecord。
v3.6: 增加 hybrid retrieval / RRF / rerank / quality summary。
当前: RAG 成为 Maker、Checker、Eval 共享的证据基础设施。
```

### 6.8 Memory

功能：

- 保存用户授权的长期记忆。
- 支持当前会话短期记忆。
- 提供 memory context 给 Maker 个性化回答。

边界：

```text
MemoryContext != Medical Evidence
```

字段和约束：

| 设计 | 原因 |
|---|---|
| `require_consent=True` | 医疗记忆不能静默保存。 |
| `user_id` 隔离 | 防止跨用户串记忆。 |
| `sensitive` 默认不返回 | 避免敏感信息误用。 |
| `ToolResult.evidence=[]` | memory 不作为医学证据。 |
| `not_medical_evidence=True` | 显式提醒 Maker/Checker。 |

改进路线：

```text
早期: memory/search-history 和 similar cases 更像 legacy 工具。
v3.6: 实现 Safe Memory，强调授权、隔离和证据边界。
当前: Memory 用于个性化上下文，不参与医学 claim grounding。
```

### 6.9 Checker / ReviewerAgent

功能：

- 审查 Maker 的工具路径、证据链、上下文缺口和医疗安全边界。
- 不生成替代答案。

两阶段：

```text
Stage 1: PreStopPolicy
  - zero-token deterministic precheck
  - 不通过直接 REJECT

Stage 2: LLM semantic audit
  - 审工具参数是否合理
  - 审 evidence 是否支持 claim
  - 审是否越过医疗安全边界
```

issue taxonomy：

```text
TOOL_GAP
EVIDENCE_GAP
SAFETY_RISK
CONTEXT_GAP
OUTPUT_BOUNDARY
```

为什么 Checker 不回答问题：

如果 Checker 也生成答案，系统会变成多个 Agent 投票或合成。Maker-Checker 的价值在于结构性对抗：Maker 负责生成，Checker 负责证伪。

改进路线：

```text
v2: 引入 Maker-Checker 对抗循环。
v3.3: PreStopPolicy 接入 Reviewer，先做确定性过程预检。
v3.4: Checker prompt 升级为 process-aware semantic audit。
当前: Checker 审过程 + 证据 + 安全，而不是只看答案文采。
```

### 6.10 PreStopPolicy

功能：

- Checker LLM 调用前做零 token 预检。
- 拦截 required tools 漏调、证据缺失、安全流程缺口。

典型规则：

| 场景 | required tool |
|---|---|
| 高危症状 / 心理危机 | `assess_risk` 或风险评估流程 |
| 用药安全 / 相互作用 | `drug_safety_lookup` |
| 化验单 / 指标异常 | `lab_reference_lookup` |
| 指南 / 循证 / 治疗方案 | `guideline_search` 或 `medical_kb_search` |

为什么不放到 Router：

Router 只做分流；PreStopPolicy 需要看 Maker 实际调用过什么工具。它审的是“过程是否完整”，不是“问题属于哪类”。

为什么不完全交给 LLM Checker：

required-tool 漏调、evidence 为空、高危场景未走安全流程，这些可以确定性检查。能不用 LLM 的地方不用 LLM，更稳定也更便宜。

### 6.11 SafetyGate

功能：

- 最终输出前的确定性安全门。
- 只审“最终说出口的话是否安全”。

典型检查：

- query 含高危症状，但 `urgency` 不是 `emergency` 或 `urgent`。
- `urgency` 缺失或为 `uncertain`，且已经返修失败。
- Checker 标记 `SAFETY_RISK` 或 `OUTPUT_BOUNDARY`。

为什么和 PreStopPolicy 分开：

```text
PreStopPolicy: 你查够了吗？没查够回去查。
SafetyGate: 你说出口的话安全吗？不安全我替你改。
```

### 6.12 ResponseRenderer

功能：

- 最终渲染答案。
- 不调用 LLM。

输出策略：

| 终态 | 策略 |
|---|---|
| `normal/simple` | 直接返回 Maker answer。 |
| `challenged` | 返回 Maker answer，并追加固定不确定性提示。 |
| `gate_override` | 不返回 Maker answer，使用 SafetyGate 安全模板。 |
| `forced_safe` | 使用强制安全兜底模板。 |

为什么移除 LeadAgent LLM：

v2 的 LeadAgent 用于综合多个 Agent 结果，但 v3 中 Maker 已经生成用户答案，Checker 和 SafetyGate 已经完成审查。最后再让 LLM 改写会增加延迟，并可能改变已审查过的医学含义。

改进路线：

```text
v2: LeadAgent 负责最终表达。
v3: ResponseRenderer 替代 LeadAgent。
当前: 最终输出确定性渲染，通过审查即返回 Maker 答案。
```

### 6.13 Orchestrator

功能：

- 串联 Router、Maker、Checker、SafetyGate、ResponseRenderer。
- 处理 Checker REJECT 后的返修循环。
- 控制 forced_safe 终态。

设计原则：

Orchestrator 不理解医学规则，不直接调用 PreStopPolicy。它只处理 Checker verdict：

```text
PASS -> SafetyGate
CHALLENGE -> SafetyGate + challenged render
REJECT -> Maker repair -> Checker.review again
仍失败 -> forced_safe
```

这样规则归 Checker，流程归 Orchestrator，职责更清楚。

### 6.14 Eval / Trace

功能：

- 用 fixtures 和 trace 评估系统行为。
- 不只看最终答案，也看过程。

Eval 类型：

| Eval | 检查什么 |
|---|---|
| tool-call eval | required tools 是否被调用或被 PreStop 拦截。 |
| RAG eval | evidence type、retrieval hit、citation、新鲜度。 |
| Checker seeded cases | 漏工具、无证据、高危错误是否被识别。 |
| Memory eval | memory 是否隔离、是否被误当证据。 |

Trace 记录：

```json
{
  "route": "maker_checker",
  "process_trace": {},
  "evidence": [],
  "prestop_result": {},
  "checker_verdict": "PASS",
  "safety_gate": "pass",
  "final_action": "self_care"
}
```

为什么重要：

Agent 项目如果没有 trace，很难解释“为什么这么答”。Eval/Trace 让项目从 prompt demo 变成可调试系统。

---

## 7. 从 v2 到 v3 的改进路线

### 7.1 总体演进

```text
v2:
  Adversarial Maker-Checker
  Router simple/maker_checker
  Reviewer 审答案
  SafetyGate 兜底
  LeadAgent 表达

v3:
  Skill-aware Maker
  structured tools
  auditable RAG evidence
  process-aware Checker
  PreStopPolicy zero-token precheck
  deterministic ResponseRenderer
  Safe Memory
  Eval / Trace
  SkillResolver + Tool Visibility
```

### 7.2 功能级改进路线

| 功能 | 原问题 | 改进方法 | 当前结果 |
|---|---|---|---|
| Router | 可能被扩成 intent/tool planner | 明确只输出 simple/maker_checker | 保留 Maker 自主性 |
| AgentLoop | 裸 ReAct，可能漏调关键工具 | 保留 ReAct，但增加 Skills、ToolResult、Checker 约束 | 动态但有边界 |
| Skills | 旧 skills 实际是函数工具 | 拆成 SKILL.md 方法论 + tools 可执行函数 | 24 个方法论 Skills |
| Skill Loading | LLM 选择慢，组合风险召回不足 | S6 cluster hybrid resolver | recall 0.951，平均 2.46 skills |
| Tool 暴露 | Maker 看到太多 tools，容易误调慢工具 | Tool Visibility Control | 减少 schema 噪音 |
| RAG | 返回 answer 文本，无法审计 | EvidenceRecord + EvidenceService | source/year/citation 可追溯 |
| Retrieval | 只靠向量检索不稳 | hybrid retrieval + RRF + rerank | 药名/指标/年份更稳 |
| Checker | 只审答案质量 | process-aware two-stage audit | 审工具路径和证据链 |
| Safety | prompt 建议模型自觉调用工具 | PreStopPolicy runtime constraint | 漏调 required tools 可 REJECT |
| Final Output | LeadAgent 再次 LLM 改写 | ResponseRenderer 确定性输出 | 降延迟，避免改写医学含义 |
| Memory | 记忆边界不清 | 授权、隔离、not evidence | 安全个性化 |
| Eval | 架构改进不可量化 | fixtures + trace + report | 可解释可回归 |

### 7.3 每一步背后的思路

#### Step 1: 先保留 Maker-Checker，不改成工作流

原因：

- 项目服务 Agent 岗位面试，不能只展示固定流程。
- 医疗问题开放，强行 workflow 会限制能力。
- Maker-Checker 能展示生成与审查分离。

方法：

- Router 只做 simple/maker_checker。
- Maker 仍然自己调用工具。
- Checker 独立审查，而不是多个 Agent 投票。

#### Step 2: 把 Skills 和 Tools 拆开

原因：

- 旧 `.claude/skills` 里的文件实际是 function tools。
- Skill 如果既是方法论又执行代码，会让上下文加载、工具调用和证据审查混乱。

方法：

```text
skills/ -> SKILL.md 方法论
tools/  -> callable API / function
knowledge/ -> RAG evidence
```

#### Step 3: 让 RAG 变成证据基础设施

原因：

- 医疗回答必须能追溯来源。
- Checker 需要审查 evidence，不只是看一段文本。
- 面试里“接了 Milvus”不够，需要讲 retrieval、evidence、audit、eval。

方法：

- `medical_kb_search/guideline_search` 返回 EvidenceRecord。
- Maker 输出顶层 evidence_records。
- Checker 和 Eval 消费 evidence_records。

#### Step 4: 给 ReAct 加运行时约束

原因：

- ReAct 的强项是动态工具调用。
- ReAct 的问题是 LLM 可能漏调关键工具。
- 医疗场景不能只靠 prompt 写“请优先调用风险评估”。

方法：

- Checker 内部加入 PreStopPolicy。
- 对症状、用药、报告、指南类问题设置 required-tool 检查。
- 预检失败直接 REJECT，不调用 LLM Checker。

#### Step 5: 把 Reviewer 升级为 Checker

原因：

- 普通 reviewer 只看答案质量，不看 Maker 是怎么得到答案的。
- 医疗 Agent 的风险往往在过程里：漏查证据、漏风险评估、误用 memory。

方法：

- Checker prompt 输入 process_trace、tool_trace、evidence_records。
- issue type 收敛为 TOOL_GAP、EVIDENCE_GAP、SAFETY_RISK、CONTEXT_GAP、OUTPUT_BOUNDARY。

#### Step 6: 去掉最终 LLM LeadAgent

原因：

- Maker 已经生成用户答案。
- Checker 和 SafetyGate 已经审查。
- 再调用 LLM 改写会增加延迟，也可能改变医学含义。

方法：

- ResponseRenderer 直接输出 Maker answer。
- 只有安全覆盖时使用固定模板。

#### Step 7: Memory 后置但认真做

原因：

- Memory 是 Agent 面试重点，但医疗 memory 高风险。
- 不能让 memory 成为医学证据。

方法：

- 用户授权写入。
- user_id 隔离。
- memory_context_lookup evidence 永远为空。
- Checker prompt 明确 memory 不能当医学证据。

#### Step 8: 用实验选择 Progressive Skill Loading

原因：

- 24 个 Skills 后，全量注入不可持续。
- 纯 LLM 选择慢，纯检索/关键词召回不足。

方法：

- 比较 6 种方案。
- 选择 S6 cluster hybrid。
- 实现本地 SkillResolver，并保留 LLM SkillSelectionPass 作为 fallback。

---

## 8. 质量与测试

当前测试覆盖：

```text
151 passed
```

覆盖模块：

- SkillIndex / SkillResolver
- AgentLoop skill loading
- Tool Visibility
- ToolSpec / ToolResult
- RAG tools / EvidenceService / Advanced RAG
- PreStopPolicy
- Checker semantic audit
- Orchestrator repair loop
- Memory
- EvalCase / TraceWriter

关键实验指标：

```text
S6_cluster_hybrid:
  avg_recall:          0.951
  avg_precision:       0.861
  safety_full_recall:  0.909
  avg_selected:        2.46
  token_proxy:         817
  p95_latency_ms:      0.081
```

质量思路：

```text
不是只测最终答案；
而是测 Router、Skill selection、Tool path、RAG evidence、Checker、Memory 和 SafetyGate 的过程。
```

---

## 9. 简历表达

### 9.1 推荐版

**Medical Maker-Checker Agent | 医疗健康智能体系统**  
`Python, LLM Function Calling, ReAct, RAG, Milvus, Hybrid Retrieval, Tool Calling, Guardrails, Memory, Eval`

- 构建医疗健康 Maker-Checker Agent，支持 `Router → Maker → Checker → SafetyGate → ResponseRenderer` 主链路，覆盖科普、症状、用药、报告、慢病和循证查询等场景。
- 实现 ReAct-like Maker Agent 与结构化工具调用体系，通过 `ToolResult` 和 Evidence Records 统一管理工具输出、RAG 证据、错误和审计信息。
- 将 RAG 升级为可审计证据链，支持 `source/year/score/evidence_type/citation`，并实现 hybrid retrieval、RRF 融合、轻量 rerank 和证据质量摘要。
- 设计 24 个医疗 `SKILL.md` 方法论模块，实现 `SkillResolver + Tool Visibility Control`，按需加载 2-4 个 Skills，降低上下文成本和工具误调用。
- 设计 Two-stage Checker，使用 PreStopPolicy 零 token 拦截 required tools 漏调、证据缺失和安全流程缺口，再由 LLM Checker 审查工具路径、证据支撑和医疗安全边界。
- 实现 Safe Memory、Eval Fixtures 和 JSONL Trace，覆盖 tool-call、RAG、Checker、Memory、SafetyGate 等核心模块；全量测试 `151 passed`，SkillResolver 实验达到 `0.951 recall`。

### 9.2 更短版

**Medical Maker-Checker Agent | 医疗健康智能体系统**  
`Python, ReAct, RAG, Milvus, Function Calling, Guardrails, Memory, Eval`

- 构建医疗健康 Maker-Checker Agent，Maker 自主调用医学工具生成证据化回答，Checker 独立审查工具路径、证据链和安全边界。
- 将 RAG 从文本拼接升级为 Evidence Records，并实现 hybrid retrieval、RRF、轻量 rerank 和 citation-aware evidence quality summary。
- 设计 24 个 `SKILL.md` 医疗方法论模块和本地 SkillResolver，按需加载 2-4 个 Skills，并用 Tool Visibility Control 减少工具误调用。
- 实现 PreStopPolicy + SafetyGate 双层 guardrail，分别拦截过程缺口和最终输出风险。
- 构建 Safe Memory、Eval Fixtures 和 JSONL Trace，全量测试 `151 passed`，SkillResolver 实验达到 `0.951 recall`。

---

## 10. 面试讲法

### 10.1 30 秒版本

这个项目最初是一个 ReAct-like 医疗 Agent，Maker 自主调用工具，Reviewer 做审查。复盘后我发现医疗场景最大风险不是模型不会回答，而是它可能漏掉关键工具、证据链不可审计、memory 被误当医学证据。所以我把系统升级成 Medical Maker-Checker Agent：Router 只做 simple/maker_checker 分流；Maker 通过 SkillResolver 渐进加载 24 个医疗方法论 Skills，并在 ReAct-like loop 中自主调用结构化工具；RAG 返回 Evidence Records；Checker 先用 PreStopPolicy 零 token 检查工具路径、证据路径和安全流程，再用 LLM 做语义审计；SafetyGate 最后做确定性输出兜底。

### 10.2 为什么不是工作流

我没有让 Router 输出具体 intent、skills 或 tools，因为那会让 Maker 退化成执行器。这个项目要展示的是 bounded agency：Maker 仍然自主调用工具，但系统用 PreStopPolicy 和 SafetyGate 保证医疗安全不变量。

### 10.3 为什么 Skills 用 Markdown

Skills 是方法论，不是函数。Markdown 适合写 checklist、red lines 和 tool notes，也适合 progressive disclosure。可执行逻辑放在 tools，医学证据放在 EvidenceRecords，安全硬约束放在 Checker 的 PreStopPolicy。

### 10.4 为什么 SkillResolver 不用 LLM

原来的 LLM SkillSelectionPass 合理但慢，而且对组合风险召回不稳。我做了 6 种方案对比，最后选择 cluster hybrid：少量高精度安全规则补齐组合风险，再用 cluster gating 和轻量检索选 2-4 个 Skills。这样保留小上下文，同时 safety recall 明显更高。

### 10.5 RAG 为什么是重点

普通 RAG 只是检索一段文本。我的设计是把 RAG 变成证据基础设施：每条 evidence 有 source、year、score、type 和 citation；Maker 的 claim 可以追溯；Checker 可以审证据是否支撑结论；Eval 可以统计 evidence quality。

### 10.6 Checker 和 SafetyGate 的区别

Checker 审过程和语义：工具有没有漏、证据够不够、有没有越界。SafetyGate 只审最终输出：如果高危症状却建议观察，就直接覆盖成 urgent care。一个可修，一个硬兜底。

### 10.7 如果问还有什么不足

我会说当前还有三个方向：

- Signal Catalog：当 Router、PreStopPolicy、SkillResolver 的医学信号规则继续扩大后，可以抽成共享规则源。
- 外部 Web evidence：当前主要是本地 KB，未来可以接医学来源白名单的 Web 检索。
- Claim-evidence alignment：当前 Checker 审 evidence，但还没有完整自动化 claim-level 对齐。

---

## 11. 待改进点

### 11.1 Signal Catalog / Rule Unification

当前 Router、PreStopPolicy、SKILL.md 里可能重复表达同一类医学信号，例如“胸痛/呼吸困难是高危症状”。目前规模可控，暂不抽象；当规则变多后，可以引入共享 Signal Catalog。

触发条件：

```text
Skills > 30
PreStopPolicy rules > 15
多处规则开始频繁不一致
```

### 11.2 Legacy Tools 彻底迁移

`.claude/skills/*/script` 仍有 legacy wrappers。未来可以逐步迁到 `tools/`，让目录结构更干净。

建议顺序：

```text
assess_risk -> risk_rule_check 完全替代或统一
recommend_lifestyle -> lifestyle structured tool
deep_research -> controlled web/evidence research tool
disease_code -> icd lookup tool
search_history/search_similar_cases -> memory_context_lookup
```

### 11.3 更强 RAG Eval

当前已有 fixtures 和轻量 report。未来可以增加：

- Hit@K / MRR
- context precision / context recall
- citation accuracy
- faithfulness
- stale evidence rate
- claim-evidence alignment

### 11.4 外部医学 Web 检索

当前不建议开放普通 web search。未来如果做，需要：

- 医学来源白名单
- citation 强制字段
- source quality rerank
- Checker 审查 web evidence 是否可靠

### 11.5 Latency Eval

当前已有 timing report。未来可以做批量 latency eval：

- p50 / p90 / p95 total latency
- Maker LLM latency
- tool latency
- deep_research trigger rate
- Checker reject rate
- SafetyGate override rate

### 11.6 UI / Streaming

不建议把 Maker draft 在 Checker 前直接流给用户。可以做：

- progress streaming：正在路由、检索、审查、安全门控。
- safe final streaming：Checker + SafetyGate 通过后流式输出最终答案。
- reasoning summary streaming：只输出可控摘要，不展示 raw thinking。

---

## 12. 最终总结

这个项目的主线可以概括为：

```text
从 LLM-driven tool calling
到 skill-aware, evidence-grounded, checker-guarded Agent runtime
```

核心价值不是“用了多个 Agent”，而是：

- Maker 保留自主工具调用能力。
- Skills 作为方法论渐进披露。
- Tools 返回结构化结果。
- RAG 变成可审计证据链。
- Checker 审查过程和语义。
- SafetyGate 确定性兜底最终输出。
- Memory 有隐私和证据边界。
- Eval/Trace 让 Agent 行为可解释、可回归。

这比普通医疗问答、普通 RAG、普通 ReAct demo 更适合写在 Agent 岗位简历里。
