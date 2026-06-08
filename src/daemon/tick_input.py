"""Input preparation for daemon ticks."""

from __future__ import annotations

import hashlib
import time

from ..action_system.reach import read_response


NONE_SOURCE_IDENTITY = {
    "input_source": "none",
    "speaker_id": "none",
    "content_origin": "none",
    "author_id": "none",
    "source_id": "none",
}

EXTERNAL_SOURCE_IDENTITY = {
    "input_source": "external",
    "speaker_id": "bcyq",
    "content_origin": "direct_chat",
    "author_id": "bcyq",
    "source_id": "bcyq",
}

SIBLING_SOURCE_IDENTITY = {
    "input_source": "sibling",
    "speaker_id": "sibling",
    "content_origin": "sibling_channel",
    "author_id": "sibling",
    "source_id": "sibling",
}


def prepare_tick_input(entity, sibling_channel, logger) -> tuple[str | None, str, dict]:
    """Collect external or sibling input and run input-side feedback hooks."""
    user_input = None
    input_source = "none"
    source_identity = dict(NONE_SOURCE_IDENTITY)
    response_data = None

    try:
        response_data = read_response()
        if response_data:
            user_input = response_data.get("text", "")
            input_source = "external"
            source_identity = _get_source_identity("external", entity, EXTERNAL_SOURCE_IDENTITY)
            logger.info(f"[TickEngine] 用户回复已读取: {user_input[:50]}")
            if entity.consecutive_reaches_without_response > 0:
                logger.info(
                    f"[TickEngine] 用户回应了，consecutive_reaches 重置 "
                    f"({entity.consecutive_reaches_without_response} -> 0)"
                )
            entity.consecutive_reaches_without_response = 0
            entity.last_action_timestamp = time.time()
    except Exception as err:
        logger.warning(f"[TickEngine] 读取用户回复失败: {err}")
        user_input = None

    if not user_input and sibling_channel:
        try:
            sibling_msg = sibling_channel.poll()
            if sibling_msg:
                user_input = sibling_msg
                input_source = "sibling"
                source_identity = _get_source_identity("sibling", entity, SIBLING_SOURCE_IDENTITY)
                logger.info(f"[TickEngine] 姐妹说: {sibling_msg[:50]}")
        except Exception as err:
            logger.debug(f"[TickEngine] sibling poll failed: {err}")

    if user_input:
        try:
            from ..language_system.expression_feedback import consume_response

            consume_response(entity, user_input, entity.tick)
        except Exception as consume_err:
            logger.debug(f"[TickEngine] consume_response skipped: {consume_err}")

    if input_source == "external" and user_input:
        event_id = hashlib.sha256(
            ("external" + str(response_data.get("timestamp", 0.0)) + user_input).encode("utf-8")
        ).hexdigest()
        try:
            from ..language_system.clarification_learning import observe_reply

            observe_reply(
                entity,
                reply_text=user_input,
                now_ts=time.time(),
                source="external",
                reply_event_id=event_id,
            )
        except Exception as observe_err:
            logger.debug(f"[TickEngine] clarification observe skipped: {observe_err}")

    return user_input, input_source, source_identity


def _get_source_identity(input_source: str, entity, fallback: dict) -> dict:
    try:
        from ..language_system.source_profiler import get_source_identity

        return get_source_identity(input_source, entity)
    except Exception:
        return dict(fallback)
