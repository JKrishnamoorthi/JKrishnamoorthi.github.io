/*
 * arXiv Explorer
 * - Keyword / author search
 * - Browser-local favourites
 * - Optional daily activity chart from data/daily.json
 *
 * Note:
 * arXiv's API may enforce browser-origin/CORS restrictions depending on
 * deployment. If direct API requests are blocked, use the cached JSON
 * workflow described in README.md.
 */

const API_URL = "https://export.arxiv.org/api/query";
const FAV_KEY = "krishnamoorthi_arxiv_favourites_v1";

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

    if (!response.ok) {
      throw new Error(`arXiv returned HTTP ${response.status}`);
    }

    const xml = await response.text();
    papers = parseArxivXML(xml);

    renderPapers(papers);
    $("resultsTitle").textContent =
      searchMode === "author" ? `Papers by ${query}` : `Search results`;
    $("resultsSubtitle").textContent =
      `${papers.length} result${papers.length === 1 ? "" : "s"} · sorted by submission date`;

    setStatus(`Found ${papers.length} paper${papers.length === 1 ? "" : "s"}.`);
  } catch (error) {
    console.error(error);
    setStatus(
      "The live arXiv API could not be reached from this browser. " +
      "You can still use the page with cached JSON data once the GitHub Actions workflow is added."
    );

    $("results").innerHTML = `
      <div class="empty-state card">
        <strong>Search request failed.</strong>
        <span>${escapeHTML(error.message)}</span>
        <span>Try again, or use the cached-data workflow described in README.md.</span>
      </div>`;
  } finally {
    $("searchButton").disabled = false;
  }
}

function buildSearchQuery(query, category) {
  const escaped = query.replace(/"/g, '\\"');

  let base;
  if (searchMode === "author") {
    base = `au:"${escaped}"`;
  } else {
    base = `all:"${escaped}"`;
  }

  if (category) {
    base += ` AND cat:${category}`;
  }

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
        ${paper.pdfLink
          ? `<a href="${escapeAttr(paper.pdfLink)}" target="_blank" rel="noopener">PDF ↗</a>`
          : ""}
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

  if (exists) {
    favourites = favourites.filter((p) => p.id !== paper.id);
  } else {
    favourites.unshift(paper);
  }

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
  const favourites = getFavourites();
  const container = $("favouritesSection");
  const list = $("favourites");

  if (!favourites.length) {
    list.innerHTML = `
      <div class="empty-state card">
        <strong>No favourites yet.</strong>
        <span>Click ☆ beside a paper to save it in this browser.</span>
      </div>`;
    return;
  }

  list.innerHTML = favourites.map(paperHTML).join("");
  bindFavouriteButtons();
}

async function loadDailyData() {
  try {
    const response = await fetch("data/daily.json", { cache: "no-store" });
    if (!response.ok) throw new Error("daily.json not found");
    dailyData = await response.json();
    renderActivity(dailyData);
  } catch {
    $("activityChart").innerHTML = "";
    $("activityEmpty").style.display = "flex";
  }
}

function renderActivity(data) {
  const empty = $("activityEmpty");
  const chart = $("activityChart");

  if (!data || !data.length) {
    chart.innerHTML = "";
    empty.style.display = "flex";
    return;
  }

  empty.style.display = "none";

  const days = Number($("activityRange").value);
  const rows = data
    .filter((d) => d.date && Number.isFinite(Number(d.count)))
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-days);

  if (!rows.length) {
    chart.innerHTML = "";
    empty.style.display = "flex";
    return;
  }

  const counts = rows.map((r) => Number(r.count));
  const max = Math.max(...counts, 1);
  const min = Math.min(...counts, 0);

  const width = 900;
  const height = 260;
  const left = 48;
  const right = 12;
  const top = 15;
  const bottom = 35;
  const plotW = width - left - right;
  const plotH = height - top - bottom;

  const x = (i) => left + (rows.length === 1 ? plotW / 2 : i * plotW / (rows.length - 1));
  const y = (v) => top + plotH - ((v - min) / Math.max(max - min, 1)) * plotH;

  const points = rows.map((r, i) => `${x(i).toFixed(1)},${y(Number(r.count)).toFixed(1)}`).join(" ");
  const areaPoints =
    `${left},${top + plotH} ${points} ${x(rows.length - 1)},${top + plotH}`;

  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const yy = top + plotH * (1 - f);
    const value = Math.round(min + (max - min) * f);
    return `<line class="grid" x1="${left}" x2="${width - right}" y1="${yy}" y2="${yy}"/>
            <text x="${left - 7}" y="${yy + 4}" text-anchor="end">${value}</text>`;
  }).join("");

  const labelIndexes = uniqueLabelIndexes(rows.length);
  const labels = labelIndexes.map((i) => `
    <text x="${x(i)}" y="${height - 9}" text-anchor="middle">${formatShortDate(rows[i].date)}</text>
  `).join("");

  chart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Daily arXiv submissions">
      ${grid}
      <polygon class="area" points="${areaPoints}"></polygon>
      <polyline class="line" points="${points}"></polyline>
      ${labels}
    </svg>`;

  const total = counts.reduce((a, b) => a + b, 0);
  const avg = total / counts.length;
  const peakIndex = counts.indexOf(Math.max(...counts));

  $("periodTotal").textContent = total.toLocaleString();
  $("periodAverage").textContent = Math.round(avg).toLocaleString();
  $("peakDay").textContent =
    `${Math.max(...counts).toLocaleString()} · ${formatDate(rows[peakIndex].date)}`;

  const weekdays = {};
  rows.forEach((r) => {
    const d = new Date(`${r.date}T12:00:00`);
    const day = d.toLocaleDateString(undefined, { weekday: "long" });
    if (!weekdays[day]) weekdays[day] = [];
    weekdays[day].push(Number(r.count));
  });

  const weekdayAverage = Object.entries(weekdays)
    .map(([day, values]) => [day, values.reduce((a, b) => a + b, 0) / values.length])
    .sort((a, b) => b[1] - a[1]);

  $("weekdayPeak").textContent =
    weekdayAverage.length ? weekdayAverage[0][0] : "—";
}

function uniqueLabelIndexes(n) {
  if (n <= 6) return Array.from({ length: n }, (_, i) => i);
  const count = 6;
  return Array.from({ length: count }, (_, i) =>
    Math.round(i * (n - 1) / (count - 1))
  );
}

function findPaper(id) {
  return papers.find((p) => p.id === id) ||
    getFavourites().find((p) => p.id === id);
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
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

function formatShortDate(value) {
  const d = new Date(`${value}T12:00:00`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
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
