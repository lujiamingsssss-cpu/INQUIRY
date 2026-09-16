import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from .inquiry_review import ReviewFollowUp
from .localization import Locale
from .review_email_generation import (
    DraftGenerationRecipe,
    DraftStyle,
    FollowUpIntent,
    GeneratedDraft,
    classify_follow_up_intent,
    expected_draft_kind,
    render_generated_draft,
)
from .review_workspace import (
    EmailDraftVersion,
    ReviewWorkspace,
    _require_mutable,
    open_follow_ups,
    validate_workspace_decision,
)


class EmailOptimizationClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> str: ...


class FollowUpPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_revision: str
    target_locale: Locale
    intents: dict[str, FollowUpIntent]


def active_draft(workspace: ReviewWorkspace) -> EmailDraftVersion | None:
    return next(
        (
            item
            for item in workspace.draft_versions
            if item.version == workspace.active_draft_version
        ),
        None,
    )


def _validated_workspace(workspace: ReviewWorkspace) -> ReviewWorkspace:
    return ReviewWorkspace.model_validate_json(workspace.model_dump_json())


def _validated_follow_up_presentation(
    presentation: FollowUpPresentation,
) -> FollowUpPresentation:
    unexpected = set(vars(presentation)) - set(FollowUpPresentation.model_fields)
    if unexpected:
        raise ValueError(
            "Follow-up presentation contains unexpected fields: "
            + ", ".join(sorted(unexpected))
        )
    return FollowUpPresentation.model_validate_json(presentation.model_dump_json())


def _selected_open_follow_ups(
    workspace: ReviewWorkspace,
) -> tuple[ReviewFollowUp, ...]:
    selected = set(workspace.session.outcome.selected_follow_ups)
    return tuple(
        item for item in open_follow_ups(workspace) if item.question in selected
    )


def _build_follow_up_draft(
    workspace: ReviewWorkspace,
    style: DraftStyle,
    follow_up_presentation: FollowUpPresentation | None,
) -> GeneratedDraft:
    follow_ups = _selected_open_follow_ups(workspace)
    if not follow_ups:
        raise ValueError("No authorized open customer questions remain")
    if follow_up_presentation is not None:
        follow_up_presentation = _validated_follow_up_presentation(
            follow_up_presentation
        )
    if workspace.email_language == "zh-CN":
        if follow_up_presentation is None:
            raise ValueError("A finite Chinese follow-up presentation is required")
        if follow_up_presentation.target_locale != workspace.email_language:
            raise ValueError("Follow-up presentation locale does not match the email")
        if (
            follow_up_presentation.analysis_revision
            != workspace.session.analysis_revision
        ):
            raise ValueError("Follow-up presentation analysis revision does not match")
        expected_intents = {
            item.item_id: classify_follow_up_intent(item.question)
            for item in follow_ups
        }
        if follow_up_presentation.intents != expected_intents:
            raise ValueError(
                "Follow-up presentation items do not match the authorized open questions"
            )
        intents = tuple(
            follow_up_presentation.intents[item.item_id] for item in follow_ups
        )
    else:
        if follow_up_presentation is not None:
            raise ValueError(
                "A Chinese follow-up presentation cannot be used for an English draft"
            )
        intents = None
    return render_generated_draft(
        workspace.analysis,
        workspace.session.card,
        DraftGenerationRecipe(
            kind="follow_up",
            style=style,
            language=workspace.email_language,
            authorized_decision="needs_information",
            follow_up_ids=tuple(item.item_id for item in follow_ups),
            follow_up_intents=intents,
        ),
    )


def _build_proceed_draft(
    workspace: ReviewWorkspace,
    style: DraftStyle,
) -> GeneratedDraft:
    outcome = workspace.session.outcome
    if not outcome.can_generate_external_recommendation:
        raise ValueError("The current expert decision does not authorize an email")
    selected = outcome.selected_candidate
    assert selected is not None
    kind = expected_draft_kind(workspace.analysis, selected)
    return render_generated_draft(
        workspace.analysis,
        workspace.session.card,
        DraftGenerationRecipe(
            kind=kind,
            style=style,
            language=workspace.email_language,
            authorized_decision="proceed",
            selected_candidate=selected,
        ),
    )


