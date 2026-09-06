"""
LLM Agent Tool Calling Interface for Vajra Stream

Provides a standardized interface for LLM agents to interact with the Vajra Stream
radionics system via tool calling (function calling).

Each function is designed to be called by an LLM agent and returns structured data
that can be used in the agent's responses.

Every tool runs IN-PROCESS against the backing service or endpoint function.
Tools must not HTTP back into this same FastAPI process — the socket hop can
deadlock a saturated worker, couples tools to port 8008, and lets endpoint
paths silently drift into 404 ghosts.
"""

import os
import time
from typing import Any

from core.situation_geometry import DEFAULT_LAT, DEFAULT_LNG

# ============================================================================
# IN-PROCESS BRIDGE
# ----------------------------------------------------------------------------
# ``_run_async`` bridges sync tool bodies to async services on the persistent
# background loop (safe from inside a running event loop); ``_spawn`` is the
# fire-and-forget twin for background work like audio playback.
# ============================================================================


def _run_async(coro: Any) -> Any:
    """Run an async service call from a sync tool body and return its result."""
    from core.llm.legacy_adapter import run_async

    return run_async(coro)


def _spawn(coro: Any) -> None:
    """Schedule an async side-effect (e.g. audio playback) without waiting."""
    from core.llm.legacy_adapter import spawn_async

    spawn_async(coro)


def _dump(result: Any) -> Any:
    """Normalize a Pydantic model returned by an endpoint function to a dict."""
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result


# ============================================================================
# RNG ATTUNEMENT TOOLS
# ============================================================================


def create_rng_session(baseline_tone_arm: float = 5.0, sensitivity: float = 1.0) -> dict[str, Any]:
    """
    Create a new RNG attunement session for monitoring psychoenergetic activity.

    Use this when:
    - User wants to monitor RNG during practice
    - Starting manual radionics session
    - Need floating needle detection

    Args:
        baseline_tone_arm: Baseline setting (0-10), default 5.0
        sensitivity: Sensitivity multiplier (0.1-5.0), default 1.0

    Returns:
        {"session_id": "rng_1234567890_abcdef12"}
    """
    from backend.core.services.rng_attunement_service import get_rng_service

    service = get_rng_service()
    session_id = service.create_session(baseline_tone_arm=baseline_tone_arm, sensitivity=sensitivity)
    return {"session_id": session_id}


def get_rng_reading(session_id: str) -> dict[str, Any]:
    """
    Get current RNG reading including needle state and floating needle score.

    Use this for:
    - Monitoring psychoenergetic activity
    - Checking for floating needle (score > 0.6)
    - Real-time feedback during practice

    Args:
        session_id: RNG session ID from create_rng_session

    Returns:
        {
            "tone_arm": 5.2,
            "needle_position": 15.3,
            "needle_state": "rising",
            "floating_needle_score": 0.73,
            "coherence_index": 0.65,
            "entropy": 0.82
        }
    """
    from backend.core.services.rng_attunement_service import get_rng_service

    service = get_rng_service()
    reading = service.get_reading(session_id)
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


def stop_rng_session(session_id: str) -> dict[str, Any]:
    """Stop active RNG session"""
    from backend.core.services.rng_attunement_service import get_rng_service

    service = get_rng_service()
    summary = service.get_session_summary(session_id) or {}
    service.stop_session(session_id)
    return summary


# ============================================================================
# AUDIO TOOLS
# ----------------------------------------------------------------------------
# ADR 001: the user-facing audio subsystem is the ``vajra_service``
# singleton — these tools call it in-process instead of POSTing to
# ``/api/v1/audio/*``.
# ============================================================================


def _audio_generate(config: dict[str, Any]) -> dict[str, Any]:
    """Generate prayer-bowl audio on the canonical vajra_service (in-process)."""
    from backend.core.services.vajra_service import AudioConfig as ServiceAudioConfig
    from backend.core.services.vajra_service import vajra_service

    service_config = ServiceAudioConfig(
        frequency=config["frequency"],
        duration=config["duration"],
        volume=config["volume"],
        prayer_bowl_mode=config["prayer_bowl_mode"],
        harmonic_strength=config["harmonic_strength"],
        modulation_depth=config["modulation_depth"],
    )
    _run_async(vajra_service.generate_prayer_bowl_audio(service_config))
    return {
        "status": "success",
        "message": "Audio generation completed",
        "config": dict(config),
        "audio_generated": True,
        "samples": len(vajra_service.current_audio_data) if vajra_service.current_audio_data is not None else 0,
    }


def _audio_play(hardware_level: int = 2) -> dict[str, Any]:
    """Play the generated audio in the background (mirrors the /play endpoint)."""
    from backend.core.services.vajra_service import vajra_service

    if vajra_service.current_audio_data is None:
        return {"status": "error", "message": "No audio data available. Please generate audio first."}
    audio_length = len(vajra_service.current_audio_data)
    _spawn(vajra_service.broadcast_audio(vajra_service.current_audio_data, hardware_level))
    return {
        "status": "success",
        "message": "Audio playback started",
        "hardware_level": hardware_level,
        "audio_duration": audio_length / 44100,
        "audio_samples": audio_length,
    }


def _audio_presets() -> dict[str, Any]:
    from backend.app.api.v1.endpoints.audio import get_audio_presets

    return _dump(_run_async(get_audio_presets()))


def play_chakra_healing_audio(chakra_name: str, duration: float = 30.0) -> dict[str, Any]:
    """
    Generate and play a Tibetan prayer bowl tone tuned to a specific chakra.

    Use this when:
    - You detect negative RNG spikes and want to calm the space
    - The user requests a healing tone
    - You are leading a meditation session

    Args:
        chakra_name: Name of the chakra (e.g. "root", "sacral", "solar_plexus", "heart", "throat", "third_eye", "crown")
        duration: Duration of the audio in seconds, default 30.0

    Returns:
        {"status": "success", "message": "..."}
    """
    from backend.core.services.vajra_service import vajra_service

    _run_async(vajra_service.generate_chakra_audio(chakra_name, duration))
    gen_res = {
        "status": "success",
        "message": f"Chakra audio generation completed for {chakra_name}",
        "config": {"chakra_name": chakra_name, "duration": duration},
        "audio_generated": True,
        "samples": len(vajra_service.current_audio_data) if vajra_service.current_audio_data is not None else 0,
    }

    play_res = _audio_play()
    return {
        "status": "success",
        "message": f"Successfully playing {chakra_name} chakra healing audio.",
        "generation_details": gen_res,
        "playback_details": play_res,
    }


def set_audio_frequency(freq_hz: float, duration_s: float = 30.0) -> dict[str, Any]:
    """
    Directly tune the carrier frequency of the audio broadcast.

    Use this when:
    - You want to actively change the frequency based on RNG readings
    - Need specific Rife or Solfeggio frequencies

    Args:
        freq_hz: The frequency in Hz to play
        duration_s: Duration to play in seconds, default 30.0
    """
    config = {
        "frequency": freq_hz,
        "duration": duration_s,
        "volume": 0.8,
        "prayer_bowl_mode": True,
        "harmonic_strength": 0.3,
        "modulation_depth": 0.05,
    }
    gen_res = _audio_generate(config)
    if gen_res.get("status") == "success":
        play_res = _audio_play()
        return {"status": "success", "message": f"Successfully tuned frequency to {freq_hz} Hz.", "playback": play_res}
    return gen_res


def set_audio_modulation(harmonic_strength: float, modulation_depth: float, duration_s: float = 30.0) -> dict[str, Any]:
    """
    Change the timbre and modulation of the active broadcast.

    Use this when:
    - You want to increase or decrease the intensity/richness of the sound
    - Reacting to coherence changes

    Args:
        harmonic_strength: 0.0 to 1.0, richness of overtones
        modulation_depth: 0.0 to 1.0, depth of vibrato/tremolo
        duration_s: Duration in seconds, default 30.0
    """
    config = {
        "frequency": 432.0,  # Defaulting to a safe base frequency
        "duration": duration_s,
        "volume": 0.8,
        "prayer_bowl_mode": True,
        "harmonic_strength": harmonic_strength,
        "modulation_depth": modulation_depth,
    }
    gen_res = _audio_generate(config)
    if gen_res.get("status") == "success":
        play_res = _audio_play()
        return {
            "status": "success",
            "message": f"Successfully modulated audio (harmonics: {harmonic_strength}, depth: {modulation_depth}).",
            "playback": play_res,
        }
    return gen_res


def play_audio_preset(preset_name: str, duration_s: float = 30.0) -> dict[str, Any]:
    """
    Play a specific predefined audio preset.

    Use this when:
    - You want guaranteed safe configurations
    - You want to quickly shift states

    Available presets: 'om-frequency', 'heart-chakra', 'earth-resonance', 'pure-sine'

    Args:
        preset_name: Name of the preset to play
        duration_s: Duration in seconds, default 30.0
    """
    presets_res = _audio_presets()
    presets = presets_res.get("presets", {})
    if preset_name not in presets:
        return {"status": "error", "message": f"Preset '{preset_name}' not found."}

    config = dict(presets[preset_name])
    config["duration"] = duration_s

    gen_res = _audio_generate(config)
    if gen_res.get("status") == "success":
        play_res = _audio_play()
        return {"status": "success", "message": f"Successfully playing preset '{preset_name}'.", "playback": play_res}
    return gen_res


# ============================================================================
# BLESSING SLIDESHOW TOOLS
# ============================================================================


def create_blessing_slideshow(
    directory_path: str,
    mantra: str = "chenrezig",
    intentions: list[str] = None,
    repetitions_per_photo: int = 108,
    display_duration_ms: int = 2000,
    loop_mode: bool = True,
    rng_session_id: str | None = None,
) -> dict[str, Any]:
    """
    Create a blessing slideshow session for a directory of photos.

    Use this when:
    - User wants to bless photos
    - Manual compassion practice
    - Need visual witness for radionics

    Args:
        directory_path: Absolute path to directory with photos
        mantra: Mantra to use (chenrezig, tara, medicine_buddha, etc.)
        intentions: List of intentions (love, healing, peace, etc.)
        repetitions_per_photo: Number of mantra repetitions per photo
        display_duration_ms: How long to display each photo (ms)
        loop_mode: Whether to loop back to start
        rng_session_id: Optional RNG session to link

    Returns:
        {"session_id": "blessing_slideshow_...", "total_photos": 50}
    """
    if intentions is None:
        intentions = ["love", "healing", "peace"]

    from backend.core.services.blessing_slideshow_service import (
        IntentionSet,
        IntentionType,
        MantraType,
        get_blessing_slideshow_service,
    )

    service = get_blessing_slideshow_service()
    intention_set = IntentionSet(
        primary_mantra=MantraType(mantra),
        intentions=[IntentionType(i) for i in intentions],
        repetitions_per_photo=repetitions_per_photo,
        dedication="May all beings benefit",
    )
    session_id = service.create_session(
        directory_path=directory_path,
        intention_set=intention_set,
        loop_mode=loop_mode,
        display_duration_ms=display_duration_ms,
        rng_session_id=rng_session_id,
    )
    session = service.sessions.get(session_id)
    total_photos = len(session.photos) if session else 0
    return {"session_id": session_id, "total_photos": total_photos}


