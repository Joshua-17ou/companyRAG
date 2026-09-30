"""
LlamaIndex RAG服务 - 完整可用版本
文档入库 → 搜索 → 生成答案
"""
from typing import List, Dict, Optional
from pathlib import Path
import asyncio
import hashlib
import re
import os
from uuid import uuid4
from datetime import datetime

from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings, Document
from llama_index.core.embeddings import BaseEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.llms.anthropic import Anthropic as AnthropicLLM
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from sentence_transformers import SentenceTransformer
from modelscope import snapshot_download

from src.backend.core.config import settings
from src.backend.core.logger import logger
from src.backend.ingestion.image_mapper import image_mapper
from src.backend.agent.intent_agent import IntentAgent  # 新增：使用 IntentAgent
from src.backend.agent.prompts import ANSWER_GENERATION_PROMPT
from src.backend.ingestion.hospital_filter import HospitalFilter
from src.backend.ingestion.hospital_mapping import normalize_hospital_name, find_hospital_in_text, HOSPITAL_MAPPING
from src.backend.ingestion.chat_fallback import NO_RESULTS, greeting_answer, source_excerpt_answer
from src.backend.ingestion.answer_model import AnswerDiagnostics, deepseek_answer_chunks
from src.backend.ingestion.chunking import (
    ParserContext,
    build_chunk_config,
    split_document,
)
from src.backend.ingestion.scanned_pdf_ocr import (
    ScannedPdfProcessor,
    detect_text_layer,
)
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters


def parse_filename_permissions(filename: str) -> dict:
    """
    从文件名解析权限信息和文档类型

    Args:
        filename: 例如 "销售_手册_产品功能.md"

    Returns:
        {
            "owner_dept": "销售",
            "doc_type": "手册"  # 新增：文档类型
        }
    """
    # 移除扩展名
    name_without_ext = filename.rsplit('.', 1)[0] if '.' in filename else filename

    # 按 _ 分割
    parts = name_without_ext.split('_')

    if len(parts) < 1:
        return {"owner_dept": "未分类", "doc_type": "未分类"}

    # 部门映射
    dept_mapping = {
        "销售": "销售",
        "财务": "财务",
        "行政": "行政",
        "公共": "公共"
    }

    owner_dept = dept_mapping.get(parts[0], "未分类")

    # 提取文档类型（第二部分）
    doc_type = parts[1] if len(parts) > 1 else "未分类"

    logger.debug(f"Parse permissions: {filename} -> owner_dept={owner_dept}, doc_type={doc_type}")

    return {
        "owner_dept": owner_dept,
        "doc_type": doc_type
    }


