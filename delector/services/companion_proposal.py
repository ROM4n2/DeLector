# -*- coding: utf-8 -*-
"""伴学智能体提议 (Proposal) 生命周期管理与幂等确认入库服务 (Task 2).

依据: docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md
      docs/plans/archive/2026-11-01-companion-harness-persistence-and-refactor.md
"""

from __future__ import annotations

import sqlite3
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

_SUPPORTED_ACTIONS = {"create_vocab_cards", "create_vocab_card"}


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
            )

    def list_proposals(
        self,
        session_id: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询指定会话的提议列表，可按 pending/accepted/rejected 过滤。"""
        with get_db(self.db_path) as conn:
            return db_get_proposals(conn, session_id=session_id, status=status)

    def execute_proposal(
        self,
        proposal_id: str,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """原子流转提议状态为 accepted，并将卡片持久化至 vocab_cards（防重放幂等保护）。"""
        if action not in _SUPPORTED_ACTIONS:
            raise ValueError(f"不支持的提议动作类型: {action}")

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
            # 检查提议既有状态，杜绝重放重复插卡
            try:
                row = conn.execute(
                    "SELECT status FROM companion_proposals WHERE id = ?",
                    (proposal_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None

            if row is not None:
                if row["status"] == "accepted":
                    # 幂等返回：提议此前已确认执行，不再重复落盘
                    return {
                        "status": "ok",
                        "proposal_id": proposal_id,
                        "action": action,
                        "created_count": 0,
                    }
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
                cefr_level = str(c.get("cefr_level") or "B1").strip()
                definition_zh = str(c.get("definition_zh") or c.get("reading") or "").strip() or word
                sentence = str(c.get("sentence_context") or c.get("context_sentence") or "").strip()

                cur = conn.execute(
                    """
                    INSERT INTO vocab_cards (
                        word, lemma, pos, gender, plural, cefr_level, definition_zh, sentence_context, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'companion')
                    """,
                    (word, lemma, pos, gender, plural, cefr_level, definition_zh, sentence),
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
