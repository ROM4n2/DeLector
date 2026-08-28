# server.py 拆分重构计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 3053 行的 `server.py` 按职责拆分为 4 个模块，每个模块职责单一、边界清晰。重构不改变任何行为，316 测试必须全绿。

**Architecture:** `server.py` 保留 `app` 对象 + 路由注册 + 中间件 + 静态文件。逻辑按职责分到 `nlp.py`（NLP/CEFR）、`database.py`（DB/CRUD/备份）、`security.py`（SSRF/URL安全）。`server.py` 通过 import 从新模块拉取函数，对外 API（`app`、函数名）保持不变。

**Tech Stack:** Python 3.11, FastAPI, spaCy, SQLite

**验收标准:** 316 测试全绿，`start.py` 正常启动，所有 API 端点行为不变。

---

## 拆分映射

### `nlp.py`（~400 行）— NLP 引擎 + CEFR

从 `server.py` 搬出：

| 行范围 | 内容 |
|---|---|
| 24-27 | `import spacy`（try/except） |
| 334-336 | `import importlib` / `from pathlib import Path` / `from start import is_android` |
| 340-341 | `SPACY_MODEL_CANDIDATES`, `AUTO_DOWNLOAD_MODEL` |
| 343-380 | `_load_spacy_model()` |
| 382-414 | `nlp`, `NLP_ENGINE`, `NLP_ENGINE_DETAIL`（模块加载副作用） |
| 416-460 | `CEFR_DICT` |
| 467-490 | `get_cefr_level()` |
| 493-527 | `calculate_cefr_stats()` |
| 529-567 | `_process_german_text_pure_python()` |
| 569-636 | `process_german_text()` |
| 1114-1128 | `SYSTEM_GRAMMAR_PROMPT`（语法查询路由用到） |

依赖的 import（搬进 `nlp.py`）：
```python
import re
from typing import Dict, Any
from core_dict import lookup_core_vocab, get_core_cefr_level
from linguistics import (lookup_irregular_verb, lookup_linguistics_ext, split_komposita,
                         lookup_prep_collocations, build_prep_matrix)
from syntax_tree import (analyze_sentence_topology, build_clause_tree,
                         analyze_syntax_tree, split_sentences_pure_python)
```

导出（`server.py` 通过 `from nlp import ...` 拿到）：
```python
nlp, NLP_ENGINE, NLP_ENGINE_DETAIL,
get_cefr_level, calculate_cefr_stats,
process_german_text, SYSTEM_GRAMMAR_PROMPT
```

### `database.py`（~900 行）— DB + CRUD + 备份

从 `server.py` 搬出：

| 行范围 | 内容 |
|---|---|
| 54-61 | `DATA_DIR`, `AUDIO_CACHE_DIR`, `DATABASE_PATH`, `PROGRESS_DB_PATH` |
| 63-270 | `get_db_path`, `get_progress_db_path`, `get_db`, `get_progress_db`, `init_progress_db`, `log_study_event`, `init_db` |
| 271-297 | `get_setting`, `set_setting`, `get_effective_api_key/base_url/model` |
| 298-332 | `PRESET_ARTICLES`, `ingest_article`, `seed_preset_articles` |
| 640-660 | `VOCAB_MODEL`, `GRAMMAR_MODEL`（Anki 模型定义） |
| 661-694 | `export_anki_deck()` |
| 1710-1743 | `get_cache_info()`, `prune_audio_cache()` |
| 2110-2131 | `_require_localhost()`, `_rows_to_tuples()` |
| 2133-2163 | `build_backup_payload()` |
| 2252-2353 | `_db_snapshot_guard()`, `_replace_tables()` |
| 2354-2359 | `CardReviewReq`（review 路由的模型） |

依赖的 import（搬进 `database.py`）：
```python
import os, json, sqlite3, secrets, shutil, tempfile
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from fastapi import HTTPException, Request
import genanki
from nlp import get_cefr_level, nlp, process_german_text
from core_dict import lookup_core_vocab
```

### `security.py`（~200 行）— SSRF + URL 安全

从 `server.py` 搬出：

| 行范围 | 内容 |
|---|---|
| 778-863 | `_resolve_ssrf_targets()`, `_is_blocked_addr()`, `is_safe_public_url()` |
| 864-920 | `clean_html_to_article()`, `fetch_remote_html()` |
| 993-1051 | `parse_rss_feed()` |
| 2175-2183 | `PrepareBackupReq`（不影响 security，但跟 `_require_localhost` 配对） |

