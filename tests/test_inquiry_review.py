from pathlib import Path

import pytest
from pydantic import ValidationError

from chemical_trade_copilot.inquiry_analysis import (
    InquiryAnalysis,
    KeyParameter,
    RequirementAssessment,
    SourceCitation,
)
from chemical_trade_copilot.pdf_pages import PageRecord
from chemical_trade_copilot.inquiry_review import (
    apply_expert_decision,
    apply_session_decision,
    build_review_card,
    refresh_review_session,
    start_review_session,
    review_card_matches_analysis,
)
from chemical_trade_copilot.retrieval import SearchResult


SOURCE = SourceCitation(
    product="EPON Resin 8280",
    source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
    page_number=1,
)


def _analysis(
    *,
    supported: bool = True,
    questions: tuple[str, ...] = (
        "Which dry state and acceptance time does the customer require?",
        "What destination port and delivery point should be used?",
    ),
) -> InquiryAnalysis:
    return InquiryAnalysis(
        summary_zh="资料提供内部候选依据，仍需技术人员判断。",
        recommendation_status="supported" if supported else "insufficient_evidence",
        recommended_product="EPON Resin 8280" if supported else None,
        recommendation_reasons=("TDS contains related application evidence.",),
        requirements=(
            RequirementAssessment(
                category="technical",
                requirement="Outdoor metal coating and fast drying",
                status="supported" if supported else "insufficient_evidence",
                evidence=(SOURCE,) if supported else (),
            ),
            RequirementAssessment(
                category="logistics",
                requirement="Delivery point",
                status="needs_confirmation",
                evidence=(),
            ),
        ),
        key_parameters=(),
        evidence_gaps=("Dry-state definition requires confirmation.",),
        source_limitations=("The TDS scope does not establish customer-specific suitability.",),
        follow_up_questions=questions,
        next_action=(
            "needs_technical_confirmation"
            if not supported
            else "needs_commercial_input"
        ),
    )


def _ranked_result() -> SearchResult:
    return SearchResult(
        text="High solids coatings application evidence",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file=SOURCE.source_file,
        source_path=Path("C:/materials/EPON/TDS.pdf"),
        page_number=SOURCE.page_number,
        distance=0.1,
        page_text="High solids coatings application evidence",
        date_revision="2016",
        jurisdiction="Technical data sheet · jurisdiction not stated",
    )


def test_review_card_keeps_inquiry_facts_hypotheses_and_evidence_separate() -> None:
    inquiry = (
        "We need an epoxy resin for outdoor metal coatings. "
        "The coating will be cured at 80°C and should dry quickly."
    )

    card = build_review_card(inquiry, _analysis(), [_ranked_result()])

    assert card.expert_decision == "pending"
    assert card.target_company_validation_status == "deferred_until_after_demo"
    assert card.facts
    assert all(fact.text in inquiry for fact in card.facts)
    assert all(fact.status == "inquiry_explicit" for fact in card.facts)
    ambiguity = next(item for item in card.ambiguities if item.original_text == "dry quickly")
    assert ambiguity.status == "system_hypothesis"
    assert ambiguity.calibration_status == "pending_target_company_technical_review"
    candidate = card.internal_candidates[0]
    assert candidate.product == "EPON Resin 8280"
    assert candidate.label == "internal_candidate"
    assert candidate.evidence[0].document_type == "TDS"
    assert candidate.evidence[0].page_number == 1
    assert candidate.evidence[0].date_revision == "2016"
    assert candidate.evidence[0].jurisdiction == (
        "Technical data sheet · jurisdiction not stated"
    )
    assert "final recommendation" not in candidate.support_statement.casefold()
    assert card.evidence_limitations == (
        "The TDS scope does not establish customer-specific suitability.",
        "Dry-state definition requires confirmation.",
    )


def test_follow_ups_come_only_from_current_analysis_and_keep_technical_priority_pending() -> None:
    questions = (
        "Which chemical and concentration will contact the floor?",
        "What destination port should be used?",
    )

    card = build_review_card(
        "Chemical-resistant concrete floor coating; quote delivery to Germany.",
        _analysis(questions=questions),
        [_ranked_result()],
    )

    assert tuple(item.question for item in card.follow_ups) == questions
    assert card.follow_ups[0].suggested_priority == "pending_expert_review"
    assert card.follow_ups[0].calibration_status == (
        "pending_target_company_technical_review"
    )
    assert card.follow_ups[1].suggested_priority == "before_quote_or_sample"


