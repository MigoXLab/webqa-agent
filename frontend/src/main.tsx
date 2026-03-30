import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.tsx";
import "./index.css";

// Polyfill for crypto.randomUUID() for environments that don't support it
if (!crypto.randomUUID) {
  crypto.randomUUID = function randomUUID() {
    return (
      '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (c: any) =>
        (+c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> +c / 4).toString(16)
      )
    );
  };
}

createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>
);
