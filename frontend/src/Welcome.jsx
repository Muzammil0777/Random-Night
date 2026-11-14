import { useEffect, useRef, useState } from "react";

// ---- install the app (PWA) ----
// Android/Chrome fires beforeinstallprompt (caught at load, before React mounts); iPhone needs Share -> Add to Home Screen.
let deferredInstall = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredInstall = e; });
const standalone = () => window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent);
const inAppBrowser = () => /instagram|fban|fbav|line\/|whatsapp/i.test(navigator.userAgent);

function useInstallPrompt() {
  const [canInstall, setCanInstall] = useState(Boolean(deferredInstall));
  useEffect(() => {
    const ready = () => setCanInstall(true);
    const done = () => setCanInstall(false);
    window.addEventListener("beforeinstallprompt", ready);
    window.addEventListener("appinstalled", done);
    return () => { window.removeEventListener("beforeinstallprompt", ready); window.removeEventListener("appinstalled", done); };
  }, []);
  async function install() {
    deferredInstall?.prompt();
    await deferredInstall?.userChoice;
    deferredInstall = null;
    setCanInstall(false);
  }
  return [canInstall, install];
}

export function InstallButton({ onHelp }) {
  const [canInstall, install] = useInstallPrompt();
  if (standalone()) return null;
  return (
    <button type="button" className="link" onClick={canInstall ? install : onHelp}>Install app</button>
  );
}

const ANDROID_STEPS = [
  <>Open this site in <strong>Chrome</strong>.</>,
  <>Tap <strong>Install app</strong> if it shows, or tap <strong>⋮</strong> (top right) → <strong>Add to Home screen</strong> → <strong>Install</strong>.</>,
  <>Open <strong>Random Night</strong> from your home screen. It runs full screen, like an app.</>,
];
const IPHONE_STEPS = [
  <>Open this site in <strong>Safari</strong>. From Instagram or WhatsApp, tap <strong>⋯</strong> → <strong>Open in browser</strong> first.</>,
  <>Tap <strong>Share</strong> (the square with an arrow) at the bottom.</>,
  <>Scroll down and tap <strong>Add to Home Screen</strong> → <strong>Add</strong>.</>,
];

// Step-by-step install help, opened on the phone type we detect.
export function InstallGuide() {
  const [canInstall, install] = useInstallPrompt();
  const [os, setOs] = useState(isIos() ? "iphone" : "android");
  if (standalone()) return <p className="ok">You're using the app. ✓</p>;
  const steps = os === "iphone" ? IPHONE_STEPS : ANDROID_STEPS;
  return (
    <div className="install">
      {canInstall && <button type="button" className="cta" onClick={install}>Install Random Night</button>}
      <div className="tabs" role="group" aria-label="Your phone">
        {[["android", "Android"], ["iphone", "iPhone"]].map(([id, label]) => (
          <button key={id} type="button" aria-pressed={os === id} className={os === id ? "tab on" : "tab"}
                  onClick={() => setOs(id)}>{label}</button>
        ))}
      </div>
      <ol className="steps">{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
      {inAppBrowser() && (
        <p className="note">You're inside another app's browser. Open this page in {os === "iphone" ? "Safari" : "Chrome"} to install it.</p>
      )}
    </div>
  );
}

// ---- welcome (task 13): shown once per device after the first sign-in, reopened from Help ----
export const WELCOMED_KEY = "rn_welcomed"; // just "seen the welcome" on this phone; not a login

const CARDS = [
  {
    title: "Welcome to Random Night",
    body: (
      <>
        <p className="lead">You pick the vibe. We plan the night.</p>
        <p>Tell us where in Hyderabad, your budget, how long and the vibe. We turn it into a timed night out with
          2–4 stops, prices upfront.</p>
        <p className="muted">Free for you. Venues pay us only when you check in, and they're always labelled.</p>
      </>
    ),
  },
  {
    title: "How a night works",
    body: (
      <ol className="steps">
        <li><strong>Pick four things:</strong> area, budget, how long, vibe.</li>
        <li><strong>Get your night:</strong> a timeline of stops with times and prices.</li>
        <li><strong>Book it:</strong> every stop gets its own 6-digit code.</li>
        <li><strong>Show the code at the door.</strong> Staff check you in; you pay the venue directly.</li>
      </ol>
    ),
  },
  {
    title: "Solo, with friends, or meet new people",
    body: (
      <>
        <p><strong>Random Friday:</strong> join by Thursday 11 PM and we match you into a group of 4–6 who picked the
          same area, vibe and budget. Women-only groups are an option.</p>
        <p><strong>You're in control:</strong> share your plan with someone you trust, SOS if you need help, and report or
          block anyone. Bars and clubs need 21+ and an ID check at the door.</p>
      </>
    ),
  },
  { title: "Put it on your home screen", body: <InstallGuide /> },
];

export function Welcome({ onDone }) {
  const [i, setI] = useState(0);
  const heading = useRef(null);
  const last = i === CARDS.length - 1;

  useEffect(() => { heading.current?.focus(); }, [i]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onDone();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDone]);

  return (
    <div className="welcome" role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <div className="welcome-card">
        <div className="welcome-top">
          <span className="muted small">{i + 1} of {CARDS.length}</span>
          <button type="button" className="link" onClick={onDone}>Skip</button>
        </div>
        <h1 id="welcome-title" ref={heading} tabIndex={-1}>{CARDS[i].title}</h1>
        <div className="welcome-body">{CARDS[i].body}</div>
        <div className="dots" aria-hidden="true">
          {CARDS.map((c, n) => <span key={c.title} className={n === i ? "dot on" : "dot"} />)}
        </div>
        <div className="welcome-nav">
          {i > 0 && <button type="button" className="cta ghost" onClick={() => setI(i - 1)}>Back</button>}
          <button type="button" className="cta" onClick={() => (last ? onDone() : setI(i + 1))}>
            {last ? "Let's plan a night" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
