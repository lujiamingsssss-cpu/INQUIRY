import html
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import streamlit as st
from pydantic import ValidationError
from streamlit.errors import StreamlitAPIException

from chemical_trade_copilot.evidence_viewer import (
    build_zoomable_page_html,
    render_approved_citation_page,
)
from chemical_trade_copilot.inquiry_analysis import (
    DeepSeekInquiryAnalyzer,
    DeepSeekJsonClient,
    InquiryAnalysis,
    InquiryRetrievalPlanner,
    SourceCitation,
)
from chemical_trade_copilot.inquiry_review import (
    ReviewSessionState,
    TechnicalReviewCard,
    start_review_session,
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
    enabled_catalog_snapshot,
    evidence_scope_caption,
    load_material_catalog,
    material_catalog_fingerprint,
)
from chemical_trade_copilot.retrieval import PageIndex
from chemical_trade_copilot.review_translation import (
    ReviewTranslationBundle,
    collect_review_translation_items,
    collect_review_translation_tokens,
    translate_items,
)
from chemical_trade_copilot.review_email import (
    FollowUpPresentation,
    active_draft as authorized_active_draft,
    ensure_authorized_draft,
    classify_follow_up_intent,
    optimize_authorized_draft,
)
from chemical_trade_copilot.pdf_pages import ApprovedPdf, load_approved_pdf
from chemical_trade_copilot.review_workspace import (
    CatalogDocumentRef,
    EmailDraftVersion,
    REVIEW_PAGES,
    ReviewWorkspace,
    TARGET_MARKETS,
    TargetMarket,
    apply_workspace_decision,
    edit_active_draft,
    export_review_backup,
    finalize_workspace,
    import_review_backup,
    open_follow_ups,
    record_summary,
    select_active_draft,
    set_current_page,
    set_resolved_follow_up,
    validate_workspace_decision,
)
from chemical_trade_copilot.ui_components import (
    APP_CSS,
    build_copy_button_html,
    build_print_button_html,
)
from chemical_trade_copilot.ui_presenter import (
    build_analysis_view,
)
from chemical_trade_copilot.workflow import analyze_and_review_inquiry


DEFAULT_MATERIALS_ROOT = Path(r"G:\桌面\化工")
DEFAULT_DATABASE = Path(".chroma")
DEFAULT_MATERIAL_CATALOG = Path("materials_catalog.json")


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


def _review_translation(
    analysis: InquiryAnalysis,
    session: ReviewSessionState,
    locale: Locale,
) -> ReviewTranslationBundle | None:
    if locale == "en":
        return None
    key = f"review_translation_{session.analysis_revision}_{locale}"
    payload = st.session_state.get(key)
    if payload:
        return ReviewTranslationBundle.model_validate_json(payload)
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    client = DeepSeekJsonClient(
        api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )
    try:
        with st.spinner("正在翻译当前分析，原始证据和专家决定保持不变……"):
            bundle = translate_items(
                client,
                target_locale=locale,
                analysis_revision=session.analysis_revision,
                items=collect_review_translation_items(analysis, session),
                protected_tokens=collect_review_translation_tokens(analysis, session),
            )
    except Exception:
        st.warning(text("translation.failed", locale))
        return None
    st.session_state[key] = bundle.model_dump_json()
    return bundle


def _translated(
    bundle: ReviewTranslationBundle | None,
    item_id: str,
    original: str,
) -> str:
    return bundle.texts.get(item_id, original) if bundle else original


def _email_language(workspace: ReviewWorkspace, locale: Locale) -> ReviewWorkspace:
    labels = {
        "en": text("draft.english", locale),
        "zh-CN": text("draft.chinese", locale),
    }
    selected = normalize_locale(
        st.selectbox(
            text("draft.language", locale),
            options=SUPPORTED_LOCALES,
            format_func=labels.__getitem__,
            index=SUPPORTED_LOCALES.index(workspace.email_language),
        )
    )
    if selected == workspace.email_language:
        return workspace
    follow_up_ids = _open_selected_follow_up_ids(workspace)
    matching = tuple(
        draft
        for draft in workspace.draft_versions
        if draft.language == selected
        and draft.authorized_decision == workspace.session.outcome.decision
        and (
            workspace.session.outcome.decision != "needs_information"
            or draft.follow_up_ids == follow_up_ids
        )
    )
    active_version = (
        max(matching, key=lambda draft: draft.version).version if matching else None
    )
    updated = workspace.model_copy(
        update={
            "email_language": selected,
            "active_draft_version": active_version,
        }
    )
    _save_workspace(updated)
    return updated


class _MetadataOnlyEmbedder:
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("Evidence generation checks must not calculate embeddings")


def _material_catalog_path() -> Path:
    return Path(
        os.environ.get(
            "CHEMICAL_TRADE_MATERIAL_CATALOG", str(DEFAULT_MATERIAL_CATALOG)
        )
    )


def _current_evidence_fingerprint() -> str:
    expected = material_catalog_fingerprint(
        load_material_catalog(_material_catalog_path())
    )
    with PageIndex(
        Path(os.environ.get("CHEMICAL_TRADE_DATABASE", str(DEFAULT_DATABASE))),
        embedder=_MetadataOnlyEmbedder(),
    ) as index:
        index.assert_catalog_fingerprint(expected)
    return expected


def _current_catalog_documents() -> tuple[CatalogDocumentRef, ...]:
    snapshot = enabled_catalog_snapshot(
        load_material_catalog(_material_catalog_path())
    )
    return tuple(
        CatalogDocumentRef(relative_path=path, sha256=digest)
        for path, digest in snapshot
    )


