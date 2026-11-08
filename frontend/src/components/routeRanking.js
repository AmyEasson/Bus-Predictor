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

// Risk level: the model's (from its bad-day P90) when it has a prediction, else from history (% of these
// buses >5 min late at this time). `source` says which, because the two can disagree: never show the model's
// level next to the historical % as if they were one number.
export function riskOf(j) {
  const pct = j.insight?.risk_pct ?? null;
  if (j.prediction?.covered && j.prediction.risk_level) {
    return { level: j.prediction.risk_level, pct, source: 'model', p90: j.prediction.delay_p90_min };
  }
  if (pct != null) return { level: pct < 25 ? 'low' : pct < 50 ? 'medium' : 'high', pct, source: 'history' };
  return { level: null, pct: null, source: null };
}

// How bad a bad day is (minutes): the model's P90, else history (typical delay weighted by the late share).
const badDay = (j) => {
  const p = j.prediction;
  if (p?.covered && Number.isFinite(p.delay_p90_min)) return p.delay_p90_min;
  const { minutes } = expectedDelay(j);
  const { pct } = riskOf(j);
  if (minutes == null) return Infinity;
  return minutes * (1 + (pct ?? 50) / 100);
};
// Lower is better: when you'd arrive on a bad day (timetable + bad-day delay).
const score = (j) => j.duration_minutes + badDay(j);

export const LABELS = {
  reliable: { text: 'Most reliable', chip: 'green' },
  fastest: { text: 'Fastest on paper', chip: 'red' },
  balanced: { text: 'Balanced', chip: 'amber' },
};

// Tags journeys as in the design and sorts them:
//   reliable  lowest bad-day delay (least likely to make you late)
//   fastest   shortest on the timetable (only tagged if it isn't also the most reliable)
//   balanced  earliest bad-day arrival (timetable + bad-day delay), if it's neither of the above
// Sorts: 'best' = earliest bad-day arrival, 'reliable' = lowest bad-day delay, 'fastest', 'departure'.
export function rankRoutes(journeys, sortBy = 'best') {
  if (!journeys?.length) return [];
  const list = journeys.map((j) => ({ ...j, _bad: badDay(j), _score: score(j), _tag: null }));
  const known = list.filter((j) => Number.isFinite(j._bad));
  const reliable = known.length ? [...known].sort((a, b) => a._bad - b._bad || a.duration_minutes - b.duration_minutes)[0] : null;
  const fastest = [...list].sort((a, b) => a.duration_minutes - b.duration_minutes || a._score - b._score)[0];
  const balanced = known.length ? [...known].sort((a, b) => a._score - b._score)[0] : null;
  if (reliable) reliable._tag = 'reliable';
  if (list.length > 1 && fastest !== reliable) fastest._tag = 'fastest';
  if (balanced && !balanced._tag) balanced._tag = 'balanced';

  const byDep = (a, b) => a.departure_time.localeCompare(b.departure_time);
  if (sortBy === 'departure') return list.sort(byDep);
  if (sortBy === 'fastest') return list.sort((a, b) => a.duration_minutes - b.duration_minutes || byDep(a, b));
  if (sortBy === 'reliable') return list.sort((a, b) => a._bad - b._bad || byDep(a, b));
  return list.sort((a, b) => a._score - b._score || byDep(a, b));
}

// Coordinates of the whole journey, for drawing it.
export function journeyPath(j) {
  const legs = j.journey_type === 'transfer' ? j.legs : [{ stops: j.stops ?? [] }];
  return legs.flatMap((l) => (l.stops ?? []).map((s) => [s.stop_lat, s.stop_lon]));
}

export const lineList = (j) => (j.journey_type === 'transfer' ? j.legs.map((l) => l.route) : [j.route]);
