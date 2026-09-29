// src/lib/rosterXlsx.ts
import * as XLSX from "xlsx";

// src/lib/roster.ts
var SCORE_FAMILY_PRESETS = [
  { value: "roster", label: "\u6559\u52A1\u70B9\u540D\u518C\uFF08\u4EC5\u63A5\u8868\uFF0C\u4E0D\u8BA1\u5206\uFF09", desc: "\u56FA\u5B9A\u683C\u5F0F\uFF08\u6765\u81EA\u6559\u52A1\u7CFB\u7EDF\u5BFC\u51FA\uFF09\uFF1A\u59D3\u540D/\u5B66\u53F7/\u73ED\u7EA7\u5217\uFF0C\u4F5C\u4E3A\u540D\u5355\u63A5\u8868\u7528\uFF0C\u4E0D\u53C2\u4E0E\u52A0\u6743\u8BA1\u5206\u3002", fixed: true },
  { value: "exam", label: "\u6559\u52A1\u671F\u672B\u6210\u7EE9\u8868", desc: '\u56FA\u5B9A\u683C\u5F0F\uFF08\u6765\u81EA\u6559\u52A1\u7CFB\u7EDF\u5BFC\u51FA\uFF09\uFF1A\u8868\u5934\u542B"\u671F\u672B(\u5FC5\u586B)"\u5217\uFF0C\u76F4\u63A5\u53D6\u8BE5\u5217\u5206\u6570\u3002', fixed: true },
  { value: "xuexitong_assignment", label: "\u5B66\u4E60\u901A\xB7\u4F5C\u4E1A\u7EDF\u8BA1", desc: '\u56FA\u5B9A\u683C\u5F0F\uFF08\u6765\u81EA\u5B66\u4E60\u901A\u5BFC\u51FA\uFF09\uFF1A\u524D 8 \u884C\u5185\u542B"\u6210\u7EE9"\u884C\uFF0C\u5176\u4E0A\u4E00\u884C\u4E3A\u4F5C\u4E1A\u6807\u9898\uFF0C\u6570\u636E\u884C\u5728\u4E0B\u65B9\uFF1B\u6BCF\u751F\u53D6\u5404\u4F5C\u4E1A\u5747\u5206\u3002', fixed: true },
  { value: "xuexitong_stat", label: "\u5B66\u4E60\u901A\xB7\u7AE0\u8282\u6D4B\u9A8C\uFF08\u7EDF\u8BA1\u6587\u4EF6\uFF09", desc: '\u56FA\u5B9A\u683C\u5F0F\uFF08\u6765\u81EA\u5B66\u4E60\u901A\u5BFC\u51FA\uFF09\uFF1A\u6309 sheet \u540D\u542B"\u7AE0\u8282\u6D4B\u9A8C"\u5339\u914D\uFF0C\u7B2C 4 \u884C\u4E3A\u8868\u5934\u627E"\u6210\u7EE9"\u5217\uFF0C\u975E 0 \u8BA1\u5165\u53D6\u5747\u5206\u3002', fixed: true },
  { value: "rainclass", label: "\u96E8\u8BFE\u5802\u6C47\u603B\u8868", desc: "\u56FA\u5B9A\u683C\u5F0F\uFF08\u6765\u81EA\u96E8\u8BFE\u5802\u5BFC\u51FA\uFF09\uFF1A\u65E0\u8868\u5934\uFF0C\u7B2C 2 \u884C\u4E3A\u5217\u6807\u9898\uFF0C\u524D 3 \u5217\u4E3A\u5B66\u53F7/\u59D3\u540D/\u6C47\u603B\uFF0C\u5176\u540E\u6BCF\u8BFE 2 \u5217\uFF08\u65B9\u5F0F+\u5F97\u5206\uFF09\uFF0C\u53D6\u6BCF\u8BFE\u5F97\u5206\u5747\u503C\u3002", fixed: true },
  { value: "custom", label: "\u81EA\u5B9A\u4E49\uFF08\u624B\u52A8\u9009\u5217\uFF09", desc: "\u5176\u4ED6\u6210\u7EE9\uFF08\u9AD8\u8003\u6570\u5B66/\u5927\u4E00\u9AD8\u6570\u7B49\uFF09\uFF1A\u624B\u52A8\u6307\u5B9A\u59D3\u540D\u5217\u4E0E\u5206\u6570\u6765\u6E90\u5217 + \u6743\u91CD\u3002", fixed: false }
];
function isIncluded(src) {
  return src.includeInAggregation !== false;
}
function normalizeSource(s) {
  const family = SCORE_FAMILY_PRESETS.some((p) => p.value === s.family) ? s.family : "custom";
  return {
    uid: s.uid,
    // D46-3：IndexedDB raw 键必须透传（此前会被 normalize 吃掉）
    sheetName: s.sheetName,
    // B1：实际解析 sheet 名透传
    name: String(s.name ?? ""),
    fileName: String(s.fileName ?? ""),
    family,
    scoreColumn: String(s.scoreColumn ?? ""),
    nameColumn: String(s.nameColumn ?? ""),
    weight: Number(s.weight ?? 1) || 1,
    rows: Array.isArray(s.rows) ? s.rows : [],
    scores: s.scores && typeof s.scores === "object" ? s.scores : {},
    includeInAggregation: s.includeInAggregation === void 0 ? true : Boolean(s.includeInAggregation)
  };
}

