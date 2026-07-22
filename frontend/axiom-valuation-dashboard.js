import { AxiomValuationClient } from "./axiom-valuation-client.js";

const MODEL_ORDER = ["forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone"];
const MODEL_LABELS = {
  forward_pe: "Forward P/E",
  peg: "PEG",
  forward_ps: "Forward P/S",
  ev_ebitda: "EV / EBITDA",
  forward_pb: "Forward P/B",
  milestone: "Milestone",
};

const SCENARIO_LABELS = { bear: "Bear", base: "Base", bull: "Bull" };
const MODEL_STATUSES = ["completed", "skipped", "unavailable"];

function text(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function number(value, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(parsed);
}

function money(value, currency = "USD") {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency || "USD",
    maximumFractionDigits: 2,
  }).format(parsed);
}

function percent(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "percent",
    maximumFractionDigits: 1,
    signDisplay: "exceptZero",
  }).format(parsed);
}

function escapeHtml(value) {
  return text(value, "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function scenarioOptions(result) {
  return (result.available_scenarios || []).map((scenario) => {
    const selected = scenario.scenario_id === result.scenario_id ? " selected" : "";
    const label = SCENARIO_LABELS[scenario.scenario_type] || scenario.scenario_type;
    return `<option value="${escapeHtml(scenario.scenario_id)}"${selected}>${escapeHtml(label)} · ${escapeHtml(scenario.name)}</option>`;
  }).join("");
}

function warnings(model) {
  const items = model?.warnings || [];
  if (!items.length) return "";
  return `<ul class="axiom-model-warnings">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function modelCard(modelType, model, currency) {
  const status = model?.status || "unavailable";
  const applicability = model?.applicability || "unavailable";
  const fairValue = status === "completed" ? money(model.fair_value, currency) : "—";
  const upside = status === "completed" ? percent(model.upside) : "—";
  const reason = model?.reason_zh_tw || model?.reason || "此模型目前沒有可用結果。";
  return `
    <article class="axiom-model-card" data-model="${escapeHtml(modelType)}" data-status="${escapeHtml(status)}">
      <div class="axiom-model-card__head">
        <h3>${escapeHtml(MODEL_LABELS[modelType] || modelType)}</h3>
        <span class="axiom-status axiom-status--${escapeHtml(status)}">${escapeHtml(status)}</span>
      </div>
      <dl>
        <div><dt>Fair value</dt><dd>${fairValue}</dd></div>
        <div><dt>Upside</dt><dd>${upside}</dd></div>
        <div><dt>Eligibility</dt><dd>${escapeHtml(applicability)}</dd></div>
        <div><dt>Weight</dt><dd>${percent(model?.blend_weight)}</dd></div>
        <div><dt>Confidence</dt><dd>${percent(model?.confidence)}</dd></div>
      </dl>
      <p class="axiom-model-reason">${escapeHtml(reason)}</p>
      ${warnings(model)}
    </article>`;
}

function provenanceRows(provenance) {
  return Object.entries(provenance || {}).map(([key, value]) => `
    <tr><th scope="row">${escapeHtml(key)}</th><td>${escapeHtml(value)}</td></tr>`).join("");
}

export function renderValuation(result) {
  const currency = result.currency || "USD";
  const cards = MODEL_ORDER.map((type) => modelCard(type, result.models?.[type], currency)).join("");
  return `
    <section class="axiom-summary" aria-label="Valuation summary">
      <div><span>Ticker</span><strong>${escapeHtml(result.symbol)}</strong></div>
      <div><span>Scenario</span><strong>${escapeHtml(SCENARIO_LABELS[result.scenario_type] || result.scenario_type)}</strong></div>
      <div><span>Blended fair value</span><strong>${money(result.summary?.blended_fair_value, currency)}</strong></div>
      <div><span>Blended upside</span><strong>${percent(result.summary?.blended_upside)}</strong></div>
      <div><span>Reference price</span><strong>${money(result.reference_price, currency)}</strong></div>
      <div><span>Reference date</span><strong>${escapeHtml(result.reference_price_date)}</strong></div>
    </section>
    <div class="axiom-toolbar axiom-toolbar--scenario">
      <label>Scenario
        <select data-axiom-scenario>${scenarioOptions(result)}</select>
      </label>
      <span>${number(result.summary?.completed_models, 0)} / ${number(result.summary?.total_models, 0)} models completed</span>
    </div>
    <section class="axiom-model-grid" aria-label="Valuation models">${cards}</section>
    <details class="axiom-provenance">
      <summary>Data provenance</summary>
      <table><tbody>${provenanceRows(result.data_provenance)}</tbody></table>
      <p>Valuation as of ${escapeHtml(result.valuation_as_of)} · Price type ${escapeHtml(result.price_type)}</p>
    </details>`;
}

export function renderError(error) {
  const code = error?.code ? `<span class="axiom-error-code">${escapeHtml(error.code)}</span>` : "";
  return `<section class="axiom-error" role="alert"><h2>Valuation unavailable</h2><p>${escapeHtml(error?.message || "Unknown valuation error")}</p>${code}</section>`;
}

export class AxiomValuationDashboard {
  constructor(root, client = null) {
    if (!root) throw new Error("Dashboard root is required");
    this.root = root;
    this.client = client || new AxiomValuationClient(root.dataset.apiBase || "http://127.0.0.1:8765");
    this.abortController = null;
    this.result = null;
    this.bind();
  }

  bind() {
    const form = this.root.querySelector("[data-axiom-form]");
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      const ticker = this.root.querySelector("[data-axiom-ticker]")?.value;
      this.load(ticker);
    });
    this.root.addEventListener("change", (event) => {
      if (event.target.matches("[data-axiom-scenario]")) {
        const ticker = this.result?.symbol || this.root.querySelector("[data-axiom-ticker]")?.value;
        this.load(ticker, event.target.value);
      }
    });
  }

  async load(symbol, scenarioId = null) {
    if (this.abortController) this.abortController.abort();
    this.abortController = new AbortController();
    const output = this.root.querySelector("[data-axiom-output]");
    this.root.dataset.state = "loading";
    output.innerHTML = '<p class="axiom-loading" role="status">Loading valuation…</p>';
    try {
      this.result = await this.client.value(symbol, { scenarioId, signal: this.abortController.signal });
      output.innerHTML = renderValuation(this.result);
      this.root.dataset.state = "ready";
    } catch (error) {
      if (error?.name === "AbortError") return;
      this.result = null;
      output.innerHTML = renderError(error);
      this.root.dataset.state = "error";
    }
  }
}

export function mountAxiomValuationDashboards() {
  document.querySelectorAll("[data-axiom-dashboard]").forEach((root) => {
    const dashboard = new AxiomValuationDashboard(root);
    const initialTicker = root.dataset.initialTicker;
    if (initialTicker) dashboard.load(initialTicker);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountAxiomValuationDashboards);
} else {
  mountAxiomValuationDashboards();
}
