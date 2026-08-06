"""In-process session memory for the anonymous AI consultant prototype.

Design intent (prototype scope, not the durable persistence path):

- **Server-generated IDs only.** A session id is minted here with
  ``secrets.token_urlsafe`` and handed back to the caller. The store never
  trusts a client-supplied id to *create* a session — accepting an arbitrary
  client id would let one visitor guess or brute-force another visitor's id
  and read their conversation. A client may only *present* an id it was
  previously given; unknown or expired ids transparently start a fresh
  session rather than erroring.
- **TTL + bounded size.** Every session carries an expiry; a lazily-swept,
  bounded dict stands in for a real cache (Redis, etc.) that a production
  deployment would use instead. This is explicitly a prototype: memory is
  process-local and lost on restart or across multiple workers.
- **Only sanitized turns are stored.** The public mutation method validates
  role/content again defensively, even though the route already calls
  ``ai_text.sanitize_history`` before passing turns here.
- **Thread-safe for a single process.** A single ``Lock`` guards all
  mutations; the expected concurrency (a handful of concurrent requests in a
  dev/staging prototype) does not justify a more elaborate structure.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from app.config import get_settings

_MAX_TURN_CHARS = 4000
_ALLOWED_ROLES = frozenset({"user", "assistant"})


@dataclass
class _Session:
    turns: list[dict[str, str]]
    expires_at: float
    # Insertion/refresh order for LRU eviction when the store is full.
    touched_at: float = field(default_factory=time.monotonic)


class SessionStore:
    """Bounded, TTL'd, in-memory store of recent conversation turns."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    # -- internals -----------------------------------------------------

    def _now(self) -> float:
        return time.monotonic()

    def _purge_expired_locked(self, now: float) -> None:
        expired = [sid for sid, session in self._sessions.items() if session.expires_at <= now]
        for sid in expired:
            del self._sessions[sid]

    def _evict_if_full_locked(self, max_sessions: int) -> None:
        while max_sessions > 0 and len(self._sessions) >= max_sessions:
            # Evict least-recently-touched session rather than a random one,
            # so active conversations survive pressure from short-lived ones.
            oldest_id = min(
                self._sessions,
                key=lambda sid: self._sessions[sid].touched_at,
            )
            del self._sessions[oldest_id]

    def _new_id_locked(self) -> str:
        # Collision is practically impossible, but loop keeps invariant exact.
        session_id = secrets.token_urlsafe(24)
        while session_id in self._sessions:
            session_id = secrets.token_urlsafe(24)
        return session_id

    @staticmethod
    def _clean_turns(turns: list[dict[str, str]]) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            role = turn.get("role")
            content = turn.get("content")
            if not isinstance(role, str) or role not in _ALLOWED_ROLES:
                continue
            if not isinstance(content, str):
                continue
            text = content.strip()
            if text:
                cleaned.append({"role": role, "content": text[:_MAX_TURN_CHARS]})
        return cleaned

    @staticmethod
    def _copy_turns(turns: list[dict[str, str]]) -> list[dict[str, str]]:
        return [dict(turn) for turn in turns]

    # -- public API ----------------------------------------------------

    def open(self, session_id: str | None) -> tuple[str, list[dict[str, str]], bool]:
        """Open valid *session_id* or mint a new session.

        Returns ``(id, turns, created)``. Unknown and expired IDs never become
        keys in the store; they receive a fresh server-generated ID.
        """
        settings = get_settings()
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            if session_id:
                session = self._sessions.get(session_id)
                if session is not None:
                    session.expires_at = now + settings.session_ttl_seconds
                    session.touched_at = now
                    return session_id, self._copy_turns(session.turns), False

            new_id = self._new_id_locked()
            self._evict_if_full_locked(settings.session_max_count)
            self._sessions[new_id] = _Session(
                turns=[],
                expires_at=now + settings.session_ttl_seconds,
                touched_at=now,
            )
            return new_id, [], True

    def get_turns(self, session_id: str | None) -> list[dict[str, str]] | None:
        """Return stored turns, or ``None`` when ID is missing/expired."""
        if not session_id:
            return None
        settings = get_settings()
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.expires_at = now + settings.session_ttl_seconds
            session.touched_at = now
            return self._copy_turns(session.turns)

    def exists(self, session_id: str | None) -> bool:
        return self.get_turns(session_id) is not None

    def append_turns(self, session_id: str, new_turns: list[dict[str, str]]) -> bool:
        """Append valid *new_turns* and refresh TTL.

        Returns ``False`` when session expired between request start and
        response. It never recreates an arbitrary/expired client ID.
        """
        cleaned = self._clean_turns(new_turns)
        if not cleaned:
            return True
        settings = get_settings()
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.turns.extend(cleaned)
            limit = settings.agent_max_history_messages
            if limit <= 0:
                session.turns = []
            elif len(session.turns) > limit:
                session.turns = session.turns[-limit:]
            session.expires_at = now + settings.session_ttl_seconds
            session.touched_at = now
            return True

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear_all(self) -> None:
        """Clear all process-local sessions.

        Used by tests and controlled local resets. Production callers should
        normally let TTL/eviction remove sessions naturally.
        """
        with self._lock:
            self._sessions.clear()

    def __len__(self) -> int:  # pragma: no cover - diagnostic only
        with self._lock:
            return len(self._sessions)


# Process-wide singleton, mirroring the pattern used by app.config.get_settings.
_store = SessionStore()


def get_session_store() -> SessionStore:
    return _store
