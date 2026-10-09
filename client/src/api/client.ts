import type {
  ConversationDetailDto,
  ConversationDto,
  HealthDto,
  SubmissionResultDto,
} from "./types";

export type ApiErrorKind = "network" | "server" | "client";

/** A failed API call. `unknownOutcome` means the server may or may not have applied the change. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string | null;

  constructor(kind: ApiErrorKind, status: number | null, code: string | null, message: string) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.code = code;
  }

  get unknownOutcome(): boolean {
    return this.kind === "network" || this.kind === "server";
  }
}

interface ErrorEnvelope {
  error?: { code?: unknown; message?: unknown };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError(
      "network",
      null,
      null,
      "Cannot reach the Anonymous server. Is it running?",
    );
  }
  if (!response.ok) {
    let code: string | null = null;
    let message = `The server returned an error (${response.status}).`;
    try {
      const body = (await response.json()) as ErrorEnvelope;
      if (typeof body.error?.code === "string") code = body.error.code;
      if (typeof body.error?.message === "string") message = body.error.message;
    } catch {
      // Non-JSON error body: keep the generic message.
    }
    throw new ApiError(response.status >= 500 ? "server" : "client", response.status, code, message);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("server", response.status, null, "The server sent an unreadable response.");
  }
}

export const api = {
  health: () => request<HealthDto>("/api/v1/health"),

  listConversations: async (): Promise<ConversationDto[]> =>
    (await request<{ conversations: ConversationDto[] }>("/api/v1/conversations")).conversations,

  createConversation: (title?: string) =>
    request<ConversationDto>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify({ title: title ?? null }),
    }),

  getConversation: (id: string) =>
    request<ConversationDetailDto>(`/api/v1/conversations/${encodeURIComponent(id)}`),

  /** `submissionId` identifies one user intent; resending the same id is safe (idempotent). */
  sendMessage: (conversationId: string, submissionId: string, content: string) =>
    request<SubmissionResultDto>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ submission_id: submissionId, content }),
      },
    ),
};
