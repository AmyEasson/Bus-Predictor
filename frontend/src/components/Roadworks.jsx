import { Marker, Tooltip } from 'react-leaflet';
import L from 'leaflet';

// Colour by the extra delay per bus stretch: big (signals, closures) red, moderate amber, small grey.
export const worksTone = (s) => (s >= 15 ? 'big' : s >= 5 ? 'mid' : 'small');

const icon = (tone, size) => L.divIcon({
  className: 'works-wrap',
  html: `<div class="works-pin ${tone}" style="width:${size}px;height:${size}px"></div>`,
  iconSize: [size, size],
  iconAnchor: [size / 2, size / 2],
});
const ICONS = {};
const iconFor = (tone, size) => (ICONS[`${tone}${size}`] ??= icon(tone, size));

export function WorksTooltip({ w }) {
  return (
    <>
      <b>{w.traffic_management}</b> · {w.street}, {w.town}
      <br />
      {w.status === 'planned' ? 'Planned' : 'In progress'} · {w.start} to {w.end} · {w.category}
      <br />
      {w.effect_s < 1
        ? 'Little effect on buses'
        : `+${Math.round(w.effect_s)} s per bus stretch nearby at this hour`}{' '}
      <span style={{ opacity: 0.7 }}>
        ({w.measured ? `measured from ${w.measured_n} bus passes` : `typical for ${w.traffic_management.toLowerCase()}`})
      </span>
    </>
  );
}

// What the map shows: works in progress that noticeably slow buses (5 s+ per stretch). Planned works and
// small jobs are left off so the map isn't cluttered with things that don't matter to a bus.
export const shownWorks = (works) => (works ?? []).filter((w) => w.status === 'in_progress' && worksTone(w.effect_s) !== 'small');

// Map layer: road works in progress at the selected date/hour, sized and coloured by their effect.
export function RoadworksLayer({ data }) {
  if (!data?.works) return null;
  const works = shownWorks(data.works).sort((a, b) => a.effect_s - b.effect_s); // biggest drawn on top
  return works.map((w) => {
    const tone = worksTone(w.effect_s);
    return (
      <Marker key={w.id} position={[w.lat, w.lon]} icon={iconFor(tone, tone === 'big' ? 14 : tone === 'mid' ? 11 : 8)}>
        <Tooltip><WorksTooltip w={w} /></Tooltip>
      </Marker>
    );
  });
}

// Side card: what the road-works analysis found, and what's on now.
export function RoadworksCard({ data }) {
  if (!data) return null;
  const s = data.summary;
  const max = Math.max(1, ...s.by_type.map((t) => t.extra_s));
  const shown = shownWorks(data.works);
  const counts = shown.reduce((acc, w) => { acc[worksTone(w.effect_s)] += 1; return acc; }, { big: 0, mid: 0, small: 0 });
  const peak = s.peak;
  return (
    <div className="sheet">
      <div className="sheet-head">
        <h2>Road works</h2>
        <div className="muted small">
          {shown.length.toLocaleString()} works in progress that slow buses at {String(data.hour).padStart(2, '0')}:00 on {data.date}
          {' '}({counts.big} major: +15 s or more per stretch)
        </div>
      </div>

      <div className="block">
        <div className="label">Extra delay per bus stretch, by type</div>
        <ul className="bars">
          {s.by_type.slice(0, 6).map((t) => (
            <li key={t.traffic_management}>
              <span>{t.traffic_management}</span>
              <span className="bar-track"><i style={{ width: `${Math.max(2, (t.extra_s / max) * 100)}%` }} /></span>
              <b>+{t.extra_s.toFixed(1)} s</b>
            </li>
          ))}
        </ul>
        <div className="muted small">Compared with the same stretch at the same hour without works.</div>
      </div>

      <div className="block">
        <div className="label">It adds up</div>
        <div className="chips-row">
          {s.concurrent.map((c) => (
            <span key={c.works} className="stat-chip"><b>+{c.extra_s.toFixed(0)} s</b>{c.works} job{c.works === '1' ? '' : 's'} at once</span>
          ))}
        </div>
        {peak && (
          <div className="muted small">
            Worst at {String(peak.hour).padStart(2, '0')}:00 on weekdays (+{peak.penalty_s.toFixed(0)} s per stretch for
            signals and closures). Right now the effect is ×{data.hour_scale} its daily average.
          </div>
        )}
      </div>

      <div className="muted small">
        Showing works in progress with 5 s+ effect. Street Manager permits up to {String(data.permits_until).slice(0, 10)}; hover a marker for details.
      </div>
    </div>
  );
}
