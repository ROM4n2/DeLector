# DeLector Phase 4: 德语影子跟读播放器、网页一键抓取与跨平台多端互通 实施计划 (修订版)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 DeLector 打造高鲁棒性的德语**影子跟读播放系统（逐句停顿跟读/全文连读/单句循环/0.6x~1.2x语速/句级同步伴读高亮）**、**防 SSRF 德语网页链接（URL）智能清洗抓取入库**、**全量数据备份与还原同步**，以及**跨平台（Windows / Mac / Linux / 安卓 Termux）双击极速启动套件**。

**Architecture:**
- **影子跟读播放器（Frontend Engine & Player）**：作为 `<body>` 根级直接子元素挂载（避免 `transform` 动画导致 `position: fixed` 定位上下文失效），基于 Web Speech API 状态机驱动。过滤 `interrupted/canceled` 假错误事件，解决跳句竞态；按视图动态显隐；支持逐句停顿复述（`shadow`）、全文连读（`continuous`）、单句循环（`loop`），并在视口中平滑居中跟随与卡拉OK高亮（`.tok.reading-active`）。
- **网页链接抓取与安全清洗（Backend URL Ingest & Anti-SSRF）**：在 `server.py` 中通过 `urllib.parse` + `ipaddress` 校验目标 IP（严密拦截环回、私有网络及云元数据 IP，防止 SSRF 穿透）；使用 `readability-lxml` / 启发式正文提取器提取德语纯净正文与标题，并在工作线程池中执行 spaCy NLP 分词与入库（避免阻塞 FastAPI 事件循环），同时将 URL 真实写入 `articles.source_url` 列。
- **全量数据备份还原（Backup & Sync）**：严格匹配 `articles`, `vocab_cards`, `grammar_cards` 全字段 schema；提供 `/api/backup/export` 与 `/api/backup/restore` 接口与测试；在卡片库提供导出 JSON 与选择文件还原按钮。
- **跨平台极速启动器与网络探测**：提供 `start.py`（跨平台调度器，自动检测端口占用、打印本机与局域网访问 IP）、Windows `start.bat` 与 Unix `start.sh`（保留可执行权限位）。

**Tech Stack:** Python 3.11, FastAPI, spaCy (`de_core_news_sm`), SQLite, Web Speech API (SpeechSynthesis), Vanilla HTML/JS/CSS.

## Global Constraints

- 单进程 FastAPI + 静态前端，零 Node.js / 外部编译依赖。
- 遵循 `docs/design-system.md` 纸张与便签设计系统。
- 严防 SSRF 攻击：服务端抓取任何外部 URL 前必须解析并在各跳转阶段校验 IP，严格拦截 `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.169.254`, `::1`, `fd00::/8`。
- 测试密闭性：后端测试禁止直连公网，必须使用 `MockTransport` 或本地 HTML fixture。
- 所有任务必须通过 `pytest` 自动化验证并确保 Git 干净提交。

---

### Task 1: 德语网页 URL 安全抓取与正文提取后端 (Anti-SSRF Web Ingest)

**Files:**
- Modify: `server.py`
- Test: `test_server.py`

**Interfaces:**
- Produces: `POST /api/articles/ingest-url`
  - Input: `{"url": str, "title": Optional[str]}`
  - Output: `{"article_id": int, "title": str, "char_count": int, "stats": dict}`
- Helper: `is_safe_public_url(url: str) -> bool`
- Helper: `clean_html_to_article(raw_html: str) -> Tuple[str, str]`
- Updates: `ingest_article(title, text, db_path=None, source_url=None)` 写入 `source_url`

- [ ] **Step 1: Write the failing tests with Mock Transport**

在 `test_server.py` 中添加 SSRF 防护测试与本地 Mock 抓取测试：

