"""
文档入库和搜索API路由
基于LlamaIndex RAG服务
"""
from fastapi import APIRouter, File, UploadFile, HTTPException, status, Depends, Path
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from sqlalchemy import select
from uuid import UUID
from datetime import datetime
import tempfile
import os
import json
import re
import asyncio
from pathlib import Path as PathlibPath

from src.backend.db.database import get_db
from src.backend.db.models import KnowledgeBaseFile
from src.backend.ingestion.rag_service import RAGService
from src.backend.agent.rag_orchestrator import RAGOrchestrator
from src.backend.knowledge_base.service import KnowledgeBaseService
from src.backend.core.logger import logger
from src.backend.core.config import settings

router = APIRouter()


def _fix_mojibake_filename(filename: str) -> str:
    """修复 multipart 文件名被误按 Latin-1 解码导致的乱码。

    HTTP 头规范只允许 Latin-1，浏览器把中文文件名的原始字节直接塞进
    `filename="..."` 时，Starlette 会逐字节解成一串 codepoint < 256 的
    字符串——此时 filename 已经是错的，后续按 UTF-8 存库就变成双重编码
    乱码（实测 `销售_手册_呼吸介入手册.pdf` 存成了
    `ÏúÊÛ_ÊÖ²á_ºôÎü½éÈëÊÖ²á.pdf`）。

    还原思路：把字符串按 Latin-1 编回原始字节，再按候选编码解一次。
    候选顺序 utf-8 在前（现代浏览器发的是 UTF-8 字节），gbk/gb18030
    在后（旧客户端与 Windows 工具链）。顺序是安全的：UTF-8 字节被
    当成 GBK 解会得到乱码但**不报错**，反过来 GBK 字节几乎不是合法
    UTF-8 序列会直接抛错，所以 utf-8 优先不会误吞 GBK 的情况。

    字符串本身不在 Latin-1 可表示范围时说明客户端已经传对了，直接
    原样返回；候选编码都解不出也原样返回，避免误伤正常文件名。
    """
    try:
        raw = filename.encode("latin-1")
    except UnicodeEncodeError:
        return filename

    for encoding in ("utf-8", "gbk", "gb18030"):
        try:
            fixed = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if fixed != filename:
            return fixed
    return filename


