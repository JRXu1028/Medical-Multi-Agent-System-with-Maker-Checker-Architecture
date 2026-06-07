---
id: imaging_report
description: 用户提供 CT、MRI、超声、X 光、影像报告文字或结节描述时加载。
when_to_load:
  - 用户询问 CT、MRI、核磁、超声、B 超、X 光报告是什么意思
  - 报告包含结节、占位、阴影、囊肿、增厚、积液、退变等影像术语
  - 用户询问是否严重、是否需要复查或进一步检查
suggested_tools:
  - imaging_reference_lookup
  - medical_kb_search
  - guideline_search
---

# Imaging Report

## Method

- 先识别检查类型、部位、关键描述、大小、数量、位置、随访建议和既往对比。
- 区分影像术语解释、风险分层和诊断结论；影像报告不能单独替代临床诊断。
- 如果报告提到急症可能或用户伴随红旗症状，应优先就医边界。
- 对结节/囊肿/退变等常见词，解释“可能含义 + 需结合背景 + 复查边界”。

## Tool Notes

- 影像术语优先考虑 `imaging_reference_lookup`。
- 需要疾病背景或指南随访时考虑 `medical_kb_search` / `guideline_search`。

## Red Lines

- 不根据影像文字直接判断良恶性。
- 不忽略大小、部位、既往对比和随访建议。
- 不把“影像发现”说成“最终诊断”。
