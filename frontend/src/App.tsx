import { Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { SymbolView } from "./pages/SymbolView";
import { Settings } from "./pages/Settings";
import { Backtest } from "./pages/Backtest";
import { About } from "./pages/About";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/symbol/:symbol" element={<SymbolView />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </Layout>
  );
}
