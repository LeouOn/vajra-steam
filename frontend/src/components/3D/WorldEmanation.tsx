/**
 * WorldEmanation.tsx — 3D Earth visualization for healing broadcasts and world context.
 *
 * Renders the world answering in real time when a sitting seals:
 * - Concentric ripple rings emanating from the practitioner's origin.
 * - Cyan blessing flight arcs to resolvable geographic targets.
 * - Global aura diffusion when broadcasting to unresolvable/universal targets ("all beings").
 * - Need-glow amber pulses at verified disaster sites (full variant).
 *
 * Backed by `useBroadcastStore` and `/operator/world-context`.
 */
import React, { useRef, useState, useEffect, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Stars } from '@react-three/drei';
import * as THREE from 'three';
import { DEFAULT_LAT, DEFAULT_LNG } from '../../lib/geo';
import { apiUrl } from '../../utils/api';
import { useBroadcastStore, type BroadcastEvent } from '../../stores/broadcastStore';
import {
  resolveTargetCoords,
  latLonToVec3,
  planetToLatLon,
  createArcCurve,
  createEarthTexture,
  toneFromFrequencies,
  PLANET_COLORS,
  ASPECT_COLORS,
} from './worldEmanationHelpers';

interface Disaster {
  location?: string;
  country?: string;
  title?: string;
  severity?: string;
  lat?: number;
  lon?: number;
}

interface PlanetPosition {
  longitude?: number;
  sign?: string;
  retrograde?: boolean;
}

interface Aspect {
  planet1: string;
  planet2: string;
  aspect: string;
  exactness?: number;
}

export interface WorldEmanationProps {
  variant?: 'compact' | 'full';
  practitionerCoords?: [number, number];
  className?: string;
}

// ─── Subcomponents: 3D Scene Primitives ───

const Atmosphere: React.FC<{ isDiffusing?: boolean }> = ({ isDiffusing = false }) => {
  return (
    <mesh>
      <sphereGeometry args={[2.12, 48, 48]} />
      <shaderMaterial
        transparent
        depthWrite={false}
        uniforms={{
          uDiffusing: { value: isDiffusing ? 1.0 : 0.0 },
        }}
        vertexShader={/* glsl */ `
          varying vec3 vNormal;
          varying vec3 vPosition;
          void main() {
            vec4 worldPos = modelMatrix * vec4(position, 1.0);
            vNormal = normalize(mat3(modelMatrix) * normal);
            vPosition = worldPos.xyz;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `}
        fragmentShader={/* glsl */ `
          varying vec3 vNormal;
          varying vec3 vPosition;
          void main() {
            vec3 viewDir = normalize(cameraPosition - vPosition);
            float intensity = pow(0.72 - dot(vNormal, viewDir), 2.8);
            gl_FragColor = vec4(0.14, 0.65, 0.95, intensity * 0.4);
          }
        `}
      />
    </mesh>
  );
};

const GridLines: React.FC = () => {
  const geo = useMemo(() => {
    const pts: THREE.Vector3[] = [];
    const R = 2.02;
    for (let lat = -60; lat <= 60; lat += 30) {
      const phi = (90 - lat) * (Math.PI / 180);
      const r = R * Math.cos(phi);
      const y = R * Math.sin(phi);
      for (let i = 0; i <= 48; i++) {
        const theta = (i / 48) * Math.PI * 2;
        pts.push(new THREE.Vector3(r * Math.cos(theta), y, r * Math.sin(theta)));
      }
    }
    for (let lon = 0; lon < 360; lon += 45) {
      const theta = lon * (Math.PI / 180);
      for (let i = 0; i <= 48; i++) {
        const phi = (i / 48) * Math.PI;
        pts.push(new THREE.Vector3(R * Math.sin(phi) * Math.cos(theta), R * Math.cos(phi), R * Math.sin(phi) * Math.sin(theta)));
      }
    }
    const g = new THREE.BufferGeometry();
    g.setFromPoints(pts);
    return g;
  }, []);

  return (
    <lineSegments geometry={geo}>
      <lineBasicMaterial color="#1e3a5f" transparent opacity={0.22} />
    </lineSegments>
  );
};

