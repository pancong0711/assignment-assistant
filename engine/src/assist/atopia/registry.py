"""registry.py — D132-T15a：**工具白名单 + 分级**。

安全模型（docs/81 §2，硬编码不随配置放宽）：
- 只登记的工具可执行；**未登记 = L3 = 拒绝**（白名单，不是黑名单）；
- L3 无法通过任何配置/扩展开通；
- `extensions/` 只能把级别**调高**（更严），不能调低。

为什么分级写死在注册表而不是"按命令名猜"：
命令名可以被拼出无限变体（`kb write` / `kb.write` / `kb  write`），
按名猜测必然有漏；只有**显式登记**才能保证"没登记就不放行"。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

L0, L1, L2, L3 = "L0", "L1", "L2", "L3"
LEVEL_ORDER = {L0: 0, L1: 1, L2: 2, L3: 3}
LEVEL_LABEL = {
    L0: "只读（直接执行）",
    L1: "预览（直接执行，会花模型成本）",
    L2: "写入（必须教师二次确认）",
    L3: "危险（不开放）",
}


class ToolDenied(RuntimeError):
    """工具被拒绝执行（分级/参数/护栏）。"""


@dataclass(frozen=True)
class Tool:
    """一个可被 AI 调用的工具。

    `argv_template`：命令模板（列表），`{param}` 占位；执行时按参数替换。
    `allowed_args`：允许的参数名 → 校验函数名（"str" / "int" / "path_in_ws"）。
    """
    name: str            # 唯一 id，如 "kb.stats"
    argv: tuple[str, ...]
    level: str
    summary: str
    allowed_args: dict[str, str] = field(default_factory=dict)
    dangerous_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"name": self.name, "level": self.level,
                "levelLabel": LEVEL_LABEL.get(self.level, self.level),
                "summary": self.summary, "argv": list(self.argv),
                "allowedArgs": dict(self.allowed_args)}


def _t(name, argv, level, summary, allowed_args=None, dangerous=()) -> Tool:
    return Tool(name=name, argv=tuple(argv), level=level, summary=summary,
                allowed_args=dict(allowed_args or {}), dangerous_flags=tuple(dangerous))


# ---------------- 内置白名单 ----------------
# 只登记**确定安全**的命令；宁缺勿滥（未登记即拒绝）。
BUILTIN_TOOLS: tuple[Tool, ...] = (
    # ---- L0 只读 ----
    _t("kb.stats", ("kb", "stats"), L0, "题库统计（各 kind/章节题数）"),
    _t("kb.catalog", ("kb", "catalog"), L0, "题库目录（kind/章节/题号）"),
    _t("kb.export", ("kb", "export"), L0, "导出题库 JSON 到 kb/export"),
    _t("rules.show", ("rules", "show"), L0, "查看当前评阅规则"),
    _t("rules.summary", ("rules", "summary"), L0, "查看规则摘要（进提示词的那份）",
       {"kind": "str"}),
    _t("materials.list", ("materials", "list"), L0, "列出课堂资料章节"),
    _t("materials.show", ("materials", "show"), L0, "查看某章抽取索引",
       {"chap": "str"}),
    _t("materials.knowledge", ("materials", "knowledge"), L0, "查看某章生效知识点清单",
       {"chap": "str"}),
    _t("materials.files", ("materials", "files"), L0,
       "列出某章 _source/ 原件（文件名/大小/sha；含回收站可选）",
       {"chap": "str"}),
    _t("kb.vocab.list", ("kb", "vocab", "list"), L0, "查看受控知识点词表"),
    _t("prompt.list", ("prompt", "list"), L0, "列出提示词模板"),
    # ---- D148：通用只读文件能力（教师诉求"AI 应先找到文档再打开查看"） ----
    _t("fs.ls", ("fs", "ls"), L0,
       "列出 workspace 内目录（只读；secrets/.runtime/.git 已屏蔽）",
       {"path": "path_in_ws"}),
    _t("fs.read", ("fs", "read"), L0,
       "读 workspace 内文本文件（只读；二进制拒读；默认前 200 行）",
       {"path": "path_in_ws"}),
    _t("fs.search", ("fs", "search", "{query}"), L0,
       "按关键词搜索 workspace 内文件内容（只读；返回 文件:行:摘要）",
       {"query": "str", "glob": "str"}),
    # ---- L1 预览（只读但花 LLM 成本） ----
    _t("kb.tag-knowledge.dry", ("kb", "tag-knowledge", "--dry-run"), L1,
       "预览 AI 知识点标注（不写库）", {"kb": "str", "ids": "str"}),
    _t("kb.check-knowledge", ("kb", "check-knowledge"), L1,
       "AI 提议知识点术语等价组（只提议，不执行）"),
    _t("materials.suggest", ("materials", "suggest"), L1,
       "AI 抽取本章知识点建议（写 .ai.json，不生效）", {"chap": "str"}),
    _t("rules.generate.dry", ("rules", "generate"), L1,
       "预览 AI 生成评阅要点（不写答案库）", {"kind": "str", "chap": "str"}),
    # ---- L2 写入（必须教师确认） ----
    _t("kb.vocab.add", ("kb", "vocab", "add"), L2, "新增/更新受控词表术语",
       {"term": "str", "alias": "str"}),
    _t("kb.vocab.set-topic", ("kb", "vocab", "set-topic"), L2,
       "D138：给知识点设置章内主题（两层分类：章 → 主题 → 术语）",
       {"term": "str", "topic": "str"}),
    _t("kb.write", ("kb", "write"), L2, "写回题库（需先导出 JSON）",
       {"input": "path_in_ws", "kind": "str"}),
    _t("kb.tag-knowledge.apply", ("kb", "tag-knowledge", "--force"), L2,
       "AI 知识点标注并**写回题库**（覆盖已有标注！）",
       {"kb": "str", "ids": "str"}),
    _t("kb.check-knowledge.apply", ("kb", "check-knowledge", "--apply"), L2,
       "执行知识点术语归一（改写题库 related）", {"mapping": "path_in_ws"}),
    _t("materials.confirm", ("materials", "confirm"), L2,
       "把 AI 知识点建议固化为生效清单", {"chap": "str"}),
    _t("materials.remove", ("materials", "remove"), L2,
       "把 _source/ 里的原件**移入回收站**（不真删，可人工找回）",
       {"chap": "str", "file": "str"}),
    _t("materials.restore", ("materials", "restore"), L2,
       "把回收站里的原件**移回** _source/（同名自动改名，不覆盖）",
       {"chap": "str", "file": "str"}),
    _t("rules.set", ("rules", "set"), L2, "修改评阅规则数值", {"path": "str",
                                                              "value": "str"}),
    _t("rules.reset", ("rules", "reset"), L2, "恢复默认评阅规则"),
    _t("prompt.save", ("prompt", "save"), L2, "保存提示词模板",
       {"id": "str", "text": "str"}),
    # ---- L3 危险：登记只为**明确拒绝**与展示，永不执行 ----
    _t("engine.update", ("engine", "update"), L3, "更新引擎（覆盖程序文件）"),
    _t("engine.update.apply", ("engine", "update", "--yes"), L3, "更新引擎并确认"),
    _t("migrate.apply", ("migrate-grading-dir", "--apply"), L3,
       "迁移批阅目录（移动既有产物）"),
    _t("workspace.clean.apply", ("workspace", "clean-migrated", "--apply"), L3,
       "清理已迁移目录（删除文件）"),
    _t("grade.upload", ("grade", "--upload"), L3, "上传批阅结果到学习通"),
)

_BY_NAME: dict[str, Tool] = {t.name: t for t in BUILTIN_TOOLS}


def builtin_tools() -> tuple[Tool, ...]:
    return BUILTIN_TOOLS


def get_tool(name: str) -> Tool:
    """取工具；**未登记 → 直接拒绝**（白名单语义）。"""
    t = _BY_NAME.get(str(name or "").strip())
    if t is None:
        raise ToolDenied(f"工具未登记：{name!r}（未登记的命令一律拒绝，见 docs/81 §2）")
    return t


def is_denied(tool: Tool) -> bool:
    return tool.level == L3


# ---------------- 参数校验 ----------------
_SAFE_STR = re.compile("^[^\x00-\x1f]{0,2000}$")
_INT_RE = re.compile(r"^-?\d{1,9}$")


def validate_args(tool: Tool, ws, args: "dict | None") -> dict:
    """参数白名单校验：只允许登记过的参数名；类型/范围受限。

    重点防的是"模型自由发挥"：
    - 未登记的参数名 → 拒绝（否则可注入 `--workspace /etc` 之类）；
    - `path_in_ws` → 必须落在 workspace 内（防读取/写入任意文件）。
    """
    args = dict(args or {})
    if is_denied(tool):
        raise ToolDenied(f"L3 工具不开放：{tool.name}")
    allowed = tool.allowed_args
    bad = [k for k in args if k not in allowed]
    if bad:
        raise ToolDenied(f"{tool.name} 不接受参数：{', '.join(bad)}"
                         f"（允许：{', '.join(allowed) or '无'}）")
    out: dict = {}
    ws_p = Path(ws).resolve() if ws is not None else None
    for k, v in args.items():
        kind = allowed[k]
        if kind == "int":
            if not _INT_RE.match(str(v)):
                raise ToolDenied(f"{tool.name}.{k} 必须是整数，收到 {v!r}")
            out[k] = str(int(v))
        elif kind == "path_in_ws":
            if ws_p is None:
                raise ToolDenied(f"{tool.name}.{k} 需要 workspace 校验")
            p = (ws_p / str(v)).resolve() if not Path(str(v)).is_absolute() \
                else Path(str(v)).resolve()
            try:
                p.relative_to(ws_p)
            except Exception:  # noqa: BLE001
                raise ToolDenied(
                    f"{tool.name}.{k} 必须位于 workspace 内（收到 {v!r}）") from None
            out[k] = str(p)
        else:  # "str"
            s = str(v)
            if not _SAFE_STR.match(s):
                raise ToolDenied(f"{tool.name}.{k} 含非法字符或过长")
            if "--" in s:
                # 防止通过参数值注入新的命令行开关
                raise ToolDenied(f"{tool.name}.{k} 不得包含 `--`（防开关注入）")
            out[k] = s
    return out


def build_argv(tool: Tool, args: "dict | None") -> list[str]:
    """模板 + 校验后的参数 → argv（**列表传参，不经过 shell**）。"""
    a = dict(args or {})
    argv: list[str] = []
    used: set[str] = set()
    for tok in tool.argv:
        # D148 修复：原正则写成双反斜杠，实际匹配的是字面 `\{`，导致
        # **所有用 `{name}` 占位符传参的工具**（fs.search / kb.write …）都失效。
        m = re.fullmatch(r"\{(\w+)\}", tok)
        if m and m.group(1) in a:
            argv.append(str(a[m.group(1)]))
            used.add(m.group(1))
            continue
        argv.append(tok)
    # 形如 {"--chap": "chap"} 的参数：登记名 → CLI 开关
    for k, v in a.items():
        if k in used:
            continue
        flag = _ARG_FLAG.get(k)
        if not flag:
            raise ToolDenied(f"{tool.name} 不知道如何传递参数 {k}")
        argv += [flag, str(v)]
    return argv


# 参数名 → 实际 CLI 开关（只覆盖已登记的参数）
_ARG_FLAG = {
    "kind": "--kind",
    "chap": "--chap",
    "ids": "--ids",
    "kb": "--kb",
    "term": "--term",
    "alias": "--alias",
    "input": "--input",
    "mapping": "--mapping",
    "path": "--path",
    "value": "--value",
    "id": "--id",
    "text": "--text",
    "file": "--file",
    "topic": "--topic",
    "glob": "--glob",
}


def level_at_least(level: str, minimum: str) -> bool:
    return LEVEL_ORDER.get(level, 99) >= LEVEL_ORDER.get(minimum, 0)


# ---------------- 扩展覆盖（T18，只能更严） ----------------
EXT_DIR = "extensions"


def extensions_dir(ws) -> Path:
    """D134：扩展落在 `<ws>/atopia/extensions/`（见 paths.py）。

    为什么扩展跟 Atopia 走：它**只对 Atopia 有意义**（消费方唯一），
    且是可整体丢弃的**覆盖层**——删除 `atopia/` 后必须回内置级别。
    """
    from . import paths as P
    return P.extensions_dir(ws)


def load_overrides(ws) -> dict:
    """读 `<ws>/extensions/tools/*.json` → {tool_name: level}。

    文件格式：`{"name": "kb.stats", "level": "L2"}`（或 `{"overrides": {...}}`）。
    **只接受"调高"**：低于内置级别的覆盖被忽略并记 warning（安全关键）。
    """
    root = extensions_dir(ws) / "tools"
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    builtin = {t.name: t.level for t in BUILTIN_TOOLS}
    for f in sorted(root.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[atopia] 扩展工具文件损坏，忽略 {f.name}: {exc}")
            continue
        pairs: list[tuple[str, str]] = []
        if isinstance(data, dict) and isinstance(data.get("overrides"), dict):
            pairs = [(str(k), str(v)) for k, v in data["overrides"].items()]
        elif isinstance(data, dict) and data.get("name"):
            pairs = [(str(data["name"]), str(data.get("level") or ""))]
        for name, lvl in pairs:
            base = builtin.get(name)
            if base is None:
                # 不允许扩展**新增**工具（那等于任意命令注入）
                logger.warning(f"[atopia] 扩展试图登记未内置的工具，忽略：{name}")
                continue
            lvl = lvl.upper()
            if lvl not in LEVEL_ORDER:
                logger.warning(f"[atopia] 扩展级别非法，忽略：{name}={lvl}")
                continue
            if LEVEL_ORDER[lvl] < LEVEL_ORDER[base]:
                # 只能更严：降级请求一律拒绝（否则配置文件可给 AI 开写权限）
                logger.warning(f"[atopia] 扩展试图**降低**风险级别，已拒绝："
                               f"{name} {base} → {lvl}")
                continue
            out[name] = lvl
    return out


def effective_tools(ws) -> list[Tool]:
    """内置 + 扩展覆盖（只升不降）后的工具列表。"""
    ov = load_overrides(ws)
    out: list[Tool] = []
    for t in BUILTIN_TOOLS:
        lvl = ov.get(t.name, t.level)
        if lvl == t.level:
            out.append(t)
        else:
            out.append(Tool(name=t.name, argv=t.argv, level=lvl, summary=t.summary,
                            allowed_args=dict(t.allowed_args),
                            dangerous_flags=t.dangerous_flags))
    return out


def effective_tool(ws, name: str) -> Tool:
    """按扩展覆盖取单个工具（仍要求已登记）。"""
    t = get_tool(name)
    lvl = load_overrides(ws).get(t.name)
    if not lvl or lvl == t.level:
        return t
    return Tool(name=t.name, argv=t.argv, level=lvl, summary=t.summary,
                allowed_args=dict(t.allowed_args), dangerous_flags=t.dangerous_flags)
