# Skills Catalog

本文设计 Medical Maker-Checker Agent 的下一版 Skill Catalog。它是 proposal，不直接替换当前 `skills/` 目录。目标是从“7 个粗粒度方法论文档”扩展成“20-30 个互不重复、能映射到工具和安全约束的能力单元”。

## 设计原则

1. Skill 是方法论文档，不是函数工具。
2. Skill 粒度以“问题处理方法不同”为边界，而不是以疾病名堆数量。
3. Skill 可以建议工具，但不承载 required tool 的硬约束；硬约束仍由 Checker 内部的 PreStopPolicy 负责。
4. Skill body 必须短，适合 progressive disclosure；复杂细节放到未来 `references/`。
5. 当前能力不足的 Skill 可以保留为未来规划，但必须标注需要的新 Tool。

## 推荐的 24 个 Skills

| id | 能力边界 | 典型触发 | 当前状态 |
|---|---|---|---|
| `symptom_triage` | 身体不适、症状严重程度、是否就医的分层处理。 | 胸痛、腹痛、头痛、发热、咳嗽、呕吐、头晕、严重吗、要不要就医。 | 现有 Skill 重写/保留。 |
| `emergency_red_flags` | 急症红旗识别和急诊/急救边界。 | 呼吸困难、昏厥、意识模糊、单侧无力、严重出血、视力突然丧失。 | 新增，MVP 高优先级。 |
| `mental_health_safety` | 自杀、自残、伤害他人的心理危机安全回应。 | 不想活、自杀、自残、轻生、伤害自己、伤害别人。 | 新增，MVP 高优先级。 |
| `clarifying_questions` | 信息不足时提出关键追问，不强行诊断。 | 多久、伴随症状、年龄、病史、孕期、信息不完整。 | 新增，MVP 中优先级。 |
| `care_navigation` | 就诊科室、急诊/门诊/复诊路径建议。 | 挂什么科、去哪个科、要不要急诊、复诊、线下就医。 | 新增，MVP 中优先级。 |
| `medication_safety` | 用药安全、漏服、停药、剂量、副作用边界。 | 漏服、停药、补服、剂量、副作用、过敏、服药。 | 现有 Skill 重写/保留。 |
| `drug_interaction` | 多药同服、相互作用、重复成分和禁忌。 | 一起吃、同服、相互作用、华法林、布洛芬、抗凝、重复成分。 | 新增，MVP 高优先级。 |
| `renal_liver_dose_safety` | 肝肾功能异常、老年人和特殊剂量风险。 | 肌酐、eGFR、肾功能、肝功能、剂量调整、抗生素。 | 新增，需要新 Tool 更好支撑。 |
| `pregnancy_pediatric_safety` | 孕期、哺乳期、儿童用药和症状安全边界。 | 孕妇、怀孕、哺乳、儿童、宝宝、小孩、婴儿。 | 新增，MVP 高优先级。 |
| `geriatric_safety` | 老年人多病共存、跌倒、用药和就医风险。 | 老人、跌倒、骨折、多病、认知问题、独居。 | 新增，MVP 中优先级。 |
| `lab_report` | 化验单、异常指标、参考范围和复查建议。 | 尿酸、白细胞、血糖、血脂、肌酐、ALT、AST、指标异常。 | 现有 Skill 重写/保留。 |
| `imaging_report` | CT、MRI、超声、X 线、影像报告文字解读。 | CT、MRI、核磁、超声、X 光、结节、影像报告。 | 新增，需要新 Tool 更好支撑。 |
| `ecg_vital_signs` | 心电图、血压、血氧、心率等生命体征解释。 | 心电图、房颤、血压 180、血氧 92、心率、ST 段。 | 新增，需要新 Tool 更好支撑。 |
| `guideline_research` | 临床指南、共识、诊疗规范和推荐等级。 | 指南、共识、最新推荐、诊疗规范、治疗方案。 | 由现有 `evidence_research` 拆出。 |
| `evidence_comparison` | 比较检查、药物、治疗方案的证据利弊。 | A 和 B 区别、哪个好、利弊、方案比较、证据更强。 | 由现有 `evidence_research` 拆出。 |
| `source_quality_appraisal` | 评估来源质量、年份、新鲜度和证据强度。 | 来源、年份、RCT、系统综述、meta、研究质量、证据强度。 | 新增，依赖 RAG metadata。 |
| `health_education` | 医学概念、检查原理、常识性健康科普。 | 是什么、为什么、区别、原理、科普、常识。 | 现有 Skill 重写/保留。 |
| `preventive_care` | 筛查、疫苗、体检、风险预防和健康维护。 | 体检、筛查、预防、疫苗、HPV、流感疫苗、癌筛。 | 新增，需要新 Tool 更好支撑。 |
| `medical_device_explainer` | 家用医疗设备、可穿戴设备和检查设备解释。 | 血糖仪、血压计、血氧仪、呼吸机、可穿戴、监测设备。 | 新增，MVP 低优先级。 |
| `chronic_care` | 高血压、糖尿病、高尿酸、高血脂等慢病长期管理。 | 高血压、糖尿病、高尿酸、痛风、高血脂、长期管理。 | 由现有 `lifestyle_chronic_care` 拆出。 |
| `lifestyle_coaching` | 饮食、运动、睡眠、咖啡、饮酒等生活方式建议。 | 饮食、运动、睡眠、熬夜、咖啡、喝酒、生活方式。 | 由现有 `lifestyle_chronic_care` 拆出。 |
| `nutrition_weight_management` | 营养、减脂、控糖、控盐和体重管理。 | 减肥、减脂、体重、热量、蛋白质、控糖、控盐。 | 新增，MVP 中优先级。 |
| `rehabilitation_exercise_safety` | 康复训练、运动禁忌、疼痛后恢复边界。 | 康复、拉伸、训练、腰痛、膝盖痛、运动损伤、恢复。 | 新增，MVP 低优先级。 |
| `memory_personalization` | 使用用户授权记忆做个性化，但不当医学证据。 | 我之前、上次、记得、我的病史、偏好、过敏史。 | 新增，依赖现有 memory 工具。 |

