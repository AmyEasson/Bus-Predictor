
import { useEffect, useMemo, useState } from 'react';
import './App.css';
import { Header } from './components/Header';
import 'leaflet/dist/leaflet.css';
import { BusMap } from './components/BusMap';
import { fetchAllLiveBuses, searchStops, fetchJourneys } from './services/api';
import { fetchDelayMap } from './services/delayApi';
import { DelayPanel, DelayLegend } from './components/DelayPanel';
import { DelayLayer } from './components/DelayLayer';

// TODO: replace with POST /route once the delay model is connected.
const SAMPLE_ROUTES = [
  { id: 1, label: 'Most reliable', tone: 'green', lines: ['42'], mins: 31, timetable: 29, delay: 2, risk: 12 },
  { id: 2, label: 'Fastest on paper', tone: 'red', lines: ['43'], mins: 31, timetable: 22, delay: 9, risk: 68 },
  { id: 3, label: 'Balanced', tone: 'amber', lines: ['142'], mins: 33, timetable: 26, delay: 7, risk: 41 },
];

const TONE = {
  green: 'var(--green)',
  amber: 'var(--amber)',
  red: 'var(--red)'
};

const TIME_MODES = ['Depart after', 'Arrive by'];

function StopAutocomplete({ label, onSelect, onHover, color }) {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [isSelected, setIsSelected] = useState(false);

  useEffect(() => {
    if (query.trim().length < 2 || isSelected) {
      setSuggestions([]);
      onHover(null);
      return;
    }

    let cancelled = false;

    const timer = setTimeout(async () => {
      const results = await searchStops(query.trim());

      if (!cancelled) {
        setSuggestions(results);
      }
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, isSelected, onHover]);

  const handleChange = (value) => {
    setQuery(value);
    setIsSelected(false);
    onSelect(null);
    onHover(null);
  };

  const handleSelect = (stop) => {
    setQuery(stop.stop_name);
    setIsSelected(true);
    setSuggestions([]);
    onHover(null);
    onSelect(stop);
  };

  return (
    <div className="field autocomplete-field">
      <span className="pin" style={{ background: color }} />

      <div className="autocomplete-content">
        <label>{label}</label>

        <input
          value={query}
          onChange={(e) => handleChange(e.target.value)}
          placeholder="Search for a bus stop..."
          autoComplete="off"
        />

        {suggestions.length > 0 && !isSelected && (
          <div className="stop-dropdown">
            {suggestions.map((stop) => (
              <button
                type="button"
                className="stop-option"
                key={stop.stop_id}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => onHover(stop)}
                onMouseLeave={() => onHover(null)}
                onClick={() => handleSelect(stop)}
              >
                <div className="stop-info">
                  <span className="stop-name">{stop.stop_name}</span>
                  {stop.stop_code && (
                    <span className="stop-code">
                      Code: {stop.stop_code}
                    </span>
                  )}
                </div>
                <span className="stop-id">{stop.stop_id}</span>
              </button>
            ))}
          </div>
        )}

        {query.trim().length >= 2 &&
          suggestions.length === 0 &&
          !isSelected && (
            <div className="stop-dropdown empty">
              No matching stops found
            </div>
          )}
      </div>
    </div>
  );
}

function RouteCard({ r }) {
  return (
    <div className="card">
      <div className="card-top">
        <span className={`chip ${r.tone}`}>{r.label}</span>
      </div>
      <div className="big">{r.mins} min</div>
      <div className="meta">
        {r.lines.map((l) => (
          <span key={l} className="line-tag">{l}</span>
        ))}
        <span>timetable {r.timetable} min</span>
        <span style={{ color: TONE[r.tone], fontWeight: 600 }}>
          +{r.delay} min predicted
        </span>
      </div>
      <div className="bar">
        <i style={{ width: `${r.risk}%`, background: TONE[r.tone] }} />
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState('plan');
  const [fromStop, setFromStop] = useState(null);
  const [toStop, setToStop] = useState(null);
  const [hoveredStop, setHoveredStop] = useState(null);

  const [timeMode, setTimeMode] = useState(TIME_MODES[0]);

  // Travel date defaults to today.
  const [selectedDate, setSelectedDate] = useState(() => {
    const today = new Date();

    return [
      today.getFullYear(),
      String(today.getMonth() + 1).padStart(2, '0'),
      String(today.getDate()).padStart(2, '0'),
    ].join('-');
  });

  const [selectedTime, setSelectedTime] = useState(() => {
    const now = new Date();
    const minutes = Math.ceil(now.getMinutes() / 15) * 15;

    now.setMinutes(minutes, 0, 0);

    return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  });

  const [rows, setRows] = useState([]);
  const [firstLoad, setFirstLoad] = useState(true);
  const [searched, setSearched] = useState(false);

  const [colourBy, setColourBy] = useState('overall');
  const [factors, setFactors] = useState(['weather', 'time_of_day', 'events']);
  const [hour, setHour] = useState(Math.min(18, Math.max(7, new Date().getHours())));
  const [delay, setDelay] = useState(null);
  const [delayErr, setDelayErr] = useState(null);

  const [journeys, setJourneys] = useState([]);
  const [journeyLoading, setJourneyLoading] = useState(false);
  const [journeyError, setJourneyError] = useState(null);
  const [selectedJourney, setSelectedJourney] = useState(null);

  // Load live bus positions.
  useEffect(() => {
    const load = async () => {
      try {
        setRows(await fetchAllLiveBuses());
      } finally {
        setFirstLoad(false);
      }
    };

    load();

    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  // Load delay map data.
  useEffect(() => {
    if (tab !== 'delay-map') return;

    let stale = false;

    fetchDelayMap({ hour, colourBy, factors })
      .then((d) => {
        if (!stale) {
          setDelay(d);
          setDelayErr(null);
        }
      })
      .catch((e) => {
        if (!stale) setDelayErr(e.message);
      });

    return () => {
      stale = true;
    };
  }, [tab, hour, colourBy, factors]);

  const toggleFactor = (k) => {
    setFactors((f) =>
      f.includes(k) ? f.filter((x) => x !== k) : [...f, k]
    );
  };

  // Search for direct journeys using the selected date and time.
  const handleSearch = async () => {
    setJourneyLoading(true);
    setJourneyError(null);
    setSelectedJourney(null);

    const travelDate = selectedDate;

    try {
      const response = await fetchJourneys({
        originStopId: fromStop.stop_id,
        destinationStopId: toStop.stop_id,
        travelDate,
        limit: 10,

        departureAfter:
          timeMode === 'Depart after' ? selectedTime : null,

        arriveBy:
          timeMode === 'Arrive by' ? selectedTime : null,

        includeStops: true,
      });

      setJourneys(response.journeys);
      setSearched(true);
    } catch (error) {
      console.error('Journey search failed:', error);
      setJourneyError('Could not find journeys. Please try again.');
    } finally {
      setJourneyLoading(false);
    }
  };

  // One marker per vehicle (newest fix).
  const { buses, asOf } = useMemo(() => {
    const latest = new Map();

    for (const b of rows) {
      if (b.latitude == null || b.longitude == null) continue;

      const k = `${b.operator_ref}|${b.vehicle_ref}`;

      if (
        !latest.has(k) ||
        b.recorded_at > latest.get(k).recorded_at
      ) {
        latest.set(k, b);
      }
    }

    const list = [...latest.values()];

    const newest = list.reduce(
      (m, b) => Math.max(m, Date.parse(b.recorded_at) || 0),
      0
    );

    return {
      buses: list,
      asOf: newest ? new Date(newest) : null
    };
  }, [rows]);

  return (
    <div className="app">
      <Header
        activeTab={tab}
        setActiveTab={(newTab) => {
          setTab(newTab);

          if (newTab !== 'plan') {
            setSelectedJourney(null);
          }
        }}
        asOf={asOf}
      />

      <div className="main">
        <aside className="side">
          {tab === 'delay-map' ? (
            <DelayPanel
              data={delay}
              error={delayErr}
              colourBy={colourBy}
              setColourBy={setColourBy}
              factors={factors}
              toggleFactor={toggleFactor}
              hour={hour}
              setHour={setHour}
            />
          ) : searched ? (
            <>
              <button
                className="back"
                onClick={() => {
                  setSearched(false);
                  setSelectedJourney(null);
                }}
              >
                ← Edit search
              </button>

              <div>
                <h1>
                  {fromStop.stop_name} to {toStop.stop_name}
                </h1>
                <p className="sub">
                  {journeys.length} direct journeys found
                </p>
                <p className="journey-date">
                  {new Date(`${selectedDate}T12:00:00`).toLocaleDateString('en-GB', {
                    weekday: 'long',
                    day: 'numeric',
                    month: 'long',
                    year: 'numeric',
                  })}
                </p>
              </div>

              {journeys.length === 0 ? (
                <div className="note">
                  <div>
                    <strong>No journeys found</strong>
                    Try different stops or another travel date.
                  </div>
                </div>
              ) : (
                journeys.map((journey) => (
                  <div
                    className="card"
                    key={journey.trip_id}
                    onClick={() => setSelectedJourney(journey)}
                    style={{
                      cursor: 'pointer',
                      border:
                        selectedJourney?.trip_id === journey.trip_id
                          ? '2px solid #3b7a57'
                          : undefined,
                    }}
                  >
                    <div className="card-top">
                      <span className="line-tag">
                        Route {journey.route}
                      </span>
                      <span className="chip green">Direct</span>
                    </div>

                    <div className="big">
                      {journey.duration_minutes} min
                    </div>

                    <div className="meta">
                      <span>
                        {journey.departure_time.slice(0, 5)}
                        {' → '}
                        {journey.arrival_time.slice(0, 5)}
                      </span>
                      <span>{journey.destination}</span>
                    </div>

                    {journey.stops && (
                      <details>
                        <summary>
                          View stops ({journey.stops.length})
                        </summary>

                        <div className="journey-stops">
                          {journey.stops.map((stop) => (
                            <div
                              key={`${journey.trip_id}-${stop.stop_sequence}`}
                            >
                              {stop.stop_name}
                              <span>
                                {stop.arrival_time?.slice(0, 5)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                ))
              )}
            </>
          ) : (
            <>
              <div>
                <h1>Where to?</h1>
                <p className="sub">
                  Routes ranked by predicted delay, not just the timetable.
                </p>
              </div>

              <StopAutocomplete
                label="From"
                onSelect={setFromStop}
                onHover={setHoveredStop}
                color="#2d55d4"
              />

              <StopAutocomplete
                label="To"
                onSelect={setToStop}
                onHover={setHoveredStop}
                color="#d9534f"
              />

              {/* Time mode selection */}
              <div className="pills">
                {TIME_MODES.map((mode) => (
                  <button
                    type="button"
                    key={mode}
                    className={`pill ${timeMode === mode ? 'on' : ''}`}
                    onClick={() => setTimeMode(mode)}
                  >
                    {mode}
                  </button>
                ))}
              </div>

              {/* Date selection */}
              <div className="field">
                <label htmlFor="travel-date">Travel date</label>
                <input
                  id="travel-date"
                  className="time-select"
                  type="date"
                  value={selectedDate}
                  min={new Date().getFullYear() + '-' +
                    String(new Date().getMonth() + 1).padStart(2, '0') + '-' +
                    String(new Date().getDate()).padStart(2, '0')}
                  onChange={(e) => setSelectedDate(e.target.value)}
                />
              </div>

              {/* Time selection */}
              <div className="field time-field">
                <label>
                  {timeMode === 'Depart after'
                    ? 'Depart after'
                    : 'Arrive by'}
                </label>

                <input
                  className="time-select"
                  type="time"
                  step="900"
                  value={selectedTime}
                  onChange={(e) => setSelectedTime(e.target.value)}
                />
              </div>

              <button
                className="cta"
                disabled={!fromStop || !toStop || journeyLoading}
                onClick={handleSearch}
              >
                {journeyLoading ? 'Searching...' : 'Find routes'}
              </button>

              {journeyError && (
                <div className="note warn">
                  <div>
                    <strong>Search error</strong>
                    {journeyError}
                  </div>
                </div>
              )}

              <div className="note">
                <span
                  className="dot"
                  style={{ marginTop: 4, flex: 'none' }}
                />
                <div>
                  <strong>Delay predictions on</strong>
                  Uses live bus positions, weather and local events
                </div>
              </div>

              <div className="section">Network right now</div>

              <div className="stats">
                <div className="stat">
                  <b>–</b>
                  <span>buses on time</span>
                </div>
                <div className="stat">
                  <b>–</b>
                  <span>delayed &gt; 5 min</span>
                </div>
                <div className="stat">
                  <b>–</b>
                  <span>avg delay</span>
                </div>
              </div>
            </>
          )}
        </aside>

        <div className="mapwrap">
          {firstLoad && (
            <div className="toast">Loading bus positions…</div>
          )}

          {tab === 'plan' && !firstLoad && buses.length === 0 && (
            <div className="toast err">No bus data found</div>
          )}

          <BusMap
            buses={tab === 'plan' ? buses : []}
            hoveredStop={hoveredStop}
            selectedJourney={selectedJourney}
          >
            {tab === 'delay-map' && <DelayLayer data={delay} />}
          </BusMap>

          {tab === 'delay-map' && <DelayLegend data={delay} />}
        </div>
      </div>
    </div>
  );
}
