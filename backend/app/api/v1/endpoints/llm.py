"""
LLM Agent API Endpoints
Provides chat-based interface with tool calling and rule-based local fallback.
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

try:
    import aiohttp
except ImportError:
    aiohttp = None

from backend.app.api.v1.endpoints.agent_suggestions import (
    FailedToolCallSchema,
    log_failed_tool_call,
)
from backend.core.llm_agent.tools import TOOL_REGISTRY, get_tool_schemas
from backend.core.services.blessing_scheduler import get_scheduler
from backend.core.services.population_manager import get_population_manager
from backend.core.services.rng_attunement_service import get_rng_service

# New async LLM / context layer (Phase 1 — ProviderRegistry + ContextModule).
from core.context import (
    AnatomyContextModule,
    AstrologyContextModule,
    ContextRequest,
    HardwareContextModule,
    SystemPromptBuilder,
)
from core.llm.base import collapse_stutter, visible_text
from core.llm.defaults import (
    DEFAULT_MODELS_BY_USE_CASE,
    KNOWN_FEATURED_MODEL_IDS,
    NEMOTRON_FREE_MODEL_ID,
)
from core.llm.retry import retry_with_backoff
from core.llm.usage import LLMUsageTracker, UsageRecord
from core.situation_geometry import DEFAULT_LAT, DEFAULT_LNG

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["llm"])


class ChatMessage(BaseModel):
    role: str
    content: str
    name: str | None = None  # Match core/llm/models.py ChatMessage
    tool_call_id: str | None = None  # Required by tool loop message injection


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    api_key: str | None = None
    provider: str | None = "auto"  # 'openai', 'anthropic', 'local', 'auto'
    model: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    system_prompt: str | None = None
    stream: bool = False
    tools: list | None = None
    include_astrology: bool | None = False
    include_anatomy: bool | None = False
    include_hardware: bool | None = False
    use_rag: bool | None = False
    astrology_data: dict | None = None
    debug_mode: bool | None = False
    connection_id: str | None = None


class ToolCallLog(BaseModel):
    tool_name: str
    arguments: dict
    status: str
    result: Any | None = None
    error: str | None = None


class ChatResponse(BaseModel):
    response: str
    tool_calls: list[ToolCallLog]
    debug_info: dict | None = None


# One sitting: do not re-mint these once a success is already on the job.
_ALREADY_GENERATED = frozenset(
    {
        "generate_single_outlook",
        "generate_prayer",
        "generate_blessing",
        "generate_epic_outlook",
        "run_working",
    }
)


def format_messages_for_llm(request_messages: list[ChatMessage], default_system_prompt: str):
    # Find any system messages in request_messages
    custom_system_parts = []
    for msg in request_messages:
        if msg.role == "system":
            custom_system_parts.append(msg.content)

    if custom_system_parts:
        full_system_prompt = f"{default_system_prompt}\n\nContext and details:\n" + "\n".join(custom_system_parts)
    else:
        full_system_prompt = default_system_prompt

    # Get all non-system messages
    non_system_messages = [msg for msg in request_messages if msg.role != "system"]

    # Skip any leading assistant messages (e.g. welcome message) to ensure it starts with a user message
    first_user_idx = 0
    while first_user_idx < len(non_system_messages) and non_system_messages[first_user_idx].role == "assistant":
        first_user_idx += 1

    chat_messages = []
    for msg in non_system_messages[first_user_idx:]:
        if msg.role in ("user", "assistant"):
            chat_messages.append({"role": msg.role, "content": msg.content})

    return full_system_prompt, chat_messages


TOOL_NAME_ALIASES: dict[str, str] = {
    "list_targets": "list_populations",
    "show_targets": "list_populations",
    "show_populations": "list_populations",
    "get_targets": "list_populations",
    "list_population": "list_populations",
    "start_blessing": "start_automation",
    "stop_blessing": "stop_automation",
    "begin_session": "start_automation",
    "get_session": "get_automation_status",
    "session_status": "get_automation_status",
    "list_session": "get_automation_stats",
    "get_statistics": "get_system_status",
    "broadcast_crystal": "broadcast_healing",
    "set_scalar_frequency": "set_audio_frequency",
    "set_rng_bias": "create_rng_session",
    "calibrate_rng": "create_rng_session",
    "set_crystal_intent": "broadcast_healing",
    "get_night_sky": "get_celestial_night_sky",
    "night_sky": "get_celestial_night_sky",
    "celestial_sky": "get_celestial_night_sky",
    "get_dharani": "get_dharani_text",
    "dharani_text": "get_dharani_text",
    "dharani": "get_dharani_text",
    "timing_wheel": "get_auspicious_timing_details",
    "get_timing_wheel": "get_auspicious_timing_details",
    "world_crises": "get_active_world_crises",
    "get_world_crises": "get_active_world_crises",
    "active_crises": "get_active_world_crises",
    "living_ritual": "trigger_living_ritual_broadcast",
    "living_ritual_broadcast": "trigger_living_ritual_broadcast",
}

ARG_ALIASES: dict[str, str] = {
    "intent": "custom_context",
    "intention": "custom_context",
    "focus": "custom_context",
    "context": "custom_context",
    "aspiration": "custom_context",
    "topic": "custom_context",
    "subject": "custom_context",
    "target": "population_ids",
    "targets": "population_ids",
    "duration": "duration_minutes",
    "minutes": "duration_minutes",
    "time": "duration_minutes",
    "voice": "edge_voice",
    "speed": "rate",
    "freq": "frequency",
    "hz": "frequency",
}


def _resolve_tool_name(name: str) -> str:
    return TOOL_NAME_ALIASES.get(name, name)


def _normalize_args(args: dict) -> dict:
    """Map LLM-emitted argument names to actual function parameter names."""

    normalized = {}
    for key, value in args.items():
        normalized[ARG_ALIASES.get(key, key)] = value
    return normalized


def _parse_text_tool_calls(content: str) -> list[dict[str, Any]]:
    """Extract tool calls from LLM text output when native tool_calls is empty.

    Handles three common text-mode formats:
    1. JSON blocks: {"tool": "name", "arguments": {...}}
    2. XML tags: <tool_call>name</tool_call> or <tool_call>{"name":...}</tool_call>
    3. Code blocks: ```json\n{"tool":...}\n```
    """
    import re as _re

    results: list[dict[str, Any]] = []

    for m in _re.finditer(r"<tool_call>(.*?)</tool_call>", content, _re.DOTALL):
        inner = m.group(1).strip()
        if inner.startswith("{"):
            try:
                parsed = json.loads(inner)
                name = parsed.get("tool") or parsed.get("name") or parsed.get("function") or ""
                args = parsed.get("arguments") or parsed.get("parameters") or parsed.get("args") or {}
                if name:
                    results.append({"name": name.strip(), "arguments": args if isinstance(args, dict) else {}})
            except json.JSONDecodeError:
                pass
        elif "<arg_key>" in inner or "<arg>" in inner:
            name = inner.split("<")[0].strip()
            args: dict[str, Any] = {}
            for pair in _re.finditer(
                r"<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)</arg_value>",
                inner,
                _re.DOTALL,
            ):
                args[pair.group(1).strip()] = pair.group(2).strip()
            for pair in _re.finditer(
                r'<arg\s+name=["\'](.*?)["\']>(.*?)</arg>',
                inner,
                _re.DOTALL,
            ):
                args[pair.group(1).strip()] = pair.group(2).strip()
            if name:
                results.append({"name": name, "arguments": args})
        elif inner:
            results.append({"name": inner.strip(), "arguments": {}})

    scan_content = _re.sub(r"<tool_call>.*?</tool_call>", " ", content, flags=_re.DOTALL)

    i = 0
    while i < len(scan_content):
        if scan_content[i] != "{":
            i += 1
            continue
        depth = 0
        start = i
        while i < len(scan_content):
            if scan_content[i] == "{":
                depth += 1
            elif scan_content[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            break
        candidate = scan_content[start : i + 1]
        i += 1
        if len(candidate) < 15:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        name = parsed.get("tool") or parsed.get("name") or parsed.get("function") or ""
        args = parsed.get("arguments") or parsed.get("parameters") or parsed.get("args") or {}
        if name and isinstance(name, str):
            results.append({"name": name.strip(), "arguments": args if isinstance(args, dict) else {}})
    return results


async def execute_tool_locally(name: str, args: dict) -> Any:
    """Helper to execute a tool function from the tool registry"""
    import asyncio

    if name not in TOOL_REGISTRY:
        resolved = _resolve_tool_name(name)
        if resolved in TOOL_REGISTRY:
            name = resolved
        else:
            raise ValueError(f"Tool {name} not found in registry")

    tool_func = TOOL_REGISTRY[name]
    args = _normalize_args(args)
    logger.info(f"🔧 Executing tool {name} with args: {args}")

    # Special case: avoid self-HTTP calls by accessing services directly
    # This prevents deadlocks when tools call back to the same server
    if name == "list_populations":
        pm = get_population_manager()
        active_only = args.get("active_only", False)
        category = args.get("category")
        urgent_only = args.get("urgent_only", False)
        pops = [p.to_dict() for p in pm.get_all_populations()]
        if active_only:
            pops = [p for p in pops if p.get("is_active")]
        if category:
            pops = [p for p in pops if p.get("category") == category]
        if urgent_only:
            pops = [p for p in pops if p.get("is_urgent")]
        # Dedup by name so a seeded "California" × N ledger cannot flood
        # the follow-up prompt (Nemotron then stutter-repeats the name).
        unique: list[dict] = []
        seen: set[str] = set()
        for pop in pops:
            name = str(pop.get("name") or pop.get("id") or "").strip()
            key = name.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(
                {
                    "id": pop.get("id"),
                    "name": name,
                    "category": pop.get("category"),
                    "is_active": pop.get("is_active"),
                    "is_urgent": pop.get("is_urgent"),
                    "mantra_preference": pop.get("mantra_preference"),
                    "intentions": (pop.get("intentions") or [])[:4],
                }
            )
            if len(unique) >= 30:
                break
        return unique
    elif name == "get_population_statistics":
        pm = get_population_manager()
        stats = pm.get_statistics()
        return {
            "total_populations": stats.get("total_populations", 0),
            "active_populations": stats.get("active_populations", 0),
            "total_blessings_sent": stats.get("total_blessings_sent", 0),
            "total_mantras_repeated": stats.get("total_mantras_repeated", 0),
        }
    elif name == "create_population":
        from backend.core.services.population_manager import PopulationCategory, SourceType

        pm = get_population_manager()
        cat_str = args.get("category", "custom")
        src_str = args.get("source_type", "manual")
        try:
            category = PopulationCategory(cat_str) if isinstance(cat_str, str) else cat_str
        except ValueError:
            category = PopulationCategory.CUSTOM
        try:
            source_type = SourceType(src_str) if isinstance(src_str, str) else src_str
        except ValueError:
            source_type = SourceType.MANUAL
        pop = pm.create_population(
            name=args.get("name", "Untitled Population"),
            description=args.get("description", ""),
            category=category,
            source_type=source_type,
            directory_path=args.get("directory_path"),
            mantra_preference=args.get("mantra_preference", "chenrezig"),
            intentions=args.get("intentions", ["love", "healing", "peace"]),
            priority=args.get("priority", 5),
            is_urgent=args.get("is_urgent", False),
        )
        return pop.to_dict() if pop else None
    elif name == "update_population":
        pm = get_population_manager()
        pop = pm.update_population(args.get("population_id"), **args)
        return pop.to_dict() if pop else None
    elif name == "start_automation":
        from backend.core.services.blessing_scheduler import SchedulerConfig, SchedulerMode, get_scheduler

        scheduler = get_scheduler()
        config = SchedulerConfig(
            mode=SchedulerMode(args.get("mode", "round_robin")),
            duration_per_population=args.get("duration_per_population", 1800),
            transition_pause=args.get("transition_pause", 30),
            link_rng=args.get("link_rng", True),
            auto_dedicate=args.get("auto_dedicate", True),
            continuous_mode=args.get("continuous_mode", True),
            only_active=args.get("only_active", True),
            min_priority=args.get("min_priority", 1),
        )
        session_id = scheduler.start_automation(config=config)
        session = scheduler.sessions.get(session_id)
        queue_len = len(session.populations_queue) if session else 0
        return {"session_id": session_id, "populations_in_queue": queue_len}
    elif name == "stop_automation":
        from backend.core.services.blessing_scheduler import get_scheduler

        scheduler = get_scheduler()
        result = scheduler.stop_automation(args.get("session_id"))
        return result
    elif name == "get_automation_status":
        from backend.core.services.blessing_scheduler import get_scheduler

        scheduler = get_scheduler()
        status_info = scheduler.get_current_status(args.get("session_id"))
        return status_info if status_info is not None else {}
    elif name == "get_automation_stats":
        from backend.core.services.blessing_scheduler import get_scheduler

        scheduler = get_scheduler()
        return scheduler.get_session_stats(args.get("session_id"))
    elif name == "pause_automation":
        from backend.core.services.blessing_scheduler import get_scheduler

        scheduler = get_scheduler()
        success = scheduler.pause_automation(args.get("session_id"))
        return {
            "success": success,
            "message": "Automation paused successfully" if success else "Failed to pause automation",
        }
    elif name == "resume_automation":
        from backend.core.services.blessing_scheduler import get_scheduler

        scheduler = get_scheduler()
        success = scheduler.resume_automation(args.get("session_id"))
        return {
            "success": success,
            "message": "Automation resumed successfully" if success else "Failed to resume automation",
        }
    elif name == "create_rng_session":
        from backend.core.services.rng_attunement_service import get_rng_service

        service = get_rng_service()
        session_id = service.create_session(
            session_id=args.get("session_id"),
            baseline_tone_arm=args.get("baseline_tone_arm", 5.0),
            sensitivity=args.get("sensitivity", 1.0),
        )
        return {"session_id": session_id}
    elif name == "get_rng_reading":
        from backend.core.services.rng_attunement_service import get_rng_service

        service = get_rng_service()
        reading = service.get_reading(args.get("session_id"))
        if reading:
            return {
                "timestamp": reading.timestamp,
                "raw_value": reading.raw_value,
                "tone_arm": reading.tone_arm,
                "needle_position": reading.needle_position,
                "needle_state": reading.needle_state.value
                if hasattr(reading.needle_state, "value")
                else reading.needle_state,
                "quality": reading.quality.value if hasattr(reading.quality, "value") else reading.quality,
                "entropy": reading.entropy,
                "coherence": reading.coherence,
                "trend": reading.trend,
                "floating_needle_score": reading.floating_needle_score,
            }
        return {}
    elif name == "stop_rng_session":
        from backend.core.services.rng_attunement_service import get_rng_service

        service = get_rng_service()
        session_id = args.get("session_id")
        summary = service.get_session_summary(session_id) or {}
        service.stop_session(session_id)
        return summary
    elif name == "create_blessing_slideshow":
        from backend.core.services.blessing_slideshow_service import (
            IntentionSet,
            IntentionType,
            MantraType,
            get_blessing_slideshow_service,
        )

        service = get_blessing_slideshow_service()
        intentions = [IntentionType(i) for i in args.get("intentions", ["love", "healing", "peace"])]
        intention_set = IntentionSet(
            primary_mantra=MantraType(args.get("mantra", "chenrezig")),
            intentions=intentions,
            repetitions_per_photo=args.get("repetitions_per_photo", 108),
            dedication=args.get("dedication", "May all beings benefit"),
        )
        session_id = service.create_session(
            directory_path=args.get("directory_path"),
            intention_set=intention_set,
            loop_mode=args.get("loop_mode", True),
            display_duration_ms=args.get("display_duration_ms", 2000),
            rng_session_id=args.get("rng_session_id"),
        )
        session = service.sessions.get(session_id)
        total_photos = len(session.photos) if session else 0
        return {"session_id": session_id, "total_photos": total_photos}
    elif name == "get_current_slide":
        from backend.core.services.blessing_slideshow_service import get_blessing_slideshow_service

        service = get_blessing_slideshow_service()
        slide_info = service.get_current_slide(args.get("session_id"))
        return slide_info if slide_info is not None else {}
    elif name == "stop_slideshow":
        from backend.core.services.blessing_slideshow_service import get_blessing_slideshow_service

        service = get_blessing_slideshow_service()
        stats = service.stop_session(args.get("session_id"))
        return stats
    elif name == "forge_sigil":
        from backend.core.services.sigil_service import sigil_service

        return await sigil_service.forge_sigil(args.get("intention"), args.get("kamea", "saturn"))
    elif name == "cast_tarot_spread":
        from backend.core.services.divination_service import divination_service

        res = divination_service.draw_tarot(args.get("count", 3))
        return {"cards": res}
    elif name == "cast_i_ching":
        from backend.core.services.divination_service import divination_service

        return divination_service.cast_i_ching()
    elif name == "cast_geomancy":
        from backend.core.services.divination_service import divination_service

        return divination_service.cast_geomancy()

    elif name == "search_grimoire_correspondences":
        from backend.core.services.grimoire_service import grimoire_service

        return grimoire_service.search(args.get("query", ""))
    elif name == "get_planetary_hours_and_transits":
        import datetime

        from backend.core.services.grimoire_service import grimoire_service
        from backend.core.services.vajra_service import vajra_service

        now = datetime.datetime.now()
        astro_data = await vajra_service._get_astrology_data()
        hour_data = grimoire_service.get_planetary_hours(now.hour, now.weekday())
        return {"astrology": astro_data, "planetary_hour": hour_data, "timestamp": time.time()}
    elif name == "get_random_buddha":
        from core.eighty_eight_buddhas import get_eighty_eight_buddhas

        svc = get_eighty_eight_buddhas()
        category = args.get("category")
        b = svc.random_buddha(category=category)
        narrative = svc.generate_buddha_narrative(b.name_chinese, depth="contemplation")
        return {
            "buddha": {
                "name_chinese": b.name_chinese,
                "name_pinyin": b.name_pinyin,
                "name_sanskrit": b.name_sanskrit,
                "category": b.category,
                "meaning": b.meaning,
                "realm": b.realm,
                "light": b.light,
            },
            "narrative": narrative.get("narrative", ""),
        }
    elif name == "generate_buddha_narrative":
        from core.eighty_eight_buddhas import get_eighty_eight_buddhas

        svc = get_eighty_eight_buddhas()
        return svc.generate_buddha_narrative(
            buddha_name=args.get("buddha_name", ""),
            depth=args.get("depth", "contemplation"),
        )
    elif name == "get_88_buddhas_liturgy":
        from core.eighty_eight_buddhas import get_eighty_eight_buddhas

        svc = get_eighty_eight_buddhas()
        return svc.get_confession_sequence()
    elif name == "recite_buddha_name":
        from core.eighty_eight_buddhas import get_eighty_eight_buddhas

        svc = get_eighty_eight_buddhas()
        b = svc.get_buddha_by_name(args.get("buddha_name", ""))
        if not b:
            return {"error": f"Buddha not found: {args.get('buddha_name')}"}
        return {
            "buddha": b.name_chinese,
            "pinyin": b.name_pinyin,
            "message": f"Recitation of {b.name_chinese} ({b.name_pinyin}) would play via Edge TTS.",
        }
    elif name == "start_buddha_recitation":
        import asyncio

        from core.buddha_recitation_loop import get_recitation_loop

        loop = get_recitation_loop()
        if loop.state.running:
            return {"status": "already_running"}
        intention = args.get("intention", "愿一切众生离苦得乐")
        interval = args.get("interval_seconds", 3.0)
        mala_cycles = args.get("mala_cycles")
        try:
            running_loop = asyncio.get_event_loop()
            if running_loop.is_running():
                running_loop.create_task(
                    loop.start(intention=intention, interval_seconds=interval, mala_cycles=mala_cycles)
                )
            else:
                asyncio.run(loop.start(intention=intention, interval_seconds=interval, mala_cycles=mala_cycles))
        except RuntimeError:
            asyncio.run(loop.start(intention=intention, interval_seconds=interval, mala_cycles=mala_cycles))
        return loop.get_status()
    elif name == "stop_buddha_recitation":
        from core.buddha_recitation_loop import get_recitation_loop

        loop = get_recitation_loop()
        await loop.stop()
        return loop.get_status()
    elif name == "get_buddha_recitation_status":
        from core.buddha_recitation_loop import get_recitation_loop

        return get_recitation_loop().get_status()
    elif name == "check_saka_dawa":
        from core.auspicious_timing import check_saka_dawa as _check_saka_dawa

        return _check_saka_dawa()
    elif name == "run_working":
        from core.working import run_working as _run_working

        return _run_working(
            intention=args.get("intention", ""),
            target=args.get("target") or "all beings",
            broadcast=bool(args.get("broadcast", True)),
            duration_minutes=int(args.get("duration_minutes") or 5),
        )
    elif name == "generate_single_outlook":
        # Call the service directly. The HTTP tool used to POST back into
        # this same FastAPI worker; generate_single blocked the event loop
        # and the chat job's 25s wait_for then discarded the finished result.
        from container import container

        return await asyncio.to_thread(
            container.outlook.generate_single,
            lat=float(args.get("lat") or DEFAULT_LAT),
            lon=float(args.get("lon") or DEFAULT_LNG),
            languages=args.get("languages") or ["English"],
            genre=args.get("genre") or "healing",
            custom_context=args.get("custom_context"),
            realm_id=args.get("realm_id"),
            population_ids=args.get("population_ids"),
            character_ids=args.get("character_ids"),
            excluded_forces=args.get("excluded_forces"),
            include_dialogue=bool(args.get("include_dialogue", False)),
            model=args.get("model") or NEMOTRON_FREE_MODEL_ID,
        )
    elif name == "generate_epic_outlook":
        from container import container

        return await asyncio.to_thread(
            container.outlook.generate_epic,
            lat=float(args.get("lat") or DEFAULT_LAT),
            lon=float(args.get("lon") or DEFAULT_LNG),
            languages=args.get("languages") or ["English"],
            genre=args.get("genre") or "alchemist",
            stages=int(args.get("stages") or 9),
            custom_context=args.get("custom_context"),
            realm_id=args.get("realm_id"),
            population_ids=args.get("population_ids"),
            character_ids=args.get("character_ids"),
            excluded_forces=args.get("excluded_forces"),
            include_dialogue=bool(args.get("include_dialogue", False)),
            model=args.get("model") or NEMOTRON_FREE_MODEL_ID,
        )
    elif name == "forge_witness":
        from core.working import attach_witness_image

        return attach_witness_image(str(args.get("working_id") or ""))
    elif name == "check_auspicious_timing":
        from core.auspicious_timing import check_auspicious_window

        return check_auspicious_window(args.get("genre", "healing")).to_dict()
    elif name == "generate_character":
        from core.character_generator import CharacterGenerator

        gen = CharacterGenerator()
        sheet = gen.generate(use_llm=False)
        return sheet.to_dict()
    elif name == "generate_image":
        from backend.core.llm_agent.tools import _AGENT_DISPATCH

        return await _AGENT_DISPATCH(
            prompt=args.get("prompt", ""),
            provider=args.get("provider"),
            model=args.get("model"),
            size=args.get("size", "1024x1024"),
            quality=args.get("quality", "standard"),
            aspect_ratio=args.get("aspect_ratio"),
            subject_reference=args.get("subject_reference"),
        )
    elif (
        name == "start_character_journey"
        or name == "advance_journey"
        or name == "get_journey_status"
        or name == "run_full_journey"
    ):
        from container import container
        from modules.radionics_operator import ToolDispatcher

        disp = ToolDispatcher(container)
        return disp.dispatch(name, args)
    elif name == "get_celestial_night_sky":
        from backend.core.llm_agent.tools import get_celestial_night_sky

        return get_celestial_night_sky(
            latitude=float(args.get("latitude") or args.get("lat") or DEFAULT_LAT),
            longitude=float(args.get("longitude") or args.get("lon") or args.get("lng") or DEFAULT_LNG),
            timestamp=float(args.get("timestamp")) if args.get("timestamp") is not None else None,
        )
    elif name == "get_dharani_text":
        from backend.core.llm_agent.tools import get_dharani_text

        return get_dharani_text(
            dharani_id_or_name=str(
                args.get("dharani_id_or_name") or args.get("dharani_id") or args.get("name") or args.get("id") or ""
            )
        )
    elif name == "get_auspicious_timing_details":
        from backend.core.llm_agent.tools import get_auspicious_timing_details

        return get_auspicious_timing_details(
            latitude=float(args.get("latitude") or args.get("lat") or DEFAULT_LAT),
            longitude=float(args.get("longitude") or args.get("lon") or args.get("lng") or DEFAULT_LNG),
        )
    elif name == "get_active_world_crises":
        from backend.core.llm_agent.tools import get_active_world_crises

        return get_active_world_crises()
    elif name == "trigger_living_ritual_broadcast":
        from backend.core.llm_agent.tools import trigger_living_ritual_broadcast

        return trigger_living_ritual_broadcast(
            intention=str(args.get("intention") or "May all beings be free from suffering"),
            target=str(args.get("target") or "all beings"),
            ritual_type=str(args.get("ritual_type") or "healing"),
            duration_minutes=int(args.get("duration_minutes") or 5),
            recite_with_tts=bool(args.get("recite_with_tts", False)),
        )
    else:
        # Fallback: call the tool function directly (detect if async or sync)
        import asyncio as _asyncio
        import inspect

        if inspect.iscoroutinefunction(tool_func):
            return await tool_func(**args)
        # Run sync tool in a thread pool to avoid blocking the event loop
        # (sync tools often make HTTP requests back to this server, which
        # would deadlock if run on the event loop thread)
        loop = _asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: tool_func(**args))


async def run_rule_based_fallback(query: str) -> ChatResponse:
    """
    Intelligent fallback system that matches natural language commands
    and executes tools directly on the backend.
    """
    query_lower = query.lower().strip()
    tool_calls = []
    response_text = ""

    # 1. Start Automation
    if re.search(
        r"\b(start|begin|activate|turn\s*on|enable)\s*(the\s*)?(automation|scheduler|rotation|cycle)\b", query_lower
    ):
        try:
            res = await execute_tool_locally("start_automation", {})
            tool_calls.append(ToolCallLog(tool_name="start_automation", arguments={}, status="success", result=res))
            response_text = (
                f"🔮 **Vajra.Stream Automation Initiated**\n\n"
                f"I have successfully activated the automated blessing rotation.\n"
                f"- **Session ID**: `{res.get('session_id', '')[:28]}…`\n"
                f"- **Populations in queue**: {res.get('populations_in_queue')}\n"
                f"- **Status**: Continuous rotation started."
            )
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="start_automation", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to start automation: {str(e)}"

    # 2. Stop Automation
    elif re.search(
        r"\b(stop|pause|suspend|disable|turn\s*off|end)\s*(the\s*)?(automation|scheduler|rotation|cycle)\b", query_lower
    ):
        try:
            scheduler = get_scheduler()
            active_sessions = list(scheduler.sessions.keys())
            if active_sessions:
                session_id = active_sessions[0]
                res = await execute_tool_locally("stop_automation", {"session_id": session_id})
                tool_calls.append(
                    ToolCallLog(
                        tool_name="stop_automation", arguments={"session_id": session_id}, status="success", result=res
                    )
                )
                response_text = (
                    f"🛑 **Vajra.Stream Automation Stopped**\n\n"
                    f"I have stopped the active scheduler rotation session (`{session_id}`).\n"
                    f"- **Total duration**: {res.get('total_duration', 0):.1f} seconds\n"
                    f"- **Completed cycles**: {res.get('cycle_count', 0)}\n"
                    f"- **Total photos blessed**: {res.get('total_photos_blessed', 0)}\n"
                    f"- **Total mantras repeated**: {res.get('total_mantras', 0)}"
                )
            else:
                response_text = "ℹ️ No active automation scheduler session was found running."
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="stop_automation", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to stop automation: {str(e)}"

    # 3. List Populations
    elif re.search(r"\b(list|show|view|get)\s*(the\s*)?(populations|targets)\b", query_lower):
        try:
            res = await execute_tool_locally("list_populations", {})
            tool_calls.append(ToolCallLog(tool_name="list_populations", arguments={}, status="success", result=res))
            if res:
                response_text = (
                    "👥 **Vajra.Stream Target Populations**\n\nHere are the registered blessing target populations:\n\n"
                )
                for pop in res:
                    response_text += (
                        f"- **{pop.get('name')}** (Category: `{pop.get('category')}`)\n"
                        f"  - Intentions: {', '.join(pop.get('intentions', []))}\n"
                        f"  - Priority: {pop.get('priority')}/10 | Photo Count: {pop.get('photo_count')}\n"
                    )
            else:
                response_text = "ℹ️ No populations are registered. Go to Targets to add one!"
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="list_populations", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to list populations: {str(e)}"

    # 4. Get Population Statistics
    elif re.search(
        r"\b(stats|statistics|overall\s*stats|summary)\s*(of\s*populations|across\s*populations|of\s*blessings)?\b",
        query_lower,
    ):
        try:
            res = await execute_tool_locally("get_population_statistics", {})
            tool_calls.append(
                ToolCallLog(tool_name="get_population_statistics", arguments={}, status="success", result=res)
            )
            response_text = (
                f"📈 **Vajra.Stream System-Wide Blessing Stats**\n\n"
                f"- **Total Blessings Sent**: {res.get('total_blessings_sent', 0)}\n"
                f"- **Total Mantras Repeated**: {res.get('total_mantras_repeated', 0)}\n"
                f"- **Total Blessing Duration**: {res.get('total_blessing_duration', 0):.1f} seconds\n"
                f"- **Active Populations Count**: {res.get('total_populations', 0)}"
            )
        except Exception as e:
            tool_calls.append(
                ToolCallLog(tool_name="get_population_statistics", arguments={}, status="error", error=str(e))
            )
            response_text = f"❌ Failed to retrieve statistics: {str(e)}"

    # 5. Start RNG Session
    elif re.search(
        r"\b(start|create|begin|activate)\s*(a\s*)?(rng|random\s*number\s*generator|attunement|needle)\s*(session)?\b",
        query_lower,
    ):
        try:
            res = await execute_tool_locally("create_rng_session", {"baseline_tone_arm": 5.0, "sensitivity": 1.0})
            tool_calls.append(
                ToolCallLog(
                    tool_name="create_rng_session",
                    arguments={"baseline_tone_arm": 5.0, "sensitivity": 1.0},
                    status="success",
                    result=res,
                )
            )
            response_text = (
                f"🔮 **RNG Attunement Session Created**\n\n"
                f"The random number generator is now capturing local quantum fluctuations.\n"
                f"- **Session ID**: `{res.get('session_id')}`\n"
                f"- Tone Arm Baseline calibrated to 5.0."
            )
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="create_rng_session", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to start RNG session: {str(e)}"

    # 6. Stop RNG Session
    elif re.search(
        r"\b(stop|end|terminate|deactivate)\s*(the\s*)?(rng|random\s*number\s*generator|attunement|needle)\s*(session)?\b",
        query_lower,
    ):
        try:
            service = get_rng_service()
            active_rng = service.get_all_sessions()
            if active_rng:
                session_id = active_rng[-1]  # Take the last active session
                res = await execute_tool_locally("stop_rng_session", {"session_id": session_id})
                tool_calls.append(
                    ToolCallLog(
                        tool_name="stop_rng_session", arguments={"session_id": session_id}, status="success", result=res
                    )
                )
                response_text = (
                    f"🛑 **RNG Attunement Stopped**\n\n"
                    f"Stopped the attunement tracker session `{session_id}`.\n"
                    f"- **Total readings captured**: {res.get('total_readings', 0)}\n"
                    f"- **Floating Needle count**: {res.get('floating_needle_count', 0)}\n"
                    f"- **Average Coherence**: {res.get('avg_coherence', 0.0):.2f}\n"
                    f"- **Duration**: {res.get('duration_seconds', 0.0):.1f}s"
                )
            else:
                response_text = "ℹ️ No active RNG attunement sessions are currently running."
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="stop_rng_session", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to stop RNG session: {str(e)}"

    # 7. Forge Sigil Fallback
    elif re.search(r"\b(forge|create|make|generate)\s*(a\s*)?sigil\b", query_lower):
        try:
            intention = "Divine Alignment"
            intent_match = re.search(r"\b(for|of|to)\s+(.+)$", query_lower)
            if intent_match:
                intention = intent_match.group(2).strip()

            res = await execute_tool_locally("forge_sigil", {"intention": intention, "kamea": "saturn"})
            tool_calls.append(
                ToolCallLog(
                    tool_name="forge_sigil",
                    arguments={"intention": intention, "kamea": "saturn"},
                    status="success",
                    result=res,
                )
            )
            response_text = (
                f"🔮 **Sigil Forged for Intention: '{intention}'**\n\n"
                f"The intention has been reduced to its core letter components: `{res.get('reduced_letters')}`.\n"
                f"A neon glowing sigil has been generated on the Saturn magic square (Kamea) and saved.\n\n"
                f"*(Use the Broadcast tab to transmit this frequency signature!)*"
            )
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="forge_sigil", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to forge sigil: {str(e)}"

    # 8. Cast Tarot Spread Fallback
    elif re.search(r"\b(draw|cast|get|show)\s*(a\s*)?(tarot|card|spread)\b", query_lower):
        try:
            count = 3
            if "single" in query_lower or "one" in query_lower or "1" in query_lower:
                count = 1
            elif "ten" in query_lower or "10" in query_lower or "celtic" in query_lower:
                count = 10

            res = await execute_tool_locally("cast_tarot_spread", {"count": count})
            tool_calls.append(
                ToolCallLog(tool_name="cast_tarot_spread", arguments={"count": count}, status="success", result=res)
            )

            response_text = "🔮 **Tarot Spread Drawn**\n\nHere are the cards representing your inquiry:\n\n"
            for idx, card in enumerate(res.get("cards", [])):
                orient = " (Reversed)" if card.get("reversed") else ""
                response_text += (
                    f"{idx + 1}. **{card.get('name')}**{orient}\n"
                    f"   - *Element*: {card.get('element')} | *Ruler/Correspondence*: {card.get('ruler') or 'N/A'}\n"
                    f"   - *Guidance*: {card.get('meaning')}\n"
                )
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="cast_tarot_spread", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to draw Tarot cards: {str(e)}"

    # 9. Cast I Ching Fallback
    elif re.search(r"\b(cast|throw|get|consult)\s*(the\s*)?(i\s*ching|hexagram)\b", query_lower):
        try:
            res = await execute_tool_locally("cast_i_ching", {})
            tool_calls.append(ToolCallLog(tool_name="cast_i_ching", arguments={}, status="success", result=res))
            primary = res.get("primary", {})
            relating = res.get("relating", {})
            lines_str = ", ".join(str(l) for l in res.get("cast_lines", []))

            response_text = (
                f"☯️ **I Ching Oracle Consulted**\n\n"
                f"Lines generated (bottom-to-top): `[{lines_str}]`\n\n"
                f"**Primary Hexagram**: {primary.get('name')}\n"
                f"- *Vibe*: {primary.get('meaning')}\n\n"
            )
            if res.get("has_changes"):
                response_text += (
                    f"**Relating Hexagram** (due to changing lines at {res.get('changing_lines')}): {relating.get('name')}\n"
                    f"- *Vibe*: {relating.get('meaning')}\n"
                )
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="cast_i_ching", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to cast I Ching: {str(e)}"

    # 10. Cast Geomancy Fallback
    elif re.search(r"\b(cast|generate|geomancy|geomantic|shield)\b", query_lower):
        try:
            res = await execute_tool_locally("cast_geomancy", {})
            tool_calls.append(ToolCallLog(tool_name="cast_geomancy", arguments={}, status="success", result=res))
            figs = res.get("figures", {})

            response_text = (
                f"👁 **Geomantic Shield Chart Cast**\n\n"
                f"- **First Mother**: {figs.get('Mother 1', {}).get('name')} ({figs.get('Mother 1', {}).get('translation')})\n"
                f"- **Second Mother**: {figs.get('Mother 2', {}).get('name')} ({figs.get('Mother 2', {}).get('translation')})\n"
                f"- **Right Witness**: {figs.get('Right Witness', {}).get('name')} ({figs.get('Right Witness', {}).get('translation')})\n"
                f"- **Left Witness**: {figs.get('Left Witness', {}).get('name')} ({figs.get('Left Witness', {}).get('translation')})\n"
                f"- **The Judge**: {figs.get('Judge', {}).get('name')} - *Key*: {figs.get('Judge', {}).get('meaning')}\n"
            )
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="cast_geomancy", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to cast Geomancy chart: {str(e)}"

    # 11. Search Grimoire Fallback
    elif re.search(r"\b(search|lookup|query|find)\s*(the\s*)?grimoire\s*(for\s+)?(.+)$", query_lower):
        try:
            term = (
                re.search(r"\b(search|lookup|query|find)\s*(the\s*)?grimoire\s*(for\s+)?(.+)$", query_lower)
                .group(4)
                .strip()
            )
            res = await execute_tool_locally("search_grimoire_correspondences", {"query": term})
            tool_calls.append(
                ToolCallLog(
                    tool_name="search_grimoire_correspondences", arguments={"query": term}, status="success", result=res
                )
            )

            if res:
                response_text = f"📚 **Grimoire Search Results for '{term}'**\n\n"
                for item in res[:5]:
                    response_text += (
                        f"🪐 **Planet**: {item.get('planet')} | **Metal**: {item.get('metal')}\n"
                        f"  - **Minerals**: {', '.join(item.get('minerals', []))}\n"
                        f"  - **Herbs**: {', '.join(item.get('herbs', []))}\n"
                        f"  - **Rates**: {item.get('rates')} | **Chakra**: {item.get('chakra')}\n"
                        f"  - **Focus**: {item.get('influence')}\n\n"
                    )
                f"ℹ️ No direct correspondences found in the Grimoire library for '{term}'."
        except Exception as e:
            tool_calls.append(
                ToolCallLog(tool_name="search_grimoire_correspondences", arguments={}, status="error", error=str(e))
            )
            response_text = f"❌ Failed to search Grimoire: {str(e)}"

    # 11b. Start Narrative Loop
    elif re.search(
        r"\b(start|activate|begin|turn\s*on)\s*(the\s*)?(narrative\s*loop|broadcast\s*loop|story\s*loop|transmission\s*loop)\b",
        query_lower,
    ):
        try:
            res = await execute_tool_locally("start_narrative_loop", {"interval_minutes": 15})
            tool_calls.append(
                ToolCallLog(
                    tool_name="start_narrative_loop", arguments={"interval_minutes": 15}, status="success", result=res
                )
            )
            response_text = (
                "🔮 **Continuous Broadcast Narrative Loop Activated**\n\n"
                "I have started the background narrative generation loop.\n"
                "- **Interval**: every 15 minutes\n"
                "- **Status**: Active and broadcasting."
            )
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="start_narrative_loop", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to start narrative loop: {str(e)}"

    # 11c. Stop Narrative Loop
    elif re.search(
        r"\b(stop|deactivate|turn\s*off|end)\s*(the\s*)?(narrative\s*loop|broadcast\s*loop|story\s*loop|transmission\s*loop)\b",
        query_lower,
    ):
        try:
            res = await execute_tool_locally("stop_narrative_loop", {})
            tool_calls.append(ToolCallLog(tool_name="stop_narrative_loop", arguments={}, status="success", result=res))
            response_text = (
                "🛑 **Continuous Broadcast Narrative Loop Stopped**\n\n"
                "I have successfully stopped the active background narrative loop."
            )
        except Exception as e:
            tool_calls.append(ToolCallLog(tool_name="stop_narrative_loop", arguments={}, status="error", error=str(e)))
            response_text = f"❌ Failed to stop narrative loop: {str(e)}"

    # 11d. Get Narrative Loop Status
    elif re.search(
        r"\b(status|check|info)\s*(of\s*the\s*)?(narrative\s*loop|broadcast\s*loop|story\s*loop|transmission\s*loop)\b",
        query_lower,
    ):
        try:
            res = await execute_tool_locally("get_narrative_loop_status", {})
            tool_calls.append(
                ToolCallLog(tool_name="get_narrative_loop_status", arguments={}, status="success", result=res)
            )
            active_str = "ACTIVE (Broadcasting)" if res.get("active") else "INACTIVE"
            response_text = (
                f"ℹ️ **Continuous Narrative Loop Status**\n\n"
                f"- **Active Status**: {active_str}\n"
                f"- **Cycle Interval**: {res.get('interval_minutes')} minutes\n"
            )
            if res.get("last_generated"):
                response_text += f"- **Last Blessing Genre**: `{res['last_generated'].get('genre')}`"
        except Exception as e:
            tool_calls.append(
                ToolCallLog(tool_name="get_narrative_loop_status", arguments={}, status="error", error=str(e))
            )
            response_text = f"❌ Failed to get loop status: {str(e)}"

    # 11e. List Settings / Realms
    elif re.search(r"\b(list|show|view)\s*(the\s*)?(realms|locations|settings)\b", query_lower):
        try:
            res = await execute_tool_locally("list_narrative_locations", {})
            tool_calls.append(
                ToolCallLog(tool_name="list_narrative_locations", arguments={}, status="success", result=res)
            )
            if res:
                response_text = "🗺️ **Active Realms and Settings**\n\n"
                for loc in res:
                    m_str = "Metaphysical" if loc.get("is_metaphysical") else "Earthly"
                    response_text += f"- **{loc.get('name')}** ({m_str})\n  - *Description*: {loc.get('description')}\n"
            else:
                response_text = "ℹ️ No narrative settings found."
        except Exception as e:
            tool_calls.append(
                ToolCallLog(tool_name="list_narrative_locations", arguments={}, status="error", error=str(e))
            )
            response_text = f"❌ Failed to list settings: {str(e)}"

    # 11f. List Characters / Archetypes
    elif re.search(r"\b(list|show|view)\s*(the\s*)?(characters|archetypes)\b", query_lower):
        try:
            res = await execute_tool_locally("list_narrative_characters", {})
            tool_calls.append(
                ToolCallLog(tool_name="list_narrative_characters", arguments={}, status="success", result=res)
            )
            if res:
                response_text = "👥 **Narrative Characters and Archetypes**\n\n"
                for char in res:
                    response_text += (
                        f"- **{char.get('name')}** ({char.get('role')})\n  - *Description*: {char.get('description')}\n"
                    )
            else:
                response_text = "ℹ️ No characters found."
        except Exception as e:
            tool_calls.append(
                ToolCallLog(tool_name="list_narrative_characters", arguments={}, status="error", error=str(e))
            )
            response_text = f"❌ Failed to list characters: {str(e)}"

    # 11g. Generate Single Outlook
    elif re.search(r"\b(generate|create|write)\s*(a\s*)?(single\s*)?(outlook|blessing|story|narrative)\b", query_lower):
        try:
            res = await execute_tool_locally("generate_single_outlook", {})
            tool_calls.append(
                ToolCallLog(tool_name="generate_single_outlook", arguments={}, status="success", result=res)
            )
            response_text = (
                f"📜 **Generated Blessing Narrative**\n\n"
                f"{res.get('narrative')}\n\n"
                f"--- \n"
                f"- **Genre**: {res.get('genre')} | **Astrology**: {res.get('astrology_used')[:60]}..."
            )
        except Exception as e:
            tool_calls.append(
                ToolCallLog(tool_name="generate_single_outlook", arguments={}, status="error", error=str(e))
            )
            response_text = f"❌ Failed to generate narrative: {str(e)}"

    # 12. Predefined Dharma Tales Fallback
    elif re.search(
        r"\b(tell|generate|show|give|read)\s*(me\s*)?(a\s*)?(dharma\s*tale|teaching|story|wisdom|parable|tale)\b",
        query_lower,
    ):
        parable = (
            "🏯 **Zen Wisdom: A Cup of Tea**\n\n"
            "Nan-in, a Japanese master during the Meiji era, received a university professor who came to inquire about Zen.\n\n"
            "Nan-in served tea. He poured his visitor's cup full, and then kept on pouring.\n\n"
            "The professor watched the overflow until he no longer could restrain himself. "
            '"It is overfull. No more will go in!"\n\n'
            '"Like this cup," Nan-in said, "you are full of your own opinions and speculations. '
            'How can I show you Zen unless you first empty your cup?"'
        )
        response_text = parable

    # 13. Help / Introduction
    else:
        response_text = (
            "👋 **Welcome to the Vajra.Stream AI Command Center!**\n\n"
            "I can assist you in controlling your radionics operations and sacred generators using natural language commands. "
            "If an OpenAI or Anthropic API Key is not set, I run in **Local Command Mode**. Here are some commands you can type:\n\n"
            "- 🔮 `Start automation` - Begins the 24/7 round-robin population blessing cycle.\n"
            "- 🛑 `Stop automation` - Terminates the active scheduler and blessings.\n"
            "- 👥 `List populations` - Shows all registered blessing targets and categories.\n"
            "- 📈 `Get statistics` - Displays cumulative counts of photos blessed and mantras chanted.\n"
            "- 🎲 `Start RNG session` - Calibrates and begins tracking quantum entropy & floating needles.\n"
            "- 🛑 `Stop RNG session` - Concludes the active attunement tracker.\n"
            "- 🔮 `Forge sigil for [intention]` - Generates a vector Kamea sigil pattern.\n"
            "- 🃏 `Draw tarot cards` - Casts a Tarot spread for your query.\n"
            "- ☯️ `Cast I Ching` - Casts a hexagram representing the current situation.\n"
            "- 👁 `Cast geomancy` - Draws a shield chart mapping 16 figures to houses.\n"
            "- 📚 `Search grimoire for [herbs/crystals/planets]` - Searches correspondences library.\n"
            "- 📖 `Generate outlook` - Trigger a localized blessing parable narrative.\n"
            "- 🔄 `Start narrative loop` - Starts the background narrative generation loop.\n"
            "- 🛑 `Stop narrative loop` - Pauses continuous narrative cycles.\n"
            "- 🗺️ `List realms` - Lists all defined setting places and lands.\n"
            "- 👥 `List characters` - Lists all spiritual actors and dialogue archetypes.\n"
            "- 📚 `Tell me a dharma tale` - Generates a story or parable for your contemplation."
        )

    return ChatResponse(response=response_text, tool_calls=tool_calls)


# ============================ Context + Provider Helpers ============================
# These helpers replace the old inline compile_*_context() functions and the
# 6 copy-pasted tool-calling loops inside chat_interaction.  They are used by
# the registry-backed chat endpoint below.


async def _build_system_prompt_with_context(request: ChatRequest) -> str:
    """Build the base operator system prompt and append composable context modules.

    Uses :class:`SystemPromptBuilder` + the ContextModule registry (``core.context``)
    to assemble astrology / anatomy / hardware sections concurrently.  Every module
    is defensive — a single broken module never prevents the others from
    contributing, and a total builder failure falls back to the bare base prompt.
    """
    base_prompt = (
        "You are the Vajra.Stream AI Operator, a wise assistant designed to control a "
        "radionics board, crystal broadcasters, scalar wave generators, and blessing slideshows. "
        "Your goal is to run operations based on the user's intent. "
        "You can execute actions using tools. When the user asks for something that requires a tool, "
        "CALL THE TOOL IMMEDIATELY — do not narrate what you plan to do. "
        "For example, if you think 'I should list populations', immediately emit the tool call "
        "rather than saying 'Let me survey the populations first.' "
        "Available tools include: list_populations, create_population, update_population, "
        "start_automation, stop_automation, get_system_status, get_automation_status, "
        "forge_sigil, cast_tarot_spread, cast_i_ching, check_saka_dawa, "
        "play_chakra_healing_audio, run_working, generate_single_outlook, generate_epic_outlook, "
        "generate_blessing, generate_prayer, generate_teaching, generate_image, speak_text, "
        "search_grimoire_correspondences, get_planetary_hours_and_transits. "
        "\n\n"
        "KEY CAPABILITIES:\n"
        "- You can CREATE new populations for any group the user mentions "
        "(use create_population with category='custom' and source_type='manual')\n"
        "- You can GENERATE blessings and outlooks for specific populations "
        "(use generate_single_outlook with custom_context for the user's intention)\n"
        "- You can START automated blessing rotations for populations "
        "(use start_automation after creating or selecting populations)\n"
        "- You can call multiple tools in sequence — after each tool returns results, "
        "you may call another tool to continue the workflow, or write your final response.\n"
        "- When the user mentions a group that doesn't exist yet, CREATE it first, "
        "then generate a blessing for it.\n\n"
        "Once you receive the tool results, explain the outcome "
        "with deep compassion and wisdom, invoking the digital dharma theme."
    )
    context_request = ContextRequest(
        include_astrology=bool(request.include_astrology),
        include_anatomy=bool(request.include_anatomy),
        include_hardware=bool(request.include_hardware),
        astrology_data=request.astrology_data,
    )
    builder = SystemPromptBuilder()
    builder.register(AstrologyContextModule())
    builder.register(AnatomyContextModule())
    builder.register(HardwareContextModule())
    try:
        # SystemPromptBuilder.compose() now accepts base_prompt directly,
        # so we don't need to concatenate here. The builder returns
        # `base_prompt + "\n\n" + <rendered sections>` when sections exist.
        composed = await builder.compose(context_request, base_prompt=base_prompt)
    except Exception as exc:  # noqa: BLE001 — context failure must not break chat
        logger.warning("SystemPromptBuilder compose failed: %s", exc)
        composed = base_prompt

    if request.use_rag:
        rag_block = _build_rag_context_block(request)
        if rag_block:
            composed = f"{composed}\n\n{rag_block}"
    return composed


def _build_rag_context_block(request: ChatRequest) -> str:
    """Search the knowledge index for the latest user query and return a
    formatted "Relevant knowledge:" block, or '' if nothing matched.
    """
    try:
        from core.knowledge_index import get_knowledge_index
    except ImportError:
        return ""
    user_query = next(
        (m.content for m in reversed(request.messages) if m.role == "user"),
        None,
    )
    if not user_query:
        return ""
    try:
        idx = get_knowledge_index()
        results = idx.search(user_query, top_k=3)
    except Exception:  # noqa: BLE001 — RAG must never block chat
        logger.debug("RAG retrieval failed", exc_info=True)
        return ""
    if not results:
        return ""
    lines = ["Relevant knowledge (from the Vajra.Stream knowledge base):"]
    for r in results:
        source = r.get("source", "?")
        text = r.get("text", "").strip().replace("\n", " ")
        if len(text) > 400:
            text = text[:397] + "..."
        lines.append(f"- [{source}] {text}")
    return "\n".join(lines)


async def _select_provider_via_registry(http_request: Request, requested_provider: str) -> str | None:
    """Consult :meth:`ProviderRegistry.pick_best` to resolve ``"auto"``.

    Returns the chosen provider name (e.g. ``"openrouter"``, ``"lm_studio"``), or
    ``None`` when the registry is unavailable / empty / unhealthy.  Explicit
    (non-``"auto"``) requests are honoured only when the named provider is
    actually registered and currently healthy; otherwise ``None`` is returned so
    the caller falls through to env-var based detection.
    """
    registry = getattr(http_request.app.state, "llm_registry", None)
    if registry is None or len(registry) == 0:
        return None

    if requested_provider and requested_provider != "auto":
        if requested_provider not in registry:
            return None
        try:
            statuses = await registry.health_check_all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("registry health check failed: %s", exc)
            return None
        if any(s.provider == requested_provider and s.healthy for s in statuses):
            return requested_provider
        return None

    try:
        best = await retry_with_backoff(
            lambda: registry.pick_best(),
            max_retries=1,
            initial_backoff=0.5,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ProviderRegistry.pick_best failed: %s", exc)
        return None
    return best.name if best is not None else None


def _build_openai_tools(tool_schemas: list[dict]) -> list[dict]:
    """Convert internal tool schemas into OpenAI function-tool descriptors."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["parameters"],
            },
        }
        for s in tool_schemas
    ]


