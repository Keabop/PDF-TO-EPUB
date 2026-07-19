"""Fase 1 — Extracción cruda de spans de texto desde el PDF."""

import pymupdf

from .models import TextSpan

# Flags de pymupdf para estilo de fuente (ver pymupdf docs: span["flags"]).
_FLAG_ITALIC = 1 << 1
_FLAG_BOLD = 1 << 4


def _is_bold(span: dict) -> bool:
    if span["flags"] & _FLAG_BOLD:
        return True
    return "bold" in span["font"].lower()


def _is_italic(span: dict) -> bool:
    if span["flags"] & _FLAG_ITALIC:
        return True
    font = span["font"].lower()
    return "italic" in font or "oblique" in font


def extract_raw_spans(pdf_path: str) -> dict[int, list[TextSpan]]:
    """Usa page.get_text('dict')['blocks'] para sacar todos los spans
    de texto de cada página, con bbox/font/size/bold/italic."""
    doc = pymupdf.open(pdf_path)
    pages: dict[int, list[TextSpan]] = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        raw = page.get_text("dict")
        spans: list[TextSpan] = []

        block_index = 0
        for block in raw["blocks"]:
            if block.get("type") != 0:  # 0 = texto, 1 = imagen
                continue
            # El orden de `raw["blocks"]` es el orden de lectura nativo de
            # PyMuPDF (cuerpo primero, notas al margen después); lo preservamos
            # en block_index para respetarlo aguas abajo.
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"]
                    # Se conservan los spans de sólo-espacio: en títulos con
                    # tracking (letras espaciadas) el espacio entre palabras
                    # viene como span aparte; descartarlo pega las palabras
                    # ("LA NATURALEZA" -> "LANATURALEZA").
                    if text == "":
                        continue
                    spans.append(
                        TextSpan(
                            text=text,
                            bbox=tuple(span["bbox"]),
                            font_size=round(span["size"], 1),
                            font_name=span["font"],
                            is_bold=_is_bold(span),
                            is_italic=_is_italic(span),
                            page_num=page_num,
                            block_index=block_index,
                        )
                    )
            block_index += 1

        pages[page_num] = spans

    doc.close()
    return pages


def open_document(pdf_path: str) -> pymupdf.Document:
    """Abre el documento para que otras fases (visuals) puedan rasterizar
    páginas y buscar imágenes/tablas sin reabrir el archivo."""
    return pymupdf.open(pdf_path)


def extract_outline(doc: pymupdf.Document) -> list[tuple[int, str, int]]:
    """Devuelve el índice/marcadores embebidos del PDF como
    (nivel, título, page_index_0based). Es la fuente MÁS confiable para el
    TOC de un libro académico; vacío si el PDF no trae marcadores."""
    outline: list[tuple[int, str, int]] = []
    try:
        toc = doc.get_toc(simple=True)  # [ [level, title, page_1based], ... ]
    except Exception:
        return outline
    for entry in toc:
        if len(entry) < 3:
            continue
        level, title, page = entry[0], entry[1], entry[2]
        title = (title or "").strip()
        if not title or page is None or page < 1:
            continue
        outline.append((int(level), title, int(page) - 1))
    return outline
