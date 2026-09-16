import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .inquiry_analysis import EvidencePage, InquiryAnalysis, RequirementAssessment
from .materials import DocumentType
from .retrieval import SearchResult


RequirementCategory = Literal["technical", "compliance", "commercial", "logistics"]
ExpertDecision = Literal[
    "pending", "proceed", "needs_information", "do_not_recommend"
]


class ReviewFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    category: RequirementCategory
    source_start: int
    source_end: int
    status: Literal["inquiry_explicit"] = "inquiry_explicit"


class ReviewAmbiguity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_text: str
    possible_interpretations: tuple[str, ...]
    impact: str
    status: Literal["system_hypothesis"] = "system_hypothesis"
    calibration_status: Literal[
        "pending_target_company_technical_review"
    ] = "pending_target_company_technical_review"


class ReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product: str
    source_file: str
    document_type: DocumentType
    page_number: int
    date_revision: str
    jurisdiction: str
    applicable_conditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    status: Literal["private_document_evidence"] = "private_document_evidence"


class RequirementReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: RequirementCategory
    requirement: str
    status: Literal[
        "private_document_evidence",
        "customer_confirmation",
        "expert_judgment_required",
    ]
    evidence: tuple[ReviewEvidence, ...]


class InternalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product: str
    label: Literal["internal_candidate"] = "internal_candidate"
    support_status: Literal["analysis_supported", "related_evidence"]
    support_statement: str
    evidence: tuple[ReviewEvidence, ...]

    @model_validator(mode="after")
    def require_evidence(self) -> "InternalCandidate":
        if not self.evidence:
            raise ValueError("An internal candidate requires private-document evidence")
        return self


class ReviewFollowUp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    question: str
    category: RequirementCategory
    suggested_priority: Literal[
        "before_recommendation",
        "before_quote_or_sample",
        "optional_optimization",
        "pending_expert_review",
    ]
    status: Literal["customer_confirmation"] = "customer_confirmation"
    calibration_status: Literal[
        "pending_target_company_technical_review",
        "user_confirmed_business_boundary",
    ]


class TechnicalReviewCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inquiry: str
    facts: tuple[ReviewFact, ...]
    ambiguities: tuple[ReviewAmbiguity, ...]
    requirement_reviews: tuple[RequirementReview, ...]
    internal_candidates: tuple[InternalCandidate, ...]
    evidence_limitations: tuple[str, ...]
    follow_ups: tuple[ReviewFollowUp, ...]
    expert_decision: Literal["pending"] = "pending"
    target_company_validation_status: Literal[
        "deferred_until_after_demo"
    ] = "deferred_until_after_demo"


class ReviewDecisionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: ExpertDecision
    selected_candidate: str | None
    selected_follow_ups: tuple[str, ...]
    can_generate_external_recommendation: bool
    can_generate_follow_up_draft: bool


class ReviewSessionState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    card: TechnicalReviewCard
    analysis_revision: str
    outcome: ReviewDecisionOutcome


def build_review_card(
    inquiry: str,
    analysis: InquiryAnalysis,
    ranked_evidence: Sequence[SearchResult],
    *,
    available_evidence: Sequence[EvidencePage] | None = None,
) -> TechnicalReviewCard:
    if not inquiry.strip():
        raise ValueError("Inquiry must not be empty")
    conditions_by_identity = _conditions_by_identity(analysis)
    evidence_by_identity = {
        (item.product, item.source_file, item.page_number): _review_evidence(
            item,
            applicable_conditions=conditions_by_identity.get(
                (item.product, item.source_file, item.page_number), ()
            ),
        )
        for item in available_evidence or ranked_evidence
    }
    return TechnicalReviewCard(
        inquiry=inquiry,
        facts=_extract_facts(inquiry),
        ambiguities=_extract_ambiguities(inquiry),
        requirement_reviews=tuple(
            _review_requirement(requirement, evidence_by_identity)
            for requirement in analysis.requirements
        ),
        internal_candidates=_internal_candidates(
            analysis,
            ranked_evidence,
            conditions_by_identity,
            evidence_by_identity,
        ),
        evidence_limitations=_unique_text(
            (*analysis.source_limitations, *analysis.evidence_gaps)
        ),
        follow_ups=_follow_ups(inquiry, analysis.follow_up_questions),
    )


