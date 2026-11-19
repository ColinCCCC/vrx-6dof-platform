#!/usr/bin/env bash
# 重新生成 docs/diagrams 下的三张 Archify 框图：渲染 HTML（含校验）并导出 README 用 PNG。
#
# 用法：
#   ./scripts/render_diagrams.sh                # 全部三张，渲染 + 导出 PNG
#   ./scripts/render_diagrams.sh node-topology  # 只处理一张
#   ./scripts/render_diagrams.sh --no-png       # 只渲染 HTML，不导 PNG
#
# 依赖已安装的 Archify 技能（~/.dsh/skills/archify）与 Chrome/Chromium，
# 详见 docs/diagrams/AGENT-GUIDE.md。
set -euo pipefail

cd "$(dirname -- "${BASH_SOURCE[0]}")/.."

EXPORT_PNG=1
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --no-png) EXPORT_PNG=0 ;;
    -h|--help)
      cat <<'HELP'
重新生成 docs/diagrams 下的三张 Archify 框图：渲染 HTML（含校验）并导出 README 用 PNG。

用法：
  ./scripts/render_diagrams.sh                # 全部三张，渲染 + 导出 PNG
  ./scripts/render_diagrams.sh node-topology  # 只处理一张
  ./scripts/render_diagrams.sh --no-png       # 只渲染 HTML，不导 PNG

依赖已安装的 Archify 技能（~/.dsh/skills/archify）与 Chrome/Chromium，
详见 docs/diagrams/AGENT-GUIDE.md。
HELP
      exit 0
      ;;
    *) ARGS+=("$arg") ;;
  esac
done

find_archify() {
  local candidate
  for candidate in \
    "${ARCHIFY_CLI:-}" \
    "${HOME}/.dsh/skills/archify/bin/archify.mjs" \
    "tools/archify/archify/bin/archify.mjs"; do
    if [[ -n "$candidate" && -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

if ! ARCHIFY="$(find_archify)"; then
  cat >&2 <<'MSG'
没有找到 Archify。任选一种方式：
  1. 技能装到用户级（推荐，所有工作区可用）：
       cp -a <archify 仓库>/archify ~/.dsh/skills/archify
     或用 Skills CLI：npx skills add tt-a1i/archify -g
  2. 临时指定：ARCHIFY_CLI=/path/to/archify/bin/archify.mjs ./scripts/render_diagrams.sh
  3. 本地 checkout：git clone --depth 1 https://github.com/tt-a1i/archify tools/archify
MSG
  exit 1
fi

ALL=(control-loop node-topology dependencies)
TARGETS=("${ARGS[@]}")
if [[ ${#TARGETS[@]} -eq 0 ]]; then
  TARGETS=("${ALL[@]}")
fi

# 每次跑用新的 out-dir：同一输出路径的浏览器证据不能复用
RUN_DIR=".cache/archify/run-$(date +%Y%m%d-%H%M%S)"

for name in "${TARGETS[@]}"; do
  json="docs/diagrams/${name}.json"
  html="docs/diagrams/${name}.html"
  png="docs/diagrams/${name}.png"
  if [[ ! -f "$json" ]]; then
    printf '跳过 %s：找不到 %s\n' "$name" "$json" >&2
    continue
  fi
  node "$ARCHIFY" finalize architecture "$json" "$html" \
    --quality showcase --out-dir "${RUN_DIR}/${name}"
  if [[ $EXPORT_PNG -eq 1 ]]; then
    node scripts/export_diagram_png.mjs "$html" "$png"
  fi
  printf 'ok  %s\n' "$png"
done

printf '\n交互版 HTML 留在 docs/diagrams/（已 gitignore），可直接用浏览器打开预览。\n'
