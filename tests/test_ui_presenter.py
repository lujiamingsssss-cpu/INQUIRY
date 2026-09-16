from chemical_trade_copilot.inquiry_analysis import (
    InquiryAnalysis,
    KeyParameter,
    RequirementAssessment,
    SourceCitation,
)
from chemical_trade_copilot.ui_presenter import (
    build_analysis_view,
    build_email_draft,
)


SOURCE = SourceCitation(
    product="EPON Resin 8280",
    source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
    page_number=3,
)


def _supported_analysis() -> InquiryAnalysis:
    return InquiryAnalysis(
        summary_zh="技术条件有证据，库存和交期仍需确认。",
        recommendation_status="supported",
        recommended_product="EPON Resin 8280",
        recommendation_reasons=("指定固化体系在 TDS 中有完整条件。",),
        requirements=(
            RequirementAssessment(
                category="technical",
                requirement="MPDA 固化体系热变形温度",
                status="supported",
                evidence=(SOURCE,),
            ),
            RequirementAssessment(
                category="commercial",
                requirement="MOQ、库存和价格",
                status="needs_confirmation",
                evidence=(),
            ),
            RequirementAssessment(
                category="logistics",
                requirement="CFR Santos",
                status="needs_confirmation",
                evidence=(),
            ),
        ),
        key_parameters=(
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
        ),
        evidence_gaps=("库存与价格无当前资料。",),
        source_limitations=("TDS 修订于 2016 年。",),
        follow_up_questions=("请确认采购量和目的港。",),
        next_action="needs_commercial_input",
    )


def _insufficient_analysis(*, fail_closed: bool = False) -> InquiryAnalysis:
    reason = (
        "模型输出未通过本地证据校验，未采用其结论。"
        if fail_closed
        else "当前检索证据不足。"
    )
    return InquiryAnalysis(
        summary_zh="当前检索证据不足。",
        recommendation_status="insufficient_evidence",
        recommended_product=None,
        recommendation_reasons=(reason,),
        requirements=(
            RequirementAssessment(
                category="technical",
                requirement="200°C 连续使用和食品接触认证",
                status="insufficient_evidence",
                evidence=(),
            ),
        ),
        key_parameters=(),
        evidence_gaps=(reason,),
        source_limitations=("资料范围有限。",),
        follow_up_questions=("请确认实际工况和目标法规。",),
        next_action="needs_technical_confirmation",
    )


def test_supported_email_is_english_and_does_not_repeat_values_or_claim_attachments() -> None:
    draft = build_email_draft(_supported_analysis())

    assert "EPON Resin 8280" in draft.subject
    assert "EPON Resin 8280" in draft.body
    assert "required quantity" in draft.body
    assert "destination port" in draft.body
    assert "156" not in draft.body
    assert "attached" not in draft.body.casefold()
    assert "stock is confirmed" not in draft.body.casefold()


def test_supported_application_email_does_not_invent_a_cured_system_test() -> None:
    analysis = _supported_analysis().model_copy(
        update={
            "requirements": (
                RequirementAssessment(
                    category="technical",
                    requirement="High solids coatings application",
                    status="supported",
                    evidence=(SOURCE.model_copy(update={"page_number": 1}),),
                ),
            ),
            "key_parameters": (),
            "next_action": "ready_to_reply",
        }
    )

    draft = build_email_draft(analysis)

    assert "technical response" in draft.body
    assert "documented scope" in draft.body
    assert "cured-system" not in draft.body
    assert "test result" not in draft.body


def test_insufficient_email_asks_for_decisive_conditions_without_recommendation() -> None:
    draft = build_email_draft(_insufficient_analysis())

    assert "additional technical information" in draft.subject.casefold()
    assert "final application" in draft.body
    assert "continuous or intermittent" in draft.body
    assert "target country" in draft.body
    assert "recommend" not in draft.body.casefold()


def test_analysis_view_exposes_business_readiness_and_deduplicated_sources() -> None:
    view = build_analysis_view(_supported_analysis())

    assert view.headline == "Technical reply ready; quotation inputs required"
    assert view.technical_status == "Ready to reply"
    assert view.compliance_status == "Not requested"
    assert view.quotation_status == "Inputs required"
    assert view.logistics_status == "Confirmation required"
    assert view.citations == (SOURCE,)
    assert view.fail_closed is False


def test_analysis_view_marks_local_validation_fallback_without_separate_state() -> None:
    view = build_analysis_view(_insufficient_analysis(fail_closed=True))

    assert view.headline == "More evidence is required before recommending a product"
    assert view.fail_closed is True
    assert view.citations == ()


def test_analysis_view_uses_actual_categories_and_next_action() -> None:
    ready = _supported_analysis().model_copy(
        update={
            "requirements": (_supported_analysis().requirements[0],),
            "next_action": "ready_to_reply",
        }
    )

    ready_view = build_analysis_view(ready)
    insufficient_view = build_analysis_view(_insufficient_analysis())

    assert ready_view.headline == "Technical reply ready"
    assert ready_view.compliance_status == "Not requested"
    assert ready_view.quotation_status == "Not requested"
    assert ready_view.logistics_status == "Not requested"
    assert ready_view.next_action == "Prepare the evidence-grounded technical reply"
    assert insufficient_view.open_items == ("Technical scope or operating conditions",)
    assert "What is the final application?" in insufficient_view.customer_questions
    assert all("target country" not in item.casefold() for item in insufficient_view.customer_questions)
