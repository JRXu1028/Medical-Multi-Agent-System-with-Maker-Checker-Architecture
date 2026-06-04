# Medical Multi-Agent System with Maker-Checker Architecture

## 目录

1. [架构全景](#1-架构全景)
2. [对抗循环：完整流程与失败处理](#2-对抗循环完整流程与失败处理)
3. [核心设计理念](#3-核心设计理念)
4. [论文与项目依据](#4-论文与项目依据)
5. [选择此架构的全部原因和优点](#5-选择此架构的全部原因和优点)
6. [详细架构设计](#6-详细架构设计)
7. [实现方案](#7-实现方案)
8. [实现步骤](#8-实现步骤)
9. [面试论述指南](#9-面试论述指南)
10. [类似项目对比](#10-类似项目对比)

---

## 1. 架构全景

```
                          User Query
                              │
                              ▼
              ┌───────────────────────────────┐
              │  ROUTER (Hybrid Medical Router)  │
              │  · 简单且明确低危/非医疗 → 简单路径 │
              │  · 医疗决策/不确定 → 对抗路径    │
              │  · 依据: OneFlow (2601.12307)  │
              │    Anthropic Agent Guide (2026)│
              └──────────────┬────────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
    ┌──────────────────┐          ┌──────────────────────────┐
    │ 简单路径           │          │ 对抗 Maker-Checker 路径    │
    │                   │          │                          │
    │ Generator 直接回答 │          │  详见第 2 节：             │
    │ + Skills          │          │  对抗循环完整流程          │
    │ ↓                 │          │  · Round 1/2 循环        │
    │ Safety Gate       │          │  · 三种 verdict 路由      │
    │ ↓                 │          │  · 四种终态              │
    │ Final Answer      │          │  · 失败处理              │
    │                   │          │                          │
    │ 依据:              │          │                          │
    │ Anthropic 官方(2026)│         │                          │
    │ token↓53.7%       │          │                          │
    └──────────────────┘          └──────────────────────────┘
```

> **注意**: 简单路径直接走 Generator → Safety Gate → LeadAgent，不经过 Reviewer。以下第 2 节描述的是对抗路径的完整流程。

---

## 2. 对抗循环：完整流程与失败处理

### 2.1 三条铁律

| # | 规则 | 说明 |
|---|------|------|
| 1 | **谁发现问题谁负责指出，但修复永远由 Generator 执行** | Reviewer 不修，Safety Gate 不修，LeadAgent 不修 |
| 2 | **最多 2 轮（1 次初始生成 + 1 次修正）** | 依据：OncoAgent bounded retry (max 2)；Multi-Agent Evaluation Loops 平均 2.34 轮收敛 |
| 3 | **超过上限不继续循环，强制安全兜底** | 不存在"一直修不好"——2 轮后仍 REJECT → FORCED_SAFE_MODE |

### 2.2 完整流程图

```
User Query (高危/复杂/不确定)
    │
    ▼
╔══════════════════════════════════════════════════════╗
║                   ROUND 1 (初始)                     ║
║                                                      ║
║  ┌──────────────────────────────────────────────┐   ║
║  │  GENERATOR Agent                             │   ║
║  │  · 调用全部 9 个 Skills                        │   ║
║  │  · 产出: answer + action_signal + skill_trace │   ║
║  └──────────────────┬───────────────────────────┘   ║
║                     │                               ║
║                     ▼                               ║
║  ┌──────────────────────────────────────────────┐   ║
║  │  REVIEWER Agent                              │   ║
║  │  · 审查 action_signal + skill_trace           │   ║
║  │  · 可选: 重新调验证 Skills 做交叉验证           │   ║
║  │    允许: assess_risk, analyze_symptoms,       │   ║
║  │           clinical_guideline, search_knowledge,│  ║
║  │           deep_research                       │   ║
║  │    禁止: recommend_lifestyle, disease_code    │   ║
║  │  · 产出: verdict + challenges +               │   ║
║  │          confidence_adjusted                  │   ║
║  └──────────────────┬───────────────────────────┘   ║
║                     │                               ║
╚═════════════════════╪═══════════════════════════════╝
                      │
         ┌────────────┼────────────┐
         │            │            │
         ▼            ▼            ▼
       PASS       CHALLENGE      REJECT
         │            │            │
         │            │            ▼
         │            │    ┌──────────────────────────┐
         │            │    │ 返回 GENERATOR             │
         │            │    │ 附带:                     │
         │            │    │ · challenges 列表          │
         │            │    │ · 每条含 type, description,│
         │            │    │   severity, suggested_fix  │
         │            │    └────────────┬─────────────┘
         │            │                 │
         │            │                 ▼
         │            │    ╔══════════════════════════════════╗
         │            │    ║        ROUND 2 (最终轮)          ║
         │            │    ║                                  ║
         │            │    ║  GENERATOR 修正:                  ║
         │            │    ║  · 逐条处理 Round 1 challenges    ║
         │            │    ║  · 需要时重新调用 Skills           ║
         │            │    ║  · 产出修正版 answer + action_     ║
         │            │    ║    signal                        ║
         │            │    ║           │                      ║
         │            │    ║           ▼                      ║
         │            │    ║  REVIEWER 再审查:                 ║
         │            │    ║  · 重点检查: 上次的 challenges    ║
         │            │    ║    是否已全部修正？               ║
         │            │    ║           │                      ║
         │            │    ║  ┌────────┼────────┐             ║
         │            │    ║  │        │        │             ║
         │            │    ║ PASS  CHALLENGE  REJECT          ║
         │            │    ║  │        │        │             ║
         │            │    ╚══╪════════╪════════╪═════════════╝
         │            │       │        │        │
         │            │       │        │        ▼
         │            │       │        │  ┌──────────────────────────┐
         │            │       │        │  │ ⚠️ MAX_RETRIES = 1        │
         │            │       │        │  │ (即: 最多 1 次修正)        │
         │            │       │        │  │ 已达上限，不再循环          │
         │            │       │        │  │                          │
         │            │       │        │  │ → FORCED_SAFE_MODE        │
         │            │       │        │  │   强制安全兜底             │
         │            │       │        │  │   proposed_action         │
         │            │       │        │  │   强制 = recommend_       │
         │            │       │        │  │   urgent_care             │
         │            │       │        │  │   confidence = overridden │
         │            │       │        │  └────────────┬─────────────┘
         │            │       │        │               │
         │            └───────┴────────┴───────────────┘
         │                           │
         └───────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────┐
         │  SAFETY GATE (确定性代码，非 LLM)    │
         │                                   │
         │  1. 高危症状硬编码扫描               │
         │     query 含"胸痛"/"呼吸困难"等     │
         │     → proposed_action 必须是        │
         │       recommend_urgent_care        │
         │     否则 → BLOCK                    │
         │                                   │
         │  2. 证据充分性阈值                  │
         │     evidence 为空 且 confidence     │
         │     > 0.7 → BLOCK                  │
         │                                   │
         │  3. 格式合规检查                    │
         │     缺少 proposed_action           │
         │     → BLOCK                        │
         └──────────────┬────────────────────┘
                        │
             ┌──────────┴──────────┐
             │                     │
             ▼                     ▼
           PASS                 BLOCK
             │                     │
             │                     ▼
             │         ┌───────────────────────────┐
             │         │ GATE OVERRIDE              │
             │         │                            │
             │         │ 不是驳回，是硬覆盖：          │
             │         │ · proposed_action          │
             │         │   强制 = recommend_urgent_ │
             │         │          care              │
             │         │ · confidence 标记           │
             │         │   = overridden             │
             │         │ · 记录覆盖事件到日志          │
             │         └────────────┬──────────────┘
             │                      │
             └──────────┬───────────┘
                        │
                        ▼
         ┌──────────────────────────────┐
         │  LEADAGENT (纯表达，不仲裁)     │
         │                              │
         │  · 将 action_signal 翻译为    │
         │    自然语言                    │
         │  · 如果 action 被 Gate 覆盖 →  │
         │    克制表达安全就医建议          │
         │  · 如果来自 FORCED_SAFE_MODE  │
         │    → 表达时说明风险不确定       │
         │  · 添加免责声明                │
         └──────────────┬───────────────┘
                        │
                        ▼
                  Final Answer
```

### 2.3 循环计数逻辑

```python
MAX_RETRIES = 1  # 最多修正 1 次
retry_count = 0

# Round 1
generator_output = generator.generate(user_query)
verdict = reviewer.review(generator_output)

if verdict == REJECT and retry_count < MAX_RETRIES:
    retry_count += 1
    # Round 2
    generator_output = generator.regenerate(
        user_query,
        challenges=verdict.challenges  # 附带具体修正指令
    )
    verdict = reviewer.review(generator_output)

if verdict == REJECT and retry_count >= MAX_RETRIES:
    # 不再循环 → 强制安全兜底
    final_output = FORCED_SAFE_MODE(user_query)

# 进入 Safety Gate
gate_result = safety_gate.check(user_query, final_output.action_signal)

if not gate_result.passed:
    # Gate 硬覆盖，不是驳回重做
    final_output.action_signal.proposed_action = "recommend_urgent_care"
    final_output.action_signal.confidence = "overridden"

# 进入 LeadAgent 表达
final_answer = lead_agent.express(final_output)
```

### 2.4 三种 Verdict 的行为

| Verdict | 含义 | 行为 | 是否阻塞 |
|---------|------|------|:---:|
| **PASS** | 没有发现任何问题 | 直接放行到 Safety Gate | 否 |
| **CHALLENGE** | 有可修复的疑问（遗漏证据、confidence 偏高、边界情况未说明） | challenges 追加到 evidence，标记 uncertainty，放行到 Safety Gate | 否 |
| **REJECT** | 有严重问题（高危症状遗漏、指南误读、核心逻辑错误） | Round 1: 返回 Generator 附带 suggested_fix；Round 2: 触发 FORCED_SAFE_MODE | 是 |

### 2.5 四种终态

| 路径 | 触发条件 | 最终行为 | 用户感知 |
|------|---------|---------|---------|
| **正常通过** | R1 PASS → Gate PASS | LeadAgent 正常表达 Generator 结论 | 正常回答 |
| **带质疑通过** | R1/R2 CHALLENGE → Gate PASS | challenges 追加到 evidence，标记 uncertainty，LeadAgent 表达时说明不确定性 | "根据分析建议 X，但存在 Y 方面不确定性" |
| **Gate 硬覆盖** | 任何路径进入 Gate，Gate 触发 BLOCK | proposed_action 强制改为 urgent_care，LeadAgent 用克制语言表达安全建议 | "目前无法可靠排除风险，建议及时就医" |
| **强制安全兜底** | R2 仍 REJECT | 跳过 Gate（因为已是 urgent_care），直接输出 urgent_care + 完整免责声明 + 建议立即就医 | "目前无法可靠排除风险，基于安全原则建议立即就医" |

### 2.6 关键设计决策的理据

**为什么 REJECT 和 BLOCK 处理方式不同？**

| | REJECT（Reviewer 输出） | BLOCK（Safety Gate 输出） |
|---|---|---|
| **问题性质** | "你的推理有漏洞"——可以修正 | "你的结论违反安全红线"——不是推理问题，是安全规则问题 |
| **处理方式** | 返回 Generator 修正推理 | 不需要修正推理，直接覆盖结论 |
| **谁执行** | Generator（修改分析） | Safety Gate（硬覆盖 action） |
| **是否循环** | 是（最多 1 次修正） | 否（直接覆盖后放行） |

**为什么 FORCED_SAFE_MODE 跳过 Safety Gate？**

FORCED_SAFE_MODE 已将 proposed_action 强制设为 `recommend_urgent_care`，Gate 的高危症状检查已隐含通过。再走一遍 Gate 没有意义，只会增加无意义的代码路径。

**为什么 A-HMAD 发现 5+ 轮出现混乱？**

A-HMAD 论文报告 2 轮捕获大部分收益，3-4 轮最优，5+ 轮出现**新的混乱**——Agent 开始质疑自己之前正确的结论，或引入新的不相关论点。这就是为什么本设计硬限制 2 轮：宁可在不确定时强制安全兜底，也不让系统在循环中自我混乱。

---

## 3. 核心设计理念

### 3.1 对抗式 Maker-Checker

**Generator（构建者）** 调用所有 Skills，产出综合分析 + action_signal。
**Reviewer（证伪者）** 的目标不是"提供另一个视角"，而是**用证据驳倒 Generator 的结论**。

这不是"两个 Agent 给出不同答案然后选一个"（那是 Consensus Trap 揭示的陷阱），而是"一个人做了分析，另一个人专门找茬"的结构性对抗。

### 3.2 为什么是结构性对抗而非平权投票

**Consensus Trap (arXiv 2604.17139, 2026)** 从理论上证明了：当多数 Agent 共同犯错时，投票机制反而会放大错误。三个平权 Agent 并行输出然后仲裁 = 隐式投票。

**Multi-Agent Evaluation Loops (arXiv 2601.13268, 2026)** 的实践证明：Generator-Reviewer 对抗结构在 900 条医疗对抗查询中，将伦理违规减少 89%、风险降级 92%。

**Maker-Checker 模式 (Santa Method, 2025)** 在 500+ PRs 的生产验证中，将审查误报率从单次审查的 30-60% 降到 7.3%。

### 3.3 Reviewer 如何证伪 —— 三种具体操作

| 操作 | 机制 | 论文出处 |
|------|------|---------|
| **结构化驳回** | 不是"我觉得不对"，而是输出具体的 `{type, description, suggested_fix}` | Multi-Agent Evaluation Loops: Evaluator 输出具体 AMA violation + required_fix |
| **独立证据交叉验证** | 重新调用 Skill，用不同的检索策略查找 Generator 遗漏的内容 | adversarial-ai-review: Dev Agent grep 整个代码库验证 Reviewer 的发现 |
| **置信度校准** | 检查 Generator 的 confidence 是否与 evidence 数量/质量匹配 | A-HMAD: Learned Consensus Optimizer 根据历史可靠性加权 |

### 3.4 Router 分级：简单问题不走对抗

**OneFlow (arXiv 2601.12307, 2026)** 证明同质化多 Agent 在简单任务上不提供额外收益。**Anthropic 官方 Agent Guide (2026)** 建议"Start simple — begin with a single agent"。本项目的 Router 不把"未命中"视为简单，而是仅在简单且明确低危、明确非医疗决策，或 LLM 仲裁为 simple 时走单 Agent 路径；高危、复杂或系统不确定时进入 Maker-Checker 对抗路径。

---

## 4. 论文与项目依据

### 4.1 核心依据（直接支撑架构设计）

| 论文/项目 | 出处 | 核心发现 | 用于本架构 |
|-----------|------|---------|-----------|
| **Multi-Agent Evaluation Loops for Medical AI** | [arXiv 2601.13268](https://arxiv.org/abs/2601.13268) (Jan 2026) | Generator + 双 Evaluator 对抗结构；900条医疗对抗查询；伦理违规↓89%；风险降级↓92%；平均2.34轮收敛 | **直接依据**: Generator-Reviewer 对抗在医疗场景的有效性 |
| **adversarial-ai-review + Santa Method** | [GitHub](https://github.com/gaurav-yadav/adversarial-ai-review) (2025) / [Santa Method](https://github.com/affaan-m/everything-claude-code/blob/main/skills/santa-method/SKILL.md) | Maker-Checker 对抗审查；Developer Agent 尝试 KILL 每个发现；误报率7.3% vs 单次审查30-60%；500+ PRs生产验证 | **直接依据**: 对抗式证伪的生产可行性 |
| **Consensus Trap** | [arXiv 2604.17139](https://arxiv.org/abs/2604.17139) (Apr 2026) | 多数投票被多数错误绑架；Token级 Round-Robin 协作优于响应级聚合 | **直接依据**: 为什么不用三 Agent 平权投票 |
| **A-HMAD** | [Springer](https://link.springer.com/article/10.1007/s44443-025-00353-3) (Dec 2025) | 异构多Agent辩论减少45%幻觉；GSM8K 77%→90.2%；去掉异构模型降9个百分点 | **直接依据**: 对抗式审查减少幻觉的量化证据 |
| **OneFlow** | [arXiv 2601.12307](https://arxiv.org/abs/2601.12307) (Jan 2026) | 同质化 MAS 在7个benchmark上被单Agent+优化工作流持平或超过；KV cache复用带来成本优势 | **直接依据**: 为什么砍掉三Agent并行 |
| **CareGuardAI** | [arXiv 2604.26959](https://arxiv.org/abs/2604.26959) (Apr 2026) | 双轴安全评估 SRA(ISO 14971) + HRA(幻觉)；双重阈值≤2才放行 | **直接依据**: Safety Gate 的双轴检查设计 |
| **OncoAgent** | [HuggingFace Blog](https://huggingface.co/blog/lablab-ai-amd-developer-hackathon/oncoagent-official-paper) (May 2026) | 确定性代码 Critic；bounded retry (max 2轮)；驳回重做闭环 | **直接依据**: Critic 必须是确定性代码 + retry 上限 |
| **MAR: Multi-Agent Reflexion** | [arXiv 2512.22431](https://arxiv.org/abs/2512.22431) (Dec 2025) | 单LLM自反思会"继续重复同样的错误"；多角色辩论打破思维退化 | **间接依据**: 为什么单Agent自审查不可靠 |

### 4.2 支撑依据（间接支撑设计选择）

| 论文/项目 | 出处 | 核心发现 | 用于本架构 |
|-----------|------|---------|-----------|
| **Drop the Hierarchy** | [arXiv 2603.28990](https://arxiv.org/abs/2603.28990) (Mar 2026) | 25000次实验；协议设计比预设角色重要14%；自组织优于预设分工 | **间接依据**: 角色标签不是安全机制 |
| **PatchBoard** | [arXiv 2605.29313](https://arxiv.org/abs/2605.29313) (May 2026) | 结构化状态替代自然语言通信；84.6% vs LangGraph 30.8%；token从368k降到45k | **间接依据**: action_signal 结构化通信方向正确 |
| **Anthropic Agent Guide** | [Anthropic 官方](https://docs.anthropic.com/en/docs/agents-and-tools) (2026) | 5层架构: CLAUDE.md → MCP → Skills → Hooks → Subagents；Start simple, escalate when needed | **间接依据**: 简单路径单Agent+Skills |
| **UBC Skills Scaling Law** | [arXiv 2601.04748](https://arxiv.org/abs/2601.04748) (Jan 2026) | 单Agent+Skills: token↓53.7%, 延迟↓49.5%, 准确率持平；Skill Scaling Law: 50-100个Skill时断崖崩塌；明确列出三种必须保留多Agent的场景（对抗网络/私有状态/异构模型） | **间接依据**: SAS效率优化的理论上限；同时**直接支撑**本架构选择多Agent——Maker-Checker属于论文列出的"对抗网络"不可替代场景 |
| **X-MAS** | arXiv (May 2025) | 异构模型组合比同构高47% | **间接依据**: Generator/Reviewer 异构模型潜力 |
| **LangGraph vs CrewAI 生产对比** | [Redwerk](https://redwerk.com/blog/langgraph-vs-crewai/) (Apr 2026) | CrewAI 自然语言通信导致token爆炸；LangGraph 纯Python路由零token成本 | **间接依据**: 结构化通信 vs 自然语言通信的成本差异 |

---

## 5. 选择此架构的全部原因和优点

### 5.1 为什么放弃 v1（三 Agent 并行 + 规则仲裁）

| v1 问题 | 论文依据 |
|---------|---------|
| 三个 Agent 同 LLM、同 Skills、仅 prompt 不同 = 同质化 MAS | OneFlow (2026): 同质化 MAS 边际收益趋近零 |
| 三 Agent 平权并行 + ConflictResolver 规则仲裁 = 隐式投票 | Consensus Trap (2026): 投票机制被多数错误绑架 |
| 每个 Agent 的 post_process_result 差异化仅是 if-else 映射 | 无法产生真正的认知分歧 |
| 安全靠"DiagnosticAgent 负责风险评估"的角色标签 | CareGuardAI + OncoAgent: 安全必须是代码级 Gate |

### 5.2 为什么选择 Maker-Checker

1. **结构性对抗而非平权**：Generator 和 Reviewer 有对立的 KPI——一个构建、一个证伪。这和三个 Agent 各给各的答案有本质区别。
2. **驳回-重做闭环而非一次性仲裁**：REJECT 时带具体理由返回 Generator 修正，而不是从三个答案里硬选一个。
3. **双层安全防线**：Reviewer（LLM 审查，软防线）→ Safety Gate（确定性代码，硬防线）。单靠任何一层都不够。
4. **简单问题不浪费算力**：Router 分级——只有简单且明确低危的问题走单 Agent；高危、复杂或不确定的问题都启动对抗。
5. **学术证据充分**：3 篇直接支撑论文 + 2 个生产验证项目，覆盖医疗和通用领域。

### 5.3 与同类型架构的对比

| 维度 | CrewAI 角色扮演 | LangGraph 状态机 | OpenAI Swarm | 本架构 |
|------|:---:|:---:|:---:|:---:|
| Agent 关系 | 平权，自然语言委托 | 节点+边，结构化状态传递 | 平权，handoff 路由 | 不对等，对抗式 Maker-Checker |
| 安全机制 | 无内置 | Checkpointing（非持久执行） | 无内置 | 双层: Reviewer + Safety Gate |
| 冲突解决 | Agent 间自然语言沟通 | 纯 Python 路由函数 | handoff 优先级 | 结构化驳回 + 修正闭环 |
| Token 效率 | 低（Agent 间聊天消耗 token） | 高（纯函数路由零 token） | 中 | 中（Reviewer 会调 Skill 验证） |
| 医疗场景适配 | 需自行构建安全层 | 需自行构建安全层 | 需自行构建安全层 | 原生 Safety Gate + 医疗论文验证 |

---

## 6. 详细架构设计

### 6.1 Router 层 — Hybrid Medical Router

四级流水线：simple 只给简单且明确低危的问题；maker_checker 来自高危、复杂、语义高分、LLM 判定或系统不确定。

```
Simple Intent Guard → Maker-Checker Signals → Semantic Recall → LLM Router
    (0ms)          (0ms)          (<10ms)        (~2s, 低频)
```

**Level 0: Simple Intent Guard** — 先过滤明显非个人医疗决策和低风险健康教育问题（医保报销、设备原理、写作研究、饮水/水果/运动/睡眠等生活方式咨询）。自伤意图绕过此过滤。

**Level 1: Maker-Checker Signals** — 统一的确定性 maker_checker 信号管道。每个信号阶段通过 `MakerCheckerStage(reason_prefix, evaluator)` 注册，公共的 `_route_without_llm()` 会遍历 `_MAKER_CHECKER_STAGES`，命中任一阶段即进入对抗路径。底层规则定义为 `ContextRule(keywords, contexts, label, category)` dataclass，提供 `match(question)` 方法。当前包含四类：

| 类别 | 示例 | 策略 |
|------|------|------|
| Safety（安全红线） | 急症症状（直接触发）、特殊人群+医疗上下文、用药风险、慢性红旗 | 急症裸词触发；胸部风险/特殊人群/基础病需配合急性/症状/医疗上下文 |
| Evidence（循证需求） | 指南查询、药物咨询、检查结果+诊疗意图 | 检查词+诊疗上下文避免"CT机器怎么工作"误报 |
| Progression（进展性） | 进展性症状、病程时间窗、急性发作 | 所有进展性词需配合症状上下文（"一个月"不再裸触发"一个月运动计划"） |
| Personal Medical Intent（个人医疗意图兜底） | 我/家人/患者 + 身体异常/报告/药物/检查/诊疗决策 | 不识别具体病种，只判断是否为个人医疗决策，防止未枚举症状掉入 simple |

**Level 2: Semantic Recall** — BGE embedding 批量编码 40 个高危原型 + 27 个安全原型，计算 `max(high_risk_similarity) - max(low_risk_similarity)`。语义高分（当前阈值 0.15）直接升级 maker_checker；语义低分不再证明 simple，而是进入 LLM Router。

阈值 0.15 的来源是语义路由层的离线压力测试，而不是医学风险阈值。`tests/tools/evaluate_router_threshold.py` 对语义分数做 threshold sweep。当前结果：simple 样例最高分 0.099；0.15 阈值下 `precision=1.000`、`false_positive_rate=0.000`、直接召回 381/500 个 maker_checker。相比 0.22，0.15 在不增加低危误升级的前提下多提前召回 119 个高危/复杂样例；相比 0.10，0.15 与 simple 最高分 0.099 保持了更大的安全边际。因此 0.15 是 semantic recall 的高置信升级点。低于 0.15 的样例不会判为 simple，而是进入 LLM Router 仲裁。

评估集由 `tests/tools/generate_router_threshold_eval.py` 生成，固定随机种子 `20260603`，保证可复现。它是模板扩增的路由压力测试集，不是临床真实数据集。共 1000 条，标签平衡为 500 simple / 500 maker_checker，并由 `tests/test_router_threshold_fixture.py` 校验规模、标签平衡、query 去重和 category 字段。simple 类覆盖低风险健康教育、非个人医疗决策、医保行政流程、设备原理、医学写作/翻译/研究、非医疗物品问题；maker_checker 类覆盖胸痛/胸闷语义变体、呼吸困难语义变体、神经急症信号、出血/黑便/紫癜信号、特殊人群+症状、用药风险、检查/指南/诊疗决策、进展性症状和个人医疗意图兜底。

**Level 3: LLM Router** — 轻量分类器，默认使用 `router` LLM profile（`deepseek-v4-flash`, `temperature=0`, `max_tokens=512`, non-thinking）。在规则未命中且语义未高分时调用，输出 `{"mode": "simple"|"maker_checker", "reason": "..."}`。解析失败或不可用时 fail-closed（保守进入 maker_checker）。因此 simple 的来源只有两种：明确 simple 规则，或 LLM 明确仲裁为 simple。Router LLM 与 Generator/Reviewer/Lead 的模型配置解耦，后续可按角色替换不同模型。

**核心设计决策**：
- 特殊人群不自动等于复杂。`宝宝吃什么水果好`、`老人每天散步多久`、`孕妇能不能喝咖啡` 这类简单且明确低危的生活科普可以走 simple；但一旦出现症状、用药、检查报告、治疗选择或不确定风险，即进入 maker_checker
- 语义低分不直接 simple。embedding 不像高危原型只能说明"未召回"，不能证明安全；未高分样例交给 LLM 仲裁
- 所有 maker_checker 信号合并为 `_MAKER_CHECKER_STAGES` tuple，由 `_route_without_llm()` 统一遍历；异步主流程调用 `route_async()`，同步 `route()` 仅用于测试和脚本
- 意图过滤在规则层之前执行，防止非医疗查询被误升级

### 6.2 Generator Agent

```
系统提示词核心:
  "你是临床综合分析专家。
   任务:
   1. 调用所有必要的 Skills 收集证据
   2. 基于证据做出综合分析
   3. 输出结构化 action_signal
   
   重要: 你的输出将被 Reviewer 严格审查。
   如果证据不足，宁可标注低 confidence，不要假装确定。"

可调 Skills: 全部 9 个（与当前架构一致）

输出:
  {
    "answer": "完整自然语言回答...",
    "action_signal": {
      "result": "总结性结论",
      "evidence": ["证据项1", "证据项2", ...],
      "confidence": 0.82,
      "proposed_action": "recommend_urgent_care"
    },
    "skill_trace": [
      {"skill": "assess_risk", "key_finding": "risk_level=high"},
      {"skill": "clinical_guideline", "key_finding": "ESC 2024胸痛指南"}
    ]
  }
```

**Generator.regenerate() 实现**：

```python
async def regenerate(self, user_query: str, challenges: List[Dict]) -> Dict:
    """REJECT 后修正——接收 Reviewer 的具体驳回理由，重新运行 AgentLoop。"""
    
    # 将 challenges 转为修正指令注入 prompt
    fix_instructions = self._format_challenges(challenges)
    
    regenerate_input = {
        "question": user_query,
        "context": {
            "fix_instructions": fix_instructions,
            # 格式: "上一轮分析存在以下问题，请逐一修正:\n
            #          1. [missed_symptom] 遗漏了'胸闷'症状...\n
            #          2. [outdated_guideline] 引用的2021版指南已有2024更新..."
        }
    }
    
    # 重新运行完整 AgentLoop（重新调用 Skills + 生成分析）
    return await self.run_loop(regenerate_input)

def _format_challenges(self, challenges: List[Dict]) -> str:
    lines = ["上一轮分析存在以下问题，请逐一修正:"]
    for i, c in enumerate(challenges, 1):
        lines.append(f"{i}. [{c['type']}] {c['description']}")
        if c.get("suggested_fix"):
            lines.append(f"   建议修正: {c['suggested_fix']}")
    return "\n".join(lines)
```

### 6.3 Reviewer Agent

```
系统提示词核心:
  "你是临床安全审查专家。
   唯一目标: 证伪 Generator 的结论。
   你不是来提供替代答案的。

   审查维度（按优先级）:
   1. 遗漏风险: Generator 是否遗漏了高危症状或关键证据？
   2. 证据充分性: 每个结论是否有足够证据支撑？
   3. 逻辑一致性: 证据→结论的推理链是否完整？
   4. 时效性: 引用的指南/文献是否是最新版本？
   5. 边界情况: 是否有特殊人群（孕妇/儿童/老人）的例外？

   判据:
   · PASS:      证据充分，推理链完整，无遗漏 → 直接放行
   · CHALLENGE: 有可修复的问题（遗漏证据、confidence偏高、
                边界情况未说明）→ 追加到evidence后放行，标记uncertainty
   · REJECT:    有严重问题（高危症状遗漏、指南误读、
                逻辑矛盾）→ 返回Generator附带理由

   最多1次REJECT（共2轮）。2轮后仍REJECT → 降级为recommend_urgent_care"

可调 Skills (仅验证用):
  · assess_risk       — 独立复查风险评分
  · analyze_symptoms  — 检查是否有遗漏的症状类别
  · clinical_guideline — 查是否有更新版本或遗漏内容
  · search_knowledge  — 查反例、边界情况
  · deep_research     — 查最新研究是否推翻旧结论

禁止调 Skills:
  · recommend_lifestyle — Reviewer不负责给建议
  · disease_code        — 与安全审查无关

输出:
  {
    "verdict": "PASS" | "CHALLENGE" | "REJECT",
    "challenges": [
      {
        "type": "missed_symptom" | "insufficient_evidence" |
               "outdated_guideline" | "logic_gap" | "edge_case",
        "description": "具体的问题描述",
        "severity": "high" | "medium" | "low",
        "suggested_fix": "建议的修正方案"
      }
    ],
    "confidence_adjusted": 0.65
  }
```

### 6.4 Safety Gate

```python
class SafetyGate:
    """确定性安全门控——不经过任何 LLM。
    
    依据: CareGuardAI (2604.26959) — 双轴安全评估 SRA + 证据质量
          OncoAgent (May 2026) — 确定性代码 Critic
    """

    HIGH_RISK_SYMPTOMS = [
        "胸痛", "呼吸困难", "意识模糊", "剧烈头痛",
        "严重出血", "持续呕吐", "高热不退", "突然晕厥",
        "面部下垂", "言语不清", "单侧肢体无力", "咳血",
        "黑便", "呕血", "视力突然丧失"
    ]

    def check(
        self,
        user_query: str,
        action_signal: Dict,
        reviewer_verdict: Optional[Dict] = None
    ) -> GateResult:
        """
        三层确定性检查:
        1. 高危症状硬编码扫描
        2. 证据充分性阈值
        3. 格式与免责声明合规
        """

        # Gate 1: 高危症状硬编码检查
        for symptom in self.HIGH_RISK_SYMPTOMS:
            if symptom in user_query:
                if action_signal.get("proposed_action") != "recommend_urgent_care":
                    return GateResult(
                        passed=False,
                        reason=f"查询含高危症状'{symptom}'，"
                               f"但proposed_action="
                               f"'{action_signal.get('proposed_action')}'"
                               f"而非recommend_urgent_care",
                        gate="high_risk_symptom_check"
                    )

        # Gate 2: 证据充分性检查
        evidence = action_signal.get("evidence", [])
        confidence = action_signal.get("confidence", 0)
        if not evidence and confidence > 0.7:
            return GateResult(
                passed=False,
                reason=f"confidence={confidence}但evidence为空",
                gate="evidence_sufficiency_check"
            )

        # Gate 3: 格式合规检查
        if not action_signal.get("proposed_action"):
            return GateResult(
                passed=False,
                reason="action_signal缺少proposed_action字段",
                gate="format_compliance_check"
            )

        return GateResult(passed=True)

@dataclass
class GateResult:
    passed: bool
    reason: str = ""
    gate: str = ""
```

### 6.5 LeadAgent 表达层

```
系统提示词核心:
  "你是最终答案的表达者。你的角色仅限于:
   1. 用通俗语言表达已经裁决的结论
   2. 补充必要的医学背景知识
   3. 添加标准的免责声明

   绝对禁止:
   · 改变风险等级
   · 改变就医建议
   · 重新评判 Generator 和 Reviewer 谁对谁错
   · 添加未经 Safety Gate 验证的建议

   如果裁决结果包含 uncertainty 标记，你必须在答案中
   明确说明不确定性，并建议线下就医确认。
   
   如果裁决结果来自 FORCED_SAFE_MODE 或 Gate Override，
   你必须用克制语言表达安全建议，不暴露内部流程或实现细节。"
```

### 6.6 MakerCheckerOrchestrator（编排器）

```python
class MakerCheckerOrchestrator:
    """对抗式 Maker-Checker 流程编排器。
    
    负责:
    1. 管理 Generator → Reviewer 循环（最多 2 轮）
    2. 三种 verdict 的路由（PASS/CHALLENGE/REJECT）
    3. FORCED_SAFE_MODE 触发
    4. Safety Gate 调用与 GATE OVERRIDE
    5. 四种终态的收敛
    """

    MAX_RETRIES = 1  # 最多 1 次修正

    def __init__(self, generator, reviewer, safety_gate, lead_agent):
        self.generator = generator
        self.reviewer = reviewer
        self.safety_gate = safety_gate
        self.lead_agent = lead_agent

    async def run(self, user_query: str) -> str:
        retry_count = 0

        # ===== Round 1: 初始生成 + 审查 =====
        gen_output = await self.generator.generate(user_query)
        verdict = await self.reviewer.review(gen_output)

        # ===== 循环: REJECT 且未达上限 → Round 2 =====
        while verdict.verdict == "REJECT" and retry_count < self.MAX_RETRIES:
            retry_count += 1
            gen_output = await self.generator.regenerate(
                user_query,
                challenges=verdict.challenges
            )
            verdict = await self.reviewer.review(gen_output)

        # ===== 循环终止: 仍 REJECT → 强制安全兜底 =====
        if verdict.verdict == "REJECT":
            final_output = self._forced_safe_mode(user_query)
            return await self.lead_agent.express(final_output)

        # ===== CHALLENGE: 追加 evidence，标记 uncertainty =====
        if verdict.verdict == "CHALLENGE":
            gen_output.action_signal["evidence"].extend(
                [c["description"] for c in verdict.challenges]
            )
            gen_output.uncertainty = True

        # ===== Safety Gate =====
        gate_result = self.safety_gate.check(
            user_query,
            gen_output.action_signal
        )

        if not gate_result.passed:
            # GATE OVERRIDE: 硬覆盖，不是驳回
            gen_output.action_signal["proposed_action"] = "recommend_urgent_care"
            gen_output.action_signal["confidence"] = "overridden"
            gen_output.gate_overridden = True

        # ===== LeadAgent 表达 =====
        return await self.lead_agent.express(gen_output)

    def _forced_safe_mode(self, user_query: str) -> Dict:
        """
        强制安全兜底: R2 仍 REJECT 时触发。
        跳过 Reviewer 和 Safety Gate，直接输出 urgent_care。
        """
        return {
            "answer": None,
            "action_signal": {
                "proposed_action": "recommend_urgent_care",
                "confidence": "forced_safe_mode",
                "evidence": ["系统未能确认低风险，按安全原则建议及时就医"],
                "result": "目前无法可靠排除风险，基于安全原则建议立即就医。"
            },
            "forced_safe_mode": True
        }
```

**四个终态的路径追踪**:

| 终态 | 代码路径 |
|------|---------|
| 正常通过 | R1 PASS → Gate PASS → LeadAgent |
| 带质疑通过 | R1/R2 CHALLENGE → 追加 evidence → Gate PASS → LeadAgent |
| Gate 硬覆盖 | 任何路径 → Gate BLOCK → GATE OVERRIDE → LeadAgent |
| 强制安全兜底 | R2 REJECT → FORCED_SAFE_MODE → LeadAgent（跳过 Gate） |

---

## 7. 实现方案

### 7.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `pipeline/action_signal.py` | **新建** | ActionType枚举 + ActionSignal dataclass |
| `pipeline/safety_gate.py` | **新建** | SafetyGate确定性检查 + GateResult |
| `agents/reviewer.py` | **新建** | ReviewerAgent: 对抗式审查者 |
| `agents/generator.py` | **新建** | GeneratorAgent: 综合生成者 |
| `pipeline/orchestrator.py` | **新建** | MakerCheckerOrchestrator: 流程编排 + 循环控制 |
| `core/agent_loop.py` | 修改 | 收集skill_results传给post_process_result |
| `agents/base.py` | 修改 | post_process_result签名增加skill_results参数 |
| `pipeline/router.py` | **新建** | Hybrid Medical Router 分流 |
| `agents/lead.py` | 修改 | express改为纯表达模式；增加SafetyGate调用 |
| `pipeline/entry.py` | 修改 | 集成Router逻辑；双路径执行 |
| `pipeline/__init__.py` | 修改 | 导出新增模块 |
| `agents/skill_registry_mixin.py` | **保留不动** | Skills-Agent两层解耦不动 |

### 7.2 底层组件兼容性与演进路径

#### 总览

| 组件 | 当前实现 | Phase 1（跑通架构） | Phase 2（优化） |
|------|---------|-------------------|-------------------|
| **Skills 注册** | 全部 9 个无差别注册 | 全部注册，靠 prompt 约束 | `register_all_skills(exclude={...})` 硬约束 Reviewer |
| **ShortTermMemory** | 存对话历史，注入 AgentLoop | 沿用，不动 | 不动 |
| **LongTermMemory** | Mem0，存相似案例 | 沿用，不动 | 不动 |
| **RAG (Milvus KB)** | 单例，Skill 内部调用 | 沿用，不动（已是最优） | 不动 |
| **SharedContext** | 多 Agent 黑板模式 | 降级兼容使用 | 核心流转用 MakerCheckerState |
| **Contribution** | dataclass，存 agent_id/result | 沿用，action_signal 放 result 内 | 不动 |
| **ConstraintValidator** | YAML，PreToolUse/PostToolUse hook | 更新 agent_id + 新增少量约束 | 细化 Reviewer 约束 |
| **AutoFixer** | 输出自动修复（免责声明等） | 沿用，不动 | 不动 |
| **审计日志** | 无 | 新增结构化 `MAKER_CHECKER_TRACE` 日志 | 不动 |
| **MakerCheckerState** | 无 | 新增轻量级 dataclass 管理轮次状态 | 不动 |

---

#### Skills 注册

**当前**：`SkillRegistryMixin.register_all_skills()` 自动发现全部 9 个 Skills，无差别注册给所有 Agent。

**Phase 1（兼容优先）**：Generator 和 Reviewer 都注册全部 9 个。Generator 自然需要全部 Skills 做综合分析；Reviewer 靠 system prompt 约束不调 `recommend_lifestyle` 和 `disease_code`。LLM 在明确的 prompt 约束下几乎不会越权调用，MVP 阶段够用。

**Phase 2（硬约束）**：给 `register_all_skills()` 加 `exclude` 参数：

```python
# Generator
self.register_all_skills()  # 全部 9 个

# Reviewer
self.register_all_skills(exclude={
    "recommend_lifestyle",   # 不负责给建议
    "disease_code",          # 与安全审查无关
})
```

实现：在 `discover_skills()` 返回的列表里过滤掉 exclude 中的 function_name，其余注册逻辑不变。**改动量：约 5 行代码。**

> 为什么 Phase 2 才做：Phase 1 目标是跑通流程、验证 Generator-Reviewer 对抗的有效性。prompt 约束在初审阶段足够了——如果 Reviewer 偶尔调了 recommend_lifestyle，不会导致安全问题（它的输出还要经过 Safety Gate），只是不够"干净"。硬约束是锦上添花，不是雪中送炭。

---

#### Memory

**当前**：
- `ShortTermMemory`：存 session 对话历史（user/assistant/tool 消息），注入 `AgentLoop`，用于上下文连续性
- `LongTermMemory`（Mem0）：存相似历史案例，`SwarmCoordinator.process()` 检索后注入 context

**Phase 1（兼容）**：完全沿用。Generator 和 Reviewer 都通过 AgentLoop 获得对话历史上下文。LongTermMemory 检索在 SwarmCoordinator 中统一执行后传入 Generator。

**不需要改动**：两类记忆的设计已经正确分层——短期记忆用于本轮上下文，长期记忆用于跨 session 知识复用。新架构不影响这一层。

---

#### RAG (Milvus KB)

**当前**：`MedicalKnowledgeBase` 单例，Skill 函数内部调用 `kb.search(query, top_k, filter_type)`。Agent 不直接访问 Milvus——通过 Skills 间接访问。

**Phase 1 & 2（不动）**：已是最优设计。RAG 作为 Skill 层的底层能力，Agent 通过 `search_knowledge("query")` 间接调用。这一层与新架构完全正交——不管是一个 Agent 还是两个 Agent、是生成还是审查，都是调同一个 Skill 接口、读同一个 Milvus 库。

---

#### SharedContext

**当前**：为多 Agent 并行黑板模式设计——SubTask 分配、Contribution 收集、Event 发布订阅。

**Phase 1（降级兼容）**：保留 SharedContext 不变，但不作为 Maker-Checker 的核心数据载体。MakerCheckerOrchestrator 内部用 `MakerCheckerState`（见下方）管理轮次状态。SharedContext 主要用于：
- 降级路径：如果回退到旧三 Agent 路径，继续用 SharedContext
- 后续扩展：subagent 场景可以复用

**Phase 2（精简）**：如果 Maker-Checker 稳定后确认不需要 SharedContext 的黑板特性，可以简化或移除。

---

#### MakerCheckerState（新增）

**Phase 1（新增）**：一个轻量级 dataclass，专门管理 Generator-Reviewer 之间的轮次状态。**改动量：一个文件，约 30 行。**

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict

@dataclass
class RoundState:
    """单轮 Maker-Checker 的状态快照"""
    round_number: int
    generator_output: Optional[Dict] = None   # answer + action_signal + skill_trace
    reviewer_verdict: Optional[Dict] = None   # verdict + challenges + confidence_adjusted

@dataclass
class MakerCheckerState:
    """Maker-Checker 流程的完整状态"""
    session_id: str
    user_query: str
    rounds: List[RoundState] = field(default_factory=list)
    final_terminal: Optional[str] = None
    # "normal" | "challenged" | "gate_override" | "forced_safe"
    gate_result: Optional[Dict] = None
```

**为什么需要**：Reviewer 需要拿到 Generator 的结构化输出（action_signal + skill_trace），而不是从消息历史里自己重新解析。ShortTermMemory 存的是 LLM 对话历史（文本流），MakerCheckerState 存的是结构化的轮次状态——两者互补，不冲突。

---

#### ConstraintValidator

**当前**：`agent_constraints.yaml` 定义 per-agent 的能力和禁止行为，`ConstraintValidator` 在 AgentLoop 的 PreToolUse/PostToolUse hook 中检查。

**Phase 1（微调）**：新增 generator/reviewer 的约束项到 YAML：

```yaml
# agent_constraints.yaml
generator:
  capabilities:
    - clinical_analysis
    - evidence_synthesis
  required_outputs:
    - action_signal
    - skill_trace

reviewer:
  capabilities:
    - safety_review
    - evidence_verification
  forbidden_outputs:
    - treatment_recommendation   # 禁止输出治疗建议
    - alternative_diagnosis       # 禁止输出替代诊断
```

**改动量：约 15 行 YAML。**

---

#### 审计日志

**Phase 1（新增）**：在 MakerCheckerOrchestrator 中加结构化日志，记录每轮的关键决策：

```python
logger.info("MAKER_CHECKER_TRACE", extra={
    "session_id": state.session_id,
    "round": round_num,
    "verdict": verdict,
    "challenges_count": len(challenges),
    "final_terminal": state.final_terminal,
    "gate_passed": gate_result.passed,
})
```

**改动量：3-4 行 loguru 调用。** 不需要新的日志系统，loguru 的结构化 extra 足够。

---

#### 三个旧 Agent 类

**Phase 1（不动）**：`DiagnosticAgent`、`ResearchAgent`、`ConsultationAgent` 三个类完整保留。
- Generator 复用 `SkillRegistryMixin` 的 `register_all_skills()` 逻辑
- 降级路径：如果 Maker-Checker 异常，可以回退到旧三 Agent 模式
- 不破坏现有测试

**Phase 2（按需清理）**：如果 Maker-Checker 稳定运行一段时间后，可以考虑标记为 deprecated。

### 7.3 降级策略

| 场景 | 降级行为 |
|------|---------|
| Router 判断为简单问题 | 跳过 Reviewer，Generator → Safety Gate → LeadAgent |
| Reviewer 2轮后仍 REJECT | 降级处理，强制 `recommend_urgent_care` + 免责声明 |
| Safety Gate BLOCK | 降级处理，追加免责声明后输出 |
| Generator 或 Reviewer 异常 | 降级到旧 ConflictResolver 路径 |
| action_signal 缺失 | 降级到旧 Normalizer NLP 解析路径 |

---

## 8. 实现步骤

### Phase 1: 基础契约（1-2 天）

**Step 1.1**: 新建 `pipeline/action_signal.py`
- `ActionType` 枚举（8 种 action）
- `ActionSignal` dataclass（result, evidence, confidence, proposed_action）
- `to_dict()` / `from_dict()` 序列化方法
- 单元测试：序列化往返、字段验证

**验证**: `python -m pytest tests/test_action_signal.py`

### Phase 2: Infrastructure 改造（1-2 天）

**Step 2.1**: 修改 `core/agent_loop.py`
- 收集 skill_results 列表
- 传给 `post_process_result(result, final_answer, skill_results=skill_results)`

**Step 2.2**: 修改 `agents/base_agent.py`
- `post_process_result` 签名增加 `skill_results=None` 参数
- 默认实现忽略新参数（向后兼容）

**验证**: 运行现有 `examples/test_all.py`，确保所有测试通过

### Phase 3: Generator Agent（2-3 天）

**Step 3.1**: 新建 `agents/generator.py`
- 继承 `BaseAgent` + `SkillRegistryMixin`
- 注册全部 9 个 Skills
- System prompt: 综合分析 + 结构化输出
- `post_process_result`: 从 skill_results 提取结构化数据生成 action_signal
  - 从 `assess_risk` 结果提取 risk_level → proposed_action
  - 从 `clinical_guideline` 结果提取 evidence
  - 从 `analyze_symptoms` 结果提取 patterns
  - confidence 计算: 有高危症状 0.85-0.95, 有指南证据 +0.05, 无证据 -0.10

**验证**: 用测试医疗查询验证 Generator 产出合法 action_signal

### Phase 4: Reviewer Agent（2-3 天）

**Step 4.1**: 新建 `agents/reviewer.py`
- 继承 `BaseAgent` + `SkillRegistryMixin`
- 注册全部 9 个 Skills（同 Generator）。Phase 1 靠 system prompt 约束不调 `recommend_lifestyle` 和 `disease_code`，Phase 2 改用 `register_all_skills(exclude={...})` 硬约束。参见 [7.2 Skills 注册](#skills-注册)
- System prompt: 对抗式证伪
- `review()` 方法:
  - 接收 Generator 的 action_signal + skill_trace
  - 构建结构化审查 prompt（见下方"Reviewer.review() 实现细节"）
  - 通过 `self.run_loop()` 运行 AgentLoop：LLM 审查 → 可选调用验证 Skills 交叉验证 → 输出结构化 verdict
  - 返回 verdict + challenges + confidence_adjusted

**Reviewer.review() 实现细节**：

```python
async def review(self, generator_output: Dict) -> ReviewerVerdict:
    """审查 Generator 输出。使用 AgentLoop 运行 LLM 审查流程。"""
    
    # 构建结构化审查输入
    review_input = {
        "question": self._build_review_question(generator_output),
        "context": {
            "action_signal": generator_output["action_signal"],
            "skill_trace": generator_output.get("skill_trace", []),
        }
    }
    
    # 通过 AgentLoop 运行审查（LLM 决定是否调 Skill 做交叉验证）
    result = await self.run_loop(review_input)
    
    # post_process_result 提取结构化 verdict
    return result["reviewer_verdict"]

def _build_review_question(self, gen_output: Dict) -> str:
    """将 Generator 输出转化为审查问题"""
    signal = gen_output["action_signal"]
    return f"""请审查以下临床分析：

结论: {signal['result']}
建议行动: {signal['proposed_action']}
置信度: {signal['confidence']}
证据: {signal['evidence']}

调用的 Skills: {[t['skill'] for t in gen_output.get('skill_trace', [])]}

逐项检查:
1. 查询中的每个症状是否都被分析覆盖？
2. 每条证据是否支撑结论？是否有遗漏的反面证据？
3. 引用的指南/文献是否是最新版本？
4. 置信度是否与证据强度匹配？
5. 是否有特殊人群（孕妇/儿童/老人）的例外情况未说明？

输出 verdict (PASS/CHALLENGE/REJECT) + challenges 列表。"""
```

**Reviewer.post_process_result()**：从 LLM 的最终回答中提取结构化 verdict：

```python
async def post_process_result(self, result, final_response, skill_results=None):
    # 从 LLM 输出中解析 verdict
    verdict = self._parse_verdict(final_response)
    result["reviewer_verdict"] = {
        "verdict": verdict["verdict"],           # PASS | CHALLENGE | REJECT
        "challenges": verdict["challenges"],     # [{type, description, severity, suggested_fix}]
        "confidence_adjusted": verdict.get("confidence_adjusted"),
    }
    return result
```

**验证**: 模拟 Generator 输出（含刻意错误），验证 Reviewer 正确识别

### Phase 5: Safety Gate（1 天）

**Step 5.1**: 新建 `pipeline/safety_gate.py`
- `SafetyGate` 类（确定性代码，无 LLM 调用）
- 三层检查: 高危症状扫描 / 证据充分性 / 格式合规
- `GateResult` dataclass

**验证**: 单元测试覆盖所有 Gate 的 PASS 和 BLOCK 场景

### Phase 6: Orchestrator（2 天）

**Step 6.1**: 新建 `pipeline/orchestrator.py`
- `MakerCheckerOrchestrator` 类
- `run()` 方法: Round 1 → 循环判断 → Round 2（可选）→ 终态收敛
- `_forced_safe_mode()` 方法: REJECT 超限时的安全兜底
- 集成 Generator, Reviewer, SafetyGate, LeadAgent
- 日志记录: 每轮 Generator/Reviewer 输出、verdict、终态路径

**验证**: 模拟全部四种终态（正常/带质疑/Gate覆盖/强制兜底）

### Phase 7: Router + 编排集成（2-3 天）

**Step 7.1**: 修改 `pipeline/entry.py`
- 集成 `pipeline/router.py` 的 Hybrid Medical Router
- 简单路径: Generator → Safety Gate → LeadAgent
- 对抗路径: Generator → Reviewer → (可选重做) → Safety Gate → LeadAgent
- 降级处理逻辑

**Step 7.2**: 修改 `agents/lead.py`
- synthesis prompt 改为纯表达模式
- 集成 SafetyGate 调用

**验证**: 端到端测试简单路径和对抗路径

### Phase 8: 集成与回归（1-2 天）

**Step 8.1**: 运行 `examples/test_all.py`，确保所有现有测试通过
**Step 8.2**: 手动测试: 真实医疗问题触发对抗路径
**Step 8.3**: 日志验证: 确认 Router 决策、Reviewer verdict、Safety Gate 检查正常

---

## 9. 面试论述指南

### 核心论点（30 秒版本）

> 我的项目从三 Agent 并行 + 规则仲裁演进到了对抗式 Maker-Checker 架构。这个变化受三个关键研究的启发：Multi-Agent Evaluation Loops (2026) 在 900 条医疗查询中证明 Generator-Reviewer 对抗减少 89% 伦理违规；adversarial-ai-review 在生产中验证了对抗式证伪将误报率从 60% 降到 7.3%；Consensus Trap (2026) 从理论上证明了平权投票的脆弱性。

### 为什么是两个 Agent 而不是三个？（常见追问）

> 三个平权 Agent 并行的本质是"多次采样 + 隐式投票"。Consensus Trap (2026) 证明当多数 Agent 共同犯错时，投票会放大错误。我的设计是两个 Agent 但关系不对等——Reviewer 的 KPI 是证伪 Generator，不是提供另一个答案。这种结构性对抗是单 Agent 自审查做不到的——MAR (2025) 证明了 LLM 自反思会重复同样的错误。

### 同一个 LLM，对抗有意义吗？（核心质疑）

> 有意义，因为"构建"和"证伪"是不同的认知操作。同一个 LLM 在两种对立的 prompt 框架下行为不同——就像同一个程序员写代码和 review 代码时注意力分配不同。A-HMAD 的消融实验也证实了这一点。但如果你想让效果最大化，Generator 和 Reviewer 用异构模型会更好——X-MAS (2025) 证明异构组合比同构高 47%。这是预留的下一步优化方向。

### 安全怎么保证？（安全追问）

> 双层防线。第一层是 Reviewer 的结构化审查——输出具体的 violation 类型和 required_fix，不是模糊评分。第二层是 Safety Gate——确定性代码，高危症状硬编码扫描，不经过任何 LLM。CareGuardAI (2026) 和 OncoAgent (2026) 的共识是安全必须是代码级 Gate。我的 Safety Gate 不关心风险是哪个 Agent 评估的——它只检查 query 中的高危症状是否在最终的 proposed_action 中得到了体现。

### 简单问题也要走对抗吗？（成本追问）

> 不需要。OneFlow (2026) 证明简单任务上多 Agent 不提供额外收益。Anthropic 官方指南也建议"Start simple, escalate when needed"。我的 Router 不是简单复杂度打分，而是 Hybrid Medical Router：只有简单且明确低危、或明确非医疗决策的问题才走单 Agent；安全红线、循证需求、进展性症状、个人医疗意图、语义高风险或 LLM 仲裁为 maker_checker 时启动对抗。换句话说，simple 必须被证明，风险、复杂和不确定都进入 Maker-Checker。

### 和 LangGraph / CrewAI 比有什么不同？（框架追问）

> LangGraph 和 CrewAI 提供的是通用编排框架，但没有医疗领域的内置安全机制。CrewAI 的 Agent 间自然语言通信还会导致 token 爆炸（Redwerk 2026 报告单次运行消耗 4500 token）。我的架构专为医疗场景设计：双层安全防线、结构化 action_signal 通信（PatchBoard 风格）、确定性 Safety Gate。这不是通用框架，是领域特化的安全架构。

### 循环机制怎么设计的？最多几轮？为什么？（循环追问）

> 最多 2 轮——1 次初始生成 + 最多 1 次修正。这个数字来自两个依据：OncoAgent (2026) 的 Critic 硬编码 max 2 retries；Multi-Agent Evaluation Loops 统计平均 2.34 轮收敛。A-HMAD 还发现 5 轮以上会出现新的混乱——Agent 开始质疑自己之前正确的结论。
>
> 循环终止后有三条出路：PASS 直接放行、CHALLENGE 追加 evidence 标记 uncertainty 后放行、REJECT 触发 FORCED_SAFE_MODE 强制输出 urgent_care。不存在"一直循环修不好"的情况——硬上限 + 安全兜底覆盖了所有路径。

### 为什么不用单 Agent + 对抗式 Skill？（架构设计追问）

> 在架构设计时我对比了两种方案：单 Agent + 对抗式 Skill，还是拆成两个独立 Agent。
>
> **方案 A（单 Agent + 对抗式 Skill）**：保留单 Agent + Skills 架构，新增一个 `adversarial_review` Skill 实现自我审查。实现简单，成本低，UBC Skills Scaling Law ([arXiv 2601.04748](https://arxiv.org/abs/2601.04748)) 证明 SAS 在效率上大幅优于 MAS——token↓53.7%，延迟↓49.5%，准确率持平或略升。
>
> **方案 B（Maker-Checker 双 Agent）**：Generator 和 Reviewer 是两个独立 Agent，各有自己的 AgentLoop、消息历史、Tool 调用。Orchestrator 硬编码控制循环次数和失败处理。
>
> 我选了方案 B，核心原因四个：
>
> 1. **上下文隔离 > 模型异构**。方案 A 中 Skill 虽然可以调不同 LLM，但 Skill 输出会回到 Agent 的同一个 AgentLoop 上下文中——Contextual Drag ([arXiv 2602.04288](https://arxiv.org/abs/2602.04288), 2026) 证明历史中的失败回答会污染后续推理，导致 10-20% 性能下降，且外部反馈也无法消除。方案 B 的 Reviewer 有完全独立的 AgentLoop，从空白上下文开始审查，拿到的是 Generator 的结构化输出（action_signal + skill_trace），不接触 Generator 的推理历史。
>
> 2. **执行权归属不同**。方案 A 中 Skill 是 Agent 的工具——Agent 的 LLM 自主决定是否采纳审查意见，可能忽略。方案 B 中 Reviewer 的 verdict 由 Orchestrator 的 Python 代码强制执行——REJECT 时强制返回 Generator 修正，2 轮后仍 REJECT 触发 FORCED_SAFE_MODE，Generator 无法绕过。这是"建议"和"强制"的本质区别。
>
> 3. **UBC Skills Scaling Law 明确支持这一选择**。论文 ([arXiv 2601.04748](https://arxiv.org/abs/2601.04748)) Proposition 3.1 列出三种 SAS 无法替代 MAS 的场景，第一种就是"非可序列化通信——需要真正并行独立推理的辩论/对抗网络"。我们的 Reviewer 需要独立于 Generator 进行证伪推理，正好属于这一类别。这不是打论文的脸，而是遵循论文划定的 MAS 适用边界。
>
> 4. **Maker-Checker 有生产验证数据**。Generator 负责回答，Checker 只负责挑错、校验事实、安全风险和格式合规。[adversarial-ai-review](https://github.com/gaurav-yadav/adversarial-ai-review) 在 500+ PRs 上验证了这种模式将误报率从单次审查的 30-60% 降到 7.3%。
>
> 成本上说，Maker-Checker 多一次 LLM 调用（Reviewer），但 Reviewer 不调全部 Skills——它拿到的是 Generator 的结构化输出和 skill_trace，只在发现可疑点时选择性重调 Skill 做交叉验证。Round 1 PASS 时整体延迟只增加一次轻量 LLM 调用。
>
> 另外，如果你追问"你们只有 9 个 Skill，UBC 论文说的 SAS 优势全在效率维度——为什么要为一个 9 个 Skill 的系统承受 Maker-Checker 的额外成本？" 答案是：我们系统的瓶颈从来不是 Skill 数量（9 个远低于论文的 50-100 崩塌阈值），而是医疗安全。论文说的是 SAS 在效率维度可以替代 MAS——它没有说 SAS 在安全维度可以替代 MAS。Maker-Checker 不是为了效率，是为了安全。这是两个不同的优化目标。

### REJECT 和 BLOCK 有什么区别？（设计追问）

> REJECT 是 Reviewer 说的"你的分析有漏洞"——推理问题，可以修正，所以返回 Generator 重做。BLOCK 是 Safety Gate 说的"你的结论违反安全红线"——不是推理问题，不需要修正推理，直接硬覆盖结论。REJECT 触发循环（最多 1 次），BLOCK 不触发循环（直接覆盖后放行）。FORCED_SAFE_MODE 跳过 Safety Gate——因为它已经把 action 设为 urgent_care 了，Gate 的检查已隐含通过。

---

## 10. 类似项目对比

### GRA Framework — Generator-Reviewer-Adjudicator（架构最相似）

**论文**: [arXiv 2504.12322](https://arxiv.org/abs/2504.12322) (Apr 2025) | **GitHub**: [GX-XinGao/GRA](https://github.com/GX-XinGao/GRA) | **机构**: 上海人工智能实验室 + 中国人民大学

GRA 用多个 7-8B 小模型组成 Generator-Reviewer-Adjudicator 三步流水线合成高质量训练数据，质量媲美 72B 大模型。

**架构**: Generator（随机分配小模型）→ 多模型 Reviewer 委员会（两轮 6 维度评分）→ Adjudicator（分歧 > 阈值时仲裁）→ 后处理

**与我们的对比**:

| | GRA | 本架构 |
|---|---|---|
| **模式** | Generator-Reviewer-Adjudicator | Generator-Reviewer-Gate |
| **Genesis** | 一个 Generator | 一个 Generator |
| **Nexus** | 多模型 Reviewer 委员会 → 分歧送 Adjudicator 裁决 | 单一 Reviewer → 确定性 Safety Gate 硬覆盖 |
| **分歧处理** | "合并分歧"——Adjudicator 独立复审选出最佳 | "不安全就拦截"——BLOCK 硬覆盖，FORCED_SAFE_MODE 兜底 |
| **优化目标** | 数据合成质量 | 临床输出安全 |
| **模型** | 5 个异构 7-8B 开源模型随机分配 | 同模型（Phase 1），预留异构接入 |
| **领域** | 通用（代码/数学/推理等 7 领域） | 医疗临床决策 |

**关键区别**: GRA 解决的是"质量"——选出最好的。我们解决的是"安全"——拦截不安全的。GRA 的 Adjudicator 是 LLM 裁决分歧，我们的 Safety Gate 是确定性代码硬覆盖红线。

---

### MATRIX — 临床安全对话评估（领域最相似）

**论文**: [arXiv 2508.19163](https://arxiv.org/abs/2508.19163) (Aug 2025) | **机构**: Ufonia Ltd + NHS + Google DeepMind + University of York

MATRIX 是首个将结构化安全工程与可扩展对话 AI 评估相结合的临床安全审计框架。

**架构**: 安全场景分类法（14 种危险 × 10 临床领域）→ PatBot（模拟患者）→ BehvJudge（安全评估器，F1=0.96，敏感度=0.999）

**与我们的对比**:

| | MATRIX | 本架构 |
|---|---|---|
| **定位** | 离线安全审计框架 | 在线推理安全机制 |
| **核心问题** | "这个临床 AI 是否安全？" | "这次回答在输出前是否安全？" |
| **Patient** | PatBot 模拟患者生成测试对话 | 真实用户查询 |
| **Reviewer** | BehvJudge 检测安全故障（事后评分） | Reviewer 证伪结论（事前拦截） |
| **部署** | 离线评估工具 | 在线推理流水线 |
| **输出** | 安全评估报告 | 安全审查后的最终回答 |

**关键区别**: MATRIX 是"审计你"——告诉你哪里不安全。我们是"保护你"——在输出给用户之前已经过了 Reviewer + Safety Gate。

---

### 面试时如何使用这两个对比

> 本架构的 Maker-Checker 模式与两个相关工作有可比性：GRA（上海 AI Lab, 2025）同属 Generator-Reviewer 范式，但 GRA 的目标是数据合成质量，分歧时靠 LLM Adjudicator 选最佳——我们是医疗安全，分歧时靠确定性 Safety Gate 硬覆盖。MATRIX（NHS/DeepMind, 2025）同属临床安全方向，但它是离线的安全审计框架，在事后告诉你哪里不安全——我们是内嵌于推理流水线的在线安全机制，在输出前拦截不安全内容。

---

## 11. 实现状态

### ✅ 已完成

| 组件 | 位置 | 说明 |
|------|------|------|
| ActionSignal 数据契约 | `pipeline/action_signal.py` | ActionType枚举、CONFLICT_PAIRS、RISK_TO_ACTION、CONFIDENCE_BASE |
| SafetyGate | `pipeline/safety_gate.py` | 3个独立门检查 + apply_gate_override() |
| GeneratorAgent | `agents/generator.py` | 继承BaseAgent+SkillRegistryMixin，generate()/regenerate() |
| ReviewerAgent | `agents/reviewer.py` | 对抗式审查，ReviewerVerdict结构化判决，**硬约束排除2个Skills** |
| LeadAgent | `agents/lead.py` | express()纯表达模式，不仲裁 |
| MakerCheckerOrchestrator | `pipeline/orchestrator.py` | 2轮循环、3种verdict路由、4种终态收敛 |
| Router | `pipeline/router.py` | Simple Intent Guard + MakerCheckerStage + Semantic Recall + LLM 仲裁 |
| Terminal | `pipeline/terminal.py` | 4种终态常量 |
| 入口 | `pipeline/entry.py` | process_with_maker_checker()双路径执行 |
| Agent基类 | `agents/base.py` | 支持max_tool_calls可配置 + skill_results传递 |
| Skill自动注册 | `agents/skill_registry_mixin.py` | 支持exclude参数，kebab/snake双格式 |
| Skill动态加载 | `core/skill_loader.py` | DEFAULT_SKILLS_DIR常量化、SKILL.md解析、函数加载 |
| Skill注册表 | `core/skill_registry.py` | register/execute/to_openai_format |
| LLM客户端 | `core/llm_client.py` | surrogate字符清洗、消息清洗 |
| 单元测试 | `tests/` | 单元测试 + Router eval fixtures，覆盖核心终态与路由边界 |
| 配置安全 | `config.py` | API Key改为环境变量，.env.example + .gitignore |
| 日志降噪 | 全项目 | 注册/初始化日志→DEBUG级别 |
| 残留清理 | 全项目 | 0个旧路径(saintgeo/swarm/medix)、0个API Key泄露 |
| 独立部署 | `maker-checker/` | 从原项目剥离为独立项目，`python main.py`启动 |

### 🔲 待实现 (Phase 2)

| 项目 | 优先级 | 说明 |
|------|:---:|------|
| Generator/Reviewer 异构模型 | 高 | 当前同模型，X-MAS证明异构+47%。改初始化时传不同model_name |
| ConstraintValidator YAML更新 | 中 | 新增generator/reviewer约束项 |
| MakerCheckerState dataclass | 中 | 轻量级轮次状态管理 |
| 端到端集成测试(真实LLM) | 低 | 用真实LLM验证完整Maker-Checker管道 |

## 附录：关键术语对照

| 中文 | 英文 | 出处 |
|------|------|------|
| 对抗式生成-审查 | Adversarial Maker-Checker | adversarial-ai-review (2025) |
| 结构化驳回 | Structured Rejection | Multi-Agent Evaluation Loops (2026) |
| 确定性安全门控 | Deterministic Safety Gate | CareGuardAI + OncoAgent (2026) |
| 证据交叉验证 | Cross-Validation of Evidence | adversarial-ai-review (2025) |
| 置信度校准 | Confidence Calibration | A-HMAD (2025) |
| 驳回-重做闭环 | Reject-Redo Loop | OncoAgent (2026) |
| 混合医疗路由 | Hybrid Medical Routing | OneFlow (2026) + Anthropic Agent Guide + 本项目实现 |
| 结构性对抗 | Structural Adversariality | Consensus Trap (2026) |
