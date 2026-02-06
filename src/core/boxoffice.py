"""Trakt API client for fetching weekly box office data."""

import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import httpx

from ..utils.config import settings
from ..utils.logger import get_logger
from .exceptions import BoxOfficeError

logger = get_logger(__name__)


@dataclass
class BoxOfficeMovie:
    """Represents a movie from the Trakt box office endpoint."""

    rank: int
    title: str
    year: Optional[int] = None
    revenue: Optional[int] = None
    # IDs from Trakt
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    trakt_id: Optional[int] = None
    trakt_slug: Optional[str] = None
    # Extended info (from ?extended=full)
    overview: Optional[str] = None
    runtime: Optional[int] = None
    certification: Optional[str] = None
    genres: Optional[List[str]] = field(default=None)
    released: Optional[str] = None
    rating: Optional[float] = None
    # Poster URL (populated from Radarr/TMDB lookup later)
    poster: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class MatchResult:
    """Result of matching a box office movie against Radarr library by TMDB ID."""

    box_office_movie: BoxOfficeMovie
    radarr_movie: Optional[object] = None

    @property
    def is_matched(self) -> bool:
        """Check if movie was successfully matched."""
        return self.radarr_movie is not None


def match_box_office_to_radarr(
    box_office_movies: List[BoxOfficeMovie],
    radarr_service,
) -> List[MatchResult]:
    """
    Match box office movies against Radarr library by TMDB ID.

    Args:
        box_office_movies: List of box office movies from Trakt
        radarr_service: RadarrService instance with find_movie_by_tmdb_id method

    Returns:
        List of MatchResult objects
    """
    results = []
    for movie in box_office_movies:
        radarr_movie = None
        if movie.tmdb_id:
            radarr_movie = radarr_service.find_movie_by_tmdb_id(movie.tmdb_id)

        results.append(
            MatchResult(
                box_office_movie=movie,
                radarr_movie=radarr_movie,
            )
        )

        if radarr_movie:
            logger.debug(
                f"Matched '{movie.title}' to Radarr by TMDB ID {movie.tmdb_id}"
            )
        else:
            logger.debug(f"No Radarr match for '{movie.title}' (TMDB: {movie.tmdb_id})")

    matched_count = sum(1 for r in results if r.is_matched)
    logger.info(
        f"Matched {matched_count}/{len(box_office_movies)} box office movies by TMDB ID"
    )
    return results


class BoxOfficeService:
    """Service for fetching box office data from Trakt API."""

    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1  # seconds

    def __init__(
        self,
        client_id: Optional[str] = None,
        api_url: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        """
        Initialize Trakt box office service.

        Args:
            client_id: Trakt API client ID (defaults to config)
            api_url: Trakt API base URL (defaults to config)
            http_client: Optional HTTP client for testing
        """
        self.client_id = client_id or settings.trakt_client_id
        self.api_url = (api_url or settings.trakt_api_url).rstrip("/")

        self.client = http_client or httpx.Client(
            headers={
                "Content-Type": "application/json",
                "trakt-api-version": "2",
                "trakt-api-key": self.client_id,
            },
            timeout=30.0,
        )

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close HTTP client."""
        self.close()

    def close(self) -> None:
        """Close HTTP client."""
        if self.client:
            self.client.close()

    def fetch_box_office(self) -> List[BoxOfficeMovie]:
        """
        Fetch current weekend box office from Trakt API.

        Uses ?extended=full for complete metadata including genres,
        certification, overview, runtime, and rating.

        Returns:
            List of BoxOfficeMovie objects (top 10)

        Raises:
            BoxOfficeError: If fetching fails after all retries
        """
        url = f"{self.api_url}/movies/boxoffice?extended=full"
        logger.info(f"Fetching box office data from Trakt API: {url}")

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.client.get(url)
                response.raise_for_status()
                return self._parse_trakt_response(response.json())
            except httpx.HTTPError as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    backoff = self.INITIAL_BACKOFF * (2**attempt)
                    logger.warning(
                        f"Trakt API request failed (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}. "
                        f"Retrying in {backoff}s..."
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        f"Trakt API request failed after {self.MAX_RETRIES} attempts: {e}"
                    )
            except Exception as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    backoff = self.INITIAL_BACKOFF * (2**attempt)
                    logger.warning(
                        f"Trakt API error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}. "
                        f"Retrying in {backoff}s..."
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        f"Trakt API error after {self.MAX_RETRIES} attempts: {e}"
                    )

        raise BoxOfficeError(
            f"Failed to fetch box office data after {self.MAX_RETRIES} attempts: {last_error}"
        )

    def _parse_trakt_response(self, data: list) -> List[BoxOfficeMovie]:
        """
        Parse Trakt API box office response into BoxOfficeMovie objects.

        Args:
            data: JSON response from Trakt /movies/boxoffice endpoint

        Returns:
            List of BoxOfficeMovie objects
        """
        movies = []
        rank = 1

        for entry in data[:10]:  # Top 10 only
            movie_data = entry.get("movie", {})
            ids = movie_data.get("ids", {})
            revenue = entry.get("revenue")

            tmdb_id = ids.get("tmdb")
            if tmdb_id is None:
                logger.warning(
                    f"Skipping '{movie_data.get('title', 'Unknown')}' - no TMDB ID available"
                )
                continue

            genres = movie_data.get("genres")

            movie = BoxOfficeMovie(
                rank=rank,
                title=movie_data.get("title", "Unknown"),
                year=movie_data.get("year"),
                revenue=revenue,
                tmdb_id=tmdb_id,
                imdb_id=ids.get("imdb"),
                trakt_id=ids.get("trakt"),
                trakt_slug=ids.get("slug"),
                overview=movie_data.get("overview"),
                runtime=movie_data.get("runtime"),
                certification=movie_data.get("certification"),
                genres=genres if isinstance(genres, list) else None,
                released=movie_data.get("released"),
                rating=movie_data.get("rating"),
            )
            movies.append(movie)
            rank += 1

            logger.debug(f"Parsed movie: #{movie.rank} {movie.title} (TMDB: {movie.tmdb_id})")

        if not movies:
            raise BoxOfficeError("No movies found in Trakt box office data")

        logger.info(f"Successfully parsed {len(movies)} movies from Trakt box office")
        return movies
