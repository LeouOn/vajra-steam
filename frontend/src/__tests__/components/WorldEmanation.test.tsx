import React from 'react';
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { createRoot } from 'react-dom/client';
import { act } from 'react-dom/test-utils';
import WorldEmanation from '../../components/3D/WorldEmanation';
import { useBroadcastStore } from '../../stores/broadcastStore';

// Mock Three.js / R3F Canvas since happy-dom has no real WebGL context
vi.mock('@react-three/fiber', () => ({
  Canvas: () => <div data-testid="r3f-canvas" />,
  useFrame: () => {},
}));

vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
  Stars: () => null,
  Text: () => null,
}));

describe('WorldEmanation', () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    useBroadcastStore.getState().clear();
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    if (container && container.parentNode) {
      container.parentNode.removeChild(container);
    }
  });

  it('renders compact variant in calm field state', async () => {
    const root = createRoot(container);
    await act(async () => {
      root.render(<WorldEmanation variant="compact" />);
    });
    expect(container.querySelector('[data-testid="world-emanation"]')).not.toBeNull();
    expect(container.textContent || '').toContain('Field Receptive');
  });

  it('renders full variant with telemetry badges', async () => {
    const root = createRoot(container);
    await act(async () => {
      root.render(<WorldEmanation variant="full" />);
    });
    expect(container.querySelector('[data-testid="world-emanation"]')).not.toBeNull();
    expect(container.textContent || '').toContain('0 live');
  });

  it('reflects live broadcast status in header badge', async () => {
    const baseTime = Date.now();

    useBroadcastStore.getState().push({
      target: 'Japan',
      frequency_hz: 528,
      duration_minutes: 5,
      receivedAt: baseTime,
      expiresAt: baseTime + 5 * 60_000,
    });

    const root = createRoot(container);
    await act(async () => {
      root.render(<WorldEmanation variant="compact" />);
    });
    expect(container.textContent || '').toContain('Emanating: Japan · 528 Hz');
  });

  it('handles diffuse universal broadcasts ("all beings") without crashing', async () => {
    const baseTime = Date.now();

    useBroadcastStore.getState().push({
      target: 'all beings',
      frequency_hz: 432,
      duration_minutes: 10,
      receivedAt: baseTime,
      expiresAt: baseTime + 10 * 60_000,
    });

    const root = createRoot(container);
    await act(async () => {
      root.render(<WorldEmanation variant="full" />);
    });
    expect(container.textContent || '').toContain('Emanating: all beings · 432 Hz');
  });

  it('fetches world-context disasters and displays need-sites badge in compact mode', async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/operator/world-context')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              disasters: [
                { title: 'Quake M7.0', location: 'Philippines', severity: 'critical', lat: 14.2, lon: 121.1 },
                { title: 'Flood Alert', location: 'Vietnam', severity: 'high', lat: 16.0, lon: 108.0 },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    try {
      const root = createRoot(container);
      await act(async () => {
        root.render(<WorldEmanation variant="compact" />);
      });
      await act(async () => {
        await Promise.resolve();
      });

      expect(container.querySelector('[data-testid="crisis-need-sites-badge"]')).not.toBeNull();
      expect(container.textContent || '').toContain('2 need-sites');
    } finally {
      global.fetch = originalFetch;
    }
  });
});
