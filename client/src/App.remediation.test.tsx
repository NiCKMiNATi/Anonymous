// Regression tests for the Slice 0A independent review findings R1–R4 (see
// .agent/plans/2026-10-10-slice-0a-review-remediation.md). They use the existing transport fake and
// control the order in which responses arrive, which the original suite did not.
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { MessageDto } from "./api/types";
import { FakeBackend } from "./test/fakeBackend";

let backend: FakeBackend;

beforeEach(() => {
  backend = new FakeBackend();
  vi.stubGlobal("fetch", backend.fetch);
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const DETAIL_PATH = /^\/api\/v1\/conversations\/[^/]+$/;

interface Held {
  path: string;
  /** Deliver the held response (the server's answer as of request time), or a replacement. */
  release: (replacement?: Response) => void;
}

/**
 * Wraps the fake so conversation-detail GETs are answered by the fake immediately (the content is
 * the server's state *at request time*) but delivered to the client only when the test releases
 * them, in any order.
 */
function holdDetailGets() {
  const held: Held[] = [];
  const state = { holding: true };
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await backend.fetch(input, init);
    const path = String(input);
    if (state.holding && !init?.method && DETAIL_PATH.test(path)) {
      const replacement = await new Promise<Response | undefined>((resolve) => {
        held.push({ path, release: (r) => resolve(r) });
      });
      return replacement ?? response;
    }
    return response;
  });
  return { held, state };
}

