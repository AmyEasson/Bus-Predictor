import { Polyline, Tooltip, Marker } from 'react-leaflet';
import L from 'leaflet';
import { BAND_COLOUR } from '../services/delayApi';
 
const esc = (s) => String(s).replace(/[<>&"]/g, '');
 
function eventIcon(e) {
  const label = esc(e.name) + (e.time_label ? ` · ${esc(e.time_label)}` : '');
  return L.divIcon({ className: 'event-icon', html: `<span class="event-pin">${label}</span>`, iconSize: [0, 0] });
}
 
// Drawn inside <MapContainer>: coloured road stretches plus event pins.
export function DelayLayer({ data }) {
  if (!data) return null;
  const segments = [...data.segments].sort((a, b) => a.delay_minutes - b.delay_minutes); // worst drawn last
  return (
    <>
      {segments.map((s) => (
        <Polyline key={s.id} positions={s.path} pathOptions={{ color: BAND_COLOUR[s.band], weight: 7, opacity: 0.95, lineCap: 'round' }}>
          <Tooltip sticky>{s.name}: +{Math.round(s.delay_minutes)} min</Tooltip>
        </Polyline>
      ))}
      {data.conditions.events.map((e) => (
        <Marker key={e.id} position={[e.lat, e.lon]} icon={eventIcon(e)} interactive={false} />
      ))}
    </>
  );
}
