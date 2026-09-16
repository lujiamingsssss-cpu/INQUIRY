import json
import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .inquiry_analysis import InquiryAnalysis
from .inquiry_review import ReviewSessionState


class JsonTranslationClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> str: ...


class TranslatedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    text: str


class TranslationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    translations: tuple[TranslatedItem, ...]


class ReviewTranslationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_revision: str
    target_locale: Literal["en", "zh-CN"]
    texts: dict[str, str]


_NUMBER_PATTERN = re.compile(r"(?<![\w.])[+-]?(?:\d+(?:[.,]\d+)?|\.\d+)(?![\w.])")


def collect_review_translation_items(
    analysis: InquiryAnalysis,
    session: ReviewSessionState,
) -> dict[str, str]:
    """Return only explanatory prose; evidence identity stays canonical."""
    items: dict[str, str] = {"analysis.summary": analysis.summary_zh}
    for index, value in enumerate(analysis.recommendation_reasons):
        items[f"analysis.reason.{index}"] = value
    for index, value in enumerate(analysis.evidence_gaps):
        items[f"analysis.gap.{index}"] = value
    for index, value in enumerate(analysis.source_limitations):
        items[f"analysis.source_limit.{index}"] = value
    for index, value in enumerate(analysis.follow_up_questions):
        items[f"analysis.followup.{index}"] = value
    for index, ambiguity in enumerate(session.card.ambiguities):
        items[f"card.ambiguity.{index}.impact"] = ambiguity.impact
        for option_index, value in enumerate(ambiguity.possible_interpretations):
            items[f"card.ambiguity.{index}.interpretation.{option_index}"] = value
    for index, candidate in enumerate(session.card.internal_candidates):
        items[f"card.candidate.{index}.support"] = candidate.support_statement
        for evidence_index, evidence in enumerate(candidate.evidence):
            for value_index, value in enumerate(evidence.applicable_conditions):
                items[
                    f"card.candidate.{index}.evidence.{evidence_index}.condition.{value_index}"
                ] = value
            for value_index, value in enumerate(evidence.limitations):
                items[
                    f"card.candidate.{index}.evidence.{evidence_index}.limitation.{value_index}"
                ] = value
    for index, value in enumerate(session.card.evidence_limitations):
        items[f"card.limit.{index}"] = value
    for follow_up in session.card.follow_ups:
        items[f"card.followup.{follow_up.item_id}"] = follow_up.question
    return {key: value for key, value in items.items() if value.strip()}


def collect_review_translation_tokens(
    analysis: InquiryAnalysis,
    session: ReviewSessionState,
) -> tuple[str, ...]:
    """Collect evidence-bound strings that a translation must reproduce verbatim."""
    values: list[str | None] = []
    values.append(analysis.recommended_product)
    for parameter in analysis.key_parameters:
        values.extend(
            (
                parameter.name,
                parameter.value,
                parameter.unit,
                parameter.test_method,
                parameter.curing_agent,
                parameter.mix_ratio,
                parameter.cure_schedule,
                parameter.citation.product,
                parameter.citation.source_file,
            )
        )
    for candidate in session.card.internal_candidates:
        values.append(candidate.product)
        for evidence in candidate.evidence:
            values.extend((evidence.product, evidence.source_file))
    return tuple(dict.fromkeys(value for value in values if value and value.strip()))


def translate_items(
    client: JsonTranslationClient,
    *,
    target_locale: Literal["en", "zh-CN"],
    analysis_revision: str,
    items: dict[str, str],
    protected_tokens: tuple[str, ...] = (),
) -> ReviewTranslationBundle:
    if not analysis_revision.strip():
        raise ValueError("Analysis revision must not be empty")
    if not items:
        return ReviewTranslationBundle(
            analysis_revision=analysis_revision,
            target_locale=target_locale,
            texts={},
        )
    schema = json.dumps(TranslationResponse.model_json_schema(), ensure_ascii=False)
    language = "Simplified Chinese" if target_locale == "zh-CN" else "English"
    system_prompt = f"""Translate each supplied review field into {language}.
Return one JSON object only and preserve every item_id exactly.
Do not summarize, add, remove, reinterpret, or correct technical content.
Keep product names, filenames, citations, numbers, units, test methods, formulation
ratios, and protected tokens exactly unchanged.
The JSON must validate against this schema: {schema}
"""
    user_prompt = json.dumps(
        {
            "target_locale": target_locale,
            "protected_tokens": list(protected_tokens),
            "items": [
                {"item_id": item_id, "text": value}
                for item_id, value in items.items()
            ],
        },
        ensure_ascii=False,
    )
    response = TranslationResponse.model_validate_json(
        client.complete_json(system_prompt, user_prompt)
    )
    translated = {item.item_id: item.text for item in response.translations}
    if set(translated) != set(items):
        raise ValueError("Translation item IDs do not match the requested fields")
    for item_id, source in items.items():
        output = translated[item_id]
        for token in protected_tokens:
            if token in source and token not in output:
                raise ValueError(f"Translation changed protected token: {token}")
        if _NUMBER_PATTERN.findall(source) != _NUMBER_PATTERN.findall(output):
            raise ValueError(f"Translation changed numeric tokens in {item_id}")
    return ReviewTranslationBundle(
        analysis_revision=analysis_revision,
        target_locale=target_locale,
        texts=translated,
    )
