import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 部署形态（docs/05-D2/D13）：
// - GitHub Pages（project site）→ base /assignment-assistant/（本文件默认）
//   https://pancong0711.github.io/assignment-assistant/
// - 其他宿主/引擎同源（assist serve 托管 dist-lan）→ 覆盖 base：
//     npm run build -- --base=./                       （相对路径，最灵活）
//     npm run build -- --base=/ --outDir dist-lan      （根路径，本机 serve 同源）
// 说明：阶段4b 起 CI 以此默认配置构建并部署 Pages；dist-lan 仅本机演示用。
export default defineConfig({
  base: '/assignment-assistant/',
  plugins: [vue()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
