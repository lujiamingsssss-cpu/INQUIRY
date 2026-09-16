from chemical_trade_copilot.ui_components import (
    APP_CSS,
    build_copy_button_html,
    build_print_button_html,
)


def test_global_css_keeps_the_approved_mineral_ink_tokens_and_layout() -> None:
    expected_contract = (
        "--ctc-paper: #F2EFE7",
        "--ctc-surface: #FBFAF6",
        "--ctc-ink: #102B27",
        "--ctc-green: #316A5D",
        "--ctc-mint: #E1EBE6",
        "--ctc-gold: #A78349",
        "--ctc-line: #D7D0C3",
        "--ctc-text: #465750",
        'max-width: 1040px',
        'font-family: Georgia, "Songti SC", serif',
        "@media (max-width: 820px)",
    )

    assert all(token in APP_CSS for token in expected_contract)


def test_global_css_renders_one_accessible_laboratory_review_sheet() -> None:
    expected_contract = (
        '[data-testid="stMainBlockContainer"]',
        ".st-key-ctc_review_sheet",
        "background: var(--ctc-surface)",
        "padding: 48px 64px",
        'Inter, "Segoe UI", "Microsoft YaHei", sans-serif',
        'Georgia, "Songti SC", serif',
        "border-radius: 6px",
        ":focus-visible",
        "outline: 3px solid var(--ctc-gold)",
        '[data-testid="stAlert"]',
        "max-width: 66ch",
        "padding: 24px",
        ".st-key-ctc_email_layout",
        "grid-template-columns: minmax(0, 1fr) 210px",
        'button[kind="primary"] p',
        "color: #FFFFFF",
        ".ctc-record",
        ".ctc-print-preview",
        "grid-template-columns: repeat(2, minmax(0, 1fr))",
        "body * { visibility:hidden !important; }",
        "position:absolute",
        "body *:has(.ctc-print-preview)",
    )

    assert all(token in APP_CSS for token in expected_contract)

    main_rule = APP_CSS.split('[data-testid="stMainBlockContainer"] {', 1)[1].split(
        "}", 1
    )[0]
    assert "background: var(--ctc-surface)" not in main_rule


def test_step_navigation_css_is_flat_current_and_horizontally_scrollable() -> None:
    expected_contract = (
        '[data-testid="stSidebar"]',
        ".ctc-steps",
        "border-radius: 0",
        "border-width: 3px 0 0",
        "min-height: 56px",
        "overflow-x: auto",
        "background: transparent",
        "font-weight: 700",
        "border-top-color: var(--ctc-line)",
        "grid-template-columns: repeat(4, minmax(80px, 1fr))",
        '[data-testid="stColumn"]',
        "min-width: 80px",
        "white-space: nowrap",
        'font-family: "Cascadia Mono", Consolas, monospace',
        "justify-content: flex-start",
        "font-size: 36px",
        "h2 { font-size: 24px",
        "h3 { font-size: 22px",
    )

    assert all(token in APP_CSS for token in expected_contract)
    assert '[data-testid="column"]' not in APP_CSS


def test_copy_button_targets_the_supplied_editor_without_injecting_email_html() -> None:
    html = build_copy_button_html(
        editor_label="Editable customer follow-up",
        button_label="Copy follow-up",
        copied_text="Copied",
        missing_text="Editor not found",
    )

    assert 'aria-label="Copy follow-up"' in html
    assert 'const editorLabel = "Editable customer follow-up"' in html
    assert "getAttribute(\"aria-label\") === editorLabel" in html
    assert "navigator.clipboard.writeText(textarea.value)" in html
    assert "{{EMAIL_BODY}}" not in html


def test_copy_button_escapes_html_and_javascript_parameters() -> None:
    html = build_copy_button_html(
        editor_label='Editor </script><script>alert("x")</script>',
        button_label='<img src=x onerror="alert(1)">',
        copied_text="Copied </script>",
        missing_text="Missing </script>",
    )

    assert "<img src=x" not in html
    assert "</script><script>alert" not in html
    assert "&lt;img src=x" in html
    assert "\\u003c/script\\u003e" in html


def test_print_css_hides_web_controls_and_uses_a4_pages() -> None:
    expected_contract = (
        "@page",
        "size: A4",
        "@media print",
        ".ctc-no-print",
        ".ctc-print-sheet",
        "font-size: 12pt",
        "width: 210mm",
        "min-height: 297mm",
        '[data-testid="stElementContainer"]:has(> [data-testid="stIFrame"])',
    )

    assert all(token in APP_CSS for token in expected_contract)


def test_print_button_is_fixed_trusted_script_without_user_content() -> None:
    html = build_print_button_html("Print / Save PDF")

    assert "window.print()" in html
    assert 'aria-label="Print / Save PDF"' in html
    assert "{{" not in html


def test_print_button_escapes_its_label() -> None:
    html = build_print_button_html('<img src=x onerror="alert(1)">')

    assert "<img src=x" not in html
    assert "&lt;img src=x" in html
