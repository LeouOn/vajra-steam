import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { createRoot } from 'react-dom/client';
import { act } from 'react-dom/test-utils';
import CelestialSkyDome from '../../components/UI/CelestialSkyDome';

const mockNightSkyResponse = {
  timestamp_utc: '2026-09-06T21:00:00Z',
  observer: {
    latitude: 37.7749,
    longitude: -122.4194,
    local_sidereal_time_deg: 161.68,
    local_sidereal_time_hms: '10:46:45',
  },
  moon: {
    altitude: 42.5,
    azimuth: 115.2,
    phase_name: 'Waning Crescent',
    illumination: 22.6,
    visible: true,
    sign: 'Cancer',
  },
  planets: [
    {
      id: 'sun',
      name: 'Sun',
      glyph: '☉',
      altitude: -15.4,
      azimuth: 285.1,
      right_ascension: 165.2,
      declination: 6.1,
      longitude_ecliptic: 164.2,
      sign: 'Virgo',
      sign_glyph: '♍',
      sign_degree: 14.2,
      visible: false,
      color: '#f59e0b',
      esoteric_quality: 'Atman · Radiance',
    },
    {
      id: 'jupiter',
      name: 'Jupiter',
      glyph: '♃',
      altitude: 58.2,
      azimuth: 142.1,
      right_ascension: 92.1,
      declination: 22.4,
      longitude_ecliptic: 91.5,
      sign: 'Cancer',
      sign_glyph: '♋',
      sign_degree: 1.5,
      visible: true,
      color: '#a855f7',
      esoteric_quality: 'Guru · Expansive Grace',
    },
  ],
  visible_planets_count: 1,
  sacred_stars: [
    {
      id: 'sirius',
      name: 'Sirius (Mrigavyadha)',
      sanskrit: 'मृगव्याध (Lubdhaka)',
      altitude: 35.8,
      azimuth: 122.4,
      magnitude: -1.46,
      visible: true,
      color: '#a6d8ff',
      nakshatra: 'Ardra / Rudra',
      quality: 'Supreme Cosmic Fire',
      zenith_distance: 54.2,
    },
    {
      id: 'polaris',
      name: 'Polaris (Dhruva)',
      sanskrit: 'ध्रुव (Dhruva)',
      altitude: 37.8,
      azimuth: 0.5,
      magnitude: 1.98,
      visible: true,
      color: '#f8fafc',
      nakshatra: 'Celestial North Axis',
      quality: 'The Immovable Center',
      zenith_distance: 52.2,
    },
  ],
  visible_stars_count: 2,
};

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const noop = () => {};
const stubCtx = () =>
  ({
    clearRect: noop,
    beginPath: noop,
    arc: noop,
    fill: noop,
    stroke: noop,
    moveTo: noop,
    lineTo: noop,
    fillText: noop,
    setLineDash: noop,
    measureText: () => ({ width: 10 } as TextMetrics),
    createRadialGradient: () =>
      ({
        addColorStop: noop,
      } as unknown as CanvasGradient),
    save: noop,
    restore: noop,
    setTransform: noop,
  }) as unknown as CanvasRenderingContext2D;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(stubCtx());
  global.fetch = vi.fn().mockImplementation(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(mockNightSkyResponse),
    } as Response)
  );
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

describe('CelestialSkyDome', () => {
  it('renders the night sky card and canvas element', async () => {
    await act(async () => {
      root.render(<CelestialSkyDome latitude={37.7749} longitude={-122.4194} />);
    });
    expect(container.querySelector('[data-testid="celestial-sky-dome-card"]')).toBeDefined();
    expect(container.querySelector('[data-testid="celestial-sky-dome-canvas"]')).toBeDefined();
    expect(container.textContent).toContain('Celestial Night-Sky Dome');
  });

  it('renders visible planets and sacred stars tags', async () => {
    await act(async () => {
      root.render(<CelestialSkyDome latitude={37.7749} longitude={-122.4194} />);
    });
    // Jupiter is visible in mock
    expect(container.textContent).toContain('Jupiter');
    // Sirius and Polaris are visible in mock
    expect(container.textContent).toContain('Sirius');
    expect(container.textContent).toContain('Polaris');
    // LST and Moon phase are displayed
    expect(container.textContent).toContain('10:46:45');
    expect(container.textContent).toContain('Waning Crescent');
  });
});
