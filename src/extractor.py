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

        for block in raw["blocks"]:
            if block.get("type") != 0:  # 0 = texto, 1 = imagen
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"]
                    if not text.strip():
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
                        )
                    )

        pages[page_num] = spans

    doc.close()
    return pages


def open_document(pdf_path: str) -> pymupdf.Document:
    """Abre el documento para que otras fases (visuals) puedan rasterizar
    páginas y buscar imágenes/tablas sin reabrir el archivo."""
    return pymupdf.open(pdf_path)
