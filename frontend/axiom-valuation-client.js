export class AxiomValuationClient {
  constructor(baseUrl = "http://127.0.0.1:8765") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async value(symbol, { scenarioId = null, asOf = null } = {}) {
    const body = { symbol: String(symbol).trim().toUpperCase() };
    if (scenarioId) body.scenario_id = scenarioId;
    if (asOf) body.as_of = asOf;
    const response = await fetch(`${this.baseUrl}/v1/valuations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || payload.error || "Valuation failed");
    return payload;
  }
}

export function fairValueFor(result, modelType) {
  return result?.models?.[modelType]?.fair_value ?? null;
}
