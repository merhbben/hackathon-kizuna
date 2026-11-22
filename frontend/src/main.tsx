import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "leaflet/dist/leaflet.css";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";
import "./index.css";
import "./i18n";
import App from "./App";
import { AuthProvider } from "./lib/auth";
import { ReferenceProvider } from "./lib/reference";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ReferenceProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ReferenceProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
