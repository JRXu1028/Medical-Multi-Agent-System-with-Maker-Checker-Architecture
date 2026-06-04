"""
Agent 抽象基类 — LLM 驱动的 tool 调用 + AgentLoop 执行引擎。
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from loguru import logger

from core import LLMClient, AgentLoop
from core.skill_registry import SkillRegistry


class BaseAgent(ABC):
    """
    Agent基类
    子类需要实现：
    - get_system_prompt(): 返回系统提示词
    - register_tools(): 注册 Agent 的工具
    - process(): 主入口（可选，默认使用 run_loop）
    """

    def __init__(
        self,
        agent_id: str,
        config: Dict[str, Any],
        llm_client: Optional[LLMClient] = None
    ):
        self.agent_id = agent_id
        self.config = config
        self.llm_client = llm_client or LLMClient(
            model_type=config.get('model', 'openai_compatible'),
            profile=config.get('llm_profile', agent_id),
        )
        self.loop = AgentLoop(
            max_iterations=config.get('max_iterations', 10),
            max_tool_calls=config.get('max_tool_calls', 2),
        )

        # Skill 注册表
        self.skill_registry = SkillRegistry()
        self.register_tools()

        # 协作相关（预留扩展）
        self.capabilities: List[str] = []  # 能力标签
        self.shared_context: Optional[Any] = None  # SharedContext 引用
        self.identity_manager: Optional[Any] = None  # AgentIdentityManager 引用

        logger.debug(
            f"Initialized {self.__class__.__name__} (id={agent_id}) "
            f"with {len(self.skill_registry.get_all())} skills"
        )

    @abstractmethod
    def get_system_prompt(self) -> str:
        """
        获取系统提示词
        子类必须实现
        """
        pass

    @abstractmethod
    def register_tools(self):
        """注册 Agent 的 Skills（子类必须实现）"""
        pass

    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """获取 OpenAI function calling 格式的列表"""
        return self.skill_registry.to_openai_format()

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Skill

        Args:
            tool_name: Skill 名称
            arguments: Skill 参数

        Returns:
            Skill 执行结果
        """
        return await self.skill_registry.execute(tool_name, **arguments)

    def format_user_input(self, input_data: Dict[str, Any]) -> str:
        """
        格式化用户输入
        子类可以重写

        Args:
            input_data: 输入数据

        Returns:
            格式化后的用户消息
        """
        # 默认实现
        if 'question' in input_data:
            return input_data['question']
        elif 'query' in input_data:
            return input_data['query']
        else:
            return str(input_data)

    async def post_process_result(
        self,
        result: Dict[str, Any],
        final_response: str,
        tool_results: Optional[List[Dict[str, Any]]] = None  # 本轮的 tool call 记录
    ) -> Dict[str, Any]:
        """
        结果后处理 —— 子类重写以从 tool 返回值中提取结构化信息。

        v3 架构中（Maker-Checker），此方法从 tool_results 中读取
        各 tool 的结构化字段（如 medical_kb_search 的 evidence records、
        assess_risk 的 risk_level），生成统一的
        ActionSignal，替代旧架构的 NLP 关键词解析。

        Args:
            result:         初始结果 dict（包含 answer / iterations / agent_id）。
            final_response: LLM 的最终自然语言响应文本。
            tool_results:   本轮 AgentLoop 中所有 tool call 的完整记录，
                            每项包含 {"name", "arguments", "result"}。
                            None 表示旧代码路径（向后兼容）。

        Returns:
            处理后的 result dict。子类通常在此追加 "action_signal" 键。
        """
        # 默认不做额外处理
        return result

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理输入数据
        默认实现：运行 Agent Loop
        子类可以重写以实现自定义逻辑
        """
        return await self.run_loop(input_data)

    async def run_loop(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """运行 Agent Loop"""
        # 提取session_id（如果有）
        session_id = input_data.get('session_id')
        return await self.loop.run(self, input_data, session_id=session_id)

    # ===== 协作能力（预留扩展）=====

    def set_capabilities(self, capabilities: List[str]):
        """设置 Agent 的能力标签"""
        self.capabilities = capabilities

    def get_capabilities(self) -> List[str]:
        """获取 Agent 的能力标签"""
        return self.capabilities

    def attach_shared_context(self, shared_context: Any):
        """附加 SharedContext（预留扩展）。"""
        self.shared_context = shared_context

    def attach_identity_manager(self, identity_manager: Any):
        """附加 AgentIdentityManager（预留扩展）。"""
        self.identity_manager = identity_manager

    async def process_subtask(self, subtask: Any) -> Dict[str, Any]:
        """
        处理子任务（预留扩展）。

        子类可以重写以实现自定义逻辑
        默认实现：运行 Agent Loop
        """
        # 使用 subtask.description 作为输入
        input_data = {
            'question': subtask.description,
            'subtask_id': subtask.id,
            'subtask_type': subtask.type
        }

        return await self.run_loop(input_data)
