import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { MessageDto, RunDto } from "./api/types";
import { MessageItem } from "./components/MessageItem";
import { FakeBackend } from "./test/fakeBackend";

const NOTICE = "This reply was cut off at the model's output limit.";

function message(overrides: Partial<MessageDto> = {}): MessageDto {
  return {
    id: "msg-1",
    position: 2,
    role: "assistant",
    content: "The three colors are red, orange and",
    committed_at: "2026-01-15T12:00:01.000000Z",
    produced_by_run_id: "run-1",
    ...overrides,
  };
}

function run(overrides: Partial<RunDto> = {}): RunDto {
  return {
    id: "run-1",
    triggering_message_id: "msg-0",
    status: "succeeded",
    model_id: "Qwen3-4B-Q4_K_M",
    runtime_id: "llama.cpp-b11440",
    failure_code: null,
    failure_message: null,
    ...overrides,
  };
}

describe("truncation notice on a message (ADR-0016)", () => {
  it("is shown for a truncated assistant message, beside the unchanged content", () => {
    render(<MessageItem message={message({ completeness: "truncated" })} producingRun={run()} />);
    expect(screen.getByTestId("truncation-notice")).toHaveTextContent(NOTICE);
    expect(screen.getByTestId("truncation-notice")).toHaveAttribute("role", "note");
    // The stored text is displayed exactly, with no marker added to it.
    expect(document.querySelector(".message__body")!.textContent).toBe(
      "The three colors are red, orange and",
    );
  });

  it.each([
    ["complete", "complete" as const],
    ["unclassified (null)", null],
    ["unclassified (absent)", undefined],
  ])("is not shown when the message is %s", (_label, completeness) => {
    render(<MessageItem message={message({ completeness })} producingRun={run()} />);
    expect(screen.queryByTestId("truncation-notice")).not.toBeInTheDocument();
    expect(screen.queryByText(/cut off/i)).not.toBeInTheDocument();
  });

  it("is never inferred from the run: any run state without a truncated message shows none", () => {
    for (const status of ["succeeded", "failed", "indeterminate", "in_flight"] as const) {
      const { unmount } = render(
        <MessageItem
          message={message({ completeness: "complete" })}
          producingRun={run({ status, failure_code: status === "failed" ? "x" : null })}
        />,
      );
      expect(screen.queryByTestId("truncation-notice")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("is shown from the message alone even with no run attached", () => {
    render(<MessageItem message={message({ completeness: "truncated" })} />);
    expect(screen.getByTestId("truncation-notice")).toBeInTheDocument();
  });

  it("never labels a user message, whatever the field says", () => {
    render(
      <MessageItem
        message={message({ role: "user", produced_by_run_id: null, completeness: "complete" })}
      />,
    );
    expect(screen.queryByTestId("truncation-notice")).not.toBeInTheDocument();
  });
});

describe("truncated replies in the chat client", () => {
  let backend: FakeBackend;

  beforeEach(() => {
    backend = new FakeBackend();
    vi.stubGlobal("fetch", backend.fetch);
    window.location.hash = "";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function sendOne(text: string) {
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("Message"), `${text}{Enter}`);
    return user;
  }

  it("labels the truncated reply, leaves the composer available and keeps the text intact", async () => {
    backend.seed("Chat");
    backend.truncateNextReply = true;
    const user = await sendOne("name three colors");

    expect(await screen.findByText("Fake reply to: name three colors")).toBeInTheDocument();
    const notices = screen.getAllByTestId("truncation-notice");
    expect(notices).toHaveLength(1);
    expect(notices[0]).toHaveTextContent(NOTICE);
    const assistant = screen.getAllByRole("listitem").find((li) =>
      li.classList.contains("message--assistant"),
    )!;
    expect(within(assistant).getByTestId("truncation-notice")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // not an error or a failure

    // The run succeeded, so nothing is unsettled and the composer stays available.
    const composer = screen.getByLabelText("Message");
    expect(composer).toBeEnabled();
    await user.type(composer, "and then?");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  it("labels only the truncated reply of several, and never the complete ones", async () => {
    backend.seed("Chat");
    const user = await sendOne("first");
    await screen.findByText("Fake reply to: first");
    backend.truncateNextReply = true;
    await user.type(screen.getByLabelText("Message"), "second{Enter}");
    await screen.findByText("Fake reply to: second");
    await user.type(screen.getByLabelText("Message"), "third{Enter}");
    await screen.findByText("Fake reply to: third");

    const replies = screen
      .getAllByRole("listitem")
      .filter((li) => li.classList.contains("message--assistant"));
    expect(replies.map((li) => within(li).queryByTestId("truncation-notice") !== null)).toEqual([
      false,
      true,
      false,
    ]);
  });

  it("still shows the notice after a reload, from the persisted message", async () => {
    backend.seed("Chat");
    backend.truncateNextReply = true;
    await sendOne("name three colors");
    await screen.findByTestId("truncation-notice");

    cleanup(); // the page is closed ...
    render(<App />); // ... and opened again: the history is read from the server
    expect(await screen.findByText("Fake reply to: name three colors")).toBeInTheDocument();
    expect(await screen.findByTestId("truncation-notice")).toHaveTextContent(NOTICE);
    expect(screen.getAllByTestId("truncation-notice")).toHaveLength(1);
  });

  it("shows the notice when an unconfirmed send is retried and the server replays the result", async () => {
    backend.seed("Lossy");
    backend.truncateNextReply = true;
    backend.loseNextAcknowledgment = true;
    const user = await sendOne("did you get this");
    expect(await screen.findByText("Not confirmed saved")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    expect(await screen.findByText("Fake reply to: did you get this")).toBeInTheDocument();
    expect(await screen.findByTestId("truncation-notice")).toHaveTextContent(NOTICE);
    expect(screen.getAllByTestId("truncation-notice")).toHaveLength(1);
  });

  it("does not label legacy or complete replies", async () => {
    const conversation = backend.seed("Old");
    const detail = backend.details.get(conversation.id)!;
    detail.messages.push(
      message({ id: "u", position: 1, role: "user", produced_by_run_id: null }),
      message({ id: "a", position: 2, content: "an old reply" }), // no completeness field at all
    );
    detail.runs.push(run({ triggering_message_id: "u" }));
    render(<App />);
    expect(await screen.findByText("an old reply")).toBeInTheDocument();
    expect(screen.queryByTestId("truncation-notice")).not.toBeInTheDocument();
  });
});
