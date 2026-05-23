"""Tests for PII configuration module."""

import json
import os
import tempfile
import pytest
import yaml
from pathlib import Path

from config.pii_config import PIIConfig, GatewayConfig, GatewayTest, DetectionConfig, ScoringRules, SourceRef, NameListsConfig, LoggingConfig
from config.config_loader import load_config, reset_config, get_default_config, apply_overrides, load_source_file, resolve_sources, setup_logging


class TestPIIConfigModels:
    """Test Pydantic models."""

    def test_default_config(self):
        config = PIIConfig()
        assert config.gateway.enabled is True
        assert len(config.gateway.tests) == 3
        assert config.gateway.tests[0].name == "consecutive_digits"
        assert config.gateway.tests[0].threshold == 5
        assert config.gateway.tests[2].name == "address_signals"
        assert config.gateway.tests[2].threshold == 4
        assert config.context_window == 40

    def test_gateway_config(self):
        cfg = GatewayConfig(
            enabled=False,
            tests=[GatewayTest(name="consecutive_digits", threshold=3)]
        )
        assert cfg.enabled is False
        assert cfg.tests[0].threshold == 3

    def test_detection_config(self):
        cfg = DetectionConfig(
            detector_order=["regex"],
            passes=["raw"]
        )
        assert cfg.detector_order == ["regex"]
        assert cfg.passes == ["raw"]

    def test_scoring_rules(self):
        rules = ScoringRules(
            context_boost=0.15,
            max_score=0.95
        )
        assert rules.context_boost == 0.15
        assert rules.max_score == 0.95
        assert rules.account_no_context_score == 0.60  # default

    def test_patterns_config(self):
        config = PIIConfig()
        assert "SSN" in config.patterns
        assert "EMAIL" in config.patterns
        assert len(config.patterns["SSN"]) == 3

    def test_scores_config(self):
        config = PIIConfig()
        assert config.scores["PERSON"] == 0.80
        assert config.scores["SSN"] == 0.95


