# 词卡抽屉「复习状态」UI 立项调研

> 日期：2026-11-08　|　性质：**只读调研**（未改 `static/`、未改 `delector/`、未改测试与配置）
> 基线：`origin/master` `85cf99e`（本地主工作树 `c2e9e60` 落后于远端，本轮从远端拉分支）
> 产出分支：`docs/wordcard-review-state-research`，独立 worktree `D:\Code\DeLector-reviewstate`
> 证据标记：`[S]` 本仓源码静态核对（file:line）｜`[B]` 官方文档/规范页面｜`[T]` 数值推导（WCAG 对比度）｜`[U]` 未验证
> 外部调研说明：**没有做真实 App 截图**（Anki/Quizlet 等需客户端或登录）。外部证据是「官方文档页面实测读取 + 原文引文」，视觉样式细节未实测的项一律标 `[U]`。

---

## 0. 结论先行

1. **数据层不是空白，但抽屉链路是断的。** `vocab_cards` 已有 `mastered / mastered_at / correct_count / wrong_count / due_date / interval_days / ease_factor / repetition_count / fsrs_s / fsrs_d / fsrs_lapses` 共 11 个复习相关列 `[S]`。但抽屉打开时只调 `POST /api/lookup/vocab`，该响应**不包含任何卡片状态**；而 `GET /api/cards/vocab?scope=reader` 走的 12 字段契约把复习列全部裁掉 `[S]`。结论是「已有数据，但抽屉当前取不到」。
2. **三样东西确实完全不存在**：① 显式的 SRS 四态字段（New/Learning/Review/Relearning）；② 卡片上的「上次复习时间」列；③ 原始评分 1–4 的持久化——`quiz_log` 只存 `correct` 0/1，`grade` 在写入时被折叠 `[S]`。FSRS 的 retrievability 只在计算函数里瞬时算出，不落库、不返回 `[S]`。
3. **抽屉现在连「这个词是否已入卡」都不显示。** `#save-vocab-btn` 只在本次点击后进入 `is-saved`，重新点词又复位成「+ 加入 Anki 词汇卡」`[S]`。这是比「复习状态」更前置的缺口。
4. **外部做法高度一致：小空间里用「文本标签 + 缩写数值 + 位置/括号」承载状态，没有一家官方文档把纯色块当状态语义。** Anki 用 `Due` / `Interval` 两列与 `4d` 这类缩写；RemNote 用 `6 Due` 文本徽标；Quizlet 把「多久回来」写成短句 `[B]`。Material 3 的 chips 是**交互件**，且规范明确禁止单枚出现 `[B]`。
5. **推荐方案 B（单行等宽「复习台账」）**，前置是补一个只读状态查询与「一词多卡」匹配口径。不建议现在做 C（四态章 + 四档间隔预览）：它需要先补数据层，否则只能画一个假状态条。
6. **必须先裁决「同一 lemma 有多张卡时显示哪张」**。`vocab_cards` 的 `word`/`lemma` 没有 UNIQUE，代码注释也明说重复不会被拦 `[S]`。这个口径不先定，状态 UI 会指错卡。

---

## 1. 外部调研：头部产品怎么表达「这个词的复习状态」

### 1.1 间隔重复类产品

