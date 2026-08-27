# Präpositionen-Matrix 设计文档（v4.5.0）

日期：2026-08-27
状态：已与用户确认（三个决策 + 方案 A 均已选定）

---

## 背景与目标

FEATURES.md 里程碑表里唯一标「规划中」的条目：

> **按介词浏览的独立矩阵视图（Präpositionen-Matrix）** — 数据集就位后的零成本增量：
> 按介词维度横向浏览全部搭配

数据集现状（`prep_dict.py`，v4.4.8 补齐后）：**552 词条 / 691 条搭配**，
schema 为 `lemma → [(介词, 格, 中文义, 例句)]`。用户的主要任务是
「我想看 `auf` 都接哪些动词/形容词、各接什么格」——即**按介词分组浏览**，
而不是按 lemma 查询（现有查词抽屉已覆盖后者）。

目标：把这张表以最小的实现量暴露为可浏览、可过滤、可搜索、可入卡的界面，
作为 **v4.5.0** 发布（minor bump 符合「新功能面」语义；FEATURES 里该条目
本就挂在 v4.4+ 名下且前置条件已全部满足）。

## 已确认的设计决策

| 决策点 | 选定 | 未选 |
|---|---|---|
| 视图位置 | **嵌在复习卡片视图里**作为 segment 条第四段「Prepositionen」 | 第 6 个顶级视图（dock 要从 5 键变 6 键）；首页内嵌面板（入口太深） |
| 矩阵形态 | **按介词分组的行列表** + Dat/Akk/Gen 过滤 pill + 搜索框 | 真矩阵网格（实现量大、移动端多一层）；介词卡片墙（与卡盒撞车） |
| SRS 集成深度 | **逐条入卡**（复用 savePrepCollocation 与 /api/cards/vocab） | 整组入卡（诱导一次导入几十张）；纯浏览（错失零成本打通） |
| 索引构建位置 | **方案 A：后端一次性构建 inverted index**，前端全本地交互 | 按需查询（碎片请求）；纯前端循环调 lookup（552 次请求，误用查询 API） |

## 架构

### 数据层（Python）

`linguistics.py` 新增纯函数：

```python
def build_prep_matrix() -> dict:
    """把 PREP_COLLOCATIONS 反转成 {praeposition: {kasus: [entries]}}。

    entry = {
        "lemma": str,            # 小写原键
        "reflexive": bool,       # 中文义含 "(sich)" 或原数据标注
        "bedeutung_zh": str,
        "beispiel": str,
        "cefr": str | None,      # get_cefr_level(lemma)，查不到则 None
    }
    """
```

- 排序：介词按搭配数降序（常用者优先），同组内 lemma 字母序。
- 结果在模块级缓存（函数首次调用后存 module-level 变量），避免每次请求重建。
- 不改 `prep_dict.py` 的 schema，不碰生成工具。

`server.py` 新增只读 endpoint：

```
GET /api/prep/matrix
  -> {"groups": [{"praeposition": "auf", "total": 12,
                  "cases": {"Dat": [...], "Akk": [...]}}]}
```

- 无认证要求变化（该项目为本地优先应用，敏感设置已有回环闸，本端点是公共只读数据）。

### 前端（static/js/cards.js + index.html）

1. **segment 第四段**：卡盒视图现有 `.cards-seg-bar`（due/pending/mastered 三段）
   加一段「Prepositionen」。切换逻辑复用现有 segment 切换代码路径；
   首次激活时 fetch `/api/prep/matrix` 并缓存到模块变量，之后纯本地。
2. **渲染结构**：

   ```
   [Seg: 到期 | 待学 | 已掌握 | Prepositionen]
   [pill: 全部 | Dat | Akk | Gen]  [搜索框]
   ▼ auf · 12 条
     sich freuen (Akk·Freude) — 对…感到高兴 — 例句… [+ 卡]
     verzichten auf (Akk)      — 放弃         — 例句… [+ 卡]
   ▼ mit · 8 条
     …
   ```

3. **样式复用清单**（Explore 盘点的现成件，新 CSS 控制在组合层）：
   - 行：`.dossier-error-row` 三列模式改造（动词 / 义+格 / 动作），≤600px 叠单列
   - 过滤 pill：`.folio-anchor-pill`
   - 搜索框：`.modal-input`
   - 分组头徽章：`.cefr-ladder-badge` 风格
4. **入卡**：每行「+ 卡」按钮构造与 reader.js:514 `savePrepCollocation`
   相同的 payload，调用同一 `POST /api/cards/vocab`；成功后该行置灰显示
   「已存」（仅内存态，不持久化标记——v1 不做"哪些已入卡"的查询，刷新后恢复可点，
   文档写明这个已知限制）。
5. **show('cards') 路由不动**：矩阵数据懒加载，不给 main.js 加新的路由钩子；
   cards.js 自己管理 segment 内的数据获取。

### 版本落点（v4.5.0 发布时）

- `sw.js` CACHE_NAME → v4.5.0
- `android/app/build.gradle` fallback → 4.5.0 / 40500
- `index.html` 顶栏 → System · v4.5.0 Online
- README 徽章 + 下载表；FEATURES 当前版本号 + 该里程碑行改为「🟢 已发布」+ v4.5.0 行独立成条
- AGENTS.md 快照刷新

## 测试策略

沿用仓库既有的三层做法：

1. **纯函数契约**（新增 test_prep_matrix.py 或并入现有测试文件）：
   - `build_prep_matrix()` 返回的所有 (praeposition, kasus) 组合中，
     抽样词条归属正确（如 `bestehen auf` 归 Dat 组）
   - 总搭配数守恒：所有组内 entry 数之和 == len(PREP_COLLOCATIONS) 各 tuple 展开
   - 552 词 / 691 搭配的计数棘轮（防数据意外缩水；缩水才红，增长放行——用 >=）
2. **Endpoint 测试**（TestClient）：`GET /api/prep/matrix` 200、结构与纯函数一致
3. **静态断言**：cards.js 含第四 segment、index.html 有对应按钮文本、
   `savePrepCollocation` 复用逻辑存在（cards.js 中出现 /api/cards/vocab 调用）

变异验证：每条新断言回退对应实现后必须单独变红（不带 `-x` 跑 pytest，
区分新旧断言的失败来源）。

## 已知限制（显式记录）

- **已入卡状态不持久化**：刷新页面后「已存」标记消失。完整方案需要
  后端反查 cards 库 by word 字符串，属于第二个功能，v1 不做。
- **离线 PWA 场景**：matrix 数据不进 sw.js 预缓存清单（691 条不必预缓存）；
  首次拉取需在线，之后内存缓存到会话结束。SW 缓存策略沿用默认网络优先即可。
- 移动端 dock 不动 —— 这是选择「嵌在卡盒视图」的直接收益之一。

## 不在本期范围

- 「整组一键入卡」（见决策表）
- 矩阵真网格形态（行=介词 × 列=格）
- 按 CEFR 过滤（get_cefr_level 只做展示标签，不做过滤维度——CEFR 未知的
  词条会造出第四个伪过滤项，破坏三格闭集）
- prep_dict.py 数据扩充（531→552 的下一轮补齐是独立的 AI 流水线工作）
