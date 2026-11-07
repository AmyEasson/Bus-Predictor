// Change this if your existing services/api.js uses a different base URL.
const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api';

export const BAND_COLOUR = {
  on_time: '#2f9e5b',
  minor: '#e0a030',
  moderate: '#d9534f',
  severe: '#8b1e2d',
};

// Same thresholds as the backend: under 2 min, 2-5, 5-8, 8+
export const bandOf = (m) => (m < 2 ? 'on_time' : m < 5 ? 'minor' : m < 8 ? 'moderate' : 'severe');

export async function fetchDelayMap({ hour, colourBy = 'overall', factors }) {
  const p = new URLSearchParams({ colour_by: colourBy });
  if (hour != null) p.set('hour', hour);
  if (factors) p.set('factors', factors.join(','));
  const res = await fetch(`${BASE}/delay-map?${p}`);
  if (!res.ok) throw new Error(`Delay map request failed (${res.status})`);
  return res.json();
}