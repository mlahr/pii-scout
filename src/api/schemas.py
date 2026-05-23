from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from enum import Enum


class EntityType(str, Enum):
    PERSON = "PERSON"
    LOCATION = "LOCATION"
    ADDRESS = "ADDRESS"
    SSN = "SSN"
    PHONE_NUMBER = "PHONE_NUMBER"
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
    BIRTHDATE = "BIRTHDATE"
    DATE = "DATE"
    EMAIL = "EMAIL"
    # Piiranha-specific types
    CREDIT_CARD_NUMBER = "CREDIT_CARD_NUMBER"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    ID_CARD = "ID_CARD"
    TAX_NUMBER = "TAX_NUMBER"
    USERNAME = "USERNAME"
    PASSWORD = "PASSWORD"
    ZIPCODE = "ZIPCODE"


class DetectorType(str, Enum):
    NER = "ner"
    REGEX = "regex"
    DICT = "dict"


class ConfigOverride(BaseModel):
    """Optional configuration overrides for detection request."""
    gateway_enabled: Optional[bool] = Field(
        default=None,
        description="Override gateway enabled setting"
    )
    min_digits_threshold: Optional[int] = Field(
        default=None,
        ge=1,
        description="Override minimum consecutive digits threshold for gateway"
    )
    patterns: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Override regex patterns per entity type"
    )
    context_keywords: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Override context keywords per entity type"
    )
    scores: Optional[Dict[str, float]] = Field(
        default=None,
        description="Override base scores per entity type"
    )
    detector_order: Optional[List[str]] = Field(
        default=None,
        description="Override detector order (e.g., ['ner', 'regex', 'dict'])"
    )
    context_window: Optional[int] = Field(
        default=None,
        ge=1,
        description="Override context window size for keyword search"
    )


class DetectRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=500000,
        description="Text to analyze for PII"
    )
    min_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score threshold (default: from config)"
    )
    include_stats: bool = Field(
        default=False,
        description="Include timing statistics in response"
    )
    gateway: Optional[bool] = Field(
        default=None,
        description="Enable gateway mode. If not specified, uses config default."
    )
    entity_types: Optional[List[EntityType]] = Field(
        default=None,
        description="If provided, only return entities of these types. Omit to return all."
    )
    detectors: Optional[List[DetectorType]] = Field(
        default=None,
        description="Detectors to run. Options: ner, regex, dict. Omit to run all."
    )
    config_override: Optional[ConfigOverride] = Field(
        default=None,
        description="Optional configuration overrides"
    )


class Entity(BaseModel):
    type: str
    text: str
    start: int
    end: int
    score: float
    source: List[str]


class TimingStats(BaseModel):
    normalize_ms: float
    ner_ms: float
    regex_ms: float
    dict_ms: float
    merge_ms: float
    total_ms: float


class DetectResponse(BaseModel):
    entities: List[Entity]
    meta: dict
    stats: Optional[TimingStats] = None


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    model_loaded: bool
    model_profile: Optional[str] = None


class InfoResponse(BaseModel):
    version: str
    model_profile: str
    entity_types: List[str]
    max_text_length: int


class EntityTypesResponse(BaseModel):
    entity_types: List[str]


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
