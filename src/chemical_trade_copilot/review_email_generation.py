from dataclasses import dataclass
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .inquiry_analysis import InquiryAnalysis
from .inquiry_review import TechnicalReviewCard
from .localization import Locale
from .ui_presenter import build_email_draft


class DraftStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tone: Literal["neutral", "concise", "formal"]
    opening: Literal["standard", "direct"]
    question_format: Literal["bullets", "numbered", "paragraph"]


FollowUpIntent = Literal[
    "final_application",
    "operating_mode",
    "exposure_and_acceptance",
    "dry_state_acceptance_time",
    "target_compliance",
    "quantity_delivery_packaging",
    "quantity_destination",
    "destination_delivery_point",
    "destination_incoterm_place",
    "delivery_place_incoterm",
    "delivery_timing",
    "commercial_terms",
    "shipping_terms",
]


DraftKind = Literal["follow_up", "supported", "reviewer_candidate"]


def expected_draft_kind(
    analysis: InquiryAnalysis,
    selected_candidate: str,
) -> Literal["supported", "reviewer_candidate"]:
    if (
        analysis.recommendation_status == "supported"
        and analysis.recommended_product == selected_candidate
    ):
        return "supported"
    return "reviewer_candidate"


class DraftGenerationRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DraftKind
    style: DraftStyle
    language: Locale
    authorized_decision: Literal["proceed", "needs_information"]
    selected_candidate: str | None = None
    follow_up_ids: tuple[str, ...] | None = None
    follow_up_intents: tuple[FollowUpIntent, ...] | None = None

    @model_validator(mode="after")
    def validate_kind_fields(self) -> "DraftGenerationRecipe":
        if self.kind == "follow_up":
            if self.authorized_decision != "needs_information":
                raise ValueError("Follow-up recipe decision must request information")
            if self.selected_candidate is not None:
                raise ValueError("Follow-up recipe cannot select a candidate")
            if not self.follow_up_ids or len(self.follow_up_ids) != len(
                set(self.follow_up_ids)
            ):
                raise ValueError("Follow-up recipe requires unique question IDs")
            if self.language == "zh-CN":
                if self.follow_up_intents is None or len(
                    self.follow_up_intents
                ) != len(self.follow_up_ids):
                    raise ValueError(
                        "Chinese follow-up recipe requires one intent per question"
                    )
            elif self.follow_up_intents is not None:
                raise ValueError("English follow-up recipe cannot contain intents")
            return self
        if self.authorized_decision != "proceed":
            raise ValueError("Proceed recipe must authorize a technical reply")
        if not self.selected_candidate:
            raise ValueError("Proceed recipe requires a selected candidate")
        if self.follow_up_ids is not None or self.follow_up_intents is not None:
            raise ValueError("Proceed recipe cannot contain follow-up questions")
        return self


@dataclass(frozen=True, slots=True)
class GeneratedDraft:
    subject: str
    body: str
    follow_up_ids: tuple[str, ...] | None
    recipe: DraftGenerationRecipe


def classify_follow_up_intent(question: str) -> FollowUpIntent:
    normalized = " ".join(re.findall(r"\w+", question.casefold()))
    if not normalized:
        raise ValueError("Follow-up intent cannot be identified from an empty question")
    canonical: dict[str, FollowUpIntent] = {
        "what is the final application": "final_application",
        "is the operating condition continuous intermittent or a short peak": "operating_mode",
        "is 120 c continuous intermittent or a short peak": "operating_mode",
        "what exposure medium duration and failure criterion apply": "exposure_and_acceptance",
        "which acid concentration and exposure duration apply": "exposure_and_acceptance",
        "which dry state and acceptance time does the customer require": "dry_state_acceptance_time",
        "which target country regulation certification or customer standard applies": "target_compliance",
        "which target market documents are required": "target_compliance",
        "what quantity delivery window and packaging are required": "quantity_delivery_packaging",
        "confirm quantity preferred delivery window and packaging": "quantity_delivery_packaging",
        "confirm quantity and destination": "quantity_destination",
        "what destination port and delivery point should be used": "destination_delivery_point",
        "what destination port and named incoterm place should be used": "destination_incoterm_place",
        "which named delivery place and incoterm should be used": "delivery_place_incoterm",
        "does one month mean dispatch or arrival": "delivery_timing",
        "does three weeks mean ready shipped or delivered": "delivery_timing",
        "what price basis stock packaging payment and currency apply": "commercial_terms",
        "which incoterm lead time and freight basis apply": "shipping_terms",
    }
    try:
        return canonical[normalized]
    except KeyError as error:
        raise ValueError(
            f"Follow-up intent cannot be identified safely: {question}"
        ) from error


