import html as html_module
from pathlib import Path

from chemical_trade_copilot.export_bundle import (
    build_markdown,
    build_printable_html,
    collect_sources,
)
from chemical_trade_copilot.inquiry_analysis import (
    InquiryAnalysis,
    KeyParameter,
    RequirementAssessment,
    SourceCitation,
)
from chemical_trade_copilot.inquiry_review import build_review_card
from chemical_trade_copilot.localization import SUPPORTED_LOCALES, text
from chemical_trade_copilot.retrieval import SearchResult
from chemical_trade_copilot.ui_presenter import build_analysis_view, build_email_draft


EXPORT_KEYS = (
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


def _labels(locale: str) -> dict[str, str]:
    return {key: text(key, locale) for key in EXPORT_KEYS}


def _citation() -> SourceCitation:
    return SourceCitation(
        product="EPON Resin 8280",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        page_number=3,
    )


def _analysis() -> InquiryAnalysis:
    return InquiryAnalysis(
        summary_zh="指定 MPDA 固化体系有可追溯的 TDS 证据。",
        recommendation_status="supported",
        recommended_product="EPON Resin 8280",
        recommendation_reasons=("询盘明确指定该产品与 MPDA 固化体系。",),
        requirements=(
            RequirementAssessment(
                category="technical",
                requirement="MPDA 固化体系的 HDT 与测试方法",
                status="supported",
                evidence=(_citation(),),
            ),
            RequirementAssessment(
                category="commercial",
                requirement="巴西库存与交期",
                status="needs_confirmation",
                evidence=(),
            ),
        ),
        key_parameters=(
            KeyParameter(
                name="Heat Deflection Temperature",
                value="156",
                unit="°C",
                conditions="MPDA-cured unfilled casting",
                test_method="ASTM D648",
                curing_agent="Metaphenylenediamine (MPDA)",
                mix_ratio="EPON Resin 8280 100 pbw : MPDA 14.4 pbw",
                cure_schedule="2 h/80°C + 2 h/150°C",
                citation=_citation(),
            ),
        ),
        evidence_gaps=("巴西库存与可供数量",),
        source_limitations=("TDS 为 2005 年重新发布、页脚修订于 2016 年。",),
        follow_up_questions=("预计采购数量与时间窗口？",),
        next_action="needs_commercial_input",
    )


def _ranked() -> list[SearchResult]:
    return [
        SearchResult(
            text="Cured State Properties",
            product="EPON Resin 8280",
            doc_type="TDS",
            source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
            source_path=Path("G:/materials/EPON/TDS.pdf"),
            page_number=3,
            distance=0.1,
            page_text="Heat Deflection Temperature ASTM D648 156",
        )
    ]


INQUIRY = (
    "For an EPON Resin 8280 system cured with MPDA, confirm the heat deflection "
    "temperature, mix ratio, cure schedule and test method. The customer also asks "
    "whether stock is available in Brazil."
)


def _inputs(locale: str = "en"):
    analysis = _analysis()
    card = build_review_card(
        INQUIRY, analysis, _ranked(), available_evidence=_ranked()
    )
    view = build_analysis_view(analysis)
    draft = build_email_draft(analysis)
    return {
        "inquiry": INQUIRY,
        "market": "",
        "analysis": analysis,
        "card": card,
        "view": view,
        "draft": draft,
        "labels": _labels(locale),
    }


def test_collect_sources_deduplicates_and_sorts() -> None:
    analysis = _analysis()
    view = build_analysis_view(analysis)

    rows = collect_sources(analysis, view)

    assert len(rows) == 1
    assert rows[0].product == "EPON Resin 8280"
    assert rows[0].page_number == 3


def test_markdown_bundle_carries_conclusion_conditions_and_draft() -> None:
    markdown = build_markdown(**_inputs())

    assert markdown.startswith("# Technical reply pack")
    assert INQUIRY in markdown
    assert "EPON Resin 8280" in markdown
    assert "Technical reply ready" in markdown
    # 已核验参数必须与条件、方法、来源同组出现
    assert "156°C" in markdown
    assert "ASTM D648" in markdown
    assert "MPDA" in markdown and "14.4 pbw" in markdown
    assert "2 h/80°C + 2 h/150°C" in markdown
    assert "Physical page 3" in markdown
    # 回复草稿
    assert "Technical follow-up" in markdown
    assert "Dear [Customer name]" in markdown
    # 未指定目标市场时不输出空条目
    assert "Target market" not in markdown


def test_markdown_bundle_never_invents_commercial_values() -> None:
    markdown = build_markdown(**_inputs())

    for forbidden in ("MOQ:", "Price:", "USD", "Lead time:"):
        assert forbidden not in markdown


def test_markdown_bundle_is_localized_in_chinese() -> None:
    markdown = build_markdown(**_inputs("zh-CN"))

    assert markdown.startswith("# 技术回复包")
    assert "已核验参数" in markdown
    assert "回复草稿" in markdown
    assert "物理第 3" in markdown


def test_printable_html_is_self_contained_and_escapes_input() -> None:
    payload = _inputs()
    payload["inquiry"] = INQUIRY + " <script>alert(1)</script>"

    document = build_printable_html(**payload)

    assert document.startswith("<!doctype html>")
    assert "<style>" in document
    assert "ctc-print-sheet" in document
    assert "156°C" in document
    assert "ASTM D648" in document
    assert "Dear [Customer name]" in document
    # 用户输入必须转义，不得成为可执行标记
    assert "<script>alert(1)</script>" not in document
    assert html_module.escape("<script>alert(1)</script>") in document


def test_insufficient_analysis_exports_no_product_and_no_temperature() -> None:
    analysis = _analysis().model_copy(
        update={
            "recommendation_status": "insufficient_evidence",
            "recommended_product": None,
            "key_parameters": (),
        }
    )
    card = build_review_card(
        INQUIRY, analysis, _ranked(), available_evidence=_ranked()
    )
    payload = {
        "inquiry": INQUIRY,
        "market": "",
        "analysis": analysis,
        "card": card,
        "view": build_analysis_view(analysis),
        "draft": build_email_draft(analysis),
        "labels": _labels("en"),
    }

    markdown = build_markdown(**payload)
    document = build_printable_html(**payload)

    assert "No product recommended" in document
    assert "156°C" not in document
    assert "No product recommended" in markdown
    assert "156°C" not in markdown


def test_every_locale_produces_a_complete_bundle() -> None:
    for locale in SUPPORTED_LOCALES:
        markdown = build_markdown(**_inputs(locale))
        document = build_printable_html(**_inputs(locale))

        assert "EPON Resin 8280" in markdown
        assert "EPON Resin 8280" in document
        assert "{" not in markdown.split("\n")[0]
