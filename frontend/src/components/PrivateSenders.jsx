import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { formatWhen } from "../format";

/* The private-senders list. Mail from anyone on it never enters the portal,
   and adding an entry also removes whatever they already had here. Every
   signed-in user can edit it — the office polices itself. */
export default function PrivateSenders({ onClose, onChanged, say }) {
  const [entries, setEntries] = useState(null); // null = still loading
  const [pattern, setPattern] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  async function load() {
    try {
      setEntries(await api.privateSenders());
    } catch (err) {
      say(err.message, true);
      onClose();
    }
  }

  useEffect(() => {
    load();
    inputRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function onKey(event) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function add(event) {
    event.preventDefault();
    if (!pattern.trim() || busy) return;
    setBusy(true);
    try {
      const { entry, purged } = await api.addPrivateSender(pattern.trim());
      setPattern("");
      say(
        purged > 0
          ? `${entry.pattern} blocked — ${purged} existing message${purged === 1 ? "" : "s"} removed`
          : `${entry.pattern} blocked`,
      );
      await load();
      if (purged > 0) onChanged();
    } catch (err) {
      say(err.message, true);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  async function remove(entry) {
    try {
      await api.removePrivateSender(entry.id);
      say(`${entry.pattern} unblocked — new mail will appear again`);
      await load();
    } catch (err) {
      say(err.message, true);
    }
  }

  return (
    <div className="eq-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="eq-modal" role="dialog" aria-label="Private senders">
        <div className="eq-dtop">
          <h3>Private senders</h3>
          <button className="eq-x" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>

        <p className="eq-modal-note">
          Mail from these senders never enters the queue — nobody here sees it.
          Adding one also removes anything of theirs already in the portal, for
          good. The mail itself stays untouched in Outlook.
        </p>

        <form className="eq-padd" onSubmit={add}>
          <input
            ref={inputRef}
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="kturner@example.com — or a whole company: example.com"
            aria-label="Address or domain to block"
          />
          <button className="eq-btn pri" disabled={busy || !pattern.trim()}>
            {busy ? "Blocking…" : "Block"}
          </button>
        </form>

        {entries === null ? (
          <p className="eq-modal-note">Loading…</p>
        ) : entries.length === 0 ? (
          <p className="eq-modal-note">Nothing blocked yet.</p>
        ) : (
          <ul className="eq-plist">
            {entries.map((entry) => (
              <li key={entry.id}>
                <div>
                  <strong>{entry.pattern}</strong>
                  {entry.pattern.startsWith("@") && <span className="eq-pkind">whole domain</span>}
                  <div className="eq-pmeta">
                    {entry.added_by ? `${entry.added_by.display_name} · ` : ""}
                    {formatWhen(entry.created_at)}
                  </div>
                </div>
                <button className="eq-btn ghost" onClick={() => remove(entry)}>
                  Unblock
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
