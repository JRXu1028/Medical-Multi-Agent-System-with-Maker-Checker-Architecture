"""
LLM客户端
支持调用 OpenAI 兼容的 API（如字节跳动豆包、OpenAI、Deepseek 等）
支持 function calling
"""
import sys
import asyncio
import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


def _clean_surrogates(obj: Any) -> Any:
    """递归清理对象中所有字符串的 surrogate 字符(\\ud800-\\udfff)。"""
    if isinstance(obj, str):
        return re.sub(r'[\ud800-\udfff]', '?', obj)
    if isinstance(obj, dict):
        return {k: _clean_surrogates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_surrogates(v) for v in obj]
    return obj
from openai import AsyncOpenAI
from loguru import logger

from config import get_llm_config


@dataclass
class ToolCall:
    """Function call 数据结构"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """LLM 响应数据结构（支持 function calling）"""
    content: Optional[str]
    tool_calls: List[ToolCall]
    finish_reason: str  # "stop", "tool_calls", "length", "content_filter"
    reasoning_content: Optional[str] = None

    def has_tool_calls(self) -> bool:
        """是否包含 function calls"""
        return len(self.tool_calls) > 0


class LLMClient:
    """统一的LLM客户端，支持多种模型"""

    def __init__(
        self,
        model_type: str = "openai_compatible",
        profile: str = "default",
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化LLM客户端

        Args:
            model_type: 模型类型，默认 "openai_compatible"（支持 OpenAI 兼容的 API）
            profile: LLM 角色配置，如 router / skill_selector / generator / generator_repair / reviewer
            config: 显式配置，传入时优先于 profile
        """
        self.model_type = model_type
        self.profile = profile

        if model_type == "openai_compatible":
            # 使用 OpenAI 兼容的 API（通过 config.py 配置）
            self.config = config or get_llm_config(profile)
            self.client = AsyncOpenAI(
                api_key=self.config["api_key"],
                base_url=self.config["base_url"]
            )
            self.model_name = self.config["model_name"]
            self.temperature = self.config.get("temperature", 0.7)
            self.max_tokens = self.config.get("max_tokens", 8192)
            self.extra_body = self.config.get("extra_body")
        else:
            raise ValueError(f"Unknown model type: {model_type}")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        异步聊天接口

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            temperature: 温度参数（可选）
            max_tokens: 最大token数（可选）

        Returns:
            模型返回的文本
        """
        try:
            temperature = temperature or self.temperature
            max_tokens = max_tokens or self.max_tokens

            logger.debug(
                f"Calling LLM ({self.profile}:{self.model_name}) "
                f"with {len(messages)} messages"
            )

            request_params = {
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **kwargs,
            }
            if self.extra_body and "extra_body" not in request_params:
                request_params["extra_body"] = self.extra_body

            response = await self.client.chat.completions.create(**request_params)

            content = response.choices[0].message.content
            logger.debug(f"LLM response length: {len(content)} chars")
            return content

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    async def chat_with_retry(
        self,
        messages: List[Dict[str, str]],
        max_retries: int = 3,
        **kwargs
    ) -> str:
        """
        带重试的聊天接口

        Args:
            messages: 消息列表
            max_retries: 最大重试次数

        Returns:
            模型返回的文本
        """
        for attempt in range(max_retries):
            try:
                return await self.chat(messages, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Retry {attempt + 1}/{max_retries} after error: {e}")
                await asyncio.sleep(2 ** attempt)  # 指数退避

    def create_message(self, role: str, content: str) -> Dict[str, str]:
        """
        创建消息对象

        Args:
            role: 角色，"user" 或 "assistant" 或 "system"
            content: 消息内容

        Returns:
            消息字典
        """
        return {"role": role, "content": content}

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        带工具支持的聊天接口

        Args:
            messages: 消息列表
            tools: 工具定义列表（OpenAI format）
            tool_choice: 工具选择策略 ("auto"/"required"/"none")
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            LLMResponse 对象
        """
        try:
            temperature = temperature or self.temperature
            max_tokens = max_tokens or self.max_tokens

            logger.debug(
                f"Calling LLM ({self.profile}:{self.model_name}) "
                f"with {len(tools) if tools else 0} tools"
            )

            # 准备请求参数 — 清洗 messages 中的 surrogate 字符
            clean_messages = _clean_surrogates(messages)
            request_params = {
                "model": self.model_name,
                "messages": clean_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **kwargs
            }
            if self.extra_body and "extra_body" not in request_params:
                request_params["extra_body"] = self.extra_body

            # 添加工具参数（如果提供）
            if tools:
                request_params["tools"] = tools
                if tool_choice != "auto":
                    request_params["tool_choice"] = tool_choice

            response = await self.client.chat.completions.create(**request_params)

            # 解析响应
            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason
            reasoning_content = getattr(message, "reasoning_content", None)
            if reasoning_content is None and hasattr(message, "model_extra"):
                reasoning_content = message.model_extra.get("reasoning_content")

            # 提取工具调用
            tool_calls = []
            if hasattr(message, 'tool_calls') and message.tool_calls:
                for tc in message.tool_calls:
                    tool_calls.append(ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments)
                    ))
                logger.debug(f"LLM requested {len(tool_calls)} tool calls")

            return LLMResponse(
                content=message.content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                reasoning_content=reasoning_content
            )

        except Exception as e:
            logger.error(f"LLM call with tools failed: {e}")
            raise

    @staticmethod
    def _safe_json_dumps(obj: Any) -> str:
        """安全的 JSON 序列化，处理 surrogate / 不可编码字符。"""
        try:
            return json.dumps(obj, ensure_ascii=False)
        except (UnicodeEncodeError, UnicodeDecodeError):
            # 深度清洗：递归替换所有字符串中的 surrogate 字符
            cleaned = _clean_surrogates(obj)
            return json.dumps(cleaned, ensure_ascii=False)

    def create_tool_message(
        self,
        tool_call_id: str,
        tool_name: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        创建工具执行结果消息

        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            工具消息字典
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": self._safe_json_dumps(result)
        }
