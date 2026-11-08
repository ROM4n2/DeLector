# 视觉回归 P0（本地）

> 目标：先让视觉回归在本地稳定可跑、可判红绿。P0 只建工具不改样式；P1 起 token 换色必须用同一套矩阵与基线证明「颜色变了、结构没变」。
> 产物默认落在 `_artifacts/`（已 gitignore）；入库的只有工具、测试和 `tests/fixtures/visual/computed_style_baseline.json`。

## 1. 一键跑矩阵

```powershell
python tools/visual_matrix.py
```

脚本会：建临时数据目录 → 启动本地服务（预置文章落库）→ 种 6 张 A1 词卡 → 跑 12 界面 × 3 宽度截图 → 导出 computed-style → 跑三条闸 → 与入库基线比对 → 关服务清临时目录。

常用参数：

```powershell
python tools/visual_matrix.py --out _artifacts/my-run          # 指定产物目录
python tools/visual_matrix.py --widths 393,1280                # 只跑部分宽度
python tools/visual_matrix.py --only home,reader,settings       # 只跑部分界面（排障）
python tools/visual_matrix.py --update-baseline                 # 有意变更后更新基线
python tools/visual_matrix.py --keep-data                       # 保留临时数据目录
```

产物目录内容：

| 文件 | 用途 | 入库 |
| --- | --- | --- |
| `NN-<scene>-<width>.png` | 截图矩阵 | 否 |
| `computed-style.json` | 本次 12 控件属性现值 | 否 |
| `summary.json` | 张数、耗时、失败/缺失明细 | 否 |
| `server.log` | 本次服务日志 | 否 |

### 12 个界面

| # | key | 界面 | 进入方式 |
| --- | --- | --- | --- |
| 1 | `home` | 首页 / 文稿库 | 默认视图，等 `.article-row` |
| 2 | `reader` | 阅读器 | 打开第一篇文章，等 `.tok` |
| 3 | `drawer` | 词卡 / 生词抽屉 | 阅读器选中词元后 `openDrawer("vocab")` |
| 4 | `cards` | 卡盒（闪卡牌堆） | `loadCards()` + `setCardViewMode("deck")` |
| 5 | `exam` | 备考总览 | `show("exam")`，等选中模块 |
| 6 | `progress` | 学习进度 | `loadProgress()`，等统计环 |
| 7 | `writer` | 写作诊断 | `show("writer")`，等编辑器 |
| 8 | `german` | 德语背词工作台 | iframe 内 `#view-review` 可见 |
| 9 | `search` | 全文检索 | 输入 `der` 并触发检索 |
| 10 | `encounter` | 遇见区 / 分级短篇 | `show("encounter")` |
| 11 | `settings` | 设置弹窗 | `openSettingsModal()` |
| 12 | `quiz` | 测验浮层 | 卡盒内 `openQuizOverlay()` |

宽度固定为 **393 / 360 / 1280**（移动端 844 高，桌面 900 高），共 36 张。实际张数、逐页耗时和失败原因以 `summary.json` 为准；任何场景报错都会让脚本非 0 退出，不静默跳过。

截图前会等字体和有限动画结束，并把 `iterations === Infinity` 的循环动画暂停在 0ms（marquee、光标等），避免同一份代码两次截图出现逐帧差异。

## 2. computed-style 基线

入库基线：[tests/fixtures/visual/computed_style_baseline.json](../../tests/fixtures/visual/computed_style_baseline.json)。

12 个控件选的是**承载语义与状态**的元素，不是通用按钮堆叠：

| key | 控件 | 场景 |
| --- | --- | --- |
| `nav-tab-active` | 顶部导航选中态 | home |
| `mobile-nav-active` | 底部导航选中态 | home @393 |
| `article-row` | 文稿列表行 | home |
| `btn-primary` | 主按钮 `btn-dark` | cards |
| `btn-ghost` | 次按钮 `btn-ghost` | cards |
| `btn-accent` | 强调按钮 `btn-accent` | encounter |
| `tok-A1` | 阅读器 A1 词元 | reader |
| `tok-selected` | 阅读器选中词元 | reader-select |
| `deck-active-card` | 闪卡牌堆顶卡 | cards |
| `exam-module-active` | 备考模块选中态 | exam |
| `stat-ring-coral` | 进度统计环 | progress |
| `settings-input` | 设置输入框 | settings |

每个控件记录 20 个属性：`display / width / height / color / background-color / border-top-color / border-top-width / border-radius / font-family / font-size / font-weight / line-height / letter-spacing / padding-top / padding-left / box-shadow / opacity / transform / transition-duration / animation-name`。

比对命令：

```powershell
python tools/visual_baseline.py compare --current _artifacts/visual-matrix/<时间戳>/computed-style.json
```

输出会精确到「哪个控件、哪个属性、从什么变成什么」：

```text
[DIFF] btn-primary（主按钮 btn-dark / #view-cards .btn.btn-dark）.background-color: 'rgb(21, 20, 15)' -> 'rgb(193, 74, 43)'
```

有差异即退出码 1；无差异打印「基线一致（12 个控件）」。