def _follow_up_draft(
    card: TechnicalReviewCard,
    recipe: DraftGenerationRecipe,
) -> GeneratedDraft:
    by_id = {item.item_id: item for item in card.follow_ups}
    assert recipe.follow_up_ids is not None
    try:
        follow_ups = tuple(by_id[item_id] for item_id in recipe.follow_up_ids)
    except KeyError as error:
        raise ValueError("Draft recipe contains an unknown follow-up ID") from error
    if recipe.language == "zh-CN":
        assert recipe.follow_up_intents is not None
        expected_intents = tuple(
            classify_follow_up_intent(item.question) for item in follow_ups
        )
        if recipe.follow_up_intents != expected_intents:
            raise ValueError("Draft recipe intents do not match the canonical questions")
        templates: dict[FollowUpIntent, str] = {
            "final_application": "请确认最终用途。",
            "operating_mode": "请确认设备工况是连续、间歇还是短时峰值。",
            "exposure_and_acceptance": "请确认接触介质、浓度、持续时间和验收判据。",
            "dry_state_acceptance_time": "请确认所需的干燥状态和验收时间。",
            "target_compliance": "请确认目标市场及所需法规或认证文件。",
            "quantity_delivery_packaging": "请确认数量、交付要求和包装要求。",
            "quantity_destination": "请确认数量和目的地。",
            "destination_delivery_point": "请确认目的港和交付地点。",
            "destination_incoterm_place": "请确认目的港和指定贸易术语地点。",
            "delivery_place_incoterm": "请确认指定交货地点和贸易术语。",
            "delivery_timing": "请确认交付时间是指备妥、发运还是到达。",
            "commercial_terms": "请确认价格依据、库存、包装、付款和币种要求。",
            "shipping_terms": "请确认贸易术语、交期和运费依据。",
        }
        questions = tuple(templates[intent] for intent in recipe.follow_up_intents)
    else:
        questions = tuple(item.question for item in follow_ups)
    if recipe.style.question_format == "numbered":
        question_text = "\n".join(
            f"{index}. {question}"
            for index, question in enumerate(questions, start=1)
        )
    elif recipe.style.question_format == "bullets":
        question_text = "\n".join(f"- {question}" for question in questions)
    else:
        question_text = " ".join(questions)
    if recipe.language == "zh-CN":
        opening = {
            "standard": "感谢您的询盘。为继续进行技术审阅，请确认以下信息：",
            "direct": "为继续进行技术审阅，请确认以下信息：",
        }[recipe.style.opening]
        close = {
            "neutral": "感谢您的协助。",
            "concise": "谢谢。",
            "formal": "感谢您确认以上信息。",
        }[recipe.style.tone]
        return GeneratedDraft(
            subject="需要补充询盘信息",
            body=(
                f"尊敬的客户：\n\n{opening}\n\n{question_text}\n\n"
                f"{close}\n\n此致\n敬礼\n[姓名]"
            ),
            follow_up_ids=recipe.follow_up_ids,
            recipe=recipe,
        )
    opening = {
        "standard": "Thank you for your inquiry. Please confirm the following:",
        "direct": "To continue our review, please confirm the following:",
    }[recipe.style.opening]
    close = {
        "neutral": "Thank you for your assistance.",
        "concise": "Thank you.",
        "formal": "We appreciate your confirmation of these points.",
    }[recipe.style.tone]
    return GeneratedDraft(
        subject="Additional information required",
        body=(
            f"Dear [Customer name],\n\n{opening}\n\n{question_text}\n\n"
            f"{close}\n\nBest regards,\n[Name]"
        ),
        follow_up_ids=recipe.follow_up_ids,
        recipe=recipe,
    )


