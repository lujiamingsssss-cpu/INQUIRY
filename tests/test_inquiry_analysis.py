import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chemical_trade_copilot.inquiry_analysis import (
    DeepSeekInquiryAnalyzer,
    DeepSeekJsonClient,
    InquiryRetrievalPlanner,
    KeyParameter,
    PlannedRetriever,
    SourceCitation,
    merge_ranked_with_corpus,
)
from chemical_trade_copilot.pdf_pages import PageRecord
from chemical_trade_copilot.retrieval import SearchResult


class StubJsonClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return json.dumps(self.payload, ensure_ascii=False)


class SequenceJsonClient:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return json.dumps(self.payloads.pop(0), ensure_ascii=False)


def _evidence() -> SearchResult:
    page_text = (
        "Metaphenylenediamine (MPDA) 14.4 pbw. Cure Schedule 2 hr/80 C + "
        "2 hr/150 C. Heat Deflection Temperature ASTM D648 156 C."
    )
    return SearchResult(
        text="Heat Deflection Temperature ASTM D648 156 C",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        source_path=Path("C:/EPON-8280.pdf"),
        page_number=3,
        distance=0.1,
        page_text=page_text,
    )


def _supported_payload(source_file: str | None = None) -> dict[str, object]:
    citation = {
        "product": "EPON Resin 8280",
        "source_file": source_file
        or "TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        "page_number": 3,
    }
    return {
        "summary_zh": "客户询问 MPDA 固化体系的耐热表现并要求巴西库存信息。",
        "recommendation_status": "supported",
        "recommended_product": "EPON Resin 8280",
        "recommendation_reasons": ["TDS 给出了 MPDA 固化体系数据。"],
        "requirements": [
            {
                "category": "technical",
                "requirement": "MPDA 固化后的 HDT",
                "status": "supported",
                "evidence": [citation],
            },
            {
                "category": "commercial",
                "requirement": "巴西库存",
                "status": "needs_confirmation",
                "evidence": [],
            },
        ],
        "key_parameters": [
            {
                "name": "Heat Deflection Temperature",
                "value": "156",
                "unit": "°C",
                "conditions": "MPDA 14.4 pbw; cure 2 h/80°C + 2 h/150°C",
                "test_method": "ASTM D648",
                "curing_agent": "MPDA",
                "mix_ratio": "EPON Resin 8280 100 pbw : MPDA 14.4 pbw",
                "cure_schedule": "2 h/80°C + 2 h/150°C",
                "citation": citation,
            }
        ],
        "evidence_gaps": ["当前资料不包含巴西库存。"],
        "source_limitations": ["TDS 重新发布于 2005 年，页脚修订日期为 2016 年。"],
        "follow_up_questions": ["请确认交付城市和期望交期。"],
        "next_action": "needs_commercial_input",
    }


def test_analyzer_returns_cited_inquiry_workflow_and_uses_full_page_evidence() -> None:
    client = StubJsonClient(_supported_payload())
    analyzer = DeepSeekInquiryAnalyzer(client)

    result = analyzer.analyze("请确认 MPDA HDT 和巴西库存", [_evidence()])

    assert result.recommended_product == "EPON Resin 8280"
    assert result.key_parameters[0].conditions == "MPDA-cured unfilled casting"
    assert result.requirements[1].status == "needs_confirmation"
    assert result.next_action == "needs_commercial_input"
    assert "2016" in result.source_limitations[0]
    system_prompt, user_prompt = client.calls[0]
    assert "json" in system_prompt.lower()
    assert "当前检索证据不足" in system_prompt
    assert "不得把 SDS" in system_prompt
    assert "Do not split a cured thermal property" in system_prompt
    assert "omit that thermal value everywhere" in system_prompt
    assert _evidence().page_text in user_prompt


def test_analyzer_accepts_full_corpus_page_records() -> None:
    evidence = _evidence()
    page = PageRecord(
        text=evidence.page_text,
        product=evidence.product,
        doc_type="TDS",
        source_file=evidence.source_file,
        source_path=evidence.source_path,
        page_number=evidence.page_number,
    )
    client = StubJsonClient(_supported_payload())

    result = DeepSeekInquiryAnalyzer(client).analyze("请确认 MPDA HDT", [page])

    assert result.recommended_product == "EPON Resin 8280"
    assert page.text in client.calls[0][1]


