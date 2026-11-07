const fmt = (d) => d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });

export function Header({ activeTab, setActiveTab, asOf }) {
  // "Live" only if the newest GPS fix is under 10 minutes old; otherwise say so honestly.
  const ageMin = asOf ? (Date.now() - asOf.getTime()) / 60000 : null;
  const state = ageMin === null ? 'off' : ageMin < 10 ? 'live' : 'stale';
  const label = state === 'off' ? 'No bus data'
    : state === 'live' ? `Live · Greater Manchester · ${fmt(asOf)}`
    : `Latest data · ${asOf.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} ${fmt(asOf)}`;

  return (
    <header className="header">
      <div className="header-left">
        <div className="tabs">
          {[['plan', 'Plan'], ['delay-map', 'Delay map']].map(([id, name]) => (
            <button key={id} className={`tab ${activeTab === id ? 'active' : ''}`} onClick={() => setActiveTab(id)}>
              {name}
            </button>
          ))}
        </div>
      </div>
      <div className="status">
        <span className={`dot ${state === 'live' ? '' : state}`} />
        {label}
      </div>
    </header>
  );
}