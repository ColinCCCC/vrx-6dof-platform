# 框图（Archify）

三张 README 框图用 [Archify](https://github.com/tt-a1i/archify) 生成，不是 Mermaid：
源是带 schema 校验的类型化 JSON，渲染成 PNG 供 README 引用。交互版 HTML 只在本地生成，不进仓库。

| 图 | 源文件（改这个） | README 用图 |
| --- | --- | --- |
| 控制策略 | `control-loop.json` | `control-loop.png` |
| 节点通信 | `node-topology.json` | `node-topology.png` |
| 依赖关系 | `dependencies.json` | `dependencies.png` |

`.json` 是 Archify 的 JSON IR，`.png` 是生成物；改图只改 `.json` 再重新生成。

> 让 agent 改图的完整规则（坐标约定、诊断码、验收清单）见 [AGENT-GUIDE.md](AGENT-GUIDE.md)，
> 仓库根目录的 [AGENTS.md](../../AGENTS.md) 里有一条强制入口。

## 环境

Archify 技能已装在用户级 `~/.dsh/skills/archify`，所有 DSH 工作区都能用（不占用本仓库）。
换机器时任选一种：

```bash
npx skills add tt-a1i/archify -g                      # Skills CLI
cp -a <archify 仓库>/archify ~/.dsh/skills/archify     # 手动拷技能目录
```

渲染和导图需要本机有 Chrome / Chromium，没有就用环境变量指定：

```bash
export ARCHIFY_CHROME=/path/to/chrome        # 可选
export ARCHIFY_CHROME_NO_SANDBOX=1           # 容器/root 环境才需要
```

## 改图

```bash
./scripts/render_diagrams.sh                 # 三张：渲染 + 过校验 + 导出 PNG
./scripts/render_diagrams.sh node-topology   # 只处理一张
```

脚本对每张图依次做：

1. `finalize`：schema 校验 → 渲染 → HTML/SVG 严格检查 → 真实浏览器检查；
2. `export_diagram_png.mjs`：用无头 Chrome 把图裁成 2 倍 PNG，覆盖同名 `.png`；
3. 保留同名 `.html` 供浏览器预览（已 gitignore）。

失败时会给出可操作的诊断（例如 `clean-flow/edge-through-node`、`composition/proper-crossing`），
对照 [AGENT-GUIDE.md](AGENT-GUIDE.md#4-诊断码对照表) 改 `pos` / `via` 再跑即可。

## 约定

- 标题和节点用语用中文，包名/话题名/参数名保持英文原样；
- 虚线（`variant: "dashed"`）= 计划中或可选，实线 = 已实现；
- 节点里的频率、话题名、IP 要与 `src/marine_am_platform` 和 `config/platform_bridge.yaml` 一致，
  改代码时顺手同步这三张图。

## 关于 DSH 插件

Archify 官方有 DSH 插件 `@tt-a1i/archify-dsh`，但目前只发布到 1.0.0：它声明的目标是 DSH 0.1.2-rc.1，
而且把 `includeDefaultRoots` 设成 `false`，装进正在用的 profile 会把其他技能从目录中挤掉
（上游 issue #906，修复版 1.1.0 尚未发布）。所以这里用用户级技能根安装，效果一样、不影响别的技能。
等 1.1.0 发布后再考虑换成插件。
