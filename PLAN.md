# Plan de Implementación — PDF Académico a EPUB (Kindle)

## 1. Objetivo

Construir una herramienta en Python que tome un PDF académico/técnico (multi-columna, con fórmulas y figuras) y genere un EPUB bien estructurado y reflowable, optimizado para lectura en Kindle. El objetivo no es una conversión ingenua de texto: es reconstruir la estructura lógica del documento (capítulos, párrafos, figuras y fórmulas en su lugar correcto), no solo extraer texto plano.

## 2. Contexto y limitaciones aceptadas (leer antes de empezar)

- El PDF de entrada NO está escaneado — es texto seleccionable con layout de imprenta (multi-columna, fórmulas, figuras).
- Las fórmulas se manejan como **imágenes recortadas**, no como MathML/LaTeX. El soporte de MathML en lectores EPUB (y en Kindle en particular) es pobre a inexistente en la práctica; reconstruir fórmulas como texto matemático real es un problema aparte, fuera de este MVP.
- El Kindle no abre archivos EPUB de forma nativa en el dispositivo (esto sigue siendo cierto en 2026). El flujo final es: este programa genera un `.epub` → el usuario lo manda por **Send to Kindle** (app/email/web) → Amazon lo convierte a KFX/AZW3 del lado del servidor. Ese último paso no es responsabilidad de este proyecto.
- El objetivo del MVP es UN documento específico (el PDF real del usuario), no un conversor genérico para cualquier PDF. Generalizar es trabajo futuro, no parte de este alcance.

## 3. Stack técnico

- Python 3.10+
- `pymupdf` — extracción de texto con metadata (fuente, tamaño, bbox), detección de tablas nativa (`find_tables()`), y rasterizado de regiones (`get_pixmap`). Importar como `import pymupdf` (el alias viejo `import fitz` todavía funciona pero ya no es la forma recomendada).
- `ebooklib` — generación del EPUB (capítulos XHTML, manifest, spine, TOC).
- `Pillow` — post-proceso de imágenes recortadas si hace falta (reescalado, compresión).

No se necesita OCR ni librerías externas de tablas (pdfplumber, camelot) para este caso — PyMuPDF ya cubre extracción, imágenes y tablas nativamente.

`requirements.txt` (sin pins de versión — instalar la más reciente disponible):
```
pymupdf
ebooklib
pillow
```

## 4. Estructura del proyecto

```
pdf2epub/
├── PLAN.md
├── requirements.txt
├── main.py                 # CLI: orquesta las fases en orden
├── src/
│   ├── models.py            # Dataclasses: TextSpan, Block, Chapter, Document
│   ├── extractor.py         # Fase 1: extracción cruda
│   ├── denoise.py           # Fase 2: filtrado de headers/footers/paginación
│   ├── layout.py            # Fase 3: columnas / orden de lectura
│   ├── structure.py         # Fase 4: jerarquía de títulos y capítulos
│   ├── visuals.py           # Fase 5: figuras, fórmulas y tablas
│   └── epub_builder.py      # Fase 6: generación del EPUB
├── samples/                 # PDF real de prueba va aquí
└── output/
    ├── images/               # recortes de figuras/fórmulas
    └── *.epub
```

## 5. Modelo de datos (`src/models.py`)

Ver `src/models.py` — dataclasses `TextSpan`, `Block`, `Chapter`, `Document`.

## 6. Fases de implementación

- Fase 0 — Setup
- Fase 1 — Extracción cruda (`extractor.py`)
- Fase 2 — Filtrado de ruido (`denoise.py`)
- Fase 3 — Columnas y orden de lectura (`layout.py`)
- Fase 4 — Jerarquía de títulos y capítulos (`structure.py`)
- Fase 5 — Figuras, fórmulas y tablas (`visuals.py`)
- Fase 6 — Generación de EPUB (`epub_builder.py`)
- Fase 7 — Validación / QA manual
- Fase 8 — Fuera de alcance del MVP (backlog futuro)

## 7. Definition of Done (MVP)

El programa toma el PDF real del usuario y genera un `.epub` que:
1. Preserva el orden de lectura correcto en páginas multi-columna.
2. Tiene capítulos/secciones navegables vía TOC.
3. Incluye figuras y fórmulas como imágenes legibles en su posición correcta.
4. No incluye headers/footers/paginación como texto colado.
5. Se ve correctamente en un Kindle real después de pasar por Send to Kindle.

## 8. Cómo probarlo

```bash
python main.py --input samples/documento.pdf --output output/documento.epub
```
Abrir el `.epub` resultante en el visor de Calibre para una primera pasada rápida, y luego mandarlo por Send to Kindle para la prueba final en el dispositivo real.
