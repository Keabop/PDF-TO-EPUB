"""Fase 6 — Generación del EPUB con ebooklib.

Un EpubHtml por capítulo, CSS con unidades relativas (em/%, nunca px),
EpubNcx + EpubNav para el TOC, y EpubImage por cada figura/fórmula.
"""

import os
import unicodedata
from html import escape

from ebooklib import epub

from .models import Block, Chapter, Document

_CSS = """
body {
    font-family: serif;
    line-height: 1.5;
    margin: 0 5%;
}
h1, h2, h3, h4 {
    font-family: sans-serif;
    line-height: 1.25;
    margin: 1em 0 0.5em;
    page-break-after: avoid;
}
h1 { font-size: 1.6em; }
h2 { font-size: 1.35em; }
h3 { font-size: 1.15em; }
h4 { font-size: 1.05em; }
p {
    margin: 0 0 0.6em;
    text-align: justify;
    text-indent: 1.2em;
}
p.first, h1 + p, h2 + p, h3 + p { text-indent: 0; }
figure {
    margin: 1em 0;
    text-align: center;
    page-break-inside: avoid;
}
figure img, img.formula, img.figure {
    max-width: 100%;
    height: auto;
}
img.formula {
    display: block;
    margin: 0.8em auto;
}
figcaption {
    font-size: 0.9em;
    font-style: italic;
    margin-top: 0.4em;
    text-align: center;
}
table {
    border-collapse: collapse;
    margin: 1em auto;
    font-size: 0.9em;
    max-width: 100%;
}
th, td {
    border: 1px solid #999;
    padding: 0.3em 0.5em;
    text-align: left;
}
th { background: #eee; }
aside.margin-note {
    display: block;
    margin: 1em 0;
    padding: 0.5em 0.8em;
    border-left: 3px solid #999;
    background: #f2f2f2;
    font-size: 0.9em;
    font-style: italic;
    color: #333;
}
pre.code {
    font-family: monospace;
    font-size: 0.85em;
    line-height: 1.35;
    white-space: pre-wrap;
    word-wrap: break-word;
    margin: 1em 0;
    padding: 0.6em 0.8em;
    background: #f4f4f4;
    border: 1px solid #ddd;
    border-radius: 3px;
    overflow-x: auto;
}
pre.code code { font-family: inherit; }
"""


def _build_toc(chapter_meta):
    """Arma el TOC anidado de ebooklib. Anida los CAPÍTULOS por su nivel de
    outline (parte > capítulo > subsección-que-es-capítulo) y, dentro de cada
    capítulo, sus subtítulos (1.1, 1.1.1…). Devuelve la estructura anidada que
    espera ebooklib (nodo suelto, o (nodo, [hijos]))."""
    root: list = []
    chap_stack: list[tuple[int, list]] = [(0, root)]
    for clevel, item, subs in chapter_meta:
        while len(chap_stack) > 1 and chap_stack[-1][0] >= clevel:
            chap_stack.pop()
        children: list = []
        # Subtítulos internos, anidados entre sí por su propio nivel.
        sub_stack: list[tuple[int, list]] = [(1, children)]
        for slevel, link in subs:
            while len(sub_stack) > 1 and sub_stack[-1][0] >= slevel:
                sub_stack.pop()
            sub_children: list = []
            sub_stack[-1][1].append([link, sub_children])
            sub_stack.append((slevel, sub_children))
        chap_stack[-1][1].append([item, children])
        chap_stack.append((clevel, children))

    def convert(entries: list):
        out = []
        for node, node_children in entries:
            out.append((node, convert(node_children)) if node_children else node)
        return out

    return convert(root)


