"""从已下载的指南压缩包中抽出 Markdown，并按书名保存。

用于补救 download_markdown.py 解压后目录层级混乱、文件名容易覆盖的情况。
"""
import os
import zipfile

# ================= 配置区域 =================
# 1. 请修改为存放你下载的 .zip 压缩包的真实路径
ZIP_DIR = r"D:\多智能体协作\guidelines_md_zips"  

# 2. Markdown 最终存放的目录
MD_DIR = r"D:\多智能体协作\guidelines_md"
# ============================================

def rescue_markdowns():
    os.makedirs(MD_DIR, exist_ok=True)
    
    zip_files = [f for f in os.listdir(ZIP_DIR) if f.endswith('.zip')]
    if not zip_files:
        print(f"❌ 在 {ZIP_DIR} 没找到任何 ZIP 压缩包！请检查路径。")
        return

    print(f"🔍 找到 {len(zip_files)} 个压缩包，开始精准提取并重命名...")
    
    success_count = 0
    
    for zip_name in zip_files:
        zip_path = os.path.join(ZIP_DIR, zip_name)
        # 书名就是压缩包去掉 .zip 的名字
        book_name = zip_name.replace('.zip', '')
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                # 遍历压缩包里的所有文件
                md_found = False
                for member_info in z.infolist():
                    # 寻找以 .md 结尾的文件
                    if member_info.filename.lower().endswith('.md'):
                        # 直接把文件内容读进内存（忽略原有的层级目录结构）
                        content = z.read(member_info.filename)
                        
                        # 核心：使用书名重新命名，避免覆盖！
                        new_md_path = os.path.join(MD_DIR, f"{book_name}.md")
                        
                        # 写出到 guidelines_md 文件夹
                        with open(new_md_path, 'wb') as f:
                            f.write(content)
                        
                        print(f"✅ 提取成功: {book_name}.md")
                        md_found = True
                        success_count += 1
                        break  # 每本书只提取核心的 MD 文件即可跳出
                
                if not md_found:
                    print(f"⚠️ 警告: 压缩包 {zip_name} 中未找到 Markdown 文件。")
                    
        except Exception as e:
            print(f"❌ 解压 {zip_name} 失败: {e}")

    print(f"\n🎉 抢救完成！成功提取了 {success_count} 本独立的 Markdown 指南。")
    print(f"📂 快去 {MD_DIR} 看看是不是都有了！")

if __name__ == "__main__":
    rescue_markdowns()