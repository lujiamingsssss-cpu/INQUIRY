from pathlib import Path

from chemical_trade_copilot.inquiry_analysis import (
    InquiryAnalysis,
    RequirementAssessment,
    SourceCitation,
)
from chemical_trade_copilot.inquiry_review import (
    apply_session_decision,
    build_review_card,
    start_review_session,
)
from chemical_trade_copilot.retrieval import SearchResult
from chemical_trade_copilot.review_workspace import ReviewWorkspace


INQUIRY = "EPON Resin 8280 for an outdoor metal coating with fast drying."
CATALOG_FINGERPRINT = "catalog-epoxies-v1"
SOURCE = SourceCitation(
    product="EPON Resin 8280",
    source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
    page_number=3,
)


def sample_analysis() -> InquiryAnalysis:
    return InquiryAnalysis(
        summary_zh="资料为 EPON Resin 8280 提供内部评估依据。",
        recommendation_status="supported",
        recommended_product="EPON Resin 8280",
        recommendation_reasons=("The approved TDS contains related evidence.",),
        requirements=(
            RequirementAssessment(
                category="technical",
                requirement="Outdoor metal coating and fast drying",
                status="supported",
                evidence=(SOURCE,),
            ),
        ),
        key_parameters=(),
        evidence_gaps=("The required dry state is not defined.",),
        source_limitations=(
            "The TDS does not establish customer-specific suitability.",
        ),
        follow_up_questions=(
            "Which dry state and acceptance time does the customer require?",
            "What destination port and delivery point should be used?",
        ),
        next_action="needs_commercial_input",
    )


def sample_workspace() -> ReviewWorkspace:
    analysis = sample_analysis()
    evidence = SearchResult(
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
    card = build_review_card(INQUIRY, analysis, [evidence])
    session = start_review_session(card, analysis_revision="analysis-epoxies-v1")
    return ReviewWorkspace(
        inquiry=INQUIRY,
        target_market="unknown",
        catalog_fingerprint=CATALOG_FINGERPRINT,
        analysis=analysis,
        session=session,
    )


def workspace_with_decision(
    workspace: ReviewWorkspace,
    decision: str,
) -> ReviewWorkspace:
    follow_up_ids = (
        (workspace.session.card.follow_ups[0].item_id,)
        if decision == "needs_information"
        else ()
    )
    session = apply_session_decision(
        workspace.session,
        decision,  # type: ignore[arg-type]
        selected_candidate="EPON Resin 8280" if decision == "proceed" else None,
        selected_follow_up_ids=follow_up_ids,
    )
    return workspace.model_copy(update={"session": session})


def workspace_with_follow_up_draft(
    workspace: ReviewWorkspace | None = None,
    *,
    version: int = 1,
    language: str = "en",
) -> ReviewWorkspace:
    from chemical_trade_copilot.review_email import (
        FollowUpPresentation,
        classify_follow_up_intent,
        ensure_authorized_draft,
    )

    workspace = workspace or sample_workspace()
    follow_up_id = workspace.session.card.follow_ups[0].item_id
    session = apply_session_decision(
        workspace.session,
        "needs_information",
        selected_follow_up_ids=(follow_up_id,),
    )
    workspace = workspace.model_copy(
        update={"session": session, "email_language": language}
    )
    presentation = (
        FollowUpPresentation(
            analysis_revision=session.analysis_revision,
            target_locale="zh-CN",
            intents={
                item.item_id: classify_follow_up_intent(item.question)
                for item in session.card.follow_ups
                if item.item_id == follow_up_id
            },
        )
        if language == "zh-CN"
        else None
    )
    drafted = ensure_authorized_draft(
        workspace,
        follow_up_presentation=presentation,
    )
    if version == 1:
        return drafted
    draft = drafted.draft_versions[0].model_copy(update={"version": version})
    return ReviewWorkspace.model_validate(
        {
            **drafted.model_dump(),
            "draft_versions": (draft.model_dump(),),
            "active_draft_version": version,
        }
    )
