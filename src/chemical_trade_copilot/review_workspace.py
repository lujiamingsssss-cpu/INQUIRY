from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from .inquiry_analysis import InquiryAnalysis
from .inquiry_review import (
    ExpertDecision,
    ReviewFollowUp,
    ReviewSessionState,
    apply_session_decision,
    review_card_matches_analysis,
    validate_decision_outcome,
)
from .localization import Locale
from .review_email_generation import (
    DraftGenerationRecipe,
    render_generated_draft,
)


ReviewPage = Literal[
    "inquiry",
    "conclusion",
    "gaps",
    "evidence",
    "decision",
    "email",
    "print",
    "record",
]
REVIEW_PAGES: tuple[ReviewPage, ...] = (
    "inquiry",
    "conclusion",
    "gaps",
    "evidence",
    "decision",
    "email",
    "print",
    "record",
)
TargetMarket = Literal[
    "unknown", "EU", "US", "GB", "CN", "CA", "AU", "JP", "KR", "other"
]
TARGET_MARKETS: tuple[TargetMarket, ...] = (
    "unknown",
    "EU",
    "US",
    "GB",
    "CN",
    "CA",
    "AU",
    "JP",
    "KR",
    "other",
)
DecisionExit = Literal["ask_customer", "save_only", "technical_reply"]
DECISION_BY_EXIT: dict[DecisionExit, ExpertDecision] = {
    "ask_customer": "needs_information",
    "save_only": "do_not_recommend",
    "technical_reply": "proceed",
}
BACKUP_MAX_BYTES = 2 * 1024 * 1024


class CatalogDocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_relative_path(self) -> "CatalogDocumentRef":
        path = PurePosixPath(self.relative_path)
        if (
            not self.relative_path
            or "\\" in self.relative_path
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != self.relative_path
        ):
            raise ValueError("Catalog document path must be a normalized relative path")
        return self


class ReviewBackup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["chemical-trade-review-backup"] = "chemical-trade-review-backup"
    version: Literal[1] = 1
    workspace: "ReviewWorkspace"
    catalog_documents: tuple[CatalogDocumentRef, ...]

    @model_validator(mode="after")
    def validate_catalog_documents(self) -> "ReviewBackup":
        paths = [item.relative_path for item in self.catalog_documents]
        if len(paths) != len(set(paths)):
            raise ValueError("Review backup contains duplicate catalog document paths")
        if tuple(paths) != tuple(sorted(paths)):
            raise ValueError("Review backup catalog documents must be sorted")
        return self


class BackupRestoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace: "ReviewWorkspace | None"
    inquiry: str
    target_market: TargetMarket
    requires_reanalysis: bool
    changed_files: tuple[str, ...] = ()


def _validate_workspace_outcome(
    session: ReviewSessionState,
    resolved_follow_up_ids: tuple[str, ...],
) -> None:
    validate_decision_outcome(session.card, session.outcome)
    if session.outcome.decision != "needs_information":
        return
    resolved_questions = {
        item.question
        for item in session.card.follow_ups
        if item.item_id in resolved_follow_up_ids
    }
    if resolved_questions.intersection(session.outcome.selected_follow_ups):
        raise ValueError("Review decision includes a resolved customer question")


class EmailDraftVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(gt=0)
    language: Locale
    subject: str
    body: str
    manually_edited: bool
    authorized_decision: Literal["proceed", "needs_information"]
    follow_up_ids: tuple[str, ...] | None = None
    generation_recipe: DraftGenerationRecipe | None = None


class ReviewWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    inquiry: str
    target_market: TargetMarket
    catalog_fingerprint: str
    analysis: InquiryAnalysis
    session: ReviewSessionState
    current_page: ReviewPage = "conclusion"
    resolved_follow_up_ids: tuple[str, ...] = ()
    email_language: Locale = "en"
    draft_versions: tuple[EmailDraftVersion, ...] = ()
    active_draft_version: int | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_canonical_links(self) -> "ReviewWorkspace":
        if self.session.card.inquiry != self.inquiry:
            raise ValueError("Workspace inquiry must match the review card")
        if not review_card_matches_analysis(self.session.card, self.analysis):
            raise ValueError("Workspace analysis does not match the review card")
        follow_up_ids = {item.item_id for item in self.session.card.follow_ups}
        unknown = sorted(set(self.resolved_follow_up_ids) - follow_up_ids)
        if unknown:
            raise ValueError("Unknown resolved follow-up item: " + ", ".join(unknown))
        _validate_workspace_outcome(self.session, self.resolved_follow_up_ids)
        versions = [draft.version for draft in self.draft_versions]
        if len(versions) != len(set(versions)):
            raise ValueError("Email draft version numbers must be unique")
        for draft in self.draft_versions:
            recipe = draft.generation_recipe
            if recipe is None:
                raise ValueError("Email draft requires generated draft provenance")
            if (
                recipe.authorized_decision == "proceed"
                and self.session.outcome.decision == "proceed"
                and recipe.selected_candidate
                != self.session.outcome.selected_candidate
            ):
                raise ValueError(
                    "Proceed draft recipe selected candidate does not match "
                    "the current expert decision"
                )
            try:
                expected = render_generated_draft(
                    self.analysis,
                    self.session.card,
                    recipe,
                )
            except ValueError as error:
                raise ValueError(
                    f"Invalid generated draft provenance: {error}"
                ) from error
            if (
                draft.language != recipe.language
                or draft.authorized_decision != recipe.authorized_decision
            ):
                raise ValueError("Invalid generated draft provenance binding")
            if draft.follow_up_ids != expected.follow_up_ids:
                raise ValueError(
                    "Invalid generated draft provenance follow-up binding"
                )
            if draft.subject != expected.subject:
                raise ValueError("Invalid generated draft provenance subject")
            body_differs = draft.body != expected.body
            if body_differs != draft.manually_edited:
                raise ValueError("Email draft manual edit state is inconsistent")
        if self.active_draft_version is not None:
            active = next(
                (
                    draft
                    for draft in self.draft_versions
                    if draft.version == self.active_draft_version
                ),
                None,
            )
            if active is None:
                raise ValueError("Active email draft version does not exist")
            if (
                active.language != self.email_language
                or active.authorized_decision != self.session.outcome.decision
            ):
                raise ValueError(
                    "The active email draft does not match the current language and decision"
                )
            if active.authorized_decision == "needs_information":
                resolved = set(self.resolved_follow_up_ids)
                selected = set(self.session.outcome.selected_follow_ups)
                expected_follow_up_ids = tuple(
                    item.item_id
                    for item in self.session.card.follow_ups
                    if item.item_id not in resolved and item.question in selected
                )
                if active.follow_up_ids != expected_follow_up_ids:
                    raise ValueError(
                        "The active email draft follow-up binding is not current"
                    )
        return self


class ReviewRecordSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expert_decision: ExpertDecision
    open_gap_count: int = Field(ge=0)
    email_version: str | None
    analysis_revision: str


def _require_mutable(workspace: ReviewWorkspace) -> None:
    if workspace.completed_at is not None:
        raise ValueError("A completed review cannot be changed; create a new inquiry")


