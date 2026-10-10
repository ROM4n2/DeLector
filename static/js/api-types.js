// @ts-check
/* DeLector - 后端 API 响应形状的**单一真相源**（JSDoc typedef，无运行时代码）。
 *
 * 为什么只有本文件开了类型检查（而非全量 static/js）—— 实测数字（不是偏好）
 * -----------------------------------------------------------------------
 * ADR-0021 §6.1 原计划给 static/（33k 行前端）加类型检查。实测（typescript@5.6.3
 * 对全部 23 个 static/js/*.js 跑 `tsc --noEmit --allowJs --checkJs`，共 219 条存量错误）：
 *   - TS2339（Property 'X' does not exist on HTMLElement/Window） 199 条 —— **噪音**：
 *     只是缺 DOM/全局声明，不是 bug；
 *   - TS2322 / TS2345 / TS2554 / TS2551（真类型不匹配）      11 / 5 / 3 / 1 条。
 *   ⇒ 全量 checkJs = 219 条错误、其中 199 条噪音；接进 CI 会立刻变成「永远红的噪音源」
 *     （本仓刚有过「门禁恒真/恒红」的教训）。
 * 故改口径：**只对少数真正打 API 的模块**分阶段启用 —— 用 tsconfig.json 的**显式 allowlist**
 * 逐个文件列出。本文件是起点。**这不是「忘了开全量」**，请见上列数字与 tsconfig.json 同款说明。
 *
 * 形状来源：逐条从后端 handler 抄写（不是编造）——
 *   - ArticleListItem: delector/routes/main.py::list_articles
 *   - ArticleDetail:   delector/routes/main.py::get_article（articles 行 + processed_json 展开）
 *   - Settings:        delector/routes/main.py::get_app_settings
 *   - UpdateCheck:     delector/routes/update.py::_build_success / _build_failure
 *   - CardsVocabEnvelope: delector/routes/main.py 的 /api/cards/vocab 返回信封
 */

/**
 * `GET /api/articles` 列表项（delector/routes/main.py::list_articles）。
 * @typedef {Object} ArticleListItem
 * @property {number} id
 * @property {string} title
 * @property {string} created_at
 * @property {number} char_count   raw_text 字符数（SQL length(raw_text)）
 * @property {Object<string, *>} stats   processed_json.stats（缺失/损坏时为 {}）
 */

/**
 * `GET /api/articles/{article_id}` 详情（articles 行 + processed_json 展开）。
 * @typedef {Object} ArticleDetail
 * @property {number} id
 * @property {string} title
 * @property {string} created_at
 * @property {string} raw_text
 * @property {string} processed_json
 * @property {string} version             PROCESSED_JSON_VERSION
 * @property {number} sentence_count
 * @property {Array<Object<string, *>>} sentences
 * @property {Object<string, *>} stats
 */

/**
 * `GET /api/settings`（delector/routes/main.py::get_app_settings）。
 * @typedef {Object} Settings
 * @property {boolean} has_api_key
 * @property {string} api_key_masked
 * @property {string} api_base_url
 * @property {string} api_model
 * @property {string} tts_voice
 * @property {string} tts_rate
 * @property {string} nlp_engine
 * @property {string} nlp_engine_detail
 */

/**
 * `GET /api/update/check`（delector/routes/update.py）。
 * `has_update` 三态：true | false | null（null ⇔ 本次没查成、error_reason 非空）。
 * @typedef {Object} UpdateCheck
 * @property {string} current
 * @property {string|null} latest
 * @property {boolean|null} has_update
 * @property {string|null} page_url
 * @property {number} checked_at
 * @property {boolean} cached
 * @property {string|null} error_reason
 */

/**
 * `GET/POST /api/cards/vocab` 返回信封（前端须先解包 `.words`，见 a1_cards.js 注释）。
 * @typedef {Object} CardsVocabEnvelope
 * @property {string} cefr
 * @property {string} scope
 * @property {number} total
 * @property {Array<Object<string, *>>} words
 */

export {};
