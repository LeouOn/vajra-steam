/**
 * Astrology Panel — Western, Vedic, and Chinese astrology display.
 * Handles saved natal charts, transit analysis, synastry comparison, and backup exports.
 */
import React, { useState, useEffect, useRef, Suspense, lazy } from 'react';
import {
  Compass, Moon, Sun, Shield, Sparkles, RefreshCw, Calendar, MapPin, Clock, User, Heart, Info, ArrowRight, Download, Upload, Copy
} from 'lucide-react';
import { Card, Row, Col, Tag, Button, Space, Segmented, Switch } from 'antd';
import { audioFeedback } from '../../utils/audioFeedback';
import { apiUrl } from '../../utils/api';
import { useAudioStore } from '../../stores/audioStore';
import { useUIStore } from '../../stores/uiStore';
import VedicPanchanga from './VedicPanchanga';
import ChineseBaZi from './ChineseBaZi';

// Always-visible sub-components — imported eagerly
import SavedChartsDrawer from './SavedChartsDrawer';
import NatalCalculator from './NatalCalculator';
import NatalChartWheel from './NatalChartWheel';
import ErrorBoundary from './ErrorBoundary';

// Tabbed sub-components — lazy-loaded to reduce initial bundle
const TransitComparison = lazy(() => import('./TransitComparison'));
const SynastryViewer = lazy(() => import('./SynastryViewer'));

// 3D mandala — lazy-loaded (Three.js ~600 kB isolated into separate chunk)
const LazySacredMandala = lazy(() => import('./LazySacredMandala'));
const AspectChart = lazy(() => import('../2D/AspectChart'));

// Extraction panel — lazy-loaded
const LazyAstrologyExtractionPanel = lazy(() => import('./AstrologyExtractionPanel'));
const AuspiciousTimingWheel = lazy(() => import('./AuspiciousTimingWheel'));
const CelestialSkyDome = lazy(() => import('./CelestialSkyDome'));

// Fallback skeleton for lazy components
const LazyFallback = () => (
  <div className="bg-gray-900/60 rounded-xl border border-white/5 p-8 text-center text-xs text-gray-500 italic animate-pulse">
    Loading component…
  </div>
);

const getOrdinalSuffix = (num) => {
  if (!num) return '';
  const s = ["th", "st", "nd", "rd"];
  const v = num % 100;
  return s[(v - 20) % 10] || s[v] || s[0];
};

// Mini Solar System Orrery — CSS-only animated planet positions
const PLANET_RINGS = [
  { name: 'Mercury', radius: 28, color: '#b0b0b0', size: 3 },
  { name: 'Venus', radius: 44, color: '#f472b6', size: 4 },
  { name: 'Earth', radius: 60, color: '#22d3ee', size: 4 },
  { name: 'Mars', radius: 78, color: '#ef4444', size: 3.5 },
  { name: 'Jupiter', radius: 104, color: '#c084fc', size: 7 },
  { name: 'Saturn', radius: 130, color: '#fb923c', size: 6 },
];

