# Evidence Review Journey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有单页 Streamlit 技术审阅工作台改成一套留白充足、实时联动、可打印和可恢复的八步证据审阅流程，并保持现有证据门禁、双语能力和桌面启动方式不变。

**Architecture:** 新增一个纯 Pydantic 的 `ReviewWorkspace` 作为唯一审阅状态，包含固定的分析基线和可变的审阅状态；八个页面、邮件、打印、记录和备份全部从它派生。Streamlit 文件只负责加载/保存该状态与渲染页面，证据判断仍由现有 `InquiryAnalysis`、`TechnicalReviewCard` 和 `ReviewSessionState` 完成。

**Tech Stack:** Python 3.11–3.13、Streamlit 1.60、Pydantic 2.13、PyMuPDF、pytest 9、Streamlit AppTest、真实 Edge/Chrome、浏览器打印 CSS。

---

## 执行约束

- 工作树：`F:\外贸化工\.worktrees\technical-review-o1`；分支：`codex/technical-review-o1`。
- 保留当前所有未提交 O1–O4 改动，不重置、不覆盖、不整理无关差异。
- 未经用户另行明确授权，不提交、不推送、不创建 PR、不部署；因此本计划不包含 Git commit 步骤。
- 每个行为变更先写失败测试，确认因目标行为失败，再做最小实现。
- 使用受控索引 `F:\外贸化工\.chroma`，不得复制、重建或切换正式索引。
- UI 长期规范见 `docs/UI_STYLE_GUIDE.md`；原型服务器不是生产实现。
- 当前阶段不允许自由编辑已核验参数或分析生成的缺口项，也不增加资料库管理 UI。

## 文件职责

| 文件 | 职责 |
|---|---|
| `src/chemical_trade_copilot/review_workspace.py` | 唯一审阅状态、页面状态、缺口关闭、决定联动、邮件版本、完成快照和备份校验 |
| `src/chemical_trade_copilot/review_email.py` | 从当前授权状态生成邮件，并在“优化建议”后校验和创建新版本 |
| `src/chemical_trade_copilot/streamlit_app.py` | 八步导航、页面编排、对话框、备份上传下载和状态读写 |
| `src/chemical_trade_copilot/ui_components.py` | 实验室审阅单样式、步骤导航、删除线、A4 打印样式和可信静态 HTML |
| `src/chemical_trade_copilot/localization.py` | 新页面与普通用户文案的中英文资源键 |
| `src/chemical_trade_copilot/materials.py` | 从受控目录生成可比较的启用资料清单，不写入资料或索引 |
| `tests/test_review_workspace.py` | 状态机、联动、版本、完成和备份纯逻辑测试 |
| `tests/review_factories.py` | 跨工作状态、邮件和 Streamlit 测试复用的确定性 EPON 8280 工厂数据 |
| `tests/test_review_email.py` | 邮件授权、优化建议和技术令牌保护测试 |
| `tests/test_streamlit_app.py` | 八页真实 AppTest 交互与中英文行为 |
| `tests/test_ui_components.py` | 视觉令牌、步骤布局、删除线和打印 CSS 契约 |

## 阶段一：状态与流程骨架（Task 1–3）

本阶段只建立唯一审阅状态、受控询盘入口和八步页面骨架。完成 Task 3 后必须停止，不得自动进入证据页和专家决定实现。

### Task 1: 建立唯一审阅状态

**Files:**
- Create: `src/chemical_trade_copilot/review_workspace.py`
- Create: `tests/test_review_workspace.py`
- Create: `tests/review_factories.py`
- Modify: `src/chemical_trade_copilot/streamlit_app.py`

- [ ] **Step 1: 写出分析基线和实时状态不混淆的失败测试**

```python
def test_workspace_keeps_analysis_fixed_while_review_state_changes() -> None:
    workspace = sample_workspace()
    changed = set_resolved_follow_up(workspace, "followup-1", True)

    assert changed.analysis == workspace.analysis
    assert changed.session.card == workspace.session.card
    assert changed.resolved_follow_up_ids == ("followup-1",)
    assert workspace.resolved_follow_up_ids == ()


def test_workspace_rejects_unknown_follow_up_id() -> None:
    with pytest.raises(ValueError, match="Unknown follow-up item"):
        set_resolved_follow_up(sample_workspace(), "missing", True)
```

在 `tests/review_factories.py` 建立唯一测试工厂，后续任务不得复制另一套 EPON 示例：

