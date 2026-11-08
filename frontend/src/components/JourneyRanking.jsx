
const keyOf = (journey) => {
  if (journey.journey_type === 'transfer') {
    return journey.legs.map((leg) => leg.trip_id).join('-');
  }

  return journey.trip_id;
};

export function rankJourneys(journeys, sortBy = 'reliable') {
  if (!journeys.length) return [];

  const allHavePredictions = journeys.every(
    (journey) => journey.prediction?.covered &&
      Number.isFinite(journey.prediction.delay_p90_min)
  );

  const fastest = journeys.reduce((best, journey) =>
    journey.duration_minutes < best.duration_minutes ? journey : best
  );

  const mostReliable = allHavePredictions && journeys.length > 1
    ? journeys.reduce((best, journey) =>
        journey.prediction.delay_p90_min < best.prediction.delay_p90_min
          ? journey
          : best
      )
    : null;

  const tagged = journeys.map((journey) => {
    let label = null;

    if (mostReliable && keyOf(journey) === keyOf(mostReliable)) {
      label = { text: 'Most reliable', chip: 'green' };
    } else if (journeys.length > 1 && keyOf(journey) === keyOf(fastest)) {
      label = {
        text: 'Fastest on paper',
        chip: journey.prediction?.risk_level === 'high' ? 'red' : 'amber',
      };
    }

    return { ...journey, _label: label };
  });

  const byDeparture = (a, b) =>
    a.departure_time.localeCompare(b.departure_time);

  if (sortBy === 'departure') {
    return tagged.sort(byDeparture);
  }

  const predictedDelay = (journey) =>
    journey.prediction?.covered &&
    Number.isFinite(journey.prediction.delay_p90_min)
      ? journey.prediction.delay_p90_min
      : Infinity;

  return tagged.sort(
    (a, b) => predictedDelay(a) - predictedDelay(b) ||
      byDeparture(a, b)
  );
}

export function SortPills({ value, onChange }) {
  return (
    <div className="pills">
      {[
        ['reliable', 'Most reliable first'],
        ['departure', 'Earliest first'],
      ].map(([id, name]) => (
        <button
          type="button"
          key={id}
          className={`pill ${value === id ? 'on' : ''}`}
          onClick={() => onChange(id)}
        >
          {name}
        </button>
      ))}
    </div>
  );
}

export function JourneyLabel({ journey }) {
  if (!journey._label) return null;

  return (
    <span className={`chip ${journey._label.chip}`}>
      {journey._label.text}
    </span>
  );
}
