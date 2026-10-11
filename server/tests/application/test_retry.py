"""Explicit retry on the same saved user message (LD-04 §8): never a new message or automatic."""

from __future__ import annotations

import pytest

from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.configuration import (
    ConfigurationCatalog,
    ShippedConfiguration,
)
from anonymous.application.context import ContextBuilder
from anonymous.domain.configuration import ContextConstruction, EffectiveConfiguration
from anonymous.domain.errors import (
    ConfigurationUnavailable,
    ConversationBusy,
    ExecutionUnresolved,
    IdempotencyConflict,
    RetryNotEligible,
    RuntimeQuarantined,
)
from anonymous.domain.evidence import LifetimeScope, RunKind
from anonymous.domain.ids import UserId, new_uuid
from anonymous.domain.models import MessageRole, RunStatus
from tests.application.test_reconcile import orphan
from tests.conftest import Services
from tests.doubles import RecordingModel, failing_model


def failed_conversation(store: SqliteStore, owner: UserId):  # type: ignore[no-untyped-def]
    services = Services(store, failing_model())
    cid = services.conversations.create_conversation(owner).id
    first = services.conversations.send_message(owner, cid, new_uuid(), "please answer")
    assert first.run.status is RunStatus.FAILED
    return cid, first


def test_retry_creates_one_new_run_on_the_same_user_message_and_no_duplicate_message(
    store: SqliteStore, owner: UserId
) -> None:
    cid, first = failed_conversation(store, owner)
    model = RecordingModel("second try")
    services = Services(store, model)
    retry_id = new_uuid()
    retried = services.conversations.retry_generation(owner, cid, retry_id, first.user_message.id)

    assert retried.run.id != first.run.id and retried.run.kind is RunKind.RETRY
    assert retried.run.retry_of_run_id == first.run.id
    assert retried.run.triggering_message_id == first.user_message.id  # the SAME saved message
    assert (
        retried.assistant_message is not None and retried.assistant_message.content == "second try"
    )
    history = store.get_history(owner, cid)
    assert [m.role for m in history.messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert history.messages[0] == first.user_message  # identity, position and instant unchanged
    assert [r.status for r in history.runs] == [RunStatus.FAILED, RunStatus.SUCCEEDED]
    assert history.runs[0] == first.run  # the earlier attempt is untouched
    assert len(model.requests) == 1 and [m.content for m in model.requests[0].messages] == [
        "please answer"
    ]


def test_there_is_no_automatic_retry(store: SqliteStore, owner: UserId) -> None:
    model = failing_model()
    services = Services(store, model)
    cid = services.conversations.create_conversation(owner).id
    services.conversations.send_message(owner, cid, new_uuid(), "q")
    services.coordinator.reconcile()
    Services(store, model, boot_id="restarted").coordinator.startup()
    assert len(model.requests) == 1
    assert len(store.get_history(owner, cid).runs) == 1


def test_a_replayed_retry_returns_its_run_and_does_not_invoke_again(
    store: SqliteStore, owner: UserId
) -> None:
    cid, first = failed_conversation(store, owner)
    model = RecordingModel("ok")
    services = Services(store, model)
    retry_id = new_uuid()
    one = services.conversations.retry_generation(owner, cid, retry_id, first.user_message.id)
    two = services.conversations.retry_generation(owner, cid, retry_id, first.user_message.id)
    assert two.replayed and not one.replayed and two.run == one.run
    assert len(model.requests) == 1
    assert len(store.get_history(owner, cid).runs) == 2


def test_a_retry_id_reused_for_a_different_target_conflicts(
    store: SqliteStore, owner: UserId
) -> None:
    cid, first = failed_conversation(store, owner)
    other_cid, other = failed_conversation(store, owner)
    services = Services(store, RecordingModel())
    retry_id = new_uuid()
    services.conversations.retry_generation(owner, cid, retry_id, first.user_message.id)
    with pytest.raises(IdempotencyConflict):
        services.conversations.retry_generation(owner, other_cid, retry_id, other.user_message.id)
    assert store.get_history(owner, other_cid).runs == (other.run,)  # nothing was created


def test_each_retry_after_a_failure_is_a_new_explicit_intent(
    store: SqliteStore, owner: UserId
) -> None:
    cid, first = failed_conversation(store, owner)
    failing = Services(store, failing_model())
    second = failing.conversations.retry_generation(owner, cid, new_uuid(), first.user_message.id)
    assert second.run.status is RunStatus.FAILED and second.run.retry_of_run_id == first.run.id
    ok = Services(store, RecordingModel("finally"))
    third = ok.conversations.retry_generation(owner, cid, new_uuid(), first.user_message.id)
    assert third.run.retry_of_run_id == second.run.id and third.assistant_message is not None
    assert (
        len([m for m in store.get_history(owner, cid).messages if m.role is MessageRole.USER]) == 1
    )


def test_retry_is_refused_after_success_with_a_specific_reason_and_creates_nothing(
    store: SqliteStore, owner: UserId
) -> None:
    services = Services(store, RecordingModel("ok"))
    cid = services.conversations.create_conversation(owner).id
    done = services.conversations.send_message(owner, cid, new_uuid(), "q")
    with pytest.raises(RetryNotEligible):
        services.conversations.retry_generation(owner, cid, new_uuid(), done.user_message.id)
    assert len(store.get_history(owner, cid).runs) == 1


def test_retry_is_refused_when_the_message_was_superseded(
    store: SqliteStore, owner: UserId
) -> None:
    cid, first = failed_conversation(store, owner)
    ok = Services(store, RecordingModel("ok"))
    ok.conversations.send_message(owner, cid, new_uuid(), "a newer message")  # continues instead
    with pytest.raises(RetryNotEligible):
        ok.conversations.retry_generation(owner, cid, new_uuid(), first.user_message.id)


def test_retry_is_refused_while_an_attempt_is_active(store: SqliteStore, owner: UserId) -> None:
    cid, first = failed_conversation(store, owner)
    runtime = ScriptedRuntime()
    runtime.await_gate.arm()
    services = Services(store, runtime)
    handle = services.coordinator.begin_retry(
        owner=owner, conversation_id=cid, retry_id=new_uuid(), message_id=first.user_message.id
    )
    assert runtime.await_gate.wait_entered()
    with pytest.raises(ConversationBusy):  # no queue, no second concurrent run
        services.conversations.retry_generation(owner, cid, new_uuid(), first.user_message.id)
    runtime.await_gate.release()
    assert handle.wait(5).run.status is RunStatus.SUCCEEDED


def test_retry_is_refused_from_an_unresolved_attempt_and_while_the_runtime_is_quarantined(
    store: SqliteStore, owner: UserId
) -> None:
    other, first = failed_conversation(store, owner)  # failed before the quarantine begins
    cid, _ = orphan(store, owner, scope=LifetimeScope.EXTERNAL, late=False)
    services = Services(store, ScriptedRuntime(scope=LifetimeScope.EXTERNAL), boot_id="boot-2")
    services.coordinator.startup()  # the orphan becomes indeterminate: quarantine
    message_id = store.get_history(owner, cid).messages[0].id
    with pytest.raises(ExecutionUnresolved):
        services.conversations.retry_generation(owner, cid, new_uuid(), message_id)
    with pytest.raises(RuntimeQuarantined):  # a different, eligible conversation is blocked too
        services.conversations.retry_generation(owner, other, new_uuid(), first.user_message.id)


def test_retry_uses_the_conversations_pinned_configuration_or_is_blocked(
    store: SqliteStore, owner: UserId
) -> None:
    cid, first = failed_conversation(store, owner)
    only_other = ConfigurationCatalog(
        [
            ShippedConfiguration(
                EffectiveConfiguration(ContextConstruction("whole-history", 2)), ContextBuilder
            )
        ]
    )
    blocked = Services(store, RecordingModel(), catalog=only_other)
    with pytest.raises(ConfigurationUnavailable):
        blocked.conversations.retry_generation(owner, cid, new_uuid(), first.user_message.id)
    assert len(store.get_history(owner, cid).runs) == 1  # nothing substituted, nothing created
