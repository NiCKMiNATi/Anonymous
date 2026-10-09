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
  onRetry: () => void;
  /** Reload the saved history, then drop the unconfirmed local copy. Sends nothing. */
  onDiscard: () => void;
  /** Reload the saved history, then offer the text again as a deliberately new message. */
  onSendAsNew: () => void;
  /** True while history is being reloaded to settle an unconfirmed send. */
  reconciling: boolean;
  reconcileError: string | null;
}

export function MessageList({
  detail,
  pending,
  onRetry,
  onDiscard,
  onSendAsNew,
  reconciling,
  reconcileError,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [detail.messages.length, pending?.status]);

  const runsById = new Map(detail.runs.map((run) => [run.id, run]));
  const failedByTrigger = new Map(
    detail.runs.filter((run) => run.status === "failed").map((run) => [run.triggering_message_id, run]),
  );

  return (
    <div className="messages" role="log" aria-label="Messages" aria-live="polite">
      {detail.messages.length === 0 && !pending && (
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
                <ul>
                  <li>
                    <strong>Retry sending</strong> re-sends this same message.
                  </li>
                  <li>
                    <strong>Discard and reload</strong> reloads the saved history and drops this
                    unconfirmed copy. Nothing is sent again.
                  </li>
                  <li>
                    <strong>Reload, then send again as a new message</strong> reloads the history,
                    then puts the text in the message box. Sending it creates a new message, even
                    if the earlier attempt turns out to be saved.
                  </li>
                </ul>
                {reconciling && <p role="status">Checking the saved history…</p>}
                {reconcileError && <p>{reconcileError}</p>}
                <div className="actions">
                  <button type="button" onClick={onRetry} disabled={reconciling}>
                    Retry sending
                  </button>
                  <button type="button" onClick={onDiscard} disabled={reconciling}>
                    Discard and reload
                  </button>
                  <button type="button" onClick={onSendAsNew} disabled={reconciling}>
                    Reload, then send again as a new message
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
