"""3 号智能体：同时检索临床指南向量库和 Neo4j 医学图谱。

ChromaDB 使用百炼文本向量，Neo4j 提供疾病等结构化关系。
两路查询并发执行，结果交给 4 号智能体合成回答。
"""
import os
import sys
import time
import logging
import concurrent.futures
from pathlib import Path

from dotenv import load_dotenv

# 强行阻断代理，防止百炼 SDK 的 SSL 报错
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""

load_dotenv()

import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
from neo4j import GraphDatabase
import dashscope
from dashscope import TextEmbedding

PROJECT_ROOT = Path(__file__).parent.parent
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
logger = logging.getLogger(__name__)


class DashScopeEmbeddingFunction(EmbeddingFunction):
    """百炼文本向量化工具类"""
    def __init__(self, model_name="text-embedding-v4"):
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = TextEmbedding.call(model=self.model_name, input=input, dimension=768)
                if resp.status_code == 200:
                    return [e["embedding"] for e in resp.output["embeddings"]]
                raise Exception(f"百炼 API 失败: {resp.message}")
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                logger.warning(
                    "Embedding 网络/SSL 中断，第 %s 次重试: %s",
                    attempt + 1,
                    e,
                )
                time.sleep(3 * (attempt + 1))


class MedicalKnowledgeSearchAgent:
    """
    3号知识检索 Agent 类
    管理 ChromaDB 和 Neo4j 的长连接，负责双路并发知识召回
    """
    def __init__(
        self,
        chroma_path=None,
        neo4j_uri=None,
        neo4j_auth=None,
    ):
        logger.info("[3号 Agent] 正在初始化数据库长连接池")
        chroma_path = chroma_path or os.getenv("CHROMA_PATH") or str(PROJECT_ROOT / "chromadb")
        neo4j_uri = neo4j_uri or os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
        if neo4j_auth is None:
            neo4j_auth = (
                os.getenv("NEO4J_USER", "neo4j"),
                os.getenv("NEO4J_PASSWORD", ""),
            )
        
        # 1. 初始化 ChromaDB
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.chroma_collection = self.chroma_client.get_collection(
            name="collection_0424", 
            embedding_function=DashScopeEmbeddingFunction()
        )
        
        # 2. 初始化 Neo4j Driver (内部自带连接池)
        self.neo4j_driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
        logger.info("[3号 Agent] ChromaDB & Neo4j 连接就绪")

    def _fetch_neo4j(self, entity_name: str) -> list:
        """内部方法：精确检索图谱事实"""
        if not entity_name: return []
        facts = []
        try:
            with self.neo4j_driver.session() as session:
                disease_query = """
                MATCH (d:Disease) WHERE d.name CONTAINS $entity
                RETURN d.name as name, d.desc as desc, d.cause as cause, d.prevent as prevent LIMIT 1
                """
                res = session.run(disease_query, entity=entity_name).single()
                if res:
                    facts.extend([
                        f"【疾病定义】{res['name']}: {res['desc']}",
                        f"【病因】{res['name']}: {res['cause']}",
                        f"【建议预防】{res['prevent']}"
                    ])
                    # 查询检查与药物
                    rel_query = "MATCH (d:Disease)-[r:NEED_CHECK|RECOMMEND_DRUG]->(t) WHERE d.name = $name RETURN type(r) as rel, t.name as tgt"
                    rel_res = session.run(rel_query, name=res['name'])
                    checks, drugs = [], []
                    for rec in rel_res:
                        checks.append(rec['tgt']) if rec['rel'] == 'NEED_CHECK' else drugs.append(rec['tgt'])
                    if checks: facts.append(f"【图谱推荐检查】: {', '.join(checks)}")
                    if drugs: facts.append(f"【图谱推荐用药】: {', '.join(drugs)}")
                else:
                    # 兜底查询
                    backup_query = "MATCH (s)-[r]->(t) WHERE s.name CONTAINS $entity OR t.name CONTAINS $entity RETURN s.name, type(r), t.name LIMIT 6"
                    for rec in session.run(backup_query, entity=entity_name):
                        facts.append(f"【图谱关联】 [{rec[0]}] --({rec[1]})--> [{rec[2]}]")
            return facts
        except Exception as e:
            logger.warning("Neo4j 检索异常: %s", e)
            return []

    def _fetch_chroma(self, query_text: str, top_k: int = 3) -> list:
        """内部方法：模糊检索指南切片"""
        if not query_text: return []
        try:
            res = self.chroma_collection.query(query_texts=[query_text], n_results=top_k)
            docs = []
            if res and res['documents']:
                for doc, meta in zip(res['documents'][0], res['metadatas'][0]):
                    docs.append({
                        "book": meta.get("book", "未知指南"), 
                        "chapter": f"{meta.get('h1','')}-{meta.get('h2','')}", 
                        "content": doc
                    })
            return docs
        except Exception as e:
            logger.warning("Chroma 检索异常: %s", e)
            return []

    def run(self, state: dict) -> dict:
        """
        核心对外接口：完全顺应你的标准化 State 字典流转规范
        """
        logger.info("[3号 Agent] 复合知识检索中")
        intent = state.get("intent_analysis", {})
        
        neo4j_facts = []
        chroma_docs = []
        
        # 利用线程池并发检索，消灭网络串行等待
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {}
            if intent.get("need_graph") and intent.get("neo4j_entity"):
                futures["neo4j"] = executor.submit(self._fetch_neo4j, intent["neo4j_entity"])
            if intent.get("need_vector") and intent.get("chroma_query"):
                futures["chroma"] = executor.submit(self._fetch_chroma, intent["chroma_query"])
                
            concurrent.futures.wait(futures.values())
            if "neo4j" in futures: neo4j_facts = futures["neo4j"].result()
            if "chroma" in futures: chroma_docs = futures["chroma"].result()
            
        # 增量写入全局状态
        state["retrieved_knowledge"] = {
            "neo4j_facts": neo4j_facts,
            "chroma_docs": chroma_docs
        }
        logger.info(
            "[3号 Agent] 检索闭环。图谱事实: %s 条 | 指南切片: %s 条",
            len(neo4j_facts),
            len(chroma_docs),
        )
        return state

    def close(self):
        """当程序彻底关闭时释放图连接"""
        if hasattr(self, 'neo4j_driver'):
            self.neo4j_driver.close()


# =====================================================================
# 本地独立测试
# =====================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # 实例化 Agent（此时建立长连接）
    search_agent = MedicalKnowledgeSearchAgent()
    
    mock_state = {
        "raw_query": "肺泡蛋白质沉积症需要做什么检查？",
        "intent_analysis": {
            "need_graph": True,
            "need_vector": True,
            "neo4j_entity": "肺泡蛋白质沉积症",
            "chroma_query": "肺泡蛋白质沉积症的临床检查规范"
        }
    }
    
    # 运行检索
    result_state = search_agent.run(mock_state)
    logger.info("[测试成功] 检索到的元数据结构如下: %s", result_state["retrieved_knowledge"])
    
    # 释放资源
    search_agent.close()
