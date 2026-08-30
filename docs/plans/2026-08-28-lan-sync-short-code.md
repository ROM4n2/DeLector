# 局域网同步 — 6 位短码替代 SDP 复制粘贴

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 WebRTC P2P 同步的 SDP 复制粘贴流程改为 6 位短码输入。A 设备存 SDP 到服务端拿到短码，B 设备输入短码取出 SDP。手机上只需输入6个字符，不再复制粘贴 2-3KB 文本。

**Architecture:** 新增 `/api/wb/sync/store`（POST 存 SDP，返回6位码）和 `/api/wb/sync/fetch/{code}`（GET 取 SDP）两个临时端点。前端 UI 把 textarea 改成小输入框 + 大字显示码。WebRTC P2P 逻辑不变，只是 SDP 传递方式从复制粘贴变成短码中转。

**Tech Stack:** FastAPI, secrets, 现有 WebRTC P2P

**验收标准:** 319 测试全绿，手机上输入6位码即可完成同步。

---

## 数据流

```
A 设备                          服务端                        B 设备
  │                               │                             │
  │  ① createOffer()              │                             │
  │  ② POST /api/wb/sync/store   │                             │
  │     body: {sdp, role:"offer"} │                             │
  │  ← {code: "K7M2X9"}          │                             │
  │                               │                             │
  │  显示 "K7M2X9"                │     ③ 输入 "K7M2X9"         │
  │                               │  ← GET /wb/sync/fetch/K7M2X9│
  │                               │  → {sdp: ...}               │
  │                               │     ④ setRemoteDescription   │
  │                               │     ⑤ createAnswer()         │
  │                               │     ⑥ POST /wb/sync/store    │
  │                               │        body: {sdp, role:"answer"}│
  │                               │     ← {code: "P3R8N2"}       │
  │                               │                             │
  │  ⑦ 输入 "P3R8N2"              │  ← GET /wb/sync/fetch/P3R8N2│
  │  ← {sdp: ...}                │                             │
  │  ⑧ setRemoteDescription       │                             │
  │  ⑨ DataChannel open → 发数据  │────────────────────────────→ │
  │                               │              自动合并         │
```

---

## 文件变更

| 文件 | 改动 |
|---|---|
| `database.py` | 新增 `sync_sdp` 内存缓存（dict + TTL 清理） |
| `server.py` | 新增 `POST /api/wb/sync/store` + `GET /api/wb/sync/fetch/{code}` |
| `static/german/workbench.html` | UI 从 textarea 改为小输入框 + 大字码显示；JS 调新 API |

---

### Task 1: 服务端 — SDP 临时存储 + 短码

**Files:**
- Modify: `server.py`

**Interfaces:**
- Produces: `POST /api/wb/sync/store` → `{"code": "K7M2X9"}`；`GET /api/wb/sync/fetch/{code}` → `{"sdp": ...}`

内存缓存，5 分钟 TTL，不落盘。同步是瞬时操作，不需要持久化。

- [x] **Step 1: 新增 SDP 缓存**

在 `server.py` 里加：

```python
import secrets as _secrets  # 已有 import secrets

# WebRTC SDP 临时缓存（5 分钟 TTL，内存级，不同步落盘）
_sync_sdp_cache: Dict[str, Dict[str, Any]] = {}  # code → {sdp, ts}

def _cleanup_sync_cache():
    """清理过期的 SDP 缓存条目。"""
    now = __import__("time").time()
    expired = [k for k, v in _sync_sdp_cache.items() if now - v["ts"] > 300]
    for k in expired:
        del _sync_sdp_cache[k]
```

- [x] **Step 2: POST /api/wb/sync/store**

```python
class SyncStoreReq(BaseModel):
    sdp: Dict[str, Any]  # RTCSessionDescription 的 dict 形式
    role: str = "offer"   # "offer" | "answer"

@app.post("/api/wb/sync/store")
def sync_store_sdp(req: SyncStoreReq):
    _require_localhost(request) if False else None  # 无 request 参数，跳过
    _cleanup_sync_cache()
    code = _secrets.token_urlsafe(4)[:6].upper()  # 6 位大写字母数字
    _sync_sdp_cache[code] = {"sdp": req.sdp, "ts": __import__("time").time(), "role": req.role}
    return {"code": code}
```

等等，`_require_localhost` 需要 `request` 参数。让我重写：

```python
@app.post("/api/wb/sync/store")
def sync_store_sdp(req: SyncStoreReq, request: Request):
    _require_localhost(request)
    _cleanup_sync_cache()
    code = secrets.token_urlsafe(4)[:6].upper()
    _sync_sdp_cache[code] = {"sdp": req.sdp, "ts": time.time(), "role": req.role}
    return {"code": code}
```

- [x] **Step 3: GET /api/wb/sync/fetch/{code}**

