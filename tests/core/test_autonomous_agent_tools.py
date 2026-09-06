"""
Tests for Autonomous Agent Tool Expansion:
- get_celestial_night_sky
- get_dharani_text
- get_auspicious_timing_details
- get_active_world_crises
- trigger_living_ritual_broadcast
- execute_tool_locally integration and aliasing
"""

from unittest.mock import patch

import pytest

from backend.app.api.v1.endpoints.llm import _resolve_tool_name, execute_tool_locally
from backend.core.llm_agent.tools import (
    TOOL_REGISTRY,
    get_active_world_crises,
    get_auspicious_timing_details,
    get_celestial_night_sky,
    get_dharani_text,
    get_tool_schemas,
    trigger_living_ritual_broadcast,
)


def test_tools_registered_in_registry():
    new_tools = [
        "get_celestial_night_sky",
        "get_dharani_text",
        "get_auspicious_timing_details",
        "get_active_world_crises",
        "trigger_living_ritual_broadcast",
    ]
    for name in new_tools:
        assert name in TOOL_REGISTRY, f"{name} missing from TOOL_REGISTRY"
        assert callable(TOOL_REGISTRY[name])


def test_tool_schemas_contain_new_tools():
    schemas = get_tool_schemas(essential_only=False)
    schema_names = {s["name"] for s in schemas}
    for name in [
        "get_celestial_night_sky",
        "get_dharani_text",
        "get_auspicious_timing_details",
        "get_active_world_crises",
        "trigger_living_ritual_broadcast",
    ]:
        assert name in schema_names, f"{name} missing from schemas"


def test_get_celestial_night_sky():
    res = get_celestial_night_sky(latitude=37.7749, longitude=-122.4194)
    assert res["status"] == "success"
    assert "observer" in res
    assert res["observer"]["latitude"] == 37.7749
    assert res["observer"]["longitude"] == -122.4194
    assert "moon" in res
    assert "phase_name" in res["moon"]
    assert "illumination_pct" in res["moon"]
    assert "planets" in res
    assert len(res["planets"]) >= 7
    planet_names = [p["name"] for p in res["planets"]]
    assert "Sun" in planet_names
    assert "Moon" in planet_names
    assert "Jupiter" in planet_names
    assert "sacred_stars" in res
    assert len(res["sacred_stars"]) == 10
    star_names = [s["name"] for s in res["sacred_stars"]]
    assert any("Sirius" in name for name in star_names)
    assert any("Vega" in name for name in star_names)
    assert any("Spica" in name for name in star_names)


def test_get_dharani_text_directory():
    res = get_dharani_text("list")
    assert res["status"] == "list"
    assert res["total"] >= 5
    assert len(res["available_dharanis"]) >= 5
    ids = [d["id"] for d in res["available_dharanis"]]
    assert "great_compassion_dharani" in ids
    assert "shurangama_mantra_full" in ids
    assert "sitatapatra_dharani" in ids


def test_get_dharani_text_unabbreviated_great_compassion():
    res = get_dharani_text("great_compassion_dharani")
    assert res["status"] == "found"
    dharani = res["dharani"]
    assert dharani["id"] == "great_compassion_dharani"
    # Verify phrase 84 exists (unabbreviated text)
    assert "唵悉殿都。漫多囉。跋陀耶。娑婆訶。" in dharani["text_chinese"]
    assert "healing" in dharani["purpose"]


def test_get_dharani_text_unabbreviated_shurangama_full():
    res = get_dharani_text("shurangama_mantra_full")
    assert res["status"] == "found"
    dharani = res["dharani"]
    # Verify all 5 assemblies are present
    chinese = dharani["text_chinese"]
    assert "第一會" in chinese
    assert "第二會" in chinese
    assert "第三會" in chinese
    assert "第四會" in chinese
    assert "第五會" in chinese


