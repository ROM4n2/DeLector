# DeLector v3.0 Phase 1: 智能完形填空实战与 SuperMemo SM-2 艾宾浩斯记忆排程

## 🎯 目标与交付物
在 v2.1（文库·3D翻牌盒·横向台账）的坚实基础上，引入：
1. **智能完形填空生成与判分引擎 (Lückentext / C-Test Engine)**：
   - 模式一：**语法考点定向挖空**（介词与格、从句连词、动词变位、形容词词尾）
   - 模式二：**生词盲填强化**（根据当前文章或词库中的生词挖空）
   - 模式三：**经典 C-Test 真题模式**（德福 / DSH 标准隔词去尾挖空）
   - 即时提交、智能判题、语法原理解析与错题一键入库。
2. **SuperMemo SM-2 艾宾浩斯智能排程引擎**：
   - 拓展 `vocab_cards` 与 `grammar_cards`：引入 `due_date`（到期时间）、`interval_days`（复习间隔）、`ease_factor`（难度系数 EF，默认 2.5）、`repetition_count`（复习轮次）。
   - 自测完成或卡片翻面时支持 4 级难度评分（`1 重来/Forgot`、`2 困难/Hard`、`3 良好/Good`、`4 简单/Easy`），自动计算下一次复习到期日。
   - 卡片库增加「今日待复习 (Due Today)」智能筛选，台账增加记忆保留率与艾宾浩斯排程看板。

---

## 🛠️ 任务分解 (Tasks)

### Task 1: 后端 SM-2 算法实现与卡片数据库迁移
- **文件**: `server.py`, `test_server.py`
- **内容**:
  1. 数据库升级：为 `vocab_cards` 和 `grammar_cards` 增加 `due_date`, `interval_days`, `ease_factor`, `repetition_count` 字段。
  2. 实现 SM-2 核心计算函数 `calculate_sm2(grade: int, rep: int, interval: int, ef: float) -> Tuple[int, int, float, str]`。
  3. 新增 `POST /api/cards/{card_type}/{card_id}/review` 端点接收评分并更新排程。
  4. 新增 `GET /api/cards/due` 端点返回今日到期卡片。
  5. 编写完整单元测试，验证 SM-2 在各评分下的间隔增长与 EF 衰减。

### Task 2: 德语文章智能完形填空生成器与判分后端
- **文件**: `server.py`, `test_server.py`
- **内容**:
  1. 实现 `generate_cloze_exercise(text: str, mode: str = "grammar")`：
     - `grammar`: 基于 spaCy POS 和 dep 挖出介词（ADP）、连词（SCONJ/CCONJ）、助动词（AUX）、形容词（ADJ）。
     - `vocab`: 挖出非 A1 的 B1/B2 核心实词（NOUN/VERB）。
     - `ctest`: 从第 2 句开始，隔 2 词对偶数词截断后半部分（如 `Schul___`）。
  2. 新增 `POST /api/articles/{article_id}/exercise/cloze` 生成试题。
  3. 新增 `POST /api/exercise/cloze/evaluate` 接收用户填空并自动比对判分，记录至 `progress.db` 的 `study_log`。
  4. 编写完整单元测试。

### Task 3: 前端阅读器文章「⚔ 完形实战」交互弹窗
- **文件**: `static/index.html`, `static/style.css`, `static/app.js`
- **内容**:
  1. 阅读器顶部增加 `[ ⚔ 完形实战 (LÜCKENTEXT) ]` 入口按钮。
  2. 设计包豪斯社论风格全屏/模态弹窗 `#cloze-overlay`：
     - 顶部：三种模式切换标签（`[ 语法挖空 ]`、`[ 生词填空 ]`、`[ 经典 C-Test ]`）。
     - 中部：文章填空正文，挖空处为内嵌等宽输入框，支持 `Tab` 键快速跳转下一个空。
     - 底部：`[ 提示首字母 ]` · `[ 提交答案 ]` · `[ 重置 ]`。
  3. 提交后：正确标绿、错误标红并显现原词解析，一键收录错题为复习卡片。

### Task 4: 前端卡片库与学术台账集成 SM-2 排程视图
- **文件**: `static/index.html`, `static/app.js`, `static/style.css`
- **内容**:
  1. 卡片库分段栏新增 `[ 今日到期 DUE (N) ]` 智能过滤器。
  2. 3D 扑克卡片背面与考验模式增加 4 级反馈评分按钮（`[ 1 重来 ] [ 2 困难 ] [ 3 良好 ] [ 4 简单 ]`），点击即时触发 SM-2 计算。
  3. 学术台账 Leporello Folio 的指标行与走字带增加 `[ DUE: N KARTEN HEUTE ]`（今日待复习提醒）。
