/* PDF → EPUB 转换器前端逻辑 */
(() => {
  const $ = (id) => document.getElementById(id);
  const dropzone = $("dropzone");
  const fileInput = $("file-input");
  const fileInfo = $("file-info");
  const btnAnalyze = $("btn-analyze");
  const btnConvert = $("btn-convert");
  const statusEl = $("status");

  let currentFile = null;
  let sessionId = null;
  let bookTitle = "";

  /* ---------- 配置收集 ---------- */
  $("cfg-lh").addEventListener("input", (e) => ($("lh-val").textContent = e.target.value));
  $("cfg-scale").addEventListener("input", (e) => ($("scale-val").textContent = e.target.value));

  function collectConfig() {
    return {
      title: $("cfg-title").value.trim(),
      author: $("cfg-author").value.trim(),
      prefer_embedded_toc: $("cfg-toc").checked,
      heading_scale: parseFloat($("cfg-scale").value),
      use_pattern_headings: $("cfg-pattern").checked,
      strip_header_footer: $("cfg-strip").checked,
      extract_images: $("cfg-images").checked,
      text_indent: $("cfg-indent").checked,
      font_family: $("cfg-font").value,
      line_height: parseFloat($("cfg-lh").value),
    };
  }

  function setStatus(msg, isError = false) {
    statusEl.textContent = msg;
    statusEl.classList.toggle("error", isError);
  }

  function setLoading(btn, on, text) {
    btn.disabled = on;
    btn.classList.toggle("spinner", on);
    if (text) btn.dataset.label = btn.textContent;
    btn.textContent = on ? btn.textContent.replace(/…?$/, "") + "…" : (btn.dataset.label || btn.textContent);
  }

  /* ---------- 文件选择 ---------- */
  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => { if (e.key === "Enter") fileInput.click(); });
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length) pickFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", () => { if (fileInput.files.length) pickFile(fileInput.files[0]); });

  function pickFile(file) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setStatus("请选择 PDF 文件", true);
      return;
    }
    currentFile = file;
    sessionId = null;
    const mb = (file.size / 1024 / 1024).toFixed(2);
    fileInfo.innerHTML = `<span>📄 ${escapeHtml(file.name)}</span><span>${mb} MB</span>`;
    fileInfo.classList.remove("hidden");
    btnAnalyze.disabled = false;
    btnConvert.disabled = false;
    setStatus("文件已就绪，建议先点击「分析排版」检查章节结构。");
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /* ---------- 分析 ---------- */
  btnAnalyze.addEventListener("click", async () => {
    if (!currentFile) return;
    setLoading(btnAnalyze, true);
    setStatus("正在解析 PDF…");
    try {
      const fd = new FormData();
      fd.append("file", currentFile);
      fd.append("config", JSON.stringify(collectConfig()));
      const res = await fetch("/api/analyze", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "分析失败");
      sessionId = data.session;
      renderReport(data.report);
      setStatus("分析完成，可调整参数后重新分析，或直接转换下载。");
    } catch (e) {
      setStatus(e.message, true);
    } finally {
      setLoading(btnAnalyze, false);
    }
  });

  function renderReport(r) {
    bookTitle = r.title;
    $("empty-result").classList.add("hidden");
    $("result").classList.remove("hidden");

    $("book-meta").innerHTML =
      `<span class="book-title">${escapeHtml(r.title)}</span>` +
      `<span class="book-author">${escapeHtml(r.author)} · ${r.language === "zh" ? "中文" : "英文"}</span>`;

    $("stats").innerHTML = [
      `${r.pages} 页`,
      `${r.chapter_count} 章`,
      `${r.total_chars.toLocaleString()} 字`,
      `${r.total_images} 张图片`,
      `目录来源：${r.toc_source}`,
      `正文字号 ${r.body_size}pt`,
    ].map((s) => `<span class="chip">${escapeHtml(s)}</span>`).join("");

    $("warnings").innerHTML = r.warnings.length
      ? r.warnings.map((w) => `<div class="warn-item">⚠ ${escapeHtml(w)}</div>`).join("")
      : `<div class="ok-item">✓ 未发现明显的排版问题</div>`;

    $("chapter-tree").innerHTML = r.chapters
      .map((c) => {
        const meta = `${c.chars.toLocaleString()} 字${c.images ? ` · ${c.images} 图` : ""}`;
        return `<div class="ch-item lv${Math.min(c.level, 4)}">` +
          `<span class="ch-title">${escapeHtml(c.title)}</span>` +
          `<span class="ch-meta">${meta}</span></div>`;
      })
      .join("");
  }

  /* ---------- 转换 ---------- */
  btnConvert.addEventListener("click", async () => {
    if (!currentFile) return;
    setLoading(btnConvert, true);
    setStatus("正在生成 EPUB…");
    try {
      let sid = sessionId;
      if (!sid) { // 未分析过则先分析建立会话
        const fd = new FormData();
        fd.append("file", currentFile);
        fd.append("config", JSON.stringify(collectConfig()));
        const res = await fetch("/api/analyze", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "分析失败");
        sid = data.session;
        sessionId = sid;
        renderReport(data.report);
      }
      const res = await fetch("/api/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: sid, config: collectConfig() }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "转换失败");
      }
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename\*=UTF-8''([^;]+)/);
      const name = m ? decodeURIComponent(m[1]) : `${bookTitle || "book"}.epub`;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
      setStatus(`转换完成，已下载 ${name}（${(blob.size / 1024 / 1024).toFixed(2)} MB）`);
    } catch (e) {
      setStatus(e.message, true);
    } finally {
      setLoading(btnConvert, false);
    }
  });
})();
