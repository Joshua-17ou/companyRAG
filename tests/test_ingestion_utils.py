"""Tests for:
- _fix_mojibake_filename: GBK/UTF-8 multipart filename repair
- ANSWER_GENERATION_PROMPT: template integrity and constraint rules
- ScannedPdfParser + _merge_short_chunks: duplicate-line regression
"""
import unittest

from llama_index.core.schema import Document

from src.backend.api.routes.ingestion import _fix_mojibake_filename
from src.backend.agent.prompts import ANSWER_GENERATION_PROMPT
from src.backend.ingestion.chunking import (
    _merge_short_chunks,
    _pack_lines,
    _strip_leading_overlap,
    split_document,
)
from llama_index.core.schema import TextNode


# ---------------------------------------------------------------------------
# _fix_mojibake_filename
# ---------------------------------------------------------------------------

class MojibakeFilenameTests(unittest.TestCase):
    def test_gbk_encoded_filename_is_repaired(self):
        # "销售_手册_呼吸介入手册.pdf" encoded as GBK bytes, then mis-decoded as Latin-1
        garbled = "ÏúÊÛ_ÊÖ²á_ºôÎü½éÈëÊÖ²á.pdf"
        self.assertEqual(_fix_mojibake_filename(garbled), "销售_手册_呼吸介入手册.pdf")

    def test_normal_utf8_chinese_filename_is_unchanged(self):
        name = "正常文件名.pdf"
        self.assertEqual(_fix_mojibake_filename(name), name)

    def test_ascii_filename_is_unchanged(self):
        name = "report.pdf"
        self.assertEqual(_fix_mojibake_filename(name), name)

    def test_already_correct_chinese_with_underscore_is_unchanged(self):
        name = "销售_指南_SPD操作指南.md"
        self.assertEqual(_fix_mojibake_filename(name), name)

    def test_empty_string_is_unchanged(self):
        self.assertEqual(_fix_mojibake_filename(""), "")

    def test_pure_ascii_with_extension_is_unchanged(self):
        name = "2024_Q1_report.xlsx"
        self.assertEqual(_fix_mojibake_filename(name), name)

    def test_result_contains_no_latin1_garbage_chars(self):
        garbled = "ÏúÊÛ_ÊÖ²á_ºôÎü½éÈëÊÖ²á.pdf"
        fixed = _fix_mojibake_filename(garbled)
        # None of the garbage chars should survive
        for ch in "ÏúÊÛÊÖ²áºôÎü½éÈë":
            self.assertNotIn(ch, fixed)


# ---------------------------------------------------------------------------
# ANSWER_GENERATION_PROMPT
# ---------------------------------------------------------------------------

class AnswerPromptTests(unittest.TestCase):
    def _render(self, query="测试问题", context="文档内容"):
        return ANSWER_GENERATION_PROMPT.format(query=query, context_text=context)

    def test_template_renders_without_error(self):
        rendered = self._render()
        self.assertIsInstance(rendered, str)
        self.assertGreater(len(rendered), 0)

    def test_query_and_context_appear_in_output(self):
        rendered = self._render(query="出库流程", context="出库步骤A")
        self.assertIn("出库流程", rendered)
        self.assertIn("出库步骤A", rendered)

    def test_no_unfilled_placeholders_remain(self):
        rendered = self._render()
        self.assertNotIn("{query}", rendered)
        self.assertNotIn("{context_text}", rendered)

    def test_irrelevant_content_constraint_is_present(self):
        # Rule 7 must be in the prompt: ignore unrelated chunks
        self.assertIn("与问题无关的片段直接忽略", ANSWER_GENERATION_PROMPT)

    def test_no_topic_expansion_constraint_is_present(self):
        # Rule 8 must be in the prompt: no off-topic expansion
        self.assertIn("不要把问题引向", ANSWER_GENERATION_PROMPT)

    def test_evidence_insufficiency_constraint_is_present(self):
        # Rule 5: state what is missing, do not fill in from common knowledge
        self.assertIn("文档证据不足时明确说明", ANSWER_GENERATION_PROMPT)

    def test_image_path_constraint_is_present(self):
        # Rule 3: image path must not be modified
        self.assertIn("括号内路径一个字符都不能修改", ANSWER_GENERATION_PROMPT)

    def test_relevance_pre_filter_instruction_is_present(self):
        # The pre-amble about self-filtering before answering
        self.assertIn("相关性判断", ANSWER_GENERATION_PROMPT)

    def test_braces_in_template_are_only_placeholders(self):
        # Confirm there are no extra un-escaped braces that would break .format()
        import string
        formatter = string.Formatter()
        field_names = [fname for _, fname, _, _ in formatter.parse(ANSWER_GENERATION_PROMPT) if fname is not None]
        self.assertCountEqual(field_names, ["query", "context_text"])


# ---------------------------------------------------------------------------
# ScannedPdfParser + _merge_short_chunks duplicate-line regression
# ---------------------------------------------------------------------------

