"""
Hybrid Medical Router.

Router 只做分流，不做诊断：
1. Intent guard: 过滤科普、医保、写作、翻译、设备原理等非个人医疗决策问题。
2. Context rules: 结构化规则，关键词必须和医疗上下文一起命中。
3. Semantic recall: BGE embedding 召回同义高风险表达，只做高置信升级。
4. LLM fallback: 规则和语义层未能确定升级时，由 LLM 仲裁；不可用时 fail-closed。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import threading
from typing import Callable, Optional

import numpy as np

from .route_decision import RouteDecision


# ============================================================================
# Shared rule primitives
# ============================================================================

KeywordGroup = tuple[str, ...]


@dataclass(frozen=True)
class ContextRule:
    """可解释的路由规则。

    keywords: 触发词集合。
    contexts: 上下文条件。为空表示 keywords 命中即可触发。
    label: 输出到 RouteDecision.triggers 的人类可读标签。
    category: safety / evidence / progression。
    """

    label: str
    keywords: KeywordGroup
    contexts: KeywordGroup = ()
    category: str = "safety"

    def match(self, question: str) -> list[str]:
        matched_keywords = [kw for kw in self.keywords if kw in question]
        if not matched_keywords:
            return []
        if self.contexts and not any(ctx in question for ctx in self.contexts):
            return []
        return [f"{self.label}:{','.join(matched_keywords)}"]


@dataclass(frozen=True)
class MakerCheckerStage:
    """一类 maker_checker 信号，对应一个 RouteDecision reason 前缀。"""

    reason_prefix: str
    evaluator: Callable[[str], list[str]]

    def evaluate(self, question: str) -> RouteDecision | None:
        hits = self.evaluator(question)
        if not hits:
            return None
        return RouteDecision(
            mode="maker_checker",
            reason=f"{self.reason_prefix}: {', '.join(hits)}",
            triggers=hits,
            source="rule",
        )


def _has_any(question: str, keywords: KeywordGroup) -> bool:
    return any(kw in question for kw in keywords)


def _collect_matches(question: str, rules: tuple[ContextRule, ...]) -> list[str]:
    hits: list[str] = []
    for rule in rules:
        hits.extend(rule.match(question))
    return hits


# ============================================================================
# Intent guard: non-medical / non-personal decision queries
# ============================================================================

_NON_MEDICAL_INTENT_RULES = (
    ContextRule(
        label="非医疗决策:医保/报销",
        keywords=("医保", "报销", "挂号", "预约", "费用", "价格", "收费"),
        contexts=("怎么报销", "多少钱", "流程", "在哪里", "怎么预约"),
        category="intent",
    ),
    ContextRule(
        label="非医疗决策:设备/原理",
        keywords=("CT", "核磁", "B超", "心电图", "胃镜", "手术机器人"),
        contexts=("机器", "原理", "怎么工作", "发明", "历史", "设备"),
        category="intent",
    ),
    ContextRule(
        label="非医疗决策:写作/翻译/研究",
        keywords=("写作", "翻译", "论文", "社会学", "历史", "词义", "概念", "研究"),
        contexts=("疾病", "医院", "药物", "症状", "诊断", "自杀", "自残", "轻生"),
        category="intent",
    ),
    ContextRule(
        label="低风险健康教育",
        keywords=("多喝水", "喝水", "喝多少水", "饮水", "饮水量", "水果", "散步", "运动", "拉伸", "睡眠", "喝咖啡", "饮食", "作息"),
        contexts=("好处", "好吗", "多久", "多少", "一天", "每天", "建议", "能不能", "可以吗", "怎么做", "怎么改善", "吃什么"),
        category="intent",
    ),
    ContextRule(
        label="非医疗决策:物品问题",
        keywords=("手机", "手表", "衣服", "电脑", "耳机", "汽车"),
        contexts=("响", "抖", "斑点", "坏了", "怎么办", "怎么处理"),
        category="intent",
    ),
)

def _check_non_medical_intent(question: str) -> list[str]:
    """识别明显不是个人医疗决策的问题。

    若出现强个人就医/症状意图，则不短路，让后续 safety/evidence 规则接管。
    """

    if _has_any(question, ("我想自杀", "想自杀", "不想活了", "想死", "想轻生", "伤害自己")):
        return []
    return _collect_matches(question, _NON_MEDICAL_INTENT_RULES)


# ============================================================================
# Layer 1: context-aware safety / evidence / progression rules
# ============================================================================

_ACUTE_CONTEXT = (
    "突然", "现在", "刚刚", "持续", "越来越", "加重", "受不了",
    "伴", "同时", "还有", "出现", "发作", "不缓解",
)

_SYMPTOM_CONTEXT = (
    "症状", "痛", "疼", "闷", "喘", "晕", "吐", "烧", "热", "咳",
    "出血", "便血", "尿血", "黑便", "肿", "麻", "无力", "抽搐",
    "皮疹", "腹泻", "拉肚子", "尿少", "精神差", "乏力",
)

_MEDICAL_CONTEXT = _SYMPTOM_CONTEXT + _ACUTE_CONTEXT + (
    "用药", "吃药", "服药", "停药", "换药", "剂量", "过量",
    "检查", "检查结果", "报告异常", "指标异常", "化验单",
    "就医", "去医院", "要不要去", "严重吗",
    "治疗", "怎么治", "手术", "住院治疗",
)

_DIAGNOSTIC_CONTEXT = _MEDICAL_CONTEXT + (
    "我", "本人", "家人", "患者", "报告", "结果", "异常",
    "很高", "很低", "偏高", "偏低",
)

_SAFETY_RULES = (
    # 明确急症：直接触发
    ContextRule("急症症状", ("胸痛", "呼吸困难", "喘不上气", "喘不过气", "窒息")),
    ContextRule("神经急症", ("昏迷", "晕厥", "抽搐", "翻白眼", "口角歪斜", "言语不清", "单侧肢体无力")),
    ContextRule("严重出血", ("大出血", "严重出血", "咳血", "呕血", "黑便", "便血", "尿血", "止不住血")),
    ContextRule("过敏急症", ("喉头水肿", "过敏性休克", "脸肿喘不过气")),
    ContextRule("自伤意图", ("我想自杀", "想自杀", "不想活了", "想死", "想轻生", "伤害自己")),

    # 需要上下文的风险信号
    ContextRule("胸部风险", ("胸闷", "心悸", "心慌", "大汗", "濒死感", "被压着", "像压着"), _ACUTE_CONTEXT + ("胸", "心口", "气短")),
    ContextRule("特殊人群+医疗上下文", ("孕妇", "怀孕", "孕期", "哺乳期", "产后", "儿童", "小孩", "婴儿", "宝宝", "新生儿", "老人", "高龄"), _MEDICAL_CONTEXT),
    ContextRule("基础病+新症状/用药", ("冠心病", "心梗", "卒中", "脑梗", "糖尿病", "肾衰", "肝硬化", "癌症", "化疗", "免疫抑制", "器官移植"), _MEDICAL_CONTEXT),
    ContextRule("用药风险", ("能不能吃", "可以吃吗", "一起吃", "会冲突", "相互作用", "过量", "吃多了", "中毒", "停药", "能不能停", "漏服", "忘记吃", "加量", "减量", "换药", "药物过敏")),
    ContextRule("高风险药物", ("抗凝药", "华法林", "胰岛素", "激素", "退烧药"), ("过量", "漏服", "加量", "减量", "停药", "副作用", "不良反应", "一起吃", "能不能", "中毒", "过敏")),
    ContextRule("急症表达", ("快不行了", "撑不住了", "要死了", "受不了了", "无法呼吸", "急救", "120", "要不要急诊")),
    ContextRule("慢性红旗", ("体重下降", "消瘦", "食欲下降", "没胃口", "乏力", "盗汗", "大便发黑", "柏油便", "皮肤发黄", "眼白发黄", "淋巴结肿大", "不明原因发热", "低热", "咳血丝痰", "吞咽困难", "声音嘶哑")),
)

_EVIDENCE_RULES = (
    ContextRule("指南需求", ("指南", "标准治疗", "诊疗规范", "专家共识", "治疗方案", "一线", "首选", "循证", "meta分析", "临床路径"), category="evidence"),
    ContextRule("药物咨询", ("吃什么药", "用什么药", "药物治疗", "用药", "服药", "消炎药", "抗生素", "止痛药", "降压药", "降糖药", "副作用", "禁忌", "不良反应", "处方", "疗程"), category="evidence"),
    ContextRule("检查结果+诊疗意图", ("验血", "尿检", "心电图", "CT", "核磁", "B超", "胃镜", "肠镜", "活检", "穿刺", "血红蛋白", "白细胞", "肌酐", "转氨酶", "血糖", "血压"), ("异常", "阳性", "不好", "有问题", "严重", "很高", "很低", "偏高", "偏低", "怎么办", "怎么治", "要不要", "需不需要", "建议", "报告", "结果"), category="evidence"),
    ContextRule("诊疗判断", ("是不是", "会不会是", "可能是什么", "是什么病", "什么引起", "鉴别诊断", "分期", "分型", "严重吗", "要不要去", "需要就医", "需要去医院", "怎么治", "如何治疗", "治疗办法", "手术", "住院治疗"), _DIAGNOSTIC_CONTEXT, category="evidence"),
)

_PROGRESSION_RULES = (
    ContextRule("进展性症状", ("越来越", "持续", "加重", "恶化", "反复", "频繁", "不见好"), _SYMPTOM_CONTEXT, category="progression"),
    ContextRule("病程时间窗", ("好几天", "几天了", "三天", "一周了", "两周", "一个月", "很久了"), _SYMPTOM_CONTEXT + ("没胃口", "体重下降", "盗汗", "乏力"), category="progression"),
    ContextRule("急性发作", ("突然", "急性", "发作", "夜间醒来"), _SYMPTOM_CONTEXT, category="progression"),
)

_PERSONAL_SUBJECTS = (
    "我", "本人", "自己", "家人", "父亲", "母亲", "爸爸", "妈妈",
    "孩子", "宝宝", "小孩", "老人", "孕妇", "患者",
)

_DECISION_INTENT = (
    "怎么办", "怎么处理", "怎么回事", "要不要", "需不需要",
    "能不能", "可以吗", "该不该", "应该", "挂什么科",
    "看医生", "去医院", "治疗", "用药", "吃药",
)

_BROAD_HEALTH_SIGNALS = (
    "不舒服", "难受", "异常", "不对劲",
    "疼", "疼痛", "头痛", "胸痛", "腹痛", "胃痛", "腰痛", "剧痛", "刺痛", "绞痛", "胀痛",
    "麻木", "发麻", "发木", "抽筋", "抽动", "发抖",
    "头晕", "眩晕", "晕倒", "恶心", "反酸", "呕吐",
    "腹泻", "拉肚子", "便秘", "尿频", "尿痛", "尿少",
    "睡不着", "失眠", "没胃口", "乏力", "没劲",
    "肿胀", "红肿", "流血", "出血", "发热", "发烧",
    "咳嗽", "咳痰", "喘不过气", "胸闷", "心慌", "心悸",
    "耳鸣", "嗡嗡响", "眼前黑影", "黑影", "重影", "视物模糊",
    "喉咙痛", "吞咽困难", "皮肤发黄", "皮疹", "紫色斑点",
    "走路不稳", "踩棉花", "报告", "结果", "指标", "检查",
    "药物", "吃药", "用药",
)

_BODY_LOCATION_SIGNALS = (
    "身上", "皮肤", "脸上", "头", "眼", "耳", "鼻", "口", "喉",
    "脖子", "胸", "背", "肚子", "腹", "胃", "腰", "腿", "脚",
    "手", "胳膊", "手臂",
)

_MEDICAL_OBJECT_SIGNALS = (
    "报告", "结果", "指标", "检查", "药", "药物", "吃药", "用药",
)


def _check_personal_medical_intent(question: str) -> list[str]:
    """个人医疗意图兜底。

    目标不是识别具体高危病种，而是避免未枚举的个人症状/报告/用药问题落入 simple。
    """

    has_subject = _has_any(question, _PERSONAL_SUBJECTS)
    has_decision = _has_any(question, _DECISION_INTENT)
    has_health_signal = _has_any(question, _BROAD_HEALTH_SIGNALS)
    has_body_location = _has_any(question, _BODY_LOCATION_SIGNALS)
    has_medical_object = _has_any(question, _MEDICAL_OBJECT_SIGNALS)

    if has_health_signal and (has_subject or has_body_location or has_medical_object):
        return ["个人医疗意图:身体异常/报告/用药问题"]
    if has_decision and has_medical_object:
        return ["个人医疗意图:身体异常/报告/用药问题"]
    if has_subject and has_decision and _has_any(question, ("医院", "医生", "报告", "指标", "检查", "药")):
        return ["个人医疗意图:诊疗决策"]
    return []


_MAKER_CHECKER_STAGES = (
    MakerCheckerStage("安全红线", lambda q: _collect_matches(q, _SAFETY_RULES)),
    MakerCheckerStage("循证需求", lambda q: _collect_matches(q, _EVIDENCE_RULES)),
    MakerCheckerStage("进展性症状", lambda q: _collect_matches(q, _PROGRESSION_RULES)),
    MakerCheckerStage("个人医疗意图兜底", _check_personal_medical_intent),
)


# ============================================================================
# Layer 2: semantic recall — BGE embedding + batch encoding + thread-safe cache
# ============================================================================

_HIGH_RISK_ARCHETYPES = (
    "胸口像被压着一样疼", "心口发紧还冒冷汗", "胸前沉重像有石头压着",
    "喘不上气感觉要窒息了", "吸不上空气快憋死了", "头痛得快要裂开了",
    "突然嘴歪说话含糊", "一边手脚突然没力气", "突然看不清东西了",
    "突然站不稳快晕倒", "症状越来越严重受不了了", "突然就晕过去了",
    "老人摔倒后叫不醒", "一直在流血止不住", "大便发黑还头晕乏力",
    "吐出来的东西像血", "孩子突然翻白眼抽搐", "宝宝精神很差尿很少",
    "孕妇肚子痛还出血", "高烧寒战意识不清", "皮疹后喉咙肿呼吸费劲",
    "肚子疼到站不直还一直吐", "血压特别高还头晕眼花",
    "血糖低到发抖冒汗快晕", "这个药和我的其他药会不会有冲突",
    "我吃多了这个药会不会中毒", "胰岛素打多了现在发抖出汗",
    "吃抗凝药后出现黑便", "药物过敏后脸肿喘不过气",
    "怀孕期间能不能不吃这个药", "我这种情况到底需不需要去医院",
    "会不会是严重的病", "这个症状可能是什么大病吗",
    "检查报告说有危急值怎么办", "我不想活了想伤害自己",
    "最近没胃口体重下降十斤", "持续乏力盗汗一个月",
    "大便发黑像柏油一样", "脖子摸到肿块不痛但越来越大",
    "报告显示血红蛋白很低怎么办",
)

_LOW_RISK_ARCHETYPES = (
    "多喝水对身体有什么好处", "感冒了应该注意什么",
    "怎么预防高血压", "健康饮食有什么建议",
    "每天运动多久比较好", "睡眠不好怎么改善",
    "吃什么水果对身体好", "饭后散步对身体好吗",
    "久坐后怎么拉伸放松", "压力大时怎么调节情绪",
    "如何保持规律作息", "体检前需要注意什么",
    "轻微流鼻涕可以怎么护理", "嗓子有点干日常注意什么",
    "运动后肌肉酸痛怎么缓解", "喝咖啡会不会影响睡眠",
    "少盐少糖饮食怎么做", "晒太阳多久比较合适",
    "口腔清洁有哪些好习惯", "换季时怎么减少鼻子不舒服",
    "久看电脑眼睛疲劳怎么休息", "宝宝吃什么水果好",
    "老人每天散步多久比较好", "CT机器是怎么工作的",
    "住院医保怎么报销", "我想研究自杀这个词的社会学含义",
    "孕妇能不能喝咖啡",
)

_high_embeddings = None
_low_embeddings = None
_encoder = None
_init_lock = threading.Lock()

# 基于 tests/fixtures/router_threshold_eval_1000.jsonl 校准。
# 该阈值只触发高置信 maker_checker 升级。
# 低于该阈值不会判为 simple，而是进入 LLM 仲裁。
SEMANTIC_HIGH_THRESHOLD = 0.15


def _lazy_init_embeddings() -> None:
    """线程安全地初始化 BGE 模型和原型 embedding。"""

    global _high_embeddings, _low_embeddings, _encoder
    if _high_embeddings is not None:
        return

    with _init_lock:
        if _high_embeddings is not None:
            return

        from sentence_transformers import SentenceTransformer

        _encoder = SentenceTransformer("BAAI/bge-small-zh-v1.5", local_files_only=True)
        _high_embeddings = _encoder.encode(
            list(_HIGH_RISK_ARCHETYPES), normalize_embeddings=True
        )
        _low_embeddings = _encoder.encode(
            list(_LOW_RISK_ARCHETYPES), normalize_embeddings=True
        )


def _semantic_risk_score(question: str) -> Optional[float]:
    """净语义分 = max(high) - max(low)。None 表示语义层不可用。"""

    try:
        _lazy_init_embeddings()
        q_emb = _encoder.encode([question], normalize_embeddings=True)[0]
        max_high = float(np.max(q_emb @ _high_embeddings.T))
        max_low = float(np.max(q_emb @ _low_embeddings.T))
        return round(max_high - max_low, 3)
    except Exception as exc:
        from loguru import logger

        logger.warning(f"Semantic router unavailable: {exc}")
        return None


_LLM_ROUTER_SYSTEM_PROMPT = """你是一个医疗问题路由分类器。
你只负责判断用户问题应该进入哪个处理链路，不提供医疗建议。

