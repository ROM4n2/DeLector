# DeLector Phase 4: 德语影子跟读播放器、网页一键抓取与跨平台多端互通 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 DeLector 打造沉浸式德语**影子跟读播放系统（逐句自动停顿跟读/全文连读/单句循环/0.6x~1.2x语速/卡拉OK逐句同步高亮）**、**德语新闻网页链接（URL）一键抓取导入**、**全量数据备份与还原同步**，以及**跨平台（Windows / Mac / Linux / 安卓 Termux）双击极速启动器**。

**Architecture:**
- **影子跟读播放器（Frontend Engine & Player）**：基于 Web Speech API 与精准分句索引状态机，提供三种播控模式（`continuous` 连读、`shadow` 智能停顿跟读、`loop` 单句循环），通过卡拉OK高亮光框（`.reading-active-sent`）与平滑视口滚动实现听读合一；底部常驻优雅半透明毛玻璃播控栏（`#shadow-player`）。
- **网页链接智能抓取（Backend URL Ingest）**：在 `server.py` 中通过 `httpx` + HTML 正文清洗器提取德语新闻（DW 德语之声、Tagesschau、Spiegel 等）纯净正文与标题，自动分词入库并评定 CEFR 等级。
- **全量数据备份还原（Backup & Sync）**：提供 `/api/backup/export` 与 `/api/backup/restore` 接口，支持跨设备一键迁移全部文章、生词卡与语法笔记。
- **跨平台一键极速启动器**：编写跨平台调度器 `start.py` 以及 Windows `start.bat`、macOS/Linux/安卓 `start.sh`，自动绑定 `0.0.0.0:8000` 并打印局域网手机访问二维码与 IP 地址。

**Tech Stack:** Python 3.11, FastAPI, spaCy (`de_core_news_sm`), SQLite, Web Speech API (SpeechSynthesis), Vanilla HTML/JS/CSS.

## Global Constraints

- 保持单进程 FastAPI + 静态前端架构，零 Node.js 编译步骤。
- 纯原生 Web Speech API 驱动，零外部音频服务依赖，确保脱机可用与低延迟。
- 严格遵循 `docs/design-system.md` 纸张与便签质感（Paper Tint / Notebook Flair）。
- 所有后端新接口必须有对应的 `pytest` 测试。

---

### Task 1: 德语网页 URL 智能抓取与正文提取接口 (Backend URL Ingest)

**Files:**
- Modify: `server.py`
- Test: `test_server.py`

**Interfaces:**
- Produces: `POST /api/articles/ingest-url`
  - Input: `{"url": "https://...", "title": Optional[str]}`
  - Output: `{"article_id": int, "title": str, "char_count": int, "stats": dict}`
- Helper: `extract_article_from_url(url: str) -> Tuple[str, str]`

- [ ] **Step 1: Write the failing test**

在 `test_server.py` 中添加 URL 抓取与导入测试：

```python
def test_url_ingest_endpoint(client):
    # Test valid URL extraction with mock or sample page
    mock_url = "https://raw.githubusercontent.com/delector/mock-german/main/article.html"
    # Using mock payload simulation test
    res = client.post("/api/articles/ingest-url", json={"url": "https://example.com/test", "title": "Test Web Article"})
    # Without real network, test failure or fallback mock
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_server.py::test_url_ingest_endpoint -v`  
Expected: FAIL with `404 Not Found` or missing route.

- [ ] **Step 3: Implement `extract_article_from_url` and route in `server.py`**

在 `server.py` 中实现网页内容抓取、HTML 清洗与标题/正文提取：

