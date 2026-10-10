"""D63 T4：学习通只读提取 v2（方案 C：逐班直达导航 + evaluate 直读，零可见性断言）。

语义来源：docs/16 §12（探针复盘 ABC 对照定案）、§15（作答状态字段）、§19（schema）。
只读硬保证：整链仅 goto(GET) 与 DOM 读取；route 层拦截一切非 GET（写操作防御纵深）；
导航形态（定案）：work/list?courseid&clazzid&selectClassid&status=-1&v=0&topicid=0
（15.1：wid15 区块给出 待批/已交/未交+作答时间，服务端直出，无 AJAX 竞态）；
失败留痕：kind 只有 not_extracted / empty_confirmed 两种（19.4，禁止第三类"0"）。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

BASE = "https://mooc2-ans.chaoxing.com"
NOTICE_BASE = "https://notice.chaoxing.com"

WORK_URL = (BASE + "/mooc2-ans/work/list?courseid={course}&clazzid={clazz}"
            "&cpi={cpi}&selectClassid={clazz}&status=-1&v=0&topicid=0")
MARK_URL = (BASE + "/mooc2-ans/work/mark?courseid={course}&clazzid={clazz}&id={work}"
            "&status=0&size=200"  # size=200：round-1/probe3 双实证，mark 页 20/页默认会截断
            "&prePageNum=1&prePageSize=200&topicid=0&perspectiveType=0")
NOTICE_URL = (NOTICE_BASE + "/pc/course/notice/myNoticeList?courseid={course}&clazzid={clazz}")

JS_READ = """() => {
  const works=[];
  document.querySelectorAll('[onclick*="viewWork"]').forEach(el=>{
    const m=(el.getAttribute('onclick')||'').match(/viewWork\\('([0-9a-f]+)',\\s*'?(\\d+)'?,\\s*'?(\\d+)'?\\)/);
    if(!m) return;
    const li=el.closest('li');
    const liHtml=li?li.innerHTML:'';
    const cnt=(liHtml.match(/<em[^>]*>(\\d+)<\\/em>\\s*待批/)||[,''])[1];
    const ms=liHtml.match(/([\\d]+)\\s*已交/);
    const mu=liHtml.match(/([\\d]+)\\s*未交/);
    const mt=liHtml.match(/作答时间：([^<]+)</);
    const mark=li.querySelector('a.piyueBtn');
    works.push({name: el.textContent.trim(), workId: m[2],
                pending: cnt===''?null:parseInt(cnt),
                submitted: ms?parseInt(ms[1]):null,
                unsubmitted: mu?parseInt(mu[1]):null,
                answer_window: mt?mt[1].trim():'',
                mark_href: mark?mark.getAttribute('href'):''});
  });
  return {works,
    activeClass:(document.querySelector('li.active.classli')?.getAttribute('title')||'').trim(),
    classNodes: document.querySelectorAll('li.classli').length,
    nullPage: ((document.querySelector('.nullPage')||{}).textContent||'').trim(),
    cpi: (document.querySelector('#cpi')||{}).value||''};
}"""

JS_REVIEW = """() => {
  const out=[]; document.querySelectorAll('ul.dataBody_td').forEach(ul=>{
    const ne=ul.querySelector('li.taskBody_name div.py_name'); const pb=ul.querySelector('a.cz_py');
    if(!ne||!pb) return; let st='';
    ul.querySelectorAll('li').forEach(li=>{const t=li.textContent.trim();
      if(t.includes('待批阅')||t.includes('已批阅')||t.includes('补交')) st=t;});
    out.push({name: ne.textContent.trim(), status: st,
              // D64-c R1/R2：data 属性自带学生批阅页 URL（workAnswerId 在内）→ 报告管线直连通道
              review_path: (pb.getAttribute('data')||'').slice(0,240)});
  }); return out;
}"""

JS_NOTICES = """() => {
  const out=[];
  document.querySelectorAll('.noticeli_link, .notice-item, li.notice').forEach(el=>{
    const text=(el.textContent||'').trim().replace(/\\s+/g,' ');
    if(text) out.push({text: text.slice(0,300), href: el.getAttribute('href')||''});
  });
  if(!out.length){
    const body=document.body?document.body.innerText:'';
    if(body.includes('暂无通知')) out.push({text:'暂无通知',href:''});
  }
  return out;
}"""


READONLY_POST_PATHS = ("/mooc2-ans/visit/courselistdata",)
COURSELIST_URL = BASE + "/visit/courselistdata"


def readonly_route_decision(method: str, url: str) -> str:
    """D73：只读 POST 列表接口放行，其余写操作继续 abort。"""
    m = (method or "").upper()
    if m in ("GET", "HEAD", "OPTIONS"):
        return "continue"
    if m == "POST" and any(p in (url or "") for p in READONLY_POST_PATHS):
        return "continue"
    return "abort"


JS_DISCOVER_INFO = r"""() => {
  const val=id=>{const e=document.getElementById(id); return e?e.value:'';};
  const courses=[]; const cseen=new Set();
  const pushCourse=(id,name)=>{
    id=String(id||''); if(!id||cseen.has(id)) return;
    const text=String(name||'').trim().replace(/\s+/g,' ')
      .replace(/\s+(已结课|进行中|未开始)$/,'').trim();
    if(!text) return;
    cseen.add(id); courses.push({name:text.slice(0,80), courseId:id});
  };
  document.querySelectorAll('.course, [id^="c_"]').forEach(box=>{
    let id='';
    const inp=box.querySelector('input.courseId, input[name="courseId"]');
    if(inp) id=inp.value||'';
    if(!id){
      const a=box.querySelector('a[href*="courseId="]');
      if(a){ const m=(a.getAttribute('href')||'').match(/courseId=(\d+)/i); if(m) id=m[1]; }
    }
    const el=box.querySelector('.course-name, h3 .course-name, h3');
    pushCourse(id, el?el.textContent:box.textContent);
  });
  document.querySelectorAll('a[href*="courseId="]').forEach(a=>{
    const m=(a.getAttribute('href')||'').match(/courseId=(\d+)/i); if(!m) return;
    const box=a.closest('.course, li, [id^="c_"]');
    const el=box?box.querySelector('.course-name, h3 .course-name, h3'):null;
    pushCourse(m[1], el?el.textContent:(a.getAttribute('title')||a.textContent));
  });
  const folders=[]; const fseen=new Set();
  document.querySelectorAll('#fileList li[fileid], [onclick*="intoFolder"], [onclick*="getFileCourseList"]').forEach(el=>{
    let id=el.getAttribute('fileid')||'';
    if(!id){
      const oc=el.getAttribute('onclick')||'';
      const m=oc.match(/(?:intoFolder|getFileCourseList)\([^,]*?,?\s*['"]?(\d+)['"]?/);
      if(m) id=m[1];
    }
    if(!id||fseen.has(id)) return; fseen.add(id);
    const h=el.querySelector('h3.file-name');
    const name=(h?h.textContent:el.textContent||'').trim().replace(/\s+/g,' ').slice(0,80);
    folders.push({folderId:id, name});
  });
  return {
    defaults: {
      courseType: val('courseType') || '0',
      superstarClass: val('superstarClass') || '0',
      single: val('single') || '0',
      filterFid: val('filterFid') || '',
      from: val('from') || '',
      tchPageHeader: val('tchPageHeader') || '-1',
      stuPageHeader: val('stuPageHeader') || '-1',
      isFirefly: val('isFirefly') || '0'
    },
    courses, folders
  };
}"""


JS_PARSE_COURSELIST_HTML = r"""(html) => {
  const d=document.createElement('div'); d.innerHTML=html||'';
  const courses=[]; const cseen=new Set();
  const pushCourse=(id,name)=>{
    id=String(id||''); if(!id||cseen.has(id)) return;
    const text=String(name||'').trim().replace(/\s+/g,' ')
      .replace(/\s+(已结课|进行中|未开始)$/,'').trim();
    if(!text) return;
    cseen.add(id); courses.push({name:text.slice(0,80), courseId:id});
  };
  d.querySelectorAll('.course, [id^="c_"]').forEach(box=>{
    let id='';
    const inp=box.querySelector('input.courseId, input[name="courseId"]');
    if(inp) id=inp.value||'';
    if(!id){
      const a=box.querySelector('a[href*="courseId="]');
      if(a){ const m=(a.getAttribute('href')||'').match(/courseId=(\d+)/i); if(m) id=m[1]; }
    }
    const el=box.querySelector('.course-name, h3 .course-name, h3');
    pushCourse(id, el?el.textContent:box.textContent);
  });
  d.querySelectorAll('a[href*="courseId="]').forEach(a=>{
    const m=(a.getAttribute('href')||'').match(/courseId=(\d+)/i); if(!m) return;
    const box=a.closest('.course, li, [id^="c_"]');
    const el=box?box.querySelector('.course-name, h3 .course-name, h3'):null;
    pushCourse(m[1], el?el.textContent:(a.getAttribute('title')||a.textContent));
  });
  const folders=[]; const fseen=new Set();
  d.querySelectorAll('li[fileid], [onclick*="intoFolder"], [onclick*="getFileCourseList"]').forEach(el=>{
    let id=el.getAttribute('fileid')||'';
    if(!id){
      const oc=el.getAttribute('onclick')||'';
      const m=oc.match(/(?:intoFolder|getFileCourseList)\([^,]*?,?\s*['"]?(\d+)['"]?/);
      if(m) id=m[1];
    }
    if(!id||fseen.has(id)) return; fseen.add(id);
    const h=el.querySelector('h3.file-name');
    const name=(h?h.textContent:el.textContent||'').trim().replace(/\s+/g,' ').slice(0,80);
    folders.push({folderId:id, name});
  });
  return {courses, folders};
}"""

JS_CLASSES = r"""() => {
  const out=[];
  document.querySelectorAll('li.classli').forEach(li=>{
    const div=li.querySelector('div');
    const name=div?div.textContent.trim():li.textContent.trim();
    const id=li.getAttribute('data')||'';
    if(name&&id&&id!=='0') out.push({name, classId:id});
  });
  return out;
}"""


def parse_count_token(li_html: str, label: str) -> "int | None":
    """纯函数（可测）：从 li HTML 片段中解析 'N 已交/未交/待批' 计数。"""
    text = re.sub(r"<[^>]+>", " ", li_html)
    m = re.search(rf"(\d+)\s*{re.escape(label)}", text)
    return int(m.group(1)) if m else None


class ReadOnlyExtractor:
    """单 page 会话内的逐班只读提取器（route 层拦截写请求=反记忆化防线）。"""

    def __init__(self, ctx, page, archive_dir: "Path | None" = None):
        self.ctx, self.page, self.archive_dir = ctx, page, archive_dir
        self.steps: list[dict] = []   # D63 批次三：导航过程事件（20.3 方案 A 数据源）
        self.run_id = ''
        self._install_readonly_route()

    def _step(self, action: str, detail: str = "", title: str = "") -> None:
        """每次 goto 后记一步（URL/标题/动作/时间戳）+ 低频截图文件（截图缩略交前端）。"""
        try:
            shot = ''
            if self.archive_dir and self.run_id:
                d = Path(self.archive_dir) / 'shots'
                d.mkdir(parents=True, exist_ok=True)
                name = f"{self.run_id}-step{len(self.steps)+1:02d}"
                self.page.screenshot(path=str(d / f"{name}.png"), full_page=False)
                shot = f"shots/{name}.png"
        except Exception:
            shot = ''
        self.steps.append({"action": action, "detail": detail[:120],
                           "title": title[:60], "url": (self.page.url or "")[:200],
                           "ts": time.strftime('%H:%M:%S'), "shot": shot})

    def _install_readonly_route(self):
        def route_handler(route, request):
            if readonly_route_decision(request.method, request.url) == "continue":
                return route.continue_()
            return route.abort()
        self.ctx.route("**/*", route_handler)

    def archive(self, name: str):
        if self.archive_dir:
            try:
                (Path(self.archive_dir) / f"{name}.html").write_text(
                    self.page.content(), encoding="utf-8")
            except Exception:
                pass

    def _archive_text(self, name: str, text: str) -> None:
        """保存接口返回 HTML 片段（用于发现诊断）。"""
        if not self.archive_dir:
            return
        try:
            (Path(self.archive_dir) / f"{name}.html").write_text(text, encoding="utf-8")
        except Exception:
            pass

    def _switch_course_type(self, course_type: str) -> None:
        """D73：切换“我教的课/我学的课”，仅点击 tab，不写改删。"""
        sel = "#myTeach" if course_type == "0" else "#myLearn"
        try:
            loc = self.page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=3000)
                self.page.wait_for_timeout(2000)
        except Exception:
            pass

    def _request_courselist(self, course_type: str, folder_id: str, defaults: dict) -> str:
        """D73：只读 POST 课程列表接口；不依赖页面 route 拦截。"""
        page_header = defaults.get("stuPageHeader") if course_type == "1" else defaults.get("tchPageHeader")
        form = {
            "courseType": course_type,
            "courseFolderId": str(folder_id),
            "query": "",
            "pageHeader": page_header or "-1",
            "single": defaults.get("single") or "0",
            "superstarClass": defaults.get("superstarClass") or "0",
            "isFirefly": defaults.get("isFirefly") or "0",
            "fid": defaults.get("filterFid") or "",
            "from": defaults.get("from") or "",
        }
        resp = self.ctx.request.post(COURSELIST_URL, form=form, timeout=30000)
        text = resp.text()
        self._archive_text(f"discover-courselist-{course_type}-{folder_id}", text)
        return text

    def discover_courses(self) -> list:
        """D73：根目录 + 课程文件夹 BFS 发现全部课程（只读列表 POST）。

        旧实现只扫一次 a[href*="courseId="]，根目录为空时即失败；
        新实现兼容 courseFolderId 递归，并放行只读列表 POST。
        """
        self.page.goto(f"{BASE}/visit/interaction",
                       wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(5000)
        self.archive("discover-courses")
        initial = self.page.evaluate(JS_DISCOVER_INFO)
        defaults = initial.get("defaults") or {}
        results: dict[str, dict] = {}

        for course_type in ("0", "1"):
            self._switch_course_type(course_type)
            state = self.page.evaluate(JS_DISCOVER_INFO)
            queue: list[str] = ["0"]
            for f in state.get("folders") or []:
                fid = str(f.get("folderId") or "")
                if fid and fid not in queue:
                    queue.append(fid)
            # 根目录 DOM 里已有的课程也先计入（可能是不需要 AJAX 的账号）
            for c in state.get("courses") or []:
                results.setdefault(str(c.get("courseId")), {"name": c.get("name") or "", "courseId": str(c.get("courseId"))})

            seen_folders: set[str] = set()
            while queue:
                fid = queue.pop(0)
                if fid in seen_folders:
                    continue
                seen_folders.add(fid)
                try:
                    html = self._request_courselist(course_type, fid, defaults)
                    parsed = self.page.evaluate(JS_PARSE_COURSELIST_HTML, html)
                except Exception as e:  # noqa: BLE001
                    self._step("发现课程列表失败", f"courseType={course_type} folder={fid}", str(e)[:80])
                    continue
                for c in parsed.get("courses") or []:
                    cid = str(c.get("courseId") or "")
                    if cid:
                        results.setdefault(cid, {"name": c.get("name") or "", "courseId": cid})
                new_folders = 0
                for f in parsed.get("folders") or []:
                    nfid = str(f.get("folderId") or "")
                    if nfid and nfid not in seen_folders:
                        queue.append(nfid); new_folders += 1
                self._step("发现课程列表",
                           f"courseType={course_type} folder={fid} "
                           f"courses={len(parsed.get('courses') or [])} folders={new_folders}",
                           self.page.title())
        if not results:
            # 最后兜底：当前 DOM anchors（兼容极简页面）
            for c in (self.page.evaluate(JS_DISCOVER_INFO).get("courses") or []):
                cid = str(c.get("courseId") or "")
                if cid:
                    results[cid] = {"name": c.get("name") or "", "courseId": cid}
        return list(results.values())

    def discover_classes(self, course_id: str) -> list:
        """D72：从课程 work/list 扫描班级（借鉴 .scratch/xxt_readonly_extract.py）。"""
        info = self.goto_work_list(course_id)
        self.archive(f"discover-classes-{course_id}")
        self._step("发现班级列表", f"courseid={course_id}",
                   info.get("activeClass") or self.page.title())
        return self.page.evaluate(JS_CLASSES)

    def goto_work_list(self, course_id: str) -> dict:
        self.page.goto(f"{BASE}/mooc2-ans/work/list?courseid={course_id}",
                       wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(4000)
        info = self.page.evaluate(JS_READ)
        self._step("goto课程工作台", f"courseid={course_id}", self.page.title())
        return info

    def extract_class(self, course_id: str, class_id: str, cpi: str = "0",
                      want_names: bool = True, settle_ms: int = 3500) -> dict:
        """单班提取（10-8 定案形态：直达 classid URL）。返回 19.2 ClassRecord 分量。"""
        rec: dict = {"classId": class_id, "status": "extracted", "notes": []}
        url = WORK_URL.format(course=course_id, clazz=class_id, cpi=cpi)
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(settle_ms)
        self.archive(f"v2-list-{class_id}")
        info = self.page.evaluate(JS_READ)
        self._step("课程班级列表读取", f"class={class_id}", self.page.title())
        rec["cpi"] = info.get("cpi") or cpi
        rec["activeClass"] = info.get("activeClass", "")
        works = info.get("works", [])
        if not works:
            if "暂无作业" in info.get("nullPage", ""):
                rec["status"] = "empty_confirmed"
                rec["works"] = []
            else:
                rec["status"] = "not_extracted"
                rec["works"] = []
            return rec
        rec["works"] = []
        for w in works:
            href = w.get("mark_href") or MARK_URL.format(course=course_id,
                                                          clazz=class_id, work=w["workId"])
            # mark_href 覆写分页参数（否则页面模板自带 size=12 → 仅 20 行，probe2/v2 首跑实锤）
            href = re.sub(r"(size|prePageSize)=\d+", r"\1=200", href)
            href = re.sub(r"prePageNum=\d+", "prePageNum=1", href)
            if "size=" not in href:          # 列表模板 href 无 size 参数 → 服务端每页 20 截断；
                href += "&size=200"          # 显式 size=200（round-1/probe3/单跳实测 59 全行）
            if not href.startswith("http"):
                href = BASE + (href if href.startswith("/") else "/" + href)
            self.page.goto(href, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(4000)
            self.archive(f"v2-review-{class_id}-{w['workId']}")
            rows = self.page.evaluate(JS_REVIEW)
            self._step("作业批阅页读取", f"{w['name'][:30]}", self.page.title())
            rec["works"].append({**w, "source": "list_wid15",
                                 "submitted_names": rows})
        return rec

    def extract_notices(self, course_id: str, class_id: str, settle_ms: int = 4000) -> list:
        self.page.goto(NOTICE_URL.format(course=course_id, clazz=class_id),
                       wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(settle_ms)
        self.archive(f"v2-notice-{class_id}")
        self._step("班级通知读取", f"class={class_id}", self.page.title())
        return self.page.evaluate(JS_NOTICES)


# ---------- 纯函数（可测）：差集与锚点 ----------

def submitted_name_set(work: dict) -> set[str]:
    return {r.get("name", "").strip() for r in work.get("submitted_names", []) if r.get("name")}


def unsubmitted_diff(roster: list[dict], work: dict) -> dict:
    """未交名单 = master 花名册 − 本作业提交者（学号优先不可得 → 姓名回退，19.3 定案）。"""
    roster_names = [r.get("name", "").strip() for r in roster if r.get("name")]
    sub = submitted_name_set(work)
    return {
        "unsubmitted_names": sorted(set(roster_names) - sub),
        "sub_not_in_roster": sorted(sub - set(roster_names)),
        "roster_total": len(roster),
        "submitted_count": work.get("submitted"),
        "unsubmitted_count": work.get("unsubmitted"),
    }


def anchor_check(work: dict, roster_total: "int | None") -> dict:
    """一致性：名单数==已交数；|名册 −(已交+未交)|≤2 绿，超出进 notes（灰注，含发布人口径）。"""
    n = len(submitted_name_set(work))
    res = {"names_vs_submitted": (work.get("submitted") == n), "ok": True, "notes": []}
    if roster_total is not None and work.get("unsubmitted") is not None:
        delta = roster_total - (work.get("submitted", 0) + work.get("unsubmitted", 0))
        res["roster_delta"] = delta
        if abs(delta) > 2:
            res["notes"].append(f"roster_delta={delta}（含发布人/未入班口径，灰注非故障）")
    if not res["names_vs_submitted"]:
        res["ok"] = False
        res["notes"].append(f"名单数({n})≠已交数({work.get('submitted')})，待差值核查")
    return res
