(function () {
  'use strict';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const num = (value, digits = 2) => Number.isFinite(Number(value)) ? Number(value).toLocaleString(undefined, {maximumFractionDigits: digits}) : '—';
  const money = (row, fallbackCurrency = 'USD') => {
    const value = row && typeof row === 'object' ? row.value : row;
    const currency = row && typeof row === 'object' ? (row.currency || fallbackCurrency) : fallbackCurrency;
    return Number.isFinite(Number(value)) ? new Intl.NumberFormat(undefined, {style:'currency', currency, maximumFractionDigits:2}).format(Number(value)) : '—';
  };
  const pct = value => Number.isFinite(Number(value)) ? new Intl.NumberFormat(undefined, {style:'percent', maximumFractionDigits:1, signDisplay:'exceptZero'}).format(Number(value)) : '—';
  const statusZh = status => ({completed:'完整', partial:'部分', unavailable:'無資料', available:'可用', awaiting_canonical_data:'等待 Canonical Data', awaiting_storage_adapter:'等待筆記儲存層', awaiting_news_adapter:'等待新聞 Adapter'})[status] || status || '無資料';

  function emptyState(title, message) {
    return `<div class="axiom-empty"><strong>${esc(title)}</strong><p>${esc(message)}</p></div>`;
  }

  function diagnostics(card) {
    const rows = card.quality_diagnostics || [];
    if (!rows.length) return '<div class="axiom-quality axiom-quality--ok">未發現資料品質警告</div>';
    return `<div class="axiom-quality-list">${rows.map(row => `<div class="axiom-quality"><span>${esc(row.severity)}</span><strong>${esc(row.code)}</strong><p>${esc(row.message)}</p></div>`).join('')}</div>`;
  }

  function overview(card) {
    const profile = card.profile || {};
    const market = card.market || {};
    const confidence = card.research_confidence || {};
    return `<section class="axiom-panel active" data-panel="overview">
      <div class="axiom-kpis">
        <div><span>目前股價</span><strong>${money(market.current_price)}</strong><small>${esc(market.current_price?.as_of || '')}</small></div>
        <div><span>今日變動</span><strong>${pct(market.price_change)}</strong><small>相對前收 ${money(market.previous_close)}</small></div>
        <div><span>研究信心</span><strong>${num(confidence.score,0)} / 100</strong><small>${esc(statusZh(card.status))}</small></div>
        <div><span>市值</span><strong>${money(market.market_cap)}</strong><small>Beta ${num(market.beta?.value)}</small></div>
      </div>
      <div class="axiom-two-col">
        <article class="axiom-card"><h3>公司摘要</h3><p>${esc(profile.business_description || 'Canonical Company Registry 尚未提供公司描述。')}</p><dl><div><dt>公司</dt><dd>${esc(profile.display_name || card.ticker)}</dd></div><div><dt>產業</dt><dd>${esc(profile.official_industry || '—')}</dd></div><div><dt>國家</dt><dd>${esc(profile.country || '—')}</dd></div></dl></article>
        <article class="axiom-card"><h3>資料品質</h3>${diagnostics(card)}</article>
      </div>
    </section>`;
  }

  function companyAnalysis(card) {
    const p = card.profile || {};
    const f = card.financials || {};
    const e = card.estimates || {};
    return `<section class="axiom-panel" data-panel="company-analysis"><div class="axiom-two-col">
      <article class="axiom-card"><h3>公司解析</h3><p>${esc(p.business_description || '公司解析等待 Company Registry 補齊 business_description。')}</p><dl><div><dt>Legal name</dt><dd>${esc(p.legal_name || '—')}</dd></div><div><dt>Sector</dt><dd>${esc(p.official_sector || '—')}</dd></div><div><dt>Industry</dt><dd>${esc(p.official_industry || '—')}</dd></div></dl></article>
      <article class="axiom-card"><h3>財務與預估摘要</h3><dl><div><dt>營業現金流</dt><dd>${money(f.operating_cash_flow)}</dd></div><div><dt>資本支出</dt><dd>${money(f.capital_expenditures)}</dd></div><div><dt>前瞻營收</dt><dd>${money(e.revenue)}</dd></div><div><dt>前瞻 EPS</dt><dd>${money(e.diluted_eps)}</dd></div></dl></article>
    </div></section>`;
  }

  function valuation(card) {
    const scenarios = card.valuation || {};
    return `<section class="axiom-panel" data-panel="valuation"><div class="axiom-scenarios">${['bear','base','bull'].map(name => {
      const row = scenarios[name] || {};
      return `<article class="axiom-scenario axiom-scenario--${name}"><div class="axiom-scenario-head"><h3>${name.toUpperCase()}</h3><span>${esc(statusZh(row.status))}</span></div><strong>${money(row.fair_value)}</strong><dl><div><dt>目前股價</dt><dd>${money(row.current_price)}</dd></div><div><dt>潛在空間</dt><dd>${pct(row.upside)}</dd></div><div><dt>估值信心</dt><dd>${num(row.confidence,0)} / 100</dd></div></dl></article>`;
    }).join('')}</div><article class="axiom-card"><h3>研究層品質說明</h3>${diagnostics(card)}</article></section>`;
  }

  function ranking(card) {
    const data = card.analyst_growth_ranking || {};
    const rows = data.universe || [];
    if (!rows.length) return `<section class="axiom-panel" data-panel="ranking">${emptyState('分析師預估成長排名已保留', '目前 Research Bundle 缺少可比較的歷史營收或淨利基準，因此不產生假排名。')}</section>`;
    return `<section class="axiom-panel" data-panel="ranking"><article class="axiom-card"><h3>分析師預估成長排名</h3><div class="axiom-table-wrap"><table><thead><tr><th>排名</th><th>公司</th><th>指標</th><th>成長率</th></tr></thead><tbody>${rows.map(row => `<tr class="${row.company_id === card.company_id ? 'is-current' : ''}"><td>${row.rank}</td><td>${esc(row.ticker)} · ${esc(row.display_name || '')}</td><td>${esc(row.metric)}</td><td>${pct(row.growth)}</td></tr>`).join('')}</tbody></table></div></article></section>`;
  }

  function render(card) {
    const profile = card.profile || {};
    return `<header class="axiom-header"><div><span class="axiom-eyebrow">AXIOM RESEARCH ENGINE</span><h2>${esc(card.ticker)} · ${esc(profile.display_name || '')}</h2><p>Canonical Research Bundle 驅動的估值決策卡</p></div><div class="axiom-badges"><span>${esc(statusZh(card.status))}</span><strong>${num(card.research_confidence?.score,0)}</strong></div></header>
      <nav class="axiom-tabs" aria-label="Research sections">
        <button class="active" data-tab="overview">總覽</button><button data-tab="company-analysis">公司解析</button><button data-tab="industry-map">產業鏈地圖</button><button data-tab="research-notes">研究筆記</button><button data-tab="valuation">估值</button><button data-tab="ranking">分析師預估成長排名</button><button data-tab="news">相關新聞</button>
      </nav>
      ${overview(card)}${companyAnalysis(card)}
      <section class="axiom-panel" data-panel="industry-map">${emptyState('產業鏈地圖接口已保留', '等待 canonical industry graph adapter；本版不從舊估值內容拼接產業資料。')}</section>
      <section class="axiom-panel" data-panel="research-notes">${emptyState('研究筆記接口已保留', '等待使用者筆記儲存層；Research Engine 不會把筆記寫入 canonical bundle。')}</section>
      ${valuation(card)}${ranking(card)}
      <section class="axiom-panel" data-panel="news">${emptyState('相關新聞接口已保留', '等待 news provider adapter；本版不直接從前端抓取新聞。')}</section>
      <details class="axiom-provenance"><summary>Canonical provenance</summary><pre>${esc(JSON.stringify({research_bundle_id:card.research_bundle_id, source_record_ids:card.source_record_ids}, null, 2))}</pre></details>`;
  }

  class ValuationCard {
    constructor(root) {
      this.root = root;
      this.output = root.querySelector('[data-axiom-output]');
      this.input = root.querySelector('[data-axiom-ticker]');
      this.abort = null;
      root.querySelector('[data-axiom-form]')?.addEventListener('submit', event => { event.preventDefault(); this.load(this.input.value); });
      root.addEventListener('click', event => {
        const button = event.target.closest('[data-tab]');
        if (!button) return;
        root.querySelectorAll('[data-tab]').forEach(el => el.classList.toggle('active', el === button));
        root.querySelectorAll('[data-panel]').forEach(el => el.classList.toggle('active', el.dataset.panel === button.dataset.tab));
      });
      this.load(root.dataset.initialTicker || 'NVDA');
    }

    async load(ticker) {
      ticker = String(ticker || '').trim().toUpperCase();
      if (!ticker) return;
      this.input.value = ticker;
      if (this.abort) this.abort.abort();
      this.abort = new AbortController();
      this.root.dataset.state = 'loading';
      this.output.innerHTML = '<div class="axiom-loading">正在讀取 Canonical Research Bundle…</div>';
      try {
        const response = await fetch(this.root.dataset.endpoint, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ticker}), signal:this.abort.signal});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
        this.output.innerHTML = render(payload);
        this.root.dataset.state = 'ready';
      } catch (error) {
        if (error.name === 'AbortError') return;
        this.root.dataset.state = 'error';
        this.output.innerHTML = `<div class="axiom-error"><strong>研究估值卡載入失敗</strong><p>${esc(error.message)}</p><small>請確認 V026.0 已生成 data/research_data/company_research.json，且 Research Card API 已啟動。</small></div>`;
      }
    }
  }

  function boot() { document.querySelectorAll('[data-axiom-valuation-card]').forEach(root => { if (!root.__axiomCard) root.__axiomCard = new ValuationCard(root); }); }
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', boot) : boot();
})();
