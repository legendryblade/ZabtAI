// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2025-2026 Afeef Janjua
// Transcript primitives

export interface TranscriptWord {
  word: string;
  start: number;
  end: number;
}

export interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  speaker: string;
  speaker_name?: string | null;
  text: string;
  text_edited?: boolean;
  word_alignment_valid?: boolean;
  words: TranscriptWord[];
}

export type TranscriptEditScopeType =
  | "whole_transcript"
  | "segments"
  | "speakers";

export type TranscriptEditScope =
  | { type: "whole_transcript" }
  | { type: "segments"; segment_ids: number[] }
  | { type: "speakers"; speaker_keys: string[] };

export interface TranscriptEditReplaceTextBefore {
  segment_id: number;
  text: string;
  speaker: string | null;
  start_time: number;
  end_time: number;
  words: TranscriptWord[];
}

export interface TranscriptEditRenameSpeakerBefore {
  speaker_key: string;
  display_name: string;
}

export interface TranscriptEditReassignSpeakerBeforeSegment {
  segment_id: number;
  speaker: string | null;
}

export interface TranscriptEditReassignSpeakerBefore {
  segments: TranscriptEditReassignSpeakerBeforeSegment[];
}

export interface TranscriptEditReplaceTextOperation {
  operation: "replace_text";
  segment_id: number;
  replacement_text: string;
  before: TranscriptEditReplaceTextBefore;
}

export interface TranscriptEditRenameSpeakerOperation {
  operation: "rename_speaker";
  speaker_key: string;
  display_name: string;
  before: TranscriptEditRenameSpeakerBefore;
}

export interface TranscriptEditReassignSpeakerOperation {
  operation: "reassign_speaker";
  segment_ids: number[];
  target_speaker_key: string;
  before: TranscriptEditReassignSpeakerBefore;
}

export type TranscriptEditOperation =
  | TranscriptEditReplaceTextOperation
  | TranscriptEditRenameSpeakerOperation
  | TranscriptEditReassignSpeakerOperation;

export interface TranscriptEditProposal {
  operations: TranscriptEditOperation[];
}

export type TranscriptEditJobStatus =
  | "queued"
  | "processing"
  | "completed"
  | "applied"
  | "failed"
  | "discarded";

export interface TranscriptEditJob {
  id: string;
  meeting_id: number;
  requested_by: number;
  instruction: string;
  scope: TranscriptEditScope;
  base_revision: number;
  status: TranscriptEditJobStatus;
  proposal: TranscriptEditProposal | null;
  error: string | null;
  created_at: string;
  applied_at: string | null;
}

export interface TranscriptEditCreateRequest {
  instruction: string;
  scope: TranscriptEditScope;
}

export interface TranscriptEditApplyRequest {
  expected_revision?: number;
}

export type TranscriptEditDiscardRequest = Record<string, never>;

export type TranscriptEditStatus = TranscriptEditJobStatus;
export type ReplaceTextOperation = TranscriptEditReplaceTextOperation;
export type RenameSpeakerOperation = TranscriptEditRenameSpeakerOperation;
export type ReassignSpeakerOperation = TranscriptEditReassignSpeakerOperation;

export interface SpeakerBreakdown {
  percentage: number;
  name: string;
}

// Meeting

export interface Meeting {
  id: number;
  title: string;
  description: string | null;
  file_path: string;
  duration_seconds: number | null;
  created_at: string;
  status: MeetingStatus;
  sub_status: string | null;
  transcript_text: string | null;
  transcript_revision?: number;
  derived_transcript_revision?: number;
  derived_transcript_stale?: boolean;
  transcript_derived_stale?: boolean;
  summary_text: string | null;
  original_summary_text: string | null;
  summary_edited: boolean;
  action_items_text: string | null;
  template_id: number | null;
  template_name: string | null;
  transcription_type: TranscriptionType;
  source_type: MeetingSource;
  source_url: string | null;
  youtube_title: string | null;
  youtube_duration_seconds: number | null;
  youtube_thumbnail_url: string | null;
  youtube_channel: string | null;
  audio_url: string | null;
  speakers?: Record<string, SpeakerBreakdown>;
  segments?: TranscriptSegment[];
  meeting_type: MeetingType;
  structured_output: Record<string, unknown> | null;
  structured_output_status: StructuredOutputStatus;
  highlights: MeetingHighlight[];
  layout_hint: LayoutHint;
  requested_language: string | null;
  transliterated_text: string | null;
}

export interface MeetingList {
  items: Meeting[];
  total: number;
  skip: number;
  limit: number;
}

export interface MeetingHighlight {
  id: number;
  meeting_id: number;
  highlight_type: HighlightType;
  content: string;
  speaker: string | null;
  timestamp_start: number;
  timestamp_end: number | null;
  ai_answer: string | null;
  metadata: Record<string, unknown> | null;
  sort_order: number;
}

// Summary templates

export interface SummaryTemplate {
  id: number;
  name: string;
  body: string;
  template_type: TemplateType;
  is_system_default: boolean;
  owner_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface SummaryTemplateListItem {
  id: number;
  name: string;
  template_type: TemplateType;
  is_system_default: boolean;
}

// User + Auth

export interface User {
  email: string;
  full_name: string | null;
  tier: UserTier;
  is_active: boolean;
  minutes_used_this_month: number;
}

export interface AuthToken {
  access_token: string;
  token_type: "bearer";
}

export interface SSOLookupRequest {
  email: string;
}

export interface SSOLookupResponse {
  sso_enabled: boolean;
  redirect_url: string | null;
  organisation_name: string | null;
}

// Forward references — string literal types defined in enums.ts
import type {
  MeetingStatus,
  TranscriptionType,
  MeetingSource,
  MeetingType,
  StructuredOutputStatus,
  LayoutHint,
  HighlightType,
  TemplateType,
  UserTier,
} from "./enums";