class MergeShortChunksTests(unittest.TestCase):
    def _node(self, text, page_no=1):
        node = TextNode(text=text)
        node.metadata["page_no"] = page_no
        return node

    def test_short_trailing_chunk_is_merged_into_previous(self):
        prev = self._node("A\nB\nC")
        short = self._node("D", page_no=1)
        merged = _merge_short_chunks([prev, short], min_chars=80)
        self.assertEqual(len(merged), 1)
        self.assertIn("D", merged[0].text)

    def test_cross_page_chunks_are_not_merged(self):
        prev = self._node("A\nB\nC", page_no=1)
        short = self._node("D", page_no=2)
        merged = _merge_short_chunks([prev, short], min_chars=80)
        self.assertEqual(len(merged), 2)

    def test_no_duplicate_lines_after_merge(self):
        # Regression: _pack_lines adds overlap rows to the next chunk's start.
        # If that next chunk is short and gets merged back, the overlap row
        # appeared twice in the same chunk. _strip_leading_overlap must prevent that.
        prev = self._node("行一\n行二\n行三\n行四\n最后行")
        # short chunk starts with a line that also ends prev (simulating overlap)
        short = self._node("最后行\n备注", page_no=1)
        merged = _merge_short_chunks([prev, short], min_chars=80)
        lines = merged[0].text.split("\n")
        # "最后行" must appear exactly once
        self.assertEqual(lines.count("最后行"), 1)

    def test_long_chunk_is_not_merged(self):
        prev = self._node("A" * 100)
        long_chunk = self._node("B" * 100)
        merged = _merge_short_chunks([prev, long_chunk], min_chars=80)
        self.assertEqual(len(merged), 2)


class StripLeadingOverlapTests(unittest.TestCase):
    def test_removes_exact_overlap(self):
        prev = "行一\n行二\n行三"
        text = "行三\n行四"
        self.assertEqual(_strip_leading_overlap(prev, text), "行四")

    def test_no_overlap_returns_full_text(self):
        prev = "行一\n行二"
        text = "行三\n行四"
        self.assertEqual(_strip_leading_overlap(prev, text), "行三\n行四")

    def test_multi_line_overlap_removed(self):
        prev = "A\nB\nC\nD"
        text = "C\nD\nE"
        self.assertEqual(_strip_leading_overlap(prev, text), "E")


class ScannedPdfParserRegressionTests(unittest.TestCase):
    def _make_page_text(self, page_no, lines):
        return f"<!-- page:{page_no} -->\n" + "\n".join(lines)

    def test_no_duplicate_lines_introduced_by_merge(self):
        # Regression: when _pack_lines splits a page and the last chunk is short,
        # _merge_short_chunks absorbs it into the previous chunk. Before the fix,
        # the overlap row that opens the short chunk (already present at the end of
        # the previous chunk) appeared twice. Construct a page that forces the split.

        # Vary the rows so they are not inherently identical, and make the page
        # long enough to cross the 512-char chunk boundary
        rows = [f"iB{200+i} | 22 | 1.65 | {700+i*10}±30 | 10-{20+i} | 1.{i}" for i in range(14)]
        footer = "备注：红色标注为常规选用型号"
        text = self._make_page_text(1, rows + [footer])
        result = split_document(Document(text=text), strategy="auto")

        for node in result.nodes:
            chunk_lines = [l for l in node.text.split("\n") if l.strip()]
            for i in range(len(chunk_lines) - 1):
                self.assertNotEqual(
                    chunk_lines[i], chunk_lines[i + 1],
                    msg=f"Duplicate adjacent line introduced by merge: {chunk_lines[i]!r}"
                )

    def test_scanned_strategy_selected_for_page_marker_text(self):
        text = "<!-- page:1 -->\n内容"
        result = split_document(Document(text=text), strategy="auto")
        self.assertEqual(result.strategy, "scanned_pdf")

    def test_each_chunk_has_correct_page_no_metadata(self):
        p1 = self._make_page_text(1, ["第一页内容"])
        p2 = self._make_page_text(2, ["第二页内容"])
        result = split_document(Document(text=p1 + "\n\n" + p2), strategy="auto")
        page_nos = {node.metadata.get("page_no") for node in result.nodes}
        self.assertIn(1, page_nos)
        self.assertIn(2, page_nos)
        # No chunk should span two pages
        for node in result.nodes:
            self.assertIn(node.metadata.get("page_no"), (1, 2))

    def test_table_row_is_never_split_mid_row(self):
        # A row like "iB219 | 21 | 1.65 | ..." must appear whole, never just "iB219"
        table_rows = [f"iB{200+i} | 22 | 1.65 | 715±30 | 10-30 | 1.7" for i in range(12)]
        text = self._make_page_text(5, table_rows)
        result = split_document(Document(text=text), strategy="auto")
        for node in result.nodes:
            for line in node.text.split("\n"):
                stripped = line.strip()
                # Any fragment that looks like a broken table value alone is a failure
                self.assertNotRegex(stripped, r"^\d+\.\d+$", msg=f"Broken numeric fragment: {stripped!r}")
                self.assertNotRegex(stripped, r"^\d+$", msg=f"Isolated number fragment: {stripped!r}")


if __name__ == "__main__":
    unittest.main()
