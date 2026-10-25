import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { ContextSelectionDto, MessageDto, RunDto } from "./api/types";
import { MessageItem } from "./components/MessageItem";
import { FakeBackend } from "./test/fakeBackend";

function notice(n: number): string {
  return n === 1
    ? "The model did not receive the 1 earliest message. It remains saved above."
    : `The model did not receive the ${n} earliest messages. They remain saved above.`;
}

function message(overrides: Partial<MessageDto> = {}): MessageDto {
  return {
    id: "msg-1",
    position: 4,
    role: "assistant",
    content: "an answer",
    committed_at: "2026-01-15T12:00:01.000000Z",
    produced_by_run_id: "run-1",
    ...overrides,
  };
}

function context(omitted: number): ContextSelectionDto {
  return {
    first_message_id: "m",
    first_position: omitted + 1,
    selected_count: 2,
    omitted_count: omitted,
    selected_chars: 20,
    limit_chars: 30,
    measure: "characters",
    truncated_included_count: 0,
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

describe("omission notice on an assistant message (ADR-0017)", () => {
  it("is shown from the producing run's persisted selection", () => {
    render(<MessageItem message={message()} producingRun={run({ context: context(3) })} />);
    expect(screen.getByTestId("omission-notice")).toHaveTextContent(notice(3));
    expect(screen.getByTestId("omission-notice")).toHaveAttribute("role", "note");
    expect(document.querySelector(".message__body")!.textContent).toBe("an answer");
  });

  it("uses the singular for exactly one omitted message", () => {
    render(<MessageItem message={message()} producingRun={run({ context: context(1) })} />);
    expect(screen.getByTestId("omission-notice")).toHaveTextContent(notice(1));
  });

  it.each([
    ["nothing was omitted", context(0)],
    ["no selection was recorded (null)", null],
    ["no selection was recorded (absent)", undefined],
  ])("is not shown when %s", (_label, selection) => {
    render(<MessageItem message={message()} producingRun={run({ context: selection })} />);
    expect(screen.queryByTestId("omission-notice")).not.toBeInTheDocument();
    expect(screen.queryByText(/did not receive/i)).not.toBeInTheDocument();
  });

  it("is not shown without a producing run, and never beside a user message", () => {
    const { unmount } = render(<MessageItem message={message()} />);
    expect(screen.queryByTestId("omission-notice")).not.toBeInTheDocument();
    unmount();
    render(
      <MessageItem
        message={message({ role: "user", produced_by_run_id: null })}
        producingRun={run({ context: context(2) })}
      />,
    );
    expect(screen.queryByText(/did not receive/i)).not.toBeInTheDocument();
  });

  it("is shown together with, and independent of, the truncation notice", () => {
    render(
      <MessageItem
        message={message({ completeness: "truncated" })}
        producingRun={run({ context: context(2) })}
      />,
    );
    expect(screen.getByTestId("truncation-notice")).toHaveTextContent(
      "This reply was cut off at the model's output limit.",
    );
    expect(screen.getByTestId("omission-notice")).toHaveTextContent(notice(2));
  });

  it("does not use the run's status", () => {
    render(
      <MessageItem
        message={message()}
        producingRun={run({ status: "failed", failure_code: "x", context: context(0) })}
      />,
    );
    expect(screen.queryByTestId("omission-notice")).not.toBeInTheDocument();
  });
});

describe("omission notice in the chat client", () => {
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

  function replies() {
    return screen.getAllByRole("listitem").filter((li) => li.classList.contains("message--assistant"));
  }

  it("shows the notice beside the reply of the run that omitted history, and only there", async () => {
    backend.seed("Chat");
    const user = await sendOne("first");
    await screen.findByText("Fake reply to: first");
    backend.omitNextContext = 2;
    await user.type(screen.getByLabelText("Message"), "second{Enter}");
    await screen.findByText("Fake reply to: second");
    await user.type(screen.getByLabelText("Message"), "third{Enter}");
    await screen.findByText("Fake reply to: third");

    expect(replies().map((li) => within(li).queryByTestId("omission-notice") !== null)).toEqual([
      false,
      true,
      false,
    ]);
    expect(screen.getByTestId("omission-notice")).toHaveTextContent(notice(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeEnabled();
  });

  it("still shows it after a reload, from the persisted run", async () => {
    backend.seed("Chat");
    backend.omitNextContext = 4;
    await sendOne("hello");
    await screen.findByTestId("omission-notice");

    cleanup();
    render(<App />);
    expect(await screen.findByText("Fake reply to: hello")).toBeInTheDocument();
    expect(await screen.findByTestId("omission-notice")).toHaveTextContent(notice(4));
    expect(screen.getAllByTestId("omission-notice")).toHaveLength(1);
  });

  it("shows it when an unconfirmed send is retried and the server replays the result", async () => {
    backend.seed("Lossy");
    backend.omitNextContext = 3;
    backend.loseNextAcknowledgment = true;
    const user = await sendOne("did you get this");
    expect(await screen.findByText("Not confirmed saved")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry sending" }));
    expect(await screen.findByText("Fake reply to: did you get this")).toBeInTheDocument();
    expect(await screen.findByTestId("omission-notice")).toHaveTextContent(notice(3));
    expect(screen.getAllByTestId("omission-notice")).toHaveLength(1);
  });

  it("shows none, and no placeholder, when nothing was omitted or nothing was recorded", async () => {
    backend.seed("Chat");
    await sendOne("short chat");
    expect(await screen.findByText("Fake reply to: short chat")).toBeInTheDocument();
    expect(screen.queryByTestId("omission-notice")).not.toBeInTheDocument();
    expect(screen.queryByText(/did not receive/i)).not.toBeInTheDocument();
  });

  it("keeps the truncation notice working beside it", async () => {
    backend.seed("Chat");
    backend.truncateNextReply = true;
    backend.omitNextContext = 1;
    await sendOne("name three colors");
    expect(await screen.findByTestId("truncation-notice")).toBeInTheDocument();
    expect(await screen.findByTestId("omission-notice")).toHaveTextContent(notice(1));
  });
});
