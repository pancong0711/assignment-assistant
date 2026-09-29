// src/lib/taskpad.ts
function normalizePerPage(v, orientation) {
  const n = Number(v);
  if (n === 1 || n === 2 || n === 3 || n === 4) return n;
  return orientation === "landscape" ? 2 : 1;
}

// src/lib/sheetHtml.ts
var KATEX_VERSION = "0.16.4";
var BLANK_STUDENT = { name: "", number: "", class: "", tag: "" };
var SYNTHETIC_STUDENTS = [
  { name: "\u5B66\u751FA", number: "2026xxxx01", class: "classA", tag: "" },
  { name: "\u5B66\u751FB", number: "2026xxxx02", class: "classB", tag: "" }
];
var PAGE_W_MM = { portrait: 210, landscape: 297 };
function escapeHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function todayStr() {
  const d = /* @__PURE__ */ new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function gridKey(orientation, perPage) {
  if (perPage === 4) return "cross";
  if (perPage === 3) return orientation === "portrait" ? "rows3" : "cols3";
  return orientation === "portrait" ? "rows2" : "cols2";
}
function gridLines(orientation, perPage) {
  if (perPage === 4) return ["v", "h"];
  if (perPage === 3) return orientation === "landscape" ? ["v31", "v32"] : ["h31", "h32"];
  if (perPage === 2) return orientation === "landscape" ? ["v"] : ["h"];
  return [];
}
function printCss(orientation) {
  return `/* ===== assignment.html.j2 \u6253\u5370\u4E3B\u901A\u9053\u6837\u5F0F\uFF08\u4E0E app/src/lib/sheetHtml.ts PRINT_CSS \u9010\u5B57\u540C\u6B65\uFF09 ===== */
:root { --ink:#1f2937; --line:#333; --muted:#6b7280; --accent:#2456c4; --hairline:#c3cad6; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: #e8ecf3; color: var(--ink);
  font-family: "Noto Sans SC", "Microsoft YaHei", "PingFang SC", "Source Han Sans SC", sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.doc-hint { max-width: 210mm; margin: 8mm auto 2mm; font-size: 11px; color: #475569;
  background: #fff; border: 1px dashed var(--hairline); border-radius: 8px; padding: 6px 10px; }
.sheet-page {
  position: relative; background: #fff; overflow: hidden;
  width: 210mm; height: 296mm; margin: 10mm auto; padding: 12mm 14mm;
  display: flex; flex-direction: column; gap: 2mm;
  box-shadow: 0 2px 10px rgba(31, 41, 55, 0.18);
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.sheet-page.landscape { width: 297mm; height: 209mm; }
.sheet-header { border-bottom: 2px solid var(--line); text-align: center; font-weight: 700; padding-bottom: 2mm; }
.sh-title { font-size: 16pt; }
.sh-info { display: flex; justify-content: space-between; gap: 3mm; flex-wrap: wrap;
  font-weight: 400; font-size: 10.5pt; text-align: left; margin-top: 1.6mm; color: #222; }
.sh-assign { color: var(--muted); }
.sheet-body { flex: 1; display: flex; flex-direction: column; gap: 3mm; min-height: 0; }
.sheet-page.landscape .sheet-body { flex-direction: row; }
.sheet-body[data-grid="cols2"], .sheet-body[data-grid="cols3"] { flex-direction: row; }
.sheet-body[data-grid="rows2"], .sheet-body[data-grid="rows3"] { flex-direction: column; }
.sheet-body[data-grid="cross"] { flex-wrap: wrap; }
.sheet-body.divided { gap: 0; position: relative; }
.sheet-body.divided .sheet-frame { overflow: hidden; max-width: 50%; word-break: break-word; }
.sheet-frame { flex: 1 1 0; min-width: 0; min-height: 0; border: 1px dashed var(--hairline);
  border-radius: 2mm; padding: 3mm; overflow: hidden; display: flex; flex-direction: column; gap: 2mm; }
.sheet-body.divided .sheet-frame { border: none; border-radius: 0; padding: 3mm 4mm; }
.sheet-body[data-grid="cross"] .sheet-frame { flex: 0 0 50%; height: 50%; }
.q-id { font-weight: 700; color: var(--accent); font-size: 11pt; }
.q-tag { font-weight: 400; color: var(--muted); font-size: 9pt; }
.q-content { font-size: 11.5pt; line-height: 1.8; white-space: pre-wrap; }
.q-img { max-width: 100%; max-height: 52mm; object-fit: contain; align-self: center; }
.q-img-ph { color: var(--muted); font-size: 10pt; font-style: italic; border: 1px dashed var(--hairline);
  border-radius: 2mm; padding: 4mm; text-align: center; }
.q-solution { color: var(--muted); font-size: 10pt; border-top: 1px dashed #dfe3ea;
  padding-top: 1.5mm; margin-top: auto; }
.sheet-footer { border-top: 1px solid var(--line); padding-top: 1.5mm; font-size: 10pt;
  color: var(--muted); display: flex; justify-content: space-between; gap: 3mm; }
/* \u591A\u9898/\u9875\u5206\u9694\u7EBF\uFF08\u865A\u7EBF\uFF0C\u6B62\u4E8E\u5185\u5BB9\u533A\uFF0C\u4E0D\u7A7F\u9875\u7709\u9875\u811A\uFF1B\u4E0E CSS \u9884\u89C8/\u5F15\u64CE PDF \u540C\u53E3\u5F84\uFF09 */
.sf-line { position: absolute; pointer-events: none; z-index: 2; }
.sf-line.v { left: 50%; top: 0; width: 1px; height: 100%; }
.sf-line.h { left: 0; top: 50%; width: 100%; height: 1px; }
.sf-line.v31 { left: 33.3%; top: 0; width: 1px; height: 100%; }
.sf-line.v32 { left: 66.6%; top: 0; width: 1px; height: 100%; }
.sf-line.h31 { left: 0; top: 33.3%; width: 100%; height: 1px; }
.sf-line.h32 { left: 0; top: 66.6%; width: 100%; height: 1px; }
.sf-line.v, .sf-line.v31, .sf-line.v32 { background-image: repeating-linear-gradient(to bottom, #777 0 5px, transparent 5px 10px); }
.sf-line.h, .sf-line.h31, .sf-line.h32 { background-image: repeating-linear-gradient(to right, #777 0 5px, transparent 5px 10px); }
/* \u6C34\u5370\u5C42\uFF08\u6BCF\u9875\u91CD\u5EFA\uFF1Bitems \u9010\u5C42 + \u9875\u7801\u5927\u5B57\uFF09 */
.wm-layer { position: absolute; inset: 0; pointer-events: none; z-index: 5; }
.wm-page-text { position: absolute; left: 16%; top: 38%; font-size: 46pt; color: #333;
  opacity: 0.08; transform: rotate(-24deg); white-space: nowrap; }
.wm-anchor { position: absolute; pointer-events: none; line-height: 0; }
.wm-lt { left: 4%; top: 4%; } .wm-mt { left: 50%; top: 4%; transform: translateX(-50%); } .wm-rt { right: 4%; top: 4%; }
.wm-lm { left: 4%; top: 45%; } .wm-mm { left: 50%; top: 45%; transform: translate(-50%, -50%); } .wm-rm { right: 4%; top: 45%; }
.wm-lb { left: 4%; bottom: 4%; } .wm-mb { left: 50%; bottom: 4%; transform: translateX(-50%); } .wm-rb { right: 4%; bottom: 4%; }
.wm-img { height: auto; }
.wm-placeholder { line-height: normal; font-size: 9pt; color: #9aa3b2; background: rgba(255,255,255,0.72);
  border: 1px dashed var(--hairline); border-radius: 4px; padding: 1px 4px; white-space: nowrap; }
@page { size: A4 ${orientation}; margin: 0; }
@media print {
  body { background: #fff; }
  .doc-hint { display: none !important; }
  .sheet-page { margin: 0; box-shadow: none; page-break-after: always; break-after: page; }
  .sheet-page.last { page-break-after: auto; break-after: auto; }
}`;
}
function dataUrlParts(url) {
  const m = /^data:([^;,]+);base64,(.+)$/s.exec(url.trim());
  return m ? { mime: m[1], b64: m[2] } : null;
}
function resolveWmItems(pad, wmAssets, orientation) {
  const pageW = PAGE_W_MM[orientation] ?? 210;
  const raw = (pad.watermark.items ?? []).filter((it) => it && it.image);
  const list = raw.length ? raw.map((it) => ({ image: it.image, pos: it.pos, ratio: it.ratio, alpha: it.alpha })) : [
    // 空 items = 默认三槽占位（engine watermark preset 2603 缺省；PWA 无文件 → 占位标记）
    { image: "university", pos: "rt", ratio: 0.125, alpha: 0.5, defaultLogo: "logo-university.png" },
    { image: "text", pos: "lm", ratio: 0.1, alpha: 0.3, defaultLogo: "logo-text.png" },
    { image: "boat", pos: "lb", ratio: 0.3, alpha: 0.5, defaultLogo: "logo-boat.png" }
  ];
  return list.map((it) => {
    let dataUrl = "";
    let label = it.image;
    if (it.image.startsWith("data:")) {
      dataUrl = it.image;
      label = "\uFF08\u672C\u6D4F\u89C8\u5668\u5185\u5D4C\u56FE\u7247\uFF09";
    } else {
      const base = it.image.split("/").pop() ?? it.image;
      const hit = wmAssets?.[base] ?? wmAssets?.[it.image];
      if (hit) {
        dataUrl = hit;
        label = base;
      }
    }
    return {
      pos: it.pos,
      ratio: it.ratio,
      alpha: it.alpha,
      widthMm: Math.round(pageW * it.ratio * 10) / 10,
      dataUrl,
      label
    };
  });
}
function wmLayerHtml(wm, pageText, pageN) {
  const parts = ['<div class="wm-layer" aria-hidden="true">'];
  if (pageText) parts.push(`<span class="wm-page-text">\u7B2C ${pageN} \u9875</span>`);
  wm.forEach((it, i) => {
    parts.push(`<div class="wm-anchor wm-${escapeHtml(it.pos)}" data-wm-item="${i + 1}" data-wm-pos="${escapeHtml(it.pos)}" style="opacity: ${it.alpha};">`);
    if (it.dataUrl) {
      const p = dataUrlParts(it.dataUrl);
      parts.push(p ? `<img class="wm-img" src="data:${p.mime};base64,${p.b64}" style="width: ${it.widthMm}mm;" alt="">` : `<img class="wm-img" src="${escapeHtml(it.dataUrl)}" style="width: ${it.widthMm}mm;" alt="">`);
    } else {
      parts.push(`<span class="wm-placeholder">[\u6C34\u5370\uFF1A${escapeHtml(it.label)}\uFF08${escapeHtml(it.pos)}\uFF09]</span>`);
    }
    parts.push("</div>");
  });
  parts.push("</div>");
  return parts.join("");
}
function figHtml(imgPath, figAssets) {
  if (!imgPath) return "";
  const base = imgPath.split("/").pop() ?? imgPath;
  const hit = figAssets?.[base];
  if (hit && hit.startsWith("data:")) {
    return `<img class="q-img" src="${escapeHtml(hit)}" alt="\u9898\u56FE">`;
  }
  return `<div class="q-img-ph">[\u9898\u56FE\uFF1A${escapeHtml(imgPath)}]</div>`;
}
function katexIncludeHtml(mode = "cdn", raw) {
  if (mode === "raw" && raw) {
    return [
      `<!-- KaTeX ${KATEX_VERSION}\uFF08\u5185\u8054\u81EA\u5305\u542B\uFF1Acss+js+woff2 \u5168\u90E8\u5185\u8054\uFF1Bfile:// \u79BB\u7EBF\u53EF\u5F00\uFF09 -->`,
      "<style>",
      raw.css,
      "</style>",
      "<script>",
      raw.katexJs,
      "</script>",
      "<script>",
      raw.autoRenderJs,
      "</script>"
    ].join("\n");
  }
  if (mode === "relative") {
    return `<!-- KaTeX ${KATEX_VERSION}\uFF08\u540C\u6E90\u81EA\u6258\u7BA1 ./katex/\uFF0C\u968F PWA dist \u53D1\u5E03\uFF1B\u79BB\u7EBF\u53EF\u6E32\u67D3\uFF09 -->
<link rel="stylesheet" href="./katex/katex.min.css">
<script defer src="./katex/katex.min.js"></script>
<script defer src="./katex/contrib/auto-render.min.js"></script>`;
  }
  return `<!-- KaTeX ${KATEX_VERSION}\uFF08CDN\uFF09\uFF1A\u9898\u5E72/\u7B54\u6848\u4E2D $..$\u3001$$..$$ \u81EA\u52A8\u6E32\u67D3\u3002
     \u79BB\u7EBF\u573A\u666F\uFF1ACDN \u4E0D\u53EF\u8FBE\u65F6 renderMathInElement \u4E0D\u5B58\u5728\uFF0C\u516C\u5F0F\u6309 $..$ \u6E90\u7801\u964D\u7EA7\u663E\u793A\u3002 -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@${KATEX_VERSION}/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@${KATEX_VERSION}/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@${KATEX_VERSION}/dist/contrib/auto-render.min.js"></script>`;
}
var katexBundleCache = null;
function blobToDataUrl(buf) {
  let bin = "";
  const bytes = new Uint8Array(buf);
  const chunk = 32768;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return "data:font/woff2;base64," + btoa(bin);
}
async function fetchSelfContainedKatex() {
  if (katexBundleCache) return katexBundleCache;
  const base = document.baseURI;
  const [cssRes, jsRes, arRes] = await Promise.all([
    fetch(new URL("./katex/katex.min.css", base).href),
    fetch(new URL("./katex/katex.min.js", base).href),
    fetch(new URL("./katex/contrib/auto-render.min.js", base).href)
  ]);
  if (!cssRes.ok || !jsRes.ok || !arRes.ok) {
    throw new Error("KaTeX \u81EA\u6258\u7BA1\u8D44\u6E90\u62C9\u53D6\u5931\u8D25\uFF08\u9700 Pages/\u5F15\u64CE\u540C\u6E90\u73AF\u5883\u63D0\u4F9B ./katex/\uFF09");
  }
  let css = await cssRes.text();
  const js = await jsRes.text();
  const autoRenderJs = await arRes.text();
  const names = /* @__PURE__ */ new Set();
  for (const m of css.matchAll(/url\(fonts\/([^)'"\s]+)\.(woff2|woff|ttf)\)/g)) names.add(m[1]);
  const b64 = /* @__PURE__ */ new Map();
  for (const name of names) {
    const res = await fetch(new URL(`katex/fonts/${name}.woff2`, base).href);
    if (res.ok) b64.set(name, blobToDataUrl(await res.arrayBuffer()));
  }
  css = css.replace(/url\(fonts\/([^)'"\s]+)\.woff2\)/g, (m, n) => b64.get(n) ? `url(${b64.get(n)})` : m).replace(/,\s*url\(fonts\/[^)]+\.woff\)\s*format\("woff"\)/g, "").replace(/,\s*url\(fonts\/[^)]+\.ttf\)\s*format\("truetype"\)/g, "");
  katexBundleCache = { css, katexJs: js, autoRenderJs };
  return katexBundleCache;
}
async function buildSelfContainedHtml(inputs, opts = {}) {
  try {
    const assets = await fetchSelfContainedKatex();
    return stringifySheetHtml(inputs, { ...opts, katex: "raw", katexRaw: assets });
  } catch {
    return stringifySheetHtml(inputs, opts);
  }
}
function katexScript() {
  return `<script>
/* KaTeX \u81EA\u52A8\u6E32\u67D3\uFF08\u4EC5\u9898\u5E72/\u7B54\u6848\uFF1BCDN \u4E0D\u53EF\u8FBE\u65F6\u8DF3\u8FC7=\u6E90\u7801\u964D\u7EA7\uFF0C\u4E0D\u62A5\u9519\uFF09 */
document.addEventListener('DOMContentLoaded', function () {
  if (typeof window.renderMathInElement !== 'function') return;
  var opts = {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '$', right: '$', display: false }
    ],
    throwOnError: false
  };
  document.querySelectorAll('.q-content, .q-solution').forEach(function (el) {
    try { window.renderMathInElement(el, opts); } catch (e) { /* \u964D\u7EA7\uFF1A\u4FDD\u7559\u6E90\u7801 */ }
  });
});
</script>`;
}
function pageBlockHtml(pad, items, stu, pagesTotal, pageN, isVeryLast, wm, date, includeSolution = true, includeWatermark = true, includePageText = true, figAssets) {
  const layout = pad.layout;
  const orientation = layout.orientation === "landscape" ? "landscape" : "portrait";
  const perPage = normalizePerPage(layout.per_page, layout.orientation);
  const lines = gridLines(orientation, perPage);
  const title = String(layout.header.title ?? "") || "\u4F5C\u4E1A\u7EB8";
  const footerText = String(layout.footer.text ?? "");
  const course = String(pad.course ?? "");
  const cls = stu.class || String(pad.class ?? "") || "classA";
  const blank = !stu.name && !stu.number && !stu.class;
  const rosterSpan = blank ? "<span>\u73ED\u7EA7\uFF1A\uFF3F\uFF3F\uFF3F\uFF3F\uFF3F\uFF3F</span>\n      <span>\u5B66\u53F7\uFF1A\uFF3F\uFF3F\uFF3F\uFF3F\uFF3F\uFF3F</span>\n      <span>\u59D3\u540D\uFF1A\uFF3F\uFF3F\uFF3F\uFF3F\uFF3F\uFF3F</span>" : `<span>\u73ED\u7EA7\uFF1A${escapeHtml(cls)}</span>
      <span>\u5B66\u53F7\uFF1A${escapeHtml(stu.number)}</span>
      <span>\u59D3\u540D\uFF1A${escapeHtml(stu.name)}</span>`;
  const frames = lines.length ? lines.map((ln) => `<div class="sf-line ${ln}"></div>`).join("\n    ") + "\n    " : "";
  return `<section class="sheet-page${orientation === "landscape" ? " landscape" : ""}${isVeryLast ? " last" : ""}" data-student="${escapeHtml(stu.name)}" data-page="${pageN}">
  ${pad.watermark.enabled && includeWatermark ? wmLayerHtml(wm, pad.watermark.pageText !== false && includePageText, pageN) : ""}
  <div class="sheet-header">
    <div class="sh-title">${escapeHtml(title)}</div>
    <div class="sh-info">
      ${course ? `<span>\u8BFE\u7A0B\uFF1A${escapeHtml(course)}</span>
      ` : ""}${rosterSpan}
      <span class="sh-assign">\u4F5C\u4E1A\uFF1A${escapeHtml(pad.id)}</span>
      <span class="sh-assign">\u65E5\u671F\uFF1A${escapeHtml(date)}</span>
    </div>
  </div>
  <div class="sheet-body${lines.length ? " divided" : ""}" data-grid="${gridKey(orientation, perPage)}">
    ${frames}${items.map((fr) => `<div class="sheet-frame">
      <div class="q-id">${escapeHtml(fr.id)}${fr.tag ? ` <span class="q-tag">\u3010${escapeHtml(fr.tag)}\u3011</span>` : ""}</div>
      <div class="q-content">${escapeHtml(fr.content)}</div>
      ${figHtml(fr.imgPath, figAssets)}
      ${includeSolution && fr.solution ? `<div class="q-solution">\u53C2\u8003\u7B54\u6848\uFF1A${escapeHtml(fr.solution)}</div>` : ""}
    </div>`).join("\n    ")}
  </div>
  <div class="sheet-footer">
    <span>${footerText ? `${escapeHtml(footerText)} \xB7 ` : ""}${escapeHtml(pad.id)}-\u7B2C ${pageN}/${pagesTotal}\u9875</span>
    <span>\u7B7E\u540D\uFF1A</span>
    <span>\u65E5\u671F\uFF1A${escapeHtml(date)}</span>
  </div>
</section>`;
}
function stringifySheetHtml(inputs, opts = {}) {
  const pads = Array.isArray(inputs) ? inputs : [inputs];
  if (!pads.length) throw new Error("stringifySheetHtml\uFF1A\u81F3\u5C11\u9700\u8981\u4E00\u4EFD\u4F5C\u4E1A\u7EB8");
  const students = opts.students?.length ? opts.students : SYNTHETIC_STUDENTS;
  const date = opts.date ?? todayStr();
  const mode = opts.katex ?? "cdn";
  const includeSolution = opts.includeSolution !== false;
  const includeWatermark = opts.includeWatermark !== false;
  const includePageText = opts.includePageText !== false;
  const first = pads[0].pad;
  const orientation = first.layout.orientation === "landscape" ? "landscape" : "portrait";
  const docTitle = String(first.layout.header.title ?? "") || "\u4F5C\u4E1A\u7EB8";
  const pageSections = [];
  for (let padIdx = 0; padIdx < pads.length; padIdx++) {
    const { pad, items } = pads[padIdx];
    const perPage = normalizePerPage(pad.layout.per_page, pad.layout.orientation);
    const chunks = [];
    for (let i = 0; i < items.length; i += perPage) chunks.push(items.slice(i, i + perPage));
    if (!chunks.length) chunks.push([]);
    const wm = resolveWmItems(pad, opts.wmAssets, pad.layout.orientation === "landscape" ? "landscape" : "portrait");
    const stuList = pads[padIdx].students?.length ? pads[padIdx].students : students;
    for (let si = 0; si < stuList.length; si++) {
      const stu = stuList[si];
      chunks.forEach((chunk, pi) => {
        const veryLast = padIdx === pads.length - 1 && si === stuList.length - 1 && pi === chunks.length - 1;
        pageSections.push(pageBlockHtml(
          pad,
          chunk,
          stu,
          chunks.length,
          pi + 1,
          veryLast,
          wm,
          date,
          includeSolution,
          includeWatermark,
          includePageText,
          opts.figAssets
        ));
      });
    }
  }
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(docTitle)} \xB7 ${escapeHtml(first.id)}</title>
${katexIncludeHtml(mode, opts.katexRaw)}
<style>
${printCss(orientation)}
</style>
</head>
<body>
<div class="doc-hint">
  \u6253\u5370\uFF08Ctrl/Cmd+P\uFF09\uFF1A\u7EB8\u5F20=A4 \xB7 \u8FB9\u8DDD=\u65E0 \xB7 \u9875\u7709\u9875\u811A=\u5173 \xB7 \u80CC\u666F\u56FE\u5F62=\u5F00\uFF08\u6C34\u5370\u5C42\u4F9D\u8D56\u80CC\u666F\u56FE\u5F62\uFF0Cdocs/14 \xA7VB-6\uFF09\u3002
  \u76EE\u6807\u9009\u300C\u53E6\u5B58\u4E3A PDF\u300D\u53EF\u4FDD\u5B58\u6574\u73ED PDF\u3002\u516C\u5F0F\u7531 KaTeX \u6E32\u67D3\uFF1A\u9884\u89C8/\u6253\u5370\u7528 PWA \u540C\u6E90\u81EA\u6258\u7BA1 ./katex/\uFF08\u79BB\u7EBF\u53EF\u6E32\u67D3\uFF09\uFF1B\u5BFC\u51FA HTML \u81EA\u5305\u542B\u5185\u8054\uFF08file:// \u79BB\u7EBF\u53EF\u5F00\uFF09\uFF1BCDN \u7248\u65AD\u7F51\u65F6\u6309 $..$ \u6E90\u7801\u964D\u7EA7\u3002
</div>
${pageSections.join("\n")}
${katexScript()}
</body>
</html>`;
}
function downloadSheetHtml(html, filename) {
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1e4);
}
function printSheetHtml(html) {
  const iframe = document.createElement("iframe");
  iframe.setAttribute("aria-hidden", "true");
  iframe.style.position = "fixed";
  iframe.style.right = "0";
  iframe.style.bottom = "0";
  iframe.style.width = "0";
  iframe.style.height = "0";
  iframe.style.border = "0";
  iframe.srcdoc = html;
  const cleanup = () => {
    try {
      iframe.remove();
    } catch {
    }
  };
  iframe.onload = () => {
    setTimeout(() => {
      try {
        iframe.contentWindow?.focus();
        iframe.contentWindow?.print();
      } catch {
      }
      setTimeout(cleanup, 6e4);
    }, 300);
  };
  document.body.appendChild(iframe);
}
function expandPadItems(pad, bookOf) {
  const out = [];
  for (const item of pad.items) {
    const chap = bookOf(item.kb)?.chapters.find((c) => c.name === item.chap);
    if (!chap) continue;
    for (const id of item.ids) {
      const r = chap.rows.find((x) => x.id === id);
      if (r) out.push({ id, content: r.content, solution: r.solution, imgPath: r.img_path, tag: item.tag });
    }
  }
  return out;
}
export {
  BLANK_STUDENT,
  KATEX_VERSION,
  SYNTHETIC_STUDENTS,
  buildSelfContainedHtml,
  downloadSheetHtml,
  expandPadItems,
  fetchSelfContainedKatex,
  printCss,
  printSheetHtml,
  stringifySheetHtml,
  todayStr
};
