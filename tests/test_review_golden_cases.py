import json
from pathlib import Path

from chemical_trade_copilot.inquiry_analysis import InquiryAnalysis, RequirementAssessment
from chemical_trade_copilot.evaluation import (
    load_golden_review_cases,
    validate_review_output_case,
)
from chemical_trade_copilot.inquiry_review import build_review_card
from chemical_trade_copilot.retrieval import SearchResult


FIXTURE = Path(__file__).parent / "fixtures" / "golden_review_output_cases.json"


EXPECTED_CASE_IDS = [
    "outdoor_metal_80c_fast_dry",
    "concrete_floor_ambient_chemical_resistance",
    "germany_best_price_one_month_delivery",
    "baer_development_and_experimental_limits",
    "unsupported_200c_food_contact_lifetime",
]


def _load_cases() -> list[dict[str, object]]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload


def test_review_golden_cases_define_inputs_required_and_forbidden_outputs() -> None:
    cases = _load_cases()

    assert [case["id"] for case in cases] == EXPECTED_CASE_IDS
    for case in cases:
        assert isinstance(case["inquiry"], str) and case["inquiry"].strip()
        assert case["case_type"] == "review_output"
        assert case["required_outputs"]
        assert case["forbidden_outputs"]
        assert case["expert_decision"] == "pending"
        assert case["external_recommendation_allowed"] is False


def test_professional_assertions_remain_pending_target_company_calibration() -> None:
    cases = _load_cases()
    professional_kinds = {
        "product_applicability",
        "curing_agent_or_ratio",
        "application_process",
        "performance_boundary",
        "chemical_resistance",
        "follow_up_priority",
        "external_recommendation_permission",
    }

    assertions = [
        assertion
        for case in cases
        for assertion in case["pending_expert_assertions"]
    ]
    assert assertions
    assert all(assertion["kind"] in professional_kinds for assertion in assertions)
    assert all(
        assertion["calibration_status"]
        == "pending_target_company_technical_review"
        for assertion in assertions
    )
    assert all(case["confirmed_expert_assertions"] == [] for case in cases)


def test_public_sources_are_proxy_evidence_not_company_confirmation() -> None:
    cases = _load_cases()
    allowed_authorities = {
        "government_guidance",
        "manufacturer_guidance",
        "manufacturer_tds",
        "manufacturer_sds",
        "trade_rules_authority",
        "public_marketplace_unverified",
    }
    allowed_roles = {
        "inquiry_pattern",
        "ambiguity_basis",
        "evidence_limitation",
        "business_logistics_boundary",
        "regulatory_boundary",
    }

    for case in cases:
        assert (
            case["calibration_basis"]
            == "public_source_proxy_pending_target_company_validation"
        )
        assert case["target_company_validation_status"] == "deferred_until_after_demo"
        assert case["public_proxy_sources"]
        for source in case["public_proxy_sources"]:
            assert source["url"].startswith("https://")
            assert source["authority"] in allowed_authorities
            assert source["source_role"] in allowed_roles
            assert isinstance(source["supports"], str) and source["supports"].strip()


def test_unverified_marketplace_examples_support_only_inquiry_wording() -> None:
    cases = _load_cases()
    marketplace_sources = [
        source
        for case in cases
        for source in case["public_proxy_sources"]
        if source["authority"] == "public_marketplace_unverified"
    ]

    assert marketplace_sources
    assert all(source["source_role"] == "inquiry_pattern" for source in marketplace_sources)
    assert all(source["may_confirm_professional_assertions"] is False for source in marketplace_sources)


def test_business_logistics_case_is_review_only_and_forbids_document_inference() -> None:
    cases = {case["id"]: case for case in _load_cases()}
    germany = cases["germany_best_price_one_month_delivery"]

    assert germany["retrieval_case_ids"] == []
    assert {
        fact["category"] for fact in germany["expected_explicit_facts"]
    } == {"commercial", "logistics"}
    assert "attach_unrelated_tds_or_sds_evidence" in germany["forbidden_outputs"]
    assert "infer_price_stock_terms_lead_time_or_freight_from_tds_sds" in germany[
        "forbidden_outputs"
    ]


def test_review_cases_link_only_to_explicit_retrieval_cases() -> None:
    cases = _load_cases()
    retrieval_payload = json.loads(
        (
            FIXTURE.parent / "golden_retrieval_cases.json"
        ).read_text(encoding="utf-8")
    )
    retrieval_ids = {case["id"] for case in retrieval_payload}

    linked_ids = {
        retrieval_id
        for case in cases
        for retrieval_id in case["retrieval_case_ids"]
    }
    assert linked_ids <= retrieval_ids
    assert linked_ids == {
        "baer_product_development_limit_en",
        "baer_experimental_use_limit_en",
        "baer_xp9500_unsupported_continuous_service_temperature_en",
        "unsupported_continuous_service_temperature_zh",
    }


