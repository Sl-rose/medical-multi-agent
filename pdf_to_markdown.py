"""把本地 PDF 分批上传到 MinerU，申请转换成 Markdown。

访问令牌读取环境变量 MINERU_TOKEN。成功后的批次号写入 current_batch_list.txt。
"""
import os
import uuid
import time
import requests

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("MINERU_TOKEN", "")
PDF_FOLDER = os.getenv("GUIDELINES_SPLIT_DIR", r"D:\多智能体协作\guidelines_split")

URL_BATCH = "https://mineru.net/api/v4/file-urls/batch"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {TOKEN}"
}

def upload_all_pdfs():
    if not TOKEN:
        print("缺少环境变量 MINERU_TOKEN，请写入 .env 后再运行。")
        return
    if not os.path.exists(PDF_FOLDER):
        print(f"❌ 错误：找不到文件夹 {PDF_FOLDER}")
        return

    pdf_files = [f for f in os.listdir(PDF_FOLDER) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print("📁 文件夹中没有找到任何 PDF 文件。")
        return
    
    print(f"📁 找到 {len(pdf_files)} 个 PDF 文件，将分批申请云端上传以规避限流...")

    # ======= 【核心优化】：分批处理，每批 20 个文件 =======
    chunk_size = 20
    all_batch_ids = []

    for chunk_idx in range(0, len(pdf_files), chunk_size):
        chunk_files = pdf_files[chunk_idx:chunk_idx + chunk_size]
        print(f"\n📦 正在处理第 {chunk_idx // chunk_size + 1} 批文件（当前批次 {len(chunk_files)} 个）...")

        files_data = []
        local_file_paths = []
        
        for file_name in chunk_files:
            full_path = os.path.join(PDF_FOLDER, file_name)
            unique_id = uuid.uuid4().hex
            files_data.append({"name": file_name, "data_id": unique_id})
            local_file_paths.append(full_path)

        payload = {
            "files": files_data,
            "model_version": "vlm"
        }

        # 申请当前批次的上传 URL
        try:
            response = requests.post(URL_BATCH, headers=HEADERS, json=payload)
            if response.status_code == 429:
                print("⏳ 触发云端频率限制，脚本将自动等待 60 秒后重试此批次...")
                time.sleep(60)
                response = requests.post(URL_BATCH, headers=HEADERS, json=payload)

            if response.status_code != 200:
                print(f"❌ 申请失败，状态码: {response.status_code}, 原因: {response.text}")
                continue
                
            result = response.json()
            if result.get("code") != 0:
                print(f"❌ 业务失败，原因: {result.get('msg')}")
                continue

            batch_id = result["data"]["batch_id"]
            urls = result["data"]["file_urls"]
            all_batch_ids.append(batch_id)
            print(f"🚀 成功创建批处理任务！任务 ID: {batch_id}")

            # 上传当前批次的文件
            for i in range(len(urls)):
                file_path = local_file_paths[i]
                file_name = os.path.basename(file_path)
                print(f"  ➔ 上传 [{i+1}/{len(urls)}]: {file_name} ...")
                
                with open(file_path, 'rb') as f:
                    res_upload = requests.put(
                        urls[i], 
                        data=f, 
                        proxies={"http": None, "https": None} # 强制直连
                    )
                    if res_upload.status_code == 200:
                        print(f"  ✅ {file_name} 上传成功")
                    else:
                        print(f"  ❌ {file_name} 上传失败，状态码: {res_upload.status_code}")

            # 如果还有下一批，主动安全等待 15 秒，避免把接口压垮
            if chunk_idx + chunk_size < len(pdf_files):
                print("🛌 为避免触发 429 限流，安全等待 15 秒...")
                time.sleep(15)

        except Exception as err:
            print(f"💥 发生异常: {err}")

    # 保存所有的 batch_id
    if all_batch_ids:
        print(f"\n🎉 所有文件分批上传完毕！共生成 {len(all_batch_ids)} 个 batch_id")
        with open("current_batch_list.txt", "w", encoding="utf-8") as f_batch:
            f_batch.write("\n".join(all_batch_ids))
        print("已将所有任务 ID 记录至 current_batch_list.txt，可用于下一步的状态轮询。")

if __name__ == "__main__":
    upload_all_pdfs()