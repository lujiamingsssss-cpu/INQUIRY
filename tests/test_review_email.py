from typing import get_args

import pytest
from pydantic import ValidationError

from chemical_trade_copilot import review_email
from chemical_trade_copilot.inquiry_review import apply_session_decision
from chemical_trade_copilot.review_email import (
    DraftStyle,
    active_draft,
    ensure_authorized_draft,
    optimize_authorized_draft,
)
from chemical_trade_copilot.review_workspace import (
    ReviewWorkspace,
    edit_active_draft,
    select_active_draft,
)
from chemical_trade_copilot.ui_presenter import build_email_draft
from tests.review_factories import (
    sample_workspace,
    workspace_with_decision,
    workspace_with_follow_up_draft,
)


FollowUpPresentation = getattr(review_email, "FollowUpPresentation", None)
classify_follow_up_intent = getattr(review_email, "classify_follow_up_intent", None)


class FakeJsonClient:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.payload


def test_draft_style_is_strict_and_limited_to_finite_options() -> None:
    assert get_args(DraftStyle.model_fields["tone"].annotation) == (
        "neutral",
        "concise",
        "formal",
    )
    assert get_args(DraftStyle.model_fields["opening"].annotation) == (
        "standard",
        "direct",
    )
    assert get_args(DraftStyle.model_fields["question_format"].annotation) == (
        "bullets",
        "numbered",
        "paragraph",
    )

    with pytest.raises(ValidationError):
        DraftStyle.model_validate(
            {
                "tone": "sales",
                "opening": "standard",
                "question_format": "bullets",
            }
        )
    with pytest.raises(ValidationError):
        DraftStyle.model_validate(
            {
                "tone": "neutral",
                "opening": "standard",
                "question_format": "bullets",
                "body": "Invented customer claim",
            }
        )


def test_optimization_creates_bound_version_and_keeps_original() -> None:
    workspace = workspace_with_follow_up_draft()
    original = workspace.draft_versions[0]
    client = FakeJsonClient(
        '{"tone":"concise","opening":"direct","question_format":"numbered"}'
    )

    optimized = optimize_authorized_draft(
        client,
        workspace,
        "Make it concise and number the questions",
    )

    assert [item.version for item in optimized.draft_versions] == [1, 2]
    assert optimized.draft_versions[0] == original
    assert optimized.active_draft_version == 2
    assert active_draft(optimized) is not None
    assert active_draft(optimized).manually_edited is False  # type: ignore[union-attr]
    assert active_draft(optimized).authorized_decision == "needs_information"  # type: ignore[union-attr]
    assert active_draft(optimized).language == workspace.email_language  # type: ignore[union-attr]
    assert active_draft(optimized).follow_up_ids == original.follow_up_ids  # type: ignore[union-attr]
    assert "1." in active_draft(optimized).body  # type: ignore[union-attr]
    assert ReviewWorkspace.model_validate_json(optimized.model_dump_json()) == optimized


def test_optimization_rejects_identical_generated_draft_without_new_version() -> None:
    workspace = ensure_authorized_draft(
        workspace_with_decision(sample_workspace(), "needs_information")
    )
    before = workspace.model_dump_json()
    client = FakeJsonClient(
        '{"tone":"neutral","opening":"standard","question_format":"bullets"}'
    )

    for _ in range(2):
        with pytest.raises(ValueError, match="does not change the active draft"):
            optimize_authorized_draft(client, workspace, "Keep the current style")

    assert workspace.model_dump_json() == before
    assert len(workspace.draft_versions) == 1


def test_model_only_classifies_style_and_cannot_add_customer_claims() -> None:
    workspace = workspace_with_follow_up_draft()
    selected = workspace.session.outcome.selected_follow_ups[0]
    unselected = workspace.session.card.follow_ups[1].question
    invented = "156°C and guaranteed REACH compliance"
    client = FakeJsonClient(
        '{"tone":"formal","opening":"standard","question_format":"bullets"}'
    )

    optimized = optimize_authorized_draft(client, workspace, invented)
    draft = active_draft(optimized)

    assert draft is not None
    assert selected in draft.body
    assert unselected not in draft.body
    assert "156°C" not in draft.body
    assert "REACH" not in draft.body
    assert client.calls == [(client.calls[0][0], invented)]
    assert "DraftStyle" in client.calls[0][0]
    assert "subject" not in client.calls[0][0].lower()
    assert "body" not in client.calls[0][0].lower()
    assert workspace.inquiry not in client.calls[0][0]


