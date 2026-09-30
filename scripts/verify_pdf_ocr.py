"""扫描版 PDF OCR 可行性验证脚本（独立运行，不依赖 src/）。

用法:
    python scripts/verify_pdf_ocr.py <pdf路径> [--pages 1-5] [--dpi 200] [--out _inspect_pdf_ocr]

产出:
    <out>/page_0001.png          渲染后的页面图
    <out>/page_0001_boxes.png    叠加了 OCR 识别框的预览图
    <out>/page_0001.json         该页的 OCR 原始结果（含 bbox）
    <out>/report.json            汇总：每页文本量、耗时、平均置信度

目的：在改动任何现有代码之前，先肉眼确认中文识别质量与框的定位是否准确。
"""
import argparse
import json
import sys
import time
from pathlib import Path


def parse_pages(spec: str, total: int) -> list:
    """把 '1-5,8' 这类页码表达式解析成 1-based 页码列表。"""
    if not spec:
        return list(range(1, total + 1))
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, _, end = part.partition("-")
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(part))
    return [p for p in pages if 1 <= p <= total]


def load_pdf_pages(pdf_path: Path):
    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("缺少 PyMuPDF，请先执行: pip install pymupdf")
    return fitz.open(str(pdf_path))


def detect_text_layer(doc, sample_pages: int = 5) -> dict:
    """检测 PDF 是否已有文本层，用于判断是不是扫描件。"""
    total = doc.page_count
    indices = list(range(min(sample_pages, total)))
    per_page = []
    for i in indices:
        text = doc[i].get_text().strip()
        per_page.append(len(text))
    total_chars = sum(per_page)
    return {
        "sampled_pages": len(indices),
        "chars_per_page": per_page,
        "avg_chars_per_page": round(total_chars / len(indices), 1) if indices else 0,
        "looks_scanned": (total_chars / len(indices) < 50) if indices else True,
    }


def render_page(doc, page_no: int, dpi: int, out_dir: Path) -> tuple:
    """渲染单页为 PNG，返回 (路径, 宽, 高)。"""
    import fitz

    page = doc[page_no - 1]
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    png_path = out_dir / f"page_{page_no:04d}.png"
    pix.save(str(png_path))
    return png_path, pix.width, pix.height


def build_ocr_engine(lang: str):
    """构建 RapidOCR 引擎。

    用 RapidOCR（PP-OCR 模型的 ONNXRuntime 实现）而非 PaddleOCR：
    paddlepaddle 2.6.x 的预编译轮子在缺少 AVX-512 的 CPU 上会在建图阶段
    SIGILL，且无法用运行时开关绕过。ONNXRuntime 按 CPU 特性分发内核。
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        sys.exit("缺少 RapidOCR，请先执行: pip install rapidocr-onnxruntime")

    print(f"  RapidOCR (ONNXRuntime)，lang={lang}")
    return RapidOCR()


def run_ocr(engine, image_path: Path) -> list:
    """执行 OCR，归一化为 [{text, bbox, confidence}]。"""
    raw, _elapse = engine(str(image_path))
    return [
        {
            "text": str(entry[1]),
            "bbox": to_bbox(entry[0]),
            "confidence": float(entry[2]),
        }
        for entry in (raw or [])
    ]


def to_bbox(box) -> list:
    """把四边形或多边形统一成 [x0, y0, x1, y1]。"""
    if box is None:
        return [0, 0, 0, 0]
    try:
        if hasattr(box, "tolist"):
            box = box.tolist()
        # 嵌套一层的情况，如 [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]
        if box and isinstance(box[0], (list, tuple)):
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            return [min(xs), min(ys), max(xs), max(ys)]
        if len(box) >= 4:
            x0, y0, x1, y1 = box[0], box[1], box[2], box[3]
            return [float(min(x0, x1)), float(min(y0, y1)),
                    float(max(x0, x1)), float(max(y0, y1))]
    except Exception:
        pass
    return [0, 0, 0, 0]


def draw_boxes(image_path: Path, items: list, out_path: Path, page_size: tuple):
    """把 OCR 框画到页面上，用于肉眼校验定位是否准确。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  ⚠ 缺少 Pillow，跳过可视化输出")
        return False

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for item in items:
        x0, y0, x1, y1 = item["bbox"]
        if x1 <= x0 or y1 <= y0:
            continue
        color = (0, 200, 0) if item["confidence"] >= 0.9 else (255, 140, 0)
        draw.rectangle([x0, y0, x1, y1], outline=color, width=3)
    img.save(out_path)
    return True


