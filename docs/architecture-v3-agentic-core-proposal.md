# Medical Maker-Checker Agent v3 架构方案

面向 Agent 岗位面试的最终方向：不是把项目做成固定医疗工作流，而是做成一个保留 Agent 自主性、同时具备证据链、运行时约束、独立审查和评估体系的医疗 Maker-Checker Agent。

---

## 项目功能与使用速览

### 这个项目是什么

这是一个面向医疗健康问答场景的 Maker-Checker Agent 系统。它不是单纯 RAG QA，也不是固定医疗工作流，而是一个带安全边界的 Agent runtime：

```text
Router 负责判断问题是否需要完整监督；
Maker 负责自主加载方法论、调用工具、综合证据；
Checker 负责审查 Maker 的工具路径、证据链和医疗安全；
SafetyGate 负责最终确定性安全兜底；
ResponseRenderer 负责确定性最终渲染：通过审查时直接返回 Maker 答案，安全覆盖时使用固定模板。
```

项目的目标不是替代医生，而是展示一个医疗 Agent 如何在开放问题中保持自主性，同时通过证据、审查和规则兜底降低风险。

### 当前支持的功能

| 功能 | 说明 |
|---|---|
| 医疗问题分流 | Router 将问题分成 `simple` 和 `maker_checker`，低风险科普走快速通道，高风险/个人医疗/用药/报告/治疗决策走 Maker-Checker。 |
| Progressive Skills | Maker 通过本地 `SkillResolver` 按需加载 `SKILL.md` 方法论文档，当前已有 24 个 Maker-facing Skills + 1 个 Checker Skill。 |
| ReAct-like Agent Loop | Maker 不是固定顺序执行，而是在 LLM 工具调用循环中根据观察结果继续调用工具或生成回答。 |
| Tool Visibility Control | AgentLoop 根据本轮 loaded skills 过滤 Maker 可见工具，减少无关 tool schema、降低误调慢工具的概率。 |
| 结构化医学工具 | 支持医学知识库检索、指南检索、药物安全查询、化验指标查询、风险规则检查、影像报告查询、生命体征查询、memory context 查询，以及 legacy 医疗工具 wrapper。 |
| RAG Evidence | RAG 不直接拼最终答案，而是返回可审计证据，包含来源、年份、片段、分数、证据类型和 citation 等信息。 |
| Two-stage Checker | Checker 先用 PreStopPolicy 做零 token 确定性预检，覆盖工具路径、证据路径和安全流程，再调用 LLM 做语义审计。 |
| SafetyGate | 最终输出前用确定性规则检查高危症状和 action 是否匹配，不依赖 LLM 自觉。 |
| Memory | 支持用户授权的长期记忆和会话记忆；memory 只作为用户上下文，不作为医学证据。 |
| Eval / Trace | 提供 tool-call、RAG、Checker、Memory fixtures 和轻量 eval report；支持 JSONL trace 记录关键过程。 |
| Timing Report | `python main.py` 会打印 Router、Agent 初始化、SkillResolver/SkillSelection、LLM、Tool、Checker、SafetyGate 和 Renderer 的耗时拆解，用于定位慢点。 |

### ResponseRenderer 和安全模板

v3 最终不再使用 LeadAgent 做 LLM 表达。原因是：Maker 已经生成面向用户的答案，Checker 和 SafetyGate 已经完成审查；最后再让一个 LLM 改写，既增加延迟，也可能改变已审查过的医学含义。

因此最终输出层改为确定性 `ResponseRenderer`：

| 终态 | 输出策略 |
|---|---|
| `simple` / `normal` | 直接返回 Maker answer，不做二次改写。 |
| `challenged` | 返回 Maker answer，并追加固定的不确定性提示。 |
| `gate_override` | 不返回 Maker answer，改用 SafetyGate 安全覆盖模板。 |
| `forced_safe` | 不返回 Maker answer，改用强制安全兜底模板。 |

这里的“安全模板”不是医学知识库生成的答案，而是代码中固定的兜底表达。它只在系统无法可靠排除风险、或 Maker 答案被安全门判定为不够安全时触发，核心话术是：

```text
目前无法可靠排除较高风险。基于安全原则，建议你尽快线下就医评估；
如果正在出现胸痛、呼吸困难、意识模糊、晕厥、严重出血等急症表现，
请立即联系急救或前往急诊。
```

这样做的边界很清楚：ResponseRenderer 不诊断、不新增医学结论、不重新综合证据，只负责在“通过审查”和“安全兜底”之间选择最终表达。

### 典型能处理的问题

```text
健康科普：CT 和 MRI 有什么区别？
症状分诊：我胸痛、呼吸困难，现在怎么办？
用药安全：布洛芬和华法林能一起吃吗？
检查报告：尿酸 520 严重吗？需要复查吗？
慢病生活方式：高血压能喝咖啡吗？
循证研究：某个疾病最新指南怎么建议？
心理安全：我不想活了怎么办？
```

### 使用到的技术

| 技术模块 | 项目中的作用 |
|---|---|
| LLM function calling | Maker / Checker 通过工具调用循环执行医学工具。 |
| ReAct-like Loop | 保留 Agent 的动态决策能力，而不是把问题写死成 workflow。 |
| Markdown Skills | 用 `SKILL.md` 写领域方法论、checklist 和 red lines，支持渐进式披露。 |
| SkillResolver | 用高精度安全组合规则 + cluster gating + 轻量检索选择 2-4 个相关 Skills，替代默认 LLM SkillSelection 耗时路径。 |
| Tool Visibility Policy | 根据 loaded skills 过滤 OpenAI function schema，保留 Agent 自主选工具但减少无关工具暴露。 |
| Structured ToolResult | 工具返回结构化结果，方便 Maker 综合、Checker 审查和 Eval 统计。 |
| RAG + Milvus | 本地医学知识库检索；EvidenceService 负责证据标准化。 |
| Hybrid Retrieval / Rerank | 支持 dense + keyword 检索融合、轻量重排和证据质量摘要。 |
| Deterministic Policy | PreStopPolicy 审过程安全，SafetyGate 审最终输出安全，用代码规则兜底关键医疗风险。 |
| Maker-Checker | Maker 生成，Checker 独立审查，失败可返修。 |
| Memory Service | 用户授权记忆、按用户隔离检索、敏感记忆默认不返回。 |
| Eval Fixtures | 用 JSONL fixtures 评估 required-tool、RAG evidence、Checker seeded bad cases 和 memory。 |

### 如何运行

#### 运行环境

| 环境项 | 支持情况 |
|---|---|
| 操作系统 | Windows / macOS / Linux 均可；当前开发和测试环境是 Windows + PowerShell。 |
| Python | 推荐 Python 3.11 或 3.12；代码最低应使用 Python 3.10+，因为项目使用了 `dict | None` 等现代类型语法。 |
| 当前验证版本 | 本机已在 Python 3.13.5 下通过单元测试；但 `torch`、`sentence-transformers`、`pymilvus` 等重依赖在 3.11/3.12 生态更稳。 |
| 包管理 | 使用 `pip install -r requirements.txt`。建议使用虚拟环境，避免和全局 Conda / Anaconda 依赖冲突。 |
| LLM API | 需要 OpenAI-compatible API；`.env.example` 默认按 DeepSeek 兼容接口配置。 |
| 向量库 | RAG 完整能力依赖 Milvus / pymilvus；单元测试不要求真实 Milvus。 |
| GPU | 不是必需；如果本地加载 embedding / sentence-transformers，GPU 可提升速度。 |

1. 安装依赖：

```bash
pip install -r requirements.txt
```

2. 配置环境变量：

```bash
cp .env.example .env
```

PowerShell：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写至少：

```text
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL_NAME=
```

项目也支持按角色配置模型，例如 Router 用更快的分类模型，Maker/Checker 用更强的推理模型：

```text
ROUTER_LLM_MODEL_NAME=
SKILL_SELECTOR_LLM_MODEL_NAME=
GENERATOR_LLM_MODEL_NAME=
REVIEWER_LLM_MODEL_NAME=
```

推荐的低延迟角色拆分：

```text
Router:         qwen-flash / deepseek-v4-flash
SkillResolver:  本地规则/检索，无 LLM；仅回退到 SkillSelectionPass 时才用 qwen-flash
Maker:          deepseek-v4-pro（质量优先）或 qwen-plus（速度优先）
Checker:        qwen-plus（稳定审查）或 qwen-max（质量优先）
ResponseRenderer: 不调用 LLM；normal/simple 直接返回 Maker answer，安全终态使用固定模板
```

3. 启动交互式问答：

```bash
python main.py
```

详细日志：

```bash
python main.py -v
```

交互命令：

```text
exit / quit / q  退出
clear            清屏
```

4. 运行测试：

```bash
pytest -q tests
```

当前全量测试结果：

```text
151 passed
```

### 耗时观测

交互式运行时，`python main.py` 会在答案前输出耗时拆解：