```python
@app.get("/api/wb/sync/fetch/{code}")
def sync_fetch_sdp(code: str, request: Request):
    _require_localhost(request)
    _cleanup_sync_cache()
    entry = _sync_sdp_cache.get(code.upper())
    if not entry:
        raise HTTPException(404, "短码无效或已过期（5 分钟有效）")
    # 取一次即销毁（一次性）
    del _sync_sdp_cache[code.upper()]
    return {"sdp": entry["sdp"], "role": entry["role"]}
```

- [x] **Step 4: 测试**

```bash
python -m pytest -q -k "version_is_consistent" 2>&1 | tail -3
```

---

### Task 2: 前端 — UI 改为短码输入

**Files:**
- Modify: `static/german/workbench.html`

**Interfaces:**
- Consumes: `POST /api/wb/sync/store` + `GET /api/wb/sync/fetch/{code}`
- Produces: 用户看到6位码，输入对方码即可

- [x] **Step 1: 改 HTML — A 设备面板**

把 textarea 替换为大字码显示 + 输入框：

```html
<div id="lanStepA" style="margin-top:10px">
  <button class="btn sm ghost" id="btnLanOffer">① 生成短码</button>
  <div id="lanOfferDisplay" style="display:none;margin-top:8px;text-align:center">
    <div style="font-size:2rem;font-family:Consolas,monospace;letter-spacing:0.3em;color:var(--accent);font-weight:700" id="lanOfferCode">—</div>
    <button class="btn sm ghost" id="btnLanCopyOffer" style="margin-top:4px">复制短码</button>
  </div>
  <div style="margin-top:12px">
    <label style="font-size:13px;display:block;margin-bottom:4px">② 输入对方的短码：</label>
    <input type="text" id="lanAnswerIn" maxlength="6" style="width:160px;font-size:1.25rem;font-family:Consolas,monospace;letter-spacing:0.2em;text-transform:uppercase;text-align:center" placeholder="XXXXXX">
    <button class="btn sm ghost" id="btnLanAcceptAnswer" style="margin-top:4px">③ 确认连接并发送</button>
  </div>
</div>
```

- [x] **Step 2: 改 HTML — B 设备面板**

```html
<div id="lanStepB" style="margin-top:10px;display:none">
  <label style="font-size:13px;display:block;margin-bottom:4px">① 输入对方的短码：</label>
  <input type="text" id="lanOfferIn" maxlength="6" style="width:160px;font-size:1.25rem;font-family:Consolas,monospace;letter-spacing:0.2em;text-transform:uppercase;text-align:center" placeholder="XXXXXX">
  <button class="btn sm ghost" id="btnLanAcceptOffer" style="margin-top:4px">② 获取邀请并生成回执</button>
  <div id="lanAnswerDisplay" style="display:none;margin-top:8px;text-align:center">
    <div style="font-size:2rem;font-family:Consolas,monospace;letter-spacing:0.3em;color:var(--accent);font-weight:700" id="lanAnswerCode">—</div>
    <button class="btn sm ghost" id="btnLanCopyAnswer" style="margin-top:4px">复制短码</button>
  </div>
  <p class="hint" style="margin-top:8px;color:var(--muted)">③ 等待 A 输入你的短码，传输完成后自动 toast。</p>
</div>
```

- [x] **Step 3: 改 JS — A 生成 Offer**

把 `btnLanOffer` 的 click handler 改为调 API：

```javascript
$("btnLanOffer").addEventListener("click", async () => {
  if (_lanPC && _lanPC.signalingState === "have-local-offer" && _lanPC.localDescription) {
    lanSetStatus("已生成短码，请直接输入对方的短码");
    return;
  }
  if (_lanPC) try { _lanPC.close(); } catch (e) {}
  _lanPC = new RTCPeerConnection({ iceServers: [] });
  _lanDC = _lanPC.createDataChannel("sync");
  setupDataChannel(_lanDC, true);
  _lanPC.oniceconnectionstatechange = () => lanSetStatus("ICE: " + _lanPC.iceConnectionState);
  try {
    const offer = await _lanPC.createOffer();
    await _lanPC.setLocalDescription(offer);
    await new Promise(r => { let d = false; const t = setTimeout(() => { if (!d) { d = true; r(); } }, 5000); _lanPC.onicecandidate = e => { if (!e.candidate && !d) { d = true; clearTimeout(t); r(); } }; });
    // 存到服务端，拿到短码
    const resp = await fetch("/api/wb/sync/store", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sdp: _lanPC.localDescription, role: "offer" })
    }).then(r => r.json());
    $("lanOfferDisplay").style.display = "block";
    $("lanOfferCode").textContent = resp.code;
    lanSetStatus("短码已生成，告诉对方输入这个码");
  } catch (e) {
    lanSetStatus("生成失败: " + e.message);
  }
});
```

- [x] **Step 4: 改 JS — A 接受 Answer**