def test_business_logistics_review_does_not_attach_unrelated_technical_evidence() -> None:
    inquiry = (
        "We need 10 metric tons of epoxy resin at your best price, "
        "delivered to Germany within one month."
    )
    analysis = _analysis(
        supported=False,
        questions=(
            "Which named delivery place and Incoterm should be used?",
            "Does one month mean dispatch or arrival?",
        ),
    )

    card = build_review_card(inquiry, analysis, [])

    assert {fact.category for fact in card.facts} >= {"commercial", "logistics"}
    assert card.internal_candidates == ()
    assert any(item.original_text == "best price" for item in card.ambiguities)
    assert any(item.original_text == "within one month" for item in card.ambiguities)
    assert all(item.evidence == () for item in card.requirement_reviews)


def test_expert_decision_gate_requires_manual_candidate_selection_for_recommendation() -> None:
    card = build_review_card(
        "Epoxy resin for outdoor metal coatings.",
        _analysis(),
        [_ranked_result()],
    )

    pending = apply_expert_decision(card, "pending")
    rejected = apply_expert_decision(card, "do_not_recommend")

    assert pending.can_generate_external_recommendation is False
    assert rejected.can_generate_external_recommendation is False
    assert rejected.selected_candidate is None
    with pytest.raises(ValueError, match="select one evidence-backed internal candidate"):
        apply_expert_decision(card, "proceed")

    approved = apply_expert_decision(
        card,
        "proceed",
        selected_candidate="EPON Resin 8280",
    )

    assert approved.can_generate_external_recommendation is True
    assert approved.selected_candidate == "EPON Resin 8280"
    assert approved.can_generate_follow_up_draft is False


def test_needs_information_uses_only_manually_selected_follow_ups() -> None:
    card = build_review_card(
        "Epoxy resin for outdoor metal coatings with fast drying.",
        _analysis(),
        [_ranked_result()],
    )
    selected_id = card.follow_ups[1].item_id

    outcome = apply_expert_decision(
        card,
        "needs_information",
        selected_follow_up_ids=(selected_id,),
    )

    assert outcome.can_generate_external_recommendation is False
    assert outcome.can_generate_follow_up_draft is True
    assert outcome.selected_follow_ups == (card.follow_ups[1].question,)
    with pytest.raises(ValueError, match="Unknown follow-up selection"):
        apply_expert_decision(
            card,
            "needs_information",
            selected_follow_up_ids=("stale-question",),
        )


def test_supported_claim_without_its_current_citation_is_rejected() -> None:
    unrelated = _ranked_result()
    missing_source = SourceCitation(
        product="EPON Resin 8280",
        source_file="TDS - missing-from-current-evidence.pdf",
        page_number=9,
    )
    analysis = _analysis().model_copy(
        update={
            "requirements": (
                RequirementAssessment(
                    category="technical",
                    requirement="Unsupported application claim",
                    status="supported",
                    evidence=(missing_source,),
                ),
            )
        }
    )

    card = build_review_card("Epoxy coating application.", analysis, [unrelated])

    assert card.requirement_reviews[0].status == "expert_judgment_required"
    assert card.requirement_reviews[0].evidence == ()


def test_baer_evidence_exposes_development_and_experimental_use_limits() -> None:
    tds = SearchResult(
        text="BAER XP9500 Under Product Development",
        product="BAER XP9500",
        doc_type="TDS",
        source_file="TDS - ACS BAER XP9500.pdf",
        source_path=Path("C:/materials/BAER/TDS.pdf"),
        page_number=1,
        distance=0.1,
        page_text="BAER XP9500 Under Product Development. Test applications before commercialization.",
        date_revision="Revision 09132018",
        jurisdiction="Technical data sheet · jurisdiction not stated",
    )
    sds = SearchResult(
        text="PRODUCT USE: FOR EXPERIMENTAL USE ONLY",
        product="BAER XP9500",
        doc_type="SDS",
        source_file="SDS - ACS BAER XP9500.pdf",
        source_path=Path("C:/materials/BAER/SDS.pdf"),
        page_number=1,
        distance=0.2,
        page_text="PRODUCT USE: FOR EXPERIMENTAL USE ONLY",
        date_revision="Revised 2018-06-28",
        jurisdiction="United States · English SDS",
    )

    card = build_review_card(
        "Review BAER XP9500 as an internal candidate.",
        _analysis(supported=False, questions=()),
        [tds, sds],
    )

    evidence = card.internal_candidates[0].evidence
    assert any("Under Product Development" in item.limitations for item in evidence)
    assert any("FOR EXPERIMENTAL USE ONLY" in item.limitations for item in evidence)
    assert all(isinstance(item.applicable_conditions, tuple) for item in evidence)