@pytest.mark.parametrize("instruction", ["", "   ", "\n\t"])
def test_optimization_rejects_empty_instruction_without_calling_model(
    instruction: str,
) -> None:
    client = FakeJsonClient(
        '{"tone":"neutral","opening":"standard","question_format":"bullets"}'
    )

    with pytest.raises(ValueError, match="must not be empty"):
        optimize_authorized_draft(
            client,
            workspace_with_follow_up_draft(),
            instruction,
        )

    assert client.calls == []


@pytest.mark.parametrize("decision", ["pending", "do_not_recommend"])
def test_optimization_rejects_unauthorized_decisions_before_model_call(
    decision: str,
) -> None:
    workspace = sample_workspace()
    if decision == "do_not_recommend":
        workspace = workspace_with_decision(workspace, decision)
    client = FakeJsonClient(
        '{"tone":"neutral","opening":"standard","question_format":"bullets"}'
    )

    with pytest.raises(ValueError, match="does not authorize"):
        optimize_authorized_draft(client, workspace, "Shorten it")

    assert client.calls == []


def test_needs_information_rejects_when_no_authorized_open_selection_remains() -> None:
    workspace = workspace_with_follow_up_draft()
    selected_id = workspace.draft_versions[0].follow_up_ids[0]  # type: ignore[index]
    forged_closed = workspace.model_copy(
        update={"resolved_follow_up_ids": (selected_id,), "active_draft_version": None}
    )
    client = FakeJsonClient(
        '{"tone":"neutral","opening":"standard","question_format":"bullets"}'
    )

    with pytest.raises(ValueError):
        optimize_authorized_draft(client, forged_closed, "Shorten it")

    assert client.calls == []


def test_proceed_optimization_reuses_evidence_gated_email_draft() -> None:
    workspace = workspace_with_decision(sample_workspace(), "proceed")
    workspace = ensure_authorized_draft(workspace)
    client = FakeJsonClient(
        '{"tone":"neutral","opening":"direct","question_format":"paragraph"}'
    )

    optimized = optimize_authorized_draft(client, workspace, "Use a direct opening")
    draft = active_draft(optimized)
    evidence_gated = build_email_draft(workspace.analysis)

    assert draft is not None
    assert draft.subject == evidence_gated.subject
    assert draft.body != evidence_gated.body
    assert "Regarding EPON Resin 8280" in draft.body
    assert draft.follow_up_ids is None


def test_invalid_model_payload_cannot_change_workspace() -> None:
    workspace = workspace_with_follow_up_draft()
    client = FakeJsonClient(
        '{"tone":"concise","opening":"direct","question_format":"numbered",'
        '"body":"Buy a new product"}'
    )

    with pytest.raises(ValidationError):
        optimize_authorized_draft(client, workspace, "Improve it")

    assert workspace.active_draft_version == 1
    assert len(workspace.draft_versions) == 1


def test_manual_body_edit_updates_only_current_version_and_marks_it() -> None:
    workspace = workspace_with_follow_up_draft()
    optimized = optimize_authorized_draft(
        FakeJsonClient(
            '{"tone":"concise","opening":"direct","question_format":"numbered"}'
        ),
        workspace,
        "Make it concise",
    )
    before = optimized.draft_versions

    edited = edit_active_draft(optimized, body=active_draft(optimized).body + "\nNote.")  # type: ignore[union-attr]

    assert len(edited.draft_versions) == 2
    assert edited.draft_versions[0] == before[0]
    assert edited.draft_versions[1].version == 2
    assert edited.draft_versions[1].manually_edited is True
    assert edited.active_draft_version == 2
    assert ReviewWorkspace.model_validate_json(edited.model_dump_json()) == edited


def test_old_versions_can_be_selected_without_overwriting_them() -> None:
    workspace = workspace_with_follow_up_draft()
    optimized = optimize_authorized_draft(
        FakeJsonClient(
            '{"tone":"concise","opening":"direct","question_format":"numbered"}'
        ),
        workspace,
        "Make it concise",
    )

    selected = select_active_draft(optimized, 1)

    assert selected.active_draft_version == 1
    assert selected.draft_versions == optimized.draft_versions
    with pytest.raises(ValueError, match="does not exist"):
        select_active_draft(optimized, 99)