def _run_review(
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
    with PageIndex(
        Path(os.environ.get("CHEMICAL_TRADE_DATABASE", str(DEFAULT_DATABASE)))
    ) as index:
        index.assert_catalog_fingerprint(expected_fingerprint)
        analysis, card = analyze_and_review_inquiry(
            inquiry,
            index=index,
            planner=InquiryRetrievalPlanner(client),
            analyzer=DeepSeekInquiryAnalyzer(client),
            limit=3,
        )
    return analysis, card, expected_fingerprint


def _analysis_revision(
    inquiry: str, target_market: TargetMarket, fingerprint: str
) -> str:
    payload = f"{fingerprint}\0{target_market}\0{inquiry}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _clear_review_state() -> None:
    for key in (
        "review_workspace_json",
        "analysis_json",
        "analysis_catalog_fingerprint",
        "review_session_json",
        "active_review_inquiry",
        "review_decision_choice",
        "review_candidate_choice",
        "email_language",
        "_decision_widget_epoch",
    ):
        st.session_state.pop(key, None)
    for key in tuple(st.session_state):
        if str(key).startswith(
            (
                "email_draft_",
                "review_follow_up_",
                "review_candidate_choice_",
                "resolved_follow_up_",
                "reviewer_authorized_email",
                "review_translation_",
            )
        ):
            del st.session_state[key]


def _save_workspace(workspace: ReviewWorkspace) -> None:
    st.session_state["review_workspace_json"] = workspace.model_dump_json()
    for key in (
        "analysis_json",
        "analysis_catalog_fingerprint",
        "review_session_json",
        "active_review_inquiry",
        "email_language",
    ):
        st.session_state.pop(key, None)
    for key in tuple(st.session_state):
        if str(key).startswith(
            ("email_draft_", "review_follow_up_draft_", "reviewer_authorized_email_")
        ):
            del st.session_state[key]


def _load_workspace() -> ReviewWorkspace | None:
    payload = st.session_state.get("review_workspace_json")
    if payload:
        try:
            raw_workspace = json.loads(str(payload))
        except (json.JSONDecodeError, TypeError):
            _clear_review_state()
            return None
        if not isinstance(raw_workspace, Mapping):
            _clear_review_state()
            return None
        raw_workspace = dict(raw_workspace)
        raw_drafts = raw_workspace.get("draft_versions", [])
        if not isinstance(raw_drafts, list) or any(
            not isinstance(draft, Mapping) for draft in raw_drafts
        ):
            _clear_review_state()
            return None
        try:
            active_version = raw_workspace.get("active_draft_version")
            if active_version is not None:
                active = next(
                    (
                        draft
                        for draft in raw_drafts
                        if draft.get("version") == active_version
                    ),
                    None,
                )
                if (
                    active is not None
                    and active.get("authorized_decision") == "needs_information"
                    and active.get("follow_up_ids") is None
                ):
                    raw_workspace["active_draft_version"] = None
            workspace = ReviewWorkspace.model_validate(raw_workspace)
        except ValidationError:
            _clear_review_state()
            return None
        _save_workspace(workspace)
        return workspace

    analysis_payload = st.session_state.get("analysis_json")
    session_payload = st.session_state.get("review_session_json")
    if not analysis_payload or not session_payload:
        return None
    try:
        analysis = InquiryAnalysis.model_validate_json(analysis_payload)
        session = ReviewSessionState.model_validate_json(session_payload)
    except ValidationError:
        _clear_review_state()
        return None
    language = normalize_locale(st.session_state.get("email_language", "en"))
    decision = session.outcome.decision
    legacy_key: str | None = None
    if decision == "needs_information":
        legacy_key = f"review_follow_up_draft_{language}"
    elif decision == "proceed":
        if (
            analysis.recommendation_status == "supported"
            and analysis.recommended_product == session.outcome.selected_candidate
        ):
            legacy_key = f"email_draft_supported_{language}"
        else:
            legacy_key = f"reviewer_authorized_email_{language}"
    legacy_value = st.session_state.get(legacy_key) if legacy_key else None
    legacy_draft = str(legacy_value) if legacy_value else None
    try:
        workspace = ReviewWorkspace(
            inquiry=str(st.session_state.get("active_review_inquiry", session.card.inquiry)),
            target_market="unknown",
            catalog_fingerprint=str(
                st.session_state.get("analysis_catalog_fingerprint", "legacy-unknown")
            ),
            analysis=analysis,
            session=session,
            email_language=language,
        )
        if legacy_draft is not None and decision in {"proceed", "needs_information"}:
            presentation = (
                _follow_up_presentation(workspace)
                if decision == "needs_information"
                else None
            )
            workspace = ensure_authorized_draft(
                workspace,
                follow_up_presentation=presentation,
            )
            workspace = edit_active_draft(workspace, body=legacy_draft)
            if decision == "needs_information":
                workspace = ReviewWorkspace.model_validate(
                    {
                        **workspace.model_dump(),
                        "active_draft_version": None,
                    }
                )
    except (ValidationError, ValueError):
        _clear_review_state()
        return None
    _save_workspace(workspace)
    return workspace


def _email_client() -> DeepSeekJsonClient:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is not available in this process")
    return DeepSeekJsonClient(
        api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )


@st.dialog("How should this email be improved?")
def _email_optimization_dialog(
    workspace: ReviewWorkspace,
    locale: Locale,
    follow_up_presentation: FollowUpPresentation | None = None,
) -> None:
    instruction = st.text_area(
        text("draft.optimize_prompt", locale)
    )
    if not st.button(
        text("draft.generate_new_version", locale),
        type="primary",
    ):
        return
    try:
        optimized = optimize_authorized_draft(
            _email_client(),
            workspace,
            instruction,
            follow_up_presentation=follow_up_presentation,
        )
    except ValueError as error:
        st.error(_email_optimization_error_message(error, locale))
        return
    except Exception:
        st.error(
            "模型返回无效，工作区未更改。"
            if locale == "zh-CN"
            else "The model response was invalid. The workspace was not changed."
        )
        return
    _save_workspace(optimized)
    st.rerun()


def _email_optimization_error_message(error: ValueError, locale: Locale) -> str:
    message = str(error)
    if "does not change the active draft" in message:
        return (
            "该建议未改变草稿，因此没有创建新版本。"
            if locale == "zh-CN"
            else "The suggestion did not change the draft. No new version was created."
        )
    if "DEEPSEEK_API_KEY" in message:
        return (
            "当前进程未配置 API key，工作区未更改。"
            if locale == "zh-CN"
            else "The API key is not configured. The workspace was not changed."
        )
    return (
        "无法生成新版本，工作区未更改。"
        if locale == "zh-CN"
        else "A new version could not be generated. The workspace was not changed."
    )


def _draft_version_label(draft: EmailDraftVersion, locale: Locale) -> str:
    language = {
        "en": {"en": "English", "zh-CN": "Chinese"},
        "zh-CN": {"en": "英文", "zh-CN": "中文"},
    }[locale][draft.language]
    parts = (
        [f"版本 {draft.version}", language]
        if locale == "zh-CN"
        else [f"Version {draft.version}", language]
    )
    if draft.manually_edited:
        parts.append("已编辑" if locale == "zh-CN" else "Edited")
    return " · ".join(parts)


def _render_copy_button(editor_label: str, locale: Locale) -> None:
    st.html(
        build_copy_button_html(
            editor_label=editor_label,
            button_label=text("draft.copy", locale),
            copied_text=text("draft.copied", locale),
            missing_text=text("draft.editor_missing", locale),
        ),
        unsafe_allow_javascript=True,
    )


def _render_draft_controls(
    workspace: ReviewWorkspace,
    locale: Locale,
    follow_up_presentation: FollowUpPresentation | None = None,
) -> ReviewWorkspace:
    if authorized_active_draft(workspace) is None:
        workspace = ensure_authorized_draft(
            workspace,
            follow_up_presentation=follow_up_presentation,
        )
        _save_workspace(workspace)
    active = authorized_active_draft(workspace)
    if active is None:
        raise ValueError("No active authorized draft is available")
    compatible = tuple(
        draft.version
        for draft in workspace.draft_versions
        if draft.language == workspace.email_language
        and draft.authorized_decision == workspace.session.outcome.decision
        and (
            workspace.session.outcome.decision != "needs_information"
            or draft.follow_up_ids == active.follow_up_ids
        )
    )
    selected = st.selectbox(
        text("draft.version", locale),
        options=compatible,
        index=compatible.index(active.version),
        format_func=lambda version: _draft_version_label(
            next(draft for draft in workspace.draft_versions if draft.version == version),
            locale,
        ),
    )
    if selected != active.version:
        workspace = select_active_draft(workspace, selected)
        _save_workspace(workspace)
        st.rerun()
    if st.button(text("draft.optimize", locale)):
        _email_optimization_dialog(workspace, locale, follow_up_presentation)
    return workspace


def _follow_up_presentation(
    workspace: ReviewWorkspace,
) -> FollowUpPresentation | None:
    if workspace.email_language != "zh-CN":
        return None
    selected = set(workspace.session.outcome.selected_follow_ups)
    open_selected = tuple(
        item
        for item in open_follow_ups(workspace)
        if item.question in selected
    )
    return FollowUpPresentation(
        analysis_revision=workspace.session.analysis_revision,
        target_locale="zh-CN",
        intents={
            item.item_id: classify_follow_up_intent(item.question)
            for item in open_selected
        },
    )


def _save_manual_body(workspace: ReviewWorkspace, body: str) -> ReviewWorkspace:
    active = authorized_active_draft(workspace)
    if active is None or body == active.body:
        return workspace
    updated = edit_active_draft(workspace, body=body)
    _save_workspace(updated)
    return updated


def _open_selected_follow_up_ids(workspace: ReviewWorkspace) -> tuple[str, ...]:
    selected = set(workspace.session.outcome.selected_follow_ups)
    return tuple(
        item.item_id
        for item in open_follow_ups(workspace)
        if item.question in selected
    )


def _apply_workspace_decision(
    workspace: ReviewWorkspace,
    exit_name: str,
    *,
    selected_candidate: str | None = None,
    selected_follow_up_ids: tuple[str, ...] = (),
) -> ReviewWorkspace:
    return apply_workspace_decision(
        workspace,
        exit_name,  # type: ignore[arg-type]
        selected_candidate=selected_candidate,
        selected_follow_up_ids=selected_follow_up_ids,
    )


def _decision_widget_scope(workspace: ReviewWorkspace, widget_epoch: int) -> str:
    payload = json.dumps(
        {
            "analysis_revision": workspace.session.analysis_revision,
            "outcome": workspace.session.outcome.model_dump(mode="json"),
            "resolved_follow_up_ids": workspace.resolved_follow_up_ids,
            "widget_epoch": widget_epoch,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def _store_review_result(
    inquiry: str,
    target_market: TargetMarket,
    analysis: InquiryAnalysis,
    card: TechnicalReviewCard,
    fingerprint: str,
) -> None:
    session = start_review_session(
        card,
        analysis_revision=_analysis_revision(inquiry, target_market, fingerprint),
    )
    _clear_review_state()
    _save_workspace(
        ReviewWorkspace(
            inquiry=inquiry,
            target_market=target_market,
            catalog_fingerprint=fingerprint,
            analysis=analysis,
            session=session,
        )
    )


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
    materials_root = Path(
        os.environ.get("CHEMICAL_TRADE_MATERIALS_ROOT", str(DEFAULT_MATERIALS_ROOT))
    )
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
        st.markdown(
            f"**{rendered.source_file}**  \n"
            f"{rendered.product} · {physical_page} · "
            f"{rendered.date_revision} · {rendered.jurisdiction}"
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
        st.html(
            build_zoomable_page_html(
                rendered.png_bytes,
                alt_text=alt_text,
                source_metadata=source_metadata,
            ),
            unsafe_allow_javascript=True,
        )
        if st.button(
            f"Open original PDF page {rendered.page_number}",
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


def _render_readiness(analysis: InquiryAnalysis, locale: Locale) -> None:
    view = build_analysis_view(analysis)
    st.subheader(text("readiness.title", locale))
    customer, internal = st.columns(2, gap="large")
    with customer:
        st.markdown(f"**{text('readiness.customer', locale)}**")
        items = "".join(
            f"<li>{html.escape(view_text(question, locale))}</li>" for question in view.customer_questions
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


def _render_email(workspace: ReviewWorkspace, locale: Locale) -> None:
    with st.container(key="ctc_email_layout"):
        main_column, side_column = st.columns([3, 1])
        with side_column:
            workspace = _email_language(workspace, locale)
            workspace = _render_draft_controls(workspace, locale)
            _render_open_gap_count(workspace, locale)
        with main_column:
            language = workspace.email_language
            active = authorized_active_draft(workspace)
            if active is None:
                raise ValueError("No active authorized draft is available")
            st.text_input(
                text("draft.subject", locale),
                value=active.subject,
                disabled=True,
            )
            st.subheader(
                text(
                    "draft.chinese_reply"
                    if language == "zh-CN"
                    else "draft.english_reply",
                    locale,
                )
            )
            st.caption(text("draft.caption", locale))
            editor_label = text(
                "draft.chinese_email"
                if language == "zh-CN"
                else "draft.english_email",
                locale,
            )
            edited_body = st.text_area(
                editor_label,
                value=active.body,
                height=310,
            )
            _save_manual_body(workspace, edited_body)
            _render_copy_button(editor_label, locale)


def _render_follow_up_draft(
    workspace: ReviewWorkspace,
    locale: Locale,
) -> None:
    with st.container(key="ctc_email_layout"):
        main_column, side_column = st.columns([3, 1])
        with side_column:
            workspace = _email_language(workspace, locale)
            try:
                presentation = _follow_up_presentation(workspace)
                workspace = _render_draft_controls(workspace, locale, presentation)
            except ValueError:
                st.warning(text("translation.failed", locale))
                return
            _render_open_gap_count(workspace, locale)
        with main_column:
            active = authorized_active_draft(workspace)
            if active is None:
                st.warning(text("review.select_followup", locale))
                return
            st.text_input(
                text("draft.subject", locale),
                value=active.subject,
                disabled=True,
            )
            st.subheader(text("draft.followup_title", locale))
            st.caption(text("draft.followup_caption", locale))
            editor_label = text("draft.followup_label", locale)
            edited_body = st.text_area(
                editor_label,
                value=active.body,
                height=360,
            )
            _save_manual_body(workspace, edited_body)
            _render_copy_button(editor_label, locale)


def _render_reviewer_authorized_draft(
    workspace: ReviewWorkspace,
    locale: Locale,
) -> None:
    session = workspace.session
    selected = session.outcome.selected_candidate
    candidate = next(
        item for item in session.card.internal_candidates if item.product == selected
    )
    with st.container(key="ctc_email_layout"):
        main_column, side_column = st.columns([3, 1])
        with side_column:
            workspace = _email_language(workspace, locale)
            workspace = _render_draft_controls(workspace, locale)
            _render_open_gap_count(workspace, locale)
        with main_column:
            language = workspace.email_language
            st.html('<div class="ctc-eyebrow">Reviewer authorized</div>')
            st.header(candidate.product)
            st.html(
                '<div class="ctc-warning"><b>Manual expert decision.</b> The automated '
                "analysis did not establish a supported product recommendation. This "
                "draft uses only the reviewer-selected candidate and its disclosed "
                "limitations.</div>"
            )
            active = authorized_active_draft(workspace)
            if active is None:
                raise ValueError("No active authorized draft is available")
            st.text_input(
                text("draft.subject", locale),
                value=active.subject,
                disabled=True,
            )
            st.subheader(
                text(
                    "draft.chinese_reply"
                    if language == "zh-CN"
                    else "draft.english_reply",
                    locale,
                )
            )
            st.caption(text("draft.caption", locale))
            editor_label = text(
                "draft.chinese_email"
                if language == "zh-CN"
                else "draft.english_email",
                locale,
            )
            edited_body = st.text_area(
                editor_label,
                value=active.body,
                height=310,
            )
            _save_manual_body(workspace, edited_body)
            _render_copy_button(editor_label, locale)


def _render_step_navigation(
    workspace: ReviewWorkspace,
    locale: Locale,
) -> None:
    with st.container(key="ctc_steps"):
        columns = st.columns(len(REVIEW_PAGES))
        for index, page in enumerate(REVIEW_PAGES, start=1):
            with columns[index - 1]:
                if st.button(
                    f"**{index:02d}**  \n{text(f'page.{page}', locale)}",
                    key=f"nav_{page}",
                    type="primary" if page == workspace.current_page else "secondary",
                    use_container_width=True,
                ):
                    _save_workspace(set_current_page(workspace, page))
                    st.rerun()


def _render_inquiry_page(
    workspace: ReviewWorkspace,
    locale: Locale,
    bundle: ReviewTranslationBundle | None,
) -> None:
    card = workspace.session.card
    st.write(workspace.inquiry)
    st.caption(text(f"market.{workspace.target_market}", locale))
    st.subheader(text("review.facts", locale))
    if card.facts:
        for fact in card.facts:
            category = text(f"category.{fact.category}", locale)
            st.markdown(
                f"- **{category} · {text('status.inquiry_explicit', locale)}:** "
                f"{fact.text}"
            )
    else:
        st.caption(text("review.no_facts", locale))
    if card.ambiguities:
        st.subheader(text("review.ambiguities", locale))
        for index, ambiguity in enumerate(card.ambiguities):
            impact = _translated(
                bundle, f"card.ambiguity.{index}.impact", ambiguity.impact
            )
            st.markdown(f"**{ambiguity.original_text}** — {impact}")


def _render_open_gap_count(workspace: ReviewWorkspace, locale: Locale) -> None:
    count = len(open_follow_ups(workspace))
    if locale == "zh-CN":
        st.caption(f"{count} 个未关闭缺口")
    else:
        st.caption(f"{count} open gap{'s' if count != 1 else ''}")


def _render_conclusion_page(
    workspace: ReviewWorkspace,
    locale: Locale,
) -> None:
    analysis = workspace.analysis
    view = build_analysis_view(analysis)
    if analysis.recommended_product:
        st.header(analysis.recommended_product)
    st.subheader(view_text(view.headline, locale))
    st.write(
        text("result.supported_description", locale)
        if analysis.recommendation_status == "supported"
        else view_text(analysis.summary_zh, locale)
    )
    _render_open_gap_count(workspace, locale)
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
        text(
            "result.next_action",
            locale,
            value=view_text(view.next_action, locale),
        )
    )


def _render_gaps_page(
    workspace: ReviewWorkspace,
    locale: Locale,
    bundle: ReviewTranslationBundle | None,
) -> None:
    card = workspace.session.card
    _render_open_gap_count(workspace, locale)
    st.subheader(text("review.limits", locale))
    for requirement in card.requirement_reviews:
        category = text(f"category.{requirement.category}", locale)
        st.markdown(
            f"- **{category} · {requirement.status.replace('_', ' ').title()}:** "
            f"{requirement.requirement}"
        )
    for index, limitation in enumerate(card.evidence_limitations):
        value = _translated(bundle, f"card.limit.{index}", limitation)
        st.html(f'<div class="ctc-warning">{html.escape(value)}</div>')
    st.subheader(text("review.followups", locale))
    if card.follow_ups:
        for follow_up in card.follow_ups:
            question = _translated(
                bundle, f"card.followup.{follow_up.item_id}", follow_up.question
            )
            category = text(f"category.{follow_up.category}", locale)
            resolved = follow_up.item_id in workspace.resolved_follow_up_ids
            checked = st.checkbox(
                f"{category} · "
                f"{follow_up.suggested_priority.replace('_', ' ').title()}: "
                f"{question}",
                value=resolved,
                key=(
                    f"resolved_follow_up_{workspace.session.analysis_revision}_"
                    f"{follow_up.item_id}"
                ),
            )
            if checked != resolved:
                updated = set_resolved_follow_up(
                    workspace,
                    follow_up.item_id,
                    resolved=checked,
                )
                _save_workspace(updated)
                st.rerun()
    else:
        st.caption(text("review.no_followups", locale))
    if workspace.analysis.next_action == "needs_commercial_input":
        _render_readiness(workspace.analysis, locale)


def _render_evidence_page(
    workspace: ReviewWorkspace,
    locale: Locale,
    bundle: ReviewTranslationBundle | None,
) -> None:
    card = workspace.session.card
    st.subheader(text("review.candidates", locale))
    if card.internal_candidates:
        for candidate_index, candidate in enumerate(card.internal_candidates):
            support = _translated(
                bundle,
                f"card.candidate.{candidate_index}.support",
                candidate.support_statement,
            )
            st.markdown(
                f"**{candidate.product}** · {text('review.internal_candidate', locale)}"
            )
            st.caption(support)
            for evidence in candidate.evidence:
                st.markdown(
                    f"{evidence.document_type} · **{evidence.source_file}** · "
                    f"{text('review.physical_page', locale, page=evidence.page_number)} · "
                    f"{evidence.date_revision} · {evidence.jurisdiction}"
                )
    else:
        st.caption(text("review.no_candidate", locale))
    _render_verified_parameters(workspace.analysis, locale)
    _render_sources(workspace.analysis, locale)


def _render_decision_page(
    workspace: ReviewWorkspace,
    locale: Locale,
    bundle: ReviewTranslationBundle | None,
) -> None:
    session = workspace.session
    card = session.card
    widget_epoch = st.session_state.get("_decision_widget_epoch", 0)
    if not isinstance(widget_epoch, int) or widget_epoch < 0:
        widget_epoch = 0
    widget_scope = _decision_widget_scope(workspace, widget_epoch)
    available_follow_ups = open_follow_ups(workspace)
    selected_questions = set(session.outcome.selected_follow_ups)
    selected_follow_up_ids = tuple(
        follow_up.item_id
        for follow_up in available_follow_ups
        if st.checkbox(
            _translated(
                bundle,
                f"card.followup.{follow_up.item_id}",
                follow_up.question,
            ),
            value=follow_up.question in selected_questions,
            key=f"review_follow_up_{widget_scope}_{follow_up.item_id}",
        )
    )
    evidence_candidates = tuple(
        candidate for candidate in card.internal_candidates if candidate.evidence
    )
    candidate_options = tuple(candidate.product for candidate in evidence_candidates)
    selected_candidate = st.selectbox(
        text("review.candidate", locale),
        options=candidate_options,
        index=(
            candidate_options.index(session.outcome.selected_candidate)
            if session.outcome.selected_candidate in candidate_options
            else None
        ),
        placeholder=text("review.candidate_placeholder", locale),
        key=f"review_candidate_choice_{widget_scope}",
        disabled=not candidate_options,
    )
    chosen_exit: str | None = None
    if st.button(
        text("decision.exit.ask_customer", locale),
        type="primary",
        use_container_width=True,
        disabled=not available_follow_ups,
    ):
        chosen_exit = "ask_customer"
    second_row = st.columns(2)
    with second_row[0]:
        if st.button(
            text("decision.exit.save_only", locale),
            use_container_width=True,
        ):
            chosen_exit = "save_only"
    with second_row[1]:
        if st.button(
            text("decision.exit.technical_reply", locale),
            use_container_width=True,
            disabled=not evidence_candidates,
        ):
            chosen_exit = "technical_reply"
    if not available_follow_ups:
        st.caption(text("decision.gate.no_open_questions", locale))
    if not evidence_candidates:
        st.caption(text("decision.gate.no_evidence_candidate", locale))
    if chosen_exit is not None:
        try:
            updated = _apply_workspace_decision(
                workspace,
                chosen_exit,
                selected_candidate=(
                    selected_candidate if chosen_exit == "technical_reply" else None
                ),
                selected_follow_up_ids=(
                    selected_follow_up_ids if chosen_exit == "ask_customer" else ()
                ),
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _save_workspace(updated)
            st.session_state["_decision_widget_epoch"] = widget_epoch + 1
            st.rerun()
    if session.outcome.decision == "pending":
        st.info(text("review.pending_info", locale))
    elif session.outcome.decision == "needs_information":
        if not session.outcome.can_generate_follow_up_draft:
            st.info(text("review.select_followup", locale))
    elif session.outcome.decision == "do_not_recommend":
        st.warning(text("review.do_not_recommend", locale))


def _render_email_page(
    workspace: ReviewWorkspace,
    locale: Locale,
) -> None:
    try:
        validate_workspace_decision(workspace)
    except ValueError:
        st.warning(text("review.pending_info", locale))
        return
    session = workspace.session
    analysis = workspace.analysis
    _render_open_gap_count(workspace, locale)
    if session.outcome.decision == "pending":
        st.info(text("review.pending_info", locale))
    elif session.outcome.decision == "proceed":
        if not session.outcome.can_generate_external_recommendation:
            st.info(text("review.pending_info", locale))
        elif (
            analysis.recommendation_status == "supported"
            and analysis.recommended_product == session.outcome.selected_candidate
        ):
            _render_email(workspace, locale)
        else:
            _render_reviewer_authorized_draft(workspace, locale)
    elif session.outcome.decision == "needs_information":
        selected = set(session.outcome.selected_follow_ups)
        if session.outcome.can_generate_follow_up_draft and any(
            item.question in selected for item in open_follow_ups(workspace)
        ):
            _render_follow_up_draft(workspace, locale)
        else:
            st.info(text("review.select_followup", locale))
    else:
        st.warning(text("review.do_not_recommend", locale))


def _print_decision_label(workspace: ReviewWorkspace, locale: Locale) -> str:
    labels = {
        "pending": text("decision.pending", locale),
        "needs_information": text("decision.exit.ask_customer", locale),
        "do_not_recommend": text("decision.exit.save_only", locale),
        "proceed": text("decision.exit.technical_reply", locale),
    }
    return labels[workspace.session.outcome.decision]


def _print_review_markup(workspace: ReviewWorkspace, locale: Locale) -> str:
    escape = html.escape
    analysis = workspace.analysis
    revision = escape(workspace.session.analysis_revision)
    completed = (
        workspace.completed_at.isoformat()
        if workspace.completed_at is not None
        else text("print.live", locale)
    )
    parameters = "".join(
        "<tr>"
        f"<td>{escape(item.name)}</td>"
        f"<td>{escape(item.value)} {escape(item.unit)}</td>"
        f"<td>{escape(item.conditions)}</td>"
        f"<td>{escape(item.test_method)}</td>"
        "</tr>"
        for item in analysis.key_parameters
    ) or f'<tr><td colspan="4">{escape(text("print.no_parameters", locale))}</td></tr>'
    citations = {
        (citation.product, citation.source_file, citation.page_number)
        for requirement in analysis.requirements
        for citation in requirement.evidence
    }
    citations.update(
        (item.citation.product, item.citation.source_file, item.citation.page_number)
        for item in analysis.key_parameters
    )
    evidence = "".join(
        f"<li>{escape(product)} — {escape(source)} — Physical page {page}</li>"
        for product, source, page in sorted(citations)
    ) or f'<li>{escape(text("print.no_evidence", locale))}</li>'
    resolved = set(workspace.resolved_follow_up_ids)
    gaps = "".join(
        f'<li>{escape(text("state.closed" if item.item_id in resolved else "state.open", locale))}: '
        f"{escape(item.question)}</li>"
        for item in workspace.session.card.follow_ups
    ) or f'<li>{escape(text("print.no_gaps", locale))}</li>'
    internal = f"""
<section class="ctc-print-sheet">
  <div class="ctc-print-meta"><span>{escape(text("page.record", locale))} {revision}</span><span>{escape(completed)}</span><span>{escape(text("print.page", locale, page=1))}</span></div>
  <h2>{escape(text("print.internal_title", locale))}</h2>
  <h3>{escape(text("print.inquiry", locale))}</h3><p>{escape(workspace.inquiry)}</p>
  <h3>{escape(text("print.conclusion", locale))}</h3><p>{escape(analysis.summary_zh)}</p>
  <h3>{escape(text("print.parameters", locale))}</h3>
  <table><thead><tr><th>{escape(text("print.parameter", locale))}</th><th>{escape(text("print.value", locale))}</th><th>{escape(text("print.conditions", locale))}</th><th>{escape(text("print.method", locale))}</th></tr></thead><tbody>{parameters}</tbody></table>
  <h3>{escape(text("print.evidence", locale))}</h3><ul>{evidence}</ul>
  <h3>{escape(text("print.gaps", locale))}</h3><ul>{gaps}</ul>
  <h3>{escape(text("print.decision", locale))}</h3><p>{escape(_print_decision_label(workspace, locale))}</p>
  <p class="ctc-print-signoff">{escape(text("print.reviewer", locale))}: ____________________ &nbsp; {escape(text("print.date", locale))}: ____________</p>
</section>
""".strip()
    draft = authorized_active_draft(workspace)
    if draft is None:
        return f'<div class="ctc-print-preview">{internal}</div>'
    language = text("draft.english" if draft.language == "en" else "draft.chinese", locale)
    edited = f" · {text('draft.edited', locale)}" if draft.manually_edited else ""
    customer = f"""
<section class="ctc-print-sheet">
  <div class="ctc-print-meta"><span>{escape(text("page.record", locale))} {revision}</span><span>{escape(completed)}</span><span>{escape(text("print.page", locale, page=2))}</span></div>
  <h2>{escape(text("print.customer_email", locale))}</h2>
  <p>{escape(text("print.email_version", locale, version=draft.version, language=language, edited=edited))}</p>
  <h3>{escape(draft.subject)}</h3>
  <div class="ctc-print-email">{escape(draft.body)}</div>
</section>
""".strip()
    return f'<div class="ctc-print-preview">{internal}\n{customer}</div>'


def _render_print_page(workspace: ReviewWorkspace, locale: Locale) -> None:
    st.components.v1.html(
        build_print_button_html(text("print.action", locale)),
        height=52,
    )
    st.markdown(_print_review_markup(workspace, locale), unsafe_allow_html=True)


def _review_backup_payload(workspace: ReviewWorkspace) -> str:
    return export_review_backup(workspace, _current_catalog_documents())


def _render_backup_download(
    workspace: ReviewWorkspace,
    locale: Locale,
) -> None:
    st.download_button(
        text("backup.save", locale),
        data=_review_backup_payload(workspace),
        file_name=f"chemical-review-{workspace.session.analysis_revision[:12]}.json",
        mime="application/json",
    )


def _render_record_page(workspace: ReviewWorkspace, locale: Locale) -> None:
    summary = record_summary(workspace)
    open_gap_count = len(open_follow_ups(workspace))
    open_gap_label = (
        f"{open_gap_count} 个未关闭缺口"
        if locale == "zh-CN"
        else f"{open_gap_count} open gap{'s' if open_gap_count != 1 else ''}"
    )
    source_count = len(
        {
            (citation.source_file, citation.page_number)
            for requirement in workspace.analysis.requirements
            for citation in requirement.evidence
        }
    )
    status = text(
        "record.in_progress" if workspace.completed_at is None else "record.completed",
        locale,
    )
    completed = (
        text("record.current_session", locale)
        if workspace.completed_at is None
        else workspace.completed_at.isoformat()
    )
    record_markup = f"""
<article class="ctc-record">
  <header class="ctc-record-head">
    <span>{html.escape(text("record.status", locale))}</span>
    <strong>{html.escape(status)}</strong>
  </header>
  <section>
    <dl>
      <dt>{html.escape(text("record.decision", locale))}</dt><dd>{html.escape(_print_decision_label(workspace, locale))}</dd>
      <dt>{html.escape(text("record.open_gaps", locale))}</dt><dd>{html.escape(open_gap_label)}</dd>
      <dt>{html.escape(text("record.email_version", locale))}</dt><dd>{html.escape(summary.email_version or text("record.none", locale))}</dd>
    </dl>
  </section>
  <section>
    <dl>
      <dt>{html.escape(text("record.analysis_revision", locale))}</dt><dd>{html.escape(summary.analysis_revision)}</dd>
      <dt>{html.escape(text("record.sources", locale))}</dt><dd>{source_count}</dd>
      <dt>{html.escape(text("record.saved_at", locale))}</dt><dd>{html.escape(completed)}</dd>
    </dl>
  </section>
</article>
""".strip()
    st.markdown(
        record_markup,
        unsafe_allow_html=True,
    )
    if workspace.completed_at is None:
        _render_backup_download(workspace, locale)
        if st.button(text("record.complete", locale), type="primary"):
            try:
                completed = finalize_workspace(
                    workspace,
                    completed_at=datetime.now().astimezone(),
                )
            except ValueError as error:
                st.error(str(error))
            else:
                _save_workspace(completed)
                st.rerun()
        return
    st.success(
        f"{text('record.completed', locale)} · {workspace.completed_at.isoformat()}"
    )
    if st.button(text("record.print", locale)):
        _save_workspace(set_current_page(workspace, "print"))
        st.rerun()
    _render_backup_download(workspace, locale)
    if st.button(text("action.new", locale), key="completed_new_inquiry"):
        _clear_review_state()
        st.session_state["inquiry"] = ""
        st.rerun()


def _render_completed_read_only_page(
    workspace: ReviewWorkspace,
    locale: Locale,
) -> None:
    st.info(text("record.read_only", locale))
    page = workspace.current_page
    if page == "inquiry":
        st.write(workspace.inquiry)
    elif page == "conclusion":
        _render_conclusion_page(workspace, locale)
    elif page == "gaps":
        resolved = set(workspace.resolved_follow_up_ids)
        for item in workspace.session.card.follow_ups:
            state = text(
                "state.closed" if item.item_id in resolved else "state.open",
                locale,
            )
            st.write(f"{state}: {item.question}")
    elif page == "evidence":
        bundle = _review_translation(workspace.analysis, workspace.session, locale)
        _render_evidence_page(workspace, locale, bundle)
    elif page == "decision":
        st.write(_print_decision_label(workspace, locale))
    elif page == "email":
        draft = authorized_active_draft(workspace)
        if draft is None:
            st.write(text("record.no_email", locale))
        else:
            st.write(f"{draft.subject} · {draft.version} · {draft.language}")
            st.code(draft.body)


def _render_review_page(workspace: ReviewWorkspace, locale: Locale) -> None:
    st.title(text(f"page_title.{workspace.current_page}", locale))
    if workspace.current_page == "conclusion":
        _render_conclusion_page(workspace, locale)
        return
    if workspace.current_page == "record":
        _render_record_page(workspace, locale)
        return
    if workspace.current_page == "print":
        _render_print_page(workspace, locale)
        return
    if workspace.current_page == "email":
        if workspace.completed_at is not None:
            _render_completed_read_only_page(workspace, locale)
            return
        _render_email_page(workspace, locale)
        return
    if workspace.completed_at is not None:
        _render_completed_read_only_page(workspace, locale)
        return
    bundle = _review_translation(workspace.analysis, workspace.session, locale)
    if workspace.current_page == "inquiry":
        _render_inquiry_page(workspace, locale, bundle)
    elif workspace.current_page == "gaps":
        _render_gaps_page(workspace, locale, bundle)
    elif workspace.current_page == "evidence":
        _render_evidence_page(workspace, locale, bundle)
    elif workspace.current_page == "decision":
        _render_decision_page(workspace, locale, bundle)


def _render_entry_content(locale: Locale) -> None:
    pending_inputs = st.session_state.pop("review_backup_pending_inputs", None)
    if pending_inputs is not None:
        st.session_state["inquiry"] = pending_inputs[0]
        st.session_state["target_market"] = pending_inputs[1]
    st.html(f'<div class="ctc-eyebrow">{html.escape(text("entry.eyebrow", locale))}</div>')
    st.title(text("entry.title", locale))
    st.write(text("entry.description", locale))
    if not os.environ.get("DEEPSEEK_API_KEY"):
        st.info(text("entry.api_key_missing", locale))
    notice = st.session_state.pop("review_backup_notice", None)
    if notice == "changed":
        st.warning(text("backup.changed", locale))
    st.text_area(
        text("entry.inquiry", locale),
        key="inquiry",
        height=190,
        placeholder=text("entry.placeholder", locale),
    )
    target_market = st.selectbox(
        text("entry.target_market", locale),
        options=TARGET_MARKETS,
        format_func=lambda code: text(f"market.{code}", locale),
        key="target_market",
    )
    st.caption(text("entry.help", locale))
    if st.button(text("entry.analyze", locale), type="primary"):
        inquiry = st.session_state.get("inquiry", "")
        if not inquiry.strip():
            st.error(text("entry.empty", locale))
            return
        try:
            with st.spinner("Validating technical documents and evidence guardrails..."):
                analysis, card, fingerprint = _run_review(inquiry)
        except Exception:
            st.error(text("entry.failed", locale))
            return
        _store_review_result(inquiry, target_market, analysis, card, fingerprint)
        st.rerun()
    if st.button(text("backup.open", locale)):
        st.session_state["review_backup_open"] = not bool(
            st.session_state.get("review_backup_open", False)
        )
    if st.session_state.get("review_backup_open", False):
        uploaded = st.file_uploader(text("backup.file", locale), type=("json",))
        if uploaded is not None:
            try:
                result = import_review_backup(
                    uploaded.getvalue(),
                    _current_catalog_documents(),
                )
                current_fingerprint = _current_evidence_fingerprint()
            except (UnicodeError, ValueError, ValidationError):
                st.error(text("backup.invalid", locale))
            else:
                restored = result.workspace
                if (
                    restored is not None
                    and restored.catalog_fingerprint == current_fingerprint
                ):
                    _save_workspace(restored)
                    st.session_state["review_backup_open"] = False
                    st.rerun()
                else:
                    _clear_review_state()
                    st.session_state["review_backup_pending_inputs"] = (
                        result.inquiry,
                        result.target_market,
                    )
                    st.session_state["review_backup_open"] = False
                    st.session_state["review_backup_notice"] = "changed"
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
    legacy_analysis = st.session_state.get("analysis_json")
    legacy_session = st.session_state.get("review_session_json")
    if legacy_analysis and not legacy_session:
        _clear_review_state()
        st.warning(
            "This result predates the technical-review workflow and was cleared. "
            "Analyze the inquiry again."
        )
        _render_entry(locale)
        return
    workspace = _load_workspace()
    if workspace:
        try:
            current_fingerprint = _current_evidence_fingerprint()
        except (FileNotFoundError, ValueError):
            _clear_review_state()
            st.error(
                "The approved catalog and evidence index are not synchronized. "
                "The cached result was cleared."
            )
            _render_entry(locale)
            return
        if workspace.catalog_fingerprint != current_fingerprint:
            _clear_review_state()
            st.warning(
                "This result no longer matches the approved evidence generation and "
                "was cleared. Analyze the inquiry again."
            )
            _render_entry(locale)
            return
    if not workspace:
        _render_entry(locale)
        st.caption(
            text(
                "entry.footer",
                locale,
                scope=evidence_scope_caption(_material_catalog_path()),
            )
        )
        return
    if workspace.completed_at is None and st.button(text("action.new", locale)):
        _clear_review_state()
        st.session_state["inquiry"] = ""
        st.rerun()
    if (
        workspace.completed_at is None
        and workspace.current_page != "decision"
        and st.button(
        text("action.reanalyze", locale)
        )
    ):
        inquiry = workspace.inquiry
        target_market = workspace.target_market
        _clear_review_state()
        try:
            with st.spinner(text("entry.spinner", locale)):
                analysis, card, fingerprint = _run_review(inquiry)
        except Exception:
            st.error(
                "The analysis could not be completed safely. Check the local API and "
                "index configuration, then try again. The previous review approval "
                "was cleared."
            )
            return
        _store_review_result(
            inquiry, target_market, analysis, card, fingerprint
        )
        st.rerun()
    if workspace.session.card.inquiry != workspace.inquiry:
        _clear_review_state()
        st.warning("The inquiry changed, so the previous review decision was cleared.")
        _render_entry(locale)
        return
    _render_step_navigation(workspace, locale)
    with st.container(key="ctc_review_sheet"):
        _render_review_page(workspace, locale)
    st.divider()
    st.caption(evidence_scope_caption(_material_catalog_path()))


if __name__ == "__main__":
    main()