def _proceed_draft(
    analysis: InquiryAnalysis,
    card: TechnicalReviewCard,
    recipe: DraftGenerationRecipe,
) -> GeneratedDraft:
    selected = recipe.selected_candidate
    assert selected is not None
    if recipe.kind != expected_draft_kind(analysis, selected):
        raise ValueError("Draft recipe kind does not match the immutable analysis")
    if recipe.kind == "supported":
        evidence_gated = build_email_draft(analysis)
        if recipe.language == "en":
            body = evidence_gated.body
            if recipe.style.opening == "direct":
                body = body.replace(
                    f"Thank you for your inquiry regarding {selected}. Based on the ",
                    f"Regarding {selected}, based on the ",
                    1,
                )
            if recipe.style.tone == "concise":
                body = body.replace("Best regards,", "Regards,", 1)
            elif recipe.style.tone == "formal":
                body = body.replace("Best regards,", "Kind regards,", 1)
            return GeneratedDraft(evidence_gated.subject, body, None, recipe)
        product = analysis.recommended_product
        opening = (
            f"感谢您就 {product} 提交询盘。"
            if recipe.style.opening == "standard"
            else f"关于 {product} 的询盘："
        )
        close = {
            "neutral": "",
            "concise": "\n\n谢谢。",
            "formal": "\n\n感谢您确认上述信息。",
        }[recipe.style.tone]
        return GeneratedDraft(
            subject=f"技术跟进 — {product}",
            body=(
                "尊敬的[客户姓名]：\n\n"
                f"{opening}根据目前已批准的技术资料，"
                "可在文件载明的范围内就该产品提供技术回复。\n\n"
                "为准备准确的商务回复，请确认所需数量、交货时间、目的港、"
                "贸易术语、包装要求、最终用途及目标国家认证要求。\n\n"
                "库存、起订量、价格、运费、交期和法规适用性仍需另行确认。"
                f"{close}\n\n此致\n敬礼\n[姓名]"
            ),
            follow_up_ids=None,
            recipe=recipe,
        )
    candidate = next(
        (
            item
            for item in card.internal_candidates
            if item.product == selected and item.evidence
        ),
        None,
    )
    if candidate is None:
        raise ValueError("Reviewer draft recipe has no evidence-backed candidate")
    limitations = tuple(
        dict.fromkeys(
            limitation
            for evidence in candidate.evidence
            for limitation in evidence.limitations
        )
    )
    if recipe.language == "zh-CN":
        opening = (
            "技术审阅人员已选择"
            if recipe.style.opening == "standard"
            else "关于您的询盘，技术审阅人员已选择"
        )
        limitation_text = (
            "\n\n审阅中必须保留的文件限制：" + "；".join(limitations)
            if limitations
            else ""
        )
        close = {
            "neutral": "",
            "concise": "\n\n谢谢。",
            "formal": "\n\n感谢您确认上述信息。",
        }[recipe.style.tone]
        body = (
            "尊敬的[客户姓名]：\n\n"
            f"{opening} {candidate.product} 供客户进一步评估。该选择"
            "基于目前已批准的文件证据。请确认最终应用条件，并在商业采用前"
            "验证其对预期用途的适用性。"
            f"{limitation_text}{close}\n\n此致\n敬礼\n[姓名]"
        )
        subject = f"技术跟进 — {candidate.product}"
    else:
        opening_text = (
            "Regarding your inquiry, " if recipe.style.opening == "direct" else ""
        )
        limitation_text = (
            "\n\nDocument limitations to retain in the review: "
            + "; ".join(limitations)
            if limitations
            else ""
        )
        body = (
            "Dear [Customer name],\n\n"
            f"{opening_text}{candidate.product} was selected by the technical reviewer for further "
            "customer evaluation based on the currently approved document evidence. "
            "Please confirm the final application conditions and validate the product "
            "in the intended use before commercial adoption."
            f"{limitation_text}\n\n"
            + {
                "neutral": "Best regards,",
                "concise": "Regards,",
                "formal": "Kind regards,",
            }[recipe.style.tone]
            + "\n[Name]"
        )
        subject = f"Technical follow-up — {candidate.product}"
    return GeneratedDraft(subject, body, None, recipe)


def render_generated_draft(
    analysis: InquiryAnalysis,
    card: TechnicalReviewCard,
    recipe: DraftGenerationRecipe,
) -> GeneratedDraft:
    if recipe.kind == "follow_up":
        return _follow_up_draft(card, recipe)
    return _proceed_draft(analysis, card, recipe)
