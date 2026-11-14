import { useEffect, useRef, useState } from "react";
import { InstallButton, InstallGuide, WELCOMED_KEY, Welcome } from "./Welcome.jsx";

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
const ICONS = { party: "🎉", food: "🍜", chill: "🌙", surprise: "🎲", solo: "🙋", friends: "👯", new_people: "🤝" };
const KINDS = { // what to expect at each kind of stop
  meet: ["👋", "Meet up and ease into the night"], music: ["🎶", "Live music: find a good spot"],
  challenge: ["🎯", "A game or challenge, just for fun"], food: ["🍽️", "Food stop: eat well"],
  finale: ["✨", "The finale: end on a high"],
};
const firstName = (name) => (name.split(" ")[0] || name);
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
  const [welcome, setWelcome] = useState(false);
  const [installHelp, setInstallHelp] = useState(false);
  const [view, setView] = useState("plan"); // "plan" | "me"

  useEffect(() => {
    if (me && !localStorage.getItem(WELCOMED_KEY)) setWelcome(true); // first sign-in on this phone
  }, [me]);

  function closeWelcome() {
    localStorage.setItem(WELCOMED_KEY, "1");
    setWelcome(false);
  }

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
    setView("plan");
  }

  return (
    <div className="shell">
      <header className="top">
        <span className="brand">RANDOM NIGHT</span>
        <span className="top-links">
          <InstallButton onHelp={() => setInstallHelp(true)} />
          {me && (
            <nav className="nav" aria-label="Main">
              {[["plan", "Plan"], ["me", "Me"]].map(([id, label]) => (
                <button key={id} type="button" className="navlink" aria-current={view === id ? "page" : undefined}
                        onClick={() => setView(id)}>{label}</button>
              ))}
              <button type="button" className="navlink" onClick={() => setWelcome(true)}>Help</button>
            </nav>
          )}
        </span>
      </header>
      {welcome && <Welcome onDone={closeWelcome} />}
      {installHelp && (
        <div className="welcome" role="dialog" aria-modal="true" aria-labelledby="install-title">
          <div className="welcome-card">
            <h1 id="install-title">Install the app</h1>
            <InstallGuide />
            <button type="button" className="cta ghost" onClick={() => setInstallHelp(false)}>Close</button>
          </div>
        </div>
      )}
      <main>
        {me === undefined && <Skeleton lines={4} />}
        {me === null && (
          <>
            <Login initialError={bootError} onLoggedIn={setMe} />
            <HowItWorks />
            <Waitlist />
            <section className="card" aria-labelledby="get-app">
              <h2 id="get-app">Get the app</h2>
              <p className="muted small">No app store needed: add Random Night to your home screen in a few taps.</p>
              <InstallGuide />
            </section>
          </>
        )}
        {me && view === "me" && <Me me={me} onMe={setMe} onLogout={logout} />}
        {me && view === "plan" && <Planner me={me} onMe={setMe} />}
      </main>
    </div>
  );
}

// ---- login / signup ----
const GOOGLE_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID; // public; no button when unset
const maxDob = () => isoDate(new Date(new Date().setFullYear(new Date().getFullYear() - 18)));

function loadGoogle() {
  if (window.google?.accounts?.id) return Promise.resolve(window.google);
  return new Promise((resolve, reject) => {
    const script = Object.assign(document.createElement("script"),
      { src: "https://accounts.google.com/gsi/client", async: true, onerror: reject });
    script.onload = () => resolve(window.google);
    document.head.appendChild(script);
  });
}

