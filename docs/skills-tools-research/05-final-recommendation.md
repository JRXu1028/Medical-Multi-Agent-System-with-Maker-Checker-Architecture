# 最终推荐方案与取舍分析

本文给出 Skills / Tools 体系的最终建议。它基于外部调研、当前项目代码能力和本地 progressive loading 实验，不直接替换现有主架构。

## 总体判断

当前主架构应保持：

```text
Router → Maker → Checker / PreStopPolicy → SafetyGate → ResponseRenderer
```

这条主链路不需要为 Skills 扩展而改变。真正需要优化的是 Maker 内部的 Skill loading 和 Tool visibility：

```text
Skills:
  方法论、checklist、red lines、tool notes

Tools:
  可执行 API/function，返回 ToolResult + EvidenceRecord

Checker / PreStopPolicy:
  独立安全与过程约束，不相信 Maker 自报

SafetyGate:
  最终输出硬兜底
```

## 最终推荐

推荐下一步采用：

```text
Cluster Hybrid Progressive Skill Loading
```

具体是：

```text
1. 用少量高精度 safety implication rules 补齐关键组合场景
2. 用 cluster gating 缩小候选 Skill 范围
3. 在候选范围内做轻量 retrieval top-k
4. 每轮默认注入 2-4 个 SKILL.md
5. Maker 仍在 ReAct-like loop 中自主选择工具
6. Checker / PreStopPolicy 继续独立检查 required tools、evidence 和安全流程
```

推荐理由：

| 维度 | 结论 |
|---|---|
| 安全 | 本地实验中 safety full recall 从当前 proxy 的 0.364 提升到 0.909。 |
| 上下文 | 平均约 817 token proxy，比全量注入 7550 token proxy 小很多。 |
| 速度 | 本地 resolver p95 约 0.081ms；未来可省掉当前 SkillSelection LLM 的额外调用。 |
| 可扩展 | Skills 增加后可先按 cluster 缩小范围，而不是全 catalog 检索或全量注入。 |
| 面试表达 | 能讲清楚“bounded agency”：Maker 有自主性，安全和证据由独立约束保证。 |

## 为什么不推荐其他方案

### 不推荐全量注入

全量注入召回最高，但不是 progressive disclosure。它会带来：

- token 成本高
- 无关方法论干扰
- 工具选择噪音
- 扩展到 50+ Skills 后不可持续

### 不推荐纯 LLM 选择

当前 SkillSelectionPass 是合理起点，但不适合作为 20+ Skills 的最终方案：

- 多一次 LLM 调用，增加延迟。
- LLM 对组合风险召回不稳。
- 如果 Maker 没选到关键 Skill，后续虽然有 PreStopPolicy 兜底，但会增加 repair loop。

### 不推荐纯关键词规则

纯规则快，但覆盖和维护都差。适合做 safety implication，不适合做完整 Skill selection。

### 不推荐现在上 MCP

MCP 是工具协议，不是当前瓶颈。项目目前只有本地 RAG、药物、化验、memory 等工具，还没有复杂外部工具 server、权限隔离、部署编排需求。现在做 MCP 容易变成包装层，面试价值不如 RAG / Memory / Checker / ToolResult。

### 谨慎看待 Signal Catalog

Signal Catalog 的价值是统一 Router、PreStopPolicy、SkillResolver 的医学信号定义，避免同一知识写三遍。

但当前不建议立即实现：

- 当前规则量还可控。
- 过早配置化会增加复杂度。
- 本次实验显示只需少量 safety implication rules 就能显著提升召回。

建议触发条件：

```text
Skills > 30
PreStopPolicy rules > 15
Router / PreStopPolicy / SkillResolver 出现明显不一致
多人维护开始频繁改同一类医学信号
```

到那时再把高危症状、用药风险、报告指标、心理危机、特殊人群等抽成共享 catalog。

## 推荐落地路线

### Phase A: 文档和离线验证

已完成：

- 医学 Agent / Skills 调研报告
- 24 个 Skills Catalog
- Skill-Tool Mapping / Tool Registry 设计
- Progressive Skill Loading 本地实验
- 最终推荐方案

### Phase B: Skills 重写

已完成全部 24 个 Maker-facing SKILL.md：

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

每个 SKILL.md 保持短小：

```text
description
when_to_load
suggested_tools
Method
Tool Notes
Red Lines
```

不要写疾病百科，不要写硬约束，不要写长医学知识。

本次实施还完成了两个拆分：

