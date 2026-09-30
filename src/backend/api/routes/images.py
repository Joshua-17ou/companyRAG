"""
图片服务API路由
支持权限控制、访问日志、缓存等
"""
from fastapi import APIRouter, HTTPException, status, Depends, Path
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path as PathlibPath
import os
from datetime import datetime

from src.backend.db.database import get_db
from src.backend.core.logger import logger

router = APIRouter()


def validate_image_path(image_name: str) -> PathlibPath:
    """
    验证图片路径安全性（防止路径遍历攻击）
    """
    # 确保只包含允许的字符
    if ".." in image_name or image_name.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image name"
        )

    # 构建完整路径
    project_root = PathlibPath(__file__).parent.parent.parent.parent.parent
    image_dir = project_root / "docs" / "images"
    file_path = image_dir / image_name

    # 验证路径确实在images目录内
    try:
        file_path.resolve().relative_to(image_dir.resolve())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: path outside allowed directory"
        )

    return file_path


@router.get("/images/{image_name}")
async def get_image(
    image_name: str = Path(..., description="图片文件名，如：692ea35fe7be6c03a7e182e9.png"),
    db: AsyncSession = Depends(get_db)
):
    """
    获取图片

    支持功能：
    - 路径安全验证（防止遍历攻击）
    - 访问日志记录
    - 浏览器缓存支持
    - CORS跨域支持

    Args:
        image_name: 图片文件名

    Returns:
        图片文件流
    """
    try:
        # 1. 验证图片名称格式
        if not image_name or len(image_name) > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image name"
            )

        # 2. 验证路径安全性
        file_path = validate_image_path(image_name)

        # 3. 检查文件是否存在
        if not file_path.exists():
            logger.warning(f"Image not found: {image_name}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Image not found: {image_name}"
            )

        if not file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image path"
            )

        # 4. 记录访问日志
        file_size = file_path.stat().st_size
        logger.info(
            f"Image accessed: {image_name} "
            f"(size: {file_size} bytes, time: {datetime.now().isoformat()})"
        )

        # 5. 返回文件
        # Cache-Control: max-age=3600 表示浏览器缓存1小时
        # 这样相同的图片不会重复下载
        return FileResponse(
            path=file_path,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",  # 缓存1小时
                "ETag": f'"{file_path.stat().st_mtime}"',  # 文件修改时间作为ETag
            },
            filename=image_name
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get image {image_name}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve image"
        )


@router.get("/images/hospital/{hospital_name}")
async def list_hospital_images(
    hospital_name: str = Path(..., description="医院名称"),
    db: AsyncSession = Depends(get_db)
):
    """
    获取特定医院相关的所有图片

    Args:
        hospital_name: 医院名称（如：中山三院）

    Returns:
        该医院相关的图片列表
    """
    try:
        from src.backend.ingestion.rag_service import RAGService

        rag = RAGService()

        # 构建查询来获取该医院的所有chunks
        query = f"医院SPD > {hospital_name}"
        result = await rag.search(query, top_k=100)

        if result.get("status") == "error":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message")
            )

        # 收集所有图片
        all_images = []
        seen_images = set()  # 避免重复

        for res in result.get("results", []):
            images = res.get("images", [])
            for img in images:
                img_path = img.get("path", "")
                if img_path not in seen_images:
                    seen_images.add(img_path)
                    all_images.append({
                        "name": img_path.replace("images/", ""),
                        "path": img_path,
                        "url": f"/api/images/{img_path.replace('images/', '')}",
                        "hospital": img.get("hospital", hospital_name)
                    })

        logger.info(
            f"Listed {len(all_images)} images for hospital: {hospital_name}"
        )

        return {
            "status": "success",
            "hospital": hospital_name,
            "image_count": len(all_images),
            "images": all_images
        }

    except Exception as e:
        logger.error(f"Failed to list images for hospital {hospital_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list images: {str(e)}"
        )


