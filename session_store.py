"""当前会话状态和短期答案缓存。

开发可用内存存储，生产建议 Redis。缓存只复用首轮即完成的最终回答。
"""
import json
import logging
import os
import time
import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


def normalize_cache_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def build_cache_key(query: str) -> str:
    normalized = normalize_cache_query(query)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def create_initial_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "title": "新对话",
        "updated_at": time.time(),
        "original_query": "",
        "raw_query": "",
        "dialogue_history": [],
        "dialogue_complete": False,
        "dialogue_summary": "",
        "assistant_reply": "",
        "intent_analysis": {},
        "retrieved_knowledge": {},
        "final_answer": "",
    }


class SessionStore(ABC):
    name: str

    @abstractmethod
    def get(self, session_id: str) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    def set(self, session_id: str, state: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    def active_count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_sessions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def create(self, session_id: str) -> dict:
        state = create_initial_state(session_id)
        self.set(session_id, state)
        return state

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "active_sessions": self.active_count(),
            "startup_error": getattr(self, "startup_error", None),
        }

    def get_cached_answer(self, query: str) -> str | None:
        return None

    def set_cached_answer(self, query: str, answer: str) -> None:
        return None


class MemorySessionStore(SessionStore):
    name = "memory"

    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, tuple[dict, float]] = {}
        self._answer_cache: dict[str, tuple[str, float]] = {}

    def get(self, session_id: str) -> dict | None:
        self._delete_expired()
        item = self._sessions.get(session_id)
        if item is None:
            return None
        state, _ = item
        self.set(session_id, state)
        return state

    def set(self, session_id: str, state: dict) -> None:
        expires_at = time.time() + self.ttl_seconds
        state["updated_at"] = time.time()
        self._sessions[session_id] = (state, expires_at)

    def active_count(self) -> int:
        self._delete_expired()
        return len(self._sessions)

    def list_sessions(self) -> list[dict[str, Any]]:
        self._delete_expired()
        items = []
        for session_id, (state, _) in self._sessions.items():
            if not state.get("dialogue_history") and not state.get("original_query"):
                continue
            items.append(
                {
                    "session_id": session_id,
                    "title": state.get("title") or "新对话",
                    "updated_at": state.get("updated_at", 0),
                    "dialogue_complete": bool(state.get("dialogue_complete")),
                    "turn_count": len(state.get("dialogue_history", [])) // 2,
                }
            )
        return sorted(items, key=lambda item: item["updated_at"], reverse=True)

    def _delete_expired(self) -> None:
        now = time.time()
        expired_ids = [
            session_id
            for session_id, (_, expires_at) in self._sessions.items()
            if expires_at <= now
        ]
        for session_id in expired_ids:
            del self._sessions[session_id]

        expired_cache_keys = [
            cache_key
            for cache_key, (_, expires_at) in self._answer_cache.items()
            if expires_at <= now
        ]
        for cache_key in expired_cache_keys:
            del self._answer_cache[cache_key]

    def get_cached_answer(self, query: str) -> str | None:
        self._delete_expired()
        cache_key = build_cache_key(query)
        item = self._answer_cache.get(cache_key)
        if item is None:
            return None
        answer, _ = item
        self.set_cached_answer(query, answer)
        return answer

    def set_cached_answer(self, query: str, answer: str) -> None:
        self._answer_cache[build_cache_key(query)] = (
            answer,
            time.time() + self.ttl_seconds,
        )


class RedisSessionStore(SessionStore):
    name = "redis"

    def __init__(self, redis_url: str, ttl_seconds: int, key_prefix: str):
        from redis import Redis

        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        self.answer_key_prefix = key_prefix.replace(":session", ":answer")
        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.client.ping()

    def get(self, session_id: str) -> dict | None:
        key = self._key(session_id)
        raw = self.client.get(key)
        if raw is None:
            return None
        self.client.expire(key, self.ttl_seconds)
        return json.loads(raw)

    def set(self, session_id: str, state: dict) -> None:
        state["updated_at"] = time.time()
        self.client.setex(
            self._key(session_id),
            self.ttl_seconds,
            json.dumps(state, ensure_ascii=False),
        )

    def active_count(self) -> int:
        return len(list(self.client.scan_iter(match=f"{self.key_prefix}:*")))

    def list_sessions(self) -> list[dict[str, Any]]:
        items = []
        for key in self.client.scan_iter(match=f"{self.key_prefix}:*"):
            raw = self.client.get(key)
            if not raw:
                continue
            try:
                state = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not state.get("dialogue_history") and not state.get("original_query"):
                continue
            items.append(
                {
                    "session_id": state.get("session_id") or key.rsplit(":", 1)[-1],
                    "title": state.get("title") or "新对话",
                    "updated_at": state.get("updated_at", 0),
                    "dialogue_complete": bool(state.get("dialogue_complete")),
                    "turn_count": len(state.get("dialogue_history", [])) // 2,
                }
            )
        return sorted(items, key=lambda item: item["updated_at"], reverse=True)

    def health(self) -> dict[str, Any]:
        return {
            **super().health(),
            "ttl_seconds": self.ttl_seconds,
            "key_prefix": self.key_prefix,
        }

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}:{session_id}"

    def get_cached_answer(self, query: str) -> str | None:
        key = self._answer_key(query)
        answer = self.client.get(key)
        if answer is None:
            return None
        self.client.expire(key, self.ttl_seconds)
        return answer

    def set_cached_answer(self, query: str, answer: str) -> None:
        self.client.setex(self._answer_key(query), self.ttl_seconds, answer)

    def _answer_key(self, query: str) -> str:
        return f"{self.answer_key_prefix}:{build_cache_key(query)}"


def build_session_store() -> SessionStore:
    ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "7200"))
    store_type = os.getenv("SESSION_STORE", "memory").strip().lower()

    if store_type == "redis":
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        key_prefix = os.getenv("REDIS_KEY_PREFIX", "medical-chat:session")
        try:
            return RedisSessionStore(redis_url, ttl_seconds, key_prefix)
        except Exception as exc:
            fallback = os.getenv("SESSION_STORE_FALLBACK_TO_MEMORY", "true")
            if fallback.strip().lower() not in {"1", "true", "yes", "on"}:
                raise
            logger.warning("Redis session store failed, falling back to memory: %s", exc)
            store = MemorySessionStore(ttl_seconds)
            store.startup_error = f"RedisSessionStore failed: {type(exc).__name__}: {exc}"
            return store

    return MemorySessionStore(ttl_seconds)
