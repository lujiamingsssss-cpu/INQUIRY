"""化工询盘台 · 业务员一次性工具（单页）。

产品定位：**输入询盘 → 证据约束的结论 → 导出 → 关闭**。

与基线的差异（只动界面与状态层，不动解析能力）：

- 单页，不再有 8 页编号导航、审阅记录、备份/恢复、修订哈希、打印页、决定页与内部候选下拉、
  逐页机器翻译。删除的都是留痕与编排，与"业务员肯用的一次性工具"无关。
- **不持久化任何数据**：结果只存在于 `st.session_state`（进程内存 / 浏览器会话），
  关闭或刷新即消失；导出在内存中生成后交给浏览器下载。
- 证据门禁、失败关闭、已核验事实的条件绑定、来源物理页查看、四态决策行、英文回复草稿
  全部保留；`ui_components.APP_CSS` 未改动，界面设计语言不变。
"""

import hashlib
import html
import json
import os
from pathlib import Path
from types import SimpleNamespace

import streamlit as st
from streamlit.errors import StreamlitAPIException

from chemical_trade_copilot.evidence_viewer import (
    build_zoomable_page_html,
    render_approved_citation_page,
)
from chemical_trade_copilot.export_bundle import (
    build_markdown,
    build_printable_html,
)
from chemical_trade_copilot.inquiry_analysis import (
    DeepSeekInquiryAnalyzer,
    DeepSeekJsonClient,
    InquiryAnalysis,
    InquiryRetrievalPlanner,
    SourceCitation,
)
from chemical_trade_copilot.inquiry_review import (
    TechnicalReviewCard,
    build_review_card,
)
from chemical_trade_copilot.localization import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    Locale,
    browser_locale_script,
    normalize_locale,
    text,
    view_text,
)
from chemical_trade_copilot.materials import (
    load_material_catalog,
    material_catalog_fingerprint,
)
from chemical_trade_copilot.pdf_pages import ApprovedPdf, load_approved_pdf
from chemical_trade_copilot.retrieval import PageIndex
from chemical_trade_copilot.ui_components import (
    APP_CSS,
    build_copy_button_html,
)
from chemical_trade_copilot.ui_presenter import (
    build_analysis_view,
    build_email_draft,
)
from chemical_trade_copilot.local_settings import load_local_settings
from chemical_trade_copilot.workflow import analyze_inquiry_with_evidence


# 本机配置（模型密钥、资料根目录）由应用自己从 .env.local 读取，
# 因此双击启动脚本不需要解析配置文件，也不受代码页或 BOM 影响。
load_local_settings()

DEFAULT_MATERIALS_ROOT = Path(r"G:\桌面\化工")
DEFAULT_DATABASE = Path(".chroma")
DEFAULT_MATERIAL_CATALOG = Path("materials_catalog.json")

_RESULT_KEY = "one_shot_result"

_EXPORT_KEYS = (
    "export.title",
    "export.inquiry",
    "export.market",
    "export.status",
    "export.status.supported",
    "export.status.insufficient_evidence",
    "export.no_product",
    "export.decision",
    "export.category",
    "export.state",
    "export.parameters",
    "export.parameter",
    "export.value",
    "export.conditions",
    "export.agent",
    "export.ratio",
    "export.schedule",
    "export.method",
    "export.source",
    "export.physical_page",
    "export.facts",
    "export.ambiguities",
    "export.limitations",
    "export.follow_ups",
    "export.email",
    "export.email_subject",
    "export.sources",
    "export.open_items",
    "export.next_action",
    "export.signoff",
    "decision_line.technical",
    "decision_line.compliance",
    "decision_line.quotation",
    "decision_line.logistics",
    "category.technical",
    "category.compliance",
    "category.commercial",
    "category.logistics",
)


def _material_catalog_path() -> Path:
    return Path(
        os.environ.get(
            "CHEMICAL_TRADE_MATERIAL_CATALOG", str(DEFAULT_MATERIAL_CATALOG)
        )
    )


def _database_path() -> Path:
    return Path(os.environ.get("CHEMICAL_TRADE_DATABASE", str(DEFAULT_DATABASE)))


def _materials_root() -> Path:
    return Path(
        os.environ.get("CHEMICAL_TRADE_MATERIALS_ROOT", str(DEFAULT_MATERIALS_ROOT))
    )


def _export_labels(locale: Locale) -> dict[str, str]:
    return {key: text(key, locale) for key in _EXPORT_KEYS}


def _approved_products() -> str:
    catalog = load_material_catalog(_material_catalog_path())
    products = sorted(
        {entry.product for entry in catalog if entry.enabled}, key=str.casefold
    )
    return ", ".join(products) if products else "-"


