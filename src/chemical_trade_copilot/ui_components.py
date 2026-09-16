import html
import json


APP_CSS = """
<style>
:root {
  --ctc-paper: #F2EFE7;
  --ctc-surface: #FBFAF6;
  --ctc-ink: #102B27;
  --ctc-green: #316A5D;
  --ctc-mint: #E1EBE6;
  --ctc-gold: #A78349;
  --ctc-line: #D7D0C3;
  --ctc-text: #465750;
}
.stApp { background: var(--ctc-paper); color: var(--ctc-ink); }
[data-testid="stMainBlockContainer"] {
  max-width: 1040px;
  padding: 30px 26px 70px;
}
.st-key-ctc_review_sheet,
.st-key-ctc_entry_sheet {
  margin-top: 28px;
  min-height: 700px;
  padding: 48px 64px;
  background: var(--ctc-surface);
  border: 1px solid var(--ctc-line);
  border-radius: 6px;
  box-shadow: 0 10px 28px rgba(16,43,39,.06);
}
.st-key-ctc_app_header [data-testid="stHorizontalBlock"] {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 32px;
  align-items: end;
}
.st-key-ctc_app_header [data-testid="stColumn"],
.st-key-ctc_email_layout [data-testid="stColumn"] { width: 100% !important; }
.st-key-ctc_email_layout [data-testid="stHorizontalBlock"] {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 210px;
  gap: 46px;
  align-items: start;
}
.st-key-ctc_email_layout [data-testid="stColumn"]:last-child {
  border-left: 1px solid var(--ctc-line);
  padding-left: 22px;
}
/* 来源行：缩略图按自身宽度贴左，文件身份与操作占满剩余宽度。
   与邮件区同一套网格、间距与分隔线，只是栏宽按内容分配。 */
.st-key-ctc_source_layout [data-testid="stHorizontalBlock"] {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 38px;
  align-items: start;
}
.st-key-ctc_source_layout [data-testid="stColumn"] { width: 100% !important; }
.st-key-ctc_source_layout [data-testid="stColumn"]:first-child { width: auto !important; }
.st-key-ctc_source_layout [data-testid="stColumn"]:last-child {
  border-left: 1px solid var(--ctc-line);
  padding-left: 22px;
}
[data-testid="stSidebar"] { display: none; }
html, body, .stApp, button, input, textarea, select, label, p {
  font-family: Inter, "Segoe UI", "Microsoft YaHei", sans-serif;
}
h1, h2, h3 { font-family: Georgia, "Songti SC", serif !important; color: var(--ctc-ink) !important; }
h1 { letter-spacing: -0.025em; line-height: 1.06 !important; }
p, label, [data-testid="stCaptionContainer"] { color: var(--ctc-text); }
[data-testid="stMarkdownContainer"] > p { max-width: 66ch; line-height: 1.65; }
hr { border-color: var(--ctc-line) !important; }
.stTextArea textarea { background: var(--ctc-surface); border-color: var(--ctc-line); border-radius: 6px; color: var(--ctc-ink); }
.stTextArea textarea:focus { border-color: var(--ctc-green); box-shadow: 0 0 0 1px var(--ctc-green); }
.stButton > button, [data-testid="stDownloadButton"] > button { border-radius: 6px; min-height: 44px; }
.stButton > button:focus-visible, [data-testid="stDownloadButton"] > button:focus-visible,
input:focus-visible, textarea:focus-visible, [role="combobox"]:focus-visible {
  outline: 3px solid var(--ctc-gold);
  outline-offset: 2px;
}
.stButton > button[kind="primary"] { background: var(--ctc-ink); border-color: var(--ctc-ink); }
.stButton > button[kind="primary"] p { color: #FFFFFF; }
.stButton > button:not([kind="primary"]) { border-color: var(--ctc-ink); color: var(--ctc-ink); }
[data-testid="stAlert"] { border-radius: 6px; border: 1px solid var(--ctc-line); }
[data-testid="stCheckbox"] label:has(input:checked) p {
  color: var(--ctc-text);
  text-decoration: line-through;
  text-decoration-thickness: 1.5px;
}
.ctc-eyebrow { color: var(--ctc-green); font: 700 11px Inter, "Segoe UI", sans-serif; letter-spacing: .15em; text-transform: uppercase; }
.ctc-decision-line { display:grid; grid-template-columns:repeat(4,1fr); border-top:1px solid var(--ctc-line); border-bottom:1px solid var(--ctc-line); margin:24px 0 8px; }
.ctc-decision { padding:14px 12px; border-right:1px solid var(--ctc-line); font:12px Inter,"Segoe UI",sans-serif; color:var(--ctc-text); }
.ctc-decision:last-child { border-right:0; }
.ctc-decision b { display:block; margin-top:4px; color:var(--ctc-ink); font-size:13px; }
.ctc-dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--ctc-green); margin-right:6px; }
.ctc-dot.open { background:var(--ctc-gold); }
.ctc-fact { border:1px solid var(--ctc-line); border-radius:12px; overflow:hidden; background:var(--ctc-surface); margin:12px 0; }
.ctc-fact-head,.ctc-source { display:flex; justify-content:space-between; gap:12px; padding:11px 14px; background:var(--ctc-mint); color:var(--ctc-green); font-size:11px; }
.ctc-fact-grid { display:grid; grid-template-columns:repeat(3,1fr); }
.ctc-fact-cell { padding:17px; border-right:1px solid var(--ctc-line); color:var(--ctc-text); font-size:12px; }
.ctc-fact-cell:last-child { border-right:0; }
.ctc-fact-cell b { display:block; color:var(--ctc-ink); font:700 14px Inter,"Segoe UI",sans-serif; font-style:normal; font-variant-numeric:tabular-nums; }
.ctc-warning { border-left:3px solid var(--ctc-gold); background:#ECE7DC; padding:12px 15px; color:#70614D; font-size:12px; }
.ctc-checklist { list-style:none; padding:0; margin:0; }
.ctc-checklist li { padding:9px 0; border-bottom:1px solid var(--ctc-line); color:var(--ctc-text); font-size:13px; }
.ctc-checklist li:before { content:"□"; margin-right:9px; color:var(--ctc-green); }
.ctc-guardrail { border-left:3px solid #8D4B3B; background:#F3E5DF; padding:12px 15px; color:#754B40; font-size:12px; }
.ctc-record { border:1px solid var(--ctc-line); border-radius:6px; overflow:hidden; background:var(--ctc-surface); }
.ctc-record-head { display:flex; justify-content:space-between; gap:20px; padding:16px 20px; background:var(--ctc-mint); color:var(--ctc-green); font-size:12px; letter-spacing:.04em; text-transform:uppercase; }
.ctc-record-head strong { color:var(--ctc-ink); }
.ctc-record section { padding:18px 20px; border-top:1px solid var(--ctc-line); }
.ctc-record dl { display:grid; grid-template-columns:minmax(145px, .65fr) minmax(0, 1.35fr); gap:10px 22px; margin:0; }
.ctc-record dt { color:var(--ctc-text); font-size:12px; }
.ctc-record dd { margin:0; color:var(--ctc-ink); font-weight:600; overflow-wrap:anywhere; }
.ctc-print-preview { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:18px; align-items:start; }
.ctc-print-preview .ctc-print-sheet { width:100%; min-height:0; aspect-ratio:210 / 297; margin:0; padding:7.5%; overflow:hidden; font-size:7.5px; }
.ctc-print-preview .ctc-print-sheet h2 { margin:0 0 5%; font-size:15px; }
.ctc-print-preview .ctc-print-sheet h3 { margin:4% 0 1.5%; font-size:10px; }
.ctc-print-preview .ctc-print-sheet p,.ctc-print-preview .ctc-print-sheet li,.ctc-print-preview .ctc-print-sheet table { font-size:7.5px; line-height:1.35; }
.ctc-print-sheet { box-sizing:border-box; width: 210mm; min-height: 297mm; margin:18px auto; padding:16mm 17mm; background:white; color:#102B27; font-size: 12pt; }
.ctc-print-sheet h2 { margin:0 0 8mm; font-size:20pt; }
.ctc-print-sheet h3 { margin:6mm 0 2mm; font-size:13pt; }
.ctc-print-sheet p,.ctc-print-sheet li { color:#102B27; font-size:12pt; line-height:1.45; }
.ctc-print-meta { display:flex; justify-content:space-between; gap:8mm; padding-bottom:4mm; border-bottom:1px solid #D7D0C3; }
.ctc-print-sheet table { width:100%; border-collapse:collapse; font-size:12pt; }
.ctc-print-sheet th,.ctc-print-sheet td { padding:2.5mm; border:1px solid #D7D0C3; text-align:left; vertical-align:top; }
.ctc-print-email { white-space:pre-wrap; overflow-wrap:anywhere; }
.ctc-print-signoff { margin-top:10mm; padding-top:4mm; border-top:1px solid #102B27; }
@page { size: A4; margin: 0; }
@media print {
  body * { visibility:hidden !important; }
  .ctc-print-preview, .ctc-print-preview * { visibility:visible !important; }
  body *:has(.ctc-print-preview) { position:static !important; margin:0 !important; padding:0 !important; }
  .ctc-no-print, [data-testid="stToolbar"], [data-testid="stHeader"],
  [data-testid="stBottom"],
  [data-testid="stElementContainer"]:has(> [data-testid="stIFrame"]),
  header, footer { display:none !important; }
  [data-testid="stMainBlockContainer"] { max-width:none; padding:0; }
  .stApp { background:white; }
  .ctc-print-preview { position:absolute; left:0; top:0; width:210mm; display:block; }
  .ctc-print-sheet { width: 210mm; min-height: 297mm; margin:0; padding:16mm 17mm; break-after:page; box-shadow:none; font-size: 12pt; }
  .ctc-print-preview .ctc-print-sheet { width:210mm; min-height:297mm; aspect-ratio:auto; margin:0; padding:16mm 17mm; overflow:visible; font-size:12pt; }
  .ctc-print-preview .ctc-print-sheet h2 { margin:0 0 8mm; font-size:20pt; }
  .ctc-print-preview .ctc-print-sheet h3 { margin:6mm 0 2mm; font-size:13pt; }
  .ctc-print-preview .ctc-print-sheet p,.ctc-print-preview .ctc-print-sheet li,.ctc-print-preview .ctc-print-sheet table { font-size:12pt; line-height:1.45; }
  .ctc-print-sheet:last-child { break-after:auto; }
}
.ctc-steps,
.st-key-ctc_steps [data-testid="stHorizontalBlock"] { overflow-x: auto; }
.ctc-steps [data-testid="stButton"] button,
.st-key-ctc_steps [data-testid="stButton"] button {
  background: transparent;
  border-radius: 0;
  border-width: 3px 0 0;
  border-top-color: var(--ctc-line);
  color: var(--ctc-text);
  min-height: 56px;
  justify-content: flex-start;
  text-align: left;
  padding: 10px 8px;
}
.ctc-steps [data-testid="stButton"] button p,
.st-key-ctc_steps [data-testid="stButton"] button p {
  color:inherit;
  line-height:1.25;
  white-space: nowrap;
}
.ctc-steps [data-testid="stButton"] button p strong,
.st-key-ctc_steps [data-testid="stButton"] button p strong {
  display:inline-block;
  margin-bottom:3px;
  color:var(--ctc-green);
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size:11px;
  letter-spacing:.04em;
}
.ctc-steps [data-testid="stButton"] button[kind="primary"],
.st-key-ctc_steps [data-testid="stButton"] button[kind="primary"] {
  background: transparent;
  border-top-color: var(--ctc-green);
  color: var(--ctc-ink);
  font-weight: 700;
}
@media (max-width: 820px) {
  [data-testid="stMainBlockContainer"] { padding: 20px 0 48px; }
  .st-key-ctc_review_sheet,.st-key-ctc_entry_sheet { min-height:0; margin-top:24px; padding: 24px; border-width:1px 0; border-radius:0; box-shadow:none; }
  .st-key-ctc_app_header { padding:0 24px; }
  h1 { font-size: 36px !important; line-height:1.12 !important; }
  h2 { font-size: 24px !important; line-height:1.18 !important; }
  h3 { font-size: 22px !important; line-height:1.2 !important; }
  .st-key-ctc_app_header [data-testid="stHorizontalBlock"],
  .st-key-ctc_email_layout [data-testid="stHorizontalBlock"] { grid-template-columns:1fr; gap:18px; }
  .st-key-ctc_email_layout [data-testid="stColumn"]:last-child { border-left:0; border-top:1px solid var(--ctc-line); padding:20px 0 0; }
  .ctc-decision-line,.ctc-fact-grid { grid-template-columns:1fr; }
  .ctc-print-preview { grid-template-columns:1fr; }
  .ctc-record dl { grid-template-columns:1fr; gap:3px; }
  .ctc-record dd + dt { margin-top:10px; }
  .ctc-decision,.ctc-fact-cell { border-right:0; border-bottom:1px solid var(--ctc-line); }
  .st-key-ctc_steps [data-testid="stHorizontalBlock"] {
    display:grid;
    grid-template-columns: repeat(4, minmax(80px, 1fr));
  }
  .ctc-steps [data-testid="stColumn"],
  .st-key-ctc_steps [data-testid="stColumn"] { width:100% !important; min-width: 80px; }
}
</style>
"""


