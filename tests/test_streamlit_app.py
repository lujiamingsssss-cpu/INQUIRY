import ast
import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from chemical_trade_copilot import evidence_viewer, pdf_pages
from chemical_trade_copilot.inquiry_analysis import (
    InquiryAnalysis,
    KeyParameter,
    RequirementAssessment,
    SourceCitation,
)
from chemical_trade_copilot.materials import (
    enabled_catalog_snapshot,
    evidence_scope_caption,
    load_material_catalog,
    material_catalog_fingerprint,
)
from chemical_trade_copilot.inquiry_review import (
    ReviewSessionState,
    apply_session_decision,
    build_review_card,
    start_review_session,
)
from chemical_trade_copilot.retrieval import SearchResult
from chemical_trade_copilot.review_workspace import (
    CatalogDocumentRef,
    EmailDraftVersion,
    REVIEW_PAGES,
    ReviewWorkspace,
    export_review_backup,
    set_resolved_follow_up,
)
from chemical_trade_copilot.review_translation import ReviewTranslationBundle
from chemical_trade_copilot.ui_components import APP_CSS


APP = Path(__file__).parents[1] / "src" / "chemical_trade_copilot" / "streamlit_app.py"
CATALOG = Path(__file__).parents[1] / "materials_catalog.json"


def _current_fingerprint() -> str:
    return material_catalog_fingerprint(load_material_catalog(CATALOG))


def _supported_json() -> str:
    citation = SourceCitation(
        product="EPON Resin 8280",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        page_number=3,
    )
    analysis = InquiryAnalysis(
        summary_zh="技术条件有证据。",
        recommendation_status="supported",
        recommended_product="EPON Resin 8280",
        recommendation_reasons=("指定固化体系有证据。",),
        requirements=(
            RequirementAssessment(
                category="technical",
                requirement="MPDA HDT",
                status="supported",
                evidence=(citation,),
            ),
        ),
        key_parameters=(
            KeyParameter(
                name="Heat Deflection Temperature",
                value="156",
                unit="°C",
                conditions="Cured system",
                test_method="ASTM D648",
                curing_agent="MPDA",
                mix_ratio="100 pbw : 14.4 pbw",
                cure_schedule="2 h/80°C + 2 h/150°C",
                citation=citation,
            ),
        ),
        evidence_gaps=("Commercial facts require confirmation.",),
        source_limitations=("TDS revision is 2016.",),
        follow_up_questions=(
            "Confirm quantity and destination.",
            "Is 120°C continuous, intermittent, or a short peak?",
            "Which target-market documents are required?",
            "Does three weeks mean ready, shipped, or delivered?",
        ),
        next_action="needs_commercial_input",
    )
    return analysis.model_dump_json()


def _review_session_json(
    decision: str = "pending",
    *,
    analysis: InquiryAnalysis | None = None,
    inquiry: str = "EPON Resin 8280 with MPDA and CFR Santos",
) -> str:
    analysis = analysis or InquiryAnalysis.model_validate_json(_supported_json())
    ranked = SearchResult(
        text="EPON Resin 8280 high solids coating evidence",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        source_path=Path("G:/materials/EPON/TDS.pdf"),
        page_number=3,
        distance=0.1,
        date_revision="2016",
        jurisdiction="Technical data sheet · jurisdiction not stated",
    )
    card = build_review_card(inquiry, analysis, [ranked])
    session = start_review_session(card, analysis_revision="review-1")
    if decision == "proceed":
        session = apply_session_decision(
            session,
            "proceed",
            selected_candidate="EPON Resin 8280",
        )
    elif decision == "needs_information":
        session = apply_session_decision(
            session,
            "needs_information",
            selected_follow_up_ids=(card.follow_ups[0].item_id,),
        )
    elif decision == "do_not_recommend":
        session = apply_session_decision(session, "do_not_recommend")
    return session.model_dump_json()


def _workspace_json(
    decision: str = "pending",
    *,
    analysis: InquiryAnalysis | None = None,
    inquiry: str = "EPON Resin 8280 with MPDA and CFR Santos",
    target_market: str = "unknown",
    fingerprint: str | None = None,
) -> str:
    analysis = analysis or InquiryAnalysis.model_validate_json(_supported_json())
    return ReviewWorkspace(
        inquiry=inquiry,
        target_market=target_market,
        catalog_fingerprint=fingerprint or _current_fingerprint(),
        analysis=analysis,
        session=ReviewSessionState.model_validate_json(
            _review_session_json(decision, analysis=analysis, inquiry=inquiry)
        ),
    ).model_dump_json()


def _workspace(app: AppTest) -> ReviewWorkspace:
    return ReviewWorkspace.model_validate_json(
        app.session_state["review_workspace_json"]
    )


def _review_app(
    decision: str = "pending",
    *,
    page: str = "conclusion",
    email_version: int | None = None,
) -> AppTest:
    app = AppTest.from_file(str(APP)).run(timeout=30)
    workspace = ReviewWorkspace.model_validate_json(_workspace_json(decision))
    if email_version is not None:
        from chemical_trade_copilot.review_email import ensure_authorized_draft
        from chemical_trade_copilot.review_workspace import edit_active_draft

        if decision not in {"proceed", "needs_information"}:
            raise ValueError("An email version requires an authorizing decision")
        workspace = ensure_authorized_draft(workspace)
        workspace = edit_active_draft(
            workspace,
            body="Existing customer draft",
        )
        draft = workspace.draft_versions[0].model_copy(update={"version": email_version})
        workspace = ReviewWorkspace.model_validate(
            {
                **workspace.model_dump(),
                "draft_versions": (draft.model_dump(),),
                "active_draft_version": email_version,
            }
        )
    workspace = workspace.model_copy(update={"current_page": page})
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.session_state["inquiry"] = "EPON Resin 8280 with MPDA and CFR Santos"
    return app.run(timeout=30)


def _review_app_in_chinese(
    decision: str = "pending", *, page: str = "conclusion"
) -> AppTest:
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.query_params["lang"] = "zh-CN"
    workspace = ReviewWorkspace.model_validate_json(_workspace_json(decision))
    workspace = workspace.model_copy(update={"current_page": page})
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.session_state["inquiry"] = "EPON Resin 8280 with MPDA and CFR Santos"
    app.session_state["review_translation_review-1_zh-CN"] = (
        '{"analysis_revision":"review-1","target_locale":"zh-CN","texts":{}}'
    )
    return app.run(timeout=30)


def _print_markup(app: AppTest) -> str:
    return "\n".join(
        item.value for item in app.markdown if "ctc-print-sheet" in item.value
    )