```javascript
$("btnLanAcceptAnswer").addEventListener("click", async () => {
  if (!_lanPC) { lanSetStatus("请先点击①生成短码"); return; }
  if (_lanPC.signalingState !== "have-local-offer") {
    lanSetStatus("状态异常（" + _lanPC.signalingState + "），请重新生成短码");
    return;
  }
  const code = $("lanAnswerIn").value.trim().toUpperCase();
  if (!code || code.length !== 6) { lanSetStatus("请输入6位短码"); return; }
  try {
    const resp = await fetch("/api/wb/sync/fetch/" + code).then(r => r.json());
    await _lanPC.setRemoteDescription(resp.sdp);
    lanSetStatus("已连接，等待 DataChannel…");
  } catch (e) {
    lanSetStatus("短码无效或已过期: " + e.message);
  }
});
```

- [x] **Step 5: 改 JS — B 接受 Offer**

```javascript
$("btnLanAcceptOffer").addEventListener("click", async () => {
  if (_lanPC) try { _lanPC.close(); } catch (e) {}
  _lanPC = new RTCPeerConnection({ iceServers: [] });
  _lanPC.ondatachannel = e => { _lanDC = e.channel; setupDataChannel(_lanDC, false); };
  _lanPC.oniceconnectionstatechange = () => lanSetStatus("ICE: " + _lanPC.iceConnectionState);
  const code = $("lanOfferIn").value.trim().toUpperCase();
  if (!code || code.length !== 6) { lanSetStatus("请输入6位短码"); return; }
  try {
    const resp = await fetch("/api/wb/sync/fetch/" + code).then(r => r.json());
    await _lanPC.setRemoteDescription(resp.sdp);
    const answer = await _lanPC.createAnswer();
    await _lanPC.setLocalDescription(answer);
    await new Promise(r => { let d = false; const t = setTimeout(() => { if (!d) { d = true; r(); } }, 5000); _lanPC.onicecandidate = e => { if (!e.candidate && !d) { d = true; clearTimeout(t); r(); } }; });
    // 存 answer 到服务端
    const ansResp = await fetch("/api/wb/sync/store", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sdp: _lanPC.localDescription, role: "answer" })
    }).then(r => r.json());
    $("lanAnswerDisplay").style.display = "block";
    $("lanAnswerCode").textContent = ansResp.code;
    lanSetStatus("回执短码已生成，告诉对方输入这个码");
  } catch (e) {
    lanSetStatus("短码无效或已过期: " + e.message);
  }
});
```

- [x] **Step 6: 改复制按钮**

复制按钮改为复制大字码：

```javascript
$("btnLanCopyOffer").addEventListener("click", () => {
  const code = $("lanOfferCode").textContent;
  navigator.clipboard?.writeText(code).then(() => toast("已复制短码")).catch(() => toast("复制失败"));
});
$("btnLanCopyAnswer").addEventListener("click", () => {
  const code = $("lanAnswerCode").textContent;
  navigator.clipboard?.writeText(code).then(() => toast("已复制短码")).catch(() => toast("复制失败"));
});
```

- [x] **Step 7: 删除旧 textarea**

删除 `lanOfferOut`、`lanAnswerOut` 两个 textarea，替换为上述 `div` 显示。

- [x] **Step 8: node --check + 测试**

---

### Task 3: 文档 + 测试

**Files:**
- Modify: `test_server.py`（新增 2 条）
- Modify: `AGENTS.md`、`FEATURES.md`

- [x] **Step 1: 测试 POST/GET 往返**

```python
def test_sync_sdp_store_and_fetch():
    """SDP 短码：存入后取出，一次性销毁。"""
    sdp = {"type": "offer", "sdp": "v=0\r\n..."}
    resp = client.post("/api/wb/sync/store", json={"sdp": sdp, "role": "offer"})
    assert resp.status_code == 200
    code = resp.json()["code"]
    assert len(code) == 6
    resp = client.get(f"/api/wb/sync/fetch/{code}")
    assert resp.status_code == 200
    assert resp.json()["sdp"] == sdp
    # 第二次取应该 404（一次性）
    resp = client.get(f"/api/wb/sync/fetch/{code}")
    assert resp.status_code == 404
```

- [x] **Step 2: 测试无效码 404**

```python
def test_sync_sdp_fetch_invalid_code():
    resp = client.get("/api/wb/sync/fetch/ZZZZZZ")
    assert resp.status_code == 404
```

- [x] **Step 3: 全量测试 + 文档**

```bash
python -m pytest -q
```

Expected: 321 passed（319 + 2 新增）

- [x] **Step 4: AGENTS.md / FEATURES.md 回填**

- [ ] **Step 5: Commit**

---

## 手动验证清单

1. A 设备（电脑）点击「生成短码」→ 显示 6 位大字码
2. B 设备（手机）输入这 6 位码 → 点「获取邀请并生成回执」→ 显示回执短码
3. A 设备输入 B 的短码 → 点「确认连接并发送」→ DataChannel 连接 → 数据传输 → 自动合并
4. 全程不需要复制粘贴大段文本，只需告诉对方 6 个字符
