---
id: lab_report
description: 用户提供化验单、检查报告、异常指标、参考范围或复查问题时加载。
when_to_load:
  - 用户询问尿酸、白细胞、肌酐、血糖、血脂、肝功能、甲状腺等指标是否异常
  - 用户提供检查报告并询问严重程度、原因、复查或下一步
  - 用户问题包含指标数值、单位、参考范围或报告截图文字
suggested_tools:
  - lab_reference_lookup
  - medical_kb_search
  - guideline_search
  - assess_risk
---

# Lab Report Interpretation

## Method

- 先识别报告类型、指标名称、数值、单位、参考范围和采样背景。
- 结合年龄、性别、症状、基础病、用药、近期感染或饮食运动背景解释。
- 强调单个指标不能直接诊断，重点说明趋势、复查、就医边界和可能影响因素。
- 如果报告异常伴随急性症状，先做风险评估，再解释指标。

## Tool Notes

- 指标解释优先考虑 `lab_reference_lookup`。
- 需要疾病或指南依据时考虑 `medical_kb_search` / `guideline_search`。
- 报告异常伴随红旗症状时考虑 `assess_risk`。

## Red Lines

- 不根据单个指标直接诊断疾病。
- 不忽略单位、参考范围和检测条件。
- 不把检查报告解释成治疗处方。
