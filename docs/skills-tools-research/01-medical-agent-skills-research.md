# 医学 Agent / Skills 调研报告

本文是对 Medical Maker-Checker Agent 的 Skills / Tools 扩展调研。目标不是把项目改成固定医疗工作流，而是学习 2024-2026 年医疗 Agent、医疗 RAG、Clinical Copilot、Tool-using Medical LLM 和安全 Guardrail 项目如何组织能力边界，并反推本项目应如何设计可渐进披露的 Skills 和可审计 Tools。

## 调研结论

最重要的结论有五个：

1. 医疗 Agent 的核心能力不是“回答医学常识”，而是连续决策、澄清信息、选择工具、合成证据、识别风险和审查输出。
2. Skills 不应该等于 Tools。Skills 更适合表达方法论、checklist、red lines 和何时调用哪些工具；Tools 负责执行检索、计算、查药、查指标、查指南等确定动作。
3. 医疗安全不能依赖 Skill 是否被 Maker 选择。安全约束应保留在 Checker / PreStopPolicy / SafetyGate 这类独立规则或审查层中。
4. RAG 必须从“搜索到文本”升级为“证据基础设施”，至少要保留来源、年份、片段、证据类型、分数和 citation。
5. Memory 只能用于个性化上下文，不能作为医学证据。医学 claim 必须来自 RAG、指南、药物库、指标库或其他可追溯来源。

## 外部项目与论文

