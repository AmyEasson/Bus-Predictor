import React from 'react';

export function Header({ activeTab, setActiveTab }) {
  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '16px 24px',
      backgroundColor: '#ffffff',
      borderBottom: '1px solid #e5e7eb',
      fontFamily: 'sans-serif'
    }}>
      {/* Navigation Pills (Plan / Delay map) */}
      <div style={{
        display: 'flex',
        backgroundColor: '#f3f4f6',
        padding: '4px',
        borderRadius: '9999px',
        gap: '4px'
      }}>
        <button
          onClick={() => setActiveTab('plan')}
          style={{
            padding: '6px 16px',
            fontSize: '14px',
            fontWeight: '500',
            borderRadius: '9999px',
            border: 'none',
            cursor: 'pointer',
            backgroundColor: activeTab === 'plan' ? '#2563eb' : 'transparent',
            color: activeTab === 'plan' ? '#ffffff' : '#4b5563',
            boxShadow: activeTab === 'plan' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none'
          }}
        >
          Plan
        </button>
        <button
          onClick={() => setActiveTab('delay-map')}
          style={{
            padding: '6px 16px',
            fontSize: '14px',
            fontWeight: '500',
            borderRadius: '9999px',
            border: 'none',
            cursor: 'pointer',
            backgroundColor: activeTab === 'delay-map' ? '#2563eb' : 'transparent',
            color: activeTab === 'delay-map' ? '#ffffff' : '#4b5563',
            boxShadow: activeTab === 'delay-map' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none'
          }}
        >
          Delay map
        </button>
      </div>

      {/* Live Status Indicator */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        fontSize: '12px',
        color: '#6b7280'
      }}>
        <span style={{
          width: '8px',
          height: '8px',
          borderRadius: '50%',
          backgroundColor: '#22c55e',
          display: 'inline-block'
        }}></span>
        <span>Live · Greater Manchester · 14:52</span>
      </div>
    </header>
  );
}