# 全站视觉换皮：组件族收口记录

> 日期：2026-11-08 · 范围：P2 组件族五族 · 基线：`origin/master` `a012aeb` → `00b6e58`
> 关联文档：[调研与结构解耦评估](2026-11-08-full-site-visual-reskin-research.md)、[设计系统规范](../design-system.md)、[视觉回归基线](../agents/visual-regression.md)、[ADR-0029](../adr/2026-11-06-adr-0029-frontend-de-emoji-and-editorial-rhythm.md)、[ADR-0030](../adr/2026-11-07-adr-0030-frontend-motion-system.md)
> 本文只记录「做完了什么、刻意没做什么、还剩什么」，不复述 token 值与过程流水；规范条款见 `docs/design-system.md`。

## 0. 结论先行

五族全部合入 `master`，未改任何闸门阈值、未做 IA 重排、未动 `android/`。当前 `00b6e58` 上 `python tools/visual_gates.py` 实跑：

| 闸门 | 当前值 | 预算/口径 |
|---|---|---|
| hex 字面量（`:root` 规则体外） | **505** | ≤ 700 |
| 唯一 rgba/rgb | **99** | ≤ 150 |
| `infinite` 循环动画 | **7** | == 7（白名单，见 ADR-0030 §2.6） |
| 闸内最低对比度 | **4.63** | 正文 ≥ 4.5 / 大字与图形 ≥ 3.0 |
| `--mustard` 文字承载 | **0** | == 0 |

P2 五族合计消耗 **hex −61 / rgba −16**（566→505、115→99）。各轮终值取自 `WORKMEMORY/work.log` 对应 WORK_END，最终值在 `00b6e58` 上复跑确认。

## 1. 五族总表

| 族 | PR | merge commit | 主要文件 | hex | rgba | 静态矩阵信号 |
|---|---|---|---|---|---|---|
| 阅读器 + 词卡 | #298 | `16a00fd` | `src/css/03-reader.css`、`04-drawer-wordcard.css`、`static/js/reader.js`、computed 基线 | 566 → **550**（−16） | 115 → **109**（−6） | reader 3 档 + drawer 3 档 |
| 卡盒 + 闪卡 | #299 | `c2d1422` | `src/css/05-cards-player.css`、`06-deck-exam.css`、`07-progress-quiz.css`、`static/js/cards.js`、作答探针 | 550 → **528**（−22） | 109 → **108**（−1） | 静态矩阵 **0**（改动在交互态） |
| 备考 | #300 | `b9563e8` | `src/css/06-deck-exam.css`（exam 区）、`static/js/hard-sentences.js`、`listen-lab.js` 内联样式 | 528 → **528**（0） | 108 → **108**（0） | exam 393/360/1280 |
| 设置 | #301 | `82e2650` | `src/css/08-settings-writer.css`（设置段）、`09-a1-encounter-companion-overrides.css`、`static/js/main.js` | 528 → **519**（−9） | 108 → **108**（0） | settings 393/360/1280 |
| 写作 | #302 | `00b6e58` | `src/css/08-settings-writer.css`（writer 段）、`09-...css`（触控命中块） | 519 → **505**（−14） | 108 → **99**（−9） | writer 393/360 |

> 每族的完整矩阵、computed 基线漂移与噪声对照见 `WORKMEMORY/work.log` 2026-11-08 各轮 WORK_END；本文不重复 36 张截图明细。

## 2. 阅读器 + 词卡（#298）

**动了哪些文件**
- `src/css/03-reader.css`：选中词元提到 ID 级选择器 `#reader-content .tok.sel`；反白之外补 2px 纸色下划线（形状线索）。
- `src/css/04-drawer-wordcard.css`：已收录按钮 `#save-vocab-btn.is-saved` 改为 2px `outline` + `outline-offset: 2px` + `✓` 前缀 + 700 字重。
- `static/js/reader.js`：切换词条时移除 `is-saved`，保存成功后补 `is-saved`，避免上一词条的已收录态粘到下一词条。
- `tests/fixtures/visual/computed_style_baseline.json`：仅 `tok-selected` 4 项随选择器与下划线更新。

