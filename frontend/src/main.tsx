import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import FigureBrowser from "./pages/FigureBrowser";
import LabelingUI from "./pages/LabelingUI";
import SanityDashboard from "./pages/SanityDashboard";
import AskPage from "./pages/AskPage";

const NAV_STYLE: React.CSSProperties = {
  display: "flex",
  gap: "1.5rem",
  padding: "0.75rem 1.5rem",
  background: "#1a1a1a",
  borderBottom: "1px solid #333",
};

function App() {
  return (
    <BrowserRouter>
      <nav style={NAV_STYLE}>
        <strong style={{ marginRight: "1rem", color: "#f0c040" }}>WhoIsOnMySide</strong>
        {[
          { to: "/", label: "Figures" },
          { to: "/ask", label: "Ask" },
          { to: "/label", label: "Label" },
          { to: "/sanity", label: "Sanity Check" },
        ].map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end
            style={({ isActive }) => ({
              color: isActive ? "#f0c040" : "#aaa",
              fontWeight: isActive ? 600 : 400,
            })}
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route path="/" element={<FigureBrowser />} />
        <Route path="/figures/:id" element={<FigureBrowser />} />
        <Route path="/label" element={<LabelingUI />} />
        <Route path="/label/:figureId" element={<LabelingUI />} />
        <Route path="/ask" element={<AskPage />} />
        <Route path="/sanity" element={<SanityDashboard />} />
      </Routes>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
