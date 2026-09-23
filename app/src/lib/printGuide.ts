/** printGuide.ts — VB-6 浏览器打印教程（docs/14 §VB-6 / 05-D30）。
 *
 *  纯数据模块：不给出 UI，被 PrintGuideModal.vue 消费；供「作业纸版式」页
 *  打印卡 / 帮助卡挂「教程」按钮弹出（该视图由版式页负责代理并行开发，
 *  本任务只提供数据与组件引用，wiring 见 docs/13 §S2c 记录）。
 *
 *  内容口径 = D30 HTML + 浏览器打印主通道：A4 / 边距=无 / 页眉页脚=关 /
 *  背景图形=开（水印与版式块依赖背景图形打印）。浏览器差异指向
 *  docs/14 §VC（预览版图）与 §VB（HTML 打印主线）、HVB 打印保真验收。
 */

export interface PrintGuideStep {
  title: string
  detail: string
}

export interface PrintGuideBrowsers {
  chrome: string
  edge: string
  firefox: string
  safari: string
}

export interface PrintGuide {
  /** 打印对话框四项设置（docs/14 §VB-6）。 */
  settings: PrintGuideStep[]
  /** 浏览器差异说明（键 = UI tab 标签）。 */
  browsers: PrintGuideBrowsers
  /** 指向 docs/14 的相关条目。 */
  docRefs: string[]
}

export const PRINT_GUIDE: PrintGuide = {
  settings: [
    {
      title: '纸张大小 = A4',
      detail:
        '打印对话框「纸张尺寸」选 A4（部分浏览器称 Letter/A4 自动），任务包版式按 A4 portrait/landscape 排，选错纸张会整体缩放错位。',
    },
    {
      title: '边距 = 无（None）',
      detail:
        'HTML 分页块已自带 2cm 内边距（@page 语义），浏览器边距应设为「无/默认最小」，否则左右被二次挤压、水印与页脚可能被裁。',
    },
    {
      title: '页眉页脚 = 关（关闭页脚 / Headers and footers off）',
      detail:
        '浏览器默认页眉（网址/日期/页码）与作业纸自带的页眉页脚层重叠，务必取消勾选；火狐在「更多设置 → 页眉页脚」里关。',
    },
    {
      title: '背景图形 = 开（Print backgrounds on）',
      detail:
        '水印层与版式块的底色/分隔线以 CSS background 实现，「背景图形」不勾会丢失水印与底色，只剩黑色文字。',
    },
  ],
  browsers: {
    chrome:
      '首选：A4 快捷选项→边距「无」→scale 默认 100→勾「背景图形」→取消「页眉页脚」。目标选「另存为 PDF」可直接得到带水印整班 PDF。',
    edge:
      '与 Chromium 同内核，选项位置基本一致；差异：默认打印机常是 OneNote/Print to PDF，请手动切换输出目标；「更多设置」里背景图形默认关。',
    firefox:
      '「页面设置」有独立「页眉页脚」多选下拉（选空白）；无「背景图形」开关——用「页面设置→选项→打印背景(颜色和图片)」，未勾则水印/底色不打印（已知差异，Firefox 建议Chrome/Edge 环境出终版）。',
    safari:
      'macOS：打印对话框「显示详细信息」→纸张 A4；勾选「打印背景和颜色」；Safari 无独立页眉页脚开关，页眉由系统打印头控制（可接受程度视系统版本而异）。',
  },
  docRefs: [
    'docs/14 §VC — 预览 = 全功能版图（模板/类型/整班/名单/成绩）',
    'docs/14 §VB-6 — 打印教程需求原点（浏览器对话框差异）',
    'docs/14 §HVB — HTML 打印保真（A4 每生分页块 / 水印 / @page）',
  ],
}

export const PRINT_GUIDE_SUMMARY =
  '打印教程：A4 · 边距=无 · 页眉页脚=关 · 背景图形=开（详见教程弹层 / docs/14 §VB-6）。'