只能返回 JSON，格式如下：
{"mode":"simple"|"maker_checker","reason":"简短原因"}

以下情况使用 maker_checker：
- 个人症状、身体异常、检查报告、用药决策、治疗选择
- 症状加重、持续进展，或存在潜在医疗风险的不确定问题
- 任何模糊但可能涉及个人医疗决策的问题

以下情况才使用 simple：
- 明确低风险的一般健康科普
- 非个人化医学知识问题
- 医保、行政流程、设备原理、历史、写作、翻译、研究类问题
"""


def _parse_llm_router_json(raw: str) -> dict:
    """Parse JSON-only router output, tolerating fenced JSON."""

    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM router output does not contain a JSON object")
    data = json.loads(text[start : end + 1])
    if data.get("mode") not in {"simple", "maker_checker"}:
        raise ValueError(f"Invalid LLM router mode: {data.get('mode')}")
    return data


async def _llm_route_decision_async(question: str, semantic_score: Optional[float]) -> RouteDecision:
    from core.llm_client import LLMClient

    client = LLMClient(profile="router")
    raw = await client.chat(
        messages=[
            {"role": "system", "content": _LLM_ROUTER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n"
                    f"Semantic score: {semantic_score}\n"
                    "Classify the route."
                ),
            },
        ],
        temperature=0,
        max_tokens=512,
    )
    data = _parse_llm_router_json(raw)
    mode = data["mode"]
    reason = str(data.get("reason", "LLM route decision")).strip()
    return RouteDecision(
        mode=mode,
        reason=f"LLM 路由仲裁: {reason}",
        triggers=[f"llm_mode={mode}", f"semantic_score={semantic_score}"],
        source="llm",
    )


def _llm_route_decision(question: str, semantic_score: Optional[float]) -> RouteDecision:
    """LLM fallback for rule/semantic misses.

    If the LLM is unavailable or returns invalid output, fail closed into maker_checker.
    """

    try:
        from config import get_llm_config

        if not get_llm_config("router").get("api_key"):
            raise RuntimeError("ROUTER_LLM_API_KEY/LLM_API_KEY is not configured")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_llm_route_decision_async(question, semantic_score))
        raise RuntimeError("LLM router called from running event loop; use route_async()")
    except Exception as exc:
        from loguru import logger

        logger.warning(f"LLM router unavailable: {exc}")
        return RouteDecision(
            mode="maker_checker",
            reason="LLM 路由不可用 — 无法确认低风险，保守进入 Maker-Checker",
            triggers=[f"llm_unavailable:{type(exc).__name__}", f"semantic_score={semantic_score}"],
            source="llm",
            degraded=True,
        )


# Backward-compatible alias for existing tests/docs.
SEMANTIC_THRESHOLD = SEMANTIC_HIGH_THRESHOLD


# ============================================================================
# Main entry
# ============================================================================

def _route_without_llm(question: str) -> tuple[RouteDecision | None, str, Optional[float]]:
    """执行不需要 LLM 的路由层，返回确定决策或待仲裁分数。"""
    normalized = question.strip()
    if not normalized:
        return RouteDecision(
            mode="simple",
            reason="空输入",
            triggers=["empty_question"],
            source="rule",
        ), normalized, None

    intent_hits = _check_non_medical_intent(normalized)
    if intent_hits:
        return RouteDecision(
            mode="simple",
            reason=f"非个人医疗决策: {', '.join(intent_hits)}",
            triggers=intent_hits,
            source="rule",
        ), normalized, None

    for stage in _MAKER_CHECKER_STAGES:
        decision = stage.evaluate(normalized)
        if decision:
            return decision, normalized, None

    score = _semantic_risk_score(normalized)
    if score is not None and score >= SEMANTIC_HIGH_THRESHOLD:
        return RouteDecision(
            mode="maker_checker",
            reason=f"语义召回: 净分={score} (高阈值={SEMANTIC_HIGH_THRESHOLD})",
            triggers=[f"semantic_score={score}"],
            source="semantic",
        ), normalized, score

    return None, normalized, score


async def route_async(question: str) -> RouteDecision:
    """异步路由入口；在 Agent 主流程中使用，避免嵌套 asyncio.run()。"""

    decision, normalized, score = _route_without_llm(question)
    if decision:
        return decision

    try:
        from config import get_llm_config

        if not get_llm_config("router").get("api_key"):
            raise RuntimeError("ROUTER_LLM_API_KEY/LLM_API_KEY is not configured")
        return await _llm_route_decision_async(normalized, score)
    except Exception as exc:
        from loguru import logger

        logger.warning(f"LLM router unavailable: {exc}")
        return RouteDecision(
            mode="maker_checker",
            reason="LLM 路由不可用 — 无法确认低风险，保守进入 Maker-Checker",
            triggers=[f"llm_unavailable:{type(exc).__name__}", f"semantic_score={score}"],
            source="llm",
            degraded=True,
        )


def route(question: str) -> RouteDecision:
    """同步路由入口；测试和脚本中使用。异步流程请用 route_async()。"""

    decision, normalized, score = _route_without_llm(question)
    if decision:
        return decision

    return _llm_route_decision(normalized, score)
