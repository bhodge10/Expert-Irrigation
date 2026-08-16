import { useEffect, useRef, useState } from "react";
import Avatar from "./Avatar";
import ConfidenceBars from "./ConfidenceBars";
import { QUEUE_META, formatSentAt, formatWhen } from "../format";

function AssignMenu({ message, users, me, onAssign }) {
  const others = users.filter((u) => u.id !== me.id);
  return (
    <div className="eq-menu">
      <p>Assign to</p>
      <button onClick={() => onAssign(me.id)}>
        <Avatar user={me} small /> Me ({me.display_name.split(" ")[0]})
      </button>
      <hr />
      {others.map((u) => (
        <button key={u.id} onClick={() => onAssign(u.id)}>
          <Avatar user={u} small /> {u.display_name}
          <span className="eq-menu-role">{u.role}</span>
        </button>
      ))}
      {message.assignee && (
        <>
          <hr />
          <button style={{ color: "var(--muted)" }} onClick={() => onAssign(null)}>
            Clear assignment
          </button>
        </>
      )}
    </div>
  );
}

function MoveMenu({ message, onMove }) {
  return (
    <div className="eq-menu">
      <p>Move to queue</p>
      {Object.entries(QUEUE_META).map(([key, meta]) => {
        const current = key === message.queue;
        return (
          <button
            key={key}
            style={current ? { opacity: 0.5 } : undefined}
            onClick={() => onMove(key)}
          >
            <span className="eq-dot" style={{ background: meta.dot }} />
            {meta.label}
            {current ? " (current)" : ""}
          </button>
        );
      })}
      <hr />
      <p className="eq-menu-note">Moving it records what the sorting got wrong.</p>
    </div>
  );
}

function Composer({ message, onSend, onCancel, onDraft }) {
  const [text, setText] = useState(message.draft_reply || "");
  const [markHandled, setMarkHandled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const textareaRef = useRef(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  /* A draft generated while the composer is open lands in the (still empty)
     textarea. Never overwrites something the user typed. */
  useEffect(() => {
    if (message.draft_reply) {
      setText((current) => (current.trim() === "" ? message.draft_reply : current));
    }
  }, [message.draft_reply]);

  async function send() {
    if (!text.trim() || busy) return;
    setBusy(true);
    const ok = await onSend(text, markHandled);
    if (!ok) setBusy(false);
  }

  async function generate() {
    if (drafting) return;
    setDrafting(true);
    try {
      await onDraft();
    } finally {
      setDrafting(false);
    }
  }

  return (
    <div className="eq-comp">
      <label>Reply to sender</label>
      <div className="to">
        To: <strong>{message.from_name}</strong> &lt;{message.from_email}&gt; — sends
        from {message.mailbox}
      </div>
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Write the reply…"
      />
      <p className="eq-draftnote">
        {message.draft_reply && text === message.draft_reply
          ? "Drafted by AI in Craig's voice — read it and edit before sending. "
          : ""}
        The customer sees {message.mailbox}, not you. Who sent it is recorded on
        the message.
      </p>
      <div className="eq-arow">
        <button className="eq-btn pri" onClick={send} disabled={busy || !text.trim()}>
          {busy ? "Sending…" : "Send reply"}
        </button>
        <button className="eq-btn ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        {text.trim() === "" && (
          <button className="eq-btn ghost" onClick={generate} disabled={drafting}>
            {drafting ? "Drafting…" : "Draft with AI"}
          </button>
        )}
        <label className="eq-handled-toggle">
          <input
            type="checkbox"
            checked={markHandled}
            onChange={(e) => setMarkHandled(e.target.checked)}
          />
          Mark handled
        </label>
      </div>
    </div>
  );
}

