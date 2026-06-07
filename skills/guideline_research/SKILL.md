---
id: guideline_research
description: 用户询问临床指南、共识、诊疗规范、推荐等级、最新证据或治疗路径时加载。
when_to_load:
  - 用户询问某疾病的指南、共识、诊疗规范或推荐治疗方案
  - 用户要求说明来源、机构、年份、证据等级或推荐强度
  - 用户问题涉及“最新证据”“循证依据”“指南怎么说”
suggested_tools:
  - guideline_search
  - medical_kb_search
  - deep_research
---

# Guideline Research

## Method

- 优先查找指南、共识、系统综述和权威机构资料。
- 合成答案时标注来源、年份、机构和证据类型。
- 区分“指南推荐”“专家共识”“研究发现”和“证据不足”。
- 如果本地证据不足，应降低置信度，不编造指南名称或年份。

## Tool Notes

- 指南类问题优先考虑 `guideline_search`。
- 背景知识或疾病概念可辅助使用 `medical_kb_search`。
- `deep_research` 只在用户明确要求最新、复杂比较或本地证据不足时使用。

## Red Lines

- 不编造指南名称、年份、机构或推荐等级。
- 不把单条低质量证据当成确定结论。
- 不在证据不足时给出强推荐。
