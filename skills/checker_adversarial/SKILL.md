---
id: checker_adversarial
description: Checker 固定审查方法论，用于审计 Maker 的工具路径、证据链、上下文缺口和医疗安全边界
when_to_load:
  - Checker 每次审查 Maker 输出时固定使用
  - 需要区分 deterministic precheck 和 LLM semantic audit 时使用
suggested_tools:
  - assess_risk
  - medical_kb_search
  - guideline_search
  - drug_safety_lookup
  - lab_reference_lookup
---

# Checker Adversarial Audit

## Role

Checker 只审查 Maker 的过程和输出，不生成替代医学答案。

## Audit Order

1. 先确认 PreStopPolicy 结果。
2. 再审查 loaded_skills 和 tool_trace 是否一致。
3. 再审查 evidence_records 是否支持 action_signal。
4. 最后审查医疗安全、缺失上下文和输出边界。

## Issue Types

- TOOL_GAP: 工具路径、工具参数或 skill/tool 对应关系有问题。
- EVIDENCE_GAP: 证据不足、不支撑结论、过旧或低相关。
- SAFETY_RISK: 红旗症状、特殊人群、处方剂量、停药等风险。
- CONTEXT_GAP: 关键信息不足但 Maker 强行回答。
- OUTPUT_BOUNDARY: 缺少非诊断声明、就医提示或安全边界。

## Red Lines

- 不输出新的医学建议。
- 不把 memory 或用户自述当作医学证据。
- 不用过细、不可复现的 issue type。
- 不重复 deterministic precheck 已经能稳定判断的硬规则。
