// Shared UTC -> viewer-local timestamp rendering.
//
// Every timestamp reaching the browser is UTC: a timezone-aware ISO-8601
// string (offset or "Z" suffix) or a Django `|date:'c'` rendering of an aware
// datetime, which produces the same form. This is the one place that turns
// those into viewer-local text, using `Intl.DateTimeFormat` with explicit
// options rather than an unconfigured `toLocaleString()`.
//
// Usage:
//   - From JS: `parseusDatetime.formatTimestamp(value, "full"|"compact")`.
//   - From templates: put the raw timestamp in a `data-timestamp` attribute
//     (optionally `data-timestamp-style="compact"`) on a `<time>` element;
//     `hydrateTimestamps()` fills in the localized text on DOM ready. Wired
//     up globally in base.html, so any template following this pattern
//     "just works."

(function (global) {
  "use strict";

  const STYLES = {
    // Table/metadata rows: unambiguous full date + time + timezone label.
    full: {
      dateStyle: "medium",
      timeStyle: "medium",
    },
    // Dense alert cards: compact but still unambiguous.
    compact: {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    },
  };

  function getFormatter(style) {
    const options = STYLES[style] || STYLES.full;
    return new Intl.DateTimeFormat(undefined, options);
  }

  /**
   * Parse a UTC ISO-8601 string/Date and render it in the viewer's local
   * time zone and locale.
   *
   * @param {string|Date|null|undefined} value - A timezone-aware ISO-8601
   *   string (with offset or "Z"), or a Date object.
   * @param {"full"|"compact"} [style] - Which named format to use.
   * @param {string} [fallback] - Returned when `value` is missing/unparseable.
   * @returns {string}
   */
  function formatTimestamp(value, style, fallback) {
    const emptyFallback = fallback === undefined ? "N/A" : fallback;
    if (!value) return emptyFallback;

    const parsed = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      // Not parseable as a date; surface the original value rather than
      // silently hiding bad data.
      return String(value);
    }

    return getFormatter(style).format(parsed);
  }

  /**
   * Fill in every `[data-timestamp]` element under `root` with its
   * viewer-local rendering. Safe to call repeatedly (e.g. after injecting
   * new DOM content); already-hydrated elements are simply re-rendered.
   *
   * Expected markup:
   *   <time data-timestamp="2024-01-01T00:00:00+00:00"></time>
   *   <time data-timestamp="..." data-timestamp-style="compact"></time>
   *
   * @param {ParentNode} [root] - Defaults to the whole document.
   */
  function hydrateTimestamps(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-timestamp]").forEach((element) => {
      const rawValue = element.getAttribute("data-timestamp");
      const style = element.getAttribute("data-timestamp-style") || "full";
      const text = formatTimestamp(rawValue, style, element.getAttribute("data-timestamp-fallback"));
      element.textContent = text;
      if (rawValue && !Number.isNaN(new Date(rawValue).getTime())) {
        element.setAttribute("datetime", rawValue);
      }
    });
  }

  global.parseusDatetime = {
    formatTimestamp,
    hydrateTimestamps,
  };
})(window);
