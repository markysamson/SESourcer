const form = document.querySelector("#search-form");
const statusEl = document.querySelector("#status");
const submit = document.querySelector("#submit");
const results = document.querySelector("#results");
const rows = document.querySelector("#rows");
const warnings = document.querySelector("#warnings");
const reading = document.querySelector("#reading");
const meta = document.querySelector("#results-meta");
const sourceNote = document.querySelector("#source-note");
const queryList = document.querySelector("#query-list");
const download = document.querySelector("#download");

const SAMPLE = `Senior Product Manager, Payments
London, United Kingdom (hybrid)

We are hiring a Senior Product Manager to own the payments experience at a UK fintech.

What you'll need
- 6+ years in product management
- Payments or open banking experience
- Stakeholder management with engineering and compliance
- Agile roadmapping
- SQL

Nice to have
- Experience in a regulated bank or e-money institution
- Experimentation and A/B testing

About us
We are a 40-person company. We use Excel for planning and like dogs.
`;

let lastPayload = null;
let sortKey = "score";
let sortDir = -1;
let timer = null;

document.querySelector("#sample").addEventListener("click", () => {
  document.querySelector("#job-text").value = SAMPLE.trim();
  document.querySelector("#notes").value = "Prefer people who have worked at a UK bank.";
  document.querySelector("#limit").value = "20";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const jobText = document.querySelector("#job-text").value.trim();
  const jobUrl = document.querySelector("#job-url").value.trim();
  const notes = document.querySelector("#notes").value.trim();
  const limitValue = document.querySelector("#limit").value.trim();
  const limit = limitValue === "" ? 20 : Number(limitValue);
  if (!jobText && !jobUrl) {
    statusEl.textContent = "Add a job link or paste the description.";
    return;
  }
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    statusEl.textContent = "Candidates must be a whole number from 1 to 50.";
    return;
  }
  await runSearch({ job_text: jobText, job_url: jobUrl, notes, limit });
});

document.querySelectorAll("th button").forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.dataset.sort;
    if (sortKey === key) {
      sortDir *= -1;
    } else {
      sortKey = key;
      sortDir = key === "score" ? -1 : 1;
    }
    render();
  });
});

