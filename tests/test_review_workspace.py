import json
from types import SimpleNamespace
from typing import get_args

import pytest
from pydantic import ValidationError

from chemical_trade_copilot.inquiry_review import apply_session_decision
from chemical_trade_copilot.review_email import (
    FollowUpPresentation,
    active_draft,
    ensure_authorized_draft,
)
from chemical_trade_copilot.review_email_generation import render_generated_draft
from chemical_trade_copilot.review_workspace import (
    BACKUP_MAX_BYTES,
    BackupRestoreResult,
    CatalogDocumentRef,
    EmailDraftVersion,
    REVIEW_PAGES,
    ReviewPage,
    ReviewWorkspace,
    TARGET_MARKETS,
    TargetMarket,
    edit_active_draft,
    export_review_backup,
    finalize_workspace,
    import_review_backup,
    record_summary,
    select_active_draft,
    set_current_page,
    set_resolved_follow_up,
)
from chemical_trade_copilot import review_workspace
from tests.review_factories import (
    sample_workspace,
    workspace_with_decision,
    workspace_with_follow_up_draft,
)


def test_workspace_is_the_strict_frozen_canonical_review_state() -> None:
    workspace = sample_workspace()

    assert workspace.schema_version == 1
    assert workspace.current_page == "conclusion"
    assert workspace.resolved_follow_up_ids == ()
    assert workspace.email_language == "en"
    assert workspace.draft_versions == ()
    assert workspace.active_draft_version is None
    assert workspace.completed_at is None
    assert ReviewWorkspace.model_validate_json(workspace.model_dump_json()) == workspace

    with pytest.raises(ValidationError):
        ReviewWorkspace.model_validate({**workspace.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        workspace.current_page = "email"  # type: ignore[misc]


def _catalog_ref(path: str, digest: str) -> CatalogDocumentRef:
    return CatalogDocumentRef(relative_path=path, sha256=digest)


def test_backup_restores_workspace_when_catalog_matches() -> None:
    workspace = workspace_with_follow_up_draft()
    catalog = (_catalog_ref("EPON/TDS.pdf", "a" * 64),)

    payload = export_review_backup(workspace, catalog)
    result = import_review_backup(payload, catalog)

    assert isinstance(result, BackupRestoreResult)
    assert result.workspace == workspace
    assert result.requires_reanalysis is False
    assert result.changed_files == ()


def test_backup_with_changed_document_restores_only_reanalysis_inputs() -> None:
    workspace = workspace_with_follow_up_draft()
    original = (_catalog_ref("EPON/TDS.pdf", "a" * 64),)
    changed = (_catalog_ref("EPON/TDS.pdf", "f" * 64),)
    payload = export_review_backup(workspace, original)

    result = import_review_backup(payload, changed)

    assert result.workspace is None
    assert result.requires_reanalysis is True
    assert result.inquiry == workspace.inquiry
    assert result.target_market == workspace.target_market
    assert result.changed_files == ("EPON/TDS.pdf",)


def test_backup_rejects_oversize_unknown_fields_and_duplicate_catalog_paths() -> None:
    workspace = sample_workspace()
    catalog = (_catalog_ref("EPON/TDS.pdf", "a" * 64),)
    payload = export_review_backup(workspace, catalog)

    with pytest.raises(ValueError, match="size limit"):
        import_review_backup(b"x" * (BACKUP_MAX_BYTES + 1), catalog)

    raw = json.loads(payload)
    raw["unexpected"] = True
    with pytest.raises(ValidationError):
        import_review_backup(json.dumps(raw), catalog)

    duplicate = (
        _catalog_ref("EPON/TDS.pdf", "a" * 64),
        _catalog_ref("EPON/TDS.pdf", "b" * 64),
    )
    with pytest.raises(ValueError, match="duplicate"):
        export_review_backup(workspace, duplicate)


def test_record_summary_uses_live_decision_and_active_email_version() -> None:
    workspace = workspace_with_follow_up_draft(version=2, language="zh-CN")

    summary = record_summary(workspace)

    assert summary.expert_decision == "needs_information"
    assert summary.open_gap_count == 2
    assert summary.email_version == "2 · zh-CN"
    assert summary.analysis_revision == workspace.session.analysis_revision


def test_finalize_rejects_pending_or_missing_authorized_email() -> None:
    with pytest.raises(ValueError, match="expert decision"):
        finalize_workspace(
            sample_workspace(),
            completed_at="2026-07-30T17:00:00+08:00",
        )

    decided = workspace_with_decision(sample_workspace(), "needs_information")
    with pytest.raises(ValueError, match="authorized email"):
        finalize_workspace(
            decided,
            completed_at="2026-07-30T17:00:00+08:00",
        )


def test_finalize_requires_timezone_and_freezes_every_content_mutation() -> None:
    workspace = workspace_with_follow_up_draft()
    with pytest.raises(ValueError, match="timezone"):
        finalize_workspace(workspace, completed_at="2026-07-30T17:00:00")

    completed = finalize_workspace(
        workspace,
        completed_at="2026-07-30T17:00:00+08:00",
    )
    assert completed.completed_at.isoformat() == "2026-07-30T17:00:00+08:00"
    assert completed.current_page == "record"

    item_id = completed.session.card.follow_ups[0].item_id
    mutations = (
        lambda: set_resolved_follow_up(completed, item_id, resolved=True),
        lambda: select_active_draft(completed, completed.active_draft_version or 1),
        lambda: edit_active_draft(completed, body="Changed"),
        lambda: review_workspace.apply_workspace_decision(completed, "save_only"),
        lambda: ensure_authorized_draft(completed),
    )
    for mutate in mutations:
        with pytest.raises(ValueError, match="completed review"):
            mutate()

    assert set_current_page(completed, "print").current_page == "print"


@pytest.mark.parametrize("version", (0, -1))
def test_email_draft_version_must_be_positive(version: int) -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        EmailDraftVersion(
            version=version,
            language="en",
            subject="Manual draft",
            body="Manual body",
            manually_edited=True,
            authorized_decision="proceed",
        )


def test_workspace_accepts_only_stable_target_market_codes() -> None:
    assert TARGET_MARKETS == (
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
    workspace = sample_workspace()

    for target_market in TARGET_MARKETS:
        assert ReviewWorkspace.model_validate(
            {**workspace.model_dump(), "target_market": target_market}
        ).target_market == target_market

    with pytest.raises(ValidationError):
        ReviewWorkspace.model_validate(
            {**workspace.model_dump(), "target_market": "global-unspecified"}
        )


def test_target_market_literal_and_runtime_options_cannot_drift() -> None:
    assert get_args(TargetMarket) == TARGET_MARKETS


def test_review_pages_have_one_canonical_order_and_safe_transition() -> None:
    assert REVIEW_PAGES == (
        "inquiry",
        "conclusion",
        "gaps",
        "evidence",
        "decision",
        "email",
        "print",
        "record",
    )
    workspace = workspace_with_follow_up_draft().model_copy(
        update={"resolved_follow_up_ids": ()}
    )

    changed = set_current_page(workspace, "evidence")

    assert changed is not workspace
    assert changed.current_page == "evidence"
    assert workspace.current_page == "conclusion"
    assert changed.analysis == workspace.analysis
    assert changed.session == workspace.session
    assert changed.resolved_follow_up_ids == workspace.resolved_follow_up_ids
    assert changed.email_language == workspace.email_language
    assert changed.draft_versions == workspace.draft_versions
    assert changed.active_draft_version == workspace.active_draft_version

    with pytest.raises(ValueError, match="Unknown review page"):
        set_current_page(workspace, "missing")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unknown review page"):
        set_current_page(workspace, None)  # type: ignore[arg-type]


def test_review_page_literal_and_runtime_order_cannot_drift() -> None:
    assert get_args(ReviewPage) == REVIEW_PAGES


def test_business_exits_reuse_the_existing_decision_codes() -> None:
    assert getattr(review_workspace, "DECISION_BY_EXIT", None) == {
        "ask_customer": "needs_information",
        "save_only": "do_not_recommend",
        "technical_reply": "proceed",
    }


def test_business_exits_apply_through_the_canonical_workspace() -> None:
    apply_decision = getattr(review_workspace, "apply_workspace_decision", None)
    assert callable(apply_decision)
    workspace = sample_workspace()
    follow_up_id = workspace.session.card.follow_ups[0].item_id

    ask = apply_decision(
        workspace,
        "ask_customer",
        selected_follow_up_ids=(follow_up_id,),
    )
    save = apply_decision(workspace, "save_only")
    technical = apply_decision(
        workspace,
        "technical_reply",
        selected_candidate=workspace.session.card.internal_candidates[0].product,
    )

    assert ask.session.outcome.decision == "needs_information"
    assert save.session.outcome.decision == "do_not_recommend"
    assert technical.session.outcome.decision == "proceed"


def test_ask_customer_exit_requires_an_open_selected_question() -> None:
    workspace = sample_workspace()
    all_ids = tuple(item.item_id for item in workspace.session.card.follow_ups)
    with pytest.raises(ValueError, match="Select at least one open customer question"):
        review_workspace.apply_workspace_decision(workspace, "ask_customer")

    closed = workspace.model_copy(update={"resolved_follow_up_ids": all_ids})

    with pytest.raises(ValueError, match="No open customer questions remain"):
        review_workspace.apply_workspace_decision(
            closed,
            "ask_customer",
            selected_follow_up_ids=(all_ids[0],),
        )

    partly_closed = workspace.model_copy(update={"resolved_follow_up_ids": (all_ids[0],)})
    with pytest.raises(ValueError, match="open customer questions"):
        review_workspace.apply_workspace_decision(
            partly_closed,
            "ask_customer",
            selected_follow_up_ids=(all_ids[0],),
        )


def test_ask_customer_exit_rejects_duplicate_ids_and_successes_roundtrip() -> None:
    workspace = sample_workspace()
    first_id, second_id = (
        item.item_id for item in workspace.session.card.follow_ups
    )

    with pytest.raises(ValueError, match="duplicate"):
        review_workspace.apply_workspace_decision(
            workspace,
            "ask_customer",
            selected_follow_up_ids=(first_id, first_id),
        )
    with pytest.raises(ValueError, match="open customer questions"):
        review_workspace.apply_workspace_decision(
            workspace,
            "ask_customer",
            selected_follow_up_ids=("unknown",),
        )

    reversed_selection = review_workspace.apply_workspace_decision(
        workspace,
        "ask_customer",
        selected_follow_up_ids=(second_id, first_id),
    )

    assert reversed_selection.session.outcome.selected_follow_ups == tuple(
        item.question for item in reversed(workspace.session.card.follow_ups)
    )
    assert (
        ReviewWorkspace.model_validate_json(reversed_selection.model_dump_json())
        == reversed_selection
    )


def test_technical_reply_exit_requires_evidence_backed_internal_candidates() -> None:
    workspace = sample_workspace()
    unsupported_candidate = workspace.session.card.internal_candidates[0].model_copy(
        update={"evidence": ()}
    )
    card = workspace.session.card.model_copy(
        update={"internal_candidates": (unsupported_candidate,)}
    )
    unsupported = workspace.model_copy(
        update={"session": workspace.session.model_copy(update={"card": card})}
    )

    with pytest.raises(
        ValueError, match="No evidence-backed technical reply is available"
    ):
        review_workspace.apply_workspace_decision(
            unsupported,
            "technical_reply",
            selected_candidate=unsupported_candidate.product,
        )

    saved = review_workspace.apply_workspace_decision(unsupported, "save_only")
    assert saved.session.outcome.decision == "do_not_recommend"
    assert saved.session.outcome.can_generate_external_recommendation is False
    assert saved.session.outcome.can_generate_follow_up_draft is False


def test_workspace_rejects_forged_proceed_outcome_outside_card_candidates() -> None:
    workspace = sample_workspace()
    forged_outcome = workspace.session.outcome.model_copy(
        update={
            "decision": "proceed",
            "selected_candidate": "FORGED",
            "selected_follow_ups": (),
            "can_generate_external_recommendation": True,
            "can_generate_follow_up_draft": False,
        }
    )
    payload = {
        **workspace.model_dump(),
        "session": workspace.session.model_copy(
            update={"outcome": forged_outcome}
        ).model_dump(),
    }

    with pytest.raises(ValidationError, match="decision outcome"):
        ReviewWorkspace.model_validate(payload)


def test_workspace_load_fails_closed_for_forged_proceed_outcome(monkeypatch) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = sample_workspace()
    forged_outcome = workspace.session.outcome.model_copy(
        update={
            "decision": "proceed",
            "selected_candidate": "FORGED",
            "selected_follow_ups": (),
            "can_generate_external_recommendation": True,
            "can_generate_follow_up_draft": False,
        }
    )
    forged = workspace.session.model_copy(update={"outcome": forged_outcome})
    state: dict[str, object] = {
        "review_workspace_json": json.dumps(
            {**workspace.model_dump(mode="json"), "session": forged.model_dump(mode="json")}
        )
    }
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    assert streamlit_app._load_workspace() is None
    assert "review_workspace_json" not in state


def test_workspace_rejects_proceed_candidate_without_evidence() -> None:
    workspace = workspace_with_decision(sample_workspace(), "proceed")
    payload = workspace.model_dump()
    payload["session"]["card"]["internal_candidates"][0]["evidence"] = []

    with pytest.raises(ValidationError, match="internal candidate requires"):
        ReviewWorkspace.model_validate(payload)


def test_related_evidence_candidate_remains_a_valid_expert_proceed_choice() -> None:
    workspace = sample_workspace()
    analysis = workspace.analysis.model_copy(
        update={
            "recommendation_status": "insufficient_evidence",
            "recommended_product": None,
            "recommendation_reasons": (),
            "next_action": "insufficient_product_evidence",
        }
    )
    candidate = workspace.session.card.internal_candidates[0].model_copy(
        update={"support_status": "related_evidence"}
    )
    card = workspace.session.card.model_copy(
        update={"internal_candidates": (candidate,)}
    )
    pending = workspace.session.model_copy(update={"card": card})
    related = ReviewWorkspace.model_validate(
        {**workspace.model_dump(), "analysis": analysis, "session": pending}
    )

    authorized = review_workspace.apply_workspace_decision(
        related,
        "technical_reply",
        selected_candidate=candidate.product,
    )

    assert authorized.session.outcome.decision == "proceed"
    assert authorized.session.outcome.can_generate_external_recommendation is True


def test_workspace_rejects_unknown_or_resolved_selected_followups() -> None:
    workspace = sample_workspace()
    forged_outcome = workspace.session.outcome.model_copy(
        update={
            "decision": "needs_information",
            "selected_candidate": None,
            "selected_follow_ups": ("FORGED QUESTION",),
            "can_generate_external_recommendation": False,
            "can_generate_follow_up_draft": True,
        }
    )
    forged_payload = {
        **workspace.model_dump(),
        "session": workspace.session.model_copy(
            update={"outcome": forged_outcome}
        ).model_dump(),
    }
    with pytest.raises(ValidationError, match="decision outcome"):
        ReviewWorkspace.model_validate(forged_payload)

    selected = workspace_with_decision(workspace, "needs_information")
    selected_id = selected.session.card.follow_ups[0].item_id
    with pytest.raises(ValidationError, match="resolved customer question"):
        ReviewWorkspace.model_validate(
            {**selected.model_dump(), "resolved_follow_up_ids": (selected_id,)}
        )


def test_email_draft_version_is_strict_frozen_and_retains_authorization() -> None:
    draft = workspace_with_follow_up_draft().draft_versions[0]

    assert draft == EmailDraftVersion.model_validate_json(draft.model_dump_json())
    assert draft.authorized_decision == "needs_information"
    with pytest.raises(ValidationError):
        EmailDraftVersion.model_validate({**draft.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        draft.body = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("decision", ["pending", "do_not_recommend"])
def test_email_draft_rejects_decisions_that_cannot_authorize_a_draft(
    decision: str,
) -> None:
    draft = workspace_with_follow_up_draft().draft_versions[0]

    with pytest.raises(ValidationError):
        EmailDraftVersion.model_validate(
            {**draft.model_dump(), "authorized_decision": decision}
        )


def test_resolving_follow_up_returns_new_workspace_without_mutating_evidence_state() -> None:
    workspace = sample_workspace()
    item_id = workspace.session.card.follow_ups[0].item_id
    analysis = workspace.analysis
    card = workspace.session.card

    resolved = set_resolved_follow_up(workspace, item_id, resolved=True)

    assert resolved is not workspace
    assert resolved.resolved_follow_up_ids == (item_id,)
    assert workspace.resolved_follow_up_ids == ()
    assert resolved.analysis is analysis
    assert resolved.session.card is card
    assert set_resolved_follow_up(resolved, item_id, resolved=False).resolved_follow_up_ids == ()


def test_resolving_follow_up_rejects_unknown_item_id() -> None:
    with pytest.raises(ValueError, match="Unknown follow-up item"):
        set_resolved_follow_up(sample_workspace(), "missing", resolved=True)


def test_resolving_selected_followup_prunes_it_from_canonical_authorization() -> None:
    workspace = sample_workspace()
    selected_ids = tuple(item.item_id for item in workspace.session.card.follow_ups)
    session = apply_session_decision(
        workspace.session,
        "needs_information",
        selected_follow_up_ids=selected_ids,
    )
    workspace = workspace.model_copy(update={"session": session})

    resolved = set_resolved_follow_up(workspace, selected_ids[0], resolved=True)

    assert resolved.session.outcome.selected_follow_ups == (
        workspace.session.card.follow_ups[1].question,
    )
    assert ReviewWorkspace.model_validate_json(resolved.model_dump_json()) == resolved


def test_resolving_unselected_gap_keeps_matching_manual_draft_active() -> None:
    workspace = workspace_with_follow_up_draft()
    manual = workspace.draft_versions[0].model_copy(
        update={"body": "Manual reviewer wording", "manually_edited": True}
    )
    workspace = workspace.model_copy(update={"draft_versions": (manual,)})
    unselected_id = workspace.session.card.follow_ups[1].item_id

    resolved = set_resolved_follow_up(workspace, unselected_id, resolved=True)

    assert resolved.session.outcome == workspace.session.outcome
    assert resolved.active_draft_version == manual.version
    assert resolved.draft_versions == (manual,)


def test_reopening_unselected_gap_keeps_matching_manual_draft_active() -> None:
    workspace = workspace_with_follow_up_draft()
    manual = workspace.draft_versions[0].model_copy(
        update={"body": "Manual reviewer wording", "manually_edited": True}
    )
    unselected_id = workspace.session.card.follow_ups[1].item_id
    workspace = workspace.model_copy(
        update={
            "resolved_follow_up_ids": (unselected_id,),
            "draft_versions": (manual,),
        }
    )

    reopened = set_resolved_follow_up(workspace, unselected_id, resolved=False)

    assert reopened.session.outcome == workspace.session.outcome
    assert reopened.active_draft_version == manual.version
    assert reopened.draft_versions == (manual,)


def test_resolving_selected_gap_revokes_active_draft_but_keeps_history() -> None:
    workspace = workspace_with_follow_up_draft()
    selected_id = workspace.session.card.follow_ups[0].item_id

    resolved = set_resolved_follow_up(workspace, selected_id, resolved=True)

    assert resolved.session.outcome.selected_follow_ups == ()
    assert resolved.active_draft_version is None
    assert resolved.draft_versions == workspace.draft_versions


def test_resolved_follow_ups_always_follow_the_review_card_order() -> None:
    workspace = sample_workspace()
    first, second = (item.item_id for item in workspace.session.card.follow_ups)

    reverse_selected = set_resolved_follow_up(workspace, second, resolved=True)
    reverse_selected = set_resolved_follow_up(
        reverse_selected, first, resolved=True
    )

    assert reverse_selected.resolved_follow_up_ids == (first, second)


def test_resolved_gap_is_excluded_from_open_questions_in_card_order() -> None:
    workspace = sample_workspace()
    first, second = workspace.session.card.follow_ups

    changed = set_resolved_follow_up(workspace, first.item_id, resolved=True)

    assert review_workspace.open_follow_ups(changed) == (second,)
    assert first.item_id in changed.resolved_follow_up_ids


def test_epoxies_factories_share_one_realistic_workspace_shape() -> None:
    pending = sample_workspace()
    decided = workspace_with_decision(pending, "proceed")
    drafted = workspace_with_follow_up_draft()

    assert pending.analysis.recommended_product == "EPON Resin 8280"
    assert decided.session.outcome.decision == "proceed"
    assert drafted.session.outcome.decision == "needs_information"
    assert drafted.active_draft_version == drafted.draft_versions[0].version


@pytest.mark.parametrize(
    "decision", ["pending", "needs_information", "proceed", "do_not_recommend"]
)
def test_decision_factory_supports_every_existing_review_decision(decision: str) -> None:
    workspace = workspace_with_decision(sample_workspace(), decision)  # type: ignore[arg-type]

    assert workspace.session.outcome.decision == decision


def test_follow_up_draft_factory_accepts_workspace_version_and_language() -> None:
    source = sample_workspace()

    workspace = workspace_with_follow_up_draft(source, version=3, language="zh-CN")

    assert workspace.draft_versions[0].version == 3
    assert workspace.draft_versions[0].language == "zh-CN"
    assert workspace.active_draft_version == 3


def test_streamlit_workspace_save_load_and_one_time_legacy_migration(monkeypatch) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_follow_up_draft()
    state: dict[str, object] = {}
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    streamlit_app._save_workspace(workspace)
    assert tuple(state) == ("review_workspace_json",)
    assert streamlit_app._load_workspace() == workspace

    state.clear()
    state.update(
        {
            "analysis_json": workspace.analysis.model_dump_json(),
            "analysis_catalog_fingerprint": workspace.catalog_fingerprint,
            "review_session_json": workspace.session.model_dump_json(),
            "active_review_inquiry": workspace.inquiry,
            "email_language": "en",
            "review_follow_up_draft_en": "Legacy follow-up body",
        }
    )

    migrated = streamlit_app._load_workspace()

    assert migrated is not None
    assert migrated.inquiry == workspace.inquiry
    assert migrated.draft_versions[0].body == "Legacy follow-up body"
    assert migrated.active_draft_version is None
    assert tuple(state) == ("review_workspace_json",)
    assert streamlit_app._load_workspace() == migrated


def test_loading_canonical_workspace_clears_all_coexisting_legacy_keys(monkeypatch) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = sample_workspace()
    state: dict[str, object] = {
        "review_workspace_json": workspace.model_dump_json(),
        "analysis_json": workspace.analysis.model_dump_json(),
        "review_session_json": workspace.session.model_dump_json(),
        "analysis_catalog_fingerprint": "stale",
        "active_review_inquiry": "stale",
        "email_language": "zh-CN",
        "email_draft_supported_en": "stale draft",
        "review_follow_up_draft_en": "stale follow-up",
        "reviewer_authorized_email_en": "stale reply",
    }
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    loaded = streamlit_app._load_workspace()

    assert loaded == workspace
    assert tuple(state) == ("review_workspace_json",)


def test_email_language_and_draft_updates_write_only_the_canonical_workspace(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_decision(sample_workspace(), "needs_information")
    state: dict[str, object] = {"review_workspace_json": workspace.model_dump_json()}

    class FakeStreamlit:
        session_state = state

        @staticmethod
        def selectbox(*args, **kwargs):
            assert "key" not in kwargs
            return "zh-CN"

    monkeypatch.setattr(streamlit_app, "st", FakeStreamlit())

    localized = streamlit_app._email_language(workspace, "en")
    selected_id = next(
        item.item_id
        for item in localized.session.card.follow_ups
        if item.question in localized.session.outcome.selected_follow_ups
    )
    drafted = ensure_authorized_draft(
        localized,
        follow_up_presentation=FollowUpPresentation(
            analysis_revision=localized.session.analysis_revision,
            target_locale="zh-CN",
            intents={selected_id: "dry_state_acceptance_time"},
        ),
    )
    streamlit_app._save_workspace(drafted)

    assert localized.email_language == "zh-CN"
    assert drafted.active_draft_version == 1
    assert drafted.draft_versions[0].language == "zh-CN"
    assert drafted.draft_versions[0].authorized_decision == "needs_information"
    assert tuple(state) == ("review_workspace_json",)


def _legacy_state(workspace: ReviewWorkspace, **drafts: str) -> dict[str, object]:
    return {
        "analysis_json": workspace.analysis.model_dump_json(),
        "analysis_catalog_fingerprint": workspace.catalog_fingerprint,
        "review_session_json": workspace.session.model_dump_json(),
        "active_review_inquiry": workspace.inquiry,
        "email_language": workspace.email_language,
        **drafts,
    }


def test_legacy_follow_up_migration_uses_decision_and_language_not_key_order(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_decision(sample_workspace(), "needs_information")
    state = _legacy_state(
        workspace,
        email_draft_supported_en="stale supported reply",
        reviewer_authorized_email_en="stale reviewer reply",
        review_follow_up_draft_en="current follow-up reply",
    )
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    migrated = streamlit_app._load_workspace()

    assert migrated is not None
    assert tuple(draft.body for draft in migrated.draft_versions) == (
        "current follow-up reply",
    )
    assert migrated.active_draft_version is None


def test_legacy_proceed_migration_matches_the_current_authorization_path(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    supported = workspace_with_decision(sample_workspace(), "proceed")
    state = _legacy_state(
        supported,
        reviewer_authorized_email_en="wrong path",
        email_draft_supported_en="supported path",
    )
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    migrated = streamlit_app._load_workspace()

    assert migrated is not None
    assert tuple(draft.body for draft in migrated.draft_versions) == (
        "supported path",
    )


def test_legacy_migration_uses_only_the_selected_email_language(monkeypatch) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_decision(sample_workspace(), "needs_information")
    state = _legacy_state(
        workspace.model_copy(update={"email_language": "zh-CN"}),
        review_follow_up_draft_en="English draft",
        **{"review_follow_up_draft_zh-CN": "中文草稿"},
    )
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    migrated = streamlit_app._load_workspace()

    assert migrated is not None
    assert migrated.email_language == "zh-CN"
    assert tuple(draft.body for draft in migrated.draft_versions) == ("中文草稿",)


def test_legacy_migration_fails_closed_when_only_unrelated_drafts_remain(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_decision(sample_workspace(), "needs_information")
    state = _legacy_state(
        workspace,
        email_draft_supported_en="unrelated",
        reviewer_authorized_email_en="also unrelated",
    )
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    migrated = streamlit_app._load_workspace()

    assert migrated is not None
    assert migrated.draft_versions == ()
    assert migrated.active_draft_version is None


def test_legacy_migration_rejects_and_clears_stale_analysis_card_pair(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = sample_workspace()
    insufficient = workspace.analysis.model_copy(
        update={
            "recommendation_status": "insufficient_evidence",
            "recommended_product": None,
            "recommendation_reasons": (),
            "next_action": "insufficient_product_evidence",
        }
    )
    state = _legacy_state(workspace)
    state["analysis_json"] = insufficient.model_dump_json()
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    assert streamlit_app._load_workspace() is None
    assert "review_workspace_json" not in state
    assert "analysis_json" not in state
    assert "review_session_json" not in state


def test_canonical_load_rejects_and_clears_stale_analysis_card_pair(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = sample_workspace()
    insufficient = workspace.analysis.model_copy(
        update={
            "recommendation_status": "insufficient_evidence",
            "recommended_product": None,
            "recommendation_reasons": (),
            "next_action": "insufficient_product_evidence",
        }
    )
    payload = workspace.model_dump(mode="json")
    payload["analysis"] = insufficient.model_dump(mode="json")
    state: dict[str, object] = {"review_workspace_json": json.dumps(payload)}
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    assert streamlit_app._load_workspace() is None
    assert "review_workspace_json" not in state


def test_switching_email_language_restores_latest_matching_manual_draft(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_decision(sample_workspace(), "proceed")
    state: dict[str, object] = {"review_workspace_json": workspace.model_dump_json()}
    choices = iter(("zh-CN", "en"))

    class FakeStreamlit:
        session_state = state

        @staticmethod
        def selectbox(*args, **kwargs):
            return next(choices)

    monkeypatch.setattr(streamlit_app, "st", FakeStreamlit())
    english = ensure_authorized_draft(workspace)
    english = edit_active_draft(english, body="Manual English")
    streamlit_app._save_workspace(english)
    chinese = streamlit_app._email_language(english, "en")
    assert chinese.active_draft_version is None
    chinese = ensure_authorized_draft(chinese)
    chinese = edit_active_draft(chinese, body="中文手工稿")
    streamlit_app._save_workspace(chinese)
    chinese_version = chinese.active_draft_version

    back_to_english = streamlit_app._email_language(chinese, "en")
    assert back_to_english.active_draft_version == english.active_draft_version
    assert back_to_english.active_draft_version != chinese_version
    restored = active_draft(back_to_english)
    assert restored is not None
    rerun = edit_active_draft(back_to_english, body=restored.body)

    assert restored.body == "Manual English"
    assert restored.manually_edited is True
    assert len(rerun.draft_versions) == 2
    assert rerun.active_draft_version == restored.version


def test_reapplying_identical_authorization_keeps_drafts_but_changes_revoke_them(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_follow_up_draft()
    state: dict[str, object] = {"review_workspace_json": workspace.model_dump_json()}
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))
    selected_id = workspace.session.card.follow_ups[0].item_id

    unchanged = streamlit_app._apply_workspace_decision(
        workspace,
        "ask_customer",
        selected_follow_up_ids=(selected_id,),
    )
    changed = streamlit_app._apply_workspace_decision(
        workspace,
        "save_only",
    )

    assert unchanged.draft_versions == workspace.draft_versions
    assert unchanged.active_draft_version == workspace.active_draft_version
    assert changed.draft_versions == ()
    assert changed.active_draft_version is None


def test_draft_save_revalidates_forged_proceed_authorization(monkeypatch) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = sample_workspace()
    forged_outcome = workspace.session.outcome.model_copy(
        update={
            "decision": "proceed",
            "selected_candidate": "FORGED",
            "selected_follow_ups": (),
            "can_generate_external_recommendation": True,
            "can_generate_follow_up_draft": False,
        }
    )
    forged = workspace.model_copy(
        update={
            "session": workspace.session.model_copy(
                update={"outcome": forged_outcome}
            )
        }
    )
    original_json = workspace.model_dump_json()
    state: dict[str, object] = {"review_workspace_json": original_json}
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    with pytest.raises(ValueError, match="decision outcome"):
        ensure_authorized_draft(forged)

    assert state["review_workspace_json"] == original_json


def test_draft_save_rejects_followup_authorization_after_question_is_resolved(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_follow_up_draft()
    selected_id = workspace.session.card.follow_ups[0].item_id
    bypassed = workspace.model_copy(update={"resolved_follow_up_ids": (selected_id,)})
    original_json = workspace.model_dump_json()
    state: dict[str, object] = {"review_workspace_json": original_json}
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    with pytest.raises(ValueError, match="resolved customer question"):
        ensure_authorized_draft(bypassed)

    assert state["review_workspace_json"] == original_json


def test_draft_save_rejects_followup_authorization_outside_current_card(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = sample_workspace()
    forged_outcome = workspace.session.outcome.model_copy(
        update={
            "decision": "needs_information",
            "selected_candidate": None,
            "selected_follow_ups": ("FORGED QUESTION",),
            "can_generate_external_recommendation": False,
            "can_generate_follow_up_draft": True,
        }
    )
    forged = workspace.model_copy(
        update={
            "session": workspace.session.model_copy(
                update={"outcome": forged_outcome}
            )
        }
    )
    original_json = workspace.model_dump_json()
    state: dict[str, object] = {"review_workspace_json": original_json}
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    with pytest.raises(ValueError, match="decision outcome"):
        ensure_authorized_draft(forged)

    assert state["review_workspace_json"] == original_json


def test_workspace_rejects_active_draft_with_wrong_language_or_decision() -> None:
    workspace = workspace_with_follow_up_draft()
    draft = workspace.draft_versions[0]

    with pytest.raises(ValidationError, match="active email draft"):
        ReviewWorkspace.model_validate(
            {**workspace.model_dump(), "email_language": "zh-CN"}
        )
    with pytest.raises(ValidationError, match="active email draft"):
        ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "session": workspace_with_decision(
                    sample_workspace(), "proceed"
                ).session.model_dump(),
                "draft_versions": (
                    draft.model_copy(
                        update={"authorized_decision": "needs_information"}
                    ).model_dump(),
                ),
            }
        )


def test_workspace_rejects_unsigned_or_stale_active_follow_up_draft() -> None:
    workspace = workspace_with_follow_up_draft()
    draft = workspace.draft_versions[0]

    with pytest.raises(ValidationError, match="follow-up binding"):
        ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "draft_versions": (
                    draft.model_copy(update={"follow_up_ids": None}).model_dump(),
                ),
            }
        )
    with pytest.raises(ValidationError, match="follow-up binding"):
        ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "draft_versions": (
                    draft.model_copy(update={"follow_up_ids": ("stale",)}).model_dump(),
                ),
            }
        )


def test_old_canonical_unsigned_follow_up_draft_without_recipe_fails_closed(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_follow_up_draft()
    payload = workspace.model_dump()
    payload["draft_versions"][0].pop("follow_up_ids", None)
    payload["draft_versions"][0].pop("generation_recipe", None)
    state: dict[str, object] = {"review_workspace_json": json.dumps(payload)}
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    loaded = streamlit_app._load_workspace()

    assert loaded is None
    assert state == {}


@pytest.mark.parametrize(
    "payload",
    (
        "[]",
        "null",
        '{"active_draft_version":1,"draft_versions":[1]}',
    ),
)
def test_non_object_canonical_workspace_payload_fails_closed(
    monkeypatch,
    payload: str,
) -> None:
    from chemical_trade_copilot import streamlit_app

    state: dict[str, object] = {
        "review_workspace_json": payload,
        "analysis_json": "stale",
        "review_follow_up_draft_en": "stale",
    }
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    assert streamlit_app._load_workspace() is None
    assert state == {}


def test_old_unsigned_proceed_draft_without_recipe_fails_closed() -> None:
    workspace = workspace_with_decision(sample_workspace(), "proceed")
    draft = EmailDraftVersion(
        version=1,
        language="en",
        subject="Existing reply",
        body="Existing proceed body",
        manually_edited=True,
        authorized_decision="proceed",
    )

    with pytest.raises(ValidationError, match="generated draft provenance"):
        ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "draft_versions": (draft.model_dump(exclude={"follow_up_ids"}),),
                "active_draft_version": 1,
            }
        )


def test_select_rejects_forged_unedited_generated_history() -> None:
    workspace = ensure_authorized_draft(
        workspace_with_decision(sample_workspace(), "needs_information")
    )
    original = active_draft(workspace)
    assert original is not None
    forged = original.model_copy(
        update={
            "version": 2,
            "subject": "Forged generated subject",
            "body": "Forged generated body",
            "manually_edited": False,
        }
    )
    workspace = workspace.model_copy(
        update={"draft_versions": (*workspace.draft_versions, forged)}
    )

    with pytest.raises(ValueError, match="generated draft provenance"):
        select_active_draft(workspace, forged.version)


def test_load_workspace_rejects_forged_unedited_generated_history(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = ensure_authorized_draft(
        workspace_with_decision(sample_workspace(), "needs_information")
    )
    original = active_draft(workspace)
    assert original is not None
    forged = original.model_copy(
        update={
            "version": 2,
            "subject": "Forged generated subject",
            "body": "Forged generated body",
            "manually_edited": False,
        }
    )
    forged_workspace = workspace.model_copy(
        update={
            "draft_versions": (*workspace.draft_versions, forged),
            "active_draft_version": forged.version,
        }
    )
    state: dict[str, object] = {
        "review_workspace_json": forged_workspace.model_dump_json()
    }
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    assert streamlit_app._load_workspace() is None
    assert state == {}


def test_manually_edited_draft_cannot_forge_generated_subject() -> None:
    workspace = ensure_authorized_draft(
        workspace_with_decision(sample_workspace(), "needs_information")
    )
    original = active_draft(workspace)
    assert original is not None
    forged = original.model_copy(
        update={
            "subject": "Guaranteed REACH approval",
            "body": original.body + "\nManual note",
            "manually_edited": True,
        }
    )

    with pytest.raises(ValidationError, match="subject"):
        ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "draft_versions": (forged.model_dump(),),
            }
        )


def test_unchanged_generated_body_cannot_claim_manual_edit() -> None:
    workspace = ensure_authorized_draft(
        workspace_with_decision(sample_workspace(), "needs_information")
    )
    original = active_draft(workspace)
    assert original is not None
    falsely_edited = original.model_copy(update={"manually_edited": True})

    with pytest.raises(ValidationError, match="manual edit state"):
        ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "draft_versions": (falsely_edited.model_dump(),),
            }
        )


def test_editing_body_back_to_generated_content_clears_manual_edit_state() -> None:
    workspace = ensure_authorized_draft(
        workspace_with_decision(sample_workspace(), "needs_information")
    )
    original = active_draft(workspace)
    assert original is not None

    edited = edit_active_draft(workspace, body=original.body + "\nManual note")
    assert active_draft(edited).manually_edited is True  # type: ignore[union-attr]

    restored = edit_active_draft(edited, body=original.body)

    assert active_draft(restored).body == original.body  # type: ignore[union-attr]
    assert active_draft(restored).manually_edited is False  # type: ignore[union-attr]


def test_all_proceed_history_recipes_bind_current_selected_candidate() -> None:
    workspace = sample_workspace()
    original_candidate = workspace.session.card.internal_candidates[0]
    other_candidate = original_candidate.model_copy(
        update={
            "product": "Other Candidate",
            "support_status": "related_evidence",
        }
    )
    card = workspace.session.card.model_copy(
        update={
            "internal_candidates": (
                original_candidate,
                other_candidate,
            )
        }
    )
    session = workspace.session.model_copy(update={"card": card})
    session = apply_session_decision(
        session,
        "proceed",
        selected_candidate=original_candidate.product,
    )
    workspace = workspace.model_copy(update={"session": session})
    workspace = ensure_authorized_draft(workspace)
    original = active_draft(workspace)
    assert original is not None and original.generation_recipe is not None
    forged_recipe = original.generation_recipe.model_copy(
        update={
            "kind": "reviewer_candidate",
            "selected_candidate": other_candidate.product,
        }
    )
    rendered = render_generated_draft(workspace.analysis, card, forged_recipe)
    forged = original.model_copy(
        update={
            "version": 2,
            "subject": rendered.subject,
            "body": rendered.body,
            "generation_recipe": forged_recipe,
        }
    )

    with pytest.raises(ValidationError, match="selected candidate"):
        ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "draft_versions": (
                    original.model_dump(),
                    forged.model_dump(),
                ),
            }
        )


def test_supported_analysis_cannot_use_reviewer_candidate_recipe_kind() -> None:
    workspace = ensure_authorized_draft(
        workspace_with_decision(sample_workspace(), "proceed")
    )
    original = active_draft(workspace)
    assert original is not None and original.generation_recipe is not None
    forged_recipe = original.generation_recipe.model_copy(
        update={"kind": "reviewer_candidate"}
    )
    forged = original.model_copy(update={"generation_recipe": forged_recipe})

    with pytest.raises(ValidationError, match="recipe kind"):
        ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "draft_versions": (forged.model_dump(),),
            }
        )