def test_ranked_candidate_uses_matching_full_page_to_disclose_limits() -> None:
    ranked = SearchResult(
        text="Bio-based coating application details",
        product="BAER XP9500",
        doc_type="TDS",
        source_file="TDS - ACS BAER XP9500.pdf",
        source_path=Path("C:/materials/BAER/TDS.pdf"),
        page_number=1,
        distance=0.1,
        date_revision="Revision 09132018",
        jurisdiction="Technical data sheet · jurisdiction not stated",
    )
    full_page = PageRecord(
        text="BAER XP9500 Under Product Development. Bio-based coating application details.",
        product=ranked.product,
        doc_type="TDS",
        source_file=ranked.source_file,
        source_path=ranked.source_path,
        page_number=ranked.page_number,
        date_revision=ranked.date_revision,
        jurisdiction=ranked.jurisdiction,
    )

    card = build_review_card(
        "Review BAER XP9500 as an internal candidate.",
        _analysis(supported=False, questions=()),
        [ranked],
        available_evidence=[full_page],
    )

    assert card.internal_candidates[0].evidence[0].limitations == (
        "Under Product Development",
    )


def test_follow_ups_are_classified_and_do_not_repeat_explicit_answers() -> None:
    inquiry = "Destination port: Hamburg. The floor will contact sulfuric acid."
    analysis = _analysis(
        questions=(
            "Destination port: Hamburg?",
            "Which acid concentration and exposure duration apply?",
            "What payment terms are required?",
        )
    )

    card = build_review_card(inquiry, analysis, [])

    assert tuple(item.question for item in card.follow_ups) == (
        "Which acid concentration and exposure duration apply?",
        "What payment terms are required?",
    )
    assert tuple(item.category for item in card.follow_ups) == (
        "technical",
        "commercial",
    )


def test_refreshing_review_session_invalidates_old_decision_and_selections() -> None:
    first_card = build_review_card(
        "Epoxy resin for outdoor metal coatings.",
        _analysis(),
        [_ranked_result()],
    )
    session = start_review_session(first_card, analysis_revision="analysis-1")
    decided = apply_session_decision(
        session,
        "proceed",
        selected_candidate="EPON Resin 8280",
    )
    second_card = build_review_card(
        "Epoxy resin for a concrete floor.",
        _analysis(questions=("Which chemical exposure applies?",)),
        [_ranked_result()],
    )

    refreshed = refresh_review_session(
        decided,
        second_card,
        analysis_revision="analysis-2",
    )

    assert refreshed.card.inquiry == second_card.inquiry
    assert refreshed.analysis_revision == "analysis-2"
    assert refreshed.outcome.decision == "pending"
    assert refreshed.outcome.selected_candidate is None
    assert refreshed.outcome.selected_follow_ups == ()
    assert refreshed.outcome.can_generate_external_recommendation is False
    assert refreshed.outcome.can_generate_follow_up_draft is False
    assert not hasattr(refreshed, "approved_by")
    assert not hasattr(refreshed, "approved_at")


def test_review_card_cannot_serialize_candidate_as_final_recommendation() -> None:
    card = build_review_card(
        "Epoxy resin for outdoor metal coatings.",
        _analysis(),
        [_ranked_result()],
    )

    serialized = card.model_dump()

    assert serialized["expert_decision"] == "pending"
    assert "recommended_product" not in serialized
    assert "final_recommendation" not in serialized
    assert serialized["internal_candidates"][0]["label"] == "internal_candidate"
    with pytest.raises(ValidationError):
        card.__class__.model_validate({**serialized, "expert_decision": "proceed"})


@pytest.mark.parametrize("change", ["status", "evidence"])
def test_review_card_consistency_rejects_requirement_status_or_evidence_drift(
    change: str,
) -> None:
    analysis = _analysis()
    card = build_review_card(
        "Epoxy coating application.", analysis, [_ranked_result()]
    )
    requirement = card.requirement_reviews[0]
    if change == "status":
        requirement = requirement.model_copy(
            update={"status": "expert_judgment_required"}
        )
    else:
        requirement = requirement.model_copy(update={"evidence": ()})
    drifted = card.model_copy(
        update={
            "requirement_reviews": (requirement, *card.requirement_reviews[1:])
        }
    )

    assert review_card_matches_analysis(drifted, analysis) is False


