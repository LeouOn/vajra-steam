/**
 * CelestialSkyDome.tsx — Real-time topocentric night sky dome visualizer.
 *
 * Renders the visible sky above the practitioner's location:
 * - Zenith-centered horizon projection (0° to 90° altitude)
 * - Real-time planetary positions with sacred glyphs & colors
 * - Sacred Vedic fixed stars and Nakshatras (Sirius, Vega, Arcturus, etc.)
 * - Moon phase, illumination, and Local Sidereal Time (LST)
 */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Card, Tag, Button, Space, Switch, Tooltip, Spin, Badge } from 'antd';
import { Compass, Sparkles, Moon, Sun, Eye, RefreshCw } from 'lucide-react';
import { apiUrl } from '../../utils/api';
import { DEFAULT_LAT, DEFAULT_LNG } from '../../lib/geo';

interface ObserverInfo {
  latitude: number;
  longitude: number;
  local_sidereal_time_deg: number;
  local_sidereal_time_hms: string;
}

interface MoonData {
  altitude: number;
  azimuth: number;
  phase_name: string;
  illumination: number;
  visible: boolean;
  sign: string;
}

interface PlanetData {
  id: string;
  name: string;
  glyph: string;
  altitude: number;
  azimuth: number;
  right_ascension: number;
  declination: number;
  longitude_ecliptic: number;
  sign: string;
  sign_glyph: string;
  sign_degree: number;
  visible: boolean;
  color: string;
  esoteric_quality: string;
}

interface StarData {
  id: string;
  name: string;
  sanskrit: string;
  altitude: number;
  azimuth: number;
  magnitude: number;
  visible: boolean;
  color: string;
  nakshatra: string;
  quality: string;
  zenith_distance: number;
}

interface NightSkyPayload {
  timestamp_utc: string;
  observer: ObserverInfo;
  moon: MoonData;
  planets: PlanetData[];
  visible_planets_count: number;
  sacred_stars: StarData[];
  visible_stars_count: number;
}

interface Props {
  latitude?: number;
  longitude?: number;
  className?: string;
}

