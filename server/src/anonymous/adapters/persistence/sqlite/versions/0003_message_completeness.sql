-- 0003 (ADR-0016, dev-only): the completeness of an assistant message.
--
-- ADDITIVE ONLY. No row is rewritten and nothing is backfilled: every existing message, user or
-- assistant, keeps completeness NULL, which means "unclassified" (no completeness is invented for a
-- message whose finish was never recorded). No existing trigger or constraint is changed.
--
--   NULL        unclassified: every user message and every assistant message created before 0003
--   'complete'  the answer ended naturally (a normal complete delivery)
--   'truncated' the answer was cut off at the model's output limit (ADR-0016)
--
-- The value is written in the same INSERT that publishes the assistant message (T4), so it commits
-- atomically with the run's success; the existing messages_are_immutable trigger fires on any
-- UPDATE, so it can never change afterwards.

ALTER TABLE messages ADD COLUMN completeness TEXT
    CHECK (completeness IS NULL OR completeness IN ('complete', 'truncated'));

-- Completeness describes an assistant answer; a user message is never classified.
CREATE TRIGGER messages_completeness_only_for_assistant BEFORE INSERT ON messages
WHEN NEW.role <> 'assistant' AND NEW.completeness IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'only an assistant message can carry a completeness'); END;
