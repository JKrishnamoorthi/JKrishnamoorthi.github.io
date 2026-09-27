const CATEGORY_INFO = {
  "hep-ph": { label: "hep-ph", color: "#1d4ed8" },
  "hep-ex": { label: "hep-ex", color: "#7c3aed" },
  "hep-th": { label: "hep-th", color: "#059669" },
  "nucl-th": { label: "nucl-th", color: "#d97706" },
  "astro-ph.HE": { label: "astro-ph.HE", color: "#dc2626" },
  "astro-ph.CO": { label: "astro-ph.CO", color: "#0891b2" },
  "physics.ins-det": { label: "physics.ins-det", color: "#be185d" }
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("year").textContent = new Date().getFullYear();

  document.getElementById("range").addEventListener("change", () => {
    loadActivity();
  });

  document.querySelectorAll(".checks input").forEach((box) => {
    box.addEventListener("change", loadActivity);
  });

  loadActivity();
  loadFavourites();
});

async function loadActivity() {
  const chart = document.getElementById("chart");

  try {
    const response = await fetch("data/daily.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderActivity(data);
  } catch (error) {
    console.error(error);
    chart.innerHTML = `<p class="status error">Could not load data/daily.json.</p>`;
  }
}

function renderActivity(data) {
  const selected = [...document.querySelectorAll(".checks input:checked")].map((x) => x.value);
  const days = Number(document.getElementById("range").value);

  const rows = [...data]
    .filter((d) => d.date)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-days);

  if (!rows.length || !selected.length) {
    document.getElementById("chart").innerHTML =
      `<p class="status">Select at least one category.</p>`;
    document.getElementById("legend").innerHTML = "";
    return;
  }

  const values = {};
  selected.forEach((cat) => {
    values[cat] = rows.map((r) => Number(r[cat] || 0));
  });

  const allValues = selected.flatMap((cat) => values[cat]);
  const max = Math.max(...allValues, 1);

  const width = 900;
  const height = 300;
  const left = 52;
  const right = 18;
  const top = 18;
  const bottom = 42;
  const plotW = width - left - right;
  const plotH = height - top - bottom;

  const x = (i) =>
    left + (rows.length === 1 ? plotW / 2 : i * plotW / (rows.length - 1));
  const y = (v) => top + plotH - (v / max) * plotH;

  const grid = [0, .25, .5, .75, 1].map((f) => {
    const yy = top + plotH * (1 - f);
    const value = Math.round(max * f);
    return `
      <line class="grid" x1="${left}" x2="${width - right}" y1="${yy}" y2="${yy}"></line>
      <text class="axis-label" x="${left - 8}" y="${yy + 4}" text-anchor="end">${value}</text>
    `;
  }).join("");

  const labels = uniqueLabelIndexes(rows.length).map((i) => `
    <text class="axis-label" x="${x(i)}" y="${height - 12}" text-anchor="middle">
      ${formatShortDate(rows[i].date)}
    </text>
  `).join("");

  const lines = selected.map((cat) => {
    const points = values[cat]
      .map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`)
      .join(" ");

    return `<polyline class="chart-line" stroke="${CATEGORY_INFO[cat].color}" points="${points}"></polyline>`;
  }).join("");

  document.getElementById("chart").innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img"
         aria-label="Daily arXiv submissions by selected category">
      ${grid}
      ${lines}
      ${labels}
    </svg>
  `;

  document.getElementById("legend").innerHTML = selected.map((cat) => `
    <span class="legend-item">
      <span class="legend-dot" style="background:${CATEGORY_INFO[cat].color}"></span>
      ${CATEGORY_INFO[cat].label}
    </span>
  `).join("");

  const total = allValues.reduce((a, b) => a + b, 0);
  document.getElementById("selectedCount").textContent = selected.length;
  document.getElementById("dailyAverage").textContent =
    Math.round(total / rows.length).toLocaleString();

  let peakCat = selected[0];
  let peakValue = -1;
  selected.forEach((cat) => {
    const localPeak = Math.max(...values[cat]);
    if (localPeak > peakValue) {
      peakValue = localPeak;
      peakCat = cat;
    }
  });

  document.getElementById("peak").textContent =
    `${CATEGORY_INFO[peakCat].label} · ${peakValue.toLocaleString()}`;
}

async function loadFavourites() {
  const status = document.getElementById("favStatus");
  const list = document.getElementById("favourites");

  try {
    const response = await fetch("data/favourites.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const ids = await response.json();

    if (!Array.isArray(ids) || ids.length === 0) {
      status.textContent = "No favourite papers added yet.";
      list.innerHTML = "";
      return;
    }

    status.textContent = "Loading paper information…";

    const papers = await Promise.all(
      ids.map(async (id) => {
        try {
          return await fetchArxivPaper(normalizeArxivId(id));
        } catch (error) {
          console.error(`Could not load ${id}:`, error);
          return {
            id: normalizeArxivId(id),
            title: `arXiv:${normalizeArxivId(id)}`,
            authors: [],
            published: "",
            journal: "",
            summary: "Paper metadata could not be loaded.",
            absLink: `https://arxiv.org/abs/${normalizeArxivId(id)}`,
            pdfLink: `https://arxiv.org/pdf/${normalizeArxivId(id)}`
          };
        }
      })
    );

    list.innerHTML = papers.map(paperHTML).join("");
    status.textContent =
      `${papers.length} favourite paper${papers.length === 1 ? "" : "s"}.`;
  } catch (error) {
    console.error(error);
    status.textContent =
      "Could not load data/favourites.json.";
    status.classList.add("error");
  }
}

async function fetchArxivPaper(id) {
  const url =
    `https://export.arxiv.org/api/query?search_query=id:${encodeURIComponent(id)}&start=0&max_results=1`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`arXiv API returned HTTP ${response.status}`);
  }

  const xmlText = await response.text();
  const xml = new DOMParser().parseFromString(xmlText, "application/xml");
  const entry = xml.getElementsByTagName("entry")[0];

  if (!entry) throw new Error("Paper not found");

  const text = (tag) =>
    entry.getElementsByTagName(tag)[0]?.textContent?.trim() || "";

  const authors = [...entry.getElementsByTagName("author")]
    .map((a) => a.getElementsByTagName("name")[0]?.textContent?.trim())
    .filter(Boolean);

  const links = [...entry.getElementsByTagName("link")];

  const absLink =
    links.find((l) => l.getAttribute("type") === "text/html")?.getAttribute("href") ||
    `https://arxiv.org/abs/${id}`;

  const pdfLink =
    links.find((l) => l.getAttribute("title") === "pdf")?.getAttribute("href") ||
    `https://arxiv.org/pdf/${id}`;

  const journal =
    entry.getElementsByTagName("journal_ref")[0]?.textContent?.trim() || "";

  return {
    id,
    title: text("title").replace(/\s+/g, " "),
    authors,
    published: text("published"),
    journal,
    summary: text("summary").replace(/\s+/g, " "),
    absLink,
    pdfLink
  };
}

function paperHTML(paper) {
  const date = paper.published ? formatDate(paper.published) : "";
  const authors = paper.authors.length
    ? paper.authors.join(", ")
    : "Metadata unavailable";

  const journal = paper.journal
    ? ` · ${escapeHTML(paper.journal)}`
    : "";

  return `
    <li>
      <div class="pub-authors">${escapeHTML(authors)}</div>
      <div class="pub-title">
        <a href="${escapeAttr(paper.absLink)}" target="_blank" rel="noopener">
          ${escapeHTML(paper.title)}
        </a>
      </div>
      <div class="pub-journal">
        arXiv:${escapeHTML(paper.id)}
        ${date ? ` · ${escapeHTML(date)}` : ""}
        ${journal}
      </div>
      <p class="pub-abstract">${escapeHTML(paper.summary)}</p>
      <div class="pub-links">
        <a class="pub-link" href="${escapeAttr(paper.absLink)}" target="_blank" rel="noopener">
          Abstract ↗
        </a>
        <a class="pub-link" href="${escapeAttr(paper.pdfLink)}" target="_blank" rel="noopener">
          PDF ↗
        </a>
      </div>
    </li>
  `;
}

function normalizeArxivId(value) {
  let id = String(value).trim();
  id = id.replace(/^https?:\/\/arxiv\.org\/abs\//i, "");
  id = id.replace(/^https?:\/\/arxiv\.org\/pdf\//i, "");
  id = id.replace(/^arXiv:/i, "");
  id = id.replace(/\.pdf$/i, "");
  return id;
}

function formatDate(value) {
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
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric"
  });
}

function uniqueLabelIndexes(n) {
  if (n <= 6) return Array.from({ length: n }, (_, i) => i);
  return Array.from({ length: 6 }, (_, i) =>
    Math.round(i * (n - 1) / 5)
  );
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