// "Continue with Google". New accounts add a date of birth once: Google doesn't share it.
function GoogleSignIn({ onLoggedIn }) {
  const buttonRef = useRef(null);
  const [pending, setPending] = useState(null); // Google credential waiting for a date of birth
  const [error, setError] = useState(null);

  async function send(credential, dob) {
    setError(null);
    try {
      onLoggedIn(await api("/auth/google", { method: "POST", body: dob ? { credential, dob } : { credential } }));
    } catch (err) {
      if (err.status === 428) setPending(credential);
      else setError(err.message);
    }
  }

  useEffect(() => {
    let cancelled = false;
    loadGoogle().then((google) => {
      if (cancelled || !buttonRef.current) return;
      google.accounts.id.initialize({ client_id: GOOGLE_ID, callback: (r) => send(r.credential) });
      google.accounts.id.renderButton(buttonRef.current,
        { theme: "filled_black", size: "large", shape: "pill", text: "continue_with", width: 300 });
    }).catch(() => !cancelled && setError("Couldn't load Google sign-in. Use the email link below."));
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- set up the button once

  if (pending) {
    return (
      <form className="card" onSubmit={(e) => { e.preventDefault(); send(pending, new FormData(e.currentTarget).get("dob")); }}>
        <h2>One last thing</h2>
        <label htmlFor="g-dob">Date of birth <span className="muted">(18+ only)</span></label>
        <input id="g-dob" name="dob" type="date" max={maxDob()} required />
        <p className="muted small">We need it for the age rules. Bars and clubs also check your ID at the door.</p>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" className="cta">Finish signing up</button>
      </form>
    );
  }
  return (
    <div className="google">
      <div ref={buttonRef} />
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}

function Login({ initialError, onLoggedIn }) {
  const [isNew, setIsNew] = useState(false);
  const [sentTo, setSentTo] = useState(null);
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState(false);
  const eighteenYearsAgo = maxDob();

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
      {GOOGLE_ID && (
        <>
          <GoogleSignIn onLoggedIn={onLoggedIn} />
          <p className="or muted small">or get a login link by email</p>
        </>
      )}
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
function Skeleton({ lines = 3 }) {
  return (
    <div className="skeleton" role="status" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => <span key={i} />)}
    </div>
  );
}

function Step({ n, title, hint, children }) {
  return (
    <fieldset className="step">
      <legend><span className="num" aria-hidden="true">{n}</span>{title}</legend>
      {hint && <p className="hint">{hint}</p>}
      {children}
    </fieldset>
  );
}

const choiceLabel = (o) => `${ICONS[o] ? `${ICONS[o]} ` : ""}${LABELS[o] ?? o}`;

function Choice({ legend, name, options, value, onChange, label = choiceLabel }) {
  return (
    <fieldset className="choice">
      <legend className="sr-only">{legend}</legend>
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
    if (!window.confirm("Cancel this night? Its check-in codes stop working.")) return;
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
    if (!window.confirm("Leave this Random Friday? You can join again until 11 PM Thursday.")) return;
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
  if (!opts) return error ? <p className="error" role="alert">{error}</p> : <Skeleton lines={6} />;

  const today = isoDate(new Date());
  const lastDay = isoDate(new Date(Date.now() + 30 * 864e5));
  return (
    <>
    {last && <LastNight night={last} />}
    <form onSubmit={generate} className="planner">
      <h1>Hey {firstName(me.name)}, what's the plan?</h1>
      <Step n={1} title="When & where" hint="Nights start at 9 PM.">
        <label htmlFor="date">Date</label>
        <input id="date" type="date" min={today} max={lastDay} value={inputs.date}
               onChange={(e) => set("date")(e.target.value)} required />
        <label htmlFor="area">Area in Hyderabad</label>
        <select id="area" value={inputs.area} onChange={(e) => set("area")(e.target.value)}>
          {opts.areas.map((a) => <option key={a}>{a}</option>)}
        </select>
      </Step>
      <Step n={2} title="Budget per person" hint="Roughly what you'd spend in total, paid at the venues.">
        <Choice legend="Budget per person" name="budget" options={opts.budgets} value={inputs.budget_inr}
                onChange={set("budget_inr")} label={(b) => budgetLabel(b, opts.budgets.at(-1))} />
      </Step>
      {!joining && (
        <Step n={3} title="How long" hint="Every stop fits inside this window.">
          <Choice legend="How long" name="hours" options={opts.hours} value={inputs.hours}
                  onChange={set("hours")} label={hoursLabel} />
        </Step>
      )}
      <Step n={joining ? 3 : 4} title="Vibe" hint="Surprise me mixes it up.">
        <Choice legend="Vibe" name="vibe" options={opts.vibes} value={inputs.vibe} onChange={set("vibe")} />
      </Step>
      <Step n={joining ? 4 : 5} title="Who's coming" hint="Meet new people joins this week's Random Friday.">
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
      </Step>
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
      <div className="sticky-cta">
        <p className="summary">
          {[fmtDay(inputs.date), inputs.area, budgetLabel(inputs.budget_inr, opts.budgets.at(-1)),
            joining ? "9 PM–1 AM" : hoursLabel(inputs.hours), LABELS[inputs.vibe]].join(" · ")}
        </p>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" className="cta" disabled={busy}>
          {busy ? "One moment…" : joining ? "Join Random Friday →" : "Generate my night →"}
        </button>
      </div>
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
              <h2><span aria-hidden="true">{KINDS[s.kind]?.[0]} </span>{s.title}</h2>
              <p className="kind">{KINDS[s.kind]?.[1]}</p>
              <p className="muted">{s.venue} · {s.area} · {rupees(s.price_per_head_inr)}</p>
              {s.is_partner && <span className="badge">Partner venue</span>}
              {s.code && (s.checked_in
                ? <p className="ok">Checked in ✓</p>
                : (
                  <div className="ticket">
                    <span className="muted small">Show staff this code</span>
                    <strong aria-label={`Code ${s.code.split("").join(" ")}`}>{s.code.slice(0, 3)} {s.code.slice(3)}</strong>
                  </div>
                ))}
              {s.checked_in && <Stars stopId={s.plan_stop_id} title={s.title} initial={s.my_stars} />}
            </div>
          </li>
        ))}
      </ol>
      <p className="total"><span>About {rupees(night.total_inr)}</span> per person, paid at the venues. Random Night is free.</p>
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

// ---- landing (task 11b): how it works + launch waitlist with a referral bump ----
const refFromLink = new URLSearchParams(window.location.search).get("ref"); // a friend's share link
const WAITLIST_KEY = "rn_waitlist"; // your own share code: not a login, just so your place shows next visit

function HowItWorks() {
  return (
    <section className="card how">
      <h2>How it works</h2>
      <ol>
        <li><strong>Pick four things:</strong> area, budget, how long, and the vibe.</li>
        <li><strong>Get a timed night:</strong> 2–4 stops that fit, with prices upfront. Free for you.</li>
        <li><strong>Go solo, with friends, or meet new people:</strong> Random Friday puts you in a group of 4–6.</li>
      </ol>
      <p className="muted small">
        Partner venues pay us when you check in, and they're always labelled. They only show up when they already
        fit your picks. Bars and clubs need 21+ and an ID check.
      </p>
    </section>
  );
}

function Waitlist() {
  const [place, setPlace] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [areas, setAreas] = useState([]);

  useEffect(() => {
    let ignore = false;
    api("/options").then((o) => !ignore && setAreas(o.areas)).catch(() => {});
    const code = localStorage.getItem(WAITLIST_KEY);
    if (code) api(`/waitlist/${encodeURIComponent(code)}`).then((p) => !ignore && setPlace(p)).catch(() => {});
    return () => { ignore = true; };
  }, []);

  async function join(e) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget));
    setBusy(true);
    setError(null);
    try {
      const p = await api("/waitlist", { method: "POST", body: { email: f.email, area: f.area || null, ref: refFromLink } });
      if (p.ref_code) localStorage.setItem(WAITLIST_KEY, p.ref_code);
      setPlace(p);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const link = place?.ref_code && `${window.location.origin}/?ref=${place.ref_code}`;
  const pitch = "Random Night: tell it your area, budget and vibe, get a curated night out in Hyderabad. Join me:";

  async function copy() {
    await navigator.clipboard.writeText(link).catch(() => {});
    setCopied(true);
  }

  return (
    <section className="card waitlist" aria-labelledby="wl-title">
      <h2 id="wl-title">First Random Friday</h2>
      {place ? (
        <>
          <p className="big">You're <strong>#{place.position}</strong> of {place.total}</p>
          {link ? (
            <>
              <p>Every friend who joins with your link moves you up. {place.referrals > 0 && `${place.referrals} so far.`}</p>
              <a className="cta" href={`https://wa.me/?text=${encodeURIComponent(`${pitch} ${link}`)}`}
                 target="_blank" rel="noopener noreferrer">Share on WhatsApp</a>
              <button type="button" className="cta ghost" onClick={copy}>{copied ? "Link copied" : "Copy my link"}</button>
            </>
          ) : (
            <p className="muted small">You're already on the list. Use the link from the phone you joined on to share it.</p>
          )}
        </>
      ) : (
        <form onSubmit={join}>
          <p>We're starting with one Friday night. Get on the list: invites go out by place in line.</p>
          {refFromLink && <p className="note">A friend sent you: joining here moves them up.</p>}
          <label htmlFor="wl-email">Email</label>
          <input id="wl-email" name="email" type="email" autoComplete="email" required />
          <label htmlFor="wl-area">Where you'd go out <span className="muted">(optional)</span></label>
          <select id="wl-area" name="area" defaultValue="">
            <option value="">Anywhere in Hyderabad</option>
            {areas.map((a) => <option key={a}>{a}</option>)}
          </select>
          {error && <p className="error" role="alert">{error}</p>}
          <button type="submit" className="cta" disabled={busy}>{busy ? "Joining…" : "Join the list"}</button>
        </form>
      )}
    </section>
  );
}

// ---- me (task 14): profile, emergency contact, log out ----
function Me({ me, onMe, onLogout }) {
  const [name, setName] = useState(me.name);
  const [contact, setContact] = useState(me.emergency_contact ?? "");
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const updated = await api("/me", { method: "PATCH", body: { name, emergency_contact: contact } });
      onMe(updated);
      setContact(updated.emergency_contact ?? "");
      setMsg("Saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const dob = new Date(`${me.dob}T12:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  return (
    <section>
      <h1>Me</h1>
      <form className="card" onSubmit={save}>
        <label htmlFor="me-name">Name</label>
        <input id="me-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required
               autoComplete="name" />
        <label htmlFor="me-contact">Emergency contact's phone</label>
        <input id="me-contact" type="tel" inputMode="tel" value={contact} onChange={(e) => setContact(e.target.value)}
               placeholder="+91 98765 43210" autoComplete="off" />
        <p className="hint">Used by Share plan and SOS on your nights. Leave it empty to remove it.</p>
        {error && <p className="error" role="alert">{error}</p>}
        {msg && <p className="ok" role="status">{msg}</p>}
        <button type="submit" className="cta" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </form>
      <dl className="card facts">
        <div><dt>Email</dt><dd>{me.email}</dd></div>
        <div><dt>Date of birth</dt><dd>{dob}</dd></div>
        <div>
          <dt>ID check</dt>
          <dd>{me.id_verified ? <span className="ok">Checked ✓</span> : "Not yet: staff check your ID at your first bar night"}</dd>
        </div>
      </dl>
      <button type="button" className="cta ghost" onClick={onLogout}>Log out</button>
    </section>
  );
}
