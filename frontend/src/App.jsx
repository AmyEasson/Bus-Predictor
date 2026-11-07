import React, { useState } from 'react';
import { Header } from './components/Header';
import { BusMap } from './components/BusMap';

export default function App() {
  const [activeTab, setActiveTab] = useState('plan');
  const [fromLocation, setFromLocation] = useState('University of Manchester');
  const [toLocation, setToLocation] = useState('Piccadilly Gardens');
  const [timeMode, setTimeMode] = useState('Depart now');

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column', backgroundColor: '#f8fafc', fontFamily: 'sans-serif', color: '#1f2937' }}>
      {/* Fixed Header */}
      <Header activeTab={activeTab} setActiveTab={setActiveTab} />

      {/* Full Screen Main Content */}
      <div style={{ display: 'flex', flex: 1, padding: '16px', gap: '16px', height: 'calc(100vh - 65px)', overflow: 'hidden' }}>
        
        {/* Left Sidebar: Search & Stats */}
        <div style={{ width: '380px', flexShrink: 0, backgroundColor: '#ffffff', borderRadius: '16px', padding: '24px', border: '1px solid #e5e7eb', boxShadow: '0 1px 3px rgba(0,0,0,0.05)', overflowY: 'auto' }}>
          <h2 style={{ fontSize: '22px', fontWeight: '700', marginBottom: '4px' }}>Where to?</h2>
          <p style={{ fontSize: '12px', color: '#6b7280', marginBottom: '20px' }}>Routes ranked by predicted delay, not just the timetable.</p>

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
          <button style={{ width: '100%', backgroundColor: '#2563eb', color: '#ffffff', border: 'none', borderRadius: '12px', padding: '12px', fontSize: '14px', fontWeight: '600', cursor: 'pointer', marginBottom: '20px' }}>
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
          <div>
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

        </div>

        <div style={{ flex: 1, height: '100%', borderRadius: '16px', border: '1px solid #cbd5e1', overflow: 'hidden' }}>
          <BusMap buses={[]} />
        </div>

      </div>
    </div>
  );
}