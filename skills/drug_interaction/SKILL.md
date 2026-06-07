---
id: drug_interaction
description: 用户询问多种药物能否同服、相互作用、重复成分、禁忌或高风险药物组合时加载。
when_to_load:
  - 用户询问两种或多种药物能不能一起吃、同服间隔或相互作用
  - 用户问题包含华法林、抗凝药、NSAIDs、胰岛素、抗癫痫药等高风险组合
  - 用户担心重复成分、过敏、禁忌或副作用叠加
suggested_tools:
  - drug_safety_lookup
  - medical_kb_search
  - guideline_search
---

# Drug Interaction

## Method

- 先列出所有药物、剂量、频次、服用时间和用途。
- 检查相互作用、重复成分、同类药叠加、出血风险、低血糖风险和过敏风险。
- 如果药物名不清楚，要求用户核对通用名、商品名和成分。
- 对高风险组合给出保守边界，并建议联系医生或药师。

## Tool Notes

- 多药同服问题优先考虑 `drug_safety_lookup`。
- 涉及疾病治疗选择时考虑 `guideline_search`。

## Red Lines

- 不在无法确认药物成分时给出“可以同服”的确定结论。
- 不建议用户自行调整抗凝、降糖、抗癫痫、免疫抑制等药物。
- 不忽略非处方药、中成药、保健品和酒精。
