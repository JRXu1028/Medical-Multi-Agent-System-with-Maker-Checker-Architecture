---
id: renal_liver_dose_safety
description: 用户存在肾功能、肝功能异常，或询问特殊剂量、抗生素、止痛药等用药风险时加载。
when_to_load:
  - 用户提到肌酐、eGFR、肾功能不全、透析、肝功能异常、肝硬化
  - 用户询问某药剂量是否需要调整、能否使用或是否伤肝伤肾
  - 用户是老人、多病共存或合并多种处方药
suggested_tools:
  - drug_safety_lookup
  - lab_reference_lookup
  - medical_kb_search
  - guideline_search
---

# Renal And Liver Dose Safety

## Method

- 先确认肝肾指标、基础疾病、年龄、体重、药物名称、剂量和用药目的。
- 不根据单个“肌酐高”直接计算或调整处方剂量。
- 对肝肾功能异常、透析、肝硬化、老人多药共用场景保持保守。
- 给出“需要医生/药师核对”的边界，而不是替代处方。

## Tool Notes

- 用药风险优先考虑 `drug_safety_lookup`。
- 指标背景考虑 `lab_reference_lookup`。
- 需要指南或疾病背景时考虑 `guideline_search` / `medical_kb_search`。

## Red Lines

- 不给处方药精确剂量调整。
- 不忽略肝肾功能、体重和合并用药。
- 不把“常规剂量”默认套用到肝肾功能异常者。
