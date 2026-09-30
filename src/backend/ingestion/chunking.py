"""Configurable document chunking strategies and parser registry."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol
import re

from llama_index.core.node_parser import SimpleNodeParser
from llama_index.core.schema import Document, TextNode

from src.backend.ingestion.hospital_mapping import find_hospital_in_text
from src.backend.ingestion.hospital_parser import HospitalDocumentParser

DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 50
STRATEGY_VERSIONS = {
    "hospital_markdown": "hospital_markdown_v1",
    "markdown": "markdown_v1",
    "character": "character_v1",
    "scanned_pdf": "scanned_pdf_v1",
}


@dataclass(frozen=True)
class ChunkConfig:
    size: int = DEFAULT_CHUNK_SIZE
    overlap: int = DEFAULT_CHUNK_OVERLAP

    def __post_init__(self):
        if self.size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        if self.overlap < 0 or self.overlap >= self.size:
            raise ValueError("chunk_overlap must be nonnegative and smaller than chunk_size")


@dataclass
class ParserContext:
    file_path: Path
    image_descriptions: Dict[str, str] = field(default_factory=dict)


@dataclass
class ParseResult:
    nodes: List[TextNode]
    strategy: str
    version: str
    hospitals: List[str] = field(default_factory=list)
    image_paths: List[str] = field(default_factory=list)
    analysis: Dict[str, Any] = field(default_factory=dict)


class DocumentParser(Protocol):
    strategy: str

    def parse(self, document: Document, config: ChunkConfig, context: ParserContext) -> ParseResult:
        ...


class CharacterParser:
    strategy = "character"

    def parse(self, document: Document, config: ChunkConfig, context: ParserContext) -> ParseResult:
        parser = SimpleNodeParser.from_defaults(
            chunk_size=config.size,
            chunk_overlap=config.overlap,
        )
        nodes = parser.get_nodes_from_documents([document])
        return ParseResult(
            nodes=nodes,
            strategy=self.strategy,
            version=STRATEGY_VERSIONS[self.strategy],
            analysis={"heading_count": len(re.findall(r"^#{1,6}\s+.+$", document.text, re.MULTILINE))},
        )


class MarkdownParser(CharacterParser):
    strategy = "markdown"


class HospitalMarkdownParser:
    strategy = "hospital_markdown"

    def parse(self, document: Document, config: ChunkConfig, context: ParserContext) -> ParseResult:
        nodes = HospitalDocumentParser.parse_documents_by_hospital(
            documents=[document],
            chunk_size=config.size,
            chunk_overlap=config.overlap,
            image_descriptions=context.image_descriptions,
        )
        hospitals = sorted({node.metadata.get("hospital") for node in nodes if node.metadata.get("hospital")})
        image_paths = sorted({path for node in nodes for path in node.metadata.get("image_paths", [])})
        return ParseResult(
            nodes=nodes,
            strategy=self.strategy,
            version=STRATEGY_VERSIONS[self.strategy],
            hospitals=hospitals,
            image_paths=image_paths,
            analysis={"hospital_count": len(hospitals), "image_count": len(image_paths)},
        )


class ScannedPdfParser:
    """扫描版 PDF 专用切分器。

    与 CharacterParser 的差别：OCR 出来的文本没有 markdown 结构，
    但**有页码边界**。这里的策略是先在页内切分，再按页拼接，
    保证每个 chunk 都能追溯到确定的页码——这是前端高亮的前提。
    跨页拼接会让一个 chunk 对应多页，无法给出单一 bbox。

    另一个差别是**按行聚合而不是按字数硬切**。OCR 文本的每一行
    都是完整语义单元（尤其表格行已由上游拼成一行，见
    scanned_pdf_ocr.PageResult.blocks），按字符位置硬切会把它们
    从中间劈开。实测硬切产生过 `AK-82-00 2.70 2.16 2.` /
    `92 1.51 0.55 1.55` 这样的碎片，两半都检索不到任何东西。
    所以这里改成从上往下装行，装不下就换一个新 chunk，宁可让
    某些 chunk 略小于 chunk_size。
    """
    strategy = "scanned_pdf"
    MIN_CHUNK_CHARS = 80

    def parse(self, document: Document, config: ChunkConfig, context: ParserContext) -> ParseResult:
        page_blocks = _split_pages(document.text)
        if not page_blocks:
            return ParseResult(
                nodes=[], strategy=self.strategy,
                version=STRATEGY_VERSIONS[self.strategy],
                analysis={"page_count": 0, "chunk_count": 0},
            )

        nodes: List[TextNode] = []
        for page_no, page_text in page_blocks:
            if not page_text.strip():
                continue
            for i, chunk in enumerate(_pack_lines(page_text, config.size, config.overlap)):
                node = TextNode(text=chunk)
                node.metadata["page_no"] = page_no
                node.metadata["chunk_index"] = i
                nodes.append(node)

        # 合并过短 chunk：碎片 chunk 检索价值低，与前一个同页 chunk 合并
        nodes = _merge_short_chunks(nodes, self.MIN_CHUNK_CHARS)

        # 全局重编 chunk_index
        for i, node in enumerate(nodes):
            node.metadata["chunk_index"] = i
            node.metadata["total_chunks"] = len(nodes)

        short_count = sum(1 for n in nodes if len(n.text) < self.MIN_CHUNK_CHARS)

        return ParseResult(
            nodes=nodes,
            strategy=self.strategy,
            version=STRATEGY_VERSIONS[self.strategy],
            analysis={
                "page_count": len(page_blocks),
                "chunk_count": len(nodes),
                "pages_with_text": sum(1 for _, t in page_blocks if t.strip()),
                "short_chunks_remaining": short_count,
            },
        )


def _pack_lines(text: str, chunk_size: int, overlap: int) -> List[str]:
    """按行把一页文本装进若干 chunk，不切断任何一行。

    单行本身就超过 chunk_size 时（偶见 OCR 把整段并成一行），
    只能整行放进一个超长 chunk——截断它会造成不可逆的信息丢失，
    让它略超上限是更小的损失。
    """
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return []

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line)
        # 换行符也要计入，否则 chunk 实际长度会超出 chunk_size
        projected = current_len + line_len + (1 if current else 0)
        if current and projected > chunk_size:
            chunks.append("\n".join(current))
            # overlap 按整行回退，不回退到行中间
            current, current_len = _tail_for_overlap(current, overlap)
            projected = current_len + line_len + (1 if current else 0)
        current.append(line)
        current_len = projected

    if current:
        chunks.append("\n".join(current))
    return chunks


def _tail_for_overlap(lines: List[str], overlap: int) -> tuple:
    """从尾部取若干整行作为下一个 chunk 的重叠前缀。"""
    if overlap <= 0:
        return [], 0
    tail: List[str] = []
    total = 0
    for line in reversed(lines):
        added = len(line) + (1 if tail else 0)
        if total + added > overlap:
            break
        tail.insert(0, line)
        total += added
    return tail, total


def _merge_short_chunks(nodes: List[TextNode], min_chars: int) -> List[TextNode]:
    """合并过短的 chunk 到前一个同页 chunk。

    单页末尾的短 chunk（如只有一两行摘要）检索价值低，
    合并后语义更完整，召回率更高。跨页不合并——页码必须保持单一。

    合并前需要去掉短 chunk 开头与上一个 chunk 重叠的整行：
    `_pack_lines` 为了保证语义连续，会把上一个 chunk 结尾的若干整行
    复制到下一个 chunk 开头做重叠（overlap）。如果直接拼接
    `prev.text + "\n" + node.text`，这些重叠行会在合并后的文本里
    连续出现两次——曾在真实文档上复现：`iB229P | 22 | ...` 那一整行
    在同一个 chunk 里连续出现两遍。
    """
    if not nodes:
        return nodes
    merged: List[TextNode] = []
    for node in nodes:
        if (
            merged
            and len(node.text) < min_chars
            and merged[-1].metadata.get("page_no") == node.metadata.get("page_no")
        ):
            prev = merged[-1]
            prev.text = prev.text + "\n" + _strip_leading_overlap(prev.text, node.text)
        else:
            merged.append(node)
    return merged


def _strip_leading_overlap(prev_text: str, text: str) -> str:
    """去掉 text 开头与 prev_text 结尾重叠的整行。"""
    prev_lines = prev_text.split("\n")
    lines = text.split("\n")
    overlap_len = 0
    max_check = min(len(prev_lines), len(lines))
    for i in range(max_check, 0, -1):
        if prev_lines[-i:] == lines[:i]:
            overlap_len = i
            break
    return "\n".join(lines[overlap_len:])


def _split_pages(text: str) -> List[tuple]:
    """按 `<!-- page:N -->` 标记切分出 (页码, 正文) 列表。"""
    pattern = re.compile(r"<!--\s*page:(\d+)\s*-->")
    matches = list(pattern.finditer(text))
    if not matches:
        return []

    blocks = []
    for i, match in enumerate(matches):
        page_no = int(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((page_no, text[start:end].strip()))
    return blocks


class ParserRegistry:
    def __init__(self):
        self._parsers: Dict[str, DocumentParser] = {}

    def register(self, parser: DocumentParser) -> None:
        self._parsers[parser.strategy] = parser

    def get(self, strategy: str) -> DocumentParser:
        try:
            return self._parsers[strategy]
        except KeyError as error:
            raise ValueError(f"Unknown chunk strategy: {strategy}") from error


PARSER_REGISTRY = ParserRegistry()
PARSER_REGISTRY.register(CharacterParser())
PARSER_REGISTRY.register(MarkdownParser())
PARSER_REGISTRY.register(HospitalMarkdownParser())
PARSER_REGISTRY.register(ScannedPdfParser())


def build_chunk_config(size: Optional[int] = None, overlap: Optional[int] = None) -> ChunkConfig:
    return ChunkConfig(
        size=DEFAULT_CHUNK_SIZE if size is None else size,
        overlap=DEFAULT_CHUNK_OVERLAP if overlap is None else overlap,
    )


def detect_strategy(text: str) -> str:
    """Choose a parser from document structure, never from the filename."""
    hospital_headings = []
    for match in re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE):
        hospital = find_hospital_in_text(match.group(1))
        if hospital:
            hospital_headings.append(hospital)
    if hospital_headings:
        return "hospital_markdown"
    if re.search(r"^#{1,6}\s+.+$", text, re.MULTILINE):
        return "markdown"
    return "character"


def resolve_strategy(strategy: str, text: str) -> str:
    if strategy == "auto":
        # 带页码标记的文本一定来自扫描版 PDF，必须走页感知切分
        if re.search(r"<!--\s*page:\d+\s*-->", text):
            return "scanned_pdf"
        return detect_strategy(text)
    if strategy == "hospital":
        return "hospital_markdown"
    if strategy == "simple":
        return "character"
    if strategy not in STRATEGY_VERSIONS:
        raise ValueError(f"Unknown chunk strategy: {strategy}")
    return strategy


def split_document(
    document: Document,
    strategy: str = "auto",
    config: Optional[ChunkConfig] = None,
    context: Optional[ParserContext] = None,
) -> ParseResult:
    config = config or ChunkConfig()
    context = context or ParserContext(file_path=Path("."))
    selected = resolve_strategy(strategy, document.text)
    result = PARSER_REGISTRY.get(selected).parse(document, config, context)
    result.analysis.update({
        "requested_strategy": strategy,
        "selected_strategy": selected,
        "chunk_size": config.size,
        "chunk_overlap": config.overlap,
    })
    return result