def _record_llm_usage(
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    endpoint: str = "chat",
    success: bool = True,
) -> None:
    """Best-effort LLM usage recording for raw-client call paths.

    Used by the tool-calling loops (which call ``client.chat.completions.create``
    directly with a sync ``openai.OpenAI`` / ``anthropic.Anthropic`` client
    rather than going through the provider class). The provider-class path
    (``OpenAICompatibleProvider.generate`` / ``AnthropicProvider.generate``)
    records itself, so registry-routed calls do not call this helper — that
    keeps the JSONL audit log free of duplicates.
    """
    try:
        tracker = LLMUsageTracker.get()
        tracker.record(
            UsageRecord(
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                total_tokens=(prompt_tokens or 0) + (completion_tokens or 0),
                latency_ms=latency_ms,
                endpoint=endpoint,
                success=success,
            )
        )
    except Exception:  # noqa: BLE001 — tracker must never block an LLM call
        logger.debug("LLMUsageTracker.record failed", exc_info=True)


async def _run_openai_compatible_tool_loop(
    *,
    client: Any,
    model_name: str,
    messages: list[dict],
    tools: list[dict],
    tool_logs: list[ToolCallLog],
    max_turns: int = 5,
    provider_label: str = "provider",
    create_kwargs: dict | None = None,
    debug_raw: list | None = None,
) -> str:
    """Run the chat-completions tool-calling loop for any OpenAI-compatible client.

    Unifies the 5 previously copy-pasted loops (OpenAI, OpenRouter, DeepSeek,
    MiniMax, LM Studio).  Returns the final assistant text — either the model's
    terminal message or a ``"*(... reached maximum reasoning turns ...)*"``
    notice when the loop exhausts ``max_turns``.
    """
    extra_kwargs = create_kwargs or {}
    for turn in range(max_turns):
        logger.info(f"{provider_label} turn {turn} with model {model_name}...")
        turn_start = time.time()
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
            temperature=0.7,
            max_tokens=extra_kwargs.get("max_tokens", 4096),
            **extra_kwargs,
        )
        try:
            _turn_latency = (time.time() - turn_start) * 1000.0
            _usage = getattr(response, "usage", None)
            _record_llm_usage(
                provider=provider_label.lower().replace(" ", "_"),
                model=model_name,
                prompt_tokens=getattr(_usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(_usage, "completion_tokens", 0) or 0,
                latency_ms=_turn_latency,
            )
        except Exception:  # noqa: BLE001
            logger.debug("usage record failed in openai tool loop", exc_info=True)

        msg = response.choices[0].message
        messages.append(msg)

        if debug_raw is not None:
            try:
                debug_raw.append(
                    {
                        "turn": turn,
                        "content_preview": (msg.content or "")[:300],
                        "has_native_tool_calls": bool(getattr(msg, "tool_calls", None)),
                        "native_tool_names": [tc.function.name for tc in (getattr(msg, "tool_calls", None) or [])],
                        "finish_reason": str(getattr(response.choices[0], "finish_reason", "")),
                    }
                )
                text_tc = _parse_text_tool_calls(msg.content or "")
                if text_tc:
                    debug_raw[-1]["text_parsed_tool_calls"] = [t["name"] for t in text_tc]
            except Exception:  # noqa: BLE001
                logger.warning("Failed to capture debug trace for turn", exc_info=True)

        if not msg.tool_calls:
            text_tool_calls = _parse_text_tool_calls(msg.content or "")
            if text_tool_calls:
                logger.info(f"{provider_label}: parsed {len(text_tool_calls)} tool call(s) from text output")
                for tc_text in text_tool_calls:
                    name = _resolve_tool_name(tc_text["name"])
                    args = tc_text["arguments"]
                    try:
                        result = await execute_tool_locally(name, args)
                        tool_logs.append(ToolCallLog(tool_name=name, arguments=args, status="success", result=result))
                        messages.append(
                            {
                                "role": "user",
                                "content": f"[Tool result for {name}]: {json.dumps(result)[:2000]}",
                            }
                        )
                    except Exception as ex:
                        logger.error(f"Error executing text-parsed tool {name}: {ex}")
                        tool_logs.append(ToolCallLog(tool_name=name, arguments=args, status="error", error=str(ex)))
                        messages.append(
                            {
                                "role": "user",
                                "content": f"[Tool error for {name}]: {ex}",
                            }
                        )

                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None,
                    temperature=0.7,
                    **extra_kwargs,
                )
                final_msg = response.choices[0].message
                return final_msg.content or ""

            return msg.content or ""

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except Exception as json_err:  # noqa: BLE001
                logger.error(f"{provider_label} returned malformed tool args: {json_err}")
                args = {}
            try:
                result = await execute_tool_locally(name, args)
                tool_logs.append(ToolCallLog(tool_name=name, arguments=args, status="success", result=result))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": json.dumps(result),
                    }
                )
            except Exception as ex:
                logger.error(f"Error executing {provider_label} tool {name}: {ex}")
                try:
                    log_failed_tool_call(
                        FailedToolCallSchema(
                            tool_name=name,
                            arguments=json.dumps(args),
                            error_message=str(ex),
                        )
                    )
                except Exception as log_ex:  # noqa: BLE001
                    logger.error(f"Failed to log tool failure to DB: {log_ex}")
                tool_logs.append(ToolCallLog(tool_name=name, arguments=args, status="error", error=str(ex)))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": json.dumps({"error": str(ex)}),
                    }
                )

    return f"*({provider_label} reached maximum reasoning turns without finishing.)*"


