from pathlib import Path

from chemical_trade_copilot.inquiry_analysis import (
    InquiryAnalysis,
    RetrievalPlan,
)
from chemical_trade_copilot.pdf_pages import PageRecord
from chemical_trade_copilot.retrieval import SearchResult
from chemical_trade_copilot.workflow import (
    analyze_inquiry,
    analyze_inquiry_with_evidence,
    gather_evidence,
)


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


def _fixtures() -> tuple[SearchResult, PageRecord]:
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
    return ranked, corpus_page


def test_analyze_inquiry_reuses_planned_retrieval_and_full_selected_corpus() -> None:
    ranked, corpus_page = _fixtures()
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


def test_gather_evidence_exposes_ranked_and_corpus_without_extra_retrieval() -> None:
    ranked, corpus_page = _fixtures()
    planner = RecordingPlanner()
    index = RecordingIndex(ranked, corpus_page)

    collected = gather_evidence(
        "customer inquiry", index=index, planner=planner, limit=3
    )

    assert collected.plan.search_query == "epoxy coating"
    assert collected.plan.document_types == ("TDS",)
    assert collected.ranked == (ranked,)
    assert collected.evidence == (ranked, corpus_page)
    assert index.query_calls == [("epoxy coating", 3, ("TDS",))]
    assert index.page_calls == [("TDS",)]


def test_analyze_with_evidence_uses_one_retrieval_for_analysis_and_review() -> None:
    """复核卡与分析必须共用同一次检索，既避免重复计算，也避免两者证据不一致。"""
    ranked, corpus_page = _fixtures()
    planner = RecordingPlanner()
    index = RecordingIndex(ranked, corpus_page)
    expected = _analysis()
    analyzer = RecordingAnalyzer(expected)

    analysis, collected = analyze_inquiry_with_evidence(
        "customer inquiry",
        index=index,
        planner=planner,
        analyzer=analyzer,
        limit=3,
    )

    assert analysis == expected
    assert analyzer.calls[0][1] == [ranked, corpus_page]
    assert collected.evidence == tuple(analyzer.calls[0][1])
    assert len(index.query_calls) == 1
    assert len(index.page_calls) == 1
