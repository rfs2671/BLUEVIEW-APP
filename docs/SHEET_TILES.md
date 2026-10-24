# Sheet tiles (deep-zoom drawing viewer)

A drawing PDF is compiled once into a WebP tile pyramid and a per-page index of
its words and callouts. The viewer draws tiles; it never parses a PDF.

## Pieces

| Where | What |
| --- | --- |
| `backend/lib/sheet_tiles.py` | pypdfium2 band renderer: levels z0..z4 (long side 1024·2^z px), 512 px tiles, blank tiles skipped, `present` bitmap per level |
| `backend/lib/sheet_index.py` | pdfplumber words (upright and rotated), callouts (`3/A-402`), detail markers, callout resolution against `document_page_index` |
| `backend/lib/sheet_pipeline.py` | queue (`sheet_tile_jobs`), resumable two-pass compile (levels 0-2 + index → `ready`, 3-4 → `complete`), manifest, purge by known key |
| `backend/server.py` (SHEET TILES) | header-only routes under `/projects/{p}/files/{f}/sheets`, worker, 30-minute sweep, upload and delete hooks |
| `backend/scripts/backfill_sheet_tiles.py` | queue existing PDFs (dry run by default) |
| `frontend/src/viewer/` | geometry, tile cache, controller, search, portal, Canvas2D (web) and Skia (native) renderers |
| `frontend/src/utils/sheetTileStore.js` | progressive offline tile store (native) |

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
- **Offline quota.** The native tile store keeps a usage index and holds the device to 500 MB,
  evicting whole least-recently-used drawings, never the open one.
- **Native images** are freed 500 ms after eviction so a frame never draws a freed texture.
- **Skia 2.2.12** is the version Expo SDK 54 vets; it ships old-architecture sources and its peer
  ranges accept RN 0.81.5 and Reanimated 3.19.5 (`src/viewer/skiaCompat.test.cjs`).

## Rollout

1. Deploy the backend. Nothing changes for users: tiles compile in the background
   (upload hook, opening a drawing, the sweep). `SHEET_TILES_OFF=1` stops all of it.
2. Optional: `railway run python scripts/backfill_sheet_tiles.py` (dry run), then `--apply`.
3. Web: turn on the `sheet_tiles_viewer` feature flag for one user and open a compiled drawing.
4. Native: needs a build that includes `@shopify/react-native-skia` (see `package.json`).
   A binary without it reports the tile viewer unavailable and keeps pdf.js. Smoke-test on a
   development client (old architecture, `newArchEnabled: false`) before widening the flag.
5. Keep the legacy viewer files until the flag has been on in production for a while.

## Behaviour to know

- A file with no tiles, tiles compiling, a failed compile, or more than 600 pages opens in the
  existing PDF viewer. The decision is made once per open.
- Callout portal crops are estimates (`crop_exact: false`) and labelled "approx." The portal loads the
  whole target sheet and uses the crop (plus a 40% margin) only for its first view.
- Notes created in the tile viewer store `page_number` and page-fraction `{x, y}`. Notes created
  in the old viewer stored fractions of the viewer window, not the page; the tile viewer shows
  them as page-1 fractions, which is approximate for those older notes.
