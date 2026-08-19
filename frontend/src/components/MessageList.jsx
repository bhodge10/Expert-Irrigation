import { useEffect, useState } from "react";
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

/* One-click triage without opening the message. Every one of these is a
   training signal: a move teaches the sender's queue, an assign confirms
   the sort, Ignore files it as noise. */
function QuickActions({
  message,
  users,
  me,
  assignOpen,
  onToggleAssign,
  onMove,
  onAssign,
  onIgnore,
}) {
  const others = users.filter((u) => u.id !== me.id);
  return (
    <div
      className="eq-quick"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {message.queue !== "service" && (
        <button className="eq-mini" onClick={() => onMove(message.id, "service")}>
          → Service
        </button>
      )}
      {message.queue !== "sales" && (
        <button className="eq-mini" onClick={() => onMove(message.id, "sales")}>
          → Sales
        </button>
      )}

      <span className="eq-menu-wrap">
        <button className="eq-mini" onClick={() => onToggleAssign(message.id)}>
          {message.assignee
            ? `@ ${message.assignee.display_name.split(" ")[0]}`
            : "Assign"}
        </button>
        {assignOpen && (
          <div className="eq-menu eq-menu-mini">
            <p>Assign to</p>
            <button onClick={() => onAssign(message.id, me.id)}>
              <Avatar user={me} small /> Me ({me.display_name.split(" ")[0]})
            </button>
            {others.length > 0 && <hr />}
            {others.map((u) => (
              <button key={u.id} onClick={() => onAssign(message.id, u.id)}>
                <Avatar user={u} small /> {u.display_name}
              </button>
            ))}
          </div>
        )}
      </span>

      {message.queue !== "ignored" && (
        <button
          className="eq-mini quiet"
          title="Nobody needs to answer this — files it to Ignored and the sorting learns"
          onClick={() => onIgnore(message.id)}
        >
          Ignore
        </button>
      )}
    </div>
  );
}

function MessageCard({ message, selected, onSelect, quick }) {
  const meta = QUEUE_META[message.queue];
  const classes = ["eq-card", meta.cls];
  if (message.status === "handled") classes.push("done");
  if (quick.assignOpen) classes.push("menu-open");

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
        {message.is_private && (
          <span
            className="eq-tag t-private"
            title="Only the people this email was addressed to can see it"
          >
            Private
          </span>
        )}
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

      <QuickActions message={message} {...quick} />
    </div>
  );
}

export default function MessageList({
  messages,
  queue,
  scope,
  selectedId,
  onSelect,
  users,
  me,
  onQuickMove,
  onQuickAssign,
  onQuickIgnore,
}) {
  const heading = queue === "all" ? "All requests" : `${QUEUE_META[queue].label} queue`;
  const sub = HEADINGS[scope];

  const [assignFor, setAssignFor] = useState(null);

  useEffect(() => {
    if (assignFor === null) return undefined;
    function close(event) {
      if (!event.target.closest(".eq-menu-wrap")) setAssignFor(null);
    }
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [assignFor]);

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
          quick={{
            users,
            me,
            assignOpen: assignFor === message.id,
            onToggleAssign: (id) => setAssignFor(assignFor === id ? null : id),
            onMove: (id, q) => {
              setAssignFor(null);
              onQuickMove(id, q);
            },
            onAssign: (id, userId) => {
              setAssignFor(null);
              onQuickAssign(id, userId);
            },
            onIgnore: (id) => {
              setAssignFor(null);
              onQuickIgnore(id);
            },
          }}
        />
      ))}
    </section>
  );
}
