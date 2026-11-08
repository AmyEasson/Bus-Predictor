export function Header({ activeTab, setActiveTab }) {
  // No live feed yet: everything shown is typical behaviour from the bus archive.
  const state = 'stale';
  const label = 'Greater Manchester · from past bus data, not live';

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