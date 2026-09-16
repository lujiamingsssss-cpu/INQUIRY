"""一次性工具的界面契约测试。

覆盖三件事：

1. 入口是**单页**，不再有编号步骤导航与审阅按钮；
2. 结果页把结论、已核验参数、来源、复核卡、回复草稿与导出全部渲染出来；
3. **不落盘**：结果只在会话内存中往返，且模块源码不含任何写文件调用。
"""

import json
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from chemical_trade_copilot import streamlit_app
from chemical_trade_copilot.inquiry_analysis import (
    InquiryAnalysis,
    KeyParameter,
    RequirementAssessment,
    SourceCitation,
)
from chemical_trade_copilot.inquiry_review import build_review_card
from chemical_trade_copilot.retrieval import SearchResult
from chemical_trade_copilot.workflow import analyze_inquiry_with_evidence


APP = Path(__file__).parents[1] / "src" / "chemical_trade_copilot" / "streamlit_app.py"


# --------------------------------------------------------------------------
# 假 st：直接调用渲染函数，逐条记录界面调用
# --------------------------------------------------------------------------


class _RecordingColumn:
    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class RecordingSt:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.session_state: dict = {}
        self.query_params: dict = {}

    def _record(self, name: str, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def html(self, body, **kwargs):
        self._record("html", body)

    def header(self, body, **kwargs):
        self._record("header", body)

    def subheader(self, body, **kwargs):
        self._record("subheader", body)

    def title(self, body, **kwargs):
        self._record("title", body)

    def write(self, body, **kwargs):
        self._record("write", body)

    def caption(self, body, **kwargs):
        self._record("caption", body)

    def markdown(self, body, **kwargs):
        self._record("markdown", body)

    def divider(self):
        self._record("divider")

    def warning(self, body, **kwargs):
        self._record("warning", body)

    def info(self, body, **kwargs):
        self._record("info", body)

    def error(self, body, **kwargs):
        self._record("error", body)

    def text_input(self, label, **kwargs):
        self._record("text_input", label, **kwargs)

    def text_area(self, label, **kwargs):
        self._record("text_area", label, **kwargs)

    def button(self, label, **kwargs) -> bool:
        self._record("button", label)
        return False

    def download_button(self, label, **kwargs) -> bool:
        self._record("download_button", label, **kwargs)
        return False

    def columns(self, spec, **kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [_RecordingColumn() for _ in range(count)]

    def container(self, *args, **kwargs):
        self._record("container", *args, **kwargs)
        return _RecordingColumn()

    def values(self, name: str) -> list:
        return [args[0] for call, args, _ in self.calls if call == name]

    def joined(self) -> str:
        return "\n".join(
            str(arg)
            for _, args, _ in self.calls
            for arg in args
            if isinstance(arg, str)
        )


# --------------------------------------------------------------------------
# 夹具：真实由本地逻辑构造，不调用模型
# --------------------------------------------------------------------------


def _citation() -> SourceCitation:
    return SourceCitation(
        product="EPON Resin 8280",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        page_number=3,
    )


def _supported_analysis() -> InquiryAnalysis:
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
        source_limitations=("TDS 为 2005 年重新发布。",),
        follow_up_questions=("预计采购数量与时间窗口？",),
        next_action="needs_commercial_input",
    )


def _insufficient_analysis() -> InquiryAnalysis:
    return InquiryAnalysis(
        summary_zh="当前检索证据不足，系统已停止生成产品推荐。",
        recommendation_status="insufficient_evidence",
        recommended_product=None,
        recommendation_reasons=("模型输出未通过本地证据校验，未采用其结论。",),
        requirements=(),
        key_parameters=(),
        evidence_gaps=("缺少长期耐热与食品接触证据。",),
        source_limitations=("本次自动核验范围仅包括已批准 TDS。",),
        follow_up_questions=("请确认最终用途与目标法规。",),
        next_action="needs_technical_confirmation",
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


def _card(analysis: InquiryAnalysis, inquiry: str):
    return build_review_card(
        inquiry,
        analysis,
        _ranked(),
        available_evidence=_ranked(),
    )


INQUIRY = (
    "For an EPON Resin 8280 system cured with MPDA, confirm the heat deflection "
    "temperature, and quote CFR Santos for 5 metric tons."
)


# --------------------------------------------------------------------------
# 入口：单页、无步骤导航
# --------------------------------------------------------------------------


def test_entry_is_a_single_page_without_step_navigation(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    app = AppTest.from_file(str(APP)).run(timeout=60)

    assert not app.exception
    assert any("First decide" in item.value for item in app.title)
    labels = [button.label for button in app.button]
    assert any("Analyze inquiry" in label for label in labels)
    # 8 页编号导航已移除
    assert not any(re.match(r"\*\*0[1-8]\*\*", label or "") for label in labels)
    # 也没有"新询盘/重新分析"这类审阅期按钮
    assert not any("Start a new inquiry" in (label or "") for label in labels)
    assert not any("Reanalyze" in (label or "") for label in labels)


def test_entry_states_the_one_shot_scope_and_missing_key(monkeypatch) -> None:
    # 指向一个不存在的本机配置，隔离真实 .env.local，从而复现"未配置密钥"状态。
    monkeypatch.setenv("CHEMICAL_TRADE_ENV_FILE", str(APP.parents[2] / "absent.env"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    app = AppTest.from_file(str(APP)).run(timeout=60)

    captions = " ".join(item.value for item in app.caption)
    assert "Nothing is stored" in captions
    assert "Evidence scope" in captions
    assert "demo" not in captions.lower()
    assert app.info
    assert "DeepSeek API key" in app.info[0].value


def test_empty_inquiry_is_rejected_before_any_model_call(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    app = AppTest.from_file(str(APP)).run(timeout=60)
    app.button[0].click().run(timeout=60)

    assert app.error
    assert "Enter a customer inquiry" in app.error[0].value


# --------------------------------------------------------------------------
# 结果页：内容完整
# --------------------------------------------------------------------------


def test_supported_result_renders_conclusion_evidence_reply_and_export(
    monkeypatch,
) -> None:
    analysis = _supported_analysis()
    inquiry = (
        "For an EPON Resin 8280 system cured with MPDA, confirm the heat deflection "
        "temperature, mix ratio, cure schedule and test method."
    )
    card = _card(analysis, inquiry)
    result = streamlit_app.SimpleNamespace(inquiry=inquiry, analysis=analysis, card=card)

    fake = RecordingSt()
    monkeypatch.setattr(streamlit_app, "st", fake)

    streamlit_app._render_result(result, "en")

    joined = fake.joined()
    assert "EPON Resin 8280" in fake.values("header")
    assert any("Technical reply ready" in value for value in fake.values("subheader"))
    # 已核验事实卡：数值、方法、条件与来源物理页同组出现
    assert "156" in joined and "ASTM D648" in joined
    assert "MPDA" in joined and "14.4 pbw" in joined
    assert "physical page 3" in joined
    # 回复草稿可编辑且不自动发送
    assert any(
        "Editable English email" == label for label in fake.values("text_area")
    )
    assert "The app does not connect to an inbox" in joined
    # 导出：Markdown 与可打印 HTML 两个下载入口
    downloads = fake.values("download_button")
    assert any("Markdown" in label for label in downloads)
    assert any("printable HTML" in label for label in downloads)


def test_insufficient_result_never_offers_a_product_or_temperature(
    monkeypatch,
) -> None:
    analysis = _insufficient_analysis()
    inquiry = "请推荐可在 200°C 连续使用的食品接触环氧涂层，并给出认证和长期寿命数据。"
    card = _card(analysis, inquiry)
    result = streamlit_app.SimpleNamespace(inquiry=inquiry, analysis=analysis, card=card)

    fake = RecordingSt()
    monkeypatch.setattr(streamlit_app, "st", fake)

    streamlit_app._render_result(result, "en")

    assert not fake.values("header")
    joined = fake.joined()
    assert "Current evidence is insufficient" in joined
    # 不得出现任何"已核验参数"卡片；引用客户原话（其中可能含 200°C）是允许的，
    # 因为那是询盘事实，不是系统给出的未核验数值。
    assert "Verified fact" not in joined
    assert "156" not in joined
    assert "ASTM D648" not in joined
    assert "200°C 连续使用的食品接触环氧涂层" in joined


def test_fail_closed_result_shows_the_guardrail_notice(monkeypatch) -> None:
    analysis = _insufficient_analysis()
    inquiry = "请推荐可在 200°C 连续使用的食品接触环氧涂层。"
    card = _card(analysis, inquiry)
    result = streamlit_app.SimpleNamespace(inquiry=inquiry, analysis=analysis, card=card)

    fake = RecordingSt()
    monkeypatch.setattr(streamlit_app, "st", fake)

    streamlit_app._render_result(result, "en")

    assert any("Safe fallback applied" in value for value in fake.values("html"))


def test_result_page_is_localized_in_chinese(monkeypatch) -> None:
    analysis = _supported_analysis()
    inquiry = "EPON Resin 8280 MPDA 热变形温度与配比"
    card = _card(analysis, inquiry)
    result = streamlit_app.SimpleNamespace(inquiry=inquiry, analysis=analysis, card=card)

    fake = RecordingSt()
    monkeypatch.setattr(streamlit_app, "st", fake)

    streamlit_app._render_result(result, "zh-CN")

    joined = fake.joined()
    assert "证据" in joined
    # 中文界面不得出现英文的眉标/标题句
    assert "Evidence validated" not in joined
    assert "Current evidence is insufficient" not in joined


# --------------------------------------------------------------------------
# 不落盘
# --------------------------------------------------------------------------


def test_result_round_trips_through_session_memory_only(monkeypatch) -> None:
    fake = RecordingSt()
    monkeypatch.setattr(streamlit_app, "st", fake)
    analysis = _supported_analysis()
    card = _card(analysis, INQUIRY)

    streamlit_app._store_result(INQUIRY, analysis, card, "fingerprint-1")
    result = streamlit_app._load_result()

    assert result is not None
    assert result.inquiry == INQUIRY
    assert result.fingerprint == "fingerprint-1"
    assert result.analysis.recommended_product == "EPON Resin 8280"
    assert result.card.facts is not None
    # 载荷是 JSON 字符串，只存在于会话状态
    assert isinstance(fake.session_state[streamlit_app._RESULT_KEY], str)
    json.loads(fake.session_state[streamlit_app._RESULT_KEY])

    streamlit_app._clear_result()
    assert streamlit_app._load_result() is None


def test_app_module_contains_no_file_writing_calls() -> None:
    """一次性工具不得持久化：模块源码里不允许出现写文件调用。"""
    source = APP.read_text(encoding="utf-8")
    forbidden = (
        "write_text(",
        "write_bytes(",
        "json.dump(",
        "open(",
        "to_csv(",
        "shutil.",
        "os.remove",
        "os.makedirs",
    )

    present = [token for token in forbidden if token in source]

    assert present == [], f"发现写文件调用: {present}"


def test_workflow_returns_evidence_for_analysis_and_review_without_model_on_card(
    monkeypatch,
) -> None:
    """复核卡是纯本地计算：不得额外调用模型。"""

    class RecordingAnalyzer:
        def __init__(self, result: InquiryAnalysis) -> None:
            self.result = result
            self.calls: list[list] = []

        def analyze(self, inquiry, evidence):
            self.calls.append(list(evidence))
            return self.result

    class StubIndex:
        def query(self, query, *, limit, doc_types):
            return _ranked()

        def pages(self, *, doc_types):
            return []

    class StubPlanner:
        def plan(self, inquiry):
            from chemical_trade_copilot.inquiry_analysis import RetrievalPlan

            return RetrievalPlan(search_query="epon mpda hdt", document_types=("TDS",))

    analyzer = RecordingAnalyzer(_supported_analysis())
    analysis, collected = analyze_inquiry_with_evidence(
        INQUIRY,
        index=StubIndex(),
        planner=StubPlanner(),
        analyzer=analyzer,
        limit=3,
    )

    assert analysis.recommended_product == "EPON Resin 8280"
    assert len(analyzer.calls) == 1
    assert collected.evidence == tuple(analyzer.calls[0])
