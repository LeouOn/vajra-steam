const memStore = new Map();
const localStoragePolyfill = {
  getItem: (k) => (memStore.has(k) ? memStore.get(k) : null),
  setItem: (k, v) => memStore.set(k, String(v)),
  removeItem: (k) => memStore.delete(k),
  clear: () => memStore.clear(),
  key: (i) => Array.from(memStore.keys())[i] || null,
  get length() { return memStore.size; },
};
try { globalThis.localStorage = localStoragePolyfill; } catch {}
try { global.localStorage = localStoragePolyfill; } catch {}

// Mock AudioContext for jsdom/happy-dom — the audioFeedback module and
// audioStore both try to create an AudioContext on import. Without this
// mock, tests that transitively import those modules log "Web Audio API
// not supported in this browser" errors, which can cause test isolation
// flakes when run alongside other test files in the same vitest worker.
const noop = () => {};
const mockParam = { setValueAtTime: noop, exponentialRampToValueAtTime: noop, linearRampToValueAtTime: noop, value: 0 };
const mockNode = {
  connect: noop, disconnect: noop, start: noop, stop: noop,
  frequency: mockParam, gain: mockParam, detune: mockParam, type: '',
  buffer: null, loop: false, playbackRate: mockParam,
};
class MockAudioContext {
  currentTime = 0;
  state = 'running';
  sampleRate = 44100;
  destination = mockNode;
  createOscillator() { return mockNode; }
  createGain() { return mockNode; }
  createBufferSource() { return mockNode; }
  createAnalyser() { return { ...mockNode, getByteFrequencyData: noop, getFloatFrequencyData: noop, frequencyBinCount: 0 }; }
  createBuffer() { return { getChannelData: () => new Float32Array(0), length: 0, numberOfChannels: 1, sampleRate: 44100 }; }
  decodeAudioData() { return Promise.resolve({}); }
  resume() { return Promise.resolve(); }
  close() { return Promise.resolve(); }
}
try {
  globalThis.AudioContext = MockAudioContext;
  (globalThis as Record<string, unknown>).webkitAudioContext = MockAudioContext;
} catch {}

if (typeof HTMLCanvasElement !== 'undefined' && !HTMLCanvasElement.prototype.getContext) {
  (HTMLCanvasElement.prototype as any).getContext = () => null;
}