// Concentric ripple rings expanding from origin
const PractitionerRipples: React.FC<{ origin: THREE.Vector3; isActive: boolean; tone?: string }> = ({
  origin,
  isActive,
  tone = '#38bdf8',
}) => {
  const groupRef = useRef<THREE.Group>(null);

  useFrame((state) => {
    if (!groupRef.current) return;
    const t = state.clock.elapsedTime;
    groupRef.current.children.forEach((child, i) => {
      if (child instanceof THREE.Mesh) {
        const phase = (t * (isActive ? 1.2 : 0.5) + i * 0.7) % 2.0;
        const scale = 0.5 + phase * 1.5;
        child.scale.setScalar(scale);
        const mat = child.material as THREE.MeshBasicMaterial;
        mat.opacity = Math.max(0, (1 - phase / 2.0) * (isActive ? 0.7 : 0.3));
      }
    });
  });

  return (
    <group ref={groupRef} position={origin}>
      {[0, 1, 2].map((i) => (
        <mesh key={i}>
          <ringGeometry args={[0.04, 0.08, 24]} />
          <meshBasicMaterial color={isActive ? tone : '#e2e8f0'} transparent side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      ))}
      {/* Center origin beacon */}
      <mesh>
        <sphereGeometry args={[0.04, 16, 16]} />
        <meshBasicMaterial color={tone} />
      </mesh>
    </group>
  );
};

// Animated Bezier Blessing Arc
const BlessingFlightArc: React.FC<{ start: THREE.Vector3; end: THREE.Vector3; label: string; tone?: string }> = ({
  start,
  end,
  tone = '#38bdf8',
}) => {
  const curve = useMemo(() => createArcCurve(start, end, 0.35), [start, end]);
  const geo = useMemo(() => {
    const pts = curve.getPoints(50);
    return new THREE.BufferGeometry().setFromPoints(pts);
  }, [curve]);

  const pulseMesh = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (!pulseMesh.current) return;
    const progress = (state.clock.elapsedTime * 0.35) % 1.0;
    const pt = curve.getPoint(progress);
    pulseMesh.current.position.copy(pt);
  });

  return (
    <group>
      <line geometry={geo}>
        <lineBasicMaterial color={tone} transparent opacity={0.65} linewidth={2} depthWrite={false} />
      </line>
      <mesh ref={pulseMesh}>
        <sphereGeometry args={[0.04, 12, 12]} />
        <meshBasicMaterial color={tone} />
      </mesh>
      {/* Target marker */}
      <mesh position={end}>
        <sphereGeometry args={[0.045, 16, 16]} />
        <meshBasicMaterial color={tone} />
      </mesh>
    </group>
  );
};

// Astrological Aspect Chords
const AspectLines: React.FC<{ planetPositions: Record<string, PlanetPosition> | null; aspects: Aspect[] }> = ({ planetPositions, aspects }) => {
  if (!planetPositions || aspects.length === 0) return null;

  return (
    <group>
      {aspects.slice(0, 8).map((asp, i) => {
        const p1 = planetPositions[asp.planet1];
        const p2 = planetPositions[asp.planet2];
        if (!p1 || !p2) return null;
        const [lat1, lon1] = planetToLatLon(p1.longitude || 0);
        const [lat2, lon2] = planetToLatLon(p2.longitude || 0);
        const curve = createArcCurve(latLonToVec3(lat1, lon1), latLonToVec3(lat2, lon2), 0.2);
        const geo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(30));
        return (
          <line key={i} geometry={geo}>
            <lineBasicMaterial color={ASPECT_COLORS[asp.aspect] || '#94a3b8'} transparent opacity={0.3} depthWrite={false} />
          </line>
        );
      })}
    </group>
  );
};

// Disaster Need-Glow Markers
const DisasterMarkers: React.FC<{ disasters: Disaster[] }> = ({ disasters }) => {
  return (
    <group>
      {disasters.map((d, i) => {
        const coords = (d.lat !== undefined && d.lon !== undefined && d.lat !== null && d.lon !== null)
          ? [d.lat, d.lon] as [number, number]
          : resolveTargetCoords(d.location || d.country || d.title);
        if (!coords) return null;
        const pos = latLonToVec3(coords[0], coords[1]);
        return (
          <mesh key={i} position={pos}>
            <sphereGeometry args={[0.05, 12, 12]} />
            <meshBasicMaterial color={d.severity === 'critical' ? '#ef4444' : '#f59e0b'} transparent opacity={0.85} />
          </mesh>
        );
      })}
    </group>
  );
};

// Radiant Compassion Arcs connecting practitioner to active disaster sites
const CompassionCrisisArcs: React.FC<{
  origin: THREE.Vector3;
  disasters: Disaster[];
  isActive?: boolean;
}> = ({ origin, disasters, isActive = true }) => {
  if (!disasters || disasters.length === 0) return null;
  const activeDisasters = disasters.slice(0, 4);

  return (
    <group>
      {activeDisasters.map((d, i) => {
        const coords =
          d.lat !== undefined && d.lon !== undefined && d.lat !== null && d.lon !== null
            ? ([d.lat, d.lon] as [number, number])
            : resolveTargetCoords(d.location || d.country || d.title);
        if (!coords) return null;
        const endVec = latLonToVec3(coords[0], coords[1]);
        const tone = d.severity === 'critical' ? '#f43f5e' : '#fb923c';
        return (
          <BlessingFlightArc
            key={`crisis-arc-${i}`}
            start={origin}
            end={endVec}
            label={d.title || d.location || 'Crisis Focus'}
            tone={isActive ? tone : '#fbbf24'}
          />
        );
      })}
    </group>
  );
};