class LocalEmbeddingModel(BaseEmbedding):
    """本地Embedding模型 - 兼容LlamaIndex"""

    def __init__(self, model_name: str = "BAAI/bge-small-zh"):
        """初始化"""
        project_root = Path(__file__).parent.parent.parent.parent
        model_cache_dir = project_root / "models" / "embeddings"
        model_cache_dir.mkdir(parents=True, exist_ok=True)

        # 检查本地是否有模型
        model_local_path = model_cache_dir / "models" / model_name.replace("/", "--") / "snapshots" / "master"

        if model_local_path.exists():
            logger.info(f"Using local embedding model: {model_local_path}")
            model_dir = str(model_local_path)
        else:
            logger.info(f"Downloading embedding model from ModelScope: {model_name}")
            model_dir = snapshot_download(
                model_name,
                cache_dir=str(model_cache_dir),
                revision="master"
            )
            logger.info(f"Model downloaded to: {model_dir}")

        # 加载模型
        st_model = SentenceTransformer(model_dir)
        embed_dim = st_model.get_embedding_dimension()

        # 初始化父类
        super().__init__(model_name=model_name, embed_batch_size=32)

        # 用object.__setattr__绕过Pydantic验证
        object.__setattr__(self, "model", st_model)
        object.__setattr__(self, "_embed_dim", embed_dim)

    @property
    def embed_dim(self) -> int:
        """返回embedding维度"""
        return self._embed_dim

    def _get_text_embedding(self, text: str) -> List[float]:
        """同步获取文本embedding"""
        if not text or not isinstance(text, str):
            return [0.0] * self._embed_dim
        embedding = self.model.encode(text, convert_to_tensor=False)
        return embedding.tolist()

    async def _aget_text_embedding(self, text: str) -> List[float]:
        """异步获取文本embedding"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_text_embedding, text)

    def _get_query_embedding(self, query: str) -> List[float]:
        """同步获取查询embedding"""
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        """异步获取查询embedding"""
        return await self._aget_text_embedding(query)


class RAGService:
    """LlamaIndex RAG服务"""

    _instance = None
    _initialized = False

    def __new__(cls):
        """单例模式 - 确保全局只有一个RAG实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化RAG服务"""
        if RAGService._initialized:
            logger.info("RAG Service already initialized")
            return

        try:
            logger.info("Initializing RAG Service with LlamaIndex...")

            # 1. Embedding模型
            logger.info("Setting up embedding model...")
            embed_model = LocalEmbeddingModel()
            logger.info(f"Embedding model ready (dim={embed_model.embed_dim})")

            # 2. LLM
            logger.info("Setting up LLM...")
            llm = None

            # 根据配置选择 LLM 提供商
            if settings.llm_provider == "deepseek" and settings.deepseek_api_key:
                from llama_index.llms.openai import OpenAI
                llm = OpenAI(
                    api_key=settings.deepseek_api_key,
                    api_base=settings.deepseek_api_base,
                    model=settings.deepseek_model,
                    temperature=0.7,
                    max_tokens=settings.answer_max_tokens
                )
                logger.info(f"LLM ready (DeepSeek: {settings.deepseek_model})")
            elif settings.llm_provider == "claude" and settings.claude_api_key:
                llm = AnthropicLLM(
                    model="claude-3-5-haiku-20241022",
                    api_key=settings.claude_api_key,
                    max_tokens=1000
                )
                logger.info(f"LLM ready (Claude)")
            else:
                logger.warning(f"LLM provider '{settings.llm_provider}' not configured or API key missing")

            if llm:
                Settings.llm = llm
                self.llm = llm  # 保存到实例属性，供意图识别使用
            else:
                self.llm = None

            # 3.5. 初始化 IntentAgent
            self.intent_agent = IntentAgent()
            logger.info("IntentAgent initialized")

            # 4. Reranker (如果启用)
            self.reranker = None
            if settings.enable_rerank:
                try:
                    from src.backend.ingestion.reranker import LocalReranker
                    self.reranker = LocalReranker()
                    logger.info("Reranker loaded successfully")
                except Exception as e:
                    logger.warning(f"Failed to load reranker: {e}")

            # 5. Qdrant向量库
            logger.info("Connecting to Qdrant...")
            qdrant_client = QdrantClient(url=settings.qdrant_url, timeout=30)

            # 检查集合是否存在，如果维度不匹配则删除重建
            collection_exists = False
            try:
                collection_info = qdrant_client.get_collection(settings.qdrant_collection_name)
                # 获取向量维度
                try:
                    existing_dim = collection_info.config.vectors.size
                except:
                    # 某些版本的qdrant-client可能结构不同
                    try:
                        existing_dim = collection_info.vectors_count if hasattr(collection_info, 'vectors_count') else None
                        if not existing_dim:
                            # 尝试从points获取维度信息
                            points = qdrant_client.scroll(settings.qdrant_collection_name, limit=1)[0]
                            if points:
                                existing_dim = len(points[0].vector) if hasattr(points[0], 'vector') else 512
                            else:
                                existing_dim = embed_model.embed_dim
                    except:
                        existing_dim = 512  # 默认值

                current_dim = embed_model.embed_dim
                collection_exists = True

                if existing_dim != current_dim:
                    raise RuntimeError(
                        f"Qdrant collection '{settings.qdrant_collection_name}' dimension mismatch: "
                        f"stored={existing_dim}, current embedding model={current_dim}. "
                        f"To recover: back up the collection, then manually delete it and re-ingest. "
                        f"Automatic deletion is disabled to prevent accidental data loss."
                    )
                else:
                    logger.info(f"Collection {settings.qdrant_collection_name} exists with matching dimension {existing_dim}")
            except Exception as e:
                if "does not exist" not in str(e).lower():
                    logger.warning(f"Error checking collection: {e}")
                collection_exists = False

            # 如果集合不存在，创建新集合
            if not collection_exists:
                logger.info(f"Creating new collection {settings.qdrant_collection_name} with dimension {embed_model.embed_dim}")
                from qdrant_client.http import models
                try:
                    qdrant_client.create_collection(
                        collection_name=settings.qdrant_collection_name,
                        vectors_config=models.VectorParams(
                            size=embed_model.embed_dim,
                            distance=models.Distance.COSINE
                        )
                    )
                    logger.info(f"Collection {settings.qdrant_collection_name} created successfully")
                except Exception as create_e:
                    if "already exists" not in str(create_e):
                        logger.error(f"Failed to create collection: {create_e}")
                    else:
                        logger.info(f"Collection {settings.qdrant_collection_name} already exists")

            vector_store = QdrantVectorStore(
                client=qdrant_client,
                collection_name=settings.qdrant_collection_name
            )
            logger.info("Qdrant connected")

            # 4. 全局配置
            Settings.embed_model = embed_model
            if llm:
                Settings.llm = llm
            Settings.chunk_size = 512
            Settings.chunk_overlap = 50

            # 5. 创建索引
            logger.info("Creating vector store index...")
            self.index = VectorStoreIndex.from_vector_store(vector_store)

            # 标记为已初始化
            RAGService._initialized = True
            logger.info("RAG Service initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize RAG Service: {e}", exc_info=True)
            raise

    async def auto_load_docs_directory(self) -> Dict:
        """启动时自动加载docs目录下的所有文档"""
        try:
            project_root = Path(__file__).parent.parent.parent.parent
            docs_dir = project_root / "docs"

            if not docs_dir.exists():
                logger.info(f"Docs directory not found: {docs_dir}")
                return {"status": "info", "message": "Docs directory not found"}

            logger.info(f"Auto-loading documents from {docs_dir}...")
            result = await self.ingest_directory(str(docs_dir))

            if result.get("total_chunks", 0) > 0:
                logger.info(f"✓ Successfully auto-loaded {result['total_chunks']} chunks from docs/")
            else:
                logger.info("No documents found in docs/ directory")

            return result

        except Exception as e:
            logger.error(f"Auto-loading docs failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def _extract_pdf_content(
        self,
        pdf_path: Path,
        file_id: Optional[str],
        original_filename: Optional[str],
    ) -> tuple:
        """从 PDF 提取文本。

        先检测文本层：有文本层的是电子版，直接抽文本（快且准）；
        没有文本层的是扫描件，渲染页图后 OCR，并把每页 bbox 落到 sidecar。

        返回 (content, meta)，meta 含 file_id / is_scanned / page_count /
        pages_dir / text_layer 等。
        """
        import fitz

        display_name = original_filename or pdf_path.name
        max_bytes = settings.pdf_max_upload_mb * 1024 * 1024
        size = pdf_path.stat().st_size
        if size > max_bytes:
            raise ValueError(
                f"PDF 超过大小上限: {size / 1024 / 1024:.1f}MB > {settings.pdf_max_upload_mb}MB"
            )

        doc = fitz.open(str(pdf_path))
        try:
            page_count = doc.page_count
            text_info = detect_text_layer(doc, sample_pages=5)
        finally:
            doc.close()

        is_scanned = text_info["avg_chars_per_page"] < settings.pdf_scanned_min_chars
        meta = {
            "file_id": file_id,
            "is_scanned": is_scanned,
            "page_count": page_count,
            "text_layer": text_info,
            "pdf_size_bytes": size,
        }

        if not is_scanned:
            logger.info(
                f"PDF 判定为电子版（平均 {text_info['avg_chars_per_page']} 字符/页），直接提取文本"
            )
            doc = fitz.open(str(pdf_path))
            try:
                pages = []
                for i in range(page_count):
                    page_text = doc[i].get_text().strip()
                    if page_text:
                        # 保留页码标记，让切分器能定位来源页
                        pages.append(f"<!-- page:{i + 1} -->\n{page_text}")
                content = "\n\n".join(pages)
            finally:
                doc.close()
            return content, meta

        if not settings.pdf_ocr_enabled:
            raise ValueError(
                "该 PDF 无文本层（扫描件），但 PDF_OCR_ENABLED=false，无法入库。"
                "请在 .env 中开启 PDF_OCR_ENABLED=true"
            )

        logger.info(
            f"PDF 判定为扫描件（平均 {text_info['avg_chars_per_page']} 字符/页），启动 OCR"
        )
        if not file_id:
            file_id = str(uuid4())
            meta["file_id"] = file_id

        processor = ScannedPdfProcessor(
            pages_dir=Path(settings.pdf_pages_dir),
            dpi=settings.pdf_ocr_dpi,
            lang=settings.pdf_ocr_lang,
            min_confidence=settings.pdf_ocr_min_confidence,
            text_layer_min_chars=settings.pdf_scanned_min_chars,
        )

        ocr_started = datetime.now()
        result = await asyncio.to_thread(processor.process, pdf_path, file_id)
        elapsed = (datetime.now() - ocr_started).total_seconds()

        meta.update({
            "pages_dir": str(Path(settings.pdf_pages_dir) / file_id),
            "page_dpi": result.dpi,
            "ocr_pages": len(result.pages),
            "ocr_seconds": round(elapsed, 1),
            "page_sizes": {
                str(p.page_no): [p.width, p.height] for p in result.pages
            },
        })
        logger.info(
            f"OCR 完成: {len(result.pages)}/{page_count} 页, 耗时 {elapsed:.1f}s"
        )
        return result.to_markdown(), meta

    async def ingest_file(
        self,
        file_path: str,
        use_hospital_parser: bool = False,
        original_filename: str = None,
        chunk_strategy: str = "auto",
        chunk_size: int = None,
        chunk_overlap: int = None,
        file_id: str = None,
    ) -> Dict:
        """
        入库单个文件 - 完整流程：读取 → 切分 → 向量化 → 入库

        Args:
            file_path: 文件路径
            use_hospital_parser: 是否使用医院级别的分割器（用于医院规则库文件）
            file_id: 可选的文件UUID（来自数据库）。如果不提供，自动生成。用于与数据库保持一致。
        """
        try:
            logger.info(
                f"Ingesting file: {file_path} (strategy={chunk_strategy}, "
                f"legacy_hospital_parser={use_hospital_parser}, file_id={file_id})"
            )

            # 1. 读取文件
            from llama_index.core.schema import Document as LlamaIndexDoc

            file_path_obj = Path(file_path)

            # PDF 分支：电子版提取文本，扫描版走 OCR
            pdf_meta: Dict = {}
            if file_path_obj.suffix.lower() == ".pdf":
                content, pdf_meta = await self._extract_pdf_content(
                    file_path_obj, file_id, original_filename
                )
                if pdf_meta.get("file_id"):
                    file_id = pdf_meta["file_id"]
            else:
                # 尝试用UTF-8读取，如果失败则用其他编码
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except UnicodeDecodeError:
                    # 尝试其他常见编码
                    for encoding in ["gbk", "gb2312", "latin-1", "iso-8859-1"]:
                        try:
                            with open(file_path, "r", encoding=encoding) as f:
                                content = f.read()
                            logger.info(f"File decoded with {encoding}")
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        # 如果所有编码都失败，用errors='ignore'
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        logger.warning(f"File decoded with utf-8 (ignoring errors)")

            # 计算文件哈希值（用于去重）
            file_hash = hashlib.sha256(content.encode()).hexdigest()

            # 如果提供了file_id，使用它；否则生成新的
            if not file_id:
                file_id = str(uuid4())

            ingested_at = datetime.now().isoformat()

            # 2. 创建Document
            doc = LlamaIndexDoc(
                text=content,
                metadata={
                    "source": original_filename or str(file_path_obj.name),
                    "filename": original_filename or str(file_path_obj.name),
                    "file_path": str(file_path),
                    "file_id": file_id,
                    "file_hash": file_hash,
                    "ingested_at": ingested_at
                }
            )
            logger.info(f"File read: {len(content)} chars, hash: {file_hash[:8]}...")

            # 3. 按统一策略切分文档，并在医院策略下分析图片
            requested_strategy = "hospital_markdown" if use_hospital_parser else chunk_strategy
            config = build_chunk_config(chunk_size, chunk_overlap)
            selected_strategy = requested_strategy
            if requested_strategy == "auto":
                from src.backend.ingestion.chunking import resolve_strategy
                selected_strategy = resolve_strategy(requested_strategy, content)

            image_descriptions = {}
            if selected_strategy == "hospital_markdown":
                from src.backend.ingestion.hospital_parser import HospitalDocumentParser
                from src.backend.ingestion.image_analyzer import ImageAnalyzer

                image_descriptions = {}
                file_dir = file_path_obj.parent
                hospital_sections = HospitalDocumentParser.split_by_hospital(content)
                all_images = [img for section in hospital_sections for img in section["images"]]
                if all_images:
                    image_analyzer = ImageAnalyzer()
                    for img in all_images:
                        img_path = img["path"]
                        full_img_path = Path(img_path) if Path(img_path).is_absolute() else file_dir / img_path
                        if full_img_path.exists():
                            description = await image_analyzer.analyze_image(
                                str(full_img_path),
                                context=f"医院SPD操作指南 - {file_path_obj.name}",
                            )
                            if description:
                                image_descriptions[img_path] = description

            parse_result = split_document(
                doc,
                strategy=requested_strategy,
                config=config,
                context=ParserContext(file_path=file_path_obj, image_descriptions=image_descriptions),
            )
            nodes = parse_result.nodes
            logger.info(
                f"Document split into {len(nodes)} chunks using "
                f"{parse_result.strategy} ({parse_result.version}, "
                f"{config.size}/{config.overlap})"
            )

            strategy = parse_result.strategy
            strategy_version = parse_result.version

            # 4. 增强每个node的metadata
            # 解析文件名权限
            permissions = parse_filename_permissions(original_filename or file_path_obj.name)

            for i, node in enumerate(nodes):
                node.metadata.update({
                    "file_id": file_id,
                    "source": original_filename or file_path_obj.name,  # 前端"来源文档"展示用的完整文件名
                    "filename": original_filename or file_path_obj.name,
                    "chunk_index": i,
                    "total_chunks": len(nodes),
                    "version": 1,
                    "parser_type": strategy,
                    "chunk_strategy": strategy,
                    "chunk_strategy_version": strategy_version,
                    "chunk_size": config.size,
                    "chunk_overlap": config.overlap,
                    "owner_dept": permissions["owner_dept"],  # 添加权限信息
                    "doc_type": permissions["doc_type"]       # 添加文档类型
                })

                # PDF 来源：记录页码，前端据此打开对应页图
                if pdf_meta:
                    node.metadata["source_type"] = "pdf"
                    node.metadata["is_scanned"] = pdf_meta["is_scanned"]
                    node.metadata["pdf_page_count"] = pdf_meta["page_count"]
                    page_no = node.metadata.get("page_no")
                    if page_no:
                        node.metadata["page_no"] = int(page_no)
                        node.metadata["page_dpi"] = pdf_meta.get("page_dpi", settings.pdf_ocr_dpi)
                        sizes = pdf_meta.get("page_sizes", {})
                        if str(page_no) in sizes:
                            node.metadata["page_width"] = sizes[str(page_no)][0]
                            node.metadata["page_height"] = sizes[str(page_no)][1]

            # 5. 计算embeddings并插入向量库
            logger.info("Computing embeddings and inserting into Qdrant...")
            self.index.insert_nodes(nodes)
            logger.info(f"Successfully inserted {len(nodes)} chunks into vector store")

            logger.info(f"File ingested successfully: {file_path}")
            return {
                "status": "success",
                "file": str(file_path_obj.name),
                "file_id": file_id,
                "file_hash": file_hash,
                "file_size": len(content),
                "chunks": len(nodes),
                "parser_type": strategy,
                "chunk_strategy": strategy,
                "chunk_strategy_version": strategy_version,
                "chunk_size": config.size,
                "chunk_overlap": config.overlap,
                "hospitals": parse_result.hospitals,
                "images": parse_result.image_paths,
                "analysis": parse_result.analysis,
                "source_type": "pdf" if pdf_meta else "text",
                "pdf": {
                    "is_scanned": pdf_meta.get("is_scanned"),
                    "page_count": pdf_meta.get("page_count"),
                    "text_layer": pdf_meta.get("text_layer"),
                    "page_dpi": pdf_meta.get("page_dpi"),
                    "ocr_pages": pdf_meta.get("ocr_pages"),
                    "ocr_seconds": pdf_meta.get("ocr_seconds"),
                } if pdf_meta else None,
                "message": f"Successfully ingested {len(nodes)} chunks"
            }

        except Exception as e:
            logger.error(f"File ingestion failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def ingest_directory(
        self,
        directory: str,
        auto_detect_hospital: bool = True,
        chunk_strategy: str = "auto",
        chunk_size: int = None,
        chunk_overlap: int = None,
    ) -> Dict:
        """
        批量入库目录下的所有文档

        Args:
            directory: 目录路径
            auto_detect_hospital: 是否自动检测医院规则库文件（包含"医院"关键字的文件）
        """
        try:
            logger.info(f"Ingesting directory: {directory} (auto_detect_hospital={auto_detect_hospital})")

            dir_path = Path(directory)
            if not dir_path.exists():
                logger.warning(f"Directory does not exist: {directory}")
                return {"status": "error", "message": f"Directory not found: {directory}"}

            # 支持的文件扩展名
            supported_extensions = {".md", ".markdown", ".pdf", ".txt"}
            files = [
                f for f in dir_path.rglob("*")
                if f.is_file() and f.suffix.lower() in supported_extensions
            ]

            if not files:
                logger.warning(f"No supported files found in {directory}")
                return {
                    "status": "success",
                    "files_ingested": 0,
                    "total_chunks": 0,
                    "message": "No supported files found"
                }

            logger.info(f"Found {len(files)} files to ingest")

            total_chunks = 0
            ingested_files = []
            failed_files = []

            for file_path in files:
                try:
                    logger.info(f"Processing: {file_path.name}")

                    result = await self.ingest_file(
                        str(file_path),
                        original_filename=file_path.name,
                        chunk_strategy=chunk_strategy,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                    )

                    if result["status"] == "success":
                        chunks = result.get("chunks", 0)
                        total_chunks += chunks
                        parser_type = result.get("parser_type", "character")
                        ingested_files.append({
                            "name": file_path.name,
                            "chunks": chunks,
                            "parser_type": parser_type
                        })
                        logger.info(f"✓ {file_path.name}: {chunks} chunks ({parser_type})")
                    else:
                        failed_files.append({
                            "name": file_path.name,
                            "error": result.get("message")
                        })
                        logger.warning(f"✗ {file_path.name}: {result.get('message')}")

                except Exception as e:
                    failed_files.append({
                        "name": file_path.name,
                        "error": str(e)
                    })
                    logger.error(f"Error processing {file_path.name}: {e}")

            logger.info(f"Ingestion complete: {len(ingested_files)} succeeded, {len(failed_files)} failed")

            return {
                "status": "success" if ingested_files else "error",
                "files_ingested": len(ingested_files),
                "total_chunks": total_chunks,
                "ingested_files": ingested_files,
                "failed_files": failed_files,
                "message": f"Ingested {len(ingested_files)} files with {total_chunks} chunks"
            }

        except Exception as e:
            logger.error(f"Directory ingestion failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def search(self, query: str, top_k: int = 5, user_dept: str = None, enable_intent: bool = True, conversation_history: List[Dict] = None) -> Dict:
        """搜索文档，支持 Rerank 精排 + 权限过滤 + 意图识别"""
        try:
            logger.info(f"Searching: {query} (user_dept={user_dept}, enable_intent={enable_intent})")

            # 使用 IntentAgent 处理查询
            intent_result = None
            processed_query = query

            if enable_intent:
                try:
                    intent_process_result = await self.intent_agent.process(
                        query=query,
                        conversation_history=conversation_history,
                        enable_rewrite=True,
                        enable_context=bool(conversation_history),
                        enable_hospital_extraction=True  # 🆕 启用医院识别
                    )

                    # 使用处理后的查询
                    processed_query = intent_process_result["processed_query"]
                    intent_result = intent_process_result["intent"]

                    # 保留医院信息到 intent_result 中
                    if "hospital" in intent_process_result:
                        intent_result["hospital"] = intent_process_result["hospital"]

                    logger.info(f"Processed query: '{query}' → '{processed_query}'")
                    logger.info(f"Query intent: {intent_result['intent']} -> doc_type: {intent_result.get('doc_type')}")
                    if intent_result.get("hospital"):
                        logger.info(f"Query hospital: {intent_result.get('hospital')}")

                except Exception as e:
                    logger.warning(f"IntentAgent processing failed: {e}, using original query")
                    processed_query = query

            # 粗排：检索更多候选（如果启用 rerank，检索 top_k * 3）
            retrieve_k = top_k * 3 if (self.reranker and settings.enable_rerank) else top_k
            detected_hospital = None
            if intent_result:
                extracted_hospital = normalize_hospital_name(intent_result.get("hospital"))
                if extracted_hospital in HOSPITAL_MAPPING:
                    detected_hospital = extracted_hospital
            if not detected_hospital:
                detected_hospital = find_hospital_in_text(query) or find_hospital_in_text(processed_query)
                if detected_hospital:
                    logger.info(f"Hospital identified by local text matching: {detected_hospital}")
            retrieval_options = {"similarity_top_k": retrieve_k}
            # 注：不在retriever级别应用hospital过滤（chunks中没有hospital字段）
            # 而是在后续用HospitalFilter进行soft过滤
            retriever = self.index.as_retriever(**retrieval_options)
            logger.info(f"DEBUG: Retriever created with options: {retrieval_options}")
            logger.info(f"DEBUG: Index type: {type(self.index)}")
            nodes = retriever.retrieve(processed_query)  # 使用处理后的查询
            logger.info(f"DEBUG: Retrieved {len(nodes)} nodes")
            if nodes:
                logger.debug(f"DEBUG: First node doc_type: {nodes[0].metadata.get('doc_type', 'N/A')}")
                logger.debug(f"DEBUG: First node owner_dept: {nodes[0].metadata.get('owner_dept', 'N/A')}")

            if detected_hospital:
                logger.info(f"Applying hospital filter: {detected_hospital}")
                nodes = HospitalFilter.filter_by_hospital(
                    nodes,
                    target_hospital=detected_hospital,
                    strict=True
                )
                logger.info(f"Hospital filter result: {len(nodes)} nodes")
            else:
                logger.info(f"DEBUG: No hospital detected, skipping hospital filter")

            # 精排：使用 reranker 重新排序
            if self.reranker and settings.enable_rerank and len(nodes) > 0:
                logger.info(f"Reranking {len(nodes)} candidates to top {top_k}")
                documents = [node.get_content() for node in nodes]
                ranked_indices = self.reranker.rerank(query, documents, top_k=top_k)

                # 按 rerank 分数重新排序，并过滤低分结果
                reranked_nodes = []
                # 修复：不进行硬过滤，而是保留reranker返回的所有top_k结果
                if ranked_indices:
                    for idx, score in ranked_indices[:top_k]:
                        node = nodes[idx]
                        # 更新 score 为 rerank 分数
                        node.score = float(score)
                        reranked_nodes.append(node)

                    logger.info(f"Rerank returned {len(reranked_nodes)} nodes (no filtering)")

                nodes = reranked_nodes

            logger.info(f"DEBUG: After rerank/intent filter - {len(nodes)} nodes remaining")

            # 意图过滤（根据文档类型）
            if enable_intent and intent_result and intent_result.get("doc_type") and intent_result["intent"] != "general":
                original_count = len(nodes)
                target_doc_type = intent_result["doc_type"]
                confidence = intent_result.get("confidence", 0.0)

                # 只有置信度 >= 0.85 时才进行类型过滤（提高阈值避免过度过滤）
                if confidence >= 0.85:
                    filtered_nodes = []
                    for node in nodes:
                        node_doc_type = node.metadata.get("doc_type", "未分类")
                        if node_doc_type == target_doc_type or node_doc_type == "未分类":
                            filtered_nodes.append(node)

                    # 关键修复：只在过滤后还有结果，且通过权限过滤后仍有结果时才应用
                    # 先做权限过滤预检查
                    if len(filtered_nodes) > 0 and user_dept:
                        # 预检查：过滤后的结果是否有权限访问的
                        accessible_count = 0
                        for node in filtered_nodes:
                            owner_dept = node.metadata.get("owner_dept", "未分类")
                            if owner_dept in ["公共", "未分类"] or owner_dept == user_dept:
                                accessible_count += 1

                        if accessible_count > 0:
                            # 有可访问的结果，应用意图过滤
                            nodes = filtered_nodes
                            logger.info(f"Intent filter: {len(nodes)}/{original_count} chunks match doc_type '{target_doc_type}' (预计可访问: {accessible_count})")
                        else:
                            # 过滤后没有可访问的结果，fallback
                            logger.warning(f"Intent filter would result in 0 accessible chunks, fallback to all {original_count} chunks")
                    elif len(filtered_nodes) > 0:
                        # 没有权限过滤，直接应用意图过滤
                        nodes = filtered_nodes
                        logger.info(f"Intent filter: {len(nodes)}/{original_count} chunks match doc_type '{target_doc_type}'")
                    else:
                        # Fallback: 保持原有的 nodes 不变
                        logger.warning(f"Intent filter returned 0 results, fallback to all {original_count} chunks")
                else:
                    logger.info(f"Intent confidence {confidence} < 0.85, skipping doc_type filter")

            # 权限过滤
            if user_dept:
                original_count = len(nodes)
                filtered_nodes = []

                # 部门名称映射：英文 → 中文
                dept_mapping = {
                    "sales": "销售",
                    "sales_dept": "销售",
                    "operations": "运营",
                    "operations_dept": "运营",
                    "public": "公共",
                    "公共": "公共",
                    "销售": "销售",
                    "运营": "运营",
                }

                # 标准化user_dept
                normalized_user_dept = dept_mapping.get(user_dept.lower(), user_dept)
                logger.info(f"Normalized user_dept: '{user_dept}' → '{normalized_user_dept}'")

                for node in nodes:
                    owner_dept = node.metadata.get("owner_dept", "未分类")
                    logger.info(f"DEBUG: Node owner_dept='{owner_dept}', normalized_user_dept='{normalized_user_dept}'")

                    # 公共/未分类全员可见
                    if owner_dept in ["公共", "未分类"]:
                        filtered_nodes.append(node)
                    # 同部门可见
                    elif owner_dept == normalized_user_dept:
                        filtered_nodes.append(node)
                    # 其他情况过滤掉

                nodes = filtered_nodes
                logger.info(f"Permission filter: {len(nodes)}/{original_count} chunks accessible to dept '{normalized_user_dept}'")

            results = []
            for i, node in enumerate(nodes, 1):
                text = node.get_content()
                result = {
                    "rank": i,
                    "text": text,
                    "score": node.score if hasattr(node, "score") else 0.0,
                    "metadata": node.metadata,
                    "images": []  # 添加images数组
                }

                # 从文本中提取markdown图片
                md_images = self._extract_markdown_images(text)
                for img in md_images:
                    if os.path.exists(img["local_path"]):
                        result["images"].append({
                            "path": img["local_path"],
                            "url": img["url"],
                            "description": img["description"]
                        })

                # 使用 image_mapper 丰富图片信息（添加章节描述）
                if result["images"]:
                    result["images"] = image_mapper.enrich_images(result["images"])

                results.append(result)

            logger.info(f"Found {len(results)} results")
            return {
                "status": "success",
                "query": query,
                "results": results,
                "count": len(results)
            }

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {"status": "error", "message": str(e)}

    def _extract_markdown_images(self, text: str) -> list:
        """从markdown文本中提取图片链接（支持[text](url)和![alt](url)格式）"""
        images = []
        # 匹配所有markdown链接格式 [text](url)
        link_pattern = r'\[([^\]]*)\]\(([^)]+)\)'
        matches = re.finditer(link_pattern, text)

        for match in matches:
            alt_text = match.group(1)
            url = match.group(2)

            # 只提取图片链接（ProcessOn或图片格式）
            if 'processon.com' in url or url.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                # 简单的URL映射：ProcessOn CDN -> 本地文件
                if 'processon.com' in url and 'wps' in url:
                    file_id = url.split('/')[-1]
                    local_path = f"docs/images/{file_id}.png"
                    # 标准化为 /api/images/xxx.png 格式
                    standardized_url = f"/api/images/{file_id}.png"
                else:
                    local_path = url if url.startswith('docs/') else f"docs/{url}"
                    # 提取文件名并标准化
                    file_name = url.split('/')[-1]
                    standardized_url = f"/api/images/{file_name}"

                images.append({
                    "url": standardized_url,  # 使用标准化的 URL
                    "local_path": local_path,
                    "description": alt_text
                })

        return images

    def _normalize_image_links(self, text: str) -> str:
        """
        将文本中的图片链接统一改写为标准API路径格式：![desc](/api/images/文件名.png)
        这样LLM原样照抄后，前端可以直接识别/api/前缀并拼出完整URL
        """
        # 同时吞掉可选的 Markdown 图片前缀，避免 ![alt](url) 被重写为 !![alt](url)。
        link_pattern = r'!?\[([^\]]*)\]\(([^)]+)\)'

        def replace_link(match):
            alt_text = match.group(1)
            url = match.group(2)

            if 'processon.com' in url or url.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                img_name = url.split('/')[-1]
                if not img_name.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    img_name = f"{img_name}.png"
                return f"![{alt_text}](/api/images/{img_name})"
            # 非图片链接保持原样
            return match.group(0)

        return re.sub(link_pattern, replace_link, text)

    async def generate_answer(self, query: str, top_k: int = 3, user_dept: str = None, enable_intent: bool = True, history_context: list = None, conversation_history: list = None, search_result: Dict = None) -> Dict:
        """RAG: 搜索 + LLM生成答案，保留图片在文档原始位置，支持权限过滤 + 意图识别 + 历史上下文"""
        try:
            logger.info(f"Generating answer for: {query} (user_dept={user_dept}, enable_intent={enable_intent}, history_len={len(history_context) if history_context else 0})")

            greeting = greeting_answer(query)
            if greeting:
                return {"status": "success", "query": query, "answer": greeting, "sources": [], "images": []}

            # 1. 搜索获取相关文档片段（传递 user_dept 和 enable_intent）
            # 如果没有提供conversation_history，使用history_context
            search_history = conversation_history if conversation_history else history_context
            search_result = search_result or await self.search(query, top_k=top_k, user_dept=user_dept, enable_intent=enable_intent, conversation_history=search_history)

            if search_result.get("status") == "error":
                return {"status": "error", "message": "知识库检索失败，请稍后重试。"}
            if not search_result.get("results"):
                return {
                    "status": "success",
                    "query": query,
                    "answer": NO_RESULTS,
                    "sources": [],
                    "images": []
                }

            # 2. 收集图片（保持原样，供前端"来源文档"展示用）
            all_images = []
            seen_images = set()
            context_chunks = []

            for result in search_result.get("results", []):
                text = result.get("text", "")
                if text.strip():
                    # 将文本中的图片链接标准化为 /api/images/xxx.png 格式，
                    # 让LLM原样照抄，图片就能停留在文档原本的位置上
                    normalized_text = self._normalize_image_links(text)
                    context_chunks.append(normalized_text)

                for img in result.get("images", []):
                    img_url = img.get("url", "")
                    if img_url and img_url not in seen_images:
                        seen_images.add(img_url)
                        all_images.append(img)

            # 3. 根据配置选择 LLM 调用生成答案
            fallback = False
            diagnostics_data = None
            if not context_chunks:
                answer_text = "未找到相关内容"
            else:
                try:
                    context_text = "\n\n---\n\n".join(context_chunks)

                    # 构建消息列表（包含历史上下文）
                    messages = []

                    # 添加历史消息（如果有）
                    if history_context:
                        for msg in history_context[-6:]:  # 最多取最近6条历史消息
                            messages.append({
                                "role": msg["role"],
                                "content": msg["content"]
                            })

                    # 添加当前问题
                    current_prompt = ANSWER_GENERATION_PROMPT.format(
                        query=query, context_text=context_text
                    )

                    messages.append({"role": "user", "content": current_prompt})

                    # 根据配置选择 LLM 提供商
                    if settings.llm_provider == "deepseek" and settings.deepseek_api_key:
                        diagnostics = AnswerDiagnostics()
                        answer_parts = []
                        async for text in deepseek_answer_chunks(
                            messages, settings, diagnostics, streaming=False
                        ):
                            answer_parts.append(text)
                        answer_text = "".join(answer_parts)
                        fallback = not diagnostics.succeeded
                        diagnostics_data = diagnostics.to_dict()
                        if fallback:
                            answer_text = source_excerpt_answer(
                                context_chunks, diagnostics.failure_reason
                            )
                        logger.info(
                            "DeepSeek answer completed: request_id=%s fallback=%s",
                            diagnostics.request_id,
                            fallback,
                        )
                    elif settings.llm_provider == "claude" and settings.claude_api_key:
                        # 使用 Claude
                        from anthropic import Anthropic

                        client_kwargs = {"api_key": settings.claude_api_key}
                        if settings.claude_api_base:
                            client_kwargs["base_url"] = settings.claude_api_base
                        client = Anthropic(**client_kwargs)

                        message = client.messages.create(
                            model=settings.claude_model_sonnet,
                            max_tokens=settings.answer_max_tokens,
                            messages=messages
                        )

                        answer_text = message.content[0].text
                        logger.info(f"Claude generated answer: {answer_text[:100]}")
                    else:
                        logger.error(f"LLM provider '{settings.llm_provider}' not configured")
                        answer_text = "LLM 未配置，无法生成答案"

                except Exception as llm_error:
                    logger.error(f"LLM call failed: {llm_error}", exc_info=True)
                    fallback = True
                    answer_text = source_excerpt_answer(context_chunks, "error")

            sources = []
            for i, result in enumerate(search_result.get("results", [])[:3], 1):
                sources.append({
                    "rank": i,
                    "text": result.get("text", "")[:200],
                    "score": result.get("score", 0.0),
                    "filename": result.get("metadata", {}).get("source", "未知"),
                    "hospital": result.get("metadata", {}).get("hospital", "未知医院"),
                    "metadata": result.get("metadata", {}),
                    "images": result.get("images", [])
                })

            logger.info(f"Answer generated with {len(all_images)} images")
            return {
                "status": "success",
                "query": query,
                "answer": answer_text,
                "sources": sources,
                "images": all_images,
                "fallback": fallback,
                "diagnostics": diagnostics_data,
            }

        except Exception as e:
            logger.error(f"Answer generation failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def generate_answer_stream(
        self,
        query: str,
        top_k: int = 3,
        user_dept: str = None,
        enable_intent: bool = True,
        history_context: list = None,
        conversation_history: list = None,
        search_result: Dict = None,
    ):
        """流式生成答案 - 支持 DeepSeek 和 Claude，可复用已完成的检索结果。"""
        try:
            logger.info(f"Stream generating answer for: {query}")

            greeting = greeting_answer(query)
            if greeting:
                yield {"type": "answer_complete", "content": greeting, "sources": [], "images": []}
                return

            # 1. 搜索获取相关文档片段；Agent 模式可复用已完成的检索。
            search_history = conversation_history if conversation_history else history_context
            search_result = search_result or await self.search(
                query,
                top_k=top_k,
                user_dept=user_dept,
                enable_intent=enable_intent,
                conversation_history=search_history,
            )

            if search_result.get("status") == "error":
                yield {"type": "error", "content": "知识库检索失败，请稍后重试。"}
                return

            if not search_result.get("results"):
                yield {"type": "search_complete", "found_count": 0}
                yield {
                    "type": "answer_complete",
                    "content": NO_RESULTS,
                    "sources": [],
                    "images": []
                }
                return

            # 发送检索完成信息
            found_count = len(search_result.get("results", []))
            yield {
                "type": "search_complete",
                "found_count": found_count
            }

            # 2. 构建上下文
            context_chunks = []
            all_images = []
            seen_images = set()

            for result in search_result.get("results", []):
                if "text" in result:
                    text = result["text"]
                    normalized_text = self._normalize_image_links(text)
                    context_chunks.append(normalized_text)

                for img in result.get("images", []):
                    img_url = img.get("url", "")
                    if img_url and img_url not in seen_images:
                        seen_images.add(img_url)
                        all_images.append(img)

            # 3. 构建消息
            context_text = "\n\n---\n\n".join(context_chunks)
            messages = []

            # 添加历史消息
            if history_context:
                for msg in history_context[-6:]:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })

            # 添加当前问题
            current_prompt = ANSWER_GENERATION_PROMPT.format(
                query=query, context_text=context_text
            )

            messages.append({"role": "user", "content": current_prompt})

            full_answer = ""
            fallback = False
            diagnostics_data = None

            # 4. 根据配置选择流式 LLM
            if settings.llm_provider == "deepseek" and settings.deepseek_api_key:
                diagnostics = AnswerDiagnostics()
                async for text in deepseek_answer_chunks(
                    messages, settings, diagnostics, streaming=True
                ):
                    full_answer += text
                    yield {
                        "type": "answer_chunk",
                        "content": text
                    }
                diagnostics_data = diagnostics.to_dict()
                fallback = not diagnostics.succeeded
                if fallback:
                    full_answer = source_excerpt_answer(
                        context_chunks, diagnostics.failure_reason
                    )
                    yield {
                        "type": "answer_chunk",
                        "content": full_answer
                    }

            elif settings.llm_provider == "claude" and settings.claude_api_key:
                # Claude 流式输出
                from anthropic import Anthropic

                client_kwargs = {"api_key": settings.claude_api_key}
                if settings.claude_api_base:
                    client_kwargs["base_url"] = settings.claude_api_base
                client = Anthropic(**client_kwargs)

                with client.messages.stream(
                    model=settings.claude_model_sonnet,
                    max_tokens=settings.answer_max_tokens,
                    messages=messages
                ) as stream:
                    for text in stream.text_stream:
                        full_answer += text
                        yield {
                            "type": "answer_chunk",
                            "content": text
                        }
            else:
                yield {
                    "type": "error",
                    "content": f"LLM provider '{settings.llm_provider}' not configured"
                }
                return

            if not full_answer.strip():
                fallback = True
                full_answer = source_excerpt_answer(context_chunks, "empty")
                yield {
                    "type": "answer_chunk",
                    "content": full_answer
                }

            # 5. 返回来源和图片
            sources = []
            for i, result in enumerate(search_result.get("results", [])[:3], 1):
                sources.append({
                    "rank": i,
                    "text": result.get("text", "")[:200],
                    "score": result.get("score", 0.0),
                    "filename": result.get("metadata", {}).get("source", "未知"),
                    "hospital": result.get("metadata", {}).get("hospital", "未知医院"),
                    "metadata": result.get("metadata", {}),
                    "images": result.get("images", [])
                })

            # 最后发送完整信息
            yield {
                "type": "answer_complete",
                "content": full_answer,
                "sources": sources,
                "images": all_images,
                "fallback": fallback,
                "diagnostics": diagnostics_data,
            }

        except Exception as e:
            logger.error(f"Stream answer generation failed: {e}", exc_info=True)
            yield {
                "type": "error",
                "content": f"生成失败: {str(e)}"
            }

    async def delete_file_chunks(self, file_id: str) -> Dict:
        """删除指定文件的所有chunks"""
        try:
            logger.info(f"Deleting chunks for file_id: {file_id}")

            from qdrant_client.http.models import PointIdsList

            client = self.index.vector_store._client
            points = []
            offset = None
            while True:
                batch, offset = client.scroll(
                    collection_name=settings.qdrant_collection_name,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                points.extend(batch)
                if offset is None:
                    break

            point_ids = []
            for point in points:
                payload = point.payload or {}

                # 尝试从metadata字段获取file_id
                if "metadata" in payload and isinstance(payload["metadata"], dict):
                    file_id_in_point = payload["metadata"].get("file_id")
                else:
                    # 如果metadata不是dict，直接从payload顶级获取
                    file_id_in_point = payload.get("file_id")

                # 匹配file_id
                if file_id_in_point and str(file_id_in_point) == str(file_id):
                    point_ids.append(point.id)
                    logger.debug(f"Found point {point.id} with file_id {file_id_in_point}")

            if not point_ids:
                logger.info(f"No chunks found for file_id: {file_id}")
                return {
                    "status": "success",
                    "file_id": file_id,
                    "deleted_chunks": 0,
                    "message": "No chunks found for this file"
                }

            client.delete(
                collection_name=settings.qdrant_collection_name,
                points_selector=PointIdsList(points=point_ids),
                wait=True,
            )
            logger.info(f"Successfully deleted {len(point_ids)} chunks for file_id: {file_id}")

            self._cleanup_pdf_artifacts(file_id)

            return {
                "status": "success",
                "file_id": file_id,
                "deleted_chunks": len(point_ids),
                "message": f"Successfully deleted {len(point_ids)} chunks"
            }

        except Exception as e:
            logger.error(f"Failed to delete chunks for file_id {file_id}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    @staticmethod
    def _cleanup_pdf_artifacts(file_id: str) -> None:
        """删除该文件的页图目录与留存的源 PDF。

        只删「我们自己生成的」东西，且 file_id 必须是纯 UUID 形态，
        避免上游传来带路径分隔符的字符串把删除范围扩到目录之外。
        """
        import shutil
        from pathlib import Path as _Path

        safe = str(file_id)
        if not safe or not set(safe) <= set("0123456789abcdefABCDEF-"):
            logger.warning(f"file_id 形态异常，跳过 PDF 产物清理: {safe!r}")
            return

        pages_dir = _Path(settings.pdf_pages_dir) / safe
        if pages_dir.exists():
            try:
                shutil.rmtree(pages_dir)
                logger.info(f"已删除页图目录: {pages_dir}")
            except Exception as e:
                logger.warning(f"删除页图目录失败 {pages_dir}: {e}")

        source_pdf = _Path(settings.pdf_source_dir) / f"{safe}.pdf"
        if source_pdf.exists():
            try:
                source_pdf.unlink()
                logger.info(f"已删除源 PDF: {source_pdf}")
            except Exception as e:
                logger.warning(f"删除源 PDF 失败 {source_pdf}: {e}")

    async def clear_vector_store(self) -> Dict:
        """清空向量库中的所有数据"""
        try:
            logger.info(f"Clearing vector store: {settings.qdrant_collection_name}")

            qdrant_client = self.index.vector_store._client

            # 删除整个集合
            qdrant_client.delete_collection(settings.qdrant_collection_name)
            logger.info(f"Collection deleted: {settings.qdrant_collection_name}")

            # 重新创建空集合
            from qdrant_client.http import models
            embed_model = self.index._embed_model if hasattr(self.index, '_embed_model') else None

            if not embed_model:
                # 临时创建一个embed_model来获取维度
                from src.backend.ingestion.rag_service import LocalEmbeddingModel
                temp_embed = LocalEmbeddingModel()
                embed_dim = temp_embed.embed_dim
            else:
                embed_dim = embed_model.embed_dim if hasattr(embed_model, 'embed_dim') else 512

            qdrant_client.create_collection(
                collection_name=settings.qdrant_collection_name,
                vectors_config=models.VectorParams(
                    size=embed_dim,
                    distance=models.Distance.COSINE
                )
            )
            logger.info(f"Collection recreated: {settings.qdrant_collection_name}")

            return {
                "status": "success",
                "message": "Vector store cleared successfully"
            }

        except Exception as e:
            logger.error(f"Failed to clear vector store: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def get_kb_stats(self) -> Dict:
        """获取知识库统计信息"""
        try:
            logger.info("Getting knowledge base stats...")

            collection_info = self.index.vector_store._client.get_collection(
                settings.qdrant_collection_name
            )

            total_chunks = collection_info.points_count
            logger.info(f"Knowledge base stats: {total_chunks} chunks")

            return {
                "status": "success",
                "total_chunks": total_chunks,
                "collection_name": settings.qdrant_collection_name,
                "vector_size": collection_info.config.vectors.size if hasattr(collection_info.config, 'vectors') else 512
            }

        except Exception as e:
            logger.error(f"Failed to get KB stats: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def sync_existing_chunks_to_db(self, db_session) -> Dict:
        """将现有的chunks同步到数据库（迁移）"""
        try:
            from src.backend.knowledge_base.service import KnowledgeBaseService
            from qdrant_client.http.models import Filter

            logger.info("Syncing existing chunks to database...")

            # 查询所有points
            scroll_result = self.index.vector_store._client.scroll(
                collection_name=settings.qdrant_collection_name,
                limit=10000
            )

            if not scroll_result or not scroll_result[0]:
                logger.info("No chunks found in Qdrant")
                return {"status": "success", "synced_files": 0}

            points = scroll_result[0]
            logger.info(f"Found {len(points)} chunks in Qdrant")

            # 按file_id和source分组
            files_dict = {}
            for point in points:
                metadata = point.payload.get("metadata", {})
                source = metadata.get("source", "unknown")
                file_path = metadata.get("file_path", "")
                file_id = metadata.get("file_id", "")
                file_hash = metadata.get("file_hash", "")

                # 使用source作为key（如果没有file_id）
                key = f"{source}_{file_id}" if file_id else source

                if key not in files_dict:
                    files_dict[key] = {
                        "source": source,
                        "file_path": file_path,
                        "file_id": file_id,
                        "file_hash": file_hash,
                        "chunks": 0,
                        "total_size": 0
                    }

                files_dict[key]["chunks"] += 1

            # 保存到数据库
            kb_service = KnowledgeBaseService(db_session)
            synced_count = 0

            for file_info in files_dict.values():
                # 只有有file_hash或file_id才能保存
                if file_info["file_hash"] or file_info["file_id"]:
                    result = await kb_service.save_file_record(
                        filename=file_info["source"],
                        file_path=file_info["file_path"],
                        file_hash=file_info["file_hash"] or "unknown",
                        file_size=0,
                        total_chunks=file_info["chunks"]
                    )

                    if result.get("status") in ("success", "warning"):
                        synced_count += 1
                        logger.info(
                            f"Synced: {file_info['source']} "
                            f"({file_info['chunks']} chunks)"
                        )

            logger.info(f"Synced {synced_count} files to database")
            return {
                "status": "success",
                "synced_files": synced_count,
                "total_files": len(files_dict),
                "message": f"Synced {synced_count} files"
            }

        except Exception as e:
            logger.error(f"Failed to sync chunks: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