def _render_language_selector() -> Locale:
    requested = normalize_locale(st.query_params.get("lang", DEFAULT_LOCALE))
    widget_key = f"interface_locale_{requested}"
    if st.session_state.get("_interface_query_locale") != requested:
        st.session_state[widget_key] = requested
        st.session_state["_interface_query_locale"] = requested
    labels = {
        "en": text("language.english", requested),
        "zh-CN": text("language.chinese", requested),
    }
    st.caption(text("language.label", requested))
    selected = st.selectbox(
        "Interface language / 界面语言",
        options=SUPPORTED_LOCALES,
        format_func=labels.__getitem__,
        key=widget_key,
        label_visibility="collapsed",
    )
    locale = normalize_locale(selected)
    if locale != requested:
        st.session_state[f"interface_locale_{locale}"] = locale
        st.query_params["lang"] = locale
        st.session_state["_interface_query_locale"] = locale
        st.rerun()
    st.html(browser_locale_script(locale), unsafe_allow_javascript=True)
    return locale


# --------------------------------------------------------------------------
# 一次询盘：分析 → 结果只留在内存
# --------------------------------------------------------------------------


def _current_evidence_fingerprint() -> str:
    expected = material_catalog_fingerprint(
        load_material_catalog(_material_catalog_path())
    )
    with PageIndex(_database_path(), embedder=_MetadataOnlyEmbedder()) as index:
        index.assert_catalog_fingerprint(expected)
    return expected


class _MetadataOnlyEmbedder:
    def encode(self, texts):
        raise RuntimeError("Evidence generation checks must not calculate embeddings")


def _run_analysis(
    inquiry: str,
) -> tuple[InquiryAnalysis, TechnicalReviewCard, str]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is not available in this process")
    client = DeepSeekJsonClient(
        api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )
    expected_fingerprint = material_catalog_fingerprint(
        load_material_catalog(_material_catalog_path())
    )
    with PageIndex(_database_path()) as index:
        index.assert_catalog_fingerprint(expected_fingerprint)
        analysis, collected = _analyze_with_evidence(
            inquiry, index=index, client=client
        )
    card = build_review_card(
        inquiry,
        analysis,
        list(collected.ranked),
        available_evidence=list(collected.evidence),
    )
    return analysis, card, expected_fingerprint


def _analyze_with_evidence(inquiry: str, *, index: PageIndex, client):
    return analyze_inquiry_with_evidence(
        inquiry,
        index=index,
        planner=InquiryRetrievalPlanner(client),
        analyzer=DeepSeekInquiryAnalyzer(client),
        limit=3,
    )


def _store_result(
    inquiry: str,
    analysis: InquiryAnalysis,
    card: TechnicalReviewCard,
    fingerprint: str,
) -> None:
    """结果只写进会话内存；本工具不做任何持久化。"""
    st.session_state[_RESULT_KEY] = json.dumps(
        {
            "inquiry": inquiry,
            "analysis": json.loads(analysis.model_dump_json()),
            "card": json.loads(card.model_dump_json()),
            "fingerprint": fingerprint,
        },
        ensure_ascii=False,
    )


def _load_result():
    payload = st.session_state.get(_RESULT_KEY)
    if not payload:
        return None
    data = json.loads(payload)
    return SimpleNamespace(
        inquiry=data["inquiry"],
        analysis=InquiryAnalysis.model_validate(data["analysis"]),
        card=TechnicalReviewCard.model_validate(data["card"]),
        fingerprint=data["fingerprint"],
    )


def _clear_result() -> None:
    st.session_state.pop(_RESULT_KEY, None)


# --------------------------------------------------------------------------
# 结果页：逐字沿用基线的渲染函数，保证界面设计语言不变
# --------------------------------------------------------------------------


def _render_decision_line(analysis: InquiryAnalysis, locale: Locale) -> None:
    view = build_analysis_view(analysis)
    statuses = (
        (text("decision_line.technical", locale), view.technical_status, analysis.recommendation_status == "supported"),
        (text("decision_line.compliance", locale), view.compliance_status, False),
        (text("decision_line.quotation", locale), view.quotation_status, False),
        (text("decision_line.logistics", locale), view.logistics_status, False),
    )
    cells = "".join(
        (
            '<div class="ctc-decision">'
            f'<span><i class="ctc-dot{"" if ready else " open"}"></i>'
            f"{html.escape(label)}</span>"
            f"<b>{html.escape(view_text(status, locale))}</b></div>"
        )
        for label, status, ready in statuses
    )
    st.html(f'<div class="ctc-decision-line">{cells}</div>')


