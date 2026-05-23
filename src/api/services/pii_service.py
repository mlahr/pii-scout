import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

# Add repo root and src to path to import pii_detect and packages
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root))

from pii_detect import load_models, detect_pii, detect_pii_gateway
from config.config_loader import load_config, apply_overrides
from config.pii_config import PIIConfig

logger = logging.getLogger(__name__)


class PIIService:
    def __init__(
            self,
            model_profile: str = "spacy-fast",
            use_gpu: bool = True,
            ollama_base_url: str = "http://localhost:11434",
            ollama_model: str = "llama3.2",
            openrouter_api_key: str = "",
            openrouter_base_url: str = "https://openrouter.ai/api/v1",
            openrouter_model: str | None = None,
            piiranha_model_path: str | None = None,
            config_path: Optional[str] = None
    ):
        self.model_profile = model_profile
        self.use_gpu = use_gpu
        self.ollama_base_url = ollama_base_url
        self.ollama_model = ollama_model
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_base_url = openrouter_base_url
        self.openrouter_model = openrouter_model
        self.piiranha_model_path = piiranha_model_path
        self.config_path = config_path
        self._models: list = []
        self._loaded = False
        self._config: Optional[PIIConfig] = None

    def load(self) -> None:
        """Load PII detection model and config. Called at startup."""
        # Load config first to potentially override model profile
        try:
            self._config = load_config(path=self.config_path)
            logger.debug("PII config loaded")

            # Use model profile from config file if not overridden by env var
            if not os.environ.get('PII_MODEL_PROFILE') and self._config.models.profile:
                self.model_profile = self._config.models.profile
                logger.debug(f"Using model profile from config: {self.model_profile}")

            # Load openrouter settings from config if not already set
            if self.openrouter_model is None and self._config.models.openrouter:
                self.openrouter_model = self._config.models.openrouter.model
                self.openrouter_base_url = self._config.models.openrouter.base_url
                logger.debug(f"Using openrouter model from config: {self.openrouter_model}")

            # Load ollama settings from config if not already set
            if self._config.models.ollama:
                if self.ollama_model == "llama3.2":  # default value means not overridden
                    self.ollama_model = self._config.models.ollama.model
                if self.ollama_base_url == "http://localhost:11434":  # default
                    self.ollama_base_url = self._config.models.ollama.base_url

            # Load piiranha model path from config if not set via env var
            if self.piiranha_model_path is None:
                self.piiranha_model_path = self._config.models.piiranha.model_path
        except Exception as e:
            logger.debug(f"Config loading failed, using defaults: {e}")
            self._config = None

        logger.info(f"Loading PII model (profile={self.model_profile}, gpu={self.use_gpu})...")

        args = SimpleNamespace(
            models=self.model_profile,
            use_gpu=self.use_gpu,
            ollama_base_url=self.ollama_base_url,
            ollama_model=self.ollama_model,
            openrouter_api_key=self.openrouter_api_key,
            openrouter_base_url=self.openrouter_base_url,
            openrouter_model=self.openrouter_model,
            piiranha_model_path=self.piiranha_model_path
        )
        self._models = load_models(args)
        self._loaded = True
        model_types = ",".join(mt for _, _, mt in self._models)
        logger.info(f"PII model loaded successfully (type={model_types})")

        # Initialize dictionary detector if needed
        try:
            from detectors.name_dict_detector import initialize_detector

            init_kwargs = {}
            if self._config and self._config.name_lists:
                name_lists = self._config.name_lists
                if name_lists.first_names:
                    init_kwargs['first_names_path'] = name_lists.first_names.source
                if name_lists.last_names:
                    init_kwargs['last_names_path'] = name_lists.last_names.source
                if name_lists.stopwords:
                    init_kwargs['stopwords_path'] = name_lists.stopwords.source

            initialize_detector(**init_kwargs)
            logger.debug("Dictionary detector initialized")
        except Exception as e:
            logger.debug(f"Dictionary detector initialization failed: {e}")

        # Log startup configuration
        logger.debug(f"model: {self.model_profile} (type={model_types})")
        if self._config and self._config.gateway.enabled:
            enabled_tests = [t.name for t in self._config.gateway.tests if t.enabled]
            logger.debug(f"gateway: enabled, tests={enabled_tests}")
        else:
            logger.debug("gateway: disabled or not configured")

    @property
    def is_ready(self) -> bool:
        return self._loaded and len(self._models) > 0

    @property
    def model_type(self) -> str:
        return ",".join(mt for _, _, mt in self._models)

    @property
    def config(self) -> Optional[PIIConfig]:
        return self._config

    def detect(
            self, text: str, min_score: float = 0.0, gateway: bool = False,
            config_override: Optional[Dict[str, Any]] = None,
            entity_types: Optional[Set[str]] = None,
            detectors: Optional[Set[str]] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
        """Run PII detection on text.

        Args:
            text: Input text to analyze
            min_score: Minimum confidence score threshold
            gateway: If True, use gateway mode to skip model when no quick PII matches
            config_override: Optional dict of config overrides to apply
            entity_types: Optional set of entity type strings to return. None = all.
        """
        if not self.is_ready:
            raise RuntimeError("PII service not initialized")

        # Apply config overrides if provided
        effective_config = self._config
        if config_override and self._config:
            effective_config = apply_overrides(self._config, config_override)
        elif config_override:
            # No base config, try to create one with overrides
            from config.config_loader import get_default_config
            effective_config = apply_overrides(get_default_config(), config_override)

        if gateway:
            return detect_pii_gateway(
                text, self._models, min_score,
                detectors=detectors,
                config=effective_config,
                entity_types=entity_types
            )
        return detect_pii(
            text, self._models, min_score,
            detectors=detectors,
            config=effective_config,
            entity_types=entity_types
        )
