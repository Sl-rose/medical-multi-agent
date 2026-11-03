"""医疗安全边界。

集中维护急症关键词、急救提示、免责声明，以及禁止替代诊断和开药的约束。
问诊和回答合成都会复用这里的判断。
"""
from __future__ import annotations

from dataclasses import dataclass


SAFETY_SYSTEM_PROMPT = """医疗安全边界：
1. 你不是医生，不能替代线下医生诊断、检查、处方或急诊处置。
2. 不要给出确定诊断；可以说“可能与……有关”“建议进一步检查/就诊评估”。
3. 不要给出具体处方、剂量、疗程或自行用药方案；涉及药物时只做原则性提醒，并建议遵医嘱。
4. 不要因为知识库或图谱中出现“推荐用药”就直接建议用户服用药物。
5. 如果信息不足，明确说明不确定性，优先建议补充信息或线下就医。
6. 出现急症风险时，优先建议立即拨打急救电话或前往急诊，不继续常规问诊。
7. 回答要包含简短的风险提示：以下内容仅供参考，不能替代医生诊断。
"""


DISCLAIMER = "以下内容仅供参考，不能替代医生诊断或处方；如症状严重、持续加重或出现急症表现，请及时就医。"


EMERGENCY_ADVICE = (
    "你描述的情况可能存在急症风险。建议立即拨打急救电话或尽快前往急诊，"
    "不要仅依赖线上问答等待观察。"
)


EMERGENCY_KEYWORDS = (
    "胸痛",
    "胸闷",
    "呼吸困难",
    "喘不上气",
    "窒息",
    "昏迷",
    "意识不清",
    "抽搐",
    "偏瘫",
    "口角歪斜",
    "说话不清",
    "剧烈头痛",
    "大出血",
    "咯血",
    "呕血",
    "黑便",
    "便血",
    "严重过敏",
    "喉头水肿",
    "高热不退",
    "持续高烧",
    "严重腹痛",
    "怀孕出血",
    "胎动异常",
    "自杀",
    "轻生",
)


@dataclass(frozen=True)
class SafetyAssessment:
    emergency: bool
    matched_keywords: tuple[str, ...]


def assess_medical_safety(text: str) -> SafetyAssessment:
    normalized = text or ""
    matched = tuple(keyword for keyword in EMERGENCY_KEYWORDS if keyword in normalized)
    return SafetyAssessment(emergency=bool(matched), matched_keywords=matched)


def build_safety_context(user_context: str) -> str:
    assessment = assess_medical_safety(user_context)
    if not assessment.emergency:
        return f"{SAFETY_SYSTEM_PROMPT}\n请在回答末尾自然加入这句提示：{DISCLAIMER}"

    keywords = "、".join(assessment.matched_keywords)
    return (
        f"{SAFETY_SYSTEM_PROMPT}\n"
        f"当前用户内容命中急症风险关键词：{keywords}。\n"
        f"必须优先输出急症建议：{EMERGENCY_ADVICE}\n"
        "不要继续常规追问，不要给出诊断或用药方案。"
    )


def prepend_emergency_warning_if_needed(reply: str, user_context: str) -> str:
    assessment = assess_medical_safety(user_context)
    if not assessment.emergency:
        return reply
    if EMERGENCY_ADVICE in reply:
        return reply
    return f"{EMERGENCY_ADVICE}\n\n{reply}"