def _render_verified_parameters(analysis: InquiryAnalysis, locale: Locale) -> None:
    if not analysis.key_parameters:
        return
    st.subheader(text("result.why_title", locale))
    st.write(text("result.why_description", locale))
    for parameter in analysis.key_parameters:
        first = (
            f"{html.escape(parameter.curing_agent or text('result.not_stated', locale))} · "
            f"{html.escape(parameter.mix_ratio or text('result.not_stated', locale))}"
        )
        second = html.escape(parameter.cure_schedule or text("result.not_stated", locale))
        third = (
            f'<span class="number">{html.escape(parameter.value)}'
            f"{html.escape(parameter.unit)}</span> · {html.escape(parameter.test_method)}"
        )
        citation = parameter.citation
        st.html(
            '<div class="ctc-fact">'
            f'<div class="ctc-fact-head"><span>{html.escape(text("result.verified_fact", locale))}</span>'
            f'<span>{html.escape(text("result.not_continuous", locale))}</span></div>'
            '<div class="ctc-fact-grid">'
            f'<div class="ctc-fact-cell"><b>{first}</b>{html.escape(text("result.agent_ratio", locale))}</div>'
            f'<div class="ctc-fact-cell"><b>{second}</b>{html.escape(text("result.cure_schedule", locale))}</div>'
            f'<div class="ctc-fact-cell"><b>{third}</b>{html.escape(parameter.name)}</div>'
            '</div><div class="ctc-source">'
            f"<span>{html.escape(citation.source_file)} · {html.escape(text('source.physical_page', locale, page=citation.page_number))}"
            f"</span><b>{html.escape(text('result.verified_source', locale))}</b></div></div>"
        )
    st.html(f'<div class="ctc-warning">{html.escape(text("result.fact_warning", locale))}</div>')


@st.dialog("Original controlled PDF", width="large")
def _open_original_pdf_dialog(
    citation: SourceCitation,
    approved: ApprovedPdf,
) -> None:
    rendered = render_approved_citation_page(citation, approved)
    total_pages = approved.page_count
    st.markdown(
        f"**{rendered.source_file}**  \n"
        f"{rendered.product} · physical page {rendered.page_number} of {total_pages}"
    )
    st.html(
        build_zoomable_page_html(
            rendered.png_bytes,
            alt_text=(
                f"{rendered.product}, {rendered.source_file}, physical page "
                f"{rendered.page_number} of {total_pages}"
            ),
            source_metadata=(
                f"{rendered.product} · {rendered.source_file} · Physical page "
                f"{rendered.page_number} of {total_pages} · {rendered.date_revision} · "
                f"{rendered.jurisdiction}"
            ),
        ),
        unsafe_allow_javascript=True,
    )
    try:
        st.pdf(
            approved.pdf_bytes,
            height=700,
            key=(
                "original_pdf_"
                + hashlib.sha256(
                    f"{citation.product}\0{citation.source_file}".encode("utf-8")
                ).hexdigest()[:16]
            ),
        )
    except StreamlitAPIException:
        st.error(
            "The full original PDF viewer is unavailable in this local installation. "
            "The cited physical page above remains the controlled source."
        )


def _render_sources(analysis: InquiryAnalysis, locale: Locale) -> None:
    view = build_analysis_view(analysis)
    if not view.citations:
        return
    st.subheader(text("source.title", locale))
    st.caption(text("source.caption", locale))
    materials_root = _materials_root()
    catalog_path = _material_catalog_path()
    for citation in view.citations:
        try:
            approved = load_approved_pdf(
                citation.product,
                citation.source_file,
                materials_root,
                catalog_path,
            )
            rendered = render_approved_citation_page(citation, approved)
            total_pages = approved.page_count
        except (FileNotFoundError, ValueError):
            st.warning(
                "The controlled source is unavailable. Verify the approved materials "
                "catalog and try again."
            )
            continue
        physical_page = (
            f"{text('source.physical_page', locale, page=rendered.page_number)} "
            f"of {total_pages}"
        )
        alt_text = (
            f"{rendered.product}, {rendered.source_file}, "
            f"physical page {rendered.page_number} of {total_pages}"
        )
        source_metadata = (
            f"{rendered.product} · {rendered.source_file} · Physical page "
            f"{rendered.page_number} of {total_pages} · {rendered.date_revision} · "
            f"{rendered.jurisdiction}"
        )
        # 左右两栏：缩略图贴左按自身宽度，文件身份与操作占满剩余宽度。
        with st.container(key="ctc_source_layout"):
            viewer_column, side_column = st.columns([1, 3])
            with side_column:
                st.markdown(f"**{rendered.source_file}**")
                st.caption(
                    f"{rendered.product} · {physical_page} · "
                    f"{rendered.date_revision} · {rendered.jurisdiction}"
                )
                if st.button(
                    text(
                        "source.open_original",
                        locale,
                        page=rendered.page_number,
                    ),
                    key=(
                        "open_original_pdf_"
                        + hashlib.sha256(
                            (
                                f"{rendered.product}\0{rendered.source_file}\0"
                                f"{rendered.page_number}"
                            ).encode("utf-8")
                        ).hexdigest()[:16]
                    ),
                ):
                    _open_original_pdf_dialog(citation, approved)
            with viewer_column:
                st.html(
                    build_zoomable_page_html(
                        rendered.png_bytes,
                        alt_text=alt_text,
                        source_metadata=source_metadata,
                    ),
                    unsafe_allow_javascript=True,
                )