def get_current_slide(session_id: str) -> dict[str, Any]:
    """
    Get current slide information including photo details and progress.

    Args:
        session_id: Slideshow session ID

    Returns:
        Complete current slide info including photo, session, overlay, progress
    """
    from backend.core.services.blessing_slideshow_service import get_blessing_slideshow_service

    service = get_blessing_slideshow_service()
    slide_info = service.get_current_slide(session_id)
    return slide_info if slide_info is not None else {}


def stop_slideshow(session_id: str) -> dict[str, Any]:
    """
    Stop slideshow and get final statistics.

    Args:
        session_id: Slideshow session ID

    Returns:
        Final statistics including photos blessed, mantras repeated
    """
    from backend.core.services.blessing_slideshow_service import get_blessing_slideshow_service

    service = get_blessing_slideshow_service()
    return service.stop_session(session_id)


# ============================================================================
# POPULATION MANAGEMENT TOOLS
# ============================================================================


def create_population(
    name: str,
    category: str,
    source_type: str,
    description: str = "",
    directory_path: str | None = None,
    mantra_preference: str = "chenrezig",
    intentions: list[str] = None,
    priority: int = 5,
    is_urgent: bool = False,
) -> dict[str, Any]:
    """
    Create a new target population for automated blessings.

    Use this when:
    - User wants to add a new population
    - Setting up automated rotation
    - Organizing blessing targets

    Args:
        name: Clear, descriptive name
        category: missing_persons, refugees, disaster_victims, etc.
        source_type: local_directory, manual, etc.
        description: Optional description
        directory_path: Required for local_directory source
        mantra_preference: Preferred mantra
        intentions: List of intentions
        priority: Priority 1-10 (higher = more important)
        is_urgent: Whether urgent

    Returns:
        Complete population object with ID
    """
    if intentions is None:
        intentions = ["love", "healing", "peace"]

    from backend.core.services.population_manager import PopulationCategory, SourceType, get_population_manager

    try:
        category = PopulationCategory(category) if isinstance(category, str) else category
    except ValueError:
        category = PopulationCategory.CUSTOM
    try:
        source = SourceType(source_type) if isinstance(source_type, str) else source_type
    except ValueError:
        source = SourceType.MANUAL

    pm = get_population_manager()
    pop = pm.create_population(
        name=name,
        description=description,
        category=category,
        source_type=source,
        directory_path=directory_path,
        mantra_preference=mantra_preference,
        intentions=intentions,
        priority=priority,
        is_urgent=is_urgent,
    )
    return pop.to_dict() if pop else {"status": "error", "message": f"Could not create population '{name}'."}


def list_populations(
    active_only: bool = False, category: str | None = None, urgent_only: bool = False
) -> list[dict[str, Any]]:
    """
    Get list of all populations with optional filtering.

    Args:
        active_only: Only return active populations
        category: Filter by specific category
        urgent_only: Only return urgent populations

    Returns:
        List of population objects
    """
    from backend.core.services.population_manager import get_population_manager

    pm = get_population_manager()
    pops = [p.to_dict() for p in pm.get_all_populations()]
    if active_only:
        pops = [p for p in pops if p.get("is_active")]
    if category:
        pops = [p for p in pops if p.get("category") == category]
    if urgent_only:
        pops = [p for p in pops if p.get("is_urgent")]
    # Dedup by name so a seeded "California" × N ledger cannot flood the
    # follow-up prompt (repetition makes free models stutter the name).
    unique: list[dict[str, Any]] = []
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


def get_population_statistics() -> dict[str, Any]:
    """
    Get overall statistics across all populations.

    Returns:
        Statistics including totals, categories, blessings sent
    """
    from backend.core.services.population_manager import get_population_manager

    pm = get_population_manager()
    stats = pm.get_statistics()
    return {
        "total_populations": stats.get("total_populations", 0),
        "active_populations": stats.get("active_populations", 0),
        "total_blessings_sent": stats.get("total_blessings_sent", 0),
        "total_mantras_repeated": stats.get("total_mantras_repeated", 0),
    }


def get_system_status() -> dict[str, Any]:
    """
    Get a complete system status snapshot — populations, automation, RNG, world context.
    Use this when the user asks for 'statistics', 'status', 'system overview', or 'dashboard'.

    Returns all data in a single call so the LLM doesn't need multiple follow-up turns.
    """
    from backend.app.api.v1.endpoints.automation import get_automation_overview
    from backend.app.api.v1.endpoints.practices import all_practice_status
    from backend.app.api.v1.endpoints.ritual_engine import get_status as get_ritual_status_fn
    from backend.core.services.population_manager import get_population_manager
    from backend.core.services.rng_attunement_service import get_rng_service

    result: dict[str, Any] = {}

    try:
        stats = get_population_manager().get_statistics()
        result["population_stats"] = {
            "total_populations": stats.get("total_populations", 0),
            "active_populations": stats.get("active_populations", 0),
            "total_blessings_sent": stats.get("total_blessings_sent", 0),
            "total_mantras_repeated": stats.get("total_mantras_repeated", 0),
        }
    except Exception:
        result["population_stats"] = {"error": "unavailable"}

    try:
        rng_sessions = get_rng_service().get_all_sessions()
        result["rng_attunement"] = {"active": bool(rng_sessions), "sessions": len(rng_sessions)}
    except Exception:
        result["rng_attunement"] = {"error": "unavailable"}

    for name, call in [
        ("automation_status", get_automation_overview),
        ("ritual_status", get_ritual_status_fn),
        ("practice_status", all_practice_status),
    ]:
        try:
            result[name] = _dump(_run_async(call()))
        except Exception:
            result[name] = {"error": "unavailable"}

    pop_count = result.get("population_stats", {}).get("total_populations", len(result.get("population_stats", {})))
    result["summary"] = {
        "populations": pop_count,
        "automation": "active" if result.get("automation_status", {}).get("active") else "idle",
        "rng": "online" if result.get("rng_attunement", {}).get("active") else "offline",
        "rituals": result.get("ritual_status", {}).get("active_count", 0),
    }
    return result


def update_population(population_id: str, **updates) -> dict[str, Any]:
    """
    Update a population's settings.

    Args:
        population_id: Population ID
        **updates: Fields to update (priority, is_urgent, etc.)

    Returns:
        Updated population object
    """
    from backend.core.services.population_manager import get_population_manager

    pm = get_population_manager()
    pop = pm.update_population(population_id, **updates)
    if pop is None:
        return {"status": "error", "message": f"Population not found: {population_id}"}
    return pop.to_dict()


# ============================================================================
# AUTOMATION/SCHEDULER TOOLS
# ============================================================================


def start_automation(
    duration_per_population: int = 1800,
    transition_pause: int = 30,
    link_rng: bool = True,
    continuous_mode: bool = True,
    only_active: bool = True,
    min_priority: int = 1,
) -> dict[str, Any]:
    """
    Start automated 24/7 rotation through populations.

    Use this when:
    - User wants hands-off automatic operation
    - Setting up continuous compassion practice
    - Need fair distribution of blessing time

    Args:
        duration_per_population: Seconds to spend on each population
        transition_pause: Seconds between populations
        link_rng: Whether to create RNG session per population
        continuous_mode: Loop indefinitely if True
        only_active: Only include active populations
        min_priority: Minimum priority to include (1-10)

    Returns:
        {"session_id": "scheduler_...", "populations_in_queue": 15}
    """
    from backend.core.services.blessing_scheduler import SchedulerConfig, SchedulerMode, get_scheduler

    scheduler = get_scheduler()
    config = SchedulerConfig(
        mode=SchedulerMode("round_robin"),
        duration_per_population=duration_per_population,
        transition_pause=transition_pause,
        link_rng=link_rng,
        auto_dedicate=True,
        continuous_mode=continuous_mode,
        only_active=only_active,
        min_priority=min_priority,
    )
    session_id = scheduler.start_automation(config=config)
    session = scheduler.sessions.get(session_id)
    queue_len = len(session.populations_queue) if session else 0
    return {"session_id": session_id, "populations_in_queue": queue_len}


def get_automation_status(session_id: str) -> dict[str, Any]:
    """
    Get current automation status (lightweight, for frequent polling).

    Use this for:
    - Real-time monitoring
    - UI updates every 5-10 seconds
    - Progress tracking

    Args:
        session_id: Automation session ID

    Returns:
        Current status including population, progress, elapsed time
    """
    from backend.core.services.blessing_scheduler import get_scheduler

    scheduler = get_scheduler()
    status_info = scheduler.get_current_status(session_id)
    return status_info if status_info is not None else {}


def get_automation_stats(session_id: str) -> dict[str, Any]:
    """
    Get complete automation statistics.

    Args:
        session_id: Automation session ID

    Returns:
        Complete statistics including history, totals, sessions completed
    """
    from backend.core.services.blessing_scheduler import get_scheduler

    return get_scheduler().get_session_stats(session_id)


def stop_automation(session_id: str) -> dict[str, Any]:
    """
    Stop automated rotation and get final statistics.

    Args:
        session_id: Automation session ID

    Returns:
        Final statistics for entire automation session
    """
    from backend.core.services.blessing_scheduler import get_scheduler

    return get_scheduler().stop_automation(session_id)


def pause_automation(session_id: str) -> dict[str, Any]:
    """
    Pause automated rotation (can be resumed later).

    Args:
        session_id: Automation session ID

    Returns:
        Confirmation message
    """
    from backend.core.services.blessing_scheduler import get_scheduler

    scheduler = get_scheduler()
    success = scheduler.pause_automation(session_id)
    return {
        "success": success,
        "message": "Automation paused successfully" if success else "Failed to pause automation",
    }


def resume_automation(session_id: str) -> dict[str, Any]:
    """
    Resume paused automation.

    Args:
        session_id: Automation session ID

    Returns:
        Confirmation message
    """
    from backend.core.services.blessing_scheduler import get_scheduler

    scheduler = get_scheduler()
    success = scheduler.resume_automation(session_id)
    return {
        "success": success,
        "message": "Automation resumed successfully" if success else "Failed to resume automation",
    }


# ============================================================================
# MAGICAL & ESOTERIC OPERATIONS TOOLS
# ============================================================================


def forge_sigil(intention: str, kamea: str = "saturn") -> dict[str, Any]:
    """
    Forge a magical visual sigil from an intention statement.
    Generates both planetary Kamea SVGs and schedules Stable Diffusion generation.

    Args:
        intention: What the sigil is designed to manifest or bless
        kamea: Planetary Kamea grid to draw on (saturn, jupiter, mars)
    """
    from backend.core.services.sigil_service import sigil_service

    return _dump(_run_async(sigil_service.forge_sigil(intention, kamea)))


def cast_tarot_spread(count: int = 3, question: str = "") -> dict[str, Any]:
    """
    Draw Tarot cards from a 78-card deck with full elemental, Hebrew, and planetary correspondences.

    Args:
        count: Number of cards to draw (1, 3, or 10 for Celtic Cross)
        question: Question in focus for the Tarot oracle
    """
    from backend.app.api.v1.endpoints.divination import DrawTarotRequest, draw_tarot

    res = _dump(_run_async(draw_tarot(DrawTarotRequest(count=count))))
    if question and "cards" in res:
        res["interpretation"] = _interpret_divination("Tarot", question, res)
    return res


