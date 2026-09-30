"""扫描版 PDF 的 OCR 提取与页图渲染。

职责边界：
- 本模块只负责「PDF → 页图 + 带 bbox 的文本」
- 不负责切分、向量化、入库（那是 rag_service 的事）

关键约束：bbox 位于**渲染后的图片像素坐标系**。因此每页必须同时记录
渲染 DPI 与图片宽高，前端才能按 `显示宽 / 原图宽` 缩放高亮框。
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 判定为扫描件的阈值：抽样页的平均字符数低于此值即视为无文本层
DEFAULT_SCANNED_MIN_CHARS = 50
DEFAULT_DPI = 200
DEFAULT_LANG = "ch"
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_WORKERS = 4


# 文档配置档案（不同文档类型的专用参数）
DOCUMENT_PROFILES = {
    "default": {
        "dpi": 200,
        "min_confidence": 0.0,
        "noise_band_ratio": 0.05,
        "noise_max_chars": 12,
        "table_min_cells": 3,
        "table_min_gap_ratio": 0.015,
        "table_align_tolerance_ratio": 0.03,
        "table_max_cell_width_ratio": 0.16,
    },
    "medical_scan": {
        "dpi": 300,  # 医学影像需要更高分辨率
        "min_confidence": 0.6,  # 医学文档要求更高质量
        "noise_band_ratio": 0.08,  # 影像文档页脚更宽
        "noise_max_chars": 15,
        "table_min_cells": 3,
        "table_min_gap_ratio": 0.015,
        "table_align_tolerance_ratio": 0.03,
        "table_max_cell_width_ratio": 0.16,
    },
    "dense_table": {
        "dpi": 200,
        "min_confidence": 0.0,
        "noise_band_ratio": 0.05,
        "noise_max_chars": 12,
        "table_min_cells": 2,  # 有些窄表只有2列
        "table_min_gap_ratio": 0.01,  # 列间隙更小
        "table_align_tolerance_ratio": 0.04,  # 放宽对齐容差
        "table_max_cell_width_ratio": 0.20,  # 允许更宽的单元格
    },
}


def get_profile(profile_name: str) -> Dict:
    """获取文档配置档案，不存在则返回默认配置。"""
    return DOCUMENT_PROFILES.get(profile_name, DOCUMENT_PROFILES["default"])


@dataclass
class ProcessingMetrics:
    """处理质量指标，用于监控与优化。"""
    total_duration_sec: float
    avg_page_duration_sec: float
    ocr_confidence_mean: float
    ocr_confidence_p50: float
    ocr_confidence_min: float
    table_rows_detected: int
    noise_lines_filtered: int
    pages_with_low_confidence: List[int] = field(default_factory=list)
    failed_pages: List[Tuple[int, str]] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "total_duration_sec": round(self.total_duration_sec, 2),
            "avg_page_duration_sec": round(self.avg_page_duration_sec, 2),
            "ocr_confidence_mean": round(self.ocr_confidence_mean, 3),
            "ocr_confidence_p50": round(self.ocr_confidence_p50, 3),
            "ocr_confidence_min": round(self.ocr_confidence_min, 3),
            "table_rows_detected": self.table_rows_detected,
            "noise_lines_filtered": self.noise_lines_filtered,
            "pages_with_low_confidence": self.pages_with_low_confidence,
            "failed_pages": [(p, str(e)) for p, e in self.failed_pages],
        }


@dataclass
class PageProcessingError(Exception):
    """单页处理失败，携带页码与原因。"""
    page_no: int
    reason: str

    def __str__(self) -> str:
        return f"页 {self.page_no} 处理失败: {self.reason}"


@dataclass
class OcrLine:
    """一行 OCR 结果。bbox 为渲染图上的像素坐标 [x0, y0, x1, y1]。"""
    text: str
    bbox: List[float]
    confidence: float

    def to_dict(self) -> Dict:
        return {"text": self.text, "bbox": self.bbox, "confidence": self.confidence}


@dataclass
class PageResult:
    """单页的完整结果。"""
    page_no: int  # 1-based
    image_path: Path
    width: int
    height: int
    dpi: int
    lines: List[OcrLine] = field(default_factory=list)

    def table_rows(self) -> List[List[OcrLine]]:
        """本页识别出的表格行组（见 group_table_rows）。

        注意：此方法使用默认参数。如需使用配置档案参数，
        应从 ScannedPdfProcessor 实例调用 group_table_rows。
        """
        return group_table_rows(self.lines, self.width)

    def blocks(self) -> List[str]:
        """把本页拆成若干**不可分割**的文本块，按阅读顺序排列。

        表格行是整体一块：OCR 把每个单元格识别成独立一行，若交给
        下游按字数硬切，一行数据会被劈成两半（实测 `AK-82-00 2.70
        2.16 2.` / `92 1.51 0.55 1.55`），两半都是废文本。这里先
        用 bbox 把同一表格行的单元格拼回一行并整体输出，下游只要
        以块为单位聚合，就永远不会切裂表格。

        非表格行各自成块，保持原有阅读顺序；表格行组占据其首行位置。
        """
        rows = self.table_rows()
        # 表格行里的每一行 OCR 结果 -> 它所属的行组
        row_index: Dict[int, List[OcrLine]] = {}
        for group in rows:
            for line in group:
                row_index[id(line)] = group

        blocks: List[str] = []
        emitted: set = set()
        for line in self.lines:
            if not line.text.strip():
                continue
            group = row_index.get(id(line))
            if group is None:
                blocks.append(line.text.strip())
                continue
            key = id(group)
            if key in emitted:
                continue
            emitted.add(key)
            blocks.append(render_table_row(group))
        return blocks

    @property
    def text(self) -> str:
        return "\n".join(self.blocks())

    def to_dict(self) -> Dict:
        return {
            "page_no": self.page_no,
            "image_path": str(self.image_path),
            "width": self.width,
            "height": self.height,
            "dpi": self.dpi,
            "lines": [line.to_dict() for line in self.lines],
        }


@dataclass
class ScannedPdfResult:
    """整份 PDF 的结果。"""
    file_id: str
    total_pages: int
    dpi: int
    pages: List[PageResult] = field(default_factory=list)
    text_layer: Dict = field(default_factory=dict)
    metrics: Optional[ProcessingMetrics] = None

    @property
    def is_scanned(self) -> bool:
        return bool(self.text_layer.get("looks_scanned"))

    def to_markdown(self) -> str:
        """把各页文本拼成一份带页码标记的 Markdown。

        页码标记是必要的：切分后仍然能从文本反推内容来自哪一页，
        用于在节点 metadata 缺失时兜底定位。
        """
        parts = []
        for page in self.pages:
            if not page.text.strip():
                continue
            parts.append(f"<!-- page:{page.page_no} -->\n{page.text}")
        return "\n\n".join(parts)


def _bbox_of(line: OcrLine) -> Tuple[float, float, float, float]:
    box = line.bbox or [0.0, 0.0, 0.0, 0.0]
    return box[0], box[1], box[2], box[3]


def is_noise_line(
    line: OcrLine,
    page_width: int,
    page_height: int,
    band_ratio: float = 0.05,
    max_chars: int = 12,
) -> bool:
    """判断一行是否为页眉/页脚噪声（页码、书名脚、装饰符）。

    判据必须**同时**满足，避免误杀正文：
    1. 落在页面上下边缘带内（band_ratio 以内）
    2. 文本很短
    3. 内容长得像页码：纯数字、页码前缀词、或纯符号

    只满足 1、2 不丢——正文里的短句（如"术前"）也可能贴边。
    所以第 3 条是真正的闸门。
    """
    text = line.text.strip()
    if not text:
        return True
    if len(text) > max_chars:
        return False

    x0, y0, x1, y1 = _bbox_of(line)
    margin = page_height * band_ratio
    if not (y1 <= margin or y0 >= page_height - margin):
        return False

    # 纯数字 / 数字带分隔符
    if re.fullmatch(r"[\d\s\-–—/.,]+", text):
        return True
    # "page 12" / "第 12 页" / "12 / 20"
    if re.fullmatch(
        r"(?i)(page|p\.?|第)?\s*[\d\s\-–—/.,]*\s*(页|of)?\s*[\d\s\-–—/.,]*",
        text,
    ) and re.search(r"\d", text):
        return True
    # 纯符号/单字符装饰（如 "|"、"\page" 的残留反斜杠）
    if re.fullmatch(r"[\\|/·•\-–—_\s]+", text):
        return True
    return False


def filter_noise_lines(
    lines: List[OcrLine],
    page_width: int,
    page_height: int,
    band_ratio: float = 0.05,
    max_chars: int = 12,
) -> List[OcrLine]:
    """去掉页眉/页脚噪声行。返回新列表，不改原对象。"""
    kept = [
        line for line in lines
        if not is_noise_line(line, page_width, page_height, band_ratio, max_chars)
    ]
    dropped = len(lines) - len(kept)
    if dropped:
        logger.debug(f"过滤页眉页脚噪声 {dropped} 行")
    return kept


def group_table_rows(
    lines: List[OcrLine],
    page_width: int,
    y_tolerance_ratio: float = 0.004,
    min_cells: int = 3,
    min_gap_ratio: float = 0.015,
    min_aligned_rows: int = 2,
    align_tolerance_ratio: float = 0.03,
    max_cell_width_ratio: float = 0.16,
) -> List[List[OcrLine]]:
    """把同一表格行里的多个单元格行聚成一组，返回若干行组。

    为什么需要这一步：OCR 把表格的每个单元格识别成独立一行。切分器按
    字符数硬切时会把一行数据劈成两半（实测发生过：`AK-82-00 2.70 2.16 2.`
    / `92 1.51 0.55 1.55`），两个 chunk 都成了废文本。把整行作为不可
    分割单元交给下游，这类切裂就不会发生。

    判据分两层：

    1. **横向成行**：一个 y 带内存在 >= min_cells 个彼此有水平间隙的
       单元格。间隙是必要的，否则可能是同一段连续文字被 OCR 拆成了
       多个片段，那种情况不该当表格行处理。
    2. **纵向对齐**：这些行必须至少与另一行共享列位置（单元格左边界
       落在容差内）。这一层专门用来排除误判——手册里常见两块并排的
       图文（如 `3 | 建立经肺实质稳定工作通道 | 4 | 技术兼容性强`）、
       或者标题行里混进 logo，它们偶然也在同一 y 带上，但没有跨行
       对齐的列，不是表格。

    Returns:
        行组列表（只含通过两层判据的），组内按 x 排序，组间按 y 排序。
    """
    if len(lines) < min_cells or page_width <= 0:
        return []

    def center_y(line: OcrLine) -> float:
        _, y0, _, y1 = _bbox_of(line)
        return (y0 + y1) / 2

    ordered = sorted(lines, key=lambda l: (center_y(l), _bbox_of(l)[0]))
    page_height = max((_bbox_of(l)[3] for l in lines), default=0)
    tolerance = max(1.0, page_height * y_tolerance_ratio)

    bands: List[List[OcrLine]] = []
    for line in ordered:
        if bands and abs(center_y(line) - center_y(bands[-1][-1])) <= tolerance:
            bands[-1].append(line)
        else:
            bands.append([line])

    min_gap = page_width * min_gap_ratio
    candidates: List[List[OcrLine]] = []
    for band in bands:
        if len(band) < min_cells:
            continue
        band.sort(key=lambda l: _bbox_of(l)[0])
        gaps = [
            _bbox_of(band[i + 1])[0] - _bbox_of(band[i])[2]
            for i in range(len(band) - 1)
        ]
        if max(gaps) < min_gap:
            continue
        candidates.append(band)

    if len(candidates) < min_aligned_rows:
        return []

    # 列对齐判定：两行共享某一列，当且仅当各自存在单元格左边界落在
    # 容差内。对每行统计它与其余行的最大对齐数，够 min_aligned_rows
    # 才认为它属于表格。
    align_tolerance = page_width * align_tolerance_ratio

    def aligns(a: List[OcrLine], b: List[OcrLine]) -> bool:
        a_lefts = [_bbox_of(l)[0] for l in a]
        b_lefts = [_bbox_of(l)[0] for l in b]
        matched = sum(
            1 for x in a_lefts
            if any(abs(x - y) <= align_tolerance for y in b_lefts)
        )
        # 至少两个列位置重合，才排除"偶然一列对上"的情况
        return matched >= 2

    rows = [
        row for row in candidates
        if sum(1 for other in candidates if other is not row and aligns(row, other))
        >= min_aligned_rows - 1
    ]

    # 排除"编号 + 长句"式的并排图文块（如 `3 | 建立经肺实质稳定工作通道 |
    # 4 | 技术兼容性强`）：它们的前导序号恰好跨块对齐，看着像表格行。
    #
    # 用**单元格宽度**而不是文字长度来区分，因为长度不可分：真实表头
    # 里 `穿刺针芯露出扩展器长度`（10 字）比误判块里的 `技术兼容性强`
    # （6 字）还长，任何长度阈值都会同时切掉两者。宽度则泾渭分明——
    # 实测误判块含一个占页宽 0.22~0.24 的宽单元，而真实表格的所有
    # 单元格都 <= 0.14。表格单元格本质是一列，不可能占掉四分之一页。
    def is_tabular(row: List[OcrLine]) -> bool:
        for line in row:
            x0, _, x1, _ = _bbox_of(line)
            if (x1 - x0) / page_width > max_cell_width_ratio:
                return False
        return True

    rows = [row for row in rows if is_tabular(row)]
    rows.sort(key=lambda r: center_y(r[0]))
    return rows


def render_table_row(row: List[OcrLine]) -> str:
    """把一个表格行组渲染成单行文本，用 ` | ` 分隔单元格。

    分隔符选 ` | ` 是为了让检索仍能命中单个单元格的值，同时保留
    "这些值属于同一行"的语义。
    """
    return " | ".join(l.text.strip() for l in row if l.text.strip())


def normalize_bbox(box) -> List[float]:
    """把四边形/多边形/数组统一成 [x0, y0, x1, y1]。"""
    if box is None:
        return [0.0, 0.0, 0.0, 0.0]
    try:
        if hasattr(box, "tolist"):
            box = box.tolist()
        if box and isinstance(box[0], (list, tuple)):
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            return [min(xs), min(ys), max(xs), max(ys)]
        if len(box) >= 4:
            x0, y0, x1, y1 = box[0], box[1], box[2], box[3]
            return [min(float(x0), float(x1)), min(float(y0), float(y1)),
                    max(float(x0), float(x1)), max(float(y0), float(y1))]
    except (TypeError, ValueError, IndexError):
        pass
    return [0.0, 0.0, 0.0, 0.0]


def detect_text_layer(doc, sample_pages: int = 5) -> Dict:
    """抽样检测 PDF 是否已有文本层，用于区分电子版与扫描件。"""
    total = doc.page_count
    if total == 0:
        return {"sampled_pages": 0, "chars_per_page": [], "avg_chars_per_page": 0,
                "looks_scanned": True}

    indices = list(range(min(sample_pages, total)))
    per_page = [len(doc[i].get_text().strip()) for i in indices]
    total_chars = sum(per_page)
    avg = total_chars / len(indices) if indices else 0
    return {
        "sampled_pages": len(indices),
        "chars_per_page": per_page,
        "avg_chars_per_page": round(avg, 1),
        "looks_scanned": avg < DEFAULT_SCANNED_MIN_CHARS,
    }


class _OcrEngine:
    """RapidOCR 的薄封装。

    用 RapidOCR（PP-OCR 模型的 ONNXRuntime 实现）而不是 PaddleOCR：
    paddlepaddle 2.6.x 的预编译轮子在缺少 AVX-512 的 CPU 上会在
    `SelfAttentionFusePass` 触发 SIGILL（12 代酷睿消费级芯片已被 Intel
    屏蔽 AVX-512），且该崩溃发生在建图阶段，无法用运行时开关绕过。
    ONNXRuntime 按 CPU 特性分发内核，没有这个问题。
    """

    def __init__(self, lang: str = DEFAULT_LANG):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as error:
            raise RuntimeError(
                "缺少 RapidOCR，请安装: pip install rapidocr-onnxruntime"
            ) from error

        logger.info(f"RapidOCR 加载中 (lang={lang})")
        self.engine = RapidOCR()

    def run(self, image_path: Path) -> List[OcrLine]:
        # RapidOCR 直接吃图片路径；第二项是耗时数组，这里用不上
        raw, _elapse = self.engine(str(image_path))
        lines: List[OcrLine] = []
        for entry in (raw or []):
            box, text, score = entry[0], entry[1], entry[2]
            lines.append(OcrLine(
                text=str(text),
                bbox=normalize_bbox(box),
                confidence=float(score),
            ))
        return lines


class ScannedPdfProcessor:
    """扫描版 PDF 处理器：渲染页图 + OCR。

    每次调用创建一个实例即可，PaddleOCR 引擎在实例内部复用。
    """

    def __init__(
        self,
        pages_dir: Path,
        dpi: int = DEFAULT_DPI,
        lang: str = DEFAULT_LANG,
        min_confidence: float = 0.0,
        text_layer_min_chars: int = DEFAULT_SCANNED_MIN_CHARS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_workers: int = DEFAULT_MAX_WORKERS,
        profile: Optional[str] = None,
    ):
        self.pages_dir = Path(pages_dir)
        self.lang = lang
        self.text_layer_min_chars = text_layer_min_chars
        self.max_retries = max_retries
        self.max_workers = max_workers
        self._engine: Optional[_OcrEngine] = None
        self._noise_lines_filtered = 0

        # 应用配置档案
        profile_config = get_profile(profile or "default")
        self.dpi = dpi if dpi != DEFAULT_DPI else profile_config["dpi"]
        self.min_confidence = min_confidence if min_confidence > 0 else profile_config["min_confidence"]
        self.noise_band_ratio = profile_config["noise_band_ratio"]
        self.noise_max_chars = profile_config["noise_max_chars"]
        self.table_params = {
            "min_cells": profile_config["table_min_cells"],
            "min_gap_ratio": profile_config["table_min_gap_ratio"],
            "align_tolerance_ratio": profile_config["table_align_tolerance_ratio"],
            "max_cell_width_ratio": profile_config["table_max_cell_width_ratio"],
        }

    def __enter__(self):
        """上下文管理器支持，用于资源管理。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出时记录磁盘使用情况（不删除页图，前端需要显示）。"""
        if exc_type is None:
            disk_usage = self._compute_disk_usage()
            if disk_usage:
                logger.info(
                    f"OCR 处理器退出: 页图目录 {self.pages_dir} 占用 {disk_usage['total_mb']:.1f}MB, "
                    f"{disk_usage['file_count']} 个文件"
                )
        return False

    def _compute_disk_usage(self) -> Optional[Dict]:
        """计算页图目录磁盘使用量。"""
        if not self.pages_dir.exists():
            return None
        total_bytes = 0
        file_count = 0
        for item in self.pages_dir.rglob("*"):
            if item.is_file():
                total_bytes += item.stat().st_size
                file_count += 1
        return {
            "total_mb": total_bytes / (1024 * 1024),
            "total_bytes": total_bytes,
            "file_count": file_count,
        }

    def cleanup_file_pages(self, file_id: str, keep_ocr_json: bool = True) -> Dict:
        """可选的资源清理接口：删除指定文档的页图（保留 ocr.json）。

        注意：此方法只应在明确不需要前端显示页图时调用。
        正常流程下页图应该保留，供前端查询结果高亮显示使用。

        Returns:
            清理统计：删除的文件数、释放的空间
        """
        file_dir = self.pages_dir / file_id
        if not file_dir.exists():
            return {"deleted_files": 0, "freed_mb": 0.0}

        deleted = 0
        freed_bytes = 0
        for item in file_dir.iterdir():
            if item.is_file() and item.name.startswith("page_") and item.suffix == ".png":
                freed_bytes += item.stat().st_size
                item.unlink()
                deleted += 1
            elif not keep_ocr_json and item.name == "ocr.json":
                freed_bytes += item.stat().st_size
                item.unlink()
                deleted += 1

        logger.info(f"清理 {file_id} 页图: 删除 {deleted} 个文件, 释放 {freed_bytes / (1024 * 1024):.1f}MB")
        return {"deleted_files": deleted, "freed_mb": freed_bytes / (1024 * 1024)}

    def _get_engine(self) -> _OcrEngine:
        # 延迟初始化：先跑文本层检测，只有确认是扫描件才加载 OCR 引擎
        if self._engine is None:
            self._engine = _OcrEngine(self.lang)
        return self._engine

    def inspect(self, pdf_path: Path, sample_pages: int = 5) -> Dict:
        """只做文本层检测，不加载 OCR 引擎。用于上传时快速判断。"""
        import fitz

        doc = fitz.open(str(pdf_path))
        try:
            info = detect_text_layer(doc, sample_pages)
            info["looks_scanned"] = info["avg_chars_per_page"] < self.text_layer_min_chars
            return info
        finally:
            doc.close()

    def process(
        self,
        pdf_path: Path,
        file_id: str,
        page_spec: str = "",
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> ScannedPdfResult:
        """渲染并 OCR 整份 PDF，支持并发与失败重试。

        Args:
            page_spec: 页码表达式如 '1-5,8'，空字符串表示全部页
            progress_cb: 可选回调 (page_no, total, stage)，用于上报进度
        """
        import fitz

        pdf_path = Path(pdf_path)
        start_time = time.time()

        doc = fitz.open(str(pdf_path))
        try:
            total = doc.page_count
            text_layer = detect_text_layer(doc)
            text_layer["looks_scanned"] = (
                text_layer["avg_chars_per_page"] < self.text_layer_min_chars
            )
            pages = _parse_page_spec(page_spec, total)

            output_dir = self.pages_dir / file_id
            output_dir.mkdir(parents=True, exist_ok=True)

            result = ScannedPdfResult(
                file_id=file_id,
                total_pages=total,
                dpi=self.dpi,
                text_layer=text_layer,
            )

            # 先渲染所有页图（串行，避免 fitz 并发问题）
            page_images: Dict[int, Tuple[Path, int, int]] = {}
            for page_no in pages:
                if progress_cb:
                    progress_cb(page_no, total, "rendering")
                page_images[page_no] = self._render_page(doc, page_no, output_dir)

            doc.close()  # 提前关闭 PDF，释放文件句柄

            # 并发 OCR 处理
            if self.max_workers > 1:
                result.pages = self._process_pages_concurrent(
                    page_images, file_id, total, progress_cb
                )
            else:
                result.pages = self._process_pages_sequential(
                    page_images, file_id, total, progress_cb
                )

            # 计算处理指标
            duration = time.time() - start_time
            result.metrics = self._compute_metrics(result, duration)

            logger.info(
                f"PDF {file_id} 处理完成: {len(result.pages)}/{total} 页成功, "
                f"耗时 {duration:.1f}s, OCR置信度均值 {result.metrics.ocr_confidence_mean:.3f}"
            )

            self._write_sidecar(result, output_dir)
            return result
        except Exception:
            doc.close()
            raise

    def _render_page(self, doc, page_no: int, output_dir: Path) -> Tuple[Path, int, int]:
        import fitz

        page = doc[page_no - 1]
        zoom = self.dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image_path = output_dir / f"page_{page_no:04d}.png"
        pix.save(str(image_path))
        return image_path, pix.width, pix.height

    def _process_pages_sequential(
        self,
        page_images: Dict[int, Tuple[Path, int, int]],
        file_id: str,
        total: int,
        progress_cb: Optional[Callable[[int, int, str], None]],
    ) -> List[PageResult]:
        """串行处理页面（兜底方案）。"""
        engine = self._get_engine()
        pages = []
        for page_no, (image_path, width, height) in sorted(page_images.items()):
            try:
                if progress_cb:
                    progress_cb(page_no, total, "ocr")
                page_result = self._process_single_page(
                    engine, page_no, image_path, width, height
                )
                pages.append(page_result)
            except Exception as e:
                logger.error(f"PDF {file_id} 第 {page_no} 页处理失败: {e}", exc_info=True)
        return pages

    def _process_pages_concurrent(
        self,
        page_images: Dict[int, Tuple[Path, int, int]],
        file_id: str,
        total: int,
        progress_cb: Optional[Callable[[int, int, str], None]],
    ) -> List[PageResult]:
        """并发处理页面，带重试机制。"""
        pages_dict: Dict[int, PageResult] = {}
        failed_pages: List[Tuple[int, str]] = []

        # RapidOCR 引擎可能有线程安全问题，每个 worker 独立创建
        def process_with_engine(page_no: int, image_path: Path, width: int, height: int):
            engine = _OcrEngine(self.lang)
            for attempt in range(self.max_retries):
                try:
                    if progress_cb:
                        progress_cb(page_no, total, "ocr")
                    return self._process_single_page(engine, page_no, image_path, width, height)
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        logger.error(
                            f"PDF {file_id} 第 {page_no} 页处理失败 "
                            f"(重试 {self.max_retries} 次后放弃): {e}",
                            exc_info=True,
                        )
                        raise PageProcessingError(page_no, str(e))
                    logger.warning(
                        f"PDF {file_id} 第 {page_no} 页处理失败 (重试 {attempt + 1}/{self.max_retries}): {e}"
                    )
                    time.sleep(0.5 * (attempt + 1))  # 指数退避

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(process_with_engine, page_no, *data): page_no
                for page_no, data in page_images.items()
            }
            for future in as_completed(futures):
                page_no = futures[future]
                try:
                    page_result = future.result()
                    pages_dict[page_no] = page_result
                except PageProcessingError as e:
                    failed_pages.append((e.page_no, e.reason))

        if failed_pages:
            logger.warning(
                f"PDF {file_id} 处理完成但有 {len(failed_pages)} 页失败: "
                f"{[p for p, _ in failed_pages]}"
            )

        # 按页码排序返回
        return [pages_dict[page_no] for page_no in sorted(pages_dict.keys())]

    def _process_single_page(
        self,
        engine: _OcrEngine,
        page_no: int,
        image_path: Path,
        width: int,
        height: int,
    ) -> PageResult:
        """处理单页：OCR + 噪声过滤。"""
        lines = engine.run(image_path)

        # 置信度过滤
        if self.min_confidence > 0:
            before = len(lines)
            lines = [l for l in lines if l.confidence >= self.min_confidence]
            if before > len(lines):
                logger.debug(f"页 {page_no} 低置信度过滤: {before} -> {len(lines)} 行")

        # 页眉页脚过滤（使用配置档案参数）
        before = len(lines)
        lines = filter_noise_lines(
            lines, width, height,
            band_ratio=self.noise_band_ratio,
            max_chars=self.noise_max_chars,
        )
        filtered = before - len(lines)
        self._noise_lines_filtered += filtered

        logger.info(
            f"页 {page_no} 完成: {len(lines)} 行, "
            f"{sum(len(l.text) for l in lines)} 字符, "
            f"过滤噪声 {filtered} 行"
        )

        return PageResult(
            page_no=page_no,
            image_path=image_path,
            width=width,
            height=height,
            dpi=self.dpi,
            lines=lines,
        )

    def _compute_metrics(self, result: ScannedPdfResult, duration: float) -> ProcessingMetrics:
        """计算处理质量指标。"""
        if not result.pages:
            return ProcessingMetrics(
                total_duration_sec=duration,
                avg_page_duration_sec=0.0,
                ocr_confidence_mean=0.0,
                ocr_confidence_p50=0.0,
                ocr_confidence_min=0.0,
                table_rows_detected=0,
                noise_lines_filtered=self._noise_lines_filtered,
            )

        confidences = [line.confidence for page in result.pages for line in page.lines]
        if not confidences:
            confidences = [0.0]

        table_rows = sum(len(page.table_rows()) for page in result.pages)
        low_conf_pages = [
            page.page_no for page in result.pages
            if page.lines and sum(l.confidence for l in page.lines) / len(page.lines) < 0.7
        ]

        return ProcessingMetrics(
            total_duration_sec=duration,
            avg_page_duration_sec=duration / len(result.pages),
            ocr_confidence_mean=sum(confidences) / len(confidences),
            ocr_confidence_p50=sorted(confidences)[len(confidences) // 2],
            ocr_confidence_min=min(confidences),
            table_rows_detected=table_rows,
            noise_lines_filtered=self._noise_lines_filtered,
            pages_with_low_confidence=low_conf_pages,
        )

    def _write_sidecar(self, result: ScannedPdfResult, output_dir: Path) -> None:
        """把 bbox 和指标落到磁盘。

        向量库里只存页码和文本，bbox 坐标体积大（一页几十到几百行），
        放进 metadata 会显著撑大 Qdrant 载荷。放在 sidecar 文件里，
        前端打开某页时按页读取即可。
        """
        sidecar = {
            "file_id": result.file_id,
            "total_pages": result.total_pages,
            "dpi": result.dpi,
            "text_layer": result.text_layer,
            "pages": {str(p.page_no): p.to_dict() for p in result.pages},
            "metrics": result.metrics.to_dict() if result.metrics else None,
        }
        (output_dir / "ocr.json").write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _parse_page_spec(spec: str, total: int) -> List[int]:
    """把 '1-5,8' 解析成 1-based 页码列表，空串表示全部。"""
    if not spec:
        return list(range(1, total + 1))
    pages: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, _, end = part.partition("-")
            try:
                pages.extend(range(int(start), int(end) + 1))
            except ValueError:
                logger.warning(f"忽略非法页码片段: {part}")
        else:
            try:
                pages.append(int(part))
            except ValueError:
                logger.warning(f"忽略非法页码片段: {part}")
    seen = set()
    ordered = []
    for p in pages:
        if 1 <= p <= total and p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def locate_page_in_text(text: str) -> Optional[int]:
    """从切分后的文本里反查页码标记。

    切分可能把 `<!-- page:N -->` 标记切到别的块，所以这只是兜底手段。
    """
    import re

    match = re.search(r"<!--\s*page:(\d+)\s*-->", text)
    return int(match.group(1)) if match else None


def line_bbox_at(text: str, offset: int, page: PageResult) -> Optional[List[float]]:
    """文本块内某个偏移位置对应的行 bbox。

    用于把 chunk 的字符区间映射回页面上的矩形区域。
    """
    if not page.lines:
        return None
    cursor = 0
    for line in page.lines:
        end = cursor + len(line.text)
        if cursor <= offset < end:
            return line.bbox
        cursor = end + 1  # 换行符
    return page.lines[-1].bbox if page.lines else None