def _safe_javascript_string(value: str) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def build_copy_button_html(
    *,
    editor_label: str,
    button_label: str,
    copied_text: str,
    missing_text: str,
) -> str:
    safe_button = html.escape(button_label, quote=True)
    editor_json = _safe_javascript_string(editor_label)
    copied_json = _safe_javascript_string(copied_text)
    missing_json = _safe_javascript_string(missing_text)
    return f"""
<div class="ctc-copy-email">
  <button type="button" aria-label="{safe_button}">{safe_button}</button>
  <span aria-live="polite"></span>
</div>
<style>
.ctc-copy-email {{ display:flex; justify-content:flex-end; align-items:center; gap:10px; }}
.ctc-copy-email button {{ border:0; border-radius:8px; background:#102B27; color:white;
  padding:10px 15px; font:700 12px Inter,"Segoe UI",sans-serif; cursor:pointer; }}
.ctc-copy-email button:focus-visible {{ outline:3px solid #A78349; outline-offset:2px; }}
.ctc-copy-email span {{ color:#316A5D; font:600 11px Inter,"Segoe UI",sans-serif; }}
</style>
<script>
(function() {{
  const root = document.currentScript.previousElementSibling.previousElementSibling;
  const button = root.querySelector("button");
  const status = root.querySelector("span");
  const editorLabel = {editor_json};
  const copiedText = {copied_json};
  const missingText = {missing_json};
  button.addEventListener("click", async function() {{
    const textarea = Array.from(document.querySelectorAll("textarea")).find(
      (item) => item.getAttribute("aria-label") === editorLabel
    );
    if (!textarea) {{ status.textContent = missingText; return; }}
    await navigator.clipboard.writeText(textarea.value);
    status.textContent = copiedText;
  }});
}})();
</script>
""".strip()


def build_print_button_html(button_label: str) -> str:
    safe_button = html.escape(button_label, quote=True)
    return f"""
<div class="ctc-no-print ctc-print-action">
  <button type="button" aria-label="{safe_button}">{safe_button}</button>
</div>
<style>
.ctc-print-action button {{ border:0; border-radius:8px; background:#102B27; color:white;
  padding:10px 15px; font:700 12px Inter,"Segoe UI",sans-serif; cursor:pointer; }}
.ctc-print-action button:focus-visible {{ outline:3px solid #A78349; outline-offset:2px; }}
</style>
<script>
document.currentScript.previousElementSibling.previousElementSibling
  .querySelector("button")
  .addEventListener("click", function() {{
    try {{ window.parent.print(); }} catch (error) {{ window.print(); }}
  }});
</script>
""".strip()
