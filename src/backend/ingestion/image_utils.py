"""
增强的搜索和问答模块，支持图片返回
"""
from typing import List, Dict, Optional
from pathlib import Path


def extract_images_from_metadata(metadata: dict, docs_dir: str = "docs") -> List[Dict]:
    """
    从metadata中提取图片信息
    返回可直接渲染的图片信息列表
    """
    images = []

    # 检查是否有图片路径
    if "image_paths" in metadata:
        image_paths = metadata["image_paths"]
        if isinstance(image_paths, str):
            image_paths = [image_paths]

        for img_path in image_paths:
            # 标准化路径
            if not img_path.startswith("images/"):
                img_path = f"images/{img_path}"

            images.append({
                "path": img_path,
                "hospital": metadata.get("hospital", "未知医院"),
                "chunk_index": metadata.get("hospital_chunk_index", 0),
                "url": f"/docs/{img_path}"  # 前端可用的URL
            })

    return images


def format_search_result_with_images(node, index: int) -> Dict:
    """
    格式化搜索结果，包含图片信息
    """
    metadata = node.metadata if hasattr(node, "metadata") else {}

    # 提取图片
    images = extract_images_from_metadata(metadata)

    result = {
        "rank": index,
        "text": node.get_content() if hasattr(node, "get_content") else str(node),
        "score": node.score if hasattr(node, "score") else 0.0,
        "hospital": metadata.get("hospital", "未知医院"),
        "metadata": {
            "file_id": metadata.get("file_id", ""),
            "chunk_index": metadata.get("chunk_index", 0),
            "total_chunks": metadata.get("total_chunks", 0),
            "hospital_chunk_index": metadata.get("hospital_chunk_index", 0),
        },
        "images": images  # ✓ 图片信息
    }

    return result
