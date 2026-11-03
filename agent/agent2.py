"""2 号智能体：分步问诊，一次只追问一个缺失信息。

默认收集不适位置、持续时长和是否发烧。
命中急症关键词时立即结束常规问诊，并提示急救。
"""
import json
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from medical_safety import (
    DISCLAIMER,
    EMERGENCY_ADVICE,
    SAFETY_SYSTEM_PROMPT,
    assess_medical_safety,
    prepend_emergency_warning_if_needed,
)
from model.deepseek import My_model_client

logger = logging.getLogger(__name__)
llm = My_model_client()

DIALOGUE_COMPLETE_MARKER = "[DIALOGUE_COMPLETE]"

SYSTEM_PROMPT = f"""你是问诊助手，分步采集用户病状信息，一次只问一个问题。
需要收集信息：不舒服的具体位置、持续时长、是否发烧。
{SAFETY_SYSTEM_PROMPT}
规则：
1. 一轮只提一个问题，不要一次性多问；
2. 所有信息收集完整后汇总病情，不再追问；
3. 不给出诊断、不开药物，仅收集信息；
4. 如果用户描述出现急症风险，先提醒立即急诊/急救，不要继续常规追问；
5. 当三项信息均已收集完毕并输出汇总时，在回复最末尾单独一行写入 {DIALOGUE_COMPLETE_MARKER}；
6. 问诊总结末尾要自然加入这句提示：{DISCLAIMER}。"""


def run_dialogue_agent(state: dict) -> dict:
    """
    2号 Agent 入口函数：负责多轮记忆维护、信息采集问诊
    """
    logger.info("[2号 Agent] 多轮对话问诊启动")

    current_user_query = state.get("raw_query", "")
    history = list(state.get("dialogue_history", []))

    safety = assess_medical_safety(current_user_query)
    if safety.emergency:
        logger.warning(
            "[2号 Agent] 命中急症风险关键词，结束常规问诊: %s",
            "、".join(safety.matched_keywords),
        )
        history.append({"role": "user", "content": current_user_query})
        history.append({"role": "assistant", "content": EMERGENCY_ADVICE})
        state["dialogue_history"] = history
        state["assistant_reply"] = EMERGENCY_ADVICE
        state["dialogue_complete"] = True
        state["dialogue_summary"] = current_user_query
        state["final_answer"] = EMERGENCY_ADVICE
        return state

    history_str = ""
    for turn in history:
        role_label = "用户" if turn["role"] == "user" else "医生助手"
        history_str += f"{role_label}: {turn['content']}\n"

    combined_query = f"【历史对话记录】\n{history_str}\n【当前用户最新回答】\n{current_user_query}"
    reply = llm.ask(query=combined_query, system_prompt=SYSTEM_PROMPT)

    dialogue_complete = DIALOGUE_COMPLETE_MARKER in reply
    clean_reply = reply.replace(DIALOGUE_COMPLETE_MARKER, "").strip()
    clean_reply = prepend_emergency_warning_if_needed(clean_reply, combined_query)

    history.append({"role": "user", "content": current_user_query})
    history.append({"role": "assistant", "content": clean_reply})

    state["dialogue_history"] = history
    state["assistant_reply"] = clean_reply
    state["dialogue_complete"] = dialogue_complete

    if dialogue_complete:
        state["dialogue_summary"] = clean_reply
        logger.info("[2号 Agent] 问诊完成，已汇总病情。轮数: %s", len(history) // 2)
    else:
        state["final_answer"] = clean_reply
        logger.info("[2号 Agent] 继续追问。当前记忆轮数: %s", len(history) // 2)

    return state


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("开始独立测试 2号多轮对话 Agent")

    shared_state = {
        "session_id": "multi-turn-session-9999",
        "raw_query": "我肚子疼",
        "dialogue_history": [],
        "dialogue_complete": False,
        "dialogue_summary": "",
        "assistant_reply": "",
        "final_answer": "",
    }

    for i, user_msg in enumerate(["我肚子疼", "小腹位置，疼了大概3小时", "没有发烧"], 1):
        logger.info("[第 %s 轮问答]", i)
        shared_state["raw_query"] = user_msg
        shared_state = run_dialogue_agent(shared_state)
        logger.info("助手反馈：%s", shared_state["assistant_reply"])
        if shared_state.get("dialogue_complete"):
            logger.info("问诊已结束")
            break

    logger.info("[最终追踪] 全局共享 State 状态结构:\n%s", json.dumps(shared_state, ensure_ascii=False, indent=2))
