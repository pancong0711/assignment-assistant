<script setup lang="ts">
/** VC-4/VC-6 复用预览卡（docs/14 §VC-4/§VC-6）：表头 + 前 3 行 + 列映射说明。
 *  名单导入（VC-4）与成绩源导入（VC-6）共用同一结构模型 PreviewTable ——
 *  教师在导入后即时核对解析结构（宽松列名 rule 与引擎同款，已在 lib 层完成映射）。
 *  纯展示组件：不持有状态、不依赖 store（数据由父级通过 props 注入）。 */

defineProps<{
  title: string
  preview: {
    headers: string[]
    rows: string[][]
    notes: string[]
    rowCount: number
  } | null
  /** 名称来源（文件名） */
  fileName?: string
  /** 重要度：ok=成功绿色 / warn=需要核对黄色（如未识别出姓名列） */
  tone?: 'ok' | 'warn'
}>()
</script>

<template>
  <div class="card preview-table-card" v-if="preview">
    <h2>{{ title }} <small v-if="fileName" style="font-weight:400;color:var(--c-muted)">{{ fileName }}</small></h2>
    <p class="hint" :class="{ notice: tone === 'warn' }" v-if="preview.notes.length">
      列映射说明（与引擎同款宽松列名 rule）：<code v-for="n in preview.notes" :key="n" style="display:inline-block;margin:1px 4px 1px 0">{{ n }}</code>
    </p>
    <p class="hint">导入 <b>{{ preview.rowCount }}</b> 条；下表为表头 + 前 3 行预览（完整数据已读入名单表/宽表，可继续核对）。</p>
    <div style="overflow:auto; max-height:260px; border:1px solid var(--c-border); border-radius:8px">
      <table class="grid preview-table">
        <thead>
          <tr><th v-for="h in preview.headers" :key="h">{{ h }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in preview.rows" :key="i">
            <td v-for="(c, j) in r" :key="j">{{ c }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.preview-table-card .preview-table th,
.preview-table-card .preview-table td { white-space: nowrap; }
</style>