| 项目 / 论文 | 关注点 | 对本项目的启发 |
|---|---|---|
| [AgentClinic](https://agentclinic.github.io/) / [arXiv:2405.07960](https://arxiv.org/abs/2405.07960) | 模拟临床对话、工具使用、多模态数据、反思、持久 notebook。 | 静态 QA 会高估医疗能力，Agent 需要在不完整信息下逐步询问、检索、使用工具并记录过程。 |
| [MedAgentBench](https://stanfordmlgroup.github.io/projects/medagentbench/) / [GitHub](https://github.com/stanfordmlgroup/MedAgentBench) | FHIR EHR 环境、300 个医生编写任务、读写 EHR 工具。 | 医疗 Agent 的评估要看 tool action success，不只看答案文本；Tool schema 和动作边界很重要。 |
| [MDAgents](https://www.media.mit.edu/projects/mdagents-adaptive-collaboration-strategy-for-llms-in-medical-decision-making/overview/) / [GitHub](https://github.com/mitmedialab/MDAgents) | 根据复杂度选择 solo / 多学科团队 / 综合团队。 | Router 保留 simple / maker_checker 是合理的；复杂度影响监督强度，但不应让 Router 细分所有 Skills。 |
| [MedAgents](https://arxiv.org/abs/2311.10537) | 多学科专家角色、协作讨论、总结、共识决策。 | Checker 不应重复回答，而应做 adversarial audit；Maker 内部不必拆成太多专家，除非复杂度真的需要。 |
| [TxAgent](https://zitniklab.hms.harvard.edu/TxAgent/) / [ToolUniverse](https://github.com/mims-harvard/ToolUniverse) | 211 个生物医学工具、实时知识检索、药物相互作用、禁忌、个体化治疗、ToolRAG。 | 工具数量变大后必须做 tool retrieval / tool visibility control；用药安全值得独立成专用 Tool。 |
| [MedRAG Toolkit](https://github.com/Teddy-XiongGZ/MedRAG) | 医学 RAG toolkit，模块化 corpora / retrievers / LLMs，MIRAGE benchmark。 | RAG 设计应拆成语料、检索器、重排和生成，而不是一个 search 函数返回 answer。 |
| [MedRAG KG](https://github.com/SNOWTEAM2023/MedRAG) / [arXiv:2502.04413](https://arxiv.org/abs/2502.04413) | 知识图谱增强 RAG、诊断差异点、follow-up question generation。 | 诊断/症状场景要能主动追问；GraphRAG 可以作为未来方向，但第一版不要做空洞 KG。 |
| [Self-MedRAG](https://arxiv.org/abs/2601.04531) | hybrid retrieval、RRF、self-reflection、证据不足时重写 query。 | 本项目 v3.6 的 hybrid retrieval + RRF 路线合理；未来可增加 evidence sufficiency loop。 |
| [BioChatter](https://biochatter.org/) / [BioCypher](https://biocypher.org/) | 生物医学 KG、schema-informed retrieval、上下文感知 query generation。 | Skill loading 可借鉴“只把相关 schema/上下文给 LLM”，减少 token 并提升工具调用准确性。 |
| [AMIE](https://research.google/pubs/towards-conversational-diagnostic-ai/) / [Nature](https://www.nature.com/articles/s41586-025-08866-7) | 诊断对话、history taking、self-play、评价 rubric、患者与医生双视角。 | 症状类 Skill 应优先强调问诊信息、红旗、澄清问题和不确定性，而不是直接诊断。 |
| [CareGuardAI](https://arxiv.org/abs/2604.26959) | 临床安全风险 SRA、幻觉风险 HRA、迭代修正、阈值放行。 | Checker two-stage 设计是正确方向：先确定性预检，再 LLM 语义审计；安全风险和事实风险要分开看。 |
| [MMedAgent](https://arxiv.org/abs/2407.02483) | 多模态医疗工具选择，六个工具、七类任务、五种模态。 | 影像、心电、报告等未来应扩展为专用工具；但当前文本项目只先做 imaging/report 方法论。 |
| [MedAgent-Pro](https://arxiv.org/abs/2503.18968) | 多模态证据化诊断，任务层诊断计划 + case 层工具 agent。 | 对复杂诊断，不应让一个答案直接生成结论；要先建立证据化计划和工具结果。 |
| [DeepRare](https://www.nature.com/articles/s41586-025-10097-9) | 罕见病多 Agent，40+ 专用工具，memory bank，traceable evidence。 | Memory + 工具服务器 + 可追踪证据是医疗 Agent 的长期方向，但本项目不应直接扩成罕见病平台。 |
| [TheraAgent](https://arxiv.org/abs/2603.13676) | 自进化记忆、证据校准、PET theranostics 多专家。 | Memory 最有价值的用法是 case-based reasoning，但必须和证据校准绑定，不能裸用历史偏好。 |

## 工程文档参考

| 来源 | 关键点 | 本项目如何吸收 |
|---|---|---|
| [Claude Code Skills](https://docs.anthropic.com/en/docs/claude-code/skills) | Skill body 只有在使用时加载，frontmatter/description 负责触发，支持 supporting files 和 allowed tools。 | 保留 Markdown SKILL.md；Skill 写方法论，不写硬约束；未来可加 references 做二级披露。 |
| [Anthropic Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) | Workflow 是代码预定义路径，Agent 是 LLM 动态控制工具；复杂性会换来延迟和成本。 | 本项目保持 Maker 自主 tool loop，但用 Checker/Policy 限制医疗不变量。 |
| [Claude Code Hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) | PreToolUse / PostToolUse / Stop 等生命周期 hook 可拦截或补充上下文。 | 本项目不引入完整 hooks 系统；PreStopPolicy 已覆盖“结束前过程预检”的核心价值。 |
| [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | Agent loop 负责工具调用、结果回传、guardrails、session、trace。 | 当前 AgentLoop 自研是合理的，重点是保持 trace、tool schema、guardrail 可审计。 |

## 对 Skills / Tools 的设计约束

### Skill 应该是什么

Skill 是给 Maker 或 Checker 的方法论：

- 什么时候加载
- 先检查什么
- 需要哪些信息
- 常见误区是什么
- 红线是什么
- 可以考虑哪些工具

Skill 不应该：

- 直接执行外部 API
- 伪装成硬安全约束
- 把医学知识库内容写死在 Markdown 里
- 和其他 Skill 大量重叠

### Tool 应该是什么

Tool 是可执行函数/API：

- 输入结构化参数
- 返回 `ToolResult`
- 医学证据返回 `EvidenceRecord`
- 失败时返回 `success=false`，不抛给 LLM
- 有清晰 category、timeout、cost_level

### RAG 应该是什么

RAG 是证据基础设施：

- 检索本地知识库、指南、药物、指标等来源
- 返回结构化 evidence
- 用 hybrid retrieval / rerank 提高召回
- 让 Maker 引用 evidence，让 Checker 审查 evidence

RAG 不应该：

- 直接替 Maker 写最终答案
- 让 memory 进入 evidence
- 输出无法验证的 coverage/conflict 字段

### Memory 应该是什么

Memory 是用户上下文：

- 用户授权后保存
- 按 user_id 隔离
- 可用于个性化建议
- 不能作为医学 claim 的证据

## 对当前项目的直接影响

当前 7 个 SKILL.md 是合理的起点，但粒度偏粗：

- `symptom_triage` 应拆出 `emergency_red_flags`、`mental_health_safety`、`care_navigation` 等高风险或流程型能力。
- `medication_safety` 应拆出 `drug_interaction`、`renal_liver_dose_safety`、`pregnancy_pediatric_safety`。
- `lab_report` 应拆出 `imaging_report`、`ecg_vital_signs`。
- `health_education` 应拆出 `preventive_care`、`medical_device_explainer`。
- `lifestyle_chronic_care` 应拆成 `chronic_care`、`lifestyle_coaching`、`nutrition_weight_management`、`rehabilitation_exercise_safety`。
- `evidence_research` 应拆成 `guideline_research`、`evidence_comparison`、`source_quality_appraisal`。

但这不意味着要立刻创建 24 个真实 SKILL.md。推荐先把 catalog 和 mapping 作为 proposal 固化，再通过 progressive loading eval 决定 MVP 先落哪些。
