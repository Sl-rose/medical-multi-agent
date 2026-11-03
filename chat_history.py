"""长期对话历史。

未配置 HISTORY_DB_URL 时使用空实现；配置 MySQL 后保存会话标题和每轮消息。
左侧历史列表读这里，不依赖 Redis 会话是否过期。
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _state_messages(state: dict) -> list[dict[str, str]]:
    messages = list(state.get("dialogue_history", []))
    final_answer = state.get("final_answer", "")
    if final_answer and (
        not messages
        or messages[-1].get("role") != "assistant"
        or messages[-1].get("content") != final_answer
    ):
        messages.append({"role": "assistant", "content": final_answer})
    return messages


class DisabledChatHistoryStore:
    enabled = False

    def init_db(self) -> None:
        return None

    def create_session(self, session_id: str, title: str = "新对话") -> None:
        return None

    def sync_state(self, state: dict) -> None:
        return None

    def list_sessions(self) -> list[dict[str, Any]]:
        return []

    def get_session(self, session_id: str) -> dict | None:
        return None

    def health(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "database": "disabled",
        }


class MySQLChatHistoryStore:
    enabled = True

    def __init__(self, db_url: str):
        from sqlalchemy import create_engine

        self.db_url = db_url
        self.engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            future=True,
        )

    def init_db(self) -> None:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                      id VARCHAR(64) PRIMARY KEY,
                      title VARCHAR(32) NOT NULL,
                      dialogue_complete BOOLEAN NOT NULL DEFAULT FALSE,
                      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_messages (
                      id BIGINT AUTO_INCREMENT PRIMARY KEY,
                      session_id VARCHAR(64) NOT NULL,
                      role VARCHAR(20) NOT NULL,
                      content LONGTEXT NOT NULL,
                      turn_index INT NOT NULL,
                      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      INDEX idx_session_turn (session_id, turn_index),
                      CONSTRAINT fk_chat_messages_session
                        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
                        ON DELETE CASCADE
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """
                )
            )
        logger.info("MySQL chat history tables are ready")

    def create_session(self, session_id: str, title: str = "新对话") -> None:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO chat_sessions (id, title, dialogue_complete)
                    VALUES (:id, :title, FALSE)
                    ON DUPLICATE KEY UPDATE title = VALUES(title)
                    """
                ),
                {"id": session_id, "title": title[:32] or "新对话"},
            )

    def sync_state(self, state: dict) -> None:
        from sqlalchemy import text

        session_id = state.get("session_id")
        if not session_id:
            return

        title = (state.get("title") or "新对话")[:32]
        complete = bool(state.get("dialogue_complete"))
        messages = _state_messages(state)

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO chat_sessions (id, title, dialogue_complete)
                    VALUES (:id, :title, :complete)
                    ON DUPLICATE KEY UPDATE
                      title = VALUES(title),
                      dialogue_complete = VALUES(dialogue_complete),
                      updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {"id": session_id, "title": title, "complete": complete},
            )
            conn.execute(
                text("DELETE FROM chat_messages WHERE session_id = :session_id"),
                {"session_id": session_id},
            )
            for index, message in enumerate(messages):
                conn.execute(
                    text(
                        """
                        INSERT INTO chat_messages
                          (session_id, role, content, turn_index)
                        VALUES
                          (:session_id, :role, :content, :turn_index)
                        """
                    ),
                    {
                        "session_id": session_id,
                        "role": message.get("role", "assistant"),
                        "content": message.get("content", ""),
                        "turn_index": index,
                    },
                )

    def list_sessions(self) -> list[dict[str, Any]]:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                      s.id AS session_id,
                      s.title AS title,
                      s.dialogue_complete AS dialogue_complete,
                      UNIX_TIMESTAMP(s.updated_at) AS updated_at,
                      SUM(CASE WHEN m.role = 'user' THEN 1 ELSE 0 END) AS turn_count,
                      COUNT(m.id) AS message_count
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON m.session_id = s.id
                    GROUP BY s.id, s.title, s.dialogue_complete, s.updated_at
                    HAVING message_count > 0
                    ORDER BY s.updated_at DESC
                    LIMIT 100
                    """
                )
            ).mappings()
            return [
                {
                    "session_id": row["session_id"],
                    "title": row["title"],
                    "updated_at": float(row["updated_at"] or 0),
                    "dialogue_complete": bool(row["dialogue_complete"]),
                    "turn_count": int(row["turn_count"] or 0),
                }
                for row in rows
            ]

    def get_session(self, session_id: str) -> dict | None:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            session = conn.execute(
                text(
                    """
                    SELECT
                      id AS session_id,
                      title,
                      dialogue_complete,
                      UNIX_TIMESTAMP(updated_at) AS updated_at
                    FROM chat_sessions
                    WHERE id = :session_id
                    """
                ),
                {"session_id": session_id},
            ).mappings().first()
            if session is None:
                return None

            rows = conn.execute(
                text(
                    """
                    SELECT role, content
                    FROM chat_messages
                    WHERE session_id = :session_id
                    ORDER BY turn_index ASC, id ASC
                    """
                ),
                {"session_id": session_id},
            ).mappings()
            messages = [
                {"role": row["role"], "content": row["content"]}
                for row in rows
            ]

        return {
            "session_id": session["session_id"],
            "title": session["title"],
            "messages": messages,
            "dialogue_complete": bool(session["dialogue_complete"]),
            "updated_at": float(session["updated_at"] or 0),
            "turn_count": sum(1 for message in messages if message["role"] == "user"),
            "final_answer": messages[-1]["content"]
            if messages and messages[-1]["role"] == "assistant"
            else "",
        }

    def health(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "database": "mysql",
        }


def build_chat_history_store():
    db_url = os.getenv("HISTORY_DB_URL", "").strip()
    if not db_url:
        return DisabledChatHistoryStore()
    return MySQLChatHistoryStore(db_url)
