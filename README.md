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

### Opción A — Interfaz gráfica (la más simple)

```bash
python gui.py
```

Se abre una ventana: apretás **«Seleccionar PDF…»**, elegís el archivo y luego
**«Convertir a EPUB»**. Eso es todo. El EPUB se guarda junto al PDF, con el
mismo nombre (`documento.pdf` → `documento.epub`), y la ventana muestra el
progreso en vivo. Con documentos grandes la conversión corre en segundo plano,
así que la ventana no se congela.

> Tkinter viene incluido con las instalaciones estándar de Python en Windows y
> macOS. En Linux puede hacer falta `sudo apt install python3-tk`.

En el menú **«Tamaño del archivo»** elegís el nivel de compresión de imágenes
(ver [Tamaño del EPUB](#tamaño-del-epub-figuras-y-fórmulas) abajo). Al terminar,
la ventana te muestra el peso final del `.epub`.

### Opción B — Línea de comandos

```bash
python main.py --input samples/documento.pdf --output output/documento.epub
```

Opciones:

| Flag | Descripción |
|------|-------------|
| `--input`, `-i` | PDF de entrada (obligatorio) |
| `--output`, `-o` | EPUB de salida (obligatorio) |
| `--image-dir` | Carpeta para recortes de figuras/fórmulas (por defecto `<salida>/images`) |
| `--images` | Preset de compresión: `equilibrado` (por defecto), `calidad` o `minimo` |
| `--quiet`, `-q` | Sin logs de progreso |

Abrí el `.epub` resultante en Calibre / Apple Books para una primera pasada, y
luego mandalo por Send to Kindle para la prueba final en el dispositivo real.

## Tamaño del EPUB (figuras y fórmulas)

Las figuras y fórmulas se rasterizan como imágenes; sin compresión un PDF de
texto liviano puede generar un EPUB **enorme** (p. ej. un PDF de 7 MB / 800
páginas → EPUB de 71 MB). Eso importa porque **Send to Kindle** tiene límites de
tamaño:

| Método de envío | Límite | 
|-----------------|--------|
| Email (`…@kindle.com`) | ~50 MB por correo |
| App de escritorio / web (`send.amazon.com`) | hasta 200 MB |

Para controlarlo, el pipeline comprime las imágenes con Pillow según un preset
(`--images` en la CLI, menú «Tamaño del archivo» en la GUI):

| Preset | DPI | Figuras | Fórmulas | Uso |
|--------|-----|---------|----------|-----|
| `calidad` | 220 | JPEG q90 color | PNG gris | Máxima nitidez, archivo más pesado |
| `equilibrado` *(default)* | 150 | JPEG q82 color | PNG gris | Recomendado: se ve bien en Kindle y pesa poco |
| `minimo` | 110 | JPEG q72 **gris** | PNG gris | El archivo más chico posible |

Bajar de 300 DPI/PNG a 150 DPI/JPEG suele reducir el EPUB **~10–20×** sin pérdida
visible en la pantalla e-ink del Kindle. Las fórmulas se guardan siempre en PNG
gris (texto negro sobre blanco: nítido y liviano).

## Arquitectura del pipeline

El flujo son seis fases encadenadas, cada una en su módulo bajo `src/`:

| Fase | Módulo | Qué hace |
|------|--------|----------|
| 1 | `extractor.py` | Extrae spans de texto con bbox / fuente / tamaño / negrita-cursiva vía `page.get_text("dict")`. |
| 2 | `denoise.py` | Elimina headers/footers/numeración: texto repetido en la misma posición del margen en >70% de las páginas. |
| 5 | `visuals.py` | Detecta **figuras** (imágenes embebidas + dibujos vectoriales que no estén cubiertos por texto) y **tablas** (`find_tables()` → `<table>` HTML reflowable). La detección de **fórmulas como imagen** está **desactivada por defecto** (`--formulas-as-images` para activarla): el heurístico es poco fiable y termina rasterizando texto normal. Asocia captions por proximidad + regex. |
| 3 | `layout.py` | Detecta 1 o 2 columnas por página (histograma de coordenadas x) y reordena los spans en orden de lectura humano, intercalando bloques a ancho completo. |
| 4 | `structure.py` | Usa el **índice/marcadores embebidos del PDF** (`get_toc()`) como fuente autoritativa de capítulos y secciones; si el PDF no trae marcadores, cae al heurístico de tamaño de fuente. Fusiona líneas del cuerpo en párrafos (resolviendo guiones de corte) e intercala los bloques visuales por su posición. |
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