@router.head("/images/{image_name}")
async def check_image(
    image_name: str = Path(..., description="图片文件名"),
    db: AsyncSession = Depends(get_db)
):
    """
    检查图片是否存在（HEAD请求）
    前端可用此判断图片是否可用

    Returns:
        200 if image exists, 404 otherwise
    """
    try:
        file_path = validate_image_path(image_name)

        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found"
            )

        return {"status": "exists"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check image {image_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check image"
        )


# ---------------------------------------------------------------------------
# 扫描版 PDF 页图服务
# ---------------------------------------------------------------------------

def validate_pdf_page_path(file_id: str, page_no: int) -> PathlibPath:
    """校验并返回某页页图的路径。

    file_id 是数据库 UUID，只允许十六进制与连字符；
    page_no 由 FastAPI 转成 int，天然排除注入。两者都过一遍白名单，
    避免拼出 docs/pdf_pages 之外的路径。
    """
    if not file_id or len(file_id) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file id"
        )

    allowed = set("0123456789abcdefABCDEF-")
    if not set(file_id) <= allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file id"
        )

    if page_no < 1 or page_no > 100000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid page number"
        )

    from src.backend.core.config import settings

    pages_dir = PathlibPath(settings.pdf_pages_dir).resolve()
    file_path = pages_dir / file_id / f"page_{page_no:04d}.png"

    try:
        file_path.resolve().relative_to(pages_dir)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: path outside allowed directory"
        )

    return file_path


@router.get("/pdf-page/{file_id}/meta")
async def get_pdf_page_meta(
    file_id: str = Path(..., description="入库文件ID (UUID)"),
    db: AsyncSession = Depends(get_db)
):
    """返回该 PDF 的 OCR sidecar（每页尺寸 + 每行 bbox）。

    bbox 体积大，不放进向量库 metadata，所以前端要按需拉这个接口。

    注意：本路由必须声明在 `/pdf-page/{file_id}/{page_no}` 之前。
    FastAPI 按声明顺序匹配，`{page_no}` 是 int 转换器，会把字面量
    `meta` 当成非法整数直接 422，导致下面那条路由永远命中不到。
    """
    if not file_id or len(file_id) > 64 or not set(file_id) <= set("0123456789abcdefABCDEF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file id"
        )

    from src.backend.core.config import settings

    pages_dir = PathlibPath(settings.pdf_pages_dir).resolve()
    sidecar_path = pages_dir / file_id / "ocr.json"

    if not sidecar_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OCR result not found for file {file_id}"
        )

    try:
        import json
        content = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read OCR sidecar for {file_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read OCR result"
        )

    # 文本对前端没用（正文已经通过检索返回了），去掉可以省不少带宽
    for page in content.get("pages", {}).values():
        for line in page.get("lines", []):
            line.pop("text", None)

    return {"status": "success", **content}


@router.get("/pdf-page/{file_id}/{page_no}")
async def get_pdf_page(
    file_id: str = Path(..., description="入库文件ID (UUID)"),
    page_no: int = Path(..., ge=1, description="页码，从1开始"),
    db: AsyncSession = Depends(get_db)
):
    """获取扫描版 PDF 的某页渲染图。

    前端拿着检索结果里的 page_no 调这个接口拿整页图，
    再按 `显示宽 / page_width` 缩放 ocr.json 里的 bbox 画高亮框。
    """
    try:
        file_path = validate_pdf_page_path(file_id, page_no)

        if not file_path.exists() or not file_path.is_file():
            logger.warning(f"PDF page image not found: {file_id} p{page_no}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Page {page_no} not found for file {file_id}"
            )

        logger.info(f"PDF page accessed: {file_id} p{page_no} ({file_path.stat().st_size} bytes)")

        # 页图由源 PDF 派生，只要不重新入库就不会变，可以长缓存
        return FileResponse(
            path=file_path,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",
                "ETag": f'"{file_path.stat().st_mtime}"',
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get PDF page {file_id} p{page_no}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve page image"
        )
