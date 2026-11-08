import { useEffect, useMemo, useState } from 'react';
import { fetchJourneys } from '../services/api';
import { SearchBox } from './SearchBox';
import { PredictionBadge } from './PredictionBadge';
import { rankRoutes, journeyKey, expectedDelay, riskOf, LABELS, lineList } from './routeRanking';

const hhmm = (t) => (t ? t.slice(0, 5) : '');
const pad = (n) => String(n).padStart(2, '0');
const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
const nowHHMM = () => {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const addMin = (t, m) => {
  const [h, mm] = t.split(':').map(Number);
  const total = h * 60 + mm + Math.round(m);
  return `${pad(Math.floor(total / 60) % 24)}:${pad(total % 60)}`;
};
const RISK_TEXT = { low: 'Low', medium: 'Medium', high: 'High' };
const RISK_CHIP = { low: 'green', medium: 'amber', high: 'red' };
const RISK_HELP = 'Delay risk: how late you could be on a bad day (the worst 1 trip in 10). '
  + 'Low: under 5 min late. Medium: 5 to 10 min. High: over 10 min.';
const tone = (m) => (m == null ? '' : m < 2 ? 'g' : m < 5 ? 'a' : 'r');

function Lines({ journey }) {
  return (
    <span className="lines-row">
      {lineList(journey).map((l, i) => (
        <span key={`${l}-${i}`} className="lines-step">
          {i > 0 && <span className="chev" aria-hidden>›</span>}
          <span className="line">{l}</span>
        </span>
      ))}
    </span>
  );
}

function Tag({ journey }) {
  const t = LABELS[journey._tag];
  return t ? <span className={`chip ${t.chip}`}>{t.text}</span> : null;
}

function RiskMeter({ journey }) {
  const { pct, level, source, p90 } = riskOf(journey);
  if (!level) return null;
  // meter: the bad-day delay on a 0-15 min scale (model or history, same meaning)
  const fill = Math.min(100, (p90 / 15) * 100);
  return (
    <div className="risk">
      <div className="risk-head">
        <span className="muted small help" title={RISK_HELP}>Delay risk ⓘ</span>
        <span className={`chip ${RISK_CHIP[level]}`} title={RISK_HELP}>{RISK_TEXT[level]}</span>
        <span className="muted small">
          bad day: +{p90.toFixed(1)} min{source === 'history' ? ' (past data)' : source === 'typical' ? ' (typical for this time)' : ''}
        </span>
      </div>
      <div className="meter"><i style={{ width: `${Math.max(3, fill)}%`, background: `var(--${RISK_CHIP[level]})` }} /></div>
      {pct != null && (
        <span className="muted small">In past data, {pct}% of these buses ran 5+ min late at this time</span>
      )}
    </div>
  );
}

// "31 min · timetable 22 min · +9 min predicted"
function Duration({ journey, big = true }) {
  const { minutes, source } = expectedDelay(journey);
  const total = journey.duration_minutes + Math.max(0, Math.round(minutes ?? 0));
  return (
    <div className="dur">
      <span className={big ? 'dur-big' : 'dur-mid'}>{total} min</span>
      <span className="dur-side">
        <span className="muted">timetable {journey.duration_minutes} min</span>
        {minutes != null && (
          <span className={tone(minutes)}>
            {minutes < 1 ? 'usually on time' : `+${Math.round(minutes)} min ${source === 'history' ? 'usually' : 'predicted'}`}
          </span>
        )}
      </span>
    </div>
  );
}

function RouteCard({ journey, onSelect }) {
  const { minutes } = expectedDelay(journey);
  const arrive = addMin(hhmm(journey.arrival_time), Math.max(0, minutes ?? 0));
  return (
    <li>
      <div className={`route-card ${journey._tag === 'best' ? 'best' : ''}`} onClick={onSelect} role="button" tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && onSelect()}>
        <div className="rc-top">
          <span className="rc-tags">
            <Tag journey={journey} />
            <span className="muted small">{hhmm(journey.departure_time)} departure</span>
          </span>
          <span className="muted small">Arrive ~{arrive}</span>
        </div>
        <Duration journey={journey} />
        <div className="rc-lines">
          <Lines journey={journey} />
          <span className="muted small">{journey.journey_type === 'transfer' ? `1 change · ${journey.transfer_wait_minutes} min wait` : 'Direct'}</span>
        </div>
        <RiskMeter journey={journey} />
        {journey.insight?.explanation && <p className="rc-why">{journey.insight.explanation}</p>}
        {journey.prediction?.connection_at_risk && <span className="tag-warn">Connection at risk</span>}
        <div className="rc-foot">
          <button className="link" onClick={(e) => { e.stopPropagation(); onSelect(); }}>Route details →</button>
        </div>
      </div>
    </li>
  );
}

