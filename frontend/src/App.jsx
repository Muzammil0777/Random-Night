import { useEffect, useState } from "react";

// ---- api ----
async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin", // session lives in an httpOnly cookie; JS never sees it
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw Object.assign(new Error(errorText(data)), { status: res.status });
  return data;
}

function errorText(data) {
  const d = data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => e.msg.replace(/^Value error, /, "")).join(". ");
  return "Something went wrong. Please try again.";
}

// Read the one-time login token and strip it from the URL exactly once, at load
// (not in an effect: StrictMode would run that twice and burn the single-use link).
const loginToken = new URLSearchParams(window.location.search).get("token");
if (loginToken) window.history.replaceState(null, "", "/");
const boot = loginToken ? api("/auth/verify", { method: "POST", body: { token: loginToken } }) : api("/me");

// ---- formatting ----
const TZ = "Asia/Kolkata";
const fmtTime = (iso) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: TZ });
const fmtDay = (ymd) => new Date(`${ymd}T12:00:00+05:30`).toLocaleDateString("en-IN", { weekday: "long", timeZone: TZ });
const rupees = (n) => `₹${n.toLocaleString("en-IN")}`;
const budgetLabel = (n, max) => (n === max ? `₹${n / 1000}K+` : `₹${n / 1000}K`);
const hoursLabel = (h) => (h === null ? "All night" : `${h} hrs`);
const LABELS = { solo: "Just me", friends: "With friends", new_people: "Meet new people",
                 party: "Party", food: "Food", chill: "Chill", surprise: "Surprise me" };

function isoDate(d) {
  return d.toLocaleDateString("en-CA", { timeZone: TZ }); // YYYY-MM-DD in IST
}
// strict: never today (Random Friday closes the Thursday before).
function nextFriday(strict = false) {
  const d = new Date();
  d.setDate(d.getDate() + ((5 - d.getDay() + 7) % 7 || (strict ? 7 : 0)));
  return isoDate(d);
}

// ---- app ----
export default function App() {
  const [me, setMe] = useState(undefined); // undefined = loading, null = logged out
  const [bootError, setBootError] = useState(null);

  useEffect(() => {
    let ignore = false;
    boot
      .then((user) => !ignore && setMe(user))
      .catch((e) => {
        if (ignore) return;
        setMe(null);
        if (loginToken) setBootError(e.message);
      });
    return () => { ignore = true; };
  }, []);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    setMe(null);
  }

  return (
    <div className="shell">
      <header className="top">
        <span className="brand">RANDOM NIGHT</span>
        {me && (
          <button type="button" className="link" onClick={logout}>Log out</button>
        )}
      </header>
      <main>
        {me === undefined && <p className="muted" aria-live="polite">Loading…</p>}
        {me === null && <Login initialError={bootError} />}
        {me && <Planner me={me} />}
      </main>
    </div>
  );
}

