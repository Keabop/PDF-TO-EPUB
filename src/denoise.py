"""Fase 2 — Filtrado de headers, footers y numeración de página.

Se ejecuta antes de ordenar el texto para que ese ruido no contamine el
resultado. Dos mecanismos, robustos ante libros reales:

1. Folios: un número (arábigo o romano) solo, en el margen superior o inferior,
   es numeración de página -> se elimina siempre (no requiere repetición).
2. Encabezados/pies: texto de fuente chica en la MISMA banda vertical del
   margen en muchas páginas. Se detecta por POSICIÓN, no por texto, así que
   atrapa los encabezados que alternan (título del libro en pares, del capítulo
   en impares) y los que cambian de página en página.
"""

import re
from collections import Counter, defaultdict
from typing import Optional

from .models import TextSpan

_MARGIN_FRACTION = 0.09        # 9% superior/inferior = zona de márgenes
_BAND = 6.0                    # alto de banda para agrupar por posición vertical
_HEADER_MIN_PAGES = 0.4        # aparece en >40% de páginas (alterna par/impar)
_HEADING_SIZE_FACTOR = 1.3     # no tocar líneas más grandes (posibles títulos)

# Numeración de página: dígitos solos, o números romanos solos.
_PAGE_NUMBER_RE = re.compile(r"^[ivxlcdmIVXLCDM]+$|^\d+$")


def _body_font_size(pages: dict[int, list[TextSpan]]) -> float:
    counter: Counter = Counter()
    for spans in pages.values():
        for s in spans:
            counter[round(s.font_size)] += len(s.text)
    return float(counter.most_common(1)[0][0]) if counter else 10.0


def _margins(height: float) -> tuple[float, float]:
    return height * _MARGIN_FRACTION, height * (1 - _MARGIN_FRACTION)


def strip_boilerplate(
    pages: dict[int, list[TextSpan]],
    page_heights: Optional[dict[int, float]] = None,
) -> dict[int, list[TextSpan]]:
    """Elimina folios y encabezados/pies repetidos por posición."""
    total_pages = len(pages)
    if total_pages == 0:
        return pages

    if page_heights is None:
        page_heights = {
            page_num: max((s.bbox[3] for s in spans), default=1.0)
            for page_num, spans in pages.items()
        }

    body_size = _body_font_size(pages)
    max_heading = body_size * _HEADING_SIZE_FACTOR

    # --- Detección de bandas de encabezado/pie por posición ---
    # clave: (zona 'T'/'B', banda_y) -> conjunto de páginas donde hay texto
    # chico del margen en esa banda.
    band_pages: dict[tuple[str, int], set[int]] = defaultdict(set)
    for page_num, spans in pages.items():
        top, bottom = _margins(page_heights.get(page_num, 1.0))
        for s in spans:
            ymid = (s.bbox[1] + s.bbox[3]) / 2
            in_top = ymid <= top
            in_bottom = ymid >= bottom
            if not (in_top or in_bottom):
                continue
            if s.font_size > max_heading:
                continue  # título grande, no es encabezado
            zone = "T" if in_top else "B"
            band = round(s.bbox[1] / _BAND)
            band_pages[(zone, band)].add(page_num)

    header_bands = {
        key
        for key, pgs in band_pages.items()
        if len(pgs) / total_pages > _HEADER_MIN_PAGES
    }

    def is_boilerplate(s: TextSpan, height: float) -> bool:
        top, bottom = _margins(height)
        ymid = (s.bbox[1] + s.bbox[3]) / 2
        in_top = ymid <= top
        in_bottom = ymid >= bottom
        if not (in_top or in_bottom):
            return False
        text = s.text.strip()
        # 1) Folio suelto (número/romano) en el margen.
        if _PAGE_NUMBER_RE.match(text):
            return True
        # 2) Encabezado/pie por posición repetida (fuente chica).
        if s.font_size <= max_heading:
            zone = "T" if in_top else "B"
            band = round(s.bbox[1] / _BAND)
            if (zone, band) in header_bands:
                return True
        return False

    cleaned: dict[int, list[TextSpan]] = {}
    for page_num, spans in pages.items():
        height = page_heights.get(page_num, 1.0)
        cleaned[page_num] = [s for s in spans if not is_boilerplate(s, height)]
    return cleaned