download.addEventListener("click", () => {
  if (!lastPayload) return;
  const header = [
    "score",
    "band",
    "name",
    "role",
    "location",
    "company",
    "tenure",
    "skills",
    "linkedin_url",
    "rationale",
  ];
  const lines = [header.join(",")];
  for (const candidate of ordered(lastPayload.candidates)) {
    const values = [
      candidate.score,
      candidate.band,
      candidate.name,
      candidate.role,
      candidate.location,
      candidate.company,
      candidate.tenure,
      (candidate.skills || []).join("; "),
      candidate.linkedin_url,
      candidate.rationale,
    ];
    lines.push(values.map(csv).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "sesourcer-candidates.csv";
  link.click();
  URL.revokeObjectURL(url);
});

async function runSearch(payload) {
  submit.disabled = true;
  results.hidden = true;
  const started = Date.now();
  statusEl.textContent = "Reading the role and searching public profile listings…";
  timer = setInterval(() => {
    const seconds = Math.round((Date.now() - started) / 1000);
    statusEl.textContent = `Searching public profile listings… ${seconds}s`;
  }, 1000);
  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      statusEl.textContent = typeof data.detail === "string" ? data.detail : "The search failed.";
      return;
    }
    lastPayload = data;
    sortKey = "score";
    sortDir = -1;
    render();
    statusEl.textContent = "";
    results.hidden = false;
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch {
    statusEl.textContent = "The search could not be completed. Try again.";
  } finally {
    clearInterval(timer);
    submit.disabled = false;
  }
}

function render() {
  if (!lastPayload) return;
  const data = lastPayload;
  const count = data.returned ?? data.candidates.length;
  meta.textContent = `${count} shown · ${data.requested} requested · ${data.brief.title}`;
  renderWarnings(data.warnings || []);
  renderBrief(data.brief);
  sourceNote.textContent = data.source_note || "";
  queryList.replaceChildren();
  for (const query of data.queries || []) {
    const item = document.createElement("li");
    item.textContent = query;
    queryList.append(item);
  }
  download.hidden = count === 0;
  rows.replaceChildren();
  const candidates = ordered(data.candidates || []);
  if (!candidates.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 8;
    td.textContent = "No public profiles matched these searches.";
    tr.append(td);
    rows.append(tr);
    return;
  }
  candidates.forEach((candidate, index) => {
    rows.append(candidateRow(candidate, index));
  });
}

function ordered(candidates) {
  const copy = [...candidates];
  copy.sort((a, b) => {
    const left = sortValue(a, sortKey);
    const right = sortValue(b, sortKey);
    if (left < right) return -1 * sortDir;
    if (left > right) return 1 * sortDir;
    return 0;
  });
  return copy;
}

function sortValue(candidate, key) {
  if (key === "score") return Number(candidate.score) || 0;
  return String(candidate[key] || "").toLowerCase();
}

function candidateRow(candidate, index) {
  const tr = document.createElement("tr");
  tr.append(
    cell(scoreBlock(candidate)),
    cell(nameLink(candidate)),
    textCell(candidate.role),
    textCell(candidate.location),
    textCell(candidate.company),
    textCell(candidate.tenure),
    cell(skillList(candidate.skills)),
    cell(profileLink(candidate)),
  );
  const why = document.createElement("button");
  why.type = "button";
  why.className = "why";
  why.textContent = "Why this score";
  why.setAttribute("aria-expanded", "false");
  tr.lastChild.append(why);
  const detail = detailRow(candidate);
  why.addEventListener("click", () => {
    const open = detail.hidden;
    detail.hidden = !open;
    why.setAttribute("aria-expanded", open ? "true" : "false");
    why.textContent = open ? "Hide score" : "Why this score";
  });
  tr.dataset.index = String(index);
  return [tr, detail];
}

function cell(node) {
  const td = document.createElement("td");
  td.append(node);
  return td;
}

function textCell(value) {
  const td = document.createElement("td");
  td.textContent = value || "Not stated";
  return td;
}

function scoreBlock(candidate) {
  const wrap = document.createElement("div");
  const score = document.createElement("span");
  score.className = `score ${bandClass(candidate.band)}`;
  score.textContent = String(candidate.score);
  const band = document.createElement("span");
  band.className = "band";
  band.textContent = candidate.band || "";
  wrap.append(score, band);
  return wrap;
}

function bandClass(band) {
  if (band === "Strong fit") return "strong";
  if (band === "Good fit") return "good";
  if (band === "Partial fit") return "partial";
  return "weak";
}

function nameLink(candidate) {
  const url = safeProfileUrl(candidate.linkedin_url);
  if (!url) {
    const span = document.createElement("span");
    span.textContent = candidate.name || "Unknown";
    return span;
  }
  const link = document.createElement("a");
  link.className = "name-link";
  link.href = url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = candidate.name || "Unknown";
  return link;
}

function profileLink(candidate) {
  const url = safeProfileUrl(candidate.linkedin_url);
  const link = document.createElement("a");
  link.className = "profile-link";
  if (!url) {
    link.textContent = "Unavailable";
    link.removeAttribute("href");
    return link;
  }
  link.href = url;
  link.target = "_blank";
  link.rel = "noreferrer";
  const slug = decodeURIComponent(new URL(url).pathname.replace(/^\/in\//, ""));
  link.textContent = `in/${slug}`;
  return link;
}

function skillList(skills) {
  const list = document.createElement("ul");
  list.className = "skills";
  const items = skills && skills.length ? skills : ["Not stated"];
  for (const skill of items) {
    const li = document.createElement("li");
    li.textContent = skill;
    list.append(li);
  }
  return list;
}

function detailRow(candidate) {
  const tr = document.createElement("tr");
  tr.className = "detail";
  tr.hidden = true;
  const td = document.createElement("td");
  td.colSpan = 8;
  const rationale = document.createElement("p");
  rationale.textContent = candidate.rationale || "";
  const breakdown = document.createElement("p");
  const parts = candidate.breakdown || {};
  breakdown.textContent = `Role ${parts.role ?? 0} · Skills ${parts.skills ?? 0} · Location ${parts.location ?? 0} · Seniority ${parts.seniority ?? 0} · Notes ${parts.notes ?? 0}`;
  td.append(rationale, breakdown);
  if (candidate.experience && candidate.tenure === "Not stated") {
    const experience = document.createElement("p");
    experience.textContent = `Experience mentioned in the snippet: ${candidate.experience}. That is not tenure at the current company.`;
    td.append(experience);
  }
  if (candidate.snippet) {
    const snippet = document.createElement("p");
    snippet.className = "snippet";
    snippet.textContent = candidate.snippet;
    td.append(snippet);
  }
  tr.append(td);
  return tr;
}

function renderWarnings(items) {
  warnings.replaceChildren();
  if (!items.length) {
    warnings.hidden = true;
    return;
  }
  warnings.hidden = false;
  for (const item of items) {
    const p = document.createElement("p");
    p.textContent = item;
    warnings.append(p);
  }
}

function renderBrief(brief) {
  reading.replaceChildren();
  if (!brief) {
    reading.hidden = true;
    return;
  }
  reading.hidden = false;
  const bits = [
    brief.title,
    brief.seniority ? `Level: ${brief.seniority}` : "",
    ...(brief.locations || []),
    brief.remote ? "Remote" : "",
    brief.hybrid ? "Hybrid" : "",
    brief.years_experience ? `${brief.years_experience}+ years` : "",
  ].filter(Boolean);
  for (const bit of bits) reading.append(chip(bit));
  for (const skill of brief.must_have || []) reading.append(chip(skill));
}

function chip(text) {
  const span = document.createElement("span");
  span.className = "chip";
  span.textContent = text;
  return span;
}

function safeProfileUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:") return null;
    const host = url.hostname.toLowerCase();
    if (!(host === "linkedin.com" || host.endsWith(".linkedin.com"))) return null;
    if (!url.pathname.startsWith("/in/")) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function csv(value) {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

// candidateRow returns two nodes; append() only takes nodes, so flatten.
const _append = rows.append.bind(rows);
rows.append = (...nodes) => {
  for (const node of nodes.flat()) _append(node);
};
