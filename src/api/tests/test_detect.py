def test_detect_basic(client):
    response = client.post("/detect", json={"text": "John SSN 123-45-6789"})
    assert response.status_code == 200
    data = response.json()
    assert "entities" in data
    assert "meta" in data
    assert len(data["entities"]) == 2


def test_detect_empty_text_rejected(client):
    response = client.post("/detect", json={"text": ""})
    assert response.status_code == 422


def test_detect_missing_text_rejected(client):
    response = client.post("/detect", json={})
    assert response.status_code == 422


def test_detect_with_min_score(client):
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789",
        "min_score": 0.9
    })
    assert response.status_code == 200


def test_detect_with_stats(client):
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789",
        "include_stats": True
    })
    assert response.status_code == 200
    data = response.json()
    assert "stats" in data
    assert data["stats"] is not None
    assert "total_ms" in data["stats"]


def test_detect_without_stats(client):
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789",
        "include_stats": False
    })
    assert response.status_code == 200
    data = response.json()
    assert data["stats"] is None


def test_detect_invalid_min_score_low(client):
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789",
        "min_score": -0.1
    })
    assert response.status_code == 422


def test_detect_invalid_min_score_high(client):
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789",
        "min_score": 1.5
    })
    assert response.status_code == 422


def test_detect_response_structure(client):
    response = client.post("/detect", json={"text": "John SSN 123-45-6789"})
    data = response.json()

    # Check entity structure
    entity = data["entities"][0]
    assert "type" in entity
    assert "text" in entity
    assert "start" in entity
    assert "end" in entity
    assert "score" in entity
    assert "source" in entity

    # Check meta structure
    meta = data["meta"]
    assert "model_profile" in meta
    assert "chars" in meta
    assert "entity_count" in meta


def test_detect_entity_types_filter(client):
    """entity_types=['SSN'] should filter out PERSON from results."""
    response = client.post("/detect", json={
        "text": "John Smith SSN 123-45-6789",
        "entity_types": ["SSN"]
    })
    assert response.status_code == 200
    data = response.json()
    types = {e["type"] for e in data["entities"]}
    assert "SSN" in types
    assert "PERSON" not in types


def test_detect_entity_types_null_returns_all(client):
    """Omitting entity_types should return all types."""
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789"
    })
    assert response.status_code == 200
    data = response.json()
    types = {e["type"] for e in data["entities"]}
    assert "PERSON" in types
    assert "SSN" in types


def test_detect_entity_types_invalid_rejected(client):
    """Invalid entity type value should return 422."""
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789",
        "entity_types": ["INVALID_TYPE"]
    })
    assert response.status_code == 422


def test_detect_detectors_regex_dict(client, mock_pii_service):
    """detectors=['regex', 'dict'] should pass detectors set to service."""
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789",
        "detectors": ["regex", "dict"]
    })
    assert response.status_code == 200
    # Verify the service was called with the correct detectors set
    call_kwargs = mock_pii_service.detect.call_args
    assert call_kwargs.kwargs["detectors"] == {"regex", "dict"}


def test_detect_detectors_regex_only(client, mock_pii_service):
    """detectors=['regex'] should only pass regex detector."""
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789",
        "detectors": ["regex"]
    })
    assert response.status_code == 200
    call_kwargs = mock_pii_service.detect.call_args
    assert call_kwargs.kwargs["detectors"] == {"regex"}


def test_detect_detectors_omitted_passes_none(client, mock_pii_service):
    """Omitting detectors should pass None (run all)."""
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789"
    })
    assert response.status_code == 200
    call_kwargs = mock_pii_service.detect.call_args
    assert call_kwargs.kwargs["detectors"] is None


def test_detect_detectors_invalid_rejected(client):
    """Invalid detector value should return 422."""
    response = client.post("/detect", json={
        "text": "John SSN 123-45-6789",
        "detectors": ["invalid_detector"]
    })
    assert response.status_code == 422


def test_entity_types(client, mock_pii_service):
    """GET /entity-types should return sorted entity types from config."""
    from unittest.mock import PropertyMock, MagicMock

    mock_config = MagicMock()
    mock_config.patterns = {"SSN": [], "EMAIL": []}
    mock_config.context_keywords = {"SSN": [], "PERSON": []}
    mock_config.scores = {"SSN": 0.95, "EMAIL": 0.90, "PERSON": 0.80, "LOCATION": 0.75}

    type(mock_pii_service).config = PropertyMock(return_value=mock_config)

    response = client.get("/entity-types")
    assert response.status_code == 200
    data = response.json()
    assert data["entity_types"] == ["EMAIL", "LOCATION", "PERSON", "SSN"]


def test_entity_types_service_not_ready(client, mock_pii_service):
    """GET /entity-types should return 503 when service not ready."""
    mock_pii_service.is_ready = False
    response = client.get("/entity-types")
    assert response.status_code == 503
