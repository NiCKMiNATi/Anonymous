-- 0002 (Slice 0B-1, LD-04 revision 3.1): run ownership, durable closure fence, invocation-handoff
-- marker, execution slot, runtime binding, provenance, retry intents, and conversation
-- configuration bindings.
--
-- Legacy (0A) rows are PRESERVED UNCHANGED: every existing run and conversation receives
-- record_epoch = 'legacy_0a' through a column default; no status, label, instant, failure field or
-- message is rewritten, and no fence, handoff, binding, slot, provenance or configuration is
-- invented for them. Unresolved legacy runs keep dispatch blocked (design §5.5).
--
-- The migration STOPS SAFELY (aborts, rolls back, leaves the dataset untouched) when the dataset
-- is structurally inconsistent in a way that cannot be represented without inventing facts.
-- Unresolved legacy executions are NOT such an inconsistency.

-- ---- pre-flight (each failing CHECK names the violated precondition) ----------------------------
CREATE TABLE _preflight (
    succeeded_without_message INTEGER NOT NULL,
    message_on_non_succeeded INTEGER NOT NULL,
    several_unsettled INTEGER NOT NULL,
    message_after_unsettled INTEGER NOT NULL,
    trigger_not_user INTEGER NOT NULL,
    CONSTRAINT preflight_succeeded_run_without_message CHECK (succeeded_without_message = 0),
    CONSTRAINT preflight_assistant_message_on_non_succeeded_run CHECK (message_on_non_succeeded = 0),
    CONSTRAINT preflight_several_unsettled_runs_in_one_conversation CHECK (several_unsettled = 0),
    CONSTRAINT preflight_message_accepted_after_unsettled_run CHECK (message_after_unsettled = 0),
    CONSTRAINT preflight_run_trigger_is_not_a_user_message CHECK (trigger_not_user = 0)
);
INSERT INTO _preflight VALUES (
    EXISTS (SELECT 1 FROM model_runs r WHERE r.status = 'succeeded'
            AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.produced_by_run_id = r.id)),
    EXISTS (SELECT 1 FROM messages m JOIN model_runs r ON r.id = m.produced_by_run_id
            WHERE r.status <> 'succeeded'),
    EXISTS (SELECT 1 FROM model_runs WHERE status IN ('pending', 'in_flight', 'indeterminate')
            GROUP BY conversation_id HAVING COUNT(*) > 1),
    EXISTS (SELECT 1 FROM model_runs r JOIN messages t ON t.id = r.triggering_message_id
            WHERE r.status IN ('pending', 'in_flight', 'indeterminate')
              AND EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = r.conversation_id
                          AND m.position > t.position)),
    EXISTS (SELECT 1 FROM model_runs r JOIN messages t ON t.id = r.triggering_message_id
            WHERE t.role <> 'user')
);
DROP TABLE _preflight;

-- ---- configuration objects (insert-only) ---------------------------------------------------------
CREATE TABLE effective_configurations (
    digest     TEXT PRIMARY KEY CHECK (digest GLOB 'sha256:*'),
    manifest   TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??.??????Z')
);
CREATE TRIGGER effective_configurations_are_immutable BEFORE UPDATE ON effective_configurations
BEGIN SELECT RAISE(ABORT, 'effective configurations are immutable'); END;
CREATE TRIGGER effective_configurations_are_not_deleted BEFORE DELETE ON effective_configurations
BEGIN SELECT RAISE(ABORT, 'effective configurations cannot be deleted'); END;

ALTER TABLE conversations ADD COLUMN record_epoch TEXT NOT NULL DEFAULT 'legacy_0a'
    CHECK (record_epoch IN ('legacy_0a', '0b'));
CREATE TRIGGER conversations_new_rows_are_current_epoch BEFORE INSERT ON conversations
WHEN NEW.record_epoch <> '0b'
BEGIN SELECT RAISE(ABORT, 'new conversations must be current-epoch records'); END;
CREATE TRIGGER conversations_epoch_is_immutable BEFORE UPDATE OF record_epoch ON conversations
BEGIN SELECT RAISE(ABORT, 'record epoch is immutable'); END;

