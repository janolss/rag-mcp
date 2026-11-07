"use strict";

const serverStatus = document.querySelector("#server-status");
const indexStatus = document.querySelector("#index-status");
const message = document.querySelector("#message");
const workspaces = document.querySelector("#workspaces");
const history = document.querySelector("#history");
const reindexAll = document.querySelector("#reindex-all");
let busy = false;
let submitting = false;
let available = false;
let reindexAvailable = false;

function date(value) {
  return value == null ? "Unknown" : new Date(value * 1000).toLocaleString();
}

function cell(row, text) {
  const td = document.createElement("td");
  td.textContent = text;
  row.appendChild(td);
  return td;
}

function updateButtons() {
  reindexAll.disabled = !available || !reindexAvailable || busy || submitting || !workspaces.children.length;
  workspaces.querySelectorAll("button").forEach(button => {
    button.disabled = !available || !reindexAvailable || busy || submitting;
  });
}

async function getJSON(url, options) {
  const response = await fetch(url, { cache: "no-store", ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function reindex(workspaceId) {
  if (submitting || busy) return;
  const target = workspaceId === null ? "all workspaces" : workspaceId;
  if (!confirm(`Reindex ${target}?`)) return;
  submitting = true;
  message.textContent = "Starting indexing…";
  message.className = "";
  updateButtons();
  try {
    await getJSON("/gui/reindex", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: workspaceId })
    });
    message.textContent = `Indexing started for ${target}.`;
    busy = true;
    await refresh();
  } catch (error) {
    message.textContent = `Could not start indexing: ${error.message}`;
    message.className = "error";
  } finally {
    submitting = false;
    updateButtons();
  }
}

async function refresh() {
  try {
    const [status, data] = await Promise.all([
      getJSON("/gui/status"), getJSON("/gui/indexing-history")
    ]);
    available = true;
    reindexAvailable = status.reindex_available;
    serverStatus.textContent = `${status.server.name} ${status.server.version} — running (uptime ${Math.floor(status.server.uptime_seconds / 60)} min)`;
    serverStatus.className = "";
    indexStatus.textContent = status.index_error
      ? `Index status unavailable: ${status.index_error}`
      : `Index: ${status.index.lifecycle}; ${status.index.points_count} points`;
    indexStatus.className = status.index_error ? "error" : "";
    if (!reindexAvailable) {
      message.textContent = "Reindexing requires Qdrant local or server mode.";
      message.className = "error";
    }
    busy = data.jobs.some(job => job.status === "queued" || job.status === "running");
    workspaces.replaceChildren();
    for (const workspace of data.workspaces) {
      const row = document.createElement("tr");
      cell(row, `${workspace.name} (${workspace.id})`);
      cell(row, date(workspace.last_success_at));
      const button = document.createElement("button");
      button.textContent = "Reindex";
      button.addEventListener("click", () => reindex(workspace.id));
      cell(row, "").appendChild(button);
      workspaces.appendChild(row);
    }
    history.replaceChildren();
    for (const job of data.jobs) {
      const row = document.createElement("tr");
      cell(row, date(job.updated_at));
      cell(row, job.workspace_id === "*" ? "All workspaces" : job.workspace_id);
      cell(row, job.status);
      cell(row, job.duration_seconds == null ? "—" : `${job.duration_seconds.toFixed(1)} s`);
      cell(row, job.error || "—");
      history.appendChild(row);
    }
    updateButtons();
  } catch (error) {
    available = false;
    serverStatus.textContent = `Server unavailable: ${error.message}`;
    serverStatus.className = "error";
    updateButtons();
  }
}

reindexAll.addEventListener("click", () => reindex(null));
refresh();
setInterval(refresh, 5000);
