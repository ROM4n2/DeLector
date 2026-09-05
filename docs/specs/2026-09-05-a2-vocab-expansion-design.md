# 📐 DeLector A2 词汇与全域背词系统扩展架构设计规范 (Design Spec)

> **文档版本**: 1.0.0
> **创建日期**: 2026-09-05
> **适用版本**: DeLector `v5.3.0`
> **设计模式**: 方案 B：全域贯通方案 (Dual-Surface Integration: 背词工作台 + 备考域)
> **状态**: 已完成架构探索与双透镜分析，待评审后进入 TDD /vault-plan 实施

---

## 1. 核心问题与用户价值 (Problem Statement & User Value)

### 1.1 背景与痛点
1. **词汇断层**：DeLector 目前的备考工坊与背词工作台核心针对 Goethe A1（约 700+ 词条），当学习者跨越 A1 阶段后，缺乏系统化的 A2 词库进行复习与自测。
2. **存量资产未被激活**：DeLector 底层 `core_dict.py` 与 `core_dict_ext.py` 已收录并人工校验了 **974 个歌德 A2 词条**（涵盖名词性数格、复数屈折、精准释义），但此前未能在背词工作台 (`workbench.html`) 与备考域 (`view-exam`) 形成前台交互闭环。
3. **数据呈现粗糙**：`GET /api/cards/vocab?cefr=A2` 此前返回的词头为裸词元小写（如 `abenteuer`），缺少德语名词至关重要的定冠词（`der`/`die`/`das`）与首字母大写规范，无法直接用于 Zettelkasten 学术卡片呈现。

### 1.2 用户价值与目标
- **零网络开销与即开即用**：基于本地离线词库 974 条现成词元，0 外部 API 调用、0ms 瞬时加载。
- **全域贯通 (Dual-Surface)**：
  1. **背词工作台 (`workbench.html`)**：顶栏支持「📘 A2 词库」一键切换，无缝利用 FSRS 间隔重复记忆算法、四级矿物植物印章评分、自测选择题与拼写题进行高强度刷词。
  2. **主站备考域 (`view-exam`)**：激活 `exam_catalog.py` 中的 `A2` 考纲目录槽位，展示官方 A2 Wortliste 词表卡盒，平滑过渡到进阶备考。

---

## 2. 用户核心旅程与交互流 (User Journey & Core Flow)

```
[场景 1: 工作台刷 A2 词]
工作台顶栏 -> 点击 [📘 A2 词库] -> 异步增量同步 974 个 A2 词 -> 队列重平衡 -> Zettelkasten 抽认卡展示 ("das Abenteuer") -> 矿物印章评分 (FSRS 调度)

[场景 2: 备考域浏览 A2 词表]
主站导航 -> 切换到 [备考域] -> 等级页签选择 [A2] -> 点击 [📖 官方考纲词表 (Wortliste)] -> 网格/牌盒模式浏览 974 词 -> 点击发音 / 加入精读生词本
```

### 极简三步价值闭环
1. **步骤 1 (选择范围)**：用户进入背词工作台顶栏，分段控件由 3 档扩展为 4 档：`[ ⭐ A1 核心 | A1 全量 | 📘 A2 词库 | 🔖 精读生词 ]`，点击 `📘 A2 词库`。
2. **步骤 2 (加载与呈现)**：工作台调用 `/api/cards/vocab?cefr=A2&scope=all`，增量将 974 个 A2 词条合并入本地内存与 `localStorage`，卡片词头精准显示定冠词与复数标记（例如 `das Abenteuer`, `-`）。
3. **步骤 3 (记忆与自测)**：自测模块与拼写模式自动锁定 A2 词库池，错题与复习间隔受 FSRS 引擎统一调度。

---

## 3. 系统架构与数据模型 (Architecture & Data Models)

### 3.1 架构分层图

