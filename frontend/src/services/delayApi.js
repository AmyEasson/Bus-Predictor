import axios from 'axios';
import { API_BASE_URL } from './api';

export const BAND_COLOUR = {
  on_time: '#2f9e5b',
  minor: '#e0a030',
  moderate: '#d9534f',
  severe: '#8b1e2d',
};

// Same thresholds as the backend: under 2 min, 2-5, 5-8, 8+
export const bandOf = (m) => (m < 2 ? 'on_time' : m < 5 ? 'minor' : m < 8 ? 'moderate' : 'severe');

export async function fetchDelayMap({ hour, colourBy = 'overall', factors }) {
  const params = { colour_by: colourBy };
  if (hour != null) params.hour = hour;
  if (factors) params.factors = factors.join(',');
  try {
    const res = await axios.get(`${API_BASE_URL}/api/delay-map`, { params });
    return res.data;
  } catch (error) {
    // keep the old message shape: App.jsx shows error.message in the panel
    throw new Error(`Delay map request failed (${error.response?.status ?? error.message})`);
  }
}