# Sheet tiles (deep-zoom drawing viewer)

A drawing PDF is compiled once into a WebP tile pyramid and a per-page index of
its words and callouts. The viewer draws tiles; it never parses a PDF.

## Pieces

| Where | What |
| --- | --- |
| `backend/lib/sheet_tiles.py` | pypdfium2 band renderer: levels z0..z4 (long side 1024·2^z px), 512 px tiles, blank tiles skipped, `present` bitmap per level |
| `backend/lib/sheet_index.py` | pdfplumber words (upright and rotated), callouts (`3/A-402`), detail markers, callout resolution against `document_page_index` |
| `backend/lib/sheet_pipeline.py` | queue (`sheet_tile_jobs`), resumable two-pass compile (levels 0-2 + index → `ready`, 3-4 → `complete`), manifest, purge by known key |
| `backend/server.py` (SHEET TILES) | header-only routes under `/projects/{p}/files/{f}/sheets`, worker, 10-minute sweep (lowest priority), upload and delete hooks |
| `backend/scripts/backfill_sheet_tiles.py` | queue existing PDFs (dry run by default) |
| `frontend/src/viewer/` | geometry, tile cache, controller, search, portal, Canvas2D web renderer and the phone WebView page |

R2 layout: `projects/{pid}/files/{fid}/sheets/{build}/p{page}/z{z}/{x}_{y}.webp`, `preview.webp`, `index.json.gz`.
`build` changes with the file's bytes (`cache_version`, `size`) and with the tile/index schema.

## Auth

Every route takes `Authorization: Bearer` only (`get_current_user_header_only`);
`?token=` is refused. Tile and preview requests must carry the current `b=<build>`.
Same tenancy checks as `/content`.

## Hardening notes

- **pdfium is single-file.** `lib/pdfium_lock.py` is the one lock around every pypdfium2 call in
  the API process (`plan_page`, `sheet_tiles`). The tile compile itself runs in a child process,
  one child at a time per process, with each page rendered in bands (never a whole 16k bitmap:
  at most 64 MB, capped at 96 MB). Every document, page and bitmap is closed in a `finally`.
- **Tiles are not re-proxied.** Immutable `Cache-Control`, `ETag` + 304 before R2, an in-process
  byte LRU, and a 20 s memory of the tenancy decision for tile/preview reads. A presigned-URL
  redirect was not used (needs R2 CORS; leaves our auth).

## Phones: a WebView page

A phone draws tiles in a WebView page: the same engine and canvas viewer as the web app, hosted in the
app's existing `react-native-webview`, so it ships with an ordinary OTA update (no native module, no new
build). `sheetPlatform.native.js` reports `webview` when the app has react-native-webview, and null
otherwise (the PDF viewer is kept). A native Skia renderer was built and removed: the WebView is as fast in
practice and needs nothing compiled into the app.

- The page is generated: `node scripts/build-sheet-webview.cjs` bundles `src/viewer/webview/main.js`
  into `webview/sheetWebViewHtml.js` (a test fails if it is out of date).
- Pan, pinch, inertia, search and painting happen in the page. Pins and highlights are drawn on the
  same canvas as the tiles. Only taps and a throttled status message cross to the app. The token is
  passed in a message, never in a URL. The page runs at `https://app.levelog.com` so the API's CORS
  allows it. A killed WebView falls back to the PDF viewer.
- Limits: tiles are not cached on the phone's disk (the page has no store), so a drawing viewed offline
  opens in the PDF viewer if its file was saved there; the API's immutable cache headers still apply
  inside a session.

## Rollout

1. Deploy the backend. Nothing changes for users: tiles compile in the background
   (upload hook, opening a drawing, the sweep). `SHEET_TILES_OFF=1` stops all of it.
2. Optional: `railway run python scripts/backfill_sheet_tiles.py` (dry run), then `--apply`.
3. Web: turn on the `sheet_tiles_viewer` feature flag for one user and open a compiled drawing.
4. Phones: nothing to build. The viewer arrives with the OTA update that follows the merge to `main`.
5. Keep the legacy viewer files until the flag has been on in production for a while.

## Behaviour to know

- A file with no tiles, tiles compiling, a failed compile, or more than 600 pages opens in the
  existing PDF viewer. The decision is made once per open.
- Callout portal crops are estimates (`crop_exact: false`) and labelled "approx." The portal loads the
  whole target sheet and uses the crop (plus a 40% margin) only for its first view.
- Notes created in the tile viewer store `page_number` and page-fraction `{x, y}`. Notes created
  in the old viewer stored fractions of the viewer window, not the page; the tile viewer shows
  them as page-1 fractions, which is approximate for those older notes.
