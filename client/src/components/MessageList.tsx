import { Fragment, useEffect, useRef } from "react";
import type { ConversationDetailDto } from "../api/types";
import { MessageItem } from "./MessageItem";

export interface PendingSubmission {
  submissionId: string;
  content: string;
  /** `sending`: awaiting the server. `unknown`: the outcome could not be confirmed. */
  status: "sending" | "unknown";
  error?: string;
}

interface Props {
  detail: ConversationDetailDto;
  pending: PendingSubmission | null;
  /** Messages the user stopped tracking without a confirmed outcome (this conversation only). */
  abandoned: PendingSubmission[];
  /** Re-send the same message with the same submission id; the server's answer decides. */
  onRetry: () => void;
  /** Stop tracking the message (user decision). Sends nothing; the outcome stays unknown. */
  onAbandon: () => void;
  /** Stop tracking it and put the text in the composer to be sent as a deliberately new message. */
  onAbandonAndRewrite: () => void;
  onRetryAbandoned: (submissionId: string) => void;
  onForgetAbandoned: (submissionId: string) => void;
  /** True while another send is active, so a second one cannot start. */
  busy: boolean;
}

export function MessageList({
  detail,
  pending,
  abandoned,
  onRetry,
  onAbandon,
  onAbandonAndRewrite,
  onRetryAbandoned,
  onForgetAbandoned,
  busy,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [detail.messages.length, pending?.status, abandoned.length]);

  const runsById = new Map(detail.runs.map((run) => [run.id, run]));
  const failedByTrigger = new Map(
    detail.runs.filter((run) => run.status === "failed").map((run) => [run.triggering_message_id, run]),
  );

  return (
    <div className="messages" role="log" aria-label="Messages" aria-live="polite">
      {detail.messages.length === 0 && !pending && abandoned.length === 0 && (
        <p className="empty">No messages yet. Say hello.</p>
      )}
      <ol className="messages__list">
        {detail.messages.map((message) => {
          const failed = failedByTrigger.get(message.id);
          return (
            <Fragment key={message.id}>
              <MessageItem
                message={message}
                producingRun={
                  message.produced_by_run_id ? runsById.get(message.produced_by_run_id) : undefined
                }
              />
              {failed && (
                <li className="run-failure" role="alert">
                  <strong>Response failed.</strong> {failed.failure_message ?? "Generation failed."}{" "}
                  <span className="run-failure__code">({failed.failure_code})</span>
                  <br />
                  Your message above was saved. No response was recorded for it.
                </li>
              )}
            </Fragment>
          );
        })}
        {abandoned.map((item) => (
          <li
            key={item.submissionId}
            className="message message--user message--pending message--abandoned"
            data-testid="abandoned-message"
          >
            <div className="message__meta">
              <span className="message__author">You</span>
              <span className="message__time">Abandoned — outcome unknown</span>
            </div>
            <div className="message__body">{item.content}</div>
            <div className="run-failure" role="note">
              You stopped tracking this message before the server confirmed anything. It is{" "}
              <strong>not</strong> confirmed failed: it may still be saved, and a refreshed history
              can be older than the save. If it appears in the history it was saved. Retrying sends
              the same message with the same id, so the server answers with what actually happened
              and it is never saved twice. Forgetting only removes this note.
              <div className="actions">
                <button
                  type="button"
                  onClick={() => onRetryAbandoned(item.submissionId)}
                  disabled={busy}
                >
                  Retry abandoned message
                </button>
                <button type="button" onClick={() => onForgetAbandoned(item.submissionId)}>
                  Forget abandoned message
                </button>
              </div>
            </div>
          </li>
        ))}
        {pending && (
          <li className="message message--user message--pending" data-testid="pending-message">
            <div className="message__meta">
              <span className="message__author">You</span>
              <span className="message__time">
                {pending.status === "sending" ? "Sending…" : "Not confirmed saved"}
              </span>
            </div>
            <div className="message__body">{pending.content}</div>
            {pending.status === "unknown" && (
              <div className="run-failure" role="alert">
                {pending.error ?? "The server could not confirm whether this was saved."} It may
                or may not be saved. Retrying is safe: the same message is never saved twice.
                Reloading the history cannot settle it, because a history read can be older than
                the save; only the server's answer to this message's own id can.
                <ul>
                  <li>
                    <strong>Retry sending</strong> re-sends this same message and shows what the
                    server answers.
                  </li>
                  <li>
                    <strong>Discard and reload</strong> abandons it: you stop tracking it and the
                    history is refreshed. Nothing is sent again, and it is not marked as failed.
                  </li>
                  <li>
                    <strong>Abandon, then send again as a new message</strong> does the same and
                    puts the text in the message box. Sending it saves a new message, even if this
                    one turns out to be saved.
                  </li>
                </ul>
                <div className="actions">
                  <button type="button" onClick={onRetry}>
                    Retry sending
                  </button>
                  <button type="button" onClick={onAbandon}>
                    Discard and reload
                  </button>
                  <button type="button" onClick={onAbandonAndRewrite}>
                    Abandon, then send again as a new message
                  </button>
                </div>
              </div>
            )}
          </li>
        )}
      </ol>
      {pending?.status === "sending" && (
        <p className="generating" role="status">
          Generating response…
        </p>
      )}
      <div ref={endRef} />
    </div>
  );
}