async def _run_anthropic_tool_loop(
    *,
    client: Any,
    model_name: str,
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
    tool_logs: list[ToolCallLog],
    max_turns: int = 5,
) -> str:
    """Run the Anthropic messages tool-calling loop (block-based content format)."""
    for turn in range(max_turns):
        logger.info(f"Anthropic turn {turn}...")
        turn_start = time.time()
        response = client.messages.create(
            model=model_name,
            system=system_prompt,
            messages=messages,
            tools=tools,
            temperature=0.7,
            max_tokens=2000,
        )
        try:
            _turn_latency = (time.time() - turn_start) * 1000.0
            _usage = getattr(response, "usage", None)
            _record_llm_usage(
                provider="anthropic",
                model=model_name,
                prompt_tokens=getattr(_usage, "input_tokens", 0) or 0,
                completion_tokens=getattr(_usage, "output_tokens", 0) or 0,
                latency_ms=_turn_latency,
            )
        except Exception:  # noqa: BLE001
            logger.debug("usage record failed in anthropic tool loop", exc_info=True)

        assistant_content: list[dict] = []
        tool_requests = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_requests.append(block)
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        messages.append({"role": "assistant", "content": assistant_content})

        if not tool_requests:
            return "".join(b.text for b in response.content if b.type == "text")

        tool_results_content = []
        for tool_use in tool_requests:
            name = tool_use.name
            args = tool_use.input
            try:
                result = await execute_tool_locally(name, args)
                tool_logs.append(ToolCallLog(tool_name=name, arguments=args, status="success", result=result))
                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(result),
                    }
                )
            except Exception as ex:
                logger.error(f"Error executing Anthropic tool {name}: {ex}")
                try:
                    log_failed_tool_call(
                        FailedToolCallSchema(
                            tool_name=name,
                            arguments=json.dumps(args),
                            error_message=str(ex),
                        )
                    )
                except Exception as log_ex:  # noqa: BLE001
                    logger.error(f"Failed to log tool failure to DB: {log_ex}")
                tool_logs.append(ToolCallLog(tool_name=name, arguments=args, status="error", error=str(ex)))
                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps({"error": str(ex)}),
                    }
                )

        messages.append({"role": "user", "content": tool_results_content})

    return "*(Anthropic reached maximum reasoning turns without finishing.)*"