function errorResponse(status: number, code = "storage_unavailable") {
  return new Response(JSON.stringify({ error: { code, message: `Server said ${code}.` } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function userMessage(position: number, content: string): MessageDto {
  return {
    id: `seeded-${position}`,
    position,
    role: "user",
    content,
    committed_at: "2026-01-15T12:30:00.000000Z",
    produced_by_run_id: null,
  };
}

const heading = () => screen.getByRole("heading", { level: 2 }).textContent;
const messageBox = () => screen.getByLabelText<HTMLTextAreaElement>("Message");
const flush = () => act(async () => new Promise((resolve) => setTimeout(resolve, 30)));

describe("R1 — stale responses never replace the current selection", () => {
  it("a send finishing in A, after B was selected, neither replaces B nor retargets the composer", async () => {
    const beta = backend.seed("Beta");
    const alpha = backend.seed("Alpha");
    window.location.hash = `#/c/${alpha.id}`;
    let release!: () => void;
    backend.holdSends = new Promise<void>((resolve) => {
      release = resolve;
    });
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("Message"), "for alpha{Enter}");
    await user.click(screen.getByRole("button", { name: /Beta/ }));
    await screen.findByRole("heading", { name: "Beta", level: 2 });

    await act(async () => release());
    await waitFor(() => expect(backend.details.get(alpha.id)!.messages).toHaveLength(2));
    await flush();
    expect(heading()).toBe("Beta");
    expect(screen.queryByText("for alpha")).not.toBeInTheDocument();

    // The composer targets the displayed conversation.
    backend.holdSends = null;
    await user.type(messageBox(), "for beta{Enter}");
    await screen.findByText("Fake reply to: for beta");
    expect(backend.sendCalls.at(-1)!.conversationId).toBe(beta.id);
    expect(backend.details.get(beta.id)!.messages).toHaveLength(2);
  });

  it("responses arriving out of order during A→B→A keep showing the latest request for A", async () => {
    const beta = backend.seed("Beta");
    const alpha = backend.seed("Alpha");
    window.location.hash = `#/c/${alpha.id}`;
    const { held } = holdDetailGets();
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(held).toHaveLength(1)); // Alpha, request 1: no messages yet

    await user.click(screen.getByRole("button", { name: /Beta/ }));
    await waitFor(() => expect(held).toHaveLength(2)); // Beta
    backend.details.get(alpha.id)!.messages.push(userMessage(1, "alpha fact"));
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    await waitFor(() => expect(held).toHaveLength(3)); // Alpha, request 2: has the message
    expect(held[1]!.path).toContain(beta.id);

    await act(async () => held[2]!.release()); // newest first
    await screen.findByText("alpha fact");
    await act(async () => held[1]!.release()); // stale Beta
    await act(async () => held[0]!.release()); // stale Alpha (no messages)
    await flush();

    expect(heading()).toBe("Alpha");
    expect(screen.getByText("alpha fact")).toBeInTheDocument();
    expect(screen.queryByText(/No messages yet/)).not.toBeInTheDocument();
    expect(window.location.hash).toContain(alpha.id);
  });

  it("an older response for the same conversation cannot erase newer history", async () => {
    const c = backend.seed("Same");
    window.location.hash = `#/c/${c.id}`;
    const { held, state } = holdDetailGets();
    state.holding = false;
    const user = userEvent.setup();
    render(<App />);
    await screen.findByLabelText("Message");

    state.holding = true;
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(held).toHaveLength(1)); // snapshot: no messages
    backend.details.get(c.id)!.messages.push(userMessage(1, "newer fact"));
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(held).toHaveLength(2)); // snapshot: has the message

    await act(async () => held[1]!.release());
    await screen.findByText("newer fact");
    await act(async () => held[0]!.release());
    await flush();
    expect(screen.getByText("newer fact")).toBeInTheDocument();
  });

  it("a late error for a request that is no longer current is ignored", async () => {
    const beta = backend.seed("Beta");
    const alpha = backend.seed("Alpha");
    window.location.hash = `#/c/${alpha.id}`;
    const { held, state } = holdDetailGets();
    state.holding = false;
    const user = userEvent.setup();
    render(<App />);
    await screen.findByLabelText("Message");

    state.holding = true;
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(held).toHaveLength(1)); // Alpha refresh, will fail late
    await user.click(screen.getByRole("button", { name: /Beta/ }));
    await waitFor(() => expect(held).toHaveLength(2));
    await act(async () => held[1]!.release()); // Beta loads
    await screen.findByRole("heading", { name: "Beta", level: 2 });

    await act(async () => held[0]!.release(errorResponse(503)));
    await flush();
    expect(heading()).toBe("Beta");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(window.location.hash).toContain(beta.id);
  });

  it("a response completing after the app unmounted changes nothing and raises no error", async () => {
    const c = backend.seed("Gone");
    window.location.hash = `#/c/${c.id}`;
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { held } = holdDetailGets();
    const { unmount } = render(<App />);
    await waitFor(() => expect(held).toHaveLength(1));
    unmount();
    await act(async () => held[0]!.release());
    await act(async () => held[0]!.release(errorResponse(503)));
    expect(errors).not.toHaveBeenCalled();
  });

  it("a refused send restores its draft only in the conversation it was written in", async () => {
    const beta = backend.seed("Beta");
    const alpha = backend.seed("Alpha");
    window.location.hash = `#/c/${alpha.id}`;
    backend.refuseNextSend = { status: 409, code: "conversation_busy", message: "Busy right now." };
    let release!: () => void;
    backend.holdSends = new Promise<void>((resolve) => {
      release = resolve;
    });
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("Message"), "alpha draft{Enter}");
    await user.click(screen.getByRole("button", { name: /Beta/ }));
    await screen.findByRole("heading", { name: "Beta", level: 2 });
    await act(async () => release());
    await flush();

    expect(heading()).toBe("Beta");
    expect(messageBox()).toHaveValue("");
    expect(screen.queryByText("Busy right now.")).not.toBeInTheDocument();
    expect(window.location.hash).toContain(beta.id);

    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    await screen.findByRole("heading", { name: "Alpha", level: 2 });
    expect(messageBox()).toHaveValue("alpha draft");
  });
});