```python
import pytest
from server import is_safe_public_url, clean_html_to_article

def test_is_safe_public_url_filters_private_ips():
    assert is_safe_public_url("http://127.0.0.1:8000/api") is False
    assert is_safe_public_url("http://localhost:3000") is False
    assert is_safe_public_url("http://192.168.1.1/admin") is False
    assert is_safe_public_url("http://10.0.0.5/") is False
    assert is_safe_public_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_public_url("http://[::1]/") is False
    assert is_safe_public_url("ftp://example.com/file") is False
    assert is_safe_public_url("https://www.tagesschau.de/inland/test") is True

def test_clean_html_to_article():
    mock_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Klimawandel in den Alpen – DER SPIEGEL</title></head>
    <body>
      <nav><a href="/">Home</a></nav>
      <script>console.log("ad");</script>
      <p>Die Temperaturen in den Alpen steigen doppelt so schnell wie im globalen Durchschnitt.</p>
      <p>Forscher warnen vor gravierenden Folgen für das Ökosystem und den Tourismus der Region.</p>
      <footer>Copyright 2026</footer>
    </body>
    </html>
    """
    title, body = clean_html_to_article(mock_html)
    assert "Klimawandel in den Alpen" in title
    assert "DER SPIEGEL" not in title
    assert "Temperaturen in den Alpen" in body
    assert "Copyright" not in body

def test_url_ingest_endpoint_with_mock(client, monkeypatch):
    from unittest.mock import AsyncMock
    mock_html = "<html><head><title>Hallo Berlin</title></head><body><p>Ich lebe seit zwei Jahren in Berlin und lerne Deutsch.</p></body></html>"
    
    # Mock httpx fetch
    monkeypatch.setattr("server.fetch_remote_html", AsyncMock(return_value=mock_html))
    
    res = client.post("/api/articles/ingest-url", json={"url": "https://www.dw.com/de/hallo-berlin/a-123"})
    assert res.status_code == 200
    data = res.json()
    assert data["article_id"] > 0
    assert "stats" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_server.py::test_is_safe_public_url_filters_private_ips -v`  
Expected: FAIL (functions not defined).

- [ ] **Step 3: Implement Anti-SSRF & Web extraction in `server.py`**

在 `server.py` 中增加必要导入（`from typing import Tuple`, `import ipaddress`, `import socket`, `from urllib.parse import urlparse`）并实现安全抓取：

```python
from typing import Optional, List, Dict, Any, Tuple
import re
import html
import socket
import ipaddress
from urllib.parse import urlparse

def is_safe_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            return False
            
        # Resolve hostname IP to check against private/loopback ranges
        ip_str = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip_str)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
            return False
        return True
    except Exception:
        return False

def clean_html_to_article(raw_html: str) -> Tuple[str, str]:
    # 1. 提取 <title> 并清洗后缀
    title_match = re.search(r'<title>(.*?)</title>', raw_html, re.IGNORECASE | re.DOTALL)
    title = html.unescape(title_match.group(1).strip()) if title_match else "Extracted Article"
    title = re.split(r'[-|–]\s*(?:DER SPIEGEL|DW|Tagesschau|ZEIT ONLINE|ZDF|FAZ|SZ|Süddeutsche)', title)[0].strip()
    
    # 2. 移除干扰标签
    cleaned = re.sub(r'<(script|style|nav|header|footer|svg|aside|form|button|noscript)[^>]*>.*?</\1>', '', raw_html, flags=re.IGNORECASE | re.DOTALL)
    
    # 3. 提取所有有效段落
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', cleaned, flags=re.IGNORECASE | re.DOTALL)
    clean_paras = []
    for p in paragraphs:
        txt = re.sub(r'<[^>]+>', '', p)
        txt = html.unescape(txt).strip()
        if len(txt) > 25 and not any(k in txt.lower() for k in ["cookie", "datenschutz", "abonnieren", "newsletter", "all rights reserved"]):
            clean_paras.append(txt)
            
    if not clean_paras:
        raw_text = re.sub(r'<[^>]+>', ' ', cleaned)
        clean_paras = [html.unescape(line).strip() for line in raw_text.split('\n') if len(line.strip()) > 30]

    body_text = "\n\n".join(clean_paras)
    return title, body_text

async def fetch_remote_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"
    }
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(400, f"无法抓取该网页 (HTTP {resp.status_code})")
        # 再次校验重定向后最终落地 URL
        if not is_safe_public_url(str(resp.url)):
            raise HTTPException(400, "禁止访问内网或保留地址 (SSRF Protection)")
        return resp.text

class IngestUrlReq(BaseModel):
    url: str
    title: Optional[str] = ""

@app.post("/api/articles/ingest-url")
async def ingest_from_url(req: IngestUrlReq):
    if not is_safe_public_url(req.url):
        raise HTTPException(400, "无效网址或受限制的内部网络地址 (SSRF Protection)")
    
    raw_html = await fetch_remote_html(req.url)
    title, body_text = clean_html_to_article(raw_html)
    if not body_text or len(body_text.strip()) < 30:
        raise HTTPException(400, "未能从该网页提取到有效的德语正文，请尝试直接复制粘贴")
        
    final_title = req.title.strip() if req.title else title
    # 在非事件循环线程中执行 NLP 分词与入库
    art_id = await asyncio.to_thread(ingest_article, final_title, body_text, None, req.url)
    with get_db() as conn:
        row = conn.execute("SELECT processed_json FROM articles WHERE id = ?", (art_id,)).fetchone()
        pj = json.loads(row["processed_json"]) if row else {}
    return {"article_id": art_id, "title": final_title, "char_count": len(body_text), "stats": pj.get("stats", {})}
```