def _persist_source_pdf(tmp_path: str, file_id: str, original_filename: str) -> str:
    """把上传的 PDF 从临时目录复制到持久目录，返回持久路径。

    用 file_id 命名而不是原始文件名，避免同名文件互相覆盖，
    也避免文件名里的特殊字符进入路径。
    """
    import shutil

    source_dir = PathlibPath(settings.pdf_source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    dest = source_dir / f"{file_id}.pdf"
    shutil.copy2(tmp_path, dest)
    logger.info(f"原始 PDF 已留存: {dest} (原名 {original_filename})")
    return str(dest)

# 加载图片URL映射表
_IMAGE_MAPPING = {}

def _load_image_mapping():
    """加载图片URL映射表"""
    global _IMAGE_MAPPING
    if not _IMAGE_MAPPING:
        try:
            mapping_file = PathlibPath(__file__).parent.parent.parent.parent / ".image_mapping.json"
            if mapping_file.exists():
                with open(mapping_file, "r", encoding="utf-8") as f:
                    _IMAGE_MAPPING = json.load(f)
                logger.info(f"Loaded {len(_IMAGE_MAPPING)} image mappings")
        except Exception as e:
            logger.warning(f"Failed to load image mapping: {e}")

def map_image_url_to_local(img_url: str) -> str:
    """
    将外部URL映射到本地图片路径
    ProcessOn CDN: https://tc-cdn.processon.com/wps/XXX -> docs/images/XXX.png
    """
    if not img_url:
        return ""

    # 如果已经是本地路径
    if not img_url.startswith('http'):
        return img_url if img_url.startswith('docs/') else f"docs/{img_url}"

    # 从映射表查找
    if img_url in _IMAGE_MAPPING:
        return _IMAGE_MAPPING[img_url]

    # 尝试从URL提取ID并构造本地路径
    if 'processon.com' in img_url and 'wps' in img_url:
        file_id = img_url.split('/')[-1]
        return f"docs/images/{file_id}.png"

    return img_url

_load_image_mapping()


def extract_markdown_images(text: str) -> list:
    """
    从markdown文本中提取图片链接
    支持格式: ![alt](url) 或 [text](url)
    """
    images = []

    # 匹配markdown链接（包括图片和普通链接）: [...](url)
    link_pattern = r'\[([^\]]*)\]\(([^)]+)\)'
    matches = re.finditer(link_pattern, text)

    for match in matches:
        alt_text = match.group(1)
        url = match.group(2)

        # 检查URL是否是图片（ProcessOn CDN或本地路径）
        if 'processon.com' in url or url.endswith(('.png', '.jpg', '.jpeg', '.gif')):
            local_path = map_image_url_to_local(url)
            images.append({
                "url": url,
                "local_path": local_path,
                "description": alt_text
            })

    return images

def get_rag_service():
    """获取单例RAG服务"""
    return RAGService()


@router.post("/ingest/file")
async def ingest_file(
    file: UploadFile = File(...),
    use_hospital_parser: bool = None,
    chunk_strategy: str = "auto",
    chunk_size: int = None,
    chunk_overlap: int = None,
    db: AsyncSession = Depends(get_db)
):
    """
    上传并入库文档

    Args:
        file: 上传的文件（支持.md, .pdf）
        use_hospital_parser: 是否使用医院级别的分割器（按医院边界切分）

    Returns:
        入库结果
    """
    try:
        # 验证文件类型
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No filename provided"
            )

        file.filename = _fix_mojibake_filename(file.filename)

        valid_extensions = {".md", ".markdown", ".pdf", ".txt"}
        file_ext = os.path.splitext(file.filename)[1].lower()

        if file_ext not in valid_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {file_ext}"
            )

        # 保存临时文件
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=file_ext,
            mode="wb"
        ) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file.flush()
            tmp_path = tmp_file.name

        # PDF 需要留存原文件：扫描件的页图和 OCR 结果都是从它派生的，
        # 后续重新入库或换 DPI 重跑都要用到。文本类文件没这个需求。
        source_pdf_path = None
        committed = False
        try:
            # 计算文件哈希用于检查重复
            import hashlib
            file_hash = hashlib.sha256(content).hexdigest()

            # 第一步：先创建数据库记录，获取 UUID（用作vector store的file_id）
            kb_service = KnowledgeBaseService(db)
            db_result = await kb_service.save_file_record(
                filename=file.filename,
                file_path=tmp_path,
                file_hash=file_hash,
                file_size=len(content),
                total_chunks=0,  # 暂时设为0，后续更新
                image_count=0,   # 暂时设为0，后续更新
                source_type="document",  # 暂时设为document，后续可能更新
                file_id=None  # 让系统生成UUID
            )

            if db_result.get("status") == "warning":
                # 文件已存在
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=db_result.get("message", "This file has already been ingested")
                )

            if db_result.get("status") == "error":
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=db_result.get("message", "Failed to save file record")
                )

            database_file_id = db_result.get("file_id")
            logger.info(f"Database file record created with id: {database_file_id}")

            # 第二步：使用 database_file_id 调用入库服务
            rag = get_rag_service()
            result = await rag.ingest_file(
                tmp_path,
                use_hospital_parser=use_hospital_parser is True,
                original_filename=file.filename,
                chunk_strategy=chunk_strategy if use_hospital_parser is not True else "hospital_markdown",
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                file_id=database_file_id,  # 传入数据库生成的UUID
            )

            if result.get("status") == "success":
                logger.info(
                    f"File ingested: {file.filename} "
                    f"(strategy={result.get('chunk_strategy')}, chunks={result.get('chunks')})"
                )

                # 第三步：更新数据库记录，补充chunks数量和其他信息
                chunks = result.get("chunks", 0)
                images = result.get("images", [])
                image_count = len(images)

                # 检测医院名称
                hospitals = result.get("hospitals", [])
                hospital_name = hospitals[0] if len(hospitals) == 1 else None

                from sqlalchemy import update
                from uuid import UUID
                from datetime import datetime

                # 判定来源类型：医院规则库 / 扫描版PDF / 普通文档
                pdf_info = result.get("pdf") or {}
                if result.get("chunk_strategy") == "hospital_markdown":
                    source_type = "hospital"
                elif pdf_info.get("is_scanned"):
                    source_type = "scanned_pdf"
                elif result.get("source_type") == "pdf":
                    source_type = "pdf"
                else:
                    source_type = "document"

                # 持久化原始 PDF，供页图服务与重新 OCR 使用
                if file_ext == ".pdf":
                    try:
                        source_pdf_path = _persist_source_pdf(tmp_path, database_file_id, file.filename)
                    except Exception as persist_error:
                        logger.warning(f"留存原始 PDF 失败（不影响入库）: {persist_error}")

                update_stmt = (
                    update(KnowledgeBaseFile)
                    .where(KnowledgeBaseFile.id == UUID(database_file_id))
                    .values(
                        total_chunks=chunks,
                        image_count=image_count,
                        source_type=source_type,
                        hospital_name=hospital_name,
                        original_file_path=source_pdf_path or tmp_path,
                        chunk_strategy=result.get("chunk_strategy", "character"),
                        chunk_strategy_version=result.get("chunk_strategy_version"),
                        chunk_size=result.get("chunk_size"),
                        chunk_overlap=result.get("chunk_overlap"),
                        metadata_json={
                            "parser_type": result.get("parser_type", "character"),
                            "chunk_strategy": result.get("chunk_strategy"),
                            "chunk_strategy_version": result.get("chunk_strategy_version"),
                            "chunk_size": result.get("chunk_size"),
                            "chunk_overlap": result.get("chunk_overlap"),
                            "hospitals": hospitals,
                            "analysis": result.get("analysis", {}),
                            "upload_path": file.filename,
                            "images_count": image_count,
                            "source_pdf_path": source_pdf_path,
                            "pdf": pdf_info or None,
                        }
                    )
                )
                await db.execute(update_stmt)
                await db.commit()
                committed = True
                logger.info(f"Database record updated for file_id: {database_file_id}")

                return {
                    "status": "success",
                    "filename": file.filename,
                    "chunks": chunks,
                    "images": image_count,
                    "file_id": database_file_id,
                    "parser_type": result.get("parser_type", "character"),
                    "chunk_strategy": result.get("chunk_strategy"),
                    "chunk_strategy_version": result.get("chunk_strategy_version"),
                    "chunk_size": result.get("chunk_size"),
                    "chunk_overlap": result.get("chunk_overlap"),
                    "hospitals": hospitals,
                    "analysis": result.get("analysis", {}),
                    "hospital_name": hospital_name,
                    "source_type": source_type,
                    "is_scanned": pdf_info.get("is_scanned"),
                    "page_count": pdf_info.get("page_count"),
                    "ocr_seconds": pdf_info.get("ocr_seconds"),
                    "message": f"Successfully ingested {chunks} chunks with {image_count} images"
                }
            else:
                # 入库失败，删除已创建的数据库记录
                from sqlalchemy import update
                from uuid import UUID
                from datetime import datetime

                delete_stmt = (
                    update(KnowledgeBaseFile)
                    .where(KnowledgeBaseFile.id == UUID(database_file_id))
                    .values(status="deleted", deleted_at=datetime.now())
                )
                await db.execute(delete_stmt)
                await db.commit()
                raise Exception(result.get("message"))

        finally:
            # 清理临时文件。已持久化的 PDF 不能删——它是页图和 OCR 结果的来源。
            if os.path.exists(tmp_path) and tmp_path != source_pdf_path:
                os.remove(tmp_path)

            # 入库没成功就不要留 PDF：数据库记录已被标记 deleted，
            # 留着孤儿文件既占空间，也会让 /pdf-page 接口拿到无主页图。
            if not committed and source_pdf_path and os.path.exists(source_pdf_path):
                try:
                    os.remove(source_pdf_path)
                    logger.info(f"入库失败，已清理留存 PDF: {source_pdf_path}")
                except OSError as cleanup_error:
                    logger.warning(f"清理留存 PDF 失败 {source_pdf_path}: {cleanup_error}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File ingestion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {str(e)}"
        )


