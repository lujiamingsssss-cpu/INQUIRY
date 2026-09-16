from pathlib import Path

from chemical_trade_copilot.inquiry_analysis import (
    InquiryAnalysis,
    RequirementAssessment,
    RetrievalPlan,
    SourceCitation,
)
from chemical_trade_copilot.pdf_pages import PageRecord
from chemical_trade_copilot.retrieval import SearchResult
from chemical_trade_copilot.workflow import analyze_and_review_inquiry, analyze_inquiry
from chemical_trade_copilot.workflow import review_inquiry


class RecordingPlanner:
    def __init__(self) -> None:
        self.inquiries: list[str] = []

    def plan(self, inquiry: str) -> RetrievalPlan:
        self.inquiries.append(inquiry)
        return RetrievalPlan(search_query="epoxy coating", document_types=("TDS",))


class RecordingIndex:
    def __init__(self, ranked: SearchResult, page: PageRecord) -> None:
        self.ranked = ranked
        self.page = page
        self.query_calls: list[tuple[str, int, tuple[str, ...]]] = []
        self.page_calls: list[tuple[str, ...]] = []

    def query(
        self, query: str, *, limit: int, doc_types: tuple[str, ...]
    ) -> list[SearchResult]:
        self.query_calls.append((query, limit, doc_types))
        return [self.ranked]

    def pages(self, *, doc_types: tuple[str, ...]) -> list[PageRecord]:
        self.page_calls.append(doc_types)
        return [self.page]


class RecordingAnalyzer:
    def __init__(self, result: InquiryAnalysis) -> None:
        self.result = result
        self.calls: list[tuple[str, list[SearchResult | PageRecord]]] = []

    def analyze(
        self, inquiry: str, evidence: list[SearchResult | PageRecord]
    ) -> InquiryAnalysis:
        self.calls.append((inquiry, evidence))
        return self.result


def _analysis() -> InquiryAnalysis:
    return InquiryAnalysis(
        summary_zh="当前检索证据不足。",
        recommendation_status="insufficient_evidence",
        recommended_product=None,
        recommendation_reasons=(),
        requirements=(),
        key_parameters=(),
        evidence_gaps=("需要更多资料。",),
        source_limitations=("资料范围有限。",),
        follow_up_questions=("请确认最终用途。",),
        next_action="insufficient_product_evidence",
    )


def test_analyze_inquiry_reuses_planned_retrieval_and_full_selected_corpus() -> None:
    source_path = Path("G:/materials/EPON/TDS.pdf")
    ranked = SearchResult(
        text="matching chunk",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS.pdf",
        source_path=source_path,
        page_number=1,
        distance=0.1,
        page_text="full ranked page",
    )
    corpus_page = PageRecord(
        text="another full page",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS.pdf",
        source_path=source_path,
        page_number=2,
    )
    planner = RecordingPlanner()
    index = RecordingIndex(ranked, corpus_page)
    expected = _analysis()
    analyzer = RecordingAnalyzer(expected)

    result = analyze_inquiry(
        "customer inquiry",
        index=index,
        planner=planner,
        analyzer=analyzer,
        limit=3,
    )

    assert result == expected
    assert planner.inquiries == ["customer inquiry"]
    assert index.query_calls == [("epoxy coating", 3, ("TDS",))]
    assert index.page_calls == [("TDS",)]
    assert analyzer.calls == [("customer inquiry", [ranked, corpus_page])]


def test_review_inquiry_reuses_analysis_pipeline_and_returns_internal_candidates() -> None:
    source_path = Path("G:/materials/EPON/TDS.pdf")
    ranked = SearchResult(
        text="matching chunk",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS.pdf",
        source_path=source_path,
        page_number=1,
        distance=0.1,
        page_text="full ranked page",
    )
    corpus_page = PageRecord(
        text="another full page",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS.pdf",
        source_path=source_path,
        page_number=2,
    )
    planner = RecordingPlanner()
    index = RecordingIndex(ranked, corpus_page)
    analyzer = RecordingAnalyzer(
        InquiryAnalysis(
            summary_zh="Private evidence supports an internal review.",
            recommendation_status="supported",
            recommended_product="EPON Resin 8280",
            recommendation_reasons=("Approved document evidence.",),
            requirements=(
                RequirementAssessment(
                    category="technical",
                    requirement="Review the application evidence.",
                    status="supported",
                    evidence=(
                        SourceCitation(
                            product="EPON Resin 8280",
                            source_file="TDS.pdf",
                            page_number=2,
                        ),
                    ),
                ),
            ),
            key_parameters=(),
            evidence_gaps=(),
            source_limitations=("Technical reviewer judgment remains required.",),
            follow_up_questions=(),
            next_action="needs_technical_confirmation",
        )
    )

    card = review_inquiry(
        "customer inquiry about an epoxy coating",
        index=index,
        planner=planner,
        analyzer=analyzer,
        limit=3,
    )

    assert card.internal_candidates[0].product == "EPON Resin 8280"
    assert card.internal_candidates[0].evidence[0].page_number == 1
    assert card.requirement_reviews[0].evidence[0].page_number == 2
    assert planner.inquiries == ["customer inquiry about an epoxy coating"]
    assert analyzer.calls == [
        ("customer inquiry about an epoxy coating", [ranked, corpus_page])
    ]


def test_analyze_and_review_returns_both_outputs_from_one_pipeline_run() -> None:
    source_path = Path("G:/materials/EPON/TDS.pdf")
    ranked = SearchResult(
        text="matching chunk",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS.pdf",
        source_path=source_path,
        page_number=1,
        distance=0.1,
    )
    corpus_page = PageRecord(
        text="full approved page",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS.pdf",
        source_path=source_path,
        page_number=1,
    )
    planner = RecordingPlanner()
    index = RecordingIndex(ranked, corpus_page)
    expected = _analysis()
    analyzer = RecordingAnalyzer(expected)

    analysis, card = analyze_and_review_inquiry(
        "customer inquiry",
        index=index,
        planner=planner,
        analyzer=analyzer,
        limit=3,
    )

    assert analysis == expected
    assert card.inquiry == "customer inquiry"
    assert planner.inquiries == ["customer inquiry"]
    assert index.query_calls == [("epoxy coating", 3, ("TDS",))]
    assert analyzer.calls == [("customer inquiry", [corpus_page])]
