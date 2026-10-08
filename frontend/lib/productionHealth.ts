/** A narrow public readiness response; never forward backend payloads. */
export async function productionHealth(baseUrl: string, request: typeof fetch = fetch) {
  try {
    const response = await request(`${baseUrl.replace(/\/$/, "")}/health`, {
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(3000),
    });
    const data = await response.json();
    const status = data.status;
    if (!["healthy", "degraded", "unhealthy"].includes(status) || (response.status !== 200 && response.status !== 503) || (!response.ok && status !== "unhealthy")) {
      throw new Error("Invalid health response");
    }
    return { code: status === "unhealthy" ? 503 : 200, body: { status, frontend: "ok", backend: { reachable: true, status } } };
  } catch {
    return { code: 503, body: { status: "unhealthy", frontend: "ok", backend: { reachable: false, status: "unknown" } } };
  }
}
