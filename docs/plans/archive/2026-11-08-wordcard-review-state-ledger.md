# 词卡抽屉「复习台账」（方案 B）实施计划

> 日期：2026-11-08　|　状态：已裁决，进入实施
> 上游：[词卡抽屉复习状态 UI 立项调研](../research/2026-11-08-wordcard-review-state-research.md)（PR #306，已合并）
> 基线：`64428d7`　|　分支：`feat/wordcard-review-ledger`　|　worktree：`D:\Code\DeLector-ledger`
> 一句话：**读侧**按 lemma 去重后取一张卡，在抽屉里用一行等宽文本排版既有列；不改写入路径、不加 UNIQUE、不造状态。

---

## 1. 范围与非目标

**做**

1. 新增一个只读端点，按 `lemma` 返回一张「代表卡」的既有复习列 + 该 lemma 的卡数。
2. 抽屉词卡区域新增一行等宽「复习台账」，只排版真实存在的列。
3. 补测试：去重稳定性、空态、已掌握、工作台来源、契约不漂移、前端接线。
4. 真实浏览器验证：高度、393/360 宽度、对比度实算。

**不做**

- 不新增 UNIQUE 约束、不改 `POST /api/cards/vocab` 写入路径（裸 INSERT 作为已知问题记录，见 §7）。
- 不改 `GET /api/cards/vocab?scope=reader` 的 12 字段契约（理由见 §3）。
- 不做四态（New/Learning/Review/Relearning）、不做间隔预览、不做评分按钮、不做「上次评分」。
- 不新增可点击元素；台账是纯展示行（因此不触发 44px 命中区约束）。
- 不改 `isWorkbenchSourced` 的位置（探针按源码切片，见 §5.2）。

---

## 2. 数据事实（复述，用于锁定取数口径）

