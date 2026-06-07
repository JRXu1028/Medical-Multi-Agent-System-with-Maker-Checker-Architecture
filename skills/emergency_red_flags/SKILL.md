---
id: emergency_red_flags
description: 用户出现急症红旗信号、询问是否急诊或是否可以观察时加载。
when_to_load:
  - 用户描述呼吸困难、昏厥、意识模糊、单侧无力、严重出血、视力突然丧失
  - 用户询问胸痛、剧烈头痛、黑便、呕血、严重外伤是否需要急诊
  - 用户问题包含“要不要打 120”“能不能先观察”“是不是急症”
suggested_tools:
  - assess_risk
  - guideline_search
  - medical_kb_search
---

# Emergency Red Flags

## Method

- 先判断是否存在可能危及生命或需要急诊排查的红旗信号。
- 如果红旗明确，直接给出急诊/急救边界，不要先展开长篇科普。
- 对“不确定但可能高危”的情况，建议尽快线下评估，并说明需要观察的恶化信号。
- 不要求用户自行完成复杂鉴别诊断。

## Tool Notes

- 红旗症状优先考虑 `assess_risk`。
- 需要引用指南或急症处理原则时考虑 `guideline_search`。

## Red Lines

- 不把急症红旗淡化为普通不适。
- 不建议用户开车前往医院，如果存在晕厥、意识障碍、严重胸痛或呼吸困难。
- 不用“多喝水、休息”替代急诊边界。
