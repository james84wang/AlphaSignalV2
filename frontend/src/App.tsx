import { useState } from "react";
import { Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { SymbolView } from "./pages/SymbolView";
import { Settings } from "./pages/Settings";
import { Backtest } from "./pages/Backtest";

export default function App() {
  const [universe, setUniverse] = useState("watchlist");

  return (
    <Layout universe={universe} onUniverseChange={setUniverse}>
      <Routes>
        <Route path="/" element={<Dashboard universe={universe} />} />
        <Route path="/symbol/:symbol" element={<SymbolView />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/backtest" element={<Backtest />} />
      </Routes>
    </Layout>
  );
}
