/* DeLector - 存卡响应的纯判定层（L1）
 *
 * 为什么不放 rd-api.js：那一层的运行时导出面被
 * tests/test_reader_api_split.py 钉死为「恰好 15 个端点函数」—— 它是防假解耦、
 * 防 `*Remote` 别名回潮的机械闸，不能往里塞非端点导出。
 *
 * 本模块零 import、零 DOM、零网络、零计时器、零顶层可变状态，只做
 * 「后端响应 → 视图层可判定结果」的纯转换。5 个存卡入口共用这一份判定，
 * tools/vocab_save_feedback_probe.mjs 直接加载本文件真源码验证。
 */
'use strict';

/** 把 POST /api/cards/vocab 的响应折成视图层可判定的结果（纯函数，不改响应体）。
 *
 *  字段缺失（后端仍是旧版，或离线壳/代理截断新字段）一律按「首次新增」处理：
 *  改动前的行为逐字保留，前端因而可以先于后端契约合入而不产生回归。
 */
export function vocabSaveOutcome(res) {
  const created = !(res && res.created === false);
  const skippedFields = (res && Array.isArray(res.skipped_fields)) ? res.skipped_fields : [];
  return { created, skippedFields };
}

/** 幂等命中时给用户的解释文案；首次新增返回空串（调用方据此决定是否提示）。 */
export function vocabSaveNotice(outcome) {
  if (!outcome || outcome.created) return '';
  return outcome.skippedFields && outcome.skippedFields.length
    ? '这个词已在词卡中，本次填写未覆盖原有释义'
    : '这个词已经在词卡里，未重复添加';
}
