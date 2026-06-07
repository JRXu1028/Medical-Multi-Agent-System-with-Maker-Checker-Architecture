---
id: care_navigation
description: 用户询问挂什么科、急诊还是门诊、何时复诊、是否需要线下就医时加载。
when_to_load:
  - 用户询问挂什么科、去哪个科、是否需要急诊或门诊
  - 用户询问复查、随访、转诊或线下评估路径
  - 用户症状不一定需要诊断，但需要就医路径建议
suggested_tools:
  - assess_risk
  - medical_kb_search
  - guideline_search
---

# Care Navigation

## Method

- 先区分急诊、尽快门诊、常规门诊和居家观察边界。
- 给科室建议时说明依据和不确定性，例如内科、急诊、呼吸科、心内科、消化科等。
- 如果多个科室都可能相关，优先给安全路径而不是唯一答案。
- 对已明确红旗的情况，优先急诊/急救，不纠结具体科室。

## Tool Notes

- 高风险就医路径优先考虑 `assess_risk`。
- 需要疾病或指南路径依据时考虑 `medical_kb_search` / `guideline_search`。

## Red Lines

- 不把急症问题建议为普通预约门诊。
- 不承诺某一科室一定能解决全部问题。
- 不让用户因为线上建议延误线下评估。