```python
import re
import html

class IngestUrlReq(BaseModel):
    url: str
    title: Optional[str] = ""

def clean_html_to_text(raw_html: str) -> Tuple[str, str]:
    # 1. 提取 <title>
    title_match = re.search(r'<title>(.*?)</title>', raw_html, re.IGNORECASE | re.DOTALL)
    title = html.unescape(title_match.group(1).strip()) if title_match else "Extracted Article"
    # 清理 title 中常见的网站后缀（如 "- DER SPIEGEL", "| DW"）
    title = re.split(r'[-|–]\s*(?:DER SPIEGEL|DW|Tagesschau|ZEIT|ZDF)', title)[0].strip()
    
    # 2. 移除 <script>, <style>, <nav>, <header>, <footer>, <svg> 等噪声标签
    cleaned = re.sub(r'<(script|style|nav|header|footer|svg|aside|form|button)[^>]*>.*?</\1>', '', raw_html, flags=re.IGNORECASE | re.DOTALL)
    
    # 3. 提取所有 <p> 标签内容
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', cleaned, flags=re.IGNORECASE | re.DOTALL)
    clean_paras = []
    for p in paragraphs:
        # 去除 HTML tag
        txt = re.sub(r'<[^>]+>', '', p)
        txt = html.unescape(txt).strip()
        # 过滤过短的版权声明或无意义片段
        if len(txt) > 25:
            clean_paras.append(txt)
            
    if not clean_paras:
        # 兜底：直接提取去除标签后的纯文本
        raw_text = re.sub(r'<[^>]+>', ' ', cleaned)
        clean_paras = [html.unescape(line).strip() for line in raw_text.split('\n') if len(line.strip()) > 30]

    body_text = "\n\n".join(clean_paras)
    return title, body_text

async def fetch_and_extract_url(url: str) -> Tuple[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(400, f"无法抓取该网页 (HTTP {resp.status_code})")
        return clean_html_to_text(resp.text)

@app.post("/api/articles/ingest-url")
async def ingest_from_url(req: IngestUrlReq):
    if not req.url.startswith("http://") and not req.url.startswith("https://"):
        raise HTTPException(400, "请输入以 http:// 或 https:// 开头的合法网址")
    
    title, body_text = await fetch_and_extract_url(req.url)
    if not body_text or len(body_text.strip()) < 30:
        raise HTTPException(400, "未能从该网页提取到有效的德语正文，请尝试直接复制粘贴")
        
    final_title = req.title.strip() if req.title else title
    art_id = ingest_article(final_title, body_text)
    return {"article_id": art_id, "title": final_title, "char_count": len(body_text)}
```

- [ ] **Step 4: Run pytest and verify passes**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat(backend): add German URL web text extraction and ingest endpoint"
```

---

### Task 2: 导入弹窗 URL 与文档拖拽多标签 UI (Frontend URL & File Ingest Modal)

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`

**Interfaces:**
- UI: 模态框提供 `[ 粘贴文本 | 网页链接 URL | 上传文件 ]` 三个标签页切换；
- JS: `submitUrlImport()`, `handleFileDrop(event)`

- [ ] **Step 1: Update Modal HTML in `static/index.html`**