def test_merge_ranked_with_corpus_keeps_rank_order_and_deduplicates_pages() -> None:
    ranked = _evidence()
    duplicate = PageRecord(
        text=ranked.page_text,
        product=ranked.product,
        doc_type="TDS",
        source_file=ranked.source_file,
        source_path=ranked.source_path,
        page_number=ranked.page_number,
    )
    other = PageRecord(
        text="other full page",
        product="D.E.R. 331",
        doc_type="TDS",
        source_file="TDS - DOW D.E.R. 331 - 2009.pdf",
        source_path=Path("C:/DER-331.pdf"),
        page_number=1,
    )

    evidence = merge_ranked_with_corpus([ranked], [other, duplicate])

    assert evidence == [duplicate, other]


def test_analyzer_fails_closed_for_a_citation_not_in_retrieved_evidence() -> None:
    client = StubJsonClient(_supported_payload("invented.pdf"))
    analyzer = DeepSeekInquiryAnalyzer(client)

    result = analyzer.analyze("请确认 MPDA HDT", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.recommended_product is None
    assert "未通过本地证据校验" in result.evidence_gaps[0]


def test_analyzer_canonicalizes_a_single_evidence_product_name() -> None:
    payload = _supported_payload()
    payload["recommended_product"] = "EPON Resin 8280 with MPDA curing agent"
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请确认 MPDA HDT", [_evidence()])

    assert result.recommended_product == "EPON Resin 8280"


def test_analyzer_fails_closed_when_supported_recommendation_has_no_cited_technical_requirement() -> None:
    payload = _supported_payload()
    payload["requirements"] = [
        {
            "category": "commercial",
            "requirement": "巴西库存",
            "status": "needs_confirmation",
            "evidence": [],
        }
    ]
    payload["key_parameters"] = []
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请推荐可用产品并确认巴西库存", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.recommended_product is None


def test_analyzer_canonicalizes_thermal_context_from_verified_fact() -> None:
    payload = _supported_payload()
    parameter = payload["key_parameters"][0]  # type: ignore[index]
    parameter["mix_ratio"] = "wrong ratio"  # type: ignore[index]
    parameter["cure_schedule"] = "24 h/23°C + wrong column"  # type: ignore[index]
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请确认 MPDA HDT", [_evidence()])

    assert result.key_parameters[0].mix_ratio == (
        "EPON Resin 8280 100 pbw : MPDA 14.4 pbw"
    )
    assert result.key_parameters[0].cure_schedule == "2 h/80°C + 2 h/150°C"


def test_analyzer_fails_closed_for_contradictory_verified_property_absence() -> None:
    payload = _supported_payload()
    payload["summary_zh"] = "EPON Resin 8280 未提供任何高温性能。"
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请确认 MPDA HDT", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.key_parameters == ()


def test_analyzer_fails_closed_for_unsupported_certification_claim() -> None:
    payload = _supported_payload()
    payload["requirements"].append(  # type: ignore[union-attr]
        {
            "category": "compliance",
            "requirement": "食品接触认证",
            "status": "supported",
            "evidence": [
                {
                    "product": "EPON Resin 8280",
                    "source_file": "TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
                    "page_number": 3,
                }
            ],
        }
    )
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("是否有食品接触认证", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.key_parameters == ()


def test_analyzer_returns_insufficient_evidence_without_recommending_product() -> None:
    payload = {
        "summary_zh": "客户要求 200°C 连续使用和食品接触认证。",
        "recommendation_status": "insufficient_evidence",
        "recommended_product": None,
        "recommendation_reasons": ["当前检索证据不足。"],
        "requirements": [
            {
                "category": "technical",
                "requirement": "200°C 连续使用",
                "status": "insufficient_evidence",
                "evidence": [],
            },
            {
                "category": "compliance",
                "requirement": "食品接触认证",
                "status": "needs_confirmation",
                "evidence": [],
            },
        ],
        "key_parameters": [],
        "evidence_gaps": ["当前资料不支持连续使用温度或适用地区认证。"],
        "source_limitations": ["当前证据仅限所检索资料的日期和适用地区。"],
        "follow_up_questions": ["请确认目标国家和适用法规。"],
        "next_action": "insufficient_product_evidence",
    }
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请推荐 200°C 食品接触涂层", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.recommended_product is None
    assert result.key_parameters == ()


def test_analyzer_fails_closed_for_unbound_thermal_value_added_by_model() -> None:
    payload = {
        "summary_zh": "客户要求 200°C，但当前产品最高仅 156°C。",
        "recommendation_status": "insufficient_evidence",
        "recommended_product": None,
        "recommendation_reasons": ["当前检索证据不足。"],
        "requirements": [
            {
                "category": "technical",
                "requirement": "200°C 连续使用",
                "status": "insufficient_evidence",
                "evidence": [],
            }
        ],
        "key_parameters": [],
        "evidence_gaps": ["资料只显示 156°C。"],
        "source_limitations": ["资料较旧。"],
        "follow_up_questions": [],
        "next_action": "insufficient_product_evidence",
    }
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("需要 200°C 连续使用", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.recommended_product is None
    assert result.key_parameters == ()
    assert "156" not in result.model_dump_json()


def test_analyzer_fails_closed_when_a_temperature_parameter_is_renamed() -> None:
    payload = _supported_payload()
    parameter = payload["key_parameters"][0]  # type: ignore[index]
    parameter["name"] = "Continuous service temperature"  # type: ignore[index]
    parameter["value"] = "200"  # type: ignore[index]
    parameter["unit"] = "C"  # type: ignore[index]
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请推荐可在 200°C 连续使用的产品", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.key_parameters == ()


def test_analyzer_fails_closed_when_temperature_requirement_has_no_parameter() -> None:
    payload = _supported_payload()
    payload["requirements"][0]["requirement"] = "200 C continuous service temperature"  # type: ignore[index]
    payload["key_parameters"] = []
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("需要 200 C 连续使用", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.key_parameters == ()


def test_analyzer_does_not_treat_hdt_as_same_value_continuous_service_temperature() -> None:
    payload = _supported_payload()
    payload["requirements"][0]["requirement"] = "continuous service temperature 156 C"  # type: ignore[index]
    parameter = payload["key_parameters"][0]  # type: ignore[index]
    parameter["name"] = "Continuous service temperature"  # type: ignore[index]
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("需要 156 C 连续使用温度", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.key_parameters == ()


def test_baer_negative_golden_rejects_flash_point_as_service_temperature() -> None:
    cases = json.loads(
        (Path(__file__).parent / "fixtures" / "golden_retrieval_cases.json").read_text(
            encoding="utf-8"
        )
    )
    inquiry = next(
        case["inquiry"]
        for case in cases
        if case["id"]
        == "baer_xp9500_unsupported_continuous_service_temperature_en"
    )
    citation = {
        "product": "BAER XP9500",
        "source_file": "TDS - ACS BAER XP9500.pdf",
        "page_number": 1,
    }
    payload = {
        "summary_zh": "该闪点证明产品可以连续高温使用。",
        "recommendation_status": "supported",
        "recommended_product": "BAER XP9500",
        "recommendation_reasons": ["TDS reports a 315 C flash point."],
        "requirements": [
            {
                "category": "technical",
                "requirement": "continuous service temperature 315 C",
                "status": "supported",
                "evidence": [citation],
            }
        ],
        "key_parameters": [
            {
                "name": "Continuous service temperature",
                "value": "315",
                "unit": "C",
                "conditions": "Not stated",
                "test_method": "Not stated",
                "citation": citation,
            }
        ],
        "evidence_gaps": [],
        "source_limitations": ["Under Product Development"],
        "follow_up_questions": [],
        "next_action": "ready_to_reply",
    }
    evidence = SearchResult(
        text="Flash point: 315 C",
        product="BAER XP9500",
        doc_type="TDS",
        source_file="TDS - ACS BAER XP9500.pdf",
        source_path=Path("C:/BAER-XP9500.pdf"),
        page_number=1,
        distance=0.1,
        page_text="BAER XP-9500. Flash point: 315 C. Under Product Development.",
    )

    result = DeepSeekInquiryAnalyzer(StubJsonClient(payload)).analyze(inquiry, [evidence])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.recommended_product is None
    assert result.key_parameters == ()


@pytest.mark.parametrize(
    ("summary", "reason"),
    [
        ("该产品可在 156 C 长期连续使用。", "HDT 表明可在 156 C 持续工作。"),
        (
            "Suitable for continuous operation at 156 C.",
            "HDT supports indefinite operation at 156 C.",
        ),
    ],
)
def test_analyzer_rejects_temperature_values_in_free_narrative(
    summary: str, reason: str
) -> None:
    payload = _supported_payload()
    payload["summary_zh"] = summary
    payload["recommendation_reasons"] = [reason]
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请确认 MPDA 固化后的 HDT 156 C", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.key_parameters == ()


def test_analyzer_fails_closed_when_commercial_requirement_is_marked_supported() -> None:
    payload = _supported_payload()
    payload["requirements"][1]["status"] = "supported"  # type: ignore[index]
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请确认 MPDA HDT 和巴西库存", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.recommended_product is None


def test_analyzer_fails_closed_when_compliance_requirement_is_marked_supported() -> None:
    payload = _supported_payload()
    payload["requirements"].append(  # type: ignore[union-attr]
        {
            "category": "compliance",
            "requirement": "FDA 21 CFR 175.300 compliant",
            "status": "supported",
            "evidence": [],
        }
    )
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("是否符合 FDA 21 CFR 175.300", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.recommended_product is None


def test_analyzer_retries_once_with_grounding_validation_feedback() -> None:
    invalid = {
        "summary_zh": "客户要求 200°C，但当前产品最高仅 156°C。",
        "recommendation_status": "insufficient_evidence",
        "recommended_product": None,
        "recommendation_reasons": ["当前检索证据不足。"],
        "requirements": [],
        "key_parameters": [],
        "evidence_gaps": ["资料只显示 156°C。"],
        "source_limitations": ["资料较旧。"],
        "follow_up_questions": [],
        "next_action": "insufficient_product_evidence",
    }
    corrected = {
        **invalid,
        "summary_zh": "客户要求 200°C，当前检索证据不足。",
        "evidence_gaps": ["缺少带完整条件的连续使用温度证据。"],
    }
    client = SequenceJsonClient([invalid, corrected])

    result = DeepSeekInquiryAnalyzer(client).analyze(
        "需要 200°C 连续使用", [_evidence()]
    )

    assert result.recommendation_status == "insufficient_evidence"
    assert len(client.calls) == 2
    assert "temperature values are allowed only" in client.calls[1][1]


def test_safe_fallback_preserves_explicit_compliance_request() -> None:
    invalid = {
        "summary_zh": "客户要求 200°C，但当前产品最高仅 156°C。",
        "recommendation_status": "insufficient_evidence",
        "recommended_product": None,
        "recommendation_reasons": ["当前检索证据不足。"],
        "requirements": [],
        "key_parameters": [],
        "evidence_gaps": ["资料只显示 156°C。"],
        "source_limitations": ["资料较旧。"],
        "follow_up_questions": [],
        "next_action": "insufficient_product_evidence",
    }

    result = DeepSeekInquiryAnalyzer(StubJsonClient(invalid)).analyze(
        "请推荐可在 200°C 连续使用的食品接触环氧涂层，并给出认证和长期寿命数据。",
        [_evidence()],
    )

    requirements = {item.category: item for item in result.requirements}
    assert set(requirements) == {"technical", "compliance"}
    assert requirements["technical"].status == "insufficient_evidence"
    assert requirements["compliance"].status == "needs_confirmation"


def test_safe_fallback_preserves_all_explicit_request_categories() -> None:
    invalid = {
        "summary_zh": "invalid",
        "recommendation_status": "supported",
        "recommended_product": None,
        "recommendation_reasons": [],
        "requirements": [],
        "key_parameters": [],
        "evidence_gaps": [],
        "source_limitations": [],
        "follow_up_questions": [],
        "next_action": "ready_to_reply",
    }

    result = DeepSeekInquiryAnalyzer(StubJsonClient(invalid)).analyze(
        "Confirm continuous-use performance, FDA certification, stock and MOQ, "
        "then quote CFR Santos.",
        [_evidence()],
    )

    requirements = {item.category: item for item in result.requirements}
    assert set(requirements) == {
        "technical",
        "compliance",
        "commercial",
        "logistics",
    }
    assert requirements["technical"].status == "insufficient_evidence"
    assert all(
        requirements[category].status == "needs_confirmation"
        for category in ("compliance", "commercial", "logistics")
    )


@pytest.mark.parametrize(
    ("inquiry", "expected_categories"),
    [
        (
            "Is this product compliant with EU 10/2011? Quote DDP Hamburg.",
            {"technical", "compliance", "commercial", "logistics"},
        ),
        (
            "Can the coating reach 200 C? Provide technical support and a "
            "specification.",
            {"technical"},
        ),
        (
            "Does this product comply with FDA 21 CFR 175.300?",
            {"technical", "compliance"},
        ),
        (
            "Please confirm lead time.",
            {"technical", "commercial"},
        ),
    ],
)
def test_safe_fallback_uses_explicit_words_without_substring_false_positives(
    inquiry: str, expected_categories: set[str]
) -> None:
    invalid = {
        "summary_zh": "invalid",
        "recommendation_status": "supported",
        "recommended_product": None,
        "recommendation_reasons": [],
        "requirements": [],
        "key_parameters": [],
        "evidence_gaps": [],
        "source_limitations": [],
        "follow_up_questions": [],
        "next_action": "ready_to_reply",
    }

    result = DeepSeekInquiryAnalyzer(StubJsonClient(invalid)).analyze(
        inquiry, [_evidence()]
    )

    assert {item.category for item in result.requirements} == expected_categories


def test_analyzer_fails_closed_for_thermal_parameter_without_context() -> None:
    payload = _supported_payload()
    parameter = payload["key_parameters"][0]  # type: ignore[index]
    parameter["conditions"] = ""  # type: ignore[index]
    parameter["test_method"] = ""  # type: ignore[index]
    parameter["curing_agent"] = ""  # type: ignore[index]
    parameter["mix_ratio"] = ""  # type: ignore[index]
    parameter["cure_schedule"] = ""  # type: ignore[index]
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请确认 MPDA HDT", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.key_parameters == ()


def test_non_performance_parameter_does_not_repeat_test_method() -> None:
    parameter = KeyParameter(
        name="MPDA mix ratio",
        value="14.4",
        unit="pbw",
        conditions="",
        test_method="",
        citation=SourceCitation(
            product="EPON Resin 8280",
            source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
            page_number=3,
        ),
    )

    assert parameter.test_method == ""


def test_analyzer_fails_closed_for_unverified_nonthermal_parameter() -> None:
    payload = _supported_payload()
    payload["key_parameters"].append(  # type: ignore[union-attr]
        {
            "name": "Viscosity",
            "value": "999999",
            "unit": "mPa.s",
            "conditions": "invented conditions",
            "test_method": "invented method",
            "curing_agent": None,
            "mix_ratio": None,
            "cure_schedule": None,
            "citation": {
                "product": "EPON Resin 8280",
                "source_file": "TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
                "page_number": 3,
            },
        }
    )
    analyzer = DeepSeekInquiryAnalyzer(StubJsonClient(payload))

    result = analyzer.analyze("请确认 MPDA HDT 和黏度", [_evidence()])

    assert result.recommendation_status == "insufficient_evidence"
    assert result.key_parameters == ()


def test_retrieval_planner_removes_commercial_noise_and_selects_tds() -> None:
    client = StubJsonClient(
        {
            "search_query": (
                "D.E.R. 331 Automotive Coatings Marine and Protective Coatings"
            ),
            "document_types": ["TDS"],
        }
    )
    planner = InquiryRetrievalPlanner(client)

    plan = planner.plan(
        "越南客户需要汽车和船舶防护涂料用树脂，首单 5 吨，请报 CFR。"
    )

    assert "CFR" not in plan.search_query
    assert plan.document_types == ("TDS",)
    system_prompt, _ = client.calls[0]
    assert "Do not answer" in system_prompt
    assert "preserve" in system_prompt.lower()


class StubFilteredIndex:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, tuple[str, ...]]] = []

    def query(
        self, inquiry: str, *, limit: int, doc_types: tuple[str, ...]
    ) -> list[SearchResult]:
        self.calls.append((inquiry, limit, doc_types))
        return [_evidence()]


def test_planned_retriever_applies_query_and_document_type_plan() -> None:
    client = StubJsonClient(
        {
            "search_query": "EPON Resin 8280 high solids coatings",
            "document_types": ["TDS"],
        }
    )
    index = StubFilteredIndex()
    retriever = PlannedRetriever(index, InquiryRetrievalPlanner(client))

    results = retriever.query("full customer inquiry with CFR request", limit=3)

    assert results == [_evidence()]
    assert index.calls == [
        ("EPON Resin 8280 high solids coatings", 3, ("TDS",))
    ]


class StubOpenAIClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    def _create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        self.requests.append(kwargs)
        content = None if self.calls == 1 else '{"status":"ok"}'
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


def test_deepseek_json_client_retries_one_empty_json_response() -> None:
    openai_client = StubOpenAIClient()
    client = DeepSeekJsonClient("secret", client=openai_client)

    content = client.complete_json("return json", "input")

    assert content == '{"status":"ok"}'
    assert openai_client.calls == 2
    assert openai_client.requests[-1]["max_tokens"] == 6000
