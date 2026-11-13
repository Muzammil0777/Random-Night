import { useEffect, useState } from "react";
import { api } from "./App.jsx";

// Venue door page (/venue): staff log in once with the venue key, then type each guest's 6-digit code.
export default function Staff() {
  const [me, setMe] = useState(undefined); // undefined = loading, null = logged out

  useEffect(() => {
    let ignore = false;
    api("/staff/me").then((m) => !ignore && setMe(m)).catch(() => !ignore && setMe(null));
    return () => { ignore = true; };
  }, []);

  async function logout() {
    await api("/staff/logout", { method: "POST" }).catch(() => {});
    setMe(null);
  }

  return (
    <div className="shell">
      <header className="top">
        <span className="brand">RANDOM NIGHT · VENUE</span>
        {me && <button type="button" className="link" onClick={logout}>Log out</button>}
      </header>
      <main>
        {me === undefined && <p className="muted" aria-live="polite">Loading…</p>}
        {me === null && <KeyLogin onIn={setMe} />}
        {me && <CheckIn me={me} />}
      </main>
    </div>
  );
}

function KeyLogin({ onIn }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onIn(await api("/staff/login", { method: "POST", body: { key: new FormData(e.currentTarget).get("key") } }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h1>Venue check-in</h1>
      <label htmlFor="key">Venue key</label>
      <input id="key" name="key" type="password" autoComplete="off" required />
      {error && <p className="error" role="alert">{error}</p>}
      <button type="submit" className="cta" disabled={busy}>{busy ? "Checking…" : "Log in"}</button>
    </form>
  );
}

function CheckIn({ me }) {
  const [code, setCode] = useState("");
  const [result, setResult] = useState(null); // { ok, text }
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api("/staff/checkin", { method: "POST", body: { code } });
      setResult({ ok: true, text: `Checked in: ${r.guest}, ${r.stop}` });
      setCode("");
    } catch (err) {
      setResult({ ok: false, text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h1>{me.venue}</h1>
      <p className="muted small">{me.label}</p>
      <label htmlFor="code">Guest's 6-digit code</label>
      <input id="code" className="code-input" inputMode="numeric" autoComplete="off" pattern="\d{6}" maxLength={6}
             value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
      <button type="submit" className="cta" disabled={busy || code.length !== 6}>{busy ? "Checking…" : "Check in"}</button>
      {result && (
        <p className={result.ok ? "ok" : "error"} role={result.ok ? "status" : "alert"}>{result.text}</p>
      )}
    </form>
  );
}
