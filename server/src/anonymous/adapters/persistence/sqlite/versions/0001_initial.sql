-- Slice 0A initial schema. Only what the slice needs: no Memory, branch, merge or access tables.
-- Instants are absolute UTC text 'YYYY-MM-DDTHH:MM:SS.ffffffZ' (implementation-local encoding).
-- Message order is `position`; instants are never an ordering authority.

CREATE TABLE users (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??.??????Z')
);

CREATE TABLE conversations (
    id            TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users (id),
    title         TEXT,
    created_at    TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??.??????Z')
);
CREATE INDEX conversations_by_owner ON conversations (owner_user_id, created_at);

CREATE TABLE messages (
    id                 TEXT PRIMARY KEY,
    conversation_id    TEXT NOT NULL REFERENCES conversations (id),
    position           INTEGER NOT NULL CHECK (position >= 1),
    role               TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content            TEXT NOT NULL CHECK (length(content) > 0),
    committed_at       TEXT NOT NULL CHECK (committed_at GLOB '????-??-??T??:??:??.??????Z'),
    produced_by_run_id TEXT,
    -- An assistant message always has a producing run; a user message never does.
    CHECK ((role = 'assistant') = (produced_by_run_id IS NOT NULL)),
    UNIQUE (conversation_id, position),
    UNIQUE (id, conversation_id),
    UNIQUE (produced_by_run_id),
    FOREIGN KEY (produced_by_run_id, conversation_id)
        REFERENCES model_runs (id, conversation_id)
);

CREATE TABLE model_runs (
    id                    TEXT PRIMARY KEY,
    conversation_id       TEXT NOT NULL REFERENCES conversations (id),
    triggering_message_id TEXT NOT NULL,
    status                TEXT NOT NULL
        CHECK (status IN ('pending', 'in_flight', 'succeeded', 'failed', 'indeterminate')),
    model_id              TEXT,
    runtime_id            TEXT,
    failure_code          TEXT,
    failure_message       TEXT,
    requested_at          TEXT NOT NULL CHECK (requested_at GLOB '????-??-??T??:??:??.??????Z'),
    dispatched_at         TEXT,
    settled_at            TEXT,
    UNIQUE (id, conversation_id),
    FOREIGN KEY (triggering_message_id, conversation_id)
        REFERENCES messages (id, conversation_id),
    CHECK ((model_id IS NULL) = (runtime_id IS NULL)),
    CHECK ((model_id IS NULL) = (dispatched_at IS NULL)),
    CHECK (status <> 'pending' OR
           (model_id IS NULL AND settled_at IS NULL AND failure_code IS NULL)),
    CHECK (status <> 'in_flight' OR
           (model_id IS NOT NULL AND settled_at IS NULL AND failure_code IS NULL)),
    CHECK (status <> 'succeeded' OR
           (model_id IS NOT NULL AND settled_at IS NOT NULL AND failure_code IS NULL)),
    CHECK (status <> 'failed' OR (failure_code IS NOT NULL AND settled_at IS NOT NULL)),
    CHECK (status <> 'indeterminate' OR
           (model_id IS NOT NULL AND settled_at IS NULL AND failure_code IS NULL))
);

-- At most one unsettled generation per conversation; survives restart (LM-06).
CREATE UNIQUE INDEX model_runs_one_unsettled_per_conversation
    ON model_runs (conversation_id)
    WHERE status IN ('pending', 'in_flight', 'indeterminate');

-- Operation correlation: one logical submission maps to at most one user message and run.
CREATE TABLE submissions (
    owner_user_id   TEXT NOT NULL REFERENCES users (id),
    submission_id   TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations (id),
    content_sha256  TEXT NOT NULL,
    user_message_id TEXT NOT NULL UNIQUE REFERENCES messages (id),
    run_id          TEXT NOT NULL UNIQUE REFERENCES model_runs (id),
    created_at      TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??.??????Z'),
    PRIMARY KEY (owner_user_id, submission_id)
);

-- Preservation of committed facts (LM-01) enforced by the store, not only by application code.
CREATE TRIGGER messages_are_immutable BEFORE UPDATE ON messages
BEGIN SELECT RAISE(ABORT, 'committed messages are immutable'); END;

CREATE TRIGGER messages_are_not_deleted BEFORE DELETE ON messages
BEGIN SELECT RAISE(ABORT, 'committed messages cannot be deleted'); END;

CREATE TRIGGER submissions_are_immutable BEFORE UPDATE ON submissions
BEGIN SELECT RAISE(ABORT, 'submissions are immutable'); END;

CREATE TRIGGER submissions_are_not_deleted BEFORE DELETE ON submissions
BEGIN SELECT RAISE(ABORT, 'submissions cannot be deleted'); END;

CREATE TRIGGER model_runs_are_not_deleted BEFORE DELETE ON model_runs
BEGIN SELECT RAISE(ABORT, 'run evidence cannot be deleted'); END;

CREATE TRIGGER model_runs_settled_are_immutable BEFORE UPDATE ON model_runs
WHEN OLD.status IN ('succeeded', 'failed')
BEGIN SELECT RAISE(ABORT, 'settled runs are immutable'); END;

CREATE TRIGGER model_runs_identity_is_immutable
BEFORE UPDATE OF id, conversation_id, triggering_message_id, requested_at ON model_runs
BEGIN SELECT RAISE(ABORT, 'run identity is immutable'); END;

-- An assistant message may only be committed for a run that is in flight...
CREATE TRIGGER assistant_message_requires_in_flight_run BEFORE INSERT ON messages
WHEN NEW.role = 'assistant'
 AND COALESCE((SELECT status FROM model_runs WHERE id = NEW.produced_by_run_id), '') <> 'in_flight'
BEGIN SELECT RAISE(ABORT, 'assistant message requires an in-flight producing run'); END;

-- ...and a run may only become 'succeeded' when its assistant message exists.
CREATE TRIGGER run_success_requires_response BEFORE UPDATE ON model_runs
WHEN NEW.status = 'succeeded'
 AND NOT EXISTS (SELECT 1 FROM messages WHERE produced_by_run_id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'a succeeded run requires its assistant message'); END;
