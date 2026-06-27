"""End-to-end tests for the QR Forge API using FastAPI's TestClient."""

from __future__ import annotations

import base64
import io

from PIL import Image

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _decode_png(b64: str) -> Image.Image:
    raw = base64.b64decode(b64)
    assert raw[:8] == PNG_MAGIC, "payload is not a PNG"
    return Image.open(io.BytesIO(raw))


def test_create_returns_valid_png(client):
    r = client.post("/qr", json={"payload": "https://example.com"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"]
    img = _decode_png(body["png_base64"])
    assert img.format == "PNG"
    assert img.width > 0 and img.height > 0


def test_png_endpoint_serves_image(client):
    code_id = client.post("/qr", json={"payload": "hello world"}).json()["id"]
    r = client.get(f"/qr/{code_id}.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == PNG_MAGIC
    Image.open(io.BytesIO(r.content)).verify()  # raises if corrupt


def test_svg_endpoint_serves_image(client):
    code_id = client.post("/qr", json={"payload": "vector"}).json()["id"]
    r = client.get(f"/qr/{code_id}.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text


def test_customization_changes_image(client):
    plain = client.post("/qr", json={"payload": "same-data"}).json()
    styled = client.post(
        "/qr",
        json={
            "payload": "same-data",
            "fill_color": "#1e3a8a",
            "back_color": "#fde68a",
            "box_size": 14,
            "border": 2,
            "error_correction": "H",
        },
    ).json()

    plain_png = base64.b64decode(plain["png_base64"])
    styled_png = base64.b64decode(styled["png_base64"])

    # Same payload but different styling must yield different bytes and,
    # because box_size differs, different pixel dimensions.
    assert plain_png != styled_png
    p_img = Image.open(io.BytesIO(plain_png))
    s_img = Image.open(io.BytesIO(styled_png))
    assert p_img.size != s_img.size

    # The styled image should actually contain its background colour.
    s_rgb = s_img.convert("RGB")
    colors = {c for _, c in s_rgb.getcolors(maxcolors=100000)}
    assert (253, 230, 138) in colors  # #fde68a background


def test_tracking_redirect_increments_scans(client):
    created = client.post(
        "/qr", json={"payload": "https://example.com/landing", "tracked": True}
    ).json()
    code_id = created["id"]
    assert created["redirect_url"].endswith(f"/r/{code_id}")

    # Initially zero scans.
    stats0 = client.get(f"/qr/{code_id}/stats").json()
    assert stats0["total_scans"] == 0

    # Hit the redirect three times (don't auto-follow so we can assert the 302).
    for _ in range(3):
        rr = client.get(f"/r/{code_id}", follow_redirects=False)
        assert rr.status_code == 302
        assert rr.headers["location"] == "https://example.com/landing"

    stats1 = client.get(f"/qr/{code_id}/stats").json()
    assert stats1["total_scans"] == 3
    assert stats1["first_scan"] is not None
    assert stats1["last_scan"] is not None

    # Scan count also surfaces on the code summary.
    summary = client.get(f"/qr/{code_id}").json()
    assert summary["scan_count"] == 3


def test_redirect_404_for_untracked(client):
    code_id = client.post("/qr", json={"payload": "plain text"}).json()["id"]
    r = client.get(f"/r/{code_id}", follow_redirects=False)
    assert r.status_code == 404


def test_listing_returns_all_codes(client):
    ids = {
        client.post("/qr", json={"payload": f"item-{i}"}).json()["id"]
        for i in range(3)
    }
    listing = client.get("/qr").json()
    assert listing["count"] == 3
    listed_ids = {c["id"] for c in listing["codes"]}
    assert ids == listed_ids


def test_missing_code_is_404(client):
    assert client.get("/qr/nope/stats").status_code == 404
    assert client.get("/qr/nope.png").status_code == 404
    assert client.get("/qr/nope").status_code == 404


def test_invalid_error_correction_rejected(client):
    r = client.post("/qr", json={"payload": "x", "error_correction": "Z"})
    assert r.status_code == 422  # pydantic Literal validation


def test_empty_payload_rejected(client):
    r = client.post("/qr", json={"payload": ""})
    assert r.status_code == 422
