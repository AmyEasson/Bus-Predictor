
import { useEffect } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  CircleMarker,
  Polyline,
  ZoomControl,
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

// Fits the map to a journey when one is selected. Keyed on the route's coordinates as a string:
// routePositions is a new array on every render, and depending on it directly re-ran this effect (and
// snapped the map back) on every re-render, e.g. whenever the user panned with the delay layer on.
// When the journey is cleared the map is left where the user put it.
function JourneyMapUpdater({ routePositions }) {
  const map = useMap();
  const key = routePositions.map((p) => p.join(',')).join(';');

  useEffect(() => {
    if (!key) return;
    const positions = key.split(';').map((p) => p.split(',').map(Number));
    map.fitBounds(L.latLngBounds(positions), { padding: [50, 50], maxZoom: 15 });
  }, [map, key]);

  return null;
}

// A pin for a chosen stop (the searched place, or the start / end of directions).
const pinIcon = (kind) => L.divIcon({
  className: 'stop-pin-wrap',
  html: `<div class="stop-pin ${kind}"><div></div></div>`,
  iconSize: [28, 36],
  iconAnchor: [14, 34],
});

// Pans to a stop when it is picked from search (keyed on the stop id, not the object).
function FocusStop({ stop }) {
  const map = useMap();
  const id = stop?.stop_id;
  useEffect(() => {
    const pos = getStopPosition(stop);
    if (pos) map.flyTo(pos, Math.max(map.getZoom(), 16), { duration: 0.6 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, id]);
  return null;
}

// Frames the start and end of a directions search (before a route is picked), keyed on their ids.
function FitPins({ pins }) {
  const map = useMap();
  const key = pins.map((p) => p.stop.stop_id).join('|');
  useEffect(() => {
    const pos = pins.map((p) => getStopPosition(p.stop)).filter(Boolean);
    if (pos.length === 2) map.fitBounds(L.latLngBounds(pos), { padding: [80, 80], maxZoom: 15 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

export function BusMap({
  hoveredStop = null,
  selectedJourney = null,
  pins = [],        // [{ stop, kind: 'place' | 'from' | 'to' }]
  focusStop = null, // stop (or any {stop_id, stop_lat, stop_lon}) to pan to
  drawRoute = true, // false when a RouteOverlay child draws the journey line itself
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
      preferCanvas  // draw shapes on one canvas instead of thousands of SVG elements: smoother pan/zoom
      zoomControl={false}
    >
      {/* bottom right, out from under the floating search panel */}
      <ZoomControl position="bottomright" />
      <FocusStop stop={focusStop} />
      {!selectedJourney && <FitPins pins={pins} />}
      {/* Stadia "Alidade Smooth": pale, low-contrast basemap so the coloured delay lines stand out.
          No API key needed on localhost. To deploy on a real domain, create a free Stadia Maps account
          and add the domain there (no key goes in the code). */}
      <TileLayer
        url="https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}{r}.png"
        maxZoom={20}
        attribution='&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />

      {drawRoute && <JourneyMapUpdater routePositions={routePositions} />}

      {/* Chosen stops (hidden while a journey is drawn; it has its own start/end markers) */}
      {!selectedJourney && pins.map(({ stop, kind }) => {
        const pos = getStopPosition(stop);
        return pos && (
          <Marker key={`${kind}-${stop.stop_id}`} position={pos} icon={pinIcon(kind)} zIndexOffset={900} />
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
      {drawRoute && routePositions.length > 1 && (
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
