import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';

const hoveredStopIcon = L.divIcon({
  className: 'hovered-stop-pin',
  html: `
    <div class="hovered-stop-halo">
      <div class="hovered-stop-dot"></div>
    </div>
  `,
  iconSize: [40, 40],
  iconAnchor: [20, 20]
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
          zIndexOffset={1000}
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