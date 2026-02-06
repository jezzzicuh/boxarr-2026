# Boxarr: Replace Box Office Mojo Scraping with Trakt API

## Project Context

Boxarr is a Python/FastAPI app that tracks the weekly top 10 US box office movies and integrates them with Radarr (a movie collection manager). It currently **scrapes Box Office Mojo HTML** using BeautifulSoup to get the top 10, then fuzzy-matches titles against the user's Radarr library to show status and optionally auto-add missing movies.

We are replacing the scraping approach with the **Trakt API**, which provides the same data via a structured REST endpoint.

## Why

- **Scraping is fragile.** Any Box Office Mojo HTML change breaks the parser. This is listed as a known limitation.
- **Trakt returns TMDB IDs** with each movie, which means we can match against Radarr by exact TMDB ID instead of fuzzy string matching. This eliminates an entire class of bugs.
- **Trakt provides revenue data**, rankings, and extended metadata (genres, year, runtime, certification) in a single call.

## The Trakt Endpoint

```
GET https://api.trakt.tv/movies/boxoffice
Headers:
  Content-Type: application/json
  trakt-api-version: 2
  trakt-api-key: <CLIENT_ID>
```

Returns the top 10 grossing US movies from last weekend, updated every Monday morning. Each entry includes `title`, `year`, `revenue`, and IDs (`trakt`, `slug`, `imdb`, `tmdb`).

Use `?extended=full` to also get `overview`, `runtime`, `certification`, `genres`, `released`, `rating`, and more in the same response.

A free Trakt API application (client ID) is required: https://trakt.tv/oauth/applications

## What Changes

### Files to modify or replace

| File | Current Role | Change |
|---|---|---|
| `src/core/boxoffice.py` | Scrapes Box Office Mojo HTML, parses tables, calculates weekend dates | **Rewrite** — replace with Trakt API client using httpx. Call `GET /movies/boxoffice?extended=full`. Return structured data with TMDB IDs. Weekend date calculation logic can be removed (Trakt handles this). |
| `src/core/matcher.py` | Fuzzy title matching (normalization, Roman numerals, number-to-word, 95% threshold) | **Remove or drastically simplify** — matching should now be done by TMDB ID against the Radarr library. The entire fuzzy matching pipeline (title normalization, Roman numeral conversion, etc.) is no longer needed. |
| `src/core/radarr.py` | Radarr API client with caching | **Minor update** — add/expose a method to look up movies by TMDB ID from the cached library, if not already present. The existing `movie` endpoint integration and TMDB lookup via Radarr should still work. |
| `src/core/scheduler.py` | APScheduler wrapper, runs weekly updates, auto-add logic | **Update** — the update pipeline it orchestrates changes from scrape→fuzzy-match→enrich→add to trakt-fetch→id-match→enrich→add. The scheduler mechanics themselves stay the same. |
| `src/core/json_generator.py` | Creates weekly JSON files with TMDB enrichment | **Update** — adapt to consume Trakt response structure. If using `extended=full`, some TMDB enrichment may already be covered by Trakt data. Still use Radarr's TMDB proxy for posters/images. |
| `src/api/routes/boxoffice.py` | Box office data endpoints | **Update** — adapt to new data source shape. |
| `src/utils/config.py` | Pydantic config with YAML + env vars | **Add** — new config fields: `trakt_client_id` (required), and optionally `trakt_api_url` (default `https://api.trakt.tv`). |

### Files unaffected

- `src/core/root_folder_manager.py` — genre-to-folder mapping, no change needed
- `src/api/routes/web.py`, `config.py`, `movies.py`, `scheduler.py` — UI and control routes stay the same
- Jinja2 templates — should work as-is if the weekly JSON structure is kept compatible
- Docker/deployment config — no changes beyond adding `TRAKT_CLIENT_ID` env var

### Dependencies

- **Remove:** `beautifulsoup4` (no longer scraping HTML)
- **Keep:** `httpx` (reuse for Trakt API calls)
- **No new deps needed**

## New Data Flow

```
Before:
  Box Office Mojo (HTML) → BeautifulSoup parse → fuzzy title match vs Radarr → TMDB enrich via Radarr → auto-add

After:
  Trakt API (JSON) → exact TMDB ID match vs Radarr library → enrich if needed → auto-add
```

## Configuration

Add to `local.yaml`:
```yaml
trakt:
  client_id: "your_trakt_client_id_here"
```

And support via environment variable: `TRAKT_CLIENT_ID`

## Implementation Notes

- Trakt rate limit is 1000 calls per 5-minute period. Boxarr makes ~1 call per week, so this is a non-issue.
- Trakt returns IMDB IDs too, which could be useful as a fallback match against Radarr if TMDB ID matching fails for any reason.
- The `extended=full` response includes `certification` (e.g., "PG-13", "R"), which maps directly to the existing rating filter feature — no separate lookup needed.
- The `extended=full` response includes `genres`, which maps directly to the existing genre filter feature.
- Revenue data from Trakt could be displayed in the UI if desired (not currently shown with the scraping approach).
- Consider adding basic retry logic (e.g., 2-3 retries with backoff) to the Trakt client, since "no retry logic" is a listed known limitation of the current design.