@router.post("/search")
async def search(
    query: str,
    top_k: int = 5,
    user_dept: str = None,
    enable_intent: bool = True,  # 新增：是否启用意图识别
    db: AsyncSession = Depends(get_db)
):
    """
    搜索文档（支持返回图片 + 权限过滤 + 意图识别）

    Args:
        query: 查询文本
        top_k: 返回结果数
        user_dept: 用户所属部门（可选，用于权限过滤）
        enable_intent: 是否启用意图识别（默认True）

    Returns:
        搜索结果（包含图片信息）
    """
    try:
        if not query or len(query.strip()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query cannot be empty"
            )

        if top_k < 1 or top_k > 100:
            top_k = 5

        # 执行搜索（传递 user_dept 和 enable_intent）
        rag = get_rag_service()
        result = await rag.search(query, top_k=top_k, user_dept=user_dept, enable_intent=enable_intent)

        if result.get("status") == "error":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message")
            )

        # 增强搜索结果，添加图片信息
        from src.backend.ingestion.image_utils import format_search_result_with_images

        enhanced_results = []
        for i, res in enumerate(result.get("results", []), 1):
            # 检查结果中是否包含node对象
            enhanced = {
                "rank": i,
                "text": res.get("text", ""),
                "score": res.get("score", 0.0),
                "filename": res.get("metadata", {}).get("source") or res.get("metadata", {}).get("filename", "未知"),
                "hospital": res.get("metadata", {}).get("hospital", "未知医院"),
                "metadata": res.get("metadata", {}),
                "images": res.get("images", [])  # 直接使用 RAGService 返回的已丰富图片
            }

            enhanced_results.append(enhanced)

        result["results"] = enhanced_results

        # 记录搜索日志
        import time
        start_time = time.time()
        kb_service = KnowledgeBaseService(db)
        response_time_ms = int((time.time() - start_time) * 1000)

        image_count = sum(len(r.get("images", [])) for r in enhanced_results)
        await kb_service.log_search(
            query=query,
            result_count=len(enhanced_results),
            image_count=image_count,
            response_time_ms=response_time_ms
        )

        logger.info(f"Search: {query} -> {result.get('count')} results with {image_count} images")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@router.post("/qa")
