"""Pydantic models for PII detection configuration."""

from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """Reference to an external file for loading patterns, keywords, or name lists."""
    source: str = Field(..., description="Path to the source file (relative to config file or absolute)")


class OllamaConfig(BaseModel):
    """Configuration for Ollama model backend."""
    base_url: str = Field(default="http://localhost:11434", description="Ollama API base URL")
    model: str = Field(default="llama3.2", description="Ollama model name")


class OpenRouterConfig(BaseModel):
    """Configuration for OpenRouter model backend."""
    base_url: str = Field(default="https://openrouter.ai/api/v1", description="OpenRouter API base URL")
    model: str = Field(default="", description="OpenRouter model name (required when using openrouter profile)")


class PiiranhaConfig(BaseModel):
    """Configuration for Piiranha model backend."""
    model_path: str = Field(
        default="iiiorg/piiranha-v1-detect-personal-information",
        description="Path to Piiranha model (HuggingFace ID or local directory path)"
    )


class ModelsConfig(BaseModel):
    """Configuration for model selection and backends."""
    profile: str = Field(default="spacy-accurate", description="Model profile: spacy-fast, spacy-accurate, piiranha, ollama, openrouter")
    ollama: OllamaConfig = Field(default_factory=OllamaConfig, description="Ollama backend settings")
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig, description="OpenRouter backend settings")
    piiranha: PiiranhaConfig = Field(default_factory=PiiranhaConfig, description="Piiranha model settings")


class GatewayTest(BaseModel):
    """Configuration for a single gateway test."""
    name: str = Field(..., description="Test name: 'consecutive_digits' or 'name_dictionary'")
    enabled: bool = Field(default=True, description="Whether this test is enabled")
    threshold: Optional[int] = Field(default=None, description="Threshold for the test (e.g., min digits)")


class GatewayConfig(BaseModel):
    """Configuration for the gateway (early exit) logic."""
    enabled: bool = Field(default=True, description="Whether gateway mode is available")
    tests: List[GatewayTest] = Field(
        default_factory=lambda: [
            GatewayTest(name="consecutive_digits", enabled=True, threshold=5),
            GatewayTest(name="name_dictionary", enabled=True, threshold=None),
            GatewayTest(name="address_signals", enabled=True, threshold=4),
        ],
        description="List of gateway tests to run"
    )


class DetectionConfig(BaseModel):
    """Configuration for detection pipeline."""
    detector_order: List[str] = Field(
        default_factory=lambda: ["ner", "regex", "dict"],
        description="Order in which detectors are run"
    )
    passes: List[str] = Field(
        default_factory=lambda: ["raw", "normalized"],
        description="Text passes: 'raw' and/or 'normalized'"
    )


class ScoringRules(BaseModel):
    """Configuration for scoring adjustments."""
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum confidence score threshold")
    context_boost: float = Field(default=0.10, description="Score boost when context keyword found")
    multi_model_boost: float = Field(default=0.10, description="Score boost when multiple NER models agree on same entity")
    max_score: float = Field(default=0.99, description="Maximum score cap")
    account_no_context_score: float = Field(default=0.60, description="ACCOUNT_NUMBER score without context")
    account_min_digits: int = Field(default=8, description="Min digits for ACCOUNT_NUMBER without context")


class LuhnRetypeConfig(BaseModel):
    """Configuration for Luhn-based retyping of ACCOUNT_NUMBER candidates."""
    enabled: bool = Field(
        default=True,
        description=(
            "When enabled, ACCOUNT_NUMBER candidates that pass Luhn will be retyped to target_type "
            "to reduce false positives from payment card numbers."
        )
    )
    min_length: int = Field(
        default=13,
        description="Minimum digit length to consider for Luhn validation (typical card min is 13)."
    )
    max_length: int = Field(
        default=19,
        description="Maximum digit length to consider for Luhn validation (typical card max is 19)."
    )
    require_no_account_context: bool = Field(
        default=True,
        description=(
            "If true, only retype when ACCOUNT_NUMBER context keywords are NOT present nearby. "
            "Set to false to always retype Luhn-valid numbers regardless of account context."
        )
    )
    target_type: str = Field(
        default="CREDIT_CARD_NUMBER",
        description=(
            "Type to retype Luhn-valid ACCOUNT_NUMBER candidates into. "
            "Defaults to CREDIT_CARD_NUMBER."
        )
    )


class AddressNerFilterConfig(BaseModel):
    """Configuration for post-filtering NER-based ADDRESS entities."""
    enabled: bool = Field(
        default=True,
        description="Enable filtering of NER-based ADDRESS spans to reduce false positives."
    )
    sources: List[str] = Field(
        default_factory=lambda: ["ner"],
        description="Entity sources to apply the filter to (e.g., ['ner'])."
    )
    min_single_token_length: int = Field(
        default=4,
        description=(
            "Minimum length for single-token ADDRESS spans. "
            "Shorter single tokens (e.g., 'Thu', 'Kila') are dropped unless whitelisted."
        )
    )
    allow_single_token_digits: bool = Field(
        default=True,
        description=(
            "If true, single-token ADDRESS spans that contain digits are kept even if they are "
            "shorter than min_single_token_length."
        )
    )
    allowed_single_tokens: List[str] = Field(
        default_factory=list,
        description="Lowercase whitelist for single-token ADDRESS spans that should be kept."
    )
    require_digit: bool = Field(
        default=False,
        description="If true, require at least one digit in the ADDRESS span to keep it."
    )
    require_suffix: bool = Field(
        default=False,
        description=(
            "If true, require a street suffix (e.g., 'St', 'Ave') in the ADDRESS span to keep it."
        )
    )
    suffixes: List[str] = Field(
        default_factory=lambda: [
            "st", "street", "rd", "road", "ave", "avenue", "blvd", "lane", "ln",
            "drive", "dr", "way", "court", "ct", "place", "pl", "circle", "cir"
        ],
        description="Street suffixes used when require_suffix is enabled (lowercase)."
    )


