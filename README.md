# PDF → EPUB (Kindle) para documentos académicos

Convierte un PDF académico/técnico (multi-columna, con fórmulas y figuras) en
un EPUB **reflowable** y bien estructurado, pensado para leerse en Kindle.

No es una extracción ingenua de texto: el pipeline reconstruye la estructura
lógica del documento — capítulos, secciones, párrafos, figuras y fórmulas en su
lugar correcto — y descarta el ruido de imprenta (headers, footers, paginación).

> **Nota sobre Kindle:** el Kindle no abre `.epub` de forma nativa en el
> dispositivo. El flujo es: este programa genera el `.epub` → lo mandás por
> **Send to Kindle** (app / email / web) → Amazon lo convierte a KFX/AZW3 del
> lado del servidor. Ese último paso no es parte de este proyecto.

## Instalación

```bash
pip install -r requirements.txt
```

Dependencias: [`pymupdf`](https://pymupdf.readthedocs.io/) (extracción, tablas,
rasterizado), [`ebooklib`](https://github.com/aerkalov/ebooklib) (EPUB) y
[`Pillow`](https://python-pillow.org/) (post-proceso de imágenes).

## Uso

```bash
python main.py --input samples/documento.pdf --output output/documento.epub
```

Opciones:

| Flag | Descripción |
|------|-------------|
| `--input`, `-i` | PDF de entrada (obligatorio) |
| `--output`, `-o` | EPUB de salida (obligatorio) |
| `--image-dir` | Carpeta para recortes de figuras/fórmulas (por defecto `<salida>/images`) |
| `--quiet`, `-q` | Sin logs de progreso |

Abrí el `.epub` resultante en Calibre / Apple Books para una primera pasada, y
luego mandalo por Send to Kindle para la prueba final en el dispositivo real.

## Arquitectura del pipeline

El flujo son seis fases encadenadas, cada una en su módulo bajo `src/`:

| Fase | Módulo | Qué hace |
|------|--------|----------|
| 1 | `extractor.py` | Extrae spans de texto con bbox / fuente / tamaño / negrita-cursiva vía `page.get_text("dict")`. |
| 2 | `denoise.py` | Elimina headers/footers/numeración: texto repetido en la misma posición del margen en >70% de las páginas. |
| 5 | `visuals.py` | Detecta **figuras** (imágenes embebidas + dibujos vectoriales, rasterizadas a PNG), **fórmulas** (líneas cortas/centradas o con fuentes matemáticas, recortadas como imagen) y **tablas** (`find_tables()` → `<table>` HTML reflowable). Asocia captions por proximidad + regex. |
| 3 | `layout.py` | Detecta 1 o 2 columnas por página (histograma de coordenadas x) y reordena los spans en orden de lectura humano, intercalando bloques a ancho completo. |
| 4 | `structure.py` | Clusteriza por (tamaño de fuente, negrita) para inferir la jerarquía de títulos; arma capítulos y fusiona líneas del cuerpo en párrafos (resolviendo guiones de corte). Intercala los bloques visuales por su posición. |
| 6 | `epub_builder.py` | Genera el `.epub` con `ebooklib`: un XHTML por capítulo, CSS con unidades relativas (`em`/`%`, nunca `px`), TOC navegable (NCX + Nav) e imágenes embebidas. |

`main.py` orquesta las fases en orden. Nota: la fase 5 (visuales) corre antes de
la 3/4 para poder marcar los spans ya representados como imagen (captions,
fórmulas) y que no se dupliquen como párrafos de texto.

El modelo de datos compartido está en `src/models.py` (`TextSpan`, `Block`,
`Chapter`, `Document`).

## Alcance y limitaciones (MVP)

- El PDF de entrada **no** está escaneado: es texto seleccionable con layout de
  imprenta. No hay OCR.
- Las **fórmulas se manejan como imágenes recortadas**, no como MathML/LaTeX —
  el soporte de MathML en Kindle es pobre en la práctica. Reconstruir fórmulas
  como texto matemático real es trabajo futuro (ver `PLAN.md`, Fase 8).
- El MVP está calibrado contra un documento específico; generalizarlo a
  cualquier PDF es backlog.

## Definition of Done

El programa toma el PDF real del usuario y genera un `.epub` que:

1. Preserva el orden de lectura correcto en páginas multi-columna.
2. Tiene capítulos/secciones navegables vía TOC.
3. Incluye figuras y fórmulas como imágenes legibles en su posición correcta.
4. No incluye headers/footers/paginación como texto colado.
5. Se ve correctamente en un Kindle real tras pasar por Send to Kindle.

Ver `PLAN.md` para el plan completo de implementación.
