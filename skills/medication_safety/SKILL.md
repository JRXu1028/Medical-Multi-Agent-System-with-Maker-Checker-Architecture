---
id: medication_safety
description: 用户询问药物能否服用、漏服、停药、剂量、副作用、过敏或特殊人群用药边界时加载。
when_to_load:
  - 用户询问漏服、补服、加量、减量、停药或换药
  - 用户询问副作用、过敏、禁忌、过量或长期服药风险
  - 用户问题包含降压药、降糖药、抗凝药、胰岛素、抗癫痫药等高风险药物
suggested_tools:
  - drug_safety_lookup
  - medical_kb_search
  - guideline_search
  - assess_risk
---

# Medication Safety

## Method

- 先确认药物名称、剂量、频次、服药目的、已服用时间和是否为处方药。
- 关注重复成分、禁忌、过敏史、肝肾功能、妊娠哺乳、儿童、老人和慢病背景。
- 对处方调整保持保守，不建议用户自行停药、加量、减量或替换。
- 信息不足时说明需要补充哪些信息，并建议联系医生或药师核对。

## Tool Notes

- 用药安全问题优先考虑 `drug_safety_lookup`。
- 涉及疾病治疗路径时考虑 `guideline_search`。
- 出现严重过敏、呼吸困难、意识异常、严重出血等症状时考虑 `assess_risk`。

## Red Lines

- 不给出处方药的精确调整方案。
- 不建议自行停用降压药、抗凝药、胰岛素、抗癫痫药等高风险药物。
- 不把“可能安全”说成“绝对安全”。
