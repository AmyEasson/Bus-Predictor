const RISK = {
  low: { label: 'Low delay risk', chip: 'green' },
  medium: { label: 'Medium delay risk', chip: 'amber' },
  high: { label: 'High delay risk', chip: 'red' },
};

const REASONS = {
  model_unavailable: 'Delay model not loaded',
  route_not_in_training_data: 'No delay data for this route yet',
};

// Shows the model's prediction on a journey card (journey.prediction from /api/journeys).
export function PredictionBadge({ prediction }) {
  if (!prediction) return null;

  if (!prediction.covered) {
    return (
      <div className="meta" style={{ fontStyle: 'italic' }} title={prediction.reason}>
        {REASONS[prediction.reason] ?? 'Delay prediction unavailable'}
      </div>
    );
  }

  const { delay_p50_min: p50, arrival_p50, arrival_p90, risk_level, connection_at_risk } = prediction;
  const risk = RISK[risk_level] ?? RISK.medium;

  return (
    <>
      <div className="meta">
        <span className={`chip ${risk.chip}`}>{risk.label}</span>
        <span>{p50 < 1 ? 'Expected on time' : `Expected +${Math.round(p50)} min`}</span>
      </div>
      <div className="meta">
        <span>Typically arrives {arrival_p50}</span>
        <span>Safe by {arrival_p90}</span>
      </div>
      {prediction.mock && (
        <div className="meta" style={{ fontStyle: 'italic' }}>Sample prediction, not from the model</div>
      )}
      {connection_at_risk && (
        <div className="note warn">
          <div>
            <strong>Connection at risk</strong>
            The first bus may arrive after the second has left.
          </div>
        </div>
      )}
    </>
  );
}