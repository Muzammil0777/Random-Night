import { useEffect, useRef, useState } from "react";
import { api } from "./App.jsx";

// Venue door page (/venue): staff log in once with the venue key, then type each guest's 6-digit code.
export default function Staff() {
  const [me, setMe] = useState(undefined); // undefined = loading, null = logged out
  const [checkins, setCheckins] = useState(0); // bumps after each check-in so the dashboard refreshes

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
        {me === undefined && <p className="muted" role="status">Loading…</p>}
        {me === null && <KeyLogin onIn={setMe} />}
        {me && <CheckIn me={me} onCheckedIn={() => setCheckins((n) => n + 1)} />}
        {me && <Tonight refresh={checkins} />}
        {me && <Dashboard refresh={checkins} />}
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

function CheckIn({ me, onCheckedIn }) {
  const [code, setCode] = useState("");
  const [result, setResult] = useState(null); // { ok, text }
  const [busy, setBusy] = useState(false);
  const input = useRef(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api("/staff/checkin", { method: "POST", body: { code } });
      setResult({ ok: true, text: `Checked in: ${r.guest}, ${r.stop}` });
      setCode("");
      onCheckedIn();
    } catch (err) {
      setResult({ ok: false, text: err.message });
    } finally {
      setBusy(false);
      input.current?.focus(); // ready for the next guest
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h1>{me.venue}</h1>
      <p className="muted small">{me.label}</p>
      <label htmlFor="code">Guest's 6-digit code</label>
      <input id="code" ref={input} className="code-input" inputMode="numeric" autoComplete="off" pattern="\d{6}"
             maxLength={6} autoFocus placeholder="000000" value={code}
             onChange={(e) => { setCode(e.target.value.replace(/\D/g, "")); setResult(null); }} required />
      <button type="submit" className="cta" disabled={busy || code.length !== 6}>{busy ? "Checking…" : "Check in"}</button>
      {result && (
        <p className={result.ok ? "banner ok" : "banner err"} role={result.ok ? "status" : "alert"}>
          {result.ok ? "✓ " : "✕ "}{result.text}
        </p>
      )}
    </form>
  );
}

const timeIST = (iso) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });

// Tonight's check-ins at this venue, newest first: staff can see who's already in.
function Tonight({ refresh }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let ignore = false;
    api("/staff/tonight").then((r) => !ignore && setRows(r)).catch(() => !ignore && setRows([]));
    return () => { ignore = true; };
  }, [refresh]);
  if (!rows) return null;
  return (
    <section className="card" aria-labelledby="tonight-title">
      <h2 id="tonight-title">Tonight's check-ins ({rows.length})</h2>
      {rows.length === 0 ? <p className="muted small">Nobody yet tonight.</p> : (
        <ul className="tonight">
          {rows.map((r) => (
            <li key={`${r.at}-${r.guest}-${r.stop}`}><span><strong>{r.guest}</strong> · {r.stop}</span>
              <time className="muted" dateTime={r.at}>{timeIST(r.at)}</time></li>
          ))}
        </ul>
      )}
    </section>
  );
}

const thisMonth = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }).slice(0, 7);
const inr = (n) => `₹${n.toLocaleString("en-IN")}`;

// Routed vs checked-in guests per night, and the month's bill (only checked-in guests are billed).
function Dashboard({ refresh }) {
  const [month, setMonth] = useState(thisMonth);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let ignore = false;
    setError(null);
    api(`/staff/dashboard?month=${month}`)
      .then((d) => !ignore && setData(d))
      .catch((e) => !ignore && setError(e.message));
    return () => { ignore = true; };
  }, [month, refresh]);

  return (
    <section className="card">
      <h2>Your guests</h2>
      <label htmlFor="month">Month</label>
      <input id="month" type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
      {error && <p className="error" role="alert">{error}</p>}
      {data && (
        <>
          {data.nights.length === 0 ? (
            <p className="muted">No guests routed here this month yet.</p>
          ) : (
            <table className="nights">
              <caption className="muted small">Routed = booked a stop here. Only checked-in guests are billed.</caption>
              <thead><tr><th scope="col">Night</th><th scope="col">Routed</th><th scope="col">Checked in</th></tr></thead>
              <tbody>
                {data.nights.map((n) => (
                  <tr key={n.date}><td>{n.date}</td><td>{n.routed}</td><td>{n.checked_in}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="total">
            {data.billable_guests} checked-in guests · {inr(data.total_inr)} due
            <span className="muted small"> (current rate {inr(data.rate_inr)} per guest)</span>
          </p>
          <a className="cta ghost" href={`/api/staff/invoice.csv?month=${data.month}`} download>Download invoice (CSV)</a>
        </>
      )}
    </section>
  );
}
