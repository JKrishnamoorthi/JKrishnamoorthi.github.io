const API_URL = "https://export.arxiv.org/api/query";
const FAV_KEY = "krishnamoorthi_arxiv_favourites_v1";

const CATEGORY_LABELS = {
  "hep-ph": "hep-ph",
  "hep-ex": "hep-ex",
  "hep-th": "hep-th",
  "nucl-th": "nucl-th",
  "astro-ph.HE": "astro-ph.HE",
  "astro-ph.CO": "astro-ph.CO",
  "physics.ins-det": "physics.ins-det"
};

let searchMode = "keyword";
let papers = [];
let dailyData = [];

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
  $("year").textContent = new Date().getFullYear();

  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      searchMode = button.dataset.mode;
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      $("searchInput").placeholder =
        searchMode === "author"
          ? "e.g. Sanjib Kumar Agarwalla"
          : "e.g. neutrino oscillation, Earth tomography, NSI";
    });
  });

  $("searchButton").addEventListener("click", runSearch);
  $("searchInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") runSearch();
  });

  $("myFavouritesButton").addEventListener("click", () => {
    $("favouritesSection").classList.remove("hidden");
    renderFavourites();
    $("favouritesSection").scrollIntoView({ behavior: "smooth" });
  });

  $("clearFavourites").addEventListener("click", () => {
    localStorage.removeItem(FAV_KEY);
    renderFavourites();
    renderCurrentResults();
  });

  $("activityRange").addEventListener("change", () => renderActivity(dailyData));
  document.querySelectorAll(".category-toggle").forEach((checkbox) => {
    checkbox.addEventListener("change", () => renderActivity(dailyData));
  });

  loadDailyData();
});

async function runSearch() {
  const query = $("searchInput").value.trim();
  const category = $("category").value;
  const maxResults = $("maxResults").value;

  if (!query) {
    setStatus("Enter a keyword or author name first.");
    return;
  }

  setStatus("Searching arXiv…");
  $("searchButton").disabled = true;

  try {
    const params = new URLSearchParams({
      search_query: buildSearchQuery(query, category),
      start: "0",
      max_results: maxResults,
      sortBy: "submittedDate",
      sortOrder: "descending"
    });

    const response = await fetch(`${API_URL}?${params.toString()}`);
    if (!response.ok) throw new Error(`arXiv returned HTTP ${response.status}`);

    papers = parseArxivXML(await response.text());
    renderPapers(papers);

    $("resultsTitle").textContent =
      searchMode === "author" ? `Papers by ${query}` : "Search results";
    $("resultsSubtitle").textContent =
      `${papers.length} result${papers.length === 1 ? "" : "s"} · sorted by submission date`;
    setStatus(`Found ${papers.length} paper${papers.length === 1 ? "" : "s"}.`);
  } catch (error) {
    console.error(error);
    setStatus("The live arXiv API could not be reached from this browser.");
    $("results").innerHTML = `
      <div class="empty-state card">
        <strong>Search request failed.</strong>
        <span>${escapeHTML(error.message)}</span>
        <span>Try again later or use the cached statistics.</span>
      </div>`;
  } finally {
    $("searchButton").disabled = false;
  }
}

