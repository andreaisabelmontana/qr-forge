"""FastAPI application for QR Forge.

Routes
------
POST   /qr            create a code (returns id, links and base64 PNG)
GET    /qr            list all codes with scan counts
GET    /qr/{id}       fetch a code's metadata
GET    /qr/{id}.png   render the code as a PNG image
GET    /qr/{id}.svg   render the code as an SVG image
GET    /qr/{id}/stats scan analytics for a tracked code
GET    /r/{id}        redirect to the target URL and log the scan
"""

from __future__ import annotations

import base64
import secrets
from datetime import datetime, timezone
from typing import Literal

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import db
from .generator import ERROR_LEVELS, QROptions, render_png, render_svg


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="QR Forge",
    description="Generate, customise and track QR codes through a clean REST API.",
    version="1.0.0",
    lifespan=lifespan,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    # 8 url-safe chars — short enough for a tracking link, plenty of entropy.
    return secrets.token_urlsafe(6)[:8]


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class CreateQR(BaseModel):
    payload: str = Field(..., min_length=1, description="URL or text to encode.")
    fill_color: str = Field("#000000", description="Foreground (module) colour.")
    back_color: str = Field("#ffffff", description="Background colour.")
    box_size: int = Field(10, ge=1, le=50, description="Pixels per QR module.")
    border: int = Field(4, ge=0, le=20, description="Quiet-zone width in modules.")
    error_correction: Literal["L", "M", "Q", "H"] = Field(
        "M", description="Error-correction level (L/M/Q/H)."
    )
    tracked: bool = Field(
        False,
        description="If true, the code encodes a /r/{id} redirect that logs each scan.",
    )


class QRSummary(BaseModel):
    id: str
    payload: str
    tracked: bool
    target_url: str | None
    fill_color: str
    back_color: str
    box_size: int
    border: int
    error_correction: str
    created_at: str
    scan_count: int = 0
    image_url: str
    redirect_url: str | None = None


def _options_from_row(row: dict) -> QROptions:
    return QROptions(
        fill_color=row["fill_color"],
        back_color=row["back_color"],
        box_size=row["box_size"],
        border=row["border"],
        error_correction=row["error_correction"],
    )


def _encoded_data(row: dict, request: Request) -> str:
    """What actually goes into the QR: a redirect link for tracked codes,
    otherwise the raw payload."""
    if row["tracked"]:
        return str(request.base_url).rstrip("/") + f"/r/{row['id']}"
    return row["payload"]


def _summary(row: dict, request: Request) -> QRSummary:
    base = str(request.base_url).rstrip("/")
    return QRSummary(
        id=row["id"],
        payload=row["payload"],
        tracked=bool(row["tracked"]),
        target_url=row.get("target_url"),
        fill_color=row["fill_color"],
        back_color=row["back_color"],
        box_size=row["box_size"],
        border=row["border"],
        error_correction=row["error_correction"],
        created_at=row["created_at"],
        scan_count=int(row.get("scan_count", 0) or 0),
        image_url=f"{base}/qr/{row['id']}.png",
        redirect_url=f"{base}/r/{row['id']}" if row["tracked"] else None,
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.post("/qr", status_code=201)
def create_qr(body: CreateQR, request: Request) -> dict:
    """Create a QR code and return its metadata plus an inline base64 PNG."""
    code_id = _new_id()
    row = {
        "id": code_id,
        "payload": body.payload,
        "fill_color": body.fill_color,
        "back_color": body.back_color,
        "box_size": body.box_size,
        "border": body.border,
        "error_correction": body.error_correction,
        "tracked": 1 if body.tracked else 0,
        "target_url": body.payload if body.tracked else None,
        "created_at": _now(),
    }
    db.insert_code(row)

    data = _encoded_data(row, request)
    png = render_png(data, _options_from_row(row))
    summary = _summary({**row, "scan_count": 0}, request)
    return {
        **summary.model_dump(),
        "png_base64": base64.b64encode(png).decode("ascii"),
    }


@app.get("/qr")
def list_qr(request: Request) -> dict:
    """List every code with its current scan count."""
    rows = db.list_codes()
    return {"count": len(rows), "codes": [_summary(r, request).model_dump() for r in rows]}


@app.get("/qr/{code_id}.png")
def get_qr_png(code_id: str, request: Request) -> Response:
    """Render the code as a PNG."""
    row = db.get_code(code_id)
    if not row:
        raise HTTPException(status_code=404, detail="QR code not found")
    png = render_png(_encoded_data(row, request), _options_from_row(row))
    return Response(content=png, media_type="image/png")


@app.get("/qr/{code_id}.svg")
def get_qr_svg(code_id: str, request: Request) -> Response:
    """Render the code as an SVG."""
    row = db.get_code(code_id)
    if not row:
        raise HTTPException(status_code=404, detail="QR code not found")
    svg = render_svg(_encoded_data(row, request), _options_from_row(row))
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/qr/{code_id}/stats")
def get_qr_stats(code_id: str) -> dict:
    """Return scan analytics for a code."""
    row = db.get_code(code_id)
    if not row:
        raise HTTPException(status_code=404, detail="QR code not found")
    stats = db.scan_stats(code_id)
    return {
        "id": code_id,
        "tracked": bool(row["tracked"]),
        "target_url": row.get("target_url"),
        **stats,
    }


@app.get("/qr/{code_id}")
def get_qr(code_id: str, request: Request) -> QRSummary:
    """Fetch a single code's metadata."""
    row = db.get_code(code_id)
    if not row:
        raise HTTPException(status_code=404, detail="QR code not found")
    stats = db.scan_stats(code_id)
    row["scan_count"] = stats["total_scans"]
    return _summary(row, request)


@app.get("/r/{code_id}")
def redirect_and_log(code_id: str, request: Request) -> RedirectResponse:
    """Log a scan and redirect to the code's target URL."""
    row = db.get_code(code_id)
    if not row or not row["tracked"] or not row.get("target_url"):
        raise HTTPException(status_code=404, detail="No tracked redirect for this id")
    db.record_scan(
        code_id,
        _now(),
        request.headers.get("user-agent"),
        request.headers.get("referer"),
    )
    return RedirectResponse(url=row["target_url"], status_code=302)


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    """Tiny landing blurb so the bare service URL isn't empty."""
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>QR Forge</title>"
        "<body style=\"font-family:system-ui;max-width:640px;margin:60px auto;padding:0 20px\">"
        "<h1>QR Forge</h1>"
        "<p>A FastAPI service that generates, customises and tracks QR codes.</p>"
        "<p>Interactive API docs: <a href='/docs'>/docs</a></p>"
        "<p>Levels: " + ", ".join(sorted(ERROR_LEVELS)) + "</p>"
        "</body>"
    )