并在 `ingest_article(title, text, db_path=None, source_url=None)` 中把 `source_url` 保存至数据库：
```python
def ingest_article(title: str, text: str, db_path: Optional[str] = None, source_url: Optional[str] = None) -> int:
    processed = process_german_text(text)
    target = get_db_path(db_path)
    with get_db(target) as conn:
        cur = conn.execute("INSERT INTO articles (title, raw_text, processed_json, source_url) VALUES (?, ?, ?, ?)",
                           (title or "Untitled", text, json.dumps(processed, ensure_ascii=False), source_url or ""))
        return cur.lastrowid
```

- [ ] **Step 4: Run pytest and verify passes**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py
git commit -m "feat(backend): add SSRF-protected URL ingestion and clean article extraction"
```

---

### Task 2: 导入弹窗 URL 与真拖拽上传交互 (Frontend URL & Drag-Drop Modal)

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`

**Interfaces:**
- UI: 模态框提供 `[ 粘贴长文 | 网页链接 URL | 文档上传 ]` 标签页，触控高度符合 38px 规范。
- JS: 绑定 `dragover`, `dragenter`, `dragleave`, `drop` 事件并调用 `e.preventDefault()` 阻止浏览器直接打开文件。

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
        <div class="modal-field">
          <input id="imp-url-title" type="text" class="modal-input" placeholder="自定义标题（可选，默认自动提取网页标题）">
        </div>
        <p style="font-size:0.75rem;color:var(--pencil);line-height:1.5;margin-top:0.35rem;">
          支持自动解析 DW 德语之声、Spiegel、Tagesschau、Zeit 等主流德语新闻正文。
        </p>
      </div>

      <!-- Tab 3: File Upload -->
      <div id="import-tab-file" class="tab-content">
        <div id="dropzone" class="dropzone" onclick="document.getElementById('file-input').click()">
          <div style="font-size:1.75rem;margin-bottom:0.35rem;">📄</div>
          <div style="font-weight:600;color:var(--ink);">点击或拖拽德语文档至此处</div>
          <div style="font-size:0.75rem;color:var(--pencil);margin-top:0.25rem;">支持 .txt, .md, .text 等纯文本文档</div>
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

