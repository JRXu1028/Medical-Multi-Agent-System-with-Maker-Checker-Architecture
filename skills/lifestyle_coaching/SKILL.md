---
id: lifestyle_coaching
description: 用户询问饮食、运动、睡眠、咖啡、饮酒、熬夜等日常生活方式建议时加载。
when_to_load:
  - 用户询问饮食、运动、睡眠、熬夜、咖啡、饮酒、压力管理
  - 用户希望获得长期可执行的健康计划
  - 用户问题是低风险日常健康建议，但可能受慢病背景影响
suggested_tools:
  - recommend_lifestyle
  - medical_kb_search
---

# Lifestyle Coaching

## Method

- 先确认目标：预防、减重、控制指标、改善睡眠、恢复体能或慢病管理。
- 建议要具体、温和、可执行，避免突然高强度改变。
- 有慢病或用药背景时，强调不要替代处方和随访。
- 对急性症状或高风险读数，先转症状分诊或就医边界。

## Tool Notes

- 个性化生活方式建议可考虑 `recommend_lifestyle`。
- 需要基础证据时使用 `medical_kb_search`。

## Red Lines

- 不用生活方式建议替代急症就医。
- 不承诺快速治愈慢病。
- 不建议用户自行停药来实践生活方式。