def test_print_preview_uses_current_decision_and_email_version() -> None:
    app = _review_app(
        "needs_information",
        page="print",
        email_version=2,
    )

    markup = _print_markup(app)

    assert not app.exception
    assert 'class="ctc-print-preview"' in markup
    assert markup.count('class="ctc-print-sheet"') == 2
    assert "Ask customer for information" in markup
    assert "Email version 2 · English" in markup
    assert "Existing customer draft" in markup
    assert "TDS - Hexion EPON Resin 8280 - Rev 2016.pdf" in markup
    assert "Physical page 3" in markup


def test_print_preview_without_authorized_email_has_only_internal_sheet() -> None:
    app = _review_app("do_not_recommend", page="print")

    markup = _print_markup(app)

    assert not app.exception
    assert markup.count('class="ctc-print-sheet"') == 1
    assert "Save record without replying" in markup
    assert "Customer email" not in markup


def test_record_page_offers_a_strict_review_backup_download() -> None:
    app = _review_app("needs_information", page="record", email_version=2)

    assert not app.exception
    assert len(app.download_button) == 1
    assert app.download_button[0].label == "Save review backup"
    assert app.download_button[0].proto.url.endswith(".json")


def _current_catalog_refs() -> tuple[CatalogDocumentRef, ...]:
    return tuple(
        CatalogDocumentRef(relative_path=path, sha256=digest)
        for path, digest in enabled_catalog_snapshot(load_material_catalog(CATALOG))
    )


def test_inquiry_page_restores_a_matching_review_backup() -> None:
    workspace = ReviewWorkspace.model_validate_json(
        _workspace_json("needs_information")
    ).model_copy(update={"current_page": "evidence"})
    payload = export_review_backup(workspace, _current_catalog_refs()).encode("utf-8")
    app = AppTest.from_file(str(APP)).run(timeout=30)

    next(button for button in app.button if button.label == "Open review backup").click()
    app.run(timeout=30)
    app.file_uploader[0].upload("review.json", payload, "application/json")
    app.run(timeout=30)

    assert not app.exception
    assert _workspace(app) == workspace
    assert app.title[0].value == "Review evidence"


def test_inquiry_page_changed_catalog_restores_inputs_for_reanalysis_only() -> None:
    workspace = ReviewWorkspace.model_validate_json(
        _workspace_json("needs_information")
    )
    current = _current_catalog_refs()
    changed = (
        current[0].model_copy(update={"sha256": "f" * 64}),
        *current[1:],
    )
    payload = export_review_backup(workspace, changed).encode("utf-8")
    app = AppTest.from_file(str(APP)).run(timeout=30)

    next(button for button in app.button if button.label == "Open review backup").click()
    app.run(timeout=30)
    app.file_uploader[0].upload("review.json", payload, "application/json")
    app.run(timeout=30)

    assert not app.exception
    assert "review_workspace_json" not in app.session_state
    assert app.text_area[0].value == workspace.inquiry
    assert any("approved materials changed" in item.value for item in app.warning)


def test_record_page_uses_live_summary_and_completes_in_place() -> None:
    app = _review_app("needs_information", page="record", email_version=2)

    visible = " ".join(
        item.value for collection in (app.markdown, app.caption, app.info)
        for item in collection
    )
    assert "Ask customer for information" in visible
    assert "needs_information" not in visible
    assert "2 · en" in visible
    assert "review-1" in visible
    record_markup = "\n".join(
        item.value for item in app.markdown if "ctc-record" in item.value
    )
    assert 'class="ctc-record"' in record_markup

    next(button for button in app.button if button.label == "Confirm and complete review").click()
    app.run(timeout=30)

    completed = _workspace(app)
    assert not app.exception
    assert completed.completed_at is not None
    assert completed.current_page == "record"
    assert any("Completed review" in item.value for item in app.success)
    assert not any(
        button.label == "Confirm and complete review" for button in app.button
    )


def test_chinese_record_and_print_pages_have_no_english_interface_labels() -> None:
    record = _review_app_in_chinese("needs_information", page="record")
    record_visible = " ".join(
        item.value
        for collection in (record.markdown, record.caption, record.info)
        for item in collection
    )

    assert not record.exception
    assert "专家决定" in record_visible
    assert "邮件版本" in record_visible
    assert "分析修订" in record_visible
    assert "Expert decision" not in record_visible
    assert "Email version" not in record_visible
    assert "Analysis revision" not in record_visible

    printed = _review_app_in_chinese("needs_information", page="print")
    markup = _print_markup(printed)

    assert not printed.exception
    assert "内部证据审阅" in markup
    assert "审阅缺口" in markup
    assert "专家决定" in markup
    assert "Internal evidence review" not in markup
    assert "Review gaps" not in markup