def _slug(text: str, fallback: str) -> str:
    """Nombre de archivo interno del EPUB: sólo ASCII [a-z0-9-] para máxima
    compatibilidad entre lectores (títulos en cirílico/CJK caen al fallback)."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    keep = "".join(c if c.isalnum() else "-" for c in ascii_text)
    keep = "-".join(filter(None, keep.split("-")))
    return keep[:40] or fallback


def _block_to_html(block: Block, embedded_images: dict[str, str]) -> str:
    if block.kind == "heading":
        level = min(max(block.level or 2, 2), 4)  # h1 se reserva al capítulo
        return f"<h{level}>{escape(block.text or '')}</h{level}>"

    if block.kind == "paragraph":
        return f"<p>{escape(block.text or '')}</p>"

    if block.kind == "aside":
        # Nota al margen (cita, recuadro "Conceptos Clave", etc.): recuadro
        # visualmente separado del cuerpo.
        return f'<aside class="margin-note">{escape(block.text or "")}</aside>'

    if block.kind == "code":
        # Listado de código: monoespaciado, con saltos e indentación preservados.
        return f'<pre class="code"><code>{escape(block.text or "")}</code></pre>'

    if block.kind == "formula" and block.image_path:
        src = embedded_images.get(block.image_path)
        if src:
            return f'<img class="formula" src="{src}" alt="fórmula"/>'
        return ""

    if block.kind == "figure" and block.image_path:
        src = embedded_images.get(block.image_path)
        if not src:
            return ""
        caption = ""
        if block.caption_text:
            caption = f"<figcaption>{escape(block.caption_text)}</figcaption>"
        return (
            f'<figure><img class="figure" src="{src}" alt="figura"/>'
            f"{caption}</figure>"
        )

    if block.kind == "table" and block.html_table:
        caption = ""
        if block.caption_text:
            caption = f"<figcaption>{escape(block.caption_text)}</figcaption>"
        return f"<figure>{block.html_table}{caption}</figure>"

    return ""


def _collect_image_paths(document: Document) -> list[str]:
    paths: list[str] = []
    for chapter in document.chapters:
        for block in chapter.blocks:
            if block.image_path and block.image_path not in paths:
                if os.path.exists(block.image_path):
                    paths.append(block.image_path)
    return paths


def build_epub(document: Document, output_path: str) -> None:
    """Genera el .epub con ebooklib."""
    book = epub.EpubBook()
    book.set_identifier(_slug(document.title, "doc"))
    book.set_title(document.title)
    book.set_language("es")

    # CSS compartido.
    css = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=_CSS,
    )
    book.add_item(css)

    # Imágenes: se registran una vez y se mapea path_local -> ruta interna epub.
    embedded_images: dict[str, str] = {}
    for idx, path in enumerate(_collect_image_paths(document)):
        ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
        internal = f"images/img{idx:04d}.{ext}"
        with open(path, "rb") as fh:
            content = fh.read()
        img_item = epub.EpubImage(
            uid=f"img{idx:04d}",
            file_name=internal,
            media_type=f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}",
            content=content,
        )
        book.add_item(img_item)
        # Referencia relativa desde los XHTML (que viven en la raíz del epub).
        embedded_images[path] = internal

    chapters_html: list[epub.EpubHtml] = []
    # metadatos por capítulo para armar el TOC anidado: (nivel, item, subs)
    chapter_meta: list[tuple[int, epub.EpubHtml, list[tuple[int, epub.Link]]]] = []
    for c_idx, chapter in enumerate(document.chapters):
        file_name = f"chap_{c_idx:03d}_{_slug(chapter.title, str(c_idx))}.xhtml"
        parts = [f"<h1>{escape(chapter.title)}</h1>"]
        sub_headings: list[tuple[int, epub.Link]] = []
        h_count = 0
        for block in chapter.blocks:
            if block.kind == "heading":
                # Subtítulo dentro del capítulo: con ancla para el TOC anidado.
                h_count += 1
                hid = f"h{h_count}"
                level = min(max(block.level or 2, 2), 4)
                parts.append(
                    f'<h{level} id="{hid}">{escape(block.text or "")}</h{level}>'
                )
                sub_headings.append(
                    (
                        level,
                        epub.Link(
                            f"{file_name}#{hid}",
                            block.text or "",
                            f"c{c_idx}_{hid}",
                        ),
                    )
                )
            else:
                html = _block_to_html(block, embedded_images)
                if html:
                    parts.append(html)
        item = epub.EpubHtml(
            title=chapter.title,
            file_name=file_name,
            lang="es",
        )
        item.content = "\n".join(parts)
        item.add_item(css)
        book.add_item(item)
        chapters_html.append(item)
        chapter_meta.append((chapter.level, item, sub_headings))

    # TOC anidado: capítulos jerarquizados por su nivel (parte > capítulo > …),
    # y dentro de cada uno sus subtítulos.
    book.toc = _build_toc(chapter_meta)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters_html]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    epub.write_epub(output_path, book)