describe("R2 — only the server's answer to a submission's own id settles its outcome", () => {
  const pendingNote = () => screen.queryByTestId("pending-message");
  const abandonedNote = () => screen.queryByTestId("abandoned-message");
  const userMessages = (id: string) =>
    backend.details.get(id)!.messages.filter((m) => m.role === "user");
  const savedUserRows = () => document.querySelectorAll(".message--user:not(.message--pending)");

  async function start(title: string, mode: "lost-ack" | "late-commit", content = "one intent") {
    const c = backend.seed(title);
    window.location.hash = `#/c/${c.id}`;
    if (mode === "lost-ack") backend.loseNextAcknowledgment = true;
    else backend.deferNextCommit = true;
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("Message"), `${content}{Enter}`);
    await screen.findByText("Not confirmed saved");
    return { c, user };
  }

  it("keeps the submission unresolved across an older history snapshot, a late commit and later reads, then settles by same-id retry", async () => {
    const { c, user } = await start("Late", "late-commit", "late one");
    const refresh = () => user.click(screen.getByRole("button", { name: "Refresh" }));

    // History read #1: an older snapshot that does not contain the message.
    await refresh();
    await flush();
    expect(savedUserRows()).toHaveLength(0);
    expect(screen.getByText("Not confirmed saved")).toBeInTheDocument(); // absence proved nothing
    expect(screen.getByRole("button", { name: "Retry sending" })).toBeEnabled();

    // The original request now lands. The client has not been told anything.
    backend.commitDeferred();
    expect(userMessages(c.id)).toHaveLength(1);

    // History read #2 shows the message, yet the submission is still not settled by it.
    await refresh();
    await screen.findByText("Fake reply to: late one");
    expect(savedUserRows()).toHaveLength(1);
    expect(screen.getByText("Not confirmed saved")).toBeInTheDocument(); // presence proved nothing
    expect(backend.sendCalls).toHaveLength(1); // and nothing was sent on its behalf

    // Only the server's answer to the same id settles it, with no duplicate.
    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await waitFor(() => expect(pendingNote()).toBeNull());
    expect(backend.sendCalls).toHaveLength(2);
    expect(backend.sendCalls[1]!.submissionId).toBe(backend.sendCalls[0]!.submissionId);
    expect(userMessages(c.id)).toHaveLength(1);
    expect(backend.details.get(c.id)!.runs).toHaveLength(1);
    expect(savedUserRows()).toHaveLength(1);
  });

  it("settles by same-id retry when the original had not committed yet, and a late original then adds nothing", async () => {
    const { c, user } = await start("Early retry", "late-commit", "early retry");
    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await screen.findByText("Fake reply to: early retry");
    expect(pendingNote()).toBeNull();
    backend.commitDeferred(); // the original finally arrives: same id, so the server ignores it
    expect(userMessages(c.id)).toHaveLength(1);
    expect(backend.sendCalls[1]!.submissionId).toBe(backend.sendCalls[0]!.submissionId);
  });

  it("makes no automatic request while a submission is uncertain", async () => {
    const { user } = await start("Quiet", "late-commit");
    let gets = 0;
    const inner = backend.fetch;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
      if (!init?.method) gets += 1;
      return inner(input, init);
    });
    await flush();
    await flush();
    expect(gets).toBe(0);
    expect(backend.sendCalls).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Refresh" })); // user-initiated only
    await flush();
    expect(gets).toBeGreaterThan(0);
    expect(backend.sendCalls).toHaveLength(1);
    expect(pendingNote()).not.toBeNull();
  });

  it("keeps the uncertainty, and its id, when the user switches conversations and back", async () => {
    const beta = backend.seed("Beta");
    const { c: alpha, user } = await start("Alpha", "late-commit", "alpha intent");
    await user.click(screen.getByRole("button", { name: /Beta/ }));
    await screen.findByRole("heading", { name: "Beta", level: 2 });
    expect(pendingNote()).toBeNull(); // shown only where it belongs
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByText(/in another conversation is still being sent or is unconfirmed/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    await screen.findByRole("heading", { name: "Alpha", level: 2 });
    expect(pendingNote()).not.toBeNull();
    expect(within(pendingNote()!).getByText("alpha intent")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await waitFor(() => expect(pendingNote()).toBeNull());
    expect(backend.sendCalls.map((call) => call.submissionId)).toEqual([
      backend.sendCalls[0]!.submissionId,
      backend.sendCalls[0]!.submissionId,
    ]);
    expect(backend.sendCalls.every((call) => call.conversationId === alpha.id)).toBe(true);
    expect(userMessages(alpha.id)).toHaveLength(1);
    expect(userMessages(beta.id)).toHaveLength(0);
  });

  const BUSY = { status: 409, code: "conversation_busy", message: "Busy right now." };

  it("a 409 busy to the retry keeps the submission uncertain (same id, content, conversation); it never becomes a draft", async () => {
    const { c, user } = await start("Refused retry", "late-commit", "refused later");
    backend.refuseNextSend = BUSY;
    await user.click(screen.getByRole("button", { name: "Retry sending" }));

    const note = await screen.findByTestId("pending-message");
    await waitFor(() => expect(within(note).getByText(/Not confirmed saved/)).toBeInTheDocument());
    expect(within(note).getByText(/Busy right now\./)).toBeInTheDocument();
    expect(within(note).getByText(/does not show that the earlier attempt failed/)).toBeInTheDocument();
    expect(within(note).getByText("refused later")).toBeInTheDocument();
    expect(within(note).getByRole("button", { name: "Retry sending" })).toBeEnabled();
    expect(messageBox()).toHaveValue(""); // not turned into a fresh draft
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.queryByText(/Restored from/)).not.toBeInTheDocument();
    expect(backend.sendCalls).toHaveLength(2);
    expect(backend.sendCalls[1]!.submissionId).toBe(backend.sendCalls[0]!.submissionId);
    expect(userMessages(c.id)).toHaveLength(0);
  });

  it("recovers by same-id retry after refused retries, once the delayed original has committed", async () => {
    const { c, user } = await start("Refuse then recover", "late-commit", "slow one");
    const submissionId = () => backend.sendCalls[0]!.submissionId;

    for (let attempt = 1; attempt <= 3; attempt += 1) {
      backend.refuseNextSend = BUSY;
      await user.click(screen.getByRole("button", { name: "Retry sending" }));
      await waitFor(() => expect(backend.sendCalls).toHaveLength(1 + attempt));
      await screen.findByText(/The server refused this retry/);
      expect(pendingNote()).not.toBeNull(); // still the same uncertain submission each time
    }
    expect(new Set(backend.sendCalls.map((call) => call.submissionId))).toEqual(
      new Set([submissionId()]),
    );

    backend.commitDeferred(); // the original request finally lands
    expect(userMessages(c.id)).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Refresh" })); // a history read settles nothing
    await screen.findByText("Fake reply to: slow one");
    expect(screen.getByText(/Not confirmed saved/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await waitFor(() => expect(pendingNote()).toBeNull());
    expect(backend.sendCalls).toHaveLength(5);
    expect(backend.sendCalls.every((call) => call.submissionId === submissionId())).toBe(true);
    expect(userMessages(c.id)).toHaveLength(1); // exactly one saved message, no duplicate
    expect(backend.details.get(c.id)!.runs).toHaveLength(1);
    expect(savedUserRows()).toHaveLength(1);
  });

  it("a refused retry of an abandoned message returns it to the uncertain state, not to the composer", async () => {
    const { c, user } = await start("Abandoned refused", "late-commit", "abandoned slow");
    await user.click(screen.getByRole("button", { name: "Discard and reload" }));
    expect(abandonedNote()).not.toBeNull();

    backend.refuseNextSend = BUSY;
    await user.click(screen.getByRole("button", { name: "Retry abandoned message" }));
    await screen.findByText(/The server refused this retry/);
    expect(abandonedNote()).toBeNull(); // active again, with the same record
    const note = pendingNote()!;
    expect(within(note).getByText("abandoned slow")).toBeInTheDocument();
    expect(messageBox()).toHaveValue("");
    expect(backend.sendCalls).toHaveLength(2);
    expect(backend.sendCalls[1]!.submissionId).toBe(backend.sendCalls[0]!.submissionId);

    backend.commitDeferred();
    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await waitFor(() => expect(pendingNote()).toBeNull());
    expect(userMessages(c.id)).toHaveLength(1);
    expect(backend.sendCalls[2]!.submissionId).toBe(backend.sendCalls[0]!.submissionId);
  });

  it("keeps a refused-retry submission when the user switches conversations and back", async () => {
    const beta = backend.seed("Beta");
    const { c: alpha, user } = await start("Alpha", "late-commit", "alpha slow");
    backend.refuseNextSend = BUSY;
    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await screen.findByText(/The server refused this retry/);

    await user.click(screen.getByRole("button", { name: /Beta/ }));
    await screen.findByRole("heading", { name: "Beta", level: 2 });
    expect(pendingNote()).toBeNull();
    expect(messageBox()).toHaveValue("");
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    await screen.findByRole("heading", { name: "Alpha", level: 2 });
    expect(within(pendingNote()!).getByText("alpha slow")).toBeInTheDocument();

    backend.commitDeferred();
    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await waitFor(() => expect(pendingNote()).toBeNull());
    expect(userMessages(alpha.id)).toHaveLength(1);
    expect(userMessages(beta.id)).toHaveLength(0);
    expect(backend.sendCalls.every((call) => call.submissionId === backend.sendCalls[0]!.submissionId)).toBe(true);
  });

  it("a new id exists only after a distinct explicit action following refused retries", async () => {
    const { c, user } = await start("Explicit new", "late-commit", "decide later");
    backend.refuseNextSend = BUSY;
    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await screen.findByText(/The server refused this retry/);
    await flush();
    expect(backend.sendCalls).toHaveLength(2); // nothing automatic happened in between

    await user.click(screen.getByRole("button", { name: /Abandon, then send again as a new message/ }));
    expect(messageBox()).toHaveValue("decide later");
    expect(backend.sendCalls).toHaveLength(2); // still nothing sent
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(backend.sendCalls).toHaveLength(3));
    expect(backend.sendCalls[2]!.submissionId).not.toBe(backend.sendCalls[0]!.submissionId);
    await waitFor(() => expect(userMessages(c.id)).toHaveLength(1));
    // The delayed original is unfenced (known limitation): if it lands it is a second, distinct
    // message. The abandoned note says so; this is the user's explicit choice, never automatic.
    expect(abandonedNote()).not.toBeNull();
  });

  it("a refusal of a first attempt carries no uncertainty notice", async () => {
    const c = backend.seed("Plain refusal");
    window.location.hash = `#/c/${c.id}`;
    backend.refuseNextSend = { status: 409, code: "conversation_busy", message: "Busy right now." };
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("Message"), "plain{Enter}");
    expect(await screen.findByText("Busy right now.")).toBeInTheDocument();
    expect(messageBox()).toHaveValue("plain");
    expect(screen.queryByText(/never confirmed/)).not.toBeInTheDocument();
  });

  it("explicit discard sends nothing, restores nothing and is shown as abandoned, not failed", async () => {
    const { c, user } = await start("Abandon", "lost-ack");
    await user.click(screen.getByRole("button", { name: "Discard and reload" }));
    await screen.findByText("Fake reply to: one intent"); // the view was refreshed

    expect(pendingNote()).toBeNull();
    const note = abandonedNote()!;
    expect(within(note).getByText("Abandoned — outcome unknown")).toBeInTheDocument();
    expect(note).toHaveTextContent(/not confirmed failed/i);
    expect(screen.queryByText(/Response failed/)).not.toBeInTheDocument();
    expect(messageBox()).toHaveValue("");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await flush();
    expect(backend.sendCalls).toHaveLength(1);
    expect(userMessages(c.id)).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Retry sending" })).not.toBeInTheDocument();

    // Forgetting only removes the note.
    await user.click(screen.getByRole("button", { name: "Forget abandoned message" }));
    expect(abandonedNote()).toBeNull();
    await flush();
    expect(backend.sendCalls).toHaveLength(1);
  });

  it("discard does not depend on, or wait for, a history read", async () => {
    const { user } = await start("Offline discard", "late-commit");
    const { held } = holdDetailGets();
    await user.click(screen.getByRole("button", { name: "Discard and reload" }));
    expect(abandonedNote()).not.toBeNull(); // immediate; the held history read is irrelevant
    expect(pendingNote()).toBeNull();
    await waitFor(() => expect(held).toHaveLength(1));
    await act(async () => held[0]!.release());
    expect(abandonedNote()).not.toBeNull(); // a successful history read did not clear it
  });

  it("an abandoned message can still be settled by a same-id retry, without duplicates", async () => {
    const { c, user } = await start("Abandon then settle", "late-commit", "settle me");
    await user.click(screen.getByRole("button", { name: "Discard and reload" }));
    backend.commitDeferred();
    await flush();
    expect(abandonedNote()).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "Retry abandoned message" }));
    await waitFor(() => expect(abandonedNote()).toBeNull());
    await screen.findByText("Fake reply to: settle me");
    expect(backend.sendCalls).toHaveLength(2);
    expect(backend.sendCalls[1]!.submissionId).toBe(backend.sendCalls[0]!.submissionId);
    expect(userMessages(c.id)).toHaveLength(1);
    expect(pendingNote()).toBeNull();
  });

  it("abandoning and rewriting only prepares text; a new id exists only if the user presses Send", async () => {
    const { c, user } = await start("Rewrite", "lost-ack");
    await user.click(screen.getByRole("button", { name: /Abandon, then send again as a new message/ }));
    await screen.findByText("Fake reply to: one intent");
    expect(messageBox()).toHaveValue("one intent");
    expect(screen.getByText(/Restored from a message you abandoned/)).toBeInTheDocument();
    expect(abandonedNote()).not.toBeNull(); // the original stays visibly unresolved
    expect(backend.sendCalls).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(backend.sendCalls).toHaveLength(2));
    expect(backend.sendCalls[1]!.submissionId).not.toBe(backend.sendCalls[0]!.submissionId);
    await waitFor(() => expect(userMessages(c.id)).toHaveLength(2)); // deliberate, not accidental
    expect(screen.queryByText(/Restored from a message you abandoned/)).not.toBeInTheDocument();
  });

  it("retry still re-sends the very same submission", async () => {
    const { c, user } = await start("Plain retry", "lost-ack");
    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await screen.findByText("Fake reply to: one intent");
    expect(backend.sendCalls[1]!.submissionId).toBe(backend.sendCalls[0]!.submissionId);
    expect(userMessages(c.id)).toHaveLength(1);
    expect(pendingNote()).toBeNull();
  });
});

