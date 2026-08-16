import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Avatar from "./components/Avatar";
import DetailPane from "./components/DetailPane";
import Login from "./components/Login";
import MessageList from "./components/MessageList";
import QueueRail from "./components/QueueRail";
import { QUEUE_META } from "./format";

const EMPTY_COUNTS = { all: 0, service: 0, sales: 0, undetermined: 0, ignored: 0 };

export default function App() {
  const [me, setMe] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);

  const [users, setUsers] = useState([]);
  const [queue, setQueue] = useState("all");
  const [scope, setScope] = useState("open");
  const [messages, setMessages] = useState([]);
  const [counts, setCounts] = useState(EMPTY_COUNTS);

  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);

  const [toast, setToast] = useState(null); // { text, bad }

  const say = useCallback((text, bad = false) => {
    setToast({ text, bad });
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 2800);
    return () => clearTimeout(timer);
  }, [toast]);

  /* Do we already have a session? */
  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setCheckingSession(false));
  }, []);

  useEffect(() => {
    if (!me) return;
    api.users().then(setUsers).catch(() => setUsers([]));
  }, [me]);

  const refreshList = useCallback(
    async (silent = false) => {
      if (!me) return;
      try {
        const data = await api.messages(queue, scope);
        setMessages(data.messages);
        setCounts(data.counts);
      } catch (err) {
        if (err.status === 401) setMe(null);
        else if (!silent) say(err.message, true);
        // A failed background refresh stays quiet — the next one will catch up.
      }
    },
    [me, queue, scope, say],
  );

  useEffect(() => {
    refreshList();
  }, [refreshList]);

  /* The worker polls mail every 60s; keep the queue fresh without anyone
     touching anything. Skips while the tab is hidden, refreshes the moment
     it's visible again. */
  useEffect(() => {
    if (!me) return undefined;
    const tick = () => {
      if (!document.hidden) refreshList(true);
    };
    const timer = setInterval(tick, 30000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [me, refreshList]);

  /* Selecting a card loads the full message. */
  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      return;
    }
    api
      .message(selectedId)
      .then(setDetail)
      .catch((err) => {
        say(err.message, true);
        setSelectedId(null);
      });
  }, [selectedId, say]);

  /* Every mutation returns the updated message, so apply it and refresh the
     list for counts and ordering. */
  async function act(run, successText) {
    try {
      const updated = await run();
      setDetail(updated);
      await refreshList();
      if (successText) say(successText);
      return true;
    } catch (err) {
      if (err.status === 401) setMe(null);
      else say(err.message, true);
      return false;
    }
  }

  async function signOut() {
    try {
      await api.logout();
    } finally {
      setMe(null);
      setSelectedId(null);
      setDetail(null);
      setMessages([]);
      setCounts(EMPTY_COUNTS);
    }
  }

  if (checkingSession) {
    return <div className="eq-loading">Loading…</div>;
  }

  if (!me) {
    return <Login onSignedIn={setMe} />;
  }

  return (
    <div className="eq-page">
      <div className="eq-root">
        <div className="eq-top">
          <span className="eq-drop" />
          <span className="eq-mark">
            <b>Expert</b>
            <span>Inbox Queue</span>
          </span>
          <div className="eq-top-right">
            <span className="eq-sync">
              <span className="eq-pulse" />
              <span>Live · reading mail</span>
            </span>
            <span className="eq-me">
              <Avatar user={me} />
              {me.display_name.split(" ")[0]}
            </span>
            <button className="eq-signout" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>

        <div className="eq-shell">
          <QueueRail
            queue={queue}
            scope={scope}
            counts={counts}
            onQueue={(next) => {
              setQueue(next);
              setSelectedId(null);
            }}
            onScope={(next) => {
              setScope(next);
              setSelectedId(null);
            }}
          />

          <main className={detail ? "eq-main eq-split" : "eq-main"}>
            <MessageList
              messages={messages}
              queue={queue}
              scope={scope}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />

            {detail && (
              <DetailPane
                message={detail}
                users={users}
                me={me}
                onClose={() => setSelectedId(null)}
                onAssign={(assigneeId) =>
                  act(
                    () => api.assign(detail.id, assigneeId),
                    assigneeId === null
                      ? "Assignment cleared"
                      : assigneeId === me.id
                        ? "Assigned to you"
                        : `Assigned to ${
                            users.find((u) => u.id === assigneeId)?.display_name ??
                            "teammate"
                          }`,
                  )
                }
                onMove={(nextQueue) =>
                  act(
                    () => api.moveQueue(detail.id, nextQueue),
                    `Moved to ${QUEUE_META[nextQueue].label} — noted for next time`,
                  )
                }
                onToggleStatus={() => {
                  const next = detail.status === "handled" ? "open" : "handled";
                  return act(
                    () => api.setStatus(detail.id, next),
                    next === "handled" ? "Marked handled" : "Reopened",
                  );
                }}
                onReply={(text, markHandled) =>
                  act(
                    () => api.reply(detail.id, text, markHandled),
                    markHandled
                      ? `Reply saved for ${detail.from_name.split(" ")[0]} — marked handled`
                      : `Reply saved for ${detail.from_name.split(" ")[0]}`,
                  )
                }
                onReject={() =>
                  act(
                    () => api.reject(detail.id),
                    "Marked not valid — the sorting learns from this",
                  )
                }
                onDraft={() =>
                  act(
                    () => api.draftReply(detail.id),
                    "Draft ready — read it before sending",
                  )
                }
              />
            )}
          </main>
        </div>

        <div className="eq-foot">
          <span>Reading live mail — read-only, nothing sends yet.</span>
          <span>Assign, handle, move or reject: each one teaches the sorting.</span>
        </div>
      </div>

      <div
        className={toast ? `eq-toast on${toast.bad ? " bad" : ""}` : "eq-toast"}
        role="status"
        aria-live="polite"
      >
        {toast?.text}
      </div>
    </div>
  );
}