依赖的 import：
```python
import re, html, socket, ipaddress
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse
import httpx
```

### `server.py`（~600 行）— 路由骨架

保留：
- `load_env()` + 启动逻辑
- `app = FastAPI(...)` + 中间件 + 静态文件挂载
- 所有 `@app.xxx` 路由函数（只保留函数体，调用新模块的函数）
- 所有 `class XxxReq(BaseModel)` 请求模型

通过 import 拿到所有拆出去的函数：
```python
from nlp import (nlp, NLP_ENGINE, NLP_ENGINE_DETAIL,
                 get_cefr_level, process_german_text,
                 calculate_cefr_stats, SYSTEM_GRAMMAR_PROMPT)
from database import (init_db, get_db, get_db_path, get_progress_db,
                      get_setting, set_setting, get_effective_api_key, ...)
from security import (is_safe_public_url, clean_html_to_article, ...)
```

---

## 依赖关系图

```
server.py
  ├── nlp.py         (纯计算，无 DB 依赖)
  ├── database.py    (依赖 nlp.py: get_cefr_level, process_german_text)
  └── security.py    (独立，仅依赖 httpx)
```

**无环**：nlp → database → server 三个模块不形成环。database 依赖 nlp（文本分析），nlp 不依赖 database。

---

## 向后兼容

1. `test_server.py` 从 `server` 导入函数 → 在 `server.py` 里 `from nlp import ...` / `from database import ...` / `from security import ...`，`server.py` 的 namespace 自然包含这些名字，测试不需要改
2. `start.py` 导入 `from server import app` → `app` 仍在 `server.py`，不变
3. `test_server.py` 有 `import server` 然后访问 `server.nlp` / `server.NLP_ENGINE` → 这些名字通过 `from nlp import ...` 进入 `server.py` 的 namespace，`server.nlp` 仍然可达

---

## 执行阶段

### Phase 1：建 `nlp.py`

**Files:** Create `nlp.py`, Modify `server.py`

1. 创建 `nlp.py`，把上述函数和常量搬过去
2. `server.py` 改为 `from nlp import ...`
3. 运行 `python -m pytest -q` → 316 passed
4. `python start.py` 确认启动正常
5. Commit: `refactor(nlp): extract NLP engine, CEFR, text processing into nlp.py`

### Phase 2：建 `database.py`

**Files:** Create `database.py`, Modify `server.py`

1. 创建 `database.py`，搬 DB/CRUD/备份相关函数
2. `server.py` 改为 `from database import ...`
3. 运行 `python -m pytest -q` → 316 passed
4. `python start.py` 确认启动正常
5. Commit: `refactor(db): extract DB, CRUD, backup into database.py`

### Phase 3：建 `security.py`

**Files:** Create `security.py`, Modify `server.py`

1. 创建 `security.py`，搬 SSRF/URL 安全/HTML 清洗/RSS 解析
2. `server.py` 改为 `from security import ...`
3. 运行 `python -m pytest -q` → 316 passed
4. `python start.py` 确认启动正常
5. Commit: `refactor(security): extract SSRF, URL safety, HTML cleaning into security.py`

### Phase 4：清理 + 验收

**Files:** Modify `server.py`

1. 检查 `server.py` 里有没有残留的死代码（被搬走但 import 仍在的旧函数）
2. `pyflakes` 检查所有新模块
3. 全量 `python -m pytest -q` → 316 passed
4. `python start.py` 启动，浏览器走一遍：文章导入、卡片复习、自测、写作台
5. Commit: `refactor: cleanup dead code after module split, verify all 316 tests`

---

## 风险

| 风险 | 缓解 |
|---|---|
| 模块加载顺序导致 NLP 模型在不该初始化时初始化 | `nlp.py` 的 spaCy 加载是顶层副作用（跟现在 server.py 一样），import 时自动执行，无变化 |
| `database.py` 导入 `nlp.py` 触发 spaCy 加载 | 这跟现在 `import server` 时 spaCy 加载完全一样，没有新增风险 |
| 循环导入 | 依赖图无环：nlp 不依赖 database，database 依赖 nlp |
| 测试 import 路径变化 | `server.py` 通过 `from nlp import ...` 重导出，`import server` 后的属性访问不变 |