def _prioritize_tool_schemas(schemas: list[dict], max_count: int) -> list[dict]:
    """Return the single chat allowlist, in ESSENTIAL_TOOL_ORDER.

    ``get_tool_schemas(essential_only=True)`` already filters to the same
    names. This only restores priority order and applies ``max_count``.
    """
    from backend.core.llm_agent.tools import ESSENTIAL_TOOL_ORDER

    by_name = {s.get("name"): s for s in schemas}
    prioritized = [by_name[n] for n in ESSENTIAL_TOOL_ORDER if n in by_name]
    return prioritized[:max_count]


async def _chat_via_registry(
    http_request: Request,
    request: ChatRequest,
    provider_name: str,
    system_prompt_holder: list[str] | None = None,
    tool_schemas: list[dict] | None = None,
    tool_executor: Any = None,
) -> ChatResponse:
    """Registry-first chat path. Uses the registered provider for the request.

    The legacy code path (env-var lookups + copy-pasted tool loops) is preserved
    below as a fallback for deployments without an initialized registry or
    providers that aren't registered.

    ``system_prompt_holder`` is unused here (kept for signature symmetry with the
    fallback path); system prompt is built inside this function.

    ``tool_executor`` overrides the default ``execute_tool_locally`` dispatch —
    used by the async chat path to inject progress tracking without monkey-patching.
    """
    from backend.app.api.v1.endpoints import llm as llm_module

    _execute = tool_executor or llm_module.execute_tool_locally
    from core.llm.retry import retry_with_backoff

    registry = http_request.app.state.llm_registry
    # Build system prompt with context modules
    system_prompt = await _build_system_prompt_with_context(request)

    # Pick the requested provider from the registry (already verified `provider in registry`)
    chosen = None
    for p in registry.providers:
        if p.name == provider_name:
            chosen = p
            break
    if chosen is None:
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{provider_name}' is registered but not selectable",
        )

    from core.llm.models import ToolDefinition

    normalized = _normalize_model_id(request.model)
    if normalized != request.model:
        request = request.model_copy(update={"model": normalized})

    limited_schemas = _prioritize_tool_schemas(tool_schemas or [], 50)
    tool_defs = [ToolDefinition(**s) for s in limited_schemas]
    chat_request = request.model_copy(
        update={
            "system_prompt": system_prompt,
            "tools": tool_defs,
        }
    )

    async def _do_generate():
        return await chosen.generate(chat_request)

    try:
        response = await retry_with_backoff(_do_generate, max_retries=0, initial_backoff=0.5)
    except Exception as e:
        # Failover to next healthy provider
        chain = await registry.failover_chain()
        logger.info(
            "Provider %s failed (%s), trying failover chain of %d",
            provider_name,
            e,
            len(chain),
        )
        for next_provider in chain:
            if next_provider.name == provider_name:
                continue  # already tried
            try:
                response = await next_provider.generate(chat_request)
                logger.info("Failover succeeded via %s", next_provider.name)
                break
            except Exception as e2:
                logger.warning("Failover to %s failed: %s", next_provider.name, e2)
                continue
        else:
            logger.exception("All providers failed for chat request. Primary error: %s", e)
            raise HTTPException(
                status_code=503,
                detail=f"All providers failed. Primary=[{type(e).__name__}] {e}",
            )

    # Convert the new core.llm.models.ChatResponse to the local ChatResponse
    # (which the endpoint advertises as response_model).
    clean_content = _chat_text(response)

    tool_logs: list[ToolCallLog] = []
    raw_tool_results: list[dict] = []
    conversation_messages = list(request.messages)
    prev_tool_signature: str | None = None
    loop_start = time.time()
    max_loop_seconds = 200

    for turn in range(2):
        if time.time() - loop_start > max_loop_seconds:
            logger.info("Tool loop timed out after %.1fs — returning partial results", time.time() - loop_start)
            break
        native_tcs = response.tool_calls if hasattr(response, "tool_calls") else []
        text_tool_calls = _parse_text_tool_calls(clean_content)
        all_tool_calls = []
        for tc in native_tcs:
            all_tool_calls.append({"name": tc.get("name", ""), "arguments": tc.get("arguments", {})})
        all_tool_calls.extend(text_tool_calls)

        # Native function-calling + prose JSON often describe the same call.
        seen_calls: set[str] = set()
        deduped_calls: list[dict] = []
        for tc in all_tool_calls:
            key = json.dumps(
                {"name": tc.get("name"), "arguments": tc.get("arguments")},
                sort_keys=True,
                default=str,
            )
            if key in seen_calls:
                continue
            seen_calls.add(key)
            deduped_calls.append(tc)
        all_tool_calls = deduped_calls

        if not all_tool_calls:
            break

        signature = json.dumps(all_tool_calls, sort_keys=True, default=str)
        if signature == prev_tool_signature:
            logger.info("Tool-call loop detected (same call repeated); ending tool loop")
            break
        prev_tool_signature = signature

        logger.info(f"Registry turn {turn}: {len(native_tcs)} native + {len(text_tool_calls)} text-parsed tool calls")
        turn_results: list[dict] = []
        for tc_text in all_tool_calls:
            name = _resolve_tool_name(tc_text["name"])
            args = tc_text["arguments"]
            already_ran = {r.get("tool") for r in raw_tool_results if r.get("status") == "success"}
            if name == "list_populations" and "list_populations" in already_ran:
                logger.info("Skipping duplicate list_populations")
                continue
            if name in _ALREADY_GENERATED and name in already_ran:
                logger.info("Skipping duplicate %s", name)
                continue
            try:
                result = await _execute(name, args)
                tool_logs.append(ToolCallLog(tool_name=name, arguments=args, status="success", result=result))
                turn_results.append({"tool": name, "status": "success", "result": result})
                raw_tool_results.append({"tool": name, "status": "success", "result": result})
            except Exception as ex:
                logger.error(f"Error executing text-parsed tool {name}: {ex}")
                tool_logs.append(ToolCallLog(tool_name=name, arguments=args, status="error", error=str(ex)))
                turn_results.append({"tool": name, "status": "error", "error": str(ex)})
                raw_tool_results.append({"tool": name, "status": "error", "error": str(ex)})

        if not turn_results:
            break

        # Programmatic auto-chain: if the user asked for an outlook/blessing/
        # narrative and generate_single_outlook hasn't been executed yet, run it
        # DETERMINISTICALLY on the backend. The model frequently loops on
        # inspection tools (list_populations, get_*) or create_population and
        # never reaches the outlook tool even when it's available and hinted.
        user_query = _latest_user_text(request.messages)
        intention = _intention_from_messages(request.messages)
        if re.search(
            r"\b(working|radionic|attune|broadcast a rate|begin a working|charge this)\b", user_query
        ) and not any(r.get("tool") == "run_working" and r.get("status") == "success" for r in raw_tool_results):
            try:
                working_result = await _execute(
                    "run_working",
                    {"intention": intention[:400], "target": "all beings", "broadcast": False},
                )
                tool_logs.append(
                    ToolCallLog(
                        tool_name="run_working",
                        arguments={"intention": intention[:400]},
                        status="success",
                        result=working_result,
                    )
                )
                turn_results.append({"tool": "run_working", "status": "success", "result": working_result})
                raw_tool_results.append({"tool": "run_working", "status": "success", "result": working_result})
                logger.info("Auto-chained run_working (query-driven)")
            except Exception as auto_ex:
                logger.warning("Auto-chain run_working failed: %s", auto_ex)
        elif (
            re.search(r"\b(outlook|blessing|narrative|prayer|sutra|bless|healing story)\b", user_query)
            and not any(r.get("tool") in _ALREADY_GENERATED and r.get("status") == "success" for r in turn_results)
            and not any(r.get("tool") in _ALREADY_GENERATED and r.get("status") == "success" for r in raw_tool_results)
        ):
            created_pops = [
                r
                for r in turn_results
                if r.get("tool") == "create_population"
                and r.get("status") == "success"
                and isinstance(r.get("result"), dict)
            ]
            pop_name = created_pops[0]["result"].get("name", "") if created_pops else ""
            custom_context = (
                f"An outlook blessing for {pop_name or 'all beings in need'}. The user's intention: {intention}"
            )
            try:
                outlook_result = await _execute(
                    "generate_single_outlook",
                    {"genre": "healing", "custom_context": custom_context[:500]},
                )
                tool_logs.append(
                    ToolCallLog(
                        tool_name="generate_single_outlook",
                        arguments={"genre": "healing", "custom_context": custom_context[:500]},
                        status="success",
                        result=outlook_result,
                    )
                )
                turn_results.append({"tool": "generate_single_outlook", "status": "success", "result": outlook_result})
                raw_tool_results.append(
                    {"tool": "generate_single_outlook", "status": "success", "result": outlook_result}
                )
                logger.info("Auto-chained generate_single_outlook (query-driven)")
            except Exception as auto_ex:
                logger.warning("Auto-chain generate_single_outlook failed: %s", auto_ex)
                tool_logs.append(
                    ToolCallLog(tool_name="generate_single_outlook", arguments={}, status="error", error=str(auto_ex))
                )
                turn_results.append({"tool": "generate_single_outlook", "status": "error", "error": str(auto_ex)})

        outlook_done = any(
            r.get("tool") == "generate_single_outlook" and r.get("status") == "success" for r in turn_results
        )
        if outlook_done:
            conversation_messages = conversation_messages + [
                ChatMessage(role="assistant", content=clean_content),
            ]
            results_text = "\n".join(
                f"[Tool: {r['tool']}] {'OK' if r['status'] == 'success' else 'ERROR: ' + r.get('error', '')}\n"
                f"{_summarize_tool_result(r.get('result', r.get('error', '')))}"
                for r in turn_results
            )
            conversation_messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        f"[System: Tool results received]\n{results_text}\n\n"
                        "The outlook has been generated and is shown to the user as a card. "
                        "Write at most 3 short sentences that point at the card. "
                        "Do not restate rates, populations, or the narrative. "
                        "Do not call any more tools."
                    ),
                )
            )
            followup_request = request.model_copy(
                update={
                    "messages": conversation_messages,
                    "tools": [],
                }
            )
            try:
                followup_response = await chosen.generate(followup_request)
                clean_content = _chat_text(followup_response)
            except Exception as followup_ex:
                logger.warning(f"Outlook summary LLM call failed: {followup_ex}")
            break

        conversation_messages = conversation_messages + [
            ChatMessage(role="assistant", content=clean_content),
        ]
        results_text = "\n".join(
            f"[Tool: {r['tool']}] {'OK' if r['status'] == 'success' else 'ERROR: ' + r.get('error', '')}\n"
            f"{_summarize_tool_result(r.get('result', r.get('error', '')))}"
            for r in turn_results
        )

        # Auto-chain: if a population was just created and the user's query asks
        # for an outlook/blessing/narrative/prayer, give the LLM an explicit next step.
        chain_hint = ""
        user_query = _latest_user_text(request.messages)
        if re.search(r"\b(outlook|blessing|narrative|prayer|sutra|bless|healing story)\b", user_query):
            created_pops = [
                r
                for r in turn_results
                if r.get("tool") == "create_population"
                and r.get("status") == "success"
                and isinstance(r.get("result"), dict)
            ]
            if created_pops:
                pop_name = created_pops[0]["result"].get("name", "the population")
                chain_hint = (
                    f"\n\nThe population '{pop_name}' ALREADY EXISTS now — do NOT call "
                    "create_population again. Your next and ONLY action is to call "
                    "generate_single_outlook with genre='healing' and a custom_context that "
                    "reflects the user's intention. This is the tool that actually fulfills the "
                    "user's request for an outlook/blessing."
                )

        conversation_messages.append(
            ChatMessage(
                role="user",
                content=(
                    f"[System: Tool results received]\n{results_text}\n\n"
                    "If the user's original request is not yet fully fulfilled, "
                    "call the next tool NOW. Only write your final response to the user "
                    "after all required actions have been completed."
                    f"{chain_hint}"
                ),
            )
        )

        is_last_turn = turn >= 3
        try:
            followup_request = request.model_copy(
                update={
                    "messages": conversation_messages,
                    "tools": [] if is_last_turn else tool_defs,
                }
            )
            followup_response = await chosen.generate(followup_request)
            clean_content = _chat_text(followup_response)
            logger.info(f"Registry turn {turn}: follow-up LLM call succeeded")
        except Exception as followup_ex:
            logger.warning(f"Follow-up LLM call failed: {followup_ex}. Returning raw results.")
            break

    if not (clean_content or "").strip() and tool_logs:
        names = ", ".join(t.tool_name for t in tool_logs if t.tool_name)
        clean_content = f"Completed {len(tool_logs)} tool call(s): {names or 'unnamed'}."

    debug_info: dict = {
        "provider": response.provider,
        "model": response.model,
        "tools_executed": len(tool_logs),
        "tool_names": [t.tool_name for t in tool_logs],
        "response_chars": len(clean_content or ""),
    }
    if request.debug_mode:
        debug_info.update(
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "finish_reason": response.finish_reason,
                "text_parsed_tool_calls": [t["name"] for t in text_tool_calls],
                "raw_tool_results": raw_tool_results[:3],
            }
        )
        if getattr(response, "reasoning_content", None):
            debug_info["reasoning_content"] = response.reasoning_content
        if getattr(response, "reasoning_tokens", 0):
            debug_info["reasoning_tokens"] = response.reasoning_tokens
    return ChatResponse(
        response=clean_content,
        tool_calls=tool_logs,
        debug_info=debug_info,
    )


