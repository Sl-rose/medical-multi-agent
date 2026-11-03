"""把 rag_chunks.json 写入本地 ChromaDB，供 3 号智能体检索。

使用百炼 text-embedding-v4 生成 768 维向量，并按已有条数断点续传。
"""
import os
import json
import hashlib
import time
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
import dashscope
from dashscope import TextEmbedding

# ================= 配置区域 =================
CHUNKS_JSON = r"D:\多智能体协作\rag_chunks.json"      # 你的分块 JSON 数据路径
DB_PATH = "./chromadb"                             # ChromaDB 本地路径
COLLECTION_NAME = "collection_0424"                 # 集合名称

# 显式清除环境变量中的代理，防止 requests/urllib3 自动化读取导致 SSL 握手失败
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY") 
# ============================================

class DashScopeEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name: str = "text-embedding-v4"):
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        # 终极强悍的重试机制，应对 SSL 握手断开（UNEXPECTED_EOF）
        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = TextEmbedding.call(
                    model=self.model_name,
                    input=input,
                    dimension=768
                )
                if resp.status_code == 200:
                    return [e['embedding'] for e in resp.output['embeddings']]
                else:
                    raise Exception(f"API Error: {resp.message}")
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                # 遇到 SSL 问题或者抖动，打印提示并稍微多等一下再试
                print(f"⚠️ 触发网络或SSL中断（{e}），正在进行第 {attempt + 1} 次自动修复重试...")
                time.sleep(3 * (attempt + 1)) # 指数级延迟等待

def init_and_populate_db():
    if not os.path.exists(CHUNKS_JSON):
        print(f"❌ 找不到分块数据文件：{CHUNKS_JSON}")
        return
        
    with open(CHUNKS_JSON, "r", encoding="utf-8") as f:
        chunks_data = json.load(f)
    total_chunks = len(chunks_data)
    print(f"📊 成功加载 {total_chunks} 个知识切片，准备灌入百炼向量库...")

    # 1. 初始化持久化 ChromaDB
    chroma_client = chromadb.PersistentClient(path=DB_PATH)
    dashscope_fn = DashScopeEmbeddingFunction(model_name="text-embedding-v4")
    
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=dashscope_fn,
        metadata={"hnsw:space": "cosine"}
    )
    
    # 获取数据库里现有的全部 ID 列表，实现完美断点续传
    print("🔍 正在检查数据库现有索引，启用断点续传机制...")
    try:
        existing_count = collection.count()
        print(f"💡 数据库当前已存在 {existing_count} 条记录。")
    except:
        existing_count = 0

    # 2. 批量灌库（严格遵守百炼最新要求的单次最大 10 条）
    batch_size = 10
    print(f"🚀 开始通过百炼 API 批量生成向量（每批 {batch_size} 条）...")
    
    for i in range(0, total_chunks, batch_size):
        batch = chunks_data[i:i + batch_size]
        
        # 预先计算 ID
        batch_ids = []
        for item in batch:
            text_id = item.get("id") or hashlib.md5(item["text"].encode('utf-8')).hexdigest()
            batch_ids.append(text_id)
            
        # 断点跳过逻辑
        if existing_count > 0 and (i + len(batch)) <= existing_count:
            continue

        documents = [item["text"] for item in batch]
        metadatas = [
            {k: (v if v is not None else "") for k, v in item["metadata"].items()}
            for item in batch
        ]
        
        try:
            collection.add(
                ids=batch_ids,
                documents=documents,
                metadatas=metadatas
            )
            # 适当限速，防止高频触发百炼的 RPM 限制
            time.sleep(0.1) 
            
            # 每成功写满 100 条打印一次进度，减少控制台刷屏
            if (i + len(batch)) % 100 == 0 or (i + len(batch)) == total_chunks:
                print(f"✅ 已成功同步进度: {i + len(batch)} / {total_chunks} 条 ({(i + len(batch))/total_chunks*100:.2f}%)")
                
        except Exception as e:
            print(f"\n❌ 写入批次意外中断（位置: 第 {i} 条附近）: {e}")
            print("💡 脚本已安全暂停保护。请检查终端网络。再次运行时将直接跳过已完成数据。")
            return

    print(f"\n🎉 6万+ 医疗指南知识切片全部顺利灌库完成！")
    print(f"🧮 集合 [{COLLECTION_NAME}] 最终总有效条数: {collection.count()}")

if __name__ == "__main__":
    init_and_populate_db()