def test_email_language_is_independent_and_defaults_to_english() -> None:
    workspace = workspace_with_decision(sample_workspace(), "proceed")
    assert workspace.email_language == "en"

    chinese = workspace.model_copy(update={"email_language": "zh-CN"})
    drafted = ensure_authorized_draft(chinese)

    assert drafted.session.outcome == workspace.session.outcome
    assert active_draft(drafted).language == "zh-CN"  # type: ignore[union-attr]
    assert "尊敬的" in active_draft(drafted).body  # type: ignore[union-attr]


def test_no_public_arbitrary_optimized_subject_body_bypass_exists() -> None:
    assert not hasattr(review_email, "add_optimized_draft")


def test_no_arbitrary_unedited_subject_body_creation_path_remains() -> None:
    from chemical_trade_copilot import streamlit_app

    assert not hasattr(streamlit_app, "_save_active_draft")


def _finite_follow_up_presentation(
    workspace: ReviewWorkspace,
    *,
    intents: dict[str, str] | None = None,
    analysis_revision: str | None = None,
) -> FollowUpPresentation:
    selected = set(workspace.session.outcome.selected_follow_ups)
    selected_items = tuple(
        item
        for item in workspace.session.card.follow_ups
        if item.question in selected
        and item.item_id not in workspace.resolved_follow_up_ids
    )
    return FollowUpPresentation(
        analysis_revision=analysis_revision or workspace.session.analysis_revision,
        target_locale="zh-CN",
        intents=(
            {
                item.item_id: classify_follow_up_intent(item.question)
                for item in selected_items
            }
            if intents is None
            else intents
        ),
    )


def test_chinese_follow_up_uses_exact_translated_selected_open_item() -> None:
    workspace = workspace_with_follow_up_draft().model_copy(
        update={"email_language": "zh-CN", "active_draft_version": None}
    )
    presentation = _finite_follow_up_presentation(workspace)

    drafted = ensure_authorized_draft(
        workspace,
        follow_up_presentation=presentation,
    )
    body = active_draft(drafted).body  # type: ignore[union-attr]

    assert "请确认所需的干燥状态和验收时间。" in body
    assert workspace.session.outcome.selected_follow_ups[0] not in body


@pytest.mark.parametrize("problem", ["missing", "extra", "wrong", "revision"])
def test_chinese_follow_up_presentation_fails_closed_on_binding_errors(
    problem: str,
) -> None:
    workspace = workspace_with_follow_up_draft().model_copy(
        update={"email_language": "zh-CN", "active_draft_version": None}
    )
    follow_up_id = workspace.draft_versions[0].follow_up_ids[0]  # type: ignore[index]
    intents = {
        follow_up_id: classify_follow_up_intent(
            workspace.session.card.follow_ups[0].question
        )
    }
    revision = workspace.session.analysis_revision
    if problem == "missing":
        intents = {}
    elif problem == "extra":
        intents["not-authorized"] = "dry_state_acceptance_time"
    elif problem == "wrong":
        intents[follow_up_id] = "operating_mode"
    else:
        revision = "stale-revision"

    presentation = _finite_follow_up_presentation(
        workspace,
        intents=intents,
        analysis_revision=revision,
    )

    with pytest.raises(ValueError, match="presentation"):
        ensure_authorized_draft(
            workspace,
            follow_up_presentation=presentation,
        )


def test_finite_chinese_technical_request_does_not_copy_freeform_question() -> None:
    workspace = workspace_with_follow_up_draft()
    first = workspace.session.card.follow_ups[0]
    question = "Is 120°C continuous, intermittent, or a short peak?"
    changed_follow_up = first.model_copy(update={"question": question})
    card = workspace.session.card.model_copy(
        update={
            "follow_ups": (changed_follow_up, *workspace.session.card.follow_ups[1:])
        }
    )
    analysis = workspace.analysis.model_copy(
        update={
            "follow_up_questions": (
                question,
                *workspace.analysis.follow_up_questions[1:],
            )
        }
    )
    session = workspace.session.model_copy(update={"card": card})
    session = apply_session_decision(
        session,
        "needs_information",
        selected_follow_up_ids=(changed_follow_up.item_id,),
    )
    workspace = workspace.model_copy(
        update={
            "analysis": analysis,
            "session": session,
            "email_language": "zh-CN",
            "draft_versions": (),
            "active_draft_version": None,
        }
    )
    presentation = FollowUpPresentation(
        analysis_revision=workspace.session.analysis_revision,
        target_locale="zh-CN",
        intents={changed_follow_up.item_id: "operating_mode"},
    )

    drafted = ensure_authorized_draft(
        workspace,
        follow_up_presentation=presentation,
    )
    body = active_draft(drafted).body  # type: ignore[union-attr]

    assert body.count("请确认设备工况是连续、间歇还是短时峰值。") == 1
    assert question not in body
    assert "EPON Resin 8280" not in body
    assert "120°C" not in body


