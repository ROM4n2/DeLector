# DeLector Phase 5: 德国主播级 Edge 神经语音与文章随笔高亮笔记系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 DeLector 引入**德国电台播音级 Edge Neural 神经语音模型（`edge-tts`）与本地毫秒级音频缓存**、**正文划选浮动批注胶囊（Selection Tooltip）**、**侧边拟物便签贴纸与 AI 随笔辅助**，以及**全文精读学习讲义（Markdown）一键导出与全量备份同步**。

**Architecture:**
- **主播级神经语音引擎（Backend Neural Audio & Cache）**：在 `server.py` 中引入 `edge-tts` 异步流式合成器，支持德语顶级母语音色（`de-DE-KatjaNeural` 清脆女声 / `de-DE-ConradNeural` 沉稳男声），生成高质量 MP3 并以 SHA256 哈希缓存至 `cache/audio/`；提供 `/api/audio/tts` 端点，前端影子跟读播放器无缝切换为 HTML5 Audio 高清音频流，断网时自动平滑回退至浏览器 Web Speech API。
- **划选浮动批注胶囊（Selection Tooltip）**：选中文本时悬浮展示 `[ 🟡 荧光高亮 | 🟢 考点绿 | 📝 记随笔 | 🔊 神经朗读 ]` 工具条，划线数据持久化至 SQLite 数据库并在文章重开时完美还原。
- **段落拟物便签与 AI 速记（Margin Sticky Notes & AI Assist）**：在有笔记的段落侧边呈现拟物便签纸贴纸，点击直接滑开随笔编辑器；内置 `[ ✨ AI 提炼要点 / 德汉速释 ]` 自动生成要点摘要。
- **全景精读讲义导出（Study Guide Export）**：在文末提供 `[ 📥 导出精读笔记 (Markdown) ]`，自动汇总全文划线原句、词汇卡、语法考点与个人随笔，格式化输出为排版优美的 Markdown 讲义。

**Tech Stack:** Python 3.11, FastAPI, `edge-tts`, spaCy, SQLite, HTML5 Audio API, DeepSeek API, Vanilla HTML/JS/CSS.

## Global Constraints

- 保持单进程架构与零外部 Node.js 编译工具链。
- `edge-tts` 合成采用异步非阻塞调用，音频本地缓存按文本内容 SHA256 索引，防重复请求。
- 遵循 `docs/design-system.md` 纸张与便签设计系统，便签贴纸采用拟物阴影与胶带质感。
- 所有新接口配备完整的 `pytest` 密闭测试（使用 Mock 隔离网络）。

---

### Task 1: 微软 Edge Neural TTS 神经语音合成与本地缓存后端 (Backend Edge-TTS)

**Files:**
- Modify: `requirements.txt`
- Modify: `server.py`
- Test: `test_server.py`

**Interfaces:**
- Produces: `POST /api/audio/tts` / `GET /api/audio/tts`
  - Params/Body: `{"text": str, "voice": Optional[str] = "de-DE-KatjaNeural", "rate": Optional[str] = "+0%"}`
  - Returns: `FileResponse` (MP3 audio stream, `media_type="audio/mpeg"`)
- Helper: `generate_edge_tts_audio(text: str, voice: str = "de-DE-KatjaNeural", rate: str = "+0%") -> str` (返回缓存文件路径)

- [ ] **Step 1: Write the failing tests with Mocking**

在 `test_server.py` 中编写 `edge-tts` 音频合成与缓存测试：

```python
def test_audio_tts_endpoint_with_mock(client, monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    # Mock audio file generation
    fake_mp3 = tmp_path / "fake_de.mp3"
    fake_mp3.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00mock_audio_data")
    
    monkeypatch.setattr("server.generate_edge_tts_audio", AsyncMock(return_value=str(fake_mp3)))
    
    res = client.post("/api/audio/tts", json={"text": "Hallo Berlin!", "voice": "de-DE-KatjaNeural"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert len(res.content) > 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_server.py::test_audio_tts_endpoint_with_mock -v`  
Expected: FAIL with `404 Not Found` or missing route.

- [ ] **Step 3: Implement `generate_edge_tts_audio` and `/api/audio/tts` in `server.py`**

在 `server.py` 中增加 `edge-tts` 支持与本地哈希缓存：