function buildSearchQuery(query, category) {
  const escaped = query.replace(/"/g, '\\"');
  let base = searchMode === "author" ? `au:"${escaped}"` : `all:"${escaped}"`;
  if (category) base += ` AND cat:${category}`;
  return base;
}

function parseArxivXML(xmlText) {
  const xml = new DOMParser().parseFromString(xmlText, "application/xml");
  const entries = [...xml.getElementsByTagName("entry")];

  return entries.map((entry) => {
    const text = (tag) => entry.getElementsByTagName(tag)[0]?.textContent?.trim() || "";
    const links = [...entry.getElementsByTagName("link")];

    const absLink =
      links.find((l) => l.getAttribute("type") === "text/html")?.getAttribute("href") ||
      text("id");

    const pdfLink =
      links.find((l) => l.getAttribute("title") === "pdf")?.getAttribute("href") || "";

    const authors = [...entry.getElementsByTagName("author")]
      .map((a) => a.getElementsByTagName("name")[0]?.textContent?.trim())
      .filter(Boolean);

    const categories = [...entry.getElementsByTagName("category")]
      .map((c) => c.getAttribute("term"))
      .filter(Boolean);

    return {
      id: text("id"),
      title: text("title").replace(/\s+/g, " "),
      summary: text("summary").replace(/\s+/g, " "),
      authors,
      categories,
      published: text("published"),
      updated: text("updated"),
      absLink,
      pdfLink
    };
  });
}

function renderPapers(list) {
  const container = $("results");

  if (!list.length) {
    container.innerHTML = `
      <div class="empty-state card">
        <strong>No papers found.</strong>
        <span>Try a broader keyword, author name, or remove the category filter.</span>
      </div>`;
    return;
  }

  container.innerHTML = list.map(paperHTML).join("");
  bindFavouriteButtons();
}

function renderCurrentResults() {
  if (papers.length) renderPapers(papers);
}

function paperHTML(paper) {
  const saved = getFavourites().some((p) => p.id === paper.id);
  const date = formatDate(paper.published);
  const authors = paper.authors.join(", ");
  const categories = paper.categories.slice(0, 3);

  return `
    <article class="paper">
      <div class="paper-top">
        <div>
          <div class="paper-title">
            <a href="${escapeAttr(paper.absLink)}" target="_blank" rel="noopener">
              ${escapeHTML(paper.title)}
            </a>
          </div>
          <div class="paper-authors">${escapeHTML(authors)}</div>
        </div>
        <button class="fav-button ${saved ? "saved" : ""}"
                data-id="${escapeAttr(paper.id)}"
                title="${saved ? "Remove from favourites" : "Add to favourites"}"
                aria-label="${saved ? "Remove from favourites" : "Add to favourites"}">
          ${saved ? "★" : "☆"}
        </button>
      </div>

      <div class="paper-meta">
        ${categories.map((c) => `<span class="tag">${escapeHTML(c)}</span>`).join("")}
        <span class="tag">${escapeHTML(date)}</span>
      </div>

      <p class="paper-abstract">${escapeHTML(truncate(paper.summary, 520))}</p>

      <div class="paper-actions">
        <a href="${escapeAttr(paper.absLink)}" target="_blank" rel="noopener">Abstract ↗</a>
        ${paper.pdfLink ? `<a href="${escapeAttr(paper.pdfLink)}" target="_blank" rel="noopener">PDF ↗</a>` : ""}
        <button class="copy-id" data-id="${escapeAttr(paper.id)}">Copy arXiv ID</button>
      </div>
    </article>`;
}

function bindFavouriteButtons() {
  document.querySelectorAll(".fav-button").forEach((button) => {
    button.addEventListener("click", () => {
      const paper = findPaper(button.dataset.id);
      if (paper) toggleFavourite(paper);
    });
  });

  document.querySelectorAll(".copy-id").forEach((button) => {
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.id);
      const old = button.textContent;
      button.textContent = "Copied";
      setTimeout(() => button.textContent = old, 1000);
    });
  });
}

function toggleFavourite(paper) {
  let favourites = getFavourites();
  const exists = favourites.some((p) => p.id === paper.id);

  favourites = exists
    ? favourites.filter((p) => p.id !== paper.id)
    : [paper, ...favourites];

  localStorage.setItem(FAV_KEY, JSON.stringify(favourites));
  renderCurrentResults();
  renderFavourites();
}

function getFavourites() {
  try {
    return JSON.parse(localStorage.getItem(FAV_KEY) || "[]");
  } catch {
    return [];
  }
}

function renderFavourites() {
  const container = $("favouritesSection");
  const list = $("favourites");
  const favourites = getFavourites();

  if (!favourites.length) {
    list.innerHTML = `
      <div class="empty-state card">
        <strong>No favourites yet.</strong>
        <span>Click ☆ beside a paper to save it in this browser.</span>
      </div>`;
    return;
  }

  container.classList.remove("hidden");
  list.innerHTML = favourites.map(paperHTML).join("");
  bindFavouriteButtons();
}

async function loadDailyData() {
  try {
    const response = await fetch("data/daily.json", { cache: "no-store" });
    if (!response.ok) throw new Error("daily.json not found");
    dailyData = await response.json();
    renderActivity(dailyData);
  } catch (error) {
    console.error(error);
    $("activityChart").innerHTML = "";
    $("activityEmpty").style.display = "flex";
  }
}

function getSelectedCategories() {
  return [...document.querySelectorAll(".category-toggle:checked")]
    .map((checkbox) => checkbox.value);
}

