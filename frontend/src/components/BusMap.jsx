
import { useEffect } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  CircleMarker,
  Polyline,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';

const DEFAULT_CENTER = [53.4808, -2.2426];
const DEFAULT_ZOOM = 13;

const hoveredStopIcon = L.divIcon({
  className: 'hovered-stop-pin',
  html: `
    <div class="hovered-stop-halo">
      <div class="hovered-stop-dot"></div>
    </div>
  `,
  iconSize: [40, 40],
  iconAnchor: [20, 20],
});

// Converts stop coordinates into valid Leaflet coordinates.
function getStopPosition(stop) {
  const lat = Number(stop?.stop_lat);
  const lon = Number(stop?.stop_lon);

  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return null;
  }

  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return null;
  }

  return [lat, lon];
}

// Updates the map whenever a different journey is selected.
function JourneyMapUpdater({ selectedJourney, routePositions }) {
  const map = useMap();

  useEffect(() => {
    if (routePositions.length > 0) {
      const bounds = L.latLngBounds(routePositions);

      map.fitBounds(bounds, {
        padding: [50, 50],
        maxZoom: 15,
      });
    } else {
      map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    }
  }, [map, selectedJourney, routePositions]);

  return null;
}

export function BusMap({
  buses = [],
  hoveredStop = null,
  selectedJourney = null,
  children,
}) {
  const journeyStops = selectedJourney?.stops ?? [];

  const validJourneyStops = journeyStops
    .map((stop, index) => ({
      ...stop,
      position: getStopPosition(stop),
      index,
    }))
    .filter((stop) => stop.position !== null);

  const routePositions = validJourneyStops.map(
    (stop) => stop.position
  );

  const hoverPosition = getStopPosition(hoveredStop);

  const interchangeId = selectedJourney?.interchange_stop?.stop_id;

  return (
    <MapContainer
      center={DEFAULT_CENTER}
      zoom={DEFAULT_ZOOM}
      style={{ width: '100%', height: '100%' }}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution="&copy; OpenStreetMap contributors"
      />

      <JourneyMapUpdater
        selectedJourney={selectedJourney}
        routePositions={routePositions}
      />

      {/* Live bus markers */}
      {!selectedJourney &&
        buses.map((bus) => {
          if (bus.latitude == null || bus.longitude == null) {
            return null;
          }

          return (
            <Marker
              key={`${bus.operator_ref}-${bus.vehicle_ref}`}
              position={[bus.latitude, bus.longitude]}
            >
              <Popup>
                <b>Line {bus.published_line_name}</b>
                <br />
                Destination: {bus.destination_name || 'Unknown'}
              </Popup>
            </Marker>
          );
        })}

      {/* Stop hover preview */}
      {hoverPosition && (
        <Marker
          position={hoverPosition}
          icon={hoveredStopIcon}
          zIndexOffset={1000}
        >
          <Popup>
            <div>
              <strong>Preview Stop:</strong> {hoveredStop.stop_name}
              {hoveredStop.stop_code && (
                <div>Code: {hoveredStop.stop_code}</div>
              )}
            </div>
          </Popup>
        </Marker>
      )}

      {/* Selected journey route */}
      {routePositions.length > 1 && (
        <Polyline
          positions={routePositions}
          pathOptions={{
            color: '#276749',
            weight: 5,
            opacity: 0.85,
          }}
        />
      )}

      {/* Selected journey stops */}
      {validJourneyStops.map((stop, index) => {
        const isOrigin = index === 0;
        const isDestination = index === validJourneyStops.length - 1;
        const isInterchange =
          interchangeId != null &&
          stop.stop_id === interchangeId;

        return (
          <CircleMarker
            key={`${stop.stop_id}-${stop.index}`}
            center={stop.position}
            radius={isOrigin || isDestination ? 9 : isInterchange ? 8 : 5}
            pathOptions={{
              color: '#ffffff',
              fillColor: isOrigin
                ? '#38a169'
                : isDestination
                  ? '#1a4731'
                  : isInterchange
                    ? '#d69e2e'
                    : '#6b9b7a',
              fillOpacity: 1,
              weight: 2.5,
            }}
          >
            <Popup>
              <strong>{stop.stop_name}</strong>
              <div>
                {isOrigin
                  ? 'Origin'
                  : isDestination
                    ? 'Destination'
                    : isInterchange
                      ? 'Change buses here'
                      : 'Along the route'}
              </div>
              {stop.arrival_time && (
                <div>Arrival: {stop.arrival_time.slice(0, 5)}</div>
              )}
            </Popup>
          </CircleMarker>
        );
      })}

      {children}
    </MapContainer>
  );
}
