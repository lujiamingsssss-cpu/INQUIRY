from dataclasses import dataclass

from .inquiry_analysis import InquiryAnalysis, SourceCitation


@dataclass(frozen=True, slots=True)
class EmailDraft:
    subject: str
    body: str


@dataclass(frozen=True, slots=True)
class AnalysisView:
    headline: str
    technical_status: str
    compliance_status: str
    quotation_status: str
    logistics_status: str
    citations: tuple[SourceCitation, ...]
    fail_closed: bool
    next_action: str
    open_items: tuple[str, ...]
    customer_questions: tuple[str, ...]


def build_email_draft(analysis: InquiryAnalysis) -> EmailDraft:
    if analysis.recommendation_status == "supported":
        product = analysis.recommended_product
        if product is None:
            raise ValueError("A supported analysis requires a product")
        has_condition_bound_test = any(
            parameter.curing_agent
            and parameter.mix_ratio
            and parameter.cure_schedule
            and parameter.test_method
            for parameter in analysis.key_parameters
        )
        evidence_sentence = (
            "the specified cured-system test result is supported under the "
            "documented formulation, curing, and test conditions."
            if has_condition_bound_test
            else "the approved technical documents contain evidence supporting a "
            "technical response for this product within the documented scope."
        )
        return EmailDraft(
            subject=f"Technical follow-up — {product}",
            body=(
                "Dear [Customer name],\n\n"
                f"Thank you for your inquiry regarding {product}. Based on the "
                f"technical documents currently available, {evidence_sentence}\n\n"
                "To prepare an accurate commercial response, please confirm your "
                "required quantity, preferred delivery window, destination port, "
                "preferred Incoterm, packaging requirement, final application, and "
                "any target-country certification requirements.\n\n"
                "Stock, MOQ, price, freight, lead time, and regulatory suitability "
                "remain subject to separate confirmation.\n\n"
                "Best regards,\n[Name]"
            ),
        )
    return EmailDraft(
        subject="Additional technical information required",
        body=(
            "Dear [Customer name],\n\n"
            "Thank you for your inquiry. The currently approved technical documents "
            "do not provide enough evidence to confirm a suitable product for the "
            "requested conditions.\n\n"
            "Please confirm the final application, target country and applicable "
            "regulatory standard, whether the operating condition is continuous or "
            "intermittent, the exposure medium, and the required service duration.\n\n"
            "We will review the request again after the relevant technical or supplier "
            "documentation is available.\n\n"
            "Best regards,\n[Name]"
        ),
    )


def build_analysis_view(analysis: InquiryAnalysis) -> AnalysisView:
    citations = _unique_citations(analysis)
    fail_closed = _is_fail_closed(analysis)
    categories = {
        category: tuple(
            item for item in analysis.requirements if item.category == category
        )
        for category in ("technical", "compliance", "commercial", "logistics")
    }

    def category_status(category: str, *, supported_label: str) -> str:
        items = categories[category]
        if not items:
            return "Not requested"
        if any(item.status == "insufficient_evidence" for item in items):
            return "More evidence required"
        if any(item.status == "needs_confirmation" for item in items):
            return "Confirmation required"
        return supported_label

    open_labels = {
        "technical": "Technical scope or operating conditions",
        "compliance": "Target-market regulatory requirements",
        "commercial": "Commercial terms and availability",
        "logistics": "Destination and shipping terms",
    }
    open_items = tuple(
        label
        for category, label in open_labels.items()
        if any(item.status != "supported" for item in categories[category])
    )
    questions: list[str] = []
    if any(item.status != "supported" for item in categories["technical"]):
        questions.extend(
            ("What is the final application?", "Is the operating condition continuous, intermittent, or a short peak?", "What exposure medium, duration, and failure criterion apply?")
        )
    if any(item.status != "supported" for item in categories["compliance"]):
        questions.append("Which target country, regulation, certification, or customer standard applies?")
    if any(item.status != "supported" for item in categories["commercial"]):
        questions.append("What quantity, delivery window, and packaging are required?")
    if any(item.status != "supported" for item in categories["logistics"]):
        questions.append("What destination port and named Incoterm place should be used?")

    next_actions = {
        "ready_to_reply": "Prepare the evidence-grounded technical reply",
        "needs_technical_confirmation": "Collect the missing technical conditions",
        "needs_commercial_input": "Collect customer and internal quotation inputs",
        "insufficient_product_evidence": "Obtain additional approved product evidence",
    }
    quotation_status = (
        "Inputs required"
        if analysis.next_action == "needs_commercial_input"
        else "Do not quote yet"
        if analysis.recommendation_status == "insufficient_evidence"
        else "Not requested"
    )
    if analysis.recommendation_status == "supported":
        return AnalysisView(
            headline=(
                "Technical reply ready; quotation inputs required"
                if analysis.next_action == "needs_commercial_input"
                else "Technical reply ready"
            ),
            technical_status=category_status("technical", supported_label="Ready to reply"),
            compliance_status=category_status("compliance", supported_label="Evidence available"),
            quotation_status=quotation_status,
            logistics_status=category_status("logistics", supported_label="Evidence available"),
            citations=citations,
            fail_closed=fail_closed,
            next_action=next_actions[analysis.next_action],
            open_items=open_items,
            customer_questions=tuple(questions),
        )
    return AnalysisView(
        headline="More evidence is required before recommending a product",
        technical_status=category_status("technical", supported_label="Evidence available"),
        compliance_status=category_status("compliance", supported_label="Evidence available"),
        quotation_status=quotation_status,
        logistics_status=category_status("logistics", supported_label="Evidence available"),
        citations=citations,
        fail_closed=fail_closed,
        next_action=next_actions[analysis.next_action],
        open_items=open_items,
        customer_questions=tuple(questions),
    )


def _unique_citations(analysis: InquiryAnalysis) -> tuple[SourceCitation, ...]:
    ordered = [
        citation
        for requirement in analysis.requirements
        for citation in requirement.evidence
    ] + [parameter.citation for parameter in analysis.key_parameters]
    unique: list[SourceCitation] = []
    seen: set[tuple[str, str, int]] = set()
    for citation in ordered:
        identity = (citation.product, citation.source_file, citation.page_number)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(citation)
    return tuple(unique)


def _is_fail_closed(analysis: InquiryAnalysis) -> bool:
    narrative = " ".join(
        (*analysis.recommendation_reasons, *analysis.evidence_gaps)
    ).casefold()
    return any(
        marker in narrative
        for marker in (
            "未通过本地证据校验",
            "local evidence validation",
        )
    )
