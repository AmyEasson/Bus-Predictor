import { useEffect, useState } from 'react';
import { Polygon, Tooltip, Marker, useMap } from 'react-leaflet';
import L from 'leaflet';
import { BAND_COLOUR } from '../services/delayApi';

const esc = (s) => String(s).replace(/[<>&"]/g, '');

function eventIcon(e) {
  const label = esc(e.name) + (e.time_label ? ` · ${esc(e.time_label)}` : '');
  return L.divIcon({ className: 'event-icon', html: `<span class="event-pin">${label}</span>`, iconSize: [0, 0] });
}

// Every band gets the same treatment, so colour alone carries the meaning. A light fill keeps the
// streets readable underneath; an outline in the same colour keeps each cell's colour easy to tell apart.
const style = (band, hovered) => ({
  fillColor: BAND_COLOUR[band],
  fillOpacity: hovered ? 0.6 : 0.3,
  color: hovered ? '#1f2328' : BAND_COLOUR[band],
  weight: hovered ? 2 : 1,
  opacity: hovered ? 1 : 0.55,
});

// Reports zoom and the visible area (padded, rounded so small pans don't refetch) to the parent.
function useViewReporter(onViewChange) {
  const map = useMap();
  useEffect(() => {
    if (!onViewChange) return undefined;
    const report = () => {
      const b = map.getBounds().pad(0.5);
      const r = (v) => v.toFixed(2);
      onViewChange({
        zoom: map.getZoom(),
        bbox: `${r(b.getSouth())},${r(b.getWest())},${r(b.getNorth())},${r(b.getEast())}`,
      });
    };
    report();
    map.on('moveend', report);
    return () => { map.off('moveend', report); };
  }, [map, onViewChange]);
}

const fmtLines = (lines) => {
  const l = lines ? lines.split(',') : [];
  return l.length > 8 ? `${l.slice(0, 8).join(', ')} +${l.length - 8} more` : l.join(', ');
};

// Drawn inside <MapContainer>: hexagons coloured by typical delay, plus today's event pins.
export function DelayLayer({ data, onViewChange }) {
  const [hoverId, setHoverId] = useState(null);
  useViewReporter(onViewChange);
  if (!data) return null;

  return (
    <>
      {(data.hexes ?? []).map((h) => (
        <Polygon
          key={h.id}
          positions={h.path}
          pathOptions={style(h.band, h.id === hoverId)}
          eventHandlers={{
            mouseover: (e) => { setHoverId(h.id); e.target.bringToFront(); },
            mouseout: () => setHoverId((cur) => (cur === h.id ? null : cur)),
          }}
        >
          <Tooltip sticky>
            <b>+{h.delay_minutes.toFixed(1)} min</b> behind timetable
            <br />Worst: {h.worst_stretch} (+{Math.round(h.worst_stretch_minutes)} min)
            {h.lines && <><br />Lines {fmtLines(h.lines)}</>}
            <br /><span style={{ opacity: 0.7 }}>{h.observations.toLocaleString()} bus passes</span>
          </Tooltip>
        </Polygon>
      ))}
      {data.conditions.events.map((e) => (
        <Marker key={e.id} position={[e.lat, e.lon]} icon={eventIcon(e)} interactive={false} />
      ))}
    </>
  );
}
