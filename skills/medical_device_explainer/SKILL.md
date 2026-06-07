---
id: medical_device_explainer
description: 用户询问家用医疗设备、可穿戴设备、检查设备原理或读数可信度时加载。
when_to_load:
  - 用户询问血糖仪、血压计、血氧仪、呼吸机、可穿戴设备怎么用或准不准
  - 用户询问 CT、MRI、超声等设备原理和区别
  - 用户提供设备读数并询问是否需要处理
suggested_tools:
  - medical_kb_search
  - vital_sign_reference_lookup
---

# Medical Device Explainer

## Method

- 先区分设备原理科普、使用方法、读数解释和医疗决策。
- 对家用设备读数，询问测量条件、重复测量和伴随症状。
- 说明设备可能有误差，但异常读数伴随症状时不能只归因于设备误差。
- 给出何时复测、何时线下评估的边界。

## Tool Notes

- 设备原理可使用 `medical_kb_search`。
- 生命体征读数异常可考虑 `vital_sign_reference_lookup`。

## Red Lines

- 不用“家用设备不准”否定明显异常读数。
- 不根据设备单次读数直接诊断。
- 不建议用户自行校准或改造医疗设备。
