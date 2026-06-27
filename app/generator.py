"""QR code rendering and customisation.

Thin, well-typed wrapper around the ``qrcode`` library. Turns a payload plus a
set of styling options into PNG bytes (via Pillow) or an SVG string.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import qrcode
import qrcode.image.svg
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)

# Map the human-friendly error-correction letters to qrcode's constants.
# L ~7% recovery, M ~15%, Q ~25%, H ~30%.
ERROR_LEVELS = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}


@dataclass
class QROptions:
    """Customisation options for a rendered QR code."""

    fill_color: str = "#000000"
    back_color: str = "#ffffff"
    box_size: int = 10
    border: int = 4
    error_correction: str = "M"

    def ec_constant(self) -> int:
        level = self.error_correction.upper()
        if level not in ERROR_LEVELS:
            raise ValueError(
                f"error_correction must be one of {sorted(ERROR_LEVELS)}, got {level!r}"
            )
        return ERROR_LEVELS[level]


def _build_qr(data: str, opts: QROptions) -> qrcode.QRCode:
    qr = qrcode.QRCode(
        version=None,  # auto-size to fit the data
        error_correction=opts.ec_constant(),
        box_size=opts.box_size,
        border=opts.border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr


def render_png(data: str, opts: QROptions | None = None) -> bytes:
    """Render ``data`` to PNG bytes using the given options."""
    opts = opts or QROptions()
    qr = _build_qr(data, opts)
    img = qr.make_image(fill_color=opts.fill_color, back_color=opts.back_color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_svg(data: str, opts: QROptions | None = None) -> str:
    """Render ``data`` to an SVG string.

    The SVG path factory does not honour custom colours the way the raster
    backend does, so colours are post-processed into the markup. This keeps the
    vector output consistent with the PNG.
    """
    opts = opts or QROptions()
    qr = qrcode.QRCode(
        version=None,
        error_correction=opts.ec_constant(),
        box_size=opts.box_size,
        border=opts.border,
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")

    # Default SvgPathImage paint is black on transparent; inject the chosen
    # foreground colour and a background rectangle for the chosen back colour.
    if opts.fill_color.lower() not in ("#000000", "black"):
        svg = svg.replace('fill="#000000"', f'fill="{opts.fill_color}"')
        svg = svg.replace("fill:#000000", f"fill:{opts.fill_color}")
    if opts.back_color.lower() not in ("#ffffff", "white", "transparent"):
        svg = svg.replace(
            "<svg ",
            f'<svg style="background:{opts.back_color}" ',
            1,
        )
    return svg
