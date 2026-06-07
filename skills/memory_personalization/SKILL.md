---
id: memory_personalization
description: 用户提到既往病史、上次对话、个人偏好、过敏史或需要结合授权记忆时加载。
when_to_load:
  - 用户说我之前、上次、你记得、我的病史、我的过敏史、长期情况
  - 当前问题需要结合用户授权保存的慢病背景、用药史、偏好或禁忌
  - 用户希望获得更个性化但仍有医学证据边界的建议
suggested_tools:
  - memory_context_lookup
  - medical_kb_search
  - drug_safety_lookup
---

# Memory Personalization

## Method

- 先区分用户记忆和医学证据：记忆只提供上下文，不支撑医学 claim。
- 使用记忆时明确它来自用户既往授权记录或当前会话，而不是指南或研究。
- 个性化建议必须仍然依赖医学工具、指南或知识库证据。
- 如果用户记忆涉及过敏、妊娠、慢病或用药，应提高安全保守性。

## Tool Notes

- 需要用户上下文时考虑 `memory_context_lookup`。
- 记忆提示用药风险时，必须结合 `drug_safety_lookup` 或其他医学证据工具。
- 记忆提示疾病背景时，可结合 `medical_kb_search` / `guideline_search`。

## Red Lines

- 不把 memory 当作医学证据。
- 不暴露或推断用户没有授权保存的敏感信息。
- 不因为用户历史偏好而弱化医疗安全边界。