async def generate_answer(
    query: str,
    top_k: int = 3,
    user_dept: str = None,
    enable_intent: bool = True,
    session_id: str = None,  # 新增：会话ID（可选）
    db: AsyncSession = Depends(get_db)
):
    """
    完整RAG: 搜索 + LLM生成答案（支持权限过滤 + 意图识别 + 会话历史）

    Args:
        query: 问题
        top_k: 检索结果数
        user_dept: 用户所属部门（可选，用于权限过滤）
        enable_intent: 是否启用意图识别（默认True）
        session_id: 会话ID（可选，传递则保存消息到会话）

    Returns:
        答案、来源和图片
    """
    try:
        if not query or len(query.strip()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query cannot be empty"
            )

        # 获取历史消息作为上下文（如果提供了session_id）
        from src.backend.db.models import ChatSession, ChatMessage
        from sqlalchemy import select
        from uuid import UUID

        history_context = []
        if session_id:
            try:
                # 获取最近10条消息作为上下文
                messages_result = await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == UUID(session_id))
                    .order_by(ChatMessage.created_at.desc())
                    .limit(10)
                )
                messages = list(reversed(messages_result.scalars().all()))
                history_context = [
                    {"role": msg.role, "content": msg.content}
                    for msg in messages
                ]
            except Exception as e:
                logger.warning(f"Failed to load history context: {e}")

        # 1. 先执行搜索获取来源文档和图片（传递 user_dept 和 enable_intent）
        rag = get_rag_service()
        search_result = await rag.search(query, top_k=top_k, user_dept=user_dept, enable_intent=enable_intent)

        logger.info(f"QA API - search_result keys: {search_result.get('results', [{}])[0].keys() if search_result.get('results') else 'no results'}")
        if search_result.get('results'):
            logger.info(f"QA API - first result images: {len(search_result['results'][0].get('images', []))}")

        # 2. 生成答案（传递 user_dept、enable_intent 和历史上下文）
        answer_result = await rag.generate_answer(
            query,
            top_k=top_k,
            user_dept=user_dept,
            enable_intent=enable_intent,
            history_context=history_context,  # 传递历史上下文
            search_result=search_result,
        )

        if answer_result.get("status") == "error":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=answer_result.get("message")
            )

        # 3. 增强返回结果 - 添加搜索结果中的图片和来源信息
        enhanced_result = {
            "status": "success",
            "answer": answer_result.get("answer", ""),
            "sources": search_result.get("results", []),
            "images": [],
            "fallback": answer_result.get("fallback", False),
            "diagnostics": answer_result.get("diagnostics"),
            "message": "Answer generated successfully"
        }

        # 从搜索结果中提取所有图片
        seen_images = set()
        all_images = []

        for result in search_result.get("results", []):
            for img in result.get("images", []):
                img_path = img.get("path", "")
                if img_path and img_path not in seen_images:
                    seen_images.add(img_path)
                    all_images.append({
                        "path": img_path,
                        "url": img.get("url", ""),
                        "description": img.get("description", ""),
                        "hospital": img.get("hospital", "")
                    })

        enhanced_result["images"] = all_images

        # 4. 如果提供了session_id，保存消息到数据库
        # 原文 fallback 仅用于当前响应，不作为正式助手答案持久化
        if session_id and not answer_result.get("fallback", False):
            try:
                from sqlalchemy import update

                # 保存用户消息
                user_message = ChatMessage(
                    session_id=UUID(session_id),
                    role="user",
                    content=query
                )
                db.add(user_message)

                # 保存助手回复
                assistant_message = ChatMessage(
                    session_id=UUID(session_id),
                    role="assistant",
                    content=enhanced_result["answer"],
                    sources=search_result.get("results", []),
                    images=all_images
                )
                db.add(assistant_message)

                # 更新会话的 updated_at 和 title（如果是第一条消息）
                session_result = await db.execute(
                    select(ChatSession).where(ChatSession.id == UUID(session_id))
                )
                session = session_result.scalar_one_or_none()

                if session:
                    # 如果标题还是"新对话"，用第一个问题作为标题
                    if session.title == "新对话":
                        title = query[:50] + "..." if len(query) > 50 else query
                        await db.execute(
                            update(ChatSession)
                            .where(ChatSession.id == UUID(session_id))
                            .values(title=title)
                        )

                await db.commit()
                logger.info(f"Messages saved to session {session_id}")
            except Exception as e:
                logger.error(f"Failed to save messages: {e}")
                await db.rollback()

        logger.info(f"Answer generated for: {query} ({len(enhanced_result['sources'])} sources, {len(all_images)} images)")
        return enhanced_result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Answer generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Answer generation failed: {str(e)}"
        )


