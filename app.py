# -*- coding: utf-8 -*-
"""PDF → EPUB 转换工具 Web 服务。"""
import io
import json
import time
import uuid

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.middleware.proxy_fix import ProxyFix

from converter.epub_builder import build_epub
from converter.pdf_parser import DEFAULT_CONFIG, build_report, parse_pdf

app = Flask(__name__)
# 反代场景（如 Nginx 下 /pdf2epub/ 子路径）下正确生成 url_for 链接与前缀
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
SESSIONS = {}  # sid -> {"pdf": bytes, "name": str, "ts": float}
SESSION_TTL = 3600


def _cleanup():
    now = time.time()
    for sid in [s for s, v in SESSIONS.items() if now - v["ts"] > SESSION_TTL]:
        SESSIONS.pop(sid, None)


def _merge_config(raw):
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in cfg:
                cfg[k] = type(cfg[k])(v) if not isinstance(cfg[k], bool) else bool(v)
    cfg["line_height"] = min(max(float(cfg["line_height"]), 1.0), 3.0)
    cfg["heading_scale"] = min(max(float(cfg["heading_scale"]), 1.0), 2.0)
    return cfg


@app.route("/")
def index():
    return render_template("index.html", defaults=DEFAULT_CONFIG)


@app.route("/api/analyze", methods=["POST"])
def analyze():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "请上传 PDF 文件"}), 400
    pdf_bytes = f.read()
    if not pdf_bytes:
        return jsonify({"error": "文件内容为空"}), 400
    try:
        config = _merge_config(json.loads(request.form.get("config", "{}")))
    except json.JSONDecodeError:
        config = dict(DEFAULT_CONFIG)

    try:
        model = parse_pdf(pdf_bytes, config, filename=f.filename)
    except Exception as e:
        return jsonify({"error": f"PDF 解析失败：{e}"}), 400

    _cleanup()
    sid = uuid.uuid4().hex
    SESSIONS[sid] = {"pdf": pdf_bytes, "name": f.filename, "ts": time.time()}
    return jsonify({"session": sid, "report": build_report(model, config)})


@app.route("/api/convert", methods=["POST"])
def convert():
    data = request.get_json(silent=True) or {}
    sess = SESSIONS.get(data.get("session", ""))
    if not sess:
        return jsonify({"error": "会话已过期，请重新上传文件"}), 400
    config = _merge_config(data.get("config"))

    try:
        model = parse_pdf(sess["pdf"], config, filename=sess["name"])
        epub_bytes = build_epub(model, config)
    except Exception as e:
        return jsonify({"error": f"转换失败：{e}"}), 500

    return send_file(
        io.BytesIO(epub_bytes),
        mimetype="application/epub+zip",
        as_attachment=True,
        download_name=f'{model["title"]}.epub',
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057, debug=False)