```python
import hashlib
from fastapi.responses import FileResponse

AUDIO_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache", "audio")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

class TTSReq(BaseModel):
    text: str
    voice: Optional[str] = "de-DE-KatjaNeural"
    rate: Optional[str] = "+0%"

async def generate_edge_tts_audio(text: str, voice: str = "de-DE-KatjaNeural", rate: str = "+0%") -> str:
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(400, "Text cannot be empty")
        
    # Generate unique cache key based on text, voice and speed
    cache_key = hashlib.sha256(f"{voice}_{rate}_{clean_text}".encode("utf-8")).hexdigest()
    cache_file = os.path.join(AUDIO_CACHE_DIR, f"{cache_key}.mp3")
    
    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 100:
        return cache_file
        
    import edge_tts
    communicate = edge_tts.Communicate(clean_text, voice=voice, rate=rate)
    await communicate.save(cache_file)
    return cache_file

@app.post("/api/audio/tts")
async def get_audio_tts(req: TTSReq):
    try:
        audio_path = await generate_edge_tts_audio(req.text, req.voice or "de-DE-KatjaNeural", req.rate or "+0%")
        return FileResponse(audio_path, media_type="audio/mpeg", filename="speech.mp3")
    except Exception as e:
        raise HTTPException(500, f"TTS synthesis failed: {str(e)}")
```

- [ ] **Step 4: Run pytest and verify passes**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt server.py test_server.py
git commit -m "feat(tts): add edge-tts neural voice synthesis with local disk caching"
```

---

### Task 2: 前端高清神经音频播放与双轨回退 (Frontend Neural Audio & ShadowPlayer Integration)

**Files:**
- Modify: `static/app.js`
- Modify: `static/index.html`

**Interfaces:**
- Updates: `ShadowPlayer.speakCurrentSentence()` 优先请求 `/api/audio/tts` 使用 `HTML5 Audio` 播放；若失败则自动回退至浏览器 `SpeechSynthesis`。
- UI: 播控栏增加音色切换器 `[ 👩 Katja 女声 | 👨 Conrad 男声 ]`。

- [ ] **Step 1: Add Voice Selector to `#shadow-player` in `static/index.html`**

```html
      <div class="voice-pill">
        <button id="voice-btn-katja" class="voice-btn active" onclick="ShadowPlayer.setVoice('de-DE-KatjaNeural')" title="清脆自然女声 (Katja)">👩 女声</button>
        <button id="voice-btn-conrad" class="voice-btn" onclick="ShadowPlayer.setVoice('de-DE-ConradNeural')" title="沉稳磁性男声 (Conrad)">👨 男声</button>
      </div>
```

- [ ] **Step 2: Update `ShadowPlayer` to use Neural Audio with fallback in `static/app.js`**

```javascript
const ShadowPlayer = {
  isPlaying: false,
  currentSentIdx: 0,
  mode: 'shadow',
  rate: 0.88,
  voice: 'de-DE-KatjaNeural',
  audioEl: null,
  pauseTimer: null,

  init() {
    this.audioEl = new Audio();
  },

  setVoice(voice) {
    this.voice = voice;
    document.querySelectorAll('.voice-btn').forEach(b => {
      b.classList.toggle('active', (b.id === 'voice-btn-katja' && voice.includes('Katja')) || (b.id === 'voice-btn-conrad' && voice.includes('Conrad')));
    });
    if (this.isPlaying) this.replay();
  },

  speakCurrentSentence() {
    if (!this.isPlaying || !currentArticle || !currentArticle.sentences) return;
    if (this.currentSentIdx >= currentArticle.sentences.length) {
      this.pause();
      this.currentSentIdx = 0;
      return;
    }

    const sent = currentArticle.sentences[this.currentSentIdx];
    if (!sent) return;

    this.highlightSentence(this.currentSentIdx);
    this.updateStatusText();

    if (this.audioEl) {
      this.audioEl.pause();
      this.audioEl.removeAttribute('src');
    }

    // Convert speed rate float (e.g. 0.88) to edge-tts format (e.g. "-12%")
    const ratePercent = Math.round((this.rate - 1.0) * 100);
    const rateStr = ratePercent >= 0 ? `+${ratePercent}%` : `${ratePercent}%`;

    // 优先尝试后端高保真 Edge Neural TTS
    fetch('/api/audio/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: sent.text, voice: this.voice, rate: rateStr })
    }).then(resp => {
      if (!resp.ok) throw new Error('Neural TTS network error');
      return resp.blob();
    }).then(blob => {
      const audioUrl = URL.createObjectURL(blob);
      this.audioEl.src = audioUrl;
      const startTime = Date.now();

      this.audioEl.onended = () => {
        URL.revokeObjectURL(audioUrl);
        if (!this.isPlaying) return;
        const duration = Date.now() - startTime;
        this.handleSentenceFinished(duration);
      };

      this.audioEl.onerror = () => {
        this.fallbackWebSpeech(sent);
      };

      this.audioEl.play().catch(() => this.fallbackWebSpeech(sent));
    }).catch(() => {
      this.fallbackWebSpeech(sent);
    });
  },

  handleSentenceFinished(duration) {
    if (this.mode === 'loop') {
      this.pauseTimer = setTimeout(() => this.speakCurrentSentence(), 700);
    } else if (this.mode === 'shadow') {
      const pauseMs = Math.max(2000, Math.min(6000, duration * 1.1));
      this.showPauseCountdown(pauseMs);
      this.pauseTimer = setTimeout(() => {
        if (!this.isPlaying) return;
        this.currentSentIdx++;
        this.speakCurrentSentence();
      }, pauseMs);
    } else {
      this.pauseTimer = setTimeout(() => {
        if (!this.isPlaying) return;
        this.currentSentIdx++;
        this.speakCurrentSentence();
      }, 350);
    }
  },

  fallbackWebSpeech(sent) {
    // 极端离线回退至浏览器内置 SpeechSynthesis
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(sent.text.trim());
    utt.lang = 'de-DE';
    utt.rate = this.rate;
    const startTime = Date.now();
    utt.onend = () => {
      if (!this.isPlaying) return;
      this.handleSentenceFinished(Date.now() - startTime);
    };
    window.speechSynthesis.speak(utt);
  }
};
```

