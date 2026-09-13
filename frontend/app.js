/* Schema-Driven Dashboard Platform — bonus UI.
   Nothing here knows what a "trade" is: every control is built from whatever
   specification the API reports. The prefilled values are the assignment's own
   example, and they are data, not logic. */
"use strict";

/* ---------------------------------------------------------------- registries
   Mirrors of the server's type and aggregation registries. They exist so the
   form can say which combinations are legal before anything is sent; the
   server remains the authority. */
const TYPES = ["string", "number", "integer", "boolean"];
const NUMERIC = ["number", "integer"];
const AGGREGATIONS = {
  sum: NUMERIC, avg: NUMERIC, min: NUMERIC, max: NUMERIC,
  count: TYPES,
};
const AGG_NAMES = Object.keys(AGGREGATIONS);
const aggsFor = (type) => AGG_NAMES.filter((a) => AGGREGATIONS[a].includes(type));
const aggLegal = (a, type) => !!AGGREGATIONS[a] && AGGREGATIONS[a].includes(type);

/* Every aggregation is offered on every parameter; the ones a type cannot
   carry are shown with the reason and left unselectable. Listing only the
   legal ones made a text parameter look like a platform that knows one
   aggregation, which is the opposite of what the registry says. */
const aggWhy = (a, type) =>
  !TYPES.includes(type) ? "give the parameter a type first"
    : aggLegal(a, type) ? ""
      : "numeric parameters only";

/** Fill an aggregation <select> from the registry, legality and all. */
function aggOptions(select, type, current, noneLabel) {
  select.appendChild(option("", noneLabel || "none", !current));
  AGG_NAMES.forEach((a) => {
    const why = aggWhy(a, type);
    const o = option(a, why ? a + " \u2014 " + why : a, a === current);
    o.disabled = !!why;
    select.appendChild(o);
  });
  // A value carried in from the JSON view can be one this type cannot take.
  // The option stays selected and marked, so the control never reads as
  // something other than what will be sent.
  select.classList.toggle("bad", !!current && !aggLegal(current, type));
}

/* -------------------------------------------------------------------- state */
const S = {
  draft: {
    name: "trade",
    fields: [
      { name: "tradeId", type: "string", required: true, aggregation: "" },
      { name: "amount", type: "number", required: true, aggregation: "sum" },
      { name: "status", type: "string", required: false, aggregation: "" },
    ],
  },
  specs: [],        // registered specification names
  cache: {},        // name -> full schema as the API reports it
  intakeBind: "",
  intakeRows: [
    { tradeId: "T001", amount: "1000", status: "OPEN" },
    { tradeId: "T002", amount: "12500", status: "OPEN" },
    { tradeId: "T003", amount: "11500", status: "SETTLED" },
  ],
  formatName: "trade-dashboard",
  formatBind: "",
  views: [
    { type: "summary", field: "amount", aggregation: "" },
    { type: "table", columns: ["tradeId", "amount", "status"] },
  ],
  dashboards: [],
  onFile: {},       // specification -> specimens known to be stored
  json: { spec: false, intake: false, format: false, cert: false },
};

/* ------------------------------------------------------------------ helpers */
const $ = (id) => document.getElementById(id);
const SECTION_OF = { spec: "sec-spec", intake: "sec-intake", format: "sec-format", cert: "sec-cert" };
const NS = "http://www.w3.org/2000/svg";

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
function icon(id) {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "ic");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(NS, "use");
  use.setAttribute("href", "#" + id);
  svg.appendChild(use);
  return svg;
}
function removeButton(label, onClick, disabled) {
  const b = el("button", "rm");
  b.type = "button";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.disabled = !!disabled;
  b.appendChild(icon("i-del"));
  b.addEventListener("click", onClick);
  return b;
}
function option(value, label, selected) {
  const o = el("option", null, label);
  o.value = value;
  if (selected) o.selected = true;
  return o;
}
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

/* Words for things the API names in codes. Types are spelled the way the
   sentence needs them, so a message reads as English and not as a schema. */
const q = (s) => "\u201C" + s + "\u201D";
const A_TYPE = {
  string: "text", number: "a number", integer: "a whole number", boolean: "true or false",
};
const aType = (t) => A_TYPE[t] || (t ? "a value of type " + t : "a different kind of value");
const humanList = (xs) =>
  xs.length <= 1 ? String(xs[0] || "")
    : xs.slice(0, -1).join(", ") + " or " + xs[xs.length - 1];

/** The specification a section is working against. Falls back to the section-1
 *  draft, marked provisional, so the whole page previews before registration. */
function resolvedSpec(bind) {
  if (bind && S.cache[bind]) {
    return { name: bind, fields: S.cache[bind].fields, provisional: false };
  }
  return {
    name: S.draft.name.trim(),
    fields: S.draft.fields.filter((f) => f.name.trim()),
    provisional: true,
  };
}

function setStamp(secId, stampId, text, phase) {
  $(secId).dataset.phase = phase;
  $(stampId).textContent = text;
}

/* ---------------------------------------------------------------------- api */
async function api(method, path, body) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (_) {
    // The API serves this page, so an unreachable API is a stopped server
    // rather than a bad URL. Status 0 is how `diagnose` recognises it.
    return { ok: false, status: 0, body: null };
  }
  let payload = null;
  try { payload = await res.json(); } catch (_) { payload = null; }
  return { ok: res.ok, status: res.status, body: payload };
}

async function refresh() {
  const [schemas, dashboards] = await Promise.all([
    api("GET", "/schema"), api("GET", "/dashboard"),
  ]);
  S.specs = (schemas.ok && Array.isArray(schemas.body)) ? schemas.body : [];
  S.dashboards = (dashboards.ok && Array.isArray(dashboards.body)) ? dashboards.body : [];
  await Promise.all(S.specs.filter((n) => !S.cache[n]).map(async (n) => {
    const r = await api("GET", "/schema/" + encodeURIComponent(n));
    if (r.ok) S.cache[n] = r.body;
  }));
  if (!S.intakeBind || !S.specs.includes(S.intakeBind)) S.intakeBind = S.specs[0] || "";
  renderAll();
}

