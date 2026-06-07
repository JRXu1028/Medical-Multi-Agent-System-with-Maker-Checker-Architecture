# Medical Maker-Checker Agent

**Medical Maker-Checker — 双 Agent 对抗式医疗安全决策系统** | 2026.05–2026.06

- **设计非对称 Maker-Checker 架构**：Maker 生成候选回答，Checker 从空白上下文以证伪立场独立审查，两者不共享推理历史。Checker / PreStop 判定 REJECT 时带具体修复指令退回 Maker 返修（≤2次），超限则触发 forced_safe 

- **构建 PreStopPolicy + SafetyGate 双层确定性防线**：PreStopPolicy 在 LLM 审查前零 token 检查过程完整性，SafetyGate 在审查后检查输出安全性，两层均以代码规则执行、不依赖模型自觉

- **设计 25 个渐进式方法论文档（SKILL.md）**：将医疗能力建模为 Markdown 文档，包含触发条件、处理流程和安全红线。通过安全补齐规则 + 簇门控 + 轻量检索在 LLM 调用前自动选出 2–4 个注入上下文，不额外消耗 LLM 调用

- **构建混合检索 + 证据规范化的 RAG 管线**：Milvus 向量检索与关键词检索融合（RRF），经重排后规范化为 EvidenceRecord（source / year / snippet / score / evidence_type / citation），每条证据可溯源、可被 Checker 审计年份和相关性

- **隔离 Memory 上下文与医学证据来源**：Mem0 长期记忆仅提供用户背景（过敏史、慢病史），标注为 memory_context；医学依据必须出自 Milvus RAG、guideline_search 等可信检索工具。Checker 审计 Maker 是否把用户自述当作临床证据引用，防止"你之前说过不过敏所以安全"的推理捷径
