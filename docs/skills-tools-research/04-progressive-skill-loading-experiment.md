# Progressive Skill Loading 实验报告

本文比较 6 种 Progressive Skill Loading 方案。实验目标是找出在当前项目中更适合扩展到 20+ Skills 的加载策略：既要快、上下文小，又不能牺牲医疗安全和工具调用准确性。

## 实验边界

本实验是本地离线实验，不调用真实 LLM。它评估的是“Skill 选择策略本身”的可复现表现，而不是供应商模型的生成质量。

这样设计的原因：

- LLM 输出有随机性，不适合第一轮评估加载策略。
- 当前要比较的是 Skill catalog、触发规则、检索策略、上下文成本。
- 真正上线前仍需要补一轮真实 LLM A/B。

## 实验数据

### Skill Catalog

实验使用 24 个候选 Skills，对应 `02-skills-catalog.md`：

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

### Query Fixtures

实验使用 24 条覆盖真实医疗问答场景的 fixtures：

| 类别 | 示例 |
|---|---|
| 急症 / 症状 | 胸痛呼吸困难、腹痛呕吐头晕、血氧 92%、房颤血压 180。 |
| 心理危机 | 不想活、自杀自残风险。 |
| 用药安全 | 华法林 + 布洛芬、漏服降压药、肾功能异常用药、孕期发热用药。 |
| 报告解读 | 尿酸 520、白细胞偏高、肺结节 CT、心电图房颤。 |
| 科普 / 比较 | CT 和 MRI 区别、HPV 疫苗必要性、家用血氧仪。 |
| 慢病 / 生活方式 | 高血压咖啡、糖尿病饮食运动、睡眠血糖、减脂蛋白质。 |
| Memory | 用户提到上次青霉素过敏，再问牙疼用药。 |

每条 fixture 人工标注 expected skills，并标记是否 safety critical。

## 比较的 6 种方案

| 方案 | 描述 | 优点 | 风险 |
|---|---|---|---|
| S1 Full Injection | 一次注入全部 24 个 Skill body。 | 召回最高，不会漏 Skill。 | 上下文巨大、噪音高、工具选择更慢。 |
| S2 Index Top3 Proxy | 模拟当前“LLM 读取 Skill Index 后选择 top3”。 | 保留 Maker 自主选择，架构简单。 | 对组合风险场景召回差，且多一次 LLM 调用。 |
| S3 Keyword Rules | 纯关键词/规则选 top3。 | 极快、无需 LLM。 | 维护成本高，覆盖不足，容易漏组合语义。 |
| S4 TF-IDF Retrieval | 用字符 ngram + TF-IDF 检索相关 Skill top3。 | 快、上下文小、比关键词泛化强。 | 对安全组合关系理解不足。 |
| S5 Hard + Retrieval | 高精度医疗安全规则先补齐，再用检索补充，最多 4 个。 | 安全召回显著提升，上下文仍小。 | 需要维护少量高风险组合规则。 |
| S6 Cluster Hybrid | 先匹配能力簇，再簇内检索，同时叠加硬安全规则，最多 4 个。 | 与 S5 质量接近，局部检索更快，适合 20+ Skills 扩展。 | 需要维护 cluster taxonomy。 |

## 指标

| 指标 | 含义 |
|---|---|
| `avg_recall` | 每条 query 的 expected skills 平均召回。 |
| `avg_precision` | 选中的 Skill 中有多少是 expected。 |
| `safety_full_recall` | safety critical query 是否完整召回关键 Skills。 |
| `avg_selected` | 平均加载 Skill 数。 |
| `avg_overselect` | 平均多选 Skill 数。 |
| `avg_context_chars` | 注入 LLM 的 Skill body 字符成本。S2 额外计入 Skill Index；代码 resolver 不计入 index。 |
| `token_proxy` | 粗略 token 估算，按 `chars / 4`。 |
| `p95_latency_ms` | 本地 resolver p95 耗时，不含 LLM。 |

## 实验结果

```text
catalog_size=24
fixture_count=24
index_chars=2038
```

