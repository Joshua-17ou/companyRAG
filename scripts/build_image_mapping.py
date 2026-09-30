#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
构建图片URL到本地文件的映射表
根据ProcessOn的CDN链接格式匹配本地图片
"""
import os
import sys
import json
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def build_image_mapping():
    """构建图片映射"""
    project_root = Path(__file__).parent.parent
    images_dir = project_root / "docs" / "images"

    if not images_dir.exists():
        print(f"[错误] 图片目录不存在: {images_dir}")
        return {}

    # 获取所有本地图片
    local_images = {}
    for img_file in images_dir.glob("*.png"):
        # 提取文件ID（去掉.png后缀）
        file_id = img_file.stem
        # ProcessOn CDN URL格式
        cdn_url = f"https://tc-cdn.processon.com/wps/{file_id}"
        local_images[cdn_url] = str(img_file.relative_to(project_root))

    print(f"[成功] 找到 {len(local_images)} 个本地图片映射")
    return local_images

if __name__ == "__main__":
    mapping = build_image_mapping()
    # 保存为JSON供前端使用
    output_file = Path(__file__).parent.parent / ".image_mapping.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"[成功] 映射表已保存到: {output_file}")

