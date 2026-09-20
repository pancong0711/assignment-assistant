import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// GitHub Pages 子路径部署（docs/06 阶段2）：未来托管在
// https://<user>.github.io/assignment-assistant/app/ 之下。
export default defineConfig({
  base: '/assignment-assistant/app/',
  plugins: [vue()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
