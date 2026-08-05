import React, { useState } from "react";

const API = "http://localhost:8000";

interface Verdict {
  axis: string;
  stance: string;
  score: number;
}

interface AskResponse {
  figure: string;
  question: string;
  answer: string;
  source: string;
  verdicts: Verdict[];
  num_evidence_chunks: number;
}

const STANCE_COLOR: Record<string, string> = {
  anti: "#4caf82",
  pro: "#e05c5c",
  mixed: "#f0c040",
};

const AXIS_LABEL: Record<string, string> = {
  untouchability: "Untouchability",
  varna_hierarchy: "Varna Hierarchy",
  endogamy: "Endogamy",
  temple_entry: "Temple Entry",
  general_caste: "General Caste",
  communalism: "Muslim Relations",
  hindu_nationalism: "Hindu Nationalism",
};

const PRESET_QUESTIONS = [
  "What was this person's stance on the caste system?",
  "Did this person support or oppose untouchability?",
  "What did this person believe about the varna hierarchy?",
  "How did this person view inter-caste marriage?",
  "What evidence from their writings shows their caste stance?",
];

export default function AskPage() {
  const [figure, setFigure] = useState("");
  const [question, setQuestion] = useState(PRESET_QUESTIONS[0]);
  const [customQ, setCustomQ] = useState("");
  const [useCustom, setUseCustom] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeQuestion = useCustom ? customQ : question;

  async function handleAsk() {
    if (!figure.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ figure: figure.trim(), question: activeQuestion }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }
      setResult(await res.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 760, margin: "2rem auto", padding: "0 1rem", fontFamily: "sans-serif", color: "#ddd" }}>
      <h2 style={{ color: "#f0c040", marginBottom: "0.25rem" }}>Ask about a figure</h2>
      <p style={{ color: "#888", marginBottom: "1.5rem", fontSize: 14 }}>
        Enter a name and question. The answer is grounded in the figure's ingested writings plus
        computed stance scores. Richer answers require{" "}
        <code style={{ background: "#222", padding: "0 4px", borderRadius: 3 }}>ollama serve</code>{" "}
        to be running locally.
      </p>

      {/* Figure input */}
      <div style={{ marginBottom: "1rem" }}>
        <label style={{ display: "block", marginBottom: 6, color: "#aaa", fontSize: 13 }}>
          Historical figure (partial name OK)
        </label>
        <input
          value={figure}
          onChange={(e) => setFigure(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          placeholder="e.g. Ambedkar, Tilak, Savarkar…"
          style={{
            width: "100%", padding: "0.5rem 0.75rem", background: "#222",
            border: "1px solid #444", borderRadius: 6, color: "#eee", fontSize: 15,
            boxSizing: "border-box",
          }}
        />
      </div>

      {/* Preset questions */}
      <div style={{ marginBottom: "1rem" }}>
        <label style={{ display: "block", marginBottom: 6, color: "#aaa", fontSize: 13 }}>
          Question
        </label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {PRESET_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => { setUseCustom(false); setQuestion(q); }}
              style={{
                padding: "4px 10px", borderRadius: 4, fontSize: 12, cursor: "pointer",
                background: !useCustom && question === q ? "#f0c040" : "#2a2a2a",
                color: !useCustom && question === q ? "#111" : "#aaa",
                border: "1px solid #444",
              }}
            >
              {q}
            </button>
          ))}
          <button
            onClick={() => setUseCustom(true)}
            style={{
              padding: "4px 10px", borderRadius: 4, fontSize: 12, cursor: "pointer",
              background: useCustom ? "#f0c040" : "#2a2a2a",
              color: useCustom ? "#111" : "#aaa",
              border: "1px solid #444",
            }}
          >
            Custom…
          </button>
        </div>
        {useCustom && (
          <input
            value={customQ}
            onChange={(e) => setCustomQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAsk()}
            placeholder="Type your question…"
            autoFocus
            style={{
              width: "100%", padding: "0.5rem 0.75rem", background: "#222",
              border: "1px solid #444", borderRadius: 6, color: "#eee", fontSize: 15,
              boxSizing: "border-box",
            }}
          />
        )}
      </div>

      <button
        onClick={handleAsk}
        disabled={loading || !figure.trim() || !activeQuestion.trim()}
        style={{
          padding: "0.55rem 1.5rem", background: loading ? "#555" : "#f0c040",
          color: "#111", border: "none", borderRadius: 6, fontSize: 15,
          fontWeight: 600, cursor: loading ? "not-allowed" : "pointer",
        }}
      >
        {loading ? "Asking…" : "Ask"}
      </button>

      {error && (
        <div style={{ marginTop: "1.5rem", padding: "0.75rem 1rem", background: "#3a1a1a", borderRadius: 6, color: "#f88" }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ marginTop: "2rem" }}>
          {/* Figure name + source badge */}
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
            <h3 style={{ margin: 0, color: "#f0c040" }}>{result.figure}</h3>
            <span style={{
              fontSize: 11, padding: "2px 8px", borderRadius: 10,
              background: result.source === "fallback" ? "#444" : "#1a3a2a",
              color: result.source === "fallback" ? "#999" : "#6cf",
            }}>
              {result.source === "fallback" ? "verdict summary" : result.source}
            </span>
            <span style={{ fontSize: 11, color: "#666" }}>
              {result.num_evidence_chunks} evidence chunks
            </span>
          </div>

          {/* Answer box */}
          <div style={{
            background: "#1e1e1e", border: "1px solid #333", borderRadius: 8,
            padding: "1rem 1.25rem", marginBottom: "1.5rem",
            fontSize: 15, lineHeight: 1.7, color: "#ddd",
          }}>
            <div style={{ fontSize: 12, color: "#666", marginBottom: 8 }}>
              Q: {result.question}
            </div>
            {result.answer}
          </div>

          {/* Verdict chips */}
          {result.verdicts.length > 0 && (
            <div>
              <div style={{ fontSize: 12, color: "#666", marginBottom: 8 }}>Computed stances</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {result.verdicts.map((v) => (
                  <div
                    key={v.axis}
                    style={{
                      display: "flex", flexDirection: "column", alignItems: "center",
                      padding: "6px 14px", borderRadius: 6,
                      background: "#1e1e1e", border: `1px solid ${STANCE_COLOR[v.stance] ?? "#555"}`,
                      minWidth: 100,
                    }}
                  >
                    <span style={{ fontSize: 11, color: "#888", marginBottom: 2 }}>
                      {AXIS_LABEL[v.axis] ?? v.axis}
                    </span>
                    <span style={{ fontWeight: 700, color: STANCE_COLOR[v.stance] ?? "#ccc", fontSize: 13 }}>
                      {v.stance}
                    </span>
                    <span style={{ fontSize: 10, color: "#555", marginTop: 1 }}>
                      {v.score > 0 ? "+" : ""}{v.score.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