// Fastest on paper vs the best option, side by side - only when the fastest-looking route isn't the best one
function FastVsSafe({ routes, selected, onSelect }) {
  const fastest = routes.find((r) => r._tag === 'fastest');
  const reliable = routes.find((r) => r._tag === 'best');
  if (!fastest || !reliable) return null;
  return (
    <div className="block">
      <div className="label">Fast vs safe</div>
      <div className="vs">
        {[fastest, reliable].map((j) => {
          const { level } = riskOf(j);
          const on = journeyKey(j) === journeyKey(selected);
          return (
            <button key={journeyKey(j)} className={`vs-card ${on ? 'on' : ''}`} onClick={() => onSelect(j)}>
              <span className={`vs-label ${j._tag === 'fastest' ? 'fastest' : 'reliable'}`}>{LABELS[j._tag].text}</span>
              <Duration journey={j} big={false} />
              {level && <span className={`chip ${RISK_CHIP[level]}`}>Risk {RISK_TEXT[level]}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

const FACTOR_COLOUR = { time_of_day: 'var(--amber)', weather: '#3b82c4', events: 'var(--red)', roadworks: '#e8710a' };

function WhyPanel({ journey }) {
  const ins = journey.insight;
  if (!ins) return null;
  const max = Math.max(1, ...ins.factors.map((f) => Math.abs(f.minutes)));
  const title = journey._tag === 'fastest' ? 'Why the fastest-looking route is risky' : 'What affects this route';
  return (
    <div className="block">
      <div className="label">{title}</div>
      <div className="factors">
        {ins.factors.map((f) => (
          <div key={f.key} className="factor-card">
            <div className="fc-top">
              <span><i className="fc-dot" style={{ background: FACTOR_COLOUR[f.key] }} /> <b>{f.label}</b></span>
              <span className={f.minutes >= 0.5 ? 'r' : 'muted'}>{f.minutes >= 0 ? '+' : ''}{f.minutes.toFixed(1)} min</span>
            </div>
            <span className="muted small">{f.description}</span>
            <div className="meter thin"><i style={{ width: `${Math.max(2, (Math.abs(f.minutes) / max) * 100)}%`, background: FACTOR_COLOUR[f.key] }} /></div>
          </div>
        ))}
        {ins.roadworks?.length > 0 && (
          <div className="factor-card">
            <div className="fc-top">
              <span><i className="fc-dot" style={{ background: '#e8710a' }} /> <b>Road works on this route</b></span>
              <span className="muted small">{ins.roadworks.length} job{ins.roadworks.length === 1 ? '' : 's'}</span>
            </div>
            <ul className="works-list">
              {ins.roadworks.slice(0, 5).map((w) => (
                <li key={w.id}>
                  <span><b>{w.traffic_management}</b> · {w.street}</span>
                  <span className={w.effect_s >= 15 ? 'r' : w.effect_s >= 5 ? 'a' : 'muted'}>+{Math.round(w.effect_s)} s</span>
                  <small className="muted">{w.status === 'planned' ? 'planned' : 'in progress'} until {w.end} · {w.measured ? 'measured' : 'typical for type'}</small>
                </li>
              ))}
            </ul>
          </div>
        )}
        {ins.worst && (
          <div className="factor-card">
            <div className="fc-top">
              <span><i className="fc-dot" style={{ background: 'var(--ink)' }} /> <b>Slowest stretch</b></span>
              <span className="r">+{Math.round(ins.worst.added_s / 60)} min</span>
            </div>
            <span className="muted small">{ins.worst.name}: buses usually lose the most time here (marked on the map)</span>
          </div>
        )}
      </div>
      <div className="muted small">
        Based on {ins.data_days} days of Greater Manchester bus data · {Math.round(ins.coverage * 100)}% of this route covered · confidence: {ins.confidence}
      </div>
    </div>
  );
}

function RouteSteps({ journey }) {
  const legs = journey.journey_type === 'transfer' ? journey.legs : [{
    route: journey.route, trip_id: journey.trip_id, destination: journey.destination,
    departure_time: journey.departure_time, arrival_time: journey.arrival_time, stops: journey.stops ?? [],
  }];
  return (
    <ol className="steps">
      {legs.map((leg, i) => {
        const stops = leg.stops ?? [];
        const ride = Math.max(0, stops.length - 1);
        return (
          <li key={leg.trip_id} className="leg">
            <div className="step stop">
              <span className="step-time">{hhmm(leg.departure_time)}</span>
              <span className="step-dot" />
              <div>
                <b>{stops[0]?.stop_name ?? 'Board'}</b>
                <div className="muted small">Board <span className="line">{leg.route}</span> towards {leg.destination}</div>
              </div>
            </div>
            <div className="step ride">
              <span className="step-time" />
              <span className="step-rail" />
              <details>
                <summary>Ride {ride} stop{ride === 1 ? '' : 's'}</summary>
                <ul className="ride-stops">
                  {stops.slice(1, -1).map((s, k) => (
                    <li key={`${s.stop_id}-${k}`}><span>{s.stop_name}</span><span className="muted">{hhmm(s.arrival_time)}</span></li>
                  ))}
                </ul>
              </details>
            </div>
            <div className="step stop">
              <span className="step-time">{hhmm(leg.arrival_time)}</span>
              <span className="step-dot" />
              <div><b>{stops[stops.length - 1]?.stop_name ?? 'Get off'}</b><div className="muted small">Get off</div></div>
            </div>
            {i < legs.length - 1 && (
              <div className="step change">
                <span className="step-time" />
                <span className="step-rail dashed" />
                <div className="muted small">
                  Change buses · wait {journey.transfer_wait_minutes} min
                  {journey.prediction?.connection_at_risk && <span className="tag-warn">may miss this connection</span>}
                </div>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

// Directions: from/to + time, ranked route cards, and the chosen route's comparison, reasons and steps.
// Reports the ranked list up (onResults) so the map can draw the options.
export function Directions({ from, to, setFrom, setTo, onHover, selected, onSelectJourney, onClose, onResults, onSearched }) {
  const [timeMode, setTimeMode] = useState('now'); // now | depart | arrive
  const [date, setDate] = useState(todayIso);
  const [time, setTime] = useState(nowHHMM);
  const [sortBy, setSortBy] = useState('best');
  const [state, setState] = useState({ loading: false, error: null, journeys: null });

  useEffect(() => {
    if (!from || !to) { setState({ loading: false, error: null, journeys: null }); return undefined; }
    if (from.stop_id === to.stop_id) { setState({ loading: false, error: 'Pick two different stops.', journeys: null }); return undefined; }
    let stale = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    const at = timeMode === 'now' ? nowHHMM() : time;
    fetchJourneys({
      originStopId: from.stop_id,
      destinationStopId: to.stop_id,
      travelDate: timeMode === 'now' ? todayIso() : date,
      limit: 10,
      departureAfter: timeMode === 'arrive' ? null : at,
      arriveBy: timeMode === 'arrive' ? at : null,
      includeStops: true,
    })
      .then((r) => { if (!stale) setState({ loading: false, error: null, journeys: r.journeys }); })
      .catch(() => { if (!stale) setState({ loading: false, error: 'Could not find routes. Try again.', journeys: null }); });
    return () => { stale = true; };
  }, [from, to, timeMode, date, time]);

  const ranked = useMemo(() => rankRoutes(state.journeys ?? [], sortBy), [state.journeys, sortBy]);
  useEffect(() => { onResults?.(ranked); }, [ranked, onResults]);
  useEffect(() => {
    if (ranked.length && from && to) onSearched?.(from, to, ranked.find((r) => r._tag === 'best') ?? ranked[0]);
  }, [ranked]); // eslint-disable-line react-hooks/exhaustive-deps

  const swap = () => { setFrom(to); setTo(from); };

  if (selected) {
    const sel = ranked.find((r) => journeyKey(r) === journeyKey(selected)) ?? selected;
    const { level } = riskOf(sel);
    return (
      <div className="sheet dir">
        <button className="back-link" onClick={() => onSelectJourney(null)}>← All routes</button>
        <div className="sheet-scroll">
          <div className="sheet-head">
            <h2>
              {LABELS[sel._tag]?.text ?? 'Route'}{' '}
              {level && <span className={`chip ${RISK_CHIP[level]}`}>{RISK_TEXT[level]} risk</span>}
            </h2>
            <div className="muted">
              <Lines journey={sel} /> · {from?.stop_name} → {to?.stop_name} · {hhmm(sel.departure_time)}–{hhmm(sel.arrival_time)}
            </div>
          </div>
          <FastVsSafe routes={ranked} selected={sel} onSelect={onSelectJourney} />
          <WhyPanel journey={sel} />
          {sel.prediction?.covered && (
            <div className="block">
              <div className="label">Model prediction</div>
              <PredictionBadge prediction={sel.prediction} />
              {(sel.prediction.assumed ?? []).filter((a) => a.delay_now_min != null).map((a, i) => (
                <div key={i} className="muted small">
                  Assumes your bus reaches {a.stop_name} {a.delay_now_min < 0.5 ? 'on time' : `~${Math.round(a.delay_now_min)} min late`},
                  {a.basis === 'stop' ? ` as buses usually do there around ${String(a.hour).padStart(2, '0')}:00` : ' the network average for that hour'}.
                </div>
              ))}
            </div>
          )}
          <div className="block"><div className="label">Steps</div><RouteSteps journey={sel} /></div>
        </div>
      </div>
    );
  }

  return (
    <div className="sheet dir">
      <div className="dir-head">
        <span className="dir-title">Directions</span>
        <button className="icon-btn" onClick={onClose} aria-label="Close directions">✕</button>
      </div>

      <div className="dir-fields">
        <div className="dir-rail" aria-hidden><span className="o" /><span className="dots" /><span className="d" /></div>
        <div className="dir-inputs">
          <SearchBox value={from} onSelect={setFrom} onHover={onHover} placeholder="Choose starting stop" autoFocus={!from} className="field-box" />
          <SearchBox value={to} onSelect={setTo} onHover={onHover} placeholder="Choose destination" autoFocus={!!from && !to} className="field-box" />
        </div>
        <button className="icon-btn swap" onClick={swap} aria-label="Swap start and destination">⇅</button>
      </div>

      <div className="time-row">
        <select value={timeMode} onChange={(e) => setTimeMode(e.target.value)} aria-label="When">
          <option value="now">Leave now</option>
          <option value="depart">Depart at</option>
          <option value="arrive">Arrive by</option>
        </select>
        {timeMode !== 'now' && (
          <>
            <input type="time" value={time} step="300" onChange={(e) => setTime(e.target.value)} aria-label="Time" />
            <input type="date" value={date} min={todayIso()} onChange={(e) => setDate(e.target.value)} aria-label="Date" />
          </>
        )}
      </div>

      <div className="sheet-scroll">
        {state.error && <div className="inline-note warn">{state.error}</div>}
        {state.loading && <><div className="skeleton" /><div className="skeleton" /></>}

        {!state.loading && state.journeys && (
          state.journeys.length === 0 ? (
            <div className="inline-note">No buses found between these stops at that time. Try another time or a nearby stop.</div>
          ) : (
            <>
              <div className="results-head">
                <span className="muted small">{ranked.length} routes · {{
                  best: 'ranked by arrival time on a bad day', reliable: 'least likely to be late first',
                  fastest: 'shortest timetable first', departure: 'by departure',
                }[sortBy]}</span>
                <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} aria-label="Sort routes">
                  <option value="best">Best arrival</option>
                  <option value="reliable">Most reliable</option>
                  <option value="fastest">Fastest</option>
                  <option value="departure">Earliest</option>
                </select>
              </div>
              <ul className="results">
                {ranked.map((j) => (
                  <RouteCard key={journeyKey(j)} journey={j} onSelect={() => onSelectJourney(j)} />
                ))}
              </ul>
            </>
          )
        )}
      </div>
    </div>
  );
}
