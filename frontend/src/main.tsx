import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./lib/queryClient";
import App from "./App";
import "./index.css";

declare const __BUILD_TIME__: string;
// Logged so the build timestamp is visible in the browser console — also
// ensures __BUILD_TIME__ is included in the bundle, changing the content
// hash on every rebuild so browsers never serve a stale cached bundle.
console.debug("[AlphaSignal] build", __BUILD_TIME__);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>
);
