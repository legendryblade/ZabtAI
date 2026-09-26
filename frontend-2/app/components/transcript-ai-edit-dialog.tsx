// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2025-2026 Afeef Janjua
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { isAxiosError } from "axios";
import { CheckCircle2, CircleAlert, Loader2, Sparkles } from "lucide-react";
import {
  applyTranscriptEdit,
  createTranscriptEdit,
  discardTranscriptEdit,
  getTranscriptEdit,
} from "@/app/lib/api";
import type {
  TranscriptEditJob,
  TranscriptEditOperation,
  TranscriptEditScope,
  TranscriptEditScopeType,
  TranscriptSegment,
} from "@/app/lib/api";
import { Button } from "@/app/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/app/components/ui/dialog";

const ACTIVE_STATUSES = new Set<TranscriptEditJob["status"]>([
  "queued",
  "processing",
]);
const MAX_SEGMENT_SCOPE = 500;

const STATUS_LABELS: Record<TranscriptEditJob["status"], string> = {
  queued: "Queued",
  processing: "Processing",
  completed: "Ready to review",
  applied: "Applied",
  failed: "Failed",
  discarded: "Discarded",
};

const formatTime = (seconds: number) => {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
};

const getSpeakerKey = (segment: TranscriptSegment) =>
  segment.speaker || "SPEAKER_UNKNOWN";

const getSpeakerLabel = (speakerKey: string) => {
  if (speakerKey === "SPEAKER_UNKNOWN") return "Unknown Speaker";
  const match = /^SPEAKER_(\d+)$/.exec(speakerKey);
  return match ? `Speaker ${Number(match[1]) + 1}` : speakerKey;
};

const getSpeakerDisplayName = (value: unknown, speakerKey: string) => {
  const displayName = typeof value === "string" ? value.trim() : "";
  return displayName && displayName !== speakerKey
    ? displayName
    : getSpeakerLabel(speakerKey);
};

const getErrorMessage = (error: unknown, fallback: string) => {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item && typeof item.msg === "string"
            ? item.msg
            : null
        )
        .filter((item): item is string => Boolean(item));
      if (messages.length > 0) return messages.join(" ");
    }
  }
  return error instanceof Error && error.message ? error.message : fallback;
};

const displayValue = (value: unknown, fallback: string) =>
  typeof value === "string" ? value : fallback;