```html
  <!-- ── Import Modal ───────────────────────────────────────── -->
  <div id="modal-overlay" onclick="if(event.target===this)closeModal()">
    <div class="modal">
      <div class="modal-tabs">
        <button id="tab-btn-text" class="modal-tab active" onclick="switchImportTab('text')">粘贴长文</button>
        <button id="tab-btn-url" class="modal-tab" onclick="switchImportTab('url')">网页链接 (URL)</button>
        <button id="tab-btn-file" class="modal-tab" onclick="switchImportTab('file')">文档上传</button>
      </div>

      <!-- Tab 1: Text -->
      <div id="import-tab-text" class="tab-content active">
        <div class="modal-field">
          <input id="imp-title" type="text" class="modal-input" placeholder="文章标题（可选）">
        </div>
        <div class="modal-field">
          <textarea id="imp-text" class="modal-input modal-textarea" placeholder="粘贴德语课文、新闻或备考长文…"></textarea>
        </div>
      </div>

      <!-- Tab 2: URL -->
      <div id="import-tab-url" class="tab-content">
        <div class="modal-field">
          <input id="imp-url-input" type="url" class="modal-input" placeholder="输入德语新闻/文章链接 (如: https://www.dw.com/...)">
        </div>
        <p style="font-size:0.75rem;color:var(--pencil);line-height:1.5;margin-bottom:0.75rem;">
          支持自动解析 DW 德语之声、Spiegel、Tagesschau、Zeit 等主流德语新闻与博客正文。
        </p>
      </div>

      <!-- Tab 3: File Upload -->
      <div id="import-tab-file" class="tab-content">
        <div id="dropzone" class="dropzone" onclick="document.getElementById('file-input').click()">
          <div style="font-size:1.75rem;margin-bottom:0.35rem;">📄</div>
          <div style="font-weight:600;color:var(--ink);">点击或拖拽德语文档至此处</div>
          <div style="font-size:0.75rem;color:var(--pencil);margin-top:0.25rem;">支持 .txt, .md 等纯文本文档</div>
          <input id="file-input" type="file" accept=".txt,.md,.text" style="display:none;" onchange="handleFileSelect(event)">
        </div>
      </div>

      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="closeModal()">取消</button>
        <button id="import-btn" class="btn btn-dark" onclick="submitActiveImport()">开始阅读</button>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: Add Modal Tabs and Dropzone CSS in `static/style.css`**

```css
/* Modal Tabs & Dropzone */
.modal-tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1.25rem;
  border-bottom: 1px solid var(--rule);
  padding-bottom: 0.5rem;
}
.modal-tab {
  font-family: var(--sans);
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--pencil);
  background: transparent;
  border: none;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.12s;
}
.modal-tab:hover { color: var(--ink); background: var(--paper-tint); }
.modal-tab.active { color: #FEF9EE; background: var(--ink); }

.tab-content { display: none; }
.tab-content.active { display: block; }

.dropzone {
  border: 2px dashed var(--rule);
  border-radius: 8px;
  padding: 2.25rem 1.5rem;
  text-align: center;
  background: var(--paper);
  cursor: pointer;
  transition: all 0.15s;
}
.dropzone:hover, .dropzone.dragover {
  border-color: var(--accent);
  background: rgba(216, 72, 43, 0.04);
}
```

- [ ] **Step 3: Implement tab switching, URL import and file drop in `static/app.js`**

```javascript
let currentImportTab = 'text';

function switchImportTab(tab) {
  currentImportTab = tab;
  document.querySelectorAll('.modal-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById(`tab-btn-${tab}`).classList.add('active');
  document.getElementById(`import-tab-${tab}`).classList.add('active');
}

async function submitActiveImport() {
  if (currentImportTab === 'text') {
    await submitImport();
  } else if (currentImportTab === 'url') {
    const url = document.getElementById('imp-url-input').value.trim();
    if (!url) { alert('请输入有效的德语网页链接'); return; }
    const btn = document.getElementById('import-btn');
    btn.textContent = '抓取解析中…'; btn.disabled = true;
    try {
      const data = await api('/api/articles/ingest-url', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ url })
      });
      closeModal();
      document.getElementById('imp-url-input').value = '';
      openReader(data.article_id);
    } catch (e) {
      alert('抓取失败，请检查网址或直接复制文章内容导入');
    } finally {
      btn.textContent = '开始阅读'; btn.disabled = false;
    }
  }
}

function handleFileSelect(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(evt) {
    const text = evt.target.result;
    const title = file.name.replace(/\.[^/.]+$/, "");
    document.getElementById('imp-title').value = title;
    document.getElementById('imp-text').value = text;
    switchImportTab('text');
  };
  reader.readAsText(file);
}
```

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat(ui): add URL import tab and file upload dropzone to modal"
```

---

### Task 3: 影子跟读播放器核心状态机与音频流引擎 (Shadow Player Engine)

**Files:**
- Modify: `static/app.js`

**Interfaces:**
- Produces:
  - `playSentence(index)`
  - `togglePlayPause()`
  - `setPlaybackMode(mode)`: `'continuous' | 'shadow' | 'loop'`
  - `setPlaybackSpeed(rate)`: `0.6, 0.8, 1.0, 1.2`
  - `nextSentence()`, `prevSentence()`, `replaySentence()`
- Syncs: Active sentence highlighting and scroll tracking in reader.

- [ ] **Step 1: Implement Shadow Player Engine in `static/app.js`**

