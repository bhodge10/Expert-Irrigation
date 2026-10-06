import { useEffect, useState } from "react";
import { api } from "../api";
import { formatDate, formatSentAt } from "../format";

/* Who the sender is in ServiceTitan — account, membership, open jobs.

   Display-only, by the API terms and by decision: what shows here never goes
   anywhere else. The server builds it when a message is opened and keeps it
   on the row for a day at most, so a second open is instant. */

function prettyPhone(digits) {
  if (!digits || digits.length !== 10) return digits || "";
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

function contactLine(contact) {
  const value =
    contact.type === "Email" || contact.type === "Fax"
      ? contact.value
      : prettyPhone(contact.value.replace(/\D/g, "").replace(/^1(\d{10})$/, "$1"));
  return `${contact.type === "MobilePhone" ? "Mobile" : contact.type} ${value}`;
}

export default function ServiceTitanCard({ messageId }) {
  const [card, setCard] = useState(null);
  const [state, setState] = useState("loading"); // loading | ready | failed

  async function load(refresh = false) {
    setState("loading");
    try {
      const next = await api.serviceTitan(messageId, refresh);
      setCard(next);
      setState("ready");
    } catch {
      setState("failed");
    }
  }

  useEffect(() => {
    let cancelled = false;
    setCard(null);
    setState("loading");
    api
      .serviceTitan(messageId)
      .then((next) => {
        if (cancelled) return;
        setCard(next);
        setState("ready");
      })
      .catch(() => {
        if (!cancelled) setState("failed");
      });
    return () => {
      cancelled = true;
    };
  }, [messageId]);

  if (state === "ready" && card?.status === "off") return null;

  if (state === "loading") {
    return <div className="eq-st eq-st-quiet">Checking ServiceTitan…</div>;
  }

  if (state === "failed" || card?.status === "error") {
    return (
      <div className="eq-st eq-st-quiet">
        ServiceTitan lookup didn't work just now.{" "}
        <button className="eq-st-link" onClick={() => load(true)}>
          Try again
        </button>
      </div>
    );
  }

  const footer = (
    <span className="eq-st-foot">
      {card.checked_at ? `Checked ${formatSentAt(card.checked_at)}` : ""}
      {" · "}
      <button className="eq-st-link" onClick={() => load(true)}>
        Refresh
      </button>
    </span>
  );

  if (card.status === "unmatched") {
    return (
      <div className="eq-st eq-st-quiet">
        Not in ServiceTitan — no customer matches{" "}
        {card.phones_tried > 0
          ? `the ${card.phones_tried === 1 ? "phone number" : "phone numbers"} in this email, or `
          : ""}
        the sender's name with this email address. {footer}
      </div>
    );
  }

  const { customer } = card;
  const matchedOn =
    card.matched_by === "phone"
      ? `matched on ${prettyPhone(card.matched_phone)} in the email`
      : "matched on name, email verified";

  return (
    <div className="eq-st">
      <h4>
        In ServiceTitan
        <span className="eq-st-how">{matchedOn}</span>
      </h4>

      <div className="eq-st-row">
        <strong>{customer.name}</strong>
        {customer.type && <span className="eq-tag t-plain">{customer.type}</span>}
        {!customer.active && <span className="eq-tag t-plain">Inactive</span>}
        {customer.do_not_service && (
          <span className="eq-tag t-urgent" title="ServiceTitan has this account flagged Do Not Service">
            Do not service
          </span>
        )}
      </div>
      {customer.address && <div className="eq-st-sub">{customer.address}</div>}
      {customer.contacts.length > 0 && (
        <div className="eq-st-sub">{customer.contacts.map(contactLine).join(" · ")}</div>
      )}

      {card.memberships.length > 0 && (
        <div className="eq-st-row">
          {card.memberships.map((m) => (
            <span key={m.id} className="eq-st-item">
              <span className={`eq-tag ${m.status === "Active" ? "t-svc" : "t-plain"}`}>
                {m.status === "Active" ? "Member" : m.status}
              </span>
              {m.type}
              {m.status !== "Active" && m.to_date ? ` (to ${formatDate(m.to_date)})` : ""}
            </span>
          ))}
        </div>
      )}
      {card.memberships.length === 0 && <div className="eq-st-sub">No membership</div>}

      {card.open_jobs.length > 0 && (
        <ul className="eq-st-jobs">
          {card.open_jobs.map((job) => (
            <li key={job.id}>
              <strong>Open job #{job.number}</strong>
              {job.type ? ` · ${job.type}` : ""} · {job.status}
              {job.next_appointment
                ? ` · ${job.status === "Scheduled" ? "visit" : "next"} ${formatSentAt(job.next_appointment)}`
                : ""}
              {job.summary && <div className="eq-st-sub">{job.summary}</div>}
            </li>
          ))}
        </ul>
      )}
      {card.open_jobs.length === 0 && <div className="eq-st-sub">No open jobs</div>}

      {card.recent_jobs.length > 0 && (
        <div className="eq-st-sub">
          Recent:{" "}
          {card.recent_jobs
            .map(
              (job) =>
                `#${job.number}${job.type ? ` ${job.type}` : ""}${
                  job.completed_on ? ` (${formatDate(job.completed_on)})` : ""
                }`
            )
            .join(", ")}
        </div>
      )}

      {card.other_matches.length > 0 && (
        <div className="eq-st-sub">
          That number is also on: {card.other_matches.map((m) => m.name).join(", ")}
        </div>
      )}

      <div className="eq-st-sub">{footer}</div>
    </div>
  );
}
