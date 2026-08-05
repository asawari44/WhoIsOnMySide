import React, { useEffect, useState } from "react";

const API = "/api";

export default function SanityDashboard() {
  const [result, setResult] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);

  async function runCheck() {
    setLoading(true);
    const data = await fetch(`${API}/sanity`).then((r) => r.json());
    setResult(data);
    setLoading(false);
  }

  useEffect(() => { runCheck(); }, []);

  const passStyle: React.CSSProperties = {
    background: "#1a3a1a",
    border: "1px solid #52c068",
    color: "#52c068",
    borderRadius: 8,
    padding: "0.5rem 1rem",
    fontWeight: 700,
    display: "inline-block",
    marginBottom: "1rem",
  };
  const failStyle: React.CSSProperties = {
    ...passStyle,
    background: "#3a1a1a",
    border: "1px solid #e05252",
    color: "#e05252",
  };
  const naStyle: React.CSSProperties = {
    ...passStyle,
    background: "#2a2a2a",
    border: "1px solid #666",
    color: "#888",
  };

  return (
    <div style={{ maxWidth: 640, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1.5rem" }}>
        <h1 style={{ fontSize: 22 }}>Sanity Check — Ambedkar</h1>
        <button
          onClick={runCheck}
          disabled={loading}
          style={{
            background: "#2a4a8a",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            padding: "6px 14px",
            cursor: "pointer",
            fontSize: 13,
          }}
        >
          {loading ? "Checking…" : "Refresh"}
        </button>
      </div>

      <p style={{ color: "#888", fontSize: 13, marginBottom: "1.5rem" }}>
        B.R. Ambedkar dedicated his life to dismantling the caste system and fighting for Dalit
        rights. Every axis should return <strong style={{ color: "#52c068" }}>ANTI</strong>. If
        any axis returns PRO or MIXED, the model has a problem.
      </p>

      {!result && <p style={{ color: "#666" }}>Loading…</p>}

      {result?.status === "no_data" && (
        <div style={{ background: "#1e1e1e", border: "1px solid #444", borderRadius: 8, padding: "1.5rem" }}>
          <p style={{ color: "#888" }}>
            Ambedkar has not been ingested yet. Run:
          </p>
          <pre
            style={{
              background: "#111",
              color: "#f0c040",
              borderRadius: 6,
              padding: "0.75rem 1rem",
              fontSize: 12,
              marginTop: "0.75rem",
              overflowX: "auto",
            }}
          >
{`cd ingest
python ingest.py \\
  --name "B.R. Ambedkar" \\
  --work "Annihilation of Caste" \\
  --url "https://en.wikisource.org/wiki/Annihilation_of_Caste"`}
          </pre>
          <p style={{ color: "#888", fontSize: 12, marginTop: "0.75rem" }}>
            Then click <strong>Refresh</strong> above, then use "Run LLM Predict" on the Figures page.
          </p>
        </div>
      )}

      {result && result.figure && (
        <>
          <div style={result.overall_pass ? passStyle : result.axes?.length > 0 ? failStyle : naStyle}>
            {result.axes?.length === 0
              ? "NO VERDICTS YET — run predictions first"
              : result.overall_pass
              ? "ALL AXES PASS"
              : "SANITY FAILURE — check highlighted axes"}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {(result.axes ?? []).map((ax: any) => (
              <div
                key={ax.axis}
                style={{
                  background: ax.pass ? "#1a2a1a" : "#2a1a1a",
                  border: `1px solid ${ax.pass ? "#52c068" : "#e05252"}`,
                  borderRadius: 8,
                  padding: "0.75rem 1rem",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <div>
                  <span style={{ fontWeight: 600 }}>
                    {ax.axis.replace(/_/g, " ")}
                  </span>
                  {ax.score != null && (
                    <span style={{ color: "#666", fontSize: 12, marginLeft: 8 }}>
                      (score: {ax.score.toFixed(3)})
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span
                    style={{
                      background: ax.pass ? "#52c068" : "#e05252",
                      color: "#000",
                      borderRadius: 4,
                      padding: "2px 10px",
                      fontWeight: 700,
                      fontSize: 12,
                      textTransform: "uppercase",
                    }}
                  >
                    {ax.stance}
                  </span>
                  <span style={{ fontSize: 18 }}>{ax.pass ? "✓" : "✗"}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