def _render_readiness(analysis: InquiryAnalysis, locale: Locale) -> None:
    view = build_analysis_view(analysis)
    st.subheader(text("readiness.title", locale))
    customer, internal = st.columns(2, gap="large")
    with customer:
        st.markdown(f"**{text('readiness.customer', locale)}**")
        items = "".join(
            f"<li>{html.escape(view_text(question, locale))}</li>"
            for question in view.customer_questions
        )
        st.html(f'<ul class="ctc-checklist">{items}</ul>')
    with internal:
        st.markdown(f"**{text('readiness.internal', locale)}**")
        st.html(
            '<ul class="ctc-checklist">'
            f"<li>{html.escape(text('readiness.stock', locale))}</li>"
            f"<li>{html.escape(text('readiness.price', locale))}</li>"
            f"<li>{html.escape(text('readiness.freight', locale))}</li>"
            f"<li>{html.escape(text('readiness.payment', locale))}</li></ul>"
        )
    st.markdown(f"**{text('readiness.documents', locale)}**")
    st.caption(text("readiness.document_caption", locale))


def _render_review_card(card: TechnicalReviewCard, locale: Locale) -> None:
    """复核卡里对业务员真正有用的部分：询盘事实、歧义、边界、追问。

    全部为本地确定性计算，不额外调用模型；此处只读展示，不再有勾选与"已完成"状态。
    """
    if card.facts:
        st.subheader(text("review.facts", locale))
        for fact in card.facts:
            category = text(f"category.{fact.category}", locale)
            st.markdown(
                f"- **{category} · {text('status.inquiry_explicit', locale)}:** "
                f"{fact.text}"
            )
    if card.ambiguities:
        st.subheader(text("review.ambiguities", locale))
        for ambiguity in card.ambiguities:
            st.markdown(f"**{ambiguity.original_text}** — {ambiguity.impact}")
    limitations = list(card.evidence_limitations)
    if limitations:
        st.subheader(text("review.limits", locale))
        for limitation in limitations:
            st.html(f'<div class="ctc-warning">{html.escape(limitation)}</div>')
    if card.follow_ups:
        st.subheader(text("review.followups", locale))
        items = "".join(
            f"<li>{html.escape(follow_up.question)}</li>"
            for follow_up in card.follow_ups
        )
        st.html(f'<ul class="ctc-checklist">{items}</ul>')


def _render_email(analysis: InquiryAnalysis, locale: Locale) -> None:
    draft = build_email_draft(analysis)
    st.subheader(text("draft.english_reply", locale))
    st.caption(text("draft.caption", locale))
    st.text_input(text("draft.subject", locale), value=draft.subject, disabled=True)
    editor_label = text("draft.english_email", locale)
    st.text_area(editor_label, value=draft.body, height=310, key="draft_body")
    st.html(
        build_copy_button_html(
            editor_label=editor_label,
            button_label=text("draft.copy", locale),
            copied_text=text("draft.copied", locale),
            missing_text=text("draft.editor_missing", locale),
        ),
        unsafe_allow_javascript=True,
    )


def _export_file_stem(analysis: InquiryAnalysis) -> str:
    product = analysis.recommended_product or "no-product"
    safe = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in product
    )
    return f"reply-pack-{safe}".strip("-")