def review_card_matches_analysis(
    card: TechnicalReviewCard,
    analysis: InquiryAnalysis,
) -> bool:
    evidence_by_identity: dict[tuple[str, str, int], ReviewEvidence] = {}
    for evidence in (
        item
        for requirement in card.requirement_reviews
        for item in requirement.evidence
    ):
        identity = (evidence.product, evidence.source_file, evidence.page_number)
        existing = evidence_by_identity.get(identity)
        if existing is not None and existing != evidence:
            return False
        evidence_by_identity[identity] = evidence
    for evidence in (
        item
        for candidate in card.internal_candidates
        for item in candidate.evidence
    ):
        identity = (evidence.product, evidence.source_file, evidence.page_number)
        existing = evidence_by_identity.get(identity)
        if existing is not None and existing != evidence:
            return False
        evidence_by_identity[identity] = evidence

    conditions_by_identity = _conditions_by_identity(analysis)
    if any(
        evidence.applicable_conditions
        != conditions_by_identity.get(identity, ())
        for identity, evidence in evidence_by_identity.items()
    ):
        return False

    expected_requirements = tuple(
        _review_requirement(requirement, evidence_by_identity)
        for requirement in analysis.requirements
    )
    if len(card.requirement_reviews) != len(expected_requirements):
        return False
    for actual, expected in zip(card.requirement_reviews, expected_requirements):
        if (
            actual.category,
            actual.requirement,
            actual.status,
            tuple(_review_evidence_identity(item) for item in actual.evidence),
        ) != (
            expected.category,
            expected.requirement,
            expected.status,
            tuple(_review_evidence_identity(item) for item in expected.evidence),
        ):
            return False

    if card.evidence_limitations != _unique_text(
        (*analysis.source_limitations, *analysis.evidence_gaps)
    ):
        return False
    if card.follow_ups != _follow_ups(card.inquiry, analysis.follow_up_questions):
        return False
    supported_candidates = tuple(
        candidate.product
        for candidate in card.internal_candidates
        if candidate.support_status == "analysis_supported"
    )
    if analysis.recommendation_status == "supported":
        return supported_candidates == (analysis.recommended_product,)
    return not supported_candidates


def _review_evidence_identity(evidence: ReviewEvidence) -> tuple[str, str, int]:
    return evidence.product, evidence.source_file, evidence.page_number


def apply_expert_decision(
    card: TechnicalReviewCard,
    decision: ExpertDecision,
    *,
    selected_candidate: str | None = None,
    selected_follow_up_ids: tuple[str, ...] = (),
) -> ReviewDecisionOutcome:
    if decision != "proceed" and selected_candidate is not None:
        raise ValueError("A candidate may be selected only for a proceed decision")
    if decision != "needs_information" and selected_follow_up_ids:
        raise ValueError(
            "Follow-up questions may be selected only for a needs-information decision"
        )
    if decision == "proceed":
        candidates = {
            candidate.product: candidate
            for candidate in card.internal_candidates
            if candidate.evidence
        }
        if selected_candidate is None or selected_candidate not in candidates:
            raise ValueError("Proceed requires the reviewer to select one evidence-backed internal candidate")
        return ReviewDecisionOutcome(
            decision=decision,
            selected_candidate=selected_candidate,
            selected_follow_ups=(),
            can_generate_external_recommendation=True,
            can_generate_follow_up_draft=False,
        )
    if decision == "needs_information":
        follow_ups = {item.item_id: item.question for item in card.follow_ups}
        unknown = sorted(set(selected_follow_up_ids) - follow_ups.keys())
        if unknown:
            raise ValueError("Unknown follow-up selection: " + ", ".join(unknown))
        selected = tuple(follow_ups[item_id] for item_id in selected_follow_up_ids)
        return ReviewDecisionOutcome(
            decision=decision,
            selected_candidate=None,
            selected_follow_ups=selected,
            can_generate_external_recommendation=False,
            can_generate_follow_up_draft=bool(selected),
        )
    return ReviewDecisionOutcome(
        decision=decision,
        selected_candidate=None,
        selected_follow_ups=(),
        can_generate_external_recommendation=False,
        can_generate_follow_up_draft=False,
    )