@router.post("/qa/stream")
async def stream_qa(
    question: str,
    enable_intent: bool = True,
    user_dept: str = None,
    session_id: str = None,
    mode: str = None,
    db: AsyncSession = Depends(get_db)
):
    """
    流式问答接口 - 使用 SSE 返回思考过程和答案

    返回格式：
    data: {"type": "thinking", "content": "正在分析问题..."}
    data: {"type": "thinking", "content": "正在检索知识库..."}
    data: {"type": "answer", "content": "这是答案", "sources": [...], "images": [...]}
    data: {"type": "done"}
    """
    try:
        selected_mode = (mode or settings.rag_agent_default_mode).strip().lower()
        if selected_mode not in {"simple", "agent"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="mode must be 'simple' or 'agent'",
            )
        if selected_mode == "agent" and not settings.rag_agent_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="RAG agent mode is disabled",
            )

        logger.info(
            "Stream QA request - question: %s, dept: %s, session: %s, mode: %s",
            question,
            user_dept,
            session_id,
            selected_mode,
        )

        async def generate():
            try:
                # 1. 发送思考状态：分析问题
                yield f"data: {json.dumps({'type': 'thinking', 'content': '正在分析问题意图...'}, ensure_ascii=False)}\n\n"

                # 2. 获取会话历史
                history_context = []
                if session_id:
                    from sqlalchemy import select
                    from src.backend.db.models import ChatMessage

                    history_result = await db.execute(
                        select(ChatMessage)
                        .where(ChatMessage.session_id == session_id)
                        .order_by(ChatMessage.created_at.desc())
                        .limit(6)
                    )
                    history_messages = list(history_result.scalars().all())
                    history_messages.reverse()  # 恢复正序

                    if history_messages:
                        yield f"data: {json.dumps({'type': 'thinking', 'content': f'已加载 {len(history_messages)} 条历史消息'}, ensure_ascii=False)}\n\n"

                        for msg in history_messages:
                            history_context.append({
                                "role": msg.role,
                                "content": msg.content
                            })

                # 3. 发送思考状态：检索知识库
                yield f"data: {json.dumps({'type': 'thinking', 'content': '正在检索知识库...'}, ensure_ascii=False)}\n\n"

                # 5. 调用当前模式的流式 RAG 服务
                rag_service = RAGService()
                if selected_mode == "agent":
                    stream = RAGOrchestrator(rag_service).stream(
                        query=question,
                        top_k=3,
                        user_dept=user_dept,
                        enable_intent=enable_intent,
                        history_context=history_context,
                    )
                else:
                    stream = rag_service.generate_answer_stream(
                        query=question,
                        top_k=3,
                        user_dept=user_dept,
                        enable_intent=enable_intent,
                        history_context=history_context,
                    )

                full_answer = ""
                sources = []
                images = []
                fallback = False
                diagnostics = None

                async for chunk in stream:
                    if chunk["type"] == "thinking":
                        yield f"data: {json.dumps({'type': 'thinking', 'content': chunk['content']}, ensure_ascii=False)}\n\n"

                    elif chunk["type"] == "search_complete":
                        # 检索完成，显示结果
                        found_count = chunk.get("found_count", 0)
                        yield f"data: {json.dumps({'type': 'thinking', 'content': f'找到 {found_count} 个相关文档片段'}, ensure_ascii=False)}\n\n"
                        if found_count:
                            yield f"data: {json.dumps({'type': 'thinking', 'content': '正在生成答案...'}, ensure_ascii=False)}\n\n"

                    elif chunk["type"] == "answer_chunk":
                        # 流式推送答案片段
                        full_answer += chunk["content"]
                        yield f"data: {json.dumps({'type': 'answer_chunk', 'content': chunk['content']}, ensure_ascii=False)}\n\n"

                    elif chunk["type"] in {"answer", "answer_complete"}:
                        # 答案完成，获取来源和图片
                        full_answer = chunk["content"]
                        sources = chunk.get("sources", [])
                        images = chunk.get("images", [])
                        fallback = chunk.get("fallback", False)
                        diagnostics = chunk.get("diagnostics")
                        logger.info(f"DEBUG: Received answer_complete with {len(images)} images")
                        if images:
                            logger.info(f"DEBUG: First image: {images[0]}")

                    elif chunk["type"] == "error":
                        yield f"data: {json.dumps({'type': 'error', 'content': chunk['content']}, ensure_ascii=False)}\n\n"
                        yield 'data: {"type": "done"}\n\n'
                        return

                if not full_answer.strip():
                    yield f"data: {json.dumps({'type': 'error', 'content': '未收到有效答案，请重试。'}, ensure_ascii=False)}\n\n"
                    yield 'data: {"type": "done"}\n\n'
                    return

                # 6. 发送完整答案（包含来源和图片）
                answer_data = {
                    "type": "answer",
                    "content": full_answer,
                    "sources": sources,
                    "images": images,
                    "fallback": fallback,
                    "diagnostics": diagnostics,
                }
                yield f"data: {json.dumps(answer_data, ensure_ascii=False)}\n\n"

                # 原文 fallback 仅用于当前响应，不作为正式助手答案持久化
                if session_id and not fallback:
                    from src.backend.db.models import ChatMessage, ChatSession
                    from sqlalchemy import update
                    from uuid import UUID
                    import uuid as uuid_lib

                    # 保存用户消息
                    user_message = ChatMessage(
                        id=uuid_lib.uuid4(),
                        session_id=UUID(session_id),
                        role="user",
                        content=question
                    )
                    db.add(user_message)

                    # 保存助手回复
                    assistant_message = ChatMessage(
                        id=uuid_lib.uuid4(),
                        session_id=UUID(session_id),
                        role="assistant",
                        content=full_answer,
                        sources=sources[:5] if sources else None,
                        images=images[:6] if images else None
                    )
                    db.add(assistant_message)

                    # 更新会话标题（如果是新对话）
                    session_result = await db.execute(
                        select(ChatSession).where(ChatSession.id == UUID(session_id))
                    )
                    session = session_result.scalar_one_or_none()

                    if session and session.title == "新对话":
                        title = question[:50] if len(question) <= 50 else question[:47] + "..."
                        await db.execute(
                            update(ChatSession)
                            .where(ChatSession.id == UUID(session_id))
                            .values(title=title)
                        )

                    # 更新会话的 updated_at
                    await db.execute(
                        update(ChatSession)
                        .where(ChatSession.id == UUID(session_id))
                        .values(updated_at=assistant_message.created_at)
                    )

                    await db.commit()

                # 9. 发送完成信号
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

            except Exception as e:
                logger.error(f"Stream generation failed: {e}")
                yield f"data: {json.dumps({'type': 'error', 'content': f'生成失败: {str(e)}'}, ensure_ascii=False)}\n\n"
                yield 'data: {"type": "done"}\n\n'

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stream QA failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stream QA failed: {str(e)}"
        )