```
┌────────────────────────────────────────────────────────────────────────┐
│                        前端交互层 (Frontend Surface)                   │
├───────────────────────────────────┬────────────────────────────────────┤
│  背词工作台 (workbench.html)      │  主站备考域 (view-exam / main.js)   │
│  - scopeSeg 扩充 `data-scope="a2"`│  - exam-level-tabs 激活 `A2` 页签   │
│  - inScopeWord 扩展 A2 谓词判定    │  - a2_cards / 考纲词表卡盒容器      │
│  - 严格保持 13 处切片护栏 100% 兼容│  - exam_catalog 驱动题量徽标 (974)  │
└─────────────────┬─────────────────┴─────────────────┬──────────────────┘
                  │ fetch /api/cards/vocab?cefr=A2    │ fetch /api/a2/vocab
                  ▼                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        服务端路由与契约 (API Layer)                    │
├───────────────────────────────────┬────────────────────────────────────┤
│  server.py / routes_cards.py      │  routes_a2.py (新增或 routes_exam) │
│  - GET /api/cards/vocab?cefr=A2   │  - GET /api/a2/vocab (列表返回)    │
│  - 内存级缓存 + 冠词/大小写格式化  │  - GET /api/a2/topics (分类统计)   │
└─────────────────┬─────────────────┴─────────────────┬──────────────────┘
                  │                                   │
                  ▼                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        核心数据模型与单源 (Data Tier)                  │
├────────────────────────────────────────────────────────────────────────┤
│  1. core_dict.py (CORE_VOCAB_DB 974 A2 词元、性数格、复数、中文释义)    │
│  2. database.py (_load_a2_vocab() 冠词拼装器 + 内存 LRU 缓存)          │
│  3. exam_catalog.py (EXAM_CATALOG 注册 "A2": {"vocab": {...}})        │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据模型规范化 (Normalization Pipeline)

在 `database.py` 中重构 `get_vocab_by_cefr(cefr="A2", ...)`：

```python
GENDER_ARTICLE_MAP = {
    "Masc": "der",
    "Fem": "die",
    "Neut": "das",
}

def format_vocab_headword(lemma: str, pos: str, gender: Optional[str]) -> str:
    """对德语词条进行规范化展示格式拼装。
    名词必须首字母大写并前缀定冠词 (如 'das Abenteuer')；动词/形容词保持小写。
    """
    if not lemma:
        return ""
    pos_upper = (pos or "").upper()
    if pos_upper == "NOUN" and gender in GENDER_ARTICLE_MAP:
        art = GENDER_ARTICLE_MAP[gender]
        cap_lemma = lemma[0].upper() + lemma[1:] if len(lemma) > 1 else lemma.upper()
        return f"{art} {cap_lemma}"
    elif pos_upper == "NOUN":
        return lemma[0].upper() + lemma[1:] if len(lemma) > 1 else lemma.upper()
    return lemma.lower()
```

数据输出项结构（符合 `workbench.html` 与 `view-exam` 通用规范）：
```json
{
  "id": "a2-abenteuer",
  "hw": "das Abenteuer",
  "pos": "n.",
  "gender": "Neut",
  "plural": "-",
  "de": "",
  "zh": "冒险/奇遇",
  "core": true,
  "cefr": "A2"
}
```

### 3.3 背词工作台范围选择器与 13 处切片护栏保护

在 `static/german/workbench.html` 中：

#### 1. Markup 扩展
```html
<div class="seg" id="scopeSeg" role="group" aria-label="词汇范围切换">
  <button type="button" data-scope="core">⭐ A1 核心</button>
  <button type="button" data-scope="all">A1 全量</button>
  <button type="button" data-scope="a2">📘 A2 词库</button>
  <button type="button" data-scope="reader">精读生词</button>
