"""Dataclasses shared across the pipeline phases."""

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class TextSpan:
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    font_size: float
    font_name: str
    is_bold: bool
    is_italic: bool
    page_num: int
    column_index: int = 0
    block_index: int = 0   # índice del bloque en el orden de lectura nativo
    #                        de PyMuPDF (cada bloque ≈ un párrafo)
    read_order: int = 0    # posición final dentro de la página tras ordenar
    #                        (cuerpo primero, notas al margen al final)


@dataclass
class Block:
    kind: Literal["heading", "paragraph", "figure", "formula", "table", "caption"]
    order_index: int
    page_num: int
    level: Optional[int] = None        # solo headings: 1=capítulo, 2=sección...
    text: Optional[str] = None         # heading / paragraph / caption
    image_path: Optional[str] = None   # figure / formula
    html_table: Optional[str] = None   # table (HTML ya armado)
    caption_text: Optional[str] = None
    y0: float = 0.0                    # posición vertical en la página (interno,
    #                                    solo para intercalar bloques en orden)


@dataclass
class Chapter:
    title: str
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Document:
    title: str
    chapters: list[Chapter] = field(default_factory=list)