```python
from pathlib import Path
from typing import Literal

from chemical_trade_copilot.inquiry_analysis import (
    InquiryAnalysis,
    KeyParameter,
    RequirementAssessment,
    SourceCitation,
)
from chemical_trade_copilot.inquiry_review import (
    apply_session_decision,
    build_review_card,
    start_review_session,
)
from chemical_trade_copilot.retrieval import SearchResult
from chemical_trade_copilot.review_workspace import EmailDraftVersion, ReviewWorkspace


def sample_analysis() -> InquiryAnalysis:
    citation = SourceCitation(
        product="EPON Resin 8280",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        page_number=3,
    )
    return InquiryAnalysis(
        summary_zh="一项参数已有资料，工况仍需确认。",
        recommendation_status="supported",
        recommended_product="EPON Resin 8280",
        recommendation_reasons=("指定固化体系存在已核验数据。",),
        requirements=(RequirementAssessment(
            category="technical",
            requirement="120°C service",
            status="needs_confirmation",
            evidence=(citation,),
        ),),
        key_parameters=(KeyParameter(
            name="Heat Deflection Temperature",
            value="156",
            unit="°C",
            conditions="MPDA-cured system",
            test_method="ASTM D648",
            curing_agent="MPDA",
            mix_ratio="100 pbw : 14.4 pbw",
            cure_schedule="2 h/80°C + 2 h/150°C",
            citation=citation,
        ),),
        evidence_gaps=("Continuous-use temperature is not established.",),
        source_limitations=("HDT is not a continuous-use temperature.",),
        follow_up_questions=(
            "Is 120°C continuous, intermittent, or a short peak?",
            "What chemical media and exposure duration apply?",
            "Which target-market documents are required?",
            "Does three weeks mean ready, shipped, or delivered?",
        ),
        next_action="needs_technical_confirmation",
    )


def sample_workspace() -> ReviewWorkspace:
    analysis = sample_analysis()
    ranked = SearchResult(
        text="MPDA ASTM D648 156°C",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        source_path=Path("G:/materials/EPON/TDS.pdf"),
        page_number=3,
        distance=0.1,
        date_revision="2016",
        jurisdiction="Technical data sheet · jurisdiction not stated",
    )
    inquiry = "EPON Resin 8280 for service at 120°C in the EU"
    card = build_review_card(inquiry, analysis, [ranked])
    session = start_review_session(card, analysis_revision="review-1")
    return ReviewWorkspace(
        inquiry=inquiry,
        target_market="EU",
        catalog_fingerprint="a" * 64,
        analysis=analysis,
        session=session,
    )


def workspace_with_decision(
    workspace: ReviewWorkspace, decision: str
) -> ReviewWorkspace:
    if decision == "pending":
        return workspace
    if decision == "needs_information":
        session = apply_session_decision(
            workspace.session,
            "needs_information",
            selected_follow_up_ids=tuple(
                item.item_id for item in workspace.session.card.follow_ups
            ),
        )
    elif decision == "proceed":
        session = apply_session_decision(
            workspace.session,
            "proceed",
            selected_candidate="EPON Resin 8280",
        )
    elif decision == "do_not_recommend":
        session = apply_session_decision(workspace.session, "do_not_recommend")
    else:
        raise ValueError(f"Unknown decision: {decision}")
    return workspace.model_copy(update={"session": session})


def workspace_with_follow_up_draft(
    workspace: ReviewWorkspace | None = None,
    *,
    version: int = 1,
    language: Literal["en", "zh-CN"] = "en",
) -> ReviewWorkspace:
    workspace = workspace_with_decision(
        workspace or sample_workspace(), "needs_information"
    )
    draft = EmailDraftVersion(
        version=version,
        language=language,
        subject="Additional information required",
        body="Dear Customer,\n\nPlease confirm the open items.\n\nBest regards,",
        authorized_decision="needs_information",
    )
    return workspace.model_copy(
        update={"draft_versions": (draft,), "active_draft_version": version}
    )
```

- [ ] **Step 2: 运行测试并确认模块不存在或行为缺失**

Run:

```powershell
$env:PYTHONPATH='src'
F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_workspace.py -q
```

Expected: FAIL，错误指向 `chemical_trade_copilot.review_workspace` 尚不存在。

- [ ] **Step 3: 实现不可变的规范状态和缺口状态转换**

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .inquiry_analysis import InquiryAnalysis
from .inquiry_review import ReviewSessionState

ReviewPage = Literal[
    "inquiry", "conclusion", "gaps", "evidence",
    "decision", "email", "print", "record",
]
EmailLanguage = Literal["en", "zh-CN"]


class EmailDraftVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: int
    language: EmailLanguage
    subject: str
    body: str
    manually_edited: bool = False
    authorized_decision: Literal["proceed", "needs_information"]


class ReviewWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    inquiry: str
    target_market: str
    catalog_fingerprint: str
    analysis: InquiryAnalysis
    session: ReviewSessionState
    current_page: ReviewPage = "conclusion"
    resolved_follow_up_ids: tuple[str, ...] = ()
    email_language: EmailLanguage = "en"
    draft_versions: tuple[EmailDraftVersion, ...] = ()
    active_draft_version: int | None = None
    completed_at: str | None = None


def set_resolved_follow_up(
    workspace: ReviewWorkspace, item_id: str, resolved: bool
) -> ReviewWorkspace:
    known = {item.item_id for item in workspace.session.card.follow_ups}
    if item_id not in known:
        raise ValueError(f"Unknown follow-up item: {item_id}")
    selected = set(workspace.resolved_follow_up_ids)
    selected.discard(item_id)
    if resolved:
        selected.add(item_id)
    ordered = tuple(item.item_id for item in workspace.session.card.follow_ups if item.item_id in selected)
    return workspace.model_copy(update={"resolved_follow_up_ids": ordered})
```

- [ ] **Step 4: 把 `analysis_json`、`review_session_json` 和草稿散键迁移到单个 `review_workspace_json`，旧键只读一次后清除**

```python
def _save_workspace(workspace: ReviewWorkspace) -> None:
    st.session_state["review_workspace_json"] = workspace.model_dump_json()


def _load_workspace() -> ReviewWorkspace | None:
    payload = st.session_state.get("review_workspace_json")
    return ReviewWorkspace.model_validate_json(payload) if payload else None
```

- [ ] **Step 5: 运行纯逻辑测试和现有审阅测试**

Run:

```powershell
$env:PYTHONPATH='src'
F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_workspace.py tests/test_inquiry_review.py -q
```

Expected: PASS；现有专家决定和证据门禁行为不变。

### Task 2: 受控目标市场与询盘入口

**Files:**
- Modify: `src/chemical_trade_copilot/review_workspace.py`
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `src/chemical_trade_copilot/localization.py`
- Modify: `tests/test_streamlit_app.py`

- [ ] **Step 1: 写出目标市场不能自由输入、备份入口位于询盘页的失败测试**

```python
def test_inquiry_page_uses_controlled_target_market_and_backup_entry() -> None:
    app = AppTest.from_file(str(APP)).run(timeout=30)

    market = next(box for box in app.selectbox if box.label == "Target market")
    assert market.options == ["unknown", "EU", "US", "GB", "CN", "CA", "AU", "JP", "KR", "other"]
    assert any(button.label == "Open review backup" for button in app.button)
    assert all(item.label != "Target market" for item in app.text_input)
