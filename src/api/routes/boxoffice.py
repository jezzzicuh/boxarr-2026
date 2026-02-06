"""Box office data routes."""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...core.boxoffice import BoxOfficeService, match_box_office_to_radarr
from ...core.radarr import RadarrService
from ...utils.config import settings
from ...utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/boxoffice", tags=["boxoffice"])


class BoxOfficeMovieResponse(BaseModel):
    """Box office movie response model."""

    rank: int
    title: str
    revenue: Optional[int] = None
    weekend_gross: Optional[int] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    certification: Optional[str] = None
    radarr_id: Optional[int] = None
    radarr_status: Optional[str] = None
    radarr_has_file: bool = False


@router.get("/current", response_model=List[BoxOfficeMovieResponse])
async def get_current_box_office():
    """Get current week's box office with Radarr matching."""
    try:
        if not settings.trakt_client_id:
            raise HTTPException(
                status_code=400, detail="Trakt API not configured"
            )

        # Fetch current box office from Trakt
        boxoffice_service = BoxOfficeService()
        movies = boxoffice_service.fetch_box_office()

        # Match with Radarr if configured
        results = []
        if settings.radarr_api_key:
            radarr_service = RadarrService()
            match_results = match_box_office_to_radarr(movies, radarr_service)

            for result in match_results:
                bom = result.box_office_movie
                results.append(
                    BoxOfficeMovieResponse(
                        rank=bom.rank,
                        title=bom.title,
                        revenue=bom.revenue,
                        weekend_gross=bom.revenue,
                        tmdb_id=bom.tmdb_id,
                        imdb_id=bom.imdb_id,
                        certification=bom.certification,
                        radarr_id=(
                            result.radarr_movie.id
                            if result.is_matched
                            else None
                        ),
                        radarr_status=(
                            result.radarr_movie.status.value
                            if result.is_matched
                            else None
                        ),
                        radarr_has_file=(
                            result.radarr_movie.hasFile
                            if result.is_matched
                            else False
                        ),
                    )
                )
        else:
            # No Radarr configured, just return box office data
            results = [
                BoxOfficeMovieResponse(
                    rank=movie.rank,
                    title=movie.title,
                    revenue=movie.revenue,
                    weekend_gross=movie.revenue,
                    tmdb_id=movie.tmdb_id,
                    imdb_id=movie.imdb_id,
                    certification=movie.certification,
                )
                for movie in movies
            ]

        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting box office: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{year}/W{week}")
async def get_historical_box_office(year: int, week: int):
    """Get historical box office data for a specific week from stored JSON."""
    try:
        # Validate year and week
        if year < 2000 or year > datetime.now().year:
            raise HTTPException(status_code=400, detail="Invalid year")
        if week < 1 or week > 53:
            raise HTTPException(status_code=400, detail="Invalid week number")

        # Read from stored JSON file
        json_file = (
            Path(settings.boxarr_data_directory)
            / "weekly_pages"
            / f"{year}W{week:02d}.json"
        )

        if not json_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"No data found for week {year}W{week:02d}",
            )

        with open(json_file) as f:
            metadata = json.load(f)

        return [
            {
                "rank": movie.get("rank"),
                "title": movie.get("title"),
                "revenue": movie.get("revenue"),
                "weekend_gross": movie.get("weekend_gross"),
                "tmdb_id": movie.get("tmdb_id"),
            }
            for movie in metadata.get("movies", [])
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting historical box office: {e}")
        raise HTTPException(status_code=500, detail=str(e))
