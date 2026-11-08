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

// Risk: % chance of being >5 min late (history), and a level (model's if it has one).
export function riskOf(j) {
  const pct = j.insight?.risk_pct ?? null;
  let level = j.prediction?.covered ? j.prediction.risk_level : null;
  if (!level && pct != null) level = pct < 25 ? 'low' : pct < 50 ? 'medium' : 'high';
  return { pct, level };
}

const score = (j) => {
  // lower is better: "safe" arrival = timetable + a pessimistic delay
  const p = j.prediction;
  if (p?.covered && Number.isFinite(p.delay_p90_min)) return j.duration_minutes + p.delay_p90_min;
  const { minutes } = expectedDelay(j);
  const { pct } = riskOf(j);
  if (minutes == null) return Infinity;
  return j.duration_minutes + minutes * (1 + (pct ?? 50) / 100);
};

export const LABELS = {
  reliable: { text: 'Most reliable', chip: 'green' },
  fastest: { text: 'Fastest on paper', chip: 'red' },
  balanced: { text: 'Balanced', chip: 'amber' },
};

// Tags journeys with _tag ('reliable' | 'fastest' | 'balanced') and sorts them.
export function rankRoutes(journeys, sortBy = 'reliable') {
  if (!journeys?.length) return [];
  const list = journeys.map((j) => ({ ...j, _score: score(j), _tag: null }));
  const byScore = [...list].sort((a, b) => a._score - b._score);
  const fastest = [...list].sort((a, b) => a.duration_minutes - b.duration_minutes || a._score - b._score)[0];
  const reliable = Number.isFinite(byScore[0]._score) ? byScore[0] : null;
  if (reliable) reliable._tag = 'reliable';
  if (list.length > 1 && fastest !== reliable) fastest._tag = 'fastest';
  const balanced = byScore.find((j) => !j._tag && Number.isFinite(j._score) && j._score <= (reliable?._score ?? 0) * 1.15);
  if (balanced && list.length > 2) balanced._tag = 'balanced';

  if (sortBy === 'departure') return list.sort((a, b) => a.departure_time.localeCompare(b.departure_time));
  if (sortBy === 'fastest') return list.sort((a, b) => a.duration_minutes - b.duration_minutes);
  return list.sort((a, b) => a._score - b._score || a.departure_time.localeCompare(b.departure_time));
}

// Coordinates of the whole journey, for drawing it.
export function journeyPath(j) {
  const legs = j.journey_type === 'transfer' ? j.legs : [{ stops: j.stops ?? [] }];
  return legs.flatMap((l) => (l.stops ?? []).map((s) => [s.stop_lat, s.stop_lon]));
}

export const lineList = (j) => (j.journey_type === 'transfer' ? j.legs.map((l) => l.route) : [j.route]);