def validate_decision_outcome(
    card: TechnicalReviewCard,
    outcome: ReviewDecisionOutcome,
) -> None:
    try:
        if outcome.decision == "proceed":
            expected = apply_expert_decision(
                card,
                "proceed",
                selected_candidate=outcome.selected_candidate,
            )
        elif outcome.decision == "needs_information":
            if len(outcome.selected_follow_ups) != len(
                set(outcome.selected_follow_ups)
            ):
                raise ValueError("Follow-up selections must not contain duplicates")
            item_id_by_question = {item.question: item.item_id for item in card.follow_ups}
            selected_ids = tuple(
                item_id_by_question[question]
                for question in outcome.selected_follow_ups
            )
            expected = apply_expert_decision(
                card,
                "needs_information",
                selected_follow_up_ids=selected_ids,
            )
        else:
            expected = apply_expert_decision(card, outcome.decision)
    except (KeyError, ValueError) as error:
        raise ValueError(
            "Review decision outcome is not authorized by the current review card"
        ) from error
    if outcome != expected:
        raise ValueError(
            "Review decision outcome is not authorized by the current review card"
        )


def start_review_session(
    card: TechnicalReviewCard, *, analysis_revision: str
) -> ReviewSessionState:
    if not analysis_revision.strip():
        raise ValueError("Analysis revision must not be empty")
    return ReviewSessionState(
        card=card,
        analysis_revision=analysis_revision,
        outcome=_pending_outcome(),
    )


def apply_session_decision(
    session: ReviewSessionState,
    decision: ExpertDecision,
    *,
    selected_candidate: str | None = None,
    selected_follow_up_ids: tuple[str, ...] = (),
) -> ReviewSessionState:
    outcome = apply_expert_decision(
        session.card,
        decision,
        selected_candidate=selected_candidate,
        selected_follow_up_ids=selected_follow_up_ids,
    )
    return session.model_copy(update={"outcome": outcome})


def refresh_review_session(
    session: ReviewSessionState,
    card: TechnicalReviewCard,
    *,
    analysis_revision: str,
) -> ReviewSessionState:
    del session
    return start_review_session(card, analysis_revision=analysis_revision)


def _pending_outcome() -> ReviewDecisionOutcome:
    return ReviewDecisionOutcome(
        decision="pending",
        selected_candidate=None,
        selected_follow_ups=(),
        can_generate_external_recommendation=False,
        can_generate_follow_up_draft=False,
    )


def _extract_facts(inquiry: str) -> tuple[ReviewFact, ...]:
    facts: list[ReviewFact] = []
    for match in re.finditer(r"[^.!?。！？;；,，]+", inquiry):
        text = match.group().strip()
        if not text:
            continue
        leading = len(match.group()) - len(match.group().lstrip())
        start = match.start() + leading
        end = start + len(text)
        for category in _categories(text):
            facts.append(
                ReviewFact(
                    text=text,
                    category=category,
                    source_start=start,
                    source_end=end,
                )
            )
    return tuple(facts)


def _categories(text: str) -> tuple[RequirementCategory, ...]:
    normalized = text.casefold()
    patterns: dict[RequirementCategory, tuple[str, ...]] = {
        "technical": (
            r"\b(?:epoxy|resin|coating|adhesive|floor|substrate|cure|curing|dry|temperature|chemical resistance|hdt)\b",
            r"环氧|树脂|涂层|涂料|地坪|基材|固化|干燥|温度|耐化学",
        ),
        "compliance": (
            r"\b(?:certif\w*|compliance|regulat\w*|food[\s-]+contact|fda|rohs|reach)\b",
            r"认证|证书|合规|法规|食品接触",
        ),
        "commercial": (
            r"\b(?:price|pricing|quote|quotation|moq|stock|availability|quantity|payment|metric tons?|tonnes?|tons?|\d+\s*mt)\b",
            r"价格|报价|库存|起订|数量|付款|吨",
        ),
        "logistics": (
            r"\b(?:incoterms?|cif|fob|exw|dap|ddp|cfr|port|freight|shipping|shipment|delivery|delivered|destination)\b",
            r"贸易术语|目的港|目的地|运费|物流|交期|发运|交付",
        ),
    }
    matched = tuple(
        category
        for category, category_patterns in patterns.items()
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in category_patterns)
    )
    return matched or ("technical",)


