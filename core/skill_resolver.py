"""本地 Progressive Skill Resolver。

本模块实现 v3 Skills 调研后的 Phase C：Cluster Hybrid Progressive Skill
Loading。它在 Maker 第一次 LLM 调用前运行，用代码选择 2-4 个需要注入
上下文的 SKILL.md，避免每次都让 LLM 读取完整 Skill Index 再做选择。

设计边界：
- 只选择方法论 Skill，不执行工具。
- 不进入 tool_trace，不生成 evidence。
- 只做少量高精度安全补齐 + cluster gating + 轻量检索。
- 医疗安全硬约束仍由 Checker/PreStopPolicy 和 SafetyGate 独立负责。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from core.skill_index import SkillDoc


DEFAULT_MAX_SKILLS = 4
DEFAULT_MIN_SCORE = 0.025


@dataclass(frozen=True)
class SkillResolution:
    """SkillResolver 的可追踪输出。"""

    selected_skill_ids: List[str]
    safety_implied_skill_ids: List[str] = field(default_factory=list)
    clusters: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    resolver_version: str = "cluster_hybrid_v1"

    def to_dict(self) -> Dict[str, object]:
        """转换为 process_trace 可写入的 dict。"""

        return {
            "selected_skill_ids": self.selected_skill_ids,
            "safety_implied_skill_ids": self.safety_implied_skill_ids,
            "clusters": self.clusters,
            "scores": self.scores,
            "reasons": self.reasons,
            "resolver_version": self.resolver_version,
        }


class SkillResolver:
    """Cluster Hybrid Skill 选择器。

    它把本地实验中表现最好的方案落成生产可用的轻量组件：
    1. 高精度安全组合规则先补齐关键 Skills。
    2. 根据 query 匹配 1-2 个能力簇。
    3. 在簇内用字符 ngram TF-IDF 做轻量检索。
    4. 保序去重并限制最多加载 2-4 个 Skill。
    """

    CLUSTER_TRIGGERS: Mapping[str, Sequence[str]] = {
        "acute": (
            "症状",
            "胸痛",
            "呼吸困难",
            "腹痛",
            "头痛",
            "发热",
            "急诊",
            "挂什么科",
            "就医",
            "不想活",
            "自杀",
            "头晕",
        ),
        "medication": ("药", "同服", "漏服", "剂量", "副作用", "禁忌", "华法林", "抗生素"),
        "report": ("报告", "化验", "尿酸", "白细胞", "CT", "MRI", "心电图", "血压", "血氧"),
        "evidence": ("指南", "证据", "比较", "哪个", "推荐", "最新", "研究", "共识"),
        "education": ("是什么", "区别", "原理", "疫苗", "设备", "科普", "必要"),
        "lifestyle": ("高血压", "糖尿病", "饮食", "运动", "睡眠", "减脂", "康复", "咖啡"),
        "special": ("孕妇", "怀孕", "儿童", "老人", "哺乳", "宝宝"),
        "memory": ("我之前", "上次", "记得", "病史", "过敏史", "偏好"),
    }

    SKILL_CLUSTERS: Mapping[str, str] = {
        "symptom_triage": "acute",
        "emergency_red_flags": "acute",
        "mental_health_safety": "acute",
        "clarifying_questions": "acute",
        "care_navigation": "acute",
        "medication_safety": "medication",
        "drug_interaction": "medication",
        "renal_liver_dose_safety": "medication",
        "pregnancy_pediatric_safety": "special",
        "geriatric_safety": "special",
        "lab_report": "report",
        "imaging_report": "report",
        "ecg_vital_signs": "report",
        "guideline_research": "evidence",
        "evidence_comparison": "evidence",
        "source_quality_appraisal": "evidence",
        "health_education": "education",
        "preventive_care": "education",
        "medical_device_explainer": "education",
        "chronic_care": "lifestyle",
        "lifestyle_coaching": "lifestyle",
        "nutrition_weight_management": "lifestyle",
        "rehabilitation_exercise_safety": "lifestyle",
        "memory_personalization": "memory",
    }

    def __init__(
        self,
        *,
        max_skills: int = DEFAULT_MAX_SKILLS,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> None:
        self.max_skills = max(1, max_skills)
        self.min_score = min_score

    def resolve(
        self,
        *,
        user_query: str,
        skill_docs: Mapping[str, SkillDoc],
    ) -> SkillResolution:
        """根据用户问题和 SkillDoc catalog 选择需要加载的 Skills。"""

        if not user_query.strip() or not skill_docs:
            return SkillResolution(
                selected_skill_ids=[],
                reasons=["empty_query_or_catalog"],
            )

        hard_ids = [
            skill_id for skill_id in self._policy_implied_skills(user_query)
            if skill_id in skill_docs
        ]
        clusters = self._matched_clusters(user_query)
        candidate_ids = self._candidate_ids(skill_docs, clusters)
        ranked = self._rank_by_retrieval(user_query, skill_docs, candidate_ids)
        selected = dedupe_preserve_order(
            [
                *hard_ids,
                *[
                    skill_id for skill_id, score in ranked
                    if score >= self.min_score
                ],
            ],
            cap=self.max_skills,
        )

        # 若 query 没命中任何规则/检索，但 catalog 有 health_education，则给一个低风险默认方法论。
        if not selected and "health_education" in skill_docs:
            selected = ["health_education"]

        return SkillResolution(
            selected_skill_ids=selected,
            safety_implied_skill_ids=hard_ids,
            clusters=clusters,
            scores={skill_id: round(score, 4) for skill_id, score in ranked[:8]},
            reasons=self._build_reasons(hard_ids, clusters, selected),
        )

    def _candidate_ids(
        self,
        skill_docs: Mapping[str, SkillDoc],
        clusters: Sequence[str],
    ) -> List[str]:
        """返回 cluster gating 后的候选 Skill ids。"""

        if not clusters:
            return list(skill_docs.keys())
        cluster_set = set(clusters)
        candidates = [
            skill_id for skill_id in skill_docs
            if self.SKILL_CLUSTERS.get(skill_id) in cluster_set
        ]
        return candidates or list(skill_docs.keys())

    def _matched_clusters(self, query: str) -> List[str]:
        """用高精度关键词匹配 1-2 个能力簇。"""

        text = normalize(query)
        scored: List[Tuple[str, int]] = []
        for cluster, triggers in self.CLUSTER_TRIGGERS.items():
            hits = sum(1 for trigger in triggers if normalize(trigger) in text)
            if hits:
                scored.append((cluster, hits))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [cluster for cluster, _ in scored[:2]]

    def _rank_by_retrieval(
        self,
        query: str,
        skill_docs: Mapping[str, SkillDoc],
        candidate_ids: Sequence[str],
    ) -> List[Tuple[str, float]]:
        """在候选 Skill 中做字符 ngram TF-IDF 检索排序。"""

        doc_vectors = {
            skill_id: Counter(char_ngrams(skill_index_text(skill_docs[skill_id])))
            for skill_id in candidate_ids
            if skill_id in skill_docs
        }
        if not doc_vectors:
            return []

        doc_freq = Counter()
        for vec in doc_vectors.values():
            for token in vec:
                doc_freq[token] += 1

        query_vec = tfidf(Counter(char_ngrams(query)), doc_freq, len(doc_vectors))
        scores = []
        for skill_id, vec in doc_vectors.items():
            score = cosine(
                query_vec,
                tfidf(vec, doc_freq, len(doc_vectors)),
            )
            scores.append((skill_id, score))
        scores.sort(key=lambda item: (-item[1], item[0]))
        return scores

    def _policy_implied_skills(self, query: str) -> List[str]:
        """少量高精度组合规则，补齐医疗安全关键 Skills。

        这里不是完整 Signal Catalog，只覆盖本地实验中发现的高风险组合：
        特殊人群 + 用药、生命体征异常 + 症状、多药同服、心理危机等。
        """

        text = normalize(query)
        implied: List[str] = []

        def has_any(words: Iterable[str]) -> bool:
            return any(normalize(word) in text for word in words)

        if has_any(("胸痛", "呼吸困难", "昏厥", "晕厥", "意识模糊", "单侧无力", "严重出血", "视力突然丧失")):
            implied.extend(["symptom_triage", "emergency_red_flags"])
        if has_any(("腹痛", "头痛", "发热", "发烧", "咳嗽", "呕吐", "头晕", "疼")) and has_any(("严重", "要紧", "就医", "急诊", "观察", "怎么办")):
            implied.append("symptom_triage")
        if has_any(("自杀", "自残", "轻生", "不想活", "伤害自己", "伤害别人")):
            implied.append("mental_health_safety")
        if has_any(("一起吃", "同服", "相互作用", "华法林", "抗凝", "布洛芬")):
            implied.extend(["drug_interaction", "medication_safety"])
        if has_any(("漏服", "停药", "补两片", "剂量", "副作用", "过敏", "吃什么药")):
            implied.append("medication_safety")
        if has_any(("肌酐", "肾功能", "肝功能", "egfr", "肝硬化")) and has_any(("药", "抗生素", "剂量")):
            implied.extend(["renal_liver_dose_safety", "medication_safety"])
        if has_any(("孕妇", "怀孕", "哺乳", "儿童", "宝宝", "小孩", "婴儿")):
            implied.append("pregnancy_pediatric_safety")
            if has_any(("发烧", "发热", "药", "吃", "能吃")):
                implied.extend(["medication_safety", "symptom_triage"])
        if has_any(("老人", "老年")):
            implied.append("geriatric_safety")
            if has_any(("跌倒", "疼", "观察", "骨折")):
                implied.extend(["symptom_triage", "care_navigation"])
        if has_any(("心电图", "血压", "血氧", "心率", "房颤")):
            implied.append("ecg_vital_signs")
            if has_any(("180", "92", "要紧", "胸痛", "呼吸困难")):
                implied.append("symptom_triage")
        if has_any(("化验单", "检查报告", "尿酸", "白细胞", "血糖", "血脂")):
            implied.append("lab_report")
            if has_any(("高血压", "糖尿病", "尿酸", "血糖", "血脂")):
                implied.append("chronic_care")
            if has_any(("发热", "发烧", "就医", "严重")):
                implied.append("symptom_triage")
        if has_any(("ct", "mri", "核磁", "超声", "影像", "结节")):
            implied.append("imaging_report")
            if has_any(("区别", "是什么", "意思")):
                implied.append("health_education")
        if has_any(("比较", "区别", "哪个好", "利弊", "哪个证据")):
            implied.append("evidence_comparison")
        if has_any(("指南", "共识", "最新", "推荐", "证据")):
            implied.append("guideline_research")
            if has_any(("证据", "研究", "来源", "质量", "最新")):
                implied.append("source_quality_appraisal")
        if has_any(("高血压", "糖尿病", "高尿酸", "痛风", "高血脂")):
            implied.append("chronic_care")
        if has_any(("饮食", "运动", "睡眠", "熬夜", "咖啡", "喝酒", "生活方式")):
            implied.append("lifestyle_coaching")
        if has_any(("减肥", "减脂", "体重", "热量", "蛋白质", "控糖", "控盐")):
            implied.extend(["nutrition_weight_management", "lifestyle_coaching"])
        if has_any(("康复", "训练", "膝盖", "扭伤", "运动损伤")):
            implied.append("rehabilitation_exercise_safety")
            if has_any(("疼", "扭伤", "损伤")):
                implied.append("symptom_triage")
        if has_any(("疫苗", "接种", "筛查", "体检", "预防")):
            implied.append("preventive_care")
            if has_any(("必要", "是什么", "为什么")):
                implied.append("health_education")
        if has_any(("血氧仪", "血压计", "血糖仪", "设备", "可穿戴")):
            implied.append("medical_device_explainer")
            if has_any(("92", "血氧")):
                implied.extend(["ecg_vital_signs", "symptom_triage"])
        if has_any(("我之前", "上次", "记得", "病史", "过敏史")):
            implied.append("memory_personalization")

        return dedupe_preserve_order(implied)

    @staticmethod
    def _build_reasons(
        hard_ids: Sequence[str],
        clusters: Sequence[str],
        selected: Sequence[str],
    ) -> List[str]:
        """生成简短可观测原因。"""

        reasons: List[str] = []
        if hard_ids:
            reasons.append(f"safety_implied={','.join(hard_ids)}")
        if clusters:
            reasons.append(f"clusters={','.join(clusters)}")
        if selected:
            reasons.append(f"selected={','.join(selected)}")
        return reasons or ["no_signal_default"]


def skill_index_text(doc: SkillDoc) -> str:
    """把 SkillDoc 的紧凑触发信息转成检索文本。"""

    return " ".join(
        [
            doc.id,
            doc.description,
            " ".join(doc.when_to_load),
            " ".join(doc.suggested_tools),
        ]
    )


def normalize(text: str) -> str:
    """轻量规范化，兼容中文和英文缩写。"""

    return str(text or "").lower()


def char_ngrams(text: str) -> List[str]:
    """中文字符 2-gram + 英文/数字 token。

    不引入 sklearn/sentence-transformers，保证本地测试和 CI 快速稳定。
    """

    normalized = normalize(text)
    ascii_tokens = re.findall(r"[a-z0-9]+", normalized)
    compact = re.sub(r"\s+", "", normalized)
    grams = [compact[i : i + 2] for i in range(max(0, len(compact) - 1))]
    return ascii_tokens + grams


def tfidf(
    vec: Counter[str],
    doc_freq: Mapping[str, int],
    n_docs: int,
) -> Dict[str, float]:
    """计算轻量 TF-IDF 权重。"""

    weighted: Dict[str, float] = {}
    for token, count in vec.items():
        weighted[token] = count * math.log((n_docs + 1) / (doc_freq.get(token, 0) + 1)) + 1.0
    return weighted


def cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    """计算两个稀疏向量的余弦相似度。"""

    if not a or not b:
        return 0.0
    dot = sum(value * b.get(token, 0.0) for token, value in a.items())
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def dedupe_preserve_order(
    items: Iterable[str],
    *,
    cap: int | None = None,
) -> List[str]:
    """保序去重，并可限制最大数量。"""

    seen = set()
    result: List[str] = []
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if cap is not None and len(result) >= cap:
            break
    return result
