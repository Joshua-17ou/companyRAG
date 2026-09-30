"""
图片分析模块
用Claude Vision API分析医院SPD文档中的图片，生成描述文本
"""
import base64
import asyncio
from pathlib import Path
from typing import List, Dict, Optional

from anthropic import Anthropic

from src.backend.core.config import settings
from src.backend.core.logger import logger


class ImageAnalyzer:
    """用Claude Vision分析图片"""

    def __init__(self):
        """初始化Anthropic客户端"""
        if not settings.claude_api_key:
            logger.warning("CLAUDE_API_KEY not configured, image analysis will fail")
            self.client = None
        else:
            self.client = Anthropic(
                api_key=settings.claude_api_key,
                base_url="https://api.sandboxai.top"  # 中转站URL
            )
            logger.info("ImageAnalyzer initialized")

    def load_image_as_base64(self, image_path: str) -> Optional[str]:
        """读取图片文件并转换为base64"""
        try:
            path = Path(image_path)
            if not path.exists():
                logger.warning(f"Image file not found: {image_path}")
                return None

            with open(path, "rb") as f:
                image_data = f.read()
                base64_image = base64.standard_b64encode(image_data).decode("utf-8")
                return base64_image

        except Exception as e:
            logger.error(f"Failed to load image {image_path}: {e}")
            return None

    def get_image_media_type(self, image_path: str) -> str:
        """根据文件扩展名返回图片的MIME类型"""
        suffix = Path(image_path).suffix.lower()
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp"
        }
        return media_types.get(suffix, "image/jpeg")

    async def analyze_image(
        self,
        image_path: str,
        context: str = "这是一份医院SPD（医疗耗材供应链管理）操作指南中的图片"
    ) -> Optional[str]:
        """
        用Claude Vision分析图片，返回文本描述

        Args:
            image_path: 图片路径
            context: 图片的上下文信息

        Returns:
            图片描述文本，或None如果分析失败
        """
        if not self.client:
            logger.error("Anthropic client not initialized")
            return None

        try:
            base64_image = self.load_image_as_base64(image_path)
            if not base64_image:
                return None

            media_type = self.get_image_media_type(image_path)

            # 调用Claude Vision API
            message = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64_image
                                }
                            },
                            {
                                "type": "text",
                                "text": f"""请分析这张图片。
{context}

请用中文描述：
1. 图片展示的主要内容
2. 涉及的操作步骤或信息
3. 关键数字、字段或标注
4. 与医院SPD流程的关系

保持简洁，重点描述有助于理解医院规则的内容。"""
                            }
                        ]
                    }
                ]
            )

            description = message.content[0].text
            logger.info(f"Analyzed image: {Path(image_path).name} -> {len(description)} chars")
            return description

        except Exception as e:
            logger.error(f"Image analysis failed for {image_path}: {e}")
            return None

    async def analyze_images_batch(
        self,
        image_paths: List[str],
        context: str = "医院SPD操作指南"
    ) -> Dict[str, str]:
        """
        批量分析多张图片

        Args:
            image_paths: 图片路径列表
            context: 图片上下文

        Returns:
            {图片路径: 描述文本}
        """
        results = {}

        for image_path in image_paths:
            logger.info(f"Analyzing image: {image_path}")
            description = await self.analyze_image(image_path, context)

            if description:
                results[image_path] = description
                # 避免API速率限制
                await asyncio.sleep(1)
            else:
                logger.warning(f"Failed to analyze: {image_path}")

        return results
