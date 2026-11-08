import { useState } from 'react';
import { BAND_COLOUR } from '../services/delayApi';

const hh = (h) => `${String(h).padStart(2, '0')}:00`;

// Map corner button that turns the delay layer on/off, with a short explanation of what drives delays.
export function LayersButton({ on, onToggle, data }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="layers">
      {open && (
        <div className="layers-pop">
          <label className="layer-row">
            <input type="checkbox" checked={on} onChange={onToggle} />
            <span className="layer-swatch" />
            <span>
              <b>Typical bus delays</b>
              <small>How far behind timetable buses usually run</small>
            </span>
          </label>
          {on && data?.factors && (
            <div className="why">
              <div className="label">What we measured</div>
              {data.factors.map((f) => (
                <div key={f.key} className="why-row">
                  <b>{f.label}</b>
                  <span>{f.description}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      <button className={`layers-btn ${on ? 'on' : ''}`} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="layers-icon" aria-hidden>◈</span>
        Layers
      </button>
    </div>
  );
}

// Bottom bar shown while the delay layer is on: day type, hour-of-day timeline, legend, data note.
export function DelayBar({ data, error, hour, setHour, dayType, setDayType }) {
  const hours = data?.hourly ?? [];
  const max = Math.max(1, ...hours.map((h) => h.avg_delay_minutes));
  return (
    <div className="delay-bar">
      <div className="delay-bar-top">
        <div className="seg">
          {[['weekday', 'Weekdays'], ['weekend', 'Weekends']].map(([id, name]) => (
            <button key={id} className={dayType === id ? 'on' : ''} onClick={() => setDayType(id)}>{name}</button>
          ))}
        </div>
        <div className="legend">
          {(data?.legend ?? []).map((l) => (
            <span key={l.band}><i style={{ background: BAND_COLOUR[l.band] }} />{l.label}</span>
          ))}
        </div>
      </div>

      <div className="timeline" role="group" aria-label="Hour of day">
        {hours.map((h) => (
          <button
            key={h.hour}
            className={h.hour === hour ? 'sel' : ''}
            onClick={() => setHour(h.hour)}
            title={`${hh(h.hour)}: buses average +${h.avg_delay_minutes} min`}
          >
            <i style={{ height: `${Math.max(12, (h.avg_delay_minutes / max) * 100)}%`, background: BAND_COLOUR[h.band] }} />
            <span>{h.hour % 3 === 0 || h.hour === hour ? String(h.hour).padStart(2, '0') : ''}</span>
          </button>
        ))}
      </div>

      <div className="delay-bar-foot muted small">
        {error ? <span className="err">{error}</span> : data?.data_from ? (
          <>Typical {data.day_type} at {hh(hour)}, from {data.data_days} days of real buses ({data.data_from} to {data.data_to}). Not live.</>
        ) : 'Loading…'}
      </div>
    </div>
  );
}

const COLOUR_BY = [['overall', 'Overall'], ['weather', 'Weather'], ['time_of_day', 'Time'], ['events', 'Events']];
const tone = (m) => (m < 0.5 ? 'g' : m < 2 ? 'a' : 'r');

// Side card while the delay layer is on (in explore mode): what to colour by, which factors to include,
// and the worst stretches at the selected hour (click one to fly there).
export function DelayInsightsCard({ data, colourBy, setColourBy, factors, toggleFactor, onFocusStretch }) {
  const worst = (data?.segments ?? []).slice(0, 5);
  return (
    <div className="sheet">
      <div className="sheet-head">
        <h2>What's slowing buses?</h2>
        <div className="muted small">Each hexagon shows how far behind timetable buses typically are there. Hover for details.</div>
      </div>

      <div className="block">
        <div className="label">Colour by</div>
        <div className="seg wide">
          {COLOUR_BY.map(([id, name]) => (
            <button key={id} className={colourBy === id ? 'on' : ''} onClick={() => setColourBy(id)}>{name}</button>
          ))}
        </div>
      </div>

      {data?.factors && (
        <div className="block">
          <div className="label">Delay factors</div>
          <div className="factors">
            {data.factors.map((f) => {
              const on = factors.includes(f.key);
              return (
                <label key={f.key} className={`factor-card toggle ${on ? '' : 'off'}`}>
                  <input type="checkbox" checked={on} onChange={() => toggleFactor(f.key)} />
                  <span className="switch" aria-hidden />
                  <span className="ft">
                    <b>{f.label}</b>
                    <span className="muted small">{f.description}</span>
                  </span>
                  <span className={`delta ${tone(f.minutes)}`}>{f.minutes >= 0 ? '+' : ''}{f.minutes.toFixed(1)}m</span>
                </label>
              );
            })}
          </div>
          <div className="muted small">Minutes: average extra delay per stretch at this hour.</div>
        </div>
      )}

      {worst.length > 0 && (
        <div className="block">
          <div className="label">Worst at {String(data.hour).padStart(2, '0')}:00</div>
          <ol className="worst">
            {worst.map((s, i) => (
              <li key={s.id}>
                <button onClick={() => onFocusStretch(s)}>
                  <span className="worst-n">{i + 1}</span>
                  <span className="worst-name">{s.name}<small>{s.lines ? `Lines ${s.lines.split(',').slice(0, 4).join(', ')}` : ''}</small></span>
                  <span className="worst-min" style={{ color: BAND_COLOUR[s.band] }}>+{Math.round(s.delay_minutes)} min</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
