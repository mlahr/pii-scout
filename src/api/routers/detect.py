import logging

from fastapi import APIRouter, HTTPException

from api.config import settings
from api.schemas import DetectRequest, DetectResponse, Entity, EntityTypesResponse, TimingStats

router = APIRouter()
logger = logging.getLogger(__name__)

# Will be set by main.py
pii_service = None


def set_pii_service(service):
    global pii_service
    pii_service = service


@router.post("/detect", response_model=DetectResponse)
async def detect_pii(request: DetectRequest):
    """Detect PII entities in the provided text."""
    if not pii_service or not pii_service.is_ready:
        raise HTTPException(status_code=503, detail="Service not ready")

    text_len = len(request.text)

    # Resolve gateway: request value overrides config default
    if request.gateway is not None:
        use_gateway = request.gateway
    elif pii_service.config:
        use_gateway = pii_service.config.gateway.enabled
    else:
        use_gateway = False

    # Resolve min_score: request value overrides config default
    if request.min_score is not None:
        min_score = request.min_score
    elif pii_service.config:
        min_score = pii_service.config.scoring_rules.min_score
    else:
        min_score = 0.0

    logger.debug(f"detect request: {text_len} chars, gateway={use_gateway}, min_score={min_score}")

    if text_len > settings.max_text_length:
        raise HTTPException(
            status_code=413,
            detail=f"Text exceeds maximum length of {settings.max_text_length}"
        )

    try:
        # Convert config_override to dict if provided
        config_override = None
        if request.config_override:
            config_override = request.config_override.model_dump(exclude_none=True)
            logger.debug(f"config overrides: {config_override}")

        # Convert entity_types enum list to set of strings
        entity_types_set = None
        if request.entity_types:
            entity_types_set = {t.value for t in request.entity_types}

        # Convert detectors enum list to set of strings
        detectors_set = None
        if request.detectors:
            detectors_set = {d.value for d in request.detectors}

        entities, stats = pii_service.detect(
            request.text, min_score, gateway=use_gateway,
            config_override=config_override,
            entity_types=entity_types_set,
            detectors=detectors_set
        )

        response_entities = [
            Entity(
                type=e["type"],
                text=e["text"],
                start=e["start"],
                end=e["end"],
                score=e["score"],
                source=e.get("sources", [e.get("source", "unknown")])
            )
            for e in entities
        ]

        # Safety-net: ensure only requested entity types are returned
        if entity_types_set:
            response_entities = [e for e in response_entities if e.type in entity_types_set]

        gateway_skipped = stats.get("gateway_skipped", False)
        total_ms = stats.get("total_ms", 0)
        logger.debug(f"detect result: {len(response_entities)} entities, gateway_skipped={gateway_skipped}, {total_ms:.1f}ms")

        if response_entities:
            entity_types = {}
            for e in response_entities:
                entity_types[e.type] = entity_types.get(e.type, 0) + 1
            logger.debug(f"entity breakdown: {entity_types}")

        meta = {
            "model_profile": pii_service.model_profile,
            "chars": text_len,
            "entity_count": len(response_entities),
            "gateway_mode": use_gateway,
            "gateway_skipped": gateway_skipped
        }

        timing_stats = None
        if request.include_stats:
            timing_stats = TimingStats(
                normalize_ms=stats.get("normalize_ms", 0),
                ner_ms=stats.get("ner_ms", 0),
                regex_ms=stats.get("regex_ms", 0),
                dict_ms=stats.get("dict_ms", 0),
                merge_ms=stats.get("merge_ms", 0),
                total_ms=total_ms
            )

        return DetectResponse(
            entities=response_entities,
            meta=meta,
            stats=timing_stats
        )

    except Exception as e:
        logger.exception("Detection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entity-types", response_model=EntityTypesResponse)
async def entity_types():
    """Return all entity types supported by the current configuration."""
    if not pii_service or not pii_service.is_ready:
        raise HTTPException(status_code=503, detail="Service not ready")

    config = pii_service.config
    types: set[str] = set()

    if config:
        types.update(config.patterns.keys())
        types.update(config.context_keywords.keys())
        types.update(config.scores.keys())

    return EntityTypesResponse(entity_types=sorted(types))