@router.get("/knowledge-base")
async def get_knowledge_base_list(
    db: AsyncSession = Depends(get_db)
):
    """
    获取知识库文件列表（包括图片信息）
    """
    try:
        kb_service = KnowledgeBaseService(db)
        result = await kb_service.get_file_stats_with_images()
        return result
    except Exception as e:
        logger.error(f"Failed to get knowledge base list: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get knowledge base list: {str(e)}"
        )


@router.get("/knowledge-base/stats")
async def get_knowledge_base_stats(
    db: AsyncSession = Depends(get_db)
):
    """
    获取知识库统计信息（包括图片统计）
    """
    try:
        kb_service = KnowledgeBaseService(db)
        result = await kb_service.get_file_stats_with_images()
        return result
    except Exception as e:
        logger.error(f"Failed to get KB stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get knowledge base stats: {str(e)}"
        )


@router.delete("/knowledge-base/{file_id}")
async def delete_knowledge_base_file(
    file_id: str = Path(..., description="文件ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    删除知识库文件

    Args:
        file_id: 文件ID

    Returns:
        删除结果
    """
    try:
        # 1. 从Qdrant删除chunks
        rag = get_rag_service()
        rag_result = await rag.delete_file_chunks(file_id)

        if rag_result.get("status") == "error":
            logger.error(f"Failed to delete chunks from Qdrant: {rag_result}")
            raise Exception(f"Failed to delete chunks from Qdrant")

        # 2. 从数据库删除文件记录
        kb_service = KnowledgeBaseService(db)
        db_result = await kb_service.delete_file(file_id)

        if db_result.get("status") == "error":
            raise Exception(db_result.get("message"))

        deleted_chunks = rag_result.get("deleted_chunks", 0)
        logger.info(f"File deleted: {file_id}, {deleted_chunks} chunks removed")

        return {
            "status": "success",
            "file_id": file_id,
            "deleted_chunks": deleted_chunks,
            "message": f"Successfully deleted file and {deleted_chunks} chunks"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file: {str(e)}"
        )


@router.post("/knowledge-base/sync")
async def sync_chunks_to_database(db: AsyncSession = Depends(get_db)):
    """
    将Qdrant中的chunks同步到数据库
    用于修复数据不一致的情况
    """
    try:
        logger.info("Starting sync from Qdrant to database...")

        rag = get_rag_service()
        result = await rag.sync_chunks_to_db(db)

        return result

    except Exception as e:
        logger.error(f"Failed to sync chunks: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync: {str(e)}"
        )