// ─── Scene Content Inner ───

interface SceneContentProps {
  variant: 'compact' | 'full';
  practitionerCoords: [number, number];
  activeBroadcasts: BroadcastEvent[];
  disasters: Disaster[];
  planetPositions: Record<string, PlanetPosition> | null;
  aspects: Aspect[];
}

const SceneContent: React.FC<SceneContentProps> = ({
  variant,
  practitionerCoords,
  activeBroadcasts,
  disasters,
  planetPositions,
  aspects,
}) => {
  const groupRef = useRef<THREE.Group>(null);
  const earthTex = useMemo(() => createEarthTexture(), []);

  useFrame((_, delta) => {
    if (groupRef.current) {
      groupRef.current.rotation.y += delta * (variant === 'compact' ? 0.05 : 0.03);
    }
  });

  const originVec = useMemo(
    () => latLonToVec3(practitionerCoords[0], practitionerCoords[1]),
    [practitionerCoords],
  );

  const resolvedArcs = useMemo(() => {
    const list: Array<{ start: THREE.Vector3; end: THREE.Vector3; label: string }> = [];
    for (const b of activeBroadcasts) {
      const coords = (b.lat !== undefined && b.lon !== undefined && b.lat !== null && b.lon !== null)
        ? [b.lat, b.lon] as [number, number]
        : resolveTargetCoords(b.location || b.target);
      if (coords) {
        list.push({
          start: originVec,
          end: latLonToVec3(coords[0], coords[1]),
          label: b.target || b.location || 'Resolved Target',
        });
      }
    }
    return list;
  }, [activeBroadcasts, originVec]);

  const hasDiffuseBroadcast = useMemo(() => {
    return activeBroadcasts.some((b) => {
      const hasDirect = b.lat !== undefined && b.lon !== undefined && b.lat !== null && b.lon !== null;
      return !hasDirect && !resolveTargetCoords(b.location || b.target);
    });
  }, [activeBroadcasts]);

  const tone = useMemo(
    () => toneFromFrequencies(activeBroadcasts[0]?.frequencies),
    [activeBroadcasts],
  );

  return (
    <group ref={groupRef}>
      <mesh>
        <sphereGeometry args={[2, 48, 48]} />
        <meshStandardMaterial map={earthTex} roughness={0.7} metalness={0.1} />
      </mesh>

      <GridLines />
      <Atmosphere isDiffusing={hasDiffuseBroadcast} />

      {/* Practitioner concentric ripples */}
      <PractitionerRipples origin={originVec} isActive={activeBroadcasts.length > 0} tone={tone} />

      {/* Flight arcs to resolvable targets */}
      {resolvedArcs.map((arc, i) => (
        <BlessingFlightArc key={i} start={arc.start} end={arc.end} label={arc.label} tone={tone} />
      ))}

      {/* Radiant compassion arcs connecting practitioner to active crisis nodes */}
      <CompassionCrisisArcs
        origin={originVec}
        disasters={variant === 'compact' ? disasters.slice(0, 3) : disasters}
        isActive={activeBroadcasts.length > 0}
      />

      {/* Disaster Markers (rendered in compact as subtle pulses, and in full with markers) */}
      <DisasterMarkers disasters={variant === 'compact' ? disasters.slice(0, 3) : disasters} />
      {variant === 'full' && <AspectLines planetPositions={planetPositions} aspects={aspects} />}
    </group>
  );
};

