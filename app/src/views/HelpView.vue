<script setup lang="ts">
/**
 * HelpView.vue — docs/14 使用说明项（方案 A：独立选项卡）+ docs/15-usage-manual.md 同源。
 * 用户拍板：使用说明 = 独立选项卡；不依赖引擎（静态可用）。
 */
const QUICK_STEPS = [
  { n: 1, title: '下载一键脚本', body: '设置中心 → 一键启动 / 安装 → 下载 start.bat（Windows）或 start.sh（macOS/Linux）。' },
  { n: 2, title: '移动到 workspace 目录', body: 'D28 约定：start 脚本放在你常用资料目录（=workspace）。安装的 uv/Python/venv/缓存全部在该目录 .runtime/（删除目录=整体卸载）。' },
  { n: 3, title: '双击运行（自动起引擎 + 开 PWA）', body: 'start.log 记全程；引擎启动后浏览器访问 http://127.0.0.1:8601/（引擎同源 PWA 即完整体验）。' },
]

const TAB_GUIDES: { tab: string; items: string[] }[] = [
  { tab: '设置中心', items: [
    '引擎地址 / token / workspace 相关设置与体检（含【🔧 修复】按钮，走 /install）',
    'source_used 下载源说明（tuna/ghfast/npmmirror）',
  ]},
  { tab: '题库编辑器', items: [
    'xlsx 读入 / 编辑 / 写回（File System Access 优先，不可用降级下载导出）',
    '列结构兼容 docs/05-D3（id/content/img_path/page/related/type/solution/note）',
  ]},
  { tab: '作业纸版式', items: [
    '竖/横 A4、页眉页脚、水印 items、作业纸导出/清单',
    '🖨 打印浏览器版（window.print）/ ⬇ 下载整班 HTML（D30 主通道）',
    'per_page 1-4：4 = 十字 2×2、横版 2/3 = 左右栏、竖版 2/3 = 上下行',
  ]},
  { tab: '作业纸内容', items: [
    '跨 kind/tag 选题篮（含题图预览）',
    '每份作业纸 target_tag 标注 → 变体编排绑定 → 一键 batch zip',
    '👁 预览整班（HTML overlay，不依赖引擎）',
  ]},
  { tab: '班级与标签', items: [
    '名单 / 成绩导入预览（表头 + 前 3 行 + 列映射核对）',
    '成绩源宽表（行=学生，列=各源；默认全勾 = 分层依据，可取消某列排除）',
    '重算综合得分 / 按此列切分；特殊标签 / 批量打 tag / punish',
  ]},
  { tab: '学习通', items: [
    '阶段 6 占位（当前公告/上传/登录 chip 均置灰 + 引导说明）',
    '内含批阅工作台（作业纸选择 / 图片本地分组 / CLI 指引）',
  ]},
  { tab: '导入导出', items: [
    '题库 xlsx / 作业纸 JSON / 变体 batch zip 导出',
    'zip 导入可重建 workspace 结构（过滤 .runtime/，D14 规范）',
  ]},
]

const NAV_KEYS: Record<string, string> = {
  '设置中心': 'settings', '题库编辑器': 'kb', '作业纸版式': 'layout',
  '作业纸内容': 'content', '班级与标签': 'roster', '学习通': 'xxetong', '导入导出': 'transfer'
}
const openTab = (label: string) => {
  const k = NAV_KEYS[label]
  if (k) window.location.hash = `/${k}`
}

const PRINT_QA: { q: string; a: string }[] = [
  { q: '浏览器打印对话框设置', a: 'A4；边距=无；页眉页脚=关；背景图形=开（水印靠背景图形）' },
  { q: '打印在哪里最兼容', a: 'Chrome/Edge first；Firefox/Safari 差异见 docs/14 §VB-6' },
  { q: '打印结果与预览有细微差异', a: '极端排版跨浏览器会差异（引擎 reportlab/LaTeX 可做到像素一致，docs/05-D36 双引擎）' },
  { q: 'KaTeX 公式', a: 'PWA 自带 KaTeX 离线（0.16.4）—— 打印/浏览器/offline全数据可用' },
]

const FAQ: { q: string; a: string }[] = [
  { q: '【修复】按钮点不动？', a: '需引擎在线（Companion 模式）；静态模式下显示复制命令说明（D13）' },
  { q: '引擎 github.io 下载失败？', a: 'start.log 记录每条链（Pages primary / ghfast fallback / github direct）；换个时间段重试（CDN 抖动）' },
  { q: '多台机器共用 workspace？', a: '每台独立 workspace（数据本地）；D9 LAN 第二屏可 token 共连' },
  { q: '整班 100+ 学生 HTML 会太大？', a: '纯文本 + base64 题图（kb/fig 挂钩时数百 KB 页块）；建议 Chrome 打印（保存 PDF），兼容性最稳' },
  { q: 'GitHub 总是超时？', a: 'v10 已接多条下载链（Pages primary → github release → ghfast → 全仓 fallback），详见 D34' },
]
</script>

<template>
  <section class="help-view">
    <div class="card">
      <h2>使用说明 <small style="font-weight:400;color:var(--c-muted)">docs/14 使用说明项 · 方案 A：独立选项卡（docs/05-D37）</small></h2>
      <p class="hint">静态功能不依赖引擎；引擎在线解锁体检【🔧 修复】按钮、批阅、学习通（docs/05-D13）。</p>
      <h3>快速上手（3 步）</h3>
      <ol class="quick-steps">
        <li v-for="s in QUICK_STEPS" :key="s.n">
          <b>{{ s.title }}</b> — {{ s.body }}
        </li>
      </ol>
    </div>

    <div class="card">
      <h3>各选项卡速查（点击标题跳转对应选项卡）</h3>
      <details v-for="g in TAB_GUIDES" :key="g.tab" class="tab-guide" open>
        <summary @click.prevent="openTab(g.tab)"><b>{{ g.tab }}</b></summary>
        <ul>
          <li v-for="(it, i) in g.items" :key="i">{{ it }}</li>
        </ul>
      </details>
    </div>

    <div class="card">
      <h3>常见问题（FAQ / 打印相关）</h3>
      <details v-for="(p, i) in PRINT_QA" :key="i" class="print-qa" open>
        <summary><b>Q：{{ p.q }}</b></summary>
        <p>{{ p.a }}</p>
      </details>
      <details v-for="(p, i) in FAQ" :key="'f'+i" class="tab-guide" open>
        <summary><b>Q：{{ p.q }}</b></summary>
        <p>{{ p.a }}</p>
      </details>
    </div>
  </section>
</template>

<style scoped>
.help-view .card { margin-bottom: 14px; }
.quick-steps { padding-left: 20px }
.quick-steps li { padding: 3px 0; }
.tab-guide ul { margin: 5px 0 0 0; padding-left: 18px; }
</style>
