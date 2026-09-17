from chemical_trade_copilot import localization
from chemical_trade_copilot.localization import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    browser_locale_script,
    normalize_locale,
    text,
)


# 一次性工具界面实际使用的键。任何新增界面文案都必须同时补齐中英两侧。
ONE_SHOT_KEYS = {
    "app.scope",
    "language.label",
    "language.english",
    "language.chinese",
    "entry.eyebrow",
    "entry.title",
    "entry.description",
    "entry.inquiry",
    "entry.placeholder",
    "entry.help",
    "entry.analyze",
    "entry.empty",
    "entry.failed",
    "entry.spinner",
    "entry.api_key_missing",
    "entry.stale_cleared",
    "action.new",
    "result.validated",
    "result.supported_description",
    "result.why_title",
    "result.why_description",
    "result.not_stated",
    "result.verified_fact",
    "result.not_continuous",
    "result.agent_ratio",
    "result.cure_schedule",
    "result.verified_source",
    "result.fact_warning",
    "result.open_items",
    "result.next_action",
    "insufficient.eyebrow",
    "insufficient.guardrail",
    "guardrail.eyebrow",
    "guardrail.headline",
    "guardrail.body",
    "decision_line.technical",
    "decision_line.compliance",
    "decision_line.quotation",
    "decision_line.logistics",
    "source.title",
    "source.caption",
    "source.physical_page",
    "source.open_original",
    "readiness.title",
    "readiness.customer",
    "readiness.internal",
    "readiness.stock",
    "readiness.price",
    "readiness.freight",
    "readiness.payment",
    "readiness.documents",
    "readiness.document_caption",
    "review.facts",
    "review.ambiguities",
    "review.limits",
    "review.followups",
    "draft.subject",
    "draft.caption",
    "draft.english_reply",
    "draft.english_email",
    "draft.copy",
    "draft.copied",
    "draft.editor_missing",
    "export.title",
    "export.caption",
    "export.markdown",
    "export.print",
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
    "footer.scope",
    "footer.oneshot",
    "category.technical",
    "category.compliance",
    "category.commercial",
    "category.logistics",
    "status.inquiry_explicit",
}


def test_locales_default_to_english_and_reject_unknown_values() -> None:
    assert DEFAULT_LOCALE == "en"
    assert SUPPORTED_LOCALES == ("en", "zh-CN")
    assert normalize_locale(None) == "en"
    assert normalize_locale("zh-CN") == "zh-CN"
    assert normalize_locale("invalid") == "en"


def test_translation_catalogs_have_identical_keys() -> None:
    assert text("entry.title", "en").startswith("First decide")
    assert text("entry.title", "zh-CN").startswith("先判断")
    assert set(localization._MESSAGES["en"]) == set(localization._MESSAGES["zh-CN"])


def test_one_shot_app_localization_keys_are_complete() -> None:
    assert ONE_SHOT_KEYS <= set(localization._MESSAGES["en"])
    assert ONE_SHOT_KEYS <= set(localization._MESSAGES["zh-CN"])


def test_ordinary_user_copy_avoids_internal_implementation_terms() -> None:
    forbidden = ("JSON", "fingerprint", "资料目录指纹", "工作台")
    visible_copy = "\n".join(
        value for catalog in localization._MESSAGES.values() for value in catalog.values()
    )

    assert all(term not in visible_copy for term in forbidden)


def _template(key: str, locale: str) -> str:
    """取界面模板原文，并把占位符填成占位值，便于检查静态文案。"""
    raw = localization._MESSAGES[locale][key]
    for token in ("{products}", "{value}", "{scope}", "{page}"):
        raw = raw.replace(token, "X")
    return raw


def test_visible_copy_no_longer_announces_a_public_demo() -> None:
    """一次性工具面向业务员，界面实际用到的文案里不再出现"演示版"这类与使用者无关的措辞。"""
    for locale in SUPPORTED_LOCALES:
        visible_copy = "\n".join(
            _template(key, locale) for key in sorted(ONE_SHOT_KEYS)
        ).lower()
        assert "demo" not in visible_copy
        assert "演示" not in visible_copy
        assert "vercel" not in visible_copy


def test_scope_and_one_shot_footers_are_localized() -> None:
    assert text("footer.scope", "en", products="EPON").startswith("Evidence scope")
    assert text("footer.scope", "zh-CN", products="EPON").startswith("证据范围")
    assert "no inquiry history is kept" in text("footer.oneshot", "en").lower()
    assert "cached on this machine" in text("footer.oneshot", "en").lower()
    assert "不保留询盘记录" in text("footer.oneshot", "zh-CN")
    assert "缓存" in text("footer.oneshot", "zh-CN")


def test_result_and_export_copy_is_localized_in_both_locales() -> None:
    for key in ("result.validated", "insufficient.eyebrow", "export.title", "export.markdown"):
        assert text(key, "en") != text(key, "zh-CN")


def test_browser_script_persists_only_a_whitelisted_locale() -> None:
    script = browser_locale_script("zh-CN")

    assert "chemicalTrade.locale" in script
    assert "localStorage" in script
    assert '["en", "zh-CN"]' in script
    assert "zh-CN" in script
    assert "DEEPSEEK" not in script
