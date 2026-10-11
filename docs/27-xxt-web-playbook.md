# 27 — 学习通网页操作经验手册（Playbook）

> 来源：旧代码 `_legacy/2601playwright`（`docs/WORK_LOG.md`、`docs/LESSONS.md`、`docs/GRADING_FLOW.md`、
> `src/xuexitong/*`、`src/submit_v2/v3.py`、`src/uploader.py`）+ 本项目 `docs/16`、`docs/24 §15–17`。
> 目的：把「通过 AI 操作学习通网页」积累的经验集中一处，避免重复踩坑。**只读为默认；写操作另见 D75-5。**

---

## 1. 登录 / 会话

- `assist xxt login` 扫码 → Playwright `storage_state` 落盘（cookies + localStorage），后续复用。
- 登录态判活三信号（docs/16 §11.1）：不被重定向回 passport；无密码框；教师工作台文案可识别。
- 陷阱：`state.json` 过期无自动提示 → 所有操作前先 `check_session`（本项目已做）。
- 陷阱：storage 刚写入时旧缓存会误判 dead → 按 storage mtime 失效缓存（D68）。

## 2. 课程 / 班级发现

- 互动页 `visit/interaction` 的隐藏字段：`courseType / superstarClass / single / filterFid / from / tchPageHeader / stuPageHeader / isFirefly`。
- 列表接口：`POST /mooc2-ans/visit/courselistdata`（**只读 POST**，必须白名单，否则会误杀，D73-8）。
- 课程在文件夹里：从 `courseFolderId=0` 做 BFS（实测根目录 + 3 文件夹 = 多门课）。
- 班级在课程 `work/list` 侧栏 `li.classli`（`data` 属性 = classId）。

## 3. 作业 / 批阅列表页（mark）

- **URL**：`/mooc2-ans/work/mark?courseid=&clazzid=&id={workId}&status=0&size=200`（旧版兜底 `reviewTheList`）。
- **DOM**：每生一行 `ul.dataBody_td`
  - `li.taskBody_name div.py_name` = 姓名；
  - `a.cz_py[data]` = 批阅链接，`data` 中带 `workAnswerId`；
  - 行内 `wid15` 区块 = `待批 / 已交 / 未交 + 作答时间`（服务端直出，无 AJAX 竞态）；
  - 状态文本：`待批阅 / 已批阅 / 补交`。
- **分页**：`size=200`、`#totalPage`、`?pages=N`；`max_pages` 控制。
- **未交名单（重点）**：平台可给，当前我们只用「教师名册差集」所以显示「无差集或无名册基准」。
  - 路线 A（旧代码已验证）：`stat2` 统计页
    `https://stat2-ans.chaoxing.com/stat2/work-stastics/index?courseid=&clazzid=&cpi=&ut=t`
    - 作业 tab：每份作业「已交/总人数/未交」+ `workId`；
    - 学生 tab：每生「已交/缺交」+ `personId`，翻页 `.xl-nextPage`；
    - 得到的是「每生缺交次数」，需与名册/作业交叉才能落成「某次作业未交名单」。
  - 路线 B（推荐先探针验证）：mark 页的「未交」选项卡；预计切换 tab 会改 `status=` 或发只读 AJAX。
    探针应点击该 tab，记录 URL/参数与列表 DOM，再按班级+作业解析未交姓名。
  - 结论：**未交名单可以只读提取**；实现前先用 probe 确认走 A 还是 B。

## 4. 单生作答页（review-work）

- **URL**：`/mooc2-ans/work/library/review-work?courseid=&clazzid=&workId=&workAnswerId=`；
  旧版兜底 `/mooc-ans/work/reviewTheContentNew?...`。
