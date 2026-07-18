"""Fase 2 — Filtrado de headers, footers y numeración de página.

Se ejecuta antes de la detección de columnas para que ese heurístico no se
contamine con texto repetido en los márgenes.
"""

import re
from collections import defaultdict
from typing import Optional

from .models import TextSpan

_POS_TOLERANCE = 5.0  # puntos, para agrupar spans "en la misma posición"
_REPETITION_THRESHOLD = 0.7  # aparece en >70% de las páginas
_MARGIN_FRACTION = 0.10  # 10% superior o inferior de la página

# Numeración de página: dígitos solos, o números romanos solos.
_PAGE_NUMBER_RE = re.compile(r"^[ivxlcdmIVXLCDM]+$|^\d+$")


def _quantize(value: float, tolerance: float = _POS_TOLERANCE) -> float:
    return round(value / tolerance) * tolerance


def _text_key(span: TextSpan) -> str:
    """Normaliza el texto para agrupar: la numeración de página varía
    entre páginas pero cae en la misma posición, así que se trata como
    un solo símbolo comodín."""
    text = span.text.strip()
    if _PAGE_NUMBER_RE.match(text):
        return "<PAGENUM>"
    return text


def _group_key(span: TextSpan) -> tuple[str, float, float]:
    x0, y0, _, _ = span.bbox
    return (_text_key(span), _quantize(x0), _quantize(y0))


def _in_margin(y0: float, height: float) -> bool:
    top_margin = height * _MARGIN_FRACTION
    bottom_margin = height * (1 - _MARGIN_FRACTION)
    return y0 <= top_margin or y0 >= bottom_margin


def strip_boilerplate(
    pages: dict[int, list[TextSpan]],
    page_heights: Optional[dict[int, float]] = None,
) -> dict[int, list[TextSpan]]:
    """Detecta y elimina texto que se repite en la misma posición (bbox)
    en la mayoría de páginas (headers, footers, numeración).

    `page_heights` es opcional; si no se provee, se estima como el y1 máximo
    de los spans de cada página (aproximación razonable del alto útil).
    """
    total_pages = len(pages)
    if total_pages == 0:
        return pages

    if page_heights is None:
        page_heights = {
            page_num: max((s.bbox[3] for s in spans), default=1.0)
            for page_num, spans in pages.items()
        }

    # Cuenta en cuántas páginas distintas aparece cada "posición de texto"
    # y si en esas apariciones el span cae dentro del margen.
    occurrences: dict[tuple[str, float, float], set[int]] = defaultdict(set)
    margin_hits: dict[tuple[str, float, float], int] = defaultdict(int)

    for page_num, spans in pages.items():
        height = page_heights.get(page_num, 1.0)
        for span in spans:
            key = _group_key(span)
            occurrences[key].add(page_num)
            if _in_margin(span.bbox[1], height):
                margin_hits[key] += 1

    boilerplate_keys: set[tuple[str, float, float]] = set()
    for key, page_set in occurrences.items():
        frequency = len(page_set) / total_pages
        if frequency <= _REPETITION_THRESHOLD:
            continue
        # Todas (o casi todas) las apariciones deben estar en el margen.
        if margin_hits[key] / len(page_set) >= 0.9:
            boilerplate_keys.add(key)

    cleaned: dict[int, list[TextSpan]] = {}
    for page_num, spans in pages.items():
        cleaned[page_num] = [
            s for s in spans if _group_key(s) not in boilerplate_keys
        ]

    return cleaned
