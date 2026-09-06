import pytest

from infrastructure.event_bus import EnhancedEventBus


@pytest.fixture
def event_bus():
    bus = EnhancedEventBus()
    yield bus
    bus.clear()


@pytest.fixture
def fresh_container():
    from container import Container

    c = Container()
    c._initialized = False
    c.__init__()
    yield c
    c.reset()


@pytest.fixture
def tmp_output_dir(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    return out


# ---------------------------------------------------------------------------
# Deterministic geocoding for tests
# ---------------------------------------------------------------------------
# The real backend/core/services/geocoding_service.py wraps geopy.Nominatim,
# which is rate-limited (HTTP 429) by OpenStreetMap. The integration and
# e2e tests create natal charts with city names ("London", "Tokyo", ...)
# and were intermittently failing when pytest collected enough geocoding
# calls in a short window to hit the rate limit.
#
# This autouse fixture swaps the singleton's lookup method for a
# deterministic dict-based implementation. Tests that need to assert
# specific lat/lon (like the e2e workflow) get the same canonical
# coordinates on every run; tests that exercise the "city not found"
# path (e.g. test_400_on_bad_geocode) get a real "not found" reply.
# ---------------------------------------------------------------------------
_CANNED_GEOCODES: dict[str, dict] = {
    "London": {
        "latitude": 51.5074,
        "longitude": -0.1278,
        "timezone": "Europe/London",
        "address": "London, Greater London, England, UK",
    },
    "Paris": {
        "latitude": 48.8566,
        "longitude": 2.3522,
        "timezone": "Europe/Paris",
        "address": "Paris, Île-de-France, France",
    },
    "New York": {
        "latitude": 40.7128,
        "longitude": -74.0060,
        "timezone": "America/New_York",
        "address": "New York, NY, USA",
    },
    "Tokyo": {
        "latitude": 35.6762,
        "longitude": 139.6503,
        "timezone": "Asia/Tokyo",
        "address": "Tokyo, Japan",
    },
    "New Delhi": {
        "latitude": 28.6139,
        "longitude": 77.2090,
        "timezone": "Asia/Kolkata",
        "address": "New Delhi, Delhi, India",
    },
    "San Francisco": {
        "latitude": 37.7749,
        "longitude": -122.4194,
        "timezone": "America/Los_Angeles",
        "address": "San Francisco, CA, USA",
    },
    "Beijing": {
        "latitude": 39.9042,
        "longitude": 116.4074,
        "timezone": "Asia/Shanghai",
        "address": "Beijing, China",
    },
    "Mumbai": {
        "latitude": 19.0760,
        "longitude": 72.8777,
        "timezone": "Asia/Kolkata",
        "address": "Mumbai, Maharashtra, India",
    },
}


def _fake_get_coordinates_and_timezone(self, location_name: str) -> dict:
    """Stand-in for GeocodingService.get_coordinates_and_timezone used
    in tests. Returns canned data for known cities, a "not found"
    error for anything that starts with Xyzzy (the convention the
    e2e test uses to assert the 400 path), and a generic UTC fallback
    for any other unknown city so that tests which only assert
    *success* still succeed without hitting the real Nominatim service.
    """
    key = (location_name or "").strip()
    if key in _CANNED_GEOCODES:
        return dict(_CANNED_GEOCODES[key])
    if key.startswith("Xyzzy"):
        return {"error": f"Location '{key}' not found."}
    return {
        "latitude": 0.0,
        "longitude": 0.0,
        "timezone": "UTC",
        "address": key or "Unknown",
    }


@pytest.fixture(autouse=True)
def _deterministic_geocoding(monkeypatch):
    """Replace GeocodingService.get_coordinates_and_timezone with a
    deterministic dict lookup. Autouse so every test that triggers a
    chart creation (and therefore a city lookup) sees the same
    canonical coordinates and never hits the real Nominatim service.

    We load geocoding_service.py by file path (bypassing the circular
    import chain in backend.core.services.__init__) and register it
    in sys.modules under its real dotted name. This ensures that when
    endpoint code does ``from backend.core.services.geocoding_service
    import geocoding_service`` at runtime, Python finds the cached
    module (with the patched class) rather than importing a fresh copy.
    """
    import importlib.util
    import os
    import sys

    mod_name = "backend.core.services.geocoding_service"
    # If the module is already loaded (e.g. by a prior import), patch it directly.
    if mod_name in sys.modules:
        gs_mod = sys.modules[mod_name]
    else:
        gs_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "backend",
            "core",
            "services",
            "geocoding_service.py",
        )
        if not os.path.exists(gs_path):
            return
        spec = importlib.util.spec_from_file_location(mod_name, gs_path)
        gs_mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(gs_mod)
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).debug("Skipping geocoding patch: %s: %s", type(exc).__name__, exc)
            return
        # Register in sys.modules so the endpoint's function-level import
        # resolves to THIS module object (with the patched class).
        sys.modules[mod_name] = gs_mod

    monkeypatch.setattr(
        gs_mod.GeocodingService,
        "get_coordinates_and_timezone",
        _fake_get_coordinates_and_timezone,
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: fast isolated tests")
    config.addinivalue_line("markers", "integration: tests wiring multiple modules")
    config.addinivalue_line("markers", "slow: tests taking more than a few seconds")


# ---------------------------------------------------------------------------
# No real external LLM spend from the test suite
# ---------------------------------------------------------------------------
# A test that reaches an external provider (openrouter/deepseek/openai/...)
# burns quota and money even when it "passes". Recording happens in
# LLMUsageTracker.record — every layer funnels there — so the guard wraps
# it and fails whichever test was running when an external record landed.
# Live external calls belong in tests/e2e/ only, which this guard exempts.
_EXTERNAL_LLM_PROVIDERS = frozenset({"openrouter", "deepseek", "openai", "anthropic", "z_ai", "minimax"})


@pytest.fixture(autouse=True)
def _no_external_llm_spend(request, monkeypatch):
    nodeid = request.node.nodeid.replace("\\", "/")
    if "/e2e/" in nodeid or request.node.get_closest_marker("e2e"):
        yield
        return

    from core.llm.usage import LLMUsageTracker

    violations: list[str] = []
    original = LLMUsageTracker.record

    def guarded_record(self, record):
        if str(getattr(record, "provider", "")).lower() in _EXTERNAL_LLM_PROVIDERS:
            violations.append(
                f"{record.provider}/{getattr(record, 'model', '?')} tok={getattr(record, 'total_tokens', '?')}"
            )
        return original(self, record)

    monkeypatch.setattr(LLMUsageTracker, "record", guarded_record)
    yield
    assert not violations, (
        f"{request.node.nodeid} made REAL external LLM call(s): {', '.join(violations)}. "
        "Mock the LLM/registry in this test — live external calls belong in tests/e2e/."
    )