**解决了什么**
- `.tok.sel` 原规则与 `05-cards-player.css` 的 `.tok.reading-active` 同特异性、后者片序在后且同为 `!important`，选中态长期被静默压过；源码看起来完全正确，只有 computed/交互探针能发现。
- 已收录态原来只靠底色，色觉障碍或灰度下与普通按钮不可分；现在「形状（外框）+ 图标（✓）+ 字重」三通道。
- 词卡抽屉的材质/阴影收敛到 `--paper-*` / `--elevation-*`，规则体不再写阴影 rgba。

**刻意不做**
- **阅读指标不动**（正文行高、行宽、字号、段间距全部保持现状）。原因：ADR-0029 §16.2.1 已判定「section/content = 4.0」是合成目标值、从未落在像素上；T9 实测 70 字符/行、1.85 sans / 1.95 serif 已合格。换皮轮没有新的像素判据，改动只会重开排印欠账。
- **不给正文加任何入场/位移/呼吸**（ADR-0030 §2.5 阅读面零位移）。
- 不新增抽屉里的复习状态入口——那是 IA，不是换皮。

**遗留**
- `.tok.reading-active` 仍是独立规则；未来若再改选中态，必须继续保持 ID 级选择器或调整片序，否则会再次被压。
- 抽屉/卡盒的横向滚动容器会裁掉外扩 focus ring；本轮用 `outline-offset: -2px` 内缩规避，未改容器结构。

## 3. 卡盒 + 闪卡（#299）

**动了哪些文件**
- `src/css/05-cards-player.css`、`06-deck-exam.css`（卡控/牌盒/已掌握区）、`07-progress-quiz.css`（测验/闪卡区）。
- `static/js/cards.js`：内联 `onclick="submitChoice(...)"` 改为已暴露的 `selectChoiceOption`。
- `tools/cards_quiz_choice_probe.mjs` + `tests/test_cards_quiz_choice_probe.py`：作答探针同步桥名。

**解决了什么**
- 卡面/背面/已掌握底/删除 hover/掌握按钮文字/闪卡/听写/选项/正误底色全部换成语义 token。
- 掌握态不再只靠绿色：`↺ 重返待复习` 文案 + 3px 苔绿左轨 + `opacity: .75`；按钮同时变 moss 底/纸字。
- 选项正误：`✓ / ✗` 图标 + 700 字重 + 1px 语义边框，颜色只作冗余。
- 修复「代码看着在、其实没接线」：`submitChoice` 在 ES module 作用域里不存在，`main.js` 只暴露了 `window.selectChoiceOption`；点击抛 `ReferenceError`，正误样式从未生效且无报错。

**刻意不做**
- 06 的 exam 区（121–490 行）留给下一族；不碰 08 设置/写作、`android/`、闸门阈值。
- 不把静态矩阵扩到交互态：本族改动集中在 hover/掌握/作答，静态 36 张矩阵信号为 0，改用 CDP 定向探针验收。
- 保留 2 处材质例外：ink 底计数薄纱 `rgba(255,255,255,.2)`、测验遮罩 `rgba(246,245,240,.96)`——没有语义等价的 token，硬造一个反而增加维护面。

**遗留**
- 上述 2 处 rgba 例外仍在预算内，但属于「已知未 token 化」。
- `check_frontend_api_contract.py` / `check_silent_degradation.py` 只扫 Python，覆盖不到「内联 onclick 取不到 module 作用域」这类死绑定；本族靠探针补，未新增静态闸。

## 4. 备考（#300）

**动了哪些文件**
- `src/css/06-deck-exam.css`：七模块单列目录、激活态序号、计数、模块内入口页签、模块内空态。
- `static/js/hard-sentences.js` / `listen-lab.js`：两处 `_ensureStyle()` 内联样式给空态补 3px 左线（这两处样式本来就不在 CSS 源里，属于 JS 内联样式盲区）。

