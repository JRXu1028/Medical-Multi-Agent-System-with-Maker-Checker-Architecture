"""生成确定性的 1000 条 Router 语义阈值评估集。

这是模板扩增的路由压力测试集，不是临床基准数据集。
用途是校准 Semantic Recall 层的工作阈值。
"""

from __future__ import annotations

import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "tests" / "fixtures" / "router_threshold_eval_1000.jsonl"
RANDOM_SEED = 20260603
TARGET_SIMPLE = 500
TARGET_MAKER = 500


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        query = item["query"]
        if query in seen:
            continue
        seen.add(query)
        out.append(item)
    return out


def _simple_cases() -> list[dict]:
    rows: list[dict] = []

    subjects = ["", "宝宝", "老人", "孕妇", "上班族", "学生", "家里老人"]
    low_risk_topics = [
        "多喝水", "吃水果", "每天散步", "饭后散步", "规律睡眠", "健康饮食",
        "少盐少糖饮食", "久坐后拉伸", "运动后放松", "晒太阳", "喝咖啡",
        "口腔清洁", "体检前准备", "预防高血压", "改善作息", "缓解压力",
    ]
    low_risk_intents = [
        "有什么好处", "多久比较好", "怎么做比较好", "有什么建议",
        "需要注意什么", "可以吗", "能不能做", "适合吗",
    ]
    for subject in subjects:
        for topic in low_risk_topics:
            for intent in low_risk_intents:
                rows.append({
                    "query": f"{subject}{topic}{intent}",
                    "expected": "simple",
                    "category": "low_risk_health_education",
                })

    admin_topics = ["医保报销", "住院费用", "挂号预约", "门诊缴费", "检查预约"]
    admin_intents = ["流程是什么", "怎么操作", "在哪里办理", "需要什么材料", "大概怎么收费"]
    for topic in admin_topics:
        for intent in admin_intents:
            rows.append({
                "query": f"{topic}{intent}",
                "expected": "simple",
                "category": "medical_admin",
            })

    device_topics = ["CT机器", "核磁机器", "B超设备", "心电图机器", "胃镜设备"]
    device_intents = ["是怎么工作的", "原理是什么", "是谁发明的", "历史是什么", "设备怎么维护"]
    for topic in device_topics:
        for intent in device_intents:
            rows.append({
                "query": f"{topic}{intent}",
                "expected": "simple",
                "category": "device_principle",
            })

    research_queries = [
        "我想研究自杀这个词的社会学含义",
        "帮我翻译一段关于疾病历史的文章",
        "论文里如何解释医院管理流程",
        "写作中怎么描述药物发展史",
        "我想了解诊断这个概念的词源",
    ]
    for query in research_queries:
        rows.append({
            "query": query,
            "expected": "simple",
            "category": "research_or_writing",
        })

    object_queries = [
        "我手机一直响怎么办",
        "手表一直抖怎么办",
        "衣服上有紫色斑点怎么办",
        "电脑屏幕有黑影怎么办",
        "耳机嗡嗡响怎么处理",
    ]
    for query in object_queries:
        rows.append({
            "query": query,
            "expected": "simple",
            "category": "non_medical_object",
        })

    return _dedupe(rows)