class TestConfigLoader:
    """Test config loading functionality."""

    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_get_default_config(self):
        config = get_default_config()
        assert isinstance(config, PIIConfig)
        assert config.gateway.enabled is True

    def test_load_config_no_file(self):
        """Load config when no file exists should return defaults."""
        reset_config()
        config = load_config(path=None)
        assert isinstance(config, PIIConfig)

    def test_load_config_from_yaml(self):
        """Load config from a YAML file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({
                'gateway': {
                    'enabled': False,
                    'tests': [
                        {'name': 'consecutive_digits', 'enabled': True, 'threshold': 3}
                    ]
                },
                'context_window': 50
            }, f)
            temp_path = f.name

        try:
            reset_config()
            config = load_config(path=temp_path)
            assert config.gateway.enabled is False
            assert config.gateway.tests[0].threshold == 3
            assert config.context_window == 50
        finally:
            os.unlink(temp_path)

    def test_load_config_caching(self):
        """Verify config is cached."""
        reset_config()
        config1 = load_config(path=None)
        config2 = load_config(path=None)
        assert config1 is config2

    def test_load_config_file_not_found(self):
        """Loading non-existent file should raise error."""
        reset_config()
        with pytest.raises(FileNotFoundError):
            load_config(path="/nonexistent/path.yaml")


class TestApplyOverrides:
    """Test config override functionality."""

    def test_override_gateway_enabled(self):
        base = get_default_config()
        assert base.gateway.enabled is True

        overridden = apply_overrides(base, {"gateway_enabled": False})
        assert overridden.gateway.enabled is False
        # Original unchanged
        assert base.gateway.enabled is True

    def test_override_min_digits_threshold(self):
        base = get_default_config()
        overridden = apply_overrides(base, {"min_digits_threshold": 3})

        for test in overridden.gateway.tests:
            if test.name == "consecutive_digits":
                assert test.threshold == 3
                break

    def test_override_patterns(self):
        base = get_default_config()
        overridden = apply_overrides(base, {
            "patterns": {
                "CUSTOM": [r"\bCUSTOM-\d+\b"]
            }
        })
        assert "CUSTOM" in overridden.patterns
        assert overridden.patterns["CUSTOM"] == [r"\bCUSTOM-\d+\b"]
        # Original patterns preserved
        assert "SSN" in overridden.patterns

    def test_override_context_window(self):
        base = get_default_config()
        assert base.context_window == 40

        overridden = apply_overrides(base, {"context_window": 100})
        assert overridden.context_window == 100

    def test_override_detector_order(self):
        base = get_default_config()
        overridden = apply_overrides(base, {"detector_order": ["regex"]})
        assert overridden.detection.detector_order == ["regex"]

    def test_override_none_values_ignored(self):
        base = get_default_config()
        overridden = apply_overrides(base, {
            "gateway_enabled": None,
            "context_window": None
        })
        # Unchanged
        assert overridden.gateway.enabled is True
        assert overridden.context_window == 40


class TestExternalSources:
    """Test external source file loading."""

    def setup_method(self):
        reset_config()
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        reset_config()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_source_file_txt(self):
        """Load items from a .txt file."""
        txt_path = os.path.join(self.temp_dir, "patterns.txt")
        with open(txt_path, 'w') as f:
            f.write("pattern1\n")
            f.write("pattern2\n")
            f.write("# This is a comment\n")
            f.write("\n")  # Empty line
            f.write("pattern3\n")

        items = load_source_file(txt_path, Path(self.temp_dir))
        assert items == ["pattern1", "pattern2", "pattern3"]

    def test_load_source_file_json(self):
        """Load items from a .json file."""
        json_path = os.path.join(self.temp_dir, "keywords.json")
        with open(json_path, 'w') as f:
            json.dump(["kw1", "kw2", "kw3"], f)

        items = load_source_file(json_path, Path(self.temp_dir))
        assert items == ["kw1", "kw2", "kw3"]

    def test_load_source_file_relative_path(self):
        """Load file using path relative to config dir."""
        subdir = os.path.join(self.temp_dir, "data")
        os.makedirs(subdir)
        txt_path = os.path.join(subdir, "items.txt")
        with open(txt_path, 'w') as f:
            f.write("item1\nitem2\n")

        items = load_source_file("data/items.txt", Path(self.temp_dir))
        assert items == ["item1", "item2"]

    def test_load_source_file_not_found(self):
        """Error when source file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            load_source_file("nonexistent.txt", Path(self.temp_dir))

    def test_load_source_file_invalid_json(self):
        """Error when JSON file contains non-array."""
        json_path = os.path.join(self.temp_dir, "invalid.json")
        with open(json_path, 'w') as f:
            json.dump({"key": "value"}, f)

        with pytest.raises(ValueError, match="must contain an array"):
            load_source_file(json_path, Path(self.temp_dir))

    def test_load_source_file_unsupported_format(self):
        """Error for unsupported file formats."""
        xml_path = os.path.join(self.temp_dir, "data.xml")
        with open(xml_path, 'w') as f:
            f.write("<data></data>")

        with pytest.raises(ValueError, match="Unsupported source file format"):
            load_source_file(xml_path, Path(self.temp_dir))

    def test_resolve_sources_patterns(self):
        """Resolve SourceRef in patterns dict."""
        # Create source file
        patterns_path = os.path.join(self.temp_dir, "ssn_patterns.txt")
        with open(patterns_path, 'w') as f:
            f.write(r"\b\d{3}-\d{2}-\d{4}\b" + "\n")
            f.write(r"\b\d{9}\b" + "\n")

        # Create config with SourceRef
        config = PIIConfig(
            patterns={
                "SSN": SourceRef(source="ssn_patterns.txt"),
                "EMAIL": [r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"]
            }
        )

        resolved = resolve_sources(config, Path(self.temp_dir))

        # SSN patterns should be loaded from file
        assert resolved.patterns["SSN"] == [r"\b\d{3}-\d{2}-\d{4}\b", r"\b\d{9}\b"]
        # EMAIL patterns should remain inline
        assert resolved.patterns["EMAIL"] == [r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"]

    def test_resolve_sources_context_keywords(self):
        """Resolve SourceRef in context_keywords dict."""
        # Create source file
        kw_path = os.path.join(self.temp_dir, "ssn_keywords.txt")
        with open(kw_path, 'w') as f:
            f.write("ssn\n")
            f.write("social security\n")

        config = PIIConfig(
            context_keywords={
                "SSN": SourceRef(source="ssn_keywords.txt"),
                "PHONE_NUMBER": ["phone", "tel"]
            }
        )

        resolved = resolve_sources(config, Path(self.temp_dir))

        assert resolved.context_keywords["SSN"] == ["ssn", "social security"]
        assert resolved.context_keywords["PHONE_NUMBER"] == ["phone", "tel"]

    def test_load_config_with_external_sources(self):
        """Load config from YAML with external source references."""
        # Create patterns file
        patterns_dir = os.path.join(self.temp_dir, "patterns")
        os.makedirs(patterns_dir)
        custom_patterns_path = os.path.join(patterns_dir, "custom.txt")
        with open(custom_patterns_path, 'w') as f:
            f.write(r"\bCUSTOM-\d+\b" + "\n")

        # Create config YAML
        config_path = os.path.join(self.temp_dir, "config.yaml")
        with open(config_path, 'w') as f:
            yaml.dump({
                'patterns': {
                    'CUSTOM': {'source': 'patterns/custom.txt'},
                    'EMAIL': [r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b']
                },
                'context_window': 50
            }, f)

        config = load_config(path=config_path)

        assert config.patterns["CUSTOM"] == [r"\bCUSTOM-\d+\b"]
        assert config.patterns["EMAIL"] == [r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"]
        assert config.context_window == 50

    def test_source_ref_model(self):
        """Test SourceRef model."""
        ref = SourceRef(source="data/patterns.txt")
        assert ref.source == "data/patterns.txt"

    def test_name_lists_config_model(self):
        """Test NameListsConfig model."""
        cfg = NameListsConfig(
            first_names=SourceRef(source="data/first_names.txt"),
            last_names=SourceRef(source="data/last_names.txt"),
            stopwords=SourceRef(source="data/stopwords.json")
        )
        assert cfg.first_names.source == "data/first_names.txt"
        assert cfg.last_names.source == "data/last_names.txt"
        assert cfg.stopwords.source == "data/stopwords.json"

    def test_config_with_name_lists(self):
        """Test PIIConfig with name_lists field."""
        config = PIIConfig(
            name_lists=NameListsConfig(
                first_names=SourceRef(source="data/first_names.txt"),
                last_names=SourceRef(source="data/last_names.txt")
            )
        )
        assert config.name_lists is not None
        assert config.name_lists.first_names.source == "data/first_names.txt"
        assert config.name_lists.last_names.source == "data/last_names.txt"
        assert config.name_lists.stopwords is None  # Optional, not set

    def test_mixed_inline_and_external_patterns(self):
        """Test mixing inline and external patterns in same config."""
        # Create source file
        phone_patterns_path = os.path.join(self.temp_dir, "phone.txt")
        with open(phone_patterns_path, 'w') as f:
            f.write(r"\b\d{3}-\d{4}\b" + "\n")

        config_path = os.path.join(self.temp_dir, "config.yaml")
        with open(config_path, 'w') as f:
            yaml.dump({
                'patterns': {
                    'SSN': [r'\b\d{3}-\d{2}-\d{4}\b'],  # Inline
                    'PHONE_NUMBER': {'source': 'phone.txt'}  # External
                }
            }, f)

        config = load_config(path=config_path)

        # Both should work
        assert config.patterns["SSN"] == [r'\b\d{3}-\d{2}-\d{4}\b']
        assert config.patterns["PHONE_NUMBER"] == [r'\b\d{3}-\d{4}\b']

    def test_error_on_missing_source_file(self):
        """Error when referenced source file doesn't exist."""
        config_path = os.path.join(self.temp_dir, "config.yaml")
        with open(config_path, 'w') as f:
            yaml.dump({
                'patterns': {
                    'CUSTOM': {'source': 'nonexistent.txt'}
                }
            }, f)

        with pytest.raises(FileNotFoundError):
            load_config(path=config_path)


class TestLoggingConfig:
    """Test logging configuration."""

    def setup_method(self):
        reset_config()
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        reset_config()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_logging_config(self):
        """Test default logging config values."""
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.format == "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    def test_custom_logging_config(self):
        """Test custom logging config from dict."""
        config = LoggingConfig(level="DEBUG", format="%(levelname)s - %(message)s")
        assert config.level == "DEBUG"
        assert config.format == "%(levelname)s - %(message)s"

    def test_pii_config_has_logging(self):
        """Test that PIIConfig has logging field with defaults."""
        config = PIIConfig()
        assert config.logging is not None
        assert config.logging.level == "INFO"
        assert config.logging.format == "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    def test_load_logging_config_from_yaml(self):
        """Test loading logging config from YAML file."""
        config_path = os.path.join(self.temp_dir, "config.yaml")
        with open(config_path, 'w') as f:
            yaml.dump({
                'logging': {
                    'level': 'DEBUG',
                    'format': '%(levelname)s: %(message)s'
                }
            }, f)

        config = load_config(path=config_path)
        assert config.logging.level == "DEBUG"
        assert config.logging.format == "%(levelname)s: %(message)s"

    def test_setup_logging_uses_config(self):
        """Test that setup_logging applies config settings."""
        import logging
        config = PIIConfig(logging=LoggingConfig(level="WARNING"))
        setup_logging(config)
        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING

    def test_setup_logging_env_override(self):
        """Test that PII_LOG_LEVEL env var overrides config."""
        import logging
        config = PIIConfig(logging=LoggingConfig(level="WARNING"))
        os.environ["PII_LOG_LEVEL"] = "ERROR"
        try:
            setup_logging(config)
            root_logger = logging.getLogger()
            assert root_logger.level == logging.ERROR
        finally:
            del os.environ["PII_LOG_LEVEL"]