def test_follow_up_presentation_locale_must_match_workspace_language() -> None:
    workspace = workspace_with_follow_up_draft().model_copy(
        update={"email_language": "zh-CN", "active_draft_version": None}
    )
    presentation = _finite_follow_up_presentation(workspace).model_copy(
        update={"target_locale": "en"}
    )

    with pytest.raises(ValueError, match="locale"):
        ensure_authorized_draft(
            workspace,
            follow_up_presentation=presentation,
        )

    english = workspace.model_copy(
        update={"email_language": "en", "active_draft_version": None}
    )
    with pytest.raises(ValueError, match="English draft"):
        ensure_authorized_draft(
            english,
            follow_up_presentation=_finite_follow_up_presentation(workspace),
        )


def test_existing_english_active_draft_still_rejects_forged_presentation() -> None:
    workspace = workspace_with_follow_up_draft()
    presentation = _finite_follow_up_presentation(workspace).model_copy(
        update={"body": "malicious body"}
    )

    with pytest.raises(ValueError, match="unexpected fields"):
        ensure_authorized_draft(
            workspace,
            follow_up_presentation=presentation,
        )


def test_existing_chinese_active_draft_still_validates_presentation() -> None:
    workspace = workspace_with_follow_up_draft().model_copy(
        update={"email_language": "zh-CN", "active_draft_version": None}
    )
    presentation = _finite_follow_up_presentation(workspace)
    drafted = ensure_authorized_draft(
        workspace,
        follow_up_presentation=presentation,
    )
    malformed = presentation.model_copy(update={"analysis_revision": "stale"})

    with pytest.raises(ValueError, match="analysis revision"):
        ensure_authorized_draft(
            drafted,
            follow_up_presentation=malformed,
        )


def test_arbitrary_translated_claim_cannot_enter_deterministic_chinese_follow_up() -> None:
    workspace = sample_workspace()
    selected_ids = tuple(item.item_id for item in workspace.session.card.follow_ups)
    session = apply_session_decision(
        workspace.session,
        "needs_information",
        selected_follow_up_ids=selected_ids,
    )
    workspace = workspace.model_copy(
        update={"session": session, "email_language": "zh-CN"}
    )
    malicious_claim = "保证符合REACH并可商业采用。"
    presentation = FollowUpPresentation(
        analysis_revision=session.analysis_revision,
        target_locale="zh-CN",
        intents={
            item.item_id: classify_follow_up_intent(item.question)
            for item in workspace.session.card.follow_ups
        },
    )

    with pytest.raises(ValidationError):
        FollowUpPresentation.model_validate(
            {
                **presentation.model_dump(),
                "texts": {item_id: malicious_claim for item_id in selected_ids},
            }
        )

    original = ensure_authorized_draft(
        workspace,
        follow_up_presentation=presentation,
    )
    drafted = optimize_authorized_draft(
        FakeJsonClient(
            '{"tone":"neutral","opening":"direct","question_format":"numbered"}'
        ),
        original,
        malicious_claim,
        follow_up_presentation=presentation,
    )
    body = active_draft(drafted).body  # type: ignore[union-attr]

    assert malicious_claim not in body
    assert "请确认所需的干燥状态和验收时间。" in body
    assert "请确认目的港和交付地点。" in body