def set_resolved_follow_up(
    workspace: ReviewWorkspace,
    item_id: str,
    *,
    resolved: bool,
) -> ReviewWorkspace:
    _require_mutable(workspace)
    known_ids = {item.item_id for item in workspace.session.card.follow_ups}
    if item_id not in known_ids:
        raise ValueError(f"Unknown follow-up item: {item_id}")
    selected = set(workspace.resolved_follow_up_ids)
    if resolved:
        selected.add(item_id)
    else:
        selected.discard(item_id)
    resolved_ids = tuple(
        item.item_id
        for item in workspace.session.card.follow_ups
        if item.item_id in selected
    )
    update: dict[str, object] = {"resolved_follow_up_ids": resolved_ids}
    authorization_changed = False
    if workspace.session.outcome.decision == "needs_information":
        selected_questions = set(workspace.session.outcome.selected_follow_ups)
        remaining_selected_ids = tuple(
            item.item_id
            for item in workspace.session.card.follow_ups
            if item.item_id not in selected
            and item.question in selected_questions
        )
        updated_session = apply_session_decision(
            workspace.session,
            "needs_information",
            selected_follow_up_ids=remaining_selected_ids,
        )
        update["session"] = updated_session
        authorization_changed = updated_session.outcome != workspace.session.outcome
    if workspace.active_draft_version is not None:
        active = next(
            (
                draft
                for draft in workspace.draft_versions
                if draft.version == workspace.active_draft_version
            ),
            None,
        )
        if (
            active is not None
            and active.authorized_decision == "needs_information"
            and authorization_changed
        ):
            update["active_draft_version"] = None
    return workspace.model_copy(update=update)


def open_follow_ups(workspace: ReviewWorkspace) -> tuple[ReviewFollowUp, ...]:
    resolved = set(workspace.resolved_follow_up_ids)
    return tuple(
        item
        for item in workspace.session.card.follow_ups
        if item.item_id not in resolved
    )


def validate_workspace_decision(workspace: ReviewWorkspace) -> None:
    _validate_workspace_outcome(
        workspace.session,
        workspace.resolved_follow_up_ids,
    )


def select_active_draft(
    workspace: ReviewWorkspace,
    version: int,
) -> ReviewWorkspace:
    _require_mutable(workspace)
    if not any(draft.version == version for draft in workspace.draft_versions):
        raise ValueError(f"Email draft version {version} does not exist")
    updated = workspace.model_copy(update={"active_draft_version": version})
    try:
        return ReviewWorkspace.model_validate_json(updated.model_dump_json())
    except ValidationError as error:
        if "generated draft provenance" in str(error).casefold():
            raise ValueError("Invalid generated draft provenance") from error
        raise ValueError(
            "Email draft version does not match the current authorization"
        ) from error


def edit_active_draft(
    workspace: ReviewWorkspace,
    *,
    body: str,
) -> ReviewWorkspace:
    _require_mutable(workspace)
    active = next(
        (
            draft
            for draft in workspace.draft_versions
            if draft.version == workspace.active_draft_version
        ),
        None,
    )
    if active is None:
        raise ValueError("No active email draft is available to edit")
    if active.generation_recipe is None:
        raise ValueError("Email draft requires generated draft provenance")
    generated = render_generated_draft(
        workspace.analysis,
        workspace.session.card,
        active.generation_recipe,
    )
    edited = active.model_copy(
        update={"body": body, "manually_edited": body != generated.body}
    )
    updated = workspace.model_copy(
        update={
            "draft_versions": tuple(
                edited if draft.version == active.version else draft
                for draft in workspace.draft_versions
            )
        }
    )
    return ReviewWorkspace.model_validate_json(updated.model_dump_json())


def apply_workspace_decision(
    workspace: ReviewWorkspace,
    exit_name: DecisionExit,
    *,
    selected_candidate: str | None = None,
    selected_follow_up_ids: tuple[str, ...] = (),
) -> ReviewWorkspace:
    _require_mutable(workspace)
    if exit_name == "ask_customer":
        available_ids = {item.item_id for item in open_follow_ups(workspace)}
        if not available_ids:
            raise ValueError("No open customer questions remain")
        if not selected_follow_up_ids:
            raise ValueError("Select at least one open customer question")
        if len(selected_follow_up_ids) != len(set(selected_follow_up_ids)):
            raise ValueError("Open customer question selections contain duplicate IDs")
        unavailable = sorted(set(selected_follow_up_ids) - available_ids)
        if unavailable:
            raise ValueError(
                "Selections must be limited to open customer questions: "
                + ", ".join(unavailable)
            )
    if exit_name == "technical_reply" and not any(
        candidate.evidence for candidate in workspace.session.card.internal_candidates
    ):
        raise ValueError("No evidence-backed technical reply is available")
    session = apply_session_decision(
        workspace.session,
        DECISION_BY_EXIT[exit_name],
        selected_candidate=selected_candidate,
        selected_follow_up_ids=selected_follow_up_ids,
    )
    if session.outcome == workspace.session.outcome:
        return workspace.model_copy(update={"session": session})
    return workspace.model_copy(
        update={
            "session": session,
            "draft_versions": (),
            "active_draft_version": None,
        }
    )