## 3. 三条闸

```powershell
python tools/visual_gates.py          # 人读
python tools/visual_gates.py --json   # 机器读
```

| 闸 | 口径 | 预算 | P1 实测（2026-11-08, origin/master `0ec6dfd`） |
| --- | --- | --- | --- |
| 颜色字面量 | `static/style.css` 中 `:root` 以外的 hex 出现次数 + rgba/rgb 唯一值 | hex ≤ 700 / rgba ≤ 150 | 581 / 118 |
| 逼近告警 | 任一字面量达到预算的 90%（hex 630 / rgba 135）时打印 `[WARN]`，不阻断 | 90% | 未触发（hex 83.0% / rgba 78.7%） |
| 对比度 | 语义 token 对，正文 4.5:1，大字与图形 3:1 | 见下 | 最低 4.63 |
| 循环动画 | `static/**/*.css` 中 `infinite` 声明数 | == 7 | 7 |
| mustard 用途 | 裸 `--mustard` 是否出现在文字色声明 | 0 | 0 |

所有数值都在运行时从 CSS 现算。`--json` 会带出每对颜色的前景/背景解析值与实测比值。

**闸门内的对比度对**（全部通过）：`ink|ink-mute|pencil` on `paper`、`paper` on `ink`、`paper-card` on `accent`、`danger|moss` on `paper`、`accent` on `paper`、`ink` on `mustard`、`paper-card` on `moss`、`muted|ink-faint|coral|mustard-ink` on `paper`、`paper-card` on `coral`。

## 3.1 P1 换色：仅 token，5 处欠账清零

### 改前 / 改后（现算）

| token 对 | 角色 | 改前 | 改后 | 阈值 |
| --- | --- | --- | --- | --- |
| `coral` on `paper` | 正文（原按图形） | 2.82 | **5.26** | ≥4.5 |
| `paper-card` on `coral` | 正文（原按大字） | 2.99 | **5.58** | ≥4.5 |
| `muted` on `paper` | 正文 | 3.49 | **4.76** | ≥4.5 |
| `ink-faint` on `paper` | 正文 | 3.43 | **4.98** | ≥4.5 |
| `mustard` on `paper` | 仅装饰 | 1.72 | 1.72 | 不判定 |
| `mustard-ink` on `paper` | 正文（新 token） | — | **5.69** | ≥4.5 |

### coral：单值重选，不拆 fill/text

所有 coral 底色上都压白色小字（0.625–0.76rem：更新 chip hover、feed 等级标签、feed 摄入按钮、遇见区两个新增按钮），所以底色本身必须对白色 ≥4.5。若拆成「亮底色 + 白字」，要达标仍需改规则体里的文字颜色，超出「只动 token」范围；而按 4.5 反推，文字向与底色向会收敛到同一亮度，拆出的两个值几乎相同，不增加能力。因此统一取 `#b44322`——它本就是 24 处 coral 旧回退值，实测 5.26 / 5.58 双向过线。代价是装饰性 coral 点线一起变深，对比度反而更稳。

### mustard：仅装饰，禁止承载文字

`--mustard: #e9b94a` 保持 1.72，只允许出现在边框、描边、阴影等非文本处；任何文字色 MUST 用新 token `--mustard-ink: #825c00`（5.69）。workbench 的 `--hard` 同时承担文字色，已改为 `var(--mustard-ink)`。机械闸 `mustard decorative-only` 会扫描 `static/style.css`，裸 `--mustard` 一旦出现在 `color / caret-color / text-decoration-color / text-emphasis-color` 声明即红。

### token 分层（暗色只留插槽）

改动只涉及 4 组 token，没有重写整张色板：

```css
/* 值层：只放色值，未来暗色主题只替换这一层 */
--color-coral-700: #b44322;
--color-mustard-400: #e9b94a;
--color-mustard-700: #825c00;
--color-gray-500: #756e61;
--color-gray-450: #726b5e;

/* 语义层：规则体只认这一层 */
--color-accent-coral: var(--color-coral-700);
--color-accent-mustard: var(--color-mustard-400);
--color-accent-mustard-ink: var(--color-mustard-700);
--text-muted: var(--color-gray-500);
--text-faint: var(--color-gray-450);

/* 兼容层：既有规则体不动 */
--coral: var(--color-accent-coral);
--mustard: var(--color-accent-mustard);
--mustard-ink: var(--color-accent-mustard-ink);
--muted: var(--text-muted);
--ink-faint: var(--text-faint);
```

**双份镜像**：主应用只加载 `static/style.css`（`:root` 在 `src/css/01-tokens-base.css`），workbench iframe 只加载 `static/css/tokens.css`，iframe 不继承父文档 `:root`。两处 MUST 同步；`test_token_mirrors_agree_for_p1_pairs` 会逐 token 比对解析值。暗色插槽沿用 workbench 既有 `[data-theme="dark"]`，本轮只保证 `--hard` 在暗色下仍指向文字安全色，不实现暗色。

### P1 验证记录

