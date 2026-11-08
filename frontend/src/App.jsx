import { useCallback, useEffect, useState } from 'react';
import 'leaflet/dist/leaflet.css';
import './App.css';
import { BusMap } from './components/BusMap';
import { DelayLayer } from './components/DelayLayer';
import { SearchBox } from './components/SearchBox';
import { StopCard } from './components/StopCard';
import { Directions } from './components/Directions';
import { LayersButton, DelayBar, DelayInsightsCard } from './components/DelayControls';
import { RouteOverlay, RouteLegend } from './components/RouteOverlay';
import { expectedDelay } from './components/routeRanking';
import { fetchDelayMap, fetchNetworkSummary } from './services/delayApi';

// Hexagon width (m) for a zoom level: big cells for the whole city, fine ones on the street.
// Must be one of the backend's HEX_SIZES.
function hexSizeFor(zoom) {
  if (zoom <= 10) return 2000;
  if (zoom <= 11) return 1200;
  if (zoom <= 12) return 700;
  if (zoom <= 13) return 400;
  if (zoom <= 14) return 250;
  return 150;
}

// Recent trips, remembered in this browser only.
const RECENT_KEY = 'recentTrips';
const loadRecent = () => {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY)) ?? []; } catch { return []; }
};
const saveRecent = (list) => {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* storage blocked: fine */ }
};