// ---- login / signup ----
function Login({ initialError }) {
  const [isNew, setIsNew] = useState(false);
  const [sentTo, setSentTo] = useState(null);
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState(false);
  const eighteenYearsAgo = isoDate(new Date(new Date().setFullYear(new Date().getFullYear() - 18)));

  async function submit(e) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget));
    setBusy(true);
    setError(null);
    try {
      await api("/auth/request", { method: "POST", body: isNew ? f : { email: f.email } });
      setSentTo(f.email);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (sentTo) {
    return (
      <section className="card">
        <h1>Check your email</h1>
        <p>We sent a login link to <strong>{sentTo}</strong>. It works once and expires in 15 minutes.</p>
        <button type="button" className="link" onClick={() => setSentTo(null)}>Use a different email</button>
      </section>
    );
  }

  return (
    <section>
      <h1 className="hero">You choose the vibe.<br />We create the night.</h1>
      <form className="card" onSubmit={submit}>
        <label htmlFor="email">Email</label>
        <input id="email" name="email" type="email" autoComplete="email" required />
        {isNew && (
          <>
            <label htmlFor="name">Your name</label>
            <input id="name" name="name" autoComplete="given-name" maxLength={80} required />
            <label htmlFor="dob">Date of birth <span className="muted">(18+ only)</span></label>
            <input id="dob" name="dob" type="date" max={eighteenYearsAgo} required />
          </>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" className="cta" disabled={busy}>
          {busy ? "Sending…" : isNew ? "Sign up" : "Email me a login link"}
        </button>
        <button type="button" className="link" onClick={() => { setIsNew(!isNew); setError(null); }}>
          {isNew ? "I already have an account" : "New here? Sign up"}
        </button>
      </form>
    </section>
  );
}

// ---- planner ----
function Choice({ legend, name, options, value, onChange, label = (o) => LABELS[o] ?? String(o) }) {
  return (
    <fieldset className="choice">
      <legend>{legend}</legend>
      <div className="chips">
        {options.map((o) => (
          <label key={String(o)} className="chip">
            <input type="radio" name={name} checked={value === o} onChange={() => onChange(o)} />
            <span>{label(o)}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Planner({ me }) {
  const [opts, setOpts] = useState(null);
  const [inputs, setInputs] = useState({ date: nextFriday(), area: "", budget_inr: 2000, hours: 4, vibe: "party", company: "solo" });
  const [night, setNight] = useState(null);
  const [drop, setDrop] = useState(null);
  const [womenOnly, setWomenOnly] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (key) => (value) => setInputs((prev) => ({ ...prev, [key]: value }));

  useEffect(() => {
    let ignore = false;
    api("/options").then((o) => {
      if (ignore) return;
      setOpts(o);
      setInputs((prev) => ({ ...prev, area: prev.area || o.areas[0] }));
    }).catch((e) => !ignore && setError(e.message));
    return () => { ignore = true; };
  }, []);

  async function generate(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (joining) setDrop(await joinDrop());
      else setNight(await api("/plans/preview", { method: "POST", body: inputs }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function joinDrop() {
    const { date, area, vibe, budget_inr } = inputs;
    // Ticking "I'm a woman" is the self-declaration women-only groups rely on.
    if (womenOnly && !me.gender) await api("/me", { method: "PATCH", body: { gender: "woman" } });
    try {
      return await api("/drops", { method: "POST", body: { date, area, vibe, budget_inr, women_only: womenOnly } });
    } catch (err) {
      if (err.status === 409) return api(`/drops/${date}`); // already joined: show where it stands
      throw err;
    }
  }

  async function leaveDrop() {
    try {
      await api(`/drops/${drop.date}`, { method: "DELETE" });
      setDrop(null);
    } catch (err) {
      setError(err.message);
      setDrop(null);
    }
  }

  const joining = inputs.company === "new_people";
  if (drop) return <Drop drop={drop} maxBudget={opts.budgets.at(-1)} onBack={() => setDrop(null)} onLeave={leaveDrop} />;
  if (night) return <Night night={night} inputs={inputs} maxBudget={opts.budgets.at(-1)} onBack={() => setNight(null)} />;
  if (!opts) return error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>;

  const today = isoDate(new Date());
  const lastDay = isoDate(new Date(Date.now() + 30 * 864e5));
  return (
    <form onSubmit={generate}>
      <h1>Hey {me.name}, what's the plan?</h1>
      <div className="card">
        <label htmlFor="date">When</label>
        <input id="date" type="date" min={today} max={lastDay} value={inputs.date}
               onChange={(e) => set("date")(e.target.value)} required />
        <label htmlFor="area">Where in Hyderabad</label>
        <select id="area" value={inputs.area} onChange={(e) => set("area")(e.target.value)}>
          {opts.areas.map((a) => <option key={a}>{a}</option>)}
        </select>
        <Choice legend="Budget per person" name="budget" options={opts.budgets} value={inputs.budget_inr}
                onChange={set("budget_inr")} label={(b) => budgetLabel(b, opts.budgets.at(-1))} />
        {!joining && (
          <Choice legend="How long" name="hours" options={opts.hours} value={inputs.hours}
                  onChange={set("hours")} label={hoursLabel} />
        )}
        <Choice legend="Vibe" name="vibe" options={opts.vibes} value={inputs.vibe} onChange={set("vibe")} />
        <Choice legend="Who's coming" name="company" options={opts.company} value={inputs.company}
                onChange={(c) => {
                  set("company")(c);
                  if (c === "new_people" && inputs.date <= today) set("date")(nextFriday(true));
                }} />
        {joining && (
          <label className="check">
            <input type="checkbox" checked={womenOnly} onChange={(e) => setWomenOnly(e.target.checked)} />
            <span>I'm a woman and want a women-only group</span>
          </label>
        )}
      </div>
      {joining && (
        <p className="note">
          Random Friday: join by 11 PM Thursday and we match you into a group of 4–6 who picked the same area, vibe and
          budget. Nights run 9 PM to 1 AM.
        </p>
      )}
      {!me.id_verified && (
        <p className="note">Bars and clubs unlock once you're 21+ and we've checked your ID at your first night.</p>
      )}
      {inputs.company === "friends" && (
        <p className="note">Bringing friends to a bar? Everyone needs a valid ID showing they're 21+.</p>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <button type="submit" className="cta" disabled={busy}>{busy ? "One moment…" : joining ? "Join Random Friday →" : "Generate my night →"}</button>
    </form>
  );
}

function Drop({ drop, maxBudget, onBack, onLeave }) {
  const picks = { ...drop, hours: 4 };
  if (drop.status === "matched") {
    return (
      <>
        <p className="note">Your group: <strong>{drop.group.join(", ")}</strong>. Meet them at the first stop.</p>
        <Night night={drop.night} inputs={picks} maxBudget={maxBudget} onBack={onBack} />
      </>
    );
  }
  const waiting = drop.status === "waiting";
  return (
    <section className="card">
      <h1>{waiting ? "You're in for Random Friday" : "No group this week"}</h1>
      <p className="meta">{[fmtDay(drop.date), drop.area, budgetLabel(drop.budget_inr, maxBudget), LABELS[drop.vibe]].join(" · ")}</p>
      <p>
        {waiting
          ? "We form groups of 4–6 on Thursday night. Check back then to see your group and your night."
          : "Not enough people picked the same area, vibe and budget this week. Plan a night with friends, or try next Friday."}
      </p>
      {waiting && <button type="button" className="cta ghost" onClick={onLeave}>Leave this Friday</button>}
      <button type="button" className="link" onClick={onBack}>Back</button>
    </section>
  );
}

function Night({ night, inputs, maxBudget, onBack }) {
  const anyPartner = night.stops.some((s) => s.is_partner);
  const meta = [fmtDay(inputs.date), inputs.area, budgetLabel(inputs.budget_inr, maxBudget),
                hoursLabel(inputs.hours), LABELS[inputs.vibe]];
  return (
    <section>
      <h1>Your night, curated.</h1>
      <p className="meta">{meta.join(" · ")}</p>
      <ol className="timeline">
        {night.stops.map((s) => (
          <li key={`${s.starts_at}-${s.title}`}>
            <time dateTime={s.starts_at}>{fmtTime(s.starts_at)}</time>
            <div>
              <h2>{s.title}</h2>
              <p className="muted">{s.venue} · {s.area} · {rupees(s.price_per_head_inr)}</p>
              {s.is_partner && <span className="badge">Partner venue</span>}
            </div>
          </li>
        ))}
      </ol>
      <p className="total">About {rupees(night.total_inr)} per person, paid at the venues. Random Night is free.</p>
      {anyPartner && (
        <p className="note">
          Partner venues pay Random Night when you check in. They only appear when they already fit your
          area, budget, time and vibe.
        </p>
      )}
      {!night.bars_unlocked && <p className="note">No bars or clubs tonight: those need 21+ and an ID check.</p>}
      <p className="muted small">Area, budget and duration are known upfront. The surprise is the experience, not your safety.</p>
      <button type="button" className="cta ghost" onClick={onBack}>Change my night</button>
    </section>
  );
}