| 产品 | 状态词（原文） | 在卡片详情/小空间的写法 | 证据 | 能否借进我们的语汇 |
| --- | --- | --- | --- | --- |
| **Anki** | New / Learning / Review / Relearn；Review 再分 Young（<21 天）与 Mature（≥21 天） | 浏览器用 `Due`（到期日/新卡位次）+ `Interval`（间隔）两列**纯文本**；暂停/埋藏用**括号包日期**；Card Info 用 `4d`、`5mo` 这类缩写 | [B] [Card States](https://docs.ankiweb.net/getting-started.html#card-states)、[Browsing](https://docs.ankiweb.net/browsing.html#columns)、[Stats](https://docs.ankiweb.net/stats.html#card-info) | **可借鉴**：标签 + 缩写数值 + 位置编码，天然适合窄抽屉 |
| **SuperMemo / SM-2** | interval（间隔天数）、E-Factor（易度 1.3–2.5）、next repetition | 官方文档**未覆盖 UI**，只定义 `I(1)=1`、`I(2)=6`、`I(n)=I(n-1)*EF` | [B] [Wozniak 1990 原文](https://www.supermemo.com/en/blog/application-of-a-computer-to-improve-the-results-obtained-in-working-with-the-supermemo-method) | 借概念不借皮：我们已有 `interval_days` / `ease_factor` |
| **RemNote** | Due / Due Reviews / practice queue / cards left | 右上角 `6 Due` 文本徽标；队列顶部 `13 cards left`；**数字 + 名词**，无颜色语义 | [B] [Getting Started with Spaced Repetition](https://help.remnote.com/en/articles/6022755-getting-started-with-spaced-repetition) | **可借鉴**：计数徽标可放词头行 |
| **Mochi** | New / Learned / Archived / Due today / re-review | 官方文档说明状态分组与 Due today 队列，**详情页样式未覆盖** `[U]` | [B] [Reviewing](https://www.mochi.cards/docs/reviewing/) | 借状态词表，不借视觉 |
| **Quizlet** | New / Not Studied / Still Learning / Mastered；评分 Repeat / Hard / Okay / Easy | 评分按钮旁写**具体返回时间**（“within minutes / about a day / four or more days”）；Progress 用三个分组名做筛选入口 | [B] [Spaced Repetition](https://help.quizlet.com/hc/en-us/articles/48324742264077-Studying-with-Spaced-Repetition)、[Progress](https://help.quizlet.com/hc/en-us/articles/360048803491-Using-Progress-for-targeted-studying) | **可借鉴**：「下次什么时候回来」比抽象等级更易懂 |
| **Memrise** | Difficult Words / marked as difficult / greyed out | 单词旁一个 ⚡ 即标记；无待练项时整个模式置灰 | [B] [Difficult Words](https://memrise.zendesk.com/hc/en-us/articles/360015887577-What-are-Difficult-Words) | **不借鉴**：图标+置灰近似「字形/颜色即状态」，撞 ADR-0029 I1 |
| **Duolingo** | strength meter / full bars / half-full / weakest words | 强度用**条数与长度（形状编码）**；满格另有金色图标；技能详情直接列最弱词 | [B] [How we learn how you learn](https://blog.duolingo.com/how-we-learn-how-you-learn/) | **部分借鉴**：形状编码不依赖颜色；但彩色条不合纸感 |

**关键原文（可直接复核）** `[B]`：

- Anki：“A mature card is one that has an interval of 21 days or greater.”
- Quizlet：“Easy — You remembered it easily. The card typically returns in four or more days.”
- Anki 的卡片状态定义把四态写成互斥语义（New / Learning / Review / Relearn），而 Relearn 是「复习阶段忘了以后回到学习态」——这说明四态不是四个装饰标签，而是一条**有方向的状态机**。

### 1.2 规范层

| 规范 | 与本议题相关的条款 | 对抽屉的具体约束 |
| --- | --- | --- |
| **Material 3 · Chips** `[B]` | Chips 是 Assist / Filter / Input / Suggestion 四型**交互件**；规范没有 status chip 这一型；「Don't display a single chip by itself. Chips should appear in a set.」；标签 ≤20 字符 | **不能**把 chip 当状态徽章。抽屉里单枚状态胶囊会同时违反语义与规范。状态用「标签 + 数值」的排版层，不用 chip 组件 |
| **Apple HIG** `[B]` | progress 分 determinate/indeterminate；文案要具体，避免 vague terms；「Avoid relying solely on color to differentiate between objects, indicate interactivity, or communicate essential information.」 | 状态必须写人话（`到期 11-12`）而不是只给一个色点；颜色只能是辅助层 |
| **WCAG 2.1 SC 1.4.1** `[B]` | 颜色不得是传达信息、指示动作、区分元素的**唯一**视觉手段 | 与 ADR-0029 I1 同向：必须叠文本或形状 |
| **WCAG 2.1 SC 1.4.11** `[B]` | 状态指示器/组件边界对相邻颜色 ≥ 3:1 | 状态章边框不能用 `--line`（见 §3.1 实测值） |

### 1.3 判断：哪些「看起来像」但不该落地

**可以借**

- Anki 的 `标签 + 缩写`：`到期 4d`、`间隔 21d`，用 `--mono` 排版，不新增组件。
- RemNote 的 `N Due` 计数：我们对应的是「今日到期 N 张」，但这是全局量，不属于单张词卡，最多放抽屉外。
- Quizlet 的「具体返回时间」：把 `due_date` 写成相对时间（今天/明天/11-12），比显示「已掌握/复习中」更有信息量。
- Duolingo 的「形状/长度编码」：如果以后要表达记忆强度，优先用**确定性刻度**（细线段数），而不是彩色进度条。

**不借**

- M3 单枚状态 chip：交互语义错位，规范也禁止单枚。
- Memrise 的 ⚡ 图标 + 置灰：字形/颜色唯一载体，直接违反 I1。
- Duolingo 的彩色强度条、大厂暖色圆角状态卡：会毁掉「纸感 + 编辑式排版」的墨线语汇。
- Anki 的四态章照搬：我们的数据里没有状态机，硬做就是假状态（见 §2.5）。

---

## 2. 代码取证：到底有哪些真实数据

### 2.1 数据层：真实持久化的列

`vocab_cards` 建表 `[S]` [schema.py:170-197](file:///d:/Code/DeLector/delector/core/db/schema.py#L170-L197)：

| 列 | 行号 | 语义 | 写入者 |
| --- | --- | --- | --- |
| `mastered` / `mastered_at` | 182-183 | 用户手动「已掌握」标记与时间 | `PATCH /api/cards/{type}/{id}/master` [cards.py:319-334](file:///d:/Code/DeLector/delector/routes/cards.py#L319-L334) |
| `correct_count` / `wrong_count` | 184-185 | DSR 复习正/误累计（**工作台词恒为 0**） | `/review` 与 `/api/quiz/record` |
| `due_date` | 186 | 下次到期日（`YYYY-MM-DD`） | `/review` 按 FSRS 计算后写回 |
| `interval_days` | 187 | 当前间隔（天） | 同上 |
| `ease_factor` | 188 | 兼容 SM-2 的易度列，现被 FSRS 当作 difficulty 用 | 同上 |
| `repetition_count` | 189 | DSR 复习次数 | 同上 |
| `fsrs_s` / `fsrs_d` / `fsrs_lapses` | 193-195 | 背词工作台的 FSRS-6 稳定性/难度/遗忘次数 | `project_wb_deck` 投影 [vocab_pool.py:123-145](file:///d:/Code/DeLector/delector/core/vocab_pool.py#L123-L145) |

`grammar_cards` 有同样的复习列，但**没有** `fsrs_*` `[S]` [schema.py:199-220](file:///d:/Code/DeLector/delector/core/db/schema.py#L199-L220)。

另有两张相关的表：

- `quiz_log`：`card_id / card_type / mode / correct / attempted_at` `[S]` [schema.py:58-65](file:///d:/Code/DeLector/delector/core/db/schema.py#L58-L65)。**没有 `grade` 列**，评分被折叠成 `correct` 0/1。
- `wb_state`：单行 `payload` JSON 镜像，背词工作台的 FSRS 卡状态在这里 `[S]` [schema.py:278-282](file:///d:/Code/DeLector/delector/core/db/schema.py#L278-L282)、[connection.py:331-361](file:///d:/Code/DeLector/delector/core/db/connection.py#L331-L361)。

### 2.2 写入路径：两套调度系统，不能互相假装

1. **卡盒 DSR 路径**：`POST /api/cards/{type}/{id}/review` 读取 `repetition_count / interval_days / ease_factor`，调 `calculate_fsrs`，写回 `repetition_count / interval_days / ease_factor / due_date` 与正误计数 `[S]` [cards.py:388-449](file:///d:/Code/DeLector/delector/routes/cards.py#L388-L449)。`grade >= 2` 记一次正确，否则记一次错误；**原始 1–4 评分没有落库** `[S]` [cards.py:416-418](file:///d:/Code/DeLector/delector/routes/cards.py#L416-L418)。
2. **背词工作台 FSRS 路径**：工作台把整份状态 upsert 到 `wb_state`，并在同一事务里投影进 `vocab_cards`，但**只写** `definition_zh / sentence_context / source / fsrs_s / fsrs_d / fsrs_lapses`，**不写** `due_date / correct_count / wrong_count` `[S]` [vocab_pool.py:123-145](file:///d:/Code/DeLector/delector/core/vocab_pool.py#L123-L145)。

这带来一个必须在 UI 里保留的区分：`fsrs_s > 0` 的行是「工作台来源」，卡面应显示 `工作台 · s=…`，不能显示 `0 正 / 0 误`。这个判据与文案已经写在 [cards.js:203-247](file:///d:/Code/DeLector/static/js/cards.js#L203-L247)：

```js
export function isWorkbenchSourced(card) {
  const wbS = Number(card.fsrs_s);
  return Number.isFinite(wbS) && wbS > 0;
}
```

并且注释明确了一条纪律：**`s` 是 FSRS 稳定性（天），`repetition_count` 是 DSR 复习次数（次），量纲不同，MUST NOT 混写** `[S]` [cards.js:233-236](file:///d:/Code/DeLector/static/js/cards.js#L233-L236)。

### 2.3 读取路径：抽屉现在能拿到什么

抽屉词卡结构 `[S]` [drawer.html:77-134](file:///d:/Code/DeLector/static/modals/drawer.html#L77-L134)：

| 元素 | 行号 | 现在显示 |
| --- | --- | --- |
| `#d-word` | 81 | 词形 |
| `#d-cefr` | 95 | CEFR 徽章 |
| `#d-meta` | 97 | 原型 / 词性 / 性别 / 格 / 可分动词等 |
| `#d-def-status` | 109-116 | 释义来源（本地词库 / AI / 暂无） |
| `#d-def` | 118-124 | 中文释义输入 |
| `#save-vocab-btn` | 126-133 | 「+ 加入 Anki 词汇卡」，点击后 `is-saved` |

阅读器填值链路 `[S]` [reader.js:377-397](file:///d:/Code/DeLector/static/js/reader.js#L377-L397)、[reader.js:426-428](file:///d:/Code/DeLector/static/js/reader.js#L426-L428)：

```js
document.getElementById("d-word").textContent = token.text;
document.getElementById("d-cefr").textContent = "CEFR " + lvl;
...
saveBtn.textContent = "+ 加入 Anki 词汇卡";
saveBtn.classList.remove("is-saved");
```

查词请求只发句子/词形/lemma `[S]` [reader.js:439-443](file:///d:/Code/DeLector/static/js/reader.js#L439-L443)，端点是 `POST /api/lookup/vocab` `[S]` [rd-api.js:33-39](file:///d:/Code/DeLector/static/js/rd-api.js#L33-L39)。后端响应字段只有 `definition_zh / plural / gender / pos / cefr_level / synonyms / source`，外加 `stammformen / komposita / praepositionen` `[S]` [main.py:314-440](file:///d:/Code/DeLector/delector/routes/main.py#L314-L440)。**没有任何卡片状态。**

其他三个可能被误认为「能拿到」的接口：

- `GET /api/cards`：`SELECT *`，**全字段**，但抽屉从不调用；它只服务卡盒页 `[S]` [cards.py:229-248](file:///d:/Code/DeLector/delector/routes/cards.py#L229-L248)、[cards.js:70-78](file:///d:/Code/DeLector/static/js/cards.js#L70-L78)。
- `GET /api/cards/vocab?scope=reader`：返回统一 12 字段契约 `{id, hw, pos, gender, plural, de, zh, ipa, example_zh, core, cefr, letter}`，**复习列在映射时全部丢弃** `[S]` [vocab.py:191-230](file:///d:/Code/DeLector/delector/core/db/vocab.py#L191-L230)、[vocab.py:430-473](file:///d:/Code/DeLector/delector/core/db/vocab.py#L430-L473)。
- `GET /api/cards/known-lemmas`：只返回 `lemma` 列表，用于 i+1 覆盖率；**不带任何状态** `[S]` [cards.py:278-292](file:///d:/Code/DeLector/delector/routes/cards.py#L278-L292)。

### 2.4 前端现有的「复习状态 UI」都在别处

- 卡盒页已经有状态文案 `cardStatsTag(card)`。非工作台分支的模板是 `${mastered ? "已掌握" : due_date ? "到期: " + due_date : "待复习"} · ${correct_count} 正 / ${wrong_count} 误`（注意：`已掌握` 也仍会拼上正误计数）；工作台分支是 `${mastered ? "已掌握 · " : ""}工作台 · s=…` `[S]` [cards.js:240-247](file:///d:/Code/DeLector/static/js/cards.js#L240-L247)。渲染位置是卡面页脚与目录网格 `[S]` [cards.js:345](file:///d:/Code/DeLector/static/js/cards.js#L345)、[cards.js:652](file:///d:/Code/DeLector/static/js/cards.js#L652)。
- 卡盒页背面有四档评分按钮（1 重来 / 2 困难 / 3 良好 / 4 简单），按钮内联下次间隔天数 `[S]` [cards.js:387-402](file:///d:/Code/DeLector/static/js/cards.js#L387-L402)；`next_intervals` 由后端预计算 `[S]` [cards.py:141-147](file:///d:/Code/DeLector/delector/routes/cards.py#L141-L147)、[cards.py:474-477](file:///d:/Code/DeLector/delector/routes/cards.py#L474-L477)。
- 抽屉侧**只有** `#save-vocab-btn.is-saved` 这一个保存成功态 `[S]` [04-drawer-wordcard.css:548-566](file:///d:/Code/DeLector/src/css/04-drawer-wordcard.css#L548-L566)。没有 `mastered`、没有 `due`、没有评分按钮。

可直接复用的既有「状态章」样式（都不是交互件）：

- `.cefr-badge`：`--mono`、`0.65rem`、`1px solid currentColor`、`4px` 圆角 `[S]` [04-drawer-wordcard.css:354-370](file:///d:/Code/DeLector/src/css/04-drawer-wordcard.css#L354-L370)。
- `.lp-status`：`--mono`、`0.6875rem`、`1px solid currentColor`、`2px` 圆角，`data-state="covered"` 切 `--moss` `[S]` [09-a1-encounter-companion-overrides.css:524-540](file:///d:/Code/DeLector/src/css/09-a1-encounter-companion-overrides.css#L524-L540)。

### 2.5 三级结论（这是本轮最重要的表）

| 级别 | 字段/量 | 位置 | 抽屉能不能直接显示 |
| --- | --- | --- | --- |
| **已有，可直接显示** | `mastered`、`due_date`、`interval_days`、`repetition_count`、`correct_count`、`wrong_count`、`ease_factor`、`fsrs_s`、`fsrs_d`、`fsrs_lapses` | `vocab_cards` 真实列 `[S]` schema.py:182-195 | **不能**——抽屉查词链路不返回它们；需要补一个只读投影 |
| **已有，可直接显示（派生自现有列）** | `next_intervals`（四档评分后的间隔预览） | `/api/cards` 与 `/api/cards/due` 现算 `[S]` cards.py:141-147 | 同上，需接口把卡片行交给抽屉 |
| **已有，但需计算/跨表** | 上次复习时间 | `quiz_log.attempted_at` 的 `MAX`，且**工作台复习不写 `quiz_log`** `[S]` schema.py:58-65 | 需跨表聚合，且只有卡盒路径可信 |
| **已有，但需计算** | 连续正确次数 | 由 `quiz_log.correct` 序列推导；口径未定义 `[S]` | 需先定义「连续」的边界（跨模式？跨卡型？） |
| **已有，但需计算** | 当前记忆可提取度 retrievability | `_calc_fsrs_step` 内部算出 `r` 后即丢弃 `[S]` cards.py:109-110 | 不落库、不返回，属于不可显示 |
| **已有，但需语义裁决** | 四态（New/Learning/Review/Relearning） | 无字段；理论上可由 `repetition_count`、`due_date`、`fsrs_s`、`mastered` 派生 | 需先裁决阈值，否则就是编造 |
| **完全不存在** | 显式 `srs_state` 列 | — | 不存在 |
| **完全不存在** | 卡片级 `last_reviewed_at` 列 | — | 不存在（只能跨表近似） |
| **完全不存在** | 原始 `grade` 1–4 的持久化 | `quiz_log` 只有 `correct` 0/1 `[S]` | 不存在；复习后无法回看「上次给了几档」 |
| **完全不存在** | 独立 `next_due` 列 | `due_date` 承担该语义 | 不需要新增；但要明确二者同义 |
| **完全不存在** | 单卡复习历史曲线 / 记忆强度时间序列 | — | 不存在 |

### 2.6 四个会做错的地方

1. **一词多卡，匹配口径未定义。** `POST /api/cards/vocab` 是裸 INSERT，`word`/`lemma` 上没有 UNIQUE，代码注释明确说重复不会被拦 `[S]` [cards.js:1229-1230](file:///d:/Code/DeLector/static/js/cards.js#L1229-L1230)。抽屉里同一 lemma 可能对应 2 张以上卡，显示哪一张必须裁决（最新一张？到期最近的一张？聚合成「2 张卡」？）。
2. **两套调度不能混写。** `fsrs_s` 是工作台的稳定性（天），`repetition_count` 是卡盒的复习次数（次）`[S]` [cards.js:233-236](file:///d:/Code/DeLector/static/js/cards.js#L233-L236)。任何「复习 N 次」的文案都必须先判断来源。
3. **「已掌握」是手动标记，不是调度终态。** 它由用户点「斩」写入 `mastered`，与 DSR/FSRS 进度无关 `[S]` [cards.py:319-334](file:///d:/Code/DeLector/delector/routes/cards.py#L319-L334)、[cards.js:227-231](file:///d:/Code/DeLector/static/js/cards.js#L227-L231)。把它当成 Anki 的 Mature 会误导。
4. **抽屉里的词是屈折形，卡里可能存的是原形。** 抽屉用 `token.text` 与 `token.lemma` 两个值 `[S]` [reader.js:439-443](file:///d:/Code/DeLector/static/js/reader.js#L439-L443)，而卡表同时有 `word` 与 `lemma` 两列 `[S]` schema.py:174-175。匹配必须先定「按 word 还是按 lemma」。

---

## 3. 候选方案

### 3.1 公共约束与实测数值

- **颜色之外必须还有一层**：文本是主载体，颜色只做低饱和辅助（ADR-0029 §3 第 1 条、`docs/design-system.md` §10；WCAG 1.4.1）。
- **对比度** `[T]`：在本轮实际底色上计算（`.sticky-word-card` 为 `var(--paper-card)` `#ffffff`；抽屉底为 `var(--note-yellow)` `#fffbe6`）：

| 前景 token | on `#ffffff` | on `#fffbe6` | 判定 |
| --- | ---: | ---: | --- |
| `--ink-faint` `#726b5e` | 5.28 | 5.07 | 正文 ≥4.5 通过 |
| `--muted` `#756e61` | 5.05 | 4.85 | 通过 |
| `--ink-mute` `#5a5448` | 7.51 | 7.22 | 通过 |
| `--coral` `#b44322` | 5.58 | 5.36 | 通过 |
| `--moss` `#3b6e3f` | 6.02 | 5.79 | 通过 |
| `--olive` `#6e7448` | 4.94 | 4.75 | 通过（余量最小） |

- **非文本对比** `[T]`：`--line`（`rgba(21,20,15,0.16)`）在白底混合后约 `#d9d8d4`，对比 **1.43:1**，低于 SC 1.4.11 的 3:1。**状态章边框必须用 `currentColor`（同 `.cefr-badge` / `.lp-status`），不能用 `--line` 当唯一边界。**
- **命中区 44px**：纯展示状态不是控件，不受 44px 约束；一旦加「去复习」这类可点元素，命中区必须 ≥44px（`docs/design-system.md` §8.3）。现有 `.deck-workbench-link` 的命中区未实测 `[U]`。

### 3.2 方案 A：入卡状态章（最小）

| 项 | 内容 |
| --- | --- |
| 展示什么 | 仅三态：`未入卡` / `待复习` / `已掌握`；不显示间隔、不显示正误 |
| 放在哪 | 词头行右侧、CEFR 徽章左边；或 `#d-meta` 行首 |
| 占多少空间 | 单枚 `--mono` 11px 章，高约 20–22px；不新增整行 |
| 数据依赖 | `mastered`、`due_date`（已有，需补只读查询） |
| 需后端改动 | 是：新增按 `lemma`/`word` 查询单卡状态的只读端点（或在 lookup 响应里加一个 `card_state` 对象） |
| 刻意不做 | 不做四态、不显示间隔、不显示正误、不显示评分按钮 |
| 风险 | `未入卡` 对每次查词都出现，会变成噪音；`已掌握` 与保存按钮语义重叠 |

### 3.3 方案 B：单行「复习台账」（推荐）

| 项 | 内容 |
| --- | --- |
| 展示什么 | 一行等宽元数据：`待复习 · 到期 11-12 · 间隔 4d · 3 正 / 1 误`；已掌握时前置 `已掌握 ·`；工作台来源改用 `工作台 · s=4.2`，不出现「次」 |
| 放在哪 | `#d-meta` 之下、`中文释义 / 笔记` 标签之上；左侧 2px 竖线或上边框做「台账条」 |
| 占多少空间 | 单行 11px / 行高 ~16px，加上下 4–6px，总高约 **24–28px**；抽屉宽 420px（移动端 92vw）内可容纳 |
| 数据依赖 | 已有可直接显示那一级 + 一个只读状态查询；`next_intervals` 可选（不默认展开四档） |
| 需后端改动 | 是：只读端点返回 `mastered / due_date / interval_days / repetition_count / correct_count / wrong_count / fsrs_s`；不改任何写路径 |
| 刻意不做 | 不做四态章、不做彩色强度条、不做单卡评分按钮（复习入口仍在卡盒/工作台）、不做「上次评分」 |
| 为什么推荐 | 信息密度最高而视觉新增最小；全部走既有 `--mono` 元数据语汇，与 CEFR 徽章、台账表头同源；文案可逐字段回溯到真实列，没有编造空间 |

**方案 B 的匹配口径（必须一起裁决）**：建议返回「候选卡列表」或按「最近创建的一张」取，但**这属于产品裁决，不在本调研内拍板**。若不裁决，UI 只能显示「已在词库（2 张）」，不显示具体状态。

### 3.4 方案 C：四态章 + 四档间隔预览（暂缓）

| 项 | 内容 |
| --- | --- |
| 展示什么 | Anki 式四态章 `新卡 / 学习中 / 复习 / 再学习` + 四个「下次出现」胶囊 |
| 放在哪 | 词头行 + 卡片底部，替代现有保存按钮区域 |
| 占多少空间 | 状态章 22px + 四档评分条 44–56px + 间距，约 **120–160px**；移动端抽屉要再让位 |
| 数据依赖 | 四态需派生（阈值未定）；「上次复习时间」跨表且工作台缺失；原始评分完全不存在 |
| 需后端改动 | 大：补状态派生、补 `last_reviewed_at`、补 `grade` 持久化；还要统一两套调度 |
| 刻意不做 | 不先画假状态条；不在本轮补数据层 |
| 判定 | **不建议现在做**。它会把一个「读词时顺便看一眼」的场景，变成第二个复习工作台，且核心数据缺失 |

### 3.5 横向对比

| 维度 | A 最小 | **B 台账（推荐）** | C 四态 |
| --- | --- | --- | --- |
| 新增视觉层 | 1 枚章 | 1 行等宽文本 + 1 条细线 | 章 + 评分条 |
| 高度占用 | ~22px | ~24–28px | ~120–160px |
| 依赖等级 | 已有（需接口） | 已有（需接口） | 部分完全不存在 |
| 后端改动 | 小 | 小 | 大 |
| 信息量 | 低 | 中 | 高但不可信 |
| 与纸感/编辑语汇 | 好 | **最好** | 易滑向大厂卡片风 |
| 主要风险 | 噪音、语义重叠 | 一词多卡口径 | 假状态 |

**推荐 B**，理由：它只把**已经存在**的列排版出来，零编造；用既有 `--mono` + `currentColor` 边框，不新增组件族；一行高度对阅读流几乎无干扰。A 可作为 B 的降级态（数据接口未就绪时先只显示「已入卡 / 未入卡」）。C 应等到数据层补齐后再单独立项。

---

## 4. 若推进：最小验收清单（不是本轮执行）

- [ ] 新增只读状态查询后，用真实 DB 验证：`mastered=1` 的卡、`fsrs_s>0` 的工作台卡、`due_date` 为空的卡、同一 lemma 两张卡，四种情形文案正确。
- [ ] 文案逐字段可回溯：`到期` 只能来自 `due_date`，`间隔` 只能来自 `interval_days`，`N 正 / N 误` 只能来自 `correct_count/wrong_count`，`s=` 只能来自 `fsrs_s`。
- [ ] 工作台来源**不得**出现 `0 正 / 0 误`（沿用 `isWorkbenchSourced` 判据，不得复制阈值）。
- [ ] 颜色之外有文本/边框/线型/字重至少一层；边框用 `currentColor`，实测 ≥3:1。
- [ ] 正文 11px 等宽在 `#ffffff` 与 `#fffbe6` 两种底色上均 ≥4.5:1（本报告已给值，落地后复测）。
- [ ] 若加可点元素，命中区 ≥44px；`prefers-reduced-motion` 下无新增动画。
- [ ] 抽屉 420px / 360px 两档宽度下不换行溢出。

## 5. 本轮边界与未验证项

- **只读**：未改 `static/`、`src/css/`、`delector/`、`tests/`、配置；未启动服务、未跑 pytest、未做真实 App 截图。
- **未实测**：外部产品的详情页视觉样式（需登录/客户端）；抽屉新方案的实际渲染高度与换行（尚未实现）；`.deck-workbench-link` 命中区。
- **已知存量缺陷（不在本调研范围）**：工作台与卡盒两套调度并存导致的「白复习」问题已有探针记录 `[S]` [test_cards_workbench_no_review_probe.py:4-8](file:///d:/Code/DeLector/tests/test_cards_workbench_no_review_probe.py#L4-L8)；本调研只把它作为「为什么不能混写状态」的证据，不提出修复。
