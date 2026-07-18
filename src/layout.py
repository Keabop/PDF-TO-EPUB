"""Fase 3 — Detección de columnas y orden de lectura.

Se procesa por página, sin asumir el mismo layout en todo el documento:
habrá páginas a ancho completo (figuras grandes, portada) mezcladas con
páginas de dos columnas.
"""

from .models import TextSpan

# Fracción del ancho de página que un span debe cruzar para considerarse
# "ancho completo" (spanning) en vez de pertenecer a una sola columna.
_FULL_WIDTH_FRACTION = 0.60


def _detect_split_x(
    spans: list[TextSpan], page_width: float
) -> float | None:
    """Estima la coordenada x del corte entre dos columnas mediante un
    histograma de los x0 de inicio. Devuelve None si parece una columna."""
    if len(spans) < 6:
        return None

    mid = page_width / 2.0
    left_starts = [s.bbox[0] for s in spans if s.bbox[0] < mid]
    right_starts = [s.bbox[0] for s in spans if s.bbox[0] >= mid]

    # Para ser dos columnas de verdad, ambos lados deben tener masa de texto.
    if len(left_starts) < 3 or len(right_starts) < 3:
        return None

    # ¿Hay un "valle" claro alrededor de la mitad? Si muchos spans empiezan
    # justo a la derecha del centro, es la segunda columna.
    right_col_start = min(right_starts)
    left_col_max_right = max(
        (s.bbox[2] for s in spans if s.bbox[0] < mid), default=mid
    )
    # El inicio de la columna derecha debe caer después del final de la
    # izquierda (con un pequeño gap), o sea, existe canaleta.
    if right_col_start > left_col_max_right - 5:
        return mid
    return None


def detect_columns(spans: list[TextSpan], page_width: float) -> list[TextSpan]:
    """Agrupa bloques por su coordenada x de inicio para detectar 1 o 2
    columnas por página. Regresa los spans anotados con column_index y ya
    ordenados en orden de lectura real.

    Estrategia:
      1. Si no hay corte de columna claro -> una columna, orden por (y, x).
      2. Si hay dos columnas -> se separan los spans "ancho completo"
         (que cruzan la canaleta) de los de cada columna. Se emite en
         orden: para cada banda vertical, primero lo full-width que la
         abre, luego columna izquierda, luego derecha.
    """
    if not spans:
        return []

    split_x = _detect_split_x(spans, page_width)

    if split_x is None:
        ordered = sorted(spans, key=lambda s: (round(s.bbox[1]), s.bbox[0]))
        for s in ordered:
            s.column_index = 0
        return ordered

    full_width_threshold = page_width * _FULL_WIDTH_FRACTION
    full_width: list[TextSpan] = []
    left: list[TextSpan] = []
    right: list[TextSpan] = []

    for span in spans:
        width = span.bbox[2] - span.bbox[0]
        crosses_gutter = span.bbox[0] < split_x < span.bbox[2]
        if width >= full_width_threshold and crosses_gutter:
            span.column_index = -1
            full_width.append(span)
        elif span.bbox[0] < split_x:
            span.column_index = 0
            left.append(span)
        else:
            span.column_index = 1
            right.append(span)

    return _interleave(full_width, left, right)


def _interleave(
    full_width: list[TextSpan],
    left: list[TextSpan],
    right: list[TextSpan],
) -> list[TextSpan]:
    """Intercala los bloques ancho-completo según su posición vertical
    entre los bloques de columnas.

    Modelo simple y robusto: los spans full-width parten la página en
    bandas. Dentro de cada banda [y_prev, y_full) se emite izquierda y
    luego derecha; después el propio bloque full-width.
    """
    full_sorted = sorted(full_width, key=lambda s: s.bbox[1])
    left_sorted = sorted(left, key=lambda s: (s.bbox[1], s.bbox[0]))
    right_sorted = sorted(right, key=lambda s: (s.bbox[1], s.bbox[0]))

    result: list[TextSpan] = []
    y_prev = float("-inf")

    def emit_band(y_lo: float, y_hi: float) -> None:
        band_left = [s for s in left_sorted if y_lo <= s.bbox[1] < y_hi]
        band_right = [s for s in right_sorted if y_lo <= s.bbox[1] < y_hi]
        result.extend(band_left)
        result.extend(band_right)

    for fw in full_sorted:
        emit_band(y_prev, fw.bbox[1])
        result.append(fw)
        y_prev = fw.bbox[1]

    # Última banda (después del último full-width, o toda la página si no hubo).
    emit_band(y_prev, float("inf"))

    return result


def order_pages(
    pages: dict[int, list[TextSpan]],
    page_widths: dict[int, float],
) -> dict[int, list[TextSpan]]:
    """Aplica detect_columns a cada página y devuelve los spans ordenados."""
    ordered: dict[int, list[TextSpan]] = {}
    for page_num, spans in pages.items():
        width = page_widths.get(page_num)
        if width is None:
            width = max((s.bbox[2] for s in spans), default=1.0)
        ordered[page_num] = detect_columns(spans, width)
    return ordered
