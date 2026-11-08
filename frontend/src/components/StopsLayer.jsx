import { useEffect, useState } from 'react';
import { Marker, Popup, Tooltip, useMap } from 'react-leaflet';
import L from 'leaflet';
import { fetchStopsInArea } from '../services/api';

export const STOPS_MIN_ZOOM = 16; // street level: a few hundred stops on screen at most

// A stop dot with a small arrow pointing the way buses leave it (bearing from the timetable).
// Icons are cached per rounded bearing so hundreds of stops reuse a handful of icons.
const ICONS = {};
function stopIcon(bearing, kind) {
  const b = bearing == null ? null : Math.round(bearing / 10) * 10;
  const key = `${b}-${kind}`;
  if (!ICONS[key]) {
    const arrow = b == null ? '' : `<i class="stop-arrow" style="transform: rotate(${b}deg)"></i>`;
    ICONS[key] = L.divIcon({
      className: 'stop-dot-wrap',
      html: `<div class="stop-dot ${kind}">${arrow}<span></span></div>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });
  }
  return ICONS[key];
}

// Every bus stop once you're zoomed in to street level, fetched for the area in view.
//   choicesFor(stop) -> null to act straight away (onPick), or [{label, action}] to ask first in a popup
//   highlight        -> {stop_id: 'place' | 'from' | 'to'} for stops already chosen
export function StopsLayer({ onPick, choicesFor = () => null, highlight = {} }) {
  const map = useMap();
  const [view, setView] = useState({ zoom: map.getZoom(), bbox: null });
  const [stops, setStops] = useState([]);
  const [asking, setAsking] = useState(null); // stop_id whose choice popup is open

  useEffect(() => {
    const update = () => {
      const b = map.getBounds().pad(0.3);
      const r = (v) => v.toFixed(3);
      setView({ zoom: map.getZoom(), bbox: `${r(b.getSouth())},${r(b.getWest())},${r(b.getNorth())},${r(b.getEast())}` });
    };
    update();
    map.on('moveend', update);
    return () => { map.off('moveend', update); };
  }, [map]);

  const show = view.zoom >= STOPS_MIN_ZOOM;
  useEffect(() => {
    if (!show || !view.bbox) return undefined;
    let stale = false;
    fetchStopsInArea(view.bbox)
      .then((s) => { if (!stale) setStops(s); })
      .catch(() => { if (!stale) setStops([]); });
    return () => { stale = true; };
  }, [show, view.bbox]);

  if (!show) return null;
  const askStop = asking ? stops.find((s) => s.stop_id === asking) : null;
  const choices = askStop ? choicesFor(askStop) : null;
  return (
    <>
      {stops.map((s) => {
        const kind = highlight[s.stop_id] ?? 'plain';
        return (
          <Marker
            key={s.stop_id}
            position={[s.stop_lat, s.stop_lon]}
            icon={stopIcon(s.bearing, kind)}
            zIndexOffset={kind === 'plain' ? 0 : 500}
            eventHandlers={{
              click: () => {
                const c = choicesFor(s);
                if (c?.length) setAsking(s.stop_id);
                else onPick(s);
              },
            }}
          >
            {asking !== s.stop_id && (
              <Tooltip direction="top" offset={[0, -8]}>
                <b>{s.stop_name}</b>
                {s.towards && <><br /><span style={{ opacity: 0.75 }}>towards {s.towards}</span></>}
                {s.lines?.length > 0 && <><br />{s.lines.join(' · ')}</>}
              </Tooltip>
            )}
          </Marker>
        );
      })}
      {askStop && choices?.length > 0 && (
        <Popup
          position={[askStop.stop_lat, askStop.stop_lon]}
          offset={[0, -6]}
          closeButton={false}
          autoPan={false}
          eventHandlers={{ remove: () => setAsking(null) }}
        >
          <div className="stop-choice">
            <b>{askStop.stop_name}</b>
            {askStop.towards && <span className="muted small">towards {askStop.towards}</span>}
            {choices.map((c) => (
              <button key={c.label} className="action" onClick={() => { setAsking(null); c.action(); }}>
                {c.label}
              </button>
            ))}
          </div>
        </Popup>
      )}
    </>
  );
}
