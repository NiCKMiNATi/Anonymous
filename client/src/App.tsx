import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api/client";
import type { ConversationDetailDto, ConversationDto } from "./api/types";
import { Composer } from "./components/Composer";
import { ConversationList } from "./components/ConversationList";
import { MessageList, type PendingSubmission } from "./components/MessageList";
import { newSubmissionId } from "./ids";
import { useHashSelection } from "./useHashSelection";

const UNSETTLED = new Set(["pending", "in_flight", "indeterminate"]);

type DetailState = "idle" | "loading" | "ready" | "error";

interface Pending extends PendingSubmission {
  conversationId: string;
}

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError("client", null, null, "Something unexpected went wrong.");
}

export function App() {
  const [selectedId, select] = useHashSelection();
  const [serverDown, setServerDown] = useState(false);
  const [conversations, setConversations] = useState<ConversationDto[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<ConversationDetailDto | null>(null);
  const [detailState, setDetailState] = useState<DetailState>("idle");
  const [detailError, setDetailError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ key: 0, text: "" });

  const noteResult = useCallback((error: unknown): ApiError => {
    const apiError = asApiError(error);
    if (apiError.kind === "network") setServerDown(true);
    return apiError;
  }, []);

  const loadConversations = useCallback(async () => {
    try {
      const list = await api.listConversations();
      setConversations(list);
      setListError(null);
      setServerDown(false);
    } catch (error) {
      setListError(noteResult(error).message);
    }
  }, [noteResult]);

  const loadDetail = useCallback(
    async (id: string, options: { quiet?: boolean } = {}) => {
      if (!options.quiet) setDetailState("loading");
      try {
        const loaded = await api.getConversation(id);
        setDetail(loaded);
        setDetailState("ready");
        setDetailError(null);
        setServerDown(false);
      } catch (error) {
        setDetailError(noteResult(error).message);
        setDetailState("error");
      }
    },
    [noteResult],
  );

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (!selectedId && conversations && conversations.length > 0) {
      select(conversations[0]!.id);
    }
  }, [selectedId, conversations, select]);

  useEffect(() => {
    setSendError(null);
    if (!selectedId) {
      setDetail(null);
      setDetailState("idle");
      return;
    }
    setDetail(null);
    void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  const createConversation = async () => {
    setCreating(true);
    try {
      const created = await api.createConversation();
      setConversations((current) => [created, ...(current ?? [])]);
      select(created.id);
      setListError(null);
    } catch (error) {
      setListError(noteResult(error).message);
    } finally {
      setCreating(false);
    }
  };

  const submit = async (conversationId: string, submissionId: string, content: string) => {
    setSendError(null);
    setPending({ conversationId, submissionId, content, status: "sending" });
    try {
      await api.sendMessage(conversationId, submissionId, content);
      setPending(null);
      await loadDetail(conversationId, { quiet: true }); // the server's history is authoritative
    } catch (error) {
      const apiError = noteResult(error);
      if (apiError.unknownOutcome) {
        setPending({
          conversationId,
          submissionId,
          content,
          status: "unknown",
          error: apiError.message,
        });
        return;
      }
      // A definite refusal (busy, invalid, not found): nothing was saved; keep the draft.
      setPending(null);
      setSendError(apiError.message);
      setDraft((current) => ({ key: current.key + 1, text: content }));
      await loadDetail(conversationId, { quiet: true });
    }
  };

  const send = (content: string) => {
    if (!selectedId) return;
    void submit(selectedId, newSubmissionId(), content);
  };

  const retry = () => {
    if (pending) void submit(pending.conversationId, pending.submissionId, pending.content);
  };

  const discard = () => {
    if (!pending) return;
    setDraft((current) => ({ key: current.key + 1, text: pending.content }));
    const id = pending.conversationId;
    setPending(null);
    void loadDetail(id, { quiet: true });
  };

  const refresh = () => {
    void loadConversations();
    if (selectedId) void loadDetail(selectedId, { quiet: true });
  };

  const visiblePending = pending && pending.conversationId === selectedId ? pending : null;
  const unsettled = detail?.runs.some((run) => UNSETTLED.has(run.status)) ?? false;
  const composerDisabled = pending !== null || unsettled || detailState !== "ready";
  let disabledReason: string | undefined;
  if (unsettled && pending === null) {
    disabledReason =
      "A response is being generated or is unresolved for this conversation, so sending is paused. Use Refresh to check its state.";
  }

  return (
    <div className="app">
      <header className="app__header">
        <h1>Anonymous</h1>
        <p className="dev-banner">
          Development build — no authentication yet; local use only. Use synthetic data.
        </p>
      </header>

      {serverDown && (
        <div className="banner banner--error" role="alert">
          Cannot reach the Anonymous server. Is it running?{" "}
          <button type="button" onClick={refresh}>
            Retry
          </button>
        </div>
      )}

      <div className="app__body">
        <div className="app__sidebar">
          {conversations === null && !listError && <p role="status">Loading conversations…</p>}
          {listError && !serverDown && (
            <p className="banner banner--error" role="alert">
              {listError}
            </p>
          )}
          {conversations !== null && (
            <ConversationList
              conversations={conversations}
              selectedId={selectedId}
              onSelect={select}
              onCreate={() => void createConversation()}
              creating={creating}
            />
          )}
        </div>

        <main className="conversation" aria-label="Current conversation">
          {!selectedId && conversations !== null && conversations.length === 0 && (
            <p className="empty">Create a conversation to get started.</p>
          )}
          {selectedId && detailState === "loading" && <p role="status">Loading conversation…</p>}
          {selectedId && detailState === "error" && !serverDown && (
            <p className="banner banner--error" role="alert">
              {detailError}
            </p>
          )}
          {selectedId && detail && (
            <>
              <div className="conversation__header">
                <h2>{detail.conversation.title ?? "Untitled conversation"}</h2>
                <button type="button" onClick={refresh}>
                  Refresh
                </button>
              </div>
              <MessageList
                detail={detail}
                pending={visiblePending}
                onRetry={retry}
                onDiscard={discard}
              />
              <Composer
                key={draft.key}
                restoredText={draft.text}
                disabled={composerDisabled}
                disabledReason={disabledReason}
                error={sendError}
                onSend={send}
              />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
