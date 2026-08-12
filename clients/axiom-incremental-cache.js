export class AxiomIncrementalCache {
  constructor({
    manifestUrl = "/v1/publication/manifest.json",
    cacheName = "axiom-publication-v1",
  } = {}) {
    this.manifestUrl = manifestUrl;
    this.cacheName = cacheName;
    this.manifest = null;
  }

  async refreshManifest() {
    const cache = await caches.open(this.cacheName);
    const previousResponse = await cache.match(this.manifestUrl);
    const previous = previousResponse ? await previousResponse.clone().json() : null;
    const headers = new Headers();
    const previousEtag = previousResponse?.headers.get("ETag");
    if (previousEtag) headers.set("If-None-Match", previousEtag);
    const response = await fetch(this.manifestUrl, { headers, cache: "no-cache" });
    if (response.status === 304 && previous) {
      this.manifest = previous;
      return { manifest: previous, changedCompanyIds: [] };
    }
    if (!response.ok) throw new Error(`AXIOM manifest request failed: ${response.status}`);
    const manifest = await response.clone().json();
    await cache.put(this.manifestUrl, response);
    await this.#removeSupersededShards(cache, previous, manifest);
    this.manifest = manifest;
    return {
      manifest,
      changedCompanyIds: manifest.changed_company_ids || [],
      removedCompanyIds: manifest.removed_company_ids || [],
    };
  }

  async company(ticker) {
    if (!this.manifest) await this.refreshManifest();
    const normalized = String(ticker || "").trim().toUpperCase();
    const aliasFile = this.manifest.indexes?.ticker_to_file?.[normalized];
    const canonicalTicker = aliasFile ? aliasFile.replace(/\.json$/, "") : normalized;
    const entry = this.manifest.companies?.[canonicalTicker];
    if (!entry) throw new Error(`AXIOM company is not published: ${normalized}`);
    const cache = await caches.open(this.cacheName);
    let response = await cache.match(entry.url);
    if (!response) {
      response = await fetch(entry.url, { cache: "force-cache" });
      if (!response.ok) throw new Error(`AXIOM company request failed: ${response.status}`);
      await cache.put(entry.url, response.clone());
    }
    return response.json();
  }

  async #removeSupersededShards(cache, previous, current) {
    if (!previous?.companies) return;
    const currentUrls = new Set(Object.values(current.companies || {}).map((row) => row.url));
    await Promise.all(
      Object.values(previous.companies)
        .filter((row) => !currentUrls.has(row.url))
        .map((row) => cache.delete(row.url)),
    );
  }
}