def _build_authorized_draft(
    workspace: ReviewWorkspace,
    style: DraftStyle,
    follow_up_presentation: FollowUpPresentation | None = None,
) -> GeneratedDraft:
    validate_workspace_decision(workspace)
    decision = workspace.session.outcome.decision
    if decision == "needs_information":
        if not workspace.session.outcome.can_generate_follow_up_draft:
            raise ValueError("The current expert decision does not authorize an email")
        return _build_follow_up_draft(workspace, style, follow_up_presentation)
    if decision == "proceed":
        if follow_up_presentation is not None:
            raise ValueError("A proceed draft cannot use a follow-up presentation")
        return _build_proceed_draft(workspace, style)
    raise ValueError("The current expert decision does not authorize an email")


def _append_deterministic_draft(
    workspace: ReviewWorkspace,
    draft: GeneratedDraft,
) -> ReviewWorkspace:
    version = max((item.version for item in workspace.draft_versions), default=0) + 1
    versioned = EmailDraftVersion(
        version=version,
        language=workspace.email_language,
        subject=draft.subject,
        body=draft.body,
        manually_edited=False,
        authorized_decision=workspace.session.outcome.decision,  # type: ignore[arg-type]
        follow_up_ids=draft.follow_up_ids,
        generation_recipe=draft.recipe,
    )
    updated = workspace.model_copy(
        update={
            "draft_versions": (*workspace.draft_versions, versioned),
            "active_draft_version": version,
        }
    )
    return ReviewWorkspace.model_validate_json(updated.model_dump_json())


def ensure_authorized_draft(
    workspace: ReviewWorkspace,
    *,
    follow_up_presentation: FollowUpPresentation | None = None,
) -> ReviewWorkspace:
    workspace = _validated_workspace(workspace)
    _require_mutable(workspace)
    if follow_up_presentation is not None:
        _build_authorized_draft(
            workspace,
            DraftStyle(
                tone="neutral",
                opening="standard",
                question_format="bullets",
            ),
            follow_up_presentation,
        )
    if active_draft(workspace) is not None:
        return workspace
    style = DraftStyle(
        tone="neutral",
        opening="standard",
        question_format=(
            "bullets"
            if workspace.session.outcome.decision == "needs_information"
            else "paragraph"
        ),
    )
    return _append_deterministic_draft(
        workspace,
        _build_authorized_draft(workspace, style, follow_up_presentation),
    )


def optimize_authorized_draft(
    client: EmailOptimizationClient,
    workspace: ReviewWorkspace,
    instruction: str,
    *,
    follow_up_presentation: FollowUpPresentation | None = None,
) -> ReviewWorkspace:
    workspace = _validated_workspace(workspace)
    _require_mutable(workspace)
    if not instruction.strip():
        raise ValueError("Optimization instruction must not be empty")
    _build_authorized_draft(
        workspace,
        DraftStyle(tone="neutral", opening="standard", question_format="bullets"),
        follow_up_presentation,
    )
    if active_draft(workspace) is None:
        raise ValueError("No active authorized draft is available to optimize")
    schema = json.dumps(DraftStyle.model_json_schema(), ensure_ascii=False)
    raw = client.complete_json(
        "Classify the requested email style. Return only the DraftStyle JSON fields. "
        f"The JSON must validate against this schema: {schema}",
        instruction,
    )
    style = DraftStyle.model_validate_json(raw)
    generated = _build_authorized_draft(
        workspace,
        style,
        follow_up_presentation,
    )
    current = active_draft(workspace)
    assert current is not None
    if generated.subject == current.subject and generated.body == current.body:
        raise ValueError("Optimization does not change the active draft")
    return _append_deterministic_draft(workspace, generated)
