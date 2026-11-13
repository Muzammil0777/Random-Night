import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import Staff from "./Staff.jsx";
import "./app.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    {window.location.pathname.startsWith("/venue") ? <Staff /> : <App />}
  </StrictMode>,
);
