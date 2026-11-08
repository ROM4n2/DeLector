# 视觉回归 P0（本地）

> 目标：在**不接 CI、不改样式和页面**的前提下，先让视觉回归在本地稳定可跑、可判红绿。
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

| 闸 | 口径 | 预算 | P0 实测（2026-11-08, origin/master） |
| --- | --- | --- | --- |
| 颜色字面量 | `static/style.css` 中 `:root` 以外的 hex 出现次数 + rgba/rgb 唯一值 | hex ≤ 582 / rgba ≤ 118 | 581 / 118 |
| 对比度 | 语义 token 对，正文 4.5:1，大字与图形 3:1 | 见下 | 最低 4.63 |
| 循环动画 | `static/**/*.css` 中 `infinite` 声明数 | == 7 | 7 |

所有数值都在运行时从 CSS 现算。`--json` 会带出每对颜色的前景/背景解析值与实测比值。

**闸门内的对比度对**（全部通过）：`ink|ink-mute|pencil` on `paper`、`paper` on `ink`、`paper-card` on `accent`、`danger|moss` on `paper`、`accent` on `paper`、`ink` on `mustard`、`paper-card` on `moss`。

**已知欠账（P0 只报告不阻断，P1 换皮必须清零）**：

| 对 | 实测 | 要求 |
| --- | --- | --- |
| `muted` on `paper` | 3.49 | 4.5（正文） |
| `ink-faint` on `paper` | 3.43 | 4.5（正文） |
| `coral` on `paper` | 2.82 | 3.0（图形） |
| `paper-card` on `coral` | 2.99 | 3.0（大字） |
| `mustard` on `paper` | 1.72 | 3.0（图形） |

这些是调研报告已登记的设计存量问题；P0 不碰样式，所以放进 advisory 列表持续可见。P1 修完后把它们移进 `CONTRAST_PAIRS` 的闸门段（`advisory=False`）。

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

- P0 **不接 CI**：`.github/workflows/ci.yml`、`tools/ci_shards*`、`src/css/` 属于另一条 CSS 拆分线，本工具只读构建后的 `static/style.css`。
- 暂不做像素级 diff（P1 再做）；当前用「截图留档 + 控件的 computed-style 精确比对」抓回归。
- `font-family` 等属性受本机字体影响；换机器首次跑请先 `--update-baseline` 生成该机基线，或后续在 CI 容器里固定字体。
- 截图是**视口截图**，不是整页长图；滚动区域只覆盖首屏，布局回归以 12 界面首屏与 computed-style 为准。
- 浏览器查找顺序：`DELECTOR_CHROME` → `%LOCALAPPDATA%\ms-playwright\chromium-*` → 系统 Chrome/Edge → `/usr/bin/chromium`。找不到时脚本直接报错，不静默降级。
