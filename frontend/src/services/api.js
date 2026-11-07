// frontend/src/services/api.js
const API_BASE_URL = "http://localhost:8000";

export async function fetchRoutes() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/routes`);
    if (!res.ok) throw new Error("Failed to fetch routes");
    return await res.json();
  } catch (error) {
    console.error("API Error (fetchRoutes):", error);
    return [];
  }
}

export async function fetchBusesForRoute(lineName) {
  try {
    const res = await fetch(`${API_BASE_URL}/api/buses/${lineName}`);
    if (!res.ok) throw new Error(`Failed to fetch buses for line ${lineName}`);
    return await res.json();
  } catch (error) {
    console.error("API Error (fetchBusesForRoute):", error);
    return [];
  }
}