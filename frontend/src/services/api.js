import axios from 'axios';

// Override with VITE_API_URL in frontend/.env (e.g. VITE_API_URL=http://localhost:8000)
export const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

// Fetch summary active routes (for sidebar counts or route options)
export async function fetchRoutes() {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/routes`);
    return response.data;
  } catch (error) {
    console.error('Error fetching routes:', error);
    return [];
  }
}

// Fetch actual GPS positions for a specific route line (e.g. "42")
export async function fetchBusPositionsForRoute(lineName = "42") {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/buses/${lineName}`);
    return response.data; // Returns array of bus objects with latitude, longitude, vehicle_ref, etc.
  } catch (error) {
    console.error(`Error fetching positions for line ${lineName}:`, error);
    return [];
  }
}

// Fetch all live bus positions across all routes for the default map view
export async function fetchAllLiveBuses() {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/buses/all/live`);
    return response.data; // Returns array of all active bus objects
  } catch (error) {
    console.error('Error fetching all live buses:', error);
    return [];
  }
}

// Search available stops by name
export async function searchStops(query) {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/stops/search`, {
      params: { q: query, limit: 10 }
    });
    return response.data;
  } catch (error) {
    console.error('Error searching stops:', error);
    return [];
  }
}

// Search for direct bus journeys
export async function fetchJourneys({
  originStopId,
  destinationStopId,
  travelDate,
  limit = 10,
  departureAfter = null,
  arriveBy = null,
  includeStops = true,
}) {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/journeys`, {
      params: {
        origin_stop_id: originStopId,
        destination_stop_id: destinationStopId,
        travel_date: travelDate,
        limit,
        departure_after: departureAfter || undefined,
        arrive_by: arriveBy || undefined,
        include_stops: includeStops,
      },
    });

    return response.data;
  } catch (error) {
    console.error('Error fetching journeys:', error);
    throw error;
  }
}
// Stop card: the stop, lines serving it, next departures today and typical delay there now
export async function fetchStopInfo(stopId) {
  const response = await axios.get(`${API_BASE_URL}/api/stops/${encodeURIComponent(stopId)}`);
  return response.data;
}