</div>
```

#### 2. `inScopeWord` 谓词严格兼容扩展 (Critical Guardrail)
既有 `tools/wb_queue_probe.mjs` 与 `test_german_workbench.py` 断言：
- `inScopeWord helper 必须以 wordFilters.scope === 'core' 为 truth source`
- `inScopeWord helper 必须按 (w.tags || []).includes('core') 判定核心词`

**兼容实现**：
```javascript
function inScopeWord(w) {
  return !w || (wordFilters.scope === "core"
    ? (w.tags || []).includes("core")
    : (wordFilters.scope === "reader"
      ? !!(w.custom || (w.tags || []).includes("reader") || String(w.id || "").startsWith("card-"))
      : (wordFilters.scope === "a2"
        ? (w.cefr === "A2" || (w.tags || []).includes("a2") || String(w.id || "").startsWith("a2-"))
        : (wordFilters.scope === "all"
          ? !(w.cefr === "A2" || (w.tags || []).includes("a2") || String(w.id || "").startsWith("a2-") || (w.custom && (w.tags || []).includes("reader")))
          : wordFilters.scope !== "core"))));
}
```
*注：当 scope 为 "all"（A1 全量）时，若本地已混存 A2 或精读词，精确排斥 A2 与精读生词，确保「A1 全量」仅包含 A1 语料；当 scope 为 "a2" 时，精确匹配 A2 词条。*

#### 3. 增量词库拉取 `syncA2CardsFromServer()`
切换至 `a2` 时触发异步获取，成功后增量追加至 `S.words`、去重并写入 `localStorage`，触发 `refilterReviewQueueForScope()` 与 `renderWords()`。

### 3.4 备考域目录注册 (Exam Catalog Integration)

在 `exam_catalog.py` 中正式注册 A2 等级条目：
```python
EXAM_CATALOG: Dict[str, Dict[str, Any]] = {
    "A1": { ... },
    "A2": {
        "title": "A2",
        "modules": {
            "vocab": {
                "title": "📖 官方考纲词表 (Wortliste)",
                "panel": "exam-cards-family",
                "api_prefix": "/api/a2",
                "count_fn": lambda: len([k for k, v in CORE_VOCAB_DB.items() if v[0] == "A2"]),
            }
        },
    },
}
```

---

## 4. 边界异常与系统韧性 (Edge Cases & Resilience)

1. **离线独立形态支持 (Offline Standalone Resilience)**：
   - 用户若在脱机（纯离线 / 单文件 `workbench.html` 打开）环境下使用：
   - 首次在在线环境点击过一次「A2 词库」后，所有 974 词已完整沉淀在 `localStorage["wb.words.v1"]`。脱机刷新后数据依然健全可用。
   - 若未联网且未曾同步过 A2 词库，工作台提示友好 toast：「请连接 DeLector 服务端以获取 A2 词库数据」，不白屏、不崩溃。
2. **切范围不重填与 FSRS 进度安全 (Scope No-Top-Up & Zero Progress Loss)**：
   - 遵从 ADR-0002 约束：从 A1 切换到 A2 或反向切换时，队列只做 `inScopeWord` 过滤，不得调用 `renormalizeQueueTail()` 盲目补齐新词。
   - 各词条的 FSRS 调度数据（`S.cards[id]`）按唯一 `id`（如 `a2-abenteuer`）隔离，切换模式零进度损失。
3. **大小写与变音符检索韧性**：
   - 搜索框输入小写 `abenteuer` 或大写 `Abenteuer` 均能模糊命中，不受前缀定冠词干扰。

---

## 5. 测试与验证策略 (Test Strategy)

根据 DeLector 严苛工程质量纪律，实施阶段将建立全维度自动化守卫：

### 5.1 自动化测试矩阵
1. **数据层契约测试 (`test_a2_vocab_data.py` - 新增)**：
   - 验证 `database.get_vocab_by_cefr("A2")` 返回整整 974 个词条。
   - 验证名词冠词与首字母大写正确性（随机抽样 20 个名词，assert 其以 `der `/`die `/`das ` 开头且词首大写）。
   - 验证无 `None` 或畸形词头。
2. **端点契约测试 (`test_server.py`)**：
   - 验证 `GET /api/cards/vocab?cefr=A2&scope=all` 返回 200，字段齐全。
   - 验证 `GET /api/a2/vocab` 返回标准列表。
   - 验证 `GET /api/exams/catalog` 包含 A1 与 A2 两个等级，A2 的 vocab 模块 count 精确为 974。
3. **工作台切片探针与静态契约测试**：
   - 运行 `node tools/wb_queue_probe.mjs`，确保 13/13 条切片护栏 100% 保持全绿。
   - 运行 `pytest test_german_workbench.py test_workbench_tokens.py -q`，确保 UI 变量与词库逻辑零回归。
4. **全量回归基线**：
   - 确保现有 574 项全量 pytest 测试全部通过，新增测试纳入永久守卫。

---

## 6. Spec 自审核对表 (Self-Review Checklist)

- [x] **零 TODO / TBD 占位符**：数据源明确为 `CORE_VOCAB_DB` 974 词条，UI 与路由定义明确。
- [x] **无跨域污染**：不修改 spaCy 标注逻辑，不破坏 `tokens.css` 墨水纸张设计系统。
- [x] **严格防范数据集污染**：遵从 `01-Rules/DATASET-HYGIENE-PATTERNS.md`，名词冠词按性数格规则严格对齐，不生造机械错误例句。
- [x] **切片探针兼容**：`inScopeWord` 扩展严格保留既有断言特征（`_SCOPE_IS_CORE` 与 `core` includes 判定）。
