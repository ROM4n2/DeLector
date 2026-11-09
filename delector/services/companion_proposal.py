# -*- coding: utf-8 -*-
"""伴学智能体提议 (Proposal) 生命周期管理与幂等确认入库服务 (Task 2).

依据: docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md
      docs/plans/archive/2026-11-01-companion-harness-persistence-and-refactor.md
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from delector.core.database import get_db, log_study_event
from delector.core.db.companion import (
    create_proposal as db_create_proposal,
)
from delector.core.db.companion import (
    get_proposals as db_get_proposals,
)
from delector.core.db.companion import (
    update_proposal_status,
)
from delector.core.vocab_identity import fill_empty_columns, find_card_id

_SUPPORTED_ACTIONS = {
    "create_vocab_cards",
    "create_vocab_card",
    "apply_writing_revision",
    "set_weekly_goal",
}
_MULTI_ACTIONS = {"apply_writing_revision", "set_weekly_goal"}


class CompanionProposalService:
    """伴学提议生命周期服务，提供提议挂起、状态防重放流转与生词卡幂等落盘。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    def create_proposal(
        self,
        session_id: str,
        action: str,
        title: str,
        payload: Dict[str, Any],
        message_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录伴学提议条目（默认状态为 pending）。"""
        with get_db(self.db_path) as conn:
            return db_create_proposal(
                conn,
                session_id=session_id,
                action=action,
                title=title,
                payload=payload,
                message_id=message_id,
                proposal_id=proposal_id,
            )

    def reject_proposal(self, proposal_id: str) -> Dict[str, Any]:
        """将 pending 提议标记为 rejected；不写任何卡片。"""
        with get_db(self.db_path) as conn:
            rejected = update_proposal_status(conn, proposal_id, "rejected")
        return {
            "status": "ok" if rejected else "not_found",
            "proposal_id": proposal_id,
            "rejected": rejected,
        }

    def list_proposals(
        self,
        session_id: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询指定会话的提议列表，可按 pending/accepted/rejected 过滤。"""
        with get_db(self.db_path) as conn:
            return db_get_proposals(conn, session_id=session_id, status=status)

    def _execute_multi_action(
        self,
        proposal_id: str,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行写作修订或周目标写入；校验、业务写入与状态流转同事务。"""
        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM companion_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise ValueError("提议不存在")
            if row["status"] == "accepted":
                return {
                    "status": "ok",
                    "proposal_id": proposal_id,
                    "action": action,
                    "created_count": 0,
                }
            if row["status"] == "rejected":
                raise ValueError("提议已拒绝，不能再次确认")

            if action == "set_weekly_goal":
                goal = str(payload.get("goal") or "").strip()
                if not goal:
                    raise ValueError("学习目标不能为空")
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES ('companion_weekly_goal', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                    """,
                    (goal,),
                )
                result: Dict[str, Any] = {"goal": goal}
            else:
                essay_id = payload.get("essay_id")
                if not isinstance(essay_id, int) or isinstance(essay_id, bool) or essay_id <= 0:
                    raise ValueError("缺少有效 essay_id")
                original = str(payload.get("original_text") or "").strip()
                revised = str(payload.get("revised_text") or "").strip()
                if not original:
                    raise ValueError("原句不能为空")
                if not revised:
                    raise ValueError("改写文本不能为空")
                if original == revised:
                    raise ValueError("改写文本不能与原句相同")
                essay = conn.execute(
                    "SELECT content FROM essays WHERE id = ?",
                    (essay_id,),
                ).fetchone()
                if essay is None:
                    raise ValueError("作文不存在")
                content = str(essay["content"])
                if content.count(original) != 1:
                    raise ValueError("原句在当前作文中不存在或不唯一")
                updated = content.replace(original, revised, 1)

                from delector.nlp_engine import processor as nlp_processor
                from delector.services.writing import analyze_essay_text

                analysis = analyze_essay_text(updated[:5000], getattr(nlp_processor, "nlp", None))
                conn.execute(
                    """
                    UPDATE essays
                    SET content = ?, analysis_json = ?, cefr_level = ?, error_count = ?,
                        sentence_count = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        updated,
                        json.dumps(analysis, ensure_ascii=False),
                        analysis.get("cefr", {}).get("recommended_level"),
                        analysis["error_count"],
                        len(analysis["sentences"]),
                        datetime.utcnow().isoformat(),
                        essay_id,
                    ),
                )
                result = {"content": updated, "analysis_json": analysis}

            conn.execute(
                """
                UPDATE companion_proposals
                SET status = 'accepted', resolved_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), proposal_id),
            )
            conn.commit()

        return {
            "status": "ok",
            "proposal_id": proposal_id,
            "action": action,
            "created_count": 1,
            **result,
        }

    def execute_proposal(
        self,
        proposal_id: str,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """原子流转提议状态为 accepted，并执行对应写入（防重放幂等保护）。"""
        if action not in _SUPPORTED_ACTIONS:
            raise ValueError(f"不支持的提议动作类型: {action}")
        if action in _MULTI_ACTIONS:
            return self._execute_multi_action(proposal_id, action, payload)

        # 归一化提取待落盘卡片列表
        cards = payload.get("cards")
        if cards is None:
            if "card" in payload and isinstance(payload["card"], dict):
                cards = [payload["card"]]
            elif "word" in payload:
                cards = [payload]
            else:
                raise ValueError("提议 payload 缺少有效的 'cards' 列表")
        elif not isinstance(cards, list):
            raise ValueError("提议 payload 缺少有效的 'cards' 列表")

        with get_db(self.db_path) as conn:
            # Step 1（只堵新增）：身份 = (lemma_key(lemma), word_key(word))，见
            # delector/core/vocab_identity.py。存量重复未知，故**不建 UNIQUE**；
            # BEGIN IMMEDIATE 把「查重 → 插入」收成一个写事务，收窄并发窗口。
            # 这不等于唯一索引：绕过本函数的写入（直接 SQL / 旧库还原）仍可重复。
            conn.execute("BEGIN IMMEDIATE")
            # 检查提议既有状态，杜绝重放重复插卡
            try:
                row = conn.execute(
                    "SELECT status FROM companion_proposals WHERE id = ?",
                    (proposal_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None

            if row is not None and row["status"] == "accepted":
                # 幂等返回：提议此前已确认执行，不再重复落盘
                return {
                    "status": "ok",
                    "proposal_id": proposal_id,
                    "action": action,
                    "created_count": 0,
                }
            if row is not None and row["status"] == "rejected":
                raise ValueError("提议已拒绝，不能再次确认")

            # 空/畸形提议不允许被确认成「已入库」：没有任何有效词条时直接报错，
            # 状态保持 pending，避免前端把空提议标成 accepted 却一张卡都没写。
            if not any(isinstance(c, dict) and str(c.get("word", "")).strip() for c in cards):
                raise ValueError("提议中没有可入库的词条")

            if row is not None:
                update_proposal_status(conn, proposal_id, "accepted")

            created_count = 0
            for c in cards:
                if not isinstance(c, dict):
                    continue
                word = str(c.get("word", "")).strip()
                if not word:
                    continue
                lemma = str(c.get("lemma") or word).strip()
                pos = str(c.get("pos") or "").strip()
                gender = str(c.get("gender") or "").strip()
                plural = str(c.get("plural") or "").strip()
                cefr_level = str(c.get("cefr_level") or "").strip()
                # definition_zh 只接受真正的中文释义：reading 是读音/音标，缺省时留空，
                # 由前端提案卡片与卡盒 UI 显式标记「待补充」，绝不用音标冒充释义。
                definition_zh = str(c.get("definition_zh") or "").strip()
                sentence = str(c.get("sentence_context") or c.get("context_sentence") or "").strip()

                # 同一张卡已存在（含别的入口先建的）：只补空列，不新增行、
                # 不重复计 created_count、不重复记 add_card 事件。合法多卡靠 word
                # 区分（如 bestehen auf/aus/in），不会在这里被合并。
                existing_id = find_card_id(conn, lemma, word)
                if existing_id is not None:
                    fill_empty_columns(
                        conn,
                        existing_id,
                        {
                            "pos": pos,
                            "gender": gender,
                            "plural": plural,
                            "cefr_level": cefr_level,
                            "definition_zh": definition_zh,
                            "sentence_context": sentence,
                        },
                    )
                    continue

                cur = conn.execute(
                    """
                    INSERT INTO vocab_cards (
                        word, lemma, pos, gender, plural, cefr_level, definition_zh, sentence_context, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'companion')
                    """,
                    (word, lemma, pos, gender, plural, cefr_level or "B1", definition_zh, sentence),
                )
                created_count += 1
                card_id = cur.lastrowid
                if card_id:
                    try:
                        log_study_event("add_card", card_id, word, db_path=self.db_path)
                    except Exception:  # silent-ok: 学习事件埋点写入失败不回滚生词卡真实事务
                        pass
            conn.commit()

        return {
            "status": "ok",
            "proposal_id": proposal_id,
            "action": action,
            "created_count": created_count,
        }
