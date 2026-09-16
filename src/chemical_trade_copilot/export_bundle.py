"""一次性工具的导出：把一次分析结果组装成可带走的技术回复包。

设计约束（与产品目标一致）：

- **不落盘**：本模块只做字符串组装，不写任何文件、不读任何文件；调用方负责把结果
  交给浏览器下载或剪贴板。
- **无新依赖**：只用标准库与已有模块。
- **可单测**：全部为纯函数，输入输出明确。
- **不新增主张**：导出内容只重排 ``InquiryAnalysis`` / ``TechnicalReviewCard`` /
  ``EmailDraft`` 里已经过本地证据门禁的内容，不推断、不补充任何数值或结论。
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .inquiry_analysis import InquiryAnalysis
from .inquiry_review import TechnicalReviewCard
from .ui_components import APP_CSS
from .ui_presenter import AnalysisView, EmailDraft

DECISION_KEYS = ("technical", "compliance", "quotation", "logistics")


@dataclass(frozen=True, slots=True)
class SourceRow:
    """导出用的一行来源；只包含批准清单里可追溯的字段。"""

    product: str
    source_file: str
    page_number: int


def collect_sources(
    analysis: InquiryAnalysis, view: AnalysisView
) -> tuple[SourceRow, ...]:
    """来源以分析里的引用为准，按产品、文件、物理页去重并稳定排序。"""
    rows = {
        (citation.product, citation.source_file, citation.page_number)
        for citation in view.citations
    }
    for parameter in analysis.key_parameters:
        citation = parameter.citation
        rows.add((citation.product, citation.source_file, citation.page_number))
    return tuple(
        SourceRow(product=product, source_file=source_file, page_number=page)
        for product, source_file, page in sorted(rows)
    )


def decision_rows(view: AnalysisView, labels: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    statuses = (
        (view.technical_status, view.technical_status),
        (view.compliance_status, view.compliance_status),
        (view.quotation_status, view.quotation_status),
        (view.logistics_status, view.logistics_status),
    )
    return tuple(
        (labels[f"decision_line.{key}"], status)
        for key, (_, status) in zip(DECISION_KEYS, statuses)
    )


def _conclusion_headline(analysis: InquiryAnalysis, view: AnalysisView) -> str:
    if analysis.recommendation_status == "supported":
        return analysis.recommended_product or ""
    return ""


def build_markdown(
    *,
    inquiry: str,
    market: str,
    analysis: InquiryAnalysis,
    card: TechnicalReviewCard,
    view: AnalysisView,
    draft: EmailDraft,
    labels: Mapping[str, str],
) -> str:
    """把一次分析组装成 Markdown 技术回复包。"""
    L = labels.__getitem__
    lines: list[str] = []
    lines.append(f"# {L('export.title')}")
    lines.append("")
    lines.append(f"- **{L('export.inquiry')}**: {inquiry.strip()}")
    if market:
        lines.append(f"- **{L('export.market')}**: {market}")
    lines.append(f"- **{L('export.status')}**: {L('export.status.' + analysis.recommendation_status)}")
    lines.append("")

    product = _conclusion_headline(analysis, view)
    if product:
        lines.append(f"## {product}")
        lines.append("")
    else:
        lines.append(f"## {L('export.no_product')}")
        lines.append("")
    lines.append(f"**{view.headline}**")
    lines.append("")
    if analysis.recommendation_status != "supported":
        # 证据不足时，模型的摘要文本经本地门禁保留；直接引用，不重写。
        lines.append(analysis.summary_zh)
        lines.append("")
    if view.open_items:
        lines.append(f"- {L('export.open_items')}: " + " · ".join(view.open_items))
    lines.append(f"- {L('export.next_action')}: {view.next_action}")
    lines.append("")

    lines.append(f"## {L('export.decision')}")
    lines.append("")
    lines.append(f"| {L('export.category')} | {L('export.state')} |")
    lines.append("|---|---|")
    for key, (label, status) in zip(DECISION_KEYS, decision_rows(view, labels)):
        lines.append(f"| {label} | {status} |")
    lines.append("")

    if analysis.key_parameters:
        lines.append(f"## {L('export.parameters')}")
        lines.append("")
        for parameter in analysis.key_parameters:
            value = f"{parameter.value}{parameter.unit}"
            lines.append(f"### {parameter.name}: {value}")
            lines.append("")
            if parameter.conditions:
                lines.append(f"- {L('export.conditions')}: {parameter.conditions}")
            if parameter.curing_agent:
                lines.append(f"- {L('export.agent')}: {parameter.curing_agent}")
            if parameter.mix_ratio:
                lines.append(f"- {L('export.ratio')}: {parameter.mix_ratio}")
            if parameter.cure_schedule:
                lines.append(f"- {L('export.schedule')}: {parameter.cure_schedule}")
            if parameter.test_method:
                lines.append(f"- {L('export.method')}: {parameter.test_method}")
            citation = parameter.citation
            lines.append(
                f"- {L('export.source')}: {citation.source_file} · "
                f"{L('export.physical_page')} {citation.page_number}"
            )
            lines.append("")

    if card.facts:
        lines.append(f"## {L('export.facts')}")
        lines.append("")
        for fact in card.facts:
            lines.append(f"- **{L('category.' + fact.category)}**: {fact.text}")
        lines.append("")

    if card.ambiguities:
        lines.append(f"## {L('export.ambiguities')}")
        lines.append("")
        for ambiguity in card.ambiguities:
            lines.append(f"- **{ambiguity.original_text}** — {ambiguity.impact}")
        lines.append("")

    if card.evidence_limitations or analysis.source_limitations:
        lines.append(f"## {L('export.limitations')}")
        lines.append("")
        for limitation in card.evidence_limitations:
            lines.append(f"- {limitation}")
        for limitation in analysis.source_limitations:
            lines.append(f"- {limitation}")
        lines.append("")

    if card.follow_ups:
        lines.append(f"## {L('export.follow_ups')}")
        lines.append("")
        for follow_up in card.follow_ups:
            lines.append(f"- {follow_up.question}")
        lines.append("")

    lines.append(f"## {L('export.email')}")
    lines.append("")
    lines.append(f"**{L('export.email_subject')}**: {draft.subject}")
    lines.append("")
    lines.append("```text")
    lines.append(draft.body)
    lines.append("```")
    lines.append("")

    sources = collect_sources(analysis, view)
    if sources:
        lines.append(f"## {L('export.sources')}")
        lines.append("")
        for row in sources:
            lines.append(
                f"- {row.product} · {row.source_file} · "
                f"{L('export.physical_page')} {row.page_number}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _html_list(items: Sequence[str]) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def build_printable_html(
    *,
    inquiry: str,
    market: str,
    analysis: InquiryAnalysis,
    card: TechnicalReviewCard,
    view: AnalysisView,
    draft: EmailDraft,
    labels: Mapping[str, str],
) -> str:
    """可打印 HTML：浏览器打开后 Ctrl+P 即可存 PDF。

    复用工作台自己的 ``APP_CSS``，因此打印件与屏幕上的版式语言一致。
    """
    L = labels.__getitem__
    product = _conclusion_headline(analysis, view)
    parts: list[str] = []
    parts.append('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">')
    parts.append(f"<title>{html.escape(L('export.title'))}</title>")
    parts.append(APP_CSS)
    parts.append(
        "<style>body{background:#FFFFFF;margin:0;padding:0;}"
        ".ctc-print-sheet{margin:0 auto;box-shadow:none;}</style>"
    )
    parts.append("</head><body>")
    parts.append('<article class="ctc-print-sheet">')

    meta_right = (
        f"<span>{html.escape(L('export.market'))}: {html.escape(market)}</span>"
        if market
        else ""
    )
    parts.append(
        '<div class="ctc-print-meta">'
        f"<span>{html.escape(L('export.title'))}</span>"
        f"{meta_right}"
        "</div>"
    )
    if product:
        parts.append(f"<h2>{html.escape(product)}</h2>")
    else:
        parts.append(f"<h2>{html.escape(L('export.no_product'))}</h2>")
    parts.append(f"<p><strong>{html.escape(view.headline)}</strong></p>")
    if analysis.recommendation_status != "supported":
        parts.append(f"<p>{html.escape(analysis.summary_zh)}</p>")

    parts.append(f"<h3>{html.escape(L('export.inquiry'))}</h3>")
    parts.append(f"<p>{html.escape(inquiry.strip())}</p>")

    parts.append(f"<h3>{html.escape(L('export.decision'))}</h3>")
    parts.append("<table><tr>")
    for key in DECISION_KEYS:
        parts.append(f"<th>{html.escape(L('decision_line.' + key))}</th>")
    parts.append("</tr><tr>")
    for _, status in decision_rows(view, labels):
        parts.append(f"<td>{html.escape(status)}</td>")
    parts.append("</tr></table>")

    if analysis.key_parameters:
        parts.append(f"<h3>{html.escape(L('export.parameters'))}</h3>")
        parts.append(
            "<table><tr>"
            f"<th>{html.escape(L('export.parameter'))}</th>"
            f"<th>{html.escape(L('export.value'))}</th>"
            f"<th>{html.escape(L('export.conditions'))}</th>"
            f"<th>{html.escape(L('export.method'))}</th>"
            f"<th>{html.escape(L('export.source'))}</th>"
            "</tr>"
        )
        for parameter in analysis.key_parameters:
            conditions = " · ".join(
                value
                for value in (
                    parameter.conditions,
                    parameter.curing_agent,
                    parameter.mix_ratio,
                    parameter.cure_schedule,
                )
                if value
            )
            citation = parameter.citation
            parts.append(
                "<tr>"
                f"<td>{html.escape(parameter.name)}</td>"
                f"<td>{html.escape(parameter.value + parameter.unit)}</td>"
                f"<td>{html.escape(conditions)}</td>"
                f"<td>{html.escape(parameter.test_method)}</td>"
                f"<td>{html.escape(citation.source_file)} · "
                f"{html.escape(L('export.physical_page'))} {citation.page_number}</td>"
                "</tr>"
            )
        parts.append("</table>")

    if card.facts:
        parts.append(f"<h3>{html.escape(L('export.facts'))}</h3>")
        parts.append(
            _html_list([f"{L('category.' + fact.category)}: {fact.text}" for fact in card.facts])
        )

    if card.ambiguities:
        parts.append(f"<h3>{html.escape(L('export.ambiguities'))}</h3>")
        parts.append(
            _html_list(
                [f"{item.original_text} — {item.impact}" for item in card.ambiguities]
            )
        )

    limitations = [*card.evidence_limitations, *analysis.source_limitations]
    if limitations:
        parts.append(f"<h3>{html.escape(L('export.limitations'))}</h3>")
        parts.append(_html_list(list(limitations)))

    if card.follow_ups:
        parts.append(f"<h3>{html.escape(L('export.follow_ups'))}</h3>")
        parts.append(_html_list([item.question for item in card.follow_ups]))

    parts.append(f"<h3>{html.escape(L('export.email'))}</h3>")
    parts.append(f"<p><strong>{html.escape(draft.subject)}</strong></p>")
    parts.append(f'<p class="ctc-print-email">{html.escape(draft.body)}</p>')

    sources = collect_sources(analysis, view)
    if sources:
        parts.append(f"<h3>{html.escape(L('export.sources'))}</h3>")
        parts.append(
            _html_list(
                [
                    f"{row.product} · {row.source_file} · "
                    f"{L('export.physical_page')} {row.page_number}"
                    for row in sources
                ]
            )
        )

    parts.append('<div class="ctc-print-signoff">')
    parts.append(f"<p>{html.escape(L('export.signoff'))}</p>")
    parts.append("</div>")
    parts.append("</article></body></html>")
    return "\n".join(parts)