def test_same_category_distinct_intents_render_distinct_chinese_questions() -> None:
    workspace = sample_workspace()
    questions = (
        "Which dry state and acceptance time does the customer require?",
        "Is 120°C continuous, intermittent, or a short peak?",
    )
    follow_ups = tuple(
        item.model_copy(
            update={
                "question": question,
                "category": "technical",
                "suggested_priority": "pending_expert_review",
                "calibration_status": "pending_target_company_technical_review",
            }
        )
        for item, question in zip(workspace.session.card.follow_ups, questions)
    )
    analysis = workspace.analysis.model_copy(update={"follow_up_questions": questions})
    card = workspace.session.card.model_copy(update={"follow_ups": follow_ups})
    session = workspace.session.model_copy(update={"card": card})
    session = apply_session_decision(
        session,
        "needs_information",
        selected_follow_up_ids=tuple(item.item_id for item in follow_ups),
    )
    workspace = workspace.model_copy(
        update={
            "analysis": analysis,
            "session": session,
            "email_language": "zh-CN",
            "active_draft_version": None,
        }
    )

    drafted = ensure_authorized_draft(
        workspace,
        follow_up_presentation=_finite_follow_up_presentation(workspace),
    )
    body = active_draft(drafted).body  # type: ignore[union-attr]

    assert body.count("请确认所需的干燥状态和验收时间。") == 1
    assert body.count("请确认设备工况是连续、间歇还是短时峰值。") == 1


def test_follow_up_presentation_roundtrip_rejects_model_copy_extra_body() -> None:
    workspace = workspace_with_follow_up_draft().model_copy(
        update={"email_language": "zh-CN", "active_draft_version": None}
    )
    forged = _finite_follow_up_presentation(workspace).model_copy(
        update={"body": "恶意正文"}
    )

    with pytest.raises(ValueError):
        ensure_authorized_draft(workspace, follow_up_presentation=forged)


def test_unknown_chinese_follow_up_intent_fails_closed() -> None:
    workspace = workspace_with_follow_up_draft()
    first = workspace.session.card.follow_ups[0]
    unknown_question = "Please clarify everything about this request."
    changed = first.model_copy(update={"question": unknown_question})
    card = workspace.session.card.model_copy(
        update={"follow_ups": (changed, *workspace.session.card.follow_ups[1:])}
    )
    analysis = workspace.analysis.model_copy(
        update={
            "follow_up_questions": (
                unknown_question,
                *workspace.analysis.follow_up_questions[1:],
            )
        }
    )
    session = workspace.session.model_copy(update={"card": card})
    session = apply_session_decision(
        session,
        "needs_information",
        selected_follow_up_ids=(changed.item_id,),
    )
    workspace = workspace.model_copy(
        update={
            "analysis": analysis,
            "session": session,
            "email_language": "zh-CN",
            "active_draft_version": None,
        }
    )

    with pytest.raises(ValueError, match="intent"):
        ensure_authorized_draft(
            workspace,
            follow_up_presentation=_finite_follow_up_presentation(workspace),
        )


@pytest.mark.parametrize(
    ("question", "expected"),
    (
        ("What is the final application?", "final_application"),
        ("Is 120°C continuous, intermittent, or a short peak?", "operating_mode"),
        (
            "Which acid concentration and exposure duration apply?",
            "exposure_and_acceptance",
        ),
        (
            "Which dry state and acceptance time does the customer require?",
            "dry_state_acceptance_time",
        ),
        ("Which target-market documents are required?", "target_compliance"),
        (
            "Confirm quantity, preferred delivery window, and packaging.",
            "quantity_delivery_packaging",
        ),
        ("Confirm quantity and destination.", "quantity_destination"),
        (
            "What destination port and delivery point should be used?",
            "destination_delivery_point",
        ),
        (
            "Which named delivery place and Incoterm should be used?",
            "delivery_place_incoterm",
        ),
        ("Does three weeks mean ready, shipped, or delivered?", "delivery_timing"),
        (
            "What price basis, stock, packaging, payment, and currency apply?",
            "commercial_terms",
        ),
        ("Which Incoterm, lead time, and freight basis apply?", "shipping_terms"),
    ),
)
def test_follow_up_intent_classifier_covers_fixed_current_questions(
    question: str,
    expected: str,
) -> None:
    assert classify_follow_up_intent(question) == expected


@pytest.mark.parametrize(
    "question",
    (
        "Which packaging color does the customer prefer?",
        "Is the intermittent internet connection acceptable?",
        "请确认客户喜欢哪一种包装颜色？",
    ),
)
def test_follow_up_intent_classifier_rejects_keyword_substring_lookalikes(
    question: str,
) -> None:
    with pytest.raises(ValueError, match="cannot be identified safely"):
        classify_follow_up_intent(question)


def test_follow_up_intent_classifier_allows_only_cosmetic_normalization() -> None:
    assert (
        classify_follow_up_intent(
            "  WHAT destination port and delivery point should be used!!!  "
        )
        == "destination_delivery_point"
    )