describe("R3 — an undecodable conversation link is handled, not fatal", () => {
  it.each(["#/c/%", "#/c/%E0%A4%A", "#/c/%FF"])("renders a recoverable state for %s", async (hash) => {
    const seeded = backend.seed("Still usable");
    window.location.hash = hash;
    const user = userEvent.setup();
    expect(() => render(<App />)).not.toThrow();

    expect(await screen.findByText(/link is not valid/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Still usable/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /New conversation/i })).toBeInTheDocument();
    expect(window.location.hash).toBe(hash); // not silently rewritten to another conversation
    expect(screen.queryByLabelText("Message")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Still usable/ }));
    await screen.findByRole("heading", { name: "Still usable", level: 2 });
    expect(screen.queryByText(/link is not valid/)).not.toBeInTheDocument();
    expect(window.location.hash).toContain(seeded.id);
  });

  it("copes with a bad hash arriving after mount and recovers when a good one follows", async () => {
    const c = backend.seed("Hash change");
    window.location.hash = `#/c/${c.id}`;
    render(<App />);
    await screen.findByRole("heading", { name: "Hash change", level: 2 });

    await act(async () => {
      window.location.hash = "#/c/%";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByText(/link is not valid/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2 })).not.toBeInTheDocument();

    await act(async () => {
      window.location.hash = `#/c/${c.id}`;
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await screen.findByRole("heading", { name: "Hash change", level: 2 });
    expect(screen.queryByText(/link is not valid/)).not.toBeInTheDocument();
  });

  it("leaves a well-formed but unknown id to the server's own not-found answer", async () => {
    window.location.hash = "#/c/does-not-exist";
    render(<App />);
    expect(await screen.findByText("Conversation not found.")).toBeInTheDocument();
    expect(screen.queryByText(/link is not valid/)).not.toBeInTheDocument();
  });
});