def test_review_projection_preserves_golden_fact_and_ambiguity_source_phrases() -> None:
    analysis = InquiryAnalysis(
        summary_zh="No product conclusion.",
        recommendation_status="insufficient_evidence",
        recommended_product=None,
        recommendation_reasons=("No product conclusion.",),
        requirements=(),
        key_parameters=(),
        evidence_gaps=(),
        source_limitations=(),
        follow_up_questions=(),
        next_action="needs_technical_confirmation",
    )

    for case in _load_cases():
        inquiry = case["inquiry"]
        card = build_review_card(inquiry, analysis, [])
        for expected in case["expected_explicit_facts"]:
            assert any(
                expected["text"] in fact.text
                and expected["category"] == fact.category
                and inquiry[fact.source_start : fact.source_end] == fact.text
                for fact in card.facts
            ), (case["id"], expected)
        assert {
            ambiguity.original_text for ambiguity in card.ambiguities
        } >= {
            expected["original_phrase"]
            for expected in case["expected_ambiguities"]
        }


def test_typed_review_cases_validate_real_review_card_outputs() -> None:
    cases = load_golden_review_cases(FIXTURE)

    for case in cases:
        analysis, ranked = _executable_review_inputs(case.case_id)
        card = build_review_card(case.inquiry, analysis, ranked)
        validate_review_output_case(case, card)


def test_germany_review_output_rejects_unrelated_technical_evidence() -> None:
    case = next(
        case
        for case in load_golden_review_cases(FIXTURE)
        if case.case_id == "germany_best_price_one_month_delivery"
    )
    analysis = InquiryAnalysis(
        summary_zh="Commercial and logistics review only.",
        recommendation_status="insufficient_evidence",
        recommended_product=None,
        recommendation_reasons=(),
        requirements=(),
        key_parameters=(),
        evidence_gaps=(),
        source_limitations=(),
        follow_up_questions=(),
        next_action="needs_commercial_input",
    )
    unrelated = SearchResult(
        text="unrelated TDS",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS.pdf",
        source_path=Path("C:/materials/TDS.pdf"),
        page_number=1,
        distance=0.1,
    )
    card = build_review_card(case.inquiry, analysis, [unrelated])

    try:
        validate_review_output_case(case, card)
    except ValueError as error:
        assert "unrelated technical evidence" in str(error)
    else:
        raise AssertionError("Germany review output accepted unrelated TDS evidence")


def _executable_review_inputs(
    case_id: str,
) -> tuple[InquiryAnalysis, list[SearchResult]]:
    requirements: tuple[RequirementAssessment, ...] = ()
    gaps: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    ranked: list[SearchResult] = []
    next_action = "needs_technical_confirmation"
    if case_id == "concrete_floor_ambient_chemical_resistance":
        gaps = ("Chemical exposure and acceptance conditions remain unconfirmed.",)
    elif case_id == "germany_best_price_one_month_delivery":
        requirements = (
            RequirementAssessment(
                category="commercial",
                requirement="Price and quantity terms",
                status="needs_confirmation",
                evidence=(),
            ),
            RequirementAssessment(
                category="logistics",
                requirement="Destination and delivery terms",
                status="needs_confirmation",
                evidence=(),
            ),
        )
        questions = (
            "What price basis, stock, packaging, payment, and currency apply?",
            "Which Incoterm, lead time, and freight basis apply?",
        )
        next_action = "needs_commercial_input"
    elif case_id == "baer_development_and_experimental_limits":
        ranked = [
            SearchResult(
                text="Under Product Development",
                product="BAER XP9500",
                doc_type="TDS",
                source_file="TDS - ACS BAER XP9500.pdf",
                source_path=Path("C:/materials/BAER/TDS.pdf"),
                page_number=1,
                distance=0.1,
                page_text="Under Product Development",
                date_revision="Revision 09132018",
                jurisdiction="Technical data sheet · jurisdiction not stated",
            ),
            SearchResult(
                text="FOR EXPERIMENTAL USE ONLY",
                product="BAER XP9500",
                doc_type="SDS",
                source_file="SDS - ACS BAER XP9500.pdf",
                source_path=Path("C:/materials/BAER/SDS.pdf"),
                page_number=1,
                distance=0.2,
                page_text="FOR EXPERIMENTAL USE ONLY",
                date_revision="Revised 2018-06-28",
                jurisdiction="United States · English SDS",
            ),
        ]
    elif case_id == "unsupported_200c_food_contact_lifetime":
        requirements = (
            RequirementAssessment(
                category="technical",
                requirement="Continuous service at 200°C",
                status="insufficient_evidence",
                evidence=(),
            ),
            RequirementAssessment(
                category="compliance",
                requirement="Food-contact certification",
                status="insufficient_evidence",
                evidence=(),
            ),
            RequirementAssessment(
                category="technical",
                requirement="Long-term service life",
                status="insufficient_evidence",
                evidence=(),
            ),
        )
        gaps = (
            "Continuous-service evidence is missing.",
            "Food-contact authorization evidence is missing.",
            "Long-term service-life evidence is missing.",
        )
    return (
        InquiryAnalysis(
            summary_zh="No external product conclusion.",
            recommendation_status="insufficient_evidence",
            recommended_product=None,
            recommendation_reasons=("No external product conclusion.",),
            requirements=requirements,
            key_parameters=(),
            evidence_gaps=gaps,
            source_limitations=(),
            follow_up_questions=questions,
            next_action=next_action,
        ),
        ranked,
    )