```text
耗时拆解:
  total:              总耗时
  router:             路由耗时
  agent_init:         Agent / Tool 注册初始化耗时
  generator_loop:
    skill_select:     SkillResolver 或 LLM SkillSelectionPass 耗时
    llm_total:        Maker LLM 总耗时
    tools_total:      Maker 工具总耗时
      tool xxx:       单个工具耗时
  checker:
    prestop:          PreStopPolicy 零 token 预检耗时
    llm_audit:        Checker LLM 审查耗时
  safety_gate:        最终确定性安全门耗时
  response_renderer:  确定性最终渲染耗时
```

这部分不是业务逻辑，而是可观测性。它用于回答“为什么慢”：如果 `tool medical_kb_search` 很慢，多半是 RAG / Milvus / embedding 加载；如果 `skill_select` 慢，要看当前走的是本地 SkillResolver 还是回退的 LLM SkillSelectionPass；如果 `checker.llm_audit` 慢，说明 Checker 模型或 prompt 太重。

### 响应时间优化规划

当前耗时观测显示，真正需要优先压缩的是 `llm_total`，其次才是个别慢工具。例如一次 simple 查询中：

```text
total:       95.80s
router:       7.44s
llm_total:   46.19s
tools_total: 38.81s
deep_research: 37.77s
```

另一轮不触发 `deep_research` 时：

```text
total:      41.07s
llm_total: 35.98s
tools:      0.27s
```

这说明优化不能只停留在“工具慢”或“RAG 慢”，主线应该是：

```text
减少 LLM 每轮看到的上下文
减少 LLM 轮数
减少不必要 tool schema
减少慢模型/大 max_tokens 的使用
避免 simple 问题误触发 deep_research
```

#### 1. 模型与角色配置

目标是按角色使用不同速度/能力模型，而不是所有阶段都用同一个重模型。

| 角色 | 推荐策略 | 原因 |
|---|---|---|
| Router | qwen-flash / deepseek-flash，non-thinking | 只做分流，必须快。 |
| SkillResolver | 本地规则/检索，无 LLM | 用 `cluster_hybrid_v1` 选择 2-4 个 SKILL.md，避免额外 LLM 调用。 |
| Maker Round 1 | qwen-plus / deepseek-chat / deepseek-v4-pro non-thinking | Maker 是主耗时来源，第一轮默认不应开 thinking。 |
| Maker Repair | deepseek-v4-pro thinking / qwen-max | 只有 PreStop 或 Checker 明确 REJECT 后才升级推理预算。 |
| Checker | qwen-plus 低温；高风险审查可切 qwen-max | Checker 要稳定挑错，但不一定每轮都用最慢模型。 |
| ResponseRenderer | 不调用 LLM | 正常路径直接返回 Maker answer。 |

Generator 配置需要显式检查：

```text
GENERATOR_LLM_DISABLE_THINKING=true
GENERATOR_LLM_MAX_TOKENS=1800~2200
GENERATOR_REPAIR_LLM_DISABLE_THINKING=false
GENERATOR_REPAIR_LLM_MAX_TOKENS=3000
```

如果 Maker 仍然 30s+，优先怀疑：

```text
thinking 未真正关闭
max_tokens 太大
模型本身吞吐慢
prompt/tool schema 太长
```

Maker 的推理预算策略是：

```text
Round 1:
  generator profile
  默认 non-thinking
  目标是快速给出可审查 draft

Checker / PreStop REJECT:
  regenerate()
  临时切到 generator_repair profile
  可以使用 thinking / strong model
  修复完成后恢复 generator profile
```

这个设计把 thinking 变成“被审查触发的修复资源”，而不是每轮默认消耗。它比 Router 提前猜复杂度更稳：如果 Maker 的输出真的不合格，Checker 会用确定性预检或 LLM 审查把它打回；只有这时才付出高推理成本。

#### 2. Tool Visibility Control

目前 Maker 每轮可能看到过多工具 schema。即使最终不调用，LLM 也要读这些描述并做选择，会增加输入 token 和决策成本。

优化方向：

```text
SkillResolver -> loaded_skills -> allowed tool subset
```

示例：

| loaded skill | 可见工具 |
|---|---|
| health_education | `medical_kb_search` |
| symptom_triage | `assess_risk`, `medical_kb_search`, `guideline_search` |
| medication_safety | `drug_safety_lookup`, `medical_kb_search` |
| lab_report | `lab_reference_lookup`, `medical_kb_search` |
| guideline_research / evidence_comparison | `guideline_search`, `medical_kb_search`, `deep_research` |

这不是固定 workflow。Agent 仍然自己选择工具，只是运行时不把无关工具暴露给它。收益：

```text
减少 tool schema token
减少误调 deep_research
减少 LLM 选择成本
提升 tool-call precision
```

#### 3. AgentLoop 轮数控制

ReAct-like loop 必须保留，但要限制不必要的多轮。

建议规则：

```text
max_tool_calls: simple 1~2，maker_checker 2~3
max_iterations: simple 2~3，maker_checker 3~4
工具已返回有效 evidence 后，下一轮优先 final
如果 tool_calls 连续失败，不再继续检索，要求 final 或澄清
```

后续可以在 AgentLoop 中加入轻量 stop heuristic：

```text
if evidence_records 非空 and required tool 已满足:
    追加 system/user reminder: “请基于已有证据给出最终回答，不要继续调用工具。”
```

这仍然保留 Agent 自主性，但减少“查了还想查”的循环。

#### 4. Prompt 与上下文压缩

LLM 慢常常不是模型单点问题，而是上下文太大。

应压缩：

```text
Generator system prompt
SKILL.md 注入内容
tool schema 描述
tool result observation
RAG evidence 展示字段
```

原则：

```text
给 Maker 的证据 = title/year/snippet/evidence_type/citation
给 Checker 的证据 = 完整 EvidenceRecord
给 trace/eval 的证据 = 完整 metadata
```

也就是说，Maker 不一定需要看到 `chunk_id/score/metadata` 等完整对象；这些可以保留给 Checker 和 trace。

#### 5. RAG 与工具冷启动

如果耗时集中在：

```text
tool medical_kb_search
tool guideline_search
Loading weights
```

优化方向是：

```text
应用启动时预热 embedding/reranker
MedicalKnowledgeBase 单例懒加载后复用
Milvus client / collection handle 复用
首轮 query 前做一次轻量 warmup
deep_research 默认禁用，只有 guideline_research / evidence_comparison 或明确“最新/指南/研究”才暴露
```

特别注意：`deep_research` 不是普通 RAG 工具，应该视为慢速外部研究工具。它适合：

```text
最新指南
复杂方案比较
循证研究问题
```

不适合：

```text
基础健康科普
低风险生活问题
简单设备/检查区别
```

#### 6. Simple 路径的边界

simple 路径不是“不安全地快”，而是“低风险下少做不必要步骤”。

simple 优化目标：

```text
Router: 0.5~1.5s
SkillResolver: ~0s
Maker LLM: 3~8s
Tool: 0~2s
Total: 5~12s
```

maker_checker 优化目标：

```text
Maker: 8~20s
Checker precheck: ~0s
Checker LLM: 3~8s
SafetyGate/Renderer: ~0s
Total: 15~35s
```

#### 7. Eval 指标

响应时间优化不能只看平均耗时，还要防止质量下降。

建议增加 latency eval：

```text
p50 / p90 / p95 total latency
p50 / p90 llm_total
tool-call count distribution
deep_research trigger rate
required-tool recall
SafetyGate override rate
Checker reject rate
```

判断一个优化是否可接受：

```text
latency 降低
required-tool recall 不下降
SafetyGate override 不异常上升
Checker seeded bad case 命中率不下降
RAG evidence hit rate 不下降
```

#### 8. 推荐实施顺序

第一优先级：

```text
1. 确认 Generator / Reviewer thinking 是否真正关闭
2. 下调 Generator max_tokens 到 1800~2200
3. 打印每轮 LLM 耗时和 token 使用量（如果供应商返回 usage）
4. 根据 loaded_skills 做 tool visibility control
```

第二优先级：

```text
5. 压缩 tool schema 和 tool result observation
6. evidence 足够后引导下一轮 final
7. deep_research 只在 guideline_research / evidence_comparison 或明确最新/指南/研究问题中暴露
8. RAG/embedding/reranker warmup
```

第三优先级：

```text
9. 建 latency eval report
10. 对 simple/maker_checker 分别设 p50/p90 目标
11. 做模型 A/B：qwen-plus vs deepseek-chat vs qwen-max
```

面试叙事可以这样讲：

> 我没有简单把 Agent 改成 workflow 来追求速度，而是做了可观测的 Agent runtime 优化：先用 timing report 定位 Router、SkillResolver、LLM、Tool、Checker 的耗时，再用 role-based model routing、tool visibility control、prompt/context compression 和 loop stop heuristic 降低延迟，同时用 required-tool recall、RAG hit rate 和 Checker seeded eval 防止速度优化牺牲医疗安全。

#### 9. 流式输出的边界

流式输出可以优化体感，但不能破坏 Maker-Checker 的安全边界。

不建议做：

```text
把 Maker draft 在 Checker / SafetyGate 前直接流给用户
把模型 raw thinking / reasoning_content 原样流给用户
```

原因：

