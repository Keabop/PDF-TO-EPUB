"""Fase 3 — Orden de lectura.

Se apoya en el orden de bloques nativo de PyMuPDF (`get_text` devuelve los
bloques ya en orden de lectura: cuerpo primero, notas al margen después),
capturado en `TextSpan.block_index`. En vez de re-ordenar spans por (y, x)
—lo que entremezclaba el cuerpo con las barras laterales/citas al margen—,
respetamos ese orden y sólo separamos el material de margen para que no quede
cortando el hilo del texto principal.
"""

from collections import defaultdict

from .models import TextSpan


def _block_bbox(spans: list[TextSpan]) -> tuple[float, float, float, float]:
    x0 = min(s.bbox[0] for s in spans)
    y0 = min(s.bbox[1] for s in spans)
    x1 = max(s.bbox[2] for s in spans)
    y1 = max(s.bbox[3] for s in spans)
    return x0, y0, x1, y1


def _main_left_edge(blocks: list[list[TextSpan]], page_width: float) -> float:
    """Estima el borde izquierdo de la columna principal del cuerpo: el x0 más
    frecuente entre los bloques anchos (los párrafos del cuerpo)."""
    counter: dict[int, int] = defaultdict(int)
    for spans in blocks:
        x0, _, x1, _ = _block_bbox(spans)
        if (x1 - x0) < page_width * 0.20:
            continue  # bloque angosto: probablemente margen, no cuenta
        counter[round(x0 / 10) * 10] += len(spans)
    if not counter:
        return 0.0
    return float(max(counter.items(), key=lambda kv: kv[1])[0])


def order_page(spans: list[TextSpan], page_width: float) -> list[TextSpan]:
    """Devuelve los spans de una página en orden de lectura, con el material de
    margen (barras laterales, citas) desplazado al final para no cortar el
    cuerpo. Preserva el orden nativo de bloques dentro de cada grupo."""
    if not spans:
        return []

    # Agrupa por bloque conservando el orden nativo (block_index).
    blocks: dict[int, list[TextSpan]] = defaultdict(list)
    for s in spans:
        blocks[s.block_index].append(s)
    ordered_blocks = [blocks[i] for i in sorted(blocks.keys())]

    main_left = _main_left_edge(ordered_blocks, page_width)
    # Tolerancia: un bloque es "de margen" si empieza claramente a la izquierda
    # del cuerpo y es angosto (nota lateral), o si cae en el margen derecho.
    left_threshold = main_left - 25
    body: list[list[TextSpan]] = []
    asides: list[list[TextSpan]] = []
    for spans_b in ordered_blocks:
        x0, _, x1, _ = _block_bbox(spans_b)
        width = x1 - x0
        is_narrow = width < page_width * 0.28
        starts_left_of_body = x0 < left_threshold
        if main_left > 0 and is_narrow and starts_left_of_body:
            asides.append(spans_b)
        else:
            body.append(spans_b)

    result: list[TextSpan] = []
    for spans_b in body + asides:
        result.extend(spans_b)
    # Marca la posición final de lectura de cada span dentro de la página.
    for i, s in enumerate(result):
        s.read_order = i
    return result


def order_pages(
    pages: dict[int, list[TextSpan]],
    page_widths: dict[int, float],
) -> dict[int, list[TextSpan]]:
    """Aplica order_page a cada página."""
    ordered: dict[int, list[TextSpan]] = {}
    for page_num, spans in pages.items():
        width = page_widths.get(page_num)
        if width is None:
            width = max((s.bbox[2] for s in spans), default=1.0)
        ordered[page_num] = order_page(spans, width)
    return ordered
