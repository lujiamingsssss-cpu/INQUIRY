from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class InquiryEvidence:
    """一次检索的全部产物，供分析模型与本地复核卡共用，避免重复检索。"""

    plan: RetrievalPlan
    ranked: tuple[SearchResult, ...]
    evidence: tuple[EvidencePage, ...]


def gather_evidence(
    inquiry: str,
    *,
    index: EvidenceIndex,
    planner: RetrievalPlanner,
    limit: int = 3,
) -> InquiryEvidence:
    """检索规划 → 页级命中 → 合并为该文档类型下的完整证据集合。

    步骤与顺序和引入审阅工作流之前逐字一致。送入分析模型的证据集合保持为
    「命中页 + 该文档类型下的全部物理页」，**不做裁剪**，因此单次分析的
    解析能力不因界面简化而改变。
    """
    return gather_evidence_for_plan(
        planner.plan(inquiry), index=index, limit=limit
    )


def gather_evidence_for_plan(
    plan: RetrievalPlan,
    *,
    index: EvidenceIndex,
    limit: int = 3,
) -> InquiryEvidence:
    """按**已知**检索计划取证据：用于缓存命中时在本地复核证据是否仍然一致（零模型调用）。"""
    ranked = index.query(
        plan.search_query,
        limit=limit,
        doc_types=plan.document_types,
    )
    evidence = merge_ranked_with_corpus(
        ranked, index.pages(doc_types=plan.document_types)
    )
    return InquiryEvidence(
        plan=plan,
        ranked=tuple(ranked),
        evidence=tuple(evidence),
    )


def analyze_inquiry_with_evidence(
    inquiry: str,
    *,
    index: EvidenceIndex,
    planner: RetrievalPlanner,
    analyzer: InquiryAnalyzer,
    limit: int = 3,
) -> tuple[InquiryAnalysis, InquiryEvidence]:
    collected = gather_evidence(
        inquiry, index=index, planner=planner, limit=limit
    )
    analysis = analyzer.analyze(inquiry, list(collected.evidence))
    return analysis, collected


def analyze_inquiry(
    inquiry: str,
    *,
    index: EvidenceIndex,
    planner: RetrievalPlanner,
    analyzer: InquiryAnalyzer,
    limit: int = 3,
) -> InquiryAnalysis:
    analysis, _ = analyze_inquiry_with_evidence(
        inquiry,
        index=index,
        planner=planner,
        analyzer=analyzer,
        limit=limit,
    )
    return analysis
