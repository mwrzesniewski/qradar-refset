class QRadarError(Exception):
    pass

class QRadarConfigError(QRadarError):
    pass

class QRadarAPIError(QRadarError):
    pass

class QRadarNotFoundError(QRadarAPIError):
    pass
