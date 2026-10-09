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

describe("R2 — discarding an unconfirmed send never creates a hidden fresh send", () => {
  async function loseFirstAcknowledgment(content = "one intent") {
    const c = backend.seed("Lossy");
    window.location.hash = `#/c/${c.id}`;
    backend.loseNextAcknowledgment = true;
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("Message"), `${content}{Enter}`);
    await screen.findByText("Not confirmed saved");
    return { c, user };
  }
  const userMessages = (id: string) =>
    backend.details.get(id)!.messages.filter((m) => m.role === "user");

  it("reconciles against saved history, leaves the composer empty and sends nothing", async () => {
    const { c, user } = await loseFirstAcknowledgment();
    await user.click(screen.getByRole("button", { name: "Discard and reload" }));
    await screen.findByText("Fake reply to: one intent");

    expect(screen.queryByTestId("pending-message")).not.toBeInTheDocument();
    expect(messageBox()).toHaveValue("");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await flush();
    expect(backend.sendCalls).toHaveLength(1);
    expect(userMessages(c.id)).toHaveLength(1);
  });

  it("keeps the unconfirmed record, and its submission id, when history cannot be reloaded", async () => {
    const { c, user } = await loseFirstAcknowledgment();
    backend.down = true;
    await user.click(screen.getByRole("button", { name: "Discard and reload" }));
    await screen.findByText(/still unconfirmed/);
    expect(screen.getByText("Not confirmed saved")).toBeInTheDocument();

    backend.down = false;
    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await screen.findByText("Fake reply to: one intent");
    expect(backend.sendCalls).toHaveLength(2);
    expect(backend.sendCalls[1]!.submissionId).toBe(backend.sendCalls[0]!.submissionId);
    expect(userMessages(c.id)).toHaveLength(1);
  });

  it("blocks sending and every recovery action while history is being reconciled", async () => {
    const { user } = await loseFirstAcknowledgment();
    const { held } = holdDetailGets();
    await user.click(screen.getByRole("button", { name: "Discard and reload" }));
    await waitFor(() => expect(held).toHaveLength(1));

    await user.type(messageBox(), "typed meanwhile");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Retry sending" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Discard and reload" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /send again as a new message/ })).toBeDisabled();

    await act(async () => held[0]!.release());
    await screen.findByText("Fake reply to: one intent");
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  });

  it("offers a separate, explicit new message only after reconciling, with a fresh submission id", async () => {
    const { c, user } = await loseFirstAcknowledgment();
    await user.click(screen.getByRole("button", { name: /send again as a new message/ }));
    await screen.findByText("Fake reply to: one intent"); // history reconciled first
    expect(messageBox()).toHaveValue("one intent");
    expect(screen.getByText(/Restored from an unconfirmed send/)).toBeInTheDocument();
    expect(backend.sendCalls).toHaveLength(1); // restoring is not sending

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(backend.sendCalls).toHaveLength(2));
    expect(backend.sendCalls[1]!.submissionId).not.toBe(backend.sendCalls[0]!.submissionId);
    await waitFor(() => expect(userMessages(c.id)).toHaveLength(2)); // deliberate, not accidental
    expect(screen.queryByText(/Restored from an unconfirmed send/)).not.toBeInTheDocument();
  });

  it("retry still re-sends the very same submission", async () => {
    const { c, user } = await loseFirstAcknowledgment();
    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    await screen.findByText("Fake reply to: one intent");
    expect(backend.sendCalls[1]!.submissionId).toBe(backend.sendCalls[0]!.submissionId);
    expect(userMessages(c.id)).toHaveLength(1);
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