/* ============================================================ 1 SPECIFICATION */
function renderSpecRows() {
  const body = $("spec-rows");
  clear(body);
  S.draft.fields.forEach((f, i) => {
    const tr = el("tr");
    const ord = el("td", "c-idx", String(i + 1));
    ord.dataset.label = "#";
    tr.appendChild(ord);

    const nameCell = el("td");
    nameCell.dataset.label = "name";
    const name = el("input");
    name.type = "text"; name.value = f.name; name.spellcheck = false;
    name.placeholder = "parameter name";
    name.setAttribute("aria-label", "Parameter " + (i + 1) + " name");
    name.addEventListener("input", () => { f.name = name.value; propagate(); });
    nameCell.appendChild(name);
    tr.appendChild(nameCell);

    const typeCell = el("td", "c-type");
    typeCell.dataset.label = "type";
    const type = el("select");
    type.setAttribute("aria-label", "Parameter " + (i + 1) + " type");
    TYPES.forEach((t) => type.appendChild(option(t, t, t === f.type)));
    type.addEventListener("change", () => {
      f.type = type.value;
      if (f.aggregation && !aggsFor(f.type).includes(f.aggregation)) f.aggregation = "";
      renderSpecRows(); propagate();
    });
    typeCell.appendChild(type);
    tr.appendChild(typeCell);

    const reqCell = el("td", "c-req");
    reqCell.dataset.label = "required";
    const req = el("input");
    req.type = "checkbox"; req.checked = !!f.required;
    req.setAttribute("aria-label", "Parameter " + (i + 1) + " required");
    req.addEventListener("change", () => { f.required = req.checked; propagate(); });
    reqCell.appendChild(req);
    tr.appendChild(reqCell);

    const aggCell = el("td", "c-agg");
    aggCell.dataset.label = "aggregation";
    const agg = el("select");
    agg.setAttribute("aria-label", "Parameter " + (i + 1) + " default determination");
    aggOptions(agg, f.type, f.aggregation);
    agg.addEventListener("change", () => { f.aggregation = agg.value; propagate(); });
    aggCell.appendChild(agg);
    tr.appendChild(aggCell);

    const act = el("td", "c-act");
    act.dataset.label = "";
    act.appendChild(removeButton("Remove parameter " + (i + 1), () => {
      S.draft.fields.splice(i, 1); renderSpecRows(); propagate();
    }, S.draft.fields.length <= 1));
    tr.appendChild(act);

    body.appendChild(tr);
  });
}

function specPayload() {
  return {
    name: S.draft.name.trim(),
    fields: S.draft.fields.map((f) => {
      const out = { name: f.name.trim(), type: f.type };
      if (f.required) out.required = true;
      if (f.aggregation) out.aggregation = f.aggregation;
      return out;
    }),
  };
}

/* ============================================================= 2 SPECIMEN INTAKE */
function renderIntake() {
  const spec = resolvedSpec(S.intakeBind);
  const head = $("intake-head");
  const body = $("intake-rows");
  clear(head); clear(body);

  const bind = $("intake-bind");
  clear(bind);
  if (S.specs.length) {
    S.specs.forEach((n) => bind.appendChild(option(n, n, n === S.intakeBind)));
  } else {
    bind.appendChild(option("", "— none registered —", true));
  }
  bind.disabled = !S.specs.length;

  const note = $("intake-bindnote");
  note.textContent = spec.provisional
    ? "Provisional. These columns follow the draft above and update as you edit it. Register the specification to enable intake."
    : spec.fields.length + " parameter" + (spec.fields.length === 1 ? "" : "s") +
      ", " + spec.fields.filter((f) => f.required).length + " required.";

  if (!spec.fields.length) {
    const tr = el("tr");
    const td = el("td");
    td.colSpan = 2;
    td.appendChild(el("div", "empty-line", "Declare at least one parameter in section 1."));
    tr.appendChild(td); body.appendChild(tr);
    $("intake-add").disabled = true;
    return;
  }
  $("intake-add").disabled = spec.provisional;

  const idxHead = el("th", "c-idx");
  idxHead.appendChild(el("span", "kk", "row"));
  head.appendChild(idxHead);
  spec.fields.forEach((f) => {
    const th = el("th");
    th.appendChild(document.createTextNode(f.name));
    const t = el("span", "t", f.type + (f.required ? " · required" : ""));
    th.appendChild(t);
    head.appendChild(th);
  });
  head.appendChild(el("th", "c-act"));

  S.intakeRows.forEach((row, i) => {
    const tr = el("tr");
    tr.dataset.row = String(i);
    const idx = el("td", "c-idx", String(i));
    idx.dataset.label = "row";
    idx.title = "row " + i + " in the rows array";
    tr.appendChild(idx);
    spec.fields.forEach((f) => {
      const td = el("td");
      td.dataset.field = f.name;
      td.dataset.label = f.name;
      let input;
      if (f.type === "boolean") {
        input = el("select");
        [["", "—"], ["true", "true"], ["false", "false"]].forEach(([v, l]) =>
          input.appendChild(option(v, l, String(row[f.name] ?? "") === v)));
      } else {
        input = el("input");
        input.type = NUMERIC.includes(f.type) ? "number" : "text";
        if (f.type === "integer") input.step = "1";
        else if (f.type === "number") input.step = "any";
        input.spellcheck = false;
        input.value = row[f.name] ?? "";
        input.placeholder = f.required ? "" : "optional";
      }
      input.setAttribute("aria-label", f.name + ", specimen " + (i + 1));
      input.disabled = spec.provisional;
      input.addEventListener("input", () => { row[f.name] = input.value; syncJson("intake"); });
      input.addEventListener("change", () => { row[f.name] = input.value; syncJson("intake"); });
      td.appendChild(input);
      tr.appendChild(td);
    });
    const act = el("td", "c-act");
    act.dataset.label = "";
    act.appendChild(removeButton("Remove specimen " + (i + 1), () => {
      S.intakeRows.splice(i, 1); renderIntake(); syncJson("intake");
    }, spec.provisional || S.intakeRows.length <= 1));
    tr.appendChild(act);
    body.appendChild(tr);
  });
}

function intakePayload() {
  const spec = resolvedSpec(S.intakeBind);
  const rows = S.intakeRows.map((row) => {
    const out = {};
    spec.fields.forEach((f) => {
      const raw = row[f.name];
      if (raw === undefined || raw === null || raw === "") return;
      if (NUMERIC.includes(f.type)) {
        const n = Number(raw);
        out[f.name] = Number.isNaN(n) ? raw : n;
      } else if (f.type === "boolean") {
        out[f.name] = raw === "true" || raw === true;
      } else {
        out[f.name] = String(raw);
      }
    });
    return out;
  });
  return { schema: spec.name, rows };
}

