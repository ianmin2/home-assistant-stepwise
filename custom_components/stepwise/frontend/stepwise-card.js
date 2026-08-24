/*
 * The manager card.
 *
 * Not a step-following card, on purpose. Google built one of those for the
 * Nest Hub, measured it, and deleted it — and the answer to what people
 * actually wanted is voice resumption, which is the rest of this project.
 * This is the other thing: somewhere to see what is held, correct what is
 * wrong, and start or pick up a job. A quirk nobody can see is permanent.
 *
 * It talks over the websocket API rather than to entities, so nothing here
 * ends up in the recorder database, and there are no entity ids to regret.
 */

// Home Assistant ships Lit; borrowing it from an element it has already
// defined keeps this a single file with no build step and no npm, which is
// the same discipline as the integration's empty requirements list. The
// element may not exist yet at import time, hence the wait.
async function borrowLit() {
  await customElements.whenDefined("ha-panel-lovelace");
  const Base = Object.getPrototypeOf(customElements.get("ha-panel-lovelace"));
  return { Base, html: Base.prototype.html, css: Base.prototype.css };
}

const DOTS = (done, total) => "●".repeat(Math.max(0, done)) + "○".repeat(Math.max(0, total - done));

const SIZE = (bytes) => {
  if (!bytes) return "0 B";
  const units = ["B", "kB", "MB", "GB"];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n < 10 && i > 0 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
};

const WORD = {
  run_started: "started", advanced: "done", repositioned: "moved", undone: "put back",
  note: "note", asked: "asked", challenged: "disputed", amended: "changed",
  quirk_stated: "said", quirk_learned: "learnt", quirk_confirmed: "confirmed",
  quirk_retracted: "forgotten", timer_started: "timer", paused: "put down",
  resumed: "picked up", finished: "finished",
};

