import React, { useCallback, useEffect, useState } from "react";

const API = "/api";

const AXES = ["untouchability", "varna_hierarchy", "endogamy", "temple_entry", "general_caste"];
const STANCES = ["pro", "anti", "mixed", "not_about_caste"];
const ROLES = ["author_asserted", "quoted_other", "describing", "ambiguous"];

const AXIS_HELP: Record<string, string> = {
  untouchability: "Mentions of untouchables / Dalits and discrimination against them",
  varna_hierarchy: "Four-varna ordering (Brahmin/Kshatriya/Vaishya/Shudra) as divinely ordained",
  endogamy: "Restriction on inter-caste marriage",
  temple_entry: "Right of lower-caste people to enter Hindu temples",
  general_caste: "Caste system overall",
};

const STANCE_COLOR: Record<string, string> = {
  pro: "#e05252",
  anti: "#52c068",
  mixed: "#e0c040",
  not_about_caste: "#555",
};

export default function LabelingUI() {
  const [figures, setFigures] = useState<any[]>([]);
  const [selectedFigure, setSelectedFigure] = useState<number | null>(null);
  const [chunks, setChunks] = useState<any[]>([]);
  const [chunkIdx, setChunkIdx] = useState(0);
  const [page, setPage] = useState(0);

  const [axis, setAxis] = useState("general_caste");
  const [stance, setStance] = useState<string | null>(null);
  const [role, setRole] = useState("author_asserted");
  const [confidence, setConfidence] = useState(1.0);
  const [notes, setNotes] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${API}/figures`).then((r) => r.json()).then(setFigures);
  }, []);

  useEffect(() => {
    if (!selectedFigure) return;
    fetch(`${API}/figures/${selectedFigure}/chunks?page=${page}&per_page=20`)
      .then((r) => r.json())
      .then((d) => {
        setChunks(d.chunks ?? []);
        setChunkIdx(0);
      });
  }, [selectedFigure, page]);

  const currentChunk = chunks[chunkIdx] ?? null;

  const saveAnnotation = useCallback(async () => {
    if (!currentChunk || !stance) return;
    await fetch(`${API}/annotations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chunk_id: currentChunk.id,
        speaker_role: role,
        axis,
        stance,
        confidence,
        notes,
      }),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 1200);
    // Advance to next chunk
    if (chunkIdx < chunks.length - 1) {
      setChunkIdx((i) => i + 1);
    }
    setStance(null);
    setNotes("");
  }, [currentChunk, stance, role, axis, confidence, notes, chunkIdx, chunks.length]);

  const btn = (label: string, value: string, current: string | null, color: string, setter: (v: string) => void) => (
    <button
      key={value}
      onClick={() => setter(value)}
      style={{
        background: current === value ? color : "#2a2a2a",
        color: current === value ? "#000" : "#ccc",
        border: `1px solid ${current === value ? color : "#444"}`,
        borderRadius: 6,
        padding: "6px 14px",
        cursor: "pointer",
        fontWeight: current === value ? 700 : 400,
        fontSize: 13,
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ display: "flex", height: "calc(100vh - 48px)" }}>
      {/* Config sidebar */}
      <aside style={{ width: 260, borderRight: "1px solid #333", padding: "1rem", overflowY: "auto" }}>
        <h2 style={{ fontSize: 13, color: "#888", marginBottom: "0.75rem" }}>FIGURE</h2>
        <select
          value={selectedFigure ?? ""}
          onChange={(e) => { setSelectedFigure(Number(e.target.value)); setPage(0); }}
          style={{ width: "100%", background: "#222", color: "#eee", border: "1px solid #444", borderRadius: 6, padding: 8, marginBottom: "1rem" }}
        >
          <option value="">-- select --</option>
          {figures.map((f) => (
            <option key={f.id} value={f.id}>{f.name}</option>
          ))}
        </select>

        <h2 style={{ fontSize: 13, color: "#888", marginBottom: "0.5rem" }}>AXIS</h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: "1rem" }}>
          {AXES.map((a) => (
            <button
              key={a}
              onClick={() => setAxis(a)}
              title={AXIS_HELP[a]}
              style={{
                background: axis === a ? "#2a4a8a" : "#1e1e1e",
                color: axis === a ? "#fff" : "#aaa",
                border: `1px solid ${axis === a ? "#7eb8f7" : "#333"}`,
                borderRadius: 6, padding: "6px 10px",
                cursor: "pointer", textAlign: "left", fontSize: 12,
              }}
            >
              {a.replace(/_/g, " ")}
            </button>
          ))}
        </div>

        <div style={{ fontSize: 12, color: "#666", fontStyle: "italic" }}>
          {AXIS_HELP[axis]}
        </div>
      </aside>

      {/* Main labeling area */}
      <main style={{ flex: 1, display: "flex", flexDirection: "column", padding: "1.5rem", overflowY: "auto" }}>
        {!currentChunk ? (
          <p style={{ color: "#666" }}>
            {selectedFigure ? "No more chunks on this page." : "Select a figure to start labeling."}
          </p>
        ) : (
          <>
            <div style={{ fontSize: 12, color: "#666", marginBottom: "0.5rem" }}>
              Chunk {chunkIdx + 1} / {chunks.length} &nbsp;·&nbsp; {currentChunk.work_title}
            </div>

            {/* Text display */}
            <div
              style={{
                background: "#1a1a1a",
                border: "1px solid #333",
                borderRadius: 8,
                padding: "1rem",
                lineHeight: 1.8,
                fontSize: 14,
                color: "#ddd",
                flex: "0 0 auto",
                maxHeight: "40vh",
                overflowY: "auto",
                marginBottom: "1.25rem",
                whiteSpace: "pre-wrap",
              }}
            >
              {currentChunk.text_raw}
            </div>

            {/* Existing labels */}
            {currentChunk.annotations?.length > 0 && (
              <div style={{ marginBottom: "1rem", fontSize: 12, color: "#888" }}>
                Existing labels:{" "}
                {currentChunk.annotations.map((a: any) => (
                  <span key={a.axis} style={{ marginRight: 6, color: STANCE_COLOR[a.stance] ?? "#aaa" }}>
                    [{a.axis}] {a.stance}
                  </span>
                ))}
              </div>
            )}

            {/* Speaker role */}
            <div style={{ marginBottom: "1rem" }}>
              <div style={{ fontSize: 12, color: "#888", marginBottom: 6 }}>SPEAKER ROLE</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {ROLES.map((r) => btn(r.replace(/_/g, " "), r, role, "#7eb8f7", setRole))}
              </div>
            </div>

            {/* Stance */}
            <div style={{ marginBottom: "1rem" }}>
              <div style={{ fontSize: 12, color: "#888", marginBottom: 6 }}>STANCE on {axis.replace(/_/g, " ")}</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {STANCES.map((s) =>
                  btn(s.replace(/_/g, " "), s, stance, STANCE_COLOR[s] ?? "#aaa", setStance)
                )}
              </div>
            </div>

            {/* Confidence */}
            <div style={{ marginBottom: "1rem" }}>
              <label style={{ fontSize: 12, color: "#888" }}>
                CONFIDENCE: {confidence.toFixed(1)}
              </label>
              <input
                type="range" min={0} max={1} step={0.1}
                value={confidence}
                onChange={(e) => setConfidence(Number(e.target.value))}
                style={{ display: "block", width: "100%", marginTop: 4 }}
              />
            </div>

            {/* Notes */}
            <textarea
              placeholder="Notes (optional)"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              style={{
                width: "100%", background: "#1e1e1e", color: "#ccc",
                border: "1px solid #444", borderRadius: 6, padding: 8,
                fontSize: 13, resize: "vertical", minHeight: 60, marginBottom: "1rem",
              }}
            />

            {/* Actions */}
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
              <button
                onClick={saveAnnotation}
                disabled={!stance}
                style={{
                  background: stance ? "#2a6a2a" : "#1e1e1e",
                  color: "#fff", border: "none", borderRadius: 6,
                  padding: "8px 20px", cursor: stance ? "pointer" : "not-allowed",
                  fontWeight: 600, fontSize: 14,
                }}
              >
                Save &amp; Next
              </button>
              <button
                onClick={() => setChunkIdx((i) => Math.min(i + 1, chunks.length - 1))}
                style={{ background: "#2a2a2a", color: "#ccc", border: "1px solid #444", borderRadius: 6, padding: "8px 14px", cursor: "pointer" }}
              >
                Skip
              </button>
              {saved && <span style={{ color: "#52c068", fontSize: 13 }}>Saved!</span>}
            </div>

            {/* Page navigation */}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1.5rem" }}>
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                style={{ background: "#333", color: "#fff", border: "none", borderRadius: 4, padding: "6px 12px", cursor: "pointer" }}
              >
                Prev page
              </button>
              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={chunks.length < 20}
                style={{ background: "#333", color: "#fff", border: "none", borderRadius: 4, padding: "6px 12px", cursor: "pointer" }}
              >
                Next page
              </button>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