- 每生**新开 page**，`wait_until="load"` + sleep，读完 `close()`；顺序执行。
- **作答图片选择器**：`img.ans-ued-img`、`img[class*="ans-ued"]`、`img.ued-img`、
  `img[class*="studentAnswer"] img`、`.studentAnswer img`；
  - 优先 `data-original`（原图），过滤 `photo.chaoxing.com` 头像、`eidt.png/editor`、`popClose`、
    `naturalWidth/Height < 100`；相对路径补 `location.origin`。
- **两栏批语（重点）**：
  - 作业批语：`textarea[name="comment"]`（对应 UEditor `edui1`）；
  - 题目批语：`textarea[id^="answer"]`（每题一个）/ `#ueditor_0` iframe body；
  - 分数：`#tmpscore`（页面加载校验也看它）。
  - 本项目作业纸只有 1 道学习通题 → 「作业批语/题目批语」语义等价，但平台是两个独立栏，
    上传时需**写两次**（旧代码 `upload_report_and_score` 正是这样做的）。
- **图片下载**：`page.context.request.get(url)` 复用上下文 cookie；不要用裸 requests（会 401/跳登录）。
- **懒加载**：图片可能滚动后才出现 → `wait_for_selector` + 逐步滚动，不能只 `sleep(1)`。
- 评语读取：与图片同一页；本项目 `JS_REVIEW_DETAIL` 已读 `comment/per_question_comments/score`。

## 5. 公告页 / UEditor 上传（写会话经验，当前冻结）

- 通知列表页自身数据走 **POST AJAX**；「非 GET 全 abort」会误杀 → 只读白名单要按内容页放行（docs/16 §24.1）。
- 公告编辑器：UEditor；旧代码 `edui1`=作业批语、`ueditor_0`/`edui92`=题目批语。
- 上传图片：点 UEditor `insertimage` 按钮 → 对话框 webuploader → **POST 到上传 CDN**（写会话专用白名单）；
  插入后要同步 `textarea` 与 `#ueditor_0` iframe body，防止 `markAction` 覆盖。
- 覆盖已存在批语：清空 `textarea[name=comment]` + `#ueditor_0` body，再插入新内容（原图/文字），最后提交。

## 6. Playwright 踩坑清单

- iframe 嵌套多：操作前先列 frames；`switch_frame` 改 page 变量要传回外层。
- strict mode：多个「批阅」按钮会报 strict violation → 用逐行定位 + `.first` 或索引。
- 动态加载：`get_by_text` 可能超时 → `sleep` + `wait_for_selector` 兜底。
- Windows 中文输出到 Node 会乱码 → 跨进程信号用 ASCII。
- `page.context.request.get` 才能带登录态下载图片。
- 存储/网络：BaiduSync 同步目录会导致引擎更新复制不完整（D73-12）→ 更新前暂停同步。

## 7. 只读探针方法论（新增功能都用它）

1. 打开目标页，route 只放行 GET/HEAD/OPTIONS；
2. 所有非 GET 请求**记录 `(method,url)` 但不继续**；
3. 同时记录关键选择器命中（图片数、批语字段长度、分数）；
4. 依据 probe JSON 把**明确的只读 AJAX**加入 `--allow-post` 白名单；
5. 再跑下载/提取；白名单按操作最小化，永不「全放行」。

## 8. 经验来源索引

| 经验 | 位置 |
|---|---|
| 浏览器探索路径/踩坑 | `_legacy/2601playwright/docs/WORK_LOG.md` |
| 开发教训（先研究再写码等） | `_legacy/2601playwright/docs/LESSONS.md` |
| 批阅全流程 | `_legacy/2601playwright/docs/GRADING_FLOW.md` |
| mark/学生列表/图片下载 | `_legacy/2601playwright/src/xuexitong/homeworks.py` |
| review-work 上传/两栏批语 | `_legacy/2601playwright/src/uploader.py`、`src/submit_v2/v3.py` |
| 未交扫描（stat2） | `_legacy/2601playwright/src/submit_v3.py::scan_unsubmitted` |
| 本项目只读边界/通知页教训 | `docs/16` §23–24；`docs/24` §15–17 |