def _maker_cases() -> list[dict]:
    rows: list[dict] = []

    chest_subjects = ["我", "老人", "家人", "爸爸", "妈妈"]
    chest_signals = [
        "胸口像被压着一样疼", "心口发紧还冒冷汗", "胸前沉重像有石头压着",
        "胸闷心慌大汗", "胸口堵得喘不上气", "心口像被勒住一样",
    ]
    acute_contexts = ["突然出现", "现在还没缓解", "越来越严重", "同时头晕", "活动后更明显"]
    for subject in chest_subjects:
        for signal in chest_signals:
            for ctx in acute_contexts:
                rows.append({
                    "query": f"{subject}{ctx}{signal}",
                    "expected": "maker_checker",
                    "category": "semantic_chest_risk",
                })

    breath_subjects = ["我", "孩子", "老人", "家人"]
    breath_signals = [
        "喘不过气", "吸不上空气", "感觉要窒息", "呼吸很费劲",
        "喉咙肿了喘不过气", "一躺下就喘不上来",
    ]
    for subject in breath_subjects:
        for signal in breath_signals:
            for ctx in acute_contexts:
                rows.append({
                    "query": f"{subject}{ctx}{signal}",
                    "expected": "maker_checker",
                    "category": "semantic_breathing_risk",
                })

    neuro_subjects = ["我", "老人", "家人", "爸爸", "妈妈", "孩子"]
    neuro_signals = [
        "突然说话含糊", "一边手脚没力气", "突然站不稳快晕倒",
        "嘴角歪斜", "眼前突然看不清", "突然翻白眼抽搐",
    ]
    for subject in neuro_subjects:
        for signal in neuro_signals:
            for ctx in ["刚刚", "突然", "现在还在", "反复出现"]:
                rows.append({
                    "query": f"{subject}{ctx}{signal}",
                    "expected": "maker_checker",
                    "category": "semantic_neuro_risk",
                })

    bleeding_signals = [
        "大便发黑像柏油", "吐出来的东西像血", "一直流血止不住",
        "咳血丝越来越多", "尿里有血", "皮肤突然出现紫色斑点",
    ]
    for subject in ["我", "老人", "家人", "宝宝"]:
        for signal in bleeding_signals:
            for ctx in ["今天", "这两天", "同时头晕乏力", "越来越明显"]:
                rows.append({
                    "query": f"{subject}{ctx}{signal}怎么办",
                    "expected": "maker_checker",
                    "category": "semantic_bleeding_risk",
                })

    special_subjects = ["宝宝", "孕妇", "老人", "新生儿", "免疫抑制患者"]
    special_signals = [
        "持续呕吐尿量减少", "高热寒战精神很差", "肚子痛还出血",
        "头痛越来越严重", "吃药后脸肿喘不过气",
    ]
    for subject in special_subjects:
        for signal in special_signals:
            for intent in ["怎么办", "要不要去医院", "严重吗", "需要急诊吗"]:
                rows.append({
                    "query": f"{subject}{signal}{intent}",
                    "expected": "maker_checker",
                    "category": "special_population_medical",
                })

    drug_queries = [
        "这个药能和降压药一起吃吗",
        "华法林漏服后能不能补一片",
        "胰岛素打多了现在发抖出汗",
        "抗凝药吃完出现黑便怎么办",
        "药物过敏后脸肿喘不过气",
        "孕期能不能停这个药",
        "吃多了这个药会不会中毒",
        "降糖药和退烧药会不会冲突",
    ]
    for query in drug_queries:
        for suffix in ["", "现在很担心", "要不要去医院", "怎么处理"]:
            rows.append({
                "query": f"{query}{suffix}",
                "expected": "maker_checker",
                "category": "medication_risk",
            })

    evidence_queries = [
        "高血压最新治疗指南是什么",
        "这个病的标准治疗方案是什么",
        "感冒了需要吃什么药",
        "检查报告显示血红蛋白很低怎么办",
        "心电图报告异常需要怎么处理",
        "头晕是不是脑供血不足需要做什么检查",
        "这个结果阳性严重吗",
        "需要手术还是住院治疗",
    ]
    for query in evidence_queries:
        for suffix in ["", "请按指南说", "需要循证依据", "我想知道诊疗路径"]:
            rows.append({
                "query": f"{query}{suffix}",
                "expected": "maker_checker",
                "category": "evidence_or_diagnostic",
            })

    progression_signals = [
        "头痛三天越来越严重",
        "乏力盗汗一个月",
        "最近没胃口体重下降十斤",
        "咳嗽两周不见好",
        "腹痛反复发作越来越频繁",
        "皮疹越来越多不见好",
    ]
    for subject in ["我", "家人", "老人"]:
        for signal in progression_signals:
            for intent in ["怎么办", "要不要检查", "严重吗", "需要看医生吗"]:
                rows.append({
                    "query": f"{subject}{signal}{intent}",
                    "expected": "maker_checker",
                    "category": "progression",
                })

    personal_unknown = [
        "我耳朵里一直嗡嗡响怎么办",
        "家人走路像踩棉花怎么办",
        "我眼前总有黑影飘怎么办",
        "我身上突然出现紫色斑点怎么办",
        "妈妈脖子摸到肿块越来越大怎么办",
        "爸爸最近总是没力气还没胃口怎么办",
    ]
    for query in personal_unknown:
        rows.append({
            "query": query,
            "expected": "maker_checker",
            "category": "personal_medical_intent",
        })

    return _dedupe(rows)


def main() -> None:
    random.seed(RANDOM_SEED)
    simple = _simple_cases()
    maker = _maker_cases()

    if len(simple) < TARGET_SIMPLE or len(maker) < TARGET_MAKER:
        raise RuntimeError(
            f"生成样例不足: simple={len(simple)}, maker={len(maker)}"
        )

    selected = (
        random.sample(simple, TARGET_SIMPLE)
        + random.sample(maker, TARGET_MAKER)
    )
    random.shuffle(selected)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as f:
        for row in selected:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"已写入 {len(selected)} 条样例到 {OUTPUT.relative_to(ROOT)}")
    print(f"simple={TARGET_SIMPLE} maker_checker={TARGET_MAKER}")


if __name__ == "__main__":
    main()
