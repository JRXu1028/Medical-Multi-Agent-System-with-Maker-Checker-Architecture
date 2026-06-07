# Skill-Tool Mapping / Tool Registry

本文把推荐的 24 个 Skills 映射到当前项目的可执行 Tools，并标注哪些工具已经可复用、哪些应新增、哪些只适合未来规划。这里的“Tool Registry”是设计视图，不等于当前已经实现了独立 registry 文件；当前运行层仍通过 `SkillRegistryMixin` 把 structured tools 和 legacy `.claude/skills` 注册给 Maker。

## 当前可复用工具

### 现代 structured tools

| tool | 状态 | 说明 |
|---|---|---|
| `medical_kb_search` | existing structured | 本地医学知识库检索，返回 `ToolResult + EvidenceRecord`。 |
| `guideline_search` | existing structured | 临床指南类检索，返回机构、年份、来源、snippet 等证据字段。 |
| `drug_safety_lookup` | existing structured | 药物相互作用、禁忌、特殊人群、漏服/过量等用药安全检索。 |
| `lab_reference_lookup` | existing structured | 化验指标含义、参考范围、异常解释和复查建议。 |
| `memory_context_lookup` | existing structured | 用户授权长期记忆检索，只返回上下文，不返回医学证据。 |
| `risk_rule_check` | existing structured | 确定性红旗风险规则检查，返回 `risk_level`、`matched_rules` 和 `recommendation`。 |
| `imaging_reference_lookup` | existing structured | 影像报告术语、CT/MRI/超声/X 光、结节和随访边界检索。 |
| `vital_sign_reference_lookup` | existing structured | 血压、血氧、心率、体温、心电图文字和风险边界检索。 |

### Legacy executable skills

| tool | 状态 | 说明 |
|---|---|---|
| `assess_risk` | legacy existing | 高风险症状/心理危机等风险评估，目前仍是 PreStopPolicy 关键 required tool。 |
| `analyze_symptoms` | legacy existing | 症状分析辅助，适合过渡期复用。 |
| `search_knowledge` | legacy existing | 旧知识检索 wrapper，可逐步替换为 `medical_kb_search`。 |
| `clinical_guideline` | legacy existing | 旧指南查询 wrapper，可逐步替换为 `guideline_search`。 |
| `deep_research` | legacy existing, slow | 慢速深度研究工具，只应在明确需要最新证据/指南/复杂比较时暴露。 |
| `recommend_lifestyle` | legacy existing | 生活方式建议工具，可作为慢病生活方式过渡工具。 |
| `disease_code` | legacy existing | 疾病编码查询，当前不是核心问答路径。 |
| `search_history` / `search_similar_cases` | legacy existing | 旧 memory/case 查询入口，未来应收敛到 `memory_context_lookup`。 |

## 建议新增工具

| tool | 类型 | 优先级 | 说明 |
|---|---|---|---|
| `pregnancy_pediatric_safety_lookup` | structured | 中 | 孕期、哺乳期、儿童用药/症状安全证据。 |
| `renal_liver_dose_lookup` | structured | 中 | 肝肾功能异常下的剂量风险和用药注意事项。 |
| `vaccine_schedule_lookup` | structured | 中 | 疫苗接种年龄、禁忌、补种和筛查指南。 |
| `clinical_calculator` | structured | 中 | BMI、eGFR、ASCVD 等常用计算器；输出必须标注公式来源和适用范围。 |
| `care_navigation_lookup` | structured | 低 | 科室/急诊/门诊路径建议，可先由 Skill 方法论 + RAG 支撑。 |
| `mental_health_crisis_protocol` | structured | 中 | 心理危机响应协议、热线/急救边界；需按地区配置。 |
| `source_quality_rerank` | structured | 低 | 对 evidence records 做来源质量、新鲜度、证据类型优先级排序。 |
| `structured_web_research` | future | 低 | 受控外部 Web 检索，只允许权威机构/指南/数据库，不开放普通搜索。 |
| `fhir_ehr_lookup` | future | 低 | 真实 EHR / FHIR 环境工具，适合 MedAgentBench 类任务，不适合当前 demo 第一版。 |

## Skill 到 Tool 的映射

