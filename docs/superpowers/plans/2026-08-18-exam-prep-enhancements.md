# DeLector Phase 2: 零基础 A1 启航与全级别歌德备考增强 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全面支持零基础至初学阶段（A1-A2）的核心学习诉求，将 A1 提升为一级欧标色阶与考点重点，预置 A1/A2 友好样文与日常生活邮件，提供德语冠词性数格（der/die/das）高亮、原生德语发音 (TTS)、短语搭配查询与键盘流。

**Architecture:** 
- 后端：在 `server.py` 中将 A1 纳入完整 CEFR 词库映射；预置从 A1（自我介绍与日常、租房邮件）到 A2/B1/B2/C1 的全阶梯经典样文；针对 A1 常见语法（动词变位、冠词四格变换、动词位置规则）优化 DeepSeek 解析。
- 前端：在 `static/style.css` 与 `static/index.html` 中引入 A1 专属浅天蓝（`#E2F0FF`）荧光标；突出展示德语三大冠词性别（der 蓝 / die 红 / das 绿）；集成 Web Speech API 原生朗读与全局快捷键。

**Tech Stack:** Python 3.11, FastAPI, spaCy (`de_core_news_sm`), SQLite, Web Speech API (`SpeechSynthesis`), Vanilla JS/CSS.

## Global Constraints

- 不引入 Node.js 或前端构建工具，保持单进程极简运行。
- A1 必须作为核心色标与功能完整支持（不可降级为灰色或默认忽略）。
- 德语音频朗读必须使用浏览器原生 `window.speechSynthesis`（`lang="de-DE"`），零外部音频依赖。
- 遵循 `docs/design-system.md` 设计规范并补充 A1 色彩 Token。
- 测试必须使用 `pytest` 并且全绿通过。

---

### Task 1: A1-C1 全阶梯歌德样文库与 A1 词库映射 (Preset Articles & A1 Support)

**Files:**
- Modify: `server.py:30-80`
- Test: `test_server.py`

**Interfaces:**
- Produces: `PRESET_ARTICLES`（包含 A1, A2, B1, B2, C1 各级别典型文稿）
- Ensures: 当数据库为空时自动植入 4 篇以上从入门到进阶的高质量德语课文，A1 包含标准日常会话与自我介绍。

- [ ] **Step 1: Write the failing test**

在 `test_server.py` 中更新种子数据与 A1 分词测试：

```python
def test_seed_preset_articles_with_a1(client, test_db_path):
    from server import init_db, get_db
    init_db(test_db_path)
    
    with get_db(test_db_path) as conn:
        rows = conn.execute("SELECT title, raw_text FROM articles").fetchall()
        assert len(rows) >= 4
        titles = [r["title"] for r in rows]
        assert any("[A1]" in t for t in titles)
        assert any("[A2]" in t for t in titles)
        assert any("[B1]" in t for t in titles)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_server.py::test_seed_preset_articles_with_a1 -v`  
Expected: FAIL with `AssertionError`.

- [ ] **Step 3: Update `PRESET_ARTICLES` in `server.py`**

在 `server.py` 中添加 A1 及以上级别样文，并在 `ingest_article` 分词时将基础词汇显式标记为 `A1`：

```python
PRESET_ARTICLES = [
    {
        "title": "【A1 入门篇】Hallo Berlin! Mein erster Tag in Deutschland",
        "text": "Guten Tag! Ich heiße Lukas und ich komme aus China. Jetzt wohne ich in Berlin und lerne Deutsch an einer Sprachschule. Jeden Morgen trinke ich einen Kaffee, esse ein Brötchen und fahre mit der U-Bahn zum Deutschkurs. Der Unterricht macht viel Spaß. Am Nachmittag gehe ich in den Supermarkt und kaufe frisches Obst und Brot."
    },
    {
        "title": "【A2 进阶篇】Eine Reise nach München: Hotel und Freizeit",
        "text": "Letztes Wochenende bin ich mit dem Zug nach München gefahren. Ich habe ein kleines Zimmer im Stadtzentrum reserviert. Das Wetter war sehr schön, deshalb habe ich den ganzen Nachmittag im Englischen Garten verbracht. Am Abend habe ich typische bayerische Spezialitäten in einem traditionellen Restaurant probiert."
    },
    {
        "title": "【B1 提升篇】Klimaschutz im Alltag: Was jeder tun kann",
        "text": "Der Klimawandel ist eine der größten Herausforderungen unserer Zeit. Viele Menschen fragen sich, wie sie im Alltag einen Beitrag zum Umweltschutz leisten können. Experten empfehlen, öfter auf das Fahrrad umzusteigen und Energie im Haushalt zu sparen. Eine bewusste Ernährung mit regionalen Lebensmitteln spielt ebenfalls eine wichtige Rolle."
    },
    {
        "title": "【B2 高级篇】Die Transformation der modernen Arbeitswelt: Homeoffice",
        "text": "Die fortschreitende Digitalisierung hat die Arbeitsbedingungen grundlegend verändert. Immer mehr Unternehmen stellen ihren Mitarbeitern flexible Arbeitszeitmodelle zur Verfügung. Obwohl das Arbeiten von zu Hause aus die Vereinbarkeit von Beruf und Familie erleichtert, stehen viele Beschäftigte vor der Herausforderung, klare Grenzen zwischen Arbeit und Freizeit zu ziehen."
    }
]

def seed_preset_articles(db_path: Optional[str] = None):
    target = get_db_path(db_path)
    with get_db(target) as conn:
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if count == 0:
            for art in PRESET_ARTICLES:
                ingest_article(art["title"], art["text"], db_path=target)
```