function renderActivity(data) {
  const empty = $("activityEmpty");
  const chart = $("activityChart");
  const selected = getSelectedCategories();

  if (!data || !data.length || !selected.length) {
    chart.innerHTML = "";
    empty.style.display = "flex";
    return;
  }

  empty.style.display = "none";

  const days = Number($("activityRange").value);
  const rows = data
    .filter((d) => d.date)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-days);

  if (!rows.length) {
    chart.innerHTML = "";
    empty.style.display = "flex";
    return;
  }

  const width = 900;
  const height = 320;
  const left = 55;
  const right = 20;
  const top = 35;
  const bottom = 45;
  const plotW = width - left - right;
  const plotH = height - top - bottom;

  const values = rows.flatMap((row) =>
    selected.map((category) => Number(row[category]) || 0)
  );
  const max = Math.max(...values, 1);

  const x = (i) => left + (rows.length === 1 ? plotW / 2 : i * plotW / (rows.length - 1));
  const y = (value) => top + plotH - (value / max) * plotH;

  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const yy = top + plotH * (1 - f);
    const value = Math.round(max * f);
    return `
      <line class="grid" x1="${left}" x2="${width - right}" y1="${yy}" y2="${yy}"></line>
      <text x="${left - 8}" y="${yy + 4}" text-anchor="end">${value.toLocaleString()}</text>`;
  }).join("");

  const seriesSVG = selected.map((category) => {
    const points = rows.map((row, i) =>
      `${x(i).toFixed(1)},${y(Number(row[category]) || 0).toFixed(1)}`
    ).join(" ");

    const circles = rows.map((row, i) => {
      const value = Number(row[category]) || 0;
      return `
        <circle class="category-point ${categoryClass(category)}"
                cx="${x(i)}" cy="${y(value)}" r="2.8">
          <title>${CATEGORY_LABELS[category]} · ${formatDate(row.date)}: ${value.toLocaleString()}</title>
        </circle>`;
    }).join("");

    return `
      <polyline class="category-line ${categoryClass(category)}" points="${points}"></polyline>
      ${circles}`;
  }).join("");

  const labelIndexes = uniqueLabelIndexes(rows.length);
  const labels = labelIndexes.map((i) => `
    <text x="${x(i)}" y="${height - 12}" text-anchor="middle">${formatShortDate(rows[i].date)}</text>
  `).join("");

  const legend = selected.map((category) => `
    <span class="chart-legend-item">
      <span class="legend-dot ${categoryClass(category)}"></span>
      ${CATEGORY_LABELS[category]}
    </span>
  `).join("");

  chart.innerHTML = `
    <div class="chart-legend">${legend}</div>
    <svg viewBox="0 0 ${width} ${height}" role="img"
         aria-label="Daily HEP and astrophysics arXiv activity">
      ${grid}
      ${seriesSVG}
      ${labels}
    </svg>`;

  updateActivityStats(rows, selected);
}

function updateActivityStats(rows, selected) {
  const dailyTotals = rows.map((row) =>
    selected.reduce((sum, category) => sum + (Number(row[category]) || 0), 0)
  );

  const total = dailyTotals.reduce((a, b) => a + b, 0);
  const avg = dailyTotals.length ? total / dailyTotals.length : 0;

  const categoryTotals = selected.map((category) => [
    category,
    rows.reduce((sum, row) => sum + (Number(row[category]) || 0), 0)
  ]).sort((a, b) => b[1] - a[1]);

  $("periodTotal").textContent = total.toLocaleString();
  $("periodAverage").textContent = Math.round(avg).toLocaleString();
  $("peakDay").textContent = categoryTotals.length
    ? `${CATEGORY_LABELS[categoryTotals[0][0]]} · ${categoryTotals[0][1].toLocaleString()}`
    : "—";

  const weekdays = {};
  rows.forEach((row) => {
    const day = new Date(`${row.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "long" });
    const value = selected.reduce((sum, category) => sum + (Number(row[category]) || 0), 0);
    (weekdays[day] ||= []).push(value);
  });

  const weekdayAverage = Object.entries(weekdays)
    .map(([day, values]) => [day, values.reduce((a, b) => a + b, 0) / values.length])
    .sort((a, b) => b[1] - a[1]);

  $("weekdayPeak").textContent = weekdayAverage.length ? weekdayAverage[0][0] : "—";
}

function categoryClass(category) {
  return "cat-" + category.replace(/\./g, "-").replace(/[^a-zA-Z0-9_-]/g, "");
}

function uniqueLabelIndexes(n) {
  if (n <= 6) return Array.from({ length: n }, (_, i) => i);
  const count = 6;
  return Array.from({ length: count }, (_, i) => Math.round(i * (n - 1) / (count - 1)));
}

function findPaper(id) {
  return papers.find((p) => p.id === id) || getFavourites().find((p) => p.id === id);
}

function setStatus(message) {
  $("searchStatus").textContent = message;
}

function truncate(text, length) {
  return text.length > length ? `${text.slice(0, length).trim()}…` : text;
}

function formatDate(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatShortDate(value) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function escapeHTML(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHTML(value);
}