- [ ] **Step 3: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat(audio): integrate edge neural voice playback with offline speech fallback"
```

---

### Task 3: 划选浮动批注胶囊与高亮数据持久化 (Selection Tooltip & Highlight DB)

**Files:**
- Modify: `server.py`
- Test: `test_server.py`
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`

**Interfaces:**
- Table: `reading_notes` in SQLite:
  - `(id INTEGER PRIMARY KEY, article_id INTEGER, sentence_id INTEGER, selected_text TEXT, color TEXT, note_content TEXT, created_at DATETIME)`
- Endpoints:
  - `GET /api/articles/{id}/notes` -> List of notes/highlights
  - `POST /api/articles/{id}/notes` -> Create note/highlight
  - `DELETE /api/notes/{id}` -> Remove note/highlight
- UI: 选中文字后弹出浮动工具栏 `#selection-tooltip`：`[ 🟡 黄色高亮 | 🟢 绿色高亮 | 📝 添加笔记 | 🔊 朗读 ]`

- [ ] **Step 1: Write DB Schema & Note Endpoints in `server.py` and test in `test_server.py`**

在 `server.py` 的 `init_db()` 中建表：
```sql
CREATE TABLE IF NOT EXISTS reading_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    sentence_id INTEGER,
    selected_text TEXT NOT NULL,
    color TEXT DEFAULT 'yellow',
    note_content TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

编写 CRUD 路由并添加 `pytest` 测试。

- [ ] **Step 2: Implement Selection Tooltip HTML & CSS in `static/index.html` and `static/style.css`**

```html
<!-- ── Selection Floating Tooltip ──────────────────────────── -->
<div id="selection-tooltip" class="selection-tooltip hidden">
  <button class="hl-color-btn hl-yellow" onclick="applyHighlight('yellow')" title="黄色荧光笔"></button>
  <button class="hl-color-btn hl-green" onclick="applyHighlight('green')" title="绿色荧光笔"></button>
  <button class="hl-color-btn hl-pink" onclick="applyHighlight('pink')" title="粉色重点笔"></button>
  <span class="typo-sep"></span>
  <button class="tooltip-action-btn" onclick="openNoteFromSelection()">📝 记笔记</button>
  <button class="tooltip-action-btn" onclick="playSelectedAudio()">🔊 朗读</button>
</div>
```

```css
/* Selection Tooltip */
.selection-tooltip {
  position: absolute;
  z-index: 60;
  transform: translate(-50%, -100%);
  background: var(--stage);
  color: #FEF9EE;
  padding: 4px 8px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}
