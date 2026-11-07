import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { BusMap } from './components/BusMap';
import { fetchAllLiveBuses } from './services/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('plan');
  const [fromLocation, setFromLocation] = useState('University of Manchester');
  const [toLocation, setToLocation] = useState('Piccadilly Gardens');
  const [timeMode, setTimeMode] = useState('Depart now');
  const [buses, setBuses] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // New state for Fix #3: Track if user clicked "Find routes"
  const [hasSearched, setHasSearched] = useState(false);
  const [mockRoutes, setMockRoutes] = useState([]);

  // Fetch all live buses on mount and poll every 15 seconds
  useEffect(() => {
    async function loadBuses() {
      setLoading(true);
      const data = await fetchAllLiveBuses();
      setBuses(data);
      setLoading(false);
    }
    
    loadBuses();
    const interval = setInterval(loadBuses, 15000);
    return () => clearInterval(interval);
  }, []);

  // Handle Find Routes click
  const handleFindRoutes = () => {
    setHasSearched(true);
    // Mock recommendations for your teammates to wire up later
    setMockRoutes([
      { id: 1, line: '42', name: 'Line 42 (Most Reliable)', time: '18 mins', delay: '+1m', badgeColor: '#059669', bg: '#ecfdf5' },
      { id: 2, line: '43', name: 'Line 43 (Fastest on Paper)', time: '15 mins', delay: '+4m', badgeColor: '#d97706', bg: '#fffbeb' },
      { id: 3, line: '142', name: 'Line 142 (Alternative)', time: '22 mins', delay: 'On time', badgeColor: '#2563eb', bg: '#eff6ff' }
    ]);
  };

  const handleResetSearch = () => {
    setHasSearched(false);
  };

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column', backgroundColor: '#f8fafc', fontFamily: 'sans-serif', color: '#1f2937' }}>
      {/* Fixed Header */}
      <Header activeTab={activeTab} setActiveTab={setActiveTab} />

      {/* Full Screen Main Content */}
      <div style={{ display: 'flex', flex: 1, padding: '16px', gap: '16px', height: 'calc(100vh - 65px)', overflow: 'hidden' }}>
        
        {/* Left Sidebar: Search & Results / Stats */}
        <div style={{ width: '380px', flexShrink: 0, backgroundColor: '#ffffff', borderRadius: '16px', padding: '24px', border: '1px solid #e5e7eb', boxShadow: '0 1px 3px rgba(0,0,0,0.05)', overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
          
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <h2 style={{ fontSize: '22px', fontWeight: '700', marginBottom: '4px' }}>Where to?</h2>
              <p style={{ fontSize: '12px', color: '#6b7280', marginBottom: '20px' }}>Routes ranked by predicted delay, not just the timetable.</p>
            </div>
            {hasSearched && (
              <button 
                onClick={handleResetSearch}
                style={{ background: 'none', border: 'none', color: '#2563eb', fontSize: '12px', fontWeight: '600', cursor: 'pointer', padding: '4px 8px' }}
              >
                ← Edit search
              </button>
            )}
          </div>

          {!hasSearched ? (
            <>
              {/* From / To Inputs */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px' }}>
                  <span style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#2563eb', marginRight: '12px' }}></span>
                  <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
                    <span style={{ fontSize: '10px', fontWeight: '600', color: '#9ca3af', textTransform: 'uppercase' }}>From</span>
                    <input
                      type="text"
                      value={fromLocation}
                      onChange={(e) => setFromLocation(e.target.value)}
                      style={{ border: 'none', background: 'transparent', fontSize: '14px', fontWeight: '500', outline: 'none', color: '#1f2937' }}
                    />
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '12px', padding: '12px' }}>
                  <span style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#ef4444', marginRight: '12px' }}></span>
                  <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
                    <span style={{ fontSize: '10px', fontWeight: '600', color: '#9ca3af', textTransform: 'uppercase' }}>To</span>
                    <input
                      type="text"
                      value={toLocation}
                      onChange={(e) => setToLocation(e.target.value)}
                      style={{ border: 'none', background: 'transparent', fontSize: '14px', fontWeight: '500', outline: 'none', color: '#1f2937' }}
                    />
                  </div>
                </div>
              </div>

              {/* Time Mode Pills */}
              <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
                {['Depart now', 'Arrive by', 'Tomorrow 08:15'].map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setTimeMode(mode)}
                    style={{
                      padding: '6px 12px',
                      borderRadius: '9999px',
                      fontSize: '12px',
                      fontWeight: '500',
                      cursor: 'pointer',
                      border: '1px solid',
                      backgroundColor: timeMode === mode ? '#111827' : '#ffffff',
                      color: timeMode === mode ? '#ffffff' : '#4b5563',
                      borderColor: timeMode === mode ? '#111827' : '#e5e7eb'
                    }}
                  >
                    {mode}
                  </button>
                ))}
              </div>

              {/* Find Routes Button */}
              <button 
                onClick={handleFindRoutes}
                style={{ width: '100%', backgroundColor: '#2563eb', color: '#ffffff', border: 'none', borderRadius: '12px', padding: '12px', fontSize: '14px', fontWeight: '600', cursor: 'pointer', marginBottom: '20px', transition: 'background 0.2s' }}
              >
                Find routes
              </button>

              {/* Delay Predictions Notice */}
              <div style={{ backgroundColor: '#ecfdf5', border: '1px solid #d1fae5', borderRadius: '12px', padding: '14px', display: 'flex', gap: '12px', marginBottom: '24px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#10b981', marginTop: '4px' }}></span>
                <div style={{ fontSize: '12px' }}>
                  <strong style={{ display: 'block', color: '#065f46', marginBottom: '2px' }}>Delay predictions on</strong>
                  <span style={{ color: '#047857' }}>Uses live bus positions, weather and local events</span>
                </div>
              </div>

              {/* Network Stats Cards */}
              <div style={{ marginTop: 'auto' }}>
                <span style={{ fontSize: '11px', fontWeight: '700', color: '#9ca3af', textTransform: 'uppercase', display: 'block', marginBottom: '12px' }}>Network right now</span>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
                  <div style={{ backgroundColor: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '10px', padding: '10px', textAlign: 'center' }}>
                    <span style={{ fontSize: '16px', fontWeight: '700', color: '#059669', display: 'block' }}>62%</span>
                    <span style={{ fontSize: '10px', color: '#6b7280' }}>buses on time</span>
                  </div>
                  <div style={{ backgroundColor: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '10px', padding: '10px', textAlign: 'center' }}>
                    <span style={{ fontSize: '16px', fontWeight: '700', color: '#dc2626', display: 'block' }}>14</span>
                    <span style={{ fontSize: '10px', color: '#6b7280' }}>delayed &gt; 5m</span>
                  </div>
                  <div style={{ backgroundColor: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: '10px', padding: '10px', textAlign: 'center' }}>
                    <span style={{ fontSize: '16px', fontWeight: '700', color: '#d97706', display: 'block' }}>+3m</span>
                    <span style={{ fontSize: '10px', color: '#6b7280' }}>avg delay</span>
                  </div>
                </div>
              </div>
            </>
          ) : (
            /* Searched Route Results View (Hook for your team's routing model) */
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', flex: 1, overflowY: 'auto' }}>
              <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '4px' }}>
                Showing recommendations from <strong>{fromLocation}</strong> to <strong>{toLocation}</strong>:
              </div>

              {mockRoutes.map((route) => (
                <div key={route.id} style={{ backgroundColor: route.bg, border: '1px solid #e5e7eb', borderRadius: '12px', padding: '14px', cursor: 'pointer' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <strong style={{ fontSize: '14px', color: '#1f2937' }}>{route.name}</strong>
                    <span style={{ fontSize: '12px', fontWeight: '700', color: route.badgeColor }}>{route.delay}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#4b5563' }}>
                    <span>Estimated trip: <strong>{route.time}</strong></span>
                    <span style={{ color: '#2563eb', fontWeight: '600' }}>View on map →</span>
                  </div>
                </div>
              ))}
            </div>
          )}

        </div>

        {/* Right Content Area: Map Container with Loading & Empty State Badges */}
        <div style={{ flex: 1, height: '100%', borderRadius: '16px', border: '1px solid #cbd5e1', overflow: 'hidden', position: 'relative' }}>
          {loading && (
            <div style={{ position: 'absolute', top: '16px', right: '16px', zIndex: 1000, backgroundColor: '#111827', color: '#ffffff', padding: '8px 16px', borderRadius: '9999px', fontSize: '12px', fontWeight: '600', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }}>
              Updating live positions...
            </div>
          )}
          {!loading && buses.length === 0 && (
            <div style={{ position: 'absolute', top: '16px', right: '16px', zIndex: 1000, backgroundColor: '#ef4444', color: '#ffffff', padding: '8px 16px', borderRadius: '9999px', fontSize: '12px', fontWeight: '600', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }}>
              No active buses found
            </div>
          )}
          <BusMap buses={buses} />
        </div>

      </div>
    </div>
  );
}