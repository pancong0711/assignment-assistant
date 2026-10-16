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
banned_regex='(^|/)(_legacy|roster|exports|handwriting|submissions|作业)/|(^|/)kb/[^/]+\.xlsx$|(^|/)settings\.local[^/]*\.json$|\.env$'
while IFS= read -r f; do
  [[ -e "$f" ]] || continue
  if echo "$f" | grep -Eq "$banned_regex"; then
    # 引擎源码例外：engine/src/assist/{grading,roster}/ 是代码（学生数据目录 classes/*/roster/ 仍拦截）
    if [[ "$f" == engine/src/assist/grading/* || "$f" == engine/src/assist/roster/* ]]; then :; else
      log "路径命中红线: $f"
    fi
  fi
  if echo "$f" | grep -Eq '(^|/)grading/' && [[ "$f" != engine/src/assist/grading/* ]]; then
    log "路径命中红线(grading 学生数据目录): $f"
  fi
done <<< "$files"

# 2) 密钥特征扫描（已知前缀 = 高置信；异形/高熵 = 启发式，宁少误报）
# 2a) 已知厂商密钥前缀（高置信，直接判失败）。
#     新增前缀时同步补 engine/tests/test_secret_scan.py 的样本，避免与测试写死 fixture 冲突。
KNOWN_PREFIX_RE='sk-[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|hf_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}'
known_hits=$(grep -InE "$KNOWN_PREFIX_RE" $(echo "$files") 2>/dev/null || true)
if [[ -n "$known_hits" ]]; then
  echo "$known_hits" | head -20
  log "疑似真实密钥（已知厂商前缀）"
fi

# 2b) 异形/高熵启发式：形如 `key/secret/token/password = "<32+ 位混合字符>"`。
#     要求同时满足：① 键名提示敏感；② 值 ≥32 字符且含大小写+数字；
#     ③ 排除占位/测试 fixture/文档示例（placeholder、example、xxx、<...>、test、demo、
#        fixture、sk-abc/sk-key/sk-secret/sk-demo 等显然的假值）。
ENTROPY_LINE_RE='(api[_-]?key|access[_-]?key|secret[_-]?key|client[_-]?secret|auth[_-]?token|password|passwd)["'"'"' ]?[[:space:]]*[:=][[:space:]]*["'"'"'\x60]?[A-Za-z0-9_\-]{32,}'
entropy_hits=$(grep -InE "$ENTROPY_LINE_RE" $(echo "$files") 2>/dev/null \
  | grep -viE 'placeholder|example|sample|dummy|fake|redacted|xxx+|<[^>]*>|\$\{|test|demo|fixture|abcdefgh|12345678|1234|stub|noop|0000|sk-key-|sk-secret-|sk-plain-|sk-legacy-|sk-demo' \
  || true)
if [[ -n "$entropy_hits" ]]; then
  echo "$entropy_hits" | head -20
  log "疑似异形密钥（敏感键名 + 长随机值；确认后请改占位符/移出仓库）"
fi

# 3) 可疑真实姓名/班级（示例占位允许；本脚本自身保留检测词，故排除自身）
if grep -InE --exclude=check-secrets.sh '潘聪|环境[0-9]{2}|化工班|应用化[0-9]{2}' $(echo "$files") 2>/dev/null; then
  log "命中真实姓名/班级字样（应使用占位符）"
fi

[[ $fail -eq 0 ]] && echo "脱敏检查通过" && exit 0 || exit 1
