// OWNER: Member 4
import { useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { checkHealth } from "./api";
import CitizenPage from "./pages/CitizenPage";
import HelperPage from "./pages/HelperPage";
import OfficerPage from "./pages/OfficerPage";
import AdminPage from "./pages/AdminPage";
import AuditorPage from "./pages/AuditorPage";

export default function App() {
  const [backend, setBackend] = useState("checking...");

  useEffect(() => {
    checkHealth()
      .then(() => setBackend("backend is running"))
      .catch(() => setBackend("backend is NOT reachable"));
  }, []);

  return (
    <div style={{ fontFamily: "sans-serif", padding: 16 }}>
      <h1>rasta</h1>
      <p><b>PROTOTYPE – not an official service.</b> ({backend})</p>
      <nav style={{ display: "flex", gap: 12 }}>
        <Link to="/">Citizen</Link>
        <Link to="/helper">Helper</Link>
        <Link to="/officer">Officer</Link>
        <Link to="/admin">Admin</Link>
        <Link to="/auditor">Auditor</Link>
      </nav>
      <hr />
      <Routes>
        <Route path="/" element={<CitizenPage />} />
        <Route path="/helper" element={<HelperPage />} />
        <Route path="/officer" element={<OfficerPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/auditor" element={<AuditorPage />} />
      </Routes>
    </div>
  );
}
