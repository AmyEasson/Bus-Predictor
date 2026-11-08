import { useEffect, useState } from 'react';
import { fetchStopInfo } from '../services/api';
import { BAND_COLOUR } from '../services/delayApi';

const BAND_TEXT = { on_time: 'usually on time', minor: 'often a few minutes late', moderate: 'often late', severe: 'usually very late' };

// The card for a selected stop: lines, typical delay now, next departures, and the two ways into directions.
export function StopCard({ stop, onDirectionsTo, onDirectionsFrom }) {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let stale = false;
    setInfo(null);
    setError(null);
    fetchStopInfo(stop.stop_id)
      .then((d) => { if (!stale) setInfo(d); })
      .catch(() => { if (!stale) setError('Could not load this stop.'); });
    return () => { stale = true; };
  }, [stop.stop_id]);

  const typical = info?.typical;

  return (
    <div className="sheet">
      <div className="sheet-head">
        <h2>{stop.stop_name}</h2>
        <div className="muted">
          Bus stop{(info?.towards ?? stop.towards) ? ` · towards ${info?.towards ?? stop.towards}` : ''}
        </div>
      </div>

      <div className="actions">
        <button className="action primary" onClick={onDirectionsTo}>
          <span aria-hidden>➜</span> Directions
        </button>
        <button className="action" onClick={onDirectionsFrom}>
          <span aria-hidden>●</span> Start here
        </button>
      </div>

      {error && <div className="inline-note warn">{error}</div>}
      {!info && !error && <div className="skeleton" />}

      {info && (
        <>
          {info.lines.length > 0 && (
            <div className="block">
              <div className="label">Lines</div>
              <div className="chips">
                {info.lines.map((l) => <span key={l} className="line">{l}</span>)}
              </div>
            </div>
          )}

          {typical && (
            <div className="block typical" style={{ borderColor: BAND_COLOUR[typical.band] }}>
              <span className="typ-dot" style={{ background: BAND_COLOUR[typical.band] }} />
              <div>
                <b>
                  {typical.delay_minutes < 1 ? 'On time' : `+${typical.delay_minutes.toFixed(0)} min`}
                </b>{' '}
                <span>{BAND_TEXT[typical.band]} around {String(typical.hour).padStart(2, '0')}:00 on {typical.day_type}s</span>
                <div className="muted small">From {typical.observations.toLocaleString()} past bus arrivals</div>
              </div>
            </div>
          )}

          <div className="block">
            <div className="label">Next departures</div>
            {info.departures.length === 0 ? (
              <div className="muted">No more buses today.</div>
            ) : (
              <ul className="departures">
                {info.departures.map((d) => (
                  <li key={d.trip_id}>
                    <span className="line">{d.route}</span>
                    <span className="dep-headsign">{d.headsign || '—'}</span>
                    <span className="dep-time">
                      {d.minutes_away <= 0 ? 'Now' : d.minutes_away < 60 ? `${d.minutes_away} min` : d.time}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="muted small">Timetabled times</div>
          </div>
        </>
      )}
    </div>
  );
}
