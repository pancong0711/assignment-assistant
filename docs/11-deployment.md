# 11 — 线上部署（GitHub Pages · 阶段4b）

> 目标：教师打开 **https://pancong0711.github.io/assignment-assistant/** 即为完整 PWA
> （可安装到主屏、离线缓存），数据全在教师本地；引擎功能（体检真项/批阅/学习通）
> 由教师本机 `assist serve` 提供，网页跨域连接 `127.0.0.1:8601`（D2/D5/D13）。

## 1. 一次性开启（仓库管理员）

GitHub 仓库 → **Settings → Pages → Build and deployment → Source 选 `GitHub Actions`**。
之后每次 push main 自动构建部署（`.github/workflows/pages.yml`）。

## 2. 构建与部署规则

- CI 在 `app/` 内 `npm ci && npm run build`，vite `base = /assignment-assistant/`；
- 产物部署到 Pages 根，线上路径即上表 URL；
- **构建产物不入库**：`app/dist/`、`app/dist-lan/` 均已 gitignore（4b 起消除仓库内 dist）。

## 3. base 覆盖速查（app/ 内执行）

```bash
npm run build                       # Pages 默认（/assignment-assistant/）
npm run build -- --base=./          # 相对路径：任何目录都能直接打开
npm run build -- --base=/ --outDir dist-lan --emptyOutDir false   # 本机 assist serve 同源
```

## 4. 验收清单

1. Pages URL 200 且 PWA 可安装：
   - `manifest.webmanifest`、SW 注册成功；
   - 浏览器地址栏出现"安装"图标（或菜单"安装 app"），添加主屏后离线可开首页；
2. 静态功能与本地一致：题库编辑 xlsx 读写、设计器/预览、任务包 JSON/zip、设置中心-manual 导出；
3. 引擎联动降级正确：体检页 fetch `http://127.0.0.1:8601/doctor` —— 教师本机开着
   `assist serve` 时绿黄红真实；未开时黄色 + serve 引导（CORS 已允许 Pages 来源；
   https 页面访问 127.0.0.1 的 http 属浏览器允许的本地豁免，部署后实测确认）；
4. `tools/check-secrets.sh` 在 CI 内先行退出（workflow 步骤）。

## 5. 已知边界（与局域网演示服务相同，非缺陷）

- Pages 是纯静态端：批阅/学习通/体检真项需教师本机引擎（D2 两态设计）；
- File System Access 在 Pages（https）完整可用；Firefox/Safari 自动降级 file input；
- SW 离线缓存只覆盖静态资源，引擎产物（PDF/报告）始终走"引擎后在本地生成"。