```text
Maker draft 还没经过 Checker 和 SafetyGate，可能包含未审查的医疗建议。
raw thinking 不是稳定产品输出，可能包含中间错误、废弃假设或供应商私有推理格式。
```

推荐做：

```text
1. Progress streaming
   - 正在路由
   - 正在选择 Skills
   - 正在检索医学知识
   - 正在进行 Checker 预检
   - 正在进行安全门控

2. Safe final streaming
   - Checker + SafetyGate 通过后，再把最终 answer 流式展示

3. Reasoning summary streaming
   - 不展示 raw thinking
   - 展示可控摘要，例如“正在比较影像检查适用场景”“正在核对药物相互作用”
```

所以当前优先级不是先做 token streaming，而是先把 `llm_total` 降下来。等 Maker Round 1 non-thinking、repair thinking 和 tool visibility control 落地后，再考虑给 CLI / Web UI 加进度流。

5. 运行轻量 eval report：

```powershell
python -m evals.run_evals `
  evals/tool_call_cases.jsonl `
  evals/rag_cases.jsonl `
  evals/checker_seeded_cases.jsonl `
  evals/memory_cases.jsonl
```

PowerShell 也可以写成一行：

```powershell
python -m evals.run_evals evals/tool_call_cases.jsonl evals/rag_cases.jsonl evals/checker_seeded_cases.jsonl evals/memory_cases.jsonl
```

### 当前实现边界

- 本项目是医疗健康 Agent 架构演示，不提供真实诊断或治疗承诺。
- RAG 证据依赖本地知识库内容质量；没有证据时，系统应降低置信度或建议就医/咨询专业人士。
- Memory 只用于个性化上下文，不能作为医学证据。
- Signal Catalog、MCP wrapping、完整外部 Web 医学检索属于未来可选扩展，不是当前主链路必要条件。

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
    - safety-process check
    - 不依赖 Maker 自报
  - LLM adversarial audit
    - tool path audit
    - evidence audit
    - medical safety audit
  ↓
SafetyGate
  - deterministic final guard
  ↓
ResponseRenderer
  - deterministic final rendering
  - normal/simple: return Maker answer
  - gate_override/forced_safe: safety template
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
    degraded_reason: str | None
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
    - AgentLoop runs internal SkillResolver
    - AgentLoop injects 2-4 selected SKILL.md
    - AgentLoop filters visible tools by loaded_skills
    - performs ReAct-like tool calling
    - collects structured ToolResult + RAG evidence
    - produces draft_answer + action_signal + trace
    |
    v
Checker Agent
    - deterministic precheck: PreStopPolicy
      - 输入: user_query, route_decision.triggers, tool_trace, evidence, action_signal
      - 检查 Tool Path / Evidence Path / Safety Process
      - 不通过: 返回 REJECT + typed reject_type，不调用 LLM
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
ResponseRenderer
    - deterministic final rendering
    - 不调用 LLM，不改写已通过审查的 Maker 答案
    |
    v
Final Answer
```

注意：`SkillResolver` 是 Maker/AgentLoop 内部的上下文准备模块，不是 Router 后面的独立 pipeline 节点。它不替 Router 分流，也不替 Maker 生成答案；安全约束由 Checker 内部的 PreStopPolicy 独立执行。PreStopPolicy 是独立代码模块，但不是独立 pipeline 节点。

---

## 4. 术语边界

### 4.1 Skills

Skills 是给 Maker/Checker 看的领域方法论，不是可执行函数，也不是安全硬约束唯一来源。

推荐形态：

```text
skills/
  symptom_triage/SKILL.md
  emergency_red_flags/SKILL.md
  medication_safety/SKILL.md
  drug_interaction/SKILL.md
  lab_report/SKILL.md
  imaging_report/SKILL.md
  ecg_vital_signs/SKILL.md
  health_education/SKILL.md
  guideline_research/SKILL.md
  evidence_comparison/SKILL.md
  chronic_care/SKILL.md
  memory_personalization/SKILL.md
  ...
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
  - assess_risk
  - medical_kb_search
  - guideline_search
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

Frontmatter 只做 SkillResolver 检索和工具提示，不作为 PreStopPolicy 的唯一硬约束来源。硬约束放在 Checker 内部持有的独立 policy 中。

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
- Tool Path Audit: required tools 是否被调用（报告类 → lab_reference_lookup，指南类 → guideline_search / medical_kb_search 等）
- Evidence Path Audit: Maker 是否声称高置信但没有收集任何 evidence，或 action_signal 缺失
- Safety Process Audit: 高危症状、心理危机、高风险用药等场景是否走过必要安全流程
```

不通过时：Checker 直接返回 **REJECT**，并按缺口类型给出 `reject_type`：

```text
NEED_MORE_TOOL_USE   -> 工具路径缺口
NEED_MORE_EVIDENCE   -> 证据路径缺口
SAFETY_PROCESS_GAP   -> 安全流程缺口
```

这一轮不调用 LLM Checker。返修后 Reviewer.review() 会重新从 PreStopPolicy 开始检查；仍不满足时，由 Orchestrator 走 **FORCED_SAFE**。

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

两者不交叉检查同一件事。PreStopPolicy 里的安全检查是“过程安全”：

```text
高危问题有没有走必要安全流程？
```

SafetyGate 是“输出安全”：

```text
最终 proposed_action 是否和风险匹配？
```

因此 `胸痛 + 没调 assess_risk` 由 PreStopPolicy 返修，`胸痛 + action=observe` 由 SafetyGate 硬覆盖。

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
Maker receives user_query
-> AgentLoop runs SkillResolver (cluster_hybrid_v1)
-> SkillResolver selects 2-4 SKILL.md
-> AgentLoop injects selected SKILL.md
-> ToolVisibilityPolicy filters visible tools
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

当前实现已经从“LLM 读取 Skill Index 再选择”升级为本地 `SkillResolver`：

```text
user_query
  -> safety implication rules
  -> cluster gating
  -> lightweight retrieval top-k
  -> selected_skill_ids
  -> AgentLoop injects selected SKILL.md
```

这一步仍然不是 Router 决策，也不是 workflow 固定流程。Router 只负责 `simple / maker_checker`；SkillResolver 只负责为 Maker 准备方法论上下文，Maker 后续仍在 ReAct-like loop 中自主选择工具和生成答案。

SkillResolver 的输出会写入 `process_trace.skill_selection.resolver`：

```python
SkillResolution:
    selected_skill_ids: list[str]
    safety_implied_skill_ids: list[str]
    clusters: list[str]
    scores: dict[str, float]
    reasons: list[str]
    resolver_version: "cluster_hybrid_v1"
```

为什么这样改：

```text
- LLM SkillSelectionPass 多一次 LLM 调用，影响响应速度。
- 单纯 top-k 检索在组合医疗风险上召回不足。
- 高精度 safety implication rules 能补齐“孕妇 + 发热 + 用药”“胸痛 + 呼吸困难”等组合场景。
- cluster gating 让 Skills 扩展到 24 个后仍能保持小上下文。
```

旧的 LLM SkillSelectionPass 仍保留为回退策略：当 `skill_selection_strategy` 未设置为 `cluster_hybrid` / `hybrid_resolver` / `resolver` 时，AgentLoop 继续使用原来的 LLM 选择流程。

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
AgentLoop:
    SkillResolver.resolve(user_query, skill_docs) -> SkillResolution
    load_skill_context(skill_ids: list[str]) -> list[SkillDoc]
```

含义：

```text
普通 Tool:
  assess_risk
  medical_kb_search
  drug_safety_lookup
  返回 ToolResult，作为 observation 进入对话

Skill loading:
  读取 SKILL.md
  由 AgentLoop 注入 system/context
  只记录 loaded_skills，不记录为 tool_call
```

这点实现上很重要：Skill loading 只是让 Maker 获得更多方法论上下文，不是 tool execution。

### 5.4 Tool Visibility Control

当前 AgentLoop 在注入 SKILL.md 后，会根据 `loaded_skills` 过滤 Maker 可见工具：

```text
loaded_skills -> ToolVisibilityPolicy -> visible OpenAI function schemas
```

示例：

| loaded skills | visible tools |
|---|---|
| `health_education` | `medical_kb_search`, `assess_risk` |
| `symptom_triage`, `emergency_red_flags` | `assess_risk`, `risk_rule_check`, `medical_kb_search`, `guideline_search`, `analyze_symptoms` |
| `medication_safety`, `drug_interaction` | `drug_safety_lookup`, `medical_kb_search`, `guideline_search` |
| `imaging_report` | `imaging_reference_lookup`, `medical_kb_search`, `guideline_search` |
| `ecg_vital_signs` | `vital_sign_reference_lookup`, `assess_risk`, `medical_kb_search`, `guideline_search` |
| `memory_personalization` | `memory_context_lookup` + 当前问题相关医学工具 |

这不是 workflow。Maker 仍然自己选择工具；系统只是减少无关工具 schema，降低误调 `deep_research` 等慢工具的概率。若没有 loaded skills 或过滤后为空，策略会回退为原工具列表，避免过度过滤。

### 5.5 PreStopPolicy 的落点

