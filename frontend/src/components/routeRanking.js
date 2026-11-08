// Ranking and display numbers for journey options.
// Prefers Amy's model prediction (journey.prediction) and falls back to the delay engine's history
// (journey.insight), so routes are still ranked when the model isn't loaded.

export function journeyKey(j) {
  return j.journey_type === 'transfer' ? j.legs.map((l) => l.trip_id).join('-') : j.trip_id;
}

// Expected minutes late on arrival, and where that number comes from.
export function expectedDelay(j) {
  const p = j.prediction;
  if (p?.covered && Number.isFinite(p.delay_p50_min)) return { minutes: p.delay_p50_min, source: p.mock ? 'sample' : 'model' };
  const t = j.insight?.typical_late_min;
  if (Number.isFinite(t)) return { minutes: t, source: 'history' };
  return { minutes: null, source: null };
}

// Same cut-offs as backend prediction.py: how late you'd be on a bad day (1 trip in 10).
export const riskLevel = (p90) => (p90 < 5 ? 'low' : p90 < 10 ? 'medium' : 'high');

// How bad a bad day is (minutes late, P90): the model's when it covers the route, else the route's own
// historical 90th-percentile delay for this time band. Both mean the same thing, so routes can be compared
// whichever source they come from, and the risk label always comes from this same number.
const badDay = (j) => {
  const p = j.prediction;
  if (p?.covered && Number.isFinite(p.delay_p90_min)) return p.delay_p90_min;
  const h = j.insight?.bad_day_min;
  return Number.isFinite(h) ? h : Infinity;
};

// Risk: the label always comes from the bad-day delay (so "most reliable" can't carry a higher label than a
// route it beat). `pct` (share of these buses >5 min late in past data) is shown separately, as context.
export function riskOf(j) {
  const pct = j.insight?.risk_pct ?? null;
  const p90 = badDay(j);
  if (!Number.isFinite(p90)) return { level: null, pct, source: null };
  const source = j.prediction?.covered && Number.isFinite(j.prediction.delay_p90_min)
    ? 'model'
    : j.insight?.bad_day_basis === 'typical' ? 'typical' : 'history';
  return { level: riskLevel(p90), pct, source, p90 };
}
const clockMin = (t) => {
  const [h, m] = String(t).split(':').map(Number);
  return h * 60 + m; // GTFS times can pass 24:00, which keeps after-midnight arrivals in order
};
// When you'd actually arrive on a bad day: scheduled arrival + bad-day delay. This is what routes are judged
// on. Comparing delays alone made a 45-min route with no delay look "safer" than a 13-min one that's 2 min late,
// even though the 13-min one gets you there half an hour earlier on its worst day.
const badArrival = (j) => clockMin(j.arrival_time) + (Number.isFinite(badDay(j)) ? badDay(j) : 0);

// A steadier route is only worth recommending if it gets you there about as early (on a bad day) as the best.
export const RELIABLE_WINDOW_MIN = 10;

export const LABELS = {
  best: { text: 'Best option', chip: 'green' },
  reliable: { text: 'Most reliable', chip: 'green' },
  fastest: { text: 'Fastest on paper', chip: 'red' },
};

// Tags and sorts journey options:
//   best      earliest arrival on a bad day: the recommendation
//   reliable  smallest bad-day delay among routes arriving within RELIABLE_WINDOW_MIN of the best (if not the best)
//   fastest   shortest timetable, tagged only when it is NOT the best: it looks quickest but arrives later on a
//             bad day (that's the "fast vs safe" trade-off; otherwise there is none to show)
// Sorts: 'best' (earliest bad-day arrival), 'reliable' (smallest bad-day delay), 'fastest', 'departure'.
export function rankRoutes(journeys, sortBy = 'best') {
  if (!journeys?.length) return [];
  const list = journeys.map((j) => ({ ...j, _bad: badDay(j), _score: badArrival(j), _tag: null }));
  const byScore = [...list].sort((a, b) => a._score - b._score || a.duration_minutes - b.duration_minutes);
  const best = byScore[0];
  best._tag = 'best';
  const reliable = list
    .filter((j) => j !== best && Number.isFinite(j._bad) && j._score <= best._score + RELIABLE_WINDOW_MIN
      && j._bad < best._bad)
    .sort((a, b) => a._bad - b._bad || a._score - b._score)[0];
  if (reliable) reliable._tag = 'reliable';
  const fastest = [...list].sort((a, b) => a.duration_minutes - b.duration_minutes || a._score - b._score)[0];
  if (!fastest._tag && fastest.duration_minutes < best.duration_minutes) fastest._tag = 'fastest';

  const byDep = (a, b) => a.departure_time.localeCompare(b.departure_time);
  if (sortBy === 'departure') return list.sort(byDep);
  if (sortBy === 'fastest') return list.sort((a, b) => a.duration_minutes - b.duration_minutes || byDep(a, b));
  if (sortBy === 'reliable') return list.sort((a, b) => a._bad - b._bad || a._score - b._score);
  return list.sort((a, b) => a._score - b._score || byDep(a, b));
}

// Coordinates of the whole journey, for drawing it.
export function journeyPath(j) {
  const legs = j.journey_type === 'transfer' ? j.legs : [{ stops: j.stops ?? [] }];
  return legs.flatMap((l) => (l.stops ?? []).map((s) => [s.stop_lat, s.stop_lon]));
}

export const lineList = (j) => (j.journey_type === 'transfer' ? j.legs.map((l) => l.route) : [j.route]);