```

- [ ] **Step 2: 运行单测并确认当前自由文本或缺少入口导致失败**

Run:

```powershell
$env:PYTHONPATH='src'
$env:CHEMICAL_TRADE_DATABASE='F:\外贸化工\.chroma'
F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_streamlit_app.py::test_inquiry_page_uses_controlled_target_market_and_backup_entry -q
```

Expected: FAIL，缺少 `Target market` 受控选择或 `Open review backup`。

- [ ] **Step 3: 定义稳定市场代码并渲染选择框**

```python
TARGET_MARKETS = (
    "unknown", "EU", "US", "GB", "CN", "CA", "AU", "JP", "KR", "other"
)

target_market = st.selectbox(
    text("entry.target_market", locale),
    options=TARGET_MARKETS,
    format_func=lambda code: text(f"market.{code}", locale),
    key="target_market",
)
```

- [ ] **Step 4: 分析哈希加入目标市场，改变询盘或市场必然创建新修订并撤销旧授权**

```python
def _analysis_revision(inquiry: str, target_market: str, fingerprint: str) -> str:
    payload = f"{fingerprint}\0{target_market}\0{inquiry}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 5: 运行入口、重新分析撤权和双语测试**

Run:

```powershell
$env:PYTHONPATH='src'
$env:CHEMICAL_TRADE_DATABASE='F:\外贸化工\.chroma'
F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_streamlit_app.py -q
```

Expected: PASS；目标市场使用稳定代码，界面显示本地化名称。

### Task 3: 八步可点击导航与逐页渲染

**Files:**
- Modify: `src/chemical_trade_copilot/review_workspace.py`
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `src/chemical_trade_copilot/ui_components.py`
- Modify: `tests/test_streamlit_app.py`
- Modify: `tests/test_ui_components.py`

- [ ] **Step 1: 写出八个步骤均可点击且切页不丢状态的失败测试**

```python
def test_all_review_steps_are_clickable_and_preserve_workspace() -> None:
    app = _review_app("needs_information")
    before = app.session_state["review_workspace_json"]

    next(button for button in app.button if button.label == "04 Evidence").click()
    app.run(timeout=30)

    assert any(title.value == "Review evidence" for title in app.title)
    restored = ReviewWorkspace.model_validate_json(app.session_state["review_workspace_json"])
    original = ReviewWorkspace.model_validate_json(before)
    assert restored.analysis == original.analysis
    assert restored.session.outcome == original.session.outcome
```

在 `tests/test_streamlit_app.py` 统一读取新状态，并扩展现有 `_review_app` 工厂；后续 AppTest 示例均使用这两个函数：

```python
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
    workspace = sample_workspace().model_copy(update={"current_page": page})
    workspace = workspace_with_decision(workspace, decision)
    if email_version is not None:
        workspace = workspace_with_follow_up_draft(workspace, version=email_version)
        workspace = workspace.model_copy(update={"current_page": page})
    app.session_state["review_workspace_json"] = workspace.model_dump_json()
    return app.run(timeout=30)
```

- [ ] **Step 2: 运行测试并确认当前单页结构失败**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_streamlit_app.py::test_all_review_steps_are_clickable_and_preserve_workspace -q`

Expected: FAIL，找不到八步按钮或证据页标题。

- [ ] **Step 3: 实现页面状态转换和导航渲染**

```python
REVIEW_PAGES: tuple[ReviewPage, ...] = (
    "inquiry", "conclusion", "gaps", "evidence",
    "decision", "email", "print", "record",
)


def set_current_page(workspace: ReviewWorkspace, page: ReviewPage) -> ReviewWorkspace:
    if page not in REVIEW_PAGES:
        raise ValueError(f"Unknown review page: {page}")
    return workspace.model_copy(update={"current_page": page})


def _render_step_navigation(workspace: ReviewWorkspace, locale: Locale) -> None:
    columns = st.columns(8)
    for index, page in enumerate(REVIEW_PAGES, start=1):
        with columns[index - 1]:
            if st.button(
                f"{index:02d} {text(f'page.{page}', locale)}",
                key=f"nav_{page}",
                type="primary" if page == workspace.current_page else "secondary",
                use_container_width=True,
            ):
                _save_workspace(set_current_page(workspace, page))
                st.rerun()
```

- [ ] **Step 4: 添加步骤条 CSS 与窄屏行为**

```css
.ctc-steps [data-testid="stButton"] button {
  border-radius: 0;
  border-width: 3px 0 0;
  min-height: 56px;
}
@media (max-width: 820px) {
  .ctc-steps { overflow-x: auto; }
  .ctc-steps [data-testid="column"] { min-width: 112px; }
}
```

- [ ] **Step 5: 运行 AppTest 和 CSS 契约测试**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_streamlit_app.py tests/test_ui_components.py -q`

Expected: PASS；八页可往返且工作状态不丢失。

### 阶段一停止门

完成 Task 1–3 后，先运行该阶段全部专项测试和相关现有测试，再执行范围与复杂度自查：

- 差异是否只服务于唯一状态、受控市场和八步导航验收；
- 是否仍存在或新建第二状态源、第二套导航或重复页面流程；
- 是否新增未被当前失败案例证明必要的依赖、抽象、通用接口或未来平台能力；
- 是否误入证据查看、专家决定、邮件、打印、备份或完成快照的后续阶段实现；
- 是否保持已核验参数、分析生成缺口和受控资料只读边界。

发现拓宽或复杂化时，在本阶段内删除、收窄或退回计划；更新 `CURRENT_WORK.md` 的证据与唯一下一动作，然后停止等待用户继续指令。

## 阶段二：证据审阅与专家决定（Task 4–6）

本阶段把结论、缺口、真实 PDF 和三个专家出口接到阶段一的唯一状态，不创建第二事实源。

### Task 4: 结论与缺口实时联动

**Files:**
- Modify: `src/chemical_trade_copilot/review_workspace.py`
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `src/chemical_trade_copilot/ui_components.py`
- Modify: `tests/test_review_workspace.py`
- Modify: `tests/test_streamlit_app.py`

