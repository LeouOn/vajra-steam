"""
Tests for core.celestial_sky — topocentric celestial night-sky dome calculations.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.celestial_sky import PLANET_INFO, SACRED_FIXED_STARS, calculate_night_sky


@pytest.mark.unit
def test_calculate_night_sky_structure():
    """calculate_night_sky returns a complete dictionary with observer, moon, planets, and stars."""
    dt = datetime(2026, 9, 6, 21, 0, 0, tzinfo=timezone.utc)
    res = calculate_night_sky(latitude=37.7749, longitude=-122.4194, dt=dt)

    assert "timestamp_utc" in res
    assert "observer" in res
    assert "moon" in res
    assert "planets" in res
    assert "sacred_stars" in res

    obs = res["observer"]
    assert obs["latitude"] == 37.7749
    assert obs["longitude"] == -122.4194
    assert "local_sidereal_time_deg" in obs
    assert "local_sidereal_time_hms" in obs

    # Planets count matches PLANET_INFO
    assert len(res["planets"]) == len(PLANET_INFO)
    for p in res["planets"]:
        assert "id" in p
        assert "name" in p
        assert "glyph" in p
        assert -90.0 <= p["altitude"] <= 90.0
        assert 0.0 <= p["azimuth"] <= 360.0
        assert "sign" in p
        assert "visible" in p
        assert isinstance(p["visible"], bool)

    # Moon data
    moon = res["moon"]
    assert "phase_name" in moon
    assert 0.0 <= moon["illumination"] <= 100.0
    assert "altitude" in moon

    # Stars count matches SACRED_FIXED_STARS
    assert len(res["sacred_stars"]) == len(SACRED_FIXED_STARS)
    for s in res["sacred_stars"]:
        assert "id" in s
        assert "name" in s
        assert "sanskrit" in s
        assert -90.0 <= s["altitude"] <= 90.0
        assert 0.0 <= s["azimuth"] <= 360.0
        assert "nakshatra" in s
        assert "quality" in s


@pytest.mark.unit
def test_calculate_night_sky_polaris_near_latitude():
    """Polaris altitude should closely approximate observer latitude in Northern hemisphere."""
    lat = 37.7749
    lon = -122.4194
    dt = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
    res = calculate_night_sky(latitude=lat, longitude=lon, dt=dt)

    polaris = next((s for s in res["sacred_stars"] if s["id"] == "polaris"), None)
    assert polaris is not None
    # Polaris Dec is ~89.26°, so its altitude should be within 1.5° of latitude
    assert abs(polaris["altitude"] - lat) < 1.5