CREATE TABLE conversation_configuration_bindings (
    conversation_id      TEXT NOT NULL REFERENCES conversations (id),
    seq                  INTEGER NOT NULL CHECK (seq >= 1),
    configuration_digest TEXT NOT NULL REFERENCES effective_configurations (digest),
    origin               TEXT NOT NULL CHECK (origin IN ('initial', 'adoption', 'legacy_baseline')),
    baseline_evidence    TEXT,
    owner_user_id        TEXT REFERENCES users (id),
    adoption_id          TEXT,
    created_at           TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??.??????Z'),
    PRIMARY KEY (conversation_id, seq),
    CHECK ((origin = 'adoption') = (adoption_id IS NOT NULL)),
    CHECK ((origin = 'adoption') = (owner_user_id IS NOT NULL)),
    CHECK ((origin = 'legacy_baseline') = (baseline_evidence IS NOT NULL)),
    CHECK (origin <> 'initial' OR seq = 1)
);
CREATE UNIQUE INDEX conversation_bindings_adoption_intent
    ON conversation_configuration_bindings (owner_user_id, adoption_id)
    WHERE adoption_id IS NOT NULL;
CREATE TRIGGER conversation_bindings_are_immutable BEFORE UPDATE ON conversation_configuration_bindings
BEGIN SELECT RAISE(ABORT, 'configuration bindings are append-only'); END;
CREATE TRIGGER conversation_bindings_are_not_deleted BEFORE DELETE ON conversation_configuration_bindings
BEGIN SELECT RAISE(ABORT, 'configuration bindings cannot be deleted'); END;
CREATE TRIGGER conversation_adoption_requires_settled_conversation
BEFORE INSERT ON conversation_configuration_bindings
WHEN NEW.origin = 'adoption'
 AND EXISTS (SELECT 1 FROM model_runs WHERE conversation_id = NEW.conversation_id
             AND status IN ('pending', 'in_flight', 'indeterminate'))
BEGIN SELECT RAISE(ABORT, 'a configuration cannot be adopted while a run is unsettled'); END;

-- ---- run ownership, fence, handoff, binding, provenance -----------------------------------------
ALTER TABLE model_runs ADD COLUMN record_epoch TEXT NOT NULL DEFAULT 'legacy_0a'
    CHECK (record_epoch IN ('legacy_0a', '0b'));
ALTER TABLE model_runs ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0
    CHECK (state_version >= 0);
ALTER TABLE model_runs ADD COLUMN kind TEXT NOT NULL DEFAULT 'initial'
    CHECK (kind IN ('initial', 'retry'));
ALTER TABLE model_runs ADD COLUMN retry_of_run_id TEXT REFERENCES model_runs (id);
ALTER TABLE model_runs ADD COLUMN closed_at TEXT
    CHECK (closed_at IS NULL OR closed_at GLOB '????-??-??T??:??:??.??????Z');
ALTER TABLE model_runs ADD COLUMN closure_reason TEXT
    CHECK (closure_reason IS NULL OR closure_reason IN
        ('deadline', 'shutdown', 'publication_unconfirmed', 'connection_lost',
         'runtime_failure', 'instance_mismatch', 'supervisor_fault', 'orphan_reconcile'));
ALTER TABLE model_runs ADD COLUMN handoff TEXT
    CHECK (handoff IS NULL OR handoff IN ('NONE', 'STARTED'));
ALTER TABLE model_runs ADD COLUMN handoff_outcome TEXT
    CHECK (handoff_outcome IS NULL OR handoff_outcome IN
        ('NOT_CALLED', 'NOT_STARTED', 'ACCEPTED', 'UNKNOWN'));
ALTER TABLE model_runs ADD COLUMN execution_boot_id TEXT;
ALTER TABLE model_runs ADD COLUMN slot_id TEXT;
ALTER TABLE model_runs ADD COLUMN binding_format TEXT;
ALTER TABLE model_runs ADD COLUMN binding_adapter_id TEXT;
ALTER TABLE model_runs ADD COLUMN binding_adapter_version TEXT;
ALTER TABLE model_runs ADD COLUMN binding_instance_ref TEXT;
ALTER TABLE model_runs ADD COLUMN binding_control_ref TEXT;
ALTER TABLE model_runs ADD COLUMN binding_declared_bases TEXT;
ALTER TABLE model_runs ADD COLUMN binding_lifetime_scope TEXT
    CHECK (binding_lifetime_scope IS NULL OR binding_lifetime_scope IN ('owning_process', 'external'));