- [ ] **Step 1: 写出勾选关闭、删除线和追问排除的失败测试**

```python
def test_resolved_gap_is_excluded_from_open_questions() -> None:
    workspace = sample_workspace()
    item_id = workspace.session.card.follow_ups[0].item_id

    changed = set_resolved_follow_up(workspace, item_id, True)

    assert item_id not in {item.item_id for item in open_follow_ups(changed)}
    assert item_id in changed.resolved_follow_up_ids


def test_gap_checkbox_updates_record_without_reanalysis() -> None:
    app = _review_app("needs_information")
    revision = _workspace(app).session.analysis_revision
    next(box for box in app.checkbox if "120°C" in box.label).check()
    app.run(timeout=30)

    assert _workspace(app).session.analysis_revision == revision
    visible = " ".join(
        item.value for collection in (app.markdown, app.caption, app.text)
        for item in collection
    )
    assert "3 open gaps" in visible
```

- [ ] **Step 2: 运行测试并确认当前状态没有统一联动**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_workspace.py tests/test_streamlit_app.py -k "resolved_gap or gap_checkbox" -q`

Expected: FAIL，缺少 `open_follow_ups` 或记录未更新。

- [ ] **Step 3: 实现开放缺口派生函数并在结论、缺口、邮件和记录复用**

```python
def open_follow_ups(workspace: ReviewWorkspace) -> tuple[ReviewFollowUp, ...]:
    resolved = set(workspace.resolved_follow_up_ids)
    return tuple(item for item in workspace.session.card.follow_ups if item.item_id not in resolved)
```

- [ ] **Step 4: 为已关闭缺口添加删除线；不增加编辑、添加或删除按钮**

```css
[data-testid="stCheckbox"] label:has(input:checked) p {
  color: var(--ctc-muted);
  text-decoration: line-through;
  text-decoration-thickness: 1.5px;
}
```

- [ ] **Step 5: 运行状态、界面和黄金案例测试**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_workspace.py tests/test_streamlit_app.py tests/test_review_golden_cases.py -q`

Expected: PASS；勾选只改变实时审阅状态，不改变证据基线。

### Task 5: 真实原始 PDF 证据查看

**Files:**
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `src/chemical_trade_copilot/pdf_pages.py`
- Modify: `tests/test_pdf_pages.py`
- Modify: `tests/test_streamlit_app.py`

- [ ] **Step 1: 写出证据链接必须绑定真实文件和物理页的失败测试**

```python
def test_evidence_page_exposes_real_pdf_and_physical_page() -> None:
    app = _review_app("needs_information", page="evidence")

    assert any(
        button.label == "Open original PDF page 3" for button in app.button
    )
    assert "physical page 3 of 5" in app.markdown[0].value
```

- [ ] **Step 2: 运行测试并确认当前证据只显示缩略图或缺少可打开链接**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_pdf_pages.py tests/test_streamlit_app.py -k evidence_page -q`

Expected: FAIL，缺少真实链接或物理页绑定。

- [ ] **Step 3: 使用现有受控资料根目录解析文件，不接受用户提供的任意路径**

```python
def approved_pdf_path(
    product: str, source_file: str, materials_root: Path, catalog_path: Path
) -> Path:
    catalog = load_material_catalog(catalog_path)
    matches = [
        entry for entry in catalog
        if entry.enabled
        and entry.product == product
        and entry.relative_path.name == source_file
    ]
    if len(matches) != 1:
        raise ValueError(f"Approved PDF is not uniquely identified: {source_file}")
    path = (materials_root / matches[0].relative_path).resolve()
    path.relative_to(materials_root.resolve())
    return path
```

- [ ] **Step 4: 复用现有可信静态物理页查看器，并在同一对话框用 `st.pdf` 提供完整原文件查看**

对话框首先显示引用的真实物理页渲染和页码，再显示完整 PDF 查看器。禁止把询盘、模型输出或 PDF 文本插入可执行 JavaScript；文件路径只来自已启用目录项，不启动第二个文件服务器。

- [ ] **Step 5: 运行 PDF、目录完整性和真实浏览器打开测试**

Run:

```powershell
$env:PYTHONPATH='src'
$env:CHEMICAL_TRADE_DATABASE='F:\外贸化工\.chroma'
F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_pdf_pages.py tests/test_streamlit_app.py -q
```

Expected: PASS；真实 Edge 与 Chrome 点击后打开同一 PDF 的正确物理页。

### Task 6: 三个专家决定和权限联动

**Files:**
- Modify: `src/chemical_trade_copilot/review_workspace.py`
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `tests/test_review_workspace.py`
- Modify: `tests/test_streamlit_app.py`

- [ ] **Step 1: 写出三条业务出口和布局契约的失败测试**

```python
def test_decision_page_has_three_real_business_exits() -> None:
    app = _review_app(page="decision")
    labels = {button.label for button in app.button}

    assert "Ask customer for information" in labels
    assert "Save record without replying" in labels
    assert "Authorize technical reply" in labels
    assert "Reanalyze" not in labels
```

- [ ] **Step 2: 运行测试并确认旧四选项或布局失败**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_streamlit_app.py::test_decision_page_has_three_real_business_exits -q`

Expected: FAIL。

- [ ] **Step 3: 复用现有决定代码并定义用户出口映射**

```python
DECISION_BY_EXIT = {
    "ask_customer": "needs_information",
    "save_only": "do_not_recommend",
    "technical_reply": "proceed",
}
```

“向客户追问信息”独占第一行；其余两个按钮第二行等宽。任何决定变化都调用 `apply_session_decision`，清除不再授权的活动草稿，并立即保存工作状态。

- [ ] **Step 4: 对无开放缺口的追问出口和无证据候选的技术回复出口实施门禁**

