"""4 号智能体：把问诊摘要、图谱事实和指南片段合成最终回答。

回答必须依据检索结果，不直接开药或给剂量。
回复末尾附参考来源和“不能替代医生诊断”的提示。
"""
import sys
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from medical_safety import DISCLAIMER, build_safety_context
from model.deepseek import My_model_client

logger = logging.getLogger(__name__)
llm = My_model_client()


def _build_user_context(state: dict) -> str:
    original = state.get("original_query", "")
    summary = state.get("dialogue_summary", "")
    if summary:
        return f"用户主诉：{original}\n问诊汇总：{summary}"
    return original or state.get("raw_query", "")


def _build_reference_sources(chroma_docs: list[dict]) -> str:
    sources: list[str] = []
    seen: set[tuple[str, str]] = set()

    for doc in chroma_docs:
        book = str(doc.get("book") or "未知指南").strip()
        chapter = str(doc.get("chapter") or "未知章节").strip()
        key = (book, chapter)
        if key in seen:
            continue
        seen.add(key)
        sources.append(f"{len(sources) + 1}. 《{book}》：{chapter}")

    if not sources:
        return ""

    return "参考来源：\n" + "\n".join(sources)


def run_answer_synthesizer_agent(state: dict) -> dict:
    """
    4号 Agent 入口函数：整合全链路信息，生成最终答案并写入 state
    """
    logger.info("[4号 Agent] 整合回答启动")

    user_context = _build_user_context(state)
    safety_context = build_safety_context(user_context)
    intent = state.get("intent_analysis", {}).get("intent", "")
    knowledge = state.get("retrieved_knowledge", {})
    neo4j_facts = knowledge.get("neo4j_facts", [])
    chroma_docs = knowledge.get("chroma_docs", [])

    graph_context = "\n".join(neo4j_facts) if neo4j_facts else "未检索到匹配的图谱结构化关系。"

    vector_context = ""
    for idx, doc in enumerate(chroma_docs):
        vector_context += f"\n--- [文献参考 {idx+1}] 《{doc['book']}》({doc['chapter']}) ---\n{doc['content']}\n"
    if not vector_context:
        vector_context = "未检索到匹配的临床指南文本。"

    if intent in ("闲聊", "挂号导诊"):
        generation_prompt = f"""你是友好的医疗助手。用户意图为「{intent}」。
请简洁、礼貌地回答，不要给出具体诊断或处方。若需要专业诊疗，引导用户进一步咨询。

{safety_context}"""
    else:
        generation_prompt = f"""你是一名极其严谨、专业的临床 AI 医学专家助手。请基于以下提供的多路融合知识，回答用户的健康咨询。
你的回答必须100%严格基于这些提供的信息，严禁捏造任何数据。若存在冲突，请以【临床诊疗指南】为准。
即使图谱或知识库中出现“推荐用药”，也不得直接建议用户自行服用药物、给出剂量或疗程，只能建议遵医嘱咨询医生。

{safety_context}

【知识库 1：核心医学结构化图谱事实】
{graph_context}

【知识库 2：国家临床诊疗指南详细切片】
{vector_context}"""

    response = llm.chat_completion(
        messages=[
            {"role": "system", "content": generation_prompt},
            {"role": "user", "content": user_context},
        ]
    )
    final_answer = response.choices[0].message.content or ""
    if DISCLAIMER not in final_answer:
        final_answer = f"{final_answer.rstrip()}\n\n{DISCLAIMER}"
    reference_sources = _build_reference_sources(chroma_docs)
    if reference_sources and "参考来源：" not in final_answer:
        final_answer = f"{final_answer.rstrip()}\n\n{reference_sources}"
        logger.info("[4号 Agent] 已追加参考来源，来源数: %s", len(chroma_docs))
    state["final_answer"] = final_answer
    return state


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    logger.info("开始独立测试 4号整合回答 Agent")

    mock_incoming_state = {
        "session_id": "test-session-final-step",
        "original_query": "肺泡蛋白质沉积症是由什么引起的？需要做什么检查？",
        "raw_query": "肺泡蛋白质沉积症是由什么引起的？需要做什么检查？",
        "dialogue_history": [],
        "dialogue_summary": "",
        "intent_analysis": {
            "intent": "健康咨询",
            "need_graph": True,
            "need_vector": True,
            "neo4j_entity": "肺泡蛋白质沉积症",
            "chroma_query": "肺泡蛋白质沉积症的病因与临床检查规范",
        },
        "retrieved_knowledge": {
            "neo4j_facts": [
                "【疾病定义】肺泡蛋白质沉积症: 是一种罕见疾病。",
                "【病因】肺泡蛋白质沉积症: 推测与几方面因素有关。",
                "【图谱推荐检查】: 胸部CT检查, 肺活检, 支气管镜检查",
            ],
            "chroma_docs": [
                {
                    "book": "临床诊疗指南_放射学检查技术分册_part1pdf",
                    "chapter": "小儿体部 CT 扫描技术指南-检查方法",
                    "content": "对于疑似肺泡蛋白质沉积等间质性肺病的患儿，高分辨率CT(HRCT)是首选影像学检查手段。",
                }
            ],
        },
    }

    updated_state = run_answer_synthesizer_agent(mock_incoming_state)
    logger.info(updated_state.get("final_answer", "未能成功生成最终答案"))
