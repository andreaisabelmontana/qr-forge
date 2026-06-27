# QR Forge

A FastAPI service that generates, customises and tracks QR codes through a clean REST API. Codes are rendered with `qrcode` + Pillow, persisted in SQLite, and (optionally) made trackable: a tracked code encodes a short redirect link that logs every scan so you can pull analytics back out.

- **Live demo UI:** https://andreaisabelmontana.github.io/qr-forge/ (static page that calls a running API)
- Backend is a real FastAPI app — `app/api.py`, `app/generator.py`, `app/db.py`.

## Run it

```bash
pip install -r requirements.txt
uvicorn app.api:app --reload
```

Then open http://127.0.0.1:8000/docs for the interactive OpenAPI docs.

## API

| Method | Route             | Purpose                                              |
|--------|-------------------|------------------------------------------------------|
| POST   | `/qr`             | Create a code. Returns metadata + inline base64 PNG. |
| GET    | `/qr`             | List all codes with their scan counts.               |
| GET    | `/qr/{id}`        | Fetch one code's metadata.                           |
| GET    | `/qr/{id}.png`    | Render the code as a PNG.                            |
| GET    | `/qr/{id}.svg`    | Render the code as an SVG.                           |
| GET    | `/qr/{id}/stats`  | Scan analytics for a tracked code.                  |
| GET    | `/r/{id}`         | Redirect (302) to the target URL and log the scan.  |

## Customisation

`POST /qr` accepts these fields (all optional except `payload`):

| Field              | Default     | Notes                                            |
|--------------------|-------------|--------------------------------------------------|
| `payload`          | —           | URL or text to encode (required).               |
| `fill_color`       | `#000000`   | Foreground / module colour.                     |
| `back_color`       | `#ffffff`   | Background colour.                              |
| `box_size`         | `10`        | Pixels per QR module (1–50).                    |
| `border`           | `4`         | Quiet-zone width in modules (0–20).             |
| `error_correction` | `M`         | `L` ~7%, `M` ~15%, `Q` ~25%, `H` ~30% recovery. |
| `tracked`          | `false`     | If true, the code encodes a trackable redirect. |

## How scan tracking works

When you create a code with `"tracked": true`, the original `payload` is stored as the
**target URL**, but the QR image itself encodes `…/r/{id}` instead of the raw URL. Each time
someone scans it and their device opens that link, `GET /r/{id}`:

1. records a scan row (timestamp, user-agent, referrer) in SQLite, then
2. returns a `302` redirect to the stored target URL.

`GET /qr/{id}/stats` then aggregates those rows: total scans, first/last scan time, and a
per-user-agent breakdown.

## Example

```bash
# create a tracked QR pointing at a landing page
curl -s -X POST http://127.0.0.1:8000/qr \
  -H 'Content-Type: application/json' \
  -d '{"payload":"https://example.org","tracked":true,"fill_color":"#1e293b","error_correction":"Q"}'
# -> {"id":"AOOu2D4m", ..., "redirect_url":"http://127.0.0.1:8000/r/AOOu2D4m", "png_base64":"iVBORw0K..."}

# save the image
curl -s http://127.0.0.1:8000/qr/AOOu2D4m.png -o code.png

# simulate a scan (302 to the target, logged)
curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}\n' http://127.0.0.1:8000/r/AOOu2D4m

# read analytics
curl -s http://127.0.0.1:8000/qr/AOOu2D4m/stats
# -> {"total_scans":1,"first_scan":"...","last_scan":"...","by_user_agent":[...]}
```

## Project layout

```
app/
  db.py         SQLite schema + queries (codes, scans)
  generator.py  QR rendering & customisation (PNG / SVG)
  api.py        FastAPI app: routes, Pydantic models
tests/          pytest suite (FastAPI TestClient)
demo.py         self-contained end-to-end demo
```

## Tests

```bash
python -m pytest -q
```

Covers: PNG validity (magic bytes + Pillow decode), customisation producing a different image,
the redirect incrementing the scan count visible in `/stats`, listing, and validation errors.

## License

MIT — see [LICENSE](LICENSE).