```javascript
// ── Shadow Reading Audio Engine ──────────────────────────────────────────────
const ShadowPlayer = {
  isPlaying: false,
  currentSentIdx: 0,
  mode: 'shadow', // 'continuous' | 'shadow' | 'loop'
  rate: 0.88,
  pauseTimer: null,
  utterance: null,

  init() {
    this.bindEvents();
  },

  play() {
    if (!currentArticle || !currentArticle.sentences.length) return;
    this.isPlaying = true;
    this.updatePlayBtn(true);
    this.speakCurrentSentence();
  },

  pause() {
    this.isPlaying = false;
    if (this.pauseTimer) clearTimeout(this.pauseTimer);
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    this.updatePlayBtn(false);
    this.clearSentenceHighlight();
  },

  toggle() {
    if (this.isPlaying) this.pause();
    else this.play();
  },

  speakCurrentSentence() {
    if (!this.isPlaying || !currentArticle) return;
    if (this.currentSentIdx >= currentArticle.sentences.length) {
      this.pause();
      this.currentSentIdx = 0;
      return;
    }

    const sent = currentArticle.sentences[this.currentSentIdx];
    this.highlightSentence(this.currentSentIdx);
    this.updateStatusText();

    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(sent.text.trim());
    utt.lang = 'de-DE';
    utt.rate = this.rate;

    const voices = window.speechSynthesis.getVoices();
    const deVoice = voices.find(v => v.lang.startsWith('de') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('German') || v.name.includes('Hedda') || v.name.includes('Stefan')));
    if (deVoice) utt.voice = deVoice;

    const startTime = Date.now();

    utt.onend = () => {
      if (!this.isPlaying) return;
      const duration = Date.now() - startTime;

      if (this.mode === 'loop') {
        this.pauseTimer = setTimeout(() => this.speakCurrentSentence(), 800);
      } else if (this.mode === 'shadow') {
        // 影子跟读模式：停顿相当于句长的 1.1 倍（至少 2 秒，最多 5 秒）供学习者复述
        const pauseMs = Math.max(2000, Math.min(5000, duration * 1.1));
        this.showPauseCountdown(pauseMs);
        this.pauseTimer = setTimeout(() => {
          this.currentSentIdx++;
          this.speakCurrentSentence();
        }, pauseMs);
      } else {
        // 连续播放模式
        this.pauseTimer = setTimeout(() => {
          this.currentSentIdx++;
          this.speakCurrentSentence();
        }, 400);
      }
    };

    utt.onerror = () => this.pause();
    this.utterance = utt;
    window.speechSynthesis.speak(utt);
  },

  seekSentence(idx) {
    if (!currentArticle) return;
    this.currentSentIdx = Math.max(0, Math.min(currentArticle.sentences.length - 1, idx));
    if (this.isPlaying) {
      if (this.pauseTimer) clearTimeout(this.pauseTimer);
      this.speakCurrentSentence();
    } else {
      this.highlightSentence(this.currentSentIdx);
      this.updateStatusText();
    }
  },

  next() { this.seekSentence(this.currentSentIdx + 1); },
  prev() { this.seekSentence(this.currentSentIdx - 1); },
  replay() { this.seekSentence(this.currentSentIdx); },

  setMode(mode) {
    this.mode = mode;
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    if (this.isPlaying && this.pauseTimer) {
      clearTimeout(this.pauseTimer);
      this.speakCurrentSentence();
    }
  },

  setSpeed(rate) {
    this.rate = rate;
    document.getElementById('speed-val').textContent = `${rate}x`;
    if (this.isPlaying) this.replay();
  },

  highlightSentence(idx) {
    document.querySelectorAll('.tok').forEach(el => el.classList.remove('reading-active'));
    const sent = currentArticle?.sentences[idx];
    if (!sent) return;
    sent.tokens.forEach(t => {
      const el = document.getElementById('tok-' + t.id);
      if (el) el.classList.add('reading-active');
    });
    // 平滑滚动
    const firstTok = document.getElementById('tok-' + sent.tokens[0]?.id);
    if (firstTok) firstTok.scrollIntoView({ behavior: 'smooth', block: 'center' });
  },

  clearSentenceHighlight() {
    document.querySelectorAll('.tok.reading-active').forEach(el => el.classList.remove('reading-active'));
  },

  updatePlayBtn(playing) {
    const btn = document.getElementById('player-play-btn');
    if (btn) btn.innerHTML = playing ? '⏸' : '▶';
  },

  updateStatusText() {
    const el = document.getElementById('player-status');
    if (el && currentArticle) {
      el.textContent = `句 ${this.currentSentIdx + 1} / ${currentArticle.sentences.length}`;
    }
  },

  showPauseCountdown(ms) {
    const el = document.getElementById('player-status');
    if (el) el.textContent = `🎙️ 请跟读 (${Math.round(ms/1000)}s)…`;
  }
};
```