# ============================ Chat Endpoint ============================


def _provider_default_model(provider_class) -> str | None:
    """Read a provider class's declared ``default_model`` without instantiating it.

    Instantiating the provider class just to read the default would trigger
    HTTP-client construction and env-var validation. Introspecting the
    ``__init__`` signature is side-effect-free and tracks future changes to
    the provider's configured default automatically.
    """
    import inspect

    try:
        sig = inspect.signature(provider_class.__init__)
        param = sig.parameters.get("default_model")
        if param and param.default is not inspect.Parameter.empty:
            return param.default
    except Exception as e:
        logger.debug("Could not introspect default_model on %s: %s", provider_class, e)
    return None


@router.post("/chat", response_model=ChatResponse)
async def chat_compat(request: ChatRequest, http_request: Request):
    """Legacy synchronous chat endpoint — kept for backward compatibility."""
    provider_name = _resolve_provider_name(request, http_request)
    if provider_name == "auto":
        registry_choice = await _select_provider_via_registry(http_request, "auto")
        if registry_choice:
            provider_name = registry_choice
    return await _chat_via_registry(http_request, request, provider_name, tool_schemas=get_tool_schemas())


@router.post("/chat/async")
async def chat_async(request: ChatRequest, http_request: Request):
    """Asynchronous chat — returns immediately with a job_id, pushes progress via WebSocket."""
    from backend.app.api.v1.chat_job_manager import create_job, register_task

    job_id = create_job(connection_id=request.connection_id)
    task = asyncio.create_task(_run_chat_async(job_id, request, http_request, request.connection_id))
    register_task(job_id, task)
    return {"status": "accepted", "job_id": job_id}


@router.get("/chat/jobs/{job_id}")
async def chat_job_status(job_id: str):
    """Poll an async chat job (fallback when the websocket event is missed)."""
    from backend.app.api.v1.chat_job_manager import get_job, job_public_view

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown chat job")
    return job_public_view(job)


@router.post("/chat/jobs/{job_id}/cancel")
async def chat_job_cancel(job_id: str):
    """Cancel a running async chat job. Stop in the UI should call this."""
    from backend.app.api.v1.chat_job_manager import cancel_job, get_job

    if get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Unknown chat job")
    cancel_job(job_id)
    return {"status": "cancelled", "job_id": job_id}


# Backward-compatible name for autonomous_agent.py
chat_interaction = chat_compat