function OperationPreview({ operation }: { operation: TranscriptEditOperation }) {
  if (operation.operation === "replace_text") {
    return (
      <div className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
        <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-muted-foreground">
          <span>Text replacement</span>
          <span aria-hidden>·</span>
          <span>Segment {operation.segment_id}</span>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-md border border-border bg-background p-2.5">
            <p className="mb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
              Before
            </p>
            <p className="whitespace-pre-wrap break-words text-sm text-foreground">
              {displayValue(operation.before?.text, "Original text unavailable")}
            </p>
          </div>
          <div className="rounded-md border border-primary/30 bg-primary/5 p-2.5">
            <p className="mb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-primary">
              After
            </p>
            <p className="whitespace-pre-wrap break-words text-sm text-foreground">
              {displayValue(operation.replacement_text, "Replacement unavailable")}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (operation.operation === "rename_speaker") {
    return (
      <div className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
        <div className="text-xs font-medium text-muted-foreground">
          Speaker rename · {getSpeakerLabel(operation.speaker_key)}
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-md border border-border bg-background p-2.5">
            <p className="mb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
              Before
            </p>
            <p className="break-words text-sm text-foreground">
              {getSpeakerDisplayName(operation.before?.display_name, operation.speaker_key)}
            </p>
          </div>
          <div className="rounded-md border border-primary/30 bg-primary/5 p-2.5">
            <p className="mb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-primary">
              After
            </p>
            <p className="break-words text-sm text-foreground">
              {displayValue(operation.display_name, "Name unavailable")}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (operation.operation !== "reassign_speaker") {
    return (
      <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
        Unsupported proposal operation.
      </div>
    );
  }

  const segmentIds = Array.isArray(operation.segment_ids) ? operation.segment_ids : [];
  const beforeSegments = Array.isArray(operation.before?.segments)
    ? operation.before.segments
    : [];

  return (
    <div className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
      <div className="text-xs font-medium text-muted-foreground">
        Speaker reassignment · {segmentIds.length} segment
        {segmentIds.length === 1 ? "" : "s"}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-md border border-border bg-background p-2.5">
          <p className="mb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
            Before
          </p>
          <div className="space-y-1 text-sm text-foreground">
            {beforeSegments.map((segment) => (
              <p key={segment.segment_id} className="break-words">
                <span className="text-muted-foreground">Segment {segment.segment_id}:</span>{" "}
                {getSpeakerLabel(segment.speaker || "SPEAKER_UNKNOWN")}
              </p>
            ))}
            {beforeSegments.length === 0 && (
              <p className="text-sm text-muted-foreground">Original assignments unavailable</p>
            )}
          </div>
        </div>
        <div className="rounded-md border border-primary/30 bg-primary/5 p-2.5">
          <p className="mb-1 text-[0.7rem] font-semibold uppercase tracking-wide text-primary">
            After
          </p>
          <p className="break-words text-sm text-foreground">
            {getSpeakerLabel(operation.target_speaker_key)}
          </p>
        </div>
      </div>
    </div>
  );
}

function ProposalPreview({ job }: { job: TranscriptEditJob }) {
  if (!job.proposal || job.proposal.operations.length === 0) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
        The edit completed without a reviewable proposal.
      </div>
    );
  }

  return (
    <div className="space-y-3" aria-label="Proposed transcript changes">
      {job.proposal.operations.map((operation, index) => (
        <OperationPreview key={`${operation.operation}-${index}`} operation={operation} />
      ))}
    </div>
  );
}

interface TranscriptAiEditDialogProps {
  meetingId: number;
  segments: TranscriptSegment[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApplied: (job: TranscriptEditJob) => void | Promise<void>;
}

export function TranscriptAiEditDialog({
  meetingId,
  segments,
  open,
  onOpenChange,
  onApplied,
}: TranscriptAiEditDialogProps) {
  const [instruction, setInstruction] = useState("");
  const [scopeType, setScopeType] = useState<TranscriptEditScopeType>("whole_transcript");
  const [selectedSpeakerKey, setSelectedSpeakerKey] = useState("");
  const [selectedSegmentIds, setSelectedSegmentIds] = useState<Set<number>>(
    () => new Set()
  );
  const [job, setJob] = useState<TranscriptEditJob | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isDiscarding, setIsDiscarding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const requestEpochRef = useRef(0);
  const busyRef = useRef(false);
  const openRef = useRef(open);

  const speakerOptions = useMemo(() => {
    const options = new Map<string, string>();
    for (const segment of segments) {
      const key = getSpeakerKey(segment);
      const named = segment.speaker_name?.trim();
      if (named && named !== key) {
        options.set(key, named);
      } else if (!options.has(key)) {
        options.set(key, getSpeakerLabel(key));
      }
    }
    return Array.from(options.entries())
      .map(([key, label]) => ({ key, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [segments]);

  const orderedSegments = useMemo(
    () =>
      [...segments].sort(
        (a, b) => a.start - b.start || (a.id ?? 0) - (b.id ?? 0)
      ),
    [segments]
  );

  useEffect(() => {
    openRef.current = open;
  }, [open]);

  useEffect(() => {
    if (!open || isDiscarding || !job || !ACTIVE_STATUSES.has(job.status)) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const nextJob = await getTranscriptEdit(meetingId, job.id);
        if (cancelled) return;
        setError(null);
        setJob(nextJob);
        if (ACTIVE_STATUSES.has(nextJob.status)) {
          timer = setTimeout(poll, 1000);
        }
      } catch (pollError) {
        if (!cancelled) {
          setError(getErrorMessage(pollError, "Could not check the edit status."));
        }
      }
    };

    timer = setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [open, meetingId, job, pollAttempt, isDiscarding]);

  const buildScope = (): TranscriptEditScope | null => {
    if (scopeType === "whole_transcript") {
      return { type: "whole_transcript" };
    }
    if (scopeType === "speakers") {
      return selectedSpeakerKey
        ? { type: "speakers", speaker_keys: [selectedSpeakerKey] }
        : null;
    }
    return selectedSegmentIds.size > 0
      ? { type: "segments", segment_ids: Array.from(selectedSegmentIds) }
      : null;
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busyRef.current) return;
    const trimmedInstruction = instruction.trim();
    const scope = buildScope();

    if (!trimmedInstruction) {
      setError("Describe the transcript change you want to make.");
      return;
    }
    if (!scope) {
      setError(
        scopeType === "speakers"
          ? "Choose a speaker first."
          : "Choose at least one segment first."
      );
      return;
    }

    const requestEpoch = requestEpochRef.current;
    busyRef.current = true;
    setIsSubmitting(true);
    setError(null);
    try {
      const createdJob = await createTranscriptEdit(meetingId, {
        instruction: trimmedInstruction,
        scope,
      });
      if (requestEpochRef.current === requestEpoch && openRef.current) {
        setJob(createdJob);
      }
    } catch (submitError) {
      if (requestEpochRef.current === requestEpoch && openRef.current) {
        setError(getErrorMessage(submitError, "Could not start the transcript edit."));
      }
    } finally {
      busyRef.current = false;
      setIsSubmitting(false);
    }
  };

  const handleApply = async () => {
    if (!job || job.status !== "completed" || !job.proposal || busyRef.current) return;

    const requestEpoch = requestEpochRef.current;
    busyRef.current = true;
    setIsApplying(true);
    setError(null);
    try {
      const appliedJob = await applyTranscriptEdit(
        meetingId,
        job.id,
        job.base_revision
      );
      if (requestEpochRef.current !== requestEpoch || !openRef.current) return;
      setJob(appliedJob);
      setNeedsRefresh(true);
      try {
        await onApplied(appliedJob);
        if (requestEpochRef.current === requestEpoch && openRef.current) {
          setNeedsRefresh(false);
        }
      } catch {
        setError("The edit was applied, but the meeting could not be refreshed.");
      }
    } catch (applyError) {
      if (requestEpochRef.current === requestEpoch && openRef.current) {
        setError(getErrorMessage(applyError, "Could not apply the transcript edit."));
      }
    } finally {
      busyRef.current = false;
      setIsApplying(false);
    }
  };

  const handleRetryRefresh = async () => {
    if (!job || job.status !== "applied" || busyRef.current) return;
    const requestEpoch = requestEpochRef.current;
    busyRef.current = true;
    setIsRefreshing(true);
    setError(null);
    try {
      await onApplied(job);
      if (requestEpochRef.current === requestEpoch && openRef.current) {
        setNeedsRefresh(false);
      }
    } catch (refreshError) {
      if (requestEpochRef.current === requestEpoch && openRef.current) {
        setError(getErrorMessage(refreshError, "Could not refresh the meeting."));
      }
    } finally {
      busyRef.current = false;
      setIsRefreshing(false);
    }
  };

  const handleDiscard = async () => {
    if (
      !job ||
      job.status === "applied" ||
      job.status === "discarded" ||
      busyRef.current
    ) return;

    const requestEpoch = requestEpochRef.current;
    busyRef.current = true;
    setIsDiscarding(true);
    setError(null);
    try {
      const discardedJob = await discardTranscriptEdit(meetingId, job.id);
      if (requestEpochRef.current === requestEpoch && openRef.current) {
        setJob(discardedJob);
      }
    } catch (discardError) {
      if (requestEpochRef.current === requestEpoch && openRef.current) {
        setError(getErrorMessage(discardError, "Could not discard the transcript edit."));
      }
    } finally {
      busyRef.current = false;
      setIsDiscarding(false);
    }
  };

  const resetForm = () => {
    requestEpochRef.current += 1;
    busyRef.current = false;
    setInstruction("");
    setScopeType("whole_transcript");
    setSelectedSpeakerKey("");
    setSelectedSegmentIds(new Set());
    setJob(null);
    setError(null);
    setPollAttempt(0);
    setNeedsRefresh(false);
  };

  const handleDialogOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && busyRef.current) return;
    const hasUnresolvedJob = Boolean(
      job &&
      job.status !== "failed" &&
      job.status !== "discarded" &&
      (job.status !== "applied" || needsRefresh)
    );
    if (!nextOpen && hasUnresolvedJob) {
      setError(
        job?.status === "completed"
          ? "Apply or discard this proposal before closing."
          : "Discard this edit or wait for it to finish before closing."
      );
      return;
    }
    if (!nextOpen) resetForm();
    onOpenChange(nextOpen);
  };

  const handleStartOver = () => {
    resetForm();
  };

  const handleRetryPoll = () => {
    setError(null);
    setPollAttempt((attempt) => attempt + 1);
  };

  const isActiveJob = Boolean(job && ACTIVE_STATUSES.has(job.status));
  const canDiscard = Boolean(
    job && job.status !== "applied" && job.status !== "discarded"
  );
  const canApply = job?.status === "completed" && Boolean(job.proposal);
  const isBusy = isSubmitting || isApplying || isRefreshing || isDiscarding;
  const formDisabled = Boolean(job) || isSubmitting;

  return (
    <Dialog open={open} onOpenChange={handleDialogOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl" aria-busy={isBusy}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" aria-hidden />
            Edit transcript with AI
          </DialogTitle>
          <DialogDescription>
            Describe a text or speaker change. Nothing changes until you review and apply the
            proposal.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span className="whitespace-pre-wrap break-words">{error}</span>
          </div>
        )}

        {!job ? (
          <form id="transcript-ai-edit-form" className="space-y-5" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <label htmlFor="transcript-ai-edit-instruction" className="text-sm font-medium">
                What should be changed?
              </label>
              <textarea
                id="transcript-ai-edit-instruction"
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                maxLength={4000}
                rows={4}
                autoFocus
                placeholder="For example: Correct the product name and assign the last two turns to the product manager."
                className="min-h-28 w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                aria-describedby="transcript-ai-edit-help"
              />
              <p id="transcript-ai-edit-help" className="text-xs text-muted-foreground">
                Use plain language. The preview will show every proposed change before anything is
                applied.
              </p>
            </div>

            <div className="space-y-2">
              <label htmlFor="transcript-ai-edit-scope" className="text-sm font-medium">
                Scope
              </label>
              <select
                id="transcript-ai-edit-scope"
                value={scopeType}
                onChange={(event) =>
                  setScopeType(event.target.value as TranscriptEditScopeType)
                }
                className="h-9 w-full rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <option value="whole_transcript">Whole transcript</option>
                <option value="speakers">One speaker</option>
                <option value="segments">Selected segments</option>
              </select>
            </div>

            {scopeType === "speakers" && (
              <div className="space-y-2">
                <label htmlFor="transcript-ai-edit-speaker" className="text-sm font-medium">
                  Speaker
                </label>
                <select
                  id="transcript-ai-edit-speaker"
                  value={selectedSpeakerKey}
                  onChange={(event) => setSelectedSpeakerKey(event.target.value)}
                  className="h-9 w-full rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <option value="">Select a speaker</option>
                  {speakerOptions.map((speaker) => (
                    <option key={speaker.key} value={speaker.key}>
                      {speaker.label}
                    </option>
                  ))}
                </select>
                {speakerOptions.length === 0 && (
                  <p className="text-xs text-muted-foreground">No speakers are available.</p>
                )}
              </div>
            )}

            {scopeType === "segments" && (
              <div className="space-y-2">
                <div>
                  <p id="transcript-ai-edit-segments-label" className="text-sm font-medium">
                    Segments
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Choose the transcript rows the AI should consider.
                  </p>
                </div>
                {orderedSegments.length > 0 ? (
                  <div
                    className="max-h-44 space-y-1 overflow-y-auto rounded-lg border border-border p-1"
                    role="group"
                    aria-labelledby="transcript-ai-edit-segments-label"
                  >
                    {orderedSegments.map((segment) => {
                      const checked = selectedSegmentIds.has(segment.id);
                      return (
                        <label
                          key={segment.id}
                          className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
                        >
                          <input
                            type="checkbox"
                            className="mt-1 size-3.5 shrink-0 accent-primary"
                            checked={checked}
                            disabled={!checked && selectedSegmentIds.size >= MAX_SEGMENT_SCOPE}
                            onChange={(event) => {
                              if (
                                event.target.checked &&
                                !selectedSegmentIds.has(segment.id) &&
                                selectedSegmentIds.size >= MAX_SEGMENT_SCOPE
                              ) {
                                setError(`Select no more than ${MAX_SEGMENT_SCOPE} segments.`);
                                return;
                              }
                              setSelectedSegmentIds((current) => {
                                const next = new Set(current);
                                if (event.target.checked) next.add(segment.id);
                                else next.delete(segment.id);
                                return next;
                              });
                            }}
                          />
                          <span className="min-w-0 flex-1">
                            <span className="mr-2 tabular-nums text-xs text-muted-foreground">
                              {formatTime(segment.start)}
                            </span>
                            <span className="break-words">{segment.text}</span>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No segments are available.</p>
                )}
                {selectedSegmentIds.size > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {selectedSegmentIds.size} of {MAX_SEGMENT_SCOPE} segments selected
                  </p>
                )}
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              Only transcript text, speaker names, and speaker assignments can be changed. Timing
              and word boundaries stay unchanged.
            </p>
          </form>
        ) : (
          <div className="space-y-4" aria-live="polite">
            {isActiveJob && (
              <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 p-4">
                <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-primary" aria-hidden />
                <div>
                  <p className="font-medium">{STATUS_LABELS[job.status]}…</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    The AI is preparing a proposal. You can discard it if you no longer want to
                    wait.
                  </p>
                </div>
              </div>
            )}

            {job.status === "completed" && (
              <>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <CheckCircle2 className="size-4 text-primary" aria-hidden />
                  <span>Review the changes below before applying them.</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="rounded-full border border-border px-2 py-0.5">
                    Based on revision {job.base_revision}
                  </span>
                </div>
                <ProposalPreview job={job} />
              </>
            )}

            {job.status === "failed" && (
              <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-destructive" role="alert">
                <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
                <div>
                  <p className="font-medium">The transcript edit failed.</p>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm">
                    {displayValue(job.error, "The service could not complete this edit.")}
                  </p>
                </div>
              </div>
            )}

            {job.status === "applied" && (
              <div className="flex items-start gap-3 rounded-lg border border-primary/30 bg-primary/5 p-4 text-primary">
                <CheckCircle2 className="mt-0.5 size-5 shrink-0" aria-hidden />
                <div>
                  <p className="font-medium">Edit applied.</p>
                  <p className="mt-1 text-sm text-foreground">The transcript has been updated.</p>
                </div>
              </div>
            )}

            {job.status === "discarded" && (
              <div className="rounded-lg border border-border bg-muted/30 p-4">
                <p className="font-medium">Edit discarded.</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  No transcript changes were applied.
                </p>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {canDiscard && (
            <Button
              type="button"
              variant="outline"
              onClick={handleDiscard}
              loading={isDiscarding}
              disabled={isBusy && !isDiscarding}
            >
              Discard
            </Button>
          )}
          {needsRefresh && (
            <Button
              type="button"
              variant="outline"
              onClick={handleRetryRefresh}
              loading={isRefreshing}
              disabled={isBusy && !isRefreshing}
            >
              Retry refresh
            </Button>
          )}
          <Button type="button" variant="outline" onClick={() => handleDialogOpenChange(false)} disabled={isBusy}>
            Close
          </Button>
          {!job && (
            <Button
              type="submit"
              form="transcript-ai-edit-form"
              loading={isSubmitting}
              disabled={formDisabled || !instruction.trim() || !buildScope()}
            >
              Generate preview
            </Button>
          )}
          {canApply && (
            <Button type="button" onClick={handleApply} loading={isApplying} disabled={isBusy}>
              Apply changes
            </Button>
          )}
          {job && (job.status === "failed" || job.status === "discarded") && (
            <Button type="button" variant="outline" onClick={handleStartOver} disabled={isBusy}>
              Start over
            </Button>
          )}
          {isActiveJob && error && (
            <Button type="button" variant="outline" onClick={handleRetryPoll} disabled={isBusy}>
              Retry status
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
