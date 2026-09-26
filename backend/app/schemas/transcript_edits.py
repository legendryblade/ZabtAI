from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_INSTRUCTION_LENGTH = 4000
MAX_REPLACEMENT_TEXT_LENGTH = 10000
MAX_SCOPE_ITEMS = 500
MAX_OPERATIONS = 100
MAX_SPEAKER_KEY_LENGTH = 200
MAX_ERROR_LENGTH = 1000
TranscriptEditStatus = Literal[
    "queued",
    "processing",
    "completed",
    "applied",
    "discarded",
    "failed",
]


def _reject_control_characters(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise ValueError("control characters are not allowed")
    return value


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TranscriptEditScope(StrictRequestModel):
    type: Optional[Literal["whole_transcript", "segments", "speakers"]] = Field(
        default=None,
        validation_alias=AliasChoices("type", "scope_type", "kind"),
    )
    segment_ids: Optional[list[int]] = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_ITEMS,
    )
    speaker_keys: Optional[list[str]] = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_ITEMS,
    )

    @model_validator(mode="before")
    @classmethod
    def infer_scope_type(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if not any(key in normalized for key in ("type", "scope_type", "kind")):
            if normalized.get("segment_ids") is not None:
                normalized["type"] = "segments"
            elif normalized.get("speaker_keys") is not None:
                normalized["type"] = "speakers"
            else:
                normalized["type"] = "whole_transcript"
        return normalized

    @model_validator(mode="after")
    def validate_scope_shape(self) -> "TranscriptEditScope":
        if self.type is None:
            raise ValueError("scope type is required")
        if self.type == "whole_transcript":
            if self.segment_ids is not None or self.speaker_keys is not None:
                raise ValueError("whole transcript scope cannot contain selections")
        elif self.type == "segments":
            if self.segment_ids is None or self.speaker_keys is not None:
                raise ValueError("segments scope requires only segment_ids")
        elif self.type == "speakers":
            if self.speaker_keys is None or self.segment_ids is not None:
                raise ValueError("speakers scope requires only speaker_keys")
        return self

    @field_validator("segment_ids")
    @classmethod
    def unique_segment_ids(cls, value: Optional[list[int]]) -> Optional[list[int]]:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("segment_ids must not contain duplicates")
        if value is not None and any(item <= 0 for item in value):
            raise ValueError("segment_ids must be positive")
        return value

    @field_validator("speaker_keys")
    @classmethod
    def valid_speaker_keys(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return value
        if any(not item for item in value):
            raise ValueError("speaker_keys must not contain empty values")
        if any(len(item) > MAX_SPEAKER_KEY_LENGTH for item in value):
            raise ValueError("speaker_keys are too long")
        if len(value) != len(set(value)):
            raise ValueError("speaker_keys must not contain duplicates")
        for item in value:
            _reject_control_characters(item)
        return value


class ReplaceTextOperation(StrictRequestModel):
    operation: Literal["replace_text"]
    segment_id: int = Field(gt=0)
    replacement_text: str = Field(
        min_length=1,
        max_length=MAX_REPLACEMENT_TEXT_LENGTH,
    )

    @field_validator("replacement_text")
    @classmethod
    def replacement_text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("replacement_text must not be blank")
        return _reject_control_characters(value)


class RenameSpeakerOperation(StrictRequestModel):
    operation: Literal["rename_speaker"]
    speaker_key: str = Field(min_length=1, max_length=MAX_SPEAKER_KEY_LENGTH)
    display_name: str = Field(min_length=1, max_length=MAX_SPEAKER_KEY_LENGTH)

    @field_validator("speaker_key", "display_name")
    @classmethod
    def speaker_values_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("speaker values must not be blank")
        return _reject_control_characters(value)


class ReassignSpeakerOperation(StrictRequestModel):
    operation: Literal["reassign_speaker"]
    segment_ids: list[int] = Field(min_length=1, max_length=MAX_SCOPE_ITEMS)
    target_speaker_key: str = Field(min_length=1, max_length=MAX_SPEAKER_KEY_LENGTH)

    @field_validator("segment_ids")
    @classmethod
    def unique_segment_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("segment_ids must be positive")
        if len(value) != len(set(value)):
            raise ValueError("segment_ids must not contain duplicates")
        return value

    @field_validator("target_speaker_key")
    @classmethod
    def target_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("target_speaker_key must not be blank")
        return _reject_control_characters(value)


TranscriptEditOperation = Annotated[
    Union[ReplaceTextOperation, RenameSpeakerOperation, ReassignSpeakerOperation],
    Field(discriminator="operation"),
]


class TranscriptEditProposal(StrictRequestModel):
    operations: list[TranscriptEditOperation] = Field(
        min_length=1,
        max_length=MAX_OPERATIONS,
    )


class StoredReplaceTextOperation(ReplaceTextOperation):
    before: dict[str, Any]


class StoredRenameSpeakerOperation(RenameSpeakerOperation):
    before: dict[str, Any]


class StoredReassignSpeakerOperation(ReassignSpeakerOperation):
    before: dict[str, Any]


StoredTranscriptEditOperation = Annotated[
    Union[StoredReplaceTextOperation, StoredRenameSpeakerOperation, StoredReassignSpeakerOperation],
    Field(discriminator="operation"),
]


class TranscriptEditProposalRead(StrictRequestModel):
    operations: list[StoredTranscriptEditOperation] = Field(
        min_length=1,
        max_length=MAX_OPERATIONS,
    )


class TranscriptEditCreateRequest(StrictRequestModel):
    instruction: str = Field(min_length=1, max_length=MAX_INSTRUCTION_LENGTH)
    scope: TranscriptEditScope

    @field_validator("instruction")
    @classmethod
    def instruction_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instruction must not be blank")
        return value


class TranscriptEditApplyRequest(StrictRequestModel):
    expected_revision: Optional[int] = Field(default=None, ge=0)
    base_revision: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def revisions_agree(self) -> "TranscriptEditApplyRequest":
        if (
            self.expected_revision is not None
            and self.base_revision is not None
            and self.expected_revision != self.base_revision
        ):
            raise ValueError("expected_revision and base_revision must match")
        return self


class TranscriptEditDiscardRequest(StrictRequestModel):
    pass


class TranscriptEditRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    meeting_id: int
    requested_by: int
    instruction: str
    scope: TranscriptEditScope
    base_revision: int
    status: TranscriptEditStatus
    proposal: Optional[TranscriptEditProposalRead] = None
    error: Optional[str] = None
    created_at: datetime
    applied_at: Optional[datetime] = None


TranscriptEditCreate = TranscriptEditCreateRequest


class TranscriptEditCreateResponse(TranscriptEditRead):
    pass


TranscriptEditJobCreate = TranscriptEditCreateRequest


class TranscriptEditGetResponse(TranscriptEditRead):
    pass


class TranscriptEditJobResponse(TranscriptEditRead):
    pass


TranscriptEditJobRead = TranscriptEditJobResponse


class TranscriptEditApplyResponse(TranscriptEditRead):
    pass


class TranscriptEditDiscardResponse(TranscriptEditRead):
    pass


TranscriptEditApply = TranscriptEditApplyRequest
TranscriptEditDiscard = TranscriptEditDiscardRequest
ReplaceText = ReplaceTextOperation
RenameSpeaker = RenameSpeakerOperation
ReassignSpeaker = ReassignSpeakerOperation
