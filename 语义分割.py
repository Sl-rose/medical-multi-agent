"""按标题层级切分指南 Markdown，生成 rag_chunks.json。

先按 Markdown 标题切开，再按段落和句号控制每块长度，供向量库入库。
"""
import os
import json
import re
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# ================= 配置区域 =================
MD_DIR = r"D:\多智能体协作\guidelines_md"          # 你的纯净 Markdown 目录
OUTPUT_JSON = r"D:\多智能体协作\rag_chunks.json"    # 切块后的结构化输出

CHUNK_SIZE = 600      # 每个切块的最大字符数（包含父级上下文前缀）
CHUNK_OVERLAP = 120   # 两个相邻切块的重叠字数
# ============================================

def process_medical_guidelines():
    # 1. 定义 Markdown 标题层级捕获规则
    headers_to_split_on = [
        ("#", "h1"),
        ("##", "h2"),
        ("###", "h3"),
        ("####", "h4"),
    ]
    
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on, 
        strip_headers=False  # 保留文本内部的标题符号，维持原有可读性
    )
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""]  # 优先在段落和句号处截断
    )

    all_chunks = []
    chunk_counter = 0

    print("🚀 开始对医学指南进行层级语义分块...")
    
    # 遍历文件夹
    for root, dirs, files in os.walk(MD_DIR):
        for file in files:
            if not file.lower().endswith('.md'):
                continue
                
            file_path = os.path.join(root, file)
            # 从路径或文件名中提取分册名称（如：呼吸科学分册）
            book_name = os.path.basename(os.path.dirname(file_path))
            if book_name == os.path.basename(MD_DIR) or not book_name:
                book_name = file.replace(".md", "")
            
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    md_content = f.read()
                
                # 步骤 A: 先按 Markdown 标题将大文件切成“章节语义块”
                header_sections = header_splitter.split_text(md_content)
                
                # 步骤 B: 遍历每个章节，在内部进行带 Overlap 的细粒度切块
                for section in header_sections:
                    # 提取当前章节捕获到的层级元数据
                    h1 = section.metadata.get("h1", "")
                    h2 = section.metadata.get("h2", "")
                    h3 = section.metadata.get("h3", "")
                    h4 = section.metadata.get("h4", "")
                    
                    # 核心创新：构建上下文前缀（Context Prefix）
                    # 当大模型单独检索到这一块时，能瞬间知道这是“呼吸分册-第三章-肺炎-诊断标准”
                    context_prefix = f"【来源】{book_name}"
                    if h1: context_prefix += f" -> {h1}"
                    if h2: context_prefix += f" -> {h2}"
                    if h3: context_prefix += f" -> {h3}"
                    if h4: context_prefix += f" -> {h4}"
                    context_prefix += "\n【正文】\n"
                    
                    # 计算前缀长度，动态扣除切块可用空间
                    available_size = CHUNK_SIZE - len(context_prefix)
                    if available_size < 100:
                        # 防止标题太长导致正文没空间，设置保底
                        available_size = 300 
                        
                    # 调整内部切片器的尺寸
                    text_splitter._chunk_size = available_size
                    text_splitter._chunk_overlap = CHUNK_OVERLAP
                    
                    # 进行带重叠的子切块
                    sub_chunks = text_splitter.split_text(section.page_content)
                    
                    for sub_text in sub_chunks:
                        # 拼接上下文前缀与子切块正文
                        final_content = context_prefix + sub_text.strip()
                        
                        # 构造最终写入向量库的数据结构
                        chunk_data = {
                            "id": f"chunk_{chunk_counter:06d}",
                            "text": final_content,
                            "metadata": {
                                "book": book_name,
                                "h1": h1,
                                "h2": h2,
                                "h3": h3,
                                "h4": h4,
                                "length": len(final_content)
                            }
                        }
                        all_chunks.append(chunk_data)
                        chunk_counter += 1
                        
            except Exception as e:
                print(f"❌ 处理文件失败 {file}: {e}")

    # 3. 持久化存储为 JSON 缓存
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
        
    print(f"\n🎉 分块圆满完成！")
    print(f"📊 总共生成知识切片（Chunks）: {len(all_chunks)} 个")
    print(f"💾 数据已安全保存在: {OUTPUT_JSON}")

if __name__ == "__main__":
    process_medical_guidelines()