`vocab_cards` 真实列 `[S]` [schema.py:170-197](file:///d:/Code/DeLector/delector/core/db/schema.py#L170-L197)：
`mastered` / `mastered_at` / `correct_count` / `wrong_count` / `due_date` / `interval_days` / `ease_factor` / `repetition_count` / `fsrs_s` / `fsrs_d` / `fsrs_lapses` / `created_at`。

两条写入路径量纲不同，台账必须显式区分：

- 卡盒 DSR：`due_date = 复习当天 + 新 interval_days` `[S]` [cards.py:117-118](file:///d:/Code/DeLector/delector/routes/cards.py#L117-L118)。
- 背词工作台：只投影 `fsrs_s/d/lapses`，**不写** `due_date` / 正误计数 `[S]` [vocab_pool.py:123-145](file:///d:/Code/DeLector/delector/core/vocab_pool.py#L123-L145)。

---

## 3. 数据通路裁决：新增专用只读端点

**结论：新增 `GET /api/cards/vocab/ledger/{lemma}`，不动两个既有契约。**

理由：

1. **扩 12 字段契约会直接踩既有断言。** `tests/test_vocab_contract_uniform.py:87` 与 reader 分支的 `:442`、`:467` 都是 `set(w.keys()) == CONTRACT_FIELDS`。按「不放松断言」的规矩，这条路要么改断言（禁止），要么给 reader 分支开特例（破坏统一契约的本意）。两者都不做。
2. **不塞进 `POST /api/lookup/vocab`。** 该端点承担三级查词与 AI 兜底，混入本地卡片状态会让「查词」与「取卡」两个关切耦合，且它已有 `source` 等字段语义，容易被误解为卡片来源。
3. 新端点字段少、可单独测试、不会让工作台消费 `scope=reader` 时多收无用字段。

**契约（新端点）**

```json
{
  "lemma": "gehen",
  "card_count": 2,
  "card": {
    "id": 42,
    "mastered": false,
    "due_date": "2026-11-12",
    "interval_days": 4,
    "repetition_count": 3,
    "correct_count": 3,
    "wrong_count": 1,
    "fsrs_s": null,
    "is_workbench": false
  }
}
```

- 无卡时 `{"lemma": "...", "card_count": 0, "card": null}`（HTTP 200，空态不是 404）。
- `is_workbench` 由 SQL 判定（`COALESCE(fsrs_s,0) > 0`），语义与 `known-lemmas` `[S]` [cards.py:290](file:///d:/Code/DeLector/delector/routes/cards.py#L290) 及 `cards.js` 的 `isWorkbenchSourced` `[S]` [cards.js:203-206](file:///d:/Code/DeLector/static/js/cards.js#L203-L206) 一致。**前端不再复制数值阈值**，避免 `reader.js → cards.js` 形成被 `test_cards_and_a1_no_circular_dependency` 拦下的环。
- 只返回既有列，不做任何派生状态词；状态词由前端从 `mastered` / `due_date` / `is_workbench` 组合。
- **lemma 走路径参数而非 query**：前端网络层闸门 `tools/check_frontend_layers.py` 要求 `api()` 路径可静态归一并与后端路由对账，query 串无法折算（`/ledger?lemma={}` ≠ `/ledger/{lemma}`）。前端传 `encodeURIComponent(lemma)`；全空白 lemma 在 `rd-api.js` 直接返回空态，不发起请求。

---

## 4. 去重取数规则（确定性）

### 4.1 匹配键

按 `vocab_cards.lemma = ?` **精确匹配**。抽屉与存卡同源于 `token.lemma` `[S]` [reader.js:439-443](file:///d:/Code/DeLector/static/js/reader.js#L439-L443)、[reader.js:853-863](file:///d:/Code/DeLector/static/js/reader.js#L853-L863)，因此精确匹配与写入侧同源。

不做 `LOWER()` / `COLLATE NOCASE`：SQLite 的大小写折叠只覆盖 ASCII，对 `Ä/Ö/Ü/ß` 失效，会形成「部分折叠」的隐性不一致。legacy 空 lemma 卡不匹配（`lemma TEXT NOT NULL` 允许空串），这是已知边界，不在此轮修数据。

### 4.2 代表卡选取

```sql
WITH ranked AS (
  SELECT
    id, mastered, due_date, interval_days, repetition_count,
    correct_count, wrong_count, fsrs_s, created_at,
    CASE
      WHEN mastered = 1 AND mastered_at IS NOT NULL AND mastered_at <> ''
        THEN substr(mastered_at, 1, 10)
      WHEN due_date IS NOT NULL AND due_date <> ''
       AND interval_days IS NOT NULL AND interval_days > 0
        THEN date(due_date, '-' || CAST(interval_days AS TEXT) || ' days')
      ELSE NULL
    END AS last_signal_day
  FROM vocab_cards
  WHERE lemma = ?
)
SELECT *, COUNT(*) OVER () AS card_count
FROM ranked
ORDER BY last_signal_day DESC, created_at DESC, id DESC
LIMIT 1;
```

**为什么是这个顺序**

1. `last_signal_day DESC` —— 「最近一次用户动作」最新的一张。它由两段真实时间戳合成：
   - 手动「已掌握」日 = `mastered_at` 的日期部分（显式裁决）；
   - 最近复习日 = `date(due_date, '-interval_days days')`。这不是拍脑袋的近似，而是写入公式 `due_date = 复习日 + interval_days` `[S]` [cards.py:117-118](file:///d:/Code/DeLector/delector/routes/cards.py#L117-L118) 的**精确逆运算**（`due_date` 与 `interval_days` 同一次写回）。
   - SQLite 的 `DESC` 把 NULL 排在最后 ⇒ 从未复习、也未掌握的新卡不会盖过有真实动作的卡。
2. `created_at DESC` —— 同一天动作（或都无动作）时取用户**最近创建**的那张；这正是用户加卡顺序的自然倒序。
3. `id DESC` —— `created_at` 精度到秒，同一秒内可能相同；`id` 自增提供**完全确定**的最终裁决，杜绝依赖扫描顺序。

`COUNT(*) OVER ()` 是同一 CTE 上的聚合，一次查询同时给出「代表卡」与「卡数」，不做 N+1。

**不采用**：把候选卡数组交给前端 `[0]`。那等于让 SQLite 的隐式扫描顺序决定状态，索引/计划一变就漂移，且无法测试「同一输入永远同一行」。

### 4.3 台账是否标「该词有 N 张卡」

**决定：标，用文字 `共 N 张`（仅 `card_count > 1` 时出现），不加图标、不用颜色。**

取舍：

- 好处：重复卡是真实存在的数据缺陷，且两张卡的状态可能不同。只显示一张而不声明，用户会以为看到的是「这个词」的唯一状态；标出卡数是对「我们取了一张代表卡」的诚实披露，也让「为什么这里的到期日和卡盒里另一张不同」可被解释。
- 代价：多占约 5 个字符宽度，并可能引出「我该怎么删」的疑问——但抽屉本来就不是清理重复卡的地方，这个疑问会被带到卡盒页解决，路径合理。
- 为什么不直接不显示：静默隐藏会让台账看起来比数据实际更确定，违反本项目「不编造/不静默降级」的既有纪律。
- 文案用 `共 2 张` 而不是 `×2`：后者对屏幕阅读器是无语义符号，前者本身即完整语义（ADR-0029 I1）。

---

## 5. 展示规格

### 5.1 位置与结构

抽屉词卡内、`#d-meta` 之后插入：

```html
<div id="d-ledger" class="wordcard-ledger" hidden></div>
```

- 无卡（`card_count == 0`）时**整行隐藏**。不在每次查词都显示「未入卡」：保存按钮的文案已经表达该状态，常驻一行空态是噪音，也会让每次查词多出 24px。
- 加载中同样隐藏（不显示骨架），失败隐藏（不写假数据）。

### 5.2 列、列序、单位与缩写

单行、等宽、`·`（**无空格**）分隔，段序固定：

| # | 段 | 取值 | 空值规则 |
| --- | --- | --- | --- |
| 1 | 状态词 | `已掌握`（`mastered`）/ `待复习`（有 `due_date`）/ `未排期`（其余） | 永不省略 |
| 2 | `到期MM-DD` | `due_date`；若年份 ≠ 当前年则 `到期YYYY-MM-DD` | 无 `due_date` ⇒ 省略整段 |
| 3 | `间隔Nd` | `interval_days`，`N` 为整数天 | 仅当 `due_date` 存在且 `interval_days > 0`；否则省略（默认值 1 不代表真实排期，不能显示） |
| 4 | `N正/M误` | `correct_count` / `wrong_count` | 工作台来源 ⇒ 改为 `工作台 s=X.Xd`；两者都为 0 ⇒ 省略（不出现 `0正/0误`） |
| 5 | `共N张` | `card_count` | 仅 `> 1` 时出现 |

示例（真实数据形态）：

- 卡盒复习过：`待复习·到期11-12·间隔4d·3正/1误`
- 已掌握且无排期：`已掌握`
- 工作台来源：`未排期·工作台 s=4.2d`
- 重复卡：`待复习·到期11-12·间隔4d·2正/0误·共2张`

单位与缩写口径：

- `d` = 天（Anki 既有缩写）；`s` = FSRS 稳定性（天），**不写「次/复习/轮」**，避免与 `repetition_count` 混量纲。
- `s` 保留 1 位小数（与 `cardStatsTag` 的 `toFixed(1)` 一致）`[S]` [cards.js:244](file:///d:/Code/DeLector/static/js/cards.js#L244)。
- 到期日只给 `MM-DD`，跨年才补年份：抽屉是**读词时瞥一眼**的场景，年份是噪音；跨年时省略年份会造成歧义，故补全。

### 5.3 视觉与无障碍

- 字体 `var(--mono)`、`0.6875rem`（11px）、`line-height: 1.45`（≈16px）、`font-variant-numeric: tabular-nums`。
- 行盒：`padding: 4px 0 4px 8px` + `border-left: 2px solid currentColor` ⇒ **24px 高**（目标 24–28px；Edge 实测 `offsetHeight=24`）。
- 前景 `var(--ink-mute)` `#5a5448`：on `#ffffff` 实算 **7.51:1**，on `#fffbe6` **7.22:1**，均 ≥4.5（正文）。边框同色 ⇒ 非文本 **7.51:1**，≥3.0。浏览器实测前景 `rgb(90, 84, 72)`、边框 `rgb(90, 84, 72)`、背景 `rgb(255, 255, 255)`，与手算一致。
- **边框不得用 `var(--line)`**（叠白底 1.43:1，低于 SC 1.4.11）。
- 状态语义由**文本**承载；颜色不承担任何区分职责。不新增图标，不用字形当唯一载体（ADR-0029 I1）。
- 纯展示、不可点 ⇒ 不涉及 44px 命中区；不加 `tabindex`、不加 role，避免伪造控件语义。
- 换行策略：`white-space: normal`。实测文本宽度：带空格写法 325.6px（在 393/360 会折行），**无空格写法 220px**，在 1440 / 393（内容宽 295px）/ 360（内容宽 262px）下均为单行 24px。Edge 实测 393/360 下 `rowScrollWidth == rowClientWidth`、`drawerScrollWidth == drawerClientWidth`，无横向溢出。极端组合（跨年到期 + 重复卡，文本约 264px）在 360 下允许折成两行而**不溢出**。`white-space: nowrap` + `ellipsis` 会藏掉信息，不采用。

### 5.4 分隔符与间距（实测依据）

`·` 两侧不加空格、标签与数值紧贴（`到期11-12` / `间隔4d` / `3正/1误` / `共2张`）。这不是审美偏好：带空格写法实测 325.6px，在 393px 抽屉（内容宽 295px）就会折行到 40px 高，直接违反 24–28px 的单行目标；无空格写法 220px，三个断点都稳。

---

## 6. 实现清单

### 6.1 后端 `delector/routes/cards.py`

- 新增 `GET /api/cards/vocab/ledger/{lemma}`（放在 `known-lemmas` 附近）。
- `lemma` 路径参数；strip 后为空直接返回空态。
- 用 §4.2 的单条 SQL；返回 §3 的契约。
- 不写任何表；不调用 `log_study_event`。

### 6.2 前端

- `static/js/rd-api.js`：`fetchVocabLedger(lemma)` → `GET /api/cards/vocab/ledger/{encodeURIComponent(lemma)}`；全空白直接返回本地空态（不请求）。
- `static/js/reader.js`：
  - `inspect()` 开头清空并隐藏 `#d-ledger`；
  - 查词并发请求台账（不阻塞查词）；响应只在 `state.selectedToken?.text === token.text` 时落地，照抄既有竞态守卫 `[S]` [reader.js:445](file:///d:/Code/DeLector/static/js/reader.js#L445)；
  - `saveVocab()` 成功后重取一次台账（让「刚入卡」立刻出现）；
  - 新增 `renderVocabLedger` / `clearVocabLedger`（纯文本拼装，`textContent`，无 `innerHTML`）。
- `static/modals/drawer.html`：插入 `#d-ledger`，随后跑 `python tools/build_index_html.py` 重新生成 `static/index.html`。
- `src/css/04-drawer-wordcard.css`：追加 `.wordcard-ledger` 规则（紧邻 `#d-meta` 区域）。**不直接改 `static/style.css`**；改完跑 `python tools/build_css.py` 与 `python tools/check_css_sync.py --check`。

### 6.3 测试

新增 `tests/test_wordcard_ledger.py`（后端 + 前端接线断言）：

1. **空态**：无卡 → `card_count == 0`、`card is None`。
2. **确定性去重**：同一 lemma 插入 3 张卡（不同 `due_date`/`interval_days`/`created_at`/`id`），断言选中「最近动作」那张；再以不同插入顺序重建同数据，断言结果逐字段一致（证明不依赖扫描顺序）。
3. **并列**：`last_signal_day` 相同 → 取 `created_at` 最新；`created_at` 相同 → 取 `id` 最大。
4. **已掌握**：`mastered=1` + `mastered_at` 参与 `last_signal_day`；`mastered` 透传。
5. **工作台来源**：`fsrs_s=4.2` → `is_workbench == true`；`fsrs_s=0`/NULL → `false`。
6. **契约不漂移**：既有 `tests/test_vocab_contract_uniform.py` 原样通过（不修改任何断言）。
7. **前端接线**：`drawer.html` / `index.html` 含 `#d-ledger`；`reader.js` 引用新端点且使用 `textContent`；CSS 中 `.wordcard-ledger` 的边框为 `currentColor` 且不含 `var(--line)`。

### 6.4 验证

- `pytest tests/test_wordcard_ledger.py tests/test_vocab_contract_uniform.py tests/test_server_cards_vocab.py tests/test_frontend_module_graph.py`
- `python tools/build_css.py` + `python tools/check_css_sync.py --check` + `python tools/build_index_html.py --check`
- 起服务，造 4 类真实数据（卡盒 / 已掌握 / 工作台 / 重复），浏览器实测：
  - 台账行 `offsetHeight`（目标 24–28px）；
  - 393px / 360px 视口下无横向溢出（`scrollWidth <= clientWidth`）；
  - 计算样式取实际前景/背景，实算对比度 ≥4.5；
  - 边框颜色 == 文本色（`currentColor` 生效）。

---

## 7. 已知问题（记录，不在本轮修）

1. **裸 INSERT 无唯一约束**：`POST /api/cards/vocab` 直接插入，`word`/`lemma` 无 UNIQUE，重复卡由写路径真实产生 `[S]` [cards.py:186-206](file:///d:/Code/DeLector/delector/routes/cards.py#L186-L206)、[cards.js:1229-1230](file:///d:/Code/DeLector/static/js/cards.js#L1229-L1230)。本轮只在读侧去重，**不补约束、不改写入路径**——补约束需要先有去重迁移与用户可见的合并策略，属于独立立项。
2. **两套调度并存**：卡盒 DSR 与工作台 FSRS 各自写列；台账用 `is_workbench` 显式区分，不跨系统混算。`fsrs_s` 与 `repetition_count` 量纲不同，任何文案不得互换。
3. **legacy `lemma` 为空串**的卡不参与匹配；不做模糊回退，避免匹配到错误的词。
4. **`last_signal_day` 依赖 `due_date` 与 `interval_days` 的同次写回**；若未来有外部工具只改其中一个，摘要会偏一天。当前唯一写入者满足该前提 `[S]` [cards.py:388-449](file:///d:/Code/DeLector/delector/routes/cards.py#L388-L449)。

---

## 8. 验收清单

- [ ] 同一 lemma 多卡只出一行，且重复请求结果逐字段一致。
- [ ] 空态整行隐藏；已掌握 / 工作台 / 重复卡文案符合 §5.2。
- [ ] 12 字段契约测试未改动且全绿。
- [ ] CSS 走 `src/css/` 拼接，`check_css_sync` 通过。
- [ ] 实测量到行高 24–28px，393/360 无溢出，对比度 ≥4.5，边框 = `currentColor`。
- [ ] PR 打开不自动合并；CI 逐 job 按真实 conclusion 核验。