def main():
    parser = argparse.ArgumentParser(description="扫描版 PDF OCR 验证")
    parser.add_argument("pdf", help="PDF 文件路径")
    parser.add_argument("--pages", default="", help="页码，如 1-5,8（默认全部）")
    parser.add_argument("--dpi", type=int, default=200, help="渲染 DPI，默认 200")
    parser.add_argument("--lang", default="ch", help="OCR 语言，默认 ch")
    parser.add_argument("--out", default="_inspect_pdf_ocr", help="输出目录")
    parser.add_argument("--max-pages", type=int, default=10, help="最多处理多少页，默认 10")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"文件不存在: {pdf_path}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("扫描版 PDF OCR 验证")
    print("=" * 60)
    print(f"文件: {pdf_path}")
    print(f"大小: {pdf_path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"输出: {out_dir.resolve()}")
    print()

    t0 = time.time()
    doc = load_pdf_pages(pdf_path)
    print(f"总页数: {doc.page_count}")

    # 1. 文本层检测
    print("\n[1/4] 检测文本层...")
    text_info = detect_text_layer(doc)
    print(f"  抽样 {text_info['sampled_pages']} 页，"
          f"平均每页 {text_info['avg_chars_per_page']} 字符")
    if text_info["looks_scanned"]:
        print("  → 判定为【扫描件】，需要 OCR")
    else:
        print("  → 判定为【电子版 PDF】，已有文本层，OCR 可能非必需")
        print("     提示: 电子版可直接提取文本 + 坐标，无需渲染和 OCR")

    # 2. 渲染
    pages = parse_pages(args.pages, doc.page_count)[:args.max_pages]
    print(f"\n[2/4] 渲染页面 (dpi={args.dpi})，共 {len(pages)} 页...")
    rendered = {}
    for page_no in pages:
        png_path, width, height = render_page(doc, page_no, args.dpi, out_dir)
        rendered[page_no] = {
            "png": png_path,
            "width": width,
            "height": height,
            "size_kb": round(png_path.stat().st_size / 1024, 1),
        }
        print(f"  第 {page_no} 页: {width}x{height}, "
              f"{rendered[page_no]['size_kb']} KB → {png_path.name}")

    render_elapsed = time.time() - t0

    # 3. OCR
    print(f"\n[3/4] 加载 OCR 引擎 (lang={args.lang})...")
    engine = build_ocr_engine(args.lang)

    print(f"\n[4/4] 逐页 OCR...")
    report = {
        "pdf": str(pdf_path),
        "total_pages": doc.page_count,
        "dpi": args.dpi,
        "text_layer": text_info,
        "pages": [],
    }

    ocr_t0 = time.time()
    total_chars = 0
    all_confidences = []

    for page_no in pages:
        info = rendered[page_no]
        page_t0 = time.time()
        items = run_ocr(engine, info["png"])
        page_elapsed = time.time() - page_t0

        chars = sum(len(i["text"]) for i in items)
        total_chars += chars
        confidences = [i["confidence"] for i in items]
        all_confidences.extend(confidences)
        avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

        json_path = out_dir / f"page_{page_no:04d}.json"
        json_path.write_text(
            json.dumps({
                "page_no": page_no,
                "width": info["width"],
                "height": info["height"],
                "dpi": args.dpi,
                "items": items,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        boxes_path = out_dir / f"page_{page_no:04d}_boxes.png"
        drew = draw_boxes(info["png"], items, boxes_path, (info["width"], info["height"]))

        low_conf = [i for i in items if i["confidence"] < 0.8]
        print(f"  第 {page_no} 页: {len(items)} 行, {chars} 字符, "
              f"平均置信度 {avg_conf:.3f}, 耗时 {page_elapsed:.1f}s")
        if low_conf:
            print(f"    ⚠ {len(low_conf)} 行置信度 < 0.8")

        report["pages"].append({
            "page_no": page_no,
            "width": info["width"],
            "height": info["height"],
            "png_kb": info["size_kb"],
            "line_count": len(items),
            "char_count": chars,
            "avg_confidence": avg_conf,
            "low_confidence_lines": len(low_conf),
            "elapsed_seconds": round(page_elapsed, 2),
            "boxes_preview": boxes_path.name if drew else None,
        })

    ocr_elapsed = time.time() - ocr_t0
    total_elapsed = time.time() - t0

    avg_conf_all = round(sum(all_confidences) / len(all_confidences), 3) if all_confidences else 0.0
    report["summary"] = {
        "pages_processed": len(pages),
        "total_chars": total_chars,
        "avg_confidence": avg_conf_all,
        "ocr_seconds": round(ocr_elapsed, 1),
        "total_seconds": round(total_elapsed, 1),
        "per_page_ocr_seconds": round(ocr_elapsed / len(pages), 2) if pages else 0,
        "extrapolated_full_doc_minutes": round(
            (ocr_elapsed / len(pages)) * doc.page_count / 60, 1
        ) if pages else 0,
    }

    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 终端预览第一页前几行，方便快速判断质量
    if pages:
        first = json.loads((out_dir / f"page_{pages[0]:04d}.json").read_text(encoding="utf-8"))
        print(f"\n--- 第 {pages[0]} 页识别预览（前 10 行）---")
        for item in first["items"][:10]:
            bbox = [round(v) for v in item["bbox"]]
            print(f"  [{item['confidence']:.2f}] {bbox} {item['text'][:60]}")

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    print(f"  处理页数:      {len(pages)}")
    print(f"  总字符数:      {total_chars}")
    print(f"  平均置信度:    {avg_conf_all}")
    print(f"  渲染耗时:      {render_elapsed:.1f}s")
    print(f"  OCR 耗时:      {ocr_elapsed:.1f}s ({report['summary']['per_page_ocr_seconds']}s/页)")
    print(f"  总耗时:        {total_elapsed:.1f}s")
    print(f"  全文预估:      {report['summary']['extrapolated_full_doc_minutes']} 分钟")
    print()
    print(f"输出目录: {out_dir.resolve()}")
    print("  → 打开 *_boxes.png 肉眼检查识别框位置是否准确")
    print("  → 打开 *.json 查看完整识别文本和 bbox 坐标")
    print("  → report.json 为汇总报告")

    doc.close()


if __name__ == "__main__":
    main()