def test_destination_and_named_incoterm_uses_dedicated_intent_and_template() -> None:
    question = "What destination port and named Incoterm place should be used?"
    assert classify_follow_up_intent(question) == "destination_incoterm_place"
    workspace = sample_workspace()
    first = workspace.session.card.follow_ups[0]
    changed_follow_up = first.model_copy(
        update={
            "question": question,
            "category": "logistics",
            "suggested_priority": "before_quote_or_sample",
            "calibration_status": "user_confirmed_business_boundary",
        }
    )
    card = workspace.session.card.model_copy(
        update={"follow_ups": (changed_follow_up, *workspace.session.card.follow_ups[1:])}
    )
    analysis = workspace.analysis.model_copy(
        update={
            "follow_up_questions": (
                question,
                *workspace.analysis.follow_up_questions[1:],
            )
        }
    )
    session = workspace.session.model_copy(update={"card": card})
    session = apply_session_decision(
        session,
        "needs_information",
        selected_follow_up_ids=(changed_follow_up.item_id,),
    )
    workspace = workspace.model_copy(
        update={"analysis": analysis, "session": session, "email_language": "zh-CN"}
    )
    presentation = FollowUpPresentation(
        analysis_revision=session.analysis_revision,
        target_locale="zh-CN",
        intents={changed_follow_up.item_id: "destination_incoterm_place"},
    )

    drafted = ensure_authorized_draft(
        workspace,
        follow_up_presentation=presentation,
    )
    body = active_draft(drafted).body  # type: ignore[union-attr]

    assert "请确认目的港和指定贸易术语地点。" in body
    assert "交期" not in body
    assert "运费" not in body


def test_canonical_workspace_validation_precedes_empty_optimization_instruction() -> None:
    workspace = sample_workspace()
    forged_outcome = workspace.session.outcome.model_copy(
        update={
            "decision": "proceed",
            "selected_candidate": "FORGED",
            "can_generate_external_recommendation": True,
        }
    )
    forged = workspace.model_copy(
        update={"session": workspace.session.model_copy(update={"outcome": forged_outcome})}
    )
    client = FakeJsonClient(
        '{"tone":"neutral","opening":"standard","question_format":"paragraph"}'
    )

    with pytest.raises(ValueError, match="decision outcome"):
        optimize_authorized_draft(client, forged, "")

    assert client.calls == []


def _manual_candidate_workspace(*, language: str) -> ReviewWorkspace:
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
    return workspace.model_copy(
        update={"analysis": analysis, "session": session, "email_language": language}
    )


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_supported_proceed_applies_finite_style_without_changing_safety_claims(
    language: str,
) -> None:
    workspace = workspace_with_decision(sample_workspace(), "proceed").model_copy(
        update={"email_language": language}
    )
    original = ensure_authorized_draft(workspace)

    optimized = optimize_authorized_draft(
        FakeJsonClient(
            '{"tone":"concise","opening":"direct","question_format":"paragraph"}'
        ),
        original,
        "Make it direct and concise",
    )

    before = original.draft_versions[-1].body
    after = optimized.draft_versions[-1].body
    assert after != before
    assert "EPON Resin 8280" in after
    if language == "en":
        assert "Stock, MOQ, price, freight, lead time, and regulatory suitability" in after
        assert "Regards," in after
    else:
        assert "库存、起订量、价格、运费、交期和法规适用性仍需另行确认" in after
        assert "谢谢。" in after


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_manual_candidate_proceed_applies_style_and_retains_limitations(
    language: str,
) -> None:
    workspace = _manual_candidate_workspace(language=language)
    original = ensure_authorized_draft(workspace)
    limitation_tokens = tuple(
        limitation
        for evidence in workspace.session.card.internal_candidates[0].evidence
        for limitation in evidence.limitations
    )

    optimized = optimize_authorized_draft(
        FakeJsonClient(
            '{"tone":"formal","opening":"direct","question_format":"paragraph"}'
        ),
        original,
        "Make it direct and formal",
    )
    body = optimized.draft_versions[-1].body

    assert body != original.draft_versions[-1].body
    assert workspace.session.outcome.selected_candidate in body
    for limitation in limitation_tokens:
        assert limitation in body
    if language == "en":
        assert "Kind regards," in body
        assert "validate the product in the intended use before commercial adoption" in body
    else:
        assert "感谢您确认上述信息。" in body
        assert "在商业采用前验证其对预期用途的适用性" in body
