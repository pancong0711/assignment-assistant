# NOTICE — 第三方库与资产

本仓库以 MIT 协议发布；以下为运行依赖及其协议（以各库官方声明为准），
仅代码依赖声明与说明，不含任何库源码副本。

## 引擎（engine/，Python）

| 库 | 许可证 | 用途 |
|---|---|---|
| click | BSD | CLI 命令组 |
| openpyxl | MIT | kb 题库/点名册 xlsx 读写 |
| reportlab | BSD | 作业纸 PDF 排版/水印页 |
| pypdf | BSD-3 | 水印层与内容页合并（旧项目用同作者 PyPDF2 的现代延续版） |
| loguru | MIT | 日志 |
| pillow | MIT-CMU | 题图/水印图尺寸计算 |
| httpx | BSD | LLM API 请求（批阅，阶段3） |
| playwright | Apache-2.0 | 学习通自动化（阶段4，需自装浏览器内核） |

## 前端（app/，PWA）

以运行时 npm 依赖的 package.json 为准；主要项见下（完整以 npm 查询为准）：

| 库 | 许可证 | 用途 |
|---|---|---|
| Vue 3 | MIT | 前端框架（D4） |
| Pinia | MIT | 状态管理 |
| SheetJS (xlsx, community) | Apache-2.0 | 浏览器端题库 xlsx 读写（05-D3） |
| JSZip | MIT/MPL2 | zip 导入导出 |
| vite | MIT | 构建 |

## 字体（不入库，教师自备）

- 正式环境：教师自备 simsun.ttc / simkai.ttf（Windows 系统字体，版权各自遵守）。
- 开源替代（见 docs/05-D15）：
  - 文泉驿微米黑 `wqy-microhei.ttc` — GPL-2.0 + 字体嵌入例外（多数 Linux 系统自带，不随仓库分发）；
  - 霞鹜文楷 `LXGWWenKai-Regular.ttf` — SIL OFL 1.1，`tools/fonts-download.sh` 从发版页下载（不随仓库分发）。
- 水印 logo 的占位图为合成图形；真实校徽/logo 由教师替换且不入库。

## 数据红线提醒

本仓库约定不含：真实题库、学生数据、批阅记录、任何 apikey/token/登录态
（docs/04 §2）。`_legacy/` 为本机开发参考档案（gitignore，永不推送）。
