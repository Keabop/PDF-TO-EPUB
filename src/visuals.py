"""Fase 5 — Figuras, fórmulas y tablas.

- Figuras: imágenes embebidas + dibujos vectoriales agrupados en regiones,
  rasterizados y guardados optimizados como JPEG (ver imaging.py).
- Fórmulas: líneas cortas/centradas con whitespace vertical o fuentes
  matemáticas; se recortan como imagen PNG en escala de grises (no MathML).
- Tablas: page.find_tables() nativo -> <table> HTML reflowable.

El formato/compresión de las imágenes lo controla ImageSettings (imaging.py),
para mantener el peso del EPUB bajo el límite de Send to Kindle.
"""

import re

import pymupdf

from .imaging import ImageSettings, save_optimized
from .models import Block, TextSpan

_CAPTION_RE = re.compile(
    r"^(Fig(?:ura|ure)?\.?\s*\d+|Cuadro\s*\d+|Tabla\s*\d+|Table\s*\d+)",
    re.IGNORECASE,
)

# Fuentes típicas de composición matemática.
_MATH_FONT_HINTS = ("symbol", "cmmi", "cmsy", "cmex", "math", "mathematicalpi")

_CAPTION_MAX_GAP = 40.0  # puntos: distancia máx. figura<->caption


def _looks_like_math_font(font_name: str) -> bool:
    lower = font_name.lower()
    return any(hint in lower for hint in _MATH_FONT_HINTS)


def _find_caption(
    region: tuple[float, float, float, float], spans: list[TextSpan]
) -> tuple[str | None, list[TextSpan]]:
    """Busca un caption por proximidad debajo (o encima) de la región.
    Devuelve (texto_caption, spans_consumidos)."""
    rx0, ry0, rx1, ry1 = region
    best: TextSpan | None = None
    for span in spans:
        if not _CAPTION_RE.match(span.text.strip()):
            continue
        sx0, sy0, sx1, sy1 = span.bbox
        # Debajo de la figura o justo encima, y con solape horizontal.
        below = 0 <= sy0 - ry1 <= _CAPTION_MAX_GAP
        above = 0 <= ry0 - sy1 <= _CAPTION_MAX_GAP
        overlaps_x = not (sx1 < rx0 or sx0 > rx1)
        if (below or above) and overlaps_x:
            if best is None or abs(sy0 - ry1) < abs(best.bbox[1] - ry1):
                best = span
    if best is None:
        return None, []

    # Recolecta la línea completa del caption (spans en la misma y).
    caption_spans = [
        s
        for s in spans
        if abs(s.bbox[1] - best.bbox[1]) <= 3.0
        and not (s.bbox[2] < region[0] - 200 or s.bbox[0] > region[2] + 200)
    ]
    caption_spans.sort(key=lambda s: s.bbox[0])
    text = " ".join(s.text.strip() for s in caption_spans).strip()
    return text, caption_spans


def _rasterize(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    out_dir: str,
    name_stem: str,
    kind: str,
    settings: ImageSettings,
) -> str:
    """Rasteriza la región y la guarda optimizada (formato/compresión según
    el tipo). Devuelve la ruta final (la extensión la decide imaging)."""
    pix = page.get_pixmap(clip=rect, dpi=settings.dpi)
    return save_optimized(pix, out_dir, name_stem, kind, settings)


