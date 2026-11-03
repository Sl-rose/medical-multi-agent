"""把超过上传页数限制的指南 PDF 切成较小文件。

只处理名单中的超限文件，输出到 guidelines_split，供后续云端转 Markdown。
"""
import os
from pypdf import PdfReader, PdfWriter

# ================= 配置区域 =================
# 包含那 30 个被拒绝 PDF 的原始目录
INPUT_DIR = r"D:\多智能体协作\临床诊疗指南"  
# 切分后用来准备重新上传的目录
OUTPUT_DIR = r"D:\多智能体协作\guidelines_split" 
# 每个切片的最大页数（设为 150 页，避开 200 页红线且给云端留足解析Buffer）
STEP = 150 
# ============================================

# 刚才被拒的 30 个文件名列表（用于精准过滤，防止处理到不需要的文件）
FAILED_FILES = [
    "临床诊疗指南 — 传染病学分册.pdf", "临床诊疗指南 — 免疫学分册.pdf", "临床诊疗指南 — 外科学分册.pdf",
    "临床诊疗指南 — 妇产科学分册.pdf", "临床诊疗指南 — 小儿内科分册.pdf", "临床诊疗指南 — 小儿外科学分册.pdf",
    "临床诊疗指南 — 急诊医学分册.pdf", "临床诊疗指南 — 整形外科学分册.pdf", "临床诊疗指南 — 烧伤外科学分册.pdf",
    "临床诊疗指南 — 物理医学与康复分册.pdf", "临床诊疗指南 — 疼痛学分册.pdf", "临床诊疗指南 — 病理学分册.pdf",
    "临床诊疗指南 — 皮肤病与性病分册.pdf", "临床诊疗指南 — 眼科学分册.pdf", "临床诊疗指南 — 神经病学分册.pdf",
    "临床诊疗指南 — 美容医学分册.pdf", "临床诊疗指南 — 耳鼻咽喉头颈外科分册.pdf", "临床诊疗指南 — 肾脏病学分册.pdf",
    "临床诊疗指南 — 肿瘤分册.pdf", "临床诊疗指南 — 骨科分册.pdf", "临床诊疗指南 器官移植学分册_陈实著.pdf",
    "临床诊疗指南 辅助生殖技术与精子库分册_黄....pdf", "临床诊疗指南_创伤学分册2007.pdf", "临床诊疗指南_口腔医学分册.pdf",
    "临床诊疗指南_护理学分册.PDF", "临床诊疗指南_护理学分册_1026155918.PDF", "临床诊疗指南_放射学检查技术分册.pdf",
    "临床诊疗指南_核医学分册.PDF", "临床诊疗指南_神经外科学分册.pdf", "临床诊疗指南_重症医学分册.PDF"
]

def split_pdf(file_path, output_dir, step=150):
    file_name = os.path.basename(file_path)
    base_name, ext = os.path.splitext(file_name)
    
    try:
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        print(f"📖 正在处理: {file_name} (总计 {total_pages} 页)")
        
        if total_pages <= step:
            print(f"ℹ️ 该文件其实未超限，直接复制...")
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            with open(os.path.join(output_dir, file_name), "wb") as f:
                writer.write(f)
            return

        part_num = 1
        for start_page in range(0, total_pages, step):
            end_page = min(start_page + step, total_pages)
            writer = PdfWriter()
            
            # 抽取指定范围的页面
            for page_idx in range(start_page, end_page):
                writer.add_page(reader.pages[page_idx])
            
            # 生成带后缀的新文件名
            split_file_name = f"{base_name}_part{part_num}{ext}"
            output_path = os.path.join(output_dir, split_file_name)
            
            with open(output_path, "wb") as f:
                writer.write(f)
            
            print(f"   └─ 💾 已生成切片: {split_file_name} (第 {start_page+1} 至 {end_page} 页)")
            part_num += 1
            
    except Exception as e:
        print(f"❌ 切分文件 {file_name} 时出错: {e}")

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 模糊匹配处理，防止列表中带省略号的文件名导致找不到文件
    all_files = os.listdir(INPUT_DIR)
    target_paths = []
    
    for f in all_files:
        # 去除扩展名进行前缀匹配，解决像 "辅助生殖技术与精子库分册_黄....pdf" 的匹配问题
        short_name = os.path.splitext(f)[0][:10] 
        if any(short_name in failed for failed in FAILED_FILES):
            target_paths.append(os.path.join(INPUT_DIR, f))
            
    print(f"🎯 识别到 {len(target_paths)} 个待切分的超限 PDF 文件。开始切分...")
    
    for path in target_paths:
        split_pdf(path, OUTPUT_DIR, STEP)
        
    print("\n🎉 所有超限文件切分完毕！请前往 `guidelines_split` 目录查看结果。")

if __name__ == "__main__":
    main()