/* ============================================================== 3 REPORT FORMAT */
function renderFormat() {
  const spec = resolvedSpec(S.formatBind || S.intakeBind);
  const host = $("format-views");
  clear(host);

  const bind = $("format-bind");
  clear(bind);
  bind.appendChild(option("", "— leave blank (infer) —", !S.formatBind));
  S.specs.forEach((n) => bind.appendChild(option(n, n, n === S.formatBind)));
  bind.disabled = !S.specs.length;
  $("format-name").value = S.formatName;

  const note = $("format-bindnote");
  if (!S.specs.length) {
    note.textContent = "Blank is refused while nothing is registered: NO_SCHEMA_REGISTERED.";
  } else if (S.specs.length === 1) {
    note.textContent = "Blank is inferred: exactly one specification is on file. This is the assignment's own config, which carries no binding.";
  } else {
    note.textContent = "Blank is refused now: AMBIGUOUS_SCHEMA. " + S.specs.length +
      " specifications are on file, so the binding is not unique.";
  }

  const disabled = spec.provisional;

  if (!S.views.length) {
    host.appendChild(el("div", "empty-line", "No views configured. A report needs at least one."));
  }

  S.views.forEach((v, i) => {
    const row = el("div", "view");
    row.appendChild(el("span", "vkind", v.type === "summary" ? "Determination" : "Results table"));

    if (v.type === "summary") {
      const fieldWrap = el("label", "field inline");
      fieldWrap.appendChild(el("span", "lab", "Parameter"));
      const fsel = el("select");
      fsel.disabled = disabled;
      spec.fields.forEach((f) => fsel.appendChild(option(f.name, f.name, f.name === v.field)));
      if (!spec.fields.some((f) => f.name === v.field)) {
        fsel.insertBefore(option(v.field, v.field + " (not in specification)", true), fsel.firstChild);
      }
      fsel.addEventListener("change", () => {
        v.field = fsel.value;
        const t = (spec.fields.find((f) => f.name === v.field) || {}).type;
        if (v.aggregation && t && !aggsFor(t).includes(v.aggregation)) v.aggregation = "";
        renderFormat(); syncJson("format");
      });
      fieldWrap.appendChild(fsel);
      row.appendChild(fieldWrap);

      const target = spec.fields.find((f) => f.name === v.field);
      const aggWrap = el("label", "field inline");
      aggWrap.appendChild(el("span", "lab", "Determination"));
      const asel = el("select");
      asel.disabled = disabled;
      const specDefault = target && target.aggregation;
      aggOptions(asel, target ? target.type : "", v.aggregation, specDefault
        ? "specification default (" + specDefault + ")"
        : "— none — ");
      asel.addEventListener("change", () => { v.aggregation = asel.value; syncJson("format"); });
      aggWrap.appendChild(asel);
      row.appendChild(aggWrap);
    } else {
      const wrap = el("div", "cols");
      spec.fields.forEach((f) => {
        const lab = el("label");
        const cb = el("input");
        cb.type = "checkbox";
        cb.checked = v.columns.includes(f.name);
        cb.disabled = disabled;
        cb.addEventListener("change", () => {
          v.columns = spec.fields.filter((x) =>
            x.name === f.name ? cb.checked : v.columns.includes(x.name)).map((x) => x.name);
          syncJson("format");
        });
        lab.appendChild(cb);
        lab.appendChild(document.createTextNode(f.name));
        lab.appendChild(el("span", "ty", f.type));
        wrap.appendChild(lab);
      });
      row.appendChild(wrap);
    }

    row.appendChild(removeButton("Remove view " + (i + 1), () => {
      S.views.splice(i, 1); renderFormat(); syncJson("format");
    }, disabled));
    host.appendChild(row);
  });

  document.querySelectorAll("[data-addview]").forEach((b) => { b.disabled = disabled; });
}

function formatPayload() {
  const out = { name: S.formatName.trim() };
  if (S.formatBind) out.schema = S.formatBind;
  out.views = S.views.map((v) => {
    if (v.type === "summary") {
      const s = { type: "summary", field: v.field };
      if (v.aggregation) s.aggregation = v.aggregation;
      return s;
    }
    return { type: "table", columns: v.columns.slice() };
  });
  return out;
}

/* ================================================================ 4 CERTIFICATE */
function renderCertControls() {
  const pick = $("cert-pick");
  const current = pick.value;
  clear(pick);
  if (S.dashboards.length) {
    S.dashboards.forEach((n) => pick.appendChild(option(n, n, n === current)));
  } else {
    pick.appendChild(option("", "— none registered —", true));
  }
  pick.disabled = !S.dashboards.length;
  $("cert-send").disabled = !S.dashboards.length;
}