def _image_regions(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Regiones de imágenes embebidas en la página."""
    rects: list[pymupdf.Rect] = []
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            for r in page.get_image_rects(xref):
                rects.append(pymupdf.Rect(r))
        except Exception:
            continue
    return rects


def _drawing_regions(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Agrupa dibujos vectoriales en regiones (clusters) mediante la utilidad
    nativa de PyMuPDF; sirve para figuras hechas de trazos."""
    try:
        clusters = page.cluster_drawings()
    except Exception:
        return []
    return [pymupdf.Rect(c) for c in clusters]


def _merge_overlapping(rects: list[pymupdf.Rect]) -> list[pymupdf.Rect]:
    """Fusiona rectángulos que se solapan/tocan para no recortar una misma
    figura en pedazos."""
    merged: list[pymupdf.Rect] = []
    for rect in sorted(rects, key=lambda r: (r.y0, r.x0)):
        placed = False
        for i, m in enumerate(merged):
            if m.intersects(rect):
                merged[i] = m | rect
                placed = True
                break
        if not placed:
            merged.append(pymupdf.Rect(rect))
    return merged


def _detect_formula_lines(
    spans: list[TextSpan], page_width: float, column_width: float
) -> list[tuple[float, float, float, float]]:
    """Detecta líneas que parecen fórmulas: fuentes matemáticas, o líneas
    cortas/centradas. Devuelve regiones (bbox) a recortar."""
    regions: list[tuple[float, float, float, float]] = []
    # Agrupa spans por línea (y0 aprox.).
    by_line: dict[int, list[TextSpan]] = {}
    for s in spans:
        by_line.setdefault(round(s.bbox[1] / 3.0), []).append(s)

    for line_spans in by_line.values():
        text = "".join(s.text for s in line_spans).strip()
        if not text:
            continue
        has_math_font = any(_looks_like_math_font(s.font_name) for s in line_spans)
        x0 = min(s.bbox[0] for s in line_spans)
        y0 = min(s.bbox[1] for s in line_spans)
        x1 = max(s.bbox[2] for s in line_spans)
        y1 = max(s.bbox[3] for s in line_spans)
        width = x1 - x0
        is_short = width < column_width * 0.5
        centered = abs((x0 + x1) / 2 - page_width / 2) < page_width * 0.12
        # Señal fuerte: fuente matemática. Señal débil: corta + centrada +
        # con dígitos/operadores.
        looks_formulaic = bool(re.search(r"[=+\-×·/^_∑∫√≤≥≈∞]", text))
        if has_math_font or (is_short and centered and looks_formulaic):
            # Padding para no cortar sub/superíndices.
            regions.append((x0 - 4, y0 - 4, x1 + 4, y1 + 4))
    return regions


def extract_visuals(
    page: pymupdf.Page,
    spans: list[TextSpan],
    out_dir: str,
    page_index: int,
    settings: ImageSettings,
) -> tuple[list[Block], set[int]]:
    """Detecta figuras, fórmulas y tablas en la página y las convierte en
    Blocks. Devuelve (blocks, ids_de_spans_consumidos) para que el texto de
    captions no se duplique como párrafo."""
    blocks: list[Block] = []
    consumed_span_ids: set[int] = set()
    page_rect = page.rect
    page_width = page_rect.width
    column_width = page_width / 2.0  # asunción de 2 columnas para el umbral

    # --- Tablas (primero, para excluir su área del resto) ---
    table_rects: list[pymupdf.Rect] = []
    try:
        tables = page.find_tables()
        table_list = list(tables.tables) if tables else []
    except Exception:
        table_list = []

    for t_idx, table in enumerate(table_list):
        rect = pymupdf.Rect(table.bbox)
        table_rects.append(rect)
        html = _table_to_html(table)
        caption, cap_spans = _find_caption(tuple(rect), spans)
        for cs in cap_spans:
            consumed_span_ids.add(id(cs))
        blocks.append(
            Block(
                kind="table",
                order_index=0,
                page_num=page_index,
                html_table=html,
                caption_text=caption,
                y0=rect.y0,
            )
        )

    # --- Figuras (imágenes + dibujos vectoriales) ---
    fig_rects = _merge_overlapping(
        _image_regions(page) + _drawing_regions(page)
    )
    for f_idx, rect in enumerate(fig_rects):
        # Ignora regiones diminutas (líneas, viñetas) o dentro de una tabla.
        if rect.width < 20 or rect.height < 20:
            continue
        if any(_mostly_inside(rect, tr) for tr in table_rects):
            continue
        name_stem = f"p{page_index:04d}_fig{f_idx:02d}"
        try:
            path = _rasterize(page, rect, out_dir, name_stem, "figure", settings)
        except Exception:
            continue
        caption, cap_spans = _find_caption(tuple(rect), spans)
        for cs in cap_spans:
            consumed_span_ids.add(id(cs))
        blocks.append(
            Block(
                kind="figure",
                order_index=0,
                page_num=page_index,
                image_path=path,
                caption_text=caption,
                y0=rect.y0,
            )
        )

    # --- Fórmulas ---
    # Excluye spans que ya caen dentro de figuras o tablas.
    exclude = fig_rects + table_rects
    free_spans = [
        s
        for s in spans
        if not any(_point_inside(s.bbox, r) for r in exclude)
    ]
    for m_idx, region in enumerate(
        _detect_formula_lines(free_spans, page_width, column_width)
    ):
        rect = pymupdf.Rect(region)
        if rect.width < 10 or rect.height < 6:
            continue
        name_stem = f"p{page_index:04d}_eq{m_idx:02d}"
        try:
            path = _rasterize(page, rect, out_dir, name_stem, "formula", settings)
        except Exception:
            continue
        # Marca los spans de esa fórmula como consumidos.
        for s in free_spans:
            if _point_inside(s.bbox, rect):
                consumed_span_ids.add(id(s))
        blocks.append(
            Block(
                kind="formula",
                order_index=0,
                page_num=page_index,
                image_path=path,
                y0=rect.y0,
            )
        )

    return blocks, consumed_span_ids


def _table_to_html(table) -> str:
    """Convierte una tabla de PyMuPDF a <table> HTML simple."""
    try:
        rows = table.extract()
    except Exception:
        return "<table></table>"
    parts = ["<table>"]
    for r_idx, row in enumerate(rows):
        tag = "th" if r_idx == 0 else "td"
        cells = "".join(
            f"<{tag}>{_escape(str(c) if c is not None else '')}</{tag}>"
            for c in row
        )
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</table>")
    return "".join(parts)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _mostly_inside(inner: pymupdf.Rect, outer: pymupdf.Rect) -> bool:
    inter = inner & outer
    if inter.is_empty:
        return False
    inner_area = inner.width * inner.height
    if inner_area <= 0:
        return False
    return (inter.width * inter.height) / inner_area > 0.7


def _point_inside(bbox: tuple, rect: pymupdf.Rect) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1
