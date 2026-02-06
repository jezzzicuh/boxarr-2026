"""Scheduler management routes."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...core.root_folder_manager import RootFolderManager
from ...core.scheduler import BoxarrScheduler
from ...utils.config import settings
from ...utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

# Module-level scheduler instance
_scheduler: Optional[BoxarrScheduler] = None


def get_scheduler() -> BoxarrScheduler:
    """Get the scheduler instance."""
    global _scheduler
    if not _scheduler:
        from ...core.boxoffice import BoxOfficeService
        from ...core.radarr import RadarrService

        _scheduler = BoxarrScheduler(
            boxoffice_service=(
                BoxOfficeService() if settings.trakt_client_id else None
            ),
            radarr_service=RadarrService() if settings.radarr_api_key else None,
        )
    return _scheduler


class TriggerResponse(BaseModel):
    """Trigger response model."""

    success: bool
    message: str
    movies_found: Optional[int] = None
    movies_added: Optional[int] = None


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_update():
    """Manually trigger box office update."""
    try:
        scheduler = get_scheduler()
        result = await scheduler.update_box_office()

        # Handle added_movies which is a list
        added_movies = result.get("added_movies", [])
        movies_added_count = len(added_movies) if isinstance(added_movies, list) else 0

        return TriggerResponse(
            success=True,
            message="Box office update completed",
            movies_found=result.get(
                "total_count"
            ),  # Fixed: was "total_movies" but scheduler returns "total_count"
            movies_added=movies_added_count,
        )
    except Exception as e:
        logger.error(f"Error triggering update: {e}")
        return TriggerResponse(
            success=False,
            message=str(e),
        )


@router.post("/reload")
async def reload_scheduler():
    """Manually reload the scheduler with current settings."""
    try:
        scheduler = get_scheduler()

        if not scheduler._running:
            return {
                "success": False,
                "message": "Scheduler is not running",
            }

        # Reload with current settings
        if scheduler.reload_schedule():
            next_run = scheduler.get_next_run_time()
            return {
                "success": True,
                "message": f"Scheduler reloaded with cron: {settings.boxarr_scheduler_cron}",
                "next_run": next_run.isoformat() if next_run else None,
                "cron": settings.boxarr_scheduler_cron,
            }
        else:
            return {
                "success": False,
                "message": "Failed to reload scheduler",
            }
    except Exception as e:
        logger.error(f"Error reloading scheduler: {e}")
        return {
            "success": False,
            "message": str(e),
        }


@router.get("/status")
async def get_scheduler_status():
    """Get current scheduler status and configuration."""
    try:
        scheduler = get_scheduler()

        # Get job information
        jobs = scheduler.scheduler.get_jobs() if scheduler.scheduler else []
        job_info = []

        for job in jobs:
            job_info.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": (
                        job.next_run_time.isoformat() if job.next_run_time else None
                    ),
                    "pending": job.pending,
                }
            )

        # Get next run time
        next_run = scheduler.get_next_run_time() if scheduler._running else None

        # Calculate time until next run
        time_until_next = None
        if next_run:
            from datetime import datetime

            import pytz

            now = datetime.now(pytz.timezone(settings.boxarr_scheduler_timezone))
            delta = next_run - now
            time_until_next = {
                "days": delta.days,
                "hours": delta.seconds // 3600,
                "minutes": (delta.seconds % 3600) // 60,
                "total_hours": delta.total_seconds() / 3600,
            }

        # Get last run info from history
        last_run_info = None
        try:
            history_dir = Path(settings.boxarr_data_directory) / "history"
            if history_dir.exists():
                history_files = sorted(history_dir.glob("*_latest.json"), reverse=True)
                if history_files:
                    with open(history_files[0]) as f:
                        data = json.load(f)
                        timestamp = data.get("timestamp")
                        if timestamp:
                            from datetime import datetime

                            last_run_time = datetime.fromisoformat(
                                timestamp.replace("Z", "+00:00")
                            )
                            last_run_info = {
                                "timestamp": last_run_time.isoformat(),
                                "success": True,
                                "matched_count": data.get("matched_count", 0),
                                "total_count": data.get("total_count", 0),
                            }
        except Exception as e:
            logger.debug(f"Could not get last run info: {e}")

        return {
            "enabled": settings.boxarr_scheduler_enabled,
            "running": scheduler._running if scheduler else False,
            "cron_expression": settings.boxarr_scheduler_cron,
            "timezone": settings.boxarr_scheduler_timezone,
            "next_run_time": next_run.isoformat() if next_run else None,
            "time_until_next": time_until_next,
            "last_run": last_run_info,
            "jobs": job_info,
            "auto_add_enabled": settings.boxarr_features_auto_add,
        }
    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}")
        return {
            "enabled": settings.boxarr_scheduler_enabled,
            "running": False,
            "error": str(e),
        }


@router.get("/history")
async def get_scheduler_history():
    """Get scheduler run history."""
    try:
        history_dir = Path(settings.boxarr_data_directory) / "history"
        if not history_dir.exists():
            return {"runs": []}

        # Get all history files
        history_files = sorted(history_dir.glob("*.json"), reverse=True)[:20]

        runs = []
        for file_path in history_files:
            # Parse filename for timestamp
            # Format: YYYYWW_YYYYMMDD_HHMMSS.json
            parts = file_path.stem.split("_")
            if len(parts) >= 3:
                date_str = parts[1]
                time_str = parts[2]

                try:
                    run_time = datetime.strptime(
                        f"{date_str}_{time_str}", "%Y%m%d_%H%M%S"
                    )

                    # Read result
                    import json

                    with open(file_path) as f:
                        result = json.load(f)

                    # Handle added_movies which could be a list or count
                    added_movies = result.get("added_movies", [])
                    added_count = (
                        len(added_movies)
                        if isinstance(added_movies, list)
                        else added_movies
                    )

                    runs.append(
                        {
                            "timestamp": run_time.isoformat(),
                            "week": parts[0],
                            "success": result.get("success", False),
                            "movies_found": result.get(
                                "total_count", result.get("total_movies")
                            ),
                            "movies_added": added_count,
                            "error": result.get("error"),
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error parsing history file {file_path}: {e}")
                    continue

        return {"runs": runs}
    except Exception as e:
        logger.error(f"Error getting scheduler history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateWeekRequest(BaseModel):
    """Request model for updating a specific week."""

    year: int
    week: int


@router.post("/update-week")
async def update_specific_week(request: UpdateWeekRequest):
    """Re-match a specific historical week against current Radarr library.

    Since Trakt only returns current-week data, historical weeks are
    regenerated by reconstructing BoxOfficeMovie objects from stored JSON
    and re-matching against the current Radarr library.
    """
    year = request.year
    week = request.week
    try:
        # Validate inputs
        if year < 2000 or year > datetime.now().year:
            raise HTTPException(status_code=400, detail="Invalid year")
        if week < 1 or week > 53:
            raise HTTPException(status_code=400, detail="Invalid week number")

        from ...core.boxoffice import (
            BoxOfficeMovie,
            MatchResult,
            match_box_office_to_radarr,
        )
        from ...core.json_generator import WeeklyDataGenerator
        from ...core.radarr import RadarrService

        # Check if JSON file exists for this week
        json_file = (
            Path(settings.boxarr_data_directory)
            / "weekly_pages"
            / f"{year}W{week:02d}.json"
        )

        if not json_file.exists():
            return {
                "success": False,
                "message": (
                    f"No stored data for week {year}W{week:02d}. "
                    f"Historical data cannot be fetched from Trakt."
                ),
            }

        # Read stored JSON
        with open(json_file) as f:
            metadata = json.load(f)

        # Reconstruct BoxOfficeMovie objects from stored JSON
        from .movies import _reconstruct_movies_from_json

        box_office_movies = _reconstruct_movies_from_json(metadata)

        if not box_office_movies:
            return {
                "success": False,
                "message": f"No movie data in stored file for week {year}W{week:02d}",
            }

        # Match with Radarr
        match_results = []
        added_count = 0

        if settings.radarr_api_key:
            radarr_service = RadarrService()

            # Re-match against current Radarr library by TMDB ID
            match_results = match_box_office_to_radarr(
                box_office_movies, radarr_service
            )

            # Auto-add if enabled — use Trakt data from stored JSON
            if settings.boxarr_features_auto_add:
                unmatched = [r for r in match_results if not r.is_matched]

                limit = settings.boxarr_features_auto_add_limit
                if limit < len(unmatched):
                    unmatched = sorted(
                        unmatched, key=lambda r: r.box_office_movie.rank
                    )[:limit]

                root_folder_manager = RootFolderManager(radarr_service)

                for result in unmatched:
                    bom = result.box_office_movie
                    if not bom.tmdb_id:
                        continue

                    # Re-release filter using Trakt year
                    if settings.boxarr_features_auto_add_ignore_rereleases:
                        if bom.year and bom.year < (year - 1):
                            continue

                    # Genre filter using Trakt genres
                    movie_genres = bom.genres or []
                    if settings.boxarr_features_auto_add_genre_filter_enabled:
                        if (
                            settings.boxarr_features_auto_add_genre_filter_mode
                            == "whitelist"
                        ):
                            whitelist = (
                                settings.boxarr_features_auto_add_genre_whitelist
                            )
                            if whitelist and not any(
                                g in whitelist for g in movie_genres
                            ):
                                continue
                        else:
                            blacklist = (
                                settings.boxarr_features_auto_add_genre_blacklist
                            )
                            if blacklist and any(
                                g in blacklist for g in movie_genres
                            ):
                                continue

                    # Rating filter using Trakt certification
                    if settings.boxarr_features_auto_add_rating_filter_enabled:
                        rating_whitelist = (
                            settings.boxarr_features_auto_add_rating_whitelist
                        )
                        if (
                            rating_whitelist
                            and bom.certification
                            and bom.certification not in rating_whitelist
                        ):
                            continue

                    # Determine root folder
                    chosen_root = root_folder_manager.determine_root_folder(
                        genres=movie_genres,
                        movie_title=bom.title,
                    )

                    try:
                        movie = radarr_service.add_movie(
                            tmdb_id=bom.tmdb_id,
                            quality_profile_id=None,
                            root_folder=chosen_root,
                            monitored=True,
                            search_for_movie=True,
                        )
                        if movie:
                            added_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to auto-add {bom.title}: {e}")

                # Re-match if we added movies
                if added_count > 0:
                    radarr_service.bust_cache()
                    match_results = match_box_office_to_radarr(
                        box_office_movies, radarr_service
                    )
        else:
            # No Radarr, create unmatched results
            match_results = [
                MatchResult(box_office_movie=movie) for movie in box_office_movies
            ]

        # Generate data file
        generator = WeeklyDataGenerator(
            radarr_service=radarr_service if settings.radarr_api_key else None
        )
        generator.generate_weekly_data(match_results, year, week)

        return {
            "success": True,
            "message": f"Updated week {year}W{week:02d}",
            "movies_found": len(box_office_movies),
            "movies_added": added_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating week: {e}")
        raise HTTPException(status_code=500, detail=str(e))
