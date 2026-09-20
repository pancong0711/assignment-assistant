#!/usr/bin/env bash
# CI/本地脱敏检查：阻止敏感数据进入仓库。
# 用法: bash tools/check-secrets.sh [路径]   (默认: 已暂存文件)
set -euo pipefail
files=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || git ls-files)
[[ -z "${files// /}" ]] && files=$(git ls-files)
fail=0
log() { echo -e "\033[31m[脱敏失败] $*\033[0m"; fail=1; }

# 1) 红名单：绝不入库的路径（与 .gitignore 互补，防误 add 例外规则）
# grading/ 是学生数据目录红线；engine/src/assist/grading/ 是引擎源码包（代码，允许）
banned_regex='(^|/)(_legacy|roster|exports|handwriting|submissions|作业)/|(^|/)kb/[^/]+\.xlsx$|\.env$'
while IFS= read -r f; do
  [[ -e "$f" ]] || continue
  echo "$f" | grep -Eq "$banned_regex" && log "路径命中红线: $f"
  if echo "$f" | grep -Eq '(^|/)grading/' && [[ "$f" != engine/src/assist/grading/* ]]; then
    log "路径命中红线(grading 学生数据目录): $f"
  fi
done <<< "$files"

# 2) 密钥特征扫描
if grep -InE '(api[_-]?key|token|secret|Bearer)[[:space:]]*[:=][[:space:]]*[^[:space:]"'"'"'`]{16,}' $(echo "$files") 2>/dev/null | grep -viE 'placeholder|example|<.*>|xxx' | head -20; then
  [[ ${PIPESTATUS[0]} -eq 0 ]] || true
fi
grep -InE "sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}" $(echo "$files") 2>/dev/null \
  && log "疑似真实密钥" || true

# 3) 可疑真实姓名/班级（示例占位允许；本脚本自身保留检测词，故排除自身）
if grep -InE --exclude=check-secrets.sh '潘聪|环境[0-9]{2}|化工班|应用化[0-9]{2}' $(echo "$files") 2>/dev/null; then
  log "命中真实姓名/班级字样（应使用占位符）"
fi

[[ $fail -eq 0 ]] && echo "脱敏检查通过" && exit 0 || exit 1
