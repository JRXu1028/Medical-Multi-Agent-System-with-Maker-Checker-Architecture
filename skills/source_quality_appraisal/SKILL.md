---
id: source_quality_appraisal
description: 用户关心证据来源、年份、研究质量、指南等级或回答需要判断证据强弱时加载。
when_to_load:
  - 用户询问证据强不强、来源是否可靠、年份是否过时
  - 回答需要比较指南、系统综述、RCT、观察研究、专家共识
  - RAG 返回多条来源且需要解释证据可信度
suggested_tools:
  - guideline_search
  - medical_kb_search
---

# Source Quality Appraisal

## Method

- 优先区分指南/共识、系统综述、随机试验、观察研究、病例报告和普通科普。
- 关注来源机构、年份、适用人群、研究类型和是否与用户问题直接相关。
- 如果 evidence metadata 不足，应明确“不足以判断证据强度”。
- 不要伪造 coverage、conflict 或证据等级。

## Tool Notes

- 需要证据来源时使用 `guideline_search` / `medical_kb_search`。
- 只使用工具返回中真实存在的 source、year、citation、evidence_type 等字段。

## Red Lines

- 不编造证据等级或指南年份。
- 不把过时或低相关证据说成强证据。
- 不把 memory 或用户自述当作医学来源。
