/* Small display helpers shared by the card and the detail pane. */

export const QUEUE_META = {
  service: { label: "Service", cls: "svc", tag: "t-svc", dot: "var(--green)" },
  sales: { label: "Sales", cls: "sal", tag: "t-sal", dot: "var(--blue)" },
  undetermined: { label: "Undetermined", cls: "oth", tag: "t-oth", dot: "var(--slate)" },
  ignored: { label: "Ignored", cls: "oth", tag: "t-oth", dot: "var(--muted)" },
};

/* Today shows a clock time, yesterday says so, anything older shows a date.
   Office staff scanning the list care about "how stale", not the exact stamp. */
export function formatWhen(iso) {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";

  const now = new Date();
  const isSameDay = (a, b) => a.toDateString() === b.toDateString();

  if (isSameDay(at, now)) {
    return at
      .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      .toLowerCase();
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameDay(at, yesterday)) return "Yesterday";

  return at.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function formatSentAt(iso) {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return at.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function snippet(text, max = 150) {
  const flat = (text || "").replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}
