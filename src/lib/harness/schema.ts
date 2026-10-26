// GENERATED FILE - do not edit by hand.
// Source: backend/server/storage/contract.py
// Regenerate: python -m server.storage.contract --write

export const SCHEMA_VERSION = 5 as const;
export const TASK_STATES = [
  'draft',
  'queued',
  'planning',
  'awaiting_plan',
  'executing',
  'awaiting_action',
  'verifying',
  'repairing',
  'awaiting_decision',
  'paused_limit',
  'stopping',
  'paused',
  'recovery_required',
  'closed',
  'failed',
  'cancelled',
] as const;
export type TaskState = (typeof TASK_STATES)[number];
export const RUN_STATES = [
  'queued',
  'active',
  'paused',
  'stopping',
  'done',
  'failed',
  'unknown',
] as const;
export type RunState = (typeof RUN_STATES)[number];
export const ACTION_STATES = [
  'pending',
  'awaiting_approval',
  'dispatching',
  'running',
  'succeeded',
  'failed',
  'denied',
  'unknown',
] as const;
export type ActionState = (typeof ACTION_STATES)[number];
export const LEASE_STATES = [
  'active',
  'released',
  'expired',
  'quarantined',
] as const;
export type LeaseState = (typeof LEASE_STATES)[number];
export const ACCESS_MODES = [
  'ask',
  'grant',
  'auto',
] as const;
export type AccessMode = (typeof ACCESS_MODES)[number];
export const EVENT_TYPES = [
  'message_started',
  'text_delta',
  'message_finished',
  'plan_updated',
  'approval_required',
  'approval_decided',
  'action_started',
  'action_finished',
  'budget_updated',
  'lease_state_changed',
  'selection_quality_changed',
  'file_changed',
  'verification_finished',
  'repair_started',
  'task_state_changed',
  'apply_file_finished',
  'recovery_required',
] as const;
export type EventType = (typeof EVENT_TYPES)[number];
export const VERIFICATION_TARGETS = [
  'working_copy',
  'apply_candidate',
] as const;
export type VerificationTarget = (typeof VERIFICATION_TARGETS)[number];
export const VERIFICATION_OUTCOMES = [
  'passed',
  'failed',
  'skipped',
  'not_configured',
  'stopped',
  'timed_out',
] as const;
export type VerificationOutcome = (typeof VERIFICATION_OUTCOMES)[number];
export const QUALITY_STATUSES = [
  'verified_snapshot',
  'not_verified',
  'stale',
  'failed',
] as const;
export type QualityStatus = (typeof QUALITY_STATUSES)[number];
export const FILE_CHANGE_KINDS = [
  'added',
  'modified',
  'deleted',
  'binary',
  'unsupported',
] as const;
export type FileChangeKind = (typeof FILE_CHANGE_KINDS)[number];
export const ERROR_CODES = [
  'invalid_request',
  'unauthorized',
  'forbidden',
  'not_found',
  'conflict',
  'idempotency_conflict',
  'request_in_progress',
  'workspace_busy',
  'selection_stale',
  'lease_lost',
  'budget_revision_mismatch',
  'budget_exhausted',
  'action_not_approved',
  'runtime_unavailable',
  'recovery_required',
  'rate_limited',
  'unavailable',
  'error',
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];
export const LIMITS = {
  "active_ms": 600000,
  "model_calls": 40,
  "tool_calls": 80,
  "repairs_allowed": 2,
  "command_timeout_s": 120,
  "install_timeout_s": 600,
  "output_bytes": 1000000,
  "context_bytes": 65536,
  "snapshot_bytes": 500000000,
  "snapshot_files": 50000
} as const;
export type ApiErrorBody = {
  code: (typeof ERROR_CODES)[number];
  message: string;
  details: Record<string, unknown>;
  retryable: boolean;
  current_revision?: number;
};

export type EventEnvelope<T = unknown> = {
  schema_version: number;
  task_id: string;
  run_id: string | null;
  sequence: number;
  event_id: string;
  type: (typeof EVENT_TYPES)[number];
  occurred_at: number;
  payload: T;
};