统一叫 `PreStopPolicy`，但第一版不把它做成独立 pipeline 节点，也不把它暴露成普通 tool。它运行在 `Reviewer.review()` 内部，是 Checker 的第一阶段：

```text
Maker draft/action_signal/evidence 生成后
-> Reviewer.review()
   -> PreStopPolicy.before_review()
      - Tool Path Audit
      - Evidence Path Audit
      - Safety Process Audit
   -> 预检失败: 直接返回 REJECT + typed reject_type，不调用 LLM
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

当前已经落地 24 个 Maker-facing Skills + 1 个 Checker 专用 Skill。Skill 的粒度不是按疾病名堆数量，而是按处理方法、工具路径和安全边界划分。

### 6.1 Maker-facing Skills

| Skill | 适用场景 | 说明 |
|---|---|---|
| `symptom_triage` | 身体不适、症状严重程度、是否就医 | 强调症状分层、红旗识别和就医边界 |
| `emergency_red_flags` | 急症红旗、急诊/急救边界 | 胸痛、呼吸困难、昏厥、意识异常等高危信号 |
| `mental_health_safety` | 自杀、自残、伤害他人风险 | 先关注即时安全，不输出自伤细节 |
| `clarifying_questions` | 信息不足、背景不完整 | 提出关键追问，不强行诊断 |
| `care_navigation` | 挂什么科、急诊还是门诊、复诊 | 给安全就医路径，不替代线下分诊 |
| `medication_safety` | 漏服、停药、剂量、副作用、过敏 | 强调用药调整边界 |
| `drug_interaction` | 多药同服、相互作用、重复成分 | 强调用药组合风险 |
| `renal_liver_dose_safety` | 肝肾功能异常、特殊剂量风险 | 不给处方剂量调整 |
| `pregnancy_pediatric_safety` | 孕期、哺乳期、儿童、婴幼儿 | 特殊人群更保守 |
| `geriatric_safety` | 老年人、跌倒、多病共存、多药共用 | 降低老年风险漏判 |
| `lab_report` | 化验单、指标异常、复查 | 强调单位、参考范围和上下文 |
| `imaging_report` | CT/MRI/超声/X 光报告、结节 | 区分影像发现和最终诊断 |
| `ecg_vital_signs` | 心电图、血压、血氧、心率 | 读数异常结合症状判断 |
| `guideline_research` | 指南、共识、诊疗规范、推荐等级 | 强调来源、年份、机构 |
| `evidence_comparison` | 检查/药物/治疗方案比较 | 比较收益、风险、适用人群和证据强度 |
| `source_quality_appraisal` | 来源质量、年份、证据强弱 | 不伪造证据等级或 coverage |
| `health_education` | 医学概念、检查原理、健康科普 | 区分科普和个人医疗建议 |
| `preventive_care` | 筛查、疫苗、体检、预防 | 强调适用人群和禁忌 |
| `medical_device_explainer` | 家用设备、可穿戴、读数可信度 | 解释设备但不忽略异常读数风险 |
| `chronic_care` | 高血压、糖尿病、高尿酸等慢病长期管理 | 不用生活方式替代处方随访 |
| `lifestyle_coaching` | 饮食、运动、睡眠、咖啡、饮酒 | 可执行、温和、长期建议 |
| `nutrition_weight_management` | 减脂、控糖、控盐、营养搭配 | 不推荐极端节食或补剂 |
| `rehabilitation_exercise_safety` | 康复训练、运动损伤、疼痛恢复 | 先排除运动/外伤红旗 |
| `memory_personalization` | 用户授权记忆、病史、偏好、过敏史 | memory 只作上下文，不作医学证据 |

### 6.2 Checker Skill

| Skill | 说明 |
|---|---|
| `checker_adversarial` | Checker 专用审查方法论，审计 Maker 的工具路径、证据链、上下文缺口和医疗安全边界 |

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

### 6.3 SkillLoader 改造边界

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
SkillRegistry 作为当前 function-calling adapter 只处理可执行函数；
AgentLoop 负责把选中的 SkillDoc 注入上下文。
```

不要让 `SkillLoader` 同时做 Markdown 方法论加载和 Python function tool 注册，否则 v3 会重新退回 skills/tools 混乱。

---

## 7. Tools 设计与目录迁移

### 7.1 当前已实现 Tools

当前 `tools/` 目录已经落地的现代结构化工具：

| Tool | 来源 | 目标 |
|---|---|---|
| medical_kb_search | 从 `search-knowledge` 改造 | 返回 evidence records |
| guideline_search | 从 `clinical-guideline` 改造 | 返回指南/共识 evidence |
| lab_reference_lookup | 新增 | 常见指标解释和参考范围 |
| drug_safety_lookup | 新增 | 药物相互作用、禁忌、特殊人群 |
| memory_context_lookup | 新增 | 只返回用户上下文，不作为医学证据 |
| risk_rule_check | 新增 | 确定性红旗规则检查，返回 risk_level / matched_rules / recommendation |
| imaging_reference_lookup | 新增 | 影像报告术语、CT/MRI/超声/X 光、结节和随访边界 |
| vital_sign_reference_lookup | 新增 | 血压、血氧、心率、体温、心电图文字和风险边界 |

仍通过 `.claude/skills` legacy wrapper 暴露、但语义上属于工具的能力：

| Tool | 当前状态 |
|---|---|
| assess_risk | PreStopPolicy 症状类 required tool，仍由 legacy wrapper 注册 |
| analyze_symptoms | 仍由 legacy wrapper 注册 |
| recommend_lifestyle | 仍由 legacy wrapper 注册 |
| deep_research | 仍由 legacy wrapper 注册 |
| disease_code | 仍由 legacy wrapper 注册 |

未来可选工具：

| Tool | 目标 |
|---|---|
| renal_liver_dose_lookup | 肝肾功能异常下的剂量风险和用药注意事项 |
| pregnancy_pediatric_safety_lookup | 孕期、哺乳期、儿童用药/症状安全证据 |
| vaccine_schedule_lookup | 疫苗接种年龄、禁忌、补种和筛查指南 |
| clinical_calculator | BMI、eGFR、ASCVD 等常用计算器 |
| web_research_search | 医学 Web 检索 |
| evidence_rerank | 对 evidence records 重排 |
| icd10_lookup | ICD-10 查询 |
| calculator | BMI、单位换算、基础计算 |
| ask_followup | 生成澄清问题，不是最终回答 |

### 7.2 Tools 为什么要搬目录

最终应该搬。因为 `.claude/skills/*/script/*.py` 看起来是 Skills，实际上是 Tools。

对面试项目来说，目录结构本身就是架构表达：

```text
skills/      -> SKILL.md，方法论和渐进式披露
tools/       -> 可执行函数/API
knowledge/   -> RAG、Milvus、证据归一化
core/        -> agent loop、function-calling adapter、PreStopPolicy、trace
agents/      -> maker、checker
pipeline/    -> router、orchestrator、safety gate、response renderer
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
  定义 ToolSpec、ToolResult
  旧 .claude/skills 继续作为 legacy

Step 2:
  从旧 script 里抽逻辑到 tools/
  旧 script 改成 thin wrapper，调用新 tools/

Step 3:
  AgentLoop 通过当前 SkillRegistry adapter 同时暴露 legacy wrappers 和 structured tools
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

v3.6 已补齐的高级 RAG 能力：

- dense + keyword hybrid retrieval
- Reciprocal Rank Fusion
- lightweight rerank
- evidence quality summary
- memory_context 防误用检查

仍然暂缓的能力：

- web research evidence：需要外部搜索源和医学来源白名单，先不接入。
- claim-evidence alignment：需要稳定的 claim extractor 和人工/seeded eval，后续再做。
- GraphRAG：适合大规模医学知识图谱，不适合当前项目第一阶段数据规模。

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
或者 Maker 面对高风险场景但没有走必要安全流程。
```

Checker 被设计成 two-stage auditor：

```text
Stage 1: deterministic precheck
  组件: PreStopPolicy
  成本: 0 token
  职责: 拦截工具路径、证据路径、安全流程上的确定性过程缺口

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
    tool_trace: list[ToolResult]  # 来自 MakerOutput.process_trace["tool_trace"]
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
| before_final | 未来 AgentLoop stop hook 预留 | user_query, route_decision, tool_trace | required tools 是否漏调；高风险场景是否缺安全流程 |
| before_review | Reviewer.review() 内部，LLM Checker 调用前 | draft_answer, evidence, action_signal, tool_trace | Tool Path Audit、Evidence Path Audit、Safety Process Audit |

注意：`before_review` 中 evidence 为空+高置信的检查只在 Checker precheck 阶段处理（过程问题，可修）。SafetyGate 不重复此检查。

### 9.3 规则示例

```python
PreStopRule:
    name: "high_risk_symptom_requires_risk_assessment"
    patterns: ["胸痛", "呼吸困难", "昏厥", "剧烈头痛", "单侧无力"]
    required_tools: ["assess_risk"]
    issue_type: "SAFETY_PROCESS_GAP"
    audit_scope: "safety_process"
    repair_instruction: "必须先做风险评估"

