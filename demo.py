"""End-to-end demo of QR Forge.

Spins up the app in-process with a throwaway database, creates a tracked QR
code, writes its PNG to disk, simulates a few scans through the redirect
endpoint, and prints the real analytics that come back from the service.

Run:  python demo.py
"""

from __future__ import annotations

import base64
import importlib
import os
import tempfile

from fastapi.testclient import TestClient


def main() -> None:
    # Use a temp DB so the demo is self-contained and repeatable.
    tmpdir = tempfile.mkdtemp(prefix="qrforge_demo_")
    os.environ["QRFORGE_DB"] = os.path.join(tmpdir, "demo.db")

    import app.db as db
    import app.api as api

    importlib.reload(db)
    importlib.reload(api)

    with TestClient(api.app) as client:
        print("== Create a tracked QR code ==")
        resp = client.post(
            "/qr",
            json={
                "payload": "https://andreaisabelmontana.github.io/qr-forge/",
                "fill_color": "#1e293b",
                "back_color": "#f8fafc",
                "box_size": 12,
                "border": 4,
                "error_correction": "Q",
                "tracked": True,
            },
        )
        code = resp.json()
        code_id = code["id"]
        print(f"   id            : {code_id}")
        print(f"   tracked       : {code['tracked']}")
        print(f"   target_url    : {code['target_url']}")
        print(f"   redirect_url  : {code['redirect_url']}")
        print(f"   image_url     : {code['image_url']}")

        # Write the PNG to a real file.
        out_path = os.path.join(os.getcwd(), "demo_qr.png")
        png = base64.b64decode(code["png_base64"])
        with open(out_path, "wb") as fh:
            fh.write(png)
        png_magic = b"\x89PNG\r\n\x1a\n"
        magic_ok = "OK" if png[:8] == png_magic else "BAD"
        print(f"   PNG written   : {out_path} ({len(png)} bytes, magic={magic_ok})")

        print("\n== Simulate scans through /r/{id} ==")
        agents = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8)",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        ]
        for ua in agents:
            r = client.get(
                f"/r/{code_id}", headers={"user-agent": ua}, follow_redirects=False
            )
            print(f"   GET /r/{code_id} -> {r.status_code} Location={r.headers.get('location')}")

        print("\n== Analytics from /qr/{id}/stats ==")
        stats = client.get(f"/qr/{code_id}/stats").json()
        print(f"   total_scans   : {stats['total_scans']}")
        print(f"   first_scan    : {stats['first_scan']}")
        print(f"   last_scan     : {stats['last_scan']}")
        print("   by_user_agent :")
        for row in stats["by_user_agent"]:
            print(f"       {row['count']:>2}x  {row['user_agent']}")

        print("\n== Listing (GET /qr) ==")
        listing = client.get("/qr").json()
        print(f"   {listing['count']} code(s):")
        for c in listing["codes"]:
            print(f"       {c['id']}  scans={c['scan_count']:>2}  tracked={c['tracked']}  {c['payload']}")


if __name__ == "__main__":
    main()
