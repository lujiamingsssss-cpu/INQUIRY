import base64
import hashlib
import html
from dataclasses import dataclass
from pathlib import Path

import fitz

from .inquiry_analysis import SourceCitation
from .pdf_pages import ApprovedPdf, load_approved_pdf


@dataclass(frozen=True, slots=True)
class RenderedSourcePage:
    product: str
    source_file: str
    page_number: int
    date_revision: str
    jurisdiction: str
    png_bytes: bytes


def render_citation_page(
    citation: SourceCitation,
    materials_root: Path,
    catalog_path: Path,
    *,
    scale: float = 1.5,
) -> RenderedSourcePage:
    approved = load_approved_pdf(
        citation.product,
        citation.source_file,
        materials_root,
        catalog_path,
    )
    return render_approved_citation_page(citation, approved, scale=scale)


def render_approved_citation_page(
    citation: SourceCitation,
    approved: ApprovedPdf,
    *,
    scale: float = 1.5,
) -> RenderedSourcePage:
    """Render a physical citation page from one verified PDF byte snapshot."""
    if (
        approved.product != citation.product
        or approved.source_file != citation.source_file
    ):
        raise ValueError(
            f"Citation is not an approved source document: {citation.source_file}"
        )
    with fitz.open(stream=approved.pdf_bytes, filetype="pdf") as document:
        if citation.page_number < 1 or citation.page_number > document.page_count:
            raise ValueError(
                f"Physical page {citation.page_number} is outside the source PDF"
            )
        page = document.load_page(citation.page_number - 1)
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(scale, scale),
            alpha=False,
        )
        png_bytes = pixmap.tobytes("png")
    return RenderedSourcePage(
        product=approved.product,
        source_file=citation.source_file,
        page_number=citation.page_number,
        date_revision=approved.date_revision,
        jurisdiction=approved.jurisdiction,
        png_bytes=png_bytes,
    )


def build_zoomable_page_html(
    png_bytes: bytes, *, alt_text: str, source_metadata: str
) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    safe_alt = html.escape(alt_text, quote=True)
    safe_metadata = html.escape(source_metadata)
    viewer_id = hashlib.sha256(png_bytes + alt_text.encode("utf-8")).hexdigest()[:12]
    return f"""
<div class="ctc-source-viewer" data-viewer-id="{viewer_id}"
     data-min-zoom="50" data-max-zoom="250" data-zoom-step="25">
  <button class="ctc-source-thumbnail" type="button"
          aria-label="Open source page viewer">
    <img src="data:image/png;base64,{encoded}" alt="{safe_alt}">
    <span>Click to inspect the physical PDF page</span>
  </button>
  <div class="ctc-source-overlay" role="dialog" aria-modal="true"
       aria-label="Source PDF page viewer" hidden>
    <div class="ctc-source-toolbar">
      <span class="ctc-source-identity">{safe_metadata}</span>
      <div>
        <span class="ctc-zoom-status" aria-live="polite">100%</span>
        <button type="button" data-action="zoom-out" aria-label="Zoom out">−</button>
        <button type="button" data-action="reset" aria-label="Reset zoom">Reset</button>
        <button type="button" data-action="zoom-in" aria-label="Zoom in">+</button>
        <button type="button" data-action="close" aria-label="Close source page viewer">Close</button>
      </div>
    </div>
    <div class="ctc-source-canvas">
      <img src="data:image/png;base64,{encoded}" alt="{safe_alt}">
    </div>
  </div>
</div>
<style>
.ctc-source-thumbnail {{ width:100%; border:1px solid #D7D0C3; border-radius:12px;
  background:#FBFAF6; padding:12px; color:#316A5D; cursor:zoom-in; text-align:left; }}
.ctc-source-thumbnail img {{ display:block; width:100%; max-height:260px;
  object-fit:contain; background:#D2CFC7; }}
.ctc-source-thumbnail span {{ display:block; padding-top:9px; font:600 12px Inter,Segoe UI,sans-serif; }}
.ctc-source-thumbnail:focus-visible,.ctc-source-toolbar button:focus-visible {{ outline:3px solid #A78349; outline-offset:2px; }}
.ctc-source-overlay {{ position:fixed; inset:0; z-index:999999; background:rgba(16,43,39,.88);
  padding:24px; }}
.ctc-source-overlay[hidden] {{ display:none; }}
.ctc-source-toolbar {{ min-height:70px; display:flex; align-items:center; justify-content:space-between;
  background:#FBFAF6; padding:0 16px; border-radius:12px 12px 0 0; color:#102B27;
  font:600 13px Inter,Segoe UI,sans-serif; }}
.ctc-source-identity {{ max-width:62%; line-height:1.45; padding:8px 12px 8px 0; }}
.ctc-zoom-status {{ margin-right:8px; font-variant-numeric:tabular-nums; }}
.ctc-source-toolbar button {{ border:1px solid #BFB8AB; background:#F2EFE7; color:#102B27;
  border-radius:7px; padding:8px 11px; margin-left:5px; cursor:pointer; }}
.ctc-source-toolbar button[data-action="close"] {{ background:#102B27; color:white; border-color:#102B27; }}
.ctc-source-canvas {{ height:calc(100vh - 118px); overflow:auto; background:#C7C4BC;
  text-align:center; border-radius:0 0 12px 12px; padding:24px; }}
.ctc-source-canvas img {{ display:block; width:100%; height:auto; max-width:none; margin:0 auto;
  cursor:zoom-in; box-shadow:0 12px 35px rgba(0,0,0,.25); }}
</style>
<script>
(function() {{
  const root = document.currentScript.previousElementSibling.previousElementSibling;
  const thumbnail = root.querySelector(".ctc-source-thumbnail");
  const overlay = root.querySelector(".ctc-source-overlay");
  const image = root.querySelector(".ctc-source-canvas img");
  const status = root.querySelector(".ctc-zoom-status");
  const minZoom = Number(root.dataset.minZoom);
  const maxZoom = Number(root.dataset.maxZoom);
  const step = Number(root.dataset.zoomStep);
  let zoom = 100;
  function applyZoom(next) {{
    zoom = Math.max(minZoom, Math.min(maxZoom, next));
    image.style.width = zoom + "%";
    image.style.cursor = zoom === 100 ? "zoom-in" : "zoom-out";
    status.textContent = zoom + "%";
  }}
  function closeViewer() {{ overlay.hidden = true; document.body.style.overflow = ""; applyZoom(100); }}
  thumbnail.addEventListener("click", function() {{
    overlay.hidden = false; document.body.style.overflow = "hidden"; applyZoom(100);
  }});
  image.addEventListener("click", function() {{ applyZoom(zoom === 100 ? 150 : 100); }});
  root.querySelector('[data-action="zoom-in"]').addEventListener("click", function() {{ applyZoom(zoom + step); }});
  root.querySelector('[data-action="zoom-out"]').addEventListener("click", function() {{ applyZoom(zoom - step); }});
  root.querySelector('[data-action="reset"]').addEventListener("click", function() {{ applyZoom(100); }});
  root.querySelector('[data-action="close"]').addEventListener("click", closeViewer);
  overlay.addEventListener("click", function(event) {{ if (event.target === overlay) closeViewer(); }});
  document.addEventListener("keydown", function(event) {{ if (event.key === "Escape" && !overlay.hidden) closeViewer(); }});
}})();
</script>
""".strip()