export default function CelestialSkyDome({
  latitude = DEFAULT_LAT,
  longitude = DEFAULT_LNG,
  className = '',
}: Props): React.ReactElement {
  const [data, setData] = useState<NightSkyPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [showStars, setShowStars] = useState<boolean>(true);
  const [showPlanets, setShowPlanets] = useState<boolean>(true);
  const [hoveredObject, setHoveredObject] = useState<{
    name: string;
    sub: string;
    alt: number;
    az: number;
    extra: string;
    x: number;
    y: number;
  } | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const fetchSky = async () => {
    setLoading(true);
    try {
      const res = await fetch(apiUrl(`/astrology/night-sky?latitude=${latitude}&longitude=${longitude}`));
      if (res.ok) {
        const json = (await res.json()) as NightSkyPayload;
        setData(json);
      }
    } catch {
      /* best effort fallback */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSky();
    const interval = setInterval(fetchSky, 60000);
    return () => clearInterval(interval);
  }, [latitude, longitude]);

  // Canvas drawing loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId = 0;

    const render = (time: number) => {
      const dpr = window.devicePixelRatio || 1;
      const size = Math.min(canvas.clientWidth || 500, canvas.clientHeight || 500);
      if (canvas.width !== size * dpr || canvas.height !== size * dpr) {
        canvas.width = size * dpr;
        canvas.height = size * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);

      const cx = size / 2;
      const cy = size / 2;
      const radius = size * 0.42;

      // Dark celestial background circle
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
      grad.addColorStop(0, '#0f172a');
      grad.addColorStop(0.7, '#090d16');
      grad.addColorStop(1, '#020617');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fill();

      // Concentric Altitude Rings (30°, 60°)
      [30, 60].forEach((deg) => {
        const r = ((90 - deg) / 90) * radius;
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.12)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();

        ctx.fillStyle = 'rgba(148, 163, 184, 0.35)';
        ctx.font = '9px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`${deg}°`, cx, cy - r + 11);
      });
      ctx.setLineDash([]);

      // Horizon Circle
      ctx.strokeStyle = 'rgba(139, 92, 246, 0.4)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.stroke();

      // Cardinal Labels (N at Top, E at Left, S at Bottom, W at Right)
      const cardinals = [
        { label: 'N', az: 0 },
        { label: 'E', az: 90 },
        { label: 'S', az: 180 },
        { label: 'W', az: 270 },
      ];
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      cardinals.forEach(({ label, az }) => {
        const radAz = (az * Math.PI) / 180;
        const lx = cx - (radius + 14) * Math.sin(radAz);
        const ly = cy - (radius + 14) * Math.cos(radAz);
        ctx.fillStyle = label === 'N' ? '#a78bfa' : 'rgba(226, 232, 240, 0.6)';
        ctx.fillText(label, lx, ly);
      });

      // Zenith crosshair
      ctx.strokeStyle = 'rgba(139, 92, 246, 0.3)';
      ctx.beginPath();
      ctx.moveTo(cx - 5, cy);
      ctx.lineTo(cx + 5, cy);
      ctx.moveTo(cx, cy - 5);
      ctx.lineTo(cx, cy + 5);
      ctx.stroke();

      // Helper to project Alt/Az to canvas (x, y)
      const project = (alt: number, az: number): [number, number] => {
        const r = ((90 - Math.max(0, alt)) / 90) * radius;
        const radAz = (az * Math.PI) / 180;
        const px = cx - r * Math.sin(radAz);
        const py = cy - r * Math.cos(radAz);
        return [px, py];
      };

      // Draw Sacred Stars
      if (showStars && data.sacred_stars) {
        data.sacred_stars.forEach((s, idx) => {
          if (!s.visible) return;
          const [sx, sy] = project(s.altitude, s.azimuth);
          const twinkle = 0.8 + 0.2 * Math.sin(time * 0.003 + idx * 1.5);
          const dotSize = Math.max(2, 4.5 - s.magnitude * 0.8);

          // Star glow
          ctx.beginPath();
          ctx.arc(sx, sy, dotSize * 2, 0, Math.PI * 2);
          ctx.fillStyle = s.color;
          ctx.globalAlpha = 0.15 * twinkle;
          ctx.fill();

          // Star core
          ctx.beginPath();
          ctx.arc(sx, sy, dotSize, 0, Math.PI * 2);
          ctx.fillStyle = s.color;
          ctx.globalAlpha = twinkle;
          ctx.fill();
          ctx.globalAlpha = 1.0;

          // Star label
          ctx.font = '9px sans-serif';
          ctx.textAlign = 'left';
          ctx.fillStyle = 'rgba(226, 232, 240, 0.7)';
          ctx.fillText(s.name.split(' ')[0], sx + 6, sy - 2);
        });
      }

      // Draw Planets
      if (showPlanets && data.planets) {
        data.planets.forEach((p) => {
          if (!p.visible) return;
          const [px, py] = project(p.altitude, p.azimuth);

          // Planet glow aura
          ctx.beginPath();
          ctx.arc(px, py, 11, 0, Math.PI * 2);
          ctx.fillStyle = p.color;
          ctx.globalAlpha = 0.2;
          ctx.fill();

          // Planet glyph circle
          ctx.beginPath();
          ctx.arc(px, py, 7.5, 0, Math.PI * 2);
          ctx.fillStyle = '#0f172a';
          ctx.globalAlpha = 0.85;
          ctx.fill();
          ctx.strokeStyle = p.color;
          ctx.lineWidth = 1.5;
          ctx.stroke();

          // Glyph character
          ctx.globalAlpha = 1.0;
          ctx.fillStyle = p.color;
          ctx.font = '11px sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(p.glyph, px, py);

          // Name & Sign tag
          ctx.font = '9px sans-serif';
          ctx.textAlign = 'left';
          ctx.fillStyle = p.color;
          ctx.fillText(`${p.name} ${p.sign_glyph}`, px + 10, py - 4);
        });
      }

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animId);
  }, [data, showStars, showPlanets]);

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const size = Math.min(canvas.clientWidth || 500, canvas.clientHeight || 500);
    const cx = size / 2;
    const cy = size / 2;
    const radius = size * 0.42;

    const project = (alt: number, az: number): [number, number] => {
      const r = ((90 - Math.max(0, alt)) / 90) * radius;
      const radAz = (az * Math.PI) / 180;
      return [cx - r * Math.sin(radAz), cy - r * Math.cos(radAz)];
    };

    // Check planets first
    for (const p of data.planets) {
      if (!p.visible) continue;
      const [px, py] = project(p.altitude, p.azimuth);
      if (Math.hypot(mx - px, my - py) < 14) {
        setHoveredObject({
          name: `${p.name} ${p.glyph} in ${p.sign} ${p.sign_glyph}`,
          sub: `Alt: ${p.altitude}° · Az: ${p.azimuth}°`,
          alt: p.altitude,
          az: p.azimuth,
          extra: p.esoteric_quality,
          x: mx,
          y: my,
        });
        return;
      }
    }

    // Check stars
    for (const s of data.sacred_stars) {
      if (!s.visible) continue;
      const [sx, sy] = project(s.altitude, s.azimuth);
      if (Math.hypot(mx - sx, my - sy) < 12) {
        setHoveredObject({
          name: `${s.name}`,
          sub: `${s.nakshatra} · Alt: ${s.altitude}° · Az: ${s.azimuth}°`,
          alt: s.altitude,
          az: s.azimuth,
          extra: s.quality,
          x: mx,
          y: my,
        });
        return;
      }
    }

    setHoveredObject(null);
  };

  return (
    <Card
      data-testid="celestial-sky-dome-card"
      className={`border border-purple-500/20 bg-slate-950/60 backdrop-blur-md rounded-2xl ${className}`}
      title={
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Compass className="w-5 h-5 text-purple-400" />
            <span className="text-purple-200 font-serif text-lg tracking-wide">
              Celestial Night-Sky Dome
            </span>
            <Tag color="purple">Horizon Alt/Az</Tag>
          </div>
          {data && (
            <div className="flex items-center gap-3 text-xs text-slate-400 font-mono">
              <span>LST: {data.observer.local_sidereal_time_hms}</span>
              <span className="flex items-center gap-1 text-amber-300">
                <Moon className="w-3.5 h-3.5" />
                {data.moon.phase_name} ({data.moon.illumination}%)
              </span>
            </div>
          )}
        </div>
      }
      extra={
        <Space orientation="horizontal" size="small">
          <Button
            size="small"
            icon={<RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />}
            onClick={fetchSky}
          >
            Refresh
          </Button>
        </Space>
      }
    >
      <div className="flex flex-col lg:flex-row gap-6 items-center">
        {/* Sky Dome Canvas */}
        <div className="relative w-full max-w-[440px] aspect-square flex items-center justify-center">
          <canvas
            ref={canvasRef}
            data-testid="celestial-sky-dome-canvas"
            className="w-full h-full cursor-crosshair rounded-full"
            onMouseMove={handleMouseMove}
            onMouseLeave={() => setHoveredObject(null)}
          />

          {/* Interactive Hover Tooltip */}
          {hoveredObject && (
            <div
              className="pointer-events-none absolute z-20 max-w-[260px] rounded-lg border border-purple-500/30 bg-slate-900/90 p-2.5 shadow-xl text-xs text-slate-200"
              style={{ left: Math.min(hoveredObject.x + 10, 260), top: Math.max(hoveredObject.y - 45, 10) }}
            >
              <div className="font-semibold text-purple-300">{hoveredObject.name}</div>
              <div className="text-slate-400 font-mono text-[11px]">{hoveredObject.sub}</div>
              <div className="text-amber-200/90 text-[10px] mt-1 border-t border-slate-700/60 pt-1">
                {hoveredObject.extra}
              </div>
            </div>
          )}
        </div>

        {/* Telemetry & Legend Panel */}
        <div className="flex-1 w-full space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <span className="text-xs uppercase tracking-wider text-slate-400 font-medium">
              Overhead Visibility
            </span>
            <div className="flex items-center gap-4 text-xs">
              <label className="flex items-center gap-1.5 cursor-pointer text-slate-300">
                <Switch size="small" checked={showPlanets} onChange={setShowPlanets} />
                <span>Planets ({data?.visible_planets_count || 0})</span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer text-slate-300">
                <Switch size="small" checked={showStars} onChange={setShowStars} />
                <span>Vedic Stars ({data?.visible_stars_count || 0})</span>
              </label>
            </div>
          </div>

          {/* Active Visible Planets Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {data?.planets
              .filter((p) => p.visible)
              .map((p) => (
                <div
                  key={p.id}
                  className="rounded-lg border border-slate-800 bg-slate-900/50 p-2 text-xs flex flex-col justify-between"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium" style={{ color: p.color }}>
                      {p.name} {p.glyph}
                    </span>
                    <Tag color="default" className="text-[10px] m-0">
                      Alt {p.altitude}°
                    </Tag>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-1">
                    {p.sign} {p.sign_glyph} · Az {p.azimuth}°
                  </div>
                </div>
              ))}
          </div>

          {/* Sacred Stars & Nakshatras */}
          <div>
            <div className="text-xs text-slate-400 mb-2 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-amber-400" />
              <span>Visible Vedic Nakshatras Overhead:</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {data?.sacred_stars
                .filter((s) => s.visible)
                .map((s) => (
                  <Tooltip key={s.id} title={`${s.quality} (Azimuth: ${s.azimuth}°, Alt: ${s.altitude}°)`}>
                    <Tag
                      color="purple"
                      className="cursor-help py-0.5 px-2 text-xs border border-purple-500/30"
                      style={{ borderColor: s.color }}
                    >
                      <span className="font-semibold" style={{ color: s.color }}>
                        {s.name.split(' ')[0]}
                      </span>{' '}
                      <span className="opacity-75 font-mono text-[10px]">+{s.altitude}°</span>
                    </Tag>
                  </Tooltip>
                ))}
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