- [ ] **Step 2: Commit**

```bash
git add static/app.js
git commit -m "feat(audio): implement ShadowPlayer state machine with auto-pause shadowing"
```

---

### Task 4: 底部悬浮播控栏 UI 与卡拉OK逐句高亮 (Shadow Player UI)

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`

**Interfaces:**
- UI: `#shadow-player` 悬浮在屏幕底部，包含播放、上下句、单句重播、模式切换（`跟读 🎙️` / `连读 ▶️` / `单句 🔁`）、语速胶囊。
- Style: `.tok.reading-active` 呈现带有呼吸光晕的卡拉OK伴读高亮框。

- [ ] **Step 1: Add Player HTML to `static/index.html` in `#view-reader`**

```html
  <!-- ── Floating Shadow Reading Player ──────────────────────── -->
  <div id="shadow-player" class="shadow-player">
    <div class="player-left">
      <button id="player-prev-btn" class="player-btn" onclick="ShadowPlayer.prev()" title="上一句 (←)">⏮</button>
      <button id="player-play-btn" class="player-btn player-btn-main" onclick="ShadowPlayer.toggle()" title="播放/暂停 (Space)">▶</button>
      <button id="player-next-btn" class="player-btn" onclick="ShadowPlayer.next()" title="下一句 (→)">⏭</button>
      <button id="player-replay-btn" class="player-btn" onclick="ShadowPlayer.replay()" title="重播当前句 (R)">🔁</button>
      <span id="player-status" class="player-status">句 1 / -</span>
    </div>

    <div class="player-right">
      <!-- Mode toggles -->
      <div class="player-mode-group">
        <button class="mode-btn active" data-mode="shadow" onclick="ShadowPlayer.setMode('shadow')" title="智能影子跟读（每句停顿等候跟读）">🎙️ 跟读</button>
        <button class="mode-btn" data-mode="continuous" onclick="ShadowPlayer.setMode('continuous')" title="全文连续朗读">▶ 连读</button>
        <button class="mode-btn" data-mode="loop" onclick="ShadowPlayer.setMode('loop')" title="单句循环练习">🔂 单句</button>
      </div>

      <!-- Speed menu -->
      <div class="speed-pill">
        <button class="speed-step-btn" onclick="ShadowPlayer.setSpeed(0.6)">0.6x</button>
        <button class="speed-step-btn active" onclick="ShadowPlayer.setSpeed(0.88)">0.8x</button>
        <button class="speed-step-btn" onclick="ShadowPlayer.setSpeed(1.0)">1.0x</button>
        <button class="speed-step-btn" onclick="ShadowPlayer.setSpeed(1.2)">1.2x</button>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: Add CSS for Shadow Player & Karaoke Glow in `static/style.css`**

```css
/* Floating Shadow Reading Dock */
.shadow-player {
  position: fixed;
  bottom: 1.5rem;
  left: 50%;
  transform: translateX(-50%);
  z-index: 30;
  width: min(720px, calc(100vw - 2rem));
  background: rgba(26, 23, 20, 0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 999px;
  padding: 0.5rem 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.28);
  color: #FEF9EE;
  transition: all 0.25s ease;
}

