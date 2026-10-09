import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, ApiError } from "./api/client";
import type { ConversationDetailDto, ConversationDto } from "./api/types";
import { Composer } from "./components/Composer";
import { ConversationList } from "./components/ConversationList";
import { MessageList, type PendingSubmission } from "./components/MessageList";
import { newSubmissionId } from "./ids";
import { useHashSelection } from "./useHashSelection";

const UNSETTLED = new Set(["pending", "in_flight", "indeterminate"]);

type DetailState = "idle" | "loading" | "ready" | "error";

/** `applied`: this response is now what is displayed. `superseded`: no longer current, ignored. */
type LoadResult = "applied" | "failed" | "superseded";

interface Pending extends PendingSubmission {
  conversationId: string;
}

/** Text restored into the composer; it belongs to one conversation only. */
interface Draft {
  key: number;
  text: string;
  conversationId: string | null;
  notice: string | null;
}

const RESTORED_AS_NEW_NOTICE =
  "Restored from an unconfirmed send. If the earlier attempt is already shown above, clear this box; sending it saves a new message.";

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError("client", null, null, "Something unexpected went wrong.");
}

export function App() {
  const [selectedId, select, invalidLink] = useHashSelection();
  const [serverDown, setServerDown] = useState(false);
  const [conversations, setConversations] = useState<ConversationDto[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<ConversationDetailDto | null>(null);
  const [detailState, setDetailState] = useState<DetailState>("idle");
  const [detailError, setDetailError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [sendError, setSendError] = useState<{ conversationId: string; message: string } | null>(
    null,
  );
  const [draft, setDraft] = useState<Draft>({
    key: 0,
    text: "",
    conversationId: null,
    notice: null,
  });
  const [reconciling, setReconciling] = useState(false);
  const [reconcileError, setReconcileError] = useState<string | null>(null);

  // Freshness of history loads. `selectedIdRef` is the conversation the user is looking at now;
  // `detailSeq` changes whenever that selection changes (and on unmount) and for every new load,
  // so a response that is no longer the latest request for the current selection is discarded
  // instead of replacing what is displayed. Both are only presentation bookkeeping: the server
  // remains the sole owner of history.
  const selectedIdRef = useRef<string | null>(null);
  const detailSeq = useRef(0);
  useLayoutEffect(() => {
    selectedIdRef.current = selectedId;
    detailSeq.current += 1;
    return () => {
      selectedIdRef.current = null;
      detailSeq.current += 1;
    };
  }, [selectedId]);

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
    async (id: string, options: { quiet?: boolean } = {}): Promise<LoadResult> => {
      // Only the conversation on screen is ever loaded; anything else would be discarded anyway.
      if (selectedIdRef.current !== id) return "superseded";
      const seq = ++detailSeq.current;
      const isCurrent = () => detailSeq.current === seq && selectedIdRef.current === id;
      if (!options.quiet) setDetailState("loading");
      try {
        const loaded = await api.getConversation(id);
        if (!isCurrent()) return "superseded";
        setDetail(loaded);
        setDetailState("ready");
        setDetailError(null);
        setServerDown(false);
        return "applied";
      } catch (error) {
        if (!isCurrent()) return "superseded";
        setDetailError(noteResult(error).message);
        setDetailState("error");
        return "failed";
      }
    },
    [noteResult],
  );

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (!selectedId && !invalidLink && conversations && conversations.length > 0) {
      select(conversations[0]!.id);
    }
  }, [selectedId, invalidLink, conversations, select]);

  useEffect(() => {
    setSendError(null);
    setReconcileError(null);
    setDetail(null);
    if (!selectedId) {
      setDetailState("idle");
      return;
    }
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
      // A definite refusal (busy, invalid, not found): nothing was saved; keep the draft for the
      // conversation it was written in.
      setPending(null);
      setSendError({ conversationId, message: apiError.message });
      setDraft((current) => ({
        key: current.key + 1,
        text: content,
        conversationId,
        notice: null,
      }));
      await loadDetail(conversationId, { quiet: true });
    }
  };

  const send = (content: string) => {
    if (!selectedId) return;
    setDraft((current) => ({ ...current, text: "", conversationId: null, notice: null }));
    void submit(selectedId, newSubmissionId(), content);
  };

  // Same submission id: the server answers a duplicate with the original outcome.
  const retry = () => {
    if (pending) void submit(pending.conversationId, pending.submissionId, pending.content);
  };

  // An unconfirmed send is only forgotten after the saved history was reloaded, so the
  // `submissionId` is never dropped while its outcome is still unknown. Nothing is re-sent here.
  const reconcile = async (restoreAsNewMessage: boolean) => {
    if (!pending || reconciling) return;
    const { conversationId, content } = pending;
    setReconciling(true);
    setReconcileError(null);
    const result = await loadDetail(conversationId, { quiet: true });
    setReconciling(false);
    if (result !== "applied") {
      if (result === "failed") {
        setReconcileError(
          "Could not reload the saved history, so this message is still unconfirmed. Try again.",
        );
      }
      return;
    }
    setPending(null);
    if (restoreAsNewMessage) {
      setDraft((current) => ({
        key: current.key + 1,
        text: content,
        conversationId,
        notice: RESTORED_AS_NEW_NOTICE,
      }));
    }
  };

  const refresh = () => {
    void loadConversations();
    if (selectedId) void loadDetail(selectedId, { quiet: true });
  };

  const retryConversations = () => {
    setListError(null);
    void loadConversations();
  };

  const showDetail = detail !== null && selectedId !== null && detail.conversation.id === selectedId;
  const visiblePending = pending && pending.conversationId === selectedId ? pending : null;
  const unsettled = showDetail && detail.runs.some((run) => UNSETTLED.has(run.status));
  const composerDisabled =
    pending !== null || unsettled || detailState !== "ready" || !showDetail || reconciling;
  let disabledReason: string | undefined;
  if (unsettled && pending === null) {
    disabledReason =
      "A response is being generated or is unresolved for this conversation, so sending is paused. Use Refresh to check its state.";
  } else if (pending !== null && pending.conversationId !== selectedId) {
    disabledReason =
      "A message in another conversation is still being sent or is unconfirmed, so sending is paused until it is settled.";
  }
  const restoredHere = draft.conversationId === selectedId;
  const shownSendError = sendError?.conversationId === selectedId ? sendError.message : null;

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
            <div className="banner banner--error" role="alert">
              <p>{listError}</p>
              <button type="button" onClick={retryConversations}>
                Retry loading conversations
              </button>
            </div>
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
          {invalidLink && (
            <p className="banner banner--error" role="alert">
              That conversation link is not valid. Choose a conversation from the list or create a
              new one.
            </p>
          )}
          {!selectedId && !invalidLink && conversations !== null && conversations.length === 0 && (
            <p className="empty">Create a conversation to get started.</p>
          )}
          {selectedId && detailState === "loading" && <p role="status">Loading conversation…</p>}
          {selectedId && detailState === "error" && !serverDown && (
            <div className="banner banner--error" role="alert">
              <p>{detailError}</p>
              <button type="button" onClick={() => void loadDetail(selectedId)}>
                Retry loading conversation
              </button>
            </div>
          )}
          {showDetail && (
            <>
              <div className="conversation__header">
                <h2>{detail.conversation.title ?? "Untitled conversation"}</h2>
                <button type="button" onClick={refresh} disabled={reconciling}>
                  Refresh
                </button>
              </div>
              <MessageList
                detail={detail}
                pending={visiblePending}
                onRetry={retry}
                onDiscard={() => void reconcile(false)}
                onSendAsNew={() => void reconcile(true)}
                reconciling={reconciling}
                reconcileError={reconcileError}
              />
              <Composer
                key={draft.key}
                restoredText={restoredHere ? draft.text : ""}
                restoredNotice={restoredHere ? draft.notice : null}
                disabled={composerDisabled}
                disabledReason={disabledReason}
                error={shownSendError}
                onSend={send}
              />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
