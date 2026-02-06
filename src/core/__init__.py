"""Core business logic for Boxarr."""

from .boxoffice import BoxOfficeMovie, BoxOfficeService, MatchResult, match_box_office_to_radarr
from .exceptions import (
    BoxarrException,
    BoxOfficeError,
    ConfigurationError,
    RadarrAuthenticationError,
    RadarrConnectionError,
    RadarrError,
    RadarrNotFoundError,
    SchedulerError,
)
from .radarr import MovieStatus, QualityProfile, RadarrMovie, RadarrService
from .scheduler import BoxarrScheduler

__all__ = [
    # Services
    "BoxOfficeService",
    "RadarrService",
    "BoxarrScheduler",
    # Data classes
    "BoxOfficeMovie",
    "RadarrMovie",
    "QualityProfile",
    "MovieStatus",
    "MatchResult",
    # Functions
    "match_box_office_to_radarr",
    # Exceptions
    "BoxarrException",
    "ConfigurationError",
    "BoxOfficeError",
    "RadarrError",
    "RadarrConnectionError",
    "RadarrAuthenticationError",
    "RadarrNotFoundError",
    "SchedulerError",
]