// ─── Error Boundary / Canvas Guard ───
class CanvasErrorBoundary extends React.Component<{ children: React.ReactNode; fallback: React.ReactNode }, { hasError: boolean }> {
  constructor(props: { children: React.ReactNode; fallback: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

// ─── Main WorldEmanation Component ───

export default function WorldEmanation({
  variant = 'compact',
  practitionerCoords: customCoords,
  className = '',
}: WorldEmanationProps): React.ReactElement {
  const recentBroadcasts = useBroadcastStore((state) => state.recentBroadcasts);
  const [practitionerCoords, setPractitionerCoords] = useState<[number, number]>(
    customCoords || [DEFAULT_LAT, DEFAULT_LNG],
  );

  const [disasters, setDisasters] = useState<Disaster[]>([]);
  const [planetPositions, setPlanetPositions] = useState<Record<string, PlanetPosition> | null>(null);
  const [aspects, setAspects] = useState<Aspect[]>([]);

  // Discover practitioner coordinates if available
  useEffect(() => {
    if (customCoords) return;
    if (typeof navigator !== 'undefined' && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setPractitionerCoords([pos.coords.latitude, pos.coords.longitude]);
        },
        () => {
          /* keep default fallback */
        },
        { timeout: 3000 },
      );
    }
  }, [customCoords]);

  // World-context telemetry fetch (active for both compact and full variants)
  useEffect(() => {
    let mounted = true;
    const fetchTelemetry = async () => {
      try {
        const res = await fetch(apiUrl('/operator/world-context'));
        if (res.ok && mounted) {
          const data = (await res.json()) as { disasters?: Disaster[] };
          setDisasters(data.disasters || []);
        }
      } catch {
        /* best effort */
      }
    };

    const fetchAstro = async () => {
      if (variant !== 'full') return;
      try {
        const res = await fetch(apiUrl(`/astrology/current?latitude=${practitionerCoords[0]}&longitude=${practitionerCoords[1]}`));
        if (res.ok && mounted) {
          const data = (await res.json()) as { astrology?: { western?: { positions?: Record<string, PlanetPosition>; aspects?: Aspect[] } } };
          const western = data.astrology?.western;
          setPlanetPositions(western?.positions || null);
          setAspects(western?.aspects || []);
        }
      } catch {
        /* best effort */
      }
    };

    fetchTelemetry();
    fetchAstro();
    const interval = setInterval(fetchTelemetry, 120000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [variant, practitionerCoords]);

  const activeBroadcasts = useMemo(() => {
    const now = Date.now();
    return recentBroadcasts.filter((b) => b.expiresAt > now);
  }, [recentBroadcasts]);

  const activeTargetSummary = useMemo(() => {
    if (activeBroadcasts.length === 0) return null;
    const first = activeBroadcasts[0];
    const target = first.target || 'the field';
    const hz = first.frequency_hz ? ` · ${first.frequency_hz} Hz` : '';
    return `${target}${hz}`;
  }, [activeBroadcasts]);

  const fallbackView = (
    <div className="w-full h-full flex flex-col items-center justify-center p-4 text-center bg-slate-950/40 rounded-xl border border-sky-900/30 text-sky-300">
      <div className="text-2xl mb-1">🌍</div>
      <div className="text-xs font-semibold">World Emanation</div>
      <div className="text-[10px] text-slate-400 mt-1">
        {activeTargetSummary ? `Broadcasting: ${activeTargetSummary}` : 'Field is calm and receptive'}
      </div>
    </div>
  );

  const containerHeight = variant === 'compact' ? 'h-60' : 'h-96 md:h-[450px]';

  return (
    <div
      data-testid="world-emanation"
      className={`relative w-full ${containerHeight} rounded-xl overflow-hidden bg-gradient-to-b from-slate-950/80 to-sky-950/30 border border-sky-500/20 shadow-inner ${className}`}
    >
      <CanvasErrorBoundary fallback={fallbackView}>
        <Canvas camera={{ position: [0, 0.4, 5.2], fov: 45 }}>
          <ambientLight intensity={0.4} />
          <directionalLight position={[5, 3, 5]} intensity={0.9} />
          <Stars radius={40} depth={20} count={variant === 'compact' ? 600 : 1500} factor={2} fade speed={0.3} />
          <SceneContent
            variant={variant}
            practitionerCoords={practitionerCoords}
            activeBroadcasts={activeBroadcasts}
            disasters={disasters}
            planetPositions={planetPositions}
            aspects={aspects}
          />
          <OrbitControls
            enableZoom={variant === 'full'}
            enablePan={false}
            enableRotate={true}
            minDistance={3.5}
            maxDistance={8}
            autoRotate={true}
            autoRotateSpeed={variant === 'compact' ? 0.4 : 0.2}
          />
        </Canvas>
      </CanvasErrorBoundary>

      {/* Top Banner overlay */}
      <div className="absolute top-2.5 left-3 right-3 flex items-center justify-between pointer-events-none">
        <div className="flex items-center gap-1.5 bg-slate-950/75 backdrop-blur-md px-2.5 py-1 rounded-full border border-sky-500/30 text-[11px] font-mono text-sky-200">
          <span className={`w-2 h-2 rounded-full ${activeBroadcasts.length > 0 ? 'bg-cyan-400 animate-pulse' : 'bg-slate-500'}`} />
          <span>{activeTargetSummary ? `Emanating: ${activeTargetSummary}` : 'Field Receptive'}</span>
        </div>

        <div className="flex gap-2 text-[10px] font-mono">
          {disasters.length > 0 && (
            <span
              data-testid="crisis-need-sites-badge"
              className="bg-slate-950/80 px-2 py-0.5 rounded border border-amber-500/30 text-amber-300"
            >
              {disasters.length} need-sites
            </span>
          )}
          {variant === 'full' && (
            <span className="bg-slate-950/80 px-2 py-0.5 rounded border border-cyan-500/30 text-cyan-300">
              {activeBroadcasts.length} live
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
