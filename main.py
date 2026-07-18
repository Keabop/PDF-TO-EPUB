"""CLI: orquesta las fases del pipeline PDF -> EPUB en orden.

Uso:
    python main.py --input samples/documento.pdf --output output/documento.epub
"""

import argparse
import os
import sys

from src.denoise import strip_boilerplate
from src.epub_builder import build_epub
from src.extractor import extract_outline, extract_raw_spans, open_document
from src.imaging import DEFAULT_PRESET, PRESETS, get_settings
from src.layout import order_pages
from src.structure import build_document_tree
from src.visuals import extract_visuals


def _document_title(pdf_path: str, doc) -> str:
    meta_title = (doc.metadata or {}).get("title") if doc else None
    if meta_title and meta_title.strip():
        return meta_title.strip()
    return os.path.splitext(os.path.basename(pdf_path))[0]


def default_output_path(pdf_path: str) -> str:
    """Deriva la ruta del EPUB: mismo nombre y carpeta que el PDF, extensión
    .epub. Sirve para la GUI, donde el usuario solo elige el PDF."""
    base = os.path.splitext(pdf_path)[0]
    return base + ".epub"


def convert(
    pdf_path: str,
    output_path: str,
    image_dir: str,
    verbose: bool = True,
    on_log=None,
    image_preset: str = DEFAULT_PRESET,
    formulas_as_images: bool = False,
):
    def log(msg: str) -> None:
        if verbose:
            print(msg, file=sys.stderr)
        if on_log is not None:
            on_log(msg)

    settings = get_settings(image_preset)

    # --- Fase 1: extracción cruda ---
    log("· Fase 1: extrayendo spans de texto…")
    pages = extract_raw_spans(pdf_path)
    log(f"  {sum(len(v) for v in pages.values())} spans en {len(pages)} páginas")

    doc = open_document(pdf_path)
    page_widths = {i: doc[i].rect.width for i in range(len(doc))}
    page_heights = {i: doc[i].rect.height for i in range(len(doc))}
    title = _document_title(pdf_path, doc)
    outline = extract_outline(doc)
    if outline:
        log(f"  índice embebido: {len(outline)} entradas")

    # --- Fase 2: filtrado de ruido ---
    log("· Fase 2: quitando headers/footers/paginación…")
    before = sum(len(v) for v in pages.values())
    pages = strip_boilerplate(pages, page_heights)
    after = sum(len(v) for v in pages.values())
    log(f"  {before - after} spans de boilerplate eliminados")

    # --- Fase 5 (visuales) por página: se hace antes de ordenar el texto para
    #     poder marcar los spans consumidos (captions, fórmulas) ---
    log(f"· Fase 5: detectando figuras, fórmulas y tablas… (imágenes: {image_preset})")
    visual_blocks = []
    total_pages = len(doc)
    for page_index in range(total_pages):
        page = doc[page_index]
        spans = pages.get(page_index, [])
        blocks, consumed = extract_visuals(
            page, spans, image_dir, page_index, settings,
            detect_formulas=formulas_as_images,
        )
        visual_blocks.extend(blocks)
        # Progreso por página: útil en documentos largos (500+ págs).
        if total_pages >= 50 and (page_index + 1) % 25 == 0:
            log(f"    página {page_index + 1}/{total_pages}")
        # Quita del texto los spans ya representados como visual (captions/eqs).
        pages[page_index] = [s for s in spans if id(s) not in consumed]
    log(f"  {len(visual_blocks)} bloques visuales")

    # --- Fase 3: columnas y orden de lectura ---
    log("· Fase 3: detectando columnas y orden de lectura…")
    ordered = order_pages(pages, page_widths)
    ordered_spans = []
    for page_index in sorted(ordered.keys()):
        ordered_spans.extend(ordered[page_index])

    # --- Fase 4: jerarquía de títulos y capítulos ---
    fuente = "índice embebido" if outline else "tamaño de fuente"
    log(f"· Fase 4: construyendo jerarquía de capítulos… (fuente: {fuente})")
    document = build_document_tree(
        ordered_spans, title=title, visual_blocks=visual_blocks, outline=outline
    )
    log(f"  {len(document.chapters)} capítulos")

    doc.close()

    # --- Fase 6: generación del EPUB ---
    log("· Fase 6: generando EPUB…")
    build_epub(document, output_path)
    log(f"✓ EPUB generado en {output_path}")
    return document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Convierte un PDF académico en un EPUB reflowable para Kindle."
    )
    parser.add_argument("--input", "-i", required=True, help="PDF de entrada")
    parser.add_argument("--output", "-o", required=True, help="EPUB de salida")
    parser.add_argument(
        "--image-dir",
        default=None,
        help="Carpeta para los recortes de figuras/fórmulas "
        "(por defecto: <dir-de-salida>/images)",
    )
    parser.add_argument(
        "--images",
        choices=list(PRESETS.keys()),
        default=DEFAULT_PRESET,
        help="Preset de compresión de imágenes: 'equilibrado' (recomendado), "
        "'calidad' (más nítido, más pesado) o 'minimo' (archivo más chico, "
        "escala de grises). Por defecto: %(default)s",
    )
    parser.add_argument(
        "--formulas-as-images",
        action="store_true",
        help="Recorta fórmulas como imágenes (heurístico poco fiable, puede "
        "convertir texto normal en imagen). Desactivado por defecto: las "
        "fórmulas quedan como texto.",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Sin logs")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"error: no existe el PDF de entrada: {args.input}", file=sys.stderr)
        return 2

    image_dir = args.image_dir or os.path.join(
        os.path.dirname(os.path.abspath(args.output)), "images"
    )

    convert(
        args.input,
        args.output,
        image_dir,
        verbose=not args.quiet,
        image_preset=args.images,
        formulas_as_images=args.formulas_as_images,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