def _extract_ambiguities(inquiry: str) -> tuple[ReviewAmbiguity, ...]:
    definitions = (
        (
            r"\b(?:dry quickly|fast[\s-]*drying|quick[\s-]*dry)\b|快速干燥|迅速干燥",
            ("dry to touch", "ready to handle", "ready to recoat", "fully cured"),
            "The requested drying state and acceptance time are not defined.",
        ),
        (
            r"\bchemical resistance\b|耐化学品|耐化学性",
            ("exposure chemical", "concentration", "temperature", "duration and frequency"),
            "The exposure and acceptance conditions are not defined.",
        ),
        (
            r"\b(?:ambient|room) temperature\b|常温",
            ("site temperature", "humidity", "required cure-completion state"),
            "The environmental condition and cure endpoint are not defined.",
        ),
        (
            r"\b(?:best|lowest) price\b|最低价格|最优价格",
            ("price under agreed packaging and payment", "price under an agreed Incoterm"),
            "The commercial basis for comparing price is not defined.",
        ),
        (
            r"\bwithin one month\b|一个月内",
            ("dispatch within one month", "arrival within one month"),
            "The delivery milestone is not defined.",
        ),
        (
            r"\bdelivered to\s+(?P<value>[A-Za-z][A-Za-z -]*?)(?=\s+within\b|[,.!?]|$)",
            ("country-level destination", "named port, terminal, city, or premises"),
            "The named delivery point and applicable trade term are not defined.",
        ),
    )
    ambiguities: list[ReviewAmbiguity] = []
    seen: set[tuple[int, int]] = set()
    for pattern, interpretations, impact in definitions:
        for match in re.finditer(pattern, inquiry, flags=re.IGNORECASE):
            original_text = match.groupdict().get("value") or match.group()
            start = match.start("value") if "value" in match.groupdict() else match.start()
            end = match.end("value") if "value" in match.groupdict() else match.end()
            identity = (start, end)
            if identity in seen:
                continue
            seen.add(identity)
            ambiguities.append(
                ReviewAmbiguity(
                    original_text=original_text,
                    possible_interpretations=interpretations,
                    impact=impact,
                )
            )
    return tuple(sorted(ambiguities, key=lambda item: inquiry.find(item.original_text)))


def _review_evidence(
    item: EvidencePage, *, applicable_conditions: tuple[str, ...] = ()
) -> ReviewEvidence:
    text = item.page_text if isinstance(item, SearchResult) and item.page_text else item.text
    normalized = text.casefold()
    limitations: list[str] = []
    if "under product development" in normalized:
        limitations.append("Under Product Development")
    if "for experimental use only" in normalized:
        limitations.append("FOR EXPERIMENTAL USE ONLY")
    return ReviewEvidence(
        product=item.product,
        source_file=item.source_file,
        document_type=item.doc_type,
        page_number=item.page_number,
        date_revision=item.date_revision,
        jurisdiction=item.jurisdiction,
        applicable_conditions=applicable_conditions,
        limitations=tuple(limitations),
    )


def _review_requirement(
    requirement: RequirementAssessment,
    evidence_by_identity: dict[tuple[str, str, int], ReviewEvidence],
) -> RequirementReview:
    statuses = {
        "supported": "private_document_evidence",
        "needs_confirmation": "customer_confirmation",
        "insufficient_evidence": "expert_judgment_required",
    }
    evidence = tuple(
        evidence_by_identity[identity]
        for citation in requirement.evidence
        if (
            identity := (
                citation.product,
                citation.source_file,
                citation.page_number,
            )
        )
        in evidence_by_identity
    )
    status = statuses[requirement.status]
    if requirement.status == "supported" and not evidence:
        status = "expert_judgment_required"
    return RequirementReview(
        category=requirement.category,
        requirement=requirement.requirement,
        status=status,  # type: ignore[arg-type]
        evidence=evidence,
    )


