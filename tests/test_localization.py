import json

import pytest

from chemical_trade_copilot import localization
from chemical_trade_copilot.localization import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    browser_locale_script,
    normalize_locale,
    text,
)
from chemical_trade_copilot.review_workspace import REVIEW_PAGES
from chemical_trade_copilot.review_translation import (
    ReviewTranslationBundle,
    collect_review_translation_items,
    collect_review_translation_tokens,
    translate_items,
)
from chemical_trade_copilot.inquiry_analysis import InquiryAnalysis
from chemical_trade_copilot.inquiry_review import ReviewSessionState
from test_streamlit_app import _review_session_json, _supported_json


class RecordingTranslationClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return json.dumps(self.payload, ensure_ascii=False)


def test_locales_default_to_english_and_reject_unknown_values() -> None:
    assert DEFAULT_LOCALE == "en"
    assert SUPPORTED_LOCALES == ("en", "zh-CN")
    assert normalize_locale(None) == "en"
    assert normalize_locale("zh-CN") == "zh-CN"
    assert normalize_locale("invalid") == "en"


def test_translation_catalogs_have_identical_keys() -> None:
    assert text("entry.title", "en").startswith("First decide")
    assert text("entry.title", "zh-CN").startswith("先判断")


def test_eight_page_localization_keys_are_complete() -> None:
    required = {
        *(f"page.{name}" for name in REVIEW_PAGES),
        *(f"page_title.{name}" for name in REVIEW_PAGES),
        "backup.open",
        "backup.save",
        "backup.invalid",
        "draft.optimize",
        "draft.generate_new_version",
        "print.action",
        "record.complete",
        "record.decision",
        "record.email_version",
        "record.analysis_revision",
        "record.no_email",
        "state.open",
        "state.closed",
    }

    assert required <= set(localization._MESSAGES["en"])
    assert set(localization._MESSAGES["en"]) == set(
        localization._MESSAGES["zh-CN"]
    )


def test_ordinary_user_copy_avoids_internal_implementation_terms() -> None:
    forbidden = ("JSON", "fingerprint", "资料目录指纹", "工作台")
    visible_copy = "\n".join(
        value for catalog in localization._MESSAGES.values() for value in catalog.values()
    )

    assert all(term not in visible_copy for term in forbidden)


def test_target_markets_and_backup_entry_are_localized_independently() -> None:
    assert text("entry.target_market", "en") == "Target market"
    assert text("entry.target_market", "zh-CN") == "目标市场"
    assert text("market.unknown", "en") == "Not specified"
    assert text("market.unknown", "zh-CN") == "未指定"
    assert text("market.other", "en") == "Other"
    assert text("market.other", "zh-CN") == "其他"
    assert text("backup.open", "en") == "Open review backup"
    assert text("backup.open", "zh-CN") == "打开审阅备份"
    assert text("backup.file", "en") == "Choose a review backup file"
    assert text("backup.file", "zh-CN") == "选择审阅备份文件"
    assert "DeepSeek API key" in text("entry.api_key_missing", "en")
    assert "DeepSeek API Key" in text("entry.api_key_missing", "zh-CN")


def test_deployment_scope_is_described_as_a_public_demo() -> None:
    assert text("entry.footer", "en", scope="Approved evidence").startswith(
        "Public demo"
    )
    assert text("entry.footer", "zh-CN", scope="已批准证据").startswith("公开演示")


def test_review_page_navigation_and_titles_are_localized() -> None:
    assert text("page.inquiry", "en") == "Inquiry"
    assert text("page.evidence", "en") == "Evidence"
    assert text("page.record", "zh-CN") == "记录"
    assert text("page_title.conclusion", "en") == "Review conclusion"
    assert text("page_title.evidence", "zh-CN") == "审阅证据"


def test_browser_script_persists_only_a_whitelisted_locale() -> None:
    script = browser_locale_script("zh-CN")

    assert "chemicalTrade.locale" in script
    assert "localStorage" in script
    assert '["en", "zh-CN"]' in script
    assert "zh-CN" in script
    assert "DEEPSEEK" not in script


def test_translation_preserves_protected_technical_tokens() -> None:
    client = RecordingTranslationClient(
        {
            "translations": [
                {
                    "item_id": "requirement.0",
                    "text": "EPON Resin 8280 在 156 °C 条件下的 ASTM D648 结果。",
                }
            ]
        }
    )

    bundle = translate_items(
        client,
        target_locale="zh-CN",
        analysis_revision="revision-1",
        items={
            "requirement.0": "EPON Resin 8280 ASTM D648 result at 156 °C."
        },
        protected_tokens=("EPON Resin 8280", "ASTM D648", "156 °C"),
    )

    assert isinstance(bundle, ReviewTranslationBundle)
    assert bundle.target_locale == "zh-CN"
    assert bundle.texts["requirement.0"].startswith("EPON Resin 8280")
    assert len(client.calls) == 1


def test_translation_is_rejected_when_a_protected_value_changes() -> None:
    client = RecordingTranslationClient(
        {
            "translations": [
                {
                    "item_id": "requirement.0",
                    "text": "EPON Resin 8280 的结果是 165 °C。",
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="protected token"):
        translate_items(
            client,
            target_locale="zh-CN",
            analysis_revision="revision-1",
            items={"requirement.0": "EPON Resin 8280 result at 156 °C."},
            protected_tokens=("EPON Resin 8280", "156 °C"),
        )


def test_translation_is_rejected_when_it_adds_a_numeric_claim() -> None:
    client = RecordingTranslationClient(
        {
            "translations": [
                {
                    "item_id": "requirement.0",
                    "text": "原始结果为 156 °C，建议值为 165 °C。",
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="numeric tokens"):
        translate_items(
            client,
            target_locale="zh-CN",
            analysis_revision="revision-1",
            items={"requirement.0": "The result is 156 °C."},
            protected_tokens=("156 °C",),
        )


def test_review_translation_collection_keeps_evidence_identity_out_of_translatable_text() -> None:
    analysis = InquiryAnalysis.model_validate_json(_supported_json())
    session = ReviewSessionState.model_validate_json(_review_session_json())

    items = collect_review_translation_items(analysis, session)
    tokens = collect_review_translation_tokens(analysis, session)

    assert items["analysis.summary"] == "技术条件有证据。"
    assert any(key.endswith(".support") for key in items)
    assert "EPON Resin 8280" in tokens
    assert "156" in tokens
    assert "°C" in tokens
    assert all("source_file" not in key for key in items)