## 当前 7 个 Skills 的重构关系

| 当前 Skill | 建议重构为 |
|---|---|
| `symptom_triage` | `symptom_triage` + `emergency_red_flags` + `clarifying_questions` + `care_navigation` |
| `medication_safety` | `medication_safety` + `drug_interaction` + `renal_liver_dose_safety` + `pregnancy_pediatric_safety` |
| `lab_report` | `lab_report` + `imaging_report` + `ecg_vital_signs` |
| `health_education` | `health_education` + `preventive_care` + `medical_device_explainer` |
| `lifestyle_chronic_care` | `chronic_care` + `lifestyle_coaching` + `nutrition_weight_management` + `rehabilitation_exercise_safety` |
| `evidence_research` | `guideline_research` + `evidence_comparison` + `source_quality_appraisal` |
| `checker_adversarial` | 保留为 Checker 内部方法论；不参与 Maker 的普通 Skill selection。 |

## 推荐落地优先级

### 第一批: 已落 24 个 Maker-facing Skills

当前已完成全部 24 个 Maker-facing SKILL.md：

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

当前已落地状态：

```text
skills/
├── symptom_triage
├── emergency_red_flags
├── clarifying_questions
├── care_navigation
├── mental_health_safety
├── medication_safety
├── drug_interaction
├── renal_liver_dose_safety
├── pregnancy_pediatric_safety
├── geriatric_safety
├── lab_report
├── imaging_report
├── ecg_vital_signs
├── guideline_research
├── evidence_comparison
├── source_quality_appraisal
├── health_education
├── preventive_care
├── medical_device_explainer
├── chronic_care
├── lifestyle_coaching
├── nutrition_weight_management
├── rehabilitation_exercise_safety
├── memory_personalization
└── checker_adversarial
```

其中 `checker_adversarial` 是 Checker 的固定审查方法论，不参与普通 Maker 问答的能力扩展叙事。旧的 `evidence_research` 已拆成 `guideline_research`、`evidence_comparison`、`source_quality_appraisal`；旧的 `lifestyle_chronic_care` 已拆成 `chronic_care`、`lifestyle_coaching`、`nutrition_weight_management`、`rehabilitation_exercise_safety`。这样 Maker 在 SkillSelection/SkillResolver 中看到的是更清晰的能力边界。

### 仍需后续强化的 Skills

以下 Skills 已有 SKILL.md，但还可以随着专用工具和 RAG 语料继续增强：

```text
renal_liver_dose_safety
pregnancy_pediatric_safety
preventive_care
source_quality_appraisal
rehabilitation_exercise_safety
```

## 每个 SKILL.md 的建议结构

```markdown
---
id: symptom_triage
description: 用户描述身体不适、症状严重程度、是否需要就医或急诊时加载。
when_to_load:
  - 用户描述胸痛、呼吸困难、腹痛、发热、头晕、呕吐等症状
  - 用户询问症状是否严重、是否需要就医
suggested_tools:
  - assess_risk
  - medical_kb_search
  - guideline_search
---

# Symptom Triage

## Method

- 先识别红旗症状，再讨论常见原因。
- 信息不足时追问关键字段，但明显高危时不要等待完整信息。
- 不做确定诊断，只做风险分层、就医建议和需要补充的信息。

## Tool Notes

- 高风险症状优先考虑 `assess_risk`。
- 需要疾病或指南依据时考虑 `medical_kb_search` / `guideline_search`。

## Red Lines

- 不把胸痛、呼吸困难、昏厥、意识障碍说成“先观察即可”。
- 不用生活方式建议替代急性风险评估。
```

## 不推荐创建的 Skills

暂不推荐按疾病名创建大量 Skill，例如：

```text
hypertension_skill
diabetes_skill
asthma_skill
gastritis_skill
headache_skill
```

原因：

- 疾病名 Skill 容易堆数量，边界重叠。
- 同一个疾病可能涉及症状分诊、慢病管理、用药安全、指南研究多个处理方法。
- 当前项目的差异化是 Agent runtime，而不是疾病百科库。

更好的方式是：疾病相关知识放进 RAG / guideline / drug / lab tools，Skill 只写处理方法。
