# assignment-assistant app（阶段2 PWA 骨架）

大学物理作业纸设计 + AI 批阅工具的静态前端。

- 技术栈：Vue 3 + Vite + TypeScript + Pinia（docs/05-D4）
- 构建：`npm install && npm run build` → `dist/`（base = `/assignment-assistant/app/`，供 GitHub Pages 子路径部署）
- 开发：`npm run dev`
- PWA：`public/manifest.webmanifest` + `public/sw.js`（简单 service worker，离线缓存静态资源）
- 题库 xlsx 读写：SheetJS（`xlsx` npm 包版本）；zip 导入导出：JSZip

页面（顶部选项卡）：设置中心（首次运行向导雏形）、题库编辑器、作业纸设计、导入导出。

决策依据：docs/01 架构、docs/04 数据契约（任务包 schema §1）、docs/05（D1 CLI 超集、
D3 xlsx 为 source of truth、D11 浏览器降级、D13 设置中心/向导/条件式置灰、D14 导出白名单）。

`.npm-cache/` 仅为沙箱内离线 npm 缓存，不入库。