def test_review_card_consistency_rejects_follow_up_drift() -> None:
    analysis = _analysis()
    card = build_review_card(
        "Epoxy coating application.", analysis, [_ranked_result()]
    )

    drifted = card.model_copy(update={"follow_ups": card.follow_ups[:-1]})

    assert review_card_matches_analysis(drifted, analysis) is False


def test_review_card_consistency_rejects_requirement_citation_drift() -> None:
    analysis = _analysis()
    card = build_review_card(
        "Epoxy coating application.", analysis, [_ranked_result()]
    )
    changed_source = SOURCE.model_copy(update={"page_number": 99})
    changed_requirement = analysis.requirements[0].model_copy(
        update={"evidence": (changed_source,)}
    )
    drifted_analysis = analysis.model_copy(
        update={
            "requirements": (changed_requirement, *analysis.requirements[1:])
        }
    )

    assert review_card_matches_analysis(card, drifted_analysis) is False


def test_review_card_consistency_accepts_normalized_blank_and_duplicate_limits() -> None:
    analysis = _analysis().model_copy(
        update={
            "source_limitations": (
                "  The TDS scope does not establish customer-specific suitability.  ",
                "",
                "The TDS scope does not establish customer-specific suitability.",
            ),
            "evidence_gaps": (
                "Dry-state definition requires confirmation.",
                "  ",
                "Dry-state definition requires confirmation.",
            ),
        }
    )

    card = build_review_card(
        "Epoxy coating application.", analysis, [_ranked_result()]
    )

    assert review_card_matches_analysis(card, analysis) is True


def test_review_card_consistency_accepts_legal_empty_insufficient_output() -> None:
    analysis = _analysis(supported=False, questions=()).model_copy(
        update={"source_limitations": ("", "  "), "evidence_gaps": ()}
    )

    card = build_review_card("Unresolved epoxy request.", analysis, [])

    assert card.internal_candidates == ()
    assert card.follow_ups == ()
    assert card.evidence_limitations == ()
    assert review_card_matches_analysis(card, analysis) is True


def _analysis_with_projected_parameter() -> InquiryAnalysis:
    return _analysis().model_copy(
        update={
            "key_parameters": (
                KeyParameter(
                    name="Heat Deflection Temperature",
                    value="156",
                    unit="°C",
                    conditions="Cured system",
                    test_method="ASTM D648",
                    curing_agent="MPDA",
                    mix_ratio="100 pbw : 14.4 pbw",
                    cure_schedule="2 h/80°C + 2 h/150°C",
                    citation=SOURCE,
                ),
            )
        }
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"value": "155"},
        {"test_method": "Different method", "conditions": "Different condition"},
    ],
)
def test_review_card_consistency_rejects_projected_parameter_detail_drift(
    updates: dict[str, str],
) -> None:
    analysis = _analysis_with_projected_parameter()
    card = build_review_card(
        "Epoxy coating application.", analysis, [_ranked_result()]
    )
    changed_parameter = analysis.key_parameters[0].model_copy(update=updates)
    drifted = analysis.model_copy(update={"key_parameters": (changed_parameter,)})

    assert review_card_matches_analysis(card, drifted) is False


def test_review_card_consistency_rejects_parameter_citation_identity_drift() -> None:
    analysis = _analysis_with_projected_parameter()
    card = build_review_card(
        "Epoxy coating application.", analysis, [_ranked_result()]
    )
    changed_citation = SOURCE.model_copy(update={"page_number": 2})
    changed_parameter = analysis.key_parameters[0].model_copy(
        update={"citation": changed_citation}
    )
    drifted = analysis.model_copy(update={"key_parameters": (changed_parameter,)})

    assert review_card_matches_analysis(card, drifted) is False


def test_review_card_consistency_allows_unprojected_parameter_citation() -> None:
    analysis = _analysis_with_projected_parameter()
    unprojected_citation = SOURCE.model_copy(update={"page_number": 2})
    unprojected_parameter = analysis.key_parameters[0].model_copy(
        update={"citation": unprojected_citation}
    )
    analysis = analysis.model_copy(update={"key_parameters": (unprojected_parameter,)})

    card = build_review_card(
        "Epoxy coating application.",
        analysis,
        [_ranked_result()],
        available_evidence=[_ranked_result()],
    )

    assert card.internal_candidates[0].evidence[0].applicable_conditions == ()
    assert review_card_matches_analysis(card, analysis) is True