// Flow, like a maps app:
//   explore    search box (+ directions button), typical-now card, recent trips
//   place      a stop was picked: its card, with Directions / Start here
//   directions from/to + time, ranked route cards; picking one shows fast-vs-safe, why, and steps
// The delay hexagons are a map layer from the Layers button; in explore mode they come with a side card.
export default function App() {
  const [mode, setMode] = useState('explore');
  const [place, setPlace] = useState(null);
  const [from, setFrom] = useState(null);
  const [to, setTo] = useState(null);
  const [routes, setRoutes] = useState([]);
  const [selectedJourney, setSelectedJourney] = useState(null);
  const [hoveredStop, setHoveredStop] = useState(null);
  const [focus, setFocus] = useState(null);
  const [recent, setRecent] = useState(loadRecent);

  const [summary, setSummary] = useState(null);

  const [layerOn, setLayerOn] = useState(false);
  const [colourBy, setColourBy] = useState('overall');
  const [factors, setFactors] = useState(['weather', 'time_of_day', 'events']);
  const [hour, setHour] = useState(() => Math.max(6, new Date().getHours()));
  const [dayType, setDayType] = useState(() => ([0, 6].includes(new Date().getDay()) ? 'weekend' : 'weekday'));
  const [mapView, setMapView] = useState({ zoom: 13, bbox: null });
  const [delay, setDelay] = useState(null);
  const [delayErr, setDelayErr] = useState(null);
  const hexM = hexSizeFor(mapView.zoom);
  const bbox = mapView.zoom >= 14 ? mapView.bbox : null; // zoomed in: only what's on screen

  useEffect(() => {
    let stale = false;
    const load = () => fetchNetworkSummary({ hour: new Date().getHours() })
      .then((s) => { if (!stale) setSummary(s); })
      .catch(() => { if (!stale) setSummary(null); });
    load();
    const t = setInterval(load, 10 * 60 * 1000);
    return () => { stale = true; clearInterval(t); };
  }, []);

  useEffect(() => {
    if (!layerOn) return undefined;
    let stale = false;
    fetchDelayMap({ hour, colourBy, factors, dayType, hexM, bbox })
      .then((d) => { if (!stale) { setDelay(d); setDelayErr(null); } })
      .catch((e) => { if (!stale) setDelayErr(e.message); });
    return () => { stale = true; };
  }, [layerOn, hour, colourBy, factors, dayType, hexM, bbox]);

  const toggleFactor = (k) => setFactors((f) => (f.includes(k) ? f.filter((x) => x !== k) : [...f, k]));

  const pickPlace = (stop) => {
    setPlace(stop);
    setFocus(stop);
    setMode(stop ? 'place' : 'explore');
  };
  const openDirections = ({ from: f = null, to: t = null } = {}) => {
    setFrom(f);
    setTo(t);
    setSelectedJourney(null);
    setRoutes([]);
    setMode('directions');
  };
  const closeDirections = () => {
    setSelectedJourney(null);
    setRoutes([]);
    setMode(place ? 'place' : 'explore');
  };
  // remember the trip with its usual delay, for the "Recent" list
  const onSearched = useCallback((f, t, best) => {
    const { minutes } = expectedDelay(best);
    const h = best.departure_time.slice(0, 2);
    const item = { from: f, to: t, usual: minutes, at: `${h}:00` };
    setRecent((list) => {
      const next = [item, ...list.filter((r) => !(r.from.stop_id === f.stop_id && r.to.stop_id === t.stop_id))].slice(0, 5);
      saveRecent(next);
      return next;
    });
  }, []);
  const showDelays = () => setLayerOn(true);
  const focusStretch = (s) => {
    const [a, b] = s.path;
    setFocus({ stop_id: s.id, stop_lat: (a[0] + b[0]) / 2, stop_lon: (a[1] + b[1]) / 2 });
  };

  const inDirections = mode === 'directions';
  const pins = inDirections
    ? [from && { stop: from, kind: 'from' }, to && { stop: to, kind: 'to' }].filter(Boolean)
    : place ? [{ stop: place, kind: 'place' }] : [];

  return (
    <div className="app">
      <BusMap
        hoveredStop={hoveredStop}
        selectedJourney={selectedJourney}
        pins={pins}
        focusStop={inDirections ? null : focus}
        drawRoute={!inDirections}
      >
        {layerOn && <DelayLayer data={delay} onViewChange={setMapView} />}
        {inDirections && <RouteOverlay routes={routes} selected={selectedJourney} />}
      </BusMap>

      {inDirections && <RouteLegend routes={routes} selected={selectedJourney} />}

      <div className="panel">
        {inDirections ? (
          <Directions
            from={from}
            to={to}
            setFrom={(s) => { setFrom(s); setSelectedJourney(null); }}
            setTo={(s) => { setTo(s); setSelectedJourney(null); }}
            onHover={setHoveredStop}
            selected={selectedJourney}
            onSelectJourney={setSelectedJourney}
            onClose={closeDirections}
            onResults={setRoutes}
            onShowDelays={showDelays}
            onSearched={onSearched}
          />
        ) : (
          <>
            <SearchBox
              value={place}
              onSelect={pickPlace}
              onHover={setHoveredStop}
              placeholder="Search bus stops"
              className="main-search"
              leading={<span className="search-icon" aria-hidden>⌕</span>}
              trailing={
                <>
                  {place && <button className="icon-btn" onClick={() => pickPlace(null)} aria-label="Clear">✕</button>}
                  <button className="icon-btn dir-btn" onClick={() => openDirections({ to: place })} aria-label="Directions" title="Directions">➜</button>
                </>
              }
            />

            {mode === 'place' && place ? (
              <StopCard
                stop={place}
                onDirectionsTo={() => openDirections({ to: place })}
                onDirectionsFrom={() => openDirections({ from: place })}
              />
            ) : layerOn ? (
              <DelayInsightsCard
                data={delay}
                colourBy={colourBy}
                setColourBy={setColourBy}
                factors={factors}
                toggleFactor={toggleFactor}
                onFocusStretch={focusStretch}
              />
            ) : (
              <div className="sheet">
                {summary && (
                  <div className="block">
                    <div className="label">Network at this hour ({summary.day_type}s)</div>
                    <div className="stats">
                      <div><b className={summary.pct_on_time >= 70 ? 'g' : summary.pct_on_time >= 55 ? 'a' : 'r'}>{summary.pct_on_time}%</b><span>buses on time</span></div>
                      <div><b className="r">{summary.delayed_over_5min.toLocaleString()}</b><span>over 5 min late</span></div>
                      <div><b className="a">+{summary.avg_delay_minutes} min</b><span>average delay</span></div>
                    </div>
                    <div className="muted small">Typical for this hour, from past bus data. Not live.</div>
                  </div>
                )}
                {recent.length > 0 && (
                  <div className="block">
                    <div className="label">Recent</div>
                    <ul className="recent">
                      {recent.map((r) => (
                        <li key={`${r.from.stop_id}-${r.to.stop_id}`}>
                          <button onClick={() => openDirections({ from: r.from, to: r.to })}>
                            <b>{r.from.stop_name} → {r.to.stop_name}</b>
                            <span className="muted small">
                              {r.usual == null ? 'No delay data' : r.usual < 1 ? `Usually on time at ${r.at}` : `Usually +${Math.round(r.usual)} min at ${r.at}`}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <button className="action primary wide" onClick={() => setLayerOn(true)}>Explore where buses get delayed</button>
              </div>
            )}
          </>
        )}
      </div>

      <LayersButton on={layerOn} onToggle={() => setLayerOn((v) => !v)} data={delay} />

      {layerOn && (
        <DelayBar data={delay} error={delayErr} hour={hour} setHour={setHour} dayType={dayType} setDayType={setDayType} />
      )}
    </div>
  );
}
