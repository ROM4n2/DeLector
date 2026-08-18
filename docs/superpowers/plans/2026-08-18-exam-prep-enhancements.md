# DeLector Phase 2: 歌德备考与阅读体感增强 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增强 DeLector 的歌德备考实战体感，提供开箱即用的欧标经典阅读真题库、多词短语/固定搭配查询、原生德语语音朗读 (TTS) 以及全局高效键盘快捷键。

**Architecture:** 
- 后端：在 `server.py` 启动初始化时自动植入 B1/B2/C1 精选阅读真题（若数据库为空）；增强 `/api/lookup/grammar` 接口对多词复合短语（Nomen-Verb-Verbindungen / 介词固定搭配）的解析准确度。
- 前端：在 `static/app.js` 与 `static/index.html` 中引入 Web Speech API 原生德语朗读模块、多词连续选中机制、键盘快捷键监听器（`Esc`, `J/K`, `Ctrl+Enter`）。

**Tech Stack:** Python 3.11, FastAPI, spaCy (`de_core_news_sm`), SQLite, Web Speech API (`SpeechSynthesis`), Vanilla JS/CSS.

## Global Constraints

- 不引入 Node.js 或前端打包工具，保持单进程极简架构。
- 德语音频朗读必须使用浏览器原生 `window.speechSynthesis`（`lang="de-DE"`），零外部音频依赖。
- 严格遵循 `docs/design-system.md` 中的设计规范（字体、配色、便签质感与动效）。
- 测试必须使用 `pytest` 并且全绿通过。

---

### Task 1: 歌德 B1-C1 经典备考样文预置种子数据 (Preset Exam Articles)

**Files:**
- Modify: `server.py:25-50`
- Test: `test_server.py`

**Interfaces:**
- Produces: `seed_preset_articles(db_path: Optional[str] = None)`
- Ensures: 当 `articles` 表为空时，自动插入 3 篇高质量歌德 B1/B2/C1 典型主题文章。

- [ ] **Step 1: Write the failing test**

在 `test_server.py` 中添加种子数据测试：

```python
def test_seed_preset_articles_when_empty(client, test_db_path):
    # Call init_db which should seed 3 preset articles
    from server import init_db, get_db
    init_db(test_db_path)
    
    with get_db(test_db_path) as conn:
        rows = conn.execute("SELECT title, raw_text FROM articles").fetchall()
        assert len(rows) >= 3
        titles = [r["title"] for r in rows]
        assert any("[B1]" in t for t in titles)
        assert any("[B2]" in t for t in titles)
        assert any("[C1]" in t for t in titles)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_server.py::test_seed_preset_articles_when_empty -v`  
Expected: FAIL with `AssertionError: assert len(rows) >= 3` (当前只有 0 行).

- [ ] **Step 3: Write minimal implementation in `server.py`**

在 `server.py` 中实现 `PRESET_ARTICLES` 并在 `init_db` 中自动植入：

