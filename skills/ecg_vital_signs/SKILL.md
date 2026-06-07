---
id: ecg_vital_signs
description: 用户询问心电图、血压、血氧、心率、体温等生命体征或读数异常时加载。
when_to_load:
  - 用户提供心电图文字、房颤、ST 段、早搏、心率异常等信息
  - 用户提供血压、血氧、心率、体温读数并询问是否危险
  - 用户家用设备读数异常并伴随胸痛、气短、头晕、昏厥等症状
suggested_tools:
  - vital_sign_reference_lookup
  - assess_risk
  - medical_kb_search
  - guideline_search
---

# ECG And Vital Signs

## Method

- 先确认读数、单位、测量设备、测量条件、重复测量结果和伴随症状。
- 生命体征异常要结合症状判断，不能只看单个数字。
- 血氧低、血压极高/极低、心率明显异常并伴随不适时要更保守。
- 对家用设备读数，说明可能误差，但不要用“设备可能不准”掩盖风险。

## Tool Notes

- 读数解释优先考虑 `vital_sign_reference_lookup`。
- 伴随胸痛、呼吸困难、昏厥、意识异常时考虑 `assess_risk`。

## Red Lines

- 不把血氧明显偏低或胸痛伴心电异常建议为普通观察。
- 不根据单次读数直接诊断疾病。
- 不忽略测量条件和重复测量。