.hl-color-btn {
  width: 18px; height: 18px;
  border-radius: 50%;
  border: 1.5px solid #fff;
  cursor: pointer;
}
.hl-yellow { background: #FFE885; }
.hl-green  { background: #B4E8B0; }
.hl-pink   { background: #FFB8B8; }
```

- [ ] **Step 3: Implement selection handling and persistence in `static/app.js`**

- [ ] **Step 4: Commit**

```bash
git add server.py test_server.py static/index.html static/style.css static/app.js
git commit -m "feat(notes): add selection tooltip and persistent highlight annotations"
```

---

### Task 4: 段落拟物便签贴纸与 AI 速记辅助 (Margin Sticky Notes & AI Assist)

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`
- Modify: `server.py`

**Interfaces:**
- Produces: `POST /api/ai/note-assist`
  - Input: `{"sentence": str, "selected_text": str}`
  - Output: `{"summary_zh": str, "key_points": List[str]}`
- UI: 段落右侧显示微型便签贴纸图标 `📌 笔记`，点击滑出便签编辑框。

- [ ] **Step 1: Add AI Note Assist endpoint in `server.py` and test in `test_server.py`**

```python
SYSTEM_NOTE_PROMPT = """你是一位资深德语精读私教。
请根据给定的德语句子和选中的文本，为学习者生成精准的中文精读随笔备忘要点（包括句法结构、短语搭配及地道翻译）。
以 JSON 格式输出：
{
  "summary_zh": "中文一句话精读解析",
  "key_points": ["要点1", "要点2"]
}"""
```

- [ ] **Step 2: Implement Margin Sticky Note badges & Note Drawer in `static/app.js`**

- [ ] **Step 3: Commit**

```bash
git add server.py test_server.py static/index.html static/style.css static/app.js
git commit -m "feat(notes): add margin sticky note badges and AI note-taking assist"
```

---

### Task 5: 全文精读讲义 Markdown 导出与全量备份同步 (Study Guide Export & Backup Sync)

**Files:**
- Modify: `server.py`
- Modify: `static/index.html`
- Modify: `static/app.js`
- Test: `test_server.py`

**Interfaces:**
- Produces: `GET /api/articles/{id}/export-guide` -> Markdown file download
- Updates: `GET /api/backup/export` & `POST /api/backup/restore` 包含 `reading_notes` 表。

- [ ] **Step 1: Add Study Guide Markdown generator in `server.py`**

```python
@app.get("/api/articles/{article_id}/export-guide")
def export_study_guide(article_id: int):
    with get_db() as conn:
        art = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not art:
            raise HTTPException(404, "Article not found")
        notes = conn.execute("SELECT * FROM reading_notes WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()
        vocab = conn.execute("SELECT * FROM vocab_cards WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()
        grammar = conn.execute("SELECT * FROM grammar_cards WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()

    md = [f"# {art['title']} — DeLector 精读讲义\n"]
    md.append(f"> 导出日期: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 字符数: {len(art['raw_text'])}\n")
    
    if notes:
        md.append("## 📝 精读随笔与重点批注\n")
        for n in notes:
            md.append(f"- **高亮原句**: *{n['selected_text']}*")
            if n['note_content']:
                md.append(f"  - 💡 **随笔笔记**: {n['note_content']}")
        md.append("")

    if vocab:
        md.append("## 🗂️ 核心生词表\n")
        md.append("| 单词 | 原型 | 词性 | CEFR | 中文释义 | 原文语境 |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for v in vocab:
            md.append(f"| **{v['word']}** | {v['lemma']} | {v['pos']} | {v['cefr_level']} | {v['definition_zh']} | *{v['sentence_context']}* |")
        md.append("")

    if grammar:
        md.append("## 🎓 歌德考点深度解析\n")
        for g in grammar:
            md.append(f"### ✦ {g['grammar_name']} ({g['cefr_level']})")
            if g['rule_formula']:
                md.append(f"- **语法公式**: `{g['rule_formula']}`")
            md.append(f"- **解析**: {g['explanation_zh']}")
            md.append(f"- **例句**: *{g['sentence_context']}*\n")

    content = "\n".join(md)
    return Response(content=content, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=study_guide_{article_id}.md"})
```

- [ ] **Step 2: Update Backup Export/Restore in `server.py` to include `reading_notes`**

- [ ] **Step 3: Add Export Guide button in `static/index.html` reader topbar**

- [ ] **Step 4: Run pytest**

Run: `pytest test_server.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py test_server.py static/index.html static/app.js
git commit -m "feat(export): add one-click Markdown study guide export and full DB backup sync"
```

---

### Task 6: 全链路测试与安全验收 (E2E Verification & Security Guard)

**Files:**
- Test: `test_server.py`

- [ ] **Step 1: Run complete pytest suite**

Run: `pytest -v`  
Expected: 100% PASS

- [ ] **Step 2: Scan for secret key leaks using strict regex rule**

Run:
```bash
grep -nE '(sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)' server.py static/app.js test_server.py
```
Expected: 0 matches found.

- [ ] **Step 3: Live Verification in Browser**

1. 打开 `http://localhost:8000`，播放德语句子，验证播音员级 Katja / Conrad 神经人声。
2. 选中文本，验证浮动工具条弹出、彩色荧光划线与侧边便签贴纸。
3. 记笔记并调用 AI 速记辅助，在文章末尾导出 Markdown 讲义。