def _generate_offline_teach_response(chat_msgs: list[Any], system_prompt: str) -> str:
    """Generate structured educational response using local knowledge corpora when LLMs are offline."""
    user_text = ""
    for m in reversed(chat_msgs):
        if getattr(m, "role", None) == "user" or (isinstance(m, dict) and m.get("role") == "user"):
            user_text = getattr(m, "content", "") if hasattr(m, "content") else m.get("content", "")
            break

    query = user_text.lower().strip()
    from backend.core.services.grimoire_service import grimoire_service

    # 1. Tarot Queries
    if "tarot" in system_prompt.lower() or "card" in query or "arcana" in query or "suit" in query:
        matches = grimoire_service.search(query, category="tarot")
        if matches:
            top = matches[0]
            card = top.get("details", {})
            return (
                f"## 🃏 {top['title']}\n\n"
                f"**Arcana:** {str(card.get('arcana', '')).capitalize()} Arcana · **Element:** {card.get('element', 'N/A')} · **Astrological Ruler:** {card.get('ruler', 'N/A')}\n\n"
                f"### Symbolism & Description\n{card.get('desc', top['description'])}\n\n"
                f"### Core Interpretations\n"
                f"- **Upright (Direct Energy):** {card.get('upright', '')}\n"
                f"- **Reversed (Internalized / Blocked):** {card.get('reversed', '')}\n\n"
                f"### Key Keywords\n{', '.join(card.get('keywords', []))}\n\n"
                f"> *Lesson Tip:* In a reading, observe whether this card interacts harmoniously with adjacent cards of the same elemental suit."
            )
        if "major" in query:
            return (
                "## 🃏 The Major Arcana: The Fool's Journey\n\n"
                "The 22 Major Arcana cards (0 to 21) represent the soul's profound spiritual evolution, from innocence to cosmic integration:\n\n"
                "- **0. The Fool:** The beginning of the journey, unconditioned awareness, holy trust.\n"
                "- **1. The Magician:** Focused will, mastery of the 4 elements (Wand, Cup, Sword, Pentacle).\n"
                "- **2. The High Priestess:** Intuition, subconscious wisdom, the veil between worlds.\n"
                "- **3. The Empress:** Abundance, creative fertility, mother nature.\n"
                "- **4. The Emperor:** Order, structure, temporal sovereignty.\n"
                "- **5. The Hierophant:** Sacred tradition, esoteric transmission, spiritual teacher.\n\n"
                "When a Major Arcana card appears in a spread, it indicates major life lessons and archetypal themes beyond temporary daily circumstances."
            )
        if "suit" in query or "element" in query:
            return (
                "## 🃏 The Four Tarot Suits & Elements\n\n"
                "The 56 Minor Arcana are organized into four suits, each governing an elemental domain of human experience:\n\n"
                "1. **Wands (Fire 🔥):** Willpower, inspiration, creative drive, spiritual passion, career ambition.\n"
                "2. **Cups (Water 💧):** Emotions, intuition, love, relationships, the unconscious psyche.\n"
                "3. **Swords (Air 💨):** Intellect, logic, communication, mental clarity, truth and conflict.\n"
                "4. **Pentacles (Earth 🌍):** Material abundance, physical body, finances, craft, manifest stability.\n\n"
                "When reading, notice which suit dominates the spread to determine the primary life plane involved."
            )
        if "spread" in query:
            return (
                "## 🃏 Essential Tarot Spreads\n\n"
                "Here are the core classical spreads for practice:\n\n"
                "1. **Single-Card Daily Draw:** Perfect for daily contemplation. Ask: *'What energy requires my awareness today?'*\n"
                "2. **Three-Card Spread (Past / Present / Future):**\n"
                "   - **Card 1 (Left):** Root influences & past conditions.\n"
                "   - **Card 2 (Center):** Current situation & active lesson.\n"
                "   - **Card 3 (Right):** Potential outcome based on current trajectory.\n"
                "3. **Mind / Body / Spirit Spread:** Analyzes energetic alignment across your mental, physical, and spiritual planes.\n"
                "4. **The Celtic Cross (10 Cards):** The comprehensive classical spread revealing hidden obstacles, unconscious influences, and final synthesis."
            )

    # 2. I Ching Queries
    if "iching" in system_prompt.lower() or "i ching" in query or "hexagram" in query or "trigram" in query:
        matches = grimoire_service.search(query, category="iching")
        if matches:
            top = matches[0]
            hex_data = top.get("details", {})
            lines_md = "\n".join(f"- **Line {idx + 1}:** {line}" for idx, line in enumerate(hex_data.get("lines", [])))
            return (
                f"## ☯️ {top['title']}\n\n"
                f"**Upper Trigram:** {hex_data.get('upper_trigram')} · **Lower Trigram:** {hex_data.get('lower_trigram')} · **Element:** {hex_data.get('element', '')}\n\n"
                f"### The Judgment (彖)\n{hex_data.get('judgment', '')}\n\n"
                f"### The Image (象)\n{hex_data.get('image', hex_data.get('images', ''))}\n\n"
                f"### The Six Line Dynamics\n{lines_md}\n\n"
                f"> *Philosophical Wisdom:* {hex_data.get('meaning', 'Adapt with clarity to the transforming season.')}"
            )
        if "trigram" in query or "bagua" in query:
            return (
                "## ☯️ The 8 Bagua Trigrams (八卦)\n\n"
                "The I Ching is built from combinations of the eight primordial nature trigrams:\n\n"
                "1. **☰ Qián (Heaven):** Pure Yang, creative strength, leadership, northwest.\n"
                "2. **☷ Kūn (Earth):** Pure Yin, receptive devotion, mothering, southwest.\n"
                "3. **☵ Kǎn (Water/Abyss):** Flowing through danger, emotional depth, north.\n"
                "4. **☲ Lí (Fire/Clinging):** Clarity, illumination, consciousness, south.\n"
                "5. **☳ Zhèn (Thunder):** Arousing action, springtime, dynamic movement, east.\n"
                "6. **☴ Xùn (Wind/Wood):** Gentle penetration, subtle influence, southeast.\n"
                "7. **☶ Gèn (Mountain):** Keeping still, meditation, steadfastness, northeast.\n"
                "8. **☱ Duì (Lake/Joy):** Joyous expression, serenity, openness, west."
            )
        if "cast" in query or "coin" in query:
            return (
                "## ☯️ The 3-Coin Casting Method\n\n"
                "To cast a hexagram with 3 identical coins:\n\n"
                "- Assign **Heads = 3** (Yang) and **Tails = 2** (Yin).\n"
                "- Toss all 3 coins 6 times, recording from **bottom (Line 1) to top (Line 6)**:\n"
                "  - **6 (2+2+2):** Old Yin (changing broken line `--- x ---` -> solid).\n"
                "  - **7 (2+2+3):** Young Yang (stable solid line `-------`).\n"
                "  - **8 (2+3+3):** Young Yin (stable broken line `---   ---`).\n"
                "  - **9 (3+3+3):** Old Yang (changing solid line `--- o ---` -> broken).\n\n"
                "Lines 6 and 9 transform into their polar opposites to generate the resulting hexagram."
            )

    # 3. Astrology Queries
    if (
        "astrology" in system_prompt.lower()
        or "zodiac" in query
        or "sign" in query
        or "planet" in query
        or "aspect" in query
        or "house" in query
    ):
        matches = grimoire_service.search(query, category="planets")
        if matches:
            top = matches[0]
            p = top.get("details", {})
            return (
                f"## 🪐 Astrological Teaching: {top['title']}\n\n"
                f"**Cosmic Influence:** {p.get('influence', '')}\n\n"
                f"- **Chakra Resonance:** {p.get('chakra', 'N/A')}\n"
                f"- **Element & Metal:** {p.get('element', 'N/A')} · {p.get('metal', 'N/A')}\n"
                f"- **Sacred Minerals:** {', '.join(p.get('minerals', []))}\n"
                f"- **Aligned Herbs:** {', '.join(p.get('herbs', []))}\n"
                f"- **Harmonic Frequencies:** {', '.join(str(f) + ' Hz' for f in p.get('frequencies', []))}\n"
                f"- **Radionics Dial Rates:** {', '.join(str(r) for r in p.get('rates', []))}\n\n"
                f"> *Tutor Guidance:* When analyzing a chart, place this planet in its sign and house to see how its archetypal principle expresses through the native's life path."
            )
        if "sign" in query or "zodiac" in query:
            return (
                "## 🌟 The 12 Zodiac Signs & The 4 Elements\n\n"
                "The zodiac divides the ecliptic into 12 archetypal fields grouped by 4 elements and 3 modalities:\n\n"
                "- **🔥 Fire (Aries, Leo, Sagittarius):** Vitality, inspiration, initiative, dynamic passion.\n"
                "- **🌍 Earth (Taurus, Virgo, Capricorn):** Grounded pragmatism, material stability, manifest structure.\n"
                "- **💨 Air (Gemini, Libra, Aquarius):** Intellect, communication, social exchange, objective clarity.\n"
                "- **💧 Water (Cancer, Scorpio, Pisces):** Intuition, emotional empathy, psychic sensitivity, spiritual depth.\n\n"
                "**Modalities:**\n"
                "- **Cardinal (Aries, Cancer, Libra, Capricorn):** Initiators, pioneering momentum.\n"
                "- **Fixed (Taurus, Leo, Scorpio, Aquarius):** Stabilizers, persistent endurance.\n"
                "- **Mutable (Gemini, Virgo, Sagittarius, Pisces):** Adaptors, flexible transition."
            )
        if "house" in query:
            return (
                "## 🏛️ The 12 Astrological Houses (Life Arenas)\n\n"
                "The 12 houses represent where planetary energies manifest in daily existence:\n\n"
                "- **1st House (Ascendant):** Self, identity, physical appearance, vitality.\n"
                "- **2nd House:** Resources, personal values, material income.\n"
                "- **3rd House:** Communication, siblings, local environment, learning.\n"
                "- **4th House (IC):** Home, roots, family foundation, inner sanctuary.\n"
                "- **5th House:** Creativity, self-expression, children, joy.\n"
                "- **6th House:** Daily discipline, health, sacred service, work routine.\n"
                "- **7th House (Descendant):** Partnerships, marriage, one-on-one relationships.\n"
                "- **8th House:** Transformation, shared resources, occult mystery, rebirth.\n"
                "- **9th House:** Higher philosophy, spiritual quests, long journeys, dharma.\n"
                "- **10th House (MC):** Vocation, public reputation, worldly achievement.\n"
                "- **11th House:** Community, aspirational ideals, friendships, collective vision.\n"
                "- **12th House:** Unconscious psyche, spiritual liberation, meditation, solitude."
            )
        if "aspect" in query:
            return (
                "## 📐 The 5 Major Astrological Aspects\n\n"
                "Aspects describe geometric angular relationships between planetary nodes:\n\n"
                "- **Conjunction (0°):** Fusion of planetary energies into a unified powerhouse.\n"
                "- **Sextile (60°):** Harmonious opportunity, creative communication between compatible elements.\n"
                "- **Square (90°):** Dynamic friction, catalytic challenge compelling growth and action.\n"
                "- **Trine (120°):** Effortless flow, natural grace, mutual elemental harmony.\n"
                "- **Opposition (180°):** Polar tension requiring conscious balance and relational synthesis."
            )

    # 4. Sutra & Sacred Scripture Queries
    if (
        "sutra" in query
        or "shurangama" in query
        or "surangama" in query
        or "ushnisha" in query
        or "usnisa" in query
        or "casket" in query
        or "karanda" in query
        or "dharani" in query
        or "mantra" in query
    ):
        # Check specific famous sutras/dharanis first
        if "shurangama" in query or "surangama" in query or "楞嚴" in query:
            return (
                "## 📜 The Śūraṅgama Sūtra (楞嚴經 — The Sutra of the Heroic March)\n\n"
                "The **Śūraṅgama Sūtra** is the supreme Mahayana scripture on meditation, the nature of consciousness, and overcoming psychic/energetic obstacles on the path to Buddhahood.\n\n"
                "### 1. The True Mind vs. Conscious Illusion (Seven Inquiries into the Mind)\n"
                "The Buddha questions Ananda on where the 'mind' is located. Ananda offers seven locations (inside the body, outside, behind the sense organs, hidden within, between inner and outer, etc.) — all are systematically refuted. The Buddha reveals that the discriminating conscious mind is merely a shadow of external conditions, while the **True Mind (Tathāgatagarbha)** is unborn, unceasing, and ever-present luminous awareness.\n\n"
                "### 2. Avalokiteshvara's Organ of Hearing Penetration (耳根圓通)\n"
                "Among the 25 sages who describe their gateway to enlightenment, Bodhisattva Avalokiteshvara presents the practice of **turning the faculty of hearing inward** (*反聞聞自性*): entering the stream of hearing, forgetting external sounds, dissolving the duality of sound and silence, and resting in primordial stillness until the illusion of birth and death vanishes.\n\n"
                "### 3. The Great Śūraṅgama Mantra (楞嚴咒 / Sitātapatrā Dhāraṇī)\n"
                "The longest and most protective mantra in the Buddhist canon. It is taught as the indestructible diamond canopy (*Sitātapatrā*) protecting practitioners against the **50 Skandha Maras (五陰魔)** — the subtle psychic distortions of form, feeling, perception, impulse, and consciousness that arise during advanced samadhi."
            )

        if "ushnisha" in query or "usnisa" in query or "vijaya" in query or "尊勝" in query or "namgyalma" in query:
            return (
                "## 📜 The Uṣṇīṣa Vijaya Dhāraṇī Sūtra (佛頂尊勝陀羅尼經)\n\n"
                "The **Uṣṇīṣa Vijaya Dhāraṇī** ('Victorious Crown of the Buddha') is one of the most venerated longevity and karmic purification scriptures in East Asian and Tibetan Buddhism (where the deity is revered as **Namgyalma**).\n\n"
                "### 1. Origin & Purpose: The Rescue of Devaputra Sushthita\n"
                "The god Sushthita learned that upon his death he would fall from heaven to suffer seven consecutive rebirths as animals (dog, fox, monkey, snake, vulture, crow) and then fall into the lowest hells. Terrified, he sought refuge in the Buddha, who radiated rainbow light from His crown uṣṇīṣa and revealed this sacred Dharani, entirely reversing Sushthita's negative karma and granting him liberation.\n\n"
                "### 2. Purification of Heavy Karma & Liberation from Lower Realms\n"
                "Reciting the Uṣṇīṣa Vijaya Dharani eliminates all obstacles arising from past negative actions, cures chronic and terminal illnesses, and protects against untimely death. It is traditionally recited 21 times daily or 108 times during healing and memorial services.\n\n"
                "### 3. Consecration of Stupas and Wind-Blessing Pillars\n"
                "The sutra records that if this Dharani is engraved onto a high pillar, stupa, or mountain crest, any sentient being touched by the shadow of the pillar or by wind carrying dust from the stupa will have their karmic obscurations cleansed and gain rebirth in a pure land."
            )

        if "casket" in query or "karanda" in query or "guhyadhatu" in query or "寶篋印" in query or "relic" in query:
            return (
                "## 📿 The Guhyadhātu Karaṇḍa-mudrā Dhāraṇī (寶篋印陀羅尼)\n\n"
                "**Full Title:** *Ārya Sarva-tathāgatādhiṣṭhāna-hṛdaya Guhyadhātu Karaṇḍa-mudrā Dhāraṇī Sūtra* (*一切如來心秘密全身舍利寶篋印陀羅尼經* — The Secret Relic Casket Seal of the Heart-Essence of All Tathāgatas).\n\n"
                "### 1. The Reliquary of All Tathāgatas\n"
                "When the Buddha discovered a ruined, crumbling stupa in Magadha, He wept and prostrated before it. When Vajrapāṇi asked why, the Buddha revealed that within this single Dharani reside the **whole-body relics (*dhātu*) and heart-essence (*hṛdaya*) of all Buddhas of the ten directions**, past, present, and future, along with all 84,000 Dharma teachings.\n\n"
                "### 2. Transmutation of Ruin into Diamond\n"
                "The sutra teaches that whenever this Dharani is written, recited, or enshrined within a stupa, the ground transforms into an indestructible diamond reliquary. All Buddhas gather to bless it, celestial beings guard it, and whoever circumambulates it is liberated from poverty, suffering, and negative karmic cycles.\n\n"
                "### 3. Canonical Sanskrit Invocations\n"
                "- *Namas tryadhvikānāṃ sarva tathāgatānām...*\n"
                "- *Sarva-tathāgata-dhātu-dhare padmaṃ-bhavati...*\n"
                "- *Supratiṣṭhita-stūpe tathāgatādhiṣṭhite hūṃ hūṃ svāhā!*\n\n"
                "> *Application:* Highly recommended for stupa consecration, ancestor liberation, wishing fulfillment, and supreme energetic protection."
            )

        # General sutra search fallback
        matches = grimoire_service.search(query, category="sutras")
        if matches:
            top = matches[0]
            s_det = top.get("details", {})
            return (
                f"## 📜 {top['title']}\n\n"
                f"**Theme:** {s_det.get('theme', '').capitalize()} · **Sanskrit:** {s_det.get('sanskrit_name', '')}\n\n"
                f"### Sacred Scripture Passage\n"
                f"{s_det.get('passage', top['description'])}\n\n"
                f"### Context & Practice Meaning\n"
                f"{s_det.get('context', 'A profound Mahayana teaching on wisdom, compassion, and awakening.')}\n\n"
                f"> *Keywords:* {', '.join(s_det.get('tags', []))}"
            )

        mantra_matches = grimoire_service.search(query, category="mantras")
        if mantra_matches:
            top = mantra_matches[0]
            m_det = top.get("details", {})
            return (
                f"## 📿 {top['title']}\n\n"
                f"**Deity / Alignment:** {m_det.get('deity', 'All Buddhas')} · **Tradition:** {m_det.get('tradition', 'Mahayana/Vajrayana')}\n\n"
                f"### Sacred Mantra Text\n"
                f"```\n{m_det.get('text_sanskrit') or m_det.get('mantra', '')}\n```\n\n"
                f"- **Purpose:** {m_det.get('purpose') or m_det.get('meaning', '')}\n"
                f"- **Chakra Resonance:** {m_det.get('chakra', 'Heart')}\n"
                f"- **Frequency Tuning:** {m_det.get('frequency_hz', 'N/A')} Hz\n"
            )

    # 5. General Fallback
    return (
        f"## 📚 Esoteric Wisdom Lesson: {user_text.title()}\n\n"
        f"In traditional esoteric study, **{user_text}** connects the macrocosm (cosmic laws and astrological cycles) with the microcosm (the human subtle body and consciousness).\n\n"
        f"### Key Principles\n"
        f"1. **As Above, So Below:** The celestial cycles reflect internal psychological and energetic states.\n"
        f"2. **Harmonic Resonance:** Colors, minerals, herbs, and sound frequencies share vibrational signatures.\n"
        f"3. **Intuitive Synthesis:** Real mastery arises from integrating intellectual understanding with direct meditative contemplation.\n\n"
        f"> *Contemplation:* Select any specific card, hexagram, or planet in the Grimoire to explore its exact correspondences."
    )


@router.post("/teach", response_model=ChatResponse)
async def teach_interaction(request: ChatRequest, http_request: Request):
    """Clean LLM endpoint for educational use — no operator prompt, no tools.

    Unlike ``/chat``, this endpoint passes the caller's system message
    directly to the LLM without prepending the operator base prompt or
    exposing operator tool schemas. If no LLM provider is available, it
    falls back to the structured offline knowledge curriculum.
    """
    if not request.messages:
        raise HTTPException(status_code=400, detail="Message list cannot be empty")

    system_parts = [m.content for m in request.messages if m.role == "system"]
    system_prompt = "\n\n".join(system_parts) if system_parts else "You are a helpful teacher."
    chat_msgs = [m for m in request.messages if m.role != "system"]
    if not chat_msgs:
        raise HTTPException(status_code=400, detail="No user/assistant messages found")

    registry = getattr(http_request.app.state, "llm_registry", None)
    if not registry or not registry.providers:
        # Graceful offline teaching fallback
        fallback_text = _generate_offline_teach_response(chat_msgs, system_prompt)
        return ChatResponse(response=fallback_text, tool_calls=[])

    provider_name = await _select_provider_via_registry(http_request, request.provider or "auto")
    if not provider_name:
        provider_name = registry.providers[0].name if registry.providers else None
    if not provider_name:
        fallback_text = _generate_offline_teach_response(chat_msgs, system_prompt)
        return ChatResponse(response=fallback_text, tool_calls=[])

    chosen = None
    for p in registry.providers:
        if p.name == provider_name:
            chosen = p
            break
    if chosen is None:
        fallback_text = _generate_offline_teach_response(chat_msgs, system_prompt)
        return ChatResponse(response=fallback_text, tool_calls=[])

    from core.llm.models import ChatRequest as CoreChatRequest

    core_request = CoreChatRequest(
        messages=[{"role": m.role, "content": m.content} for m in chat_msgs],
        system_prompt=system_prompt,
        max_tokens=request.max_tokens or 1200,
        temperature=request.temperature or 0.7,
        model=request.model,
        stream=False,
        tools=[],
    )

    try:
        response = await retry_with_backoff(lambda: chosen.generate(core_request), max_retries=1, initial_backoff=0.5)
    except Exception as e:
        chain = await registry.failover_chain()
        for next_provider in chain:
            if next_provider.name == provider_name:
                continue
            try:
                response = await next_provider.generate(core_request)
                logger.info("Teach failover succeeded via %s", next_provider.name)
                break
            except Exception as e2:
                logger.warning("Teach failover to %s failed: %s", next_provider.name, e2)
                continue
        else:
            # All external LLM providers failed — fall back to structured curriculum
            logger.info("External LLMs failed for /teach; using offline knowledge fallback: %s", e)
            fallback_text = _generate_offline_teach_response(chat_msgs, system_prompt)
            return ChatResponse(response=fallback_text, tool_calls=[])

    clean_content = _chat_text(response)
    return ChatResponse(response=clean_content, tool_calls=[])


@router.get("/usage/summary")
async def get_usage_summary() -> dict:
    """Return the cumulative LLM usage summary.

    Totals (calls, tokens, cost), per-provider breakdown, daily cost vs cap,
    and the last 50 in-memory records. The JSONL log file on disk is the
    authoritative audit trail; this endpoint is the live view.
    """
    tracker = LLMUsageTracker.get()
    return tracker.get_summary()


@router.get("/usage/recent")
async def get_recent_usage(limit: int = 50) -> dict:
    """Return the most recent LLM calls (default 50, max 1000 in memory)."""
    tracker = LLMUsageTracker.get()
    records = tracker.recent_calls[-limit:]
    return {
        "calls": [
            {
                "timestamp": r.timestamp,
                "provider": r.provider,
                "model": r.model,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "cost_usd": r.cost_usd,
                "latency_ms": r.latency_ms,
                "endpoint": r.endpoint,
                "success": r.success,
            }
            for r in records
        ],
        "count": len(records),
    }


@router.get("/usage/reset")
async def reset_usage() -> dict:
    """Clear in-memory usage counters and records.

    The JSONL log file on disk is preserved for audit. Useful for testing
    and for starting a fresh accounting window without restarting the server.
    """
    tracker = LLMUsageTracker.get()
    tracker.reset()
    return {"status": "reset"}