```python
if exit_name == "ask_customer" and not open_follow_ups(workspace):
    raise ValueError("No open customer questions remain")
if exit_name == "technical_reply" and not workspace.session.card.internal_candidates:
    raise ValueError("No evidence-backed technical reply is available")
```

- [ ] **Step 5: 运行现有专家决定负例和新界面测试**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_inquiry_review.py tests/test_review_workspace.py tests/test_streamlit_app.py -k "decision or recommend or draft" -q`

Expected: PASS；禁止项不能生成邮件。

### 阶段二停止门

完成 Task 4–6 后，先验证缺口联动、真实物理页和三个决定的正负路径，再执行范围与复杂度自查：

- 是否只有已批准的三种专家出口，且没有替专家代签或推荐；
- 是否有任何产品名、数值、单位、条件、页码、证据 ID 或决定代码被静默改写；
- 是否把“检索未命中”误作“原始资料不存在”，或让模型绕过证据门禁；
- PDF 查看是否限定受控路径，且没有引入文件服务、数据库或资料库管理 UI；
- 本阶段新增的每层代码是否都能由固定失败案例解释。

发现拓宽或复杂化时先收窄；更新 `CURRENT_WORK.md` 后停止等待用户继续指令。

## 阶段三：客户输出、打印与留档（Task 7–10）

本阶段实现受当前专家授权约束的邮件版本、A4 打印、用户备份和完成快照，不连接邮箱或外部存储。

### Task 7: 邮件语言、人工编辑与优化版本

**Files:**
- Create: `src/chemical_trade_copilot/review_email.py`
- Create: `tests/test_review_email.py`
- Modify: `src/chemical_trade_copilot/review_workspace.py`
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `tests/test_streamlit_app.py`

- [ ] **Step 1: 写出优化必须新建版本、保留旧版且不能新增技术主张的失败测试**

```python
def test_optimization_creates_new_version_and_keeps_original() -> None:
    workspace = workspace_with_follow_up_draft()
    optimized = add_optimized_draft(
        workspace,
        subject="Additional information required",
        body="Dear Customer,\n\nPlease confirm the four open items.\n\nBest regards,",
    )

    assert [item.version for item in optimized.draft_versions] == [1, 2]
    assert optimized.active_draft_version == 2
    assert optimized.draft_versions[0].body == workspace.draft_versions[0].body


def test_optimization_client_can_only_choose_finite_style_options() -> None:
    class FakeJsonClient:
        def __init__(self, payload: str) -> None:
            self.payload = payload

        def complete_json(self, system_prompt: str, user_prompt: str) -> str:
            assert "DraftStyle" in system_prompt
            assert user_prompt
            return self.payload

    client = FakeJsonClient(
        '{"tone":"concise","opening":"direct","question_format":"numbered"}'
    )
    optimized = optimize_authorized_draft(
        client, workspace_with_follow_up_draft(), "Make it concise and number the questions"
    )

    assert optimized.active_draft_version == 2
    assert "156°C" not in active_draft(optimized).body
    assert "1." in active_draft(optimized).body
```

- [ ] **Step 2: 运行测试并确认邮件版本模块不存在**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_email.py -q`

Expected: FAIL，模块或函数不存在。

- [ ] **Step 3: 让模型只返回有限样式选项，再用确定性模板重排已授权内容**

```python
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .ui_presenter import build_email_draft


class EmailOptimizationClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> str: ...


class DraftStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: Literal["neutral", "concise", "formal"]
    opening: Literal["standard", "direct"]
    question_format: Literal["bullets", "numbered", "paragraph"]


def active_draft(workspace: ReviewWorkspace) -> EmailDraftVersion | None:
    return next(
        (
            item for item in workspace.draft_versions
            if item.version == workspace.active_draft_version
        ),
        None,
    )


def build_authorized_draft(
    workspace: ReviewWorkspace, *, style: DraftStyle
) -> tuple[str, str]:
    decision = workspace.session.outcome.decision
    if decision == "proceed":
        draft = build_email_draft(workspace.analysis)
        return draft.subject, draft.body
    if decision != "needs_information":
        raise ValueError("The current expert decision does not authorize an email")
    questions = tuple(item.question for item in open_follow_ups(workspace))
    if not questions:
        raise ValueError("No open customer questions remain")
    if style.question_format == "numbered":
        question_text = "\n".join(
            f"{index}. {question}" for index, question in enumerate(questions, start=1)
        )
    elif style.question_format == "bullets":
        question_text = "\n".join(f"- {question}" for question in questions)
    else:
        question_text = " ".join(questions)
    opening = {
        "standard": "Thank you for your inquiry.",
        "direct": "To continue our review, please confirm the following:",
    }[style.opening]
    tone_close = {
        "neutral": "Thank you for your assistance.",
        "concise": "Thank you.",
        "formal": "We appreciate your confirmation of these points.",
    }[style.tone]
    body = (
        f"Dear [Customer name],\n\n{opening}\n\n{question_text}\n\n"
        f"{tone_close}\n\nBest regards,\n[Name]"
    )
    return "Additional information required", body


def optimize_authorized_draft(
    client: EmailOptimizationClient,
    workspace: ReviewWorkspace,
    instruction: str,
) -> ReviewWorkspace:
    if not instruction.strip():
        raise ValueError("Optimization instruction must not be empty")
    raw = client.complete_json(
        "Classify the requested email style. Return only the DraftStyle JSON fields.",
        instruction,
    )
    style = DraftStyle.model_validate_json(raw)
    subject, body = build_authorized_draft(workspace, style=style)
    return add_optimized_draft(workspace, subject=subject, body=body)


def add_optimized_draft(
    workspace: ReviewWorkspace, *, subject: str, body: str
) -> ReviewWorkspace:
    active = active_draft(workspace)
    next_version = max(item.version for item in workspace.draft_versions) + 1
    draft = active.model_copy(
        update={"version": next_version, "subject": subject, "body": body, "manually_edited": False}
    )
    return workspace.model_copy(
        update={
            "draft_versions": (*workspace.draft_versions, draft),
            "active_draft_version": next_version,
        }
    )
```