def test_initial_app_is_an_english_single_inquiry_page(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = AppTest.from_file(str(APP)).run(timeout=30)

    assert not app.exception
    assert app.text_area[0].label == "Customer inquiry"
    assert app.button[0].label == "Analyze inquiry"
    assert "First decide what can be answered" in app.title[0].value
    assert any(
        "DeepSeek API key has not been configured" in message.value
        for message in app.info
    )
    assert not any(
        button.label.startswith(tuple(f"{index:02d} " for index in range(1, 9)))
        for button in app.button
    )


def test_all_review_steps_are_clickable_and_preserve_canonical_workspace() -> None:
    expected_labels = (
        "**01**  \nInquiry",
        "**02**  \nConclusion",
        "**03**  \nGaps",
        "**04**  \nEvidence",
        "**05**  \nDecision",
        "**06**  \nEmail",
        "**07**  \nPrint",
        "**08**  \nRecord",
    )
    expected_titles = (
        "Review inquiry",
        "Review conclusion",
        "Review gaps",
        "Review evidence",
        "Expert decision",
        "Customer email",
        "Print review",
        "Review record",
    )

    for page, label, title in zip(
        REVIEW_PAGES, expected_labels, expected_titles, strict=True
    ):
        app = _review_app("needs_information", email_version=3)
        stable = _workspace(app)
        resolved_id = stable.session.card.follow_ups[0].item_id
        stable = set_resolved_follow_up(
            stable,
            resolved_id,
            resolved=True,
        )
        app.session_state["review_workspace_json"] = stable.model_dump_json()
        app.run(timeout=30)
        original = _workspace(app)

        assert tuple(
            button.label for button in app.button if button.label in expected_labels
        ) == expected_labels
        next(button for button in app.button if button.label == label).click()
        app.run(timeout=30)

        restored = _workspace(app)
        assert [item.value for item in app.title] == [title]
        assert restored.current_page == page
        assert restored.analysis == original.analysis
        assert restored.session == original.session
        assert restored.session.outcome == original.session.outcome
        assert restored.resolved_follow_up_ids == original.resolved_follow_up_ids
        assert restored.draft_versions == original.draft_versions
        assert restored.active_draft_version == original.active_draft_version
        assert restored.email_language == original.email_language

        current = next(button for button in app.button if button.label == label)
        assert current.proto.type == "primary"
        assert all(
            button.proto.type == "secondary"
            for button in app.button
            if button.label in expected_labels and button.label != label
        )


def test_each_review_page_has_one_real_localized_title() -> None:
    expected_titles = {
        "inquiry": "Review inquiry",
        "conclusion": "Review conclusion",
        "gaps": "Review gaps",
        "evidence": "Review evidence",
        "decision": "Expert decision",
        "email": "Customer email",
        "print": "Print review",
        "record": "Review record",
    }

    for page in REVIEW_PAGES:
        app = _review_app(page=page)

        assert not app.exception
        assert [title.value for title in app.title] == [expected_titles[page]]


def test_existing_pdf_source_viewer_is_rendered_only_on_the_evidence_page() -> None:
    evidence = _review_app(page="evidence")

    assert any(
        item.value == "Inspect the source page" for item in evidence.subheader
    )
    assert any(
        item.value.startswith("Click the authentic PDF page")
        for item in evidence.caption
    )

    for page in REVIEW_PAGES:
        if page == "evidence":
            continue
        app = _review_app(page=page)

        assert all(
            item.value != "Inspect the source page" for item in app.subheader
        )
        assert all(
            not item.value.startswith("Click the authentic PDF page")
            for item in app.caption
        )


def test_evidence_action_opens_the_controlled_original_pdf_at_cited_physical_page() -> None:
    app = _review_app(page="evidence")

    initial_html_count = len(app.get("html"))
    assert any(
        "physical page 3 of 5" in item.value.casefold()
        for item in app.markdown
    )
    action = next(
        button
        for button in app.button
        if button.label == "Open original PDF page 3"
    )
    action.click()
    app.run(timeout=30)

    assert not app.exception
    dialog = app.get("dialog")[0]
    assert any(
        "physical page 3 of 5" in item.value.casefold()
        for item in dialog.markdown
    )
    assert len(app.get("html")) == initial_html_count + 1
    assert len(dialog.get("html")) == 1
    assert len(dialog.get("bidi_component")) == 1
    visible_dialog_nodes = tuple(
        node.type
        for node in dialog
        if node.type not in {"dialog", "flex_container"}
    )
    assert visible_dialog_nodes == ("markdown", "html", "bidi_component")
    assert all(
        "full original PDF viewer is unavailable" not in item.value
        for item in app.error
    )


def test_original_pdf_dialog_uses_one_verified_byte_snapshot_for_zoom_and_pdf(
    monkeypatch,
) -> None:
    from chemical_trade_copilot import streamlit_app

    citation = InquiryAnalysis.model_validate_json(_supported_json()).requirements[
        0
    ].evidence[0]
    approved = pdf_pages.load_approved_pdf(
        citation.product,
        citation.source_file,
        Path(r"G:\桌面\化工"),
        CATALOG,
    )
    rendered = evidence_viewer.render_approved_citation_page(citation, approved)
    output: dict[str, object] = {}
    fake_st = SimpleNamespace(
        markdown=lambda value: output.setdefault("markdown", value),
        html=lambda value, **kwargs: output.setdefault("html", value),
        pdf=lambda data, **kwargs: output.setdefault("pdf", data),
        error=lambda value: output.setdefault("error", value),
    )
    monkeypatch.setattr(streamlit_app, "st", fake_st)

    streamlit_app._open_original_pdf_dialog.__wrapped__(citation, approved)

    assert output["pdf"] is approved.pdf_bytes
    assert f"physical page 3 of {approved.page_count}" in str(output["markdown"])
    assert base64.b64encode(rendered.png_bytes).decode("ascii") in str(output["html"])
    assert "error" not in output


def test_original_pdf_actions_exist_only_on_the_evidence_page() -> None:
    for page in REVIEW_PAGES:
        app = _review_app(page=page)
        actions = [
            button
            for button in app.button
            if button.label.startswith("Open original PDF page ")
        ]

        assert bool(actions) is (page == "evidence")


def test_evidence_failure_does_not_expose_material_paths(monkeypatch) -> None:
    secret_root = r"C:\private-customer-materials\missing"
    monkeypatch.setenv("CHEMICAL_TRADE_MATERIALS_ROOT", secret_root)

    app = _review_app(page="evidence")

    assert not app.exception
    warnings = " ".join(item.value for item in app.warning)
    assert "controlled source is unavailable" in warnings.casefold()
    assert secret_root.casefold() not in warnings.casefold()


def test_pdf_runtime_dependency_is_declared_explicitly() -> None:
    project = APP.parents[2] / "pyproject.toml"
    contents = project.read_text(encoding="utf-8")

    assert '"streamlit[pdf]>=1.60,<1.61"' in contents
    assert '"streamlit-pdf>=2.0.1,<2.1"' in contents


def test_review_navigation_uses_chinese_labels_without_changing_page_codes() -> None:
    app = _review_app_in_chinese(page="evidence")

    labels = {button.label for button in app.button}
    assert {
        "**01**  \n询盘",
        "**02**  \n结论",
        "**03**  \n缺口",
        "**04**  \n证据",
        "**05**  \n决定",
        "**06**  \n邮件",
        "**07**  \n打印",
        "**08**  \n记录",
    } <= labels
    assert [title.value for title in app.title] == ["审阅证据"]
    assert _workspace(app).current_page == "evidence"


def test_inquiry_page_uses_localized_controlled_market_and_real_backup_entry() -> None:
    app = AppTest.from_file(str(APP)).run(timeout=30)

    market = next(box for box in app.selectbox if box.label == "Target market")
    assert market.options == [
        "Not specified",
        "European Union",
        "United States",
        "United Kingdom",
        "China",
        "Canada",
        "Australia",
        "Japan",
        "South Korea",
        "Other",
    ]
    assert app.session_state["target_market"] == "unknown"
    assert all(item.label != "Target market" for item in app.text_input)
    assert all(item.label != "Choose a review backup file" for item in app.file_uploader)

    next(button for button in app.button if button.label == "Open review backup").click()
    app.run(timeout=30)

    assert any(
        uploader.label == "Choose a review backup file"
        for uploader in app.file_uploader
    )


def test_chinese_inquiry_page_localizes_market_names_and_backup_entry() -> None:
    app = AppTest.from_file(str(APP)).run(timeout=30)
    next(
        box for box in app.selectbox if box.label == "Interface language / 界面语言"
    ).set_value("zh-CN")
    app.run(timeout=30)

    market = next(box for box in app.selectbox if box.label == "目标市场")
    assert market.options[0] == "未指定"
    assert market.options[-1] == "其他"
    assert any(button.label == "打开审阅备份" for button in app.button)


def test_switching_interface_language_immediately_rerenders_the_selector() -> None:
    app = AppTest.from_file(str(APP)).run(timeout=30)

    next(
        box
        for box in app.selectbox
        if box.label == "Interface language / 界面语言"
    ).set_value("zh-CN")
    app.run(timeout=30)

    assert not app.exception
    assert any(item.value == "界面语言" for item in app.caption)
    assert any(title.value.startswith("先判断") for title in app.title)


def test_chinese_locale_translates_the_review_ui_without_dropping_the_decision() -> None:
    app = _review_app_in_chinese("proceed", page="evidence")

    assert not app.exception
    assert any(title.value == "审阅证据" for title in app.title)
    assert any(item.value == "内部候选" for item in app.subheader)
    workspace = ReviewWorkspace.model_validate_json(
        app.session_state["review_workspace_json"]
    )
    assert workspace.session.outcome.decision == "proceed"


def test_email_language_defaults_to_english_even_in_the_chinese_interface() -> None:
    app = _review_app_in_chinese("proceed", page="email")

    email_language = next(box for box in app.selectbox if box.label == "邮件语言")
    assert email_language.value == "en"
    assert any(area.label == "可编辑英文邮件" for area in app.text_area)


def test_chinese_locale_translates_the_authorized_result_sections() -> None:
    conclusion = _review_app_in_chinese("proceed", page="conclusion")
    gaps = _review_app_in_chinese("proceed", page="gaps")
    evidence = _review_app_in_chinese("proceed", page="evidence")

    assert "技术结论依据" in {item.value for item in evidence.subheader}
    assert "报价前仍需确认" in {item.value for item in gaps.subheader}
    assert "Why the technical conclusion holds" not in {
        item.value for item in evidence.subheader
    }
    assert "What is still needed before a quotation" not in {
        item.value for item in gaps.subheader
    }
    assert any("下一步：" in item.value for item in conclusion.caption)


def test_switching_email_language_changes_only_the_authorized_draft() -> None:
    app = _review_app_in_chinese("proceed", page="email")
    before = ReviewWorkspace.model_validate_json(
        app.session_state["review_workspace_json"]
    ).session

    next(box for box in app.selectbox if box.label == "邮件语言").set_value("zh-CN")
    app.run(timeout=30)

    assert not app.exception
    after = ReviewWorkspace.model_validate_json(
        app.session_state["review_workspace_json"]
    )
    assert after.session == before
    draft = next(area for area in app.text_area if area.label == "可编辑中文邮件")
    assert "尊敬的" in draft.value
    assert "EPON Resin 8280" in draft.value


def test_evidence_scope_caption_reads_enabled_products_from_catalog(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        """[
          {"product":"Product B","relative_path":"B/TDS.pdf","document_type":"TDS","date_revision":"2026","jurisdiction":"US","enabled":true,"sha256":"0000000000000000000000000000000000000000000000000000000000000000","source_url":"https://example.com/b","acquired_on":"2026-07-28"},
          {"product":"Product A","relative_path":"A/TDS.pdf","document_type":"TDS","date_revision":"2026","jurisdiction":"US","enabled":true,"sha256":"1111111111111111111111111111111111111111111111111111111111111111","source_url":"https://example.com/a","acquired_on":"2026-07-28"},
          {"product":"Old Product","relative_path":"Old/TDS.pdf","document_type":"TDS","date_revision":"2020","jurisdiction":"US","enabled":false,"sha256":"2222222222222222222222222222222222222222222222222222222222222222","source_url":"https://example.com/old","acquired_on":"2026-07-28"}
        ]""",
        encoding="utf-8",
    )

    caption = evidence_scope_caption(catalog)

    assert "Product A and Product B" in caption
    assert "Old Product" not in caption


def test_supported_analysis_renders_product_readiness_and_editable_email() -> None:
    conclusion = _review_app("proceed", page="conclusion")
    email = _review_app("proceed", page="email")

    assert not conclusion.exception
    assert not email.exception
    assert any(header.value == "EPON Resin 8280" for header in conclusion.header)
    assert any(
        "Technical reply ready; quotation inputs required" in item.value
        for item in conclusion.subheader
    )
    assert any(
        area.label == "Editable English email" and "EPON Resin 8280" in area.value
        for area in email.text_area
    )
    assert all(
        "156" not in area.value
        for area in email.text_area
        if "email" in area.label.lower()
    )


def test_pending_review_is_the_main_flow_and_hides_external_drafts() -> None:
    app = _review_app(page="evidence")

    assert not app.exception
    assert any(title.value == "Review evidence" for title in app.title)
    assert any(item.value == "Internal candidates" for item in app.subheader)
    assert all(area.label != "Editable English email" for area in app.text_area)
    assert all(area.label != "Editable customer follow-up" for area in app.text_area)


def test_decision_page_has_exactly_three_real_business_exits() -> None:
    app = _review_app(page="decision")
    labels = {button.label for button in app.button}
    exit_labels = (
        "Ask customer for information",
        "Save record without replying",
        "Authorize technical reply",
    )

    assert set(exit_labels) <= labels
    assert tuple(button.label for button in app.button if button.label in exit_labels) == exit_labels
    assert "Reanalyze inquiry" not in labels
    assert "Apply expert decision" not in labels
    assert not app.radio
    decision_columns = [
        column
        for column in app.columns
        if any(
            getattr(child, "label", None) in exit_labels
            for child in column.children.values()
        )
    ]
    assert [
        tuple(
            child.label
            for child in column.children.values()
            if getattr(child, "label", None) in exit_labels
        )
        for column in decision_columns
    ] == [(exit_labels[1],), (exit_labels[2],)]
    assert decision_columns[0].weight == decision_columns[1].weight


def test_each_business_exit_applies_and_saves_the_mapped_decision() -> None:
    app = _review_app(page="decision")

    next(box for box in app.checkbox if "Confirm quantity" in box.label).check()
    app.run(timeout=30)
    next(
        button
        for button in app.button
        if button.label == "Ask customer for information"
    ).click()
    app.run(timeout=30)

    assert not app.exception
    assert _workspace(app).session.outcome.decision == "needs_information"

    app = _review_app(page="decision")
    next(
        box for box in app.selectbox if box.label == "Evidence-backed internal candidate"
    ).set_value("EPON Resin 8280")
    app.run(timeout=30)
    next(
        button
        for button in app.button
        if button.label == "Authorize technical reply"
    ).click()
    app.run(timeout=30)

    assert not app.exception
    assert _workspace(app).session.outcome.decision == "proceed"

    app = _review_app("needs_information", page="decision", email_version=1)
    next(
        button
        for button in app.button
        if button.label == "Save record without replying"
    ).click()
    app.run(timeout=30)

    saved = _workspace(app)
    assert saved.session.outcome.decision == "do_not_recommend"
    assert saved.draft_versions == ()
    assert saved.active_draft_version is None


def test_save_exit_resets_staged_question_and_candidate_widgets() -> None:
    app = _review_app(page="decision")
    question = next(box for box in app.checkbox if "Confirm quantity" in box.label)
    question.check()
    app.run(timeout=30)
    candidate = next(
        box for box in app.selectbox if box.label == "Evidence-backed internal candidate"
    )
    candidate.set_value("EPON Resin 8280")
    app.run(timeout=30)

    next(
        button
        for button in app.button
        if button.label == "Save record without replying"
    ).click()
    app.run(timeout=30)

    saved = _workspace(app)
    assert saved.session.outcome.decision == "do_not_recommend"
    assert saved.session.outcome.selected_candidate is None
    assert saved.session.outcome.selected_follow_ups == ()
    assert next(
        box for box in app.checkbox if "Confirm quantity" in box.label
    ).value is False
    assert next(
        box for box in app.selectbox if box.label == "Evidence-backed internal candidate"
    ).value is None


def test_repeating_same_save_exit_resets_staged_widgets() -> None:
    app = _review_app("do_not_recommend", page="decision")
    next(box for box in app.checkbox if "Confirm quantity" in box.label).check()
    app.run(timeout=30)
    next(
        box for box in app.selectbox if box.label == "Evidence-backed internal candidate"
    ).set_value("EPON Resin 8280")
    app.run(timeout=30)

    next(
        button
        for button in app.button
        if button.label == "Save record without replying"
    ).click()
    app.run(timeout=30)

    saved = _workspace(app)
    assert saved.session.outcome.decision == "do_not_recommend"
    assert saved.session.outcome.selected_candidate is None
    assert saved.session.outcome.selected_follow_ups == ()
    assert next(
        box for box in app.checkbox if "Confirm quantity" in box.label
    ).value is False
    assert next(
        box for box in app.selectbox if box.label == "Evidence-backed internal candidate"
    ).value is None


def test_repeating_same_ask_or_technical_exit_resets_only_noncanonical_stage() -> None:
    ask = _review_app("needs_information", page="decision")
    next(
        box for box in ask.selectbox if box.label == "Evidence-backed internal candidate"
    ).set_value("EPON Resin 8280")
    ask.run(timeout=30)
    next(
        button
        for button in ask.button
        if button.label == "Ask customer for information"
    ).click()
    ask.run(timeout=30)

    assert _workspace(ask).session.outcome.decision == "needs_information"
    assert next(
        box for box in ask.selectbox if box.label == "Evidence-backed internal candidate"
    ).value is None
    assert next(
        box for box in ask.checkbox if "Confirm quantity" in box.label
    ).value is True

    technical = _review_app("proceed", page="decision")
    next(
        box for box in technical.checkbox if "Confirm quantity" in box.label
    ).check()
    technical.run(timeout=30)
    next(
        button
        for button in technical.button
        if button.label == "Authorize technical reply"
    ).click()
    technical.run(timeout=30)

    assert _workspace(technical).session.outcome.decision == "proceed"
    assert next(
        box for box in technical.checkbox if "Confirm quantity" in box.label
    ).value is False
    assert next(
        box
        for box in technical.selectbox
        if box.label == "Evidence-backed internal candidate"
    ).value == "EPON Resin 8280"


def test_switching_from_technical_to_ask_then_save_clears_staged_candidate() -> None:
    app = _review_app(page="decision")
    candidate = next(
        box for box in app.selectbox if box.label == "Evidence-backed internal candidate"
    )
    candidate.set_value("EPON Resin 8280")
    app.run(timeout=30)
    next(
        button
        for button in app.button
        if button.label == "Authorize technical reply"
    ).click()
    app.run(timeout=30)
    assert _workspace(app).session.outcome.selected_candidate == "EPON Resin 8280"

    next(box for box in app.checkbox if "Confirm quantity" in box.label).check()
    app.run(timeout=30)
    next(
        button
        for button in app.button
        if button.label == "Ask customer for information"
    ).click()
    app.run(timeout=30)

    asked = _workspace(app)
    assert asked.session.outcome.decision == "needs_information"
    assert asked.session.outcome.selected_candidate is None
    assert next(
        box for box in app.selectbox if box.label == "Evidence-backed internal candidate"
    ).value is None

    next(
        button
        for button in app.button
        if button.label == "Save record without replying"
    ).click()
    app.run(timeout=30)
    assert next(
        box for box in app.checkbox if "Confirm quantity" in box.label
    ).value is False


def test_decision_page_disables_customer_question_exit_when_no_open_questions_remain() -> None:
    app = _review_app(page="decision")
    workspace = _workspace(app)
    workspace = workspace.model_copy(
        update={
            "resolved_follow_up_ids": tuple(
                item.item_id for item in workspace.session.card.follow_ups
            )
        }
    )
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.run(timeout=30)

    ask = next(
        button
        for button in app.button
        if button.label == "Ask customer for information"
    )
    save = next(
        button
        for button in app.button
        if button.label == "Save record without replying"
    )
    assert ask.disabled is True
    assert save.disabled is False
    assert any("No open customer questions remain" in item.value for item in app.caption)


def test_decision_page_disables_technical_reply_without_evidence_backed_candidates() -> None:
    analysis = InquiryAnalysis.model_validate_json(_supported_json()).model_copy(
        update={
            "recommendation_status": "insufficient_evidence",
            "recommended_product": None,
            "recommendation_reasons": (),
            "next_action": "insufficient_product_evidence",
        }
    )
    inquiry = "Customer requests an unsupported coating recommendation"
    card = build_review_card(inquiry, analysis, [])
    workspace = ReviewWorkspace(
        inquiry=inquiry,
        target_market="unknown",
        catalog_fingerprint=_current_fingerprint(),
        analysis=analysis,
        session=start_review_session(card, analysis_revision="review-no-candidate"),
        current_page="decision",
    )
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.run(timeout=30)

    technical = next(
        button
        for button in app.button
        if button.label == "Authorize technical reply"
    )
    save = next(
        button
        for button in app.button
        if button.label == "Save record without replying"
    )
    assert technical.disabled is True
    assert save.disabled is False
    assert any(
        "No evidence-backed technical reply is available" in item.value
        for item in app.caption
    )


def test_proceed_decision_reveals_the_existing_editable_email() -> None:
    app = _review_app("proceed", page="email")

    assert not app.exception
    assert any(
        area.label == "Editable English email" and "EPON Resin 8280" in area.value
        for area in app.text_area
    )


def test_manual_proceed_after_fail_closed_uses_a_distinct_reviewer_draft() -> None:
    analysis = InquiryAnalysis.model_validate_json(_supported_json()).model_copy(
        update={
            "recommendation_status": "insufficient_evidence",
            "recommended_product": None,
            "recommendation_reasons": (),
            "next_action": "insufficient_product_evidence",
        }
    )
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.session_state["review_workspace_json"] = _workspace_json(
        "proceed", analysis=analysis
    )
    workspace = ReviewWorkspace.model_validate_json(
        app.session_state["review_workspace_json"]
    ).model_copy(update={"current_page": "email"})
    app.session_state["review_workspace_json"] = workspace.model_dump_json()

    app.run(timeout=30)

    assert not app.exception
    assert all(header.value != "Supported technical result" for header in app.header)
    assert any(header.value == "EPON Resin 8280" for header in app.header)
    draft = next(area for area in app.text_area if area.label == "Editable English email")
    assert "selected by the technical reviewer" in draft.value
    assert "do not provide enough evidence" not in draft.value


def test_needs_information_shows_only_the_selected_follow_up_draft() -> None:
    app = _review_app("needs_information", page="email")

    assert not app.exception
    assert all(area.label != "Editable English email" for area in app.text_area)
    draft = next(
        area for area in app.text_area if area.label == "Editable customer follow-up"
    )
    assert "Confirm quantity and destination." in draft.value


def test_chinese_follow_up_email_does_not_consume_freeform_translation_bundle() -> None:
    app = _review_app("needs_information", page="email")
    workspace = _workspace(app)
    selected = next(
        item
        for item in workspace.session.card.follow_ups
        if item.question in workspace.session.outcome.selected_follow_ups
    )
    freeform_claim = "保证符合REACH并可商业采用。"
    workspace = workspace.model_copy(
        update={"email_language": "zh-CN", "active_draft_version": None}
    )
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.session_state[
        f"review_translation_{workspace.session.analysis_revision}_zh-CN"
    ] = ReviewTranslationBundle(
        analysis_revision=workspace.session.analysis_revision,
        target_locale="zh-CN",
        texts={f"card.followup.{selected.item_id}": freeform_claim},
    ).model_dump_json()

    app.run(timeout=30)

    draft = next(
        area for area in app.text_area if area.label == "Editable customer follow-up"
    )
    assert "请确认数量和目的地。" in draft.value
    assert freeform_claim not in draft.value
    assert selected.question not in draft.value


def test_gap_checkbox_updates_all_open_gap_views_without_reanalysis() -> None:
    app = _review_app("needs_information", page="gaps")
    revision = _workspace(app).session.analysis_revision

    next(box for box in app.checkbox if "120°C" in box.label).check()
    app.run(timeout=30)

    changed = _workspace(app)
    assert changed.session.analysis_revision == revision
    assert len(changed.resolved_follow_up_ids) == 1
    visible = " ".join(
        item.value
        for collection in (app.markdown, app.caption, app.text)
        for item in collection
    )
    assert "3 open gaps" in visible

    for page in ("conclusion", "email", "record"):
        next(
            button
            for button in app.button
            if button.label == {
        "conclusion": "**02**  \nConclusion",
        "email": "**06**  \nEmail",
        "record": "**08**  \nRecord",
            }[page]
        ).click()
        app.run(timeout=30)
        visible = " ".join(
            item.value
            for collection in (app.markdown, app.caption, app.text)
            for item in collection
        )
        assert "3 open gaps" in visible
        assert _workspace(app).session.analysis_revision == revision


def test_resolved_gap_is_excluded_from_the_follow_up_email() -> None:
    app = _review_app(page="gaps")
    workspace = _workspace(app)
    session = apply_session_decision(
        workspace.session,
        "needs_information",
        selected_follow_up_ids=tuple(
            item.item_id for item in workspace.session.card.follow_ups
        ),
    )
    workspace = workspace.model_copy(
        update={"session": session, "current_page": "email"}
    )
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.run(timeout=30)

    initial_draft = next(
        area for area in app.text_area if area.label == "Editable customer follow-up"
    )
    assert "120°C" in initial_draft.value
    initial_draft.set_value(initial_draft.value.replace("- Is 120°C", "* Is 120°C"))
    app.run(timeout=30)
    next(button for button in app.button if button.label == "**03**  \nGaps").click()
    app.run(timeout=30)

    next(box for box in app.checkbox if "120°C" in box.label).check()
    app.run(timeout=30)
    next(button for button in app.button if button.label == "**06**  \nEmail").click()
    app.run(timeout=30)

    draft = next(
        area for area in app.text_area if area.label == "Editable customer follow-up"
    )
    assert "120°C" not in draft.value
    assert "Confirm quantity and destination." in draft.value


def test_closing_all_selected_gaps_locks_the_empty_follow_up_email() -> None:
    app = _review_app(page="gaps")
    workspace = _workspace(app)
    session = apply_session_decision(
        workspace.session,
        "needs_information",
        selected_follow_up_ids=tuple(
            item.item_id for item in workspace.session.card.follow_ups
        ),
    )
    workspace = workspace.model_copy(update={"session": session})
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.run(timeout=30)

    for question in tuple(item.question for item in workspace.session.card.follow_ups):
        next(box for box in app.checkbox if question in box.label).check()
        app.run(timeout=30)
    next(button for button in app.button if button.label == "**06**  \nEmail").click()
    app.run(timeout=30)

    assert all(
        area.label != "Editable customer follow-up" for area in app.text_area
    )
    assert any(
        "Select at least one current follow-up" in item.value for item in app.info
    )


def test_language_round_trip_does_not_reactivate_a_stale_follow_up_draft() -> None:
    app = _review_app(page="email")
    workspace = _workspace(app)
    session = apply_session_decision(
        workspace.session,
        "needs_information",
        selected_follow_up_ids=tuple(
            item.item_id for item in workspace.session.card.follow_ups
        ),
    )
    workspace = workspace.model_copy(update={"session": session})
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.run(timeout=30)

    english = next(
        area for area in app.text_area if area.label == "Editable customer follow-up"
    )
    english.set_value(english.value.replace("- Is 120°C", "* Is 120°C"))
    app.run(timeout=30)
    next(box for box in app.selectbox if box.label == "Email language").set_value(
        "zh-CN"
    )
    app.run(timeout=30)

    next(button for button in app.button if button.label == "**03**  \nGaps").click()
    app.run(timeout=30)
    next(box for box in app.checkbox if "120°C" in box.label).check()
    app.run(timeout=30)
    next(button for button in app.button if button.label == "**06**  \nEmail").click()
    app.run(timeout=30)
    next(box for box in app.selectbox if box.label == "Email language").set_value("en")
    app.run(timeout=30)

    current = _workspace(app)
    active = next(
        draft
        for draft in current.draft_versions
        if draft.version == current.active_draft_version
    )
    assert "120°C" not in active.body
    assert any(
        draft.language == "en" and "120°C" in draft.body
        for draft in current.draft_versions
        if draft.version != current.active_draft_version
    )


def test_language_round_trip_restores_a_manual_follow_up_draft_when_gaps_are_unchanged() -> None:
    app = _review_app(page="email")
    workspace = _workspace(app)
    session = apply_session_decision(
        workspace.session,
        "needs_information",
        selected_follow_up_ids=tuple(
            item.item_id for item in workspace.session.card.follow_ups
        ),
    )
    workspace = workspace.model_copy(update={"session": session})
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.run(timeout=30)

    english = next(
        area for area in app.text_area if area.label == "Editable customer follow-up"
    )
    english.set_value(english.value + "\n\nManual reviewer note.")
    app.run(timeout=30)
    manual_version = _workspace(app).active_draft_version

    next(box for box in app.selectbox if box.label == "Email language").set_value(
        "zh-CN"
    )
    app.run(timeout=30)
    next(button for button in app.button if button.label == "**03**  \nGaps").click()
    app.run(timeout=30)
    next(button for button in app.button if button.label == "**06**  \nEmail").click()
    app.run(timeout=30)
    next(box for box in app.selectbox if box.label == "Email language").set_value("en")
    app.run(timeout=30)

    current = _workspace(app)
    assert current.active_draft_version == manual_version
    active = next(
        draft
        for draft in current.draft_versions
        if draft.version == current.active_draft_version
    )
    assert "Manual reviewer note." in active.body


def test_manual_email_edit_marks_current_version_without_creating_another() -> None:
    app = _review_app("proceed", page="email")
    original = _workspace(app)
    original_version = original.active_draft_version
    original_count = len(original.draft_versions)
    editor = next(area for area in app.text_area if area.label == "Editable English email")

    editor.set_value(editor.value + "\n\nManual reviewer note.")
    app.run(timeout=30)

    changed = _workspace(app)
    active = next(
        draft
        for draft in changed.draft_versions
        if draft.version == changed.active_draft_version
    )
    assert changed.active_draft_version == original_version
    assert len(changed.draft_versions) == original_count
    assert active.manually_edited is True
    assert "Manual reviewer note." in active.body


def test_email_page_displays_active_version_selector_and_optimization_dialog() -> None:
    app = _review_app("needs_information", page="email")

    assert not app.exception
    subject = next(field for field in app.text_input if field.label == "Email subject")
    assert subject.value == "Additional information required"
    assert subject.disabled is True
    assert any(box.label == "Draft version" for box in app.selectbox)
    optimize = next(button for button in app.button if button.label == "Optimize draft")
    optimize.click()
    app.run(timeout=30)

    dialog = app.get("dialog")[0]
    assert any(
        area.label == "How should this email be improved?"
        for area in dialog.get("text_area")
    )
    assert any(
        button.label == "Generate new version" for button in dialog.get("button")
    )


def test_review_and_email_use_the_approved_prototype_layout_containers() -> None:
    source = APP.read_text(encoding="utf-8")

    assert 'with st.container(key="ctc_review_sheet")' in source
    assert 'with st.container(key="ctc_email_layout")' in source


def test_no_change_optimization_has_a_safe_specific_ui_message() -> None:
    from chemical_trade_copilot import streamlit_app

    assert streamlit_app._email_optimization_error_message(
        ValueError("Optimization does not change the active draft"),
        "en",
    ) == "The suggestion did not change the draft. No new version was created."
    assert streamlit_app._email_optimization_error_message(
        ValueError("Optimization does not change the active draft"),
        "zh-CN",
    ) == "该建议未改变草稿，因此没有创建新版本。"


@pytest.mark.parametrize("decision", ("proceed", "needs_information"))
def test_english_email_paths_render_copy_for_the_actual_editor(decision: str) -> None:
    app = _review_app(decision, page="email")
    editor = next(area for area in app.text_area if "Editable" in area.label)
    rendered_html = "\n".join(item.proto.body for item in app.get("html"))

    assert editor.label in rendered_html
    assert "Copy email" in rendered_html


@pytest.mark.parametrize("decision", ("proceed", "needs_information"))
def test_chinese_email_paths_render_copy_for_the_actual_editor(decision: str) -> None:
    app = _review_app_in_chinese(decision, page="email")
    next(box for box in app.selectbox if box.label == "邮件语言").set_value("zh-CN")
    app.run(timeout=30)
    editor = next(area for area in app.text_area if "可编辑" in area.label)
    rendered_html = "\n".join(item.proto.body for item in app.get("html"))

    assert editor.label in rendered_html
    assert "复制邮件" in rendered_html


def test_version_label_reports_language_and_only_real_manual_edits() -> None:
    from chemical_trade_copilot import streamlit_app
    from chemical_trade_copilot.review_email import ensure_authorized_draft

    workspace = ensure_authorized_draft(
        ReviewWorkspace.model_validate_json(_workspace_json("needs_information"))
    )
    generated = workspace.draft_versions[0]
    edited = generated.model_copy(
        update={"version": 2, "body": generated.body + "\nManual", "manually_edited": True}
    )

    assert streamlit_app._draft_version_label(generated, "en") == "Version 1 · English"
    assert streamlit_app._draft_version_label(edited, "en") == "Version 2 · English · Edited"
    assert streamlit_app._draft_version_label(generated, "zh-CN") == "版本 1 · 英文"
    assert streamlit_app._draft_version_label(edited, "zh-CN") == "版本 2 · 英文 · 已编辑"


def test_streamlit_email_renderers_do_not_keep_overwritten_fallback_bodies() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "body = build_email_draft(analysis).body" not in source
    assert "product_line = (" not in source
    assert "selected by the technical reviewer for further" not in source


def test_email_page_switches_active_version_without_overwriting_history() -> None:
    app = _review_app("needs_information", page="email")
    workspace = _workspace(app)
    first = next(
        draft
        for draft in workspace.draft_versions
        if draft.version == workspace.active_draft_version
    )
    second = first.model_copy(
        update={
            "version": first.version + 1,
            "body": "Second retained version",
            "manually_edited": True,
        }
    )
    workspace = workspace.model_copy(
        update={
            "draft_versions": (*workspace.draft_versions, second),
            "active_draft_version": second.version,
        }
    )
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.run(timeout=30)

    selector = next(box for box in app.selectbox if box.label == "Draft version")
    assert selector.options == [
        f"Version {first.version} · English",
        f"Version {second.version} · English · Edited",
    ]
    selector.set_value(first.version)
    app.run(timeout=30)

    changed = _workspace(app)
    assert changed.active_draft_version == first.version
    assert changed.draft_versions == workspace.draft_versions


def test_optimization_without_api_key_is_safe_and_keeps_workspace(monkeypatch) -> None:
    from chemical_trade_copilot import streamlit_app

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        streamlit_app._email_client()
    app = _review_app("needs_information", page="email")
    before = _workspace(app)

    next(button for button in app.button if button.label == "Optimize draft").click()
    app.run(timeout=30)
    dialog = app.get("dialog")[0]
    next(
        area
        for area in dialog.get("text_area")
        if area.label == "How should this email be improved?"
    ).set_value("Make it concise")
    next(
        button
        for button in dialog.get("button")
        if button.label == "Generate new version"
    ).click()
    app.run(timeout=30)

    assert _workspace(app) == before
    assert not app.exception
    assert "The API key is not configured. The workspace was not changed." in APP.read_text(
        encoding="utf-8"
    )


def test_same_language_render_fails_closed_on_unsigned_follow_up_body() -> None:
    app = _review_app(page="email")
    workspace = _workspace(app)
    session = apply_session_decision(
        workspace.session,
        "needs_information",
        selected_follow_up_ids=tuple(
            item.item_id for item in workspace.session.card.follow_ups
        ),
    )
    unsigned = EmailDraftVersion(
        version=1,
        language="en",
        subject="Old draft",
        body="UNSIGNED OLD BODY with 120°C",
        manually_edited=True,
        authorized_decision="needs_information",
    )
    workspace = workspace.model_copy(
        update={
            "session": session,
            "draft_versions": (unsigned,),
            "active_draft_version": 1,
        }
    )
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    app.run(timeout=30)

    assert "review_workspace_json" not in app.session_state
    assert all("UNSIGNED OLD BODY" not in area.value for area in app.text_area)


def test_resolved_gap_css_uses_checkbox_state_without_edit_controls() -> None:
    assert '[data-testid="stCheckbox"] label:has(input:checked) p' in APP_CSS
    assert "text-decoration: line-through" in APP_CSS
    assert "text-decoration-thickness: 1.5px" in APP_CSS

    app = _review_app(page="gaps")
    labels = {button.label.casefold() for button in app.button}
    assert not {"edit", "add", "delete"} & labels


def test_do_not_recommend_keeps_all_external_drafts_hidden() -> None:
    app = _review_app("do_not_recommend", page="email")

    assert not app.exception
    assert all("Editable" not in area.label for area in app.text_area)
    assert any("Do not recommend" in item.value for item in app.warning)


def test_starting_new_inquiry_clears_review_decision_and_draft_authorization() -> None:
    app = _review_app("proceed")

    next(button for button in app.button if button.label == "Start a new inquiry").click()
    app.run(timeout=30)

    assert not app.exception
    assert "review_workspace_json" not in app.session_state
    assert app.session_state["inquiry"] == ""


def test_reanalysis_revokes_old_approval_even_when_new_analysis_fails(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = _review_app("proceed")

    next(button for button in app.button if button.label == "Reanalyze inquiry").click()
    app.run(timeout=30)

    assert not app.exception
    assert "review_workspace_json" not in app.session_state
    assert any("could not be completed safely" in item.value for item in app.error)


def test_result_storage_does_not_reassign_the_instantiated_inquiry_widget() -> None:
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_store_review_result"
    )
    inquiry_assignments = [
        target
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Subscript)
        and isinstance(target.slice, ast.Constant)
        and target.slice.value == "inquiry"
    ]

    assert inquiry_assignments == []


