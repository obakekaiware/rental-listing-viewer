(() => {
  const state = {
    listings: [],
    sortKey: "rent_yen",
    sortDir: 1, // 1 = asc, -1 = desc
    filterText: "",
    filterMadori: "",
    activeTowns: null, // null = no town restriction (show all); Set(...) once towns are known
    rentMin: null, // 円 (converted from the 万円 input)
    rentMax: null,
    mensekiMin: null, // m2
    mensekiMax: null,
  };

  const els = {
    body: document.getElementById("listing-body"),
    emptyMessage: document.getElementById("empty-message"),
    table: document.getElementById("listing-table"),
    filterInput: document.getElementById("filter-input"),
    madoriFilter: document.getElementById("madori-filter"),
    townFilter: document.getElementById("town-filter"),
    rentMin: document.getElementById("rent-min"),
    rentMax: document.getElementById("rent-max"),
    mensekiMin: document.getElementById("menseki-min"),
    mensekiMax: document.getElementById("menseki-max"),
    resultCount: document.getElementById("result-count"),
    lastUpdated: document.getElementById("last-updated"),
    scrapeBtn: document.getElementById("scrape-btn"),
    scrapeStatus: document.getElementById("scrape-status"),
    areaName: document.getElementById("area-name"),
  };

  function yen(v) {
    if (v === null || v === undefined) return "-";
    return (v / 10000).toLocaleString("ja-JP", { maximumFractionDigits: 1 }) + "万円";
  }

  function num(v, unit) {
    if (v === null || v === undefined) return "-";
    return v + unit;
  }

  function yenPerM2(v) {
    if (v === null || v === undefined) return "-";
    return Math.round(v).toLocaleString("ja-JP") + "円/m²";
  }

  function mapUrl(address) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;
  }

  // (賃料+管理費)を専有面積で割った㎡単価。同じ間取りの物件同士を比べるときの
  // 割安度の目安として使う (面積が違う物件を家賃だけで比べても意味が薄いため)。
  function computeUnitPrice(l) {
    if (!l.menseki_m2) return null;
    const monthly = (l.rent_yen || 0) + (l.admin_fee_yen || 0);
    return monthly / l.menseki_m2;
  }

  function render() {
    const text = state.filterText.trim().toLowerCase();
    let rows = state.listings.filter((l) => {
      if (state.filterMadori && l.madori !== state.filterMadori) return false;
      if (state.activeTowns && !state.activeTowns.has(l.town || "")) return false;
      if (state.rentMin !== null && (l.rent_yen === null || l.rent_yen < state.rentMin)) return false;
      if (state.rentMax !== null && (l.rent_yen === null || l.rent_yen > state.rentMax)) return false;
      if (state.mensekiMin !== null && (l.menseki_m2 === null || l.menseki_m2 < state.mensekiMin)) return false;
      if (state.mensekiMax !== null && (l.menseki_m2 === null || l.menseki_m2 > state.mensekiMax)) return false;
      if (!text) return true;
      const haystack = [l.building_name, l.address, ...(l.stations || [])]
        .join(" ")
        .toLowerCase();
      return haystack.includes(text);
    });

    rows.sort((a, b) => {
      const av = a[state.sortKey];
      const bv = b[state.sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (av < bv) return -1 * state.sortDir;
      if (av > bv) return 1 * state.sortDir;
      return 0;
    });

    els.body.innerHTML = "";
    for (const l of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${yen(l.rent_yen)}</td>
        <td>${yen(l.admin_fee_yen)}</td>
        <td>${l.madori || "-"}</td>
        <td>${num(l.menseki_m2, "m²")}</td>
        <td>${yenPerM2(l.unit_price_yen)}</td>
        <td>${l.building_name || "-"}</td>
        <td>${l.town || "-"}</td>
        <td>${l.address ? `${l.address} <a class="map-link" href="${mapUrl(l.address)}" target="_blank" rel="noopener">地図</a>` : "-"}</td>
        <td>${(l.stations || []).map((s) => `<span class="station-line">${s}</span>`).join("")}</td>
        <td>${l.age_text || "-"}</td>
        <td>${l.floor || "-"}</td>
        <td>${yen(l.deposit_yen)}</td>
        <td>${yen(l.gratuity_yen)}</td>
        <td>${l.detail_url ? `<a class="detail-link" href="${l.detail_url}" target="_blank" rel="noopener">SUUMOで見る</a>` : "-"}</td>
      `;
      els.body.appendChild(tr);
    }

    els.resultCount.textContent = `${rows.length} / ${state.listings.length} 件`;
    els.emptyMessage.classList.toggle("hidden", state.listings.length > 0);
    els.table.classList.toggle("hidden", state.listings.length === 0);

    for (const th of els.table.querySelectorAll("th[data-key]")) {
      const arrow = th.querySelector(".arrow");
      if (th.dataset.key === state.sortKey) {
        arrow.textContent = state.sortDir === 1 ? "▲" : "▼";
      } else {
        arrow.textContent = "";
      }
    }
  }

  function populateMadoriOptions() {
    const values = Array.from(new Set(state.listings.map((l) => l.madori).filter(Boolean))).sort();
    els.madoriFilter.innerHTML = '<option value="">間取り: すべて</option>';
    for (const v of values) {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      els.madoriFilter.appendChild(opt);
    }
  }

  function populateTownFilter() {
    const towns = Array.from(new Set(state.listings.map((l) => l.town).filter(Boolean))).sort();
    state.activeTowns = new Set(towns);
    els.townFilter.innerHTML = towns
      .map(
        (t) => `
        <label class="town-checkbox">
          <input type="checkbox" value="${t}" checked> ${t}
        </label>`
      )
      .join("");
  }

  els.townFilter.addEventListener("change", (e) => {
    if (e.target.tagName !== "INPUT") return;
    if (e.target.checked) {
      state.activeTowns.add(e.target.value);
    } else {
      state.activeTowns.delete(e.target.value);
    }
    render();
  });

  async function loadListings() {
    const res = await fetch("/api/listings");
    const data = await res.json();
    state.listings = (data.listings || []).map((l) => ({ ...l, unit_price_yen: computeUnitPrice(l) }));
    els.lastUpdated.textContent = data.scraped_at ? `最終取得: ${data.scraped_at}` : "";
    populateMadoriOptions();
    populateTownFilter();
    render();
  }

  els.table.querySelectorAll("th[data-key]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (state.sortKey === key) {
        state.sortDir *= -1;
      } else {
        state.sortKey = key;
        state.sortDir = 1;
      }
      render();
    });
  });

  els.filterInput.addEventListener("input", (e) => {
    state.filterText = e.target.value;
    render();
  });

  els.madoriFilter.addEventListener("change", (e) => {
    state.filterMadori = e.target.value;
    render();
  });

  function parseNullableFloat(str) {
    if (str === "" || str === null || str === undefined) return null;
    const v = parseFloat(str);
    return Number.isNaN(v) ? null : v;
  }

  els.rentMin.addEventListener("input", (e) => {
    const man = parseNullableFloat(e.target.value);
    state.rentMin = man === null ? null : Math.round(man * 10000);
    render();
  });

  els.rentMax.addEventListener("input", (e) => {
    const man = parseNullableFloat(e.target.value);
    state.rentMax = man === null ? null : Math.round(man * 10000);
    render();
  });

  els.mensekiMin.addEventListener("input", (e) => {
    state.mensekiMin = parseNullableFloat(e.target.value);
    render();
  });

  els.mensekiMax.addEventListener("input", (e) => {
    state.mensekiMax = parseNullableFloat(e.target.value);
    render();
  });

  let pollTimer = null;

  async function pollScrapeStatus() {
    const res = await fetch("/api/scrape/status");
    const status = await res.json();
    els.scrapeStatus.textContent = status.message || "";
    if (status.running) {
      pollTimer = setTimeout(pollScrapeStatus, 1500);
    } else {
      els.scrapeBtn.disabled = false;
      clearTimeout(pollTimer);
      loadListings();
    }
  }

  els.scrapeBtn.addEventListener("click", async () => {
    els.scrapeBtn.disabled = true;
    const res = await fetch("/api/scrape", { method: "POST" });
    if (res.status === 409) {
      els.scrapeBtn.disabled = false;
      return;
    }
    pollScrapeStatus();
  });

  loadListings();
})();