并在 `init_db` 中调用 `seed_preset_articles(target_path)`。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat(backend): add A1 beginner preset passages and full CEFR ladder"
```

---

### Task 2: 零基础 A1 语法考点与冠词性数格深度支持 (Beginner Grammar & Morphology)

**Files:**
- Modify: `server.py:200-250`
- Test: `test_server.py`

**Interfaces:**
- Enhances: `SYSTEM_GRAMMAR_PROMPT`，重点面向 A1/A2 初学者，详细解析：
  1. 动词现在时变位（Konjugation im Präsens）
  2. 动词在句中的位置（Verbposition: Hauptsatz / Nebensatz）
  3. 四格/三格冠词变化（der/den/dem, die/die/der, das/das/dem）
  4. 介词格要求（Akkusativ / Dativ / Wechselpräpositionen）

- [ ] **Step 1: Write the failing test**

```python
def test_a1_grammar_prompt_coverage():
    from server import SYSTEM_GRAMMAR_PROMPT
    assert "A1" in SYSTEM_GRAMMAR_PROMPT
    assert "变位" in SYSTEM_GRAMMAR_PROMPT or "格" in SYSTEM_GRAMMAR_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_server.py::test_a1_grammar_prompt_coverage -v`  
Expected: FAIL if prompt doesn't explicitly mention A1 foundations.

- [ ] **Step 3: Update `SYSTEM_GRAMMAR_PROMPT` in `server.py`**

```python
SYSTEM_GRAMMAR_PROMPT = """你是一位精通德语欧标（Goethe-Zertifikat A1-C1）的资深德语教学与考点解析专家。
用户会提供一个德语完整句子，以及他们点击的目标词汇或短语（用户可能是 A1-A2 零基础/初学者）。

请详细分析该词或短语在句中的关键语法考点，特别关照初学者的痛点（如：冠词四格变化、三格动词、动词现在时变位、可分动词前缀、从句动词置后、固定介词搭配）。

以严格的 JSON 格式输出，字段如下：
{
  "grammar_name": "考点名称（如：Akkusativ mit bestimmtem Artikel / Trennbare Verben / Nomen-Verb-Verbindung / Präposition mit Dativ）",
  "cefr_level": "考点对应的欧标等级，只能是 A1/A2/B1/B2/C1 之一",
  "explanation_zh": "面向初学者的通俗精炼中文解析（1-3句话，解释在句中的语法作用、为什么用这个格/变位，指出考试高频错点）",
  "rule_formula": "语法规则或公式（如：trinken + Akkusativ: den Kaffee (m.) / fahren mit + Dativ: der U-Bahn (f.)）",
  "collocations": ["高频用法1", "高频用法2"]
}
不要输出除 JSON 以外的任何文字。"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat(nlp): enrich DeepSeek prompt for A1/A2 beginner grammar foundations"
```

---

### Task 3: A1 视觉系统扩展与德语冠词性别专属高亮 (A1 & Gender Color System)

**Files:**
- Modify: `static/style.css`
- Modify: `static/index.html`
- Modify: `static/app.js`

**Interfaces:**
- Style Token:
  - `--hl-A1: #E2F0FF; --hl-A1-ink: #15558D;` (天蓝色标记 A1 基础词汇)
  - 德语冠词性标：阳性 `der` (深蓝), 阴性 `die` (朱红/粉), 中性 `das` (森林绿)
- UI: 首页图例新增 `A1 入门基石`，抽屉单词卡片突出显示冠词与性别。

- [ ] **Step 1: Update `static/style.css` with A1 and Gender Badges**

```css
/* CEFR A1 Token */
--hl-A1:       #E2F0FF;
--hl-A1-ink:   #15558D;

.hl-A1 { background: var(--hl-A1); color: var(--hl-A1-ink); }
.tok.A1 { background: var(--hl-A1); }
.badge-A1 { background: var(--hl-A1); color: var(--hl-A1-ink); border-color: var(--hl-A1-ink); }

/* Gender Badges for A1 Beginners */
.gender-tag {
  font-family: var(--mono);
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  margin-left: 4px;
}
.gender-der { background: #E3F2FD; color: #1565C0; border: 1px solid #90CAF9; }
.gender-die { background: #FCE4EC; color: #C2185B; border: 1px solid #F48FB1; }
.gender-das { background: #E8F5E9; color: #2E7D32; border: 1px solid #A5D6A7; }
```

- [ ] **Step 2: Update `static/index.html` Legend**

在图例区加入 A1：

```html
<div class="cefr-legend">
  <strong>欧标色标：</strong>
  <span class="hl-pill hl-A1">A1 入门基石</span>
  <span class="hl-pill hl-A2">A2 进阶表达</span>
  <span class="hl-pill hl-B1">B1 核心词汇</span>
  <span class="hl-pill hl-B2">B2 高级搭配</span>
  <span class="hl-pill hl-C1">C1 精通论述</span>
</div>
```

- [ ] **Step 3: Update `static/app.js` token inspection to render gender tags**

```javascript
// 在 inspect() 中渲染 der/die/das 提示：
let genderHtml = '';
if (token.gender === 'Masc') genderHtml = '<span class="gender-tag gender-der">der 阳性</span>';
else if (token.gender === 'Fem') genderHtml = '<span class="gender-tag gender-die">die 阴性</span>';
else if (token.gender === 'Neut') genderHtml = '<span class="gender-tag gender-das">das 中性</span>';

document.getElementById('d-meta').innerHTML =
  `原型: <strong>${token.lemma}</strong> · 词性: ${token.pos} ${genderHtml}` +
  (token.case ? ` · ${token.case}` : '');
```

- [ ] **Step 4: Verify in browser**

查看 A1 样文，确认 A1 单词带有淡蓝荧光标记，点击名词（如 *Kaffee, U-Bahn, Brötchen*）抽屉清晰呈现 `der 阳性`、`die 阴性`、`das 中性`。

- [ ] **Step 5: Commit**

```bash
git add static/style.css static/index.html static/app.js
git commit -m "feat(ui): add A1 pastel blue highlights and der/die/das gender badges"
```

---

### Task 4: 原生德语朗读 (TTS) 与初学跟读优化 (Audio Playback)

**Files:**
- Modify: `static/app.js`
- Modify: `static/index.html`
- Modify: `static/style.css`

**Interfaces:**
- Produces: `playGermanAudio(text: string, rate: number = 0.88)`
- 针对初学者将默认发音速率调整为 `0.88`（清晰慢速，便于模仿和辨音）。

- [ ] **Step 1: Implement `playGermanAudio` in `static/app.js`**

```javascript
function playGermanAudio(text, rate = 0.88) {
  if (!('speechSynthesis' in window) || !text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'de-DE';
  utterance.rate = rate; // 慢速发音，利于初学者跟读
  
  const voices = window.speechSynthesis.getVoices();
  const deVoice = voices.find(v => v.lang.startsWith('de') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('German') || v.name.includes('Hedda') || v.name.includes('Stefan')));
  if (deVoice) utterance.voice = deVoice;
  
  window.speechSynthesis.speak(utterance);
}
```

- [ ] **Step 2: Add Speaker buttons to Drawer in `static/index.html`**

在单词标题和原句旁添加发音按钮。

- [ ] **Step 3: Test audio playback in browser**

点击单词和整句发音，验证慢速清晰朗读效果。

- [ ] **Step 4: Commit**

```bash
git add static/app.js static/index.html static/style.css
git commit -m "feat(audio): integrate beginner-friendly slow-rate German TTS"
```

---

### Task 5: 键盘极速操作流与短语选中 (Shortcuts & Phrase Selection)

**Files:**
- Modify: `static/app.js`

- [ ] **Step 1: Add keyboard navigation (J/K, Esc, Ctrl+Enter)**
- [ ] **Step 2: Add multi-token drag selection support**
- [ ] **Step 3: Run full test suite (`pytest`)**
- [ ] **Step 4: Commit**

```bash
git add static/app.js
git commit -m "feat(interaction): add keyboard shortcuts and multi-token selection"
```

---

### Task 6: 最终验收与回归验证 (End-to-End Verification)

- [ ] **Step 1: Run complete pytest suite**
- [ ] **Step 2: Secret key scan check**
- [ ] **Step 3: Live UI validation across A1-C1 user journey**
