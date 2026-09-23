/* PDF → EPUB 转换器前端逻辑 */
(() => {
  const $ = (id) => document.getElementById(id);
  const dropzone = $("dropzone");
  const fileInput = $("file-input");
  const fileInfo = $("file-info");
  const btnAnalyze = $("btn-analyze");
  const btnConvert = $("btn-convert");
  const btnPreviewPdf = $("btn-preview-pdf");
  const btnPreviewEpub = $("btn-preview-epub");
  const statusEl = $("status");

  let currentFile = null;
  let sessionId = null;
  let bookTitle = "";
  let epubBlob = null;

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
    epubBlob = null;
    const mb = (file.size / 1024 / 1024).toFixed(2);
    fileInfo.innerHTML = `<span>📄 ${escapeHtml(file.name)}</span><span>${mb} MB</span>`;
    fileInfo.classList.remove("hidden");
    btnAnalyze.disabled = false;
    btnConvert.disabled = false;
    btnPreviewPdf.disabled = false;
    btnPreviewEpub.disabled = true;
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
      epubBlob = blob;
      btnPreviewEpub.disabled = false;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
      setStatus(`转换完成，已下载 ${name}（${(blob.size / 1024 / 1024).toFixed(2)} MB），可点击「预览 EPUB」查看效果。`);
    } catch (e) {
      setStatus(e.message, true);
    } finally {
      setLoading(btnConvert, false);
    }
  });

  /* ---------- 预览阅读器 ---------- */
  const modal = $("preview-modal");
  const tocList = $("toc-list");
  const content = $("preview-content");
  const pvPrev = $("pv-prev");
  const pvNext = $("pv-next");
  const pvPage = $("pv-page");

  let previewMode = null; // "pdf" | "epub"
  let pdfDoc = null, pdfPageNo = 1, pdfRendering = false, pdfPending = null;
  let epubBook = null, rendition = null;

  pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdf.worker.min.js";

  function openModal(title) {
    $("preview-title").textContent = title;
    tocList.innerHTML = "";
    content.innerHTML = "";
    pvPage.textContent = "";
    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    modal.classList.add("hidden");
    document.body.style.overflow = "";
    if (rendition) { try { rendition.destroy(); } catch (e) {} rendition = null; }
    if (epubBook) { try { epubBook.destroy(); } catch (e) {} epubBook = null; }
    if (pdfDoc) { try { pdfDoc.destroy(); } catch (e) {} pdfDoc = null; }
    previewMode = null;
    content.classList.remove("epub-mode");
  }

  $("pv-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener("keydown", (e) => {
    if (modal.classList.contains("hidden")) return;
    if (e.key === "Escape") closeModal();
    else if (e.key === "ArrowLeft") pvPrev.click();
    else if (e.key === "ArrowRight") pvNext.click();
  });

  function renderTocItems(items, depth, onClick, labelOf, childrenOf) {
    items.forEach((it) => {
      const btn = document.createElement("button");
      btn.className = "toc-item lv" + Math.min(depth + 1, 4);
      btn.textContent = labelOf(it);
      btn.title = btn.textContent;
      btn.addEventListener("click", () => onClick(it));
      tocList.appendChild(btn);
      const children = childrenOf(it);
      if (children && children.length) renderTocItems(children, depth + 1, onClick, labelOf, childrenOf);
    });
  }

  function showTocEmpty(msg) {
    tocList.innerHTML = `<div class="toc-empty">${escapeHtml(msg)}</div>`;
  }

  /* ----- PDF 预览（pdf.js） ----- */
  btnPreviewPdf.addEventListener("click", async () => {
    if (!currentFile) return;
    openModal(`PDF 预览 · ${currentFile.name}`);
    previewMode = "pdf";
    content.classList.remove("epub-mode");
    showTocEmpty("正在读取目录…");
    const canvas = document.createElement("canvas");
    content.appendChild(canvas);
    const ctx = canvas.getContext("2d");

    try {
      const data = await currentFile.arrayBuffer();
      pdfDoc = await pdfjsLib.getDocument({
        data,
        cMapUrl: "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/cmaps/",
        cMapPacked: true,
        standardFontDataUrl: "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/standard_fonts/",
      }).promise;
      pdfPageNo = 1;

      const outline = await pdfDoc.getOutline();
      if (outline && outline.length) {
        tocList.innerHTML = "";
        renderTocItems(
          outline, 0,
          (it) => gotoPdfDest(it.dest),
          (it) => it.title || "(未命名)",
          (it) => it.items
        );
      } else {
        showTocEmpty("该 PDF 无书签目录，可使用上一页 / 下一页翻页。");
      }
      await renderPdfPage(1);
    } catch (e) {
      showTocEmpty(`PDF 加载失败：${e.message}`);
    }

    async function renderPdfPage(n) {
      if (pdfRendering) { pdfPending = n; return; }
      pdfRendering = true;
      try {
        const page = await pdfDoc.getPage(n);
        const base = page.getViewport({ scale: 1 });
        const scale = Math.max((content.clientWidth - 40) / base.width, 0.4);
        const vp = page.getViewport({ scale });
        canvas.width = vp.width;
        canvas.height = vp.height;
        await page.render({ canvasContext: ctx, viewport: vp }).promise;
        pdfPageNo = n;
        pvPage.textContent = `${n} / ${pdfDoc.numPages}`;
        pvPrev.disabled = n <= 1;
        pvNext.disabled = n >= pdfDoc.numPages;
        content.scrollTop = 0;
      } finally {
        pdfRendering = false;
        if (pdfPending !== null && pdfPending !== pdfPageNo) {
          const p = pdfPending;
          pdfPending = null;
          renderPdfPage(p);
        } else {
          pdfPending = null;
        }
      }
    }

    async function gotoPdfDest(dest) {
      if (!pdfDoc || !dest) return;
      try {
        const d = typeof dest === "string" ? await pdfDoc.getDestination(dest) : dest;
        if (!d || !d[0]) return;
        const idx = await pdfDoc.getPageIndex(d[0]);
        await renderPdfPage(idx + 1);
      } catch (e) { /* 忽略无效目录项 */ }
    }

    pvPrev.onclick = () => { if (pdfPageNo > 1) renderPdfPage(pdfPageNo - 1); };
    pvNext.onclick = () => { if (pdfDoc && pdfPageNo < pdfDoc.numPages) renderPdfPage(pdfPageNo + 1); };
  });

  /* ----- EPUB 预览（epub.js） ----- */
  btnPreviewEpub.addEventListener("click", async () => {
    if (!epubBlob) return;
    openModal(`EPUB 预览 · ${bookTitle || "book"}.epub`);
    previewMode = "epub";
    content.classList.add("epub-mode");
    showTocEmpty("正在读取目录…");

    try {
      const buf = await epubBlob.arrayBuffer();
      epubBook = ePub(buf);
      rendition = epubBook.renderTo(content, {
        width: "100%",
        height: "100%",
        flow: "scrolled-doc",
        spread: "none",
      });
      await rendition.display();

      const nav = await epubBook.loaded.navigation;
      if (nav.toc && nav.toc.length) {
        tocList.innerHTML = "";
        renderTocItems(
          nav.toc, 0,
          (it) => rendition.display(it.href),
          (it) => (it.label || "").trim() || "(未命名)",
          (it) => it.subitems
        );
      } else {
        showTocEmpty("该 EPUB 无目录，可使用上一页 / 下一页翻页。");
      }
      pvPage.textContent = "";
      pvPrev.disabled = false;
      pvNext.disabled = false;
    } catch (e) {
      showTocEmpty(`EPUB 加载失败：${e.message}`);
    }

    pvPrev.onclick = () => rendition && rendition.prev();
    pvNext.onclick = () => rendition && rendition.next();
  });
})();
