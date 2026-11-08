import './DelayPanel.css';
import { BAND_COLOUR, bandOf } from '../services/delayApi';

const TABS = [['overall', 'Overall'], ['weather', 'Weather'], ['time_of_day', 'Time'], ['events', 'Events']];
const tone = (m) => (m < 2 ? 'g' : m < 5 ? 'a' : 'r');
const hh = (h) => String(h).padStart(2, '0');

const DAY_TYPES = [['weekday', 'Weekdays'], ['weekend', 'Weekends']];

export function DelayPanel({ data, error, colourBy, setColourBy, factors, toggleFactor, hour, setHour, dayType, setDayType }) {
  const max = data ? Math.max(1, ...data.hourly.map((h) => h.avg_delay_minutes)) : 1;
  return (
    <>
      <div>
        <h1>What's slowing buses?</h1>
        <p className="sub">Each hexagon shows how far behind timetable buses typically are in that area. Hover for details.</p>
      </div>
      {data?.data_from && (
        <div className="note">
          <div>
            <strong>Typical {data.day_type} pattern, not live</strong>
            From {data.data_days} days of real bus journeys ({data.data_from} to {data.data_to}).
          </div>
        </div>
      )}
      {error && <div className="note warn"><div><strong>Couldn't load the delay map</strong>{error}</div></div>}

      <div className="section">Day</div>
      <div className="seg">
        {DAY_TYPES.map(([id, name]) => (
          <button key={id} className={`seg-btn ${dayType === id ? 'on' : ''}`} onClick={() => setDayType(id)}>{name}</button>
        ))}
      </div>

      <div className="section">Colour by</div>
      <div className="seg">
        {TABS.map(([id, name]) => (
          <button key={id} className={`seg-btn ${colourBy === id ? 'on' : ''}`} onClick={() => setColourBy(id)}>{name}</button>
        ))}
      </div>

      {data && (
        <>
          <div className="section">Delay factors</div>
          {data.factors.map((f) => {
            const on = factors.includes(f.key);
            return (
              <div className="factor" key={f.key}>
                <button role="switch" aria-checked={on} aria-label={`Include ${f.label}`} className={`switch ${on ? 'on' : ''}`} onClick={() => toggleFactor(f.key)} />
                <div className="factor-text"><b>{f.label}</b><span>{f.description}</span></div>
                <span className={`delta ${tone(f.minutes)}`}>+{Math.round(f.minutes)}m</span>
              </div>
            );
          })}

          <div className="section">Hour of day</div>
          <div className="hours">
            {data.hourly.map((h) => (
              <button key={h.hour} className={`hour ${h.hour === hour ? 'sel' : ''}`} onClick={() => setHour(h.hour)} title={`${hh(h.hour)}:00, avg +${h.avg_delay_minutes} min`}>
                <i style={{ height: `${Math.max(14, (h.avg_delay_minutes / max) * 56)}px`, background: BAND_COLOUR[h.band] }} />
                <span>{hh(h.hour)}</span>
              </button>
            ))}
          </div>

          <div className="section">Worst at {hh(hour)}:00</div>
          {data.worst.map((w, i) => (
            <div className="worst" key={w.segment_id}>
              <span>{i + 1}</span><b>{w.name}</b>
              <em style={{ color: BAND_COLOUR[bandOf(w.delay_minutes)] }}>+{Math.round(w.delay_minutes)} min</em>
            </div>
          ))}
        </>
      )}
    </>
  );
}

// Legend and weather chip that sit on top of the map.
export function DelayLegend({ data }) {
  if (!data) return null;
  return (
    <>
      <div className="wx-chip">{data.conditions.weather.summary}</div>
      <div className="legend">
        <div className="legend-title">Avg delay vs timetable</div>
        <div className="legend-row">
          {data.legend.map((l) => (
            <span key={l.band}><i style={{ background: BAND_COLOUR[l.band] }} />{l.label}</span>
          ))}
        </div>
      </div>
    </>
  );
}