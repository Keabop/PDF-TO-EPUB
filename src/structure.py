"""Fase 4 — Jerarquía de títulos, párrafos y capítulos.

Clusteriza las líneas por (tamaño de fuente, negrita) en todo el documento.
Los tamaños más grandes y menos frecuentes son headings; el más frecuente es
el cuerpo. Con eso arma Chapters y fusiona líneas del cuerpo en párrafos.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Optional

from .models import Block, Chapter, Document, TextSpan

_LINE_TOLERANCE = 3.0       # agrupar spans en una línea (misma y0 aprox.)
_SIZE_EPSILON = 0.6         # diferencia mínima de tamaño para ser heading
# Un salto vertical mayor a este múltiplo de la altura de línea abre párrafo.
_PARAGRAPH_GAP_FACTOR = 0.6


@dataclass
class _Line:
    text: str
    font_size: float
    is_bold: bool
    page_num: int
    y0: float
    y1: float


def _merge_spans_into_lines(spans: list[TextSpan]) -> list[_Line]:
    """Agrupa spans consecutivos (ya en orden de lectura) que pertenecen a la
    misma línea física: misma página, misma columna y y0 cercana."""
    lines: list[_Line] = []
    buffer: list[TextSpan] = []

    def flush() -> None:
        if not buffer:
            return
        text = "".join(s.text for s in buffer).strip()
        if text:
            # Tamaño/negrita dominantes ponderados por longitud de texto.
            size = _dominant([(s.font_size, len(s.text)) for s in buffer])
            bold_chars = sum(len(s.text) for s in buffer if s.is_bold)
            total_chars = sum(len(s.text) for s in buffer)
            lines.append(
                _Line(
                    text=text,
                    font_size=size,
                    is_bold=bold_chars >= total_chars / 2,
                    page_num=buffer[0].page_num,
                    y0=min(s.bbox[1] for s in buffer),
                    y1=max(s.bbox[3] for s in buffer),
                )
            )
        buffer.clear()

    prev: Optional[TextSpan] = None
    for span in spans:
        if prev is not None:
            same_line = (
                span.page_num == prev.page_num
                and span.column_index == prev.column_index
                and abs(span.bbox[1] - prev.bbox[1]) <= _LINE_TOLERANCE
            )
            if not same_line:
                flush()
        buffer.append(span)
        prev = span
    flush()
    return lines


def _dominant(weighted: list[tuple[float, int]]) -> float:
    counter: Counter = Counter()
    for value, weight in weighted:
        counter[value] += weight
    return counter.most_common(1)[0][0]


def _body_font_size(lines: list[_Line]) -> float:
    counter: Counter = Counter()
    for line in lines:
        counter[round(line.font_size, 1)] += len(line.text)
    if not counter:
        return 10.0
    return counter.most_common(1)[0][0]


def _heading_level_map(
    lines: list[_Line], body_size: float
) -> dict[float, int]:
    """Mapea cada tamaño de heading (> body) a un nivel: el más grande = 1."""
    heading_sizes = sorted(
        {
            round(line.font_size, 1)
            for line in lines
            if line.font_size >= body_size + _SIZE_EPSILON
        },
        reverse=True,
    )
    return {size: idx + 1 for idx, size in enumerate(heading_sizes)}


def _classify(
    line: _Line, body_size: float, level_map: dict[float, int]
) -> tuple[str, Optional[int]]:
    size = round(line.font_size, 1)
    if size in level_map:
        return "heading", level_map[size]
    # Línea corta en negrita al tamaño del cuerpo: subtítulo del nivel más bajo.
    if line.is_bold and len(line.text) < 80 and line.text[-1:] not in ".:;,":
        deepest = (max(level_map.values()) + 1) if level_map else 2
        return "heading", deepest
    return "paragraph", None


def _dehyphenate_join(acc: str, nxt: str) -> str:
    """Une dos líneas del mismo párrafo, resolviendo guiones de corte."""
    if acc.endswith("-") and not acc.endswith((" -", "--")):
        return acc[:-1] + nxt
    if not acc:
        return nxt
    return acc + " " + nxt


def _lines_to_paragraphs(lines: list[_Line]) -> list[str]:
    """Fusiona líneas de cuerpo consecutivas en párrafos, abriendo uno nuevo
    ante un salto vertical grande o un cambio de página."""
    if not lines:
        return []
    heights = [l.y1 - l.y0 for l in lines if l.y1 > l.y0]
    median_h = sorted(heights)[len(heights) // 2] if heights else 12.0

    paragraphs: list[str] = []
    current = ""
    prev: Optional[_Line] = None
    for line in lines:
        if prev is not None:
            gap = line.y0 - prev.y1
            new_para = (
                line.page_num != prev.page_num
                or gap > median_h * _PARAGRAPH_GAP_FACTOR
            )
            if new_para:
                paragraphs.append(current)
                current = ""
        current = _dehyphenate_join(current, line.text)
        prev = line
    if current:
        paragraphs.append(current)
    return [p for p in paragraphs if p.strip()]


def build_document_tree(
    ordered_spans: list[TextSpan],
    title: str = "Documento",
    visual_blocks: Optional[list[Block]] = None,
) -> Document:
    """Clusteriza por (font_size, is_bold), arma Chapters y fusiona líneas
    del cuerpo en Blocks kind='paragraph'. Los `visual_blocks` (figuras,
    fórmulas, tablas) se intercalan por su posición (page_num, y0)."""
    lines = _merge_spans_into_lines(ordered_spans)
    body_size = _body_font_size(lines)
    level_map = _heading_level_map(lines, body_size)

    # Construye una secuencia unificada de "items" con posición, para poder
    # intercalar texto y visuales en orden de lectura.
    items: list[tuple[int, float, str, object]] = []

    # Agrupa líneas de cuerpo consecutivas para convertirlas en párrafos,
    # emitiendo headings como puntos de corte.
    body_run: list[_Line] = []

    def flush_body() -> None:
        for para in _lines_to_paragraphs(body_run):
            first = body_run[0]
            items.append((first.page_num, first.y0, "paragraph", para))
        body_run.clear()

    for line in lines:
        kind, level = _classify(line, body_size, level_map)
        if kind == "heading":
            flush_body()
            items.append((line.page_num, line.y0, "heading", (line.text, level)))
        else:
            if body_run and (
                body_run[-1].page_num != line.page_num
                or line.y0 - body_run[-1].y1 > (line.y1 - line.y0) * 3
            ):
                flush_body()
            body_run.append(line)
    flush_body()

    for vb in visual_blocks or []:
        items.append((vb.page_num, vb.y0, "visual", vb))

    items.sort(key=lambda it: (it[0], it[1]))

    return _assemble_chapters(items, title)


def _assemble_chapters(
    items: list[tuple[int, float, str, object]], title: str
) -> Document:
    """Recorre los items en orden y los reparte en capítulos: cada heading de
    nivel 1 abre un capítulo nuevo; lo anterior al primer nivel-1 va a un
    capítulo inicial con el título del documento."""
    document = Document(title=title)
    current = Chapter(title=title)  # capítulo inicial (frontmatter / intro)
    order = 0

    for page_num, y0, kind, payload in items:
        if kind == "heading" and payload[1] == 1:  # type: ignore[index]
            if current.blocks:
                document.chapters.append(current)
            current = Chapter(title=payload[0])  # type: ignore[index]
            order = 0
            continue

        if kind == "heading":
            text, level = payload  # type: ignore[misc]
            block = Block(
                kind="heading",
                order_index=order,
                page_num=page_num,
                level=level,
                text=text,
                y0=y0,
            )
        elif kind == "paragraph":
            block = Block(
                kind="paragraph",
                order_index=order,
                page_num=page_num,
                text=payload,  # type: ignore[arg-type]
                y0=y0,
            )
        else:  # visual: el Block ya viene armado por visuals.py
            block = payload  # type: ignore[assignment]
            block.order_index = order

        current.blocks.append(block)
        order += 1

    if current.blocks:
        document.chapters.append(current)

    document.chapters = [c for c in document.chapters if c.blocks]
    if not document.chapters:
        document.chapters = [Chapter(title=title)]
    return document