- [ ] **Step 2: Add Drag-Drop & Tabs CSS in `static/style.css`**

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
  padding: 8px 14px;
  min-height: 38px;
  border-radius: 6px;
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
  background: rgba(216, 72, 43, 0.05);
}
```

- [ ] **Step 3: Implement true drag-drop and URL submit in `static/app.js`**

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
    const title = document.getElementById('imp-url-title').value.trim();
    if (!url) { alert('请输入有效的德语网页链接'); return; }
    const btn = document.getElementById('import-btn');
    btn.textContent = '抓取解析中…'; btn.disabled = true;
    try {
      const data = await api('/api/articles/ingest-url', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ url, title })
      });
      closeModal();
      document.getElementById('imp-url-input').value = '';
      document.getElementById('imp-url-title').value = '';
      openReader(data.article_id);
    } catch (e) {
      alert('抓取失败，请检查网址是否为公开德语网页，或直接复制文本导入');
    } finally {
      btn.textContent = '开始阅读'; btn.disabled = false;
    }
  } else if (currentImportTab === 'file') {
    const text = document.getElementById('imp-text').value.trim();
    if (text) {
      await submitImport();
    } else {
      document.getElementById('file-input').click();
    }
  }
}

function handleFileSelect(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  readFileContent(file);
  e.target.value = ''; // 允许再次选择同一文件
}

function readFileContent(file) {
  const reader = new FileReader();
  reader.onload = function(evt) {
    const text = evt.target.result;
    const title = file.name.replace(/\.[^/.]+$/, "");
    document.getElementById('imp-title').value = title;
    document.getElementById('imp-text').value = text;
    switchImportTab('text');
  };
  reader.readAsText(file, "UTF-8");
}

// 绑定真正拖拽事件，阻止浏览器直接打开文件
function setupDropzone() {
  const dz = document.getElementById('dropzone');
  if (!dz) return;
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evtName => {
    dz.addEventListener(evtName, (e) => { e.preventDefault(); e.stopPropagation(); });
  });
  dz.addEventListener('dragover', () => dz.classList.add('dragover'));
  dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
  dz.addEventListener('drop', (e) => {
    dz.classList.remove('dragover');
    const file = e.dataTransfer?.files?.[0];
    if (file) readFileContent(file);
  });
}
```