| strategy | avg_recall | avg_precision | safety_full_recall | avg_selected | avg_overselect | avg_context_chars | token_proxy | p95_latency_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S1_full_injection | 1.000 | 0.090 | 1.000 | 24.00 | 21.83 | 30200 | 7550 | 0.001 |
| S2_index_top3_proxy | 0.701 | 0.875 | 0.364 | 1.79 | 0.33 | 4361 | 1090 | 0.157 |
| S3_keyword_rules | 0.674 | 0.792 | 0.455 | 1.79 | 0.42 | 2312 | 578 | 0.027 |
| S4_tfidf_retrieval | 0.701 | 0.875 | 0.364 | 1.79 | 0.33 | 2323 | 581 | 0.143 |
| S5_hard_plus_retrieval | 0.951 | 0.861 | 0.909 | 2.50 | 0.46 | 3335 | 834 | 0.166 |
| S6_cluster_hybrid | 0.951 | 0.861 | 0.909 | 2.46 | 0.42 | 3267 | 817 | 0.081 |

## 关键观察

### 1. 全量注入不可取

S1 的召回是 100%，但平均注入约 7550 token proxy。24 个 Skill 还只是第一版 catalog，如果未来每个 Skill 加 references，成本会继续上升。

全量注入的问题不是速度本身，而是：

- LLM 要读大量无关方法论。
- 工具选择噪音增加。
- 面试叙事会退化成“把所有 prompt 都塞进去”。
- 无法体现 progressive disclosure。

### 2. 单纯 LLM Index / 检索 top3 不够安全

S2 和 S4 的平均召回为 0.701，但 safety full recall 只有 0.364。典型漏例：

```text
孕妇发烧能吃对乙酰氨基酚吗？
```

单纯相似度容易选中：

```text
pregnancy_pediatric_safety
```

但漏掉：

```text
medication_safety
symptom_triage
```

这说明医疗问题经常是组合场景，不是单标签分类。

### 3. 纯关键词规则也不够

S3 很快，但 avg_recall 只有 0.674。关键词规则能命中显式词，却难以处理：

- 慢病 + 营养
- 报告 + 症状
- 特殊人群 + 用药
- 设备读数 + 急性风险

规则可以用于硬安全补齐，但不应承担全部 Skill selection。

### 4. 硬安全规则 + 检索是最有效组合

S5 / S6 的 `avg_recall` 都达到 0.951，`safety_full_recall` 达到 0.909，同时平均只加载约 2.5 个 Skill。

这说明可行路线不是：

```text
全交给 LLM 选
```

也不是：

```text
全交给规则匹配
```

而是：

```text
少量高精度安全组合规则 + 轻量 Skill 检索
```

### 5. S6 比 S5 更适合作为 20+ Skills 的扩展方案

S5 和 S6 指标几乎相同，但 S6 有两个优势：

- `avg_context_chars` 更低：3267 vs 3335。
- `p95_latency_ms` 更低：0.081ms vs 0.166ms。

差异在当前 24 个 Skill 下不大，但当 Skills 扩展到 50+ 时，先匹配 cluster 再簇内检索更容易保持稳定。

## 推荐方案

推荐采用：

```text
S6 Cluster Hybrid:
  hard safety implication rules
  + skill cluster gating
  + local retrieval top-k
  + cap 2-4 loaded skills
```

当前已将该方案落地为 `core.skill_resolver.SkillResolver`，并在 `GeneratorAgent` 默认配置中启用：

```text
GeneratorAgent:
  skill_selection_strategy = cluster_hybrid
  skill_resolver_max_skills = 4
  tool_visibility_control_enabled = true

AgentLoop:
  SkillResolver runs before Maker LLM
  code selects 2-4 candidate Skills
  Maker receives selected SKILL.md
  Maker still decides tools in ReAct-like loop
```

旧 LLM SkillSelectionPass 仍保留为回退策略：当 `skill_selection_strategy` 未设置为 `cluster_hybrid` / `hybrid_resolver` / `resolver` 时，AgentLoop 继续使用原来的 LLM 选择流程。

## 仍需补充的真实测试

这次实验已满足“当前环境真实运行”，但还不是生产级 eval。上线前还需要：

1. 真实 LLM A/B：比较当前 SkillSelectionPass 与 S6 resolver 在 50-100 条问句上的 tool-call precision。
2. Checker 通过率：观察 S6 是否降低 PreStopPolicy REPAIR 和 Checker REJECT。
3. 延迟 p50/p90：确认去掉 SkillSelection LLM 后是否稳定减少 1-3 秒。
4. 医疗人工 review：至少抽样检查 safety critical 问题是否仍然安全。
5. Tool visibility eval：确认 loaded skills 限制可见工具后，不会漏掉必要工具。

## 实验脚本处理

本次实验使用临时脚本：

```text
_tmp_progressive_skill_experiment.py
```

脚本只用于生成本报告数据，不属于生产代码。运行完成后应删除。