function defineCard({ Base, html, css }) {
  class StepwiseCard extends Base {
    static get properties() {
      return { hass: {}, _config: {}, _tab: {}, _data: {}, _open: {}, _busy: {}, _error: {} };
    }

    constructor() {
      super();
      this._tab = "runs";
      this._data = {};
      this._open = null;
      this._busy = false;
      this._error = null;
    }

    setConfig(config) {
      this._config = config || {};
      if (config?.tab) this._tab = config.tab;
    }

    getCardSize() { return 8; }

    static getStubConfig() { return { type: "custom:stepwise-card" }; }

    updated(changed) {
      if (changed.has("hass") && this.hass && !this._data.overview) this._refresh();
    }

    async _call(type, payload = {}) {
      try {
        return await this.hass.callWS({ type: `stepwise/${type}`, ...payload });
      } catch (err) {
        this._error = err?.message || String(err);
        throw err;
      }
    }

    async _refresh() {
      this._busy = true;
      this._error = null;
      try {
        const [overview, runs, subjects, procedures] = await Promise.all([
          this._call("overview"),
          this._call("runs", { include_finished: true, limit: 40 }),
          this._call("subjects"),
          this._call("procedures"),
        ]);
        this._data = { overview, runs: runs.runs, subjects: subjects.subjects, procedures: procedures.procedures };
        if (this._open) {
          const still = this._data.runs.find((r) => r.run_id === this._open.run_id);
          this._open = still ? await this._call("run", { run_id: this._open.run_id }) : null;
        }
      } catch (err) {
        /* surfaced through _error */
      } finally {
        this._busy = false;
      }
    }

    async _act(type, payload, confirm) {
      if (confirm && !window.confirm(confirm)) return;
      this._busy = true;
      try {
        await this._call(type, payload);
        await this._refresh();
      } catch (err) {
        this._busy = false;
      }
    }

    async _openRun(run_id) {
      this._open = await this._call("run", { run_id });
    }

    render() {
      if (!this.hass) return html``;
      const o = this._data.overview;
      return html`
        <ha-card>
          <div class="head">
            <div class="title">${this._config?.title ?? "Stepwise"}</div>
            <div class="counts">
              ${o ? html`
                <span>${o.counts.runs ?? 0} runs</span>
                <span>${o.counts.procedures ?? 0} procedures</span>
                <span>${o.counts.subjects ?? 0} things</span>
                <span class="size" title="Everything Stepwise knows, on disk">${SIZE(o.size_bytes)}</span>
              ` : html`<span>…</span>`}
            </div>
          </div>

          <div class="tabs">
            ${["runs", "things", "library"].map((tab) => html`
              <button class="tab ${this._tab === tab ? "on" : ""}" @click=${() => { this._tab = tab; this._open = null; }}>${tab}</button>
            `)}
            <button class="refresh" ?disabled=${this._busy} @click=${() => this._refresh()} title="Refresh">↻</button>
          </div>

          ${this._error ? html`<div class="error">${this._error}</div>` : ""}
          ${this._open ? this._renderRun() : this._renderTab()}
        </ha-card>
      `;
    }

    _renderTab() {
      if (this._tab === "runs") return this._renderRuns();
      if (this._tab === "things") return this._renderThings();
      return this._renderLibrary();
    }

    _renderRuns() {
      const runs = this._data.runs || [];
      if (!runs.length) return html`<div class="empty">Nothing on the go, and nothing finished yet.</div>`;
      return html`
        <div class="list">
          ${runs.map((run) => html`
            <div class="row run ${run.status}">
              <div class="line1">
                <button class="ref" @click=${() => this._openRun(run.run_id)}>${run.reference}</button>
                <span class="subject">${run.subject ?? ""}</span>
              </div>
              <div class="line2">
                <span class="dots" title="step ${run.step} of ${run.total_steps}">${DOTS(Math.max(0, run.step - 1), run.total_steps || 0)}</span>
                <span class="where">step ${run.step} of ${run.total_steps}</span>
                <span class="since">${run.status === "active" || run.status === "paused" ? `last touched ${run.since}` : run.status}</span>
              </div>
              <div class="acts">
                ${run.status === "active" || run.status === "paused" ? html`
                  <button @click=${() => this._act("run/finish", { run_id: run.run_id, how: "paused" })}>Put it down</button>
                  <button @click=${() => this._act("run/finish", { run_id: run.run_id, how: "done" })}>Finished</button>
                ` : html`
                  <button @click=${() => this._act("run/resume", { run_id: run.run_id })}>Pick it up</button>
                `}
                <button @click=${() => this._export(run.run_id)}>Export</button>
                <button class="danger" @click=${() => this._act("run/delete", { run_id: run.run_id },
                  `Delete ${run.reference}? Its whole history goes with it. Export it first if you want to keep it.`)}>Delete</button>
              </div>
            </div>
          `)}
        </div>
      `;
    }

    _renderRun() {
      const run = this._open;
      const done = Math.max(0, run.step - 1);
      return html`
        <div class="detail">
          <div class="line1">
            <button class="back" @click=${() => { this._open = null; }}>‹ back</button>
            <span class="ref">${run.reference}</span>
            <span class="subject">${run.subject ?? ""}</span>
          </div>
          <div class="line2">
            <span class="dots">${DOTS(done, run.total_steps)}</span>
            <span class="where">step ${run.step} of ${run.total_steps}</span>
            <span class="since">last touched ${run.since}</span>
          </div>

          <div class="steps">
            ${run.steps.map((step) => html`
              <div class="step ${step.n < run.step ? "done" : ""} ${step.n === run.step ? "here" : ""}">
                <span class="n">${step.n}</span><span>${step.instruction}</span>
              </div>
            `)}
          </div>

          <div class="sub">What happened — read only, and exportable</div>
          <div class="history">
            ${run.history.map((row) => html`
              <div class="event">
                <span class="what">${WORD[row.what] ?? row.what}</span>
                <span class="at">${row.at.slice(11)}</span>
                <span class="detail-text">${row.detail}</span>
                <span class="step-n">${row.step ? `(step ${row.step})` : ""}</span>
              </div>
            `)}
          </div>
        </div>
      `;
    }

    _renderThings() {
      const subjects = this._data.subjects || [];
      if (!subjects.length) return html`<div class="empty">Nothing on file yet. Things arrive when you mention them.</div>`;
      return html`
        <div class="list">
          ${subjects.map((s) => html`
            <div class="row">
              <div class="line1"><span class="ref">${s.label}</span><span class="subject">${[s.make, s.model].filter(Boolean).join(" ")}</span></div>
              ${s.quirks.filter((q) => q.status === "active").map((q) => html`
                <div class="quirk">
                  <span>${q.claim}</span>
                  <span class="from">${q.learned_from === "user" ? "you told me" : q.learned_from === "web" ? "read somewhere" : q.learned_from}</span>
                  ${q.last_confirmed_at ? "" : html`<span class="unconfirmed" title="Never confirmed by you">unconfirmed</span>`}
                  <button class="danger" @click=${() => this._act("quirk/retract", { quirk_id: q.id }, `Forget "${q.claim}"?`)}>Forget</button>
                </div>
              `)}
              ${s.facts.map((f) => html`
                <div class="quirk fact">
                  <span>${f.text}</span><span class="from">fact</span>
                  <button class="danger" @click=${() => this._act("fact/forget", { fact_id: f.id }, `Forget "${f.text}"?`)}>Forget</button>
                </div>
              `)}
              <div class="acts">
                <button class="danger" @click=${() => this._act("subject/delete", { subject_id: s.id },
                  `Forget ${s.label}, and everything learnt about it?`)}>Forget this thing</button>
              </div>
            </div>
          `)}
        </div>
      `;
    }

    _renderLibrary() {
      const procedures = this._data.procedures || [];
      if (!procedures.length) return html`<div class="empty">No procedures stored yet.</div>`;
      return html`
        <div class="list">
          ${procedures.map((p) => html`
            <div class="row">
              <div class="line1"><span class="ref">${p.title}</span><span class="subject">${p.total_steps} steps · ${p.source}</span></div>
              <div class="acts">
                <button @click=${() => this._act("run/start", { procedure_id: p.id })}>Start</button>
                <button class="danger" @click=${() => this._act("procedure/delete", { procedure_id: p.id },
                  `Delete "${p.title}"? Runs of it keep their own copy of the steps.`)}>Delete</button>
              </div>
            </div>
          `)}
        </div>
      `;
    }

    async _export(run_id) {
      const result = await this.hass.callService("stepwise", "export_run", { run_id }, undefined, true, true);
      const markdown = result?.response?.markdown ?? "";
      // The viewer's sandbox blocks page-initiated downloads, so this opens the
      // record for copying rather than pretending to save a file.
      const w = window.open("", "_blank");
      if (w) {
        w.document.title = "Stepwise export";
        const pre = w.document.createElement("pre");
        pre.style.cssText = "white-space:pre-wrap;font:13px ui-monospace,monospace;padding:24px";
        pre.textContent = markdown;
        w.document.body.appendChild(pre);
      }
    }

    static get styles() {
      return css`
        ha-card { padding: 16px; }
        .head { display:flex; justify-content:space-between; align-items:baseline; gap:12px; flex-wrap:wrap; }
        .title { font-size:1.25rem; font-weight:500; }
        .counts { display:flex; gap:12px; font-size:.8rem; color:var(--secondary-text-color); }
        .counts .size { font-variant-numeric:tabular-nums; }
        .tabs { display:flex; gap:4px; margin:12px 0; align-items:center; }
        .tab { background:none; border:none; padding:6px 10px; border-radius:14px; cursor:pointer;
               color:var(--secondary-text-color); font:inherit; font-size:.85rem; text-transform:capitalize; }
        .tab.on { background:var(--primary-color); color:var(--text-primary-color); }
        .refresh { margin-left:auto; background:none; border:none; cursor:pointer; font-size:1rem;
                   color:var(--secondary-text-color); }
        .error { background:var(--error-color,#b00); color:#fff; padding:8px 10px; border-radius:6px; font-size:.85rem; }
        .empty { color:var(--secondary-text-color); padding:16px 0; font-size:.9rem; }
        .list { display:flex; flex-direction:column; gap:10px; }
        .row { border:1px solid var(--divider-color); border-radius:8px; padding:10px 12px; }
        .row.done, .row.abandoned { opacity:.62; }
        .line1 { display:flex; justify-content:space-between; gap:8px; align-items:baseline; }
        .ref, .back { font-weight:500; }
        button.ref, .back { background:none; border:none; padding:0; cursor:pointer; font:inherit;
                            font-weight:500; color:var(--primary-color); text-align:left; }
        .subject { font-size:.78rem; color:var(--secondary-text-color); }
        .line2 { display:flex; gap:10px; align-items:baseline; margin-top:4px; font-size:.8rem;
                 color:var(--secondary-text-color); flex-wrap:wrap; }
        .dots { letter-spacing:1px; color:var(--primary-color); }
        .since { margin-left:auto; }
        .acts { display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
        .acts button, .quirk button { font:inherit; font-size:.75rem; padding:4px 9px; border-radius:12px;
                                      border:1px solid var(--divider-color); background:none; cursor:pointer;
                                      color:var(--primary-text-color); }
        .acts button:hover, .quirk button:hover { border-color:var(--primary-color); }
        button.danger { color:var(--error-color,#b00); }
        .quirk { display:flex; gap:8px; align-items:baseline; margin-top:6px; font-size:.85rem; }
        .quirk .from { font-size:.72rem; color:var(--secondary-text-color); margin-left:auto; }
        .quirk .unconfirmed { font-size:.72rem; color:var(--warning-color,#b8860b); }
        .quirk.fact { opacity:.85; }
        .detail .line1 { gap:10px; justify-content:flex-start; }
        .steps { margin:10px 0; display:flex; flex-direction:column; gap:2px; }
        .step { display:flex; gap:8px; font-size:.85rem; padding:3px 0; color:var(--secondary-text-color); }
        .step .n { width:1.4em; text-align:right; opacity:.6; }
        .step.done { text-decoration:line-through; opacity:.5; }
        .step.here { color:var(--primary-text-color); font-weight:500; }
        .sub { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em;
               color:var(--secondary-text-color); margin-top:12px; }
        .history { margin-top:6px; display:flex; flex-direction:column; gap:2px;
                   font:12px ui-monospace,SFMono-Regular,Menlo,monospace; }
        .event { display:flex; gap:8px; }
        .event .what { width:5.5em; color:var(--primary-color); }
        .event .at { color:var(--secondary-text-color); }
        .event .detail-text { flex:1; }
        .event .step-n { color:var(--secondary-text-color); }
        @media (max-width:420px) { .since { margin-left:0; } .event .detail-text { word-break:break-word; } }
      `;
    }
  }

  customElements.define("stepwise-card", StepwiseCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "stepwise-card",
    name: "Stepwise",
    description:
      "Browse runs and their history, correct what a thing has learnt, and start or pick up a job.",
    preview: true,
  });
}

if (!customElements.get("stepwise-card")) {
  borrowLit().then(defineCard).catch((err) => {
    console.error("Stepwise card could not start:", err);
  });
}