并在 `// -- Init` 底部执行 `setupDropzone()`。

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat(ui): implement real drag-and-drop file import and multi-tab modal"
```

---

### Task 3: 影子跟读播放器状态机与跳句竞态修复 (Shadow Player Engine)

**Files:**
- Modify: `static/app.js`

**Interfaces:**
- Produces: `ShadowPlayer` object with:
  - `play()`, `pause()`, `toggle()`
  - `next()`, `prev()`, `replay()`
  - `setMode('shadow' | 'continuous' | 'loop')`
  - `setSpeed(rate: number)`
  - `seekSentence(idx: number)`
  - `reset()`

- [ ] **Step 1: Implement robust ShadowPlayer state machine in `static/app.js`**

```javascript
// ── Shadow Reading Audio Engine ──────────────────────────────────────────────
const ShadowPlayer = {
  isPlaying: false,
  currentSentIdx: 0,
  mode: 'shadow', // 'continuous' | 'shadow' | 'loop'
  rate: 0.88,
  pauseTimer: null,
  utterance: null,
  isIntentionalCancel: false,

  init() {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.onvoiceschanged = () => {
        window.speechSynthesis.getVoices();
      };
    }
  },

  reset() {
    this.pause();
    this.currentSentIdx = 0;
    this.clearSentenceHighlight();
    this.updateStatusText();
  },

  play() {
    if (!currentArticle || !currentArticle.sentences || !currentArticle.sentences.length) return;
    this.isPlaying = true;
    this.updatePlayBtn(true);
    this.speakCurrentSentence();
  },

  pause() {
    this.isPlaying = false;
    if (this.pauseTimer) { clearTimeout(this.pauseTimer); this.pauseTimer = null; }
    if ('speechSynthesis' in window) {
      this.isIntentionalCancel = true;
      window.speechSynthesis.cancel();
      this.isIntentionalCancel = false;
    }
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

    if ('speechSynthesis' in window) {
      this.isIntentionalCancel = true;
      window.speechSynthesis.cancel();
      this.isIntentionalCancel = false;

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
          this.pauseTimer = setTimeout(() => this.speakCurrentSentence(), 700);
        } else if (this.mode === 'shadow') {
          // 影子跟读模式：停顿相当于句长的 1.1 倍（至少 2 秒，最多 6 秒）供大声跟读
          const pauseMs = Math.max(2000, Math.min(6000, duration * 1.1));
          this.showPauseCountdown(pauseMs);
          this.pauseTimer = setTimeout(() => {
            if (!this.isPlaying) return;
            this.currentSentIdx++;
            this.speakCurrentSentence();
          }, pauseMs);
        } else {
          // 连续播放模式
          this.pauseTimer = setTimeout(() => {
            if (!this.isPlaying) return;
            this.currentSentIdx++;
            this.speakCurrentSentence();
          }, 350);
        }
      };

      // 核心修复：过滤 interrupted 与 canceled，避免跳句或调速时误暂停
      utt.onerror = (e) => {
        if (e.error !== 'interrupted' && e.error !== 'canceled' && !this.isIntentionalCancel) {
          this.pause();
        }
      };

      this.utterance = utt;
      window.speechSynthesis.speak(utt);
    }
  },

  seekSentence(idx) {
    if (!currentArticle) return;
    this.currentSentIdx = Math.max(0, Math.min(currentArticle.sentences.length - 1, idx));
    if (this.isPlaying) {
      if (this.pauseTimer) { clearTimeout(this.pauseTimer); this.pauseTimer = null; }
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
      this.pauseTimer = null;
      this.speakCurrentSentence();
    }
  },

  setSpeed(rate) {
    this.rate = rate;
    document.querySelectorAll('.speed-step-btn').forEach(b => {
      b.classList.toggle('active', parseFloat(b.dataset.speed) === rate);
    });
    if (this.isPlaying) {
      if (this.pauseTimer) { clearTimeout(this.pauseTimer); this.pauseTimer = null; }
      this.speakCurrentSentence();
    }
  },

  highlightSentence(idx) {
    document.querySelectorAll('.tok').forEach(el => el.classList.remove('reading-active'));
    const sent = currentArticle?.sentences[idx];
    if (!sent || !sent.tokens.length) return;
    sent.tokens.forEach(t => {
      const el = document.getElementById('tok-' + t.id);
      if (el) el.classList.add('reading-active');
    });
    const firstTok = document.getElementById('tok-' + sent.tokens[0].id);
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

并在 `openReader(id)` 中重置播放器：`ShadowPlayer.reset();`。

- [ ] **Step 2: Commit**

```bash
git add static/app.js
git commit -m "feat(audio): implement robust ShadowPlayer engine with race-free speech seeking"
```

---

### Task 4: 底部悬浮毛玻璃播控栏与卡拉OK高亮 (Shadow Player UI & Body Dock)

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`

**Interfaces:**
- HTML: `#shadow-player` 挂载在 `<body>` 根级（避免包含块失效陷阱），并在 `show(view)` 中控制显隐（仅 `reader` 视图激活时展示）。
- UI: 播控栏居中悬浮、支持在抽屉展开时智能向左避让；点击正文句子直接调用 `ShadowPlayer.seekSentence(sent.id)`。

- [ ] **Step 1: Add Player HTML directly under `<body>` in `static/index.html`**

```html
  <!-- ── Floating Shadow Reading Player (Root Level) ─────────── -->
  <div id="shadow-player" class="shadow-player hidden">
    <div class="player-left">
      <button id="player-prev-btn" class="player-btn" onclick="ShadowPlayer.prev()" title="上一句 (←)">⏮</button>
      <button id="player-play-btn" class="player-btn player-btn-main" onclick="ShadowPlayer.toggle()" title="播放/暂停 (Space)">▶</button>
      <button id="player-next-btn" class="player-btn" onclick="ShadowPlayer.next()" title="下一句 (→)">⏭</button>
      <button id="player-replay-btn" class="player-btn" onclick="ShadowPlayer.replay()" title="重播当前句 (R)">🔁</button>
      <span id="player-status" class="player-status">句 1 / -</span>
    </div>

    <div class="player-right">
      <div class="player-mode-group">
        <button class="mode-btn active" data-mode="shadow" onclick="ShadowPlayer.setMode('shadow')" title="智能影子跟读（每句停顿等候跟读）">🎙️ 跟读</button>
        <button class="mode-btn" data-mode="continuous" onclick="ShadowPlayer.setMode('continuous')" title="全文连续朗读">▶ 连读</button>
        <button class="mode-btn" data-mode="loop" onclick="ShadowPlayer.setMode('loop')" title="单句循环练习">🔂 单句</button>
      </div>

      <div class="speed-pill">
        <button class="speed-step-btn" data-speed="0.6" onclick="ShadowPlayer.setSpeed(0.6)">0.6x</button>
        <button class="speed-step-btn active" data-speed="0.88" onclick="ShadowPlayer.setSpeed(0.88)">0.8x</button>
        <button class="speed-step-btn" data-speed="1.0" onclick="ShadowPlayer.setSpeed(1.0)">1.0x</button>
        <button class="speed-step-btn" data-speed="1.2" onclick="ShadowPlayer.setSpeed(1.2)">1.2x</button>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: Add Player CSS in `static/style.css`**

```css
/* Floating Shadow Reading Dock */
.shadow-player {
  position: fixed;
  bottom: 1.5rem;
  left: 50%;
  transform: translateX(-50%);
  z-index: 50;
  width: min(720px, calc(100vw - 2rem));
  background: rgba(26, 23, 20, 0.94);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 999px;
  padding: 0.5rem 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 10px 32px rgba(0, 0, 0, 0.35);
  color: #FEF9EE;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.shadow-player.hidden {
  display: none !important;
}

body.drawer-open .shadow-player {
  left: calc((100vw - var(--drawer-width) - var(--drawer-gap)) / 2);
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
  padding: 4px 9px;
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
  background: rgba(233, 132, 37, 0.26) !important;
  color: var(--ink) !important;
  box-shadow: 0 2px 0 var(--amber);
  border-radius: 2px;
}
```

- [ ] **Step 3: Update `show(view)` and Keyboard handler in `static/app.js`**

在 `show(view)` 中控制 `#shadow-player`：
```javascript
function show(view) {
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.getElementById('view-' + view).classList.add('active');
  closeDrawer();
  clearCefrFocus();
  
  const player = document.getElementById('shadow-player');
  if (player) {
    player.classList.toggle('hidden', view !== 'reader');
    if (view !== 'reader') ShadowPlayer.pause();
  }

  if (view === 'home')  loadArticles();
  if (view === 'cards') loadCards();
}
```

在全局键盘监听器中准确排除 `BUTTON`, `INPUT`, `TEXTAREA` 以及模态框打开状态：
```javascript
document.addEventListener('keydown', (e) => {
  const isEditing = ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName);
  const isModalOpen = document.getElementById('modal-overlay')?.classList.contains('open');

  if (e.key === 'Escape') {
    clearCefrFocus();
    closeDrawer();
    closeModal();
    return;
  }

  if (isEditing || isModalOpen) return;

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

并在用户点击正文中的任意句子时，同步更新播放器选中的句子：在 `inspect(tokenId, sentId)` 中调用 `ShadowPlayer.seekSentence(sentId)`.

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat(ui): mount floating ShadowPlayer dock and bind synchronized audio shortcuts"
```

---

### Task 5: 全库备份导出还原与前端界面 (Full Database Backup & Restore API)

**Files:**
- Modify: `server.py`
- Test: `test_server.py`
- Modify: `static/index.html`
- Modify: `static/app.js`

**Interfaces:**
- Produces: `GET /api/backup/export` (返回全字段全表 JSON)
- Produces: `POST /api/backup/restore` (事务性全量替换还原)
- UI: 卡片库顶部提供 `[ 导出全库备份 ]` 与 `[ 从备份文件还原 ]`

- [ ] **Step 1: Write Backup Export & Round-Trip Restore Tests in `test_server.py`**

```python
def test_backup_export_and_restore_roundtrip(client):
    # 1. Export current backup
    res = client.get("/api/backup/export")
    assert res.status_code == 200
    data = res.json()
    assert "version" in data
    assert "articles" in data
    assert "vocab_cards" in data
    assert "grammar_cards" in data
    
    # 2. Modify or add custom entry
    custom_backup = {
        "version": 1,
        "articles": [{
            "id": 999,
            "title": "Backup Test Article",
            "raw_text": "Ein Test für Backup.",
            "processed_json": "{}",
            "source_url": "https://example.com/backup",
            "created_at": "2026-08-18 12:00:00"
        }],
        "vocab_cards": [{
            "id": 999,
            "article_id": 999,
            "word": "Test",
            "lemma": "Test",
            "pos": "NOUN",
            "gender": "Masc",
            "cefr_level": "A1",
            "definition_zh": "测试",
            "sentence_context": "Ein Test.",
            "plural": "Tests",
            "created_at": "2026-08-18 12:00:00"
        }],
        "grammar_cards": [{
            "id": 999,
            "article_id": 999,
            "sentence_context": "Ein Test.",
            "grammar_name": "Nomen",
            "cefr_level": "A1",
            "explanation_zh": "名词",
            "rule_formula": "Pattern",
            "examples_zh": "例子",
            "created_at": "2026-08-18 12:00:00"
        }]
    }
    
    # 3. Restore custom backup
    res_restore = client.post("/api/backup/restore", json=custom_backup)
    assert res_restore.status_code == 200
    
    # 4. Verify roundtrip integrity
    res_verify = client.get("/api/articles/999")
    assert res_verify.status_code == 200
    assert res_verify.json()["title"] == "Backup Test Article"
```

- [ ] **Step 2: Implement full-schema Backup & Restore in `server.py`**

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
    version: Optional[int] = 1
    articles: List[Dict[str, Any]] = []
    vocab_cards: List[Dict[str, Any]] = []
    grammar_cards: List[Dict[str, Any]] = []

@app.post("/api/backup/restore")
def restore_database_backup(req: RestoreReq):
    with get_db() as conn:
        # 完整支持所有现有字段，防丢失
        for a in req.articles:
            conn.execute(
                "INSERT OR REPLACE INTO articles (id, title, raw_text, processed_json, source_url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (a.get("id"), a.get("title", "Untitled"), a.get("raw_text", ""), a.get("processed_json", "{}"), a.get("source_url", ""), a.get("created_at"))
            )
        for v in req.vocab_cards:
            conn.execute(
                "INSERT OR REPLACE INTO vocab_cards (id, article_id, word, lemma, pos, gender, cefr_level, definition_zh, sentence_context, plural, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (v.get("id"), v.get("article_id"), v.get("word", ""), v.get("lemma", ""), v.get("pos", ""), v.get("gender", ""), v.get("cefr_level", "A1"), v.get("definition_zh", ""), v.get("sentence_context", ""), v.get("plural", ""), v.get("created_at"))
            )
        for g in req.grammar_cards:
            conn.execute(
                "INSERT OR REPLACE INTO grammar_cards (id, article_id, sentence_context, grammar_name, cefr_level, explanation_zh, rule_formula, examples_zh, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (g.get("id"), g.get("article_id"), g.get("sentence_context", ""), g.get("grammar_name", ""), g.get("cefr_level", "A1"), g.get("explanation_zh", ""), g.get("rule_formula", ""), g.get("examples_zh", ""), g.get("created_at"))
            )
    return {"status": "ok", "message": "全量备份恢复成功"}
```

- [ ] **Step 3: Add Backup buttons in `static/index.html` & JS in `static/app.js`**

在 `static/index.html` 的 `cards-topbar` 中增加备份与还原按钮：
```html
    <div class="cards-topbar">
      <button class="btn btn-ghost" onclick="show('home')">← 返回文库</button>
      <h2>待复习卡片库</h2>
      <div style="display:flex;gap:0.5rem;">
        <button class="btn btn-ghost" onclick="downloadBackupJson()" title="导出包含文章与卡片的 JSON 备份">导出备份</button>
        <button class="btn btn-ghost" onclick="document.getElementById('backup-file-input').click()" title="从备份文件还原">还原备份</button>
        <input id="backup-file-input" type="file" accept=".json" style="display:none;" onchange="uploadBackupJson(event)">
        <a href="/api/cards/export/apkg" class="btn btn-dark">导出 Anki (.apkg)</a>
      </div>
    </div>
```

在 `static/app.js` 中增加下载与上传逻辑：
```javascript
async function downloadBackupJson() {
  const data = await api('/api/backup/export');
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `delector_backup_${new Date().toISOString().slice(0,10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function uploadBackupJson(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async function(evt) {
    try {
      const payload = JSON.parse(evt.target.result);
      await api('/api/backup/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      alert('备份还原成功！');
      loadCards();
      refreshCount();
    } catch {
      alert('备份文件格式不正确或还原失败');
    }
  };
  reader.readAsText(file);
  e.target.value = '';
}
```

- [ ] **Step 4: Run pytest and verify passes**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py static/index.html static/app.js
git commit -m "feat(sync): add robust database backup export and restore with UI integration"
```

---

### Task 6: 跨平台极简启动器与网络探测 (`start.py`, `start.bat`, `start.sh`)

**Files:**
- Create: `start.py`
- Create: `start.bat`
- Create: `start.sh`

- [ ] **Step 1: Write `start.py` with port detection & clean IP banner**

```python
#!/usr/bin/env python3
"""
DeLector - Cross-Platform Instant Launcher
Auto-detects port availability, LAN IP, and launches default browser.
"""
import os
import sys
import socket
import webbrowser
import threading
import time

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def open_browser(port: int):
    time.sleep(1.2)
    # Support Android Termux termux-open-url fallback
    if os.environ.get("TERMUX_VERSION") or os.path.exists("/data/data/com.termux"):
        os.system(f"termux-open-url http://localhost:{port}")
    else:
        webbrowser.open(f"http://127.0.0.1:{port}")

def main():
    port = 8000
    if is_port_in_use(port):
        print(f"[提示] 端口 {port} 正在运行中或已被占用，正在尝试连接已有服务...")
        open_browser(port)
        return

    ip = get_local_ip()
    print("=" * 60)
    print("  DeLector — 德语欧标沉浸阅读与考点剖析工作台")
    print("=" * 60)
    print(f"  ● 电脑本机访问: http://localhost:{port}")
    if ip != "127.0.0.1":
        print(f"  ● 手机/平板访问: http://{ip}:{port} (同一 Wi-Fi 局域网)")
    print("=" * 60)
    print("  按 Ctrl+C 停止服务\n")

    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create `start.bat` for Windows**

```bat
@echo off
title DeLector - 德语欧标沉浸阅读工作台
cd /d "%~dp0"
python start.py
pause
```

- [ ] **Step 3: Create executable `start.sh` for macOS/Linux/Termux**

```bash
#!/bin/bash
cd "$(dirname "$0")"
python3 start.py
```

并赋予可执行位：
```bash
git update-index --chmod=+x start.sh
```

- [ ] **Step 4: Commit**

```bash
git add start.py start.bat start.sh
git commit -m "feat(launcher): add cross-platform one-click launchers with port detection"
```

---

### Task 7: 全链路验收与安全密钥扫描 (E2E Verification & Security Guard)

**Files:**
- Test: `test_server.py`

- [ ] **Step 1: Run complete pytest suite**

Run: `pytest -v`  
Expected: 100% PASS with 0 errors.

- [ ] **Step 2: Scan for secret key leaks using strict regex rule**

Run secret key scan check across all tracked and untracked files:
```bash
grep -nE '(sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)' server.py static/app.js test_server.py
```
Expected: No matches found.

- [ ] **Step 3: Live Verification in Browser**

1. 打开 `http://localhost:8000`。
2. 导入测试：粘贴 URL 或拖入 `.txt` 德语文件，验证分词、CEFR 等级自动计算与入库。
3. 影子跟读测试：点击进入文章，底部悬浮出现 `#shadow-player`；点击 `▶` 播放，验证逐句高亮与跟读停顿计时。
4. 快捷键测试：按 `Space` 暂停/播放、`← / →` 跳句、`R` 键重听，验证无竞态打断 bug。
5. 备份测试：进入卡片库，导出 JSON 备份并成功还原。