def _render_export(
    inquiry: str,
    analysis: InquiryAnalysis,
    card: TechnicalReviewCard,
    locale: Locale,
) -> None:
    """导出：在内存里组装，交给浏览器下载；本工具不写任何文件。"""
    view = build_analysis_view(analysis)
    draft = build_email_draft(analysis)
    labels = _export_labels(locale)
    payload = {
        "inquiry": inquiry,
        "market": "",
        "analysis": analysis,
        "card": card,
        "view": view,
        "draft": draft,
        "labels": labels,
    }
    markdown = build_markdown(**payload)
    printable = build_printable_html(**payload)
    stem = _export_file_stem(analysis)
    st.subheader(text("export.title", locale))
    st.caption(text("export.caption", locale))
    left, right = st.columns(2)
    with left:
        st.download_button(
            text("export.markdown", locale),
            data=markdown,
            file_name=f"{stem}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with right:
        st.download_button(
            text("export.print", locale),
            data=printable,
            file_name=f"{stem}.html",
            mime="text/html",
            use_container_width=True,
        )


def _render_result(result, locale: Locale) -> None:
    analysis = result.analysis
    view = build_analysis_view(analysis)
    if analysis.recommendation_status == "supported":
        st.html(f'<div class="ctc-eyebrow">{html.escape(text("result.validated", locale))}</div>')
    else:
        st.html(
            f'<div class="ctc-eyebrow">{html.escape(text("insufficient.eyebrow", locale))}</div>'
        )
    if analysis.recommended_product:
        st.header(analysis.recommended_product)
    st.subheader(view_text(view.headline, locale))
    st.write(
        text("result.supported_description", locale)
        if analysis.recommendation_status == "supported"
        else view_text(analysis.summary_zh, locale)
    )
    if view.fail_closed:
        st.html(
            f'<div class="ctc-guardrail">{html.escape(text("insufficient.guardrail", locale))}</div>'
        )
    _render_decision_line(analysis, locale)
    if view.open_items:
        st.caption(
            text(
                "result.open_items",
                locale,
                value=" · ".join(view_text(item, locale) for item in view.open_items),
            )
        )
    st.caption(
        text("result.next_action", locale, value=view_text(view.next_action, locale))
    )
    st.divider()
    _render_verified_parameters(analysis, locale)
    if analysis.next_action == "needs_commercial_input":
        st.divider()
        _render_readiness(analysis, locale)
    st.divider()
    _render_sources(analysis, locale)
    st.divider()
    _render_review_card(result.card, locale)
    st.divider()
    _render_email(analysis, locale)
    st.divider()
    _render_export(result.inquiry, analysis, result.card, locale)


# --------------------------------------------------------------------------
# 入口与主流程
# --------------------------------------------------------------------------


def _render_entry_content(locale: Locale) -> None:
    st.html(f'<div class="ctc-eyebrow">{html.escape(text("entry.eyebrow", locale))}</div>')
    st.title(text("entry.title", locale))
    st.write(text("entry.description", locale))
    if not os.environ.get("DEEPSEEK_API_KEY"):
        st.info(text("entry.api_key_missing", locale))
    st.text_area(
        text("entry.inquiry", locale),
        key="inquiry",
        height=190,
        placeholder=text("entry.placeholder", locale),
    )
    st.caption(text("entry.help", locale))
    if st.button(text("entry.analyze", locale), type="primary"):
        inquiry = st.session_state.get("inquiry", "")
        if not inquiry.strip():
            st.error(text("entry.empty", locale))
            return
        try:
            with st.spinner(text("entry.spinner", locale)):
                analysis, card, fingerprint = _run_analysis(inquiry)
        except Exception:
            st.error(text("entry.failed", locale))
            return
        _store_result(inquiry, analysis, card, fingerprint)
        st.rerun()


def _render_entry(locale: Locale) -> None:
    with st.container(key="ctc_entry_sheet"):
        _render_entry_content(locale)


def main() -> None:
    st.set_page_config(
        page_title="Chemical Trade Copilot",
        page_icon="⚗",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.html(APP_CSS)
    with st.container(key="ctc_app_header"):
        brand_column, locale_column = st.columns([3, 1])
        with locale_column:
            locale = _render_language_selector()
        with brand_column:
            st.caption(text("app.scope", locale))

    result = _load_result()
    if result is not None:
        try:
            current_fingerprint = _current_evidence_fingerprint()
        except (FileNotFoundError, ValueError):
            _clear_result()
            st.warning(text("entry.stale_cleared", locale))
            _render_entry(locale)
            return
        if result.fingerprint != current_fingerprint:
            _clear_result()
            st.warning(text("entry.stale_cleared", locale))
            _render_entry(locale)
            return
        if st.button(text("action.new", locale)):
            _clear_result()
            st.session_state["inquiry"] = ""
            st.rerun()
        with st.container(key="ctc_review_sheet"):
            _render_result(result, locale)
    else:
        _render_entry(locale)

    st.divider()
    st.caption(
        text("footer.scope", locale, products=_approved_products())
    )
    st.caption(text("footer.oneshot", locale))


if __name__ == "__main__":
    main()