describe("R4 — HTTP-level load failures offer a bounded, user-initiated retry", () => {
  function failFirstGets(match: (path: string) => boolean, failures: number) {
    const calls = { total: 0, failed: 0 };
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (!init?.method && match(path)) {
        calls.total += 1;
        if (calls.failed < failures) {
          calls.failed += 1;
          return errorResponse(503);
        }
      }
      return backend.fetch(input, init);
    });
    return calls;
  }

  it("retries the conversation list after an HTTP 503 and then recovers", async () => {
    backend.seed("Recovered");
    const calls = failFirstGets((p) => p === "/api/v1/conversations", 1);
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText("Server said storage_unavailable.")).toBeInTheDocument();

    await flush();
    expect(calls.total).toBe(1); // no automatic retry loop

    await user.click(screen.getByRole("button", { name: "Retry loading conversations" }));
    await screen.findByRole("heading", { name: "Recovered", level: 2 });
    expect(calls.total).toBe(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps offering retry while the failure persists, one request per click", async () => {
    backend.seed("Later");
    const calls = failFirstGets((p) => p === "/api/v1/conversations", 2);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: "Retry loading conversations" });
    await user.click(screen.getByRole("button", { name: "Retry loading conversations" }));
    await screen.findByRole("button", { name: "Retry loading conversations" });
    expect(calls.total).toBe(2);
    await user.click(screen.getByRole("button", { name: "Retry loading conversations" }));
    await screen.findByRole("heading", { name: "Later", level: 2 });
    expect(calls.total).toBe(3);
  });

  it("retries a conversation whose detail failed to load, without re-sending anything", async () => {
    const c = backend.seed("Detail");
    window.location.hash = `#/c/${c.id}`;
    const calls = failFirstGets((p) => DETAIL_PATH.test(p), 1);
    const user = userEvent.setup();
    render(<App />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Server said storage_unavailable.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Message")).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: "Retry loading conversation" }));
    await screen.findByRole("heading", { name: "Detail", level: 2 });
    expect(calls.total).toBe(2);
    expect(backend.sendCalls).toHaveLength(0);
    expect(backend.details.get(c.id)!.messages).toHaveLength(0);
  });

  it("still reports an unreachable server with the existing Retry banner", async () => {
    backend.down = true;
    const user = userEvent.setup();
    render(<App />);
    const banner = await screen.findByText(/Cannot reach the Anonymous server/);
    expect(banner).toBeInTheDocument();
    backend.down = false;
    backend.seed("Back");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("heading", { name: "Back", level: 2 });
  });
});
