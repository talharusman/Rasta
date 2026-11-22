// OWNER: Member 4
// Voice input (speech-to-text) and read-aloud (text-to-speech) using the
// browser's built-in Web Speech API. Nothing is sent to RASTA servers, but the
// browser may send audio to its own speech service (Chrome/Edge use Google /
// Microsoft), which the UI discloses. Firefox has no speech input, so a typed
// fallback is shown. The recognised text is always displayed for confirmation.
import { useEffect, useRef, useState } from "react";

type Lang = "en" | "ur";

const LOCALES: Record<Lang, string> = { en: "en-US", ur: "ur-PK" };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SpeechRecognitionImpl: any =
  typeof window !== "undefined"
    ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    : undefined;

export const speechInputSupported = Boolean(SpeechRecognitionImpl);
export const speechOutputSupported = typeof window !== "undefined" && "speechSynthesis" in window;

/** Converts Urdu/Arabic-Indic digits to 0-9 and keeps only the digits. */
export function digitsFromSpeech(text: string): string {
  return text
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[^0-9]/g, "");
}

export function VoiceInputButton({
  lang,
  onText,
  numeric = false,
  label,
}: {
  lang: Lang;
  onText: (text: string) => void;
  numeric?: boolean;
  label: string;
}) {
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const [problem, setProblem] = useState("");
  const recognition = useRef<any>(null);

  useEffect(() => () => recognition.current?.abort?.(), []);

  if (!speechInputSupported) {
    return (
      <small style={{ display: "block", color: "#856c5e" }}>
        Voice input is not available in this browser. Please type, or use Chrome / Edge.
      </small>
    );
  }

  const start = () => {
    setProblem("");
    setHeard("");
    const rec = new SpeechRecognitionImpl();
    rec.lang = LOCALES[lang];
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (event: any) => {
      const text: string = event.results?.[0]?.[0]?.transcript ?? "";
      setHeard(text);
      if (numeric) {
        const digits = digitsFromSpeech(text);
        if (digits) onText(digits);
        else setProblem("No number was recognised. Please say the digits again or type them.");
      } else if (text.trim()) {
        onText(text.trim());
      }
    };
    rec.onerror = (event: any) => {
      setProblem(event.error === "not-allowed"
        ? "Microphone permission was denied. You can type instead."
        : "Could not hear clearly. Please try again or type.");
    };
    rec.onend = () => setListening(false);
    recognition.current = rec;
    setListening(true);
    rec.start();
  };

  return (
    <span style={{ display: "block", marginTop: 4 }}>
      <button
        type="button"
        className="secondary-button"
        onClick={listening ? () => recognition.current?.stop() : start}
        aria-label={`${listening ? "Stop listening" : "Speak"}: ${label}`}
        style={{ padding: "6px 12px", fontSize: 12 }}
      >
        {listening ? "● Listening… tap to stop" : `🎤 Speak (${lang === "ur" ? "اردو" : "English"})`}
      </button>
      <small style={{ display: "block", marginTop: 4, color: "#856c5e" }}>
        Your browser's speech service (e.g. Google in Chrome) turns speech into text. Do not say real ID numbers.
      </small>
      {heard && (
        <small style={{ display: "block", marginTop: 4 }} aria-live="polite">
          Heard: “{heard}” - check the box above and correct it if needed.
        </small>
      )}
      {problem && (
        <small style={{ display: "block", marginTop: 4, color: "#a3402b" }} role="alert">
          {problem}
        </small>
      )}
    </span>
  );
}

export function speak(text: string, lang: Lang) {
  if (!speechOutputSupported || !text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = LOCALES[lang];
  utterance.rate = 0.9;
  window.speechSynthesis.speak(utterance);
}

export function ReadAloudButton({ text, lang }: { text: string; lang: Lang }) {
  if (!speechOutputSupported || !text) return null;
  return (
    <button
      type="button"
      className="secondary-button"
      onClick={() => speak(text, lang)}
      aria-label="Read this aloud"
      style={{ padding: "6px 12px", fontSize: 12 }}
    >
      🔊 {lang === "ur" ? "سنیں" : "Read aloud"}
    </button>
  );
}