def _internal_candidates(
    analysis: InquiryAnalysis,
    ranked_evidence: Sequence[SearchResult],
    conditions_by_identity: dict[tuple[str, str, int], tuple[str, ...]],
    evidence_by_identity: dict[tuple[str, str, int], ReviewEvidence],
) -> tuple[InternalCandidate, ...]:
    grouped: dict[str, list[ReviewEvidence]] = {}
    for item in ranked_evidence:
        identity = (item.product, item.source_file, item.page_number)
        evidence = evidence_by_identity.get(
            identity,
            _review_evidence(
                item,
                applicable_conditions=conditions_by_identity.get(identity, ()),
            ),
        )
        product_evidence = grouped.setdefault(item.product, [])
        if evidence not in product_evidence:
            product_evidence.append(evidence)
    return tuple(
        InternalCandidate(
            product=product,
            support_status=(
                "analysis_supported"
                if analysis.recommendation_status == "supported"
                and analysis.recommended_product == product
                else "related_evidence"
            ),
            support_statement="Related private-document evidence for internal technical review only.",
            evidence=tuple(evidence),
        )
        for product, evidence in grouped.items()
    )


def _follow_ups(
    inquiry: str, questions: Sequence[str]
) -> tuple[ReviewFollowUp, ...]:
    inquiry_normalized = _normalized_words(inquiry)
    unique = tuple(
        question
        for question in _unique_text(questions)
        if _normalized_words(question) not in inquiry_normalized
    )
    return tuple(
        ReviewFollowUp(
            item_id=f"follow-up-{index}",
            question=question,
            category=_follow_up_category(question),
            suggested_priority=(
                "before_quote_or_sample"
                if _is_business_or_logistics_question(question)
                else "pending_expert_review"
            ),
            calibration_status=(
                "user_confirmed_business_boundary"
                if _is_business_or_logistics_question(question)
                else "pending_target_company_technical_review"
            ),
        )
        for index, question in enumerate(unique, start=1)
    )


def _follow_up_category(question: str) -> RequirementCategory:
    categories = _categories(question)
    for category in ("compliance", "logistics", "commercial", "technical"):
        if category in categories:
            return category  # type: ignore[return-value]
    return "technical"


def _normalized_words(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def _conditions_by_identity(
    analysis: InquiryAnalysis,
) -> dict[tuple[str, str, int], tuple[str, ...]]:
    conditions: dict[tuple[str, str, int], list[str]] = {}
    for parameter in analysis.key_parameters:
        identity = (
            parameter.citation.product,
            parameter.citation.source_file,
            parameter.citation.page_number,
        )
        context = "; ".join(
            value
            for value in (
                f"{parameter.name}: {parameter.value} {parameter.unit}".strip(),
                f"conditions: {parameter.conditions}" if parameter.conditions else "",
                f"test method: {parameter.test_method}" if parameter.test_method else "",
                f"curing agent: {parameter.curing_agent}" if parameter.curing_agent else "",
                f"mix ratio: {parameter.mix_ratio}" if parameter.mix_ratio else "",
                f"cure schedule: {parameter.cure_schedule}" if parameter.cure_schedule else "",
            )
            if value
        )
        conditions.setdefault(identity, []).append(context)
    return {identity: tuple(values) for identity, values in conditions.items()}


def _is_business_or_logistics_question(question: str) -> bool:
    normalized = question.casefold()
    return bool(
        re.search(
            r"\b(?:price|quote|quantity|payment|packaging|stock|moq|delivery|destination|port|incoterm|freight|shipping)\b",
            normalized,
        )
        or any(
            phrase in normalized
            for phrase in ("价格", "报价", "数量", "付款", "包装", "库存", "交期", "目的港", "贸易术语", "运费")
        )
    )


def _unique_text(values: Sequence[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return tuple(unique)
