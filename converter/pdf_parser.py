# -*- coding: utf-8 -*-
"""PDF 解析：提取文本块、识别章节标题、去除页眉页脚、提取图片。"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pymupdf as fitz  # PyMuPDF

DEFAULT_CONFIG = {
    "title": "",                 # 书名（留空则取 PDF 元数据/文件名）
    "author": "",                # 作者
    "prefer_embedded_toc": True,  # 优先使用 PDF 内嵌书签作为目录
    "heading_scale": 1.15,       # 标题字号 >= 正文字号 * 该系数 时判定为标题
    "max_heading_chars": 60,     # 标题最大字数
    "use_pattern_headings": True,  # 识别“第X章/Chapter N”等模式标题
    "strip_header_footer": True,  # 去除重复页眉页脚与页码
    "extract_images": True,      # 提取正文图片
    "font_family": "serif",      # 正文字体族
    "line_height": 1.8,          # 行距
    "text_indent": True,         # 段首缩进 2 字符
    "min_chapter_chars": 50,     # 章节字数过少时给出排版警告
}

HEADING_PATTERN = re.compile(
    r"^\s*(第\s*[0-9零一二三四五六七八九十百千两]+\s*[章节卷部篇回集幕]"
    r"|chapter\s+\d+|part\s+\d+|book\s+\d+|prologue|epilogue"
    r"|序[章言曲]?|前言|引言|导言|楔子|尾声|后记|跋|附录|番外篇?)"
    r"([\s:：、.．\-—].*)?$",
    re.IGNORECASE,
)

PAGE_NUM_PATTERN = re.compile(r"^[-–—\s]*(\d{1,4}|第\s*\d{1,4}\s*页)[-–—\s]*$")
CJK_RE = re.compile(r"[一-鿿　-〿＀-￯]")


@dataclass
class Block:
    kind: str               # 'p' | 'img'
    text: str = ""
    size: float = 0.0
    bold: bool = False
    page: int = 0
    image: bytes = b""
    ext: str = "png"
    res_name: str = ""      # EPUB 内图片资源名（构建期填充）


@dataclass
class Chapter:
    title: str
    level: int = 1
    blocks: list = field(default_factory=list)
    chars: int = 0
    images: int = 0


def _is_bold(span):
    return bool(span["flags"] & 16) or "bold" in span["font"].lower()


def _norm_edge_text(text):
    t = re.sub(r"\s+", "", text)
    t = re.sub(r"\d+", "#", t)
    return t


def _join_lines(lines):
    """块内多行合并为一个段落（中文行尾无空格拼接，拉丁文补空格）。"""
    out = ""
    for t in lines:
        t = t.strip()
        if not t:
            continue
        if not out:
            out = t
        elif CJK_RE.search(out[-1]) or CJK_RE.search(t[0]):
            out += t
        else:
            out += " " + t
    return out


def _extract_blocks(doc, config):
    """按阅读顺序提取全部文本块/图片块，并剔除重复页眉页脚。"""
    page_dicts = []
    npages = len(doc)
    strip = config["strip_header_footer"]

    # 第一遍：收集页眉（顶部 12%）与页脚（底部 12%）区域内的文本
    top_occ, bot_occ = defaultdict(set), defaultdict(set)
    for pno in range(npages):
        pd = doc[pno].get_text("dict")
        page_dicts.append(pd)
        if not strip:
            continue
        h = doc[pno].rect.height
        for block in pd["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                text = "".join(s["text"] for s in line["spans"]).strip()
                if not text or len(text) > 60:
                    continue
                y0, y1 = line["bbox"][1], line["bbox"][3]
                norm = _norm_edge_text(text)
                if y1 < h * 0.12:
                    top_occ[norm].add(pno)
                elif y0 > h * 0.88:
                    bot_occ[norm].add(pno)

    banned = set()
    if strip and npages >= 3:
        thr = max(3, int(npages * 0.3) + 1)
        banned = {t for t, s in top_occ.items() if len(s) >= thr}
        banned |= {t for t, s in bot_occ.items() if len(s) >= thr}

    # 第二遍：构建有序块列表
    blocks = []
    seen_img = set()
    for pno in range(npages):
        h = doc[pno].rect.height
        for block in page_dicts[pno]["blocks"]:
            if block["type"] == 1:
                if not config["extract_images"]:
                    continue
                data = block.get("image")
                if not data or len(data) < 1024:
                    continue
                import hashlib
                digest = hashlib.md5(data).hexdigest()
                if digest in seen_img:
                    continue
                seen_img.add(digest)
                blocks.append(Block(kind="img", image=data,
                                    ext=block.get("ext", "png"), page=pno))
                continue

            lines, sizes, bold_first = [], [], False
            for line in block["lines"]:
                spans = line["spans"]
                text = "".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                if strip:
                    y0, y1 = line["bbox"][1], line["bbox"][3]
                    in_edge = y1 < h * 0.12 or y0 > h * 0.88
                    if in_edge and (_norm_edge_text(text) in banned
                                    or PAGE_NUM_PATTERN.match(text)):
                        continue
                lines.append(text)
                sizes.extend(s["size"] for s in spans if s["text"].strip())
                if not bold_first and spans:
                    bold_first = _is_bold(spans[0])

            para = _join_lines(lines)
            if para:
                blocks.append(Block(kind="p", text=para, page=pno,
                                    size=max(sizes) if sizes else 0.0,
                                    bold=bold_first))
    return blocks


def _body_font_size(blocks):
    c = Counter()
    for b in blocks:
        if b.kind == "p" and b.size:
            c[round(b.size * 2) / 2] += len(b.text)
    return c.most_common(1)[0][0] if c else 11.0


def _heading_level(b, body_size, config):
    if b.kind != "p":
        return 0
    text = b.text.strip()
    if not text or len(text) > config["max_heading_chars"]:
        return 0
    ratio = (b.size / body_size) if body_size else 1.0
    if ratio >= config["heading_scale"]:
        return 1 if ratio >= max(1.6, config["heading_scale"] + 0.3) else 2
    if config["use_pattern_headings"] and HEADING_PATTERN.match(text):
        if b.bold or ratio >= 0.95:
            return 2
    return 0


def _chapters_from_headings(blocks, body_size, config):
    chapters = []
    cur = Chapter(title="卷首", level=1)
    for b in blocks:
        lvl = _heading_level(b, body_size, config)
        if lvl:
            if cur.blocks:
                chapters.append(cur)
            cur = Chapter(title=b.text.strip(), level=lvl)
        else:
            cur.blocks.append(b)
    if cur.blocks or not chapters:
        chapters.append(cur)
    return chapters


def _chapters_from_toc(blocks, toc):
    titles = {t[1].strip() for t in toc}
    chapters = []
    for i, (lvl, title, page1) in enumerate(toc):
        start = max(0, page1 - 1)
        end = (toc[i + 1][2] - 1) if i + 1 < len(toc) else 10 ** 9
        ch = Chapter(title=title.strip(), level=min(max(lvl, 1), 4))
        ch.blocks = [b for b in blocks if start <= b.page < end]
        # 去掉与目录条目重复的标题行（含嵌套目录中上级标题行）
        while ch.blocks and ch.blocks[0].kind == "p":
            t = ch.blocks[0].text.strip()
            if not t:
                ch.blocks.pop(0)
            elif t in titles or ((t in ch.title or ch.title in t) and len(t) <= len(ch.title) + 6):
                ch.blocks.pop(0)
            else:
                break
        chapters.append(ch)
    first_page = max(0, toc[0][2] - 1)
    front = [b for b in blocks if b.page < first_page]
    if front:
        chapters.insert(0, Chapter(title="卷首", level=1, blocks=front))
    return chapters


def _render_cover(doc):
    try:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        return pix.tobytes("png")
    except Exception:
        return None


def _detect_language(text):
    sample = text[:5000]
    if not sample:
        return "zh"
    cjk = len(CJK_RE.findall(sample))
    return "zh" if cjk / max(len(sample), 1) > 0.15 else "en"


def parse_pdf(pdf_bytes, config, filename=""):
    """解析 PDF，返回结构化模型（供分析与生成 EPUB 使用）。"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    meta = doc.metadata or {}

    blocks = _extract_blocks(doc, config)
    body_size = _body_font_size(blocks)

    used_toc = False
    toc = doc.get_toc(simple=True) if config["prefer_embedded_toc"] else []
    toc = [t for t in toc if t[1].strip() and t[2] >= 1]
    if toc:
        chapters = _chapters_from_toc(blocks, toc)
        used_toc = True
    else:
        chapters = _chapters_from_headings(blocks, body_size, config)

    for ch in chapters:
        ch.chars = sum(len(b.text) for b in ch.blocks if b.kind == "p")
        ch.images = sum(1 for b in ch.blocks if b.kind == "img")

    title = config["title"].strip() or (meta.get("title") or "").strip()
    if not title or title.lower().endswith(".pdf"):
        title = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE).strip() or "未命名书籍"
    author = config["author"].strip() or (meta.get("author") or "").strip() or "佚名"
    full_text = "".join(b.text for b in blocks if b.kind == "p")

    model = {
        "title": title,
        "author": author,
        "language": _detect_language(full_text),
        "npages": len(doc),
        "body_size": body_size,
        "used_toc": used_toc,
        "chapters": chapters,
        "cover_png": _render_cover(doc),
    }
    doc.close()
    return model