PreStopRule:
    name: "mental_health_crisis_requires_safety_assessment"
    patterns: ["自杀", "自残", "不想活", "伤害自己"]
    required_tools: ["assess_risk"]
    issue_type: "SAFETY_PROCESS_GAP"
    audit_scope: "safety_process"
    repair_instruction: "必须先触发安全评估流程"

PreStopRule:
    name: "medication_safety_requires_drug_lookup"
    patterns: ["能一起吃吗", "相互作用", "漏服", "副作用", "禁忌", "华法林", "胰岛素", "孕妇"]
    required_tools: ["drug_safety_lookup"]
    issue_type: "SAFETY_PROCESS_GAP"
    audit_scope: "safety_process"
    repair_instruction: "必须先查证药物安全信息"

PreStopRule:
    name: "lab_report_requires_reference_lookup"
    patterns: ["化验单", "报告", "尿酸", "白细胞", "肌酐", "血糖"]
    required_tools: ["lab_reference_lookup"]
    issue_type: "TOOL_GAP"
    audit_scope: "tool_path"
    repair_instruction: "必须先查证指标参考含义"

PreStopRule:
    name: "evidence_research_requires_retrieval"
    patterns: ["指南", "最新证据", "循证", "治疗方案"]
    any_of_tools: ["guideline_search", "medical_kb_search"]
    issue_type: "TOOL_GAP"
    audit_scope: "tool_path"
    repair_instruction: "必须先获取医学证据"
```

第一版只做高精度规则，不追求覆盖所有医疗意图。宁可先保证关键风险场景不漏。

### 9.4 行为

```text
PASS:
  继续调用 LLM Checker

REJECT:
  Checker 不调用 LLM，直接把 PreStopIssue 转成 challenges 退回 Maker
  reject_type:
    NEED_MORE_TOOL_USE   -> 普通工具路径缺口
    NEED_MORE_EVIDENCE   -> 证据路径缺口
    SAFETY_PROCESS_GAP   -> 安全流程缺口

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
  用它检查是否必须调用 assess_risk
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
    - assess_risk
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
    process_trace
      - loaded_skills
      - tool_trace
      - tool_summary
      - skill_selection
    evidence_records
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
症状类 100 条 -> assess_risk recall
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
漏调 assess_risk
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
  "process_trace": {
    "loaded_skills": ["symptom_triage"],
    "tool_trace": [],
    "tool_summary": []
  },
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
- 每个模块只负责一件事：SkillDocLoader 不注册工具，SkillRegistry adapter 不读 SKILL.md
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
- 让 Maker 能从 `tool_results` 中提取顶层 `evidence_records`，同时在 `ActionSignal` 中只保留 `evidence` 摘要和 `evidence_ids` 引用。

为什么先做这一阶段：

RAG 是医疗 Agent 简历里最容易被追问的能力。只说“接了 Milvus”不够，必须能说清楚：

```text
retrieval -> evidence record -> Maker grounding -> Checker audit -> eval
```

所以 v3.1 的目标不是“加几个文件”，而是把 RAG 做成可被下游 Agent 审计的证据基础设施。

最终 Maker 输出契约：

```python
MakerOutput = {
    "user_query": str,
    "answer": str,
    "action_signal": {
        "result": str,
        "evidence": list[str],      # 给 SafetyGate/ResponseRenderer/用户侧表达使用的短摘要
        "evidence_ids": list[str],  # 指向顶层 evidence_records 的证据引用
        "confidence": float,
        "proposed_action": str,
    },
    "evidence_records": list[EvidenceRecord],  # 完整结构化证据，只放顶层
    "process_trace": {
        "loaded_skills": list[str],
        "tool_trace": list[dict],
        "tool_summary": list[dict],
        "skill_selection": dict,
    },
}
```

设计约束：不再保留顶层 `loaded_skills/tool_trace/skill_trace` 兼容字段，也不再把完整 `evidence_records` 复制进 `action_signal`。旧模块应迁移到新契约，而不是让新旧字段长期并存。

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
  - 功能：Maker 从 `tool_results` 中提取顶层 `evidence_records`，同时把 evidence record 压缩成短文本摘要合并进 `ActionSignal.evidence`，并在 `ActionSignal.evidence_ids` 中保存证据引用。
  - 原因：完整证据实体应该只在顶层保存，方便 Checker/Eval 审计；`ActionSignal` 只表达最终结论、动作、置信度和证据摘要，避免同时承担过程日志或证据实体存储职责。
  - 最终契约：不再保留 `action_signal["evidence_records"]`；下游模块统一读取顶层 `result["evidence_records"]` 和 `action_signal["evidence_ids"]`。
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
  - 功能：当语义层不可用时，同步 `route()` 保持 `source="rule"`，同时返回 `degraded=True` 和 `degraded_reason="semantic_unavailable"`。
  - 原因：`source` 应只表示谁做出路由决策；降级状态由独立字段表达，避免 `rule_degraded` 这类混合语义。
  - 改动文件：`pipeline/router.py`、`pipeline/route_decision.py`
  - 质量保证：`tests/test_router_eval.py`、`tests/test_pipeline.py`

本阶段亮点：

- RAG 不再是“搜索到一段话”，而是带 `source/year/score/citation/evidence_type` 的证据链。
- Tools 和 Skills 的边界开始被拆开：Tools 是可执行 API，Skills 后续会变成 SKILL.md 方法论文档。
- legacy wrapper 让旧 AgentLoop 可以继续运行，新 evidence contract 又能被 Maker/Checker 逐步消费。
- evidence extraction 被抽成纯数据模块，降低 Generator 对 LLMClient、AgentLoop 和 SkillRegistry 的耦合。
- RAG tool 失败时返回 `success=False`，向量库故障不会直接击穿 AgentLoop。

v3.1 当时测试结果：

```text
pytest -q tests
85 passed, 2 skipped
```

当前最终全量测试结果见 v3.7：`151 passed`。

说明：pytest 运行时在 Windows 下产生过 `pytest-cache-files-*` 临时目录和 `.pytest_cache` 写入 warning。这些是测试缓存/临时产物，不属于项目功能文件，应在测试后清理；测试源码本身保留，用作回归保障。

### v3.2: Progressive Skills + ReAct Loop

说明：本节记录的是 v3.2 的历史落地状态。当时实现的是 LLM `SkillSelectionPass` 和 6 个 compact SKILL.md；当前默认路径已在 v3.7 升级为 `SkillResolver(cluster_hybrid_v1)` + 24 个 Maker-facing Skills + Tool Visibility Control。

本阶段要交付的能力：

- 建立 SKILL.md 方法论文档体系，让 Skills 成为“领域操作手册”，而不是函数工具。
- 给 Maker 一个紧凑 Skill Index，让它先判断需要加载哪些方法论，再进入正式 tool loop。
- 在 AgentLoop 内部实现 `SkillSelectionPass`，批量加载选中的 SKILL.md。
- 保留 ReAct-like tool loop，让 Maker 仍然能根据工具观察结果逐步决策。
- 输出统一 `process_trace`，其中包含 `loaded_skills`、`tool_trace`、`tool_summary` 和 `skill_selection`，为后续 Checker 审查过程路径做准备。

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
  - 功能：Generator 默认开启 `progressive_skills_enabled=True`，并把 `loaded_skills/tool_trace/tool_summary/skill_selection` 收敛到顶层 `process_trace`。
  - 原因：后续 Checker 不应只审最终答案，还要审查 Maker 加载了哪些方法论、调用了哪些工具；这些过程字段属于同一个 trace 对象，不应散落在顶层。
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

v3.2 当时测试结果：

```text
pytest -q tests
130 passed, 2 skipped
```

### v3.3: Checker Precheck / PreStopPolicy

本阶段要交付的能力：

