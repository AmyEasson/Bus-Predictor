const keyOf = (j) => (j.journey_type === 'transfer' ? j.legs.map((l) => l.trip_id).join('-') : j.trip_id);

// Tags the best journeys ("Most reliable", "Fastest on paper") and sorts the list, like the Figma.
// With fewer than two predicted journeys there is nothing to compare, so it falls back to departure order.
export function rankJourneys(journeys, sortBy = 'reliable') {
  const covered = journeys.filter((j) => j.prediction?.covered);
  const reliable = covered.length > 1
    ? covered.reduce((a, b) => (b.prediction.delay_p90_min < a.prediction.delay_p90_min ? b : a))
    : null;
  const fastest = journeys.length > 1
    ? journeys.reduce((a, b) => (b.duration_minutes < a.duration_minutes ? b : a))
    : null;

  const tagged = journeys.map((j) => {
    let label = null;
    if (reliable && keyOf(j) === keyOf(reliable)) label = { text: 'Most reliable', chip: 'green' };
    else if (fastest && keyOf(j) === keyOf(fastest)) {
      label = { text: 'Fastest on paper', chip: j.prediction?.risk_level === 'high' ? 'red' : 'amber' };
    }
    return { ...j, _label: label };
  });

  const byDeparture = (a, b) => a.departure_time.localeCompare(b.departure_time);
  if (sortBy === 'departure' || covered.length < 2) return tagged.sort(byDeparture);
  const p90 = (j) => (j.prediction?.covered ? j.prediction.delay_p90_min : Infinity);
  return tagged.sort((a, b) => p90(a) - p90(b) || byDeparture(a, b));
}

export function SortPills({ value, onChange }) {
  return (
    <div className="pills">
      {[['reliable', 'Most reliable first'], ['departure', 'Earliest first']].map(([id, name]) => (
        <button type="button" key={id} className={`pill ${value === id ? 'on' : ''}`} onClick={() => onChange(id)}>{name}</button>
      ))}
    </div>
  );
}

export function JourneyLabel({ journey }) {
  if (!journey._label) return null;
  return <span className={`chip ${journey._label.chip}`}>{journey._label.text}</span>;
}