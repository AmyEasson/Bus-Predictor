import { MapContainer, TileLayer, Marker, Popup, CircleMarker, Polyline } from 'react-leaflet';
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

export function BusMap({
  buses = [],
  hoveredStop = null,
  selectedJourney = null,
  children
}) {
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
      {!selectedJourney && buses.map((bus) => {
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

      {/* Selected journey route line */}
      {selectedJourney?.stops?.length > 1 && (
        <Polyline
          positions={selectedJourney.stops
            .filter(stop => stop.stop_lat != null && stop.stop_lon != null)
            .map(stop => [stop.stop_lat, stop.stop_lon])}
          pathOptions={{
            color: '#276749',
            weight: 5,
            opacity: 0.85,
          }}
        />
      )}

      {/* Selected journey stops */}
      {selectedJourney?.stops?.map((stop, index) => {
        if (stop.stop_lat == null || stop.stop_lon == null) return null;

        const isOrigin = index === 0;
        const isDestination = index === selectedJourney.stops.length - 1;

        return (
          <CircleMarker
            key={`${selectedJourney.trip_id}-${stop.stop_sequence}`}
            center={[stop.stop_lat, stop.stop_lon]}
            radius={isOrigin || isDestination ? 9 : 5}
            pathOptions={{
              color: isOrigin ? '#ffffff' : '#276749',
              fillColor: isOrigin ? '#38a169' : isDestination ? '#1a4731' : '#6b9b7a',
              fillOpacity: 1,
              weight: 2.5,
            }}
          >
            <Popup>
              <strong>{stop.stop_name}</strong>
              <div>
                {isOrigin ? 'Origin' : isDestination ? 'Destination' : 'Along the route'}
              </div>
            </Popup>
          </CircleMarker>
        );
      })}

      {children}
    </MapContainer>
  );
}