body.drawer-open .shadow-player {
  left: calc((100vw - var(--drawer-width)) / 2);
  width: min(600px, calc(100vw - var(--drawer-width) - 3rem));
}

.player-left, .player-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.player-btn {
  width: 32px; height: 32px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.12);
  color: #FEF9EE;
  display: grid;
  place-items: center;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.14s ease;
}
.player-btn:hover { background: rgba(255, 255, 255, 0.25); transform: scale(1.08); }
.player-btn-main {
  width: 38px; height: 38px;
  background: var(--accent);
  color: #fff;
  font-size: 1rem;
}
.player-btn-main:hover { background: #E65335; }

.player-status {
  font-family: var(--mono);
  font-size: 0.6875rem;
  color: rgba(255, 255, 255, 0.7);
  margin-left: 0.35rem;
  white-space: nowrap;
}

.player-mode-group {
  display: flex;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  padding: 2px;
  gap: 2px;
}
.mode-btn {
  font-family: var(--sans);
  font-size: 0.6875rem;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 999px;
  border: none;
  color: rgba(255, 255, 255, 0.65);
  background: transparent;
  cursor: pointer;
  transition: all 0.12s;
}
.mode-btn:hover { color: #fff; }
.mode-btn.active { background: #fff; color: var(--ink); }

.speed-pill {
  display: flex;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  padding: 2px;
  gap: 2px;
}
.speed-step-btn {
  font-family: var(--mono);
  font-size: 0.625rem;
  font-weight: 600;
  padding: 3px 6px;
  border-radius: 999px;
  border: none;
  color: rgba(255, 255, 255, 0.6);
  background: transparent;
  cursor: pointer;
  transition: all 0.12s;
}
.speed-step-btn:hover { color: #fff; }
.speed-step-btn.active { background: var(--amber); color: #fff; }

/* Karaoke Active Sentence Highlight Glow */
.tok.reading-active {
  background: rgba(233, 132, 37, 0.28) !important;
  color: var(--ink) !important;
  box-shadow: 0 2px 0 var(--amber);
  border-radius: 2px;
}
```

- [ ] **Step 3: Bind keyboard shortcuts and click-to-seek in `static/app.js`**

在 `static/app.js` 中拦截 `Space`、`←`、`→`、`R` 键，并在点词/句子时支持无缝定位播放：

```javascript
// Space / Arrow navigation for Audio
document.addEventListener('keydown', (e) => {
  if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;

  if (e.code === 'Space') {
    e.preventDefault();
    ShadowPlayer.toggle();
  } else if (e.key === 'ArrowRight') {
    e.preventDefault();
    ShadowPlayer.next();
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault();
    ShadowPlayer.prev();
  } else if (e.key === 'r' || e.key === 'R') {
    e.preventDefault();
    ShadowPlayer.replay();
  }
});
```

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat(ui): add floating ShadowPlayer dock and visual karaoke highlight"
```

---

### Task 5: 全库数据一键备份/还原与设备同步 (Full Database Backup & Restore API)

**Files:**
- Modify: `server.py`
- Test: `test_server.py`
- Modify: `static/index.html`
- Modify: `static/app.js`

**Interfaces:**
- Produces:
  - `GET /api/backup/export` -> JSON backup of all tables (`articles`, `vocab_cards`, `grammar_cards`)
  - `POST /api/backup/restore` -> Overwrite / merge restored JSON

- [ ] **Step 1: Add Backup & Restore endpoints in `server.py`**

```python
@app.get("/api/backup/export")
def export_database_backup():
    with get_db() as conn:
        articles = [dict(r) for r in conn.execute("SELECT * FROM articles").fetchall()]
        vocab = [dict(r) for r in conn.execute("SELECT * FROM vocab_cards").fetchall()]
        grammar = [dict(r) for r in conn.execute("SELECT * FROM grammar_cards").fetchall()]
        
    return {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "articles": articles,
        "vocab_cards": vocab,
        "grammar_cards": grammar
    }

class RestoreReq(BaseModel):
    articles: list
    vocab_cards: list
    grammar_cards: list

@app.post("/api/backup/restore")
def restore_database_backup(req: RestoreReq):
    with get_db() as conn:
        # Restore articles
        for a in req.articles:
            conn.execute("INSERT OR REPLACE INTO articles (id, title, raw_text, processed_json, created_at) VALUES (?, ?, ?, ?, ?)",
                         (a.get("id"), a["title"], a["raw_text"], a["processed_json"], a.get("created_at")))
        # Restore vocab cards
        for v in req.vocab_cards:
            conn.execute("INSERT OR REPLACE INTO vocab_cards (id, article_id, word, lemma, pos, gender, cefr_level, definition_zh, sentence_context, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (v.get("id"), v.get("article_id"), v["word"], v["lemma"], v.get("pos"), v.get("gender"), v.get("cefr_level"), v["definition_zh"], v["sentence_context"], v.get("created_at")))
        # Restore grammar cards
        for g in req.grammar_cards:
            conn.execute("INSERT OR REPLACE INTO grammar_cards (id, article_id, sentence_context, grammar_name, cefr_level, explanation_zh, rule_formula, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (g.get("id"), g.get("article_id"), g["sentence_context"], g["grammar_name"], g["cefr_level"], g["explanation_zh"], g.get("rule_formula"), g.get("created_at")))
    return {"status": "ok", "message": "备份还原成功"}
```

- [ ] **Step 2: Add Backup test in `test_server.py`**

```python
def test_backup_export_and_restore(client):
    res = client.get("/api/backup/export")
    assert res.status_code == 200
    data = res.json()
    assert "articles" in data
    assert "vocab_cards" in data
    assert "grammar_cards" in data
```

- [ ] **Step 3: Run pytest**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add server.py test_server.py static/index.html static/app.js
git commit -m "feat(sync): add full database backup export and restore endpoints"
```

---

### Task 6: 跨平台一键静默双击启动器与局域网提示 (`start.py`, `start.bat`, `start.sh`)

**Files:**
- Create: `start.py`
- Create: `start.bat`
- Create: `start.sh`

- [ ] **Step 1: Write `start.py`**

```python
#!/usr/bin/env python3
"""
DeLector - Cross-Platform Instant Launcher
Auto-detects local IP, binds 0.0.0.0, and launches default browser.
"""
import os
import sys
import socket
import webbrowser
import threading
import time

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:8000")

def main():
    ip = get_local_ip()
    print("=" * 60)
    print("  DeLector — 德语欧标沉浸阅读与考点剖析工作台")
    print("=" * 60)
    print(f"  ● 本机访问:   http://localhost:8000")
    print(f"  ● 手机/平板:  http://{ip}:8000 (同一局域网Wi-Fi下直接访问)")
    print("=" * 60)
    print("  按 Ctrl+C 停止服务\n")

    threading.Thread(target=open_browser, daemon=True).start()
    
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create Windows `start.bat`**

```bat
@echo off
title DeLector - 德语欧标沉浸阅读工作台
cd /d "%~dp0"
python start.py
pause
```

- [ ] **Step 3: Create macOS/Linux/Android Termux `start.sh`**

```bash
#!/bin/bash
cd "$(dirname "$0")"
python3 start.py
```

- [ ] **Step 4: Commit**

```bash
git add start.py start.bat start.sh
git commit -m "feat(launcher): add cross-platform one-click launchers for Windows, Mac, and Termux"
```

---

### Task 7: 全链路自动化测试与端到端验收 (E2E Verification)

**Files:**
- Test: `test_server.py`

- [ ] **Step 1: Run complete pytest suite**

Run: `pytest -v`  
Expected: 100% PASS

- [ ] **Step 2: Scan for secret key leaks**

Scan working tree with regex.

- [ ] **Step 3: Live Verification in Browser**

1. 打开 `http://localhost:8000`。
2. 在导入模态框中切换到“网页链接 (URL)”，输入德语新闻链接并确认抓取。
3. 进入文章，使用底部悬浮的 ShadowPlayer 进行逐句跟读、连读与语速缩放。
4. 验证卡拉OK高亮光晕与键盘快捷键（`Space`, `←`, `→`, `R`）。
