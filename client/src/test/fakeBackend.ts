import type {
  ConversationDetailDto,
  ConversationDto,
  MessageDto,
  RunDto,
  SubmissionResultDto,
} from "../api/types";

/**
 * In-memory stand-in for the slice 0A HTTP API, mimicking its status codes and error envelope.
 * It exists only for client tests; the real contract is exercised by the server's own tests and
 * the manual browser smoke test.
 */
export class FakeBackend {
  conversations: ConversationDto[] = [];
  details = new Map<string, { messages: MessageDto[]; runs: RunDto[] }>();
  submissions = new Map<string, SubmissionResultDto>();
  sendCalls: { conversationId: string; submissionId: string; content: string }[] = [];

  down = false;
  failGeneration = false;
  /** Next send commits on the server but the response is lost on the way back. */
  loseNextAcknowledgment = false;
  /** Next send is refused with this error. */
  refuseNextSend: { status: number; code: string; message: string } | null = null;
  /** Hold sends until released, to observe the in-progress state. */
  holdSends: Promise<void> | null = null;

  private counter = 0;
  private tick = 0;

  private nextId(prefix: string): string {
    this.counter += 1;
    return `${prefix}-${this.counter}`;
  }

  private nextInstant(): string {
    this.tick += 1;
    return new Date(Date.UTC(2026, 0, 15, 12, 0, this.tick)).toISOString();
  }

  seed(title: string | null = null): ConversationDto {
    const conversation: ConversationDto = {
      id: this.nextId("conv"),
      title,
      created_at: this.nextInstant(),
    };
    this.conversations.unshift(conversation);
    this.details.set(conversation.id, { messages: [], runs: [] });
    return conversation;
  }

  private json(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  private error(status: number, code: string, message: string): Response {
    return this.json(status, { error: { code, message } });
  }

  fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    if (this.down) throw new TypeError("Failed to fetch");
    const url = new URL(String(input), "http://127.0.0.1");
    const method = init?.method ?? "GET";
    const path = url.pathname;

    if (path === "/api/v1/health") {
      return this.json(200, { status: "ok", schema_version: 1, storage: "ok", security: "none" });
    }
    if (path === "/api/v1/conversations" && method === "GET") {
      return this.json(200, { conversations: this.conversations });
    }
    if (path === "/api/v1/conversations" && method === "POST") {
      return this.json(201, this.seed());
    }
    const match = /^\/api\/v1\/conversations\/([^/]+)(\/messages)?$/.exec(path);
    if (!match) return this.error(404, "not_found", "Not found.");
    const id = decodeURIComponent(match[1]!);
    const detail = this.details.get(id);
    const conversation = this.conversations.find((c) => c.id === id);
    if (!detail || !conversation) {
      return this.error(404, "conversation_not_found", "Conversation not found.");
    }
    if (!match[2] && method === "GET") {
      const body: ConversationDetailDto = {
        conversation,
        messages: detail.messages,
        runs: detail.runs,
      };
      return this.json(200, body);
    }
    if (match[2] && method === "POST") return this.handleSend(id, detail, init);
    return this.error(405, "method_not_allowed", "Method not allowed.");
  };

  private async handleSend(
    conversationId: string,
    detail: { messages: MessageDto[]; runs: RunDto[] },
    init?: RequestInit,
  ): Promise<Response> {
    const body = JSON.parse(String(init?.body)) as { submission_id: string; content: string };
    this.sendCalls.push({
      conversationId,
      submissionId: body.submission_id,
      content: body.content,
    });
    if (this.holdSends) await this.holdSends;
    if (this.down) throw new TypeError("Failed to fetch");

    const existing = this.submissions.get(body.submission_id);
    if (existing) return this.json(200, { ...existing, replayed: true });

    if (this.refuseNextSend) {
      const refusal = this.refuseNextSend;
      this.refuseNextSend = null;
      return this.error(refusal.status, refusal.code, refusal.message);
    }

    const user: MessageDto = {
      id: this.nextId("msg"),
      position: detail.messages.length + 1,
      role: "user",
      content: body.content,
      committed_at: this.nextInstant(),
      produced_by_run_id: null,
    };
    detail.messages.push(user);
    const run: RunDto = {
      id: this.nextId("run"),
      triggering_message_id: user.id,
      status: "succeeded",
      model_id: "fake-echo-1",
      runtime_id: "fake-in-process-runtime-1",
      failure_code: null,
      failure_message: null,
    };
    let assistant: MessageDto | null = null;
    if (this.failGeneration) {
      run.status = "failed";
      run.failure_code = "fake_failure";
      run.failure_message = "The fake model was asked to fail.";
    } else {
      assistant = {
        id: this.nextId("msg"),
        position: detail.messages.length + 1,
        role: "assistant",
        content: `Fake reply to: ${body.content}`,
        committed_at: this.nextInstant(),
        produced_by_run_id: run.id,
      };
      detail.messages.push(assistant);
    }
    detail.runs.push(run);
    const result: SubmissionResultDto = {
      submission_id: body.submission_id,
      replayed: false,
      user_message: user,
      run,
      assistant_message: assistant,
    };
    this.submissions.set(body.submission_id, result);

    if (this.loseNextAcknowledgment) {
      this.loseNextAcknowledgment = false;
      throw new TypeError("Failed to fetch");
    }
    return this.json(201, result);
  }
}
