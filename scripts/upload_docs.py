#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量上传docs目录中的文档到知识库"""
import os
import sys
import requests
from pathlib import Path
import time

# 配置编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 配置
API_BASE = "http://localhost:8000"
DOCS_DIR = Path(__file__).parent.parent / "docs"

def upload_file(file_path: str) -> dict:
    """上传单个文件"""
    filename = Path(file_path).name
    print(f"[上传] {filename}...", end=" ", flush=True)

    try:
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f)}
            response = requests.post(
                f"{API_BASE}/api/ingest/file",
                files=files,
                timeout=300  # 5分钟超时
            )

        if response.status_code == 200:
            data = response.json()
            chunks = data.get('chunks', 0)
            print(f"✓ 成功 ({chunks} chunks)")
            return {"status": "success", "filename": filename, "chunks": chunks}
        else:
            print(f"✗ 失败 (HTTP {response.status_code})")
            return {"status": "error", "filename": filename, "error": response.text}

    except Exception as e:
        print(f"✗ 错误: {str(e)}")
        return {"status": "error", "filename": filename, "error": str(e)}

def main():
    """主函数"""
    print("[开始] 上传 docs 目录文件到知识库\n")
    print(f"[目录] {DOCS_DIR}\n")

    # 查找所有可上传的文件
    valid_extensions = {'.md', '.markdown', '.pdf', '.txt'}
    files_to_upload = []

    for file_path in DOCS_DIR.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in valid_extensions:
            files_to_upload.append(str(file_path))

    if not files_to_upload:
        print("[错误] 没有找到可上传的文件 (支持: .md, .pdf, .txt)")
        return

    print(f"[文件] 找到 {len(files_to_upload)} 个文件要上传:\n")
    for f in files_to_upload:
        print(f"  - {Path(f).name}")
    print()

    # 上传所有文件
    results = []
    total_chunks = 0

    for file_path in files_to_upload:
        result = upload_file(file_path)
        results.append(result)
        if result['status'] == 'success':
            total_chunks += result.get('chunks', 0)
        time.sleep(1)  # 避免API过载

    # 统计
    print("\n" + "="*50)
    print("[统计] 上传结果:")
    print("="*50)

    success_count = sum(1 for r in results if r['status'] == 'success')
    error_count = len(results) - success_count

    print(f"成功: {success_count}/{len(results)}")
    print(f"失败: {error_count}/{len(results)}")
    print(f"总chunks: {total_chunks}")

    if error_count > 0:
        print("\n[警告] 失败的文件:")
        for r in results:
            if r['status'] == 'error':
                print(f"  - {r['filename']}: {r.get('error')}")

    print("\n[完成] 上传完成！")
    print(f"[下一步] 访问 http://localhost:8501 搜索知识库内容\n")

if __name__ == "__main__":
    main()

