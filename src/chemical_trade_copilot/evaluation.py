import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from .materials import DocumentType
from .inquiry_review import TechnicalReviewCard
from .retrieval import SearchResult


@dataclass(frozen=True, slots=True)
class RetrievalTarget:
    product: str
    source_file: str
    page_number: int


@dataclass(frozen=True, slots=True)
class GoldenRetrievalCase:
    case_id: str
    inquiry: str
    expected_targets: tuple[RetrievalTarget, ...]
    requires_insufficient_evidence: bool
    retrieval_query: str | None = None
    document_types: tuple[DocumentType, ...] | None = None


class Retriever(Protocol):
    def query(
        self,
        inquiry: str,
        *,
        limit: int,
        doc_types: tuple[DocumentType, ...] | None = None,
    ) -> list[SearchResult]: ...


@dataclass(frozen=True, slots=True)
class CaseRetrievalResult:
    case_id: str
    first_target_rank: int | None


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    answerable_cases: int
    hit_at_k: dict[int, float]
    cases: tuple[CaseRetrievalResult, ...]


@dataclass(frozen=True, slots=True)
class ReviewFactTarget:
    text: str
    category: str


@dataclass(frozen=True, slots=True)
class GoldenReviewOutputCase:
    case_id: str
    inquiry: str
    expected_facts: tuple[ReviewFactTarget, ...]
    expected_ambiguities: tuple[str, ...]
    must_outputs: tuple[str, ...]
    forbidden_outputs: tuple[str, ...]
    retrieval_case_ids: tuple[str, ...]
    confirmed_expert_assertions: tuple[str, ...]
    pending_expert_assertions: tuple[str, ...]