- 在 Checker 调用 LLM 前增加一个确定性 precheck。
- 对高精度医疗信号做 Tool Path Audit，防止 Maker 没调必需工具就 final。
- 对 `action_signal`、`proposed_action` 和 evidence 做 Evidence Path Audit。
- 对高危症状、心理危机、高风险用药做 Safety Process Audit。
- 发现过程缺口时，Checker 不调用 LLM，直接返回可返修的 `REJECT`，并标注 `NEED_MORE_TOOL_USE / NEED_MORE_EVIDENCE / SAFETY_PROCESS_GAP`。
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
高风险问题有没有走必要安全流程？
```

它不问：

```text
最终医学建议内容是否安全？
```

后者仍由 LLM Checker 和 SafetyGate 负责，避免把确定性过程检查和语义安全审计揉在一起。

已实现功能：

- 建立 PreStopPolicy 过程检查器。
  - 功能：提供 `before_final()` 和 `before_review()`；第一版实际使用 `before_review()`，其内部会执行 Tool Path Audit、Evidence Path Audit 和 Safety Process Audit。
  - 原因：当前 AgentLoop 尚未在 LLM final 前提供可中断 repair hook，因此先在 Maker draft 后、LLM Checker 前执行完整过程检查，是最小可落地实现。
  - 改动文件：`core/prestop_policy.py`
  - 质量保证：`tests/test_prestop_policy.py`

- 实现 required-tool / any-of 高精度规则。
  - 功能：高危症状和心理危机要求 `assess_risk`；用药安全要求 `drug_safety_lookup`；报告解读要求 `lab_reference_lookup`；指南/治疗方案要求 `guideline_search` 或 `medical_kb_search` 至少一个。
  - 原因：把 required-tool 从 prompt 建议升级为 runtime policy；`any_of_tools` 避免等价检索工具导致误杀。
  - 改动文件：`core/prestop_policy.py`
  - 质量保证：`tests/test_prestop_policy.py`

- 实现 evidence/action_signal 过程完整性检查。
  - 功能：缺少 `action_signal`、缺少 `proposed_action`、高置信但无 evidence 时返回可返修问题。
  - 原因：这些是可修复的过程问题，应退回 Maker 补证据或降低置信度，而不是直接由 SafetyGate 覆盖。
  - 改动文件：`core/prestop_policy.py`
  - 质量保证：`tests/test_prestop_policy.py`

- 实现 Safety Process Audit。
  - 功能：高危症状、心理危机、高风险用药等场景如果没有走必要工具流程，会输出 `SAFETY_PROCESS_GAP`。
  - 原因：PreStop 审“过程安全”，SafetyGate 审“最终输出安全”；二者互补，不重复。
  - 改动文件：`core/prestop_policy.py`
  - 质量保证：`tests/test_prestop_policy.py`、`tests/test_reviewer_precheck.py`

- 将 PreStopPolicy 接入 Reviewer。
  - 功能：每次 `Reviewer.review()` 开始时先运行 PreStopPolicy；若预检失败，Reviewer 直接返回 `REJECT`，不调用 LLM Checker，并透传 `reject_type`。
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
- PreStopPolicy 被拆成 Tool Path / Evidence Path / Safety Process 三类 zero-token audit。
- Safety Process Audit 让“高风险问题必须先走安全流程”成为运行时约束，而不是 prompt 建议。
- `any_of_tools` 支持等价工具能力，例如指南类问题可由 `guideline_search` 或 `medical_kb_search` 任一满足。
- PreStopPolicy 保持独立可测的规则模块，但生命周期归 Reviewer/Checker 管。
- Orchestrator 不理解 PreStop 规则，只根据 Checker verdict 做 repair / forced_safe。
- 返修路径是可执行的：`Checker precheck REJECT -> Generator.regenerate -> Checker.review again -> LLM Checker / forced_safe`。
- 第一版规则只做高精度场景，避免过早做庞大 Signal Catalog。

v3.3 当时测试结果：

```text
pytest -q tests
130 passed, 2 skipped
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
- Checker prompt 显式读取 `process_trace/evidence_records/action_signal/prestop_result`，其中 `loaded_skills/tool_trace/tool_summary` 都来自 `process_trace`。
- 用药安全和化验单场景不再只靠 `search_knowledge` 兜底，而是有专用工具。

为什么这样做：

v3.3 解决的是“关键工具漏调时能不能零 token 拦截”。v3.4 解决的是“进入 LLM Checker 后，它到底按什么结构审”。如果 Checker 仍然沿用旧的答案质量维度，它会像普通 reviewer，而不是 process-aware Checker。

已实现功能：

- 升级 Checker system prompt。
  - 功能：将 issue type 收敛为 5 类：`TOOL_GAP`、`EVIDENCE_GAP`、`SAFETY_RISK`、`CONTEXT_GAP`、`OUTPUT_BOUNDARY`。
  - 原因：这些类别既能覆盖工具路径、证据、医疗安全、上下文不足和输出越界，又不会像旧维度那样过细导致 LLM 分类不稳定。
  - 质量保证：`tests/test_checker_semantic_audit.py`

- 让 Checker 显式审查 Maker 的 `process_trace`。
  - 功能：审查 prompt 中加入 `Loaded Skills`、`Tool Trace` 和 `Tool Summary`，并要求和 `Evidence Records` 交叉对比。
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
  - 功能：把 route、process_trace、evidence、prestop_result、checker_verdict、safety_gate 和 final_action 写成 JSONL。
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

### Future: Signal Catalog / Rule Unification（暂缓）

当 Router rules、PreStopPolicy rules、Skills 数量明显增多后再做。

目标：

- 把高危症状、用药风险、报告指标、心理危机等医学信号统一定义
- Router 读取 signal 决定 `simple / maker_checker`
- PreStopPolicy 读取 signal 决定 required tools
- Skill Index 读取 signal 生成 `when_to_load`
- 避免 Router、PreStopPolicy、SKILL.md 三处重复维护同一批医学信号

暂不在第一版实现，避免过早抽象。

当前判断：

- 暂不实现 Signal Catalog。
- 原因：目前 Router / PreStopPolicy / SKILL.md 的规则数量还可控；过早抽象会把清晰 pipeline 变成配置系统。
- 保留改进方向：当规则数超过 20、Skills 超过 20，或出现多处维护不一致时，再将高危症状、用药风险、报告指标、心理危机等信号统一到共享 catalog。

### v3.6: Advanced RAG / Safe Memory

本阶段真正做 Future 里对面试最有价值的部分：

- Advanced RAG
- Safe Memory
- modern structured tools registration
- memory/RAG eval fixtures

不做：

- MCP wrapping
- Signal Catalog
- GraphRAG

为什么这样取舍：

MCP 是外部工具协议，对当前项目来说主要是包装层；如果没有多个外部 server、权限模型和部署场景，做了也只是“接口漂亮”。Signal Catalog 当前也不是瓶颈，先不为未来规模引入配置复杂度。相比之下，Memory 和 RAG 是 Agent 岗位面试高频追问点，且能直接提升系统质量。

参考的工程方向：

- LangGraph 把 memory 区分为 short-term thread memory 和 long-term cross-session memory。
- Mem0 / Letta 类项目强调用户长期记忆、个性化和跨会话召回。
- LlamaIndex 的 RRF / hybrid retrieval 思路适合把 dense 和 keyword 结果融合。
- Ragas 的指标体系启发了 context precision、faithfulness、retrieval quality 的 eval 方向。

已实现 Advanced RAG：

- hybrid retrieval。
  - 功能：`EvidenceService.advanced_search()` 优先执行 dense + keyword 两路检索；如果底层 KB 没有 `keyword_search`，自动退化为 dense + rerank。
  - 原因：医疗 RAG 不能只依赖向量相似度。关键词命中对药名、指标名、指南年份、缩写很重要。
  - 质量保证：`tests/test_advanced_rag.py`

- Reciprocal Rank Fusion。
  - 功能：用 RRF 融合 dense 和 keyword 排名，避免不同检索器分数尺度不一致的问题。
  - 原因：RRF 是工业 RAG 中常用的稳健融合方法，适合第一版不引入额外 reranker 模型的场景。
  - 质量保证：`tests/test_advanced_rag.py`

- lightweight rerank。
  - 功能：基于原始检索分数、query overlap、evidence_type priority、citation 和年份新鲜度做轻量重排。
  - 原因：不加载额外 cross-encoder，保证 CI 和本地测试稳定；同时比裸 top-k 更可控。
  - 质量保证：`tests/test_advanced_rag.py`

- evidence quality summary。
  - 功能：统计 evidence types、newest/oldest year、citation coverage、low score count、stale count、memory_context_count。
  - 原因：只输出机器能稳定计算的字段，不伪造 coverage/conflict 这种需要医学判断的字段。
  - 质量保证：`tests/test_advanced_rag.py`

- Milvus best-effort keyword_search。
  - 功能：真实 `MedicalKnowledgeBase` 增加 keyword 分支，失败时自动回退。
  - 原因：让 hybrid retrieval 不只停留在测试替身上，同时避免强依赖全文索引。
  - 质量保证：`tests/test_advanced_rag.py`、`tests/test_rag_tools.py`

已实现 Safe Memory：

- 长期记忆需要用户授权。
  - 功能：`MemoryService.remember()` 默认 `require_consent=True`；无授权不写入。
  - 原因：医疗 memory 有隐私和安全风险，不能静默保存用户健康信息。
  - 质量保证：`tests/test_memory.py`

- 按 user_id 隔离。
  - 功能：`LocalMemoryStore` 只返回同一 `user_id` 的记录。
  - 原因：医疗 Agent 的 memory 必须先保证不串用户。
  - 质量保证：`tests/test_memory.py`

- memory_context_lookup 只返回上下文。
  - 功能：返回 `ToolResult.data.memory_context`，`ToolResult.evidence` 永远为空，并标记 `not_medical_evidence=True`。
  - 原因：用户偏好、慢病背景、历史对话可以帮助个性化，但不能支撑医学 claim。
  - 质量保证：`tests/test_memory.py`

- 短期记忆和 legacy 长期记忆兼容。
  - 功能：补 `ShortTermMemory` 和 `LongTermMemory`，让旧 `search-history` / `search-similar-cases` wrapper 不再引用不存在的模块。
  - 原因：不一次性删除 legacy，而是让旧入口能工作，同时逐步切到现代 Tool。
  - 质量保证：`tests/test_memory.py`