```python
PRESET_ARTICLES = [
    {
        "title": "【B1 样篇】Klimaschutz im Alltag: Was jeder tun kann",
        "text": "Der Klimawandel ist eine der größten Herausforderungen unserer Zeit. Viele Menschen fragen sich, wie sie im Alltag einen Beitrag leisten können. Experten empfehlen, öfter auf das Fahrrad umzusteigen und Energie im Haushalt zu sparen. Eine bewusste Ernährung mit regionalen Lebensmitteln spielt ebenfalls eine wichtige Rolle für den Umweltschutz."
    },
    {
        "title": "【B2 样篇】Die Transformation der modernen Arbeitswelt: Chancen des Homeoffice",
        "text": "Die fortschreitende Digitalisierung hat die Arbeitsbedingungen grundlegend verändert. Immer mehr Unternehmen stellen ihren Mitarbeitern flexible Arbeitszeitmodelle zur Verfügung. Obwohl das Arbeiten von zu Hause aus die Vereinbarkeit von Beruf und Familie erleichtert, stehen viele Beschäftigte vor der Herausforderung, klare Grenzen zwischen Arbeit und Freizeit zu ziehen."
    },
    {
        "title": "【C1 样篇】Künstliche Intelligenz und ethische Verantwortung im Diskurs",
        "text": "Die rasanten Entwicklungen im Bereich der generativen künstlichen Intelligenz werfen tiefgreifende ethische und gesellschaftliche Fragestellungen auf. Es gilt zu hinterfragen, inwieweit autonome Algorithmen in Entscheidungsprozesse von existenzieller Tragweite eingebunden werden dürfen. Gesetzgeber stehen vor der anspruchsvollen Aufgabe, Innovationen zu fördern, ohne grundlegende Menschenrechte zu gefährden."
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

并在 `init_db` 尾部调用 `seed_preset_articles(target_path)`。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test_server.py -v`  
Expected: PASS (所有测试通过)

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat(backend): seed preset Goethe B1/B2/C1 exam articles on init"
```

---

### Task 2: 多词固定搭配与短语解析支持 (Multi-word Phrase Lookup)

**Files:**
- Modify: `server.py:200-240`
- Test: `test_server.py`

**Interfaces:**
- Consumes: `GrammarLookupRequest(sentence: str, target_phrase: str)`
- Enhances: 深度优化 DeepSeek Prompt，使其在接收到短语（如 *zur Verfügung stellen*, *im Alltag*, *abhängen von*）时，能准确识别固定搭配类型（Funktionsverbgefüge / Rektion der Verben）与考点等级。

- [ ] **Step 1: Write the failing test**

在 `test_server.py` 中添加多词短语解析单元测试：

```python
def test_multi_token_phrase_grammar_prompt():
    from server import SYSTEM_GRAMMAR_PROMPT
    assert "固定搭配" in SYSTEM_GRAMMAR_PROMPT or "Funktionsverbgefüge" in SYSTEM_GRAMMAR_PROMPT
    assert "搭配" in SYSTEM_GRAMMAR_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_server.py::test_multi_token_phrase_grammar_prompt -v`  
Expected: FAIL if prompt lacks explicit collocation instruction.

- [ ] **Step 3: Update `SYSTEM_GRAMMAR_PROMPT` in `server.py`**

完善系统提示词，强化对多词短语、动词介词搭配、功能动词结构（FVG）的解析：

```python
SYSTEM_GRAMMAR_PROMPT = """你是一位精通德语欧标（Goethe-Zertifikat A1-C1）的资深德语语法与考点解析专家。
用户会提供一个德语完整句子，以及他们选中的目标词汇或多词短语/固定搭配（如 Funktionsverbgefüge, Nomen-Verb-Verbindungen, 介词固定搭配）。

请分析该目标词或短语在句中的关键语法考点，并以严格的 JSON 格式输出，字段如下：
{
  "grammar_name": "考点名称（如：Nomen-Verb-Verbindung: zur Verfügung stellen / Passiversatz / Relativsatz mit Präposition）",
  "cefr_level": "考点对应的欧标等级，只能是 A2/B1/B2/C1 之一",
  "explanation_zh": "中文通俗精炼解析（1-3句话，解释在句子中的含义、句法功能与考试重点）",
  "rule_formula": "结构公式或固定搭配公式（如：etw.(A) zur Verfügung stellen = bereitstellen）",
  "collocations": ["高频搭配1", "高频搭配2"]
}
不要输出除 JSON 以外的任何文字。"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat(nlp): enhance DeepSeek grammar prompt for multi-word collocations"
```

---

### Task 3: 浏览器原生德语发音 (Web Speech TTS) 模块集成

**Files:**
- Modify: `static/app.js`
- Modify: `static/index.html`

**Interfaces:**
- Produces: `playGermanAudio(text: string)`
- UI: 在抽屉单词旁添加 `🔊` 朗读按钮，在例句上下文旁添加 `🔊` 朗读按钮。

- [ ] **Step 1: Add TTS audio helper in `static/app.js`**

```javascript
function playGermanAudio(text) {
  if (!('speechSynthesis' in window) || !text) return;
  window.speechSynthesis.cancel(); // 停止当前正在播放的音频
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'de-DE';
  utterance.rate = 0.92; // 略微放慢，更适合学习者清晰辨音
  
  // 优先选择德语高质量原生音色
  const voices = window.speechSynthesis.getVoices();
  const deVoice = voices.find(v => v.lang.startsWith('de') && (v.name.includes('Google') || v.name.includes('Natural') || v.name.includes('German')));
  if (deVoice) utterance.voice = deVoice;
  
  window.speechSynthesis.speak(utterance);
}
```

- [ ] **Step 2: Update HTML Drawer to include Speaker Buttons**

在 `static/index.html` 的词汇卡与原句上下文旁添加朗读触发按钮：

```html
<!-- Word Headline -->
<div class="sticky-word-headline">
  <div style="display:flex;align-items:center;gap:0.5rem;">
    <span id="d-word"></span>
    <button class="speaker-btn" onclick="playGermanAudio(document.getElementById('d-word').textContent)" title="朗读单词">🔊</button>
  </div>
  <span class="cefr-badge" id="d-cefr"></span>
</div>

<!-- Context Box -->
<div class="context-box">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.25rem;">
    <span class="input-label" style="margin:0;">原句上下文</span>
    <button class="speaker-btn-sm" onclick="playGermanAudio(document.getElementById('d-sent').textContent)" title="朗读整句">🔊 朗读原句</button>
  </div>
  <div id="d-sent"></div>
</div>
```

- [ ] **Step 3: Add CSS for speaker buttons in `static/style.css`**

```css
.speaker-btn {
  font-size: 1rem;
  padding: 2px 6px;
  border-radius: 4px;
  opacity: 0.65;
  transition: opacity 0.14s, transform 0.14s;
}
.speaker-btn:hover { opacity: 1; transform: scale(1.1); }
.speaker-btn-sm {
  font-family: var(--mono);
  font-size: 0.65rem;
  color: var(--pencil);
  padding: 2px 6px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: #fff;
  transition: all 0.12s;
}
.speaker-btn-sm:hover { border-color: var(--ink); color: var(--ink); }
```

- [ ] **Step 4: Verify in browser**

打开 `http://localhost:8000`，点击任意德语单词，点击 `🔊` 按钮，确认能清晰听到德语发音。

- [ ] **Step 5: Commit**

```bash
git add static/app.js static/index.html static/style.css
git commit -m "feat(audio): add browser-native German TTS speech playback"
```

---

### Task 4: 多词短语划选与全局键盘流 (Multi-Token Selection & Shortcuts)

**Files:**
- Modify: `static/app.js`
- Modify: `static/index.html`

**Interfaces:**
- Multi-token Selection: 监听阅读器文本划选 `selectionchange` / `mouseup`，若用户选中多个词，工作台自动切换为短语解析模式。
- Keyboard Shortcuts:
  - `Escape`: 关闭抽屉 / 模态框
  - `J` / `K`: 选中文本中的上一个 / 下一个生词 Token
  - `Ctrl+Enter` / `Cmd+Enter`: 快速保存当前词汇到 Anki

- [ ] **Step 1: Add Keyboard Shortcut listeners in `static/app.js`**

```javascript
document.addEventListener('keydown', (e) => {
  // Esc: 关闭抽屉或模态框
  if (e.key === 'Escape') {
    closeDrawer();
    closeModal();
    return;
  }

  // Ctrl+Enter or Cmd+Enter: 快捷保存词汇卡
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    const drawer = document.getElementById('drawer');
    if (drawer.classList.contains('open')) {
      e.preventDefault();
      saveVocab();
      return;
    }
  }

  // J / K 在阅读模式下快速跳词（当没有聚焦在 input 输入框时）
  if (!['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
    if (e.key === 'j' || e.key === 'k') {
      const tokens = Array.from(document.querySelectorAll('.tok'));
      if (!tokens.length) return;
      const curIndex = tokens.findIndex(el => el.classList.contains('sel'));
      let nextIndex = 0;
      if (e.key === 'j') {
        nextIndex = curIndex < tokens.length - 1 ? curIndex + 1 : 0;
      } else {
        nextIndex = curIndex > 0 ? curIndex - 1 : tokens.length - 1;
      }
      tokens[nextIndex].click();
    }
  }
});
```

- [ ] **Step 2: Add Multi-Token Selection Handler in `static/app.js`**

```javascript
// 支持鼠标划选多词或长短语
document.getElementById('reader-content').addEventListener('mouseup', () => {
  const sel = window.getSelection();
  const text = sel.toString().trim();
  if (text && text.includes(' ') && text.length > 2) {
    inspectPhrase(text);
  }
});

function inspectPhrase(phraseText) {
  if (!currentArticle) return;
  // 查找包含该短语的句子
  const matchedSent = currentArticle.sentences.find(s => s.text.includes(phraseText)) || currentArticle.sentences[0];
  selectedToken = { text: phraseText, lemma: phraseText, pos: 'PHRASE', cefr_level: 'B2', gender: '', case: '' };
  selectedSent = matchedSent;
  grammarData = null;

  document.getElementById('d-word').textContent = phraseText;
  document.getElementById('d-cefr').textContent = 'CEFR B2+';
  document.getElementById('d-cefr').className = 'cefr-badge badge-B2';
  document.getElementById('d-meta').textContent = '固定搭配 / 短语短句';
  document.getElementById('d-def').value = '';
  document.getElementById('d-sent').textContent = matchedSent ? matchedSent.text : '';
  document.getElementById('grammar-result').classList.add('hidden');
  document.getElementById('save-vocab-btn').textContent = '+ 加入 Anki 短语卡';
  openDrawer();
}
```

- [ ] **Step 3: Run test suite & check integration**

Run: `pytest`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add static/app.js
git commit -m "feat(interaction): add multi-token phrase selection and power-user shortcuts"
```

---

### Task 5: 最终全链路验证与回归测试 (End-to-End Verification)

**Files:**
- Test: `test_server.py`

- [ ] **Step 1: Run complete pytest suite**

Run: `pytest -v`  
Expected: All tests PASS with zero regressions.

- [ ] **Step 2: Secret key scan check**

Run:
```bash
git log -n 5 -p | grep -E "(sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{36})"
```
Expected: Zero results found.

- [ ] **Step 3: Verify live server UI**

打开 `http://localhost:8000`：
1. 首页直接展示 3 篇经典歌德样文。
2. 打开任意样文，点击单词，按 `J`/`K` 平滑换词，按 `🔊` 朗读。
3. 划选多个词（如 *zur Verfügung stellen*），抽屉自动弹出短语模式。
4. 导出 Anki 卡片，验证 `.apkg` 生成正常。
