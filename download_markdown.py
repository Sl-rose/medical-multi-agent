"""按 MinerU 批次号下载已转换的指南压缩包，并解压为 Markdown。

访问令牌读取环境变量 MINERU_TOKEN。批次号写在 BATCH_IDS 中。
"""
import os
import time
import zipfile
import requests

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("MINERU_TOKEN", "")
DOWNLOAD_DIR = os.getenv("GUIDELINES_ZIP_DIR", r"D:\多智能体协作\guidelines_md_zips")
EXTRACT_DIR = os.getenv("GUIDELINES_MD_DIR", r"D:\多智能体协作\guidelines_md")

BATCH_IDS = [
    "2b427e37-9ef1-48ac-8bf5-55f8cadba94a",
    "afe5a23a-6525-492f-bb4c-e41999c2a0ac",
    "6428a65a-8b0e-4292-8e7b-415974623257",
    "da7519f5-1fd1-4fa7-a97e-d9781c712b79",
    "f3acc321-0acc-4454-858f-83f899b7e213"
]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}"
}

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)

def download_and_extract_file(url, file_name):
    """下载单个文件的zip并解压"""
    # 过滤掉文件名中的非法字符用于安全保存
    safe_name = "".join([c for c in file_name if c.isalpha() or c.isdigit() or c in (' ', '_', '-')]).rstrip()
    zip_path = os.path.join(DOWNLOAD_DIR, f"{safe_name}.zip")
    
    print(f"📥 正在下载: {file_name}...")
    try:
        res = requests.get(url, stream=True, proxies={"http": None, "https": None})
        if res.status_code == 200:
            with open(zip_path, 'wb') as f:
                for chunk in res.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # 解压
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(EXTRACT_DIR)
            print(f"📂 成功解压: {file_name} -> 到 guidelines_md 目录")
            return True
        else:
            print(f"❌ 下载失败: {file_name}, 状态码: {res.status_code}")
    except Exception as e:
        print(f"💥 处理 {file_name} 时发生异常: {e}")
    return False

def start_harvest():
    if not TOKEN:
        print("缺少环境变量 MINERU_TOKEN，请写入 .env 后再运行。")
        return
    print("🚀 开始检索并收网已转换成功的临床指南文档...")
    failed_due_to_limit = []
    
    for batch_id in BATCH_IDS:
        url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
        try:
            response = requests.get(url, headers=HEADERS, proxies={"http": None, "https": None})
            if response.status_code != 200:
                print(f"❌ 无法读取批次 [{batch_id[:8]}]")
                continue
                
            result = response.json()
            file_list = result.get("data", {}).get("extract_result", [])
            
            for file_info in file_list:
                f_name = file_info.get("file_name")
                state = file_info.get("state")
                err_msg = file_info.get("err_msg", "")
                
                if state == "done":
                    download_url = file_info.get("full_zip_url")
                    if download_url:
                        download_and_extract_file(download_url, f_name)
                elif "exceeds limit" in err_msg:
                    if f_name not in failed_due_to_limit:
                        failed_due_to_limit.append(f_name)
                        
        except Exception as e:
            print(f"💥 请求批次时出错 [{batch_id[:8]}]: {e}")
            
    print("\n================== 收网报告 ==================")
    print(f"✅ 成功下载并解压了所有已就绪的 Markdown 成果！")
    print(f"⚠️ 以下 {len(failed_due_to_limit)} 个文件因超过 200 页被云端拒绝:")
    for f in failed_due_to_limit:
        print(f"   - {f}")
    print("==============================================")

if __name__ == "__main__":
    start_harvest()