ALTER TABLE model_runs ADD COLUMN binding_late_delivery_excluded INTEGER
    CHECK (binding_late_delivery_excluded IS NULL OR binding_late_delivery_excluded IN (0, 1));
ALTER TABLE model_runs ADD COLUMN configuration_digest TEXT REFERENCES effective_configurations (digest);
ALTER TABLE model_runs ADD COLUMN provenance_json TEXT;
ALTER TABLE model_runs ADD COLUMN termination_basis TEXT
    CHECK (termination_basis IS NULL OR termination_basis IN
        ('never_dispatched', 'adapter_never_reached', 'runtime_reported_terminal',
         'process_exit_verified', 'execution_terminated_verified'));
ALTER TABLE model_runs ADD COLUMN completion_observed TEXT
    CHECK (completion_observed IS NULL OR completion_observed IN ('yes', 'no', 'unknown'));

-- The execution slot: at most one run owns it, exactly while it is in_flight or indeterminate.
-- Legacy rows have slot_id NULL and never collide (NULLs are distinct).
CREATE UNIQUE INDEX model_runs_one_slot_owner ON model_runs (slot_id)
    WHERE slot_id IS NOT NULL AND status IN ('in_flight', 'indeterminate');

CREATE TABLE retry_intents (
    owner_user_id   TEXT NOT NULL REFERENCES users (id),
    retry_id        TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations (id),
    message_id      TEXT NOT NULL REFERENCES messages (id),
    run_id          TEXT NOT NULL UNIQUE REFERENCES model_runs (id),
    created_at      TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??.??????Z'),
    PRIMARY KEY (owner_user_id, retry_id)
);
CREATE TRIGGER retry_intents_are_immutable BEFORE UPDATE ON retry_intents
BEGIN SELECT RAISE(ABORT, 'retry intents are immutable'); END;
CREATE TRIGGER retry_intents_are_not_deleted BEFORE DELETE ON retry_intents
BEGIN SELECT RAISE(ABORT, 'retry intents cannot be deleted'); END;

-- ---- insert rules --------------------------------------------------------------------------------
CREATE TRIGGER model_runs_begin_pending_in_current_epoch BEFORE INSERT ON model_runs
WHEN NEW.status <> 'pending' OR NEW.record_epoch <> '0b'
BEGIN SELECT RAISE(ABORT, 'new runs are current-epoch and begin pending'); END;

CREATE TRIGGER model_runs_retry_chain BEFORE INSERT ON model_runs
WHEN (NEW.kind = 'retry') <> (NEW.retry_of_run_id IS NOT NULL)
  OR (NEW.kind = 'retry' AND (
        NOT EXISTS (SELECT 1 FROM model_runs p WHERE p.id = NEW.retry_of_run_id
                    AND p.triggering_message_id = NEW.triggering_message_id
                    AND p.conversation_id = NEW.conversation_id AND p.status = 'failed')
     OR EXISTS (SELECT 1 FROM messages t JOIN messages l ON l.conversation_id = t.conversation_id
                WHERE t.id = NEW.triggering_message_id AND l.position > t.position)))
BEGIN SELECT RAISE(ABORT, 'a retry follows a failed run of the latest saved user message'); END;

-- ---- publication: an assistant message needs an in-flight, OPEN-fence, handoff-STARTED run -------
DROP TRIGGER assistant_message_requires_in_flight_run;
CREATE TRIGGER assistant_message_requires_open_started_run BEFORE INSERT ON messages
WHEN NEW.role = 'assistant'
 AND NOT EXISTS (SELECT 1 FROM model_runs WHERE id = NEW.produced_by_run_id
                 AND status = 'in_flight' AND closed_at IS NULL
                 AND handoff = 'STARTED' AND record_epoch = '0b')
BEGIN SELECT RAISE(ABORT, 'assistant message requires an in-flight, open, started current run'); END;

-- ---- update rules: every transition has its own source predicate (design §4.1) ------------------
CREATE TRIGGER model_runs_version_increments BEFORE UPDATE ON model_runs
WHEN NEW.state_version <> OLD.state_version + 1
BEGIN SELECT RAISE(ABORT, 'state_version must increase by exactly one per write'); END;

