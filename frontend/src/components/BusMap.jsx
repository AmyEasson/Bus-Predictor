import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';

const hoveredStopIcon = L.divIcon({
  className: 'hovered-stop-pin',
  html: '<div style="background-color: #ff9800; width: 16px; height: 16px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 5px rgba(0,0,0,0.5);"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8]
});

export function BusMap({ buses = [], hoveredStop = null, children }) {
  // Safely check if hoveredStop has valid numeric coordinates
  const hasValidHoverStop = 
    hoveredStop && 
    typeof hoveredStop.stop_lat === 'number' && 
    typeof hoveredStop.stop_lon === 'number';

  return (
    <MapContainer 
      center={[53.4808, -2.2426]} 
      zoom={13} 
      style={{ width: '100%', height: '100%' }}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; OpenStreetMap contributors'
      />

      {/* Render live buses safely */}
      {buses.map((bus) => {
        if (bus.latitude == null || bus.longitude == null) return null;
        return (
          <Marker 
            key={`${bus.operator_ref}-${bus.vehicle_ref}`} 
            position={[bus.latitude, bus.longitude]}
          >
            <Popup>
              <b>Line {bus.published_line_name}</b><br />
              Destination: {bus.destination_name || 'Unknown'}
            </Popup>
          </Marker>
        );
      })}

      {/* Render preview marker safely */}
      {hasValidHoverStop && (
        <Marker
          position={[hoveredStop.stop_lat, hoveredStop.stop_lon]}
          icon={hoveredStopIcon}
        >
          <Popup>
            <div>
              <strong>Preview Stop:</strong> {hoveredStop.stop_name}
              {hoveredStop.stop_code && <div>Code: {hoveredStop.stop_code}</div>}
            </div>
          </Popup>
        </Marker>
      )}

      {children}
    </MapContainer>
  );
}