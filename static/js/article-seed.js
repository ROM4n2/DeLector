/* DeLector - 文章列表内置静态快照（首装 / 存储被清空时的首帧来源）
 *
 * 数据镜像自后端 `delector/core/db/content.py` 的 PRESET_ARTICLES 与
 * `delector/data/preset_processed.json` 的 stats。字段与
 * `static/js/api-types.js` 的 ArticleListSnapshot 严格同形（5 键），
 * 由 tests/test_articles_list_contract.py 与 article_store 探针共同守卫。
 *
 * 只用于「真实数据尚未到达」的首帧渲染；同步完成后由 store 用真实列表整表替换。
 */
'use strict';

export const ARTICLE_SEED_SNAPSHOT = Object.freeze([
  {
    id: 4,
    title: '【B2 高级篇】Die Transformation der modernen Arbeitswelt: Homeoffice',
    created_at: '内置预置',
    char_count: 373,
    stats: {
      cefr_counts: { A1: 28, A2: 3, B1: 7, B2: 8, C1: 0 },
      cefr_percentages: { A1: 60.9, A2: 6.5, B1: 15.2, B2: 17.4, C1: 0.0 },
      est_reading_minutes: 1,
      recommended_level: 'B1',
      word_count: 46,
    },
  },
  {
    id: 3,
    title: '【B1 提升篇】Klimaschutz im Alltag: Was jeder tun kann',
    created_at: '内置预置',
    char_count: 341,
    stats: {
      cefr_counts: { A1: 28, A2: 7, B1: 12, B2: 0, C1: 0 },
      cefr_percentages: { A1: 59.6, A2: 14.9, B1: 25.5, B2: 0.0, C1: 0.0 },
      est_reading_minutes: 1,
      recommended_level: 'B1',
      word_count: 47,
    },
  },
  {
    id: 2,
    title: '【A2 进阶篇】Eine Reise nach München: Hotel und Freizeit',
    created_at: '内置预置',
    char_count: 312,
    stats: {
      cefr_counts: { A1: 32, A2: 10, B1: 3, B2: 0, C1: 0 },
      cefr_percentages: { A1: 71.1, A2: 22.2, B1: 6.7, B2: 0.0, C1: 0.0 },
      est_reading_minutes: 1,
      recommended_level: 'A2',
      word_count: 45,
    },
  },
  {
    id: 1,
    title: '【A1 入门篇】Hallo Berlin! Mein erster Tag in Deutschland',
    created_at: '内置预置',
    char_count: 323,
    stats: {
      cefr_counts: { A1: 51, A2: 4, B1: 0, B2: 0, C1: 0 },
      cefr_percentages: { A1: 92.7, A2: 7.3, B1: 0.0, B2: 0.0, C1: 0.0 },
      est_reading_minutes: 1,
      recommended_level: 'A1',
      word_count: 55,
    },
  },
]);
