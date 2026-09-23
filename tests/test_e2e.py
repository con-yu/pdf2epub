# -*- coding: utf-8 -*-
"""端到端测试：生成测试 PDF -> 解析 -> 生成 EPUB -> 校验结构。"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf as fitz  # noqa: E402
from converter.epub_builder import build_epub  # noqa: E402
from converter.pdf_parser import DEFAULT_CONFIG, build_report, parse_pdf  # noqa: E402


def make_test_pdf() -> bytes:
    doc = fitz.open()
    toc = []
    body = "这是一个用于测试的正文段落。它包含足够多的文字，用来验证段落合并与排版输出是否符合预期。"

    FONT = "china-s"  # PyMuPDF 内置中文字体，保证文本可提取

    def new_page():
        p = doc.new_page(width=595, height=842)
        # 页眉页脚（每页重复，应被剔除）
        p.insert_text((220, 30), "测试书名 内部资料", fontsize=9, fontname=FONT)
        p.insert_text((290, 820), f"- {doc.page_count} -", fontsize=9, fontname=FONT)
        return p

    # 封面
    p = doc.new_page(width=595, height=842)
    p.insert_text((150, 300), "测试之书", fontsize=36, fontname=FONT)

    # 第一章（带书签）
    for part in range(2):
        p = new_page()
        if part == 0:
            p.insert_text((80, 100), "第一章 开始的旅程", fontsize=20, fontname=FONT)
            toc.append([1, "第一章 开始的旅程", doc.page_count])
            p.insert_text((80, 140), "第一节 出发", fontsize=15, fontname=FONT)
            toc.append([2, "第一节 出发", doc.page_count])
            y = 170
        else:
            y = 80
        for i in range(12):
            p.insert_text((80, y), body + f"（第{i + 1}段）", fontsize=11, fontname=FONT)
            y += 22

    # 第二章
    p = new_page()
    p.insert_text((80, 100), "第二章 深入探索", fontsize=20, fontname=FONT)
    toc.append([1, "第二章 深入探索", doc.page_count])
    y = 140
    for i in range(10):
        p.insert_text((80, y), body + f"（第{i + 1}段）", fontsize=11, fontname=FONT)
        y += 22

    doc.set_toc(toc)
    buf = doc.tobytes()
    doc.close()
    return buf


def main():
    pdf_bytes = make_test_pdf()
    print(f"[1] 生成测试 PDF: {len(pdf_bytes) / 1024:.1f} KB")

    config = dict(DEFAULT_CONFIG)
    model = parse_pdf(pdf_bytes, config, filename="测试之书.pdf")
    report = build_report(model, config)

    print(f"[2] 解析结果: 标题={report['title']} 章节数={report['chapter_count']} "
          f"总字数={report['total_chars']} 目录来源={report['toc_source']}")
    for c in report["chapters"]:
        print(f"    L{c['level']} {c['title']} ({c['chars']} 字, {c['images']} 图)")
    for w in report["warnings"]:
        print(f"    [警告] {w}")

    assert report["toc_source"] == "PDF 内嵌书签", "应使用内嵌书签目录"
    assert report["chapter_count"] >= 3, "应识别出至少 3 个章节"

    # 页眉页脚应被剔除
    all_text = "".join(b.text for ch in model["chapters"] for b in ch.blocks if b.kind == "p")
    assert "测试书名" not in all_text, "页眉未被剔除"
    assert "- 2 -" not in all_text and "- 3 -" not in all_text, "页码未被剔除"
    assert "开始的旅程" not in all_text, "目录标题重复行未被剔除"
    print("[3] 页眉/页脚/页码剔除: 通过")

    epub_bytes = build_epub(model, config)
    print(f"[4] 生成 EPUB: {len(epub_bytes) / 1024:.1f} KB")

    z = zipfile.ZipFile(io.BytesIO(epub_bytes))
    names = z.namelist()
    assert "mimetype" in names and "EPUB/nav.xhtml" in names, "EPUB 结构不完整"
    assert any(n.endswith(".xhtml") and "text/" in n for n in names), "缺少章节文件"
    assert "EPUB/style/style.css" in names, "缺少样式表"
    assert any("cover" in n for n in names), "缺少封面"
    nav = z.read("EPUB/nav.xhtml").decode("utf-8")
    assert "第一章 开始的旅程" in nav and "第二章 深入探索" in nav, "目录跳转缺少章节链接"
    print(f"[5] EPUB 校验通过: {len(names)} 个文件, 目录跳转链接正常")

    out = Path(__file__).resolve().parent.parent / "tests" / "output.epub"
    out.write_bytes(epub_bytes)
    print(f"[6] 样例输出已保存: {out}")
    print("\n=== 全部测试通过 ===")


if __name__ == "__main__":
    main()
