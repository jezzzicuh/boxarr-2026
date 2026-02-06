"""Tests for Trakt API box office service."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.core.boxoffice import BoxOfficeMovie, BoxOfficeService
from src.core.exceptions import BoxOfficeError


# Sample Trakt API response
TRAKT_RESPONSE = [
    {
        "revenue": 150000000,
        "movie": {
            "title": "Inside Out 2",
            "year": 2024,
            "ids": {
                "trakt": 123456,
                "slug": "inside-out-2-2024",
                "imdb": "tt22022452",
                "tmdb": 1022789,
            },
            "overview": "Joy and the other emotions deal with a new set of feelings.",
            "runtime": 96,
            "certification": "PG",
            "genres": ["animation", "family", "comedy"],
            "released": "2024-06-14",
            "rating": 7.6,
        },
    },
    {
        "revenue": 85000000,
        "movie": {
            "title": "Deadpool & Wolverine",
            "year": 2024,
            "ids": {
                "trakt": 789012,
                "slug": "deadpool-wolverine-2024",
                "imdb": "tt6263850",
                "tmdb": 533535,
            },
            "overview": "Deadpool teams up with Wolverine.",
            "runtime": 128,
            "certification": "R",
            "genres": ["action", "comedy", "science-fiction"],
            "released": "2024-07-26",
            "rating": 8.1,
        },
    },
    {
        "revenue": 20000000,
        "movie": {
            "title": "No TMDB Movie",
            "year": 2024,
            "ids": {
                "trakt": 999,
                "slug": "no-tmdb",
                "imdb": None,
                "tmdb": None,
            },
        },
    },
]


@pytest.fixture
def mock_http_client():
    """Create a mock HTTP client."""
    client = MagicMock(spec=httpx.Client)
    return client


def test_fetch_box_office_success(mock_http_client):
    """Test successful box office fetch from Trakt."""
    response = MagicMock()
    response.json.return_value = TRAKT_RESPONSE
    response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = response

    service = BoxOfficeService(
        client_id="test-id",
        http_client=mock_http_client,
    )
    movies = service.fetch_box_office()

    # Should skip the movie without TMDB ID
    assert len(movies) == 2
    assert movies[0].title == "Inside Out 2"
    assert movies[0].tmdb_id == 1022789
    assert movies[0].revenue == 150000000
    assert movies[0].rank == 1
    assert movies[1].title == "Deadpool & Wolverine"
    assert movies[1].rank == 2


def test_movies_without_tmdb_id_skipped(mock_http_client):
    """Test that movies without TMDB ID are skipped with warning."""
    response = MagicMock()
    response.json.return_value = TRAKT_RESPONSE
    response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = response

    service = BoxOfficeService(
        client_id="test-id",
        http_client=mock_http_client,
    )
    movies = service.fetch_box_office()

    # Third movie has no TMDB ID, should be skipped
    tmdb_ids = [m.tmdb_id for m in movies]
    assert None not in tmdb_ids
    assert len(movies) == 2


def test_retry_logic_succeeds_on_third_attempt(mock_http_client):
    """Test retry logic - fail twice, succeed on third attempt."""
    response_ok = MagicMock()
    response_ok.json.return_value = TRAKT_RESPONSE[:2]  # Only movies with TMDB IDs
    response_ok.raise_for_status = MagicMock()

    mock_http_client.get.side_effect = [
        httpx.HTTPError("Connection failed"),
        httpx.HTTPError("Timeout"),
        response_ok,
    ]

    service = BoxOfficeService(
        client_id="test-id",
        http_client=mock_http_client,
    )
    # Override backoff for faster tests
    service.INITIAL_BACKOFF = 0

    with patch("time.sleep"):
        movies = service.fetch_box_office()

    assert len(movies) == 2
    assert mock_http_client.get.call_count == 3


def test_raises_after_max_retries(mock_http_client):
    """Test that BoxOfficeError is raised after max retries."""
    mock_http_client.get.side_effect = httpx.HTTPError("Connection refused")

    service = BoxOfficeService(
        client_id="test-id",
        http_client=mock_http_client,
    )
    service.INITIAL_BACKOFF = 0

    with patch("time.sleep"):
        with pytest.raises(BoxOfficeError, match="Failed to fetch"):
            service.fetch_box_office()

    assert mock_http_client.get.call_count == 3


def test_correct_trakt_api_headers():
    """Test that correct Trakt API headers are set."""
    service = BoxOfficeService(client_id="my-test-client-id")

    headers = service.client.headers
    assert headers["trakt-api-version"] == "2"
    assert headers["trakt-api-key"] == "my-test-client-id"
    assert headers["Content-Type"] == "application/json"

    service.close()


def test_box_office_movie_fields(mock_http_client):
    """Test that all Trakt fields are correctly parsed into BoxOfficeMovie."""
    response = MagicMock()
    response.json.return_value = TRAKT_RESPONSE[:1]
    response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = response

    service = BoxOfficeService(
        client_id="test-id",
        http_client=mock_http_client,
    )
    movies = service.fetch_box_office()

    movie = movies[0]
    assert movie.rank == 1
    assert movie.title == "Inside Out 2"
    assert movie.year == 2024
    assert movie.revenue == 150000000
    assert movie.tmdb_id == 1022789
    assert movie.imdb_id == "tt22022452"
    assert movie.trakt_id == 123456
    assert movie.trakt_slug == "inside-out-2-2024"
    assert movie.overview == "Joy and the other emotions deal with a new set of feelings."
    assert movie.runtime == 96
    assert movie.certification == "PG"
    assert movie.genres == ["animation", "family", "comedy"]
    assert movie.released == "2024-06-14"
    assert movie.rating == 7.6
    assert movie.poster is None  # Trakt doesn't provide posters


def test_fetch_url_includes_extended_full(mock_http_client):
    """Test that the fetch URL includes ?extended=full."""
    response = MagicMock()
    response.json.return_value = TRAKT_RESPONSE[:1]
    response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = response

    service = BoxOfficeService(
        client_id="test-id",
        api_url="https://api.trakt.tv",
        http_client=mock_http_client,
    )
    service.fetch_box_office()

    call_url = mock_http_client.get.call_args[0][0]
    assert "extended=full" in call_url
    assert "/movies/boxoffice" in call_url


def test_empty_response_raises_error(mock_http_client):
    """Test that an empty response raises BoxOfficeError."""
    response = MagicMock()
    response.json.return_value = []
    response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = response

    service = BoxOfficeService(
        client_id="test-id",
        http_client=mock_http_client,
    )

    with pytest.raises(BoxOfficeError, match="No movies found"):
        service.fetch_box_office()


def test_top_10_limit(mock_http_client):
    """Test that only top 10 movies are returned."""
    # Create 15 movies
    movies_data = []
    for i in range(15):
        movies_data.append(
            {
                "revenue": 100000 * (15 - i),
                "movie": {
                    "title": f"Movie {i+1}",
                    "year": 2024,
                    "ids": {"tmdb": 1000 + i, "trakt": i, "slug": f"movie-{i}"},
                },
            }
        )

    response = MagicMock()
    response.json.return_value = movies_data
    response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = response

    service = BoxOfficeService(
        client_id="test-id",
        http_client=mock_http_client,
    )
    movies = service.fetch_box_office()

    assert len(movies) == 10


def test_context_manager():
    """Test context manager protocol."""
    with BoxOfficeService(client_id="test-id") as service:
        assert service.client is not None
