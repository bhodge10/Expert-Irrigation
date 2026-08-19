import { QUEUE_META } from "../format";

const QUEUE_ORDER = ["all", "service", "sales", "undetermined", "ignored"];
const SCOPES = [
  ["open", "Open"],
  ["mine", "Mine"],
  ["done", "Done"],
];

export default function QueueRail({ queue, scope, counts, onQueue, onScope, onPrivateSenders }) {
  return (
    <nav className="eq-rail">
      <p className="eq-eyebrow">Queues</p>

      {QUEUE_ORDER.map((key) => (
        <button
          key={key}
          className="eq-q"
          aria-pressed={queue === key}
          onClick={() => onQueue(key)}
        >
          <span
            className="eq-dot"
            style={{ background: key === "all" ? "var(--ink)" : QUEUE_META[key].dot }}
          />
          {key === "all" ? "All" : QUEUE_META[key].label}
          <span className="eq-count">{counts[key] ?? 0}</span>
        </button>
      ))}

      <div className="eq-rule" />
      <p className="eq-eyebrow">Show</p>
      <div className="eq-seg">
        {SCOPES.map(([key, label]) => (
          <button key={key} aria-pressed={scope === key} onClick={() => onScope(key)}>
            {label}
          </button>
        ))}
      </div>

      <div className="eq-legend">
        <b>Sorting</b>
        Mail is read as it arrives in Craig, Megan and Joyce's inboxes, then
        dropped into a queue. Undetermined waits for a human call; Ignored is
        mail nobody needs to answer. Wrong call? Move it — the correction is
        recorded and the sorting learns.
      </div>

      <button className="eq-rail-link" onClick={onPrivateSenders}>
        Private senders…
      </button>
    </nav>
  );
}
