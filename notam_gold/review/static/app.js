const STRATA_NAMES = {
  declared_distances: "Declared distances",
  displaced_threshold: "Displaced threshold",
  partial_closure: "Partial closure",
  full_closure: "Full closure",
  ficon_rwycc: "Condition report with RwyCC",
  ficon_no_rwycc: "Condition report, no RwyCC",
  obstacle: "Obstacle",
  cancelled: "Cancelled",
  plausible_negative: "Plausible negative",
  other_negative: "Other negative",
};

const STATUS_LABELS = {
  unreviewed: "Unreviewed",
  accepted: "Accepted",
  edited: "Edited",
  ambiguous: "Ambiguous",
  skipped: "Skipped",
  stale: "Needs re-review",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) throw Object.assign(new Error("Request failed"), { body });
  return body;
}

const FILTERS_KEY = "notam-review-filters";

const COMPASS_POINTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const RELATIVE_ENDS = ["thresholdEnd", "departureEnd"];

/** Blank runway-end entries become null, so an unfinished "Runway end…" never saves as "". */
function cleaned(form) {
  const copied = copy(form);
  for (const effect of copied.effects) if (effect.closedEnd === "") effect.closedEnd = null;
  return copied;
}

/** The reviewer's last filters, surviving reloads; empty when storage is unavailable. */
function savedFilters() {
  try {
    return JSON.parse(localStorage.getItem(FILTERS_KEY)) ?? {};
  } catch {
    return {};
  }
}

function saveFilters(filters) {
  try {
    localStorage.setItem(FILTERS_KEY, JSON.stringify(filters));
  } catch {
    // Private browsing or blocked storage: filters simply reset on reload.
  }
}

function emptyExtraction() {
  return { isCanceled: false, effects: [] };
}

/** Split `text` into runs, each tagged with the evidence paths whose quotes cover it. */
function evidenceSegments(text, evidence) {
  const spans = [];
  for (const { path, quote } of evidence) {
    const words = quote.trim().split(/\s+/).filter(Boolean);
    if (!words.length) continue;
    const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    for (const match of text.matchAll(new RegExp(escaped.join("\\s+"), "g"))) {
      spans.push({ start: match.index, end: match.index + match[0].length, path });
    }
  }
  const cuts = [...new Set([0, text.length, ...spans.flatMap((s) => [s.start, s.end])])].sort((a, b) => a - b);
  const segments = [];
  for (let i = 0; i < cuts.length - 1; i++) {
    const [start, end] = [cuts[i], cuts[i + 1]];
    const paths = spans.filter((s) => s.start <= start && s.end >= end).map((s) => s.path);
    segments.push({ text: text.slice(start, end), paths });
  }
  return segments;
}

/** Parse a path like `effects[0].declaredDistances.TORA` into keys. */
function pathKeys(path) {
  return [...path.matchAll(/([^.[\]]+)|\[(\d+)\]/g)].map((m) => (m[2] !== undefined ? Number(m[2]) : m[1]));
}