@router.get("/models", summary="List available LLM models")
async def list_models():
    """List available local GGUF models and API configurations."""
    try:
        from core.llm.legacy_adapter import LegacyLLMIntegration as LLMIntegration

        llm = LLMIntegration(model_type="auto")
        available = llm.list_available_models()

        # Check active/loaded models in LM Studio via direct HTTP request
        import json as json_mod
        import urllib.error
        import urllib.request

        lm_studio_models = []
        lm_studio_url = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234")
        try:
            req = urllib.request.Request(f"{lm_studio_url}/v1/models")
            with urllib.request.urlopen(req, timeout=1.5) as response:
                models_data = json_mod.loads(response.read().decode())
                lm_studio_models = [m["id"] for m in models_data.get("data", [])]
        except Exception:
            pass

        # Determine the default selected model — prefer loaded LM Studio model
        default_model = ""
        if lm_studio_models:
            default_model = f"lm_studio:{lm_studio_models[0]}"
        elif available.get("local"):
            default_model = f"local:{available['local'][0]}"

        return {
            "status": "success",
            "available": {
                "local": [f"local:{m}" for m in available.get("local", [])],
                "api": available.get("api", []),
                "lm_studio": lm_studio_models,
            },
            "default_model": default_model,
            "lm_studio_connected": len(lm_studio_models) > 0 or default_model != "",
        }
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        return {
            "status": "success",
            "available": {"local": [], "api": [], "lm_studio": []},
            "default_model": "",
            "lm_studio_connected": False,
        }


@router.get("/providers/health")
async def get_providers_health(request: Request) -> dict:
    """Return current health status for all registered providers."""
    registry = getattr(request.app.state, "llm_registry", None)
    if registry is None or len(registry) == 0:
        return {
            "providers": [],
            "healthy_count": 0,
            "total_count": 0,
            "message": "LLM registry not initialized",
        }
    statuses = await registry.health_check_all()
    return {
        "providers": [s.model_dump() for s in statuses],
        "healthy_count": sum(1 for s in statuses if s.healthy),
        "total_count": len(statuses),
    }


PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "openai": {"label": "OpenAI", "requires_api_key": True, "default_priority": 50},
    "anthropic": {"label": "Anthropic", "requires_api_key": True, "default_priority": 60},
    "openrouter": {"label": "OpenRouter", "requires_api_key": True, "default_priority": 90},
    "deepseek": {"label": "DeepSeek", "requires_api_key": True, "default_priority": 70},
    "z_ai": {"label": "Z.AI", "requires_api_key": True, "default_priority": 65},
    "minimax": {"label": "MiniMax", "requires_api_key": True, "default_priority": 40},
    "lm_studio": {"label": "LM Studio", "requires_api_key": False, "default_priority": 80},
    "local_gguf": {"label": "Local GGUF", "requires_api_key": False, "default_priority": 30},
}


class ProviderRegisterRequest(BaseModel):
    provider: str
    api_key: str | None = None
    base_url: str | None = None
    priority: int | None = None


class ProviderTestRequest(BaseModel):
    provider: str
    api_key: str | None = None
    base_url: str | None = None


class ProviderUnregisterRequest(BaseModel):
    provider: str


def _provider_factory(name: str):
    from core.llm.providers import (
        AnthropicProvider,
        DeepSeekProvider,
        LMStudioProvider,
        LocalGGUFProvider,
        MinimaxProvider,
        OpenAIProvider,
        OpenRouterProvider,
        ZAIProvider,
    )

    return {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "openrouter": OpenRouterProvider,
        "deepseek": DeepSeekProvider,
        "z_ai": ZAIProvider,
        "minimax": MinimaxProvider,
        "lm_studio": LMStudioProvider,
        "local_gguf": LocalGGUFProvider,
    }[name]


@router.get("/providers/available")
async def providers_available() -> dict:
    """Return the static catalog of providers the UI can register."""
    return {"providers": PROVIDER_CATALOG}


@router.post("/providers/discover")
async def providers_discover() -> dict:
    """Probe local LM Studio and report discovered vs unreachable endpoints."""
    entry: dict[str, Any] = {
        "name": "lm_studio",
        "base_url": "http://localhost:1234/v1",
        "reachable": False,
        "models": [],
        "error": None,
    }
    discovered: list[dict[str, Any]] = []
    unreachable: list[dict[str, Any]] = []
    try:
        import httpx

        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get("http://localhost:1234/v1/models")
        if resp.status_code == 200:
            payload = resp.json()
            models = payload.get("data", []) if isinstance(payload, dict) else []
            entry["reachable"] = True
            entry["models"] = [m.get("id") for m in models if isinstance(m, dict)]
            discovered.append(entry)
        else:
            entry["error"] = f"HTTP {resp.status_code}"
            unreachable.append(entry)
    except Exception as exc:
        entry["error"] = str(exc)[:200]
        unreachable.append(entry)
    return {"discovered": discovered, "unreachable": unreachable}


@router.post("/providers/test")
async def providers_test(req: ProviderTestRequest) -> dict:
    if req.provider not in PROVIDER_CATALOG:
        raise HTTPException(
            status_code=400,
            detail=f"{req.provider} is not a supported provider. Supported: {sorted(PROVIDER_CATALOG)}",
        )
    try:
        factory = _provider_factory(req.provider)
        kwargs: dict[str, Any] = {}
        if req.api_key:
            kwargs["api_key"] = req.api_key
        if req.base_url:
            kwargs["base_url"] = req.base_url
        provider = factory(**kwargs)
        status = await provider.health_check()
        return {
            "reachable": bool(status.healthy),
            "provider": req.provider,
            "error": None if status.healthy else getattr(status, "message", None) or getattr(status, "error", None),
        }
    except Exception as exc:
        return {"reachable": False, "provider": req.provider, "error": str(exc)[:200]}


