import { useState } from "react";
import { api } from "../api";

export default function Login({ onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const user = await api.login(email.trim(), password);
      onSignedIn(user);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="eq-login-wrap">
      <div className="eq-login">
        <div className="eq-top">
          <span className="eq-drop" />
          <span className="eq-mark">
            <b>Expert</b>
            <span>Inbox Queue</span>
          </span>
        </div>

        <form onSubmit={submit}>
          <h1>Sign in</h1>
          <p className="eq-login-sub">
            Customer mail for the whole office, in one place.
          </p>

          {error && <div className="eq-error">{error}</div>}

          <div className="eq-field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="eq-field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button className="eq-btn pri" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