/** A plain deep copy; `structuredClone` rejects Alpine's reactive proxies. */
function copy(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

function getAt(root, path) {
  return pathKeys(path).reduce((value, key) => (value == null ? undefined : value[key]), root);
}

function setAt(root, path, value) {
  const keys = pathKeys(path);
  const parent = keys.slice(0, -1).reduce((node, key) => node[key], root);
  parent[keys.at(-1)] = value;
}

/** Whether `path` is `prefix` itself or a field or item inside it. */
function isWithin(path, prefix) {
  return path === prefix || path.startsWith(prefix + ".") || path.startsWith(prefix + "[");
}

document.addEventListener("alpine:init", () => {
  Alpine.data("review", () => ({
    queue: [],
    index: 0,
    filters: { stratum: "", half: "", status: "all", disagreement: false },
    closedEndChoices: [
      { value: "", label: "Not stated" },
      { value: "thresholdEnd", label: "Threshold end (FIRST)" },
      { value: "departureEnd", label: "Departure end (LAST)" },
      ...COMPASS_POINTS.map((point) => ({ value: point, label: point })),
      { value: "runway", label: "Runway end…" },
    ],
    progress: [],
    enums: { closure: [], contaminant: [] },
    current: null,
    form: emptyExtraction(),
    note: "",
    problems: [],
    segments: [],
    hoverPath: null,
    message: "",
    busy: false,
    loaded: false,
    showHelp: false,
    cache: new Map(),
    validateTimer: null,

    async init() {
      this.enums = await api("/api/enums");
      const linked = new URLSearchParams(location.search).get("key");
      if (!linked) this.filters = { ...this.filters, ...savedFilters() };
      await this.reload(linked);
    },

    /** Reload the queue for the current filters, opening `key` if given, else the first NOTAM. */
    async reload(key = null) {
      saveFilters(this.filters);
      const params = new URLSearchParams({
        status: this.filters.status,
        disagreement: this.filters.disagreement,
        ...(this.filters.stratum && { stratum: this.filters.stratum }),
        ...(this.filters.half && { half: this.filters.half }),
      });
      const [{ items }] = await Promise.all([api(`/api/queue?${params}`), this.refreshProgress()]);
      this.queue = items;
      this.loaded = true;
      const index = Math.max(0, items.findIndex((item) => item.key === key));
      if (items.length) await this.show(index);
      else this.current = null;
    },

    async refreshProgress() {
      const half = this.filters.half ? `?half=${this.filters.half}` : "";
      this.progress = await api(`/api/progress${half}`);
    },

    fetchNotam(key) {
      if (!this.cache.has(key)) {
        const request = api(`/api/notam?key=${encodeURIComponent(key)}`);
        request.catch(() => this.cache.delete(key));
        this.cache.set(key, request);
      }
      return this.cache.get(key);
    },

    async show(index) {
      this.index = index;
      const { key, status } = this.queue[index];
      let notam = await this.fetchNotam(key);
      if (!notam.review && !["unreviewed", "stale"].includes(status)) {
        // A copy fetched before this NOTAM was saved; never show it in place of the saved review.
        this.cache.clear();
        notam = await this.fetchNotam(key);
      }
      if (this.queue[this.index]?.key !== key) return;
      this.current = notam;
      const silver = notam.silverA?.extraction ?? emptyExtraction();
      const start = this.isStale(notam) ? silver : (notam.review?.extraction ?? silver);
      this.form = copy(start);
      this.note = notam.review?.note ?? "";
      this.message = "";
      this.segments = evidenceSegments(notam.prompt, notam.silverA?.evidence ?? []);
      this.validate();
      for (const offset of [1, 2, -1]) {
        const neighbour = this.queue[index + offset];
        if (neighbour) this.fetchNotam(neighbour.key);
      }
    },

    /** The dropdown choice for a stored closedEnd: its own value, or "runway" for a runway designator. */
    closedEndChoice(value) {
      if (value === null) return "";
      return [...RELATIVE_ENDS, ...COMPASS_POINTS].includes(value) ? value : "runway";
    },
    chooseClosedEnd(effect, choice) {
      effect.closedEnd = { "": null, runway: "" }[choice] ?? choice;
      this.changed();
    },

    isStale(notam = this.current) {
      return (notam?.staleDifferences.length ?? 0) > 0;
    },
    restoreSavedLabel() {
      this.form = copy(this.current.review.extraction);
      this.changed();
    },

    async go(step) {
      const next = this.index + step;
      if (next >= 0 && next < this.queue.length) await this.show(next);
    },

    changed() {
      clearTimeout(this.validateTimer);
      this.validateTimer = setTimeout(() => this.validate(), 150);
    },

    async validate() {
      const { problems } = await api("/api/validate", {
        method: "POST",
        body: JSON.stringify({ extraction: cleaned(this.form) }),
      });
      this.problems = problems;
    },

    problemAt(path, includeChildren = false) {
      const found = this.problems.find((p) => (includeChildren ? isWithin(p.path, path) : p.path === path));
      return found?.message ?? "";
    },

    // Disagreement between run A and run B, indexed like run A's effects.
    flaggedExact(path) {
      return this.current?.disagreements.some((d) => d.path === path) ?? false;
    },
    flagged(path) {
      return this.differencesWithin(path).length > 0;
    },
    /** Run B's value at `path` (indexed like run A): run A's value with run B's differences applied. */
    bValue(path) {
      const differences = this.differencesWithin(path);
      const exact = differences.find((d) => d.path === path);
      if (exact) return exact.b;
      const value = copy(getAt(this.current?.silverA?.extraction, path));
      for (const d of differences) setAt({ root: value }, "root" + d.path.slice(path.length), copy(d.b));
      return value;
    },
    differencesWithin(path) {
      return this.current?.disagreements.filter((d) => isWithin(d.path, path)) ?? [];
    },
    /** Replace the form's value at `path` with run B's. */
    useB(path) {
      for (const d of this.differencesWithin(path)) setAt(this.form, d.path, copy(d.b));
      this.changed();
    },
    addRunBEffects(differences) {
      for (const d of differences) this.form.effects.push(copy(d.b));
      this.changed();
    },
    extraEffects() {
      return this.current?.disagreements.filter((d) => d.path.startsWith("effects[B:")) ?? [];
    },
    short(value) {
      if (value === undefined) return "(not compared)";
      if (value === null) return "null";
      if (typeof value === "object" && "value" in value && "unit" in value) return `${value.value} ${value.unit}`;
      return JSON.stringify(value);
    },

    isLit(paths) {
      const hover = this.hoverPath;
      if (!hover || !paths.length) return false;
      return paths.some((p) => isWithin(p, hover) || hover.startsWith(p + "."));
    },

    textShowsCancel() {
      return /\bNOTAMC\b|\bCANCEL+ED\b|\bCNL\b/.test(this.current?.prompt ?? "");
    },

    strataName(stratum) {
      return STRATA_NAMES[stratum] ?? stratum;
    },
    statusLabel(status) {
      return STATUS_LABELS[status] ?? status;
    },
    currentStatus() {
      return this.queue[this.index]?.status ?? "unreviewed";
    },

    addEffect() {
      this.form.effects.push({
        runway: null,
        closure: "none",
        closedLength: null,
        closedEnd: null,
        thresholdDisplacement: null,
        declaredDistances: null,
        surfaceCondition: null,
        obstacle: null,
      });
      this.changed();
    },
    emptyObstacle() {
      return {
        heightAGL: null,
        heightMSL: null,
        distance: null,
        distanceReference: null,
        bearingDegrees: null,
        latitude: null,
        longitude: null,
      };
    },
    toggle(object, key, stated, units) {
      object[key] = stated ? { value: null, unit: units[0] } : null;
      this.changed();
    },
    formatCodes(codes) {
      return codes ? codes.join("/") : "";
    },
    parseCodes(text) {
      const trimmed = text.trim();
      return trimmed ? trimmed.split(/[/\s,]+/).filter(Boolean).map(Number) : null;
    },
    intOrNull(text) {
      return text.trim() === "" ? null : parseInt(text, 10);
    },
    numberOrNull(text) {
      return text.trim() === "" ? null : Number(text);
    },
    async fillPosition(obstacle, input) {
      try {
        const { latitude, longitude } = await api(`/api/dms?text=${encodeURIComponent(input.value)}`);
        Object.assign(obstacle, { latitude, longitude });
        input.value = "";
        this.changed();
      } catch {
        this.message = "That isn't a DMS position like 403906N0734931W.";
      }
    },

    async submit(status, extraction) {
      if (this.busy || !this.current) return;
      this.busy = true;
      try {
        const key = this.current.key;
        const result = await api("/api/review", {
          method: "POST",
          body: JSON.stringify({ key, status, extraction, note: this.note }),
        });
        this.queue[this.index].status = result.status;
        this.cache.delete(key);
        this.refreshProgress();
        await this.go(1);
        this.message = `Saved ${key} as ${this.statusLabel(result.status).toLowerCase()}.`;
      } catch (error) {
        const problems = error.body?.detail?.problems;
        if (problems) this.problems = problems;
        this.message = problems ? "Fix the highlighted problems before saving." : "Couldn't save. Is the server running?";
      } finally {
        this.busy = false;
      }
    },
    accept() {
      return this.submit("accepted", cleaned(this.form));
    },
    save() {
      return this.submit("edited", cleaned(this.form));
    },
    mark(status) {
      return this.submit(status, cleaned(this.form));
    },

    onKey(event) {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName);
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        this.save();
        return;
      }
      if (event.key === "Escape") {
        document.activeElement?.blur();
        this.showHelp = false;
        return;
      }
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
      const actions = {
        a: () => this.accept(),
        s: () => this.save(),
        m: () => this.mark("ambiguous"),
        k: () => this.mark("skipped"),
        n: () => this.$refs.note.focus(),
        j: () => this.go(1),
        ArrowRight: () => this.go(1),
        p: () => this.go(-1),
        ArrowLeft: () => this.go(-1),
        "?": () => (this.showHelp = !this.showHelp),
      };
      const action = actions[event.key];
      if (action) {
        event.preventDefault();
        action();
      }
    },
  }));
});