class PostFiltersConfig(BaseModel):
    """Configuration for post-detection filters."""
    address_ner: AddressNerFilterConfig = Field(
        default_factory=AddressNerFilterConfig,
        description="Post-filter settings for NER-based ADDRESS entities."
    )


class NameListsConfig(BaseModel):
    """Configuration for name dictionary sources."""
    first_names: Optional[SourceRef] = Field(default=None, description="Source for first names list")
    last_names: Optional[SourceRef] = Field(default=None, description="Source for last names list")
    stopwords: Optional[SourceRef] = Field(default=None, description="Source for stopwords list")


class LoggingConfig(BaseModel):
    """Configuration for logging."""
    level: str = Field(default="INFO", description="Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    format: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s", description="Log format string")


# Type alias for pattern/keyword values: either a list of strings or a source reference
PatternValue = Union[List[str], SourceRef]


class PIIConfig(BaseModel):
    """Root configuration for PII detection."""
    models: ModelsConfig = Field(default_factory=ModelsConfig, description="Model selection and backend settings")
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    luhn_retype: LuhnRetypeConfig = Field(
        default_factory=LuhnRetypeConfig,
        description="Settings for Luhn-based retyping of ACCOUNT_NUMBER candidates."
    )
    post_filters: PostFiltersConfig = Field(
        default_factory=PostFiltersConfig,
        description="Post-detection filtering rules to reduce false positives."
    )

    # patterns and context_keywords can be either inline lists or source references
    # After resolution (in config_loader), these will only contain List[str] values
    patterns: Dict[str, PatternValue] = Field(
        default_factory=lambda: {
            "SSN": [
                r"\b\d{3}-\d{2}-\d{4}\b",
                r"\b\d{3} \d{2} \d{4}\b",
                r"\b\d{9}\b"
            ],
            "PHONE_NUMBER": [
                r"(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?:[-. ]?\d{1,5})?",
                r"\+\d{1,4}[-. ]?\d{2,4}[-. ]?\d{3,4}[-. ]?\d{3,4}(?:[-. ]?\d{1,4})?",
                r"\+?\d{1,4}[-. ]\d{4,6}[-. ]\d{4}",
            ],
            "DATE": [
                r"\b\d{4}-\d{2}-\d{2}\b",
                r"\b\d{1,2}/\d{1,2}/\d{4}\b",
                r"\b[A-Z][a-z]{2,8} \d{1,2},? \d{4}\b"
            ],
            "ACCOUNT_NUMBER": [
                r"\b\d{8,17}\b",
                r"\b[A-Z0-9]{2,}\d{6,}\b"
            ],
            "ADDRESS": [
                r"\b\d{1,5}\s+[A-Za-z0-9 .]+\s+(?:St|Street|Rd|Road|Ave|Avenue|Blvd|Lane|Ln|Drive|Dr|Way|Court|Ct|Place|Pl|Circle|Cir)\b(?:.{0,20}(?:Apt|Unit|#|Suite|Ste|Floor|Fl)\s*\w+)?(?:.{0,30}(?:\d{5}(?:-\d{4})?)?)?",
            ],
            "EMAIL": [
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
            ],
        },
        description="Regex patterns per entity type"
    )

    context_keywords: Dict[str, PatternValue] = Field(
        default_factory=lambda: {
            "SSN": ["ssn", "social security", "soc sec"],
            "PHONE_NUMBER": ["phone", "tel", "mobile", "cell", "fax", "contact"],
            "BIRTHDATE": ["dob", "date of birth", "born", "birthdate", "birth"],
            "ACCOUNT_NUMBER": ["account", "acct", "a/c", "iban", "routing", "swift", "bank"],
            "ADDRESS": ["address", "addr", "ship to", "billing", "street", "residence", "live at", "located at"],
            "PERSON": ["name", "mr", "mrs", "ms", "miss", "dr", "patient", "client", "customer", "employee", "applicant", "full name", "first name", "last name", "surname", "signed by"],
        },
        description="Context keywords for each entity type"
    )

    name_lists: Optional[NameListsConfig] = Field(
        default=None,
        description="External sources for name dictionary detector"
    )

    scores: Dict[str, float] = Field(
        default_factory=lambda: {
            "PERSON": 0.80,
            "LOCATION": 0.75,
            "SSN": 0.95,
            "PHONE_NUMBER": 0.85,
            "DATE": 0.75,
            "BIRTHDATE": 0.75,
            "ACCOUNT_NUMBER": 0.80,
            "ADDRESS": 0.70,
            "EMAIL": 0.90,
            "CREDIT_CARD_NUMBER": 0.95,
            "DRIVERS_LICENSE": 0.90,
            "ID_CARD": 0.90,
            "TAX_NUMBER": 0.90,
            "USERNAME": 0.85,
            "PASSWORD": 0.95,
            "ZIPCODE": 0.75,
        },
        description="Base confidence scores per entity type"
    )

    scoring_rules: ScoringRules = Field(default_factory=ScoringRules)
    context_window: int = Field(default=40, description="Characters to search for context keywords")
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="Logging configuration")
