"""
医院级别的文档分割器
按医院（## 标题）来分割文档，而不是固定字符数
支持处理图片标记和生成图片描述
"""
import re
from typing import List, Dict, Optional
from pathlib import Path
from llama_index.core.schema import Document, TextNode, NodeRelationship, RelatedNodeInfo
from src.backend.ingestion.hospital_mapping import normalize_hospital_name


class HospitalDocumentParser:
    """按医院边界分割文档的解析器"""

    # 医院标题的正则表达式（二级标题 ## ）
    HOSPITAL_PATTERN = re.compile(r'^## (.+)$', re.MULTILINE)

    # 图片标记的正则表达式 ![alt](url) 或 ![alt](path/to/image)
    IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')

    @staticmethod
    def extract_images(text: str) -> tuple:
        """
        从文本中提取图片信息
        返回：(清理后的文本, [{"alt": "...", "path": "...", "description": "..."}, ...])
        """
        images = []

        def replace_image(match):
            alt_text = match.group(1)
            image_path = match.group(2)
            images.append({
                "alt": alt_text if alt_text else "图片",
                "path": image_path,
                "description": None  # 后续由image_analyzer填充
            })
            # 用文本提示替代图片标记
            return f"\n[图片: {alt_text or image_path}]\n"

        # 替换所有图片标记
        cleaned_text = HospitalDocumentParser.IMAGE_PATTERN.sub(replace_image, text)

        return cleaned_text, images

    @staticmethod
    def split_by_hospital(text: str) -> List[Dict]:
        """
        按医院标题分割文本
        返回：[{"hospital": "医院名", "content": "内容", "images": [...]}, ...]
        """
        sections = []
        current_hospital = None
        current_content = []

        for line in text.split('\n'):
            # 检查是否是医院标题行
            match = re.match(HospitalDocumentParser.HOSPITAL_PATTERN, line)

            if match:
                # 如果已有前一个医院，保存它
                if current_hospital:
                    content_text = '\n'.join(current_content).strip()
                    # 从内容中提取图片
                    cleaned_content, images = HospitalDocumentParser.extract_images(content_text)

                    sections.append({
                        "hospital": current_hospital,
                        "content": content_text,
                        "images": images
                    })

                # 开始新医院
                current_hospital = normalize_hospital_name(match.group(1))
                current_content = [line]  # 保留标题行
            else:
                if current_hospital:  # 只在有医院的情况下收集内容
                    current_content.append(line)

        # 保存最后一个医院
        if current_hospital:
            content_text = '\n'.join(current_content).strip()
            # 从内容中提取图片
            cleaned_content, images = HospitalDocumentParser.extract_images(content_text)

            sections.append({
                "hospital": current_hospital,
                "content": content_text,
                "images": images
            })

        return sections

    @staticmethod
    def split_hospital_content(hospital_content: str, chunk_size: int = 512, chunk_overlap: int = 50) -> List[str]:
        """
        在医院内部按字符数进一步切分内容
        这样可以保持医院的完整性，同时处理很长的医院规则
        """
        chunks = []
        content = hospital_content.strip()
        if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_overlap must be nonnegative and smaller than chunk_size")

        if len(content) <= chunk_size:
            return [content]

        image_spans = [match.span() for match in HospitalDocumentParser.IMAGE_PATTERN.finditer(content)]
        start = 0
        while start < len(content):
            end = min(start + chunk_size, len(content))
            for image_start, image_end in image_spans:
                if image_start < end < image_end:
                    end = image_end
            chunk = content[start:end]
            if chunk.strip():
                chunks.append(chunk)

            # 如果是最后一个块，退出
            if end >= len(content):
                break
            next_start = max(start + 1, end - chunk_overlap)
            for image_start, image_end in image_spans:
                if image_start < next_start < image_end:
                    next_start = image_start if image_start > start else image_end
            start = next_start

        return chunks

    @staticmethod
    def parse_documents_by_hospital(
        documents: List[Document],
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        image_descriptions: Optional[Dict[str, str]] = None
    ) -> List[TextNode]:
        """
        将文档按医院边界分割，然后创建TextNode

        Args:
            documents: LlamaIndex Document列表
            chunk_size: 单个医院内容块的最大字符数
            chunk_overlap: 块之间的重叠字符数
            image_descriptions: {图片路径: 描述文本} 的字典

        Returns:
            TextNode列表，每个node代表一个医院的一部分
        """
        nodes = []
        node_id = 0
        image_descriptions = image_descriptions or {}

        for doc in documents:
            text = doc.text

            # 第一步：按医院分割
            hospital_sections = HospitalDocumentParser.split_by_hospital(text)

            # 第二步：遍历每个医院
            for section in hospital_sections:
                hospital_name = section["hospital"]
                hospital_content = section["content"]
                images = section["images"]

                # 增强图片信息：添加描述
                for img in images:
                    img_path = img["path"]
                    if img_path in image_descriptions:
                        img["description"] = image_descriptions[img_path]

                final_content = HospitalDocumentParser.IMAGE_PATTERN.sub(
                    lambda match: match.group(0) + (
                        f"\n[图片说明: {image_descriptions[match.group(2)]}]"
                        if image_descriptions.get(match.group(2)) else ""
                    ),
                    hospital_content
                )

                # 第三步：在医院内按字符数切分
                chunks = HospitalDocumentParser.split_hospital_content(
                    final_content,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap
                )

                # 第四步：为每个chunk创建TextNode
                for chunk_idx, chunk in enumerate(chunks):
                    # 保留原文档的metadata
                    metadata = doc.metadata.copy() if doc.metadata else {}

                    # 添加医院相关的metadata
                    _, chunk_images = HospitalDocumentParser.extract_images(chunk)
                    metadata.update({
                        "hospital": hospital_name,
                        "hospital_chunk_index": chunk_idx,
                        "hospital_total_chunks": len(chunks),
                        "has_images": len(chunk_images) > 0,
                        "image_count": len(chunk_images)
                    })

                    # 添加图片路径信息到metadata
                    metadata["image_paths"] = [img["path"] for img in chunk_images]

                    # 创建node
                    node = TextNode(
                        text=chunk,
                        metadata=metadata,
                        relationships={NodeRelationship.SOURCE: RelatedNodeInfo(node_id=doc.doc_id)}
                    )
                    nodes.append(node)
                    node_id += 1

        return nodes
