# Medical Multi-Agent System with Maker-Checker Architecture

双 Agent 对抗式临床决策系统：

- **Generator** 调用 9 个医学 Skills 产出综合分析 + action_signal
- **Reviewer / Checker** 以证伪立场独立审查，先用 PreStopPolicy 做零 token 工具路径、证据路径和安全流程预检，再输出结构化 verdict (PASS/CHALLENGE/REJECT)
- **SafetyGate** 确定性代码硬防线 —— 高危症状检查不经过任何 LLM
- **ResponseRenderer** 确定性最终渲染 —— 通过审查直接返回 Maker 答案，安全覆盖使用固定模板
- **Router** 自动分流：简单且明确低危的问题走快速通道，高危/复杂/不确定问题走完整对抗管道

## 架构

```
User Query → Router
              ├── simple:       Generator → SafetyGate → ResponseRenderer
              └── maker_checker: Generator → Reviewer → SafetyGate → ResponseRenderer
                                       ↑__________________|
                                          REJECT → 修正 (≤2轮)
                                          CHALLENGE → 追加evidence
```

## 论文依据

| 论文 | 链接 | 核心发现 |
|------|------|---------|
| Multi-Agent Evaluation Loops | [arXiv 2601.13268](https://arxiv.org/abs/2601.13268) | Generator-Reviewer 对抗减少 89% 伦理违规 |
| adversarial-ai-review | [GitHub](https://github.com/gaurav-yadav/adversarial-ai-review) | 对抗审查误报率 7.3% vs 单次审查 30-60% |
| Consensus Trap | [arXiv 2604.17139](https://arxiv.org/abs/2604.17139) | 投票放大错误，对抗是解法 |
| UBC Skills Scaling Law | [arXiv 2601.04748](https://arxiv.org/abs/2601.04748) | SAS 效率优势 (token↓53.7%)，对抗网络不可替代 |
| CareGuardAI | [arXiv 2604.26959](https://arxiv.org/abs/2604.26959) | 双轴安全评估 SRA + HRA |
| OncoAgent | [HuggingFace](https://huggingface.co/blog/lablab-ai-amd-developer-hackathon/oncoagent-official-paper) | 确定性 Critic + bounded retry |

完整架构文档见 [docs/architecture-v2-adversarial-maker-checker.md](docs/architecture-v2-adversarial-maker-checker.md)。

## 项目结构

```
maker-checker/
├── main.py                     # 启动入口
├── config.py                   # LLM API 配置
├── agents/                     # "谁在思考" — Agent 定义
│   ├── base.py                 #   Agent 抽象基类
│   ├── generator.py            #   临床综合分析 (Maker)
│   ├── reviewer.py             #   对抗式安全审查 (Checker)
│   └── skill_registry_mixin.py #   Skill 自动注册
├── pipeline/                   # "流程怎么走" — 管道调度
│   ├── action_signal.py        #   结构化通信协议
│   ├── safety_gate.py          #   确定性安全门 (纯代码, 非 LLM)
│   ├── router.py               #   Hybrid Medical Router 分流
│   ├── orchestrator.py         #   Generator → Reviewer → Gate → Renderer
│   ├── response_renderer.py    #   确定性最终渲染 (非 LLM)
│   ├── terminal.py             #   四种终态标识
│   └── entry.py                #   对外入口 process()
├── core/                       # "系统怎么跑" — 底层运行时
│   ├── agent_loop.py           #   tool calling 循环
│   ├── llm_client.py           #   LLM 调用
│   ├── skill_loader.py         #   Skill 动态加载
│   ├── skill_registry.py       #   Skill 注册与 OpenAI tools 转换
│   └── state_manager.py        #   Agent 状态管理
├── knowledge/                  # 本地知识库 (Milvus RAG)
├── research/                   # 外部检索和证据综合
├── .claude/skills/             # 9 个医学 Skills (Anthropic 标准)
├── tests/                      # 单元测试 + Router eval fixtures
└── docs/                       # 架构文档
```

## 运行

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 然后在 .env 中填写 LLM_API_KEY / MEM0_API_KEY

# 推荐：Maker 第一轮默认 non-thinking，被 Checker REJECT 后再切 repair thinking。
GENERATOR_LLM_DISABLE_THINKING=true
GENERATOR_LLM_MAX_TOKENS=2048
GENERATOR_REPAIR_LLM_DISABLE_THINKING=false
GENERATOR_REPAIR_LLM_MAX_TOKENS=3000

# 交互模式 (Maker-Checker)
python main.py

# 详细日志
python main.py -v

# 运行测试
python -m pytest tests/ -v
```

`python main.py` 每次回答都会打印耗时拆解，用来定位慢点：

```
耗时拆解:
  total:              18.42s
  router:             0.84s
  agent_init:         0.10s
  orchestrator:       17.48s
    round 1:
      generator:      12.31s
      generator_loop_total: 12.30s
        skill_select: 0.92s
        llm_total:    8.40s
        tools_total:  2.60s
          tool medical_kb_search: 2.10s
      checker:        4.80s
        prestop:      0.00s
        llm_audit:    4.79s
    safety_gate:      0.00s
    renderer:         0.00s
```

重点看 `skill_select`、`llm_total`、单个 `tool xxx` 和 `checker.llm_audit`。如果出现 “Loading weights” 慢，通常会反映在首次 tool 调用或 RAG 检索工具耗时里。

## 典型案例

### 简单问题 → 快速通道

```
You: 多喝水有什么好处
[⚡ 快速通道] [路由: 低风险健康教育] [终态: simple] [耗时: 60s]
→ Generator 直接回答，跳过 Reviewer
```

### 高危症状 → 对抗审查

```
You: 我胸痛伴呼吸困难，需要就医吗？
[🔍 对抗审查] [路由: 安全红线: 急症症状:胸痛,急症症状:呼吸困难] [终态: normal] [耗时: 130s]
→ Generator 分析 + Reviewer 审查 + SafetyGate 检查
```

### 信息不足 → 保留不确定性

```
You: 头痛怎么办
[🔍 对抗审查] [路由: 个人医疗意图兜底] [终态: challenged] [耗时: 134s]
→ Reviewer 发现证据不足 → CHALLENGE → 回答中保留不确定性
```

### 多症状复杂 → 层层审查

```
You: 我肚子疼，呕吐，头晕，昨天晚上吃的外卖，晚上有点冷
[🔍 对抗审查] [路由: 个人医疗意图兜底 / LLM路由仲裁] [终态: challenged] [耗时: 145s]
→ Generator 调 3 个 Skills → Reviewer 发现 5 个 issues → 合并到证据
```

## 四种终态

| 终态 | 路径 | 用户感知 |
|------|------|---------|
| `normal` | Reviewer PASS → Gate PASS | 正常回答 |
| `challenged` | Reviewer CHALLENGE → 追加 evidence | "存在 Y 方面不确定性" |
| `gate_override` | Gate BLOCK → 硬覆盖 urgent_care | "目前无法可靠排除风险，建议及时就医" |
| `forced_safe` | R2 仍 REJECT → 强制兜底 | "目前无法可靠排除风险，建议立即就医" |
