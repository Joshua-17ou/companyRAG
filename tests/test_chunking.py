import json
import unittest
from pathlib import Path

from llama_index.core.schema import Document

from src.backend.ingestion.chunking import (
    ChunkConfig,
    build_chunk_config,
    detect_strategy,
    split_document,
)


class ChunkingStrategyTests(unittest.TestCase):
    def test_detects_hospital_strategy_from_content_not_filename(self):
        sample = Path("docs/销售_指南_医院送货检查指南.md").read_text(encoding="utf-8")
        self.assertEqual(detect_strategy(sample), "hospital_markdown")

    def test_detects_hospital_strategy_for_non_hospital_filename(self):
        text = "# 医院SPD\n\n## 和祐医院\n出库流程"
        self.assertEqual(detect_strategy(text), "hospital_markdown")

    def test_detects_markdown_and_character_strategies(self):
        self.assertEqual(detect_strategy("# 标题\n\n正文"), "markdown")
        self.assertEqual(detect_strategy("没有标题的普通文本"), "character")

    def test_chunk_config_validates_bounds(self):
        self.assertEqual(build_chunk_config().size, 512)
        with self.assertRaises(ValueError):
            ChunkConfig(size=0)
        with self.assertRaises(ValueError):
            ChunkConfig(size=10, overlap=10)

    def test_hospital_parse_preserves_hospital_metadata(self):
        document = Document(text="## 和祐医院\n出库流程\n## 中山三院\n验收流程")
        result = split_document(document, strategy="auto")
        self.assertEqual(result.strategy, "hospital_markdown")
        self.assertEqual(set(result.hospitals), {"和祐医院", "中山三院"})
        self.assertTrue(all(node.metadata.get("hospital") for node in result.nodes))

    def test_explicit_character_strategy_overrides_auto(self):
        document = Document(text="## 和祐医院\n出库流程")
        result = split_document(document, strategy="character")
        self.assertEqual(result.strategy, "character")
        self.assertFalse(result.hospitals)

    def test_scanned_pdf_never_splits_a_line(self):
        """扫描件切分必须整行搬运，表格行是回归重点。

        OCR 把表格的每个单元格识别成独立一行，若按字符位置硬切，
        一行数据会被劈成两半。真实数据上发生过：`iB219 | 21 | 1.` /
        `65 | 715±30 | ...`，两个 chunk 都成了废文本。
        """
        text = _real_page_text("13")
        result = split_document(Document(text=text), strategy="auto")

        self.assertEqual(result.strategy, "scanned_pdf")
        # 不得出现被腰斩的数值残片
        for node in result.nodes:
            for line in node.text.split("\n"):
                stripped = line.strip()
                self.assertNotEqual(stripped, "1.")
                self.assertNotEqual(stripped, "65")
                self.assertNotEqual(stripped, "92")
        # 每个型号行都必须完整出现在某一个 chunk 里
        for model in ("iS217", "iB219", "iB229P"):
            self.assertTrue(
                any(model in node.text for node in result.nodes),
                f"{model} 这一行没能完整保留",
            )

    def test_scanned_pdf_chunks_carry_single_page_number(self):
        text = "<!-- page:1 -->\n第一页内容\n<!-- page:2 -->\n第二页内容"
        result = split_document(Document(text=text), strategy="auto")

        self.assertEqual(result.strategy, "scanned_pdf")
        self.assertEqual(len(result.nodes), 2)
        # 跨页拼接会让 chunk 无法对应单一 bbox，高亮就失效了
        for node in result.nodes:
            self.assertIn(node.metadata["page_no"], (1, 2))
        self.assertEqual(
            [node.metadata["page_no"] for node in result.nodes], [1, 2]
        )


def _real_page_text(page_no: str) -> str:
    """从 OCR sidecar 里取真实页文本，未命中文件名或抓不到时跳过。"""
    for candidate in Path("docs/pdf_pages").glob("*/ocr.json"):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        page = payload.get("pages", {}).get(page_no)
        if page and page.get("lines"):
            lines = [line["text"] for line in page["lines"] if line["text"].strip()]
            return f"<!-- page:{page_no} -->\n" + "\n".join(lines)
    raise unittest.SkipTest("找不到可用的 OCR sidecar 夹具")


if __name__ == "__main__":
    unittest.main()