function renderCertificate(host, body) {
  const cert = el("div", "cert");

  const id = el("div", "cert-id");
  const item = (k, v, mono) => {
    const d = el("div", "ci");
    d.appendChild(el("span", "k", k));
    d.appendChild(el("span", "v" + (mono ? " mono" : ""), v));
    return d;
  };
  id.appendChild(item("Report", String(body.dashboard ?? "—")));
  id.appendChild(item("Specification", String(body.schema ?? "—")));
  id.appendChild(item("Specimens on file", String(body.rowCount ?? "—")));
  id.appendChild(item("Issued", new Date().toISOString().replace("T", " ").slice(0, 19) + "Z", true));
  cert.appendChild(id);

  const views = Array.isArray(body.views) ? body.views : [];
  const summaries = views.filter((v) => v.type === "summary");
  const tables = views.filter((v) => v.type === "table");
  const others = views.filter((v) => v.type !== "summary" && v.type !== "table");
  let sawNull = false;

  if (summaries.length) {
    cert.appendChild(el("h3", null, "Determinations"));
    const t = el("table", "det");
    const thead = el("thead");
    const hr = el("tr");
    ["Parameter", "Method", "Result"].forEach((h, i) => {
      const th = el("th", i === 2 ? "d-val" : null, h);
      hr.appendChild(th);
    });
    thead.appendChild(hr); t.appendChild(thead);
    const tb = el("tbody");
    summaries.forEach((v) => {
      const tr = el("tr");
      tr.appendChild(el("td", "d-name", String(v.field ?? "—")));
      tr.appendChild(el("td", "d-agg", String(v.aggregation ?? "—")));
      const isNil = v.value === null || v.value === undefined;
      if (isNil) sawNull = true;
      tr.appendChild(el("td", "d-val" + (isNil ? " nil" : ""),
        isNil ? "no result" : String(v.value)));
      tb.appendChild(tr);
    });
    t.appendChild(tb); cert.appendChild(t);
  }

  tables.forEach((v) => {
    cert.appendChild(el("h3", null, "Results"));
    const wrap = el("div", "scroll");
    const t = el("table", "results");
    const thead = el("thead");
    const hr = el("tr");
    // "no." not "#": section 2 numbers specimens by their zero-based `row`, and
    // two bare ordinals on one sheet would read as the same index twice.
    hr.appendChild(el("th", "c-idx", "no."));
    const cols = Array.isArray(v.columns) ? v.columns : [];
    const spec = S.cache[body.schema];
    cols.forEach((c) => {
      const th = el("th");
      th.appendChild(document.createTextNode(c));
      const f = spec && spec.fields.find((x) => x.name === c);
      if (f) th.appendChild(el("span", "ty", f.type));
      hr.appendChild(th);
    });
    thead.appendChild(hr); t.appendChild(thead);
    const tb = el("tbody");
    (v.rows || []).forEach((row, i) => {
      const tr = el("tr");
      tr.appendChild(el("td", "c-idx", String(i + 1)));
      cols.forEach((c) => {
        const raw = row[c];
        const isNil = raw === null || raw === undefined;
        if (isNil) sawNull = true;
        const numeric = typeof raw === "number";
        const td = el("td", (isNil ? "nil" : "") + (numeric ? " n" : ""),
          isNil ? "—" : (typeof raw === "object" ? JSON.stringify(raw) : String(raw)));
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
    if (!(v.rows || []).length) {
      const tr = el("tr");
      const td = el("td");
      td.colSpan = cols.length + 1;
      td.appendChild(el("div", "empty-line", "No specimens on file for this specification."));
      tr.appendChild(td); tb.appendChild(tr);
    }
    t.appendChild(tb); wrap.appendChild(t); cert.appendChild(wrap);
  });

  others.forEach((v) => {
    cert.appendChild(el("h3", null, String(v.type)));
    cert.appendChild(el("pre", "raw", JSON.stringify(v, null, 2)));
  });

  if (sawNull) {
    cert.appendChild(el("p", "legend",
      "— denotes an optional parameter with no value on file. It is reported as null rather than omitted, so every row stays rectangular."));
  }
  host.appendChild(cert);
}

/* ----------------------------------------------------------------- precheck
   A form that is simply not filled in yet should not have to ask the server.
   These checks run only in form mode: in JSON mode the textarea is authoritative
   and sending a deliberately invalid payload is the whole point of the hatch. */

function clearMarks(scope) {
  (scope || document).querySelectorAll(".bad").forEach((n) => n.classList.remove("bad"));
}

function precheck(key) {
  if (S.json[key]) return [];
  const out = [];
  const at = (nodes, msg, fix) =>
    out.push({ nodes: [].concat(nodes || []).filter(Boolean), msg: msg, fix: fix });
  const blank = (v) => v === undefined || v === null || String(v).trim() === "";

  if (key === "spec") {
    const name = S.draft.name.trim();
    if (!name) at($("spec-name"), "Specification name is required.");
    else if (S.specs.includes(name)) {
      const next = suggestName(name, S.specs);
      at($("spec-name"), "A specification named " + q(name) + " is already on file, and names " +
        "are never reused. Give this one a different name, or carry on with the one already " +
        "registered.",
        { label: "Use " + q(next) + " instead",
          run: () => { S.draft.name = next; $("spec-name").value = next; propagate(); focusOn("spec-name"); } });
    }
    const rows = [...document.querySelectorAll("#spec-rows tr")];
    const seen = new Map();
    S.draft.fields.forEach((f, i) => {
      const input = rows[i] && rows[i].querySelector('td[data-label="name"] input');
      const pname = f.name.trim();
      if (!pname) at(input, "Parameter " + (i + 1) + " needs a name.");
      else if (seen.has(pname)) {
        at(input, "\u201C" + pname + "\u201D is already used by parameter " + (seen.get(pname) + 1) + ".");
      } else seen.set(pname, i);

      // The JSON view can hand back an aggregation this type cannot carry.
      // Saying so here costs nothing and saves a round trip into a 422.
      if (f.aggregation && !aggLegal(f.aggregation, f.type)) {
        const sel = rows[i] && rows[i].querySelector('td[data-label="aggregation"] select');
        const legal = aggsFor(f.type);
        at(sel, q(f.aggregation) + " cannot apply to " +
          (pname ? q(pname) : "parameter " + (i + 1)) + ", which holds " + aType(f.type) + ". " +
          (legal.length
            ? "Use " + humanList(legal) + ", or change the type to number."
            : "Give the parameter a type first."));
      }
    });
    if (!S.draft.fields.length) at(null, "A specification needs at least one parameter.");

  } else if (key === "intake") {
    const spec = resolvedSpec(S.intakeBind);
    if (!S.intakeRows.length) at(null, "Add at least one specimen.");
    S.intakeRows.forEach((row, i) => {
      const tr = document.querySelector('#intake-rows tr[data-row="' + i + '"]');
      const cell = (fieldName) => {
        const td = tr && tr.querySelector('td[data-field="' + CSS.escape(fieldName) + '"]');
        return td && td.querySelector("input, select");
      };
      if (spec.fields.every((f) => blank(row[f.name]))) {
        // Mark every required cell, not just the first: the whole row is empty.
        at(spec.fields.filter((f) => f.required).map((f) => cell(f.name)),
           "Row " + i + " is empty.");
        return;
      }
      spec.fields.filter((f) => f.required).forEach((f) => {
        if (blank(row[f.name])) at(cell(f.name), "Row " + i + " is missing " + f.name + ".");
      });
    });

  } else if (key === "format") {
    const name = S.formatName.trim();
    if (!name) at($("format-name"), "Report name is required.");
    else if (S.dashboards.includes(name)) {
      const next = suggestName(name, S.dashboards);
      at($("format-name"), "A report named " + q(name) + " is already registered, and names " +
        "are never reused. Give this one a different name, or carry on with the one already " +
        "registered.",
        { label: "Use " + q(next) + " instead",
          run: () => { S.formatName = next; $("format-name").value = next; syncJson("format"); focusOn("format-name"); } });
    }
    if (!S.views.length) at(null, "A report needs at least one view.");
    const bound = resolvedSpec(S.formatBind || S.intakeBind);
    S.views.forEach((v, i) => {
      if (v.type === "summary" && !v.field) at(null, "Determination " + (i + 1) + " has no parameter.");
      if (v.type === "table" && !v.columns.length) {
        at(null, "Results table " + (i + 1) + " has no columns selected.");
      }
      if (v.type !== "summary" || !v.field) return;
      // FR-3.7 and FR-3.8 asked before the round trip: the determination has
      // to resolve to something, and to something the parameter can take.
      const target = bound.fields.find((f) => f.name === v.field);
      if (!target) return;
      const agg = v.aggregation || target.aggregation || "";
      if (!agg) {
        at(null, "Determination " + (i + 1) + " on " + q(v.field) + " does not say how to " +
          "aggregate, and " + q(v.field) + " has no default in the specification. Choose one " +
          "here, or set a default in section 1.");
      } else if (!aggLegal(agg, target.type)) {
        const legal = aggsFor(target.type);
        at(null, "Determination " + (i + 1) + ": " + q(agg) + " cannot apply to " + q(v.field) +
          ", which holds " + aType(target.type) + "." +
          (legal.length ? " Use " + humanList(legal) + "." : ""));
      }
    });

  } else if (key === "cert") {
    if (!$("cert-pick").value) at($("cert-pick"), "Select a report to draw.");
  }
  return out;
}

function renderPrecheck(host, problems) {
  problems.forEach((p) => p.nodes.forEach((n) => n.classList.add("bad")));
  const box = el("div", "precheck");
  const head = el("div", "precheck-head");
  head.appendChild(icon("i-flag"));
  // Covers both shapes this block reports: a field with no value, and a name
  // that has one but is already taken.
  head.appendChild(el("p", "precheck-msg",
    problems.length === 1
      ? "Nothing was sent. One problem to fix."
      : "Nothing was sent. " + problems.length + " problems to fix."));
  box.appendChild(head);
  const list = el("ul", "precheck-list");
  problems.forEach((p) => list.appendChild(el("li", null, p.msg)));
  box.appendChild(list);
  const settles = problems.find((p) => p.fix);
  if (settles) {
    const act = el("div", "oos-actions");
    const b = el("button", "btn oos-fix", settles.fix.label);
    b.type = "button";
    b.addEventListener("click", () => { clear(host); clearMarks(document); settles.fix.run(); });
    act.appendChild(b);
    box.appendChild(act);
  }
  host.appendChild(box);
  const first = problems.find((p) => p.nodes.length);
  if (first) first.nodes[0].focus();
}

/* ---------------------------------------------------------------- diagnosis
   The API answers a failure with a code. A code is the right thing to put on
   the wire and the wrong thing to put in front of a person, so nothing below
   prints one: every response becomes a sentence that names what to change and
   where to change it. The literal body stays one disclosure away, for a reader
   who wants the contract rather than the advice. */

const PANEL = {
  spec:   { thing: "specification", nameId: "spec-name",   bindId: null },
  intake: { thing: "batch",         nameId: null,          bindId: "intake-bind" },
  format: { thing: "report",        nameId: "format-name", bindId: "format-bind" },
  cert:   { thing: "report",        nameId: null,          bindId: "cert-pick" },
};

/** The number of findings shown as sentences; the rest stay in the raw body. */
const ITEM_CAP = 8;

/** The next free name in the same shape as the one that was taken. */
function suggestName(base, taken) {
  const stem = /^(.*?)(\d+)$/.exec(String(base || "").trim());
  const head = stem ? stem[1] : (String(base || "").trim() + "-" || "untitled-");
  let n = stem ? Number(stem[2]) + 1 : 2;
  while (taken.includes(head + n)) n += 1;
  return head + n;
}

/** Put the reader where the fix is made, rather than describing where it is. */
function focusOn(id, secId) {
  if (secId && $(secId)) $(secId).scrollIntoView({ behavior: "smooth", block: "start" });
  const node = id && $(id);
  if (node) { node.classList.remove("bad"); node.focus({ preventScroll: !!secId }); }
}

/** `fields[0].name` → `parameter 1 · name`, numbered the way the panel is. */
function prettyPath(path) {
  return String(path).split(".").map((part) => {
    const m = /^([A-Za-z_]+)\[(\d+)\]$/.exec(part);
    if (!m) return part;
    const n = Number(m[2]);
    if (m[1] === "fields") return "parameter " + (n + 1);
    if (m[1] === "views") return "view " + (n + 1);
    if (m[1] === "rows") return "row " + n;
    return m[1] + " " + (n + 1);
  }).join(" · ");
}

/** Where a finding is, in the terms the panel labels its own rows with.
 *
 *  Empty when the sentence already says it: a finding on one parameter names
 *  that parameter, and a chip repeating it is furniture. */
function whereOf(d) {
  const field = typeof d.field === "string" ? d.field : "";
  if (d.row !== undefined && d.row !== null) {
    return "Row " + d.row + (field ? " · " + field : "");
  }
  const path = field ? prettyPath(field) : "";
  return path.includes(" · ") ? path : "";
}

/** The view a `views[i].x` path points into, as it was sent. */
function sentView(ctx, path) {
  const m = /^views\[(\d+)\]/.exec(String(path));
  const views = ctx.sent && Array.isArray(ctx.sent.views) ? ctx.sent.views : [];
  return m ? views[Number(m[1])] : undefined;
}

/** The determination that failed on a field.
 *
 *  An INVALID_AGGREGATION names the field and the field's type -- not the
 *  aggregation, which the caller already knows it sent. True of the contract,
 *  useless in a sentence, so it is read back off the body we posted. */
function chosenAggregation(ctx, d) {
  const sent = ctx.sent || {};
  const field = typeof d.field === "string" ? d.field : "";
  const leaf = field.split(".").pop();
  if (Array.isArray(sent.fields)) {
    const f = sent.fields.find((x) => x && x.name === leaf);
    if (f && f.aggregation) return f.aggregation;
  }
  const view = sentView(ctx, field);
  if (view && view.aggregation) return view.aggregation;
  // A view that named none fell through to the specification's default.
  const target = resolvedSpec(S.formatBind || S.intakeBind).fields.find((x) => x.name === leaf);
  return (target && target.aggregation) || "";
}

/** One finding, said as a sentence that ends in something to do. */
function sentence(d, ctx) {
  const field = typeof d.field === "string" ? d.field : "";
  const leaf = field.split(".").pop().replace(/\[\d+\]$/, "");
  const inRow = d.row !== undefined && d.row !== null;
  const named = leaf ? q(leaf) : "that value";

  switch (d.code) {
    case "MISSING_REQUIRED_FIELD":
      if (inRow) {
        return named + " is required, and this specimen leaves it blank. Enter a value, " +
          "or make the parameter optional in section 1.";
      }
      if (leaf === "fields") return "A specification needs at least one parameter.";
      if (leaf === "rows") return "There are no specimens to submit. Add at least one row.";
      if (leaf === "views") return "A report needs at least one view — a determination or a results table.";
      if (leaf === "columns") return "A results table needs at least one column. Tick the parameters it should show.";
      if (leaf === "field") return "A determination has to name the parameter it measures. Choose one.";
      if (leaf === "type") {
        return ctx.key === "format"
          ? "A view has to say what kind it is — a determination or a results table."
          : "Every parameter needs a type.";
      }
      if (leaf === "name") return "A name is required, and this one is blank.";
      if (leaf === "schema") return "This request has to name the specification it works against.";
      return named + " is required and was not supplied.";

    case "TYPE_MISMATCH":
      if (inRow) {
        return named + " takes " + aType(d.expected) + ", and this specimen holds " +
          (d.actual ? aType(d.actual) : "something else") +
          ". Correct the value, or change the parameter's type in section 1.";
      }
      return named + " is not the shape this request expects" +
        (d.expected ? " — " + aType(d.expected) + " was expected" : "") +
        ". The form view writes the body correctly if you would rather not write it by hand.";

    case "UNKNOWN_FIELD": {
      if (inRow) {
        return "The specification does not declare " + named + ", so no specimen can carry it. " +
          "Clear it here, or add " + named + " as a parameter in section 1.";
      }
      const view = sentView(ctx, field);
      if (view && Object.prototype.hasOwnProperty.call(view, leaf)) {
        return named + " is not a setting this kind of view accepts. Remove it.";
      }
      if (ctx.key === "format") {
        const names = resolvedSpec(S.formatBind || S.intakeBind).fields.map((f) => f.name);
        return named + " is not a parameter of the specification this report is bound to." +
          (names.length ? " Available: " + humanList(names) + "." : "");
      }
      return named + " is not a key this request accepts. Remove it.";
    }

    case "UNKNOWN_TYPE": {
      const offered = d.expected ? humanList(d.expected.split(", ")) : "";
      if (leaf === "type") {
        return (d.actual ? q(d.actual) + " is" : "That is") + " not a kind of view." +
          (offered ? " Choose " + offered + "." : "");
      }
      return named + " is declared as " + q(d.actual || "an unknown type") +
        ", which is not a type the platform has." + (offered ? " Choose " + offered + "." : "");
    }

    case "UNKNOWN_AGGREGATION": {
      const offered = d.expected ? humanList(d.expected.split(", ")) : "";
      return q(d.actual || "that determination") + " is not a determination the platform knows" +
        (leaf ? ", and " + named + " asks for it" : "") + "." +
        (offered ? " Choose " + offered + "." : "");
    }

    case "INVALID_AGGREGATION": {
      const chosen = chosenAggregation(ctx, d);
      const legal = aggsFor(d.actual);
      return (chosen ? q(chosen) : "That determination") + " cannot apply to " + named +
        ", which holds " + aType(d.actual) + ". " +
        (legal.length
          ? "Use " + humanList(legal) + " instead, or change the parameter to a number type."
          : "Give the parameter a numeric type, or choose another determination.");
    }

    case "AGGREGATION_REQUIRED":
      return named + " has no default determination in the specification, so the view has to " +
        "name one. Choose an aggregation here, or set a default for " + named + " in section 1.";

    case "DUPLICATE_NAME":
      if (ctx.key === "format") return named + " is listed twice in the same results table. Untick one.";
      return "Two parameters are named " + named + ". Parameter names have to be unique — rename one.";

    case "INVALID_NAME":
      return "A name cannot be blank or contain a slash, because the name is how the " +
        (PANEL[ctx.key] || PANEL.spec).thing + " is fetched back. Letters, digits, dashes " +
        "and underscores are safe.";

    default:
      return "Something about " + named + " was not accepted. The technical details below " +
        "carry the platform's own words.";
  }
}

/** A whole response, turned into a headline, a paragraph, and a to-do list. */
function diagnose(status, body, ctx) {
  const panel = PANEL[ctx.key] || PANEL.spec;
  const sent = ctx.sent || {};
  const code = body && body.error;
  const details = (body && Array.isArray(body.details)) ? body.details : [];
  const out = { head: "", lead: "", items: [], more: "", fix: null };

  if (!status) {
    out.head = "The platform did not answer.";
    out.lead = "Nothing was sent and nothing was changed. This page is served by the API " +
      "itself, so if it has stopped, start it again and resend.";
    return out;
  }

  // 409. The one failure with an obvious next move, so the panel offers it.
  if (code === "DUPLICATE_NAME") {
    const taken = String(sent.name || "").trim();
    const pool = ctx.key === "format" ? S.dashboards : S.specs;
    out.head = taken ? "The name " + q(taken) + " is already in use." : "That name is already in use.";
    out.lead = "Names are never reused, so nothing was registered and the " + panel.thing +
      " already on file was left exactly as it was. Give this one a different name, or " +
      "carry on with the one already registered.";
    if (panel.nameId) {
      const next = suggestName(taken, pool);
      out.fix = {
        label: "Use " + q(next) + " instead",
        run: () => {
          if (ctx.key === "format") {
            S.formatName = next; $("format-name").value = next; syncJson("format");
          } else {
            S.draft.name = next; $("spec-name").value = next; propagate();
          }
          focusOn(panel.nameId);
        },
      };
    }
    return out;
  }

  if (code === "UNKNOWN_SCHEMA") {
    const wanted = String(sent.schema || "").trim();
    out.head = wanted
      ? "No specification named " + q(wanted) + " is on file."
      : "That specification is not on file.";
    out.lead = S.specs.length
      ? "Nothing was stored. Point this at one of the specifications already registered: " +
        humanList(S.specs) + "."
      : "Nothing was stored. Register a specification in section 1 first — everything " +
        "here is checked against one.";
    out.fix = S.specs.length
      ? { label: "Choose a registered specification",
          run: () => focusOn(panel.bindId, SECTION_OF[ctx.key]) }
      : { label: "Go to section 1", run: () => focusOn("spec-name", "sec-spec") };
    return out;
  }

  if (code === "UNKNOWN_DASHBOARD") {
    out.head = "That report is not registered.";
    out.lead = S.dashboards.length
      ? "Nothing was drawn. Pick one that is: " + humanList(S.dashboards) + "."
      : "No report has been configured yet. Configure one in section 3, then draw it here.";
    out.fix = S.dashboards.length
      ? { label: "Pick a registered report", run: () => focusOn("cert-pick", "sec-cert") }
      : { label: "Go to section 3", run: () => focusOn("format-name", "sec-format") };
    return out;
  }

  if (code === "AMBIGUOUS_SCHEMA") {
    out.head = "This report does not say which specification it belongs to.";
    out.lead = "More than one is on file" + (S.specs.length ? " — " + S.specs.join(", ") + " — " : ", ") +
      "and the platform will not guess. Choose one in “Against specification” above " +
      "and send again.";
    out.fix = { label: "Choose a specification", run: () => focusOn("format-bind", "sec-format") };
    return out;
  }

  if (code === "NO_SCHEMA_REGISTERED") {
    out.head = "There is no specification to bind this report to.";
    out.lead = "A report's views are checked against a specification's parameters, and none " +
      "is registered yet. Register one in section 1, then come back.";
    out.fix = { label: "Go to section 1", run: () => focusOn("spec-name", "sec-spec") };
    return out;
  }

  if (code === "INTERNAL_ERROR" || status >= 500) {
    out.head = "The platform could not complete that.";
    out.lead = "Nothing was saved. Try again — if it keeps happening, the technical " +
      "details below carry what the server reported.";
    return out;
  }

  if (code !== "VALIDATION_FAILED" && !details.length) {
    out.head = "The request did not go through.";
    out.lead = "Nothing was changed. The technical details below carry the platform's own words.";
    return out;
  }

  // 422. What was wrong is in `details`; what to do about it is a sentence each.
  const n = details.length;
  const count = n === 1 ? "One thing" : n + " things";
  const shown = n > ITEM_CAP ? ", the first " + ITEM_CAP + " here" : "";
  if (ctx.key === "intake") {
    out.head = "The batch was rejected — nothing was stored.";
    out.lead = n
      ? "Intake is all-or-nothing, so every specimen has to conform. " + count + " to fix" +
        shown + (S.json.intake ? ":" : ", and the rows they are in are marked above:")
      : "Intake is all-or-nothing, so every specimen has to conform.";
  } else if (ctx.key === "format") {
    out.head = "The report was not registered.";
    out.lead = n
      ? "A report is checked against its specification when it is written, not when it is " +
        "drawn. " + count + " to fix" + shown + ":"
      : "A report is checked against its specification when it is written.";
  } else {
    out.head = "The specification was not registered.";
    out.lead = n ? count + " to fix" + shown + "; nothing was stored." : "Nothing was stored.";
  }
  out.items = details.slice(0, ITEM_CAP).map((d) => ({ where: whereOf(d), say: sentence(d, ctx) }));
  if (n > ITEM_CAP) {
    out.more = (n - ITEM_CAP) + " more are listed in the technical details below.";
  }
  return out;
}

/* ------------------------------------------------------------------- results */
function renderReceipt(host, status, text, meta) {
  const box = el("div", "receipt");
  box.appendChild(icon("i-check"));
  box.appendChild(el("span", "r-txt", text));
  box.appendChild(el("span", "r-meta", "HTTP " + status + (meta ? " · " + meta : "")));
  host.appendChild(box);
}

/** Paint a diagnosis. `raw` is the response it came from, or null if the
 *  request never left the page. */
function paintProblem(host, diag, raw) {
  const box = el("div", "oos");

  const head = el("div", "oos-head");
  head.appendChild(icon("i-flag"));
  const txt = el("div");
  txt.appendChild(el("p", "oos-msg", diag.head));
  if (diag.lead) txt.appendChild(el("p", "oos-lead", diag.lead));
  head.appendChild(txt);
  box.appendChild(head);

  if (diag.items.length) {
    const list = el("ul", "oos-list");
    diag.items.forEach((it, i) => {
      const li = el("li");
      li.style.setProperty("--d", (i * 110) + "ms");
      const line = el("p", "oos-say");
      if (it.where) line.appendChild(el("span", "oos-where", it.where));
      line.appendChild(document.createTextNode(it.say));
      li.appendChild(line);
      list.appendChild(li);
    });
    box.appendChild(list);
  }
  if (diag.more) box.appendChild(el("p", "oos-more", diag.more));

  if (diag.fix) {
    const act = el("div", "oos-actions");
    const b = el("button", "btn oos-fix", diag.fix.label);
    b.type = "button";
    b.addEventListener("click", () => { clear(host); diag.fix.run(); });
    act.appendChild(b);
    box.appendChild(act);
  }

  // Nothing in the response is reachable only by paraphrase -- but the codes
  // are an implementation detail of the contract, so they wait behind a
  // disclosure instead of being the first thing the reader meets.
  if (raw && raw.body && typeof raw.body === "object") {
    const d = el("details", "rawbox");
    d.appendChild(el("summary", null, "Technical details"));
    d.appendChild(el("pre", "raw", "HTTP " + raw.status + "\n" +
      JSON.stringify(raw.body, null, 2)));
    box.appendChild(d);
  }
  host.appendChild(box);
}

function renderError(host, status, body, ctx) {
  paintProblem(host, diagnose(status, body, ctx || {}), { status: status, body: body });
}

function flagIntake(details) {
  document.querySelectorAll("#intake-rows tr").forEach((tr) => {
    tr.classList.remove("flagged");
    tr.querySelectorAll("td").forEach((td) => td.classList.remove("flagged"));
  });
  (details || []).forEach((d) => {
    if (d.row === undefined || d.row === null) return;
    const tr = document.querySelector('#intake-rows tr[data-row="' + d.row + '"]');
    if (!tr) return;
    tr.classList.add("flagged");
    if (d.field) {
      const td = tr.querySelector('td[data-field="' + CSS.escape(d.field) + '"]');
      if (td) td.classList.add("flagged");
    }
  });
}

/* ---------------------------------------------------------------- json views */
function payloadFor(key) {
  if (key === "spec") return specPayload();
  if (key === "intake") return intakePayload();
  if (key === "format") return formatPayload();
  return null;
}
function syncJson(key) {
  if (!S.json[key]) return;
  const box = $(key + "-json");
  if (box) box.value = JSON.stringify(payloadFor(key), null, 2);
}
function hydrate(key, data) {
  if (key === "spec") {
    if (typeof data.name === "string") S.draft.name = data.name;
    if (Array.isArray(data.fields)) {
      S.draft.fields = data.fields.map((f) => ({
        name: String(f && f.name != null ? f.name : ""),
        type: TYPES.includes(f && f.type) ? f.type : "string",
        required: !!(f && f.required),
        aggregation: (f && typeof f.aggregation === "string") ? f.aggregation : "",
      }));
      if (!S.draft.fields.length) S.draft.fields = [{ name: "", type: "string", required: false, aggregation: "" }];
    }
    $("spec-name").value = S.draft.name;
    renderSpecRows();
  } else if (key === "intake") {
    if (typeof data.schema === "string" && S.specs.includes(data.schema)) S.intakeBind = data.schema;
    if (Array.isArray(data.rows)) {
      S.intakeRows = data.rows.map((r) => {
        const o = {};
        Object.keys(r || {}).forEach((k) => { o[k] = r[k] === null ? "" : String(r[k]); });
        return o;
      });
      if (!S.intakeRows.length) S.intakeRows = [{}];
    }
  } else if (key === "format") {
    if (typeof data.name === "string") S.formatName = data.name;
    S.formatBind = (typeof data.schema === "string" && S.specs.includes(data.schema)) ? data.schema : "";
    if (Array.isArray(data.views)) {
      S.views = data.views.map((v) => v && v.type === "table"
        ? { type: "table", columns: Array.isArray(v.columns) ? v.columns.map(String) : [] }
        : { type: "summary", field: String((v && v.field) || ""), aggregation: String((v && v.aggregation) || "") });
    }
  }
  renderAll();
}

function setJsonMode(key, on) {
  S.json[key] = on;
  const host = document.querySelector('[data-mode-host="' + key + '"]');
  if (!host) return;
  const form = host.querySelector(".form-view");
  const json = host.classList.contains("json-view") ? host : host.querySelector(".json-view");
  if (form) form.hidden = on;
  if (json) json.hidden = !on;
  const btn = document.querySelector('[data-toggle="' + key + '"]');
  if (btn) {
    btn.setAttribute("aria-pressed", String(on));
    btn.querySelector("span").textContent = on ? "Form" : "JSON";
  }
  if (on) syncJson(key);
}

/* ------------------------------------------------------------------ requests */
async function withBusy(btn, fn) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  btn.textContent = "Working";
  try { return await fn(); }
  finally {
    btn.removeAttribute("aria-busy");
    btn.textContent = label;
    btn.disabled = false;
  }
}

function readBody(key) {
  if (!S.json[key]) return { ok: true, value: payloadFor(key) };
  try { return { ok: true, value: JSON.parse($(key + "-json").value) }; }
  catch (e) { return { ok: false, error: e }; }
}

function badJson(host, err) {
  clear(host);
  paintProblem(host, {
    head: "That JSON could not be read, so nothing was sent.",
    lead: "The body in this panel has to parse before it can go anywhere. Fix the syntax " +
      "below, or switch back to the form view and let the panel write the body for you.",
    items: [{ where: "", say: String((err && err.message) || err) }],
    more: "",
    fix: null,
  }, null);
}

async function submit(key, method, path, host, onSuccess) {
  clear(host);
  clearMarks(document.getElementById(SECTION_OF[key]));
  const problems = precheck(key);
  if (problems.length) { renderPrecheck(host, problems); return { ok: false, skipped: true }; }
  const parsed = readBody(key);
  if (!parsed.ok) return badJson(host, parsed.error);
  const res = await api(method, path, parsed.value);
  clear(host);
  if (res.ok) onSuccess(res, parsed.value);
  else renderError(host, res.status, res.body, { key: key, sent: parsed.value });
  return res;
}

/* --------------------------------------------------------------- propagation */
function propagate() {
  renderIntake();
  renderFormat();
  syncJson("spec"); syncJson("intake"); syncJson("format");
  renderStamps();
}

function renderStamps() {
  const specCount = S.specs.length;
  setStamp("sec-spec", "stamp-spec",
    specCount ? specCount + (specCount === 1 ? " specification on file" : " specifications on file") : "No specification on file",
    specCount ? "done" : "open");

  const intakeSpec = resolvedSpec(S.intakeBind);
  const onFile = S.onFile[intakeSpec.name];
  const intakeSec = $("sec-intake");
  if (intakeSec.dataset.phase !== "fail") {
    if (intakeSpec.provisional) setStamp("sec-intake", "stamp-intake", "Provisional", "provisional");
    else if (onFile) setStamp("sec-intake", "stamp-intake", onFile + " specimens on file", "done");
    else setStamp("sec-intake", "stamp-intake", "Ready for intake", "ready");
  }
  $("intake-send").disabled = intakeSpec.provisional;

  const fmtSpec = resolvedSpec(S.formatBind || S.intakeBind);
  const fmtSec = $("sec-format");
  if (fmtSec.dataset.phase !== "fail" && fmtSec.dataset.phase !== "done") {
    setStamp("sec-format", "stamp-format",
      fmtSpec.provisional ? "Provisional" : "Ready", fmtSpec.provisional ? "provisional" : "ready");
  }
  $("format-send").disabled = fmtSpec.provisional;

  const certSec = $("sec-cert");
  if (certSec.dataset.phase !== "done") {
    setStamp("sec-cert", "stamp-cert",
      S.dashboards.length ? "Ready" : "No format registered",
      S.dashboards.length ? "ready" : "locked");
  }

  $("tally-schemas").textContent = String(S.specs.length);
  $("tally-dash").textContent = String(S.dashboards.length);
  const total = Object.values(S.onFile).reduce((a, b) => a + b, 0);
  $("tally-rows").textContent = total ? String(total) : "—";
}

function renderAll() {
  renderSpecRows();
  renderIntake();
  renderFormat();
  renderCertControls();
  renderStamps();
  ["spec", "intake", "format"].forEach(syncJson);
}

/* ------------------------------------------------------------------- wiring */
$("meta-origin").textContent = location.origin;
$("spec-name").value = S.draft.name;

$("spec-name").addEventListener("input", (e) => { S.draft.name = e.target.value; propagate(); });
$("spec-add").addEventListener("click", () => {
  S.draft.fields.push({ name: "", type: "string", required: false, aggregation: "" });
  renderSpecRows(); propagate();
});
$("spec-reset").addEventListener("click", () => {
  S.draft = { name: "", fields: [{ name: "", type: "string", required: false, aggregation: "" }] };
  $("spec-name").value = "";
  clear($("spec-result"));
  renderSpecRows(); propagate();
});
$("spec-send").addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
  const host = $("spec-result");
  const res = await submit("spec", "POST", "/schema", host, (r, sent) => {
    renderReceipt(host, r.status,
      "Specification “" + sent.name + "” registered with " + sent.fields.length +
      " parameter" + (sent.fields.length === 1 ? "" : "s") + ".", "POST /schema");
  });
  if (res.ok) { S.intakeBind = res.body && res.body.name ? res.body.name : S.draft.name.trim(); await refresh(); }
}));

