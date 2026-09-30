"""
图片链接对照表映射模块
负责加载和管理图片ID与章节描述的映射关系
"""
import re
import asyncio
from typing import Dict, Optional, List
from pathlib import Path

from src.backend.core.logger import logger


class ImageMapper:
    """图片映射管理器 - 单例模式"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ImageMapper, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not ImageMapper._initialized:
            self.image_map: Dict[str, Dict] = {}
            self._load_image_mapping()
            ImageMapper._initialized = True

    def _load_image_mapping(self) -> None:
        """从图片链接对照表.md加载映射"""
        try:
            table_path = Path(__file__).parent.parent.parent.parent / "docs" / "图片链接对照表.md"

            if not table_path.exists():
                logger.warning(f"Image mapping table not found: {table_path}")
                return

            logger.info(f"Loading image mapping from: {table_path}")

            with open(table_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 解析Markdown表格
            self._parse_image_table(content)
            logger.info(f"✓ Image mapper initialized with {len(self.image_map)} images")

        except Exception as e:
            logger.error(f"Failed to load image mapping: {e}", exc_info=True)

    def _parse_image_table(self, content: str) -> None:
        """解析Markdown表格，提取图片映射"""
        # 匹配表格行：| 序号 | 图片文件 | 所属章节 | 原始链接 |
        # 例如：| 1 | `images/692ea35fe7be6c03a7e182e9.png` | 医院SPD > 和祐医院 > 查看待接收订单 | [查看原图](https://...) |

        lines = content.split('\n')
        table_started = False

        for line in lines:
            # 跳过表头和分隔线
            if '序号' in line or '---|' in line or line.strip() == '':
                continue

            # 匹配表格数据行
            if line.startswith('|'):
                table_started = True
                cells = [cell.strip() for cell in line.split('|')[1:-1]]

                if len(cells) < 3:
                    continue

                try:
                    # 提取字段
                    seq_num = cells[0].strip()
                    image_file = cells[1].strip()  # 如：`images/692ea35fe7be6c03a7e182e9.png`
                    section_desc = cells[2].strip()  # 如：医院SPD > 和祐医院 > 查看待接收订单
                    original_link = cells[3].strip() if len(cells) > 3 else ""

                    # 提取图片ID
                    image_id = self._extract_image_id(image_file)

                    if image_id:
                        self.image_map[image_id] = {
                            "file": image_file.strip('`'),
                            "section": section_desc,
                            "original_link": original_link,
                            "seq": seq_num
                        }

                except Exception as e:
                    logger.debug(f"Failed to parse table row: {line}, error: {e}")
                    continue

        logger.info(f"Parsed {len(self.image_map)} images from mapping table")

    @staticmethod
    def _extract_image_id(image_file: str) -> Optional[str]:
        """从图片文件名提取ID

        例如：
        - `images/692ea35fe7be6c03a7e182e9.png` → 692ea35fe7be6c03a7e182e9
        - images/692ea35fe7be6c03a7e182e9.png → 692ea35fe7be6c03a7e182e9
        - /api/images/692ea35fe7be6c03a7e182e9.png → 692ea35fe7be6c03a7e182e9
        """
        # 移除反引号和路径前缀
        image_file = image_file.strip('`')

        # 提取文件名（去掉路径和扩展名）
        # 支持多种格式的图片ID（24个十六进制字符）
        match = re.search(r'([a-f0-9]{24})', image_file)
        if match:
            return match.group(1)

        return None

    def get_image_info(self, image_id: str) -> Optional[Dict]:
        """根据图片ID获取完整信息

        Args:
            image_id: 图片ID（如：692ea35fe7be6c03a7e182e9）

        Returns:
            {
                "id": "692ea35fe7be6c03a7e182e9",
                "url": "/api/images/692ea35fe7be6c03a7e182e9.png",
                "file": "images/692ea35fe7be6c03a7e182e9.png",
                "section": "医院SPD > 和祐医院 > 查看待接收订单",
                "description": "查看待接收订单"  # section 的最后一部分
            }
        """
        if image_id not in self.image_map:
            return None

        info = self.image_map[image_id]

        # 提取最后一级的描述（如：查看待接收订单）
        section_parts = info['section'].split(' > ')
        description = section_parts[-1] if section_parts else "图片"

        return {
            "id": image_id,
            "url": f"/api/images/{image_id}.png",
            "file": info['file'],
            "section": info['section'],
            "description": description,
            "seq": info['seq']
        }

    def get_images_by_section(self, section_keyword: str) -> List[Dict]:
        """根据章节关键词查找相关的所有图片

        Args:
            section_keyword: 章节关键词（如：和祐医院、出库单等）

        Returns:
            匹配的图片列表
        """
        results = []

        for image_id, info in self.image_map.items():
            if section_keyword.lower() in info['section'].lower():
                results.append(self.get_image_info(image_id))

        return results

    def enrich_images(self, images: List[Dict]) -> List[Dict]:
        """丰富图片信息 - 添加章节描述

        Args:
            images: 原始图片列表，包含 url 或 id 字段

        Returns:
            丰富后的图片列表，包含 section 和 description
        """
        enriched = []

        for img in images:
            # 尝试从 URL 或 ID 中提取图片ID
            image_id = None

            if 'url' in img:
                # 从 URL 提取 ID（支持各种格式）
                # /api/images/695df082243f3955673c1bd8.png → 695df082243f3955673c1bd8
                match = re.search(r'([a-f0-9]{24})', img['url'])
                if match:
                    image_id = match.group(1)

            elif 'id' in img:
                image_id = img['id']

            # 查找映射信息
            if image_id:
                info = self.get_image_info(image_id)
                if info:
                    # 合并原始信息和映射信息
                    enriched_img = {**img, **info}
                    enriched.append(enriched_img)
                    logger.debug(f"Enriched image {image_id}: {info.get('description')}")
                else:
                    # 没找到映射，使用原始图片信息
                    enriched.append(img)
            else:
                enriched.append(img)

        return enriched


# 全局实例
image_mapper = ImageMapper()


async def enrich_images_async(images: List[Dict]) -> List[Dict]:
    """异步版本的图片信息丰富

    Args:
        images: 原始图片列表

    Returns:
        丰富后的图片列表
    """
    # 由于图片映射已在启动时加载，这里直接调用同步版本即可
    return await asyncio.get_event_loop().run_in_executor(
        None,
        image_mapper.enrich_images,
        images
    )