def set_current_page(
    workspace: ReviewWorkspace,
    page: object,
) -> ReviewWorkspace:
    try:
        validated_page = TypeAdapter(ReviewPage).validate_python(page)
    except ValidationError as error:
        raise ValueError(f"Unknown review page: {page}") from error
    return workspace.model_copy(update={"current_page": validated_page})


def record_summary(workspace: ReviewWorkspace) -> ReviewRecordSummary:
    active = next(
        (
            draft
            for draft in workspace.draft_versions
            if draft.version == workspace.active_draft_version
        ),
        None,
    )
    version = None if active is None else f"{active.version} · {active.language}"
    return ReviewRecordSummary(
        expert_decision=workspace.session.outcome.decision,
        open_gap_count=len(open_follow_ups(workspace)),
        email_version=version,
        analysis_revision=workspace.session.analysis_revision,
    )


def finalize_workspace(
    workspace: ReviewWorkspace,
    *,
    completed_at: datetime | str,
) -> ReviewWorkspace:
    workspace = ReviewWorkspace.model_validate_json(workspace.model_dump_json())
    _require_mutable(workspace)
    decision = workspace.session.outcome.decision
    if decision == "pending":
        raise ValueError("Choose an expert decision before completing the review")
    if decision in {"needs_information", "proceed"} and not any(
        draft.version == workspace.active_draft_version
        for draft in workspace.draft_versions
    ):
        raise ValueError("Generate the authorized email before completing the review")
    try:
        timestamp = TypeAdapter(datetime).validate_python(completed_at)
    except ValidationError as error:
        raise ValueError("Completion time must be a valid ISO timestamp") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Completion time must include a timezone")
    updated = workspace.model_copy(
        update={"completed_at": timestamp, "current_page": "record"}
    )
    return ReviewWorkspace.model_validate_json(updated.model_dump_json())


def export_review_backup(
    workspace: ReviewWorkspace,
    catalog_documents: tuple[CatalogDocumentRef, ...],
) -> str:
    canonical_workspace = ReviewWorkspace.model_validate_json(
        workspace.model_dump_json()
    )
    return ReviewBackup(
        workspace=canonical_workspace,
        catalog_documents=catalog_documents,
    ).model_dump_json(indent=2)


def import_review_backup(
    payload: str | bytes,
    current_documents: tuple[CatalogDocumentRef, ...],
) -> BackupRestoreResult:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > BACKUP_MAX_BYTES:
        raise ValueError("Review backup exceeds the size limit")
    backup = ReviewBackup.model_validate_json(raw)
    current_paths = [item.relative_path for item in current_documents]
    if len(current_paths) != len(set(current_paths)):
        raise ValueError("Current catalog contains duplicate document paths")
    if tuple(current_paths) != tuple(sorted(current_paths)):
        raise ValueError("Current catalog documents must be sorted")
    old = {item.relative_path: item.sha256 for item in backup.catalog_documents}
    current = {item.relative_path: item.sha256 for item in current_documents}
    changed = tuple(
        sorted(
            path
            for path in set(old) | set(current)
            if old.get(path) != current.get(path)
        )
    )
    if changed:
        return BackupRestoreResult(
            workspace=None,
            inquiry=backup.workspace.inquiry,
            target_market=backup.workspace.target_market,
            requires_reanalysis=True,
            changed_files=changed,
        )
    return BackupRestoreResult(
        workspace=backup.workspace,
        inquiry=backup.workspace.inquiry,
        target_market=backup.workspace.target_market,
        requires_reanalysis=False,
    )