- 矩阵：改前 / 改后各 36/36 张，失败 0、控件缺失 0；改后再跑一遍作为噪声基线。
- 截图差异只出现两类颜色迁移：`rgb(237,111,92) → rgb(180,67,34)`（coral）与 `rgb(140,132,119) → rgb(117,110,97)`、`rgb(139,134,118) → rgb(114,107,94)`（muted / ink-faint），其余为文字抗锯齿混合色。
- 已知非确定截图（german / encounter / drawer / reader@1280）在两份 P0 基线之间同样会变，属于存量噪声；这些界面的差异全部落在噪声区内，不与本轮颜色迁移冲突。
- computed-style 只更新 3 条：`mobile-nav-active.border-top-color`、`stat-ring-coral.border-top-color`、`stat-ring-coral.color`，均为 coral token 的有意换色；其余 12 控件 20 属性全部不变，说明布局与结构未动。


## 3.2 字面量上限：为什么是 700 / 150

**上限是硬顶，不是目标值。** 当前实测仍是 **hex 581、rgba 118**（2026-11-08，`origin/master` `0ec6dfd`），距离硬顶分别还有 119 / 32 的余量，占用约 83.0% / 78.7%。本轮调整闸门只是把「只剩 1 格」的旧预算换成可容纳后续工作的硬顶，**没有把任何现有规则体字面量转成 token**——那是后续组件族迁移的独立工作。

余量按即将到来的工作面预分，不是开放额度：

| 用途 | hex | rgba | 说明 |
| --- | ---: | ---: | --- |
| P2 组件族（按钮 / 导航 / 卡片牌堆 / 抽屉 / 播放器 / 模态） | ≤ 48 | ≤ 14 | 每族 ≤8 个单次硬投影、遮罩、渐变端点；能复用 token 的仍走 token |
| P3 边界收口（workbench iframe / A1 / 考试 / PWA 主题色） | ≤ 24 | ≤ 8 | iframe 不继承父 `:root`，少量局部值需就地声明 |
| T3–T9 动效与按压（hover / active 阴影、叠加色） | ≤ 12 | ≤ 6 | 计划内一次性反馈，不改布局 |
| 并行 PR 合并与一次性修复机动 | ≤ 35 | ≤ 4 | 只用于真实合并冲突，不作为新增功能的常规来源 |
| **合计余量** | **119** | **32** | 与 700 / 150 的差值一致 |

**逼近告警**：任一项达到硬顶的 **90%**（hex 630 / rgba 135）时，`visual_gates.py` 会在该行下方打印：

```text
[PASS] hex literals outside :root: 630 (预算 700)
       [WARN] 630/700（90%）已达逼近阈值 90%：新增字面量应优先改成 token
```

告警**不阻断**闸门（`ok` 仍为 `true`），但测试 `test_literal_caps_are_hard_ceilings_with_headroom` 要求实测低于该阈值。选 90% 而不是 95%，是为了在还来得及改 token 时给出一轮完整 PR 的提前量；等到 95% 才提示，剩余空间已不够一次组件族改动。

## 4. 一次失败怎么判

1. **先看 `summary.json`**：是场景没进入（`failures`）还是控件没找到（`missingControls`）。这类红是脚本/选择器问题，不是视觉回归。
2. **再看截图**：同宽度下对比上一版或 `origin/master` 的截图，确认差异是否只出现在预期区域。
3. **再看 computed-style diff**：
   - 只改了 token 值 → 通常多条控件同属性一起变，属于**有意换色**；
   - 只有某个控件某个属性变 → 优先怀疑**真回归**（例如误改组件规则）。
4. **最后跑闸**：颜色预算或对比度红了，说明改动越过了 P0 的约束。

**有意变更流程**：跑矩阵 → 人工确认截图与 diff → `python tools/visual_matrix.py --update-baseline` → 把 `tests/fixtures/visual/computed_style_baseline.json` 和改动一起提交，并在 PR/commit 说明为什么变。
**真回归流程**：不要更新基线；修代码后重跑，直到截图、computed-style、三条闸同时绿。

## 5. 边界

- 工具只读构建后的 `static/style.css`，不读 `src/css/`；改 token 必须同时改 `src/css/01-tokens-base.css` 与 `static/css/tokens.css` 两处镜像，再跑 `python tools/build_css.py` 与 `python tools/check_css_sync.py`。
- **不接 CI**：`.github/workflows/ci.yml`、`tools/ci_shards*` 仍由另一条线维护。
- P1 的截图比对是一次性脚本：先跑两遍改后矩阵得到噪声区，再与改前比对；尚未固化成命令。
- `font-family` 等属性受本机字体影响；换机器首次跑请先 `--update-baseline` 生成该机基线，或后续在 CI 容器里固定字体。
- 截图是**视口截图**，不是整页长图；滚动区域只覆盖首屏，布局回归以 12 界面首屏与 computed-style 为准。
- 浏览器查找顺序：`DELECTOR_CHROME` → `%LOCALAPPDATA%\ms-playwright\chromium-*` → 系统 Chrome/Edge → `/usr/bin/chromium`。找不到时脚本直接报错，不静默降级。