def cast_i_ching(question: str = "") -> dict[str, Any]:
    """
    Cast an I Ching hexagram using traditional yarrow-stalk probability weights.
    Returns primary/relating hexagrams, changing lines, and meaning interpretation.

    Args:
        question: The situation or focus query for the hexagram
    """
    from backend.app.api.v1.endpoints.divination import cast_iching

    res = _dump(_run_async(cast_iching()))
    if question and "cast" in res:
        res["interpretation"] = _interpret_divination("I Ching", question, res)
    return res


def cast_geomancy(question: str = "") -> dict[str, Any]:
    """
    Cast a Geomantic Shield Chart containing 4 Mothers, 4 Daughters, Nieces, Witnesses, and the Judge.
    Projects figures into the 12 astrological houses.

    Args:
        question: Query/trend-check focus
    """
    from backend.app.api.v1.endpoints.divination import cast_geomancy as cast_geomancy_shield

    res = _dump(_run_async(cast_geomancy_shield()))
    if question and "chart" in res:
        res["interpretation"] = _interpret_divination("Geomancy", question, res)
    return res


def _interpret_divination(system: str, question: str, details: dict[str, Any]) -> str | None:
    """RAG-grounded interpretation via the /interpret endpoint function (in-process)."""
    from backend.app.api.v1.endpoints.divination import InterpretRequest, interpret_divination

    try:
        res = _dump(
            _run_async(interpret_divination(InterpretRequest(system=system, question=question, details=details)))
        )
        return res.get("interpretation")
    except Exception:
        return None


def search_grimoire_correspondences(query: str) -> list[dict[str, Any]]:
    """
    Search the Grimoire library for herbs, stones, metals, planets, and rates that match.

    Args:
        query: Name of herb, crystal, element, or symptom/intention
    """
    # Import locally to avoid circular dependency
    from backend.core.services.grimoire_service import grimoire_service

    return grimoire_service.search(query)


def get_planetary_hours_and_transits() -> dict[str, Any]:
    """
    Retrieve current planetary hour, day ruler, auspicious timing guidelines, and transits.
    """
    import datetime

    from backend.core.services.grimoire_service import grimoire_service
    from backend.core.services.vajra_service import vajra_service

    now = datetime.datetime.now()
    astro_data = _run_async(vajra_service._get_astrology_data())
    hour_data = grimoire_service.get_planetary_hours(now.hour, now.weekday())
    return {"astrology": astro_data, "planetary_hour": hour_data, "timestamp": time.time()}


# ============================================================================
# NARRATIVE GENERATION AND OUTLOOK TOOLS
# ============================================================================