$("intake-bind").addEventListener("change", (e) => { S.intakeBind = e.target.value; renderIntake(); renderFormat(); syncJson("intake"); renderStamps(); });
$("intake-add").addEventListener("click", () => { S.intakeRows.push({}); renderIntake(); syncJson("intake"); });
async function sendIntake() {
  const host = $("intake-result");
  const res = await submit("intake", "POST", "/ingest", host, (r, sent) => {
    const n = (sent.rows || []).length;
    S.onFile[sent.schema] = (S.onFile[sent.schema] || 0) + n;
    renderReceipt(host, r.status, n + " specimen" + (n === 1 ? "" : "s") +
      " conform to “" + sent.schema + "” and are on file.", "POST /ingest");
    flagIntake([]);
    setStamp("sec-intake", "stamp-intake", S.onFile[sent.schema] + " specimens on file", "done");
  });
  if (!res.ok && !res.skipped) {
    flagIntake(res.body && res.body.details);
    setStamp("sec-intake", "stamp-intake", "Batch rejected", "fail");
  }
  renderStamps();
}

$("intake-send").addEventListener("click", (e) => withBusy(e.currentTarget, sendIntake));

$("format-name").addEventListener("input", (e) => { S.formatName = e.target.value; syncJson("format"); });
$("format-bind").addEventListener("change", (e) => { S.formatBind = e.target.value; renderFormat(); syncJson("format"); });
document.querySelectorAll("[data-addview]").forEach((b) => b.addEventListener("click", () => {
  const spec = resolvedSpec(S.formatBind || S.intakeBind);
  if (b.dataset.addview === "summary") {
    const first = spec.fields[0];
    S.views.push({ type: "summary", field: first ? first.name : "", aggregation: "" });
  } else {
    S.views.push({ type: "table", columns: spec.fields.map((f) => f.name) });
  }
  renderFormat(); syncJson("format");
}));
$("format-send").addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
  const host = $("format-result");
  const res = await submit("format", "POST", "/dashboard", host, (r, sent) => {
    const bound = (r.body && r.body.schema) || sent.schema;
    renderReceipt(host, r.status,
      "Report “" + sent.name + "” validated against specification “" + bound +
      "” and registered.", "POST /dashboard");
    setStamp("sec-format", "stamp-format", "Registered", "done");
  });
  if (!res.ok && !res.skipped) setStamp("sec-format", "stamp-format", "Rejected", "fail");
  if (res.ok) { await refresh(); $("cert-pick").value = S.formatName.trim(); }
  renderStamps();
}));

