// OWNER: Member 4
// One place for all backend calls.
const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function get(path: string) {
  const response = await fetch(API_URL + path);
  return response.json();
}

export async function post(path: string, body: unknown = {}) {
  const response = await fetch(API_URL + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}

// Hello example: asks the 3 backend parts if they are alive.
export function checkHealth() {
  return Promise.all([
    get("/api/platform/health"),
    get("/api/ai/health"),
    get("/api/mock/health"),
  ]);
}