CREATE TRIGGER model_runs_epoch_and_chain_are_immutable
BEFORE UPDATE OF record_epoch, kind, retry_of_run_id ON model_runs
BEGIN SELECT RAISE(ABORT, 'record epoch and retry chain are immutable'); END;

CREATE TRIGGER model_runs_dispatch_facts_are_immutable BEFORE UPDATE ON model_runs
WHEN OLD.dispatched_at IS NOT NULL AND (
     NEW.slot_id IS NOT OLD.slot_id OR NEW.execution_boot_id IS NOT OLD.execution_boot_id
  OR NEW.binding_format IS NOT OLD.binding_format OR NEW.binding_adapter_id IS NOT OLD.binding_adapter_id
  OR NEW.binding_adapter_version IS NOT OLD.binding_adapter_version
  OR NEW.binding_instance_ref IS NOT OLD.binding_instance_ref
  OR NEW.binding_control_ref IS NOT OLD.binding_control_ref
  OR NEW.binding_declared_bases IS NOT OLD.binding_declared_bases
  OR NEW.binding_lifetime_scope IS NOT OLD.binding_lifetime_scope
  OR NEW.binding_late_delivery_excluded IS NOT OLD.binding_late_delivery_excluded
  OR NEW.configuration_digest IS NOT OLD.configuration_digest
  OR NEW.provenance_json IS NOT OLD.provenance_json
  OR NEW.model_id IS NOT OLD.model_id OR NEW.runtime_id IS NOT OLD.runtime_id
  OR NEW.dispatched_at IS NOT OLD.dispatched_at)
BEGIN SELECT RAISE(ABORT, 'dispatch facts are immutable once recorded'); END;

CREATE TRIGGER model_runs_closure_is_consistent_and_irreversible BEFORE UPDATE ON model_runs
WHEN (NEW.closed_at IS NULL) <> (NEW.closure_reason IS NULL)
  OR (OLD.closed_at IS NOT NULL
      AND (NEW.closed_at IS NOT OLD.closed_at OR NEW.closure_reason IS NOT OLD.closure_reason))
BEGIN SELECT RAISE(ABORT, 'closure needs a reason and is irreversible'); END;

CREATE TRIGGER model_runs_handoff_moves_once BEFORE UPDATE ON model_runs
WHEN NEW.handoff IS NOT OLD.handoff
 AND NOT (OLD.handoff IS 'NONE' AND NEW.handoff IS 'STARTED'
          AND OLD.status = 'in_flight' AND NEW.status = 'in_flight'
          AND OLD.closed_at IS NULL AND NEW.closed_at IS NULL AND OLD.record_epoch = '0b')
 AND NOT (OLD.status = 'pending' AND NEW.status = 'in_flight' AND NEW.handoff IS 'NONE')
BEGIN SELECT RAISE(ABORT, 'handoff moves NONE to STARTED once, with an open fence (T3b)'); END;

CREATE TRIGGER model_runs_handoff_outcome_is_recorded_once BEFORE UPDATE ON model_runs
WHEN NEW.handoff_outcome IS NOT OLD.handoff_outcome
 AND NOT (OLD.handoff_outcome IS NULL AND NEW.handoff_outcome IS NOT NULL
          AND OLD.handoff IS 'STARTED' AND NEW.handoff IS 'STARTED' AND OLD.status = 'in_flight')
BEGIN SELECT RAISE(ABORT, 'handoff outcome is recorded once, after the handoff started'); END;

CREATE TRIGGER model_runs_only_known_transitions BEFORE UPDATE ON model_runs
WHEN NEW.status <> OLD.status
 AND NOT ((OLD.status = 'pending' AND NEW.status IN ('in_flight', 'failed'))
       OR (OLD.status = 'in_flight' AND NEW.status IN ('succeeded', 'failed', 'indeterminate'))
       OR (OLD.status = 'indeterminate' AND NEW.status = 'failed'))
BEGIN SELECT RAISE(ABORT, 'transition not permitted'); END;