```text
evidence_research
  -> guideline_research
  -> evidence_comparison
  -> source_quality_appraisal

lifestyle_chronic_care
  -> chronic_care
  -> lifestyle_coaching
  -> nutrition_weight_management
  -> rehabilitation_exercise_safety
```

这样避免旧粗粒度 Skill 和新 catalog 同时存在，减少 Maker 在 SkillSelectionPass 中看到的重复能力边界。

### Phase C: SkillResolver

已实现 `core.skill_resolver.SkillResolver`，并在 `GeneratorAgent` 默认启用 `cluster_hybrid` 策略。

当前接口：

```python
class SkillResolver:
    def resolve(self, *, user_query: str, skill_docs: Mapping[str, SkillDoc]) -> SkillResolution:
        ...

class SkillResolution:
    selected_skill_ids: List[str]
    safety_implied_skill_ids: List[str]
    clusters: List[str]
    scores: Dict[str, float]
    reasons: List[str]
    resolver_version: str = "cluster_hybrid_v1"
```

运行位置：

```text
AgentLoop 内部
Maker LLM 第一次调用前
不作为 tool call
不进入 tool_trace
不生成 evidence
```

### Phase D: Tool Visibility Control

已实现 `core.tool_visibility.ToolVisibilityPolicy`。AgentLoop 会在 SkillResolver/SkillSelectionPass 后，根据 `loaded_skills` 过滤 Maker 可见工具：

```text
selected_skills -> visible_tools
```

示例：

```text
health_education:
  medical_kb_search

medication_safety + drug_interaction:
  drug_safety_lookup
  medical_kb_search

guideline_research + evidence_comparison:
  guideline_search
  medical_kb_search
  deep_research
```

质量门槛：

```text
required-tool recall 不下降
Checker REJECT 不异常上升
SafetyGate override 不异常上升
deep_research trigger rate 明显下降
```

### Phase E: 工具补齐

已完成：

```text
risk_rule_check
imaging_reference_lookup
vital_sign_reference_lookup
```

理由：

- `risk_rule_check` 作为 legacy `assess_risk` 的现代结构化补充，直接增强安全主链路。
- `imaging_reference_lookup` 覆盖 CT/MRI/肺结节等高频问法。
- `vital_sign_reference_lookup` 覆盖血压、血氧、心率、心电图，安全价值高。

下一批工具：

```text
renal_liver_dose_lookup
pregnancy_pediatric_safety_lookup
vaccine_schedule_lookup
clinical_calculator
```

## 面试讲法

可以这样讲：

> 我没有把医疗 Agent 改成固定 workflow，而是把 Skills / Tools 分层：Skills 是渐进式披露的方法论，Tools 是可执行函数并返回结构化证据。第一版用 LLM 读取 Skill Index 选择 SKILL.md，后来我通过离线 eval 发现它在组合医疗风险上召回不稳，比如“孕妇 + 发烧 + 用药”容易只选 pregnancy skill，漏掉 medication 和 symptom triage。所以我设计了 Cluster Hybrid Skill Loading：少量高精度 safety implication rules 先补齐关键组合，再用 cluster gating 和轻量 retrieval 选择 2-4 个 Skills。实验中 safety full recall 从 0.364 提升到 0.909，平均上下文只有约 817 token proxy。Maker 仍然在 ReAct-like loop 中自主选择工具，但 Checker / PreStopPolicy 独立检查 required tools 和证据链，保证安全不依赖 Maker 自觉。

## 未完成和不确定

1. 本实验没有调用真实 LLM，仍需做在线 A/B。
2. Fixtures 只有 24 条，覆盖有限；上线前应扩到 100-300 条。
3. SkillResolver 已接入 Generator 默认路径，但仍需要真实 LLM A/B 验证 latency、tool-call precision 和 Checker reject rate。
4. Tool visibility control 已实现，但还需要扩大 required-tool eval，防止过度过滤。
5. 孕儿、肝肾剂量、疫苗、计算器等专用工具仍未补齐。
6. Signal Catalog 暂缓，但当规则规模变大时可能需要重做统一信号层。

## 最终取舍

现在最好的方向不是：

```text
更多 Skills
更多 Tools
更多 Agent
更多 prompt
```

而是：

```text
更清楚的 Skill 边界
更结构化的 ToolResult
更小的上下文加载
更强的安全补齐
更可测的 tool-call / RAG / Checker eval
```

这条路线既服务面试，也更接近可工业落地的医疗 Agent runtime。
