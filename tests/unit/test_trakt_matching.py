"""Tests for Trakt box office to Radarr TMDB ID matching."""

from unittest.mock import MagicMock

import pytest

from src.core.boxoffice import BoxOfficeMovie, MatchResult, match_box_office_to_radarr


def _make_box_office_movie(
    rank=1, title="Test Movie", tmdb_id=12345, year=2024
):
    """Helper to create a BoxOfficeMovie."""
    return BoxOfficeMovie(
        rank=rank,
        title=title,
        year=year,
        revenue=50000000,
        tmdb_id=tmdb_id,
        imdb_id=f"tt{tmdb_id}" if tmdb_id else None,
    )


def _make_radarr_movie(tmdb_id=12345, title="Test Movie"):
    """Helper to create a mock Radarr movie."""
    movie = MagicMock()
    movie.tmdbId = tmdb_id
    movie.id = tmdb_id + 1000
    movie.title = title
    movie.hasFile = True
    return movie


def test_match_by_tmdb_id():
    """Test that movies are matched by TMDB ID."""
    bom = _make_box_office_movie(tmdb_id=12345)
    radarr_movie = _make_radarr_movie(tmdb_id=12345)

    mock_service = MagicMock()
    mock_service.find_movie_by_tmdb_id.return_value = radarr_movie

    results = match_box_office_to_radarr([bom], mock_service)

    assert len(results) == 1
    assert results[0].is_matched
    assert results[0].radarr_movie == radarr_movie
    mock_service.find_movie_by_tmdb_id.assert_called_once_with(12345)


def test_unmatched_movie():
    """Test that a movie not in Radarr is unmatched."""
    bom = _make_box_office_movie(tmdb_id=99999)

    mock_service = MagicMock()
    mock_service.find_movie_by_tmdb_id.return_value = None

    results = match_box_office_to_radarr([bom], mock_service)

    assert len(results) == 1
    assert not results[0].is_matched
    assert results[0].radarr_movie is None


def test_movie_without_tmdb_id_is_unmatched():
    """Test that a movie with no TMDB ID is never matched."""
    bom = _make_box_office_movie(tmdb_id=None)

    mock_service = MagicMock()

    results = match_box_office_to_radarr([bom], mock_service)

    assert len(results) == 1
    assert not results[0].is_matched
    # Should not even attempt to look up
    mock_service.find_movie_by_tmdb_id.assert_not_called()


def test_batch_matching_preserves_order():
    """Test that batch matching preserves the original order."""
    movies = [
        _make_box_office_movie(rank=1, title="First", tmdb_id=111),
        _make_box_office_movie(rank=2, title="Second", tmdb_id=222),
        _make_box_office_movie(rank=3, title="Third", tmdb_id=333),
    ]

    mock_service = MagicMock()
    # Only match the second movie
    mock_service.find_movie_by_tmdb_id.side_effect = lambda tid: (
        _make_radarr_movie(tmdb_id=222) if tid == 222 else None
    )

    results = match_box_office_to_radarr(movies, mock_service)

    assert len(results) == 3
    assert results[0].box_office_movie.title == "First"
    assert not results[0].is_matched
    assert results[1].box_office_movie.title == "Second"
    assert results[1].is_matched
    assert results[2].box_office_movie.title == "Third"
    assert not results[2].is_matched


def test_match_result_properties():
    """Test MatchResult dataclass properties."""
    bom = _make_box_office_movie()

    # Unmatched
    result_unmatched = MatchResult(box_office_movie=bom)
    assert not result_unmatched.is_matched
    assert result_unmatched.radarr_movie is None

    # Matched
    radarr_movie = _make_radarr_movie()
    result_matched = MatchResult(box_office_movie=bom, radarr_movie=radarr_movie)
    assert result_matched.is_matched
    assert result_matched.radarr_movie == radarr_movie


def test_mixed_batch_with_and_without_tmdb_ids():
    """Test batch with a mix of movies with and without TMDB IDs."""
    movies = [
        _make_box_office_movie(rank=1, title="Has TMDB", tmdb_id=111),
        _make_box_office_movie(rank=2, title="No TMDB", tmdb_id=None),
        _make_box_office_movie(rank=3, title="Also Has TMDB", tmdb_id=333),
    ]

    mock_service = MagicMock()
    mock_service.find_movie_by_tmdb_id.side_effect = lambda tid: (
        _make_radarr_movie(tmdb_id=tid) if tid == 111 else None
    )

    results = match_box_office_to_radarr(movies, mock_service)

    assert len(results) == 3
    assert results[0].is_matched  # Has TMDB, found in Radarr
    assert not results[1].is_matched  # No TMDB ID
    assert not results[2].is_matched  # Has TMDB but not in Radarr

    # find_movie_by_tmdb_id should only be called for movies WITH TMDB IDs
    assert mock_service.find_movie_by_tmdb_id.call_count == 2


def test_box_office_movie_to_dict():
    """Test BoxOfficeMovie.to_dict() method."""
    movie = _make_box_office_movie(title="Test", tmdb_id=42)
    d = movie.to_dict()

    assert d["title"] == "Test"
    assert d["tmdb_id"] == 42
    assert d["rank"] == 1
    assert "revenue" in d