-- T3: authorization (slot, binding, provenance, configuration, boot id); refused while any legacy
-- unresolved execution could still be active (global startup quarantine).
CREATE TRIGGER model_runs_t3_dispatch_authorization BEFORE UPDATE ON model_runs
WHEN OLD.status = 'pending' AND NEW.status = 'in_flight'
 AND (OLD.record_epoch <> '0b' OR NEW.handoff IS NOT 'NONE' OR NEW.closed_at IS NOT NULL
      OR NEW.slot_id IS NULL OR NEW.execution_boot_id IS NULL OR NEW.binding_format IS NULL
      OR NEW.binding_adapter_id IS NULL OR NEW.binding_adapter_version IS NULL
      OR NEW.binding_instance_ref IS NULL OR NEW.binding_lifetime_scope IS NULL
      OR NEW.binding_declared_bases IS NULL OR NEW.binding_late_delivery_excluded IS NULL
      OR NEW.configuration_digest IS NULL OR NEW.provenance_json IS NULL
      OR EXISTS (SELECT 1 FROM model_runs WHERE record_epoch = 'legacy_0a'
                 AND status IN ('in_flight', 'indeterminate')))
BEGIN SELECT RAISE(ABORT, 'dispatch authorization requires a complete binding and no legacy blocker'); END;

-- T4: publication only from an in-flight run with an open fence and a started handoff.
CREATE TRIGGER model_runs_t4_publication BEFORE UPDATE ON model_runs
WHEN OLD.status = 'in_flight' AND NEW.status = 'succeeded'
 AND (OLD.closed_at IS NOT NULL OR OLD.handoff IS NOT 'STARTED' OR OLD.record_epoch <> '0b')
BEGIN SELECT RAISE(ABORT, 'publication needs an open fence and a started handoff'); END;

-- T6: indeterminate only after closure.
CREATE TRIGGER model_runs_t6_indeterminate BEFORE UPDATE ON model_runs
WHEN OLD.status = 'in_flight' AND NEW.status = 'indeterminate'
 AND (OLD.closed_at IS NULL OR OLD.record_epoch <> '0b')
BEGIN SELECT RAISE(ABORT, 'indeterminate requires a closed fence'); END;

-- T2: a pending run settles only as never dispatched.
CREATE TRIGGER model_runs_t2_pending_settlement BEFORE UPDATE ON model_runs
WHEN OLD.status = 'pending' AND NEW.status = 'failed'
 AND (NEW.termination_basis IS NOT 'never_dispatched' OR NEW.completion_observed IS NOT 'no')
BEGIN SELECT RAISE(ABORT, 'a pending run settles only as never dispatched'); END;

-- T5 / T7: settlement of an in-flight or indeterminate run needs a basis that is admissible for the
-- durable handoff state, no assistant message, and a closed fence. Binding-less (legacy) runs have
-- no admissible basis in 0B-1.
CREATE TRIGGER model_runs_t5_t7_settlement BEFORE UPDATE ON model_runs
WHEN OLD.status IN ('in_flight', 'indeterminate') AND NEW.status = 'failed'
 AND NOT (
      OLD.record_epoch = '0b' AND OLD.handoff IS NOT NULL
  AND NEW.closed_at IS NOT NULL AND NEW.termination_basis IS NOT NULL
  AND NEW.completion_observed IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM messages WHERE produced_by_run_id = OLD.id)
  AND (
        (OLD.handoff IS 'NONE' AND NEW.termination_basis IS 'never_dispatched')
     OR (OLD.handoff IS 'STARTED' AND OLD.handoff_outcome IS 'NOT_CALLED'
         AND NEW.termination_basis IS 'never_dispatched')
     OR (OLD.handoff IS 'STARTED' AND OLD.handoff_outcome IS 'NOT_STARTED'
         AND NEW.termination_basis IS 'adapter_never_reached')
     OR (OLD.handoff IS 'STARTED' AND COALESCE(OLD.handoff_outcome, 'UNKNOWN') IN ('ACCEPTED', 'UNKNOWN')
         AND NEW.termination_basis IN ('runtime_reported_terminal', 'process_exit_verified'))
     OR (OLD.handoff IS 'STARTED'
         AND (OLD.handoff_outcome IS 'ACCEPTED'
              OR (COALESCE(OLD.handoff_outcome, 'UNKNOWN') = 'UNKNOWN'
                  AND OLD.binding_late_delivery_excluded IS 1))
         AND NEW.termination_basis IS 'execution_terminated_verified')))
BEGIN SELECT RAISE(ABORT, 'settlement needs an admissible termination basis'); END;
