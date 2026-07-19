"""Fase 4 — Jerarquía de títulos, párrafos y capítulos.

Fuente de la estructura, en orden de preferencia:

1. El índice/marcadores embebidos del PDF (`outline`). Es lo más confiable en
   libros académicos: da títulos y niveles reales de capítulos y secciones.
2. Si el PDF no trae marcadores, se cae al heurístico de tamaño de fuente:
   clusteriza las líneas por (tamaño, negrita) y toma los tamaños más grandes
   y menos frecuentes como headings.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

from .models import Block, Chapter, Document, TextSpan

_LINE_TOLERANCE = 3.0       # agrupar spans en una línea (misma y0 aprox.)
_SIZE_EPSILON = 0.6         # diferencia mínima de tamaño para ser heading
# Un salto vertical mayor a este múltiplo de la altura de línea abre párrafo.
_PARAGRAPH_GAP_FACTOR = 0.6
# Un x0 mayor al margen del cuerpo + esto = primera línea sangrada = párrafo
# nuevo; menor al margen - esto = línea "afuera" (nota al margen, título).
_INDENT_THRESHOLD = 6.0
_OUTDENT_THRESHOLD = 10.0


def _body_left_by_page(lines: list["_Line"]) -> dict[int, float]:
    """Margen izquierdo del cuerpo por página: el x0 más frecuente entre las
    líneas (las líneas de continuación, que son mayoría). Sirve para detectar
    la sangría de primera línea que marca inicio de párrafo."""
    by_page: dict[int, Counter] = defaultdict(Counter)
    for line in lines:
        by_page[line.page_num][round(line.x0)] += 1
    return {
        pg: float(counter.most_common(1)[0][0])
        for pg, counter in by_page.items()
    }


def _starts_paragraph(
    line: "_Line", prev: Optional["_Line"], body_left: dict[int, float]
) -> bool:
    """Decide si `line` inicia un párrafo nuevo respecto de `prev`, usando
    sangría de primera línea, cambio de página y salto vertical."""
    if prev is None:
        return True
    if line.page_num != prev.page_num:
        return True
    left = body_left.get(line.page_num, line.x0)
    if line.x0 >= left + _INDENT_THRESHOLD:   # primera línea sangrada
        return True
    if line.x0 <= left - _OUTDENT_THRESHOLD:  # afuera del cuerpo (aside/título)
        return True
    line_h = max(line.y1 - line.y0, 1.0)
    if (line.y0 - prev.y1) > line_h * _PARAGRAPH_GAP_FACTOR:
        return True
    return False


@dataclass
class _Line:
    text: str
    font_size: float
    is_bold: bool
    page_num: int
    x0: float
    y0: float
    y1: float
    block_index: int
    read_order: int
    is_aside: bool


def _merge_spans_into_lines(spans: list[TextSpan]) -> list[_Line]:
    """Agrupa spans consecutivos (ya en orden de lectura) que pertenecen a la
    misma línea física: mismo bloque, misma página y y0 cercana."""
    lines: list[_Line] = []
    buffer: list[TextSpan] = []

    def flush() -> None:
        if not buffer:
            return
        # Colapsa espacios repetidos (quedan al conservar spans de sólo-espacio).
        text = re.sub(r"\s+", " ", "".join(s.text for s in buffer)).strip()
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
                    x0=min(s.bbox[0] for s in buffer),
                    y0=min(s.bbox[1] for s in buffer),
                    y1=max(s.bbox[3] for s in buffer),
                    block_index=buffer[0].block_index,
                    read_order=min(s.read_order for s in buffer),
                    is_aside=buffer[0].is_aside,
                )
            )
        buffer.clear()

    prev: Optional[TextSpan] = None
    for span in spans:
        if prev is not None:
            same_line = (
                span.page_num == prev.page_num
                and span.block_index == prev.block_index
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


# Subtítulo numerado: "1.1 …", "1.1.1 …" (al menos un punto entre números).
_SECTION_NUM_RE = re.compile(r"^(\d+(?:\.\d+)+)\b")


def _subheading_level(line: "_Line", body_size: float) -> Optional[int]:
    """Detecta subtítulos de sección DENTRO de un capítulo (los que no vienen
    en el outline). Devuelve el nivel (2, 3, …) o None.

    Señal principal: numeración "1.1"/"1.1.1" + fuente más grande que el
    cuerpo (así se descarta un cruce como "1.3, cualquier enfoque…", que va en
    tamaño de cuerpo). El nivel sale de la profundidad de la numeración."""
    if line.is_aside:
        return None
    text = line.text.strip()
    m = _SECTION_NUM_RE.match(text)
    if m and line.font_size >= body_size + 1.0:
        depth = m.group(1).count(".") + 1  # "1.1"->2, "1.1.1"->3
        return min(max(depth, 2), 4)
    return None


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


_HYPHENS = ("-", "­", "‐")  # guion normal, blando, unicode


def _dehyphenate_join(acc: str, nxt: str) -> str:
    """Une dos líneas del mismo párrafo, resolviendo guiones de corte."""
    if not acc:
        return nxt.lstrip()
    stripped = acc.rstrip()
    # Guion de corte de palabra (no un guion suelto tipo " -" ni "--").
    if (
        stripped
        and stripped[-1] in _HYPHENS
        and not stripped.endswith((" -", "--"))
    ):
        return stripped[:-1] + nxt.lstrip()
    return acc + " " + nxt


def build_document_tree(
    ordered_spans: list[TextSpan],
    title: str = "Documento",
    visual_blocks: Optional[list[Block]] = None,
    outline: Optional[list[tuple[int, str, int]]] = None,
) -> Document:
    """Arma el árbol del documento. Si el PDF trae `outline` (marcadores),
    se usa como fuente autoritativa de capítulos/secciones; si no, se cae al
    heurístico de tamaño de fuente. Los `visual_blocks` se intercalan por su
    posición (page_num, y0)."""
    if outline:
        return _build_from_outline(
            ordered_spans, outline, title, visual_blocks or []
        )
    return _build_from_font_sizes(ordered_spans, title, visual_blocks)


def _build_from_font_sizes(
    ordered_spans: list[TextSpan],
    title: str,
    visual_blocks: Optional[list[Block]],
) -> Document:
    """Heurístico de respaldo: infiere headings por tamaño de fuente."""
    lines = _merge_spans_into_lines(ordered_spans)
    body_size = _body_font_size(lines)
    level_map = _heading_level_map(lines, body_size)

    # Construye una secuencia unificada de "items" con posición, para poder
    # intercalar texto y visuales en orden de lectura.
    items: list[tuple[int, float, str, object]] = []

    # Agrupa líneas de cuerpo consecutivas para convertirlas en párrafos,
    # emitiendo headings como puntos de corte.
    body_run: list[_Line] = []

    lines_by_page: dict[int, list[_Line]] = defaultdict(list)
    for line in lines:
        lines_by_page[line.page_num].append(line)
    for page_lines in lines_by_page.values():
        page_lines.sort(key=lambda l: l.y0)

    def flush_body() -> None:
        items.extend(_paragraph_items(body_run))
        body_run.clear()

    for line in lines:
        kind, level = _classify(line, body_size, level_map)
        if kind == "heading":
            flush_body()
            items.append(
                (line.page_num, float(line.read_order), "heading", (line.text, level))
            )
        else:
            body_run.append(line)
    flush_body()

    for vb in visual_blocks or []:
        order = _visual_order_key(vb.page_num, vb.y0, lines_by_page)
        items.append((vb.page_num, order, "visual", vb))

    items.sort(key=lambda it: (it[0], it[1]))

    return _assemble_chapters(items, title)


def _assemble_chapters(
    items: list[tuple[int, float, str, object]],
    title: str,
    top_level: int = 1,
) -> Document:
    """Recorre los items en orden y los reparte en capítulos: cada heading del
    nivel superior (`top_level`) abre un capítulo nuevo; lo anterior al primero
    va a un capítulo inicial con el título del documento. Los headings de nivel
    más profundo quedan como bloques dentro del capítulo."""
    document = Document(title=title)
    current = Chapter(title=title)  # capítulo inicial (frontmatter / intro)
    order = 0

    for page_num, y0, kind, payload in items:
        if kind == "heading" and payload[1] <= top_level:  # type: ignore[index]
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
        elif kind in ("paragraph", "aside"):
            block = Block(
                kind=kind,  # type: ignore[arg-type]
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


# --------------------------------------------------------------------------- #
# Construcción a partir del outline embebido (fuente autoritativa)
# --------------------------------------------------------------------------- #

def _norm(text: str) -> str:
    """Normaliza para comparar títulos: minúsculas y solo alfanuméricos."""
    return re.sub(r"[^0-9a-záéíóúñü]", "", text.lower())


def _paragraph_items(
    lines: list[_Line],
    body_size: Optional[float] = None,
) -> list[tuple[int, float, str, object]]:
    """Convierte líneas en items de contenido:

    - Cuerpo: párrafos reconstruidos por sangría de primera línea / saltos.
    - Subtítulos: si se pasa `body_size`, las líneas que parecen subtítulos de
      sección ("1.1 …", "1.1.1 …" en fuente mayor) se emiten como 'heading'.
    - Margen (is_aside): todas las líneas de margen contiguas de una página se
      agrupan en UN solo bloque 'aside' (recuadro), para no quedar fragmentadas.

    Cada item lleva su clave de orden de lectura (page, read_order)."""
    items: list[tuple[int, float, str, object]] = []
    if not lines:
        return items
    body_left = _body_left_by_page(lines)

    cur_text = ""
    cur_page: Optional[int] = None
    cur_order: Optional[float] = None
    prev: Optional[_Line] = None

    aside_buf: list[_Line] = []

    def flush_body() -> None:
        nonlocal cur_text, prev
        if cur_text.strip() and cur_page is not None:
            items.append((cur_page, cur_order, "paragraph", cur_text))
        cur_text = ""
        prev = None

    def flush_aside() -> None:
        if not aside_buf:
            return
        text = ""
        for l in aside_buf:
            if l.text.strip():
                text = _dehyphenate_join(text, l.text.strip())
        if text:
            items.append(
                (aside_buf[0].page_num, aside_buf[0].read_order, "aside", text)
            )
        aside_buf.clear()

    for line in lines:
        if line.is_aside:
            flush_body()
            if aside_buf and aside_buf[-1].page_num != line.page_num:
                flush_aside()
            aside_buf.append(line)
            continue

        flush_aside()

        # ¿Es un subtítulo de sección dentro del capítulo?
        level = (
            _subheading_level(line, body_size)
            if body_size is not None
            else None
        )
        if level is not None:
            flush_body()
            items.append(
                (line.page_num, float(line.read_order), "heading",
                 (line.text.strip(), level))
            )
            continue

        if _starts_paragraph(line, prev, body_left):
            flush_body()
        if not cur_text:
            cur_page, cur_order = line.page_num, line.read_order
        cur_text = _dehyphenate_join(cur_text, line.text)
        prev = line

    flush_body()
    flush_aside()
    return items


def _match_heading_line(
    htitle: str, page: int, by_page: dict[int, list[_Line]], consumed: set[int]
) -> Optional[tuple[int, float]]:
    """Busca la línea del cuerpo que corresponde a un título del outline (en su
    página o la siguiente) para ubicar el heading con precisión y evitar que el
    título se duplique como párrafo. Devuelve (page, read_order) o None."""
    tnorm = _norm(htitle)
    if len(tnorm) < 4:
        return None
    prefix = tnorm[:14]
    for pg in (page, page + 1):
        for line in by_page.get(pg, []):
            if id(line) in consumed:
                continue
            lnorm = _norm(line.text)
            if not lnorm:
                continue
            if lnorm.startswith(prefix) or prefix in lnorm:
                consumed.add(id(line))
                return pg, float(line.read_order)
    return None


def _visual_order_key(
    page: int, y0: float, lines_by_page: dict[int, list[_Line]]
) -> float:
    """Ubica un visual (figura/tabla) en el flujo de lectura de su página: toma
    el read_order de la última línea del cuerpo que esté por encima del visual.
    Así la imagen cae junto al párrafo que la precede, no al final."""
    candidates = [
        l for l in lines_by_page.get(page, []) if l.y0 <= y0
    ]
    if not candidates:
        return -0.5  # antes del cuerpo de la página
    return max(l.read_order for l in candidates) + 0.5


def _build_from_outline(
    ordered_spans: list[TextSpan],
    outline: list[tuple[int, str, int]],
    title: str,
    visual_blocks: list[Block],
) -> Document:
    lines = _merge_spans_into_lines(ordered_spans)
    by_page: dict[int, list[_Line]] = defaultdict(list)
    for line in lines:
        by_page[line.page_num].append(line)
    for page_lines in by_page.values():
        page_lines.sort(key=lambda l: l.y0)

    top_level = min(level for level, _, _ in outline)
    body_size = _body_font_size(lines)
    consumed: set[int] = set()
    items: list[tuple[int, float, str, object]] = []

    for level, htitle, page in outline:
        match = _match_heading_line(htitle, page, by_page, consumed)
        if match is not None:
            pg, order = match
        else:
            # Sin coincidencia: ubicar al tope de su página.
            pg, order = page, -1.0
        items.append((pg, order, "heading", (htitle, level)))

    body_lines = [line for line in lines if id(line) not in consumed]
    # Detecta subtítulos de sección (1.1, 1.1.1…) no incluidos en el outline.
    items.extend(_paragraph_items(body_lines, body_size=body_size))

    for vb in visual_blocks:
        order = _visual_order_key(vb.page_num, vb.y0, by_page)
        items.append((vb.page_num, order, "visual", vb))

    items.sort(key=lambda it: (it[0], it[1]))
    return _assemble_chapters(items, title, top_level)