// src/lib/rosterXlsx.ts
var ROSTER_COLUMNS = ["name", "number", "class", "tag"];
var ROSTER_COLUMN_LABELS = {
  name: "\u59D3\u540D",
  number: "\u5B66\u53F7",
  class: "\u73ED\u7EA7",
  tag: "tag"
};
function newUid() {
  try {
    return crypto.randomUUID();
  } catch {
    return `src-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }
}
var HEADER_MAP = {
  "\u59D3\u540D": "name",
  "name": "name",
  "student": "name",
  "\u5B66\u751F": "name",
  "\u5B66\u53F7": "number",
  "number": "number",
  "id": "number",
  "\u5B66\u7C4D\u53F7": "number",
  "\u73ED\u7EA7": "class",
  "class": "class",
  "tag": "tag",
  "\u6807\u7B7E": "tag"
};
var FAMILIES = [
  "roster",
  "exam",
  "xuexitong_assignment",
  "xuexitong_stat",
  "rainclass",
  "custom"
];
function rosterFail(reason, matrix, sheetNames) {
  const e = new Error(reason === "no-sheet" ? "\u6587\u4EF6\u5185\u65E0 sheet" : "\u672A\u8BC6\u522B\u51FA\u59D3\u540D\u5217\uFF08\u8868\u5934\u81EA\u9002\u5E94\u4E0E\u5173\u952E\u8BCD\u627E\u8868\u5934\u884C\u4E24\u7EA7\u5747\u5931\u8D25\uFF09");
  e.reason = reason;
  e.firstRows = matrix.slice(0, 3);
  e.sheetNames = sheetNames;
  throw e;
}
function mapStudentsFromMatrix(matrix, headerI) {
  const headers = (matrix[headerI] ?? []).map((c) => c.trim());
  const cols = [];
  headers.forEach((h, j) => {
    const key = HEADER_MAP[h.toLowerCase()] ?? HEADER_MAP[h];
    if (key === "name" || key === "number" || key === "class" || key === "tag") cols.push({ j, key });
  });
  const out = [];
  for (let i = headerI + 1; i < matrix.length; i++) {
    const row = matrix[i];
    if (!row) continue;
    const stu = { name: "", number: "", class: "", tag: "", score: null, manualTag: false, punish: false };
    for (const { j, key } of cols) {
      const v = str(row[j] ?? "");
      if (key === "tag") {
        stu.tag = v;
        stu.manualTag = v !== "";
      } else stu[key] = v;
    }
    if (stu.name) out.push(stu);
  }
  return out;
}
async function readRosterXlsx(source) {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source;
  const wb = XLSX.read(buf, { type: "array" });
  const sheet = wb.Sheets[wb.SheetNames[0]];
  if (!sheet) rosterFail("no-sheet", [], wb.SheetNames);
  const matrix = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: "" }).map((r) => (r ?? []).map((c) => str(c)));
  let students = mapStudentsFromMatrix(matrix, 0);
  if (students.length) return students;
  const NAME_TOKENS = ["\u59D3\u540D", "\u540D\u5B57", "name", "\u5B66\u751F", "student"];
  for (let hi = 1; hi < Math.min(15, matrix.length); hi++) {
    const row = matrix[hi] ?? [];
    if (row.some((c) => NAME_TOKENS.includes(String(c).trim().toLowerCase()))) {
      students = mapStudentsFromMatrix(matrix, hi);
      if (students.length) return students;
    }
  }
  rosterFail("no-name-column", matrix, wb.SheetNames);
}
function allSheetMatrices(wb) {
  return wb.SheetNames.map((name) => ({
    name,
    matrix: XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, defval: "" }).map((r) => Array.isArray(r) ? r.map((c) => str(c)) : [])
  }));
}
function pickBestSheet(ms) {
  if (!ms.length) return null;
  const nonEmpty = ms.filter((m) => m.matrix.some((r) => r.some((c) => c !== "")));
  if (!nonEmpty.length) return ms[0];
  const NAME_TOKENS = ["\u59D3\u540D", "\u540D\u5B57", "name", "\u5B66\u751F", "student"];
  const hasNameHeader = (m) => m.matrix.slice(0, 15).some((row) => (row ?? []).some((c) => NAME_TOKENS.includes(String(c).trim().toLowerCase())));
  const withHeader = nonEmpty.filter(hasNameHeader);
  const pool = withHeader.length ? withHeader : nonEmpty;
  const dataRows = (m) => m.matrix.filter((r) => r.some((c) => c !== "")).length;
  return pool.reduce((best, cur) => dataRows(cur) > dataRows(best) ? cur : best);
}
function readRawSheet(buf0, fileName, sheetName) {
  const wb = XLSX.read(buf0, { type: "array" });
  const names = wb.SheetNames;
  const ms = allSheetMatrices(wb);
  const chosen = (sheetName ? ms.find((m) => m.name === sheetName) : void 0) ?? pickBestSheet(ms);
  return { fileName, sheetNames: names, matrix: chosen?.matrix ?? [], sheetName: chosen?.name ?? "" };
}
function num(v) {
  if (v === "") return null;
  const f = Number(v.replace(/[^\d.eE+-]/g, ""));
  return Number.isFinite(f) ? f : null;
}
function parseExam(m) {
  const headers = m.matrix[0] ?? [];
  const nameI = Math.max(0, headers.findIndex((h) => HEADER_MAP[h] === "name"));
  const scoreI = headers.findIndex((h) => h.includes("\u671F\u672B"));
  const col = scoreI >= 0 ? headers[scoreI] : headers[headers.length - 1] ?? "";
  const scores = {};
  for (const r of m.matrix.slice(1)) {
    const name = (r[nameI] ?? "").trim();
    const v = scoreI >= 0 ? num(r[scoreI] ?? "") : null;
    if (name && v !== null) scores[name] = v;
  }
  return { scores, nameColumn: headers[nameI] ?? "", scoreColumn: col };
}
function parseXuexitongAssignment(m) {
  const rows = m.matrix;
  let sr = -1;
  for (let i = 0; i < Math.min(8, rows.length); i++) {
    if (rows[i].some((c) => c.includes("\u6210\u7EE9"))) {
      sr = i;
      break;
    }
  }
  if (sr < 1) return { scores: {}, nameColumn: rows[0]?.[0] ?? "\u59D3\u540D", scoreColumn: '\uFF08\u524D8\u884C\u672A\u627E\u5230"\u6210\u7EE9"\u884C\uFF09' };
  const titles = rows[sr - 1] ?? [];
  const perStu = {};
  for (let k = 0; k < rows[sr].length; k++) {
    if (!rows[sr][k].includes("\u6210\u7EE9")) continue;
    for (const r of rows.slice(sr + 1)) {
      const name = (r[0] ?? "").trim();
      const v = num(r[k] ?? "");
      if (name && v !== null) (perStu[name] ??= []).push(v);
    }
  }
  const scores = {};
  for (const [nm, list] of Object.entries(perStu)) {
    if (list.length) scores[nm] = list.reduce((a, b) => a + b, 0) / list.length;
  }
  return { scores, nameColumn: rows[sr + 1]?.[0] ?? rows[0]?.[0] ?? "\u59D3\u540D", scoreColumn: `${titles.filter((t) => t).length || "?"} \u4E2A"\u6210\u7EE9"\u5217\u5747\u5206` };
}
function parseXuexitongStat(m) {
  const rows = m.matrix;
  if (rows.length <= 4) return { scores: {}, nameColumn: "", scoreColumn: "\uFF08\u884C\u6570\u4E0D\u8DB3\uFF1A\u9700\u7B2C4\u884C\u8868\u5934+\u6570\u636E\u884C\uFF09" };
  const heads = rows[3];
  const cols = heads.map((h, j) => h.includes("\u6210\u7EE9") ? j : -1).filter((j) => j >= 0);
  const perStu = {};
  for (const r of rows.slice(4)) {
    const name = (r[0] ?? "").trim();
    if (!name) continue;
    for (const j of cols) {
      const v = num(r[j] ?? "");
      if (v !== null && v !== 0) (perStu[name] ??= []).push(v);
    }
  }
  const scores = {};
  for (const [nm, list] of Object.entries(perStu)) {
    if (list.length) scores[nm] = list.reduce((a, b) => a + b, 0) / list.length;
  }
  return { scores, nameColumn: rows[4]?.[0] ?? "\u59D3\u540D", scoreColumn: cols.map((j) => heads[j]).join("|") || '\uFF08\u7B2C4\u884C\u672A\u89C1"\u6210\u7EE9"\u5217\uFF09' };
}
function parseRainclass(m) {
  const rows = m.matrix;
  if (rows.length < 3) return { scores: {}, nameColumn: "", scoreColumn: "\uFF08\u884C\u6570\u4E0D\u8DB3\uFF09" };
  const nCourses = Math.max(0, Math.floor(((rows[1]?.length ?? 0) - 3) / 2));
  const scores = {};
  for (const r of rows.slice(3)) {
    const name = (r[1] ?? "").trim();
    if (!name) continue;
    const list = [];
    for (let c = 0; c < nCourses; c++) {
      const v = num(r[3 + 2 * c + 1] ?? "");
      if (v !== null) list.push(v);
    }
    if (list.length) scores[name] = list.reduce((a, b) => a + b, 0) / list.length;
  }
  return { scores, nameColumn: "\uFF08\u7B2C2\u5217\xB7\u96E8\u8BFE\u5802\u65E0\u8868\u5934\uFF09", scoreColumn: `\u6BCF\u8BFE\u5F97\u5206\u5217\u5747\u503C\uFF08${nCourses} \u8BFE\uFF09` };
}
async function readScoreSourceXlsx(source, fileName, family = "custom", sheetName) {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source;
  const m = readRawSheet(buf, fileName, sheetName);
  if (!m.matrix.length || m.matrix.every((r) => r.every((c) => c === ""))) {
    throw new Error(`\u6587\u4EF6\u65E0\u6570\u636E\uFF1A${fileName}`);
  }
  const base = {
    uid: newUid(),
    sheetName: m.sheetName ?? "",
    // B1：记录实际解析的 sheet（normalizeSource 透传）
    name: fileName.replace(/\.xlsx$/i, ""),
    fileName,
    family,
    weight: 1,
    rows: m.matrix.slice(1).filter((r) => r.some((c) => c !== "")).map((r) => {
      const out = {};
      const headers2 = m.matrix[0] ?? [];
      for (let i = 0; i < r.length; i++) out[headers2[i] || `\u5217${i + 1}`] = r[i];
      return out;
    }),
    scores: {}
  };
  if (family === "roster") {
    return normalizeSource({ ...base, scoreColumn: "\uFF08\u70B9\u540D\u518C\uFF1A\u4EC5\u63A5\u8868\uFF0C\u4E0D\u8BA1\u5206\uFF09", nameColumn: (m.matrix[0] ?? []).find((h) => HEADER_MAP[h] === "name") ?? "\u59D3\u540D" });
  }
  if (family === "exam") return normalizeSource({ ...base, ...parseExam(m) });
  if (family === "xuexitong_assignment") return normalizeSource({ ...base, ...parseXuexitongAssignment(m) });
  if (family === "xuexitong_stat") return normalizeSource({ ...base, ...parseXuexitongStat(m) });
  if (family === "rainclass") return normalizeSource({ ...base, ...parseRainclass(m) });
  const headers = m.matrix[0] ?? [];
  const guessName = headers.find((h) => HEADER_MAP[h] === "name") ?? headers[0] ?? "";
  const nameI = Math.max(0, headers.indexOf(guessName));
  const countNums = (j) => m.matrix.slice(1, 21).filter((r) => num(r[j] ?? "") !== null).length;
  let scoreI = headers.findIndex((h, j) => j !== nameI && /分数|成绩|得分|score/i.test(h));
  if (scoreI < 0) {
    let best = 0;
    for (let j = 0; j < headers.length; j++) {
      if (j === nameI) continue;
      const nNums = countNums(j);
      if (nNums > best) {
        best = nNums;
        scoreI = j;
      }
    }
  }
  if (scoreI < 0) scoreI = headers.length - 1;
  const guessScore = headers[scoreI] ?? "";
  const scores = {};
  for (const r of m.matrix.slice(1)) {
    const name = (r[nameI] ?? "").trim();
    const v = num(r[scoreI] ?? "");
    if (name && v !== null) scores[name] = v;
  }
  return normalizeSource({ ...base, scoreColumn: guessScore, nameColumn: guessName, scores });
}
var PREVIEW_ROW_LIMIT = 3;
function previewFromMatrix(headers, dataRows, notes) {
  const rows = dataRows.filter((r) => r.some((c) => c.trim() !== "")).slice(0, PREVIEW_ROW_LIMIT).map((r) => headers.map((_, j) => r[j] ?? ""));
  return { headers, rows, notes, rowCount: dataRows.filter((r) => r.some((c) => c.trim() !== "")).length };
}
async function buildRosterPreview(source) {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source;
  const wb = XLSX.read(buf, { type: "array" });
  const sheet = wb.Sheets[wb.SheetNames[0]];
  if (!sheet) return { headers: [], rows: [], notes: ["\uFF08\u6587\u4EF6\u5185\u65E0 sheet\uFF09"], rowCount: 0 };
  const matrix = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: "" }).map((r) => (r ?? []).map((c) => str(c)));
  const NAME_TOKENS = ["\u59D3\u540D", "\u540D\u5B57", "name", "\u5B66\u751F", "student"];
  let headerI = 0;
  let modeNote = "\u8868\u5934\u81EA\u9002\u5E94\uFF08\u7B2C 1 \u884C\uFF09";
  if (mapStudentsFromMatrix(matrix, 0).length === 0) {
    const hit = matrix.slice(1, 15).findIndex((row) => (row ?? []).some((c) => NAME_TOKENS.includes(String(c).trim().toLowerCase())));
    if (hit >= 0) {
      headerI = hit + 1;
      modeNote = `\u5173\u952E\u8BCD\u5B9A\u4F4D\u8868\u5934\u884C\uFF08\u7B2C ${headerI + 1} \u884C\u542B"\u59D3\u540D/name"\u2014\u2014zjxu \u540D\u518C\u5F62\u6001\uFF0C\u524D ${headerI} \u884C\u4E3A\u8BF4\u660E\u6587\u5B57\u5DF2\u8DF3\u8FC7\uFF09`;
    } else {
      modeNote = "\u26A0 \u4E24\u7EA7\u56DE\u9000\u5747\u672A\u627E\u5230\u59D3\u540D\u5217\uFF1A\u8BFB\u5165\u5C06\u5931\u8D25\uFF08\u8BF7\u6838\u5BF9\u524D\u51E0\u884C\u5185\u5BB9\uFF1B\u82E5\u4E3A\u6559\u52A1\u540D\u518C\u4E14\u8868\u5934\u7F3A\u5931\uFF0C\u5220\u81F3\u4EC5\u5269\u8868\u5934\u884C\u540E\u91CD\u8BD5\uFF09";
    }
  }
  const headers = (matrix[headerI] ?? []).map((c) => str(c));
  const rows = matrix.slice(headerI + 1).map((r) => (r ?? []).map((c) => str(c)));
  const notes = [modeNote, ...headers.filter((h) => HEADER_MAP[h] || HEADER_MAP[h.trim().toLowerCase()]).map((h) => {
    const key = HEADER_MAP[h] ?? HEADER_MAP[h.trim().toLowerCase()];
    return `${h} \u2192 ${key}${key === "tag" ? "\uFF08\u539F\u6837\u5E26\u5165\uFF0C\u53EF\u540E\u7EED\u8986\u76D6\uFF09" : ""}`;
  })];
  return previewFromMatrix(headers, rows, notes);
}
async function buildScoreSourcePreview(source, family = "custom", sheetName) {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source;
  const wb = XLSX.read(buf, { type: "array" });
  const ms = allSheetMatrices(wb);
  const chosen = (sheetName ? ms.find((x) => x.name === sheetName) : void 0) ?? pickBestSheet(ms);
  if (!chosen) return { headers: [], rows: [], notes: ["\uFF08\u6587\u4EF6\u5185\u65E0 sheet\uFF09"], rowCount: 0 };
  const matrix = chosen.matrix;
  const headers = (matrix[0] ?? []).map((c) => str(c));
  const rows = matrix.slice(1).map((r) => (r ?? []).map((c) => str(c)));
  const notes = [
    `sheet\uFF1A${chosen.name || "\uFF08\u65E0\u540D\uFF09"}${wb.SheetNames.length > 1 ? `\uFF08B1 \u81EA\u52A8\u9009\u62E9\uFF0C\u5171 ${wb.SheetNames.length} \u5F20\uFF1A${wb.SheetNames.join(" / ")}\uFF1B\u53EF\u5728\u6E90\u884C\u5207\u6362\uFF09` : ""} \xB7 \u683C\u5F0F\u9884\u8BBE\uFF1A${family}`
  ];
  if (family === "roster") {
    notes.push("\u6559\u52A1\u70B9\u540D\u518C\uFF1A\u4EC5\u63A5\u8868\u4E0D\u8BA1\u5206\uFF0C\u6309 \u59D3\u540D/name \u5217\u8BC6\u522B\u3002");
  } else if (family === "exam") {
    const hit = headers.find((h) => h.includes("\u671F\u672B"));
    notes.push(hit ? `\u6559\u52A1\u671F\u672B\uFF1A\u5206\u6570\u5217\u5B9A\u4F4D = \u542B"\u671F\u672B"\u7684\u5217\u300C${hit}\u300D\u3002` : '\u6559\u52A1\u671F\u672B\uFF1A\u8868\u5934\u672A\u89C1\u542B"\u671F\u672B"\u7684\u5217\uFF0C\u5C06\u56DE\u9000\u53D6\u6700\u540E\u4E00\u5217\u3002');
  } else if (family === "xuexitong_assignment") {
    notes.push('\u5B66\u4E60\u901A\xB7\u4F5C\u4E1A\u7EDF\u8BA1\uFF1A\u524D 8 \u884C\u5185\u627E"\u6210\u7EE9"\u884C\uFF0C\u5176\u4E0A\u4E00\u884C\u4E3A\u4F5C\u4E1A\u6807\u9898\uFF0C\u6BCF\u751F\u53D6\u5404"\u6210\u7EE9"\u5217\u5747\u5206\u3002');
  } else if (family === "xuexitong_stat") {
    notes.push('\u5B66\u4E60\u901A\xB7\u7AE0\u8282\u6D4B\u9A8C\uFF1A\u6309 sheet \u540D\u542B"\u7AE0\u8282\u6D4B\u9A8C"\u5339\u914D\uFF08\u5F53\u524D\u7B2C 1 \u4E2A sheet\uFF09\uFF0C\u7B2C 4 \u884C\u4E3A\u8868\u5934\u627E"\u6210\u7EE9"\u5217\uFF0C\u975E 0 \u8BA1\u5165\u53D6\u5747\u5206\u3002');
  } else if (family === "rainclass") {
    notes.push("\u96E8\u8BFE\u5802\u6C47\u603B\uFF1A\u65E0\u8868\u5934\uFF08\u7B2C 1 \u884C\u6309\u6570\u636E\u884C\u8DF3\u8FC7\uFF09\uFF0C\u7B2C 2 \u884C\u4E3A\u5217\u6807\u9898\uFF0C\u524D 3 \u5217 = \u5B66\u53F7/\u59D3\u540D/\u6C47\u603B\uFF0C\u5176\u540E\u6BCF\u8BFE 2 \u5217\u53D6\u5747\u503C\u3002");
  } else {
    const nameHit = headers.find((h) => HEADER_MAP[h] === "name") ?? headers[0] ?? "";
    const scoreHit = headers.find((h, j) => j !== headers.indexOf(nameHit) && /分数|成绩|得分|score/i.test(h));
    notes.push(`custom \u5BBD\u677E\u731C\u5217\uFF1A\u59D3\u540D\u5217 \u2248\u300C${nameHit || "\u7B2C 1 \u5217"}\u300D` + (scoreHit ? `\uFF0C\u5206\u6570\u5217 \u2248\u300C${scoreHit}\u300D\uFF08\u4E5F\u53EF\u5BFC\u5165\u540E\u5728\u6E90\u884C\u624B\u52A8\u6362\u5217\uFF09\u3002` : "\uFF0C\u5206\u6570\u5217 \u2248 \u6570\u503C\u6700\u591A\u7684\u5217\uFF08\u53EF\u5BFC\u5165\u540E\u624B\u52A8\u6362\u5217\uFF09\u3002"));
  }
  return previewFromMatrix(headers, rows, notes);
}
function writeRosterXlsx(students) {
  const aoa = [[...ROSTER_COLUMNS]];
  for (const s of students) aoa.push([s.name, s.number, s.class, s.tag]);
  const sheet = XLSX.utils.aoa_to_sheet(aoa);
  sheet["!cols"] = [{ wch: 14 }, { wch: 16 }, { wch: 18 }, { wch: 14 }];
  const wb = XLSX.utils.book_new();
  wb.Props = { Title: "roster\uFF08assignment-assistant \u5BFC\u51FA\uFF0Cengine assist sheet make --roster \u53EF\u76F4\u63A5\u7528\uFF09" };
  XLSX.utils.book_append_sheet(wb, sheet, "roster");
  return XLSX.write(wb, { bookType: "xlsx", type: "array" });
}
function buildTaskPackage(students, sources, ratios) {
  const specialTag = {};
  for (const s of students) {
    if (!s.manualTag || s.tag === "") continue;
    (specialTag[s.tag] ??= []).push(s.name);
  }
  const punishList = students.filter((s) => s.punish).map((s) => s.name);
  const pkg = {
    kind: "assignment-assistant.roster-task-package",
    version: 1,
    note: "\u5408\u6210\u793A\u4F8B\u5360\u4F4D\u8BF4\u660E\uFF1A\u5206\u7EC4\u6BD4\u4F8B + special_tag \u53C2\u6570\u4F5C\u4E1A\u7EB8\uFF08M5 \u6210\u7EE9\u7BA1\u7406\uFF0Cdocs/05-D18/D19\uFF09",
    group_cfg: ratios.map((g) => ({ group_name: g.tag, group_ratio: g.ratio })),
    special_tag_cfg: specialTag,
    punish: punishList,
    // score_sources[].family 与 engine `--score family:file[:col[:weight]]` 对齐（family 可省=custom）
    // VC-5：include_in_aggregation=false = 教师取消勾选（score excluding），
    // 教师综合得分为 PWA 端按勾选集合计算；引擎 CLI 侧需手动省略对应 --score
    // （作业纸 JSON 的该标记为核对提示）。
    score_sources: sources.map((s) => ({
      family: s.family,
      name: s.name,
      file: s.fileName,
      score_column: s.scoreColumn,
      name_column: s.nameColumn,
      weight: s.weight,
      include_in_aggregation: isIncluded(s),
      excluded: !isIncluded(s) || void 0
    })),
    generated_at: (/* @__PURE__ */ new Date()).toISOString()
  };
  return JSON.stringify(pkg, null, 2);
}
function taskPackageReadme() {
  return `# \u5206\u7EC4\u6BD4\u4F8B + special_tag \u4F5C\u4E1A\u7EB8\uFF08M5 \u6210\u7EE9\u7BA1\u7406 \xB7 \u9644\u5E26\u8BF4\u660E\uFF09

\u672C\u5305\u7531 app\u300C\u73ED\u7EA7\u4E0E\u6807\u7B7E\u300D\u9009\u9879\u5361\u5BFC\u51FA\uFF08\u7EAF\u524D\u7AEF\u8BA1\u7B97\uFF0Cdocs/05-D18/D19\uFF09\uFF0C\u4F9B
engine \`assist sheet make --roster\` / CLI / AI \u9605\u8BFB\u3002\u5168\u90E8\u793A\u4F8B\u5747\u4E3A\u5360\u4F4D
\uFF08\u5B66\u751FA / classA\uFF09\uFF0C\u4E0D\u542B\u771F\u5B9E\u6570\u636E\u3002

## \u6587\u4EF6
- \`roster.xlsx\` \u2014 \u540D\u5355\u8868\uFF08name/number/class/tag\uFF0Ctag \u6052\u4E3A\u82F1\u6587\u503C\uFF0C
  \u4E0E engine files/roster.py \u7684 _HEADER_MAP/_HEADERS \u517C\u5BB9\uFF0C\u53EF\u76F4\u63A5 --roster \u4F7F\u7528\uFF09\u3002
- \`roster.json\` \u2014 \u540C\u4E00\u540D\u5355\u7684 JSON \u7248\uFF08\u4F9B CLI/AI \u4F7F\u7528\uFF09\u3002
- \`task-package.json\` \u2014 \u5206\u7EC4\u6BD4\u4F8B + special_tag + score_sources \u53C2\u6570\uFF08\u672C\u8BF4\u660E\u5BF9\u5E94\u7684\u673A\u5668\u8BFB\u4EF6\uFF09\u3002

## \u6210\u7EE9\u6E90\u683C\u5F0F\u9884\u8BBE\uFF08docs/05-D19\uFF0C\u4E0E engine scores.py ADAPTERS \u540C\u53E3\u5F84\uFF09
- \u56FA\u5B9A\u56DB\u7C7B\uFF08\u65E0\u9700\u9009\u5217\uFF0C\u6309\u5217\u540D/\u8868\u7ED3\u6784 family \u8BED\u4E49\u81EA\u52A8\u5B9A\u4F4D\uFF09\uFF1A
  - exam\uFF08\u6559\u52A1\u671F\u672B\u6210\u7EE9\u8868\uFF1A\u5217"\u671F\u672B(\u5FC5\u586B)"\uFF09
  - xuexitong_assignment\uFF08\u5B66\u4E60\u901A\u4F5C\u4E1A\u7EDF\u8BA1\uFF1A\u524D 8 \u884C"\u6210\u7EE9"\u884C + \u4E0A\u884C\u4F5C\u4E1A\u6807\u9898\uFF09
  - xuexitong_stat\uFF08\u5B66\u4E60\u901A\u7AE0\u8282\u6D4B\u9A8C\uFF1A\u7B2C 4 \u884C"\u6210\u7EE9"\u5217\uFF0C\u975E 0 \u5747\u5206\uFF09
  - rainclass\uFF08\u96E8\u8BFE\u5802\u6C47\u603B\uFF1A\u7B2C 2 \u884C\u6807\u9898\uFF0C\u524D 3 \u5217\u5B66\u53F7/\u59D3\u540D/\u6C47\u603B\uFF0C\u6BCF\u8BFE 2 \u5217\u53D6\u5747\u503C\uFF09
- roster\uFF08\u6559\u52A1\u70B9\u540D\u518C\uFF09\uFF1A\u4EC5\u63A5\u8868\uFF0C\u4E0D\u8BA1\u5206\u3002
- custom\uFF1A\u6559\u5E08\u624B\u52A8\u9009\u5217/\u5217\u540D list + \u6743\u91CD\u3002
- CLI \u5BF9\u5E94\uFF1A\`--score family:file[:col[:weight]]\`\uFF08family \u53EF\u7701=custom\uFF09\u3002

## \u5207\u5206\u89C4\u5219\uFF08\u4E0E _legacy student.py \u5BF9\u9F50\uFF09
1. \u6309\u7EFC\u5408\u5F97\u5206\uFF08\u5404\u6210\u7EE9\u6E90\u6309\u6743\u91CD\u52A0\u6743\u3001\u6E90\u5185\u6309\u6700\u5927\u503C\u5F52\u4E00\u5230 0~100\uFF09\u964D\u5E8F\u6392\u5E8F\uFF1B
2. \u81EA\u4E0A\u800C\u4E0B\u9010\u6BD4\u4F8B\u5207\u5206\u6863\u6B21\uFF1Aint(\u4EBA\u6570\xD7\u6BD4\u4F8B)\uFF0C\u4F59\u6570\u8865\u5230\u6700\u540E\u4E00\u4E2A\u975E translation \u9879\uFF1B
3. translation \u7279\u6B8A\uFF1A\u6309\u6BD4\u4F8B\u968F\u673A\u6563\u5E03\u5230\u5168\u540D\u5355\uFF08legacy \u540C\u6B3E"\u968F\u673A\u6311\u9009"\u8BED\u4E49\uFF09\uFF1B
4. special_tag_cfg / punish\uFF1A\u624B\u52A8\u6307\u5B9A\u5B66\u751F tag \u8986\u76D6\uFF0C\u4E0D\u88AB\u81EA\u52A8\u5207\u5206\u51B2\u6389\uFF1B
5. punish \u4E0D\u53C2\u4E0E\u6BD4\u4F8B\uFF0C\u4EC5\u624B\u52A8\u52FE\u9009\u8986\u76D6\uFF08\u671F\u672B\u8865\u4EA4\u7EDF\u4E00\u9898\u96C6\uFF0Cdocs/05-D17\uFF09\uFF1B
6. score_sources[].include_in_aggregation\uFF1Afalse = \u8BE5\u6E90\u88AB\u6559\u5E08\u53D6\u6D88\u52FE\u9009
   \uFF08score excluding\uFF0Cdocs/14 \xA7VC-5\uFF09\uFF0CPWA \u7AEF\u7EFC\u5408\u5F97\u5206\u4E0D\u542B\u8BE5\u6E90\uFF1B
   \u5F15\u64CE CLI \u6267\u884C\u65F6\u8BF7\u5BF9\u5E94\u7701\u7565\u8BE5\u6E90\u7684 --score \u53C2\u6570\uFF08\u672C\u6807\u8BB0\u4E3A\u4EBA\u5DE5\u6838\u5BF9\u63D0\u793A\uFF09\u3002

## group_cfg \u7ED3\u6784
\`group_cfg: [{ group_name, group_ratio }]\`\uFF08\u6BD4\u4F8B\u4E4B\u548C \u2264 1\uFF09\u3002
`;
}
function str(v) {
  if (v == null) return "";
  return String(v).trim();
}
export {
  FAMILIES,
  ROSTER_COLUMNS,
  ROSTER_COLUMN_LABELS,
  buildRosterPreview,
  buildScoreSourcePreview,
  buildTaskPackage,
  newUid,
  pickBestSheet,
  readRosterXlsx,
  readScoreSourceXlsx,
  taskPackageReadme,
  writeRosterXlsx
};
