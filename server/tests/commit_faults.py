"""Fault injection at the real SQLite COMMIT boundary (and at an individual statement).

The store opens a short-lived connection per operation (``store.connect``). These helpers replace
that factory with one that returns a proxy around the *real* connection, so a fault is injected at
the actual database call and not at a service or store method boundary:

* ``statement``     — a statement of the operation raises before it executes: the transaction is
                      rolled back, and the application must see a **known** failure;
* ``before_commit`` — the real ``COMMIT`` is never issued (the transaction is rolled back) and the
                      error is raised: nothing is durable, but the application cannot know that;
* ``after_commit``  — the real ``COMMIT`` is issued and succeeds, then the acknowledgment is lost:
                      everything is durable, and the application cannot know that either.

A rule targets a store operation by name (the public store method on the call stack), so tests do
not depend on how many transactions an operation happens to run or on SQL text.
"""

from __future__ import annotations

import sqlite3
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from anonymous.adapters.persistence.sqlite import store as store_module
from anonymous.adapters.persistence.sqlite.connection import connect as real_connect

STATEMENT = "statement"
BEFORE_COMMIT = "before_commit"
AFTER_COMMIT = "after_commit"


@dataclass(slots=True)
class Rule:
    operation: str
    point: str
    nth: int = 1  # the nth matching event for this operation triggers; later ones pass
    pattern: str | None = None  # statement rules: the statement must start with this text
    seen: int = 0
    hits: int = 0  # how many times this rule actually injected a fault
    repeat: bool = False  # fire on every matching event from the nth on
    active: bool = True

    @property
    def fired(self) -> bool:
        return self.hits > 0


class CommitFaultPlan:
    def __init__(self) -> None:
        self._rules: list[Rule] = []
        self._lock = threading.Lock()
        self.events: list[tuple[str, str]] = []  # (operation, what happened), in order
        # Set when any operation *attempts* ``BEGIN IMMEDIATE`` (before it may block on the write
        # lock): proof that a competing writer has reached the lock without waiting a fixed time.
        self.write_begin_attempted = threading.Event()

    def arm(
        self,
        operation: str,
        point: str,
        *,
        nth: int = 1,
        pattern: str | None = None,
        repeat: bool = False,
    ) -> Rule:
        rule = Rule(operation, point, nth=nth, pattern=pattern, repeat=repeat)
        with self._lock:
            self._rules.append(rule)
        return rule

    def take(self, operation: str | None, point: str, sql: str = "") -> bool:
        if operation is None:
            return False
        with self._lock:
            for rule in self._rules:
                if not rule.active or rule.operation != operation or rule.point != point:
                    continue
                if rule.pattern is not None and not sql.lstrip().startswith(rule.pattern):
                    continue
                rule.seen += 1
                if rule.seen == rule.nth or (rule.repeat and rule.seen > rule.nth):
                    rule.hits += 1
                    self.events.append((operation, point))
                    return True
        return False

    def disarm(self) -> None:
        """Stop injecting; the rules stay recorded so ``verify`` still checks that they fired."""
        with self._lock:
            for rule in self._rules:
                rule.active = False

    def verify(self) -> None:
        """Every armed rule must have injected at least once: a fault that never fired means the
        test did not exercise the transaction it claims to."""
        with self._lock:
            silent = [f"{r.operation}/{r.point}" for r in self._rules if not r.fired]
        assert not silent, f"armed fault rule(s) never fired: {silent}"

    def note(self, operation: str | None, what: str) -> None:
        with self._lock:
            self.events.append((operation or "?", what))

    def fired(self, operation: str, point: str) -> int:
        with self._lock:
            return sum(1 for e in self.events if e == (operation, point))


def _store_operation() -> str | None:
    """The public store method that is executing (the outermost public one below the proxy)."""
    store_file = store_module.__file__
    frame = sys._getframe(2)
    found: str | None = None
    while frame is not None:
        code = frame.f_code
        if code.co_filename == store_file and not code.co_name.startswith("_"):
            found = code.co_name
            break
        frame = frame.f_back  # type: ignore[assignment]
    return found


class FaultingConnection:
    """Delegates everything to a real ``sqlite3.Connection``; intercepts ``execute`` only."""

    def __init__(self, inner: sqlite3.Connection, plan: CommitFaultPlan) -> None:
        self._inner = inner
        self._plan = plan

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        head = sql.lstrip().upper()
        if head.startswith("COMMIT"):
            operation = _store_operation()
            if self._plan.take(operation, BEFORE_COMMIT):
                raise sqlite3.OperationalError("injected: COMMIT failed before durability")
            cursor = self._inner.execute(sql, *args)
            if self._plan.take(operation, AFTER_COMMIT):
                raise sqlite3.OperationalError(
                    "injected: COMMIT acknowledgment lost after durability"
                )
            return cursor
        if head.startswith("BEGIN IMMEDIATE"):
            self._plan.write_begin_attempted.set()
        if not head.startswith(("BEGIN", "ROLLBACK", "PRAGMA")) or head.startswith("BEGIN"):
            operation = _store_operation()
            if self._plan.take(operation, STATEMENT, sql):
                raise sqlite3.OperationalError("injected: statement failed")
        return self._inner.execute(sql, *args)


@contextmanager
def faulting_commits(monkeypatch: pytest.MonkeyPatch) -> Iterator[CommitFaultPlan]:
    plan = CommitFaultPlan()

    def connect(path: str | Path, **kwargs: Any) -> Any:
        return FaultingConnection(real_connect(path, **kwargs), plan)

    monkeypatch.setattr(store_module, "connect", connect)
    yield plan
    plan.verify()
