import { useEffect } from 'react';
import { Polyline, Marker, Tooltip, useMap } from 'react-leaflet';
import L from 'leaflet';
import { BAND_COLOUR } from '../services/delayApi';
import { journeyKey, journeyPath, lineList } from './routeRanking';
import { RoadworksLayer } from './Roadworks';

const RELIABLE = '#2d55d4';
const FASTEST = '#d9534f';
const NO_DATA = '#9aa3af';

const esc = (s) => String(s).replace(/[<>&"]/g, '');
const mid = (path) => [(path[0][0] + path[1][0]) / 2, (path[0][1] + path[1][1]) / 2];

function callout(title, detail, tone) {
  return L.divIcon({
    className: 'callout-wrap',
    html: `<div class="callout ${tone}"><b>${esc(title)}</b>${detail ? `<span>${esc(detail)}</span>` : ''}</div>`,
    iconSize: [0, 0],
  });
}

// One journey drawn plainly (solid or dashed), used for the options before one is picked.
function PlainRoute({ journey, colour, dashed, faded }) {
  const path = journeyPath(journey);
  if (path.length < 2) return null;
  return (
    <>
      <Polyline positions={path} pathOptions={{ color: '#fff', weight: faded ? 6 : 9, opacity: faded ? 0.5 : 0.9 }} interactive={false} />
      <Polyline
        positions={path}
        pathOptions={{ color: colour, weight: faded ? 3 : 5, opacity: faded ? 0.55 : 0.95, dashArray: dashed ? '8 9' : null, lineCap: 'round' }}
        interactive={false}
      />
    </>
  );
}

// The chosen journey, each stretch coloured by how late buses typically are there.
function DelayRoute({ journey }) {
  const stretches = journey.insight?.stretches ?? [];
  if (!stretches.length) return <PlainRoute journey={journey} colour={RELIABLE} />;
  return (
    <>
      <Polyline positions={journeyPath(journey)} pathOptions={{ color: '#fff', weight: 10, opacity: 0.95 }} interactive={false} />
      {stretches.map((s, i) => (
        <Polyline
          key={`${s.from_stop_id}-${s.to_stop_id}-${i}`}
          positions={s.path}
          pathOptions={{ color: s.band ? BAND_COLOUR[s.band] : NO_DATA, weight: 6, opacity: 1, lineCap: 'round' }}
        >
          <Tooltip sticky>
            {s.name}
            <br />
            {s.minutes == null ? 'No past data for this stretch' : s.minutes < 1 ? 'Usually on time here' : `Usually +${Math.round(s.minutes)} min late here`}
          </Tooltip>
        </Polyline>
      ))}
    </>
  );
}

// Frames the given journeys, keeping clear of the floating panel on the left (keyed on the journeys, so
// re-renders don't move the map).
function FitTo({ journeys }) {
  const map = useMap();
  const key = journeys.map(journeyKey).join('|');
  useEffect(() => {
    const pts = journeys.flatMap(journeyPath);
    if (pts.length < 2) return;
    const narrow = map.getSize().x < 700;
    map.fitBounds(L.latLngBounds(pts), {
      paddingTopLeft: narrow ? [30, 260] : [450, 80],
      paddingBottomRight: [60, 60],
      maxZoom: 16,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

// Draws the journey options on the map: before a pick, most reliable (solid) vs fastest on paper (dashed);
// after a pick, the chosen route coloured by delay plus the alternative it was compared with, faded.
export function RouteOverlay({ routes, selected }) {
  if (!routes?.length) return null;
  const reliable = routes.find((r) => r._tag === 'reliable');
  const fastest = routes.find((r) => r._tag === 'fastest');

  if (!selected) {
    return (
      <>
        <FitTo journeys={[reliable, fastest].filter(Boolean)} />
        {fastest && <PlainRoute journey={fastest} colour={FASTEST} dashed />}
        {reliable && <PlainRoute journey={reliable} colour={RELIABLE} />}
      </>
    );
  }

  const sel = routes.find((r) => journeyKey(r) === journeyKey(selected)) ?? selected;
  const alt = sel._tag === 'reliable' ? fastest : reliable;
  const worst = sel.insight?.worst;
  const altWorst = alt && sel._tag === 'reliable' ? alt.insight?.worst : null;
  return (
    <>
      <FitTo journeys={[sel]} />
      {alt && journeyKey(alt) !== journeyKey(sel) && (
        <PlainRoute journey={alt} colour={alt._tag === 'fastest' ? FASTEST : RELIABLE} dashed={alt._tag === 'fastest'} faded />
      )}
      <DelayRoute journey={sel} />
      {sel.insight?.roadworks?.length > 0 && <RoadworksLayer data={{ works: sel.insight.roadworks }} />}
      {worst && (
        <Marker
          position={mid(worst.path)}
          icon={callout(`${worst.name} +${Math.round(worst.added_s / 60)} min`, 'Where this route usually loses time', 'bad')}
          interactive={false}
          zIndexOffset={800}
        />
      )}
      {altWorst && (
        <Marker
          position={mid(altWorst.path)}
          icon={callout(`Avoided: ${altWorst.name} +${Math.round(altWorst.added_s / 60)} min`, `on line ${lineList(alt).join(' › ')}`, 'muted')}
          interactive={false}
          zIndexOffset={700}
        />
      )}
    </>
  );
}

// Small key at the top of the map while options are shown.
export function RouteLegend({ routes, selected }) {
  if (!routes?.length) return null;
  const reliable = routes.find((r) => r._tag === 'reliable');
  const fastest = routes.find((r) => r._tag === 'fastest');
  if (selected) {
    return (
      <div className="map-key">
        <span><i className="sw grad" /> Coloured by how late buses usually are</span>
        {fastest && journeyKey(fastest) !== journeyKey(selected) && <span><i className="sw dash" /> Fastest on paper · {lineList(fastest).join(' › ')}</span>}
        {reliable && journeyKey(reliable) !== journeyKey(selected) && <span><i className="sw blue" /> Most reliable · {lineList(reliable).join(' › ')}</span>}
      </div>
    );
  }
  return (
    <div className="map-key">
      {reliable && <span><i className="sw blue" /> Most reliable · {lineList(reliable).join(' › ')}</span>}
      {fastest && <span><i className="sw dash" /> Fastest on paper · {lineList(fastest).join(' › ')}</span>}
    </div>
  );
}

