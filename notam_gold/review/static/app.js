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

document.addEventListener("alpine:init", () => {
  Alpine.data("review", () => ({
    queue: [],
    index: 0,
    filters: { stratum: "", status: "all", disagreement: false },
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
      await this.refreshProgress();
      await this.reload();
    },

    async reload() {
      const params = new URLSearchParams({
        status: this.filters.status,
        disagreement: this.filters.disagreement,
        ...(this.filters.stratum && { stratum: this.filters.stratum }),
      });
      const { items } = await api(`/api/queue?${params}`);
      this.queue = items;
      this.index = 0;
      this.loaded = true;
      if (items.length) await this.show(0);
      else this.current = null;
    },

    async refreshProgress() {
      this.progress = await api("/api/progress");
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
      const key = this.queue[index].key;
      const notam = await this.fetchNotam(key);
      if (this.queue[this.index]?.key !== key) return;
      this.current = notam;
      const start = notam.review?.extraction ?? notam.silverA?.extraction ?? emptyExtraction();
      this.form = structuredClone(start);
      this.note = notam.review?.note ?? "";
      this.message = "";
      this.segments = evidenceSegments(notam.prompt, notam.silverA?.evidence ?? []);
      this.validate();
      for (const offset of [1, 2, -1]) {
        const neighbour = this.queue[index + offset];
        if (neighbour) this.fetchNotam(neighbour.key);
      }
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
        body: JSON.stringify({ extraction: this.form }),
      });
      this.problems = problems;
    },

    problemAt(path, includeChildren = false) {
      const found = this.problems.find(
        (p) => p.path === path || (includeChildren && (p.path.startsWith(path + ".") || p.path.startsWith(path + "["))),
      );
      return found?.message ?? "";
    },

    // Disagreement between run A and run B, indexed like run A's effects.
    flaggedExact(path) {
      return this.current?.disagreements.some((d) => d.path === path) ?? false;
    },
    flagged(path) {
      return (
        this.current?.disagreements.some(
          (d) => d.path === path || d.path.startsWith(path + ".") || d.path.startsWith(path + "["),
        ) ?? false
      );
    },
    bValue(path) {
      const exact = this.current?.disagreements.find((d) => d.path === path);
      if (exact) return exact.b;
      const b = this.current?.silverB?.extraction;
      if (!b) return undefined;
      return pathKeys(path).reduce((value, key) => (value == null ? value : value[key]), b);
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
      return paths.some((p) => p === hover || p.startsWith(hover + ".") || p.startsWith(hover + "[") || hover.startsWith(p + "."));
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
        const result = await api("/api/review", {
          method: "POST",
          body: JSON.stringify({ key: this.current.key, status, extraction, note: this.note }),
        });
        this.queue[this.index].status = result.status;
        this.cache.delete(this.current.key);
        this.refreshProgress();
        await this.go(1);
        this.message = `Saved the previous NOTAM as ${this.statusLabel(result.status).toLowerCase()}.`;
      } catch (error) {
        const problems = error.body?.detail?.problems;
        if (problems) this.problems = problems;
        this.message = problems ? "Fix the highlighted problems before saving." : "Couldn't save. Is the server running?";
      } finally {
        this.busy = false;
      }
    },
    accept() {
      return this.submit("accepted", this.form);
    },
    save() {
      return this.submit("edited", this.form);
    },
    mark(status) {
      return this.submit(status, this.form);
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
