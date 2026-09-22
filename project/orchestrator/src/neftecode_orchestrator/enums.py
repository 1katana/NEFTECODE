from enum import StrEnum


class Decision(StrEnum):
    RECOMMEND = "RECOMMEND"
    KEEP = "KEEP"
    REFUSE = "REFUSE"


class ComponentStatus(StrEnum):
    OK = "OK"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNAVAILABLE = "UNAVAILABLE"


class DataConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class ReliabilityRisk(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class InputSource(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    HISTORICAL = "HISTORICAL"
    LIVE = "LIVE"


class AssessmentSource(StrEnum):
    UNKNOWN = "UNKNOWN"
    REAL = "REAL"
    MOCK = "MOCK"


class QualityProduct(StrEnum):
    UNKNOWN = "UNKNOWN"
    HYDROTREATED_DIESEL = "HYDROTREATED_DIESEL"
    COMMERCIAL_DIESEL = "COMMERCIAL_DIESEL"


class OptimizationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    NO_FEASIBLE_SOLUTION = "NO_FEASIBLE_SOLUTION"
