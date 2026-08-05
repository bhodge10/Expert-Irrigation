import Avatar from "./Avatar";
import ConfidenceBars from "./ConfidenceBars";
import { QUEUE_META, formatWhen, snippet } from "../format";

const HEADINGS = {
  open: "Waiting on someone",
  mine: "Assigned to you",
  done: "Handled",
};

/* Empty states are invitations, not apologies. */
const EMPTY = {
  open: {
    title: "Nothing waiting here",
    body: "New mail lands in this queue automatically as it arrives.",
  },
  mine: {
    title: "Nothing assigned to you",
    body: "Open any message and assign it to yourself to claim it.",
  },
  done: {
    title: "Nothing handled yet today",
    body: "Messages show up here once someone replies or marks them handled.",
  },
};

function MessageCard({ message, selected, onSelect }) {
  const meta = QUEUE_META[message.queue];
  const classes = ["eq-card", meta.cls];
  if (message.status === "handled") classes.push("done");

  return (
    <div
      className={classes.join(" ")}
      role="button"
      tabIndex={0}
      aria-current={selected}
      onClick={() => onSelect(message.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(message.id);
        }
      }}
    >
      <div className="eq-row1">
        <span className="eq-from">{message.from_name}</span>
        <span className="eq-time">{formatWhen(message.received_at)}</span>
      </div>

      <div className="eq-subj">{message.subject}</div>
      <p className="eq-snip">{snippet(message.body_text)}</p>

      <div className="eq-row2">
        <span className={`eq-tag ${meta.tag}`}>{meta.label}</span>
        {message.is_urgent && <span className="eq-tag t-urgent">Emergency</span>}
        {message.status === "handled" && <span className="eq-tag t-plain">Handled</span>}

        <span className="eq-assign">
          {message.assignee ? (
            <>
              <Avatar user={message.assignee} small />
              {message.assignee.display_name.split(" ")[0]}
            </>
          ) : (
            <>
              <span className="eq-unassigned">+</span>
              Unassigned
            </>
          )}
        </span>

        <span className="eq-conf">
          <ConfidenceBars confidence={message.confidence} />
          <small>{message.confidence}%</small>
        </span>
      </div>
    </div>
  );
}

export default function MessageList({ messages, queue, scope, selectedId, onSelect }) {
  const heading = queue === "all" ? "All requests" : `${QUEUE_META[queue].label} queue`;
  const sub = HEADINGS[scope];

  if (messages.length === 0) {
    const empty = EMPTY[scope];
    return (
      <section className="eq-list">
        <div className="eq-listhead">
          <h2>{heading}</h2>
          <p>{sub}</p>
        </div>
        <div className="eq-empty">
          <b>{empty.title}</b>
          {empty.body}
        </div>
      </section>
    );
  }

  return (
    <section className="eq-list">
      <div className="eq-listhead">
        <h2>{heading}</h2>
        <p>
          {messages.length} {messages.length === 1 ? "request" : "requests"} · {sub}
        </p>
      </div>
      {messages.map((message) => (
        <MessageCard
          key={message.id}
          message={message}
          selected={selectedId === message.id}
          onSelect={onSelect}
        />
      ))}
    </section>
  );
}
