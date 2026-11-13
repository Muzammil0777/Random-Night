import { useEffect, useState } from "react";

// ---- api ----
export async function api(path, { method = "GET", body } = {}) {
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
        {me && <Planner me={me} onMe={setMe} />}
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

function Planner({ me, onMe }) {
  const [opts, setOpts] = useState(null);
  const [inputs, setInputs] = useState({ date: nextFriday(), area: "", budget_inr: 2000, hours: 4, vibe: "party", company: "solo" });
  const [night, setNight] = useState(null);
  const [booked, setBooked] = useState(null);
  const [last, setLast] = useState(null); // most recent night with a check-in: rate it, report someone
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
    api("/plans/next").then((b) => !ignore && setBooked(b)).catch(() => {});
    api("/plans/last").then((l) => !ignore && setLast(l)).catch(() => {});
    return () => { ignore = true; };
  }, []);

  async function book() {
    setBusy(true);
    setError(null);
    try {
      setBooked(await api("/plans", { method: "POST", body: inputs }));
      setNight(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setError(null);
    try {
      await api(`/plans/${booked.id}`, { method: "DELETE" });
      setBooked(null);
    } catch (err) {
      setError(err.message);
    }
  }

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
      // Already joined: show where it stands. (409 can also mean a night is booked that date.)
      if (err.status === 409) return api(`/drops/${date}`).catch(() => { throw err; });
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
  if (drop) {
    return <Drop drop={drop} me={me} onMe={onMe} maxBudget={opts.budgets.at(-1)} onBack={() => setDrop(null)}
                 onLeave={leaveDrop} />;
  }
  if (booked && opts) {
    return (
      <Night night={booked} inputs={booked.inputs} maxBudget={opts.budgets.at(-1)} title="You're booked.">
        <Safety night={booked} me={me} onMe={onMe} />
        {error && <p className="error" role="alert">{error}</p>}
        {!booked.group && <button type="button" className="cta ghost" onClick={cancel}>Cancel this night</button>}
        <button type="button" className="link" onClick={() => setBooked(null)}>Plan another night</button>
      </Night>
    );
  }
  if (night) {
    return (
      <Night night={night} inputs={inputs} maxBudget={opts.budgets.at(-1)}>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="button" className="cta" onClick={book} disabled={busy}>{busy ? "Booking…" : "Book this night"}</button>
        <button type="button" className="cta ghost" onClick={() => { setNight(null); setError(null); }}>Change my night</button>
      </Night>
    );
  }
  if (!opts) return error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>;

  const today = isoDate(new Date());
  const lastDay = isoDate(new Date(Date.now() + 30 * 864e5));
  return (
    <>
    {last && <LastNight night={last} />}
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
    </>
  );
}

function Drop({ drop, me, onMe, maxBudget, onBack, onLeave }) {
  const picks = { ...drop, hours: 4 };
  if (drop.status === "matched") {
    return (
      <>
        <p className="note">Your group: <strong>{drop.group.join(", ")}</strong>. Meet them at the first stop.</p>
        <Night night={drop.night} inputs={picks} maxBudget={maxBudget} title="Your group's night.">
          <Safety night={drop.night} me={me} onMe={onMe} />
          <button type="button" className="cta ghost" onClick={onBack}>Back</button>
        </Night>
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

function Night({ night, inputs, maxBudget, title = "Your night, curated.", children }) {
  const anyPartner = night.stops.some((s) => s.is_partner);
  const meta = [fmtDay(inputs.date), inputs.area, budgetLabel(inputs.budget_inr, maxBudget),
                hoursLabel(inputs.hours), LABELS[inputs.vibe]];
  return (
    <section>
      <h1>{title}</h1>
      <p className="meta">{meta.join(" · ")}</p>
      <ol className="timeline">
        {night.stops.map((s) => (
          <li key={`${s.starts_at}-${s.title}`}>
            <time dateTime={s.starts_at}>{fmtTime(s.starts_at)}</time>
            <div>
              <h2>{s.title}</h2>
              <p className="muted">{s.venue} · {s.area} · {rupees(s.price_per_head_inr)}</p>
              {s.is_partner && <span className="badge">Partner venue</span>}
              {s.code && (
                <p className="code">
                  {s.checked_in ? "Checked in ✓" : <>Show staff this code: <strong>{s.code.slice(0, 3)} {s.code.slice(3)}</strong></>}
                </p>
              )}
              {s.checked_in && <Stars stopId={s.plan_stop_id} title={s.title} initial={s.my_stars} />}
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
      {night.stops[0]?.code && (
        <p className="muted small">Each code works once, only at that venue, only that night. Don't share it.</p>
      )}
      {night.members?.length > 0 && <GroupSafety members={night.members} />}
      {children}
    </section>
  );
}

// ---- after the night: ratings, report/block ----
function LastNight({ night }) {
  const toRate = night.stops.filter((s) => s.checked_in);
  return (
    <section className="card">
      <h2>How was {fmtDay(night.inputs.date)}?</h2>
      {toRate.map((s) => (
        <div key={s.plan_stop_id}>
          <p className="muted small">{s.title} · {s.venue}</p>
          <Stars stopId={s.plan_stop_id} title={s.title} initial={s.my_stars} />
        </div>
      ))}
      {night.members?.length > 0 && <GroupSafety members={night.members} />}
    </section>
  );
}

function Stars({ stopId, title, initial }) {
  const [stars, setStars] = useState(initial);
  const [error, setError] = useState(null);

  async function rate(n) {
    setError(null);
    try {
      setStars((await api("/ratings", { method: "POST", body: { plan_stop_id: stopId, stars: n } })).stars);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="stars" role="group" aria-label={`Rate ${title}`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" aria-label={`${n} star${n > 1 ? "s" : ""}`} aria-pressed={stars === n}
                className={stars >= n ? "on" : ""} onClick={() => rate(n)}>★</button>
      ))}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}

function GroupSafety({ members }) {
  return (
    <div className="safety">
      <h3>Your group</h3>
      <p className="muted small">If anyone made you uneasy, tell us. Reporting also blocks them: you won't be grouped again.</p>
      {members.map((m) => <MemberActions key={m.id} member={m} />)}
    </div>
  );
}

function MemberActions({ member }) {
  const [done, setDone] = useState(null);
  const [error, setError] = useState(null);

  async function send(path, body, message) {
    setError(null);
    try {
      await api(path, { method: "POST", body });
      setDone(message);
    } catch (err) {
      setError(err.message);
    }
  }

  function report(e) {
    e.preventDefault();
    const reason = new FormData(e.currentTarget).get("reason");
    send("/reports", { user_id: member.id, reason }, `Reported and blocked ${member.name}. Thank you for telling us.`);
  }

  if (done) return <p className="ok" role="status">{done}</p>;
  return (
    <details className="member">
      <summary>{member.name}: report or block</summary>
      <form onSubmit={report}>
        <label htmlFor={`reason-${member.id}`}>What happened?</label>
        <textarea id={`reason-${member.id}`} name="reason" minLength={3} maxLength={1000} rows={3} required />
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" className="cta">Report and block</button>
        <button type="button" className="link" onClick={() => send("/blocks", { user_id: member.id }, `Blocked ${member.name}.`)}>
          Just block
        </button>
      </form>
    </details>
  );
}

// ---- safety (task 10): share the plan, SOS ----
const whatsapp = (phone, text) => `https://wa.me/${phone ? phone.replace("+", "") : ""}?text=${encodeURIComponent(text)}`;

function planText(night) {
  const stops = night.stops.map((s) => `${fmtTime(s.starts_at)} ${s.title}, ${s.venue}, ${s.area}`);
  const who = night.group ? `with a Random Night group of ${night.group.length}` : "planned with Random Night";
  const day = new Date(`${night.inputs.date}T12:00:00+05:30`)
    .toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short", timeZone: TZ });
  return [`My night out on ${day} (${who}):`, ...stops, "I'll message you when I'm home."].join("\n");
}

function Safety({ night, me, onMe }) {
  const [sos, setSos] = useState(false);
  const [locating, setLocating] = useState(false);
  const contact = me.emergency_contact;

  async function share() {
    const text = planText(night); // no check-in codes: those stay with the guest
    if (!contact && navigator.share) {
      await navigator.share({ text }).catch(() => {}); // closing the share sheet isn't an error
      return;
    }
    window.open(whatsapp(contact, text), "_blank", "noopener");
  }

  function sendLocation() {
    // location.href, not window.open: this runs after the location callback, where pop-ups get blocked.
    const send = (where) => { window.location.href = whatsapp(contact, `SOS from Random Night: I need help. ${where}`); };
    if (!navigator.geolocation) return send(`Tonight's plan: ${night.stops.map((s) => s.venue).join(" → ")}`);
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (p) => { setLocating(false); send(`I'm here: https://maps.google.com/?q=${p.coords.latitude},${p.coords.longitude}`); },
      () => { setLocating(false); send(`Tonight's plan: ${night.stops.map((s) => s.venue).join(" → ")}`); },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  return (
    <section className="card safety-card" aria-labelledby="safety-title">
      <h2 id="safety-title">Safety</h2>
      {!contact && <ContactForm onMe={onMe} />}
      <button type="button" className="cta ghost" onClick={share}>
        {contact ? "Share my plan on WhatsApp" : "Share my plan"}
      </button>
      <button type="button" className="cta sos" aria-expanded={sos} aria-controls="sos-panel" onClick={() => setSos(!sos)}>
        SOS
      </button>
      {sos && (
        <div id="sos-panel" className="sos-panel">
          <a className="cta sos" href="tel:112">Call 112 (emergency)</a>
          {contact ? (
            <>
              <a className="cta ghost" href={`tel:${contact}`}>Call my emergency contact</a>
              <button type="button" className="cta ghost" onClick={sendLocation} disabled={locating}>
                {locating ? "Finding you…" : "Send my location on WhatsApp"}
              </button>
            </>
          ) : (
            <p className="muted small">Add an emergency contact above to call them or send your location in one tap.</p>
          )}
        </div>
      )}
    </section>
  );
}

function ContactForm({ onMe }) {
  const [error, setError] = useState(null);

  async function save(e) {
    e.preventDefault();
    setError(null);
    try {
      onMe(await api("/me", { method: "PATCH", body: { emergency_contact: new FormData(e.currentTarget).get("phone") } }));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form className="contact" onSubmit={save}>
      <label htmlFor="phone">Emergency contact's phone</label>
      <input id="phone" name="phone" type="tel" inputMode="tel" autoComplete="off" placeholder="+91 98765 43210" required />
      {error && <p className="error" role="alert">{error}</p>}
      <button type="submit" className="cta">Save contact</button>
    </form>
  );
}
