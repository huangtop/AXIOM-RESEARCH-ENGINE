export class AxiomValuationClient {
  constructor(baseUrl = "http://127.0.0.1:8765") {
    this.baseUrl = String(baseUrl).replace(/\/$/, "");
  }

  async value(symbol, { scenarioId = null, asOf = null, signal = null } = {}) {
    const normalized = String(symbol || "").trim().toUpperCase();
    if (!normalized) throw new Error("Ticker is required");

    const body = { symbol: normalized };
    if (scenarioId) body.scenario_id = scenarioId;
    if (asOf) body.as_of = asOf;

    let response;
    try {
      response = await fetch(`${this.baseUrl}/v1/valuations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      });
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      throw new Error("Unable to reach the AXIOM valuation API");
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error(`Valuation API returned invalid JSON (${response.status})`);
    }

    if (!response.ok) {
      const message = payload?.message || payload?.error || `Valuation failed (${response.status})`;
      const error = new Error(message);
      error.code = payload?.error || "valuation_failed";
      error.status = response.status;
      throw error;
    }
    return payload;
  }
}

export function fairValueFor(result, modelType) {
  return result?.models?.[modelType]?.fair_value ?? null;
}
