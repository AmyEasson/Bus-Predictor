import React from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

// Fix for default marker icon missing issue in Leaflet + Vite
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

const DefaultIcon = L.icon({
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41]
});
L.Marker.prototype.options.icon = DefaultIcon;

const MANCHESTER_CENTER = [53.4808, -2.2426];

export function BusMap({ buses = [] }) {
  return (
    <div style={{ width: '100%', height: '100%', borderRadius: '16px', overflow: 'hidden' }}>
      <MapContainer
        center={MANCHESTER_CENTER}
        zoom={12}
        style={{ width: '100%', height: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {buses.map((bus, idx) => (
          bus.latitude && bus.longitude ? (
            <Marker key={idx} position={[bus.latitude, bus.longitude]}>
              <Popup>
                <div style={{ fontSize: '13px' }}>
                  <strong>Line {bus.published_line_name}</strong> to {bus.destination_name || 'N/A'}<br />
                  <span style={{ color: '#6b7280' }}>Bus Ref: {bus.vehicle_ref}</span>
                </div>
              </Popup>
            </Marker>
          ) : null
        ))}
      </MapContainer>
    </div>
  );
}