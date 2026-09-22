# -*- coding: utf-8 -*-
"""EPUB 生成：嵌套目录跳转、可配置排版样式、封面、图片嵌入。"""
import hashlib
import io
from html import escape

from ebooklib import epub

FONT_MAP = {
    "serif": "Georgia, 'Times New Roman', 'Songti SC', 'SimSun', serif",
    "sans": "'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif",
    "kai": "'Kaiti SC', KaiTi, 'STKaiti', serif",
}


def _css(config):
    font = FONT_MAP.get(config["font_family"], FONT_MAP["serif"])
    lh = config["line_height"]
    indent = "text-indent: 2em;" if config["text_indent"] else ""
    return f"""
body {{ font-family: {font}; line-height: {lh}; margin: 0 5%; }}
p {{ margin: 0.4em 0; {indent} text-align: justify; }}
h1, h2, h3, h4 {{ font-weight: bold; line-height: 1.4; margin: 1.2em 0 0.8em; page-break-after: avoid; }}
h1 {{ font-size: 1.6em; text-align: center; }}
h2 {{ font-size: 1.35em; }}
h3 {{ font-size: 1.15em; }}
h4 {{ font-size: 1.05em; }}
p.img {{ text-align: center; text-indent: 0; margin: 1em 0; }}
img {{ max-width: 100%; max-height: 95vh; }}
""".strip()


def _chapter_html(ch):
    tag = f"h{min(max(ch.level, 1), 4)}"
    parts = [f"<{tag}>{escape(ch.title)}</{tag}>"]
    for b in ch.blocks:
        if b.kind == "p":
            parts.append(f"<p>{escape(b.text)}</p>")
        else:
            parts.append(f'<p class="img"><img src="../images/{b.res_name}" alt=""/></p>')
    return "\n".join(parts)


def _toc_tree(epub_chapters):
    """根据章节层级构建嵌套目录树。"""
    root = {"level": 0, "children": []}
    stack = [root]
    for ch in epub_chapters:
        node = {"level": ch.level, "ch": ch, "children": []}
        while len(stack) > 1 and stack[-1]["level"] >= ch.level:
            stack.pop()
        stack[-1]["children"].append(node)
        stack.append(node)

    def conv(nodes):
        out = []
        for n in nodes:
            link = epub.Link(n["ch"].file_name, n["ch"].title or "未命名", n["ch"].id)
            out.append((link, tuple(conv(n["children"]))) if n["children"] else link)
        return tuple(out)

    return conv(root["children"])


def build_epub(model, config):
    """根据解析模型生成 EPUB，返回字节流。"""
    book = epub.EpubBook()
    book.set_identifier("pdf2epub-" + hashlib.md5(model["title"].encode()).hexdigest()[:12])
    book.set_title(model["title"])
    book.set_language(model["language"])
    book.add_author(model["author"])

    if model["cover_png"]:
        book.set_cover("cover.png", model["cover_png"])

    css = epub.EpubItem(uid="style", file_name="style/style.css",
                        media_type="text/css", content=_css(config).encode("utf-8"))
    book.add_item(css)

    # 图片资源（按内容去重）
    img_items = {}
    img_count = 0
    for ch in model["chapters"]:
        for b in ch.blocks:
            if b.kind != "img":
                continue
            key = hashlib.md5(b.image).hexdigest()
            if key in img_items:
                b.res_name = img_items[key][0]
                continue
            img_count += 1
            ext = "jpg" if b.ext in ("jpg", "jpeg") else b.ext
            name = f"img{img_count:04d}.{ext}"
            media = "image/jpeg" if ext == "jpg" else f"image/{ext}"
            item = epub.EpubItem(uid=f"img_{img_count}", file_name=f"images/{name}",
                                 media_type=media, content=b.image)
            book.add_item(item)
            img_items[key] = (name, item)
            b.res_name = name

    epub_chapters = []
    for i, ch in enumerate(model["chapters"], 1):
        ech = epub.EpubHtml(title=ch.title, file_name=f"text/ch{i:04d}.xhtml",
                            lang=model["language"])
        ech.level = ch.level
        ech.content = _chapter_html(ch)
        ech.add_item(css)
        book.add_item(ech)
        epub_chapters.append(ech)

    book.toc = _toc_tree(epub_chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + epub_chapters

    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()