def load_golden_cases(path: Path) -> tuple[GoldenRetrievalCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Golden retrieval cases must be a JSON list")

    cases: list[GoldenRetrievalCase] = []
    for raw_case in payload:
        targets = tuple(
            RetrievalTarget(
                product=str(target["product"]),
                source_file=str(target["source_file"]),
                page_number=int(target["page_number"]),
            )
            for target in raw_case["expected_targets"]
        )
        requires_insufficient_evidence = bool(
            raw_case["requires_insufficient_evidence"]
        )
        if requires_insufficient_evidence == bool(targets):
            raise ValueError(
                "A case must have either expected targets or an insufficient-evidence "
                "expectation"
            )
        cases.append(
            GoldenRetrievalCase(
                case_id=str(raw_case["id"]),
                inquiry=str(raw_case["inquiry"]),
                expected_targets=targets,
                requires_insufficient_evidence=requires_insufficient_evidence,
                retrieval_query=(
                    str(raw_case["retrieval_query"])
                    if raw_case.get("retrieval_query")
                    else None
                ),
                document_types=_load_document_types(raw_case.get("document_types")),
            )
        )
    return tuple(cases)


def load_golden_review_cases(path: Path) -> tuple[GoldenReviewOutputCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Golden review-output cases must be a JSON list")

    cases: list[GoldenReviewOutputCase] = []
    for raw_case in payload:
        if raw_case.get("case_type") != "review_output":
            raise ValueError("Golden review-output case has an invalid case_type")
        if raw_case.get("expert_decision") != "pending":
            raise ValueError("Golden review-output cases must start pending")
        if raw_case.get("external_recommendation_allowed") is not False:
            raise ValueError("Golden review-output cases cannot pre-authorize a recommendation")
        confirmed = raw_case.get("confirmed_expert_assertions")
        if not isinstance(confirmed, list):
            raise ValueError("confirmed_expert_assertions must be a JSON list")
        pending = raw_case.get("pending_expert_assertions")
        if not isinstance(pending, list):
            raise ValueError("pending_expert_assertions must be a JSON list")
        if any(
            assertion.get("calibration_status")
            != "confirmed_by_target_company_technical_reviewer"
            for assertion in confirmed
        ):
            raise ValueError("Confirmed assertions require target-company reviewer metadata")
        if any(
            assertion.get("calibration_status")
            != "pending_target_company_technical_review"
            for assertion in pending
        ):
            raise ValueError("Pending assertions must remain outside the fixed expert gate")
        must_outputs = raw_case.get("required_outputs")
        forbidden_outputs = raw_case.get("forbidden_outputs")
        if not isinstance(must_outputs, list) or not must_outputs:
            raise ValueError("A review-output case requires must-output expectations")
        if not isinstance(forbidden_outputs, list) or not forbidden_outputs:
            raise ValueError("A review-output case requires forbidden-output expectations")
        cases.append(
            GoldenReviewOutputCase(
                case_id=str(raw_case["id"]),
                inquiry=str(raw_case["inquiry"]),
                expected_facts=tuple(
                    ReviewFactTarget(
                        text=str(fact["text"]), category=str(fact["category"])
                    )
                    for fact in raw_case["expected_explicit_facts"]
                ),
                expected_ambiguities=tuple(
                    str(item["original_phrase"])
                    for item in raw_case["expected_ambiguities"]
                ),
                must_outputs=tuple(map(str, must_outputs)),
                forbidden_outputs=tuple(map(str, forbidden_outputs)),
                retrieval_case_ids=tuple(map(str, raw_case["retrieval_case_ids"])),
                confirmed_expert_assertions=tuple(
                    str(item["proposal"]) for item in confirmed
                ),
                pending_expert_assertions=tuple(str(item["proposal"]) for item in pending),
            )
        )
    return tuple(cases)


def validate_review_output_case(
    case: GoldenReviewOutputCase, card: TechnicalReviewCard
) -> None:
    if card.inquiry != case.inquiry:
        raise ValueError(f"Review output inquiry mismatch for {case.case_id}")
    for expected in case.expected_facts:
        if not any(
            expected.text in fact.text and expected.category == fact.category
            for fact in card.facts
        ):
            raise ValueError(
                f"Review output missed explicit fact for {case.case_id}: {expected.text}"
            )
    actual_ambiguities = {item.original_text for item in card.ambiguities}
    missing_ambiguities = set(case.expected_ambiguities) - actual_ambiguities
    if missing_ambiguities:
        raise ValueError(
            f"Review output missed ambiguities for {case.case_id}: "
            + ", ".join(sorted(missing_ambiguities))
        )
    if card.expert_decision != "pending":
        raise ValueError("Review output must leave the expert decision pending")
    serialized = card.model_dump()
    forbidden_fields = {
        "recommended_product",
        "final_recommendation",
        "external_recommendation",
    }
    if forbidden_fields & serialized.keys():
        raise ValueError("Internal review output serialized an external recommendation")
    if any(candidate.label != "internal_candidate" or not candidate.evidence for candidate in card.internal_candidates):
        raise ValueError("Internal candidates must remain evidence-backed and internally labeled")
    if "attach_unrelated_tds_or_sds_evidence" in case.forbidden_outputs and (
        card.internal_candidates
        or any(review.evidence for review in card.requirement_reviews)
    ):
        raise ValueError("Review output attached unrelated technical evidence")
    for behavior in case.must_outputs:
        _validate_required_review_behavior(behavior, card)


def _validate_required_review_behavior(
    behavior: str, card: TechnicalReviewCard
) -> None:
    if behavior == "separate_explicit_facts_from_system_hypotheses":
        valid = all(fact.status == "inquiry_explicit" for fact in card.facts) and all(
            item.status == "system_hypothesis" for item in card.ambiguities
        )
    elif behavior in {
        "keep_final_judgment_with_technical_reviewer",
        "block_external_recommendation",
        "keep_internal_candidate_separate_from_external_recommendation",
    }:
        valid = card.expert_decision == "pending" and all(
            item.label == "internal_candidate" for item in card.internal_candidates
        )
    elif behavior == "show_only_evidence_backed_internal_candidates_if_retrieval_finds_relevant_material":
        valid = all(item.evidence for item in card.internal_candidates)
    elif behavior == "identify_missing_evidence_without_selecting_a_product_for_the_reviewer":
        valid = bool(card.evidence_limitations) and card.expert_decision == "pending"
    elif behavior == "classify_price_and_quantity_as_commercial":
        valid = any(fact.category == "commercial" for fact in card.facts)
    elif behavior == "classify_destination_and_delivery_window_as_logistics":
        valid = any(fact.category == "logistics" for fact in card.facts)
    elif behavior == "state_that_business_staff_must_confirm_price_stock_packaging_payment_currency_terms_lead_time_and_freight":
        required_terms = {
            "price",
            "stock",
            "packaging",
            "payment",
            "currency",
            "incoterm",
            "lead time",
            "freight",
        }
        follow_up_text = " ".join(item.question.casefold() for item in card.follow_ups)
        valid = all(term in follow_up_text for term in required_terms)
    elif behavior == "state_that_tds_sds_do_not_answer_price_or_delivery_commitments":
        valid = not card.internal_candidates and not any(
            review.evidence
            for review in card.requirement_reviews
            if review.category in {"commercial", "logistics"}
        )
    elif behavior == "cite_tds_page_1_for_under_product_development":
        valid = _has_limited_evidence(card, "TDS", 1, "Under Product Development")
    elif behavior == "cite_sds_page_1_for_experimental_use_only":
        valid = _has_limited_evidence(card, "SDS", 1, "FOR EXPERIMENTAL USE ONLY")
    elif behavior == "show_document_date_jurisdiction_and_applicable_limitations":
        evidence = [
            item
            for candidate in card.internal_candidates
            for item in candidate.evidence
        ]
        valid = bool(evidence) and all(
            item.date_revision != "not_recorded"
            and item.jurisdiction != "not_recorded"
            for item in evidence
        ) and any(item.limitations for item in evidence)
    elif behavior == "separate_technical_compliance_and_lifetime_evidence_gaps":
        categories = {review.category for review in card.requirement_reviews}
        valid = {"technical", "compliance"} <= categories and len(card.evidence_limitations) >= 3
    elif behavior == "state_that_current_evidence_does_not_support_the_requested_claims":
        valid = bool(card.requirement_reviews) and all(
            review.status != "private_document_evidence"
            for review in card.requirement_reviews
        )
    else:
        raise ValueError(f"Unknown review must-output behavior: {behavior}")
    if not valid:
        raise ValueError(f"Review output did not satisfy must-output behavior: {behavior}")


def _has_limited_evidence(
    card: TechnicalReviewCard,
    document_type: str,
    page_number: int,
    limitation: str,
) -> bool:
    return any(
        evidence.document_type == document_type
        and evidence.page_number == page_number
        and limitation in evidence.limitations
        for candidate in card.internal_candidates
        for evidence in candidate.evidence
    )


def evaluate_retrieval(
    cases: Sequence[GoldenRetrievalCase],
    retriever: Retriever,
    *,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> RetrievalEvaluation:
    if not k_values or any(k < 1 for k in k_values):
        raise ValueError("k values must be positive integers")

    answerable = [case for case in cases if case.expected_targets]
    case_results: list[CaseRetrievalResult] = []
    for case in answerable:
        results = retriever.query(
            case.retrieval_query or case.inquiry,
            limit=max(k_values),
            doc_types=case.document_types,
        )
        rank = next(
            (
                position
                for position, result in enumerate(results, start=1)
                if _matches_any_target(result, case.expected_targets)
            ),
            None,
        )
        case_results.append(CaseRetrievalResult(case.case_id, rank))

    denominator = len(answerable)
    hit_at_k = {
        k: (
            sum(
                result.first_target_rank is not None and result.first_target_rank <= k
                for result in case_results
            )
            / denominator
            if denominator
            else 0.0
        )
        for k in k_values
    }
    return RetrievalEvaluation(
        answerable_cases=denominator,
        hit_at_k=hit_at_k,
        cases=tuple(case_results),
    )


def validate_golden_gate(
    cases: Sequence[GoldenRetrievalCase],
    retriever: Retriever,
    *,
    enabled_products: set[str],
    maximum_rank: int = 3,
) -> RetrievalEvaluation:
    applicable = tuple(case for case in cases if case.expected_targets)
    target_products = {
        target.product for case in applicable for target in case.expected_targets
    }
    disabled_targets = sorted(target_products - enabled_products)
    if disabled_targets:
        raise ValueError(
            "Positive golden target products are not enabled: "
            + ", ".join(disabled_targets)
        )
    covered_products = {
        target.product for case in applicable for target in case.expected_targets
    }
    missing = sorted(enabled_products - covered_products)
    if missing:
        raise ValueError(
            "Enabled products without a positive golden retrieval case: "
            + ", ".join(missing)
        )
    evaluation = evaluate_retrieval(
        applicable,
        retriever,
        k_values=(maximum_rank,),
    )
    failures = [
        result.case_id
        for result in evaluation.cases
        if result.first_target_rank is None or result.first_target_rank > maximum_rank
    ]
    if failures:
        raise ValueError(
            f"Golden retrieval cases missed within top {maximum_rank}: "
            + ", ".join(failures)
        )
    return evaluation


def _matches_any_target(
    result: SearchResult, targets: tuple[RetrievalTarget, ...]
) -> bool:
    return any(
        result.product == target.product
        and result.source_file == target.source_file
        and result.page_number == target.page_number
        for target in targets
    )


def _load_document_types(raw: object) -> tuple[DocumentType, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise ValueError("document_types must be a non-empty JSON list")
    values = tuple(str(value).upper() for value in raw)
    if any(value not in {"TDS", "SDS"} for value in values):
        raise ValueError("document_types may contain only TDS or SDS")
    return cast(tuple[DocumentType, ...], values)
