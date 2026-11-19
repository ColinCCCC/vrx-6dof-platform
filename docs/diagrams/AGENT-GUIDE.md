# README 框图维护指南（给 agent）

README 的三张图是 **Archify 生成物**，不是手绘图也不是 Mermaid：

```
docs/diagrams/<图>.json   ← 唯一需要编辑的源（类型化 JSON IR）
docs/diagrams/<图>.png    ← 进仓库，README 引用
docs/diagrams/<图>.html   ← 本地预览产物，已 gitignore，不提交
```

改图 = 改 JSON + 跑脚本，全程有校验兜底。**不要**手改 PNG、不要退回 Mermaid、
不要把 HTML 提交进仓库。

## 0. 环境自检（30 秒）

```bash
node -v                                              # 需要 ≥ 18
ls "${ARCHIFY_CLI:-$HOME/.dsh/skills/archify/bin/archify.mjs}"   # Archify 技能
command -v google-chrome chromium chromium-browser   # 浏览器网关用
```

- 没有 Archify：`npx skills add tt-a1i/archify -g`，或把仓库里的 `archify/` 拷到
  `~/.dsh/skills/archify`；
- 没有浏览器：设 `ARCHIFY_CHROME=/path/to/chrome`（容器/root 再加
  `ARCHIFY_CHROME_NO_SANDBOX=1`）。`finalize` 的最后一道 gate 是真实浏览器检查，
  没有浏览器会失败——先装浏览器，别跳过这道 gate。

## 1. 三张图的现状

| 图 | 源文件 | 画布 | 主要内容 |
| --- | --- | --- | --- |
| 控制策略 | `control-loop.json` | 1240×728 | 世界系目标→误差→前馈/ESO/FX-LMS→Σ→IK→速度环→Gazebo 反馈 |
| 节点通信 | `node-topology.json` | 1250×588 | Gazebo 内船体、桥接、补偿、速度环、平台 UDP 链 |
| 依赖关系 | `dependencies.json` | 1040×688 | 环境/中间件/本项目三个包 |

## 2. 改 JSON

每张图的结构（`architecture`，schema_version 1）：

```jsonc
{
  "components": [
    { "id": "comp", "type": "backend", "label": "arm_wave_compensation",
      "sublabel": "ESO + 前馈 + FX-LMS · 20 Hz", "pos": [540, 60], "size": [170, 72] }
  ],
  "connections": [
    { "id": "pose-to-comp", "from": "pose", "to": "comp",
      "label": "TF 船体", "variant": "emphasis" }
  ],
  "boundaries": [
    { "kind": "region", "label": "Gazebo Harmonic · VRX", "wraps": ["waves", "boat"], "pad": 20 }
  ],
  "cards": [ { "dot": "cyan", "title": "仿真侧", "items": ["…"] } ]
}
```

- `type`：`frontend | backend | database | cloud | security | messagebus | external`（决定配色和图例分组）；
- `variant`：`default`（普通）、`emphasis`（主链路）、`security`、`dashed`（计划中/可选）；
- 虚线 = 还没落地的计划项，这是本仓库的既有约定，别把已实现的东西画成虚线。

### 布局规则（都是踩过的坑）

1. **端口是边的中点**。写了 `toSide: "left"`，就意味着最后一段必须水平向右进入
   `(节点左边界, 节点垂直中心)` —— 所以 `via` 的最后一点要和该中心同 `y`，否则报
   `endpoint-side-direction`。同理 `fromSide` 决定首段方向。
2. **标签要留够空隙**：所需间距 ≈ `6.5px × 字符数 + 21px`，中文按 2 个字符算。
   节点间 70px 的缝大约只放得下 3 个汉字；长话题名请写进节点的 `sublabel`，label 用短词。
3. **别让两条线挤同一条走廊**：平行段间距 < 8px 会报 `ambiguous-corridor`。
4. **回流线走外侧空地**，不要横穿节点群；实在要穿就用 `via` 显式指定走廊。
5. 加节点后**整列重排**，不要只挪一个盒子，否则标签和线立刻打架。

## 3. 渲染 + 导出

```bash
./scripts/render_diagrams.sh                 # 全部三张
./scripts/render_diagrams.sh node-topology   # 只处理一张
./scripts/render_diagrams.sh --no-png        # 只渲染，不导 PNG
```

脚本做三件事：`finalize`（schema 校验 → 渲染 → HTML/SVG 严格检查 → 真实浏览器检查）、
用无头 Chrome 把图裁成 2 倍 PNG、桌面保留 HTML 供你打开预览。

只想手动跑一步时：

```bash
node "$HOME/.dsh/skills/archify/bin/archify.mjs" finalize architecture \
  docs/diagrams/node-topology.json docs/diagrams/node-topology.html \
  --quality showcase --out-dir .cache/archify/manual
```

## 4. 诊断码对照表

| 诊断码 | 含义 | 修法 |
| --- | --- | --- |
| `clean-flow/edge-through-node` | 连线穿过了无关节点 | 改 `via` 绕开，或挪节点 |
| `clean-flow/endpoint-side-direction` | 声明的 `fromSide`/`toSide` 与实际方向不符 | 让 `via` 首/末段沿该方向，或删掉 side 交给自动路由 |
| `composition/proper-crossing` | 两条线交叉（showcase 级不允许） | 重排节点让交叉消失；实在必要再保留并接受落级 |
| `composition/ambiguous-corridor` | 两条线共用一条窄走廊 | 拉开 ≥ 8px |
| `composition/label-route-clearance` | 标签压到别的线 | 缩短标签，或挪 `via`/节点 |
| `viewer/evidence-path-conflict` | 同一输出路径已有浏览器证据 | 换 `--out-dir`（脚本每次自动带时间戳目录） |
| `viewer/browser-check-runtime` | 找不到/连不上 Chrome | 设 `ARCHIFY_CHROME`、`ARCHIFY_CHROME_NO_SANDBOX=1` |

## 5. 验收清单

- [ ] `validate / deliver / check / browser-check` 四道全 pass；
- [ ] PNG 尺寸变化合理（没有突然变宽/变高到超过 1500px 宽）；
- [ ] 打开 `docs/diagrams/<图>.html` 肉眼过一遍：标签压线、交叉、图例分组是否正常；
- [ ] 图里的节点名、话题、频率、IP、协议与 `src/marine_am_platform/`、`config/platform_bridge.yaml` 一致；
- [ ] `git status` 里**没有** `docs/diagrams/*.html`。

## 6. 提交

```bash
git add docs/diagrams/<图>.json docs/diagrams/<图>.png README.md
git commit -m "README：节点图补充 xxx 链路"
```

## 7. 为什么是这套做法

- **不用 Mermaid**：GitHub 的 Mermaid 不能控布局，节点一多就糊成一团，这正是当初换掉它的原因；
- **PNG 进仓库**：GitHub README 不能内嵌 HTML/iframe，所以图只能以图片形式出现，
  交互版留作本地预览；
- **字号**：画布宽约 1200px，GitHub 正文宽度下标签约 9px、副标题 6–7px。要更大就得把图
  改成「窄高双列」，画布收到 ~900px，字号相对放大三成——这是需要用户拍板的改动。