def test_unsupported_analysis_cannot_use_supported_recipe_kind() -> None:
    workspace = sample_workspace()
    analysis = workspace.analysis.model_copy(
        update={
            "recommendation_status": "insufficient_evidence",
            "recommended_product": None,
            "recommendation_reasons": (),
            "next_action": "insufficient_product_evidence",
        }
    )
    limitation = workspace.analysis.source_limitations[0]
    evidence = workspace.session.card.internal_candidates[0].evidence[0].model_copy(
        update={"limitations": (limitation,)}
    )
    candidates = tuple(
        candidate.model_copy(
            update={"support_status": "related_evidence", "evidence": (evidence,)}
        )
        for candidate in workspace.session.card.internal_candidates
    )
    requirements = tuple(
        requirement.model_copy(update={"evidence": (evidence,)})
        for requirement in workspace.session.card.requirement_reviews
    )
    card = workspace.session.card.model_copy(
        update={
            "internal_candidates": candidates,
            "requirement_reviews": requirements,
        }
    )
    session = workspace.session.model_copy(update={"card": card})
    session = apply_session_decision(
        session,
        "proceed",
        selected_candidate=candidates[0].product,
    )
    workspace = ensure_authorized_draft(
        workspace.model_copy(update={"analysis": analysis, "session": session})
    )
    original = active_draft(workspace)
    assert original is not None and original.generation_recipe is not None
    forged_recipe = original.generation_recipe.model_copy(update={"kind": "supported"})
    forged = original.model_copy(update={"generation_recipe": forged_recipe})

    with pytest.raises(ValidationError, match="provenance"):
        ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "draft_versions": (forged.model_dump(),),
            }
        )


def test_draft_creation_rejects_mismatched_follow_up_binding(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    workspace = workspace_with_follow_up_draft()
    stale = workspace.draft_versions[0].model_copy(
        update={"follow_up_ids": ("stale",)}
    )
    workspace = workspace.model_copy(update={"draft_versions": (stale,)})
    state: dict[str, object] = {"review_workspace_json": workspace.model_dump_json()}
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))

    with pytest.raises(ValueError, match="follow-up binding"):
        ensure_authorized_draft(workspace)

    assert state["review_workspace_json"] == workspace.model_dump_json()


def test_active_draft_strictly_uses_the_workspace_pointer() -> None:
    workspace = workspace_with_follow_up_draft()
    first = workspace.draft_versions[0]
    latest = first.model_copy(
        update={"version": 2, "body": "Latest body", "manually_edited": True}
    )
    workspace = ReviewWorkspace.model_validate(
        {
            **workspace.model_dump(),
            "draft_versions": (first.model_dump(), latest.model_dump()),
            "active_draft_version": 1,
        }
    )
    assert active_draft(workspace) == first
