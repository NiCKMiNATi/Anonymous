"""Bounded recent-history selection and its provenance serialization (ADR-0017). Pure rules:
synthetic messages only, no store, runtime or model."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from anonymous.application.configuration import (
    BuilderFactory,
    baseline_manifest,
    bounded_recent_manifest,
    default_configuration_digest,
    golden_replay,
)
from anonymous.application.context import (
    BoundedRecentContextBuilder,
    ContextBuilder,
    select_recent,
)
from anonymous.domain.ids import ConversationId, MessageId, RunId
from anonymous.domain.models import Completeness, Message, MessageRole
from anonymous.domain.provenance import (
    COMPONENTS,
    ComponentIdentity,
    ContextSelection,
    ExecutionProvenance,
)

CID = ConversationId("c-1")


def message(
    position: int, content: str, *, assistant: bool = False, truncated: bool = False
) -> Message:
    return Message(
        id=MessageId(f"m{position}"),
        conversation_id=CID,
        position=position,
        role=MessageRole.ASSISTANT if assistant else MessageRole.USER,
        content=content,
        committed_at=datetime(2026, 1, 1, tzinfo=UTC),
        produced_by_run_id=RunId(f"r{position}") if assistant else None,
        completeness=Completeness.TRUNCATED if truncated else None,
    )


class ListSource:
    def __init__(self, messages: list[Message]) -> None:
        self.messages = messages

    def read_messages_through(
        self, conversation_id: ConversationId, last_message_id: MessageId
    ) -> tuple[Message, ...]:
        cut = next(m.position for m in self.messages if m.id == last_message_id)
        return tuple(m for m in self.messages if m.position <= cut)


HISTORY = [
    message(1, "a" * 10),
    message(2, "b" * 10, assistant=True),
    message(3, "c" * 10),
    message(4, "d" * 10, assistant=True),
    message(5, "e" * 5),
]


def positions(selected: tuple[Message, ...]) -> list[int]:
    return [m.position for m in selected]


# -- the rule -----------------------------------------------------------------------------------


def test_no_limit_selects_everything() -> None:
    assert select_recent(tuple(HISTORY), None) == tuple(HISTORY)


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (45, [1, 2, 3, 4, 5]),  # exact boundary: 45 characters in total fits
        (44, [2, 3, 4, 5]),  # one character over: the earliest message drops
        (35, [2, 3, 4, 5]),
        (34, [3, 4, 5]),
        (5, [5]),  # the trigger alone, exactly at the limit
        (4, [5]),  # the trigger alone, over the limit: still selected, never dropped or cut
        (0, [5]),
    ],
)
def test_selection_is_the_longest_fitting_contiguous_suffix(
    limit: int, expected: list[int]
) -> None:
    assert positions(select_recent(tuple(HISTORY), limit)) == expected


def test_selection_stops_at_the_first_message_that_does_not_fit() -> None:
    history = (message(1, "a"), message(2, "x" * 50, assistant=True), message(3, "c"))
    # message 1 would fit, but it lies beyond message 2, which does not: it is never reached
    assert positions(select_recent(history, 10)) == [3]


def test_the_triggering_message_is_the_last_selected_and_roles_and_order_are_kept() -> None:
    selected = select_recent(tuple(HISTORY), 30)
    assert selected[-1].id == "m5"
    assert [m.role for m in selected] == [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.USER]
    assert positions(selected) == sorted(positions(selected))


def test_an_empty_history_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        select_recent((), 10)


def test_counting_is_in_characters_not_bytes_and_is_only_a_proxy() -> None:
    history = (message(1, "é" * 10), message(2, "x"))  # 20 bytes, 10 characters
    assert positions(select_recent(history, 11)) == [1, 2]


# -- the builder --------------------------------------------------------------------------------


def test_the_view_carries_role_and_content_verbatim() -> None:
    builder = BoundedRecentContextBuilder(ListSource(HISTORY))
    view = builder.build_view(HISTORY[-1], 30)  # 5 + 10 + 10 fits, one more message does not
    assert [(m.role, m.content) for m in view.request.messages] == [
        (m.role, m.content) for m in HISTORY[2:]
    ]


def test_selection_numbers_are_exact() -> None:
    builder = BoundedRecentContextBuilder(ListSource(HISTORY))
    selection = builder.build_view(HISTORY[-1], 35).selection
    assert selection is not None
    assert selection.to_dict() == {
        "first_message_id": "m2",
        "first_position": 2,
        "selected_count": 4,
        "omitted_count": 1,
        "selected_chars": 35,
        "limit_chars": 35,
        "measure": "characters",
        "truncated_included_count": 0,
    }


def test_the_view_is_built_from_the_prefix_through_the_trigger_only() -> None:
    builder = BoundedRecentContextBuilder(ListSource(HISTORY))
    selection = builder.build_view(HISTORY[2], 1000).selection  # trigger is message 3
    assert selection is not None
    assert (selection.first_position, selection.selected_count, selection.omitted_count) == (
        1,
        3,
        0,
    )


def test_building_twice_gives_the_same_view_and_changes_nothing() -> None:
    source = ListSource(list(HISTORY))
    builder = BoundedRecentContextBuilder(source)
    assert builder.build_view(HISTORY[-1], 20) == builder.build_view(HISTORY[-1], 20)
    assert source.messages == HISTORY


def test_a_truncated_reply_is_included_verbatim_and_counted() -> None:
    cut = "The three colors are red, orange and"
    history = [
        message(1, "name three colors"),
        message(2, cut, assistant=True, truncated=True),
        message(3, "go on"),
    ]
    view = BoundedRecentContextBuilder(ListSource(history)).build_view(history[-1], 1000)
    assert [m.content for m in view.request.messages][1] == cut  # no marker, no edit
    assert view.selection is not None and view.selection.truncated_included_count == 1
    excluded = BoundedRecentContextBuilder(ListSource(history)).build_view(history[-1], 20)
    assert excluded.selection is not None and excluded.selection.truncated_included_count == 0


def test_an_unlimited_bounded_view_equals_the_whole_history_view() -> None:
    source = ListSource(HISTORY)
    bounded = BoundedRecentContextBuilder(source)
    whole = ContextBuilder(source)
    assert bounded.build(HISTORY[-1]) == whole.build(HISTORY[-1])
    unlimited = bounded.build_view(HISTORY[-1], None)
    assert unlimited.request == whole.build(HISTORY[-1])
    assert unlimited.selection is not None and unlimited.selection.omitted_count == 0
    assert unlimited.selection.limit_chars is None


def test_whole_history_view_has_no_selection_record() -> None:
    assert ContextBuilder(ListSource(HISTORY)).build_view(HISTORY[-1], 1).selection is None


def test_the_bounded_builder_reproduces_the_slice_0a_golden_views_without_a_limit() -> None:
    factory: BuilderFactory = BoundedRecentContextBuilder
    assert golden_replay(factory) == []


# -- manifests ----------------------------------------------------------------------------------


def test_the_two_configurations_have_distinct_digests_and_the_baseline_is_unchanged() -> None:
    assert bounded_recent_manifest().digest != baseline_manifest().digest
    assert bounded_recent_manifest().context.id == "bounded-recent-history"
    assert bounded_recent_manifest().context.version == 1
    assert default_configuration_digest() == bounded_recent_manifest().digest
    # The pinned baseline digest must never move: an existing conversation is bound to it.
    assert baseline_manifest().context.id == "whole-history"
    assert dict(baseline_manifest().baseline_reference)["commit"].startswith("01e9f46")


# -- provenance serialization -------------------------------------------------------------------


def base_provenance(selection: ContextSelection | None = None) -> ExecutionProvenance:
    return ExecutionProvenance(
        application_build=ComponentIdentity.label_only("app"),
        adapter=ComponentIdentity.label_only("adapter"),
        model_artifact=ComponentIdentity.label_only("model"),
        runtime_build=ComponentIdentity.label_only("runtime"),
        context_configuration=ComponentIdentity.label_only("whole-history@1"),
        behavior_configuration=ComponentIdentity.none(),
        context_selection=selection,
    )


SELECTION = ContextSelection("m2", 2, 4, 1, 35, 35, 1)


def test_an_absent_selection_keeps_the_exact_older_serialization() -> None:
    text = base_provenance().to_json()
    assert "context_selection" not in text
    assert set(json.loads(text)) == set(COMPONENTS)
    # byte-for-byte what the pre-ADR-0017 code wrote
    legacy = json.dumps(
        {
            name: {
                "label": getattr(base_provenance(), name).label,
                "digest": None,
                "verification": "verified" if name == "behavior_configuration" else "unspecified",
                "explicit_none": name == "behavior_configuration",
            }
            for name in COMPONENTS
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    assert text == legacy


def test_a_stored_row_without_the_field_reads_as_unrecorded() -> None:
    parsed = ExecutionProvenance.from_json(base_provenance().to_json())
    assert parsed.context_selection is None
    assert parsed == base_provenance()


def test_a_selection_round_trips_and_carries_no_message_content() -> None:
    text = base_provenance(SELECTION).to_json()
    assert ExecutionProvenance.from_json(text).context_selection == SELECTION
    body = json.loads(text)["context_selection"]
    assert set(body) == {
        "first_message_id",
        "first_position",
        "selected_count",
        "omitted_count",
        "selected_chars",
        "limit_chars",
        "measure",
        "truncated_included_count",
    }


def test_an_unlimited_selection_round_trips_with_a_null_limit() -> None:
    unlimited = ContextSelection("m1", 1, 3, 0, 12, None, 0)
    parsed = ExecutionProvenance.from_json(base_provenance(unlimited).to_json())
    assert parsed.context_selection == unlimited


@pytest.mark.parametrize(
    "kwargs",
    [
        {"selected_count": 0},
        {"omitted_count": -1},
        {"first_position": 0},
        {"measure": "tokens"},
    ],
)
def test_an_invalid_selection_is_refused(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "first_message_id": "m1",
        "first_position": 1,
        "selected_count": 1,
        "omitted_count": 0,
        "selected_chars": 1,
        "limit_chars": None,
        "truncated_included_count": 0,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        ContextSelection(**values)  # type: ignore[arg-type]