@router.post("/providers/register")
async def providers_register(req: ProviderRegisterRequest, request: Request) -> dict:
    if req.provider not in PROVIDER_CATALOG:
        raise HTTPException(
            status_code=400,
            detail=f"{req.provider} is not a supported provider. Supported: {sorted(PROVIDER_CATALOG)}",
        )
    meta = PROVIDER_CATALOG[req.provider]
    if meta["requires_api_key"] and not req.api_key:
        raise HTTPException(status_code=400, detail="API key is required for this provider")
    registry = getattr(request.app.state, "llm_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="LLM registry not initialized")
    if any(p.name == req.provider for p in registry.providers):
        raise HTTPException(status_code=409, detail=f"{req.provider} is already registered")
    factory = _provider_factory(req.provider)
    kwargs: dict[str, Any] = {}
    if req.api_key:
        kwargs["api_key"] = req.api_key
    if req.base_url:
        kwargs["base_url"] = req.base_url
    if req.priority is not None:
        kwargs["priority"] = req.priority
    provider = factory(**kwargs)
    registry.register(provider)
    return {"registered": req.provider, "priority": provider.priority}


@router.post("/providers/unregister")
async def providers_unregister(req: ProviderUnregisterRequest, request: Request) -> dict:
    registry = getattr(request.app.state, "llm_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="LLM registry not initialized")
    if not any(p.name == req.provider for p in registry.providers):
        raise HTTPException(status_code=404, detail=f"{req.provider} is not registered")
    registry.unregister(req.provider)
    return {"unregistered": req.provider}


# ============================ Model Discovery & Management ============================
# Endpoints added under /api/v1/llm/models/* — dynamic OpenRouter discovery
# (cached 5 min), user-saved custom model registry, and a fast test probe.

# In-memory cache for the OpenRouter /models response. Held at module scope so
# all worker tasks share it. The lock is created lazily inside the handler so
# constructing it does not require a running event loop on import (Windows).
_AVAILABLE_MODELS_CACHE: dict[str, Any] = {"fetched_at": 0.0, "models": [], "source": ""}
_AVAILABLE_MODELS_TTL_SECONDS: float = 300.0  # 5 minutes
_AVAILABLE_MODELS_LOCK: asyncio.Lock | None = None


def _get_available_models_lock() -> asyncio.Lock:
    """Lazy-init the module-level asyncio.Lock for the discovery cache.

    ``asyncio.Lock()`` must be created inside a running loop on Windows;
    constructing it at import time raises ``RuntimeError`` under some
    ProactorEventLoop configurations.
    """
    global _AVAILABLE_MODELS_LOCK
    if _AVAILABLE_MODELS_LOCK is None:
        _AVAILABLE_MODELS_LOCK = asyncio.Lock()
    return _AVAILABLE_MODELS_LOCK


# Path to the user's saved custom model list (JSON file in the home dir).
CUSTOM_MODELS_PATH: Path = Path.home() / ".vajra-stream" / "custom_models.json"

# OpenRouter public catalogue URL. No API key required for read.
OPENROUTER_MODELS_URL: str = "https://openrouter.ai/api/v1/models"

# OpenRouter chat-completions URL used by the test probe.
OPENROUTER_CHAT_URL: str = "https://openrouter.ai/api/v1/chat/completions"

# Probe prompt sent by POST /models/{id}/test. Kept tiny so the test
# is fast and ~free even on paid models.
_TEST_PROBE_PROMPT: str = "Say 'Hello' in one word."


class AvailableModel(BaseModel):
    """A single model entry returned by ``GET /models/available``.

    Fields are a normalized subset of the OpenRouter /models payload,
    enriched with a ``featured`` flag for the curated built-in set and
    a ``source`` indicating where the entry came from.
    """

    id: str
    name: str
    provider: str
    context_length: int | None = None
    input_per_m: float = 0.0
    output_per_m: float = 0.0
    is_free: bool = False
    featured: bool = False
    description: str = ""
    source: str = "openrouter"  # 'openrouter' | 'lm_studio' | 'local_gguf'


class AddCustomModelRequest(BaseModel):
    """Request body for ``POST /models/add``."""

    model_id: str
    display_name: str
    provider: str = "openrouter"


class SavedCustomModel(BaseModel):
    """An entry persisted in ``~/.vajra-stream/custom_models.json``."""

    model_id: str
    display_name: str
    provider: str
    added_at: str  # ISO-8601 timestamp


def _load_custom_models() -> list[dict]:
    """Load the user's saved custom models from disk.

    Returns an empty list if the file does not exist or is corrupt
    (a warning is logged on parse failure; the file is left untouched).
    """
    try:
        if CUSTOM_MODELS_PATH.exists():
            raw = CUSTOM_MODELS_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                return [m for m in data if isinstance(m, dict)]
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                return [m for m in data["models"] if isinstance(m, dict)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read custom models file %s: %s", CUSTOM_MODELS_PATH, exc)
    return []


def _save_custom_models(models: list[dict]) -> None:
    """Persist the custom-model list to disk, creating the parent dir."""
    try:
        CUSTOM_MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
        CUSTOM_MODELS_PATH.write_text(
            json.dumps(models, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to write custom models file %s: %s", CUSTOM_MODELS_PATH, exc)
        raise


def _detect_provider(model_id: str) -> str:
    """Best-effort provider extraction from a model id prefix.

    OpenRouter model ids look like ``vendor/model-name``. We take the
    first slash-separated segment. Falls back to ``"openrouter"`` for
    unscoped ids.
    """
    if "/" in model_id:
        return model_id.split("/", 1)[0].lower()
    return "openrouter"


async def _fetch_openrouter_models_uncached() -> list[dict]:
    """Hit ``GET https://openrouter.ai/api/v1/models`` and normalize rows.

    Returns an empty list on any failure (timeout, HTTP error, parse
    error) — the caller surfaces a graceful "no models" state rather
    than a 5xx. Requires ``aiohttp``; if it is not installed, returns
    ``[]`` immediately.
    """
    if aiohttp is None:
        logger.warning("aiohttp not installed — OpenRouter model discovery unavailable")
        return []
    try:
        timeout = aiohttp.ClientTimeout(total=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(OPENROUTER_MODELS_URL) as resp:
                if resp.status != 200:
                    logger.warning("OpenRouter /models returned HTTP %s", resp.status)
                    return []
                payload = await resp.json()
    except Exception as exc:  # noqa: BLE001 — discovery must never 5xx
        logger.warning("OpenRouter /models fetch failed: %s", exc)
        return []

    rows = payload.get("data", []) if isinstance(payload, dict) else []
    featured_set = set(KNOWN_FEATURED_MODEL_IDS)
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id") or ""
        if not model_id:
            continue
        pricing = row.get("pricing") or {}
        try:
            prompt_per_token = float(pricing.get("prompt") or "0")
            completion_per_token = float(pricing.get("completion") or "0")
        except (TypeError, ValueError):
            prompt_per_token = 0.0
            completion_per_token = 0.0
        input_per_m = prompt_per_token * 1_000_000.0
        output_per_m = completion_per_token * 1_000_000.0
        is_free = input_per_m == 0.0 and output_per_m == 0.0
        try:
            ctx_len = int(row.get("context_length") or 0) or None
        except (TypeError, ValueError):
            ctx_len = None
        out.append(
            {
                "id": model_id,
                "name": row.get("name") or model_id,
                "provider": _detect_provider(model_id),
                "context_length": ctx_len,
                "input_per_m": input_per_m,
                "output_per_m": output_per_m,
                "is_free": is_free,
                "featured": model_id in featured_set,
                "description": (row.get("description") or "")[:500],
                "source": "openrouter",
            }
        )
    return out


async def _fetch_lm_studio_models_uncached() -> list[dict]:
    """Best-effort list of locally-loaded LM Studio models.

    Returns ``[]`` if LM Studio is not running or unreachable; never
    raises. Uses urllib (sync) wrapped in a thread so it does not
    block the event loop and does not add an aiohttp dependency for
    this optional local probe.
    """
    import urllib.error
    import urllib.request

    base_url = os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234").rstrip("/")

    def _do_fetch() -> list[dict]:
        try:
            req = urllib.request.Request(f"{base_url}/v1/models")
            with urllib.request.urlopen(req, timeout=1.5) as response:  # noqa: S310 — local
                data = json.loads(response.read().decode())
            out: list[dict] = []
            for m in data.get("data", []):
                mid = m.get("id") or ""
                if not mid:
                    continue
                out.append(
                    {
                        "id": f"lm_studio:{mid}",
                        "name": mid,
                        "provider": "lm_studio",
                        "context_length": m.get("context_length"),
                        "input_per_m": 0.0,
                        "output_per_m": 0.0,
                        "is_free": True,
                        "featured": False,
                        "description": "Locally hosted via LM Studio",
                        "source": "lm_studio",
                    }
                )
            return out
        except Exception:  # noqa: BLE001 — LM Studio probe must be silent
            return []

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_fetch)


@router.get("/models/available", summary="List all available OpenRouter models")
async def list_available_models() -> dict:
    """Return the full OpenRouter model catalogue (cached 5 minutes).

    Merges:
      1. OpenRouter public /models response (300+ entries) — cached for
         ``_AVAILABLE_MODELS_TTL_SECONDS`` so we never hit OpenRouter on
         every page load.
      2. Locally-loaded LM Studio models (no cache; probed every call).

    Each entry is normalized to the :class:`AvailableModel` shape and
    tagged with ``featured=True`` if it appears in
    :data:`core.llm.defaults.KNOWN_FEATURED_MODEL_IDS`. The Nemotron
    free model is always included even if OpenRouter omits it.
    """
    global _AVAILABLE_MODELS_CACHE
    lock = _get_available_models_lock()
    async with lock:
        now = time.time()
        cached = _AVAILABLE_MODELS_CACHE
        needs_refresh = (now - cached.get("fetched_at", 0.0)) > _AVAILABLE_MODELS_TTL_SECONDS
        or_models: list[dict] = []
        if needs_refresh:
            or_models = await _fetch_openrouter_models_uncached()
            if or_models:
                cached["fetched_at"] = now
                cached["models"] = or_models
                cached["source"] = "openrouter"
            else:
                # Keep stale cache if we have one; otherwise seed with the
                # built-in featured set so the UI is never empty.
                if not cached.get("models"):
                    set(KNOWN_FEATURED_MODEL_IDS)
                    cached["models"] = [
                        {
                            "id": mid,
                            "name": mid.split("/")[-1],
                            "provider": _detect_provider(mid),
                            "context_length": None,
                            "input_per_m": 0.0,
                            "output_per_m": 0.0,
                            "is_free": mid.endswith(":free"),
                            "featured": True,
                            "description": "Built-in featured model",
                            "source": "builtin",
                        }
                        for mid in KNOWN_FEATURED_MODEL_IDS
                    ]
                    cached["source"] = "builtin"
        or_models = list(cached.get("models", []))

    # Merge LM Studio models (always probed; cheap and local).
    lm_models = await _fetch_lm_studio_models_uncached()

    # Defensive: ensure Nemotron is always present even if OpenRouter
    # transiently drops it from the catalogue.
    if not any(m.get("id") == NEMOTRON_FREE_MODEL_ID for m in or_models):
        or_models.insert(
            0,
            {
                "id": NEMOTRON_FREE_MODEL_ID,
                "name": "Nemotron 3 Ultra 550B (Free)",
                "provider": "nvidia",
                "context_length": 1_000_000,
                "input_per_m": 0.0,
                "output_per_m": 0.0,
                "is_free": True,
                "featured": True,
                "description": "550B MoE, 1M context, $0 input / $0 output. Built-in default.",
                "source": "builtin",
            },
        )

    # Validate rows against the Pydantic model for a stable contract.
    validated: list[dict] = []
    for m in or_models + lm_models:
        try:
            validated.append(AvailableModel(**m).model_dump())
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping malformed available-model row %r: %s", m, exc)

    return {
        "status": "success",
        "count": len(validated),
        "fetched_at": cached.get("fetched_at"),
        "source": cached.get("source", ""),
        "models": validated,
    }


@router.get("/models/saved", summary="List user-saved custom models")
async def list_saved_models() -> dict:
    """Return the user's saved-model list from ``~/.vajra-stream/custom_models.json``."""
    models = _load_custom_models()
    # Normalize each row before returning.
    out: list[dict] = []
    for m in models:
        try:
            out.append(
                SavedCustomModel(
                    model_id=str(m.get("model_id", "")),
                    display_name=str(m.get("display_name", "")),
                    provider=str(m.get("provider", "openrouter")),
                    added_at=str(m.get("added_at", "")),
                ).model_dump()
            )
        except Exception:  # noqa: BLE001
            continue
    return {"status": "success", "count": len(out), "models": out}


@router.post("/models/add", summary="Add a custom model to the saved list")
async def add_custom_model(req: AddCustomModelRequest) -> dict:
    """Add ``model_id`` to the user's saved custom model list.

    Persisted to ``~/.vajra-stream/custom_models.json`` (file is created
    if missing). Adding the same ``model_id`` twice updates the display
    name and provider in place rather than creating a duplicate.
    """
    model_id = req.model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")
    provider = (req.provider or _detect_provider(model_id)).strip() or "openrouter"
    display_name = (req.display_name or model_id).strip()

    models = _load_custom_models()
    added_at = _now_iso()
    for m in models:
        if m.get("model_id") == model_id:
            m["display_name"] = display_name
            m["provider"] = provider
            m["added_at"] = added_at
            _save_custom_models(models)
            return {"status": "updated", "model": m}
    entry = {
        "model_id": model_id,
        "display_name": display_name,
        "provider": provider,
        "added_at": added_at,
    }
    models.append(entry)
    _save_custom_models(models)
    return {"status": "added", "model": entry}


@router.delete("/models/{model_id:path}", summary="Remove a saved custom model")
async def delete_custom_model(model_id: str) -> dict:
    """Remove ``model_id`` from the saved custom model list.

    Silently succeeds (``status: "not_found"``) if the model was not in
    the saved list — DELETE should be idempotent.
    """
    models = _load_custom_models()
    before = len(models)
    models = [m for m in models if m.get("model_id") != model_id]
    if len(models) == before:
        return {"status": "not_found", "model_id": model_id}
    _save_custom_models(models)
    return {"status": "deleted", "model_id": model_id}


class ModelTestResponse(BaseModel):
    """Result of a single model probe."""

    success: bool
    response: str = ""
    latency_ms: float = 0.0
    tokens_used: int = 0
    cost_estimate: float = 0.0
    error: str = ""


@router.post(
    "/models/{model_id:path}/test",
    summary="Send a tiny probe prompt to a model and report latency + cost",
    response_model=ModelTestResponse,
)
async def test_model(model_id: str) -> ModelTestResponse:
    """Send ``"Say 'Hello' in one word."`` to ``model_id`` and report.

    Uses the OpenRouter chat-completions endpoint with a hard 15-second
    timeout. Cost is estimated via :class:`LLMUsageTracker` using the
    per-model pricing table. Returns a 200 with ``success: false`` on
    any failure (timeout, missing key, HTTP error) so the frontend can
    render the error inline without a 5xx.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return ModelTestResponse(
            success=False,
            error="OPENROUTER_API_KEY not set — cannot probe remote models.",
        )
    if aiohttp is None:
        return ModelTestResponse(
            success=False,
            error="aiohttp not installed — model probe unavailable.",
        )

    started = time.time()
    try:
        async with asyncio.timeout(15.0):
            timeout = aiohttp.ClientTimeout(total=15.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    OPENROUTER_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": _TEST_PROBE_PROMPT}],
                        "max_tokens": 16,
                    },
                ) as resp:
                    latency_ms = (time.time() - started) * 1000.0
                    body = await resp.json()
                    if resp.status >= 400:
                        err_msg = (
                            body.get("error", {}).get("message") if isinstance(body, dict) else f"HTTP {resp.status}"
                        ) or f"HTTP {resp.status}"
                        return ModelTestResponse(
                            success=False,
                            latency_ms=latency_ms,
                            error=str(err_msg)[:300],
                        )
                    choices = body.get("choices") or []
                    text = ""
                    if choices and isinstance(choices[0], dict):
                        msg = choices[0].get("message") or {}
                        text = str(msg.get("content") or "").strip()
                    usage = body.get("usage") or {}
                    prompt_toks = int(usage.get("prompt_tokens") or 0)
                    completion_toks = int(usage.get("completion_tokens") or 0)
                    total_toks = prompt_toks + completion_toks
                    cost = LLMUsageTracker.get().estimate_cost("openrouter", model_id, prompt_toks, completion_toks)
                    # Record the probe so the usage dashboard reflects it.
                    _record_llm_usage(
                        provider="openrouter",
                        model=model_id,
                        prompt_tokens=prompt_toks,
                        completion_tokens=completion_toks,
                        latency_ms=latency_ms,
                        endpoint="model_test",
                    )
                    return ModelTestResponse(
                        success=True,
                        response=text,
                        latency_ms=latency_ms,
                        tokens_used=total_toks,
                        cost_estimate=cost,
                    )
    except asyncio.TimeoutError:
        return ModelTestResponse(
            success=False,
            latency_ms=(time.time() - started) * 1000.0,
            error="Probe timed out after 15s.",
        )
    except Exception as exc:  # noqa: BLE001
        return ModelTestResponse(
            success=False,
            latency_ms=(time.time() - started) * 1000.0,
            error=f"Probe failed: {exc}"[:300],
        )


@router.get("/models/defaults", summary="Return the recommended default model per use case")
async def get_default_models() -> dict:
    """Expose :data:`core.llm.defaults.DEFAULT_MODELS_BY_USE_CASE` to the UI.

    Used by the Model Manager's "Active Model Display" section so the
    recommended default for each feature (outlook, chat, blessing loop,
    operator, divination, TTS) is rendered from a single source of truth.
    """
    return {
        "status": "success",
        "defaults": DEFAULT_MODELS_BY_USE_CASE,
    }


def _now_iso() -> str:
    """ISO-8601 UTC timestamp for persisted ``added_at`` fields."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# Nemotron Ultra on the OpenRouter :free pool regularly takes 1–3 minutes
# (reasoning tokens, then the public reply). The previous 75s job budget
# and 25s per-tool cap aborted the call while the model was still thinking.
_CHAT_JOB_TIMEOUT = 240.0
_DEFAULT_TOOL_TIMEOUT = 25.0
_TOOL_TIMEOUTS: dict[str, float] = {
    "generate_single_outlook": 200.0,
    "generate_epic_outlook": 300.0,
}


# ── Async chat support ──────────────────────────────────────────────


async def _run_chat_async(
    job_id: str,
    request: ChatRequest,
    http_request: Request,
    connection_id: str | None,
) -> None:
    """Background task: run the tool loop and push progress via WebSocket."""
    from backend.app.api.v1.chat_job_manager import (
        add_event,
        get_job,
        is_cancelled,
        update_job,
    )
    from backend.websocket.connection_manager import stable_connection_manager_v2

    async def _push(event_type: str, data: dict) -> None:
        if not connection_id:
            return
        await stable_connection_manager_v2.send_personal_message(
            {"type": event_type, "job_id": job_id, **data},
            connection_id,
        )

    async def _tracking_execute(name: str, args: dict):
        update_job(job_id, status="running", phase=f"tool:{name}")
        await _push("chat_tool_start", {"tool": name, "args": args})
        add_event(job_id, {"type": "tool_start", "tool": name, "args": args})
        tool_timeout = _TOOL_TIMEOUTS.get(name, _DEFAULT_TOOL_TIMEOUT)
        try:
            result = await asyncio.wait_for(execute_tool_locally(name, args), timeout=tool_timeout)
            await _push("chat_tool_complete", {"tool": name, "result": _safe_serialize(result)})
            add_event(job_id, {"type": "tool_complete", "tool": name, "result": _safe_serialize(result)})
            return result
        except TimeoutError:
            err = f"Tool {name} timed out after {int(tool_timeout)}s"
            await _push("chat_tool_error", {"tool": name, "error": err})
            add_event(job_id, {"type": "tool_error", "tool": name, "error": err})
            raise RuntimeError(err)
        except Exception as ex:
            await _push("chat_tool_error", {"tool": name, "error": str(ex)})
            add_event(job_id, {"type": "tool_error", "tool": name, "error": str(ex)})
            raise

    try:
        update_job(job_id, status="running", phase="starting")
        await _push("chat_started", {"message": "Processing your request..."})

        async def _run_body():
            update_job(job_id, status="running", phase="selecting_provider")
            provider_name = _resolve_provider_name(request, http_request)
            if provider_name == "auto":
                registry_choice = await _select_provider_via_registry(http_request, "auto")
                if registry_choice:
                    provider_name = registry_choice
            update_job(job_id, status="running", phase=f"generate:{provider_name}")
            await _push("chat_started", {"message": f"Calling {provider_name}..."})
            return await _chat_via_registry(
                http_request,
                request,
                provider_name,
                tool_schemas=get_tool_schemas(),
                tool_executor=_tracking_execute,
            )

        try:
            response = await asyncio.wait_for(_run_body(), timeout=_CHAT_JOB_TIMEOUT)
        except TimeoutError:
            phase = (get_job(job_id) or {}).get("phase") or "generate"
            msg = f"Timed out after {int(_CHAT_JOB_TIMEOUT)}s while {phase}. The model or a tool never returned."
            logger.error("Async chat job %s: %s", job_id, msg)
            update_job(job_id, status="error", error=msg)
            await _push("chat_error", {"error": msg})
            return
        if is_cancelled(job_id):
            await _push("chat_cancelled", {})
            return
        update_job(
            job_id,
            status="completed",
            response=response.response,
            tool_calls=[t.model_dump() for t in response.tool_calls],
            debug_info=response.debug_info,
        )
        await _push(
            "chat_complete",
            {
                "response": response.response,
                "tool_calls": [t.model_dump() for t in response.tool_calls],
                "debug_info": response.debug_info,
            },
        )

    except asyncio.CancelledError:
        update_job(job_id, status="cancelled")
        await _push("chat_cancelled", {})
        raise
    except Exception as ex:
        if is_cancelled(job_id):
            await _push("chat_cancelled", {})
            return
        logger.exception("Async chat job %s failed", job_id)
        update_job(job_id, status="error", error=str(ex))
        await _push("chat_error", {"error": str(ex)})


_FOLLOWUP_DROP_KEYS = frozenset({"svg", "ai_image", "image_data_url", "image"})
_META_USER_RE = re.compile(
    r"\b(do you have|information that you need|glad you|finally run|check out if|"
    r"maybe check|did you|can you see)\b",
    re.IGNORECASE,
)


def _chat_text(response: Any) -> str:
    """Visible reply for Command Center — strip think tokens and stutter."""
    return collapse_stutter(
        visible_text(getattr(response, "content", None), getattr(response, "reasoning_content", None))
    )


def _latest_user_text(messages: list) -> str:
    for message in reversed(messages):
        if getattr(message, "role", None) == "user":
            return str(getattr(message, "content", "") or "")
    return ""


def _intention_from_messages(messages: list) -> str:
    """Prefer the original sitting intention over a follow-up meta question."""
    texts = [str(getattr(m, "content", "") or "").strip() for m in messages if getattr(m, "role", None) == "user"]
    texts = [t for t in texts if t]
    for text in texts:
        if not _META_USER_RE.search(text) and len(text) > 12:
            return text[:400]
    return (texts[-1] if texts else "all beings")[:400]


def _summarize_population_list(items: list, limit: int = 800) -> str:
    names: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        extra = item.get("mantra_preference") or item.get("category") or ""
        names.append(f"{name} ({extra})" if extra else name)
        if len(names) >= 20:
            break
    return f"{len(items)} listed, {len(seen)} unique: " + "; ".join(names)


def _summarize_tool_result(result: Any, limit: int = 800) -> str:
    """Compact a tool result for the follow-up LLM turn.

    Divination tools return inline SVG (often >2KB). Stuffing that back into
    the next prompt makes free models echo JSON/SVG into the chat bubble.
    Population lists must not dump every row — a wall of "California" makes
    Nemotron stutter the name hundreds of times in the summary.
    """
    if isinstance(result, list):
        if result and isinstance(result[0], dict):
            return _summarize_population_list(result, limit)[:limit]
        return str(result)[:limit]

    if not isinstance(result, dict):
        return str(result)[:limit]

    if result.get("narrative"):
        slim = {
            "genre": result.get("genre"),
            "model_used": result.get("model_used"),
            "astrology": str(result.get("astrology_used") or "")[:160],
            "divination": str(result.get("divination_used") or "")[:160],
            "entities": str(result.get("entities_used") or "")[:160],
            "narrative_excerpt": str(result.get("narrative") or "")[:280],
        }
        return json.dumps(slim, default=str)[:limit]

    slim: dict[str, Any] = {}
    for key, value in result.items():
        if key.lower() in _FOLLOWUP_DROP_KEYS:
            continue
        if isinstance(value, str) and (value.lstrip().startswith("<svg") or len(value) > 400):
            slim[key] = f"<{key} omitted, {len(value)} chars>"
            continue
        if isinstance(value, list) and value and isinstance(value[0], dict):
            slim[key] = [
                {ik: iv for ik, iv in item.items() if ik.lower() not in _FOLLOWUP_DROP_KEYS}
                if isinstance(item, dict)
                else item
                for item in value[:12]
            ]
            continue
        slim[key] = value
    return json.dumps(slim, default=str)[:limit]


def _safe_serialize(obj: Any) -> Any:
    """Serialize tool result for JSON transport."""
    if isinstance(obj, str | int | float | bool | type(None)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_safe_serialize(v) for v in obj]
    return str(obj)


# Names the ProviderRegistry actually registers. Catalog vendor prefixes
# (nvidia/, meta/, google/) are OpenRouter slugs, not registry providers.
_REGISTRY_PROVIDERS = frozenset(
    {
        "auto",
        "openrouter",
        "lm_studio",
        "local",
        "deepseek",
        "anthropic",
        "openai",
        "minimax",
        "z_ai",
    }
)


def _normalize_model_id(model: str | None) -> str | None:
    """Strip launcher prefixes so the provider sees a bare model id."""
    if not model:
        return model
    for prefix in ("lm_studio:", "local:"):
        if model.startswith(prefix):
            return model[len(prefix) :]
    return model


def _provider_for_model(provider: str | None, model: str | None) -> str:
    """Map a chat request onto a registered provider name.

    OpenRouter catalog ids look like ``nvidia/nemotron-…``. Treating the
    first path segment as the provider used to send an OpenRouter model
    to a non-existent ``nvidia`` backend (or to ``pick_best``, which can
    pick LM Studio). Slash-ids go to OpenRouter unless the caller named
    a real registry provider.
    """
    requested = (provider or "auto").strip() or "auto"
    mid = model or ""
    if mid.startswith("lm_studio:"):
        return "lm_studio"
    if mid.startswith("local:"):
        return "local"
    # Catalog slugs (deepseek/..., poolside/laguna-...) are OpenRouter ids.
    # Honour them even if the picker labeled the vendor "deepseek".
    if "/" in mid:
        return "openrouter"
    if requested in _REGISTRY_PROVIDERS and requested != "auto":
        return requested
    return requested


def _resolve_provider_name(request: ChatRequest, http_request: Request) -> str:
    return _provider_for_model(request.provider, request.model)