`build_authorized_draft` 只能读取 `open_follow_ups(workspace)`、已授权决定和现有确定性称呼/落款；样式模型永远看不到添加事实的输出字段。技术回复继续复用现有证据门禁模板，不因优化建议增加产品、参数、合规或商业主张。

- [ ] **Step 4: 使用 `@st.dialog` 实现“优化建议”，邮件正文手工改变只标记当前版本为已编辑**

```python
@st.dialog("How should this email be improved?")
def _email_optimization_dialog(workspace: ReviewWorkspace, locale: Locale) -> None:
    instruction = st.text_area(text("draft.optimization_instruction", locale))
    if st.button(text("draft.generate_new_version", locale), type="primary"):
        optimized = optimize_authorized_draft(_email_client(), workspace, instruction)
        _save_workspace(optimized)
        st.rerun()
```

- [ ] **Step 5: 运行邮件、翻译保护和 UI 测试**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_email.py tests/test_localization.py tests/test_streamlit_app.py -k "email or draft or translation" -q`

Expected: PASS；默认英文，切换语言不改变决定，新版本保留旧版，禁止新增技术主张。

### Task 8: 打印预览与 A4 输出

**Files:**
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `src/chemical_trade_copilot/ui_components.py`
- Modify: `tests/test_ui_components.py`
- Modify: `tests/test_streamlit_app.py`

- [ ] **Step 1: 写出打印 CSS 和实时内容的失败测试**

```python
def test_print_css_hides_web_controls_and_uses_a4_pages() -> None:
    assert "@media print" in APP_CSS
    assert "size: A4" in APP_CSS
    assert ".ctc-no-print" in APP_CSS
    assert "font-size: 12pt" in APP_CSS


def test_print_preview_uses_current_decision_and_email_version() -> None:
    app = _review_app("needs_information", page="print", email_version=2)
    text = " ".join(item.value for item in app.markdown)
    assert "Ask customer for information" in text
    assert "Email version 2 · English" in text
```

- [ ] **Step 2: 运行测试并确认打印目前不存在**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_ui_components.py tests/test_streamlit_app.py -k print -q`

Expected: FAIL。

- [ ] **Step 3: 实现两张 A4 纸面和浏览器打印按钮**

```css
@page { size: A4; margin: 0; }
@media print {
  .ctc-no-print, [data-testid="stToolbar"], header, footer { display: none !important; }
  .ctc-print-sheet {
    width: 210mm; min-height: 297mm; padding: 16mm 17mm;
    break-after: page; background: white; font-size: 12pt;
  }
  .ctc-print-sheet:last-child { break-after: auto; }
}
```

打印按钮使用固定可信脚本 `window.print()`；用户数据只作为转义文本渲染。

- [ ] **Step 4: 打印第一页实时派生结论、证据、开放/关闭缺口和决定；第二页实时派生活动邮件版本**

未授权邮件时只打印内部审阅页，不生成空白客户邮件页。

- [ ] **Step 5: 真实浏览器打印为 PDF 并渲染检查两页**

Expected: A4 两页，无导航、按钮、截断、重叠或小于 12pt 的正文；真实资料引用可读。

### Task 9: 审阅备份的保存与恢复

**Files:**
- Modify: `src/chemical_trade_copilot/materials.py`
- Modify: `src/chemical_trade_copilot/review_workspace.py`
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `tests/test_review_workspace.py`
- Modify: `tests/test_streamlit_app.py`

- [ ] **Step 1: 写出备份不能修改资料、相同资料直接恢复、不同资料只恢复询盘输入的失败测试**

```python
def test_backup_restores_workspace_when_catalog_matches() -> None:
    workspace = sample_workspace()
    catalog = (CatalogDocumentRef(relative_path="EPON/TDS.pdf", sha256="a" * 64),)
    payload = export_review_backup(workspace, catalog)
    result = import_review_backup(payload, catalog)

    assert result.workspace == workspace
    assert result.requires_reanalysis is False


def test_backup_with_changed_document_requires_reanalysis() -> None:
    original = (CatalogDocumentRef(relative_path="EPON/TDS.pdf", sha256="a" * 64),)
    payload = export_review_backup(sample_workspace(), original)
    changed = (CatalogDocumentRef(relative_path="EPON/TDS.pdf", sha256="f" * 64),)
    result = import_review_backup(payload, changed)

    assert result.workspace is None
    assert result.requires_reanalysis is True
    assert result.inquiry == sample_workspace().inquiry
    assert result.changed_files == ("EPON/TDS.pdf",)
```

- [ ] **Step 2: 运行测试并确认备份模型不存在**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_workspace.py -k backup -q`

Expected: FAIL。

- [ ] **Step 3: 定义只含资料元数据的目录快照和严格备份模型**

```python
class CatalogDocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    relative_path: str
    sha256: str


class ReviewBackup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    format: Literal["chemical-trade-review-backup"] = "chemical-trade-review-backup"
    version: Literal[1] = 1
    workspace: ReviewWorkspace
    catalog_documents: tuple[CatalogDocumentRef, ...]


class BackupRestoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace: ReviewWorkspace | None
    inquiry: str
    target_market: str
    requires_reanalysis: bool
    changed_files: tuple[str, ...] = ()


def export_review_backup(
    workspace: ReviewWorkspace,
    catalog_documents: tuple[CatalogDocumentRef, ...],
) -> str:
    return ReviewBackup(
        workspace=workspace,
        catalog_documents=catalog_documents,
    ).model_dump_json(indent=2)


