from typing import Protocol

from .inquiry_analysis import (
    EvidencePage,
    InquiryAnalysis,
    RetrievalPlan,
    merge_ranked_with_corpus,
)
from .materials import DocumentType
from .pdf_pages import PageRecord
from .retrieval import SearchResult
from .inquiry_review import TechnicalReviewCard, build_review_card


class RetrievalPlanner(Protocol):
    def plan(self, inquiry: str) -> RetrievalPlan: ...


class EvidenceIndex(Protocol):
    def query(
        self,
        inquiry: str,
        *,
        limit: int,
        doc_types: tuple[DocumentType, ...],
    ) -> list[SearchResult]: ...

    def pages(
        self, *, doc_types: tuple[DocumentType, ...]
    ) -> list[PageRecord]: ...


class InquiryAnalyzer(Protocol):
    def analyze(
        self, inquiry: str, evidence: list[EvidencePage]
    ) -> InquiryAnalysis: ...


def analyze_inquiry(
    inquiry: str,
    *,
    index: EvidenceIndex,
    planner: RetrievalPlanner,
    analyzer: InquiryAnalyzer,
    limit: int = 3,
) -> InquiryAnalysis:
    analysis, _ = analyze_and_review_inquiry(
        inquiry,
        index=index,
        planner=planner,
        analyzer=analyzer,
        limit=limit,
    )
    return analysis


def analyze_and_review_inquiry(
    inquiry: str,
    *,
    index: EvidenceIndex,
    planner: RetrievalPlanner,
    analyzer: InquiryAnalyzer,
    limit: int = 3,
) -> tuple[InquiryAnalysis, TechnicalReviewCard]:
    plan = planner.plan(inquiry)
    ranked = index.query(
        plan.search_query,
        limit=limit,
        doc_types=plan.document_types,
    )
    evidence = merge_ranked_with_corpus(
        ranked, index.pages(doc_types=plan.document_types)
    )
    analysis = analyzer.analyze(inquiry, evidence)
    return analysis, build_review_card(
        inquiry,
        analysis,
        ranked,
        available_evidence=evidence,
    )


def review_inquiry(
    inquiry: str,
    *,
    index: EvidenceIndex,
    planner: RetrievalPlanner,
    analyzer: InquiryAnalyzer,
    limit: int = 3,
) -> TechnicalReviewCard:
    _, card = analyze_and_review_inquiry(
        inquiry,
        index=index,
        planner=planner,
        analyzer=analyzer,
        limit=limit,
    )
    return card