| Skill | 首选工具 | 可复用工具 | 需要新增 | 备注 |
|---|---|---|---|---|
| `symptom_triage` | `assess_risk` / `risk_rule_check` | `medical_kb_search`, `guideline_search`, `analyze_symptoms` | 无 | 高风险症状必须经过风险评估。 |
| `emergency_red_flags` | `assess_risk` / `risk_rule_check` | `guideline_search`, `medical_kb_search` | 无 | Skill 写红旗 checklist；硬约束仍在 PreStopPolicy。 |
| `mental_health_safety` | `assess_risk` | `medical_kb_search` | `mental_health_crisis_protocol` | 不建议只靠通用 RAG；需要地区化危机资源。 |
| `clarifying_questions` | 无必需工具 | `medical_kb_search` | 无 | 主要是方法论 Skill；帮助 Maker 在信息不足时问对问题。 |
| `care_navigation` | 无必需工具 | `medical_kb_search` | `care_navigation_lookup` | 短期用 Skill 指导，长期可查科室路径。 |
| `medication_safety` | `drug_safety_lookup` | `medical_kb_search`, `guideline_search` | 无 | 现有结构化工具已能支撑 MVP。 |
| `drug_interaction` | `drug_safety_lookup` | `medical_kb_search` | 无 | 与 `medication_safety` 区别：更强调多药同服和重复成分。 |
| `renal_liver_dose_safety` | `drug_safety_lookup` | `lab_reference_lookup`, `medical_kb_search` | `renal_liver_dose_lookup` | 现有工具可兜底，但专用剂量库更可靠。 |
| `pregnancy_pediatric_safety` | `drug_safety_lookup` | `medical_kb_search`, `guideline_search` | `pregnancy_pediatric_safety_lookup` | 特殊人群风险高，MVP 可复用药物工具，后续应专用化。 |
| `geriatric_safety` | `drug_safety_lookup` | `medical_kb_search`, `assess_risk` | 无 | 老年跌倒/多病共存多涉及症状分诊和用药安全组合。 |
| `lab_report` | `lab_reference_lookup` | `medical_kb_search`, `guideline_search` | `clinical_calculator` | 已有结构化工具支撑 MVP。 |
| `imaging_report` | `imaging_reference_lookup` | `medical_kb_search`, `guideline_search` | 无 | 已有影像专用结构化工具。 |
| `ecg_vital_signs` | `vital_sign_reference_lookup` | `assess_risk`, `medical_kb_search` | 无 | 血压/血氧/心电图异常可触发安全流程。 |
| `guideline_research` | `guideline_search` | `medical_kb_search`, `deep_research` | 无 | `deep_research` 只在明确最新/复杂证据时开放。 |
| `evidence_comparison` | `guideline_search` | `medical_kb_search`, `deep_research` | `source_quality_rerank` | 比较类问题需要证据质量排序。 |
| `source_quality_appraisal` | `guideline_search` | `medical_kb_search` | `source_quality_rerank` | 当前可用 evidence metadata 做轻量判断。 |
| `health_education` | `medical_kb_search` | 无 | 无 | 低风险科普通常只需轻量 RAG，避免误触发 deep_research。 |
| `preventive_care` | `guideline_search` | `medical_kb_search` | `vaccine_schedule_lookup` | 疫苗/筛查应尽量引用权威机构。 |
| `medical_device_explainer` | `medical_kb_search` | 无 | 无 | 家用设备解释多是科普；血氧低等结果应联动症状分诊。 |
| `chronic_care` | `guideline_search` | `medical_kb_search`, `recommend_lifestyle` | `clinical_calculator` | 慢病管理需要生活方式和指南证据。 |
| `lifestyle_coaching` | `recommend_lifestyle` | `medical_kb_search` | 无 | 不能替代用药或急症就医。 |
| `nutrition_weight_management` | `medical_kb_search` | `recommend_lifestyle` | `clinical_calculator` | 可用 BMI/热量等计算器增强。 |
| `rehabilitation_exercise_safety` | `medical_kb_search` | `assess_risk` | 无 | 运动损伤要先排除红旗，再给康复建议。 |
| `memory_personalization` | `memory_context_lookup` | `drug_safety_lookup`, `medical_kb_search` | 无 | Memory 只能影响个性化语气和上下文，不能进入 evidence。 |

## Tool Visibility Control

当前已实现 `core.tool_visibility.ToolVisibilityPolicy`。Maker 仍然自主选择工具，但 AgentLoop 会根据本轮 `loaded_skills` 过滤 OpenAI function schema，减少无关工具暴露、降低 LLM 选择成本，并减少误调 `deep_research` 等慢工具的概率。

建议规则：

```text
loaded_skills -> visible_tools
```

示例：

| Loaded Skills | Visible Tools |
|---|---|
| `health_education` | `medical_kb_search` |
| `symptom_triage`, `emergency_red_flags` | `assess_risk`, `medical_kb_search`, `guideline_search` |
| `medication_safety`, `drug_interaction` | `drug_safety_lookup`, `medical_kb_search`, `guideline_search` |
| `lab_report` | `lab_reference_lookup`, `medical_kb_search`, `guideline_search` |
| `guideline_research`, `evidence_comparison` | `guideline_search`, `medical_kb_search`, `deep_research` |
| `memory_personalization` | `memory_context_lookup` + 当前问题对应的医学工具 |

这不是 workflow。Maker 仍然自主选择工具；系统只是减少无关工具暴露。

## ToolResult 契约建议

所有新增工具都应返回：

```python
ToolResult(
    tool_name="drug_safety_lookup",
    success=True,
    data={...},
    evidence=[EvidenceRecord(...)]
)
```

强制约束：

- 医学来源放 `evidence`。
- 用户记忆放 `data.memory_context`，`evidence=[]`。
- 工具失败时返回 `success=False`，并保留 `error`。
- 不在工具里生成最终医学建议。

## 已完成的 Phase E 工具

本轮已完成 3 个工具：

```text
risk_rule_check
imaging_reference_lookup
vital_sign_reference_lookup
```

它们都通过 `ToolSpec` 注册给 Maker，并返回标准 `ToolResult`。其中 `risk_rule_check` 是确定性规则工具，`evidence=[]`；影像和生命体征工具走 `EvidenceService`，返回结构化 `EvidenceRecord`。

下一批更值得做：

```text
renal_liver_dose_lookup
pregnancy_pediatric_safety_lookup
vaccine_schedule_lookup
clinical_calculator
```