- Checker memory boundary。
  - 功能：Checker prompt 明确 `memory_context` 不能当 guideline、drug_safety、lab_reference 或 clinical evidence。
  - 原因：RAG evidence 和 memory context 必须分层，否则医疗 Agent 会把“用户说过”误当成“医学证据”。
  - 质量保证：`tests/test_checker_semantic_audit.py`

已实现 structured tools registration：

- 功能：Generator 同时注册 legacy skills 和 `tools/` 目录下的现代工具。
- 原因：`drug_safety_lookup`、`lab_reference_lookup`、`memory_context_lookup` 不能只是文件，必须真正暴露给 Maker 的 function calling。
- 质量保证：`tests/test_structured_tool_registration.py`

已扩展 Eval：

- `rag_cases.jsonl` 增加 hybrid retrieval 标签和 rerank/evidence_quality metric hint。
- 新增 `memory_cases.jsonl`，覆盖 memory personalization 和 memory_used_as_medical_evidence seeded case。
- `run_evals` 现在可以统计 10 条 tool-call / RAG / Checker / Memory fixtures。

已完成输出契约收敛：

- Maker 输出统一为 `action_signal + evidence_records + process_trace` 三层结构。
- `action_signal` 只保留最终结论、动作、置信度、`evidence` 摘要和 `evidence_ids`，不再复制完整 `evidence_records`。
- `loaded_skills/tool_trace/tool_summary/skill_selection` 统一收进 `process_trace`，不再作为顶层兼容字段暴露。
- Checker、TraceWriter、Orchestrator 测试和文档都迁移到新契约，避免新旧字段长期并存导致上下游职责不清。

v3.6 当时测试结果：

```text
pytest -q tests\test_advanced_rag.py tests\test_evidence_service.py tests\test_rag_tools.py
16 passed

pytest -q tests\test_memory.py tests\test_structured_tool_registration.py tests\test_skill_index.py
13 passed

pytest -q tests\test_memory.py tests\test_structured_tool_registration.py tests\test_checker_semantic_audit.py tests\test_generator_evidence.py tests\test_prestop_policy.py
20 passed

pytest -q tests
130 passed, 2 skipped
```

### v3.7: Skills / Tool Visibility / SkillResolver Upgrade

本阶段来自 `docs/skills-tools-research/` 的调研和本地实验结论，目标是把 Skills / Tools 体系从“可运行”继续升级到“可扩展、可测、低延迟”。

本阶段要交付的能力：

- 补齐 24 个 Maker-facing SKILL.md，覆盖真实医疗健康问答能力。
- 把 Progressive Skill Loading 从 LLM SkillSelectionPass 升级为本地 `SkillResolver`。
- 根据 loaded skills 做 Tool Visibility Control，减少 Maker 看到的无关工具。
- 补齐第一批高价值结构化工具：风险规则、影像报告、生命体征。

为什么这样做：

v3.2 的 SkillSelectionPass 是正确起点，但当 Skills 扩到 20+ 后会出现两个问题：

```text
1. 每次让 LLM 读 Skill Index 再选择，增加延迟。
2. 单纯 LLM/top-k 选择在组合医疗风险上召回不足，例如“孕妇 + 发热 + 用药”容易漏掉 medication_safety 或 symptom_triage。
```

本地实验比较了 6 种 progressive loading 策略，最佳方案是：

```text
hard safety implication rules
+ cluster gating
+ lightweight retrieval top-k
+ cap 2-4 loaded skills
```

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

已实现功能：

- 补齐 24 个 Maker-facing Skills。
  - 功能：覆盖症状、急症、心理危机、澄清追问、就医路径、用药、多药相互作用、特殊人群、化验、影像、生命体征、指南、证据比较、来源质量、科普、预防、设备、慢病、生活方式、营养、康复和 memory 个性化。
  - 原因：旧 6 个 Skill 粒度过粗，容易让 Maker 在复杂问题中加载过宽泛方法论；24 个 Skill 按处理方法划分，不按疾病名堆数量。
  - 取舍：`checker_adversarial` 保留为 Checker 固定方法论，不参与 Maker 普通 Skill selection。
  - 质量保证：`tests/test_skill_index.py`

- 删除旧粗粒度 Skills。
  - 功能：删除 `evidence_research` 和 `lifestyle_chronic_care`。
  - 原因：它们已被拆成更清晰的 `guideline_research/evidence_comparison/source_quality_appraisal` 和 `chronic_care/lifestyle_coaching/nutrition_weight_management/rehabilitation_exercise_safety`，同时保留旧 Skill 会让 Maker 看到重复边界。
  - 质量保证：`tests/test_skill_index.py`

- 实现 `SkillResolver`。
  - 功能：`core.skill_resolver.SkillResolver` 使用高精度安全组合规则、cluster gating 和轻量字符 ngram TF-IDF 检索选择 2-4 个 Skill。
  - 原因：用本地 deterministic/resolver 层替代默认 LLM SkillSelection 耗时路径，同时提升组合风险召回。
  - 输出：`selected_skill_ids/safety_implied_skill_ids/clusters/scores/reasons/resolver_version`，写入 `process_trace.skill_selection.resolver`。
  - 质量保证：`tests/test_skill_resolver.py`

- 将 Generator 默认切到 `cluster_hybrid`。
  - 功能：`GeneratorAgent` 默认启用 `skill_selection_strategy="cluster_hybrid"` 和 `skill_resolver_max_skills=4`。
  - 原因：默认路径应使用本地低延迟 resolver；旧 LLM SkillSelectionPass 保留为回退策略。
  - 质量保证：`tests/test_agent_loop_skill_selection.py`

- 实现 Tool Visibility Control。
  - 功能：`core.tool_visibility.ToolVisibilityPolicy` 根据 loaded skills 过滤 Maker 可见 OpenAI function schemas。
  - 原因：Maker 不需要每轮看到所有工具；过滤工具能减少 schema token、减少工具选择噪音，并降低误调 `deep_research` 等慢工具的概率。
  - 兜底：如果没有 loaded skills 或过滤后为空，返回原工具列表，避免过度过滤。
  - 质量保证：`tests/test_agent_loop_skill_selection.py`

- 新增 `risk_rule_check`。
  - 功能：根据高精度红旗规则返回 `risk_level/matched_rules/recommendation`，`evidence=[]`。
  - 原因：它是 legacy `assess_risk` 的现代结构化补充，服务症状、急症、心理危机和生命体征安全流程。
  - 质量保证：`tests/test_rag_tools.py`、`tests/test_structured_tool_registration.py`

- 新增 `imaging_reference_lookup`。
  - 功能：查询 CT、MRI、超声、X 光、影像报告术语、结节和随访边界，返回结构化 evidence。
  - 原因：影像报告是高频问法，不能长期只靠通用 RAG。
  - 质量保证：`tests/test_rag_tools.py`、`tests/test_structured_tool_registration.py`

- 新增 `vital_sign_reference_lookup`。
  - 功能：查询血压、血氧、心率、体温、心电图文字和风险边界，返回结构化 evidence。
  - 原因：生命体征异常和心电图结果经常触发安全流程，需要专用工具支撑。
  - 质量保证：`tests/test_rag_tools.py`、`tests/test_structured_tool_registration.py`

本阶段亮点：

- Progressive Skill Loading 从“LLM 读 index 选择”升级成“本地 resolver + 小上下文注入”。
- Skill 设计从 6 个粗粒度文档升级为 24 个按处理方法划分的医疗能力单元。
- Tool Visibility Control 保留 Agent 自主选工具，但减少无关工具暴露，不把系统改成 workflow。
- 新增风险、影像、生命体征三类结构化工具，让 Skills 不只是 Markdown，也能匹配真实工具能力。
- 所有新增能力都有独立单测和全量回归测试。

v3.7 测试结果：

```text
pytest -q -p no:cacheprovider tests\test_skill_index.py tests\test_skill_resolver.py tests\test_agent_loop_skill_selection.py tests\test_rag_tools.py tests\test_structured_tool_registration.py tests\test_tool_specs.py
33 passed

pytest -q -p no:cacheprovider tests
151 passed
```

最终取舍：

```text
做：Memory + Advanced RAG + Eval/Trace + 24 Skills + SkillResolver + Tool Visibility + high-value structured tools
不做：MCP wrapping
谨慎暂缓：Signal Catalog / Rule Unification
```

---

## 15. 当前目录结构