def test_ready_to_reply_result_does_not_invent_a_quotation_workflow() -> None:
    analysis = InquiryAnalysis.model_validate_json(_supported_json())
    analysis = analysis.model_copy(
        update={
            "requirements": (analysis.requirements[0],),
            "next_action": "ready_to_reply",
        }
    )
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.session_state["review_workspace_json"] = _workspace_json(
        "proceed",
        analysis=analysis,
        inquiry="EPON Resin 8280 MPDA technical conditions",
    )
    app.session_state["inquiry"] = "EPON Resin 8280 MPDA technical conditions"

    app.run(timeout=30)

    assert not app.exception
    assert all(
        item.value != "What is still needed before a quotation"
        for item in app.subheader
    )
    assert any(
        "Next action: Prepare the evidence-grounded technical reply" in item.value
        for item in app.caption
    )


def test_cached_analysis_is_cleared_when_catalog_generation_changes() -> None:
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.session_state["review_workspace_json"] = _workspace_json(fingerprint="stale")

    app.run(timeout=30)

    assert not app.exception
    assert "review_workspace_json" not in app.session_state
    assert all(header.value != "EPON Resin 8280" for header in app.header)
    assert any("no longer matches" in warning.value for warning in app.warning)


def test_analysis_revision_binds_catalog_market_and_inquiry() -> None:
    from chemical_trade_copilot import streamlit_app

    expected = hashlib.sha256(b"catalog\0EU\0inquiry").hexdigest()

    assert streamlit_app._analysis_revision("inquiry", "EU", "catalog") == expected
    assert streamlit_app._analysis_revision("inquiry", "US", "catalog") != expected
    assert streamlit_app._analysis_revision("changed", "EU", "catalog") != expected


def test_storing_analysis_with_changed_market_creates_pending_workspace(monkeypatch) -> None:
    from chemical_trade_copilot import streamlit_app

    old = ReviewWorkspace.model_validate_json(_workspace_json("proceed", target_market="EU"))
    state: dict[str, object] = {"review_workspace_json": old.model_dump_json()}
    monkeypatch.setattr(streamlit_app, "st", SimpleNamespace(session_state=state))
    analysis = old.analysis

    streamlit_app._store_review_result(
        old.inquiry,
        "US",
        analysis,
        old.session.card,
        old.catalog_fingerprint,
    )

    current = ReviewWorkspace.model_validate_json(state["review_workspace_json"])
    assert current.target_market == "US"
    assert current.session.analysis_revision != old.session.analysis_revision
    assert current.session.outcome.decision == "pending"
    assert current.draft_versions == ()
