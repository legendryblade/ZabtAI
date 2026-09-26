# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
from app.schemas import transcript_edits as _schemas

RenameSpeakerOperation = _schemas.RenameSpeakerOperation
ReassignSpeakerOperation = _schemas.ReassignSpeakerOperation
ReplaceTextOperation = _schemas.ReplaceTextOperation
RenameSpeaker = _schemas.RenameSpeaker
ReassignSpeaker = _schemas.ReassignSpeaker
ReplaceText = _schemas.ReplaceText
TranscriptEditApply = _schemas.TranscriptEditApply
TranscriptEditApplyRequest = _schemas.TranscriptEditApplyRequest
TranscriptEditCreate = _schemas.TranscriptEditCreate
TranscriptEditCreateRequest = _schemas.TranscriptEditCreateRequest
TranscriptEditCreateResponse = _schemas.TranscriptEditCreateResponse
TranscriptEditDiscard = _schemas.TranscriptEditDiscard
TranscriptEditDiscardRequest = _schemas.TranscriptEditDiscardRequest
TranscriptEditGetResponse = _schemas.TranscriptEditGetResponse
TranscriptEditJobCreate = _schemas.TranscriptEditJobCreate
TranscriptEditJobRead = _schemas.TranscriptEditJobRead
TranscriptEditJobResponse = _schemas.TranscriptEditJobResponse
TranscriptEditProposal = _schemas.TranscriptEditProposal
TranscriptEditProposalRead = _schemas.TranscriptEditProposalRead
TranscriptEditRead = _schemas.TranscriptEditRead
TranscriptEditScope = _schemas.TranscriptEditScope

__all__ = [
    "RenameSpeakerOperation",
    "ReassignSpeakerOperation",
    "ReplaceTextOperation",
    "RenameSpeaker",
    "ReassignSpeaker",
    "ReplaceText",
    "TranscriptEditApply",
    "TranscriptEditApplyRequest",
    "TranscriptEditCreate",
    "TranscriptEditCreateRequest",
    "TranscriptEditCreateResponse",
    "TranscriptEditDiscard",
    "TranscriptEditDiscardRequest",
    "TranscriptEditGetResponse",
    "TranscriptEditJobCreate",
    "TranscriptEditJobRead",
    "TranscriptEditJobResponse",
    "TranscriptEditProposal",
    "TranscriptEditProposalRead",
    "TranscriptEditRead",
    "TranscriptEditScope",
]