def generate_single_outlook(
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LNG,
    languages: list[str] = None,
    genre: str = "healing",
    custom_context: str | None = None,
    realm_id: str | None = None,
    population_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    excluded_forces: list[str] | None = None,
    include_dialogue: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Generate a single-pass sutra-style blessing and narrative outlook.

    Args:
        lat: Target latitude
        lon: Target longitude
        languages: List of languages to weave (English, Sanskrit, Tibetan, etc.)
        genre: Genre of blessing (healing, victory, alchemist, fun_parable, dharani)
        custom_context: Optional user aspiration text
        realm_id: Setting or realm ID
        population_ids: Target populations receiving the blessing
        character_ids: Narrative characters present in the scene
        excluded_forces: Negative forces to exclude or pacify
        include_dialogue: Weave spoken dialogue between characters if True
    """
    if languages is None:
        languages = ["English"]
    from container import container
    from core.llm.defaults import NEMOTRON_FREE_MODEL_ID

    return container.outlook.generate_single(
        lat=lat,
        lon=lon,
        languages=languages,
        genre=genre,
        custom_context=custom_context,
        realm_id=realm_id,
        population_ids=population_ids,
        character_ids=character_ids,
        excluded_forces=excluded_forces,
        include_dialogue=include_dialogue,
        model=model or NEMOTRON_FREE_MODEL_ID,
    )


def generate_epic_outlook(
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LNG,
    languages: list[str] = None,
    genre: str = "alchemist",
    stages: int = 9,
    custom_context: str | None = None,
    realm_id: str | None = None,
    population_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    excluded_forces: list[str] | None = None,
    include_dialogue: bool = False,
) -> dict[str, Any]:
    """
    Generate a multi-stage epic narrative blessing cycle.

    Args:
        lat: Target latitude
        lon: Target longitude
        languages: Languages to weave
        genre: Genre of blessing
        stages: Number of stages to generate (default 9)
        custom_context: Optional custom context
        realm_id: Setting or realm ID
        population_ids: Beneficiary populations
        character_ids: Present characters
        excluded_forces: Excluded forces list
        include_dialogue: Include direct dialogue if True
    """
    if languages is None:
        languages = ["English"]
    from container import container

    return container.outlook.generate_epic(
        lat=lat,
        lon=lon,
        languages=languages,
        genre=genre,
        stages=stages,
        custom_context=custom_context,
        realm_id=realm_id,
        population_ids=population_ids,
        character_ids=character_ids,
        excluded_forces=excluded_forces,
        include_dialogue=include_dialogue,
    )


def list_narrative_locations() -> list[dict[str, Any]]:
    """
    List all active locations and metaphysical realms.
    """
    from backend.app.api.v1.endpoints.outlook import list_locations

    return _dump(_run_async(list_locations()))


def create_narrative_location(
    name: str,
    description: str,
    location_type: str,
    source_type: str = "manual",
    is_metaphysical: bool = False,
    latitude: float | None = None,
    longitude: float | None = None,
    celestial_coordinates: str | None = None,
    dimension_frequency: float | None = None,
    realm_governor: str | None = None,
    astrological_anchor: str | None = None,
    elemental_affinity: str | None = None,
    priority: int = 5,
) -> dict[str, Any]:
    """
    Create a new location or metaphysical realm setting.

    Args:
        name: Name of location or realm
        description: Visionary description of setting
        location_type: earthly_sacred, metaphysical_realm, cosmic_anchor, historical_academy, custom
        source_type: manual, generated, mythology, geographic
        is_metaphysical: Set True for metaphysical dimensions with frequencies
        latitude: Latitude for earthly sacred sites
        longitude: Longitude for earthly sacred sites
        celestial_coordinates: Celestial/star coords (metaphysical only)
        dimension_frequency: Vibrational frequency in Hz (metaphysical only)
        realm_governor: Ruler or deity of the setting
        astrological_anchor: Astrological anchor lines
        elemental_affinity: Primary element (Fire, Water, etc.)
        priority: Priority weighting (1-10)
    """
    from backend.app.api.v1.endpoints.outlook import LocationCreate, create_location

    loc = _dump(
        _run_async(
            create_location(
                LocationCreate(
                    **{
                        "name": name,
                        "description": description,
                        "location_type": location_type,
                        "source_type": source_type,
                        "is_metaphysical": is_metaphysical,
                        "latitude": latitude,
                        "longitude": longitude,
                        "celestial_coordinates": celestial_coordinates,
                        "dimension_frequency": dimension_frequency,
                        "realm_governor": realm_governor,
                        "astrological_anchor": astrological_anchor,
                        "elemental_affinity": elemental_affinity,
                        "priority": priority,
                    }
                )
            )
        )
    )
    return loc


def list_narrative_characters() -> list[dict[str, Any]]:
    """
    List all active narrative characters and archetypes.
    """
    from backend.app.api.v1.endpoints.outlook import list_characters

    return _dump(_run_async(list_characters()))


def create_narrative_character(
    name: str,
    role: str,
    description: str,
    source_type: str = "manual",
    dialogue_style: str = "cryptic and profound",
    associated_realms: list[str] = None,
    mantra_preference: str | None = None,
    elemental_anchor: str = "space",
    priority: int = 5,
) -> dict[str, Any]:
    """
    Create a new narrative character archetype.

    Args:
        name: Character name
        role: master, student, alchemist, hero, deity, guardian, custom
        description: Archetypal description
        source_type: manual, generated, mythology, historical
        dialogue_style: Description of dialogue pattern
        associated_realms: Realm IDs frequented
        mantra_preference: Prefered mantra key
        elemental_anchor: earth, water, fire, air, space, aether
        priority: Priority weighting (1-10)
    """
    from backend.app.api.v1.endpoints.outlook import CharacterCreate, create_character

    return _dump(
        _run_async(
            create_character(
                CharacterCreate(
                    **{
                        "name": name,
                        "role": role,
                        "description": description,
                        "source_type": source_type,
                        "dialogue_style": dialogue_style,
                        "associated_realms": associated_realms or [],
                        "mantra_preference": mantra_preference,
                        "elemental_anchor": elemental_anchor,
                        "priority": priority,
                    }
                )
            )
        )
    )


def start_narrative_loop(
    interval_minutes: int = 15,
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LNG,
    languages: list[str] = None,
    genre: str = "healing",
    custom_context: str | None = None,
    realm_id: str | None = None,
    population_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    excluded_forces: list[str] | None = None,
    include_dialogue: bool = False,
) -> dict[str, Any]:
    """
    Start the continuous background narrative transmission loop.

    Args:
        interval_minutes: Minutes between generation cycles (1-1440)
        lat: Target latitude
        lon: Target longitude
        languages: Languages to weave
        genre: Genre of narrative
        custom_context: User custom aspiration notes
        realm_id: Setting or realm ID
        population_ids: List of target population IDs
        character_ids: List of character IDs present
        excluded_forces: Negative forces to exclude
        include_dialogue: Include spoken dialogue between characters if True
    """
    if languages is None:
        languages = ["English"]
    from backend.app.api.v1.endpoints.outlook import BackgroundGenerationConfig, start_background_generation

    config = BackgroundGenerationConfig(
        interval_minutes=interval_minutes,
        loop_mode="sequential_delay",
        cycle_genres=False,
        cycle_intentions=False,
        lat=lat,
        lon=lon,
        languages=languages,
        genre=genre,
        custom_context=custom_context,
    )
    result = _dump(_run_async(start_background_generation(config)))
    if result.get("status") == "already_running":
        return {"status": "already_running", "stats": result.get("stats", {})}
    return {
        "status": "success",
        "message": f"Background generation started. Mode: sequential_delay. Every {interval_minutes} min.",
        "stats": result.get("stats", {}),
    }


def stop_narrative_loop() -> dict[str, Any]:
    """
    Stop the active background narrative transmission loop.
    """
    from backend.app.api.v1.endpoints.outlook import stop_background_generation

    return _dump(_run_async(stop_background_generation()))


def get_narrative_loop_status() -> dict[str, Any]:
    """
    Check active background narrative loop state, configuration, and last generated draft.
    """
    from backend.app.api.v1.endpoints.outlook import background_status

    status = _dump(_run_async(background_status()))
    return {
        "active": status["active"],
        "interval_minutes": status["config"].get("interval_minutes", 5),
        "config": {"loop_mode": status["config"].get("loop_mode", "sequential_delay")},
        "stats": status.get("stats", {}),
        "last_generated": status.get("stats", {}).get("last_generated_at"),
    }


# ============================================================================
# 88 BUDDHAS & SAKA DAWA TOOLS (stubs — executed by llm.py's execute_tool_locally)
# ============================================================================


def get_random_buddha(category: str | None = None) -> dict[str, Any]:
    """Get a random Buddha from the 88-Buddha collection with contemplation narrative."""
    from core.eighty_eight_buddhas import get_eighty_eight_buddhas

    svc = get_eighty_eight_buddhas()
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


def generate_buddha_narrative(buddha_name: str, depth: str = "contemplation") -> dict[str, Any]:
    """Generate a sacred narrative about a specific Buddha."""
    from core.eighty_eight_buddhas import get_eighty_eight_buddhas

    return get_eighty_eight_buddhas().generate_buddha_narrative(buddha_name, depth=depth)


def get_88_buddhas_liturgy() -> dict[str, Any]:
    """Get the full 88-Buddha confession liturgy."""
    from core.eighty_eight_buddhas import get_eighty_eight_buddhas

    return get_eighty_eight_buddhas().get_confession_sequence()


def recite_buddha_name(buddha_name: str) -> dict[str, Any]:
    """Recite a single Buddha name via the unified TTS provider.

    Delegates to ToolDispatcher (modules/radionics_operator.py) which routes
    through core.tts_provider.get_tts_provider().speak(...). Falls back to a
    descriptive payload when no container is available (e.g. in unit tests).
    """
    from core.eighty_eight_buddhas import get_eighty_eight_buddhas

    svc = get_eighty_eight_buddhas()
    b = svc.get_buddha_by_name(buddha_name)
    if not b:
        return {"error": f"Buddha not found: {buddha_name}"}
    try:
        return _dispatch_via_container("recite_buddha_name", buddha_name=buddha_name)
    except Exception as dispatch_err:
        text = f"南無{b.name_chinese}" if not b.name_chinese.startswith("南無") else b.name_chinese
        try:
            from core.tts_provider import get_tts_provider

            provider = get_tts_provider()
            if provider:
                import asyncio

                try:
                    running = asyncio.get_event_loop()
                    if running.is_running():

                        async def _speak() -> str | None:
                            return await provider.speak(text=text, rate="-30%", role="buddhist_chant")

                        asyncio.ensure_future(_speak())
                        path = None
                    else:
                        path = asyncio.run(provider.speak(text=text, rate="-30%", role="buddhist_chant"))
                except RuntimeError:
                    path = asyncio.run(provider.speak(text=text, rate="-30%", role="buddhist_chant"))
                return {
                    "buddha": b.name_chinese,
                    "pinyin": b.name_pinyin,
                    "text": text,
                    "audio_path": path,
                    "message": f"Recited {b.name_chinese} ({b.name_pinyin}) via fallback TTS provider.",
                }
        except Exception as tts_err:
            return {
                "buddha": b.name_chinese,
                "pinyin": b.name_pinyin,
                "text": text,
                "message": f"Could not play recitation of {b.name_chinese} (dispatch={dispatch_err}; tts={tts_err}).",
                "error": str(tts_err),
            }
        return {
            "buddha": b.name_chinese,
            "pinyin": b.name_pinyin,
            "text": text,
            "message": f"TTS provider unavailable. Text: {text}",
        }


def start_buddha_recitation(
    intention: str = "愿一切众生离苦得乐", interval_seconds: float = 3.0, mala_cycles: int | None = None
) -> dict[str, Any]:
    """Start continuous 88-Buddha recitation loop."""
    import asyncio

    from core.buddha_recitation_loop import get_recitation_loop

    loop = get_recitation_loop()
    if loop.state.running:
        return {"status": "already_running"}
    try:
        running_loop = asyncio.get_event_loop()
        if running_loop.is_running():
            running_loop.create_task(
                loop.start(intention=intention, interval_seconds=interval_seconds, mala_cycles=mala_cycles)
            )
        else:
            asyncio.run(loop.start(intention=intention, interval_seconds=interval_seconds, mala_cycles=mala_cycles))
    except RuntimeError:
        asyncio.run(loop.start(intention=intention, interval_seconds=interval_seconds, mala_cycles=mala_cycles))
    return loop.get_status()


def stop_buddha_recitation() -> dict[str, Any]:
    """Stop active Buddha recitation loop."""
    from core.buddha_recitation_loop import get_recitation_loop

    loop = get_recitation_loop()
    loop.stop()
    return loop.get_status()


def get_buddha_recitation_status() -> dict[str, Any]:
    """Get current recitation loop status."""
    from core.buddha_recitation_loop import get_recitation_loop

    return get_recitation_loop().get_status()


def check_saka_dawa() -> dict[str, Any]:
    """Check Saka Dawa holy month status (Losar-anchored 4th Tibetan month)."""
    from core.auspicious_timing import check_saka_dawa as _check_saka_dawa

    return _check_saka_dawa()


def run_working(
    intention: str,
    target: str = "all beings",
    broadcast: bool = True,
    duration_minutes: int = 5,
) -> dict[str, Any]:
    """Seal one working: rates, Saka Dawa stamp, optional broadcast."""
    from core.working import run_working as _run_working

    return _run_working(
        intention=intention,
        target=target,
        broadcast=broadcast,
        duration_minutes=duration_minutes,
    )


def forge_witness(working_id: str) -> dict[str, Any]:
    """Generate and attach a witness image to an existing working folio."""
    from core.working import attach_witness_image

    return attach_witness_image(working_id)


def check_auspicious_timing(genre: str = "healing") -> dict[str, Any]:
    """Check auspicious timing for a ritual genre."""
    from core.auspicious_timing import check_auspicious_window

    return check_auspicious_window(genre).to_dict()


# ============================================================================
# RITUAL ENGINE TOOLS — autonomous LLM agent control over the ritual engine
# ============================================================================


def get_ritual_status() -> dict[str, Any]:
    """Get the current state, history, and merit of the autonomous ritual engine.

    Use this when:
    - The user asks about recent rituals or accumulated merit
    - You need to decide whether to start/stop the engine
    - You want to know what the engine has been doing

    Returns:
        {
            "state": "running" | "stopped" | "executing" | "paused",
            "is_running": bool,
            "rituals_today": int,
            "rituals_this_hour": int,
            "total_merit_today": float,
            "recent_history": [{"id", "practice_name", "genre", "merit_multiplier", "narrative_length", "completed_at"}, ...],
            "current_ritual": {...} | None,
        }
    """
    from core.ritual_engine import get_ritual_engine

    engine = get_ritual_engine()
    return {
        "status": engine.status,
        "history": engine.get_history(20),
        "merit": engine.get_merit_stats(),
    }


def start_ritual_engine(min_timing_quality: str = "challenging") -> dict[str, Any]:
    """Start the autonomous ritual engine.

    The engine runs on a 60-second loop, selecting and executing rituals
    based on the configured minimum timing quality and current auspicious
    windows. Practice selection uses the PracticeSelector to score by
    genre, timing, merit, and recency diversity.

    Use this when:
    - The user asks to start a continuous blessing practice
    - You detect favorable Saka Dawa or other high-merit windows
    - You want to maintain ongoing intentional practice

    Args:
        min_timing_quality: Minimum timing quality to execute — one of
            "excellent" (4), "good" (3), "challenging" (2), "transmutative" (1).
            Default "challenging" — execute unless the hour is fully blocked.

    Returns:
        {"status": "started" | "already_running", "state": "running"}
    """
    from core.ritual_engine import get_ritual_engine

    engine = get_ritual_engine()
    engine.update_config(min_timing_quality=min_timing_quality)
    _run_async(engine.start())
    return {"status": "started", "state": engine.state.value}


def stop_ritual_engine() -> dict[str, Any]:
    """Stop the autonomous ritual engine.

    Idempotent — safe to call when the engine is already stopped.

    Use this when:
    - The user asks to pause or stop automatic practice
    - You're transitioning to a manual ritual mode
    - The engine has accumulated enough merit and the user wants a break
    """
    from core.ritual_engine import get_ritual_engine

    engine = get_ritual_engine()
    _run_async(engine.stop())
    return {"status": "stopped", "state": engine.state.value}


def trigger_ritual() -> dict[str, Any]:
    """Manually trigger one ritual execution on the autonomous engine.

    Use this when:
    - The user asks for an immediate blessing
    - You want to fire a one-off practice without starting the full loop
    - You're testing or demonstrating the engine

    Returns:
        {"status": "executed" | "no_practice_selected",
         "ritual": {RitualRecord fields} | None}
    """
    from core.ritual_engine import get_ritual_engine

    engine = get_ritual_engine()
    record = _run_async(engine.trigger_now())
    if record is None:
        return {"status": "no_suitable_practice", "message": "No practice scored above threshold"}
    return {"status": "executed", "ritual": record.to_dict()}


def list_practices() -> dict[str, Any]:
    """List all available ritual practices with their genre, merit, and mantras.

    Use this when:
    - The user asks what practices are available
    - You need to recommend a specific practice for a situation
    - You want to see the merit multipliers for scoring decisions

    Returns:
        {"practices": [{"id", "name", "genre", "merit_multiplier",
                        "preferred_planetary_hours", "duration_sec", "mantra"}, ...]}
    """
    from core.practices.practice import Practice

    return {"practices": [p.__dict__ for p in Practice.get_default_practices()]}


def get_ritual_schedule(hours: int = 24) -> dict[str, Any]:
    """Get the next N hours of predicted favorable ritual timing.

    Use this when:
    - You want to schedule a specific ritual for an upcoming favorable hour
    - The user asks "when's the next good time for X?"
    - You're planning a sequence of practices

    Args:
        hours: How many hours to look ahead (default 24)

    Returns:
        {"schedule": [{"datetime", "planetary_hour", "favorable_genres", "quality"}, ...]}
    """
    from core.ritual_engine import get_ritual_engine

    engine = get_ritual_engine()
    return {"schedule": engine.status.get("schedule", [])}


def generate_character() -> dict[str, Any]:
    """Generate an RNG-seeded character."""
    from core.character_generator import CharacterGenerator

    return CharacterGenerator().generate(use_llm=False).to_dict()


def start_character_journey() -> dict[str, Any]:
    """Start a character journey arc."""
    from container import container
    from modules.radionics_operator import ToolDispatcher

    return ToolDispatcher(container).dispatch("start_character_journey", {})


def advance_journey() -> dict[str, Any]:
    """Advance character journey by one stage."""
    from container import container
    from modules.radionics_operator import ToolDispatcher

    return ToolDispatcher(container).dispatch("advance_journey", {})


def get_journey_status() -> dict[str, Any]:
    """Get current journey status."""
    from container import container
    from modules.radionics_operator import ToolDispatcher

    return ToolDispatcher(container).dispatch("get_journey_status", {})


def run_full_journey() -> dict[str, Any]:
    """Run full 6-stage journey."""
    from container import container
    from modules.radionics_operator import ToolDispatcher

    return ToolDispatcher(container).dispatch("run_full_journey", {})


# ============================================================================
# SACRED ASTRONOMY, DHARANI, CRISIS & LIVING RITUAL EXPANSION
# ============================================================================


def get_celestial_night_sky(
    latitude: float = DEFAULT_LAT,
    longitude: float = DEFAULT_LNG,
    timestamp: float | None = None,
) -> dict[str, Any]:
    """Get topocentric celestial night sky coordinates for observer.

    Computes topocentric Altitude/Azimuth for 10 solar system bodies (Sun, Moon,
    Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune, Pluto) and 10 Vedic
    nakshatra fixed stars (Sirius/Mrigashirsha, Vega/Abhijit, Arcturus/Swati,
    Spica/Chitra, Aldebaran/Rohini, Antares/Jyeshtha, Betelgeuse/Ardra,
    Polaris/Dhruva, Regulus/Magha, Pleiades/Krittika), along with Moon phase,
    illumination percentage, and Local Sidereal Time (LST).
    """
    from datetime import datetime, timezone

    from core.celestial_sky import calculate_night_sky

    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp is not None else None
    return calculate_night_sky(latitude=latitude, longitude=longitude, dt=dt)


def get_dharani_text(dharani_id_or_name: str = "") -> dict[str, Any]:
    """Retrieve unabbreviated sacred Dhāraṇī or mantra text from the canonical library.

    Loads complete canonical text (Sanskrit IAST, Chinese characters, English meaning,
    historical context, and recitation instructions) from the sacred dhāraṇī library.
    Supports Great Compassion Mantra (84 phrases), Śūraṅgama Mantra (all 5 assemblies),
    Sitātapatrā (White Umbrella), Mahāpratisarā, Cundi (with full 4-line praise), etc.
    If 'list' or empty query is supplied, returns a directory of available dhāraṇīs.
    """
    import json
    from pathlib import Path

    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    dharani_path = base_dir / "knowledge" / "dharanis.json"
    if not dharani_path.exists():
        return {"status": "error", "message": "knowledge/dharanis.json not found"}

    try:
        data = json.loads(dharani_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse dharanis.json: {e}"}

    query = (dharani_id_or_name or "").strip().lower()

    if not query or query in ("list", "all", "help", "dir"):
        summary_list = [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "name_chinese": d.get("name_chinese", ""),
                "deity": d.get("deity", ""),
                "purpose": d.get("purpose", ""),
                "frequency_hz": d.get("frequency_hz", 528),
            }
            for d in data
        ]
        return {
            "status": "list",
            "total": len(data),
            "available_dharanis": summary_list,
            "message": "Specify a dhāraṇī id or name to retrieve the full unabbreviated text.",
        }

    # Match exact ID first
    match = next((d for d in data if d.get("id", "").lower() == query), None)

    # Match substring on id, name, name_chinese, deity, purpose
    if not match:
        for d in data:
            if (
                query in d.get("id", "").lower()
                or query in d.get("name", "").lower()
                or query in d.get("name_chinese", "").lower()
                or query in d.get("deity", "").lower()
                or query in d.get("purpose", "").lower()
            ):
                match = d
                break

    if not match:
        return {
            "status": "not_found",
            "query": dharani_id_or_name,
            "message": f"Dhāraṇī '{dharani_id_or_name}' not found. Available IDs: {[d.get('id') for d in data]}",
        }

    return {
        "status": "found",
        "dharani": match,
    }


def get_auspicious_timing_details(
    latitude: float = DEFAULT_LAT,
    longitude: float = DEFAULT_LNG,
) -> dict[str, Any]:
    """Get full 24-hour Auspicious Timing Wheel details for ritual scheduling.

    Includes 24 planetary hour slices, current planetary ruler, daytime/nighttime state,
    lunar phase and tithi, nakshatra, Saka Dawa multiplier and status, and green windows
    for ritual genres (healing, victory, wisdom, purification, compassion, prosperity, protection).
    """
    from core.auspicious_timing import AuspiciousTiming

    engine = AuspiciousTiming()
    return engine.get_timing_wheel_data(lat=latitude, lon=longitude)


def get_active_world_crises() -> dict[str, Any]:
    """Retrieve active global crises, natural disasters, and humanitarian events.

    Fetches real-time alert data from GDACS (earthquakes, floods, cyclones, tsunamis)
    and humanitarian situations from ReliefWeb. Provides geographic coordinates,
    severity ratings, and recommended compassionate healing intention focal points.
    """
    from core.internet_context import compile_world_context

    ctx = compile_world_context(include_disasters=True, include_headlines=True, include_astrology=False)
    crises = []
    for ev in ctx.events:
        crises.append(
            {
                "title": ev.title,
                "description": ev.description,
                "location": ev.location or ev.country or "Global",
                "country": ev.country,
                "latitude": ev.lat,
                "longitude": ev.lon,
                "event_type": ev.event_type,
                "severity": ev.severity,
                "source": ev.source,
                "date": ev.date,
                "url": ev.url,
            }
        )
    return {
        "status": "success",
        "total_crises": len(crises),
        "disaster_count": sum(1 for c in crises if c["event_type"] == "disaster"),
        "humanitarian_count": sum(1 for c in crises if c["event_type"] == "humanitarian"),
        "crises": crises,
        "summary": ctx.summary,
    }


def trigger_living_ritual_broadcast(
    intention: str = "May all beings be free from suffering",
    target: str = "all beings",
    ritual_type: str = "healing",
    duration_minutes: int = 5,
    recite_with_tts: bool = False,
) -> dict[str, Any]:
    """Trigger a living ritual broadcast combining sacred text, Solfeggio tones, and dedication.

    Generates a full 6-section sacred ritual (Invocation, Sacred Prayer, Dharma Teaching,
    Divination/Correspondence, Hero Journey Narrative, and Dedication of Merit),
    initiates crystal bowl Solfeggio carrier broadcast, optionally cues TTS recitation,
    and archives the ritual to outlook_narratives.
    """
    from backend.app.api.v1.endpoints.radionics import RitualBroadcastRequest, ritual_broadcast

    req = RitualBroadcastRequest(
        intention=intention,
        target=target,
        ritual_type=ritual_type,
        duration_minutes=duration_minutes,
        recite_with_tts=recite_with_tts,
    )
    res = _run_async(ritual_broadcast(req))
    return _dump(res)


# ============================================================================
# IMAGE GENERATION (modular service — see backend/core/services/image_generation_service.py)
# ============================================================================


def generate_image(
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    size: str = "1024x1024",
    quality: str = "standard",
    aspect_ratio: str | None = None,
    subject_reference: str | None = None,
) -> dict[str, Any]:
    """
    Generate an image from a text prompt via OpenRouter or MiniMax.

    Cost-controlled (default daily cap $0.50), cached (1 hour), and rate-limited
    (max 10/hour). Returns a base64 data URL the chat UI can render inline.

    Use this when:
    - The user asks for a sacred illustration, mandala, deity portrait, or visual
    - You want to depict a generated blessing narrative
    - The user invokes "draw", "paint", "show me", or "create an image of"

    Args:
        prompt: Image description (max 1000 tokens; 30-60 words is ideal).
        provider: "openrouter" (default) or "minimax". None uses config default.
        model: Model slug. None uses config default
            (e.g. "google/gemini-3.1-flash-lite-image", "image-01").
        size: OpenRouter size: "1024x1024" (default), "1792x1024", "1024x1792".
        quality: OpenRouter "standard" or "hd". Ignored by MiniMax.
        aspect_ratio: MiniMax-only override (e.g. "1:1", "16:9", "4:3").
        subject_reference: MiniMax-only image URL for image-to-image consistency.

    Returns:
        {
            "image_data_url": "data:image/png;base64,...",
            "model": "google/gemini-3.1-flash-lite-image",
            "cost_usd": 0.008,
            "provider_used": "openrouter",
            "cached": false,
            "revised_prompt": "...",
            "prompt_tokens": 42
        }

    Raises:
        RuntimeError: If image generation is disabled, daily cap reached,
            rate-limited, or the provider call fails.
        ValueError: If prompt exceeds the configured token budget.
    """
    from backend.app.api.v1.endpoints.image_generation import get_service
    from backend.core.services.image_generation_service import ImageGenerationService

    service: ImageGenerationService = get_service()

    import asyncio

    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    async def _call() -> dict[str, Any]:
        return await service.generate(
            prompt=prompt,
            provider=provider,
            model=model,
            size=size,
            quality=quality,
            n=1,
            aspect_ratio=aspect_ratio,
            subject_reference=subject_reference,
        )

    if in_loop:
        return _AGENT_DISPATCH(
            prompt=prompt,
            provider=provider,
            model=model,
            size=size,
            quality=quality,
            aspect_ratio=aspect_ratio,
            subject_reference=subject_reference,
        )

    return asyncio.run(_call())


async def _AGENT_DISPATCH(
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    size: str = "1024x1024",
    quality: str = "standard",
    aspect_ratio: str | None = None,
    subject_reference: str | None = None,
) -> dict[str, Any]:
    from backend.app.api.v1.endpoints.image_generation import get_service

    service = get_service()
    cfg = service.config

    model_lock = cfg.get("model_lock", True)
    if model_lock:
        return await service.generate(
            prompt=prompt,
            provider=None,
            model=None,
            size=size,
            quality=quality,
            n=1,
            aspect_ratio=None,
            subject_reference=subject_reference,
        )

    return await service.generate(
        prompt=prompt,
        provider=provider,
        model=model,
        size=size,
        quality=quality,
        n=1,
        aspect_ratio=aspect_ratio,
        subject_reference=subject_reference,
    )


# ============================================================================
# RADIONICS / BROADCASTING / ASTROLOGY / AUDIO STUBS
# (delegate to ToolDispatcher for unified dispatch)
# ============================================================================


def _dispatch_via_container(tool_name: str, **args) -> dict[str, Any]:
    """Helper: dispatch any tool through the container's ToolDispatcher."""
    from container import container
    from modules.radionics_operator import ToolDispatcher

    return ToolDispatcher(container).dispatch(tool_name, args)


def broadcast_healing(
    target_name: str, duration_minutes: int = 10, frequency_hz: float = 528.0, intensity: float = 0.8
) -> dict[str, Any]:
    return _dispatch_via_container(
        "broadcast_healing",
        target_name=target_name,
        duration_minutes=duration_minutes,
        frequency_hz=frequency_hz,
        intensity=intensity,
    )


def broadcast_liberation(event_name: str, souls_count: int = 1000, duration_minutes: int = 108) -> dict[str, Any]:
    return _dispatch_via_container(
        "broadcast_liberation", event_name=event_name, souls_count=souls_count, duration_minutes=duration_minutes
    )


def get_available_intentions() -> dict[str, Any]:
    return _dispatch_via_container("get_available_intentions")


def get_sacred_frequencies() -> dict[str, Any]:
    return _dispatch_via_container("get_sacred_frequencies")


def text_to_rate(text: str, num_dials: int = 3) -> dict[str, Any]:
    return _dispatch_via_container("text_to_rate", text=text, num_dials=num_dials)


def measure_general_vitality(subject: str, samples: int = 10) -> dict[str, Any]:
    return _dispatch_via_container("measure_general_vitality", subject=subject, samples=samples)


def find_balancing_rates(subject: str, num_rates: int = 5) -> dict[str, Any]:
    return _dispatch_via_container("find_balancing_rates", subject=subject, num_rates=num_rates)


def search_knowledge(query: str, top_k: int = 5, category: str | None = None) -> dict[str, Any]:
    return _dispatch_via_container("search_knowledge", query=query, top_k=top_k, category=category)


def search_rate_database(query: str, category: str | None = None) -> dict[str, Any]:
    return _dispatch_via_container("search_rate_database", query=query, category=category)


def generate_scalar_waves(method: str = "hybrid", count: int = 10000, intensity: float = 1.0) -> dict[str, Any]:
    return _dispatch_via_container("generate_scalar_waves", method=method, count=count, intensity=intensity)


def get_rng_summary(session_id: str) -> dict[str, Any]:
    return _dispatch_via_container("get_rng_summary", session_id=session_id)


def get_chakra_info() -> dict[str, Any]:
    return _dispatch_via_container("get_chakra_info")


def get_meridian_info() -> dict[str, Any]:
    return _dispatch_via_container("get_meridian_info")


def create_healing_session(
    target_name: str,
    modalities: list[str] | None = None,
    duration_minutes: int = 60,
    intention: str = "complete healing",
) -> dict[str, Any]:
    return _dispatch_via_container(
        "create_healing_session",
        target_name=target_name,
        modalities=modalities,
        duration_minutes=duration_minutes,
        intention=intention,
    )


def chakra_balancing_protocol(target_name: str, chakras: list[str] | None = None) -> dict[str, Any]:
    return _dispatch_via_container("chakra_balancing_protocol", target_name=target_name, chakras=chakras)


def get_healing_modalities() -> dict[str, Any]:
    return _dispatch_via_container("get_healing_modalities")


def get_planetary_positions() -> dict[str, Any]:
    return _dispatch_via_container("get_planetary_positions")


def calculate_natal_chart(
    name: str = "", birth_date: str = "", latitude: float = 0, longitude: float = 0
) -> dict[str, Any]:
    return _dispatch_via_container(
        "calculate_natal_chart", name=name, birth_date=birth_date, latitude=latitude, longitude=longitude
    )


def generate_audio(
    frequency_hz: float = 136.1, duration_seconds: float = 10, mode: str = "prayer_bowl"
) -> dict[str, Any]:
    return _dispatch_via_container("generate_audio", frequency_hz=frequency_hz, duration_seconds=duration_seconds)


def generate_blessing(
    target_name: str, intention: str = "peace and happiness", tradition: str = "universal"
) -> dict[str, Any]:
    return _dispatch_via_container(
        "generate_blessing", target_name=target_name, intention=intention, tradition=tradition
    )


def get_blessing_traditions() -> dict[str, Any]:
    return _dispatch_via_container("get_blessing_traditions")


def generate_prayer(intention: str, tradition: str = "universal") -> dict[str, Any]:
    return _dispatch_via_container("generate_prayer", intention=intention, tradition=tradition)


def speak_text(text: str, voice: str | None = None, role: str = "dharma_teaching") -> dict[str, Any]:
    """
    Speak text through the TTS engine (Kokoro/Sherpa/Edge multilingual router).

    Use this AFTER generating a blessing, prayer, or teaching to give it voice.
    Generates audio and returns a path that can be played back.

    Args:
        text: The text to speak (will be spoken as-is)
        voice: Optional voice override
        role: Ritual role for voice selection

    Returns:
        Dict with status, audio_path, and text_length
    """
    import tempfile

    from core.tts_provider import get_tts_provider

    try:
        provider = get_tts_provider()
        result = _run_async(provider.speak_stream(text=text[:5000], voice=voice, role=role))
        if result is None:
            return {"status": "error", "error": "TTS generation failed — check backend availability"}
        audio_bytes, mime_type, backend = result
        audio_dir = os.path.join(tempfile.gettempdir(), "vajra_tts")
        os.makedirs(audio_dir, exist_ok=True)
        filename = f"tts_{int(time.time())}.{'mp3' if 'mpeg' in mime_type else 'wav'}"
        filepath = os.path.join(audio_dir, filename)
        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        return {
            "status": "success",
            "audio_path": filepath,
            "backend_used": backend,
            "text_length": len(text),
            "size_bytes": len(audio_bytes),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def generate_teaching(topic: str, length: str = "short") -> dict[str, Any]:
    return _dispatch_via_container("generate_teaching", topic=topic, length=length)


def generate_meditation_script(
    meditation_type: str, duration_minutes: int = 20, experience_level: str = "beginner"
) -> dict[str, Any]:
    return _dispatch_via_container(
        "generate_meditation_script",
        meditation_type=meditation_type,
        duration_minutes=duration_minutes,
        experience_level=experience_level,
    )


def web_search(query: str, top_k: int = 5) -> dict[str, Any]:
    return _dispatch_via_container("web_search", query=query, top_k=top_k)


def web_fetch(url: str) -> dict[str, Any]:
    return _dispatch_via_container("web_fetch", url=url)


def get_world_context() -> dict[str, Any]:
    return _dispatch_via_container("get_world_context")


def get_all_genre_windows() -> dict[str, Any]:
    return _dispatch_via_container("get_all_genre_windows")


def get_current_conditions() -> dict[str, Any]:
    return _dispatch_via_container("get_current_conditions")


# ============================================================================
# TOOL REGISTRY (for LLM agents)
# ============================================================================
def add_agent_suggestion(agent_id: str, intention: str, missing_tools: str, context: str) -> dict[str, Any]:
    """
    Log an intentional path or suggestion for a task the agent wanted to do but couldn't.
    Use this when you lack the tools, permissions, or system capabilities to complete a requested or inferred task.

    Args:
        agent_id: Identifier for the current agent (e.g. 'llm_agent_1')
        intention: What you intended to do
        missing_tools: The specific tools or capabilities you needed
        context: Why you wanted to do it
    """
    from backend.app.api.v1.endpoints.agent_suggestions import IntentionalPathSchema, log_intentional_path

    return _dump(
        log_intentional_path(
            IntentionalPathSchema(agent_id=agent_id, intention=intention, missing_tools=missing_tools, context=context)
        )
    )


# Registry of all available tools
TOOL_REGISTRY = {
    "create_rng_session": create_rng_session,
    "get_rng_reading": get_rng_reading,
    "stop_rng_session": stop_rng_session,
    "play_chakra_healing_audio": play_chakra_healing_audio,
    "set_audio_frequency": set_audio_frequency,
    "set_audio_modulation": set_audio_modulation,
    "play_audio_preset": play_audio_preset,
    "create_blessing_slideshow": create_blessing_slideshow,
    "get_current_slide": get_current_slide,
    "stop_slideshow": stop_slideshow,
    "create_population": create_population,
    "list_populations": list_populations,
    "list_targets": list_populations,
    "get_population_statistics": get_population_statistics,
    "get_system_status": get_system_status,
    "get_statistics": get_system_status,
    "update_population": update_population,
    "start_automation": start_automation,
    "get_automation_status": get_automation_status,
    "get_automation_stats": get_automation_stats,
    "stop_automation": stop_automation,
    "pause_automation": pause_automation,
    "resume_automation": resume_automation,
    "forge_sigil": forge_sigil,
    "cast_tarot_spread": cast_tarot_spread,
    "cast_i_ching": cast_i_ching,
    "cast_geomancy": cast_geomancy,
    "search_grimoire_correspondences": search_grimoire_correspondences,
    "get_planetary_hours_and_transits": get_planetary_hours_and_transits,
    "generate_single_outlook": generate_single_outlook,
    "generate_epic_outlook": generate_epic_outlook,
    "list_narrative_locations": list_narrative_locations,
    "create_narrative_location": create_narrative_location,
    "list_narrative_characters": list_narrative_characters,
    "create_narrative_character": create_narrative_character,
    "start_narrative_loop": start_narrative_loop,
    "stop_narrative_loop": stop_narrative_loop,
    "get_narrative_loop_status": get_narrative_loop_status,
    "add_agent_suggestion": add_agent_suggestion,
    # 88 Buddhas & Saka Dawa
    "get_random_buddha": get_random_buddha,
    "generate_buddha_narrative": generate_buddha_narrative,
    "get_88_buddhas_liturgy": get_88_buddhas_liturgy,
    "recite_buddha_name": recite_buddha_name,
    "start_buddha_recitation": start_buddha_recitation,
    "stop_buddha_recitation": stop_buddha_recitation,
    "get_buddha_recitation_status": get_buddha_recitation_status,
    "check_saka_dawa": check_saka_dawa,
    "check_auspicious_timing": check_auspicious_timing,
    "generate_character": generate_character,
    "start_character_journey": start_character_journey,
    "advance_journey": advance_journey,
    "get_journey_status": get_journey_status,
    "run_full_journey": run_full_journey,
    # Radionics / Broadcasting / Astrology / Audio (via ToolDispatcher)
    "broadcast_healing": broadcast_healing,
    "broadcast_liberation": broadcast_liberation,
    "get_available_intentions": get_available_intentions,
    "get_sacred_frequencies": get_sacred_frequencies,
    "text_to_rate": text_to_rate,
    "measure_general_vitality": measure_general_vitality,
    "find_balancing_rates": find_balancing_rates,
    "search_knowledge": search_knowledge,
    "search_rate_database": search_rate_database,
    "generate_scalar_waves": generate_scalar_waves,
    "get_rng_summary": get_rng_summary,
    "get_chakra_info": get_chakra_info,
    "get_meridian_info": get_meridian_info,
    "create_healing_session": create_healing_session,
    "chakra_balancing_protocol": chakra_balancing_protocol,
    "get_healing_modalities": get_healing_modalities,
    "get_planetary_positions": get_planetary_positions,
    "calculate_natal_chart": calculate_natal_chart,
    "generate_audio": generate_audio,
    "generate_blessing": generate_blessing,
    "get_blessing_traditions": get_blessing_traditions,
    "generate_prayer": generate_prayer,
    "speak_text": speak_text,
    "generate_teaching": generate_teaching,
    "generate_meditation_script": generate_meditation_script,
    "web_search": web_search,
    "web_fetch": web_fetch,
    "get_world_context": get_world_context,
    "get_all_genre_windows": get_all_genre_windows,
    "get_current_conditions": get_current_conditions,
    # Ritual engine
    "get_ritual_status": get_ritual_status,
    "start_ritual_engine": start_ritual_engine,
    "stop_ritual_engine": stop_ritual_engine,
    "trigger_ritual": trigger_ritual,
    "list_practices": list_practices,
    "get_ritual_schedule": get_ritual_schedule,
    "generate_image": _AGENT_DISPATCH,
    "run_working": run_working,
    "forge_witness": forge_witness,
    "get_celestial_night_sky": get_celestial_night_sky,
    "get_dharani_text": get_dharani_text,
    "get_auspicious_timing_details": get_auspicious_timing_details,
    "get_active_world_crises": get_active_world_crises,
    "trigger_living_ritual_broadcast": trigger_living_ritual_broadcast,
}


# Single ordered allowlist sent to the chat model. TOOL_REGISTRY can still
# execute other names if a model invents them; they are just not advertised.
# Keep this list and ``_prioritize_tool_schemas`` in lockstep — there is no
# second filter.
ESSENTIAL_TOOL_ORDER: list[str] = [
    "run_working",
    "forge_witness",
    "generate_single_outlook",
    "generate_prayer",
    "generate_image",
    "generate_epic_outlook",
    "generate_blessing",
    "generate_teaching",
    "forge_sigil",
    "speak_text",
    "cast_tarot_spread",
    "cast_i_ching",
    "cast_geomancy",
    "search_grimoire_correspondences",
    "search_knowledge",
    "web_search",
    "check_auspicious_timing",
    "get_auspicious_timing_details",
    "get_celestial_night_sky",
    "get_dharani_text",
    "get_active_world_crises",
    "trigger_living_ritual_broadcast",
    "check_saka_dawa",
    "get_planetary_hours_and_transits",
    "get_random_buddha",
    "create_population",
    "list_populations",
    "update_population",
    "get_population_statistics",
    "get_system_status",
    "start_automation",
    "stop_automation",
    "get_automation_status",
    "play_chakra_healing_audio",
]

ESSENTIAL_TOOL_NAMES: set[str] = set(ESSENTIAL_TOOL_ORDER)


def get_tool_schemas(essential_only: bool = True) -> list[dict[str, Any]]:
    """
    Get JSON schemas for all available tools.

    Merges RADIONICS_TOOLS (core radionics/broadcasting/astrology schemas)
    with the llm_agent-specific tool schemas (slideshows, populations, narratives).

    Returns schemas in OpenAI function calling format.
    Can be used with Claude, GPT-4, or other LLMs that support tool calling.

    Returns:
        List of tool schemas
    """
    # Import RADIONICS_TOOLS for the full radionics/broadcasting/astrology domain
    try:
        from core.radionics_tools import RADIONICS_TOOLS as raw_schemas

        _radionics_schemas = []
        for s in raw_schemas:
            if "type" in s and s["type"] == "function" and "function" in s:
                _radionics_schemas.append(s["function"])
            else:
                _radionics_schemas.append(s)
    except ImportError:
        _radionics_schemas = []

    # llm_agent-specific schemas (slideshows, populations, narratives, divination, etc.)
    _agent_schemas = [
        {
            "name": "create_rng_session",
            "description": "Create a new RNG attunement session for monitoring psychoenergetic activity during radionics practice",
            "parameters": {
                "type": "object",
                "properties": {
                    "baseline_tone_arm": {
                        "type": "number",
                        "description": "Baseline tone arm setting (0-10), default 5.0",
                    },
                    "sensitivity": {"type": "number", "description": "Sensitivity multiplier (0.1-5.0), default 1.0"},
                },
            },
        },
        {
            "name": "get_rng_reading",
            "description": "Get current RNG reading to check for psychoenergetic activity. floating_needle_score > 0.6 indicates release/completion",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "RNG session ID from create_rng_session"}
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "create_blessing_slideshow",
            "description": "Create a blessing slideshow for a directory of photos with mantras and intentions",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory_path": {"type": "string", "description": "Absolute path to directory containing photos"},
                    "mantra": {
                        "type": "string",
                        "enum": [
                            "chenrezig",
                            "tara",
                            "medicine_buddha",
                            "vajrasattva",
                            "manjushri",
                            "amitabha",
                            "universal",
                        ],
                        "description": "Mantra to use (default: chenrezig)",
                    },
                    "intentions": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "love",
                                "healing",
                                "peace",
                                "protection",
                                "prosperity",
                                "wisdom",
                                "reunion",
                                "safety",
                                "liberation",
                                "compassion",
                                "clarity",
                                "strength",
                            ],
                        },
                        "description": "List of intentions to transmit",
                    },
                    "rng_session_id": {
                        "type": "string",
                        "description": "Optional RNG session ID to link for monitoring",
                    },
                },
                "required": ["directory_path"],
            },
        },
        {
            "name": "create_population",
            "description": "Create a new target population for automated blessings",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Clear, descriptive name for the population"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "missing_persons",
                            "refugees",
                            "disaster_victims",
                            "conflict_zones",
                            "hospital_patients",
                            "humanitarian_crisis",
                            "memorial",
                            "custom",
                        ],
                        "description": "Category of population",
                    },
                    "source_type": {
                        "type": "string",
                        "enum": ["local_directory", "manual"],
                        "description": "Where photos come from",
                    },
                    "directory_path": {
                        "type": "string",
                        "description": "Path to photos (required for local_directory)",
                    },
                    "priority": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Priority level (1-10, higher = more important)",
                    },
                },
                "required": ["name", "category", "source_type"],
            },
        },
        {
            "name": "start_automation",
            "description": "Start automated 24/7 rotation through all populations with fair time distribution",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_per_population": {
                        "type": "integer",
                        "description": "Seconds to spend on each population (default 1800 = 30 min)",
                    },
                    "continuous_mode": {"type": "boolean", "description": "Loop indefinitely if true (default true)"},
                    "link_rng": {"type": "boolean", "description": "Monitor RNG for each population (default true)"},
                },
            },
        },
        {
            "name": "stop_automation",
            "description": "Stop the currently running automated blessing rotation and return final statistics",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Automation session ID from start_automation"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "pause_automation",
            "description": "Pause the automated blessing rotation (can be resumed later)",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Automation session ID from start_automation"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "resume_automation",
            "description": "Resume a previously paused automated blessing rotation",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Automation session ID from start_automation"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "get_automation_status",
            "description": "Get current automation status for monitoring. Call every 5-10 seconds for UI updates",
            "parameters": {
                "type": "object",
                "properties": {"session_id": {"type": "string", "description": "Automation session ID"}},
                "required": ["session_id"],
            },
        },
        {
            "name": "stop_rng_session",
            "description": "Stop an active RNG attunement session and get final summary statistics",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "RNG session ID to stop"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "set_audio_frequency",
            "description": "Directly tune the carrier frequency of the active audio broadcast. Use this to actively change frequencies based on RNG readings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "freq_hz": {"type": "number", "description": "The frequency in Hz to play (e.g. 432.0, 528.0)"},
                    "duration_s": {"type": "number", "description": "Duration to play in seconds, default 30.0"},
                },
                "required": ["freq_hz"],
            },
        },
        {
            "name": "set_audio_modulation",
            "description": "Change the timbre and modulation of the active broadcast. Use this to increase or decrease the intensity/richness of the sound.",
            "parameters": {
                "type": "object",
                "properties": {
                    "harmonic_strength": {"type": "number", "description": "0.0 to 1.0, richness of overtones"},
                    "modulation_depth": {"type": "number", "description": "0.0 to 1.0, depth of vibrato/tremolo"},
                    "duration_s": {"type": "number", "description": "Duration to play in seconds, default 30.0"},
                },
                "required": ["harmonic_strength", "modulation_depth"],
            },
        },
        {
            "name": "play_audio_preset",
            "description": "Play a specific predefined audio preset. Available presets: 'om-frequency', 'heart-chakra', 'earth-resonance', 'pure-sine'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "preset_name": {"type": "string", "description": "Name of the preset to play"},
                    "duration_s": {"type": "number", "description": "Duration in seconds, default 30.0"},
                },
                "required": ["preset_name"],
            },
        },
        {
            "name": "play_chakra_healing_audio",
            "description": "Generate and play a Tibetan prayer bowl tone tuned to a specific chakra. Use this to calm the space.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chakra_name": {"type": "string", "description": "Name of the chakra (e.g. root, sacral, heart)"},
                    "duration": {"type": "number", "description": "Duration to play in seconds, default 30.0"},
                },
                "required": ["chakra_name"],
            },
        },
        {
            "name": "list_populations",
            "description": "Get list of all populations with optional filtering",
            "parameters": {
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean", "description": "Only return active populations"},
                    "category": {"type": "string", "description": "Filter by specific category"},
                },
            },
        },
        {
            "name": "get_population_statistics",
            "description": "Get overall statistics across all populations including totals and categories",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "get_system_status",
            "description": "Complete system snapshot — populations, automation, RNG, rituals, practices. Use when user asks for 'statistics', 'status', 'dashboard', or 'system overview'. Returns everything in one call.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "forge_sigil",
            "description": "Create a graphical, neon-glowing vector sigil on a planetary magic square from an intention.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intention": {
                        "type": "string",
                        "description": "Clear intention statement (e.g. 'protection and clarity')",
                    },
                    "kamea": {
                        "type": "string",
                        "enum": ["saturn", "jupiter", "mars"],
                        "description": "Planetary grid context (default saturn)",
                    },
                },
                "required": ["intention"],
            },
        },
        {
            "name": "cast_tarot_spread",
            "description": "Draw Tarot cards with elemental, Hebrew, and planetary correspondences to answer a question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of cards to draw: 1 (single), 3 (past/present/future), or 10 (Celtic Cross)",
                    },
                    "question": {"type": "string", "description": "Focus question for oracle interpretation"},
                },
            },
        },
        {
            "name": "cast_i_ching",
            "description": "Cast I Ching hexagrams using traditional yarrow-stalk probabilities, listing primary and relating hexagram meanings.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string", "description": "The situation or query to interpret"}},
            },
        },
        {
            "name": "cast_geomancy",
            "description": "Cast a full 16-figure Geomantic shield chart projected into the 12 astrological houses.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string", "description": "Query or context for the cast"}},
            },
        },
        {
            "name": "search_grimoire_correspondences",
            "description": "Search the Grimoire database for herbs, minerals, metals, planets, chakras, and rates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The herb, stone, planet, rate, or symptom to lookup"}
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_planetary_hours_and_transits",
            "description": "Fetch current planetary hours timeline, daily rulers, and planetary transit aspects.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "generate_single_outlook",
            "description": "Generate a single-pass sutra-style blessing and narrative outlook weaving astrology, divination, and realms. USE THIS TOOL when the user asks for: an outlook, a blessing, a sutra, a prayer, a healing story, a narrative blessing, or a generated prayer/affirmation for a group of people. The custom_context should reflect the user's stated intention. Do not call create_population repeatedly; if a population is needed, create it ONCE then call this tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "Target latitude"},
                    "lon": {"type": "number", "description": "Target longitude"},
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Languages to weave (English, Sanskrit, Tibetan, Chinese, Latin, Greek, Hebrew)",
                    },
                    "genre": {
                        "type": "string",
                        "enum": ["healing", "victory", "alchemist", "fun_parable", "dharani"],
                        "description": "Blessing genre",
                    },
                    "custom_context": {"type": "string", "description": "Custom aspirations or intention text"},
                    "realm_id": {"type": "string", "description": "Location or realm ID from list_narrative_locations"},
                    "population_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Target population IDs",
                    },
                    "character_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Characters present in narrative",
                    },
                    "excluded_forces": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Negative forces to pacify",
                    },
                    "include_dialogue": {
                        "type": "boolean",
                        "description": "Whether to include active dialogue between characters",
                    },
                },
            },
        },
        {
            "name": "generate_epic_outlook",
            "description": "Generate a multi-stage epic narrative blessing cycle over an extended arc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "Target latitude"},
                    "lon": {"type": "number", "description": "Target longitude"},
                    "languages": {"type": "array", "items": {"type": "string"}, "description": "Languages to weave"},
                    "genre": {
                        "type": "string",
                        "enum": ["healing", "victory", "alchemist", "fun_parable", "dharani"],
                        "description": "Blessing genre",
                    },
                    "stages": {"type": "integer", "description": "Number of stages to generate (default 9)"},
                    "custom_context": {"type": "string", "description": "Custom aspirations or intention text"},
                    "realm_id": {"type": "string", "description": "Location or realm ID"},
                    "population_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Target population IDs",
                    },
                    "character_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Characters present in narrative",
                    },
                    "excluded_forces": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Negative forces to pacify",
                    },
                    "include_dialogue": {
                        "type": "boolean",
                        "description": "Whether to include active dialogue between characters",
                    },
                },
            },
        },
        {
            "name": "list_narrative_locations",
            "description": "List all active settings, earthly sacred sites, and metaphysical realms.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "create_narrative_location",
            "description": "Define a new location or metaphysical realm setting for narrative blessings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of location or realm"},
                    "description": {"type": "string", "description": "Visionary description"},
                    "location_type": {
                        "type": "string",
                        "enum": [
                            "earthly_sacred",
                            "metaphysical_realm",
                            "cosmic_anchor",
                            "historical_academy",
                            "custom",
                        ],
                    },
                    "source_type": {"type": "string", "enum": ["manual", "generated", "mythology", "geographic"]},
                    "is_metaphysical": {"type": "boolean", "description": "Set True for metaphysical realms"},
                    "latitude": {"type": "number", "description": "Latitude (for earthly location)"},
                    "longitude": {"type": "number", "description": "Longitude (for earthly location)"},
                    "celestial_coordinates": {"type": "string", "description": "Star coordinates (metaphysical only)"},
                    "dimension_frequency": {
                        "type": "number",
                        "description": "Vibrational frequency in Hz (metaphysical only)",
                    },
                    "realm_governor": {"type": "string", "description": "Deity/guardian ruler"},
                    "astrological_anchor": {"type": "string", "description": "Planetary line anchor"},
                    "elemental_affinity": {"type": "string", "description": "Element (Fire, Water, etc.)"},
                },
                "required": ["name", "description", "location_type"],
            },
        },
        {
            "name": "list_narrative_characters",
            "description": "List all active narrative character personalities and spiritual archetypes.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "create_narrative_character",
            "description": "Create a new character archetype to weave into dialogue parables.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Character name"},
                    "role": {
                        "type": "string",
                        "enum": ["master", "student", "alchemist", "hero", "deity", "guardian", "custom"],
                    },
                    "description": {"type": "string", "description": "Biography description"},
                    "dialogue_style": {"type": "string", "description": "Description of speaking style (e.g. koans)"},
                    "associated_realms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Realm IDs frequented",
                    },
                    "mantra_preference": {"type": "string", "description": "Preferred mantra key"},
                    "elemental_anchor": {"type": "string", "description": "Element key (space, fire, earth, etc.)"},
                },
                "required": ["name", "role", "description"],
            },
        },
        {
            "name": "start_narrative_loop",
            "description": "Start continuous background narrative generation broadcasting on cycles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "interval_minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1440,
                        "description": "Minutes per cycle",
                    },
                    "lat": {"type": "number", "description": "Target latitude"},
                    "lon": {"type": "number", "description": "Target longitude"},
                    "languages": {"type": "array", "items": {"type": "string"}, "description": "Languages to weave"},
                    "genre": {
                        "type": "string",
                        "enum": ["healing", "victory", "alchemist", "fun_parable", "dharani"],
                        "description": "Blessing genre",
                    },
                    "custom_context": {"type": "string", "description": "Custom intentions"},
                    "realm_id": {"type": "string", "description": "Realm ID"},
                    "population_ids": {"type": "array", "items": {"type": "string"}, "description": "Population IDs"},
                    "character_ids": {"type": "array", "items": {"type": "string"}, "description": "Character IDs"},
                    "excluded_forces": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Negative forces to pacify",
                    },
                    "include_dialogue": {"type": "boolean", "description": "Include dialogue if True"},
                },
            },
        },
        {
            "name": "stop_narrative_loop",
            "description": "Stop the continuous background narrative loop.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "get_narrative_loop_status",
            "description": "Check configuration and status of the continuous narrative broadcast loop.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "get_current_slide",
            "description": "Get current slideshow photo details, progress, and overlay information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Slideshow session ID"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "stop_slideshow",
            "description": "Stop an active blessing slideshow and get final statistics including photos blessed and mantras repeated.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Slideshow session ID"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "update_population",
            "description": "Update a target population's settings — priority, active status, urgency, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "population_id": {"type": "string", "description": "Population ID to update"},
                    "priority": {"type": "integer", "description": "Priority 1-10"},
                    "is_urgent": {"type": "boolean", "description": "Whether urgent"},
                    "is_active": {"type": "boolean", "description": "Whether active"},
                },
                "required": ["population_id"],
            },
        },
        {
            "name": "get_automation_stats",
            "description": "Get complete automation statistics including history, totals, sessions completed, and populations processed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Automation session ID"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "add_agent_suggestion",
            "description": "Log an intentional path or suggestion for a task the agent wanted to do but couldn't because of missing capabilities or permissions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Identifier for the current agent"},
                    "intention": {"type": "string", "description": "What you intended to do"},
                    "missing_tools": {"type": "string", "description": "The specific tools or capabilities you needed"},
                    "context": {"type": "string", "description": "Why you wanted to do it"},
                },
                "required": ["agent_id", "intention", "missing_tools", "context"],
            },
        },
        {
            "name": "run_working",
            "description": (
                "Begin a complete radionics working: derive a 5-dial rate from the "
                "intention, stamp Saka Dawa / Losar timing, map Solfeggio carriers, "
                "and optionally start a prayer-bowl broadcast. USE THIS when the user "
                "asks to begin a working, attune, broadcast a rate, charge an intention, "
                "or do radionics — not for casual chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intention": {
                        "type": "string",
                        "description": "The working's intention in the user's own words",
                    },
                    "target": {
                        "type": "string",
                        "description": "Who or what the working is for (default: all beings)",
                    },
                    "broadcast": {
                        "type": "boolean",
                        "description": "Start the prayer-bowl broadcast (default true)",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Broadcast duration in minutes, 1-30 (default 5)",
                    },
                },
                "required": ["intention"],
            },
        },
        {
            "name": "forge_witness",
            "description": (
                "Generate a manifestation image for an already sealed working "
                "and attach it to the folio. Cheaper than video. Pass working_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "working_id": {
                        "type": "string",
                        "description": "Id returned by run_working (wrk_…)",
                    },
                },
                "required": ["working_id"],
            },
        },
        {
            "name": "speak_text",
            "description": (
                "Speak text through the TTS engine. Use after generating a "
                "blessing, prayer, or teaching so it can be heard."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to speak"},
                    "voice": {"type": "string", "description": "Optional voice override"},
                    "role": {
                        "type": "string",
                        "description": "Ritual role for voice selection (default dharma_teaching)",
                    },
                },
                "required": ["text"],
            },
        },
        {
            "name": "generate_image",
            "description": (
                "Generate an image from a text prompt. The model and provider are "
                "configured in Settings — the LLM should NOT choose them. When "
                "model_lock is enabled (default), the configured default is always "
                "used. When disabled (discretionary mode), the LLM may suggest a "
                "model for the task, but the user's Settings still take precedence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Image description. 30-60 words is ideal; max 1000 tokens. "
                            "Be specific about subject, style, lighting, and mood."
                        ),
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "description": "Override the configured default aspect ratio (e.g. '1:1', '16:9', '9:16'). Only set if the user explicitly asks for a specific shape.",
                    },
                    "subject_reference": {
                        "type": "string",
                        "description": "MiniMax only: URL of reference image for character consistency",
                    },
                },
                "required": ["prompt"],
            },
        },
        {
            "name": "get_celestial_night_sky",
            "description": "Calculate topocentric celestial dome Alt/Az coordinates for 10 planets and 10 Vedic nakshatra stars, with Moon phase, illumination, and LST.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "description": "Observer latitude in degrees (default: San Francisco 37.7749)",
                    },
                    "longitude": {
                        "type": "number",
                        "description": "Observer longitude in degrees (default: San Francisco -122.4194)",
                    },
                    "timestamp": {
                        "type": "number",
                        "description": "Unix timestamp in seconds (optional, defaults to now)",
                    },
                },
            },
        },
        {
            "name": "get_dharani_text",
            "description": "Retrieve complete unabbreviated sacred Dhāraṇī text (Sanskrit IAST, Chinese characters, English meaning, and recitation count). Supports Great Compassion (84 phrases), Śūraṅgama (5 assemblies), Sitātapatrā, Mahāpratisarā, Cundi, etc. Call with 'list' to browse directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dharani_id_or_name": {
                        "type": "string",
                        "description": "Identifier or name of dhāraṇī (e.g. 'great_compassion_dharani', 'shurangama_mantra_full', 'sitatapatra_dharani', 'cundi_dharani', or 'list')",
                    },
                },
            },
        },
        {
            "name": "get_auspicious_timing_details",
            "description": "Retrieve full 24-hour Auspicious Timing Wheel data including planetary hours, current ruler, day/night status, tithi, nakshatra, Saka Dawa multiplier, and ritual genre green windows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "description": "Observer latitude in degrees"},
                    "longitude": {"type": "number", "description": "Observer longitude in degrees"},
                },
            },
        },
        {
            "name": "get_active_world_crises",
            "description": "Fetch real-time global crises and natural disaster alerts from GDACS and ReliefWeb, including geographic coordinates, magnitude/severity, and recommended compassionate healing intention focus.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "trigger_living_ritual_broadcast",
            "description": "Trigger a living ritual broadcast combining 6-section generated ritual liturgy, crystal bowl Solfeggio carriers, dedication, and optional TTS recitation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intention": {"type": "string", "description": "Sacred intention or dedication"},
                    "target": {"type": "string", "description": "Target recipient or region (default 'all beings')"},
                    "ritual_type": {
                        "type": "string",
                        "enum": [
                            "healing",
                            "victory",
                            "wisdom",
                            "purification",
                            "compassion",
                            "prosperity",
                            "protection",
                            "dedication_of_endeavors",
                        ],
                        "description": "Ritual genre or archetype",
                    },
                    "duration_minutes": {"type": "integer", "description": "Broadcast duration in minutes (default 5)"},
                    "recite_with_tts": {"type": "boolean", "description": "Whether to recite the ritual aloud via TTS"},
                },
            },
        },
    ]

    all_schemas = _radionics_schemas + _agent_schemas

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for s in all_schemas:
        name = s.get("name", "")
        if name in seen:
            continue
        seen.add(name)
        deduped.append(s)

    if essential_only:
        deduped = [s for s in deduped if s.get("name", "") in ESSENTIAL_TOOL_NAMES]

    return deduped


# Example usage for LLM agents
if __name__ == "__main__":
    # Example: Complete automated workflow
    print("Creating population...")
    pop = create_population(
        name="Test Population", category="custom", source_type="manual", description="Test population for demonstration"
    )
    print(f"Created: {pop['id']}")

    print("\nListing all populations...")
    pops = list_populations()
    print(f"Total populations: {len(pops)}")

    print("\nGetting statistics...")
    stats = get_population_statistics()
    print(f"Total blessings sent: {stats['total_blessings_sent']}")

    # More examples would follow...
