import os

from dotenv import load_dotenv


load_dotenv()


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _llm_profile(
    prefix: str,
    *,
    default_model: str,
    default_temperature: float,
    default_max_tokens: int,
    default_disable_thinking: bool = False,
) -> dict:
    """构建某个角色的 LLM 配置。

    角色专属环境变量优先；未配置时回退到通用 LLM_*。
    例如 ROUTER_LLM_MODEL_NAME 未配置时，不影响 Generator/Reviewer。
    """

    api_key = os.getenv(f"{prefix}_API_KEY") or os.getenv("LLM_API_KEY", "")
    base_url = os.getenv(f"{prefix}_BASE_URL") or os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    model_name = os.getenv(f"{prefix}_MODEL_NAME", default_model)
    temperature = _env_float(f"{prefix}_TEMPERATURE", default_temperature)
    max_tokens = _env_int(f"{prefix}_MAX_TOKENS", default_max_tokens)
    disable_thinking = _env_bool(f"{prefix}_DISABLE_THINKING", default_disable_thinking)

    config = {
        "api_key": api_key,
        "model_name": model_name,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "disable_thinking": disable_thinking,
    }
    if disable_thinking:
        config["extra_body"] = {"thinking": {"type": "disabled"}}
    return config


# LLM API config (OpenAI-compatible endpoint)
LLM_CONFIG = {
    "api_key": os.getenv("LLM_API_KEY", ""),
    "model_name": os.getenv("LLM_MODEL_NAME", "deepseek-v4-pro"),
    "base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "8192")),
    "disable_thinking": _env_bool("LLM_DISABLE_THINKING", False),
}

LLM_PROFILES = {
    "default": LLM_CONFIG,
    "router": _llm_profile(
        "ROUTER_LLM",
        default_model=os.getenv("ROUTER_LLM_MODEL_NAME", "deepseek-v4-flash"),
        default_temperature=0.0,
        default_max_tokens=512,
        default_disable_thinking=True,
    ),
    "generator": _llm_profile(
        "GENERATOR_LLM",
        default_model=os.getenv("LLM_MODEL_NAME", "deepseek-v4-pro"),
        default_temperature=0.7,
        default_max_tokens=8192,
    ),
    "reviewer": _llm_profile(
        "REVIEWER_LLM",
        default_model=os.getenv("LLM_MODEL_NAME", "deepseek-v4-pro"),
        default_temperature=0.3,
        default_max_tokens=8192,
    ),
    "lead": _llm_profile(
        "LEAD_LLM",
        default_model=os.getenv("LLM_MODEL_NAME", "deepseek-v4-pro"),
        default_temperature=0.7,
        default_max_tokens=4096,
    ),
}


def get_llm_config(profile: str = "default") -> dict:
    """按角色获取 LLM 配置，避免业务代码直接依赖环境变量。"""

    if profile not in LLM_PROFILES:
        return LLM_PROFILES["default"]
    return LLM_PROFILES[profile]

# Mem0 API config (Long-term memory)
MEM0_CONFIG = {
    "api_key": os.getenv("MEM0_API_KEY", ""),
}