```text
maker-checker/
├── agents/
│   ├── generator.py             # Maker Agent：progressive skills + structured tools
│   ├── reviewer.py              # Checker Agent：PreStopPolicy + LLM semantic audit
│   ├── evidence_extractor.py    # evidence_records / evidence_ids extraction
│   └── skill_registry_mixin.py  # legacy skills + structured tools registration
├── pipeline/
│   ├── response_renderer.py     # deterministic final rendering, no LLM call
├── core/
│   ├── agent_loop.py            # ReAct-like loop + SkillResolver/SkillSelection context loading
│   ├── llm_client.py
│   ├── skill_index.py           # SKILL.md index + SkillDocLoader
│   ├── skill_resolver.py        # cluster_hybrid progressive skill resolver
│   ├── tool_visibility.py       # loaded_skills -> visible tools
│   ├── prestop_policy.py        # Checker deterministic precheck
│   ├── trace.py                 # AgentTraceRecord / TraceWriter
│   ├── skill_registry.py        # function calling adapter
│   └── skill_loader.py          # .claude legacy wrapper discovery
├── skills/
│   ├── symptom_triage/SKILL.md
│   ├── emergency_red_flags/SKILL.md
│   ├── mental_health_safety/SKILL.md
│   ├── clarifying_questions/SKILL.md
│   ├── care_navigation/SKILL.md
│   ├── medication_safety/SKILL.md
│   ├── drug_interaction/SKILL.md
│   ├── renal_liver_dose_safety/SKILL.md
│   ├── pregnancy_pediatric_safety/SKILL.md
│   ├── geriatric_safety/SKILL.md
│   ├── lab_report/SKILL.md
│   ├── imaging_report/SKILL.md
│   ├── ecg_vital_signs/SKILL.md
│   ├── guideline_research/SKILL.md
│   ├── evidence_comparison/SKILL.md
│   ├── source_quality_appraisal/SKILL.md
│   ├── health_education/SKILL.md
│   ├── preventive_care/SKILL.md
│   ├── medical_device_explainer/SKILL.md
│   ├── chronic_care/SKILL.md
│   ├── lifestyle_coaching/SKILL.md
│   ├── nutrition_weight_management/SKILL.md
│   ├── rehabilitation_exercise_safety/SKILL.md
│   ├── memory_personalization/SKILL.md
│   └── checker_adversarial/SKILL.md
├── tools/
│   ├── __init__.py
│   ├── specs.py
│   ├── medical_kb_search.py
│   ├── guideline_search.py
│   ├── lab_reference_lookup.py
│   ├── drug_safety_lookup.py
│   ├── risk_rule_check.py
│   ├── imaging_reference_lookup.py
│   ├── vital_sign_reference_lookup.py
│   └── memory_context_lookup.py
├── knowledge/
│   ├── milvus_kb.py
│   ├── evidence_service.py
│   └── rag_retrieval.py
├── memory/
│   ├── store.py                 # LocalMemoryStore + MemoryRecord
│   ├── service.py               # consent-aware MemoryService
│   ├── short_term.py            # current-session memory
│   └── long_term.py             # legacy compatible long-term facade
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
│   ├── memory_cases.jsonl
│   ├── checker_seeded_cases.jsonl
│   └── run_evals.py
└── .claude/
    └── skills/                  # legacy wrappers: old function names delegate to new tools
```

---

## 16. 简历表达

不要写：

```text
实现了一个医疗多 Agent 问答系统。
```

建议写：

```text
构建 Medical Maker-Checker Agent，保留 Router 的 simple/maker_checker 监督分流，Maker Agent 通过 cluster-hybrid SkillResolver 渐进加载 24 个医疗 SKILL.md 方法论，并在 ReAct-like loop 中自主调用结构化医学工具生成证据化回答；Checker Agent 采用 two-stage auditor 设计，先用 PreStopPolicy 零 token 检查工具路径、证据路径和安全流程，不通过则直接退回 Maker 补修，再调用 LLM 做 tool path、RAG evidence 和 medical safety 审计；SafetyGate 只审最终输出安全，不通过则硬覆盖为 urgent_care。
```

技术 bullet：

- 设计 progressive Skills / structured Tools / RAG evidence / two-stage Checker 的 Agent runtime，将原 `.claude/skills` 中混杂的可执行逻辑拆分为方法论、工具和证据。
- 设计 24 个 Maker-facing SKILL.md，并实现 `SkillResolver`：用高精度 safety implication rules、cluster gating 和轻量检索选择 2-4 个相关 Skills，降低 LLM SkillSelection 延迟并提升组合医疗风险召回。
- 实现 Tool Visibility Control，根据 loaded skills 过滤 Maker 可见 function schemas，保留 Agent 自主工具选择能力，同时减少无关工具暴露和慢工具误调。
- 将 PreStopPolicy 收敛为 Checker 内部 deterministic precheck，不依赖 Maker 自报的 selected_skills，而是基于 user_query、route triggers 和 `process_trace.tool_trace` 检查 Tool Path、Evidence Path 与 Safety Process；预检失败时 Checker 不调用 LLM，直接返回可返修 REJECT。
- 将 SafetyGate 收敛为"输出警察"，不重复 Checker precheck 的过程检查，只审最终结论内容安全（高危症状 action 匹配、Checker 标记的 SAFETY_RISK、输出边界），不通过则硬覆盖为 urgent_care。
- 将 RAG 从自然语言搜索结果升级为 evidence records，支持 source、year、score、evidence_type、citation 等可审计字段，并用于 Checker 的证据审查。
- 新增 `risk_rule_check`、`imaging_reference_lookup`、`vital_sign_reference_lookup` 三类结构化工具，覆盖红旗规则、影像报告和生命体征高频医疗场景。
- 构建 process-aware Checker，不生成替代答案，只审查工具路径、证据支撑、风险边界和缺失上下文。
- 建立 tool-call / RAG / seeded Checker eval 与 trace 机制，用 required_tool_recall、context precision、faithfulness、unsafe_pass_rate 等指标验证改造效果。

---

## 17. 面试讲法

### 17.1 30 秒版本

> 这个项目最初是一个 ReAct-like 医疗 Agent，LLM 自主调用所谓 skills。复盘后我发现最大问题不是模型不会调工具，而是医疗场景不能只靠模型自觉：症状问题可能漏掉风险评估，用药问题可能漏掉药物安全检查，RAG 也可能只返回一段不可审计文本。所以我把它升级成 Medical Maker-Checker Agent：Router 只做 simple/maker_checker 监督分流；Maker 通过 cluster-hybrid SkillResolver 渐进加载 24 个 SKILL.md 方法论，并用 Tool Visibility Control 控制可见工具，但仍在 ReAct-like loop 中自主选择工具；Checker 做成 two-stage auditor，先用 PreStopPolicy 零 token 检查工具路径、证据路径和安全流程，失败就直接退回 Maker，不浪费 LLM 审查；通过后再由 LLM Checker 审计工具路径、证据和安全边界；SafetyGate 只审最终输出安全。

### 17.2 为什么不是 workflow

> 我没有让 Router 输出 intent、skills 或 tools，因为那会把 Maker 变成执行器。Router 只做监督等级分流。SkillResolver 是 Maker runtime 内部的上下文准备层，用少量安全组合规则和检索选择 2-4 个 SKILL.md；Maker 仍然自主选择 Tools、综合 evidence。系统只声明不变量，比如症状类高风险表达不能跳过风险评估，用药安全表达不能跳过 drug_safety_lookup。这是 bounded agency，不是固定工作流。

### 17.3 为什么 Skills 用 Markdown

> Skills 用 Markdown 是为了 progressive disclosure。当前 Maker 不再默认让 LLM 读完整 Skill Index，而是由本地 SkillResolver 选择少量相关 SKILL.md 注入上下文。Markdown 适合写 checklist、red lines、tool use notes 和领域方法论。但医疗安全硬约束不放在 Skill 激活结果里，而放在 Checker 内部的 PreStopPolicy 中，避免安全性依赖 Maker 自报。

### 17.4 为什么保留 ReAct-like loop

> 医疗问题需要根据工具结果逐步决策。完整 PAOR 听起来高级，但第一阶段未必比 ReAct 更稳。所以我保留 ReAct-like loop，只加入 progressive skill loading、structured ToolResult、Checker precheck 和 repair loop。这样既保留 Agent 自主性，又补上医疗安全约束。

### 17.5 RAG 为什么是重点

> 简单接 Milvus 只能说明做了检索。我的改造重点是把 RAG 输出变成 evidence records，让 Maker 的关键 claim 有来源，让 Checker 可以审 source、year、score、citation 和 evidence_type，并用 RAG eval 验证检索质量和回答忠实度。

### 17.6 Tools 为什么搬目录但分阶段搬

> `.claude/skills/*/script` 里的代码本质是 tools，最终应该逐步搬到 `tools/`。当前已经把 RAG、用药、化验单和 memory 做成 structured tools，并让旧 skills 作为 wrapper 或 function-calling adapter 继续暴露。这样既能表达 Skills/Tools 分层，也避免一次性重命名掩盖行为回归。

---

## 18. 最终主线

从：

```text
LLM-driven tool calling
```

到：

```text
cluster-hybrid progressive skill loading + tool-visibility-controlled Agent loop + required-tool guarded Checker
```

从：

```text
skills as function folders
```

到：

```text
24 SKILL.md domain playbooks + tools as structured callable APIs
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

这就是 v3 应该做成的样子：Maker 有自主性，Skills 有渐进式披露，SkillResolver 负责低延迟选择少量方法论文档，ToolVisibilityPolicy 控制可见工具但不替 Maker 做决策；Checker 先做确定性过程预检（REJECT/REPAIR），再做 LLM 语义审计；SafetyGate 只做输出硬覆盖（OVERRIDE）；RAG 有证据链，Eval 有指标可验证。



