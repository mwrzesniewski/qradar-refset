class QRadarError(Exception):
    """Base exception for QRadar CLI."""


class QRadarConfigError(QRadarError):
    """Configuration error."""


class QRadarAPIError(QRadarError):
    """QRadar REST API error."""


class QRadarNotFoundError(QRadarAPIError):
    """Object was not found in QRadar."""