def import_review_backup(
    payload: str,
    current_documents: tuple[CatalogDocumentRef, ...],
) -> BackupRestoreResult:
    backup = ReviewBackup.model_validate_json(payload)
    old = {item.relative_path: item.sha256 for item in backup.catalog_documents}
    current = {item.relative_path: item.sha256 for item in current_documents}
    changed = tuple(sorted(
        path for path in set(old) | set(current) if old.get(path) != current.get(path)
    ))
    if changed:
        return BackupRestoreResult(
            workspace=None,
            inquiry=backup.workspace.inquiry,
            target_market=backup.workspace.target_market,
            requires_reanalysis=True,
            changed_files=changed,
        )
    return BackupRestoreResult(
        workspace=backup.workspace,
        inquiry=backup.workspace.inquiry,
        target_market=backup.workspace.target_market,
        requires_reanalysis=False,
    )
```

在 `materials.py` 提供只读快照函数：

```python
def enabled_catalog_snapshot(
    catalog: tuple[ApprovedDocument, ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(
        (entry.relative_path.as_posix(), entry.sha256)
        for entry in catalog if entry.enabled
    ))
```

备份不包含 PDF 字节、索引数据、密钥或可执行内容；导入使用 `extra="forbid"` 和大小上限，手工添加字段不能改变受控资料。

- [ ] **Step 4: 询盘页使用 `st.file_uploader("Open review backup")`，记录页使用 `st.download_button("Save review backup")`**

界面不显示 JSON。资料清单完全一致时恢复最后页面；不一致时列出具体文件，并只恢复询盘和目标市场，要求用户点击“开始分析”。

- [ ] **Step 5: 运行备份正负例和 AppTest**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_workspace.py tests/test_streamlit_app.py -k backup -q`

Expected: PASS；无效、超大、未知版本或额外字段备份均被拒绝，资料目录和索引无写入。

### Task 10: 记录页实时联动与完成快照

**Files:**
- Modify: `src/chemical_trade_copilot/review_workspace.py`
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `tests/test_review_workspace.py`
- Modify: `tests/test_streamlit_app.py`

- [ ] **Step 1: 写出记录实时变化、完成冻结和完成阻断的失败测试**

```python
def test_record_uses_live_decision_and_active_email_version() -> None:
    workspace = workspace_with_follow_up_draft(version=2, language="zh-CN")
    assert record_summary(workspace).expert_decision == "needs_information"
    assert record_summary(workspace).email_version == "2 · zh-CN"


def test_finalize_rejects_pending_decision() -> None:
    with pytest.raises(ValueError, match="expert decision"):
        finalize_workspace(sample_workspace(), completed_at="2026-07-30T17:00:00+08:00")


def test_finalize_freezes_current_snapshot() -> None:
    completed = finalize_workspace(
        workspace_with_follow_up_draft(),
        completed_at="2026-07-30T17:00:00+08:00",
    )
    assert completed.completed_at == "2026-07-30T17:00:00+08:00"
    with pytest.raises(ValueError, match="completed review"):
        set_resolved_follow_up(completed, completed.session.card.follow_ups[0].item_id, True)
```

- [ ] **Step 2: 运行测试并确认完成行为不存在**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_workspace.py -k "record or finalize" -q`

Expected: FAIL。

- [ ] **Step 3: 实现实时摘要和完成门禁**

```python
class ReviewRecordSummary(BaseModel):
    expert_decision: str
    open_gap_count: int
    email_version: str | None
    analysis_revision: str


def record_summary(workspace: ReviewWorkspace) -> ReviewRecordSummary:
    draft = active_draft(workspace)
    version = None if draft is None else f"{draft.version} · {draft.language}"
    return ReviewRecordSummary(
        expert_decision=workspace.session.outcome.decision,
        open_gap_count=len(open_follow_ups(workspace)),
        email_version=version,
        analysis_revision=workspace.session.analysis_revision,
    )


def finalize_workspace(workspace: ReviewWorkspace, *, completed_at: str) -> ReviewWorkspace:
    if workspace.session.outcome.decision == "pending":
        raise ValueError("Choose an expert decision before completing the review")
    if workspace.session.outcome.can_generate_follow_up_draft and active_draft(workspace) is None:
        raise ValueError("Generate the authorized follow-up email before completing the review")
    return workspace.model_copy(update={"completed_at": completed_at, "current_page": "record"})


def _require_mutable(workspace: ReviewWorkspace) -> None:
    if workspace.completed_at is not None:
        raise ValueError("A completed review cannot be changed; create a new revision")
```

在 `set_resolved_follow_up`、页面切换以外的决定/草稿变更函数入口调用 `_require_mutable`。完成页仍允许在八步中只读查看，但任何内容、决定、缺口或邮件修改都必须拒绝。

- [ ] **Step 4: “确认并完成审阅”在同一记录页切换为完成面板**

完成面板显示记录编号、完成时间，并提供“打印”“保存审阅备份”“开始新询盘”。完成状态禁用审阅控件；后续修改必须从完成快照创建新修订，不能覆盖。

- [ ] **Step 5: 运行记录、决定、邮件、打印联动测试**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_review_workspace.py tests/test_streamlit_app.py -k "record or complete or decision or version" -q`

Expected: PASS；记录不再使用分析时固化的静态示例值。

### 阶段三停止门

完成 Task 7–10 后，先验证邮件授权、版本保留、A4 打印、备份正负例和完成冻结，再执行范围与复杂度自查：

- 邮件优化是否只改变已批准的语气与结构，绝不新增事实、承诺或合规主张；
- 打印、记录、备份和邮件是否都读取同一个 `ReviewWorkspace`，没有派生副本成为第二事实源；
- 备份是否严格只读恢复审阅状态，不能写资料目录、索引或执行内容；
- 是否擅自加入邮箱连接、自动发送、云存储、账户、数据库或后台管理能力；
- 是否存在为未来扩展预建但当前没有调用方或测试的接口。

发现拓宽或复杂化时先删除或收窄；更新 `CURRENT_WORK.md` 后停止等待用户继续指令。

## 阶段四：双语与真实环境验收（Task 11–12）

本阶段只补齐双语文案并在真实浏览器、打印、备份和桌面启动器上验证前三阶段成果；不得借验收扩展产品范围。

### Task 11: 双语、文案和完整视觉验收

**Files:**
- Modify: `src/chemical_trade_copilot/localization.py`
- Modify: `src/chemical_trade_copilot/streamlit_app.py`
- Modify: `src/chemical_trade_copilot/ui_components.py`
- Modify: `tests/test_localization.py`
- Modify: `tests/test_streamlit_app.py`
- Modify: `tests/test_ui_components.py`

- [ ] **Step 1: 为八页全部可见文案建立资源键完整性测试**

```python
def test_eight_page_localization_keys_are_complete() -> None:
    required = {
        *(f"page.{name}" for name in REVIEW_PAGES),
        "backup.open", "backup.save", "backup.invalid",
        "draft.optimize", "draft.generate_new_version",
        "print.action", "record.complete",
    }
    assert required <= set(TRANSLATIONS["en"])
    assert set(TRANSLATIONS["en"]) == set(TRANSLATIONS["zh-CN"])
```

- [ ] **Step 2: 运行测试并确认缺失键失败**

Run: `F:\外贸化工\.venv\Scripts\python.exe -m pytest tests/test_localization.py -q`

Expected: FAIL，列出缺少的八页键。

- [ ] **Step 3: 补齐文案并删除无行动价值的说明**

英文和中文都使用 `docs/UI_STYLE_GUIDE.md` 的具体状态语言；不新增“工作台”“JSON”“资料目录指纹”等普通用户术语。

- [ ] **Step 4: 验证界面语言与邮件语言相互独立**

Edge 保持中文界面时切换中文邮件；Chrome 首次访问仍为英文界面和英文邮件。切换任何语言不改变分析修订、决定、缺口或完成状态。

- [ ] **Step 5: 运行全部自动化测试**

Run:

```powershell
$env:PYTHONPATH='src'
$env:CHEMICAL_TRADE_DATABASE='F:\外贸化工\.chroma'
F:\外贸化工\.venv\Scripts\python.exe -m pytest -q
F:\外贸化工\.venv\Scripts\python.exe -m compileall -q src tests
```

Expected: 两条命令退出码均为 `0`，无失败、异常或编译错误。

### Task 12: 真实浏览器、打印、备份和启动器收口

**Files:**
- Verify only: `src/chemical_trade_copilot/streamlit_app.py`
- Verify only: `G:\桌面\启动化工询盘工作台（中英双语）.bat`
- Update during execution: `CURRENT_WORK.md`

- [ ] **Step 1: 用桌面 BAT 启动固定地址并核对实际命令行**

Expected: `http://127.0.0.1:8501` 返回 `200`；进程使用工作树源码、仓库虚拟环境和 `F:\外贸化工\.chroma`，控制台可见且 Ctrl+C 可停止。

- [ ] **Step 2: Edge 完成中文八步正路径**

录入询盘、选择欧盟、分析、关闭一个缺口、打开真实 PDF、选择追问、生成并优化邮件、打印、保存备份、完成审阅。每一步记录、打印和邮件版本即时一致。

- [ ] **Step 3: Chrome 完成英文隔离路径和负例**

首次访问保持英文；导入有效备份可恢复；无效备份被拒绝；禁止决定不能生成邮件；改变询盘或目标市场撤销旧授权并产生新修订。

- [ ] **Step 4: 将打印输出保存为 PDF 并逐页渲染检查**

Expected: A4 页尺寸正确；无网页导航和按钮；正文不小于 12pt；引用、页码、参数、决定和邮件版本与完成快照一致。

- [ ] **Step 5: 最终差异、凭据、生成物和停止条件审计**

Run:

```powershell
& 'C:\Users\HUGO\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe' -C 'F:\外贸化工\.worktrees\technical-review-o1' status --short
& 'C:\Users\HUGO\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe' -C 'F:\外贸化工\.worktrees\technical-review-o1' diff --check
```

Expected: 只包含授权范围；无密钥、客户敏感资料、无关生成物或空白错误；未经授权不提交。

### 阶段四停止门

完成 Task 11–12 后执行全量测试、真实动态验证、差异/凭据/生成物审计和最终复杂度自查。只有全部证据新鲜且范围未扩大时，才可声明实现完成；仍不提交、不推送、不部署。随后更新并按仓库规则清理 `CURRENT_WORK.md`，停止等待用户决定分支收口方式。

## 所有阶段通用的停止规则

- 每个阶段结束都必须停止；用户没有新的继续指令时，不自动进入下一阶段。
- 自查结论必须基于 Git 差异、测试和真实输出，不使用“应该”“大概”。
- 发现范围拓宽时优先删除或收窄实现；若收窄会改变已批准行为，则记录证据并请求用户决定。
- 任何阶段触发文末高风险停止条件时立即停止，不得用放宽断言、隐藏错误或新增复杂层绕过。

## 人工批准点与回滚

1. **当前批准点：** 用户审阅 `docs/UI_STYLE_GUIDE.md` 和本计划。未获得继续实施的明确指令前暂停。
2. **实现后批准点：** 用户在真实 Edge/Chrome 中检查八步流程、邮件、打印和记录，再决定是否收口。
3. **回滚：** 只撤销 `review_workspace.py`、`review_email.py`、对应测试以及八页 UI 接线；保留现有 O1–O4 证据、检索、双语和启动器改动。不得使用 `git reset --hard` 或覆盖用户文件。

## 停止条件

- 任何产品名、引用、文件名、物理页、数值、单位、条件、证据 ID 或决定代码在联动、翻译、邮件、打印或备份中发生无授权变化；
- 备份导入尝试写入资料目录或索引；
- 打印、记录和邮件读取不同状态源；
- 真实资料链接不能定位到引用的物理页；
- 当前受控索引与资料目录不一致；
- 需要新增数据库、账户、外部服务、邮箱连接或资料库管理 UI。

出现任一条件时停止实现，记录证据并请求用户决定，不以降级断言或隐藏错误继续。
