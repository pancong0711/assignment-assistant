#!/usr/bin/env bash
# 开源中文字体下载（不随仓库分发）：
#   LXGW WenKai（楷体类，SIL OFL）→ engine/assets/fonts/
#   WenQuanYi Micro Hei（黑体类，GPL+字体例外）多数 Linux 自带；Windows 请自备 simsun.ttc/simkai.ttf
# 用法: bash tools/fonts-download.sh
set -euo pipefail
dest="$(cd "$(dirname "$0")/.." && pwd)/engine/assets/fonts"
mkdir -p "$dest"
url="https://github.com/lxgw/LxgwWenKai/releases/download/v1.520/LXGWWenKai-Regular.ttf"
if [[ ! -f "$dest/LXGWWenKai-Regular.ttf" ]]; then
  echo "下载 LXGW WenKai (楷体开源替代) → $dest"
  curl -fL "$url" -o "$dest/LXGWWenKai-Regular.ttf"
fi
echo "完成。真实 simsun.ttc/simkai.ttf（Windows）请自行放置于 workspace 根或 settingst fonts 覆盖。"
