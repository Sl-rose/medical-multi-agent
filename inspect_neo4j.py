"""查看本地 Neo4j 里已导入的标签、关系和疾病节点字段。

连接信息读取 NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD，用于核对图谱是否导入成功。
"""
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

def inspect_database():
    print("🔍 正在连接 Neo4j 数据库进行结构探查...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            
            # 1. 查一下有哪些节点标签，以及各自的数量
            print("\n📊 --- [节点标签与分布] ---")
            labels_query = "CALL db.labels() YIELD label RETURN label"
            labels_result = session.run(labels_query)
            for record in labels_result:
                label = record["label"]
                count_query = f"MATCH (n:{label}) RETURN count(n) as count"
                count_res = session.run(count_query).single()
                print(f"  • 标签名: {label:<12} | 节点总数: {count_res['count']}")

            # 2. 查一下前 10 个关系类型
            print("\n🔗 --- [图谱关系类型] ---")
            rel_query = "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType LIMIT 10"
            rel_result = session.run(rel_query)
            for record in rel_result:
                print(f"  • 关系名: {record['relationshipType']}")

            # 3. 抽样看一个 Disease 节点，看看它的属性长啥样（字段名对齐）
            print("\n📝 --- [节点属性字段抽样 (Disease)] ---")
            sample_query = "MATCH (d:Disease) RETURN d LIMIT 1"
            sample_result = session.run(sample_query).single()
            if sample_result:
                node = sample_result["d"]
                print(f"  • 成功抽样到节点 ID: {node.id}")
                print(f"  • 包含的属性字段: {list(node.keys())}")
                print(f"  • 数据样例: {dict(node)}")
            else:
                print("  ⚠️ 图中没有找到 Disease 节点，可能使用了不同的标签名。")

        driver.close()
    except Exception as e:
        print(f"❌ 连接或查询 Neo4j 失败: {e}")

if __name__ == "__main__":
    inspect_database()