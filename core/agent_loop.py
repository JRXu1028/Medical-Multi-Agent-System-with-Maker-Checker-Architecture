"""
Agent循环引擎
实现 LLM 驱动的 tool 调用循环
支持 v3.2 Progressive SKILL.md 加载
支持短期记忆集成
支持约束验证（Harness Engineering）
"""
import uuid
import json
from typing import Dict, Any, List, Optional
from loguru import logger

from .state_manager import StateManager, TaskStatus
from .llm_client import LLMResponse
from .skill_index import SkillDocLoader

# Harness Engineering: 约束验证和自动修复（可选模块）
CONSTRAINTS_ENABLED = False
ConstraintValidator = None  # type: ignore
AutoFixer = None  # type: ignore


class AgentLoop:
    """
    Agent循环引擎
    LLM 自主决策 tool 调用，循环直到任务完成

    功能：
    - 在正式 ReAct tool loop 前执行 SkillSelectionPass（可选）
    - 把选中的 SKILL.md 作为 system context 注入，不作为 tool call
    - 支持短期记忆（ShortTermMemory）
    - 自动记录每轮的 user/assistant 消息
    """

    def __init__(self, max_iterations: int = 10, short_term_memory: Optional[Any] = None, max_tool_calls: int = 2):
        """
        初始化Agent循环引擎

        Args:
            max_iterations: 最大迭代次数（防止无限循环）
            short_term_memory: 短期记忆管理器（可选）
            max_tool_calls: 最大 tool 调用次数（硬性限制，默认2次）
        """
        self.max_iterations = max_iterations
        self.max_tool_calls = max_tool_calls
        self.state_manager = StateManager()
        self.short_term_memory = short_term_memory
        self.tool_call_count = 0

        # Harness Engineering: 约束验证器和自动修复器
        self.validator = ConstraintValidator() if CONSTRAINTS_ENABLED else None
        self.auto_fixer = AutoFixer() if CONSTRAINTS_ENABLED else None
        if CONSTRAINTS_ENABLED:
            logger.debug("✅ Constraint validation enabled")

    async def run(self, agent, input_data: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        执行Agent循环

        Args:
            agent: Agent实例
            input_data: 输入数据

        Returns:
            最终结果
        """
        task_id = str(uuid.uuid4())
        state = self.state_manager.create_state(
            task_id=task_id,
            agent_id=agent.agent_id,
            input_data=input_data,
            max_iterations=self.max_iterations
        )

        # 重置计数
        self.tool_call_count = 0

        logger.info(f"Starting Agent Loop for {agent.agent_id}, task_id={task_id}")

        try:
            state.status = TaskStatus.IN_PROGRESS

            # 初始化消息历史（包含历史对话）
            messages = self._initialize_messages(agent, input_data, session_id)
            loaded_skills: List[str] = []
            skill_selection: Dict[str, Any] = {
                "enabled": False,
                "requested_skills": [],
                "loaded_skills": [],
            }

            # 记录用户消息到短期记忆
            if self.short_term_memory and session_id:
                user_message = messages[-1]["content"] if messages else str(input_data)
                self.short_term_memory.add_message(
                    session_id=session_id,
                    role="user",
                    content=user_message
                )
                logger.debug(f"Recorded user message to short-term memory (session={session_id})")

            # v3.2 Progressive Skill Loading:
            # 这是 AgentLoop 内部的上下文加载步骤，不是 function tool call。
            # 因此它不进入 tool_results，不计入 max_tool_calls，也不生成 evidence。
            if agent.config.get("progressive_skills_enabled", False):
                skill_selection = await self._run_skill_selection_pass(
                    agent=agent,
                    messages=messages,
                )
                loaded_skills = skill_selection.get("loaded_skills", [])
                skill_context = skill_selection.get("skill_context", "")
                if skill_context:
                    self._inject_skill_context(messages, skill_context)
                state.add_intermediate_result({
                    "phase": "skill_selection",
                    "requested_skills": skill_selection.get("requested_skills", []),
                    "loaded_skills": loaded_skills,
                    "error": skill_selection.get("error"),
                })

            # 获取 Agent 的 Skills (OpenAI format)
            tools_openai_format = agent.get_tools_for_llm()

            logger.debug(f"Agent has {len(tools_openai_format) if tools_openai_format else 0} skills available")

            # 收集所有 tool call 结果，传递给 post_process_result。
            # v3 中 Skill 和 Tool 是两个层级——Skill 是 SKILL.md 方法论文档
            # （由 SkillSelectionPass 加载），Tool 是可执行函数（此处收集其返回值）。
            tool_results: list = []
            tool_trace: list = []

            # 主循环：LLM → Skill Calls → Results → LLM
            while state.should_continue():
                state.iteration += 1
                logger.debug(f"=== Iteration {state.iteration}/{state.max_iterations} ===")

                try:
                    # 调用 LLM（可能返回 tool_calls）
                    llm_response: LLMResponse = await agent.llm_client.chat_with_tools(
                        messages=messages,
                        tools=tools_openai_format,
                        tool_choice="auto",
                        temperature=agent.config.get('temperature', 0.7)
                    )

                    # 记录中间结果
                    state.add_intermediate_result({
                        'iteration': state.iteration,
                        'llm_response': {
                            'content': llm_response.content,
                            'reasoning_content': llm_response.reasoning_content,
                            'tool_calls': [
                                {'name': tc.name, 'arguments': tc.arguments}
                                for tc in llm_response.tool_calls
                            ],
                            'finish_reason': llm_response.finish_reason
                        }
                    })

                    # 情况1: LLM 返回 tool_calls，执行 tools
                    if llm_response.has_tool_calls():
                        # 硬性限制：检查是否已达到最大调用次数
                        if self.tool_call_count >= self.max_tool_calls:
                            logger.warning(f"⚠️ 已达到最大 tool 调用次数限制 ({self.max_tool_calls})，强制生成最终答案")
                            # 强制要求 LLM 提供最终答案
                            messages.append({
                                'role': 'user',
                                'content': f'已完成 {self.max_tool_calls} 次信息检索。请基于已获取的信息提供最终答复。'
                            })
                            continue

                        logger.info(f"LLM requested {len(llm_response.tool_calls)} tool calls (当前已调用 {self.tool_call_count}/{self.max_tool_calls})")

                        # 添加 assistant 消息（包含 tool_calls）
                        messages.append(self._create_assistant_message_with_tools(llm_response))

                        # 记录 assistant 消息到短期记忆
                        if self.short_term_memory and session_id:
                            tool_names = [tc.name for tc in llm_response.tool_calls]
                            self.short_term_memory.add_message(
                                session_id=session_id,
                                role="assistant",
                                content=f"调用工具：{', '.join(tool_names)}"
                            )

                        # 执行每个 tool 调用
                        for tool_call in llm_response.tool_calls:
                            # 增加计数
                            self.tool_call_count += 1
                            logger.debug(f"Executing: {tool_call.name}({tool_call.arguments}) - 第 {self.tool_call_count} 次调用")

                            # Harness Engineering: 验证调用
                            if self.validator:
                                validation_result = self.validator.validate_tool_call(
                                    agent.agent_id,
                                    tool_call.name
                                )
                                if not validation_result.get("valid"):
                                    logger.warning(
                                        f"⚠️ 约束警告: {validation_result.get('reason')}"
                                    )

                            tool_result = await agent.execute_tool(
                                tool_name=tool_call.name,
                                arguments=tool_call.arguments
                            )

                            # 收集结构化 tool call 结果，供 post_process_result 使用
                            tool_results.append({
                                "name": tool_call.name,            # tool 函数名 (如 "medical_kb_search")
                                "arguments": tool_call.arguments,  # 调用参数
                                "result": tool_result,             # 完整返回值 (含 evidence 等结构化字段)
                            })
                            tool_trace.append({
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                                "success": not (
                                    isinstance(tool_result, dict)
                                    and tool_result.get("success") is False
                                ),
                            })

                            # 添加结果消息
                            messages.append(
                                agent.llm_client.create_tool_message(
                                    tool_call_id=tool_call.id,
                                    tool_name=tool_call.name,
                                    result=tool_result
                                )
                            )

                            # 记录结果到短期记忆
                            if self.short_term_memory and session_id:
                                result_summary = str(tool_result)[:200]
                                self.short_term_memory.add_message(
                                    session_id=session_id,
                                    role="tool",
                                    content=f"{tool_call.name}: {result_summary}"
                                )

                        # 继续下一轮循环
                        continue

                    # 情况2: LLM 返回文本响应，任务完成
                    else:
                        logger.info(f"LLM provided final response (no tool calls)")

                        # Harness Engineering: 验证和修复输出
                        final_answer = llm_response.content

                        if self.validator and final_answer:
                            validation_result = self.validator.validate_output(
                                agent.agent_id,
                                final_answer
                            )

                            if not validation_result.get("valid"):
                                logger.warning(
                                    f"⚠️ 输出约束违规: {validation_result.get('violations')}"
                                )

                                # 自动修复
                                if self.auto_fixer and validation_result.get("auto_fixable"):
                                    fixed_answer = self.auto_fixer.fix_output(
                                        final_answer,
                                        validation_result.get("auto_fixable", [])
                                    )
                                    if fixed_answer != final_answer:
                                        logger.info("🔧 输出已自动修复")
                                        final_answer = fixed_answer

                        # 记录最终回答到短期记忆
                        if self.short_term_memory and session_id:
                            self.short_term_memory.add_message(
                                session_id=session_id,
                                role="assistant",
                                content=final_answer or "(empty response)"
                            )
                            logger.debug(f"Recorded final answer to short-term memory (session={session_id})")

                        result = {
                            'answer': final_answer,
                            'iterations': state.iteration,
                            'agent_id': agent.agent_id,
                            'loaded_skills': loaded_skills,
                            'tool_trace': tool_trace,
                            'skill_selection': skill_selection,
                        }

                        # 让 Agent 进行结果后处理（基于结构化 tool 返回值生成 action_signal）
                        # 传入 tool_results 使 Agent 可直接读取 tool 的结构化字段
                        # 而非从自然语言中做 NLP 关键词解析
                        if hasattr(agent, 'post_process_result'):
                            result = await agent.post_process_result(
                                result, final_answer, tool_results=tool_results
                            )

                        state.mark_completed(result)
                        break

                except Exception as e:
                    logger.error(f"Error in iteration {state.iteration}: {e}")
                    if state.iteration >= state.max_iterations:
                        state.mark_failed(str(e))
                        break
                    # 否则继续尝试

            # 如果没有成功完成（包括失败状态），生成兜底回答，保证上层总能拿到 answer
            if state.status != TaskStatus.COMPLETED:
                logger.warning(f"Max iterations reached without completion")

                # 强制调用 LLM 生成最终总结
                try:
                    logger.info("Forcing LLM to provide final answer")

                    # 添加强制总结的提示
                    messages.append({
                        'role': 'user',
                        'content': '请基于以上信息，提供最终的答复。'
                    })

                    # 调用 LLM（禁用 function calling）
                    final_response = await agent.llm_client.chat_with_tools(
                        messages=messages,
                        tools=None,
                        temperature=0.7
                    )

                    result = {
                        'answer': final_response.content or '抱歉，未能完成任务',
                        'iterations': state.iteration,
                        'warning': 'max_iterations_reached',
                        'loaded_skills': loaded_skills,
                        'tool_trace': tool_trace,
                        'skill_selection': skill_selection,
                    }

                    # 记录最终回答到短期记忆
                    if self.short_term_memory and session_id:
                        self.short_term_memory.add_message(
                            session_id=session_id,
                            role="assistant",
                            content=result['answer']
                        )

                    state.mark_completed(result)
                    logger.info("Generated fallback answer after max iterations")

                except Exception as e:
                    logger.error(f"Failed to generate fallback answer: {e}")
                    # 降级到简单提取
                    result = {
                        'answer': '抱歉，系统在处理您的问题时遇到了问题。建议您简化问题或稍后重试。',
                        'iterations': state.iteration,
                        'warning': 'max_iterations_reached',
                        'error': str(e),
                        'loaded_skills': loaded_skills,
                        'tool_trace': tool_trace,
                        'skill_selection': skill_selection,
                    }
                    state.mark_completed(result)

            logger.info(f"Agent Loop finished: status={state.status.value}, iterations={state.iteration}")
            return state.final_result or {}

        except Exception as e:
            logger.error(f"Agent Loop failed: {e}")
            state.mark_failed(str(e))
            raise

    def _initialize_messages(self, agent, input_data: Dict[str, Any], session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """初始化消息列表，包含历史对话上下文"""
        messages = []

        # 系统提示词
        system_prompt = agent.get_system_prompt()
        if system_prompt:
            messages.append({
                'role': 'system',
                'content': system_prompt
            })

        # 加载历史对话（短期记忆）
        if self.short_term_memory and session_id:
            history = self.short_term_memory.get_history(session_id, limit=5)  # 最近5轮对话
            if history:
                logger.info(f"Loaded {len(history)} historical messages from short-term memory")
                messages.extend(history)

        # 用户输入
        user_message = agent.format_user_input(input_data)
        messages.append({
            'role': 'user',
            'content': user_message
        })

        return messages

    async def _run_skill_selection_pass(
        self,
        agent,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """运行 v3.2 SkillSelectionPass。

        Maker 第一轮只读取 Skill Index，并一次性声明希望加载的 SKILL.md。
        这个过程不暴露为普通 tool，因此不会污染 tool_trace，也不会计入工具调用次数。
        """
        loader = SkillDocLoader(agent.config.get("skill_docs_dir", "skills"))
        skill_docs = loader.discover()
        if not skill_docs:
            return {
                "enabled": True,
                "requested_skills": [],
                "loaded_skills": [],
                "skill_context": "",
                "raw_response": "",
            }

        selection_prompt = self._build_skill_selection_prompt(loader.render_index())
        selection_messages = messages + [
            {
                "role": "user",
                "content": selection_prompt,
            }
        ]

        try:
            raw_response = await agent.llm_client.chat(
                selection_messages,
                temperature=0.0,
                max_tokens=800,
            )
        except Exception as exc:
            logger.warning("SkillSelectionPass failed; continue without SKILL.md: {}", exc)
            return {
                "enabled": True,
                "requested_skills": [],
                "loaded_skills": [],
                "skill_context": "",
                "raw_response": "",
                "error": str(exc),
            }

        requested_skills = self._parse_requested_skills(raw_response)
        skill_context, loaded_skills = loader.render_skill_context(requested_skills)

        logger.debug(
            "SkillSelectionPass loaded skills: requested={}, loaded={}",
            requested_skills,
            loaded_skills,
        )
        return {
            "enabled": True,
            "requested_skills": requested_skills,
            "loaded_skills": loaded_skills,
            "skill_context": skill_context,
            "raw_response": raw_response,
        }

    @staticmethod
    def _build_skill_selection_prompt(skill_index: str) -> str:
        """构造 SkillSelectionPass 提示词。"""
        return f"""你现在只需要选择本轮需要加载的 SKILL.md 方法论文档，不要回答用户问题，也不要调用工具。

Skill Index:
{skill_index}

请只输出 JSON，格式如下：
{{
  "requested_skills": ["skill_id_1", "skill_id_2"],
  "reason": "一句话说明为什么加载这些 skill"
}}

如果不需要加载任何 Skill，请输出：
{{"requested_skills": [], "reason": "无需加载"}}
"""

    @staticmethod
    def _parse_requested_skills(raw_response: str) -> List[str]:
        """从 SkillSelectionPass 输出中解析 requested_skills。

        LLM 有时会包一层 Markdown code fence，所以这里做保守 JSON 提取。
        """
        if not raw_response:
            return []

        text = raw_response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return []
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return []

        if isinstance(payload, list):
            requested = payload
        elif isinstance(payload, dict):
            requested = payload.get("requested_skills", [])
        else:
            requested = []

        if not isinstance(requested, list):
            return []
        return [str(item).strip() for item in requested if str(item).strip()]

    @staticmethod
    def _inject_skill_context(
        messages: List[Dict[str, Any]],
        skill_context: str,
    ) -> None:
        """把已加载 SKILL.md 注入到 system context 中。

        插入到首个 system message 后面，保证它在用户消息之前生效。
        当前约定 messages[0] 是 Agent 主系统提示词，SKILL.md 紧跟其后注入。
        """
        insert_at = 1 if messages and messages[0].get("role") == "system" else 0
        messages.insert(
            insert_at,
            {
                "role": "system",
                "content": skill_context,
            },
        )

    def _create_assistant_message_with_tools(self, llm_response: LLMResponse) -> Dict[str, Any]:
        """创建包含 tool_calls 的 assistant 消息"""
        message = {
            'role': 'assistant',
            'content': llm_response.content or None
        }

        if llm_response.reasoning_content:
            message['reasoning_content'] = llm_response.reasoning_content

        # 添加 tool_calls（OpenAI 格式）
        if llm_response.tool_calls:
            message['tool_calls'] = [
                {
                    'id': tc.id,
                    'type': 'function',
                    'function': {
                        'name': tc.name,
                        'arguments': json.dumps(tc.arguments, ensure_ascii=False)
                    }
                }
                for tc in llm_response.tool_calls
            ]

        return message
