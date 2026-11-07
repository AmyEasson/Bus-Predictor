import React, { useState, useEffect } from 'react';
import { fetchRoutes, fetchBusesForRoute } from './services/api';
import './App.css';

function App() {
  const [routes, setRoutes] = useState([]);
  const [selectedRoute, setSelectedRoute] = useState(null);
  const [buses, setBuses] = useState([]);
  const [loadingBuses, setLoadingBuses] = useState(false);

  // 1. Load all routes on component mount
  useEffect(() => {
    fetchRoutes().then(data => {
      setRoutes(data);
      if (data.length > 0) {
        setSelectedRoute(data[0].published_line_name);
      }
    });
  }, []);

  // 2. Fetch live buses whenever the selected route changes
  useEffect(() => {
    if (!selectedRoute) return;
    setLoadingBuses(true);
    fetchBusesForRoute(selectedRoute).then(data => {
      setBuses(data);
      setLoadingBuses(false);
    });
  }, [selectedRoute]);

  return (
    <div style={{ padding: '30px', fontFamily: 'system-ui, sans-serif', maxWidth: '1000px', margin: '0 auto' }}>
      <h1>🚌 Greater Manchester Bus Tracker</h1>

      {/* Route Selector Pills */}
      <div style={{ margin: '20px 0' }}>
        <h3>Select Route:</h3>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', maxHeight: '150px', overflowY: 'auto', padding: '5px', border: '1px solid #ddd', borderRadius: '6px' }}>
          {routes.map(r => (
            <button
              key={r.published_line_name}
              onClick={() => setSelectedRoute(r.published_line_name)}
              style={{
                padding: '8px 14px',
                background: selectedRoute === r.published_line_name ? '#0070f3' : '#f0f0f0',
                color: selectedRoute === r.published_line_name ? '#fff' : '#333',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: 'bold'
              }}
            >
              Line {r.published_line_name} <span style={{ fontSize: '0.8em', opacity: 0.8 }}>({r.active_buses})</span>
            </button>
          ))}
        </div>
      </div>

      <hr style={{ margin: '25px 0', border: 'none', borderTop: '1px solid #eee' }} />

      {/* Active Buses Display */}
      <h2>Live Positions for Line {selectedRoute}</h2>
      {loadingBuses ? (
        <p>Loading live vehicle positions...</p>
      ) : (
        <div style={{ overflowX: 'auto', border: '1px solid #e1e4e8', borderRadius: '6px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '14px' }}>
            <thead>
              <tr style={{ background: '#f6f8fa', borderBottom: '1px solid #e1e4e8' }}>
                <th style={{ padding: '12px' }}>Vehicle Ref</th>
                <th style={{ padding: '12px' }}>Destination</th>
                <th style={{ padding: '12px' }}>Latitude, Longitude</th>
                <th style={{ padding: '12px' }}>Heading</th>
                <th style={{ padding: '12px' }}>Recorded At (UTC)</th>
              </tr>
            </thead>
            <tbody>
              {buses.length === 0 ? (
                <tr>
                  <td colSpan="5" style={{ padding: '20px', textAlign: 'center', color: '#666' }}>No active buses found for this route right now.</td>
                </tr>
              ) : (
                buses.map((bus, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid #f0f0f0' }}>
                    <td style={{ padding: '10px', fontWeight: 'bold' }}>{bus.operator_ref}-{bus.vehicle_ref}</td>
                    <td style={{ padding: '10px' }}>{bus.destination_name || "Unknown"}</td>
                    <td style={{ padding: '10px', fontFamily: 'monospace' }}>{bus.latitude?.toFixed(4)}, {bus.longitude?.toFixed(4)}</td>
                    <td style={{ padding: '10px' }}>{bus.bearing ? `${bus.bearing}°` : "N/A"}</td>
                    <td style={{ padding: '10px', color: '#555' }}>{bus.recorded_at}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default App;