**解决了什么**
- 新增 `.exam-panel-tabs` / `.exam-panel-tab`：原类名在 JS 里被切、CSS 全仓零规则，浏览器默认按钮 + `.active` 不可见。新规则 token-only，44px 命中区、2px 珊瑚底线 + 700 字重，与目录的编辑式语言一致。
- 激活态序号补 700；计数加 1px 账线 + `tabular-nums`；`.listen-empty` / `.hs-empty` 补 3px 左线。
- 1280 实测页签高 24→44px、计数宽 34.6→45.6px；393/360 横向溢出 0，页签在 353/320px 容器内单行不折。

**刻意不做**
- **不修审计出的 16 个存量零规则类**：本轮只补本族范围（`.exam-panel-tab`），其余留作下一轮，避免把「换皮」扩大成「全站类名审计」。
- 不做 IA 重排、不动 cards/quiz、不动闸门阈值。
- 2 个 C 桶（真缺样式）本轮**只记录不修**：`.has-hint`（cloze 首字母提示无视觉标记）、`.companion-resume-notice`（断点恢复提示与正文同形）。

**遗留**
- `.has-hint`、`.companion-resume-notice`。
- 16 个零规则类里除这 2 个外均为纯 hook 或由 co-class/内联承担，已分类归档在 `WORKMEMORY/work.log` PITFALL 条。

## 5. 设置（#301）

**动了哪些文件**
- `src/css/08-settings-writer.css`（设置段 1–199）：模态容器/头部/分组/说明文字/preset chip/动作区。
- `src/css/09-a1-encounter-companion-overrides.css`：reasoning 分区（分段控件与状态行）。
- `static/js/main.js`：三处内联 hex 改 `data-state`（`#16a34a`、`#ca8a04`、`#dc2626`）。
- computed 基线：仅 `settings-input.height` 43→44px。

**解决了什么**
- 命中区（393 实测）：关闭 26×26→44×44（补 `flex: 0 0 auto` 防挤压）、`.btn` 36→44、密钥显隐 44×43→44×44、preset 20→44、分段 ≤420px 42→44、输入 43→44；360 同；横向溢出 0。
- 状态非颜色：字段/反馈/推理状态行加 2px 左竖线 + `data-state`（warn=accent / ok=moss / pending=pencil），文字本身带语义；分段 `aria-checked` + 600 + 2px 珊瑚底线；禁用态 2px dashed pencil 外框 + 去 sticker 阴影 + `not-allowed`。
- 内联 hex 改 `data-state` 后顺带修对比度：`#ca8a04` 2.77→4.63、`#16a34a` 3.11→5.68、`#dc2626`→4.63。
- 补 `.settings-modal-box .hint-text`：静态 `.hint-text` 在设置内零规则，16px 正文压过 12px 说明。

**刻意不做**
- **不新增 on/off 开关**：设置模态里真实不存在开关控件。为换皮凭空加开关是新增 IA 与功能，不是换皮。
- **不新增危险操作区**：唯一的「还原备份」在卡盒页，不在设置；把危险操作搬进设置会改变信息架构与误触面。
- 只按真实存在的控件（折叠行、分段、状态行、禁用态）落实非颜色状态。
- 不碰 08 的 companion 段（200–943）与 writer 段（下一族），不做 IA 重排。

**遗留**
- 分段控件在 ≤420px 的 42→44px 依赖断点内规则；未来若加减分段项，需要复验横向溢出。
- `main.js` 仍可能有其它内联颜色未纳入 `data-state`；本轮只改设置三条。

## 6. 写作（#302）

**动了哪些文件**
- `src/css/08-settings-writer.css`（writer 段 1037+）：容器/头部/标题/动作区/左栏/侧栏/卡片/输入/IDE/inlay/句导航/工具栏/诊断框/句块/错误下划线/CEFR 详情/AI 笔记/作文历史/响应式。
- `src/css/09-a1-encounter-companion-overrides.css`：仅 `.writer-actions-top .btn::after` 触控命中块。

