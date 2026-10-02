# DeLector 德语形态学与深度语法引擎实施方案 (v3.4.0)

## 概述
作为**本地优先（Local-First）**极致德语精读瑞士军刀的长远演进核心，v3.4.0 引入**三位一体德语深度语言学引擎**：
1. **德语长复合词智能拆解（Komposita-Zerlegung）**：递归拆解复合名词并识别连接词素（Fugenelemente: `-s-`, `-en-`, `-e-` 等），抽屉中各子词可独立查看与一键制卡。
2. **歌德 180+ 强变化/不规则动词三态表（Stammformen & Hilfsverb）**：收录考纲常考强变化动词三态（原形、过去时、完成时过去分词）与助动词（`haben` vs `sein`），任何变位形式均可反查并自动附入 Anki 卡片。
3. **可分动词框形结构追踪（Trennbare Verben & Satzklammer）**：利用 spaCy 依存句法树提取前缀与变位动词对（如 `steigt ... ein` ➔ `einsteigen`），实现阅读器双向高亮与自动还原原形入库。

---

## 架构与技术设计

### 1. 语言学数据层 (`linguistics.py`)
新建独立轻量模块 `linguistics.py`：
- **`IRREGULAR_VERBS` 知识库**：收录 180+ 歌德 A1-C1 强变化动词，结构为：
  ```python
  "gehen": ("ging", "gegangen", "ist", "走，去"),
  "nehmen": ("nahm", "genommen", "hat", "拿，选用"),
  "steigen": ("stieg", "gestiegen", "ist", "上升，攀登"),
  ...
  ```
  提供双向反查索引：输入 `ging` 或 `gegangen` 均能瞬间定位 `gehen`。
- **`split_komposita(word)` 复合词拆解器**：
  - 基于 `core_dict` 词库与常见德语词素进行自前向后与自后向前的双向递归匹配。
  - 自动剥离连接词素（`s`, `es`, `en`, `er`, `e`）。
  - 返回各子词的原型、词性、冠词与释义。

### 2. 后端 API 扩展 (`server.py`)
- **句子处理流水线升级 (`process_german_text`)**：
  - 遍历 spaCy 依存关系，检测 `compound:prt` / `svp` 依存弧，将主句动词与句末可分前缀关联，生成 `separable_info: {prefix_tok_id, verb_tok_id, full_lemma}`。
- **词汇查询升级 (`POST /api/lookup/vocab`)**：
  - 若为动词：自动附加 `stammformen: {infinitiv, praeteritum, partizip2, hilfsverb}`。
  - 若为复合词：自动附加 `komposita: [{word, lemma, gender, def_zh}]`。

### 3. 前端交互与视觉联动 (`static/js/reader.js`, `static/style.css`)
- **抽屉卡片增强**：
  - 动词悬停：顶部展示醒目 `⚡ 强变化三态: gehen — ging — ist gegangen` 徽章。
  - 复合词悬停：展示 `🧩 复合词拆解: [Klima (中性)] + -s- + [Schutz (阳性)]` 交互胶囊，点击子词直接就地查词/制卡。
- **可分动词阅读器联动**：
  - 点击 `steigt` 或 `ein` 时，两处 Token 同时激活 `linked-separable` 虚线框荧光，消除从句断读障碍。

---

## 实施文件清单
- `linguistics.py`：动词三态表与复合词拆解算法
- `server.py`：接入语言学引擎与 spaCy 可分动词关联
- `static/js/reader.js`：三态表与复合词胶囊交互
- `static/style.css`：语言学胶囊与高亮样式
- `test_server.py`：覆盖语言学引擎的单元测试
