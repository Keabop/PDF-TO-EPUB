"""Optimización de imágenes con Pillow.

El rasterizado a 300 DPI en PNG hace que el EPUB pese muchísimo (un PDF de
texto de 7 MB puede terminar en un EPUB de 70+ MB, que no pasa por Send to
Kindle por email). Este módulo controla resolución, formato y compresión:

- Figuras -> JPEG con downscale (color conservado por defecto).
- Fórmulas -> PNG en escala de grises (texto negro sobre blanco, nítido y
  liviano).

En un Kindle (pantalla e-ink, ~300 ppi pero chica) 150 DPI se ven perfectas y
el archivo pesa una fracción.
"""

import os
from dataclasses import dataclass

import pymupdf
from PIL import Image


@dataclass(frozen=True)
class ImageSettings:
    dpi: int = 150            # resolución de rasterizado
    max_width_px: int = 1400  # ancho máximo; se hace downscale si se supera
    jpeg_quality: int = 82    # calidad JPEG para figuras
    grayscale: bool = False   # forzar escala de grises también en figuras


# Presets pensados para elegir desde la GUI/CLI sin tocar números.
PRESETS: dict[str, ImageSettings] = {
    "equilibrado": ImageSettings(dpi=150, max_width_px=1400, jpeg_quality=82),
    "calidad": ImageSettings(dpi=220, max_width_px=1800, jpeg_quality=90),
    "minimo": ImageSettings(
        dpi=110, max_width_px=1100, jpeg_quality=72, grayscale=True
    ),
}
DEFAULT_PRESET = "equilibrado"


def get_settings(preset: str | None) -> ImageSettings:
    if preset is None:
        return PRESETS[DEFAULT_PRESET]
    return PRESETS.get(preset, PRESETS[DEFAULT_PRESET])


def _pix_to_pil(pix: pymupdf.Pixmap) -> Image.Image:
    """Convierte un Pixmap de PyMuPDF a una imagen Pillow sin re-encodear."""
    if pix.alpha:
        mode = "RGBA" if pix.n == 4 else "LA"
    else:
        mode = "L" if pix.n == 1 else "RGB"
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


def _flatten_on_white(img: Image.Image) -> Image.Image:
    """Quita el canal alfa componiendo sobre blanco (JPEG no soporta alfa)."""
    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgb = img.convert("RGBA")
        background.paste(rgb, mask=rgb.split()[-1])
        return background
    return img.convert("RGB")


def _downscale(img: Image.Image, max_width: int) -> Image.Image:
    if img.width <= max_width:
        return img
    ratio = max_width / img.width
    new_size = (max_width, max(1, round(img.height * ratio)))
    return img.resize(new_size, Image.LANCZOS)


def save_optimized(
    pix: pymupdf.Pixmap,
    out_dir: str,
    name_stem: str,
    kind: str,
    settings: ImageSettings,
) -> str:
    """Guarda el Pixmap optimizado según el tipo. Devuelve la ruta final.

    - kind == "figure": JPEG (color salvo que settings.grayscale).
    - kind == "formula" (u otro): PNG en escala de grises.
    """
    os.makedirs(out_dir, exist_ok=True)
    img = _pix_to_pil(pix)
    img = _downscale(img, settings.max_width_px)

    if kind == "figure":
        img = _flatten_on_white(img)
        if settings.grayscale:
            img = img.convert("L")
        path = os.path.join(out_dir, name_stem + ".jpg")
        img.save(path, "JPEG", quality=settings.jpeg_quality, optimize=True)
    else:
        # Fórmulas y line-art: escala de grises + PNG optimizado.
        img = img.convert("L")
        path = os.path.join(out_dir, name_stem + ".png")
        img.save(path, "PNG", optimize=True)

    return path
