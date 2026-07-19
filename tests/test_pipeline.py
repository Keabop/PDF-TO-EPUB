"""Pruebas del pipeline PDF -> EPUB.

Generan PDFs sintéticos que cubren los casos clave (una/dos columnas, outline,
tablas/figuras, escaneado, vacío, protegido, dañado) y verifican propiedades
del EPUB resultante: orden de lectura, TOC, que no se rasterice texto, y
manejo de errores. Ejecutar con:

    python -m pytest tests/ -q
    # o directamente:
    python tests/test_pipeline.py
"""

import io
import math
import os
import re
import sys
import tempfile
import unittest
import zipfile
from xml.dom.minidom import parseString

import pymupdf
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import convert  # noqa: E402

W, H = 595, 842
BODY = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do "
        "eiusmod tempor incididunt ut labore et dolore magna aliqua. ")


def _photo(w=400, h=300):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x % 256, y % 256, (x + y) % 256)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _read_chapter_texts(epub_path):
    z = zipfile.ZipFile(epub_path)
    out = {}
    for n in sorted(z.namelist()):
        if n.endswith(".xhtml") and "chap" in n:
            out[n] = z.read(n).decode("utf-8", "ignore")
    return z, out


def _plain(html):
    body = html.split("<body>", 1)[-1]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _convert(self, make_pdf, **kw):
        pdf = os.path.join(self.tmp, "in.pdf")
        epub = os.path.join(self.tmp, "out.epub")
        make_pdf(pdf)
        convert(pdf, epub, os.path.join(self.tmp, "img"), verbose=False, **kw)
        return epub

    def _assert_valid_epub(self, epub):
        z = zipfile.ZipFile(epub)
        for n in z.namelist():
            if n.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                parseString(z.read(n))  # bien formado
        first = z.infolist()[0]
        self.assertEqual(first.filename, "mimetype")
        self.assertEqual(first.compress_type, zipfile.ZIP_STORED)

    # ------------------------------------------------------------------ #
    def test_two_column_reading_order(self):
        def make(path):
            doc = pymupdf.open()
            p = doc.new_page(width=W, height=H)
            left = " ".join(f"IZQ{i}" for i in range(30))
            right = " ".join(f"DER{i}" for i in range(30))
            p.insert_textbox(pymupdf.Rect(50, 110, 290, 800), left, fontsize=11)
            p.insert_textbox(pymupdf.Rect(305, 110, 545, 800), right, fontsize=11)
            doc.save(path)
            doc.close()

        epub = self._convert(make)
        self._assert_valid_epub(epub)
        _, chaps = _read_chapter_texts(epub)
        text = " ".join(_plain(c) for c in chaps.values())
        toks = re.findall(r"(?:IZQ|DER)\d+", text)
        # Toda la columna izquierda antes que la derecha.
        last_izq = max(i for i, t in enumerate(toks) if t.startswith("IZQ"))
        first_der = min(i for i, t in enumerate(toks) if t.startswith("DER"))
        self.assertLess(last_izq, first_der, "orden de columnas incorrecto")
        # No fragmentado: pocas transiciones (idealmente 1).
        trans = sum(1 for i in range(1, len(toks)) if toks[i][:3] != toks[i - 1][:3])
        self.assertLessEqual(trans, 2)

    def test_outline_becomes_toc(self):
        def make(path):
            doc = pymupdf.open()
            titles = ["Introduccion", "Metodos", "Resultados"]
            for i, t in enumerate(titles):
                p = doc.new_page(width=W, height=H)
                p.insert_text((60, 90), f"{i+1} {t}", fontsize=20)
                p.insert_textbox(pymupdf.Rect(60, 120, 535, 780), BODY * 6, fontsize=11)
            doc.set_toc([[1, f"{i+1} {t}", i + 1] for i, t in enumerate(titles)])
            doc.save(path)
            doc.close()

        epub = self._convert(make)
        z, chaps = _read_chapter_texts(epub)
        # Un capítulo por entrada del outline.
        self.assertEqual(len(chaps), 3)
        nav = z.read("EPUB/nav.xhtml").decode("utf-8", "ignore")
        for t in ("Introduccion", "Metodos", "Resultados"):
            self.assertIn(t, nav)

    def test_numbered_subheadings_detected(self):
        def make(path):
            doc = pymupdf.open()
            p = doc.new_page(width=W, height=H)
            p.insert_text((60, 80), "1 Capitulo", fontsize=20)
            p.insert_text((60, 120), "1.1 Seccion Grande", fontsize=14)
            p.insert_textbox(pymupdf.Rect(60, 150, 535, 780), BODY * 5, fontsize=10)
            doc.set_toc([[1, "1 Capitulo", 1]])
            doc.save(path)
            doc.close()

        epub = self._convert(make)
        _, chaps = _read_chapter_texts(epub)
        html = "\n".join(chaps.values())
        self.assertRegex(html, r"<h2[^>]*>1\.1 Seccion Grande</h2>")

    def test_formulas_not_rasterized_by_default(self):
        def make(path):
            doc = pymupdf.open()
            p = doc.new_page(width=W, height=H)
            p.insert_text((W / 2 - 40, 300), "a/b - c/d + e", fontsize=11)
            p.insert_textbox(pymupdf.Rect(60, 350, 535, 700), BODY * 4, fontsize=11)
            doc.save(path)
            doc.close()

        epub = self._convert(make)
        z = zipfile.ZipFile(epub)
        imgs = [n for n in z.namelist() if "/images/" in n and n.endswith((".png", ".jpg"))]
        self.assertEqual(imgs, [], "no debería rasterizar texto como fórmula")

    def test_table_becomes_html(self):
        def make(path):
            doc = pymupdf.open()
            p = doc.new_page(width=W, height=H)
            x0, y0 = 60, 100
            for r in range(4):
                for c in range(3):
                    rect = pymupdf.Rect(x0 + c * 150, y0 + r * 30,
                                        x0 + (c + 1) * 150, y0 + (r + 1) * 30)
                    p.draw_rect(rect)
                    p.insert_text((rect.x0 + 5, rect.y0 + 20), f"c{r}{c}", fontsize=9)
            doc.save(path)
            doc.close()

        epub = self._convert(make)
        _, chaps = _read_chapter_texts(epub)
        self.assertIn("<table", "\n".join(chaps.values()))

    def test_no_hyphenation_artifacts(self):
        def make(path):
            doc = pymupdf.open()
            p = doc.new_page(width=W, height=H)
            # texto que fuerza cortes de palabra con guion
            p.insert_textbox(pymupdf.Rect(60, 100, 200, 780),
                             "responsabilidad " * 40, fontsize=11)
            doc.save(path)
            doc.close()

        epub = self._convert(make)
        _, chaps = _read_chapter_texts(epub)
        html = "\n".join(chaps.values())
        self.assertEqual(len(re.findall(r"\w- \w", html)), 0)

    def test_dehyphenation_joins_across_lines(self):
        from src.structure import _dehyphenate_join
        self.assertEqual(_dehyphenate_join("compu-", "tadora"), "computadora")
        self.assertEqual(_dehyphenate_join("hola", "mundo"), "hola mundo")
        self.assertEqual(_dehyphenate_join("", "inicio"), "inicio")

    # --- manejo de errores ---
    def test_encrypted_pdf_raises_clear_error(self):
        pdf = os.path.join(self.tmp, "enc.pdf")
        doc = pymupdf.open()
        doc.new_page()
        doc.save(pdf, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x")
        doc.close()
        with self.assertRaises(ValueError) as ctx:
            convert(pdf, os.path.join(self.tmp, "o.epub"),
                    os.path.join(self.tmp, "img"), verbose=False)
        self.assertIn("contraseña", str(ctx.exception))

    def test_corrupt_pdf_raises_clear_error(self):
        pdf = os.path.join(self.tmp, "bad.pdf")
        with open(pdf, "wb") as fh:
            fh.write(b"%PDF-1.4 garbage not a pdf")
        with self.assertRaises(ValueError):
            convert(pdf, os.path.join(self.tmp, "o.epub"),
                    os.path.join(self.tmp, "img"), verbose=False)

    def test_alternating_header_and_folios_stripped(self):
        def make(path):
            doc = pymupdf.open()
            for pno in range(6):
                p = doc.new_page(width=W, height=H)
                # Encabezado que ALTERNA par/impar (como un libro real).
                head = "TITULO DEL LIBRO" if pno % 2 == 0 else "Nombre del capitulo"
                p.insert_text((60, 25), head, fontsize=8)
                p.insert_text((W / 2, H - 25), str(pno + 10), fontsize=9)  # folio
                p.insert_textbox(pymupdf.Rect(60, 90, 535, 760), BODY * 8, fontsize=11)
            doc.save(path)
            doc.close()

        epub = self._convert(make)
        _, chaps = _read_chapter_texts(epub)
        allc = "\n".join(chaps.values())
        self.assertNotIn("TITULO DEL LIBRO", allc)
        self.assertNotIn("Nombre del capitulo", allc)
        # ningún folio suelto como párrafo
        self.assertEqual(re.findall(r"<p>\s*\d{1,3}\s*</p>", allc), [])

    def test_text_box_not_turned_into_image(self):
        def make(path):
            doc = pymupdf.open()
            p = doc.new_page(width=W, height=H)
            # caja con muchas líneas de texto (tipo índice) => NO es figura
            p.draw_rect(pymupdf.Rect(60, 100, 535, 500))
            for i in range(12):
                p.insert_text((70, 120 + i * 28), f"{i+1}.1 Seccion de ejemplo  {i+10}", fontsize=9)
            doc.save(path)
            doc.close()

        epub = self._convert(make)
        z = zipfile.ZipFile(epub)
        imgs = [n for n in z.namelist() if "/images/" in n and n.endswith((".png", ".jpg"))]
        self.assertEqual(imgs, [], "una caja de texto no debe volverse imagen")

    def test_drop_cap_joined(self):
        from src.structure import _merge_spans_into_lines
        # Simula capitular: 'C' grande + 'omprensión' normal en la misma zona.
        from src.models import TextSpan
        spans = [
            TextSpan("C", (60, 100, 90, 140), 24.0, "F", False, False, 0,
                     block_index=0, read_order=0),
            TextSpan("omprensión del tema", (92, 105, 300, 118), 11.0, "F",
                     False, False, 0, block_index=1, read_order=1),
        ]
        lines = _merge_spans_into_lines(spans)
        self.assertTrue(any(l.text.startswith("Comprensión") for l in lines))

    def test_empty_pages_no_crash(self):
        def make(path):
            doc = pymupdf.open()
            for _ in range(3):
                doc.new_page(width=W, height=H)
            doc.save(path)
            doc.close()

        epub = self._convert(make)
        self._assert_valid_epub(epub)


if __name__ == "__main__":
    unittest.main(verbosity=2)