def build_report(model, config):
    """排版检查报告：章节列表 + 警告 + 统计。"""
    chapters = model["chapters"]
    warnings = []

    if model["npages"] > 0 and sum(c.chars for c in chapters) < 100:
        warnings.append("未检测到有效文本内容：该 PDF 可能是扫描件，需要 OCR 后才能转换。")
    if not model["used_toc"] and len(chapters) <= 1:
        warnings.append("未识别出章节标题：整本书将作为单章输出。可调低“标题字号阈值”或开启模式识别后重新分析。")
    if model["used_toc"]:
        empty = []
        for i, c in enumerate(chapters):
            if c.chars == 0 and c.images == 0:
                # 有下级章节的空章节属正常的目录分组，不警告
                has_child = i + 1 < len(chapters) and chapters[i + 1].level > c.level
                if not has_child:
                    empty.append(c.title)
        if empty:
            warnings.append(f"{len(empty)} 个章节内容为空（如《{empty[0]}》），可能是书签指向有误。")

    tiny = [c for c in chapters if 0 < c.chars < config["min_chapter_chars"]]
    for c in tiny[:5]:
        warnings.append(f"章节《{c.title}》仅 {c.chars} 字，可能是误识别的标题。")

    report = {
        "title": model["title"],
        "author": model["author"],
        "language": model["language"],
        "pages": model["npages"],
        "body_size": model["body_size"],
        "toc_source": "PDF 内嵌书签" if model["used_toc"] else "字号/模式识别",
        "total_chars": sum(c.chars for c in chapters),
        "total_images": sum(c.images for c in chapters),
        "chapter_count": len(chapters),
        "warnings": warnings,
        "chapters": [
            {"title": c.title, "level": c.level, "chars": c.chars, "images": c.images}
            for c in chapters
        ],
    }
    return report
