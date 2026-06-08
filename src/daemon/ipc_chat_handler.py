"""IPC chat request handling for the daemon server."""

from __future__ import annotations

import time

from ..entity_zero_iteration import get_entity_state, run_pipeline
from ..response_cache.response_cache import _cache_weight


def handle_chat_request(request, llm_callable, response_cache, logger) -> dict:
    """Handle chat requests, including response-cache prewarming."""
    t0 = time.time()
    text = request.payload.get("text", "")
    debug = request.payload.get("debug", False)
    speaker_id = request.payload.get("speaker_id", "bcyq")
    content_origin = request.payload.get("content_origin", "direct_chat")
    author_id = request.payload.get("author_id", "")
    no_llm = request.payload.get("no_llm", True)
    entity = get_entity_state()

    try:
        from ..language_system.source_profiler import get_source_identity

        source_identity = get_source_identity(
            "ipc_chat",
            entity,
            speaker_id=speaker_id,
            content_origin=content_origin,
            author_id=author_id or None,
        )
    except Exception:
        source_identity = {
            "input_source": "ipc_chat",
            "speaker_id": str(speaker_id),
            "content_origin": str(content_origin),
            "author_id": str(author_id or speaker_id),
            "source_id": str(speaker_id),
        }

    try:
        from ..language_system.expression_feedback import consume_response

        consume_response(entity, text, entity.tick)
    except Exception as feedback_err:
        logger.debug(f"[IPCServer] expression feedback skipped: {feedback_err}")

    try:
        from ..language_system.clarification_learning import observe_reply

        observe_reply(
            entity,
            reply_text=text,
            now_ts=time.time(),
            source="ipc_chat",
            reply_event_id=str(request.id),
        )
    except Exception as observe_err:
        logger.debug(f"[IPCServer] clarification observe skipped: {observe_err}")

    cached_text, cache_sim = _probe_response_cache(entity, response_cache, logger)
    input_gate = min(1.0, float(len(str(text or ""))))
    cache_score = _cache_weight(cache_sim, threshold=0.90, steepness=20.0) * (1.0 - input_gate)
    pipeline_score = 1.0 - cache_score

    def serve_cache() -> dict:
        elapsed_ms = round((time.time() - t0) * 1000)
        logger.info(
            f"[IPCServer] cache hit sim={cache_sim:.3f} "
            f"weight={cache_score:.3f} {elapsed_ms}ms"
        )
        return {
            "response": {
                "text": cached_text,
                "confidence": cache_sim,
                "generation_time_ms": elapsed_ms,
            },
            "decision": {},
            "state_snapshot": _clean_state_snapshot(entity.to_state_snapshot()),
            "tick": entity.tick,
            "total_ms": elapsed_ms,
            "trace": [],
        }

    def serve_pipeline() -> dict:
        result = run_pipeline(
            raw_input=text,
            entity_state=entity,
            debug=debug,
            llm_callable=llm_callable,
            no_llm=no_llm,
            source_identity=source_identity,
        )
        safe = _safe_json_serializable(result)
        return {
            "response": safe.get("response", {}),
            "decision": safe.get("decision", {}),
            "state_snapshot": _clean_state_snapshot(safe.get("state_snapshot", {})),
            "tick": safe.get("tick", entity.tick),
            "total_ms": safe.get("total_ms", 0),
            "trace": safe.get("trace", []) if debug else [],
            "cx_recognized_words": safe.get("cx_recognized_words", []),
            "cx_social_intent": safe.get("cx_social_intent", "unknown"),
        }

    response = max(
        {
            "cache": (cache_score, serve_cache),
            "pipeline": (pipeline_score, serve_pipeline),
        }.items(),
        key=lambda item: item[1][0],
    )[1][1]()

    _update_source_profile(entity, response, source_identity, logger)
    return response


def _probe_response_cache(entity, response_cache, logger) -> tuple[str | None, float]:
    cached_text, cache_sim = None, 0.0
    try:
        from ..drive_system.drive_system import compute_drive_vector
        from ..pipeline_runner.utils import get_default_drive_params

        snapshot = entity.to_state_snapshot()
        drive_params = {
            "curiosity_param": snapshot.get("curiosity_param", 1.0),
            "max_info_gap_hours": snapshot.get("max_info_gap_hours", 24.0),
            "max_social_gap_hours": snapshot.get("max_social_gap_hours", 24.0),
            **get_default_drive_params(),
        }
        query_drive_vector = compute_drive_vector(snapshot, drive_params)
        has_cache = min(1.0, float(response_cache is not None and response_cache.size() > 0))
        noop_weight = 1.0 - has_cache
        cached_text, cache_sim = max(
            {
                "probe": (has_cache, lambda: response_cache.match(query_drive_vector)),
                "noop": (noop_weight, lambda: (None, 0.0)),
            }.items(),
            key=lambda item: item[1][0],
        )[1][1]()
    except Exception as err:
        logger.debug(f"[IPCServer] cache probe failed: {err}")
    return cached_text, cache_sim


def _update_source_profile(entity, response: dict, source_identity: dict, logger) -> None:
    try:
        from ..language_system.source_profiler import update_profile

        observations = entity._causal_observations
        last_delta = observations[-1]["delta"] if observations else {}
        update_profile(
            entity,
            source_identity.get("source_id", "external"),
            response.get("cx_recognized_words", []),
            response.get("cx_social_intent", "unknown"),
            last_delta,
            entity.tick,
            source_identity=source_identity,
        )
        entity.persist_to_file()
    except Exception as err:
        logger.warning(f"[SourceProfiler] update skipped: {err}")


def _clean_state_snapshot(raw: dict) -> dict:
    public_fields = {
        "tick", "energy", "loneliness", "fatigue", "stress",
        "boredom", "curiosity", "info_gap", "approach_drive", "avoid_drive",
        "somatic_tone", "anger", "anxiety", "fear", "joy", "sadness",
        "unresolved", "self_trust", "attachment", "empathy",
        "last_interaction_context",
    }
    return {key: value for key, value in raw.items() if key in public_fields}


def _safe_json_serializable(obj):
    if isinstance(obj, dict):
        return {key: _safe_json_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_json_serializable(value) for value in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    try:
        if hasattr(obj, "__dataclass_fields__"):
            return {
                field: _safe_json_serializable(getattr(obj, field))
                for field in obj.__dataclass_fields__
            }
        if hasattr(obj, "_asdict"):
            return obj._asdict()
        if hasattr(obj, "__dict__"):
            return {
                key: _safe_json_serializable(value)
                for key, value in vars(obj).items()
            }
    except Exception:
        pass
    return str(obj)
