"""把 medical.json 中的疾病记录批量写入 Neo4j。

文件为每行一个 JSON 对象。连接账号读取环境变量，不在代码中保存密码。
"""
import json
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

FILE_PATH = os.getenv("MEDICAL_JSON_PATH", "medical.json")
URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
AUTH = (
    os.getenv("NEO4J_USER", "neo4j"),
    os.getenv("NEO4J_PASSWORD", ""),
)

def batch_load_to_neo4j(file_path):
# 1. 改为按行读取 JSONLines 格式文件
    print(f"正在读取文件: {file_path} ...")
    data_list = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue  # 跳过空行
            try:
                # 逐行解析 JSON 对象并加入列表
                data_list.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"警告: 第 {line_num} 行解析失败，已跳过。错误原因: {e}")
                
    print(f"成功加载数据，共包含 {len(data_list)} 条疾病记录。")

    # 2. 初始化 Neo4j 驱动
    driver = GraphDatabase.driver(URI, auth=AUTH)
    
    # 3. 编写高效的批量 Cypher 语句 (利用 UNWIND 批量处理)
    # 这样可以减少 Python 与 Neo4j 之间的网络往返次数
    cypher_query = """
    UNWIND $batch AS item
    // 1. 创建或更新疾病核心节点
    MERGE (d:Disease {name: item.name})
    SET d.desc = coalesce(item.desc, ''),
        d.prevent = coalesce(item.prevent, ''),
        d.cause = coalesce(item.cause, ''),
        d.cured_prob = coalesce(item.cured_prob, ''),
        d.cost_money = coalesce(item.cost_money, '')
    
    // 2. 批量处理症状关系
    FOREACH (sym_name IN item.symptom |
        MERGE (s:Symptom {name: sym_name})
        MERGE (d)-[:HAS_SYMPTOM]->(s)
    )
    
    // 3. 批量处理并发症关系
    FOREACH (ac_name IN item.acompany |
        MERGE (ac:Disease {name: ac_name})
        MERGE (d)-[:ACCOMPANY_WITH]->(ac)
    )
    
    // 4. 批量处理科室关系
    FOREACH (dept_name IN item.cure_department |
        MERGE (dept:Department {name: dept_name})
        MERGE (d)-[:CURE_BY_DEPT]->(dept)
    )
    
    // 5. 批量处理检查项目关系
    FOREACH (chk_name IN item.check |
        MERGE (chk:Check {name: chk_name})
        MERGE (d)-[:NEED_CHECK]->(chk)
    )
    
    // 6. 批量处理推荐用药关系
    FOREACH (drug_name IN item.recommand_drug |
        MERGE (drug:Drug {name: drug_name})
        MERGE (d)-[:RECOMMEND_DRUG]->(drug)
    )
    
    // 7. 批量处理食物宜忌
    FOREACH (food_do IN item.do_eat |
        MERGE (f1:Food {name: food_do})
        MERGE (d)-[:DO_EAT]->(f1)
    )
    FOREACH (food_not IN item.not_eat |
        MERGE (f2:Food {name: food_not})
        MERGE (d)-[:NOT_EAT]->(f2)
    )
    """

    # 4. 分批次（Chunk）写入数据库，防止大文件撑爆内存
    batch_size = 500  # 每 500 条疾病数据为一个批次提交一次
    
    with driver.session() as session:
        # 在写入前，强烈建议先为 name 属性建立约束（确保唯一性并极大提升 MERGE 性能）
        try:
            session.run("CREATE CONSTRAINT disease_name_idx FOR (d:Disease) REQUIRE d.name IS UNIQUE")
            session.run("CREATE CONSTRAINT symptom_name_idx FOR (s:Symptom) REQUIRE s.name IS UNIQUE")
            print("已成功创建或确认节点唯一性索引。")
        except Exception:
            # 如果索引已存在会报错，直接忽略即可
            pass

        print("开始向 Neo4j 写入数据...")
        for i in range(0, len(data_list), batch_size):
            chunk = data_list[i:i + batch_size]
            
            # 使用新版推荐的显式事务上下文
            with session.begin_transaction() as tx:
                tx.run(cypher_query, batch=chunk)
                tx.commit()  # 显式提交事务
                
            print(f"进度: 已处理 {i + len(chunk)} / {len(data_list)} 条疾病记录。")
            
            # 执行批量事务
            # 正确的新版本写法
            session.execute_write(lambda tx: tx.run(cypher_query, batch=chunk))
            print(f"进度: 已处理 {i + len(chunk)} / {len(data_list)} 条疾病记录。")

    driver.close()
    print("🎉 知识图谱数据导入成功！")

if __name__ == "__main__":
    batch_load_to_neo4j(FILE_PATH)