def test_get_dharani_text_cundi_full_praise():
    res = get_dharani_text("cundi_dharani")
    assert res["status"] == "found"
    dharani = res["dharani"]
    assert "稽首皈依蘇悉帝" in dharani["text_chinese"]
    assert "我今稱讚大準提" in dharani["text_chinese"]


def test_get_auspicious_timing_details():
    res = get_auspicious_timing_details(latitude=37.7749, longitude=-122.4194)
    assert res["status"] == "success"
    assert "current_planetary_hour" in res
    assert "ruler" in res["current_planetary_hour"]
    assert "day_planet" in res["current_planetary_hour"]
    assert "moon" in res
    assert "tithi" in res["moon"]
    assert "nakshatra" in res["moon"]
    assert "saka_dawa" in res
    assert "hourly_slices" in res


def test_get_active_world_crises():
    with patch("core.internet_context.compile_world_context") as mock_compile:
        from core.internet_context import InternetContext, WorldEvent

        mock_ctx = InternetContext(
            events=[
                WorldEvent(
                    title="Earthquake M6.5",
                    description="Severe shaking reported",
                    location="Pacific Rim",
                    lat=14.2,
                    lon=121.1,
                    event_type="disaster",
                    severity="high",
                    source="GDACS",
                ),
                WorldEvent(
                    title="Flooding Alert",
                    description="Monsoon river rise",
                    location="Ganges Basin",
                    lat=25.3,
                    lon=83.0,
                    event_type="humanitarian",
                    severity="medium",
                    source="ReliefWeb",
                ),
            ],
            summary="2 events detected",
        )
        mock_compile.return_value = mock_ctx

        res = get_active_world_crises()
        assert res["status"] == "success"
        assert res["total_crises"] == 2
        assert res["disaster_count"] == 1
        assert res["humanitarian_count"] == 1
        assert res["crises"][0]["title"] == "Earthquake M6.5"
        assert res["crises"][0]["latitude"] == 14.2


def test_trigger_living_ritual_broadcast():
    with patch("backend.core.llm_agent.tools._run_async") as mock_run:
        mock_run.return_value = {
            "status": "success",
            "session_id": "ritual_test123",
            "ritual_markdown": "# Sacred Ritual\nOm Mani Padme Hum",
            "frequencies": [7.83, 528.0],
            "solfeggio_names": ["Schumann Base", "Mi (Transformation)"],
        }
        res = trigger_living_ritual_broadcast(
            intention="Peace and protection",
            target="all beings",
            ritual_type="compassion",
        )
        assert res["status"] == "success"
        assert res["session_id"] == "ritual_test123"
        assert len(res["frequencies"]) == 2


@pytest.mark.asyncio
async def test_execute_tool_locally_dispatch_and_aliases():
    # Test night sky alias
    assert _resolve_tool_name("get_night_sky") == "get_celestial_night_sky"
    res_sky = await execute_tool_locally("get_night_sky", {"lat": 37.7749, "lon": -122.4194})
    assert res_sky["status"] == "success"

    # Test dharani alias
    assert _resolve_tool_name("get_dharani") == "get_dharani_text"
    res_dharani = await execute_tool_locally("get_dharani", {"dharani_id_or_name": "cundi_dharani"})
    assert res_dharani["status"] == "found"

    # Test timing wheel alias
    assert _resolve_tool_name("timing_wheel") == "get_auspicious_timing_details"
    res_timing = await execute_tool_locally("timing_wheel", {"lat": 37.7749, "lon": -122.4194})
    assert "current_planetary_hour" in res_timing

    # Test world crises alias
    assert _resolve_tool_name("world_crises") == "get_active_world_crises"
    with patch("core.internet_context.compile_world_context") as mock_compile:
        from core.internet_context import InternetContext

        mock_compile.return_value = InternetContext(events=[], summary="No events")
        res_crises = await execute_tool_locally("world_crises", {})
        assert res_crises["status"] == "success"