**解决了什么**
- 命中区：393 第一行 42→44px（4 个按钮全部），行 2 命中顶边 220.06→224.06，行 1 底边 226.06→224.06，重叠 6→0（相切）；360 同样 42→44，2 对重叠→0；1280 单行无触控伪元素，0 变化。
- 布局：行距 6→8px，动作区 78→80px，header 171.06→173.06，编辑区 y 528.44→530.44，首屏可见 160 不变，横向溢出 0。
- 状态非颜色：状态 pill 实线 ✓ / 虚线 !；句导航徽章方角 ! / 圆角 ✓；问题徽章实线 / 虚线；作文正误条方角虚线 ! / 圆角实线 ✓；输入框与 IDE 聚焦 2px outline；四类错误下划线实线 / 虚线 / 点线 / 波浪。
- 审计 writer.js 14 个 `classList` 切换类名，CSS 源全集零缺失（无 C 桶）。

**刻意不做**
- **不做全面 IA 重排**：只换视觉材质与状态表达，侧栏/工具栏/诊断框的位置与层级不动。
- **不改写作正文行高/字号**：阅读面同 ADR-0030「零位移、不重排」；本轮唯一布局改动是热区行距 6→8px。
- 不碰设置段、卡盒/闪卡/阅读器/词卡/备考、`android/`、闸门阈值。
- 1280 单行不补触控伪元素——没有相邻行重叠问题，补了只会扩大误触面。

**遗留**
- writer 动作区不在 computed 基线控件集内，本轮用定向探针验收；未来若加按钮，需要同时更新探针或基线。
- 四类错误线型目前靠 `text-decoration-style`，打印/强制颜色模式下可能退化为同一线型；本轮未做 forced-colors 验证。

## 7. 跨族遗留清单

| 项 | 状态 | 说明 |
|---|---|---|
| `.has-hint` 真缺样式 | 未修 | cloze 首字母提示无任何视觉标记；C 桶 |
| `.companion-resume-notice` 真缺样式 | 未修 | 断点恢复提示与正文同形；C 桶 |
| 其余 14 个零规则类 | 已分类 | 纯 hook 或由内联/co-class/子节点承担，无需补规则 |
| 2 处材质 rgba 例外 | 保留 | `rgba(255,255,255,.2)`、`rgba(246,245,240,.96)`，无同义 token |
| 视觉矩阵只覆盖首屏 | 保留 | 视口截图，非整页长图；滚动区域回归不在矩阵内 |
| 假差异噪声源 | 已识别 | 随机格言、音频缓存体积、猫头鹰眨眼、滚动位移；判回归前先同源数据 + 同代码复跑 |
| workbench token 镜像 | 持续约束 | 新 token 必须在 `src/css/01-tokens-base.css` 与 `static/css/tokens.css` 两处 `:root` 同时定义 |

## 8. 验收口径与数字来源

- **实跑（2026-11-08，`00b6e58`）**：`python tools/visual_gates.py` → 505 hex / 99 rgba / 7 infinite / 4.63 最低对比 / mustard 0；16 组闸内对比全部 PASS，`mustard-on-paper` 仅装饰不参与判定。
- **各轮终值**：阅读器 550/109、卡盒 528/108、备考 528/108、设置 519/108、写作 505/99，均取自 `WORKMEMORY/work.log` 对应 WORK_END，且各轮 `build_css` + `check_css_sync` PASS。
- **未实跑/待回填**：本记录没有重新跑五族各自的 36 张截图矩阵；矩阵信号与噪声比例引用各轮 WORK_END 记录，未在 `00b6e58` 上复跑。若需要「合并后一次性全站矩阵」，应在代码线收口后单独执行并回填本节。
- **触控命中数字**：42→44px、6→0 重叠、行距 6→8px 均来自写作族 393/360 的 CDP 实测（WORK_END 2026-11-08 18:31）。
