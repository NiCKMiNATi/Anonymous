// Wire types for the slice 0A HTTP contract (server/src/anonymous/api/schemas.py).
// This contract is an implementation decision of the slice, not the accepted API design.

export interface ConversationDto {
  id: string;
  title: string | null;
  created_at: string; // absolute UTC instant
}

export type MessageRole = "user" | "assistant";

export interface MessageDto {
  id: string;
  position: number; // authoritative order; never sort by time
  role: MessageRole;
  content: string;
  committed_at: string; // authoritative commit instant (absolute UTC)
  produced_by_run_id: string | null;
  /**
   * ADR-0016: whether an assistant answer ended naturally. "truncated" means it was cut off at the
   * model's output limit. null/absent means unclassified (user messages and older messages); it is
   * never inferred from the run.
   */
  completeness?: "complete" | "truncated" | null;
}

export type RunStatus = "pending" | "in_flight" | "succeeded" | "failed" | "indeterminate";

export interface RunDto {
  id: string;
  triggering_message_id: string;
  status: RunStatus;
  model_id: string | null;
  runtime_id: string | null;
  failure_code: string | null;
  failure_message: string | null;
}

export interface ConversationDetailDto {
  conversation: ConversationDto;
  messages: MessageDto[];
  runs: RunDto[];
}

export interface SubmissionResultDto {
  submission_id: string;
  replayed: boolean;
  user_message: MessageDto;
  run: RunDto;
  assistant_message: MessageDto | null;
}

export interface HealthDto {
  status: "ok" | "unavailable";
  schema_version: number | null;
  storage: "ok" | "unavailable";
  security: string;
}
