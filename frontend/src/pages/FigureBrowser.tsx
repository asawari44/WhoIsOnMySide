import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

const API = "/api";

const AXIS_LABELS: Record<string, string> = {
  untouchability: "Untouchability",
  varna_hierarchy: "Varna Hierarchy",
  endogamy: "Endogamy",
  temple_entry: "Temple Entry",
  general_caste: "Caste (General)",
  communalism: "Muslim Relations",
  hindu_nationalism: "Hindu Nationalism",
};

const STANCE_COLOR: Record<string, string> = {
  pro: "#e05252",
  anti: "#52c068",
  mixed: "#e0c040",
  unknown: "#666",
  not_about_caste: "#666",
};

function StanceBadge({ stance }: { stance: string }) {
  return (
    <span
      style={{
        background: STANCE_COLOR[stance] ?? "#444",
        color: "#000",
        borderRadius: 4,
        padding: "2px 8px",
        fontSize: 12,
        fontWeight: 700,
        textTransform: "uppercase",
      }}
    >
      {stance.replace(/_/g, " ")}
    </span>
  );
}

export default function FigureBrowser() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [figures, setFigures] = useState<any[]>([]);
  const [selected, setSelected] = useState<any | null>(null);
  const [chunks, setChunks] = useState<any[]>([]);
  const [page, setPage] = useState(0);
  const [predictingId, setPredictingId] = useState<number | null>(null);

  useEffect(() => {
    fetch(`${API}/figures`)
      .then((r) => r.json())
      .then(setFigures);
  }, []);

  useEffect(() => {
    if (!id) { setSelected(null); return; }
    fetch(`${API}/figures/${id}`)
      .then((r) => r.json())
      .then(setSelected);
  }, [id]);

  useEffect(() => {
    if (!id) return;
    fetch(`${API}/figures/${id}/chunks?page=${page}&per_page=15`)
      .then((r) => r.json())
      .then((d) => setChunks(d.chunks ?? []));
  }, [id, page]);

  async function runPredict(figureId: number, axis = "general_caste") {
    setPredictingId(figureId);
    await fetch(`${API}/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ axis }),
    });
    // refresh
    const updated = await fetch(`${API}/figures/${figureId}`).then((r) => r.json());
    setSelected(updated);
    setPredictingId(null);
  }

  const card: React.CSSProperties = {
    background: "#1e1e1e",
    border: "1px solid #333",
    borderRadius: 8,
    padding: "1rem",
    marginBottom: "0.75rem",
    cursor: "pointer",
  };

  return (
    <div style={{ display: "flex", height: "calc(100vh - 48px)" }}>
      {/* Sidebar */}
      <aside
        style={{
          width: 240,
          borderRight: "1px solid #333",
          overflowY: "auto",
          padding: "1rem",
        }}
      >
        <h2 style={{ marginBottom: "0.75rem", fontSize: 14, color: "#888" }}>FIGURES</h2>
        {figures.length === 0 && (
          <p style={{ color: "#666", fontSize: 13 }}>No figures yet — run the ingest script.</p>
        )}
        {figures.map((f) => (
          <div
            key={f.id}
            style={{
              ...card,
              border: String(f.id) === id ? "1px solid #7eb8f7" : card.border,
            }}
            onClick={() => navigate(`/figures/${f.id}`)}
          >
            <div style={{ fontWeight: 600 }}>{f.name}</div>
            <div style={{ fontSize: 12, color: "#666" }}>
              {f.birth_year ?? "?"} – {f.death_year ?? "present"}
            </div>
            {f.verdicts?.length > 0 && (
              <div style={{ marginTop: 6 }}>
                {f.verdicts.slice(0, 2).map((v: any) => (
                  <span key={v.axis} style={{ marginRight: 4 }}>
                    <StanceBadge stance={v.stance} />
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </aside>

      {/* Detail pane */}
      <main style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>
        {!selected ? (
          <p style={{ color: "#666" }}>Select a figure to see details.</p>
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1rem" }}>
              <h1 style={{ fontSize: 24 }}>{selected.name}</h1>
              <button
                onClick={() => runPredict(selected.id)}
                disabled={predictingId === selected.id}
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
                {predictingId === selected.id ? "Predicting…" : "Run LLM Predict"}
              </button>
            </div>

            {/* Verdicts */}
            {selected.verdicts?.length > 0 && (
              <section style={{ marginBottom: "1.5rem" }}>
                <h3 style={{ fontSize: 13, color: "#888", marginBottom: "0.5rem" }}>VERDICTS</h3>
                <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                  {selected.verdicts.map((v: any) => (
                    <div
                      key={v.axis}
                      style={{
                        background: "#1e1e1e",
                        border: "1px solid #333",
                        borderRadius: 8,
                        padding: "0.6rem 1rem",
                        minWidth: 140,
                      }}
                    >
                      <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>
                        {AXIS_LABELS[v.axis] ?? v.axis}
                      </div>
                      <StanceBadge stance={v.stance} />
                      {v.score != null && (
                        <div style={{ fontSize: 11, color: "#666", marginTop: 4 }}>
                          score: {v.score.toFixed(2)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Works */}
            {selected.works?.length > 0 && (
              <section style={{ marginBottom: "1.5rem" }}>
                <h3 style={{ fontSize: 13, color: "#888", marginBottom: "0.5rem" }}>WORKS</h3>
                {selected.works.map((w: any) => (
                  <div key={w.id} style={{ ...card, cursor: "default", marginBottom: "0.4rem" }}>
                    <span style={{ fontWeight: 500 }}>{w.title}</span>
                    {w.year_written && (
                      <span style={{ color: "#666", marginLeft: 8, fontSize: 12 }}>
                        ({w.year_written})
                      </span>
                    )}
                  </div>
                ))}
              </section>
            )}

            {/* Chunks */}
            <section>
              <h3 style={{ fontSize: 13, color: "#888", marginBottom: "0.5rem" }}>
                TEXT CHUNKS (page {page + 1})
              </h3>
              {chunks.map((ch: any) => (
                <div key={ch.id} style={{ ...card, cursor: "default" }}>
                  <div style={{ fontSize: 13, lineHeight: 1.6, color: "#ccc", marginBottom: 8 }}>
                    {ch.text_raw.slice(0, 400)}
                    {ch.text_raw.length > 400 && "…"}
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {ch.predictions?.map((p: any, i: number) => (
                      <span key={i} style={{ fontSize: 11, color: "#aaa" }}>
                        [{p.axis}] <StanceBadge stance={p.stance} /> ({p.speaker_role})
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  style={{ background: "#333", color: "#fff", border: "none", borderRadius: 4, padding: "6px 12px", cursor: "pointer" }}
                >
                  Prev
                </button>
                <button
                  onClick={() => setPage((p) => p + 1)}
                  disabled={chunks.length < 15}
                  style={{ background: "#333", color: "#fff", border: "none", borderRadius: 4, padding: "6px 12px", cursor: "pointer" }}
                >
                  Next
                </button>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