export default function DetailPane({
  message,
  users,
  me,
  onClose,
  onAssign,
  onMove,
  onToggleStatus,
  onReply,
  onReject,
  onDraft,
}) {
  const [menu, setMenu] = useState(null); // "assign" | "move" | null
  const [composing, setComposing] = useState(false);

  // A different message means start clean.
  useEffect(() => {
    setMenu(null);
    setComposing(false);
  }, [message.id]);

  useEffect(() => {
    function onDocClick(event) {
      if (!event.target.closest(".eq-menu") && !event.target.closest(".eq-menu-wrap")) {
        setMenu(null);
      }
    }
    function onKey(event) {
      if (event.key !== "Escape") return;
      if (menu) setMenu(null);
      else if (composing) setComposing(false);
      else onClose();
    }
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menu, composing, onClose]);

  const meta = QUEUE_META[message.queue];
  const handled = message.status === "handled";
  const corrected = Boolean(message.corrected_by && message.original_queue);

  return (
    <aside className="eq-detail">
      <div className="eq-dhead">
        <div className="eq-dtop">
          <h3>{message.subject}</h3>
          <button className="eq-x" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="eq-dmeta">
          <span className={`eq-tag ${meta.tag}`}>{meta.label}</span>
          {message.is_urgent && <span className="eq-tag t-urgent">Emergency</span>}
          {handled && <span className="eq-tag t-plain">Handled</span>}
          <strong>{message.from_name}</strong>
          <a href={`mailto:${message.from_email}`}>{message.from_email}</a>
          <span style={{ color: "var(--muted)" }}>
            · to {message.mailbox} · {formatWhen(message.received_at)}
          </span>
          {message.attachment_count > 0 && (
            <span
              className="eq-tag t-plain"
              title={message.attachment_names.join(", ")}
            >
              📎 {message.attachment_count}
            </span>
          )}
          {message.source === "forwarded" && (
            <span className="eq-tag t-plain">Forwarded in</span>
          )}
          {message.rejected_by && (
            <span
              className="eq-tag t-plain"
              title={`${message.rejected_by.display_name} marked this as not a real request. The sorting learns from it. Reopen if it was a mistake.`}
            >
              Marked not valid
            </span>
          )}
        </div>
      </div>

      {composing ? (
        <Composer
          message={message}
          onSend={async (text, markHandled) => {
            const ok = await onReply(text, markHandled);
            if (ok) setComposing(false);
            return ok;
          }}
          onCancel={() => setComposing(false)}
          onDraft={onDraft}
        />
      ) : (
        <div className="eq-actions">
          <div className="eq-arow">
            <button className="eq-btn pri" onClick={() => setComposing(true)}>
              Reply
            </button>

            <span className="eq-menu-wrap">
              <button
                className="eq-btn"
                onClick={() => setMenu(menu === "assign" ? null : "assign")}
              >
                {message.assignee
                  ? `Reassign — ${message.assignee.display_name.split(" ")[0]}`
                  : "Assign"}
              </button>
              {menu === "assign" && (
                <AssignMenu
                  message={message}
                  users={users}
                  me={me}
                  onAssign={(id) => {
                    setMenu(null);
                    onAssign(id);
                  }}
                />
              )}
            </span>

            <span className="eq-menu-wrap">
              <button
                className="eq-btn"
                onClick={() => setMenu(menu === "move" ? null : "move")}
              >
                Move queue
              </button>
              {menu === "move" && (
                <MoveMenu
                  message={message}
                  onMove={(queue) => {
                    setMenu(null);
                    onMove(queue);
                  }}
                />
              )}
            </span>

            <button className="eq-btn ghost" onClick={onToggleStatus}>
              {handled ? "Reopen" : "Mark handled"}
            </button>

            {!message.rejected_by && (
              <button
                className="eq-btn ghost"
                title="Spam, vendor noise, or a misfire — records that the sorting was wrong and clears it from the queue. Nothing is deleted."
                onClick={onReject}
              >
                Not valid
              </button>
            )}
          </div>
        </div>
      )}

      <div className="eq-dscroll">
      <div className="eq-body">{message.body_text}</div>

      {message.classification_reasons.length > 0 && (
        <div className="eq-ai">
          {/* Once someone has moved a message, these reasons explain a queue
              it's no longer in. Say that instead of dressing them up as the
              current call. */}
          {corrected ? (
            <h4>
              Why the sorting first said{" "}
              {QUEUE_META[message.original_queue]?.label ?? message.original_queue}
            </h4>
          ) : (
            <h4>
              Why it landed here <ConfidenceBars confidence={message.confidence} />
              <span className="eq-conf-note">{message.confidence}% confident</span>
            </h4>
          )}
          <ul>
            {message.classification_reasons.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
          {corrected && (
            <p className="eq-correction">
              {message.corrected_by.display_name} moved it to {meta.label}. The
              correction is recorded.
            </p>
          )}
        </div>
      )}

      {message.notes.length > 0 && (
        <div className="eq-thread eq-notes">
          <h4>Internal notes — the customer never sees these</h4>
          {message.notes.map((note) => (
            <div className="eq-sent eq-note" key={note.id}>
              <div className="eq-sent-meta">
                {formatSentAt(note.created_at)} · {note.author_name}
                {note.from_email ? " · from the email thread" : ""}
              </div>
              <pre>{note.body_text}</pre>
            </div>
          ))}
        </div>
      )}

      {message.replies.length > 0 && (
        <div className="eq-thread">
          <h4>Replies sent</h4>
          {message.replies.map((reply) => (
            <div className="eq-sent" key={reply.id}>
              <div className="eq-sent-meta">
                {formatSentAt(reply.sent_at)} · from {message.mailbox}
                {reply.sent_by ? ` · sent by ${reply.sent_by.display_name}` : ""}
                {!reply.delivered && (
                  <strong className="eq-undelivered">
                    {" "}
                    · saved here only, not emailed
                  </strong>
                )}
              </div>
              <pre>{reply.body_text}</pre>
            </div>
          ))}
        </div>
      )}

      </div>
    </aside>
  );
}