$("cert-send").addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
  const host = $("cert-result");
  clear(host);
  clearMarks($("sec-cert"));
  const problems = precheck("cert");
  if (problems.length) { renderPrecheck(host, problems); return; }
  const name = $("cert-pick").value;
  const res = await api("GET", "/dashboard/" + encodeURIComponent(name));
  clear(host);
  if (res.ok) {
    renderCertificate(host, res.body);
    if (res.body && res.body.schema && typeof res.body.rowCount === "number") {
      S.onFile[res.body.schema] = res.body.rowCount;
    }
    setStamp("sec-cert", "stamp-cert", "Issued", "done");
    $("cert-json").value = JSON.stringify(res.body, null, 2);
  } else {
    renderError(host, res.status, res.body, { key: "cert", sent: { name: name } });
    setStamp("sec-cert", "stamp-cert", "Not issued", "fail");
    $("cert-json").value = JSON.stringify(res.body, null, 2);
  }
  renderStamps();
}));

document.addEventListener("input", (e) => {
  if (e.target && e.target.classList && e.target.classList.contains("bad")) {
    e.target.classList.remove("bad");
  }
}, true);

document.querySelectorAll("[data-toggle]").forEach((btn) => {
  btn.setAttribute("aria-pressed", "false");
  btn.addEventListener("click", () => {
    const key = btn.dataset.toggle;
    const turningOff = S.json[key];
    if (turningOff && key !== "cert") {
      let parsed;
      try { parsed = JSON.parse($(key + "-json").value); }
      catch (err) { badJson($(key + "-result"), err); return; }
      setJsonMode(key, false);
      hydrate(key, parsed || {});
      return;
    }
    setJsonMode(key, !S.json[key]);
  });
});

renderAll();
refresh();