function MiniOrrery({ positions }) {
  if (!positions) return null;
  return (
    <div className="relative" style={{ width: 280, height: 280 }}>
      {/* Sun center */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-gradient-to-br from-yellow-300 to-orange-500 shadow-[0_0_30px_rgba(251,191,36,0.5)] z-10" />
      
      {PLANET_RINGS.map((ring) => {
        const pos = positions?.[ring.name.toLowerCase()];
        const absLon = pos?.longitude || 0;
        const retrograde = pos?.retrograde || false;
        const angleRad = (absLon - 90) * (Math.PI / 180);
        const cx = 140;
        const cy = 140;
        const px = cx + ring.radius * Math.cos(angleRad);
        const py = cy + ring.radius * Math.sin(angleRad);
        
        return (
          <React.Fragment key={ring.name}>
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/5"
              style={{ width: ring.radius * 2, height: ring.radius * 2 }} />
            <div className="absolute rounded-full transition-all duration-1000"
              style={{
                width: ring.size + (retrograde ? 1 : 0), height: ring.size + (retrograde ? 1 : 0),
                backgroundColor: ring.color,
                left: px - ring.size/2, top: py - ring.size/2,
                boxShadow: `0 0 ${ring.size*2}px ${ring.color}80`,
                opacity: retrograde ? 0.6 : 1,
              }} />
            <span className="absolute text-[7px] font-mono"
              style={{ left: px + ring.size + 2, top: py - 4, color: retrograde ? '#fca5a5' : '#6b7280' }}>
              {ring.name}{retrograde ? ' ℞' : ''}
            </span>
          </React.Fragment>
        );
      })}
    </div>
  );
}

export default function AstrologyPanel() {
  const { isPlaying, frequency } = useAudioStore();
  const addToast = useUIStore((s) => s.addToast);
  const [loading, setLoading] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState('');
  const [liveData, setLiveData] = useState(null);
  const [customData, setCustomData] = useState(null);
  const [isLiveMode, setIsLiveMode] = useState(true);
  const [activeSystem, setActiveSystem] = useState('all'); // all, western, vedic, chinese

  // Database-backed state
  const [charts, setCharts] = useState([]);
  const [activeChart, setActiveChart] = useState(null);
  const [transitChart, setTransitChart] = useState(null);
  const [subjectA, setSubjectA] = useState(null);
  const [subjectB, setSubjectB] = useState(null);
  const [editingChart, setEditingChart] = useState(null);
  
  // Navigation tabs: 'wheel' (Consolidated Charts), 'transits' (Transit aspect comparison), 'synastry' (Synastry matching)
  const [activeTab, setActiveTab] = useState('wheel');

  // Privacy toggle for LLM-export paths — defaults ON so personal info is
  // stripped unless the user explicitly opts in to sharing it.
  const [stripPii, setStripPii] = useState<boolean>(true);
  const [saka, setSaka] = useState<{
    saka_dawa_duchen?: string;
    days_until_duchen?: number | null;
    is_saka_dawa?: boolean;
  } | null>(null);
  const [sealingHour, setSealingHour] = useState(false);

  // Geolocation guard — stop retrying after user blocks permission
  const geoBlocked = useRef(false);

  // Load saved charts from database
  const fetchSavedCharts = async () => {
    try {
      const response = await fetch(apiUrl('/astrology/charts'));
      if (response.ok) {
        const data = await response.json();
        setCharts(data);
      }
    } catch (e) {
      console.error("Error fetching saved charts:", e);
    }
  };

  const fetchLiveAstrology = async () => {
    if (!isLiveMode) return;
    const doFetch = async (lat, lon) => {
      try {
        const d = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        const localTime = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        
        const params = new URLSearchParams();
        params.append('datetime_str', localTime);
        if (lat !== null && lon !== null) {
          params.append('latitude', lat.toString());
          params.append('longitude', lon.toString());
        }
        
        const response = await fetch(apiUrl(`/astrology/current?${params.toString()}`));
        if (response.ok) {
          const result = await response.json();
          setLiveData(result.astrology);
        }
      } catch (e) {
        console.error("Error in live astrology fetch:", e);
      }
    };

    if (navigator.geolocation && !geoBlocked.current) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          doFetch(position.coords.latitude, position.coords.longitude);
        },
        (err) => {
          // PERMISSION_DENIED = user blocked — stop retrying to avoid console spam
          if (err.code === 1) geoBlocked.current = true;
          doFetch(null, null);
        },
        { timeout: 5000 }
      );
    } else {
      doFetch(null, null);
    }
  };

  // Poll for live transits and fetch saved charts on mount
  useEffect(() => {
    fetchSavedCharts();
    fetchLiveAstrology();
    fetch(apiUrl('/operator/saka-dawa'))
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (data) setSaka(data); })
      .catch(() => {});
    const interval = setInterval(() => {
      if (isLiveMode) fetchLiveAstrology();
    }, 20000);
    return () => clearInterval(interval);
  }, [isLiveMode]);

  useEffect(() => {
    if (charts.length > 0 && !activeChart && !isLiveMode) {
      setActiveChart(charts[0]);
      setTransitChart(charts[0]);
    }
  }, [charts, activeChart, isLiveMode]);

  // Helper: extract error detail from a failed fetch response
  const _readError = async (response) => {
    try {
      const body = await response.json();
      return body.detail || body.message || `HTTP ${response.status}`;
    } catch {
      return `HTTP ${response.status}: ${response.statusText}`;
    }
  };

  // Helper: compute and display a chart from raw birth data (city + time)
  const _computeTemporaryChart = async (birthTimeIso, cityName) => {
    // Resolve coordinates via geocode
    const geoResponse = await fetch(apiUrl('/astrology/geocode'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ city_name: cityName })
    });
    if (!geoResponse.ok) {
      const err = await _readError(geoResponse);
      throw new Error(`Could not geocode "${cityName}": ${err}`);
    }
    const geo = await geoResponse.json();

    // Hit /current with resolved coordinates
    const params = new URLSearchParams({
      datetime_str: birthTimeIso,
      latitude: geo.latitude.toString(),
      longitude: geo.longitude.toString()
    }).toString();
    const response = await fetch(apiUrl(`/astrology/current?${params}`));
    if (!response.ok) {
      const err = await _readError(response);
      throw new Error(`Chart calculation failed: ${err}`);
    }
    const result = await response.json();
    return result.astrology;
  };

  // Handle calculator submission
  const handleCalculateSubmit = async (values) => {
    setLoading(true);
    setLoadingStatus('Geocoding city…');
    audioFeedback.playTelemetry();
    try {
      const shouldSave = values.saveToDb || !!editingChart;
      const birthTimeIso = values.birth_time_iso;
      const cityName = values.city;

      if (shouldSave) {
        // Strip internal fields before sending to server
        const payload = {
          name: values.name,
          birth_time_iso: birthTimeIso,
          city: cityName,
          description: values.description || '',
          tags: values.tags || '',
          notes: values.notes || '',
        };

        let savedChart = null;
        if (editingChart) {
          setLoadingStatus('Updating saved profile…');
          const response = await fetch(apiUrl(`/astrology/charts/${editingChart.id}`), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          if (response.ok) {
            savedChart = await response.json();
            addToast({ type: 'success', title: 'Natal profile updated successfully', duration: 3 });
            setEditingChart(null);
          } else {
            const err = await _readError(response);
            addToast({ type: 'error', title: `Update failed: ${err}`, duration: 5 });
            // Fall through to compute temporary chart anyway
          }
        } else {
          setLoadingStatus('Saving to database…');
          const response = await fetch(apiUrl('/astrology/charts'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          if (response.ok) {
            savedChart = await response.json();
            addToast({ type: 'success', title: 'Natal profile saved successfully', duration: 3 });
          } else {
            const err = await _readError(response);
            addToast({ type: 'warning', title: `Could not save: ${err}. Showing temporary chart instead.`, duration: 4 });
            // Fall through to compute temporary chart
          }
        }

        // Reload saved charts list and display the chart
        if (savedChart) {
          fetchSavedCharts();
          loadNatalChart(savedChart);
        } else {
          // Save failed — fall back to temporary display
          setLoadingStatus('Computing chart positions…');
          const astroData = await _computeTemporaryChart(birthTimeIso, cityName);
          setCustomData(astroData);
          setIsLiveMode(false);
          setActiveChart(null);
        }
      } else {
        // Temporary calculation only (no save)
        setLoadingStatus('Computing chart positions…');
        const astroData = await _computeTemporaryChart(birthTimeIso, cityName);
        setCustomData(astroData);
        setIsLiveMode(false);
        setActiveChart(null);
        addToast({ type: 'info', title: 'Temporary chart computed successfully', duration: 3 });
        audioFeedback.playSuccess();
      }
    } catch (err) {
      console.error(err);
      addToast({ type: 'error', title: err.message || 'Error processing request', duration: 5 });
      audioFeedback.playError();
    } finally {
      setLoading(false);
      setLoadingStatus('');
    }
  };

  const loadNatalChart = (chart) => {
    if (chart && chart.cached_chart_data) {
      try {
        const parsed = JSON.parse(chart.cached_chart_data);
        setCustomData(parsed);
        setIsLiveMode(false);
        setActiveChart(chart);
        setActiveTab('wheel'); // Toggle back to consolidated wheel view
      } catch (e) {
        console.error("Error parsing cached chart data, falling back to recalculation", e);
        recalculateChart(chart.id);
      }
    } else {
      recalculateChart(chart.id);
    }
  };

  const recalculateChart = async (id) => {
    setLoading(true);
    try {
      const response = await fetch(apiUrl(`/astrology/charts/${id}/recalculate`), {
        method: 'POST'
      });
      if (response.ok) {
        const result = await response.json();
        setCustomData(result.cached_chart_data);
        setIsLiveMode(false);
        const matched = charts.find(c => c.id === id);
        if (matched) setActiveChart(matched);
        fetchSavedCharts();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteChart = async (id) => {
    try {
      const response = await fetch(apiUrl(`/astrology/charts/${id}`), {
        method: 'DELETE'
      });
      if (response.ok) {
        addToast({ type: 'success', title: 'Profile deleted successfully', duration: 3 });
        if (activeChart?.id === id) {
          handleResetToLive();
        }
        fetchSavedCharts();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleExportCharts = async () => {
    try {
      const response = await fetch(apiUrl('/astrology/charts/export'));
      if (response.ok) {
        const data = await response.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `vajra_astrology_profiles_backup.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        addToast({ type: 'success', title: 'Backup downloaded successfully', duration: 3 });
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleImportCharts = async (jsonData) => {
    try {
      const response = await fetch(apiUrl('/astrology/charts/import'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(jsonData)
      });
      if (response.ok) {
        const result = await response.json();
        addToast({ type: 'success', title: `Successfully imported ${result.imported} profiles`, duration: 3 });
        fetchSavedCharts();
      } else {
        addToast({ type: 'error', title: 'Failed to import profiles', duration: 5 });
      }
    } catch (e) {
      console.error(e);
      addToast({ type: 'error', title: 'Import failed', duration: 5 });
    }
  };

  const handleCopyForLLM = async () => {
    // Live mode: copy current day/location astrology (no saved chart needed)
    if (isLiveMode) {
      if (!liveData) {
        addToast({ type: 'error', title: 'Live data not yet loaded — wait for it to fetch', duration: 5 });
        return;
      }
      try {
        const { formatLiveAstrologyMarkdown } = await import('../../lib/astrologyExport');
        const markdown = formatLiveAstrologyMarkdown(liveData, { pii: stripPii });
        await navigator.clipboard.writeText(markdown);
        addToast({
          type: 'success',
          title: stripPii ? 'Current astrology copied (PII stripped) for LLM' : 'Current astrology copied for LLM',
          duration: 3,
        });
      } catch (e) {
        console.error(e);
        addToast({ type: 'error', title: 'Live astrology copy failed: ' + e.message, duration: 5 });
      }
      return;
    }
    // Natal mode: copy saved chart's natal data
    if (!activeChart?.id) {
      addToast({ type: 'error', title: 'Load a saved chart first to copy its natal data', duration: 5 });
      return;
    }
    try {
      const response = await fetch(
        apiUrl(`/astrology/charts/${activeChart.id}/natal-export`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ strip_pii: stripPii }),
        },
      );
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const result = await response.json();
      const data = result.data || result;
      const { formatNatalChartMarkdown } = await import('../../lib/astrologyExport');
      const markdown = formatNatalChartMarkdown(data, { pii: stripPii });
      await navigator.clipboard.writeText(markdown);
      addToast({
        type: 'success',
        title: stripPii ? 'Natal chart copied (PII stripped) for LLM' : 'Natal chart copied for LLM',
        duration: 3,
      });
    } catch (e) {
      console.error(e);
      addToast({ type: 'error', title: 'Natal chart copy failed: ' + e.message, duration: 5 });
    }
  };

  const handleBeginWorkingFromHour = async () => {
    const sky = isLiveMode ? liveData : customData;
    const hour = sky?.planetary_hours?.current_planetary_hour;
    const moon = sky?.moon_phase?.phase_name;
    const chartName = isLiveMode ? 'live sky' : (activeChart?.name || 'natal');
    const intention = isLiveMode
      ? `Working in the ${hour || 'present'} hour under a ${moon || 'changing'} moon`
      : `Working from ${chartName}'s chart in the ${hour || 'present'} hour`;
    setSealingHour(true);
    audioFeedback.playTelemetry();
    try {
      const res = await fetch(apiUrl('/operator/working'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intention,
          target: 'all beings',
          broadcast: true,
          source: 'cosmic-clock',
          chart_name: chartName,
          planetary_hour: hour || undefined,
          moon_phase: moon || undefined,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const folio = await res.json();
      addToast({
        type: 'success',
        title: `Working sealed ${folio.working_id || ''}`,
        message: 'See Workings for the folio, charge, and manifestation image.',
        duration: 5,
      });
      audioFeedback.playSuccess();
    } catch (e) {
      addToast({ type: 'error', title: 'Could not seal working from this hour', duration: 5 });
      audioFeedback.playError();
    } finally {
      setSealingHour(false);
    }
  };

  const handleResetToLive = () => {
    setIsLiveMode(true);
    setActiveChart(null);
    audioFeedback.playClick();
    fetchLiveAstrology();
  };

  const activeData = isLiveMode ? liveData : customData;

  const countWuXing = () => {
    const counts = { Wood: 0, Fire: 0, Earth: 0, Metal: 0, Water: 0 };
    if (!activeData?.chinese?.bazi) return counts;
    
    const charMap = {
      '木': 'Wood', '火': 'Fire', '土': 'Earth', '金': 'Metal', '水': 'Water'
    };
    
    Object.values(activeData.chinese.bazi).forEach(val => {
      const match = val.match(/\(([^)]+)\)/);
      if (match && match[1]) {
        const elementsStr = match[1];
        for (let char of elementsStr) {
          const engName = charMap[char];
          if (engName) counts[engName]++;
        }
      }
    });
    
    return counts;
  };

  const wuXingCounts = countWuXing();

  return (
    <div className="flex-1 h-full overflow-y-auto p-4 md:p-6 bg-transparent space-y-6">
      
      {/* Top Banner Header */}
      <div className="bg-gradient-to-r from-indigo-900/30 via-purple-900/30 to-cyan-900/30 rounded-xl p-5 border border-purple-500/20 relative overflow-hidden">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAiIGhlaWdodD0iNDAiIHZpZXdCb3g9IjAgMCA0MCA0MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48Y2lyY2xlIGN4PSIyMCIgY3k9IjIwIiByPSIxIiBmaWxsPSJyZ2JhKDE2OCw4NSwyNDcsMC4xKSIvPjwvc3ZnPg==')] opacity-30" />
        <div className="relative flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="relative">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center shadow-[0_0_20px_rgba(34,211,238,0.3)]">
                <Compass className="w-5 h-5 text-white animate-spin" style={{ animationDuration: '12s' }} />
              </div>
              <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-500 rounded-full animate-pulse" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white tracking-wide">Cosmic Clockwork</h2>
              <p className="text-xs text-gray-400">Tropical · Sidereal · BaZi — Swiss Ephemeris v2.10</p>
              {saka?.saka_dawa_duchen && (
                <p className="text-[11px] text-amber-300/80 mt-1" data-testid="cosmic-clock-saka">
                  Next Saka Dawa Duchen {saka.saka_dawa_duchen}
                  {saka.days_until_duchen != null ? ` · ${saka.days_until_duchen} days` : ''}
                  {saka.is_saka_dawa ? ' · holy month' : ''}
                </p>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            {['all','western','vedic','chinese'].map(sys => (
              <Button
                key={sys}
                size="small"
                shape="round"
                type={activeSystem === sys ? 'primary' : 'default'}
                onClick={() => setActiveSystem(sys)}
                style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}
              >
                {sys}
              </Button>
            ))}
            <Button
              size="small"
              shape="round"
              type={isLiveMode ? 'primary' : 'default'}
              danger={isLiveMode}
              onClick={handleResetToLive}
              style={{ fontSize: 10, fontWeight: 700 }}
              className={isLiveMode ? 'animate-pulse' : ''}
            >
              🔴 LIVE
            </Button>
            <Button
              size="small"
              type="primary"
              loading={sealingHour}
              onClick={handleBeginWorkingFromHour}
              style={{ fontSize: 10 }}
              data-testid="begin-working-from-hour"
            >
              Begin working from this hour
            </Button>
            <Button
              size="small"
              icon={<Copy />}
              onClick={handleCopyForLLM}
              className="text-[10px]"
              style={{
                background: 'linear-gradient(135deg, #f59e0b, #d97706)',
                border: 'none',
                color: '#fff',
              }}
            >
              Copy for LLM
            </Button>
            <span
              className="inline-flex items-center gap-1.5 text-[10px] font-mono text-slate-300 select-none"
              title="When ON, personal info (name, birth time, exact location) is stripped before copying."
            >
              <span aria-hidden>🔒</span>
              <Switch
                size="small"
                checked={stripPii}
                onChange={(v) => { setStripPii(v); audioFeedback.playClick(); }}
              />
              <span>Strip personal data</span>
            </span>
            <Button
              size="small"
              shape="circle"
              type="text"
              onClick={() => isLiveMode ? fetchLiveAstrology() : (activeChart ? loadNatalChart(activeChart) : fetchLiveAstrology())}
              icon={<RefreshCw className={loading ? 'animate-spin' : ''} />}
            />
          </div>
        </div>
      </div>

      <div className="flex flex-col xl:flex-row gap-6 items-start">
        {/* Left Side: Saved Database profiles panel */}
        <div className="w-full xl:w-[320px] flex-shrink-0">
          <SavedChartsDrawer
            charts={charts}
            onLoadNatal={loadNatalChart}
            onSelectTransit={(c) => { setTransitChart(c); setActiveTab('transits'); audioFeedback.playSuccess(); }}
            onSetSubjectA={setSubjectA}
            onSetSubjectB={setSubjectB}
            onEdit={setEditingChart}
            onDelete={handleDeleteChart}
            onExport={handleExportCharts}
            onImport={handleImportCharts}
            subjectA={subjectA}
            subjectB={subjectB}
            activeChartId={activeChart?.id}
          />
        </div>

        {/* Right Side: Main display container */}
        <div className="flex-1 w-full space-y-6">
          {/* Main Navigation tabs */}
          <div className="flex justify-start">
            <Segmented
              options={[
                { value: 'wheel', label: 'Celestial Positions' },
                { value: 'dome', label: 'Night-Sky Dome' },
                { value: 'timing', label: 'Auspicious Timing' },
                { value: 'transits', label: 'Transit-to-Natal' },
                { value: 'synastry', label: 'Synastry (Compatibility)' },
                { value: 'extraction', label: 'Extraction' }
              ]}
              value={activeTab}
              onChange={(val) => { audioFeedback.playTabChange(); setActiveTab(val); }}
              className="bg-black/40 border border-white/5 p-1 text-xs"
            />
          </div>

          {activeTab === 'wheel' && (
            <Space orientation="vertical" size={24} style={{ width: '100%' }}>
              {/* Form Input + Overview Card */}
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={10}>
                  <NatalCalculator
                    onSubmit={handleCalculateSubmit}
                    loading={loading}
                    loadingStatus={loadingStatus}
                    editingChart={editingChart}
                    onCancelEdit={() => setEditingChart(null)}
                  />
                </Col>
                
                <Col xs={24} lg={14}>
                  <Card className="bg-gray-900/80 border-purple-500/20" styles={{ body: { padding: '20px' } }}>
                    <Row justify="space-between" align="top" style={{ marginBottom: 16 }}>
                      <Col>
                        <Tag color="purple" className="font-mono text-[9px]">
                          {isLiveMode ? 'ACTIVE SYSTEM TRANSIT' : `NATAL PROJECTIONS: ${activeChart ? activeChart.name : 'CUSTOM'}`}
                        </Tag>
                      </Col>
                      <Col>
                        <Space size={8} align="center">
                          <span className="text-[10px] text-gray-500 font-mono">COORD: GEOCENTRIC</span>
                        </Space>
                      </Col>
                    </Row>
                    
                    <h3 className="text-xl font-bold text-white tracking-wide font-mono mb-1">
                      {isLiveMode ? '🪐 LIVE CELESTIAL CLOCKWORK' : `🔮 NATAL DETAILS: ${activeChart ? activeChart.name : 'CUSTOM'}`}
                    </h3>
                    <p className="text-xs text-gray-400 font-mono mb-4">
                      Date & Time: {activeData ? new Date(activeData.datetime).toLocaleString() : 'Loading...'}
                    </p>
                    
                    <Row gutter={[12, 12]}>
                      <Col xs={12} sm={6}>
                        <Card size="small" className="bg-gray-800/60 border-white/5" styles={{ body: { padding: '10px' } }}>
                          <span className="text-[9px] text-gray-500 font-mono block">PLANETARY HOUR</span>
                          <span className="text-sm font-bold text-yellow-400 block mt-1">
                            {activeData?.planetary_hours?.current_planetary_hour || '—'}
                          </span>
                        </Card>
                      </Col>
                      <Col xs={12} sm={6}>
                        <Card size="small" className="bg-gray-800/60 border-white/5" styles={{ body: { padding: '10px' } }}>
                          <span className="text-[9px] text-gray-500 font-mono block">VEDIC TITHI</span>
                          <span className="text-sm font-bold text-purple-400 block mt-1">
                            {activeData?.indian?.panchanga?.tithi?.name || '—'}
                          </span>
                        </Card>
                      </Col>
                      <Col xs={12} sm={6}>
                        <Card size="small" className="bg-gray-800/60 border-white/5" styles={{ body: { padding: '10px' } }}>
                          <span className="text-[9px] text-gray-500 font-mono block">BAZI YEAR PILLAR</span>
                          <span className="text-sm font-bold text-emerald-400 block mt-1">
                            {activeData?.chinese?.bazi?.year?.split(' ')[0] || '—'}
                          </span>
                        </Card>
                      </Col>
                      <Col xs={12} sm={6}>
                        <Card size="small" className="bg-gray-800/60 border-white/5" styles={{ body: { padding: '10px' } }}>
                          <span className="text-[9px] text-gray-500 font-mono block">MOON ILLUMINATION</span>
                          <span className="text-sm font-bold text-cyan-400 block mt-1">
                            {activeData?.moon_phase?.illumination != null
                              ? `${((activeData.moon_phase.illumination <= 1 ? activeData.moon_phase.illumination * 100 : activeData.moon_phase.illumination)).toFixed(1)}%`
                              : '—'}
                          </span>
                        </Card>
                      </Col>
                    </Row>
                    
                    {activeChart && activeChart.notes && (
                      <div className="mt-4 p-3 bg-white/3 border border-white/5 rounded-xl">
                        <span className="text-[9px] text-gray-500 font-mono block uppercase font-bold">Notes</span>
                        <p className="text-xs text-gray-400 mb-0 mt-0.5">{activeChart.notes}</p>
                      </div>
                    )}
                  </Card>
                </Col>
              </Row>

              {activeData ? (
                <div className="space-y-6">
                  {/* Western astrology layout */}
                  {(activeSystem === 'all' || activeSystem === 'western') && (
                    <Card
                      title={<span className="text-cyan-400 font-mono text-xs tracking-wider uppercase"><Sun className="w-4 h-4 inline mr-2" />I. Western Tropical Astrology (Transit Wheel)</span>}
                      extra={<Tag color="purple" className="font-mono text-[9px]">TROPICAL / PLACIDUS HOUSES</Tag>}
                      className="bg-gray-900/80 border-purple-500/20"
                      styles={{ body: { padding: '20px' } }}
                    >
                      <Row gutter={[16, 16]}>
                        <Col xs={24} md={8}>
                          <Card size="small" className="bg-purple-950/20 border-purple-500/20" styles={{ body: { padding: '12px' } }}>
                            <span className="text-[8px] font-mono text-amber-400 block">SUN SIGN</span>
                            <div className="text-base font-bold text-white mt-1">{activeData.western?.positions?.sun?.sign || 'Unknown'}</div>
                            <span className="text-[10px] text-gray-400 font-mono">{activeData.western?.positions?.sun?.degree?.toFixed(2)}° · H{activeData.western?.positions?.sun?.house || '?'}</span>
                          </Card>
                        </Col>
                        <Col xs={24} md={8}>
                          <Card size="small" className="bg-purple-950/20 border-purple-500/20" styles={{ body: { padding: '12px' } }}>
                            <span className="text-[8px] font-mono text-blue-300 block">MOON SIGN</span>
                            <div className="text-base font-bold text-white mt-1">{activeData.western?.positions?.moon?.sign || 'Unknown'}</div>
                            <span className="text-[10px] text-gray-400 font-mono">{activeData.western?.positions?.moon?.degree?.toFixed(2)}° · H{activeData.western?.positions?.moon?.house || '?'}</span>
                          </Card>
                        </Col>
                        <Col xs={24} md={8}>
                          <Card size="small" className="bg-purple-950/20 border-purple-500/20" styles={{ body: { padding: '12px' } }}>
                            <span className="text-[8px] font-mono text-cyan-400 block">ASCENDANT</span>
                            <div className="text-base font-bold text-white mt-1">{activeData.western?.positions?.ascendant?.sign || 'Unknown'}</div>
                            <span className="text-[10px] text-gray-400 font-mono">{activeData.western?.positions?.ascendant?.degree?.toFixed(2)}° · H1 Cusp</span>
                          </Card>
                        </Col>
                      </Row>

                      <Row gutter={[16, 16]} style={{ marginTop: 20 }}>
                        <Col xs={24} xl={8}>
                          <div className="flex flex-col items-center justify-center p-4 bg-black/55 border border-white/5 rounded-xl min-h-[350px]">
                            <WesternChartWheel positions={activeData.western?.positions} aspects={activeData.western?.aspects} />
                          </div>
                        </Col>
                        <Col xs={24} xl={8}>
                          <div className="space-y-4 font-mono">
                            <h4 className="text-[10px] font-bold text-gray-400 font-mono tracking-widest uppercase mb-0">PLANETARY COORDINATES</h4>
                            <div className="grid grid-cols-1 gap-1.5 max-h-[300px] overflow-y-auto pr-1">
                              {Object.entries(activeData.western?.positions || {}).map(([planet, pos]) => {
                                const isRetrograde = pos?.retrograde;
                                return (
                                  <div key={planet} className="flex items-center justify-between px-2.5 py-2 bg-white/3 hover:bg-white/8 rounded-md text-[11px] border border-white/5">
                                    <Space size={8}>
                                      <span className="font-semibold capitalize text-slate-300">{planet.replace('_',' ')}</span>
                                      {isRetrograde && <Tag color="red" className="text-[8px] leading-none">℞</Tag>}
                                    </Space>
                                    <Space size={4}>
                                      <span className="text-slate-200">{pos.formatted}</span>
                                      {pos.house && <Tag className="text-[8px] font-mono" color="purple">H{pos.house}</Tag>}
                                    </Space>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        </Col>
                        <Col xs={24} xl={8}>
                          <div className="space-y-4 font-mono">
                            <h4 className="text-[10px] font-bold text-gray-400 font-mono tracking-widest uppercase">ELEMENTS & ACTIVE ASPECTS</h4>
                            <div className="grid grid-cols-4 gap-2 text-center text-xs bg-black/45 p-3 rounded-xl border border-white/5">
                              {Object.entries(activeData.western?.elements || {}).map(([elem, weight]) => {
                                let color = 'text-gray-400';
                                if (elem === 'Fire') color = 'text-rose-400';
                                else if (elem === 'Earth') color = 'text-amber-400';
                                else if (elem === 'Air') color = 'text-sky-400';
                                else if (elem === 'Water') color = 'text-emerald-400';
                                return (
                                  <div key={elem}>
                                    <span className="text-[9px] text-gray-500 font-mono block leading-none">{elem.toUpperCase()}</span>
                                    <span className={`font-bold mt-1.5 block ${color}`}>{weight} pts</span>
                                  </div>
                                );
                              })}
                            </div>
                            <div className="bg-black/45 border border-white/5 rounded-xl p-3 max-h-[195px] overflow-y-auto space-y-2">
                              <span className="text-[9px] text-gray-500 font-mono block mb-1">ACTIVE CONFLUX ASPECTS</span>
                              {activeData.western?.aspects && activeData.western.aspects.length > 0 ? (
                                activeData.western.aspects.map((asp, idx) => (
                                  <div key={idx} className="flex justify-between items-center text-[10px] p-2 bg-white/5 border border-white/5 rounded-lg">
                                    <span className="font-medium text-gray-300">{asp.description}</span>
                                    <Tag color={asp.aspect === 'Conjunction' || asp.aspect === 'Trine' || asp.aspect === 'Sextile' ? 'blue' : 'red'} className="font-mono text-[8px]">
                                      {asp.aspect}
                                    </Tag>
                                  </div>
                                ))
                              ) : (
                                <div className="text-xs text-gray-500 italic py-2 text-center">No active aspects in orb</div>
                              )}
                            </div>
                          </div>
                        </Col>
                      </Row>

                      {activeData?.planetary_positions && (
                        <div style={{ marginTop: 20 }}>
                          <Suspense fallback={<div className="text-center text-xs text-gray-500 py-8">Loading aspect chart…</div>}>
                            <AspectChart positions={activeData.planetary_positions} size={400} />
                          </Suspense>
                        </div>
                      )}
                    </Card>
                  )}

                  {/* Vedic Astrology layout */}
                  {(activeSystem === 'all' || activeSystem === 'vedic') && (
                    <VedicPanchanga indianData={activeData.indian} />
                  )}

                  {/* 3D Sacred Mandala planetary visualizer (lazy-loaded) */}
                  {(activeSystem === 'all' || activeSystem === 'western') && (
                    <Card
                      title={<span className="text-purple-400 font-mono text-xs tracking-wider uppercase">🌀 Sacred Mandala — Planetary Resonance Field</span>}
                      className="bg-gray-900/80 border-purple-500/20"
                      styles={{ body: { padding: '0', height: 'min(60vh, 480px)' } }}
                    >
                      <ErrorBoundary fallbackTitle="3D mandala failed to load">
                        <Suspense fallback={
                          <div className="flex items-center justify-center h-full text-xs text-gray-500 italic animate-pulse">
                            Loading 3D mandala…
                          </div>
                        }>
                          <LazySacredMandala isPlaying={isPlaying} frequency={frequency} />
                        </Suspense>
                      </ErrorBoundary>
                    </Card>
                  )}

                  {/* Chinese Astrology layout */}
                  {(activeSystem === 'all' || activeSystem === 'chinese') && (
                    <ChineseBaZi chineseData={activeData.chinese} />
                  )}
                </div>
              ) : (
                <div className="bg-gray-900/60 p-8 border border-white/5 rounded-xl text-center italic text-gray-400 font-mono text-xs">
                  Computing ephemeris coordinates from planetary databases...
                </div>
              )}
            </Space>
          )}

          {activeTab === 'dome' && (
            <div key="dome" className="animate-slide-up">
              <ErrorBoundary fallbackTitle="Celestial night-sky dome failed to load">
                <Suspense fallback={<LazyFallback />}>
                  <CelestialSkyDome />
                </Suspense>
              </ErrorBoundary>
            </div>
          )}

          {activeTab === 'timing' && (
            <div key="timing" className="animate-slide-up">
              <ErrorBoundary fallbackTitle="Auspicious timing wheel failed to load">
                <Suspense fallback={<LazyFallback />}>
                  <AuspiciousTimingWheel />
                </Suspense>
              </ErrorBoundary>
            </div>
          )}

          {activeTab === 'transits' && (
            <div key="transits" className="animate-slide-up">
              <ErrorBoundary fallbackTitle="Transit comparison failed to load">
                <Suspense fallback={<LazyFallback />}>
                  <TransitComparison chart={transitChart || activeChart} />
                </Suspense>
              </ErrorBoundary>
            </div>
          )}

          {activeTab === 'synastry' && (
            <div key="synastry" className="animate-slide-up">
              <ErrorBoundary fallbackTitle="Synastry viewer failed to load">
                <Suspense fallback={<LazyFallback />}>
                  <SynastryViewer 
                    charts={charts} 
                    subjectA={subjectA} 
                    subjectB={subjectB} 
                    onSetSubjectA={setSubjectA} 
                    onSetSubjectB={setSubjectB} 
                  />
                </Suspense>
              </ErrorBoundary>
            </div>
          )}

          {activeTab === 'extraction' && (
            <div key="extraction" className="animate-slide-up">
              <Suspense fallback={<LazyFallback />}>
                <LazyAstrologyExtractionPanel />
              </Suspense>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const ASPECT_TYPES = [
  { name: 'Conjunction', angle: 0, orb: 8, color: 'rgba(34,197,94,0.5)' },
  { name: 'Opposition', angle: 180, orb: 8, color: 'rgba(249,115,22,0.5)', dash: '4,4' },
  { name: 'Trine', angle: 120, orb: 8, color: 'rgba(59,130,246,0.5)' },
  { name: 'Square', angle: 90, orb: 8, color: 'rgba(239,68,68,0.5)' },
  { name: 'Sextile', angle: 60, orb: 6, color: 'rgba(168,85,247,0.5)', dash: '2,2' },
];

function calcAspects(positions) {
  const names = Object.keys(positions).filter(n => n !== 'ascendant' && n !== 'midheaven');
  const out = [];
  for (let i = 0; i < names.length; i++) {
    for (let j = i + 1; j < names.length; j++) {
      let diff = Math.abs(positions[names[i]].longitude - positions[names[j]].longitude) % 360;
      if (diff > 180) diff = 360 - diff;
      for (const at of ASPECT_TYPES) {
        const orb = Math.abs(diff - at.angle);
        if (orb <= at.orb) {
          out.push({ planet1: names[i], planet2: names[j], aspect: at.name, exactness: 1 - orb / at.orb, color: at.color, dash: at.dash || 'none' });
          break;
        }
      }
    }
  }
  return out;
}

// Western Astrology Wheel Drawing Helper
const WesternChartWheel = ({ positions, aspects: serverAspects }) => {
  if (!positions) return <div className="w-60 h-60 rounded-full border border-dashed border-gray-700 animate-pulse flex items-center justify-center text-xs text-gray-600">No positions calculated</div>;

  const aspects = serverAspects?.length ? serverAspects.map(a => ({
    planet1: a.planet1, planet2: a.planet2, aspect: a.aspect, exactness: a.exactness || 0.5,
    color: ASPECT_TYPES.find(t => t.name === a.aspect)?.color || 'rgba(255,255,255,0.15)',
    dash: ASPECT_TYPES.find(t => t.name === a.aspect)?.dash || 'none',
  })).filter(a => a.planet1 && a.planet2) : calcAspects(positions);

  const cx = 160;
  const cy = 160;
  const r = 130;
  const midR = 105;
  const innerR = 85;

  const ascLon = positions.ascendant?.longitude || 0;

  const getCoordinates = (lon, radius) => {
    const rad = ((lon - ascLon - 180) * Math.PI) / 180;
    const x = cx + radius * Math.cos(rad);
    const y = cy + radius * Math.sin(rad);
    return { x, y };
  };

  const planetCoords = {};
  Object.entries(positions).forEach(([planet, info]) => {
    if (planet !== 'ascendant' && planet !== 'midheaven') {
      planetCoords[planet] = getCoordinates(info.longitude, innerR - 8);
    }
  });

  const signGlyphs = ['♈', '♉', '♊', '♋', '♌', '♍', '♎', '♏', '♐', '♑', '♒', '♓'];
  const planetGlyphs = {
    sun: '☉', moon: '☽', mercury: '☿', venus: '♀', mars: '♂',
    jupiter: '♃', saturn: '♄', uranus: '♅', neptune: '♆', pluto: '♇',
    north_node: '☊',
  };

  return (
    <svg
      viewBox="0 0 320 320"
      width="100%"
      style={{ maxWidth: 320 }}
      className="select-none font-mono"
    >
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="3" />
      <circle cx={cx} cy={cy} r={midR} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="1.5" />
      <circle cx={cx} cy={cy} r={innerR} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="1" />

      {/* Spokes */}
      {Array.from({ length: 12 }).map((_, idx) => {
        const deg = idx * 30;
        const pInner = getCoordinates(deg, midR);
        const pOuter = getCoordinates(deg, r);
        return (
          <line key={idx} x1={pInner.x} y1={pInner.y} x2={pOuter.x} y2={pOuter.y} stroke="rgba(255,255,255,0.15)" strokeWidth="1" />
        );
      })}

      {/* Signs glyphs */}
      {Array.from({ length: 12 }).map((_, idx) => {
        const deg = idx * 30 + 15;
        const pGlyph = getCoordinates(deg, (midR + r) / 2);
        const colors = ['#f87171', '#fbbf24', '#60a5fa', '#34d399'];
        const color = colors[idx % 4];
        return (
          <text key={idx} x={pGlyph.x} y={pGlyph.y + 4} textAnchor="middle" fontSize="13px" fill={color} fontWeight="bold" className="font-sans">
            {signGlyphs[idx]}
          </text>
        );
      })}

      {/* Aspects lines */}
      {aspects.map((asp, idx) => {
        const coord1 = planetCoords[asp.planet1];
        const coord2 = planetCoords[asp.planet2];
        if (!coord1 || !coord2) return null;

        return (
          <line key={idx} x1={coord1.x} y1={coord1.y} x2={coord2.x} y2={coord2.y} stroke={asp.color} strokeWidth={1 + (asp.exactness || 0.5) * 1.5} strokeDasharray={asp.dash || 'none'} />
        );
      })}

      {/* ASC / DSC / MC / IC lines */}
      {(() => {
        const ascP = getCoordinates(ascLon, r);
        const dscLon = ascLon + 180;
        const dscP = getCoordinates(dscLon, r);
        const mcLon = positions.midheaven?.longitude || (ascLon + 270);
        const mcP = getCoordinates(mcLon, r);
        const icLon = mcLon + 180;
        const icP = getCoordinates(icLon, r);
        return (
          <>
            <line x1={ascP.x} y1={ascP.y} x2={dscP.x} y2={dscP.y} stroke="rgba(253,224,71,0.3)" strokeWidth="1" strokeDasharray="6,3" />
            <line x1={mcP.x} y1={mcP.y} x2={icP.x} y2={icP.y} stroke="rgba(253,224,71,0.2)" strokeWidth="1" strokeDasharray="6,3" />
            <text x={ascP.x - 14} y={ascP.y + 3} fontSize="9" fill="rgba(253,224,71,0.6)" fontWeight="bold">ASC</text>
            <text x={dscP.x + 4} y={dscP.y + 3} fontSize="9" fill="rgba(253,224,71,0.4)" fontWeight="bold">DSC</text>
            <text x={mcP.x - 6} y={mcP.y - 6} fontSize="9" fill="rgba(253,224,71,0.4)" fontWeight="bold">MC</text>
          </>
        );
      })()}

      {/* Planet nodes */}
      {Object.entries(positions).map(([planet, info]) => {
        if (planet === 'ascendant' || planet === 'midheaven') return null;
        const coord = planetCoords[planet];
        if (!coord) return null;

        const glyph = planetGlyphs[planet] || planet.substring(0, 2).toUpperCase();

        let color = '#a855f7';
        if (planet === 'sun') color = '#fbbf24';
        else if (planet === 'moon') color = '#e2e8f0';
        else if (planet === 'mercury') color = '#38bdf8';
        else if (planet === 'venus') color = '#f472b6';
        else if (planet === 'mars') color = '#f87171';
        else if (planet === 'jupiter') color = '#c084fc';
        else if (planet === 'saturn') color = '#fb923c';
        else if (planet === 'uranus') color = '#2dd4bf';
        else if (planet === 'neptune') color = '#818cf8';
        else if (planet === 'pluto') color = '#94a3b8';
        else if (planet === 'north_node') color = '#34d399';

        return (
          <g key={planet} className="group">
            <circle cx={coord.x} cy={coord.y} r="8" fill="rgba(0, 0, 0, 0.7)" stroke={color} strokeWidth="1.2" className="cursor-help hover:scale-125 transition-transform duration-300" />
            <text x={coord.x} y={coord.y + 3.5} textAnchor="middle" fontSize="9px" fill={color} fontWeight="bold" className="pointer-events-none select-none font-sans">
              {glyph}
            </text>
            <title>{planet.toUpperCase()}: {info.formatted}</title>
          </g>
        );
      })}

      {/* Axes */}
      <line x1={cx - r - 12} y1={cy} x2={cx + r + 12} y2={cy} stroke="rgba(6,182,212,0.4)" strokeWidth="1.5" strokeDasharray="3,3" />
      {positions.midheaven && (() => {
        const pMc = getCoordinates(positions.midheaven.longitude, r + 12);
        const pIc = getCoordinates((positions.midheaven.longitude + 180) % 360, r + 12);
        return (
          <line x1={pMc.x} y1={pMc.y} x2={pIc.x} y2={pIc.y} stroke="rgba(6,182,212,0.4)" strokeWidth="1.5" strokeDasharray="3,3" />
        );
      })()}

      <text x={cx - r - 20} y={cy + 4} fill="rgb(6,182,212)" fontSize="8px" fontWeight="bold" textAnchor="middle">ASC</text>
      <text x={cx + r + 20} y={cy + 4} fill="rgb(6,182,212)" fontSize="8px" fontWeight="bold" textAnchor="middle">DSC</text>
      {positions.midheaven && (() => {
        const mcLabelCoord = getCoordinates(positions.midheaven.longitude, r + 18);
        return (
          <text x={mcLabelCoord.x} y={mcLabelCoord.y + 3} fill="rgb(6,182,212)" fontSize="8px" fontWeight="bold" textAnchor="middle">MC</text>
        );
      })()}
    </svg>
  );
};
