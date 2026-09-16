from pathlib import Path

import pytest

from chemical_trade_copilot.evaluation import (
    GoldenRetrievalCase,
    RetrievalTarget,
    evaluate_retrieval,
    load_golden_cases,
    validate_golden_gate,
)
from chemical_trade_copilot.retrieval import SearchResult


FIXTURE = Path(__file__).parent / "fixtures" / "golden_retrieval_cases.json"


def test_golden_cases_fix_products_files_pages_and_unsupported_cases() -> None:
    cases = load_golden_cases(FIXTURE)

    assert len(cases) == 9
    assert [case.case_id for case in cases] == [
        "epon_high_solids_en",
        "epon_mpda_hdt_en",
        "der_protective_coatings_zh",
        "der_formulated_hdt_zh",
        "unsupported_continuous_service_temperature_zh",
        "baer_xp9500_baked_coatings_en",
        "baer_xp9500_unsupported_continuous_service_temperature_en",
        "baer_product_development_limit_en",
        "baer_experimental_use_limit_en",
    ]
    assert all(case.expected_targets for case in cases[:4])
    assert all(
        target.source_file.startswith("TDS - ")
        and target.page_number in {1, 2, 3}
        for case in cases[:4]
        for target in case.expected_targets
    )
    assert cases[4].expected_targets == ()
    assert cases[4].requires_insufficient_evidence is True
    assert cases[5].expected_targets == (
        RetrievalTarget(
            product="BAER XP9500",
            source_file="TDS - ACS BAER XP9500.pdf",
            page_number=1,
        ),
    )
    assert cases[5].requires_insufficient_evidence is False
    assert cases[6].expected_targets == ()
    assert cases[6].requires_insufficient_evidence is True
    assert cases[7].expected_targets == (
        RetrievalTarget(
            product="BAER XP9500",
            source_file="TDS - ACS BAER XP9500.pdf",
            page_number=1,
        ),
    )
    assert cases[7].document_types == ("TDS",)
    assert cases[8].expected_targets == (
        RetrievalTarget(
            product="BAER XP9500",
            source_file="SDS - ACS BAER XP9500.pdf",
            page_number=1,
        ),
    )
    assert cases[8].document_types == ("SDS",)


class StubRetriever:
    def __init__(self) -> None:
        self.inquiries: list[str] = []
        self.document_type_filters: list[tuple[str, ...] | None] = []

    def query(
        self,
        inquiry: str,
        *,
        limit: int,
        doc_types: tuple[str, ...] | None = None,
    ) -> list[SearchResult]:
        self.inquiries.append(inquiry)
        self.document_type_filters.append(doc_types)
        if inquiry == "case-one":
            return [
                _result("wrong.pdf", 9),
                _result("target-one.pdf", 1),
            ][:limit]
        return [_result("wrong.pdf", 9)][:limit]


def _result(source_file: str, page_number: int) -> SearchResult:
    return SearchResult(
        text="evidence",
        product="Product",
        doc_type="TDS",
        source_file=source_file,
        source_path=Path(f"C:/{source_file}"),
        page_number=page_number,
        distance=0.1,
    )


def test_evaluate_retrieval_reports_rank_and_hit_at_k_for_answerable_cases() -> None:
    retriever = StubRetriever()
    cases = (
        GoldenRetrievalCase(
            case_id="one",
            inquiry="case-one",
            expected_targets=(RetrievalTarget("Product", "target-one.pdf", 1),),
            requires_insufficient_evidence=False,
        ),
        GoldenRetrievalCase(
            case_id="two",
            inquiry="case-two",
            expected_targets=(RetrievalTarget("Product", "target-two.pdf", 2),),
            requires_insufficient_evidence=False,
        ),
        GoldenRetrievalCase(
            case_id="unsupported",
            inquiry="unsupported",
            expected_targets=(),
            requires_insufficient_evidence=True,
        ),
    )

    evaluation = evaluate_retrieval(cases, retriever, k_values=(1, 3, 5))

    assert evaluation.answerable_cases == 2
    assert evaluation.hit_at_k == {1: 0.0, 3: 0.5, 5: 0.5}
    assert [(result.case_id, result.first_target_rank) for result in evaluation.cases] == [
        ("one", 2),
        ("two", None),
    ]


def test_evaluate_retrieval_uses_frozen_planned_query() -> None:
    retriever = StubRetriever()
    case = GoldenRetrievalCase(
        case_id="planned",
        inquiry="technical request plus MOQ and freight",
        expected_targets=(RetrievalTarget("Product", "target-one.pdf", 1),),
        requires_insufficient_evidence=False,
        retrieval_query="case-one",
        document_types=("TDS",),
    )

    evaluation = evaluate_retrieval((case,), retriever, k_values=(3,))

    assert retriever.inquiries == ["case-one"]
    assert retriever.document_type_filters == [("TDS",)]
    assert evaluation.hit_at_k == {3: 1.0}


def test_validate_golden_gate_requires_a_passing_case_for_each_enabled_product() -> None:
    case = GoldenRetrievalCase(
        case_id="planned",
        inquiry="noisy inquiry",
        retrieval_query="case-one",
        expected_targets=(RetrievalTarget("Product", "target-one.pdf", 1),),
        requires_insufficient_evidence=False,
    )

    evaluation = validate_golden_gate(
        (case,), StubRetriever(), enabled_products={"Product"}, maximum_rank=3
    )

    assert evaluation.hit_at_k == {3: 1.0}
    with pytest.raises(ValueError, match="Product B"):
        validate_golden_gate(
            (case,),
            StubRetriever(),
            enabled_products={"Product", "Product B"},
            maximum_rank=3,
        )


def test_validate_golden_gate_rejects_a_target_below_maximum_rank() -> None:
    case = GoldenRetrievalCase(
        case_id="missed",
        inquiry="case-two",
        expected_targets=(RetrievalTarget("Product", "target-two.pdf", 2),),
        requires_insufficient_evidence=False,
    )

    with pytest.raises(ValueError, match="missed"):
        validate_golden_gate(
            (case,), StubRetriever(), enabled_products={"Product"}, maximum_rank=3
        )


def test_validate_golden_gate_does_not_silently_skip_positive_cases() -> None:
    case = GoldenRetrievalCase(
        case_id="frozen-baseline",
        inquiry="case-one",
        expected_targets=(RetrievalTarget("Product", "target-one.pdf", 1),),
        requires_insufficient_evidence=False,
    )

    with pytest.raises(ValueError, match="Product"):
        validate_golden_gate(
            (case,), StubRetriever(), enabled_products=set(), maximum_rank=3
        )
