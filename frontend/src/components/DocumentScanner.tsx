import { useEffect, useRef, useState } from "react";
import { previewIdentityDocument, type DocumentPreview } from "../api";

type Details = { name: string; cnic: string; dob: string };

interface DocumentScannerProps {
  live?: boolean;
  citizenId?: string | null;
  onUseDetails: (details: Details, file?: File) => void;
  onEnterManually: () => void;
  initialValues?: Partial<Details>;
  title?: string;
  subtitle?: string;
}

const fields = [
  ["name", "Name", "name"],
  ["cnic", "Synthetic identity ID", "identity_number"],
  ["dob", "Date of birth", "date_of_birth"],
] as const;

export function DocumentScanner({
  live, citizenId, onUseDetails, onEnterManually, initialValues,
  title = "Preview identity photo",
  subtitle = "Choose a synthetic JPEG or PNG. You can review the suggested fields before using them.",
}: DocumentScannerProps) {
  const [file, setFile] = useState<File>();
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState<DocumentPreview>();
  const [values, setValues] = useState<Details>({
    name: initialValues?.name ?? "", cnic: initialValues?.cnic ?? "", dob: initialValues?.dob ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const pending = useRef<AbortController | null>(null);

  useEffect(() => () => pending.current?.abort(), []);

  const analyze = async () => {
    if (!file || !citizenId || !consent || pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setNotice("");
    try {
      const preview = await previewIdentityDocument(citizenId, file, controller.signal);
      if (controller.signal.aborted) return;
      setResult(preview);
      if (preview.quality_ok) {
        setValues((previous) => {
          const next = { ...previous };
          for (const [key, , source] of fields) {
            const value = preview.extracted_fields[source]?.value;
            if (value && (key !== "cnic" || value.startsWith("MOCK-"))) next[key] = value;
          }
          return next;
        });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setNotice(error instanceof Error ? error.message : "Preview unavailable. You can enter details manually.");
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      if (pending.current === controller) pending.current = null;
    }
  };

  return (
    <section className="doc-scanner-container panel">
      <h4>{title}</h4>
      <p>{subtitle}</p>
      <label>
        Identity photo
        <input type="file" accept="image/jpeg,image/png" capture="environment" disabled={busy}
          onChange={(event) => {
            const next = event.target.files?.[0];
            setResult(undefined);
            setValues({ name: initialValues?.name ?? "", cnic: initialValues?.cnic ?? "", dob: initialValues?.dob ?? "" });
            if (next && (next.size > 5 * 1024 * 1024 || !["image/jpeg", "image/png"].includes(next.type))) {
              setFile(undefined);
              setNotice("Choose a JPEG or PNG up to 5 MiB, or continue manually.");
              return;
            }
            setFile(next);
            setNotice("");
          }} />
      </label>
      {live && file && (
        <>
          <label className="consent-check">
            <input type="checkbox" checked={consent} disabled={busy}
              onChange={(event) => setConsent(event.target.checked)} />
            I authorize a local preview of this synthetic photo.
          </label>
          <button type="button" className="outline-button" onClick={analyze}
            disabled={busy || !consent || !citizenId}>
            {busy ? "Checking photo…" : "Check photo"}
          </button>
        </>
      )}
      {!live && <p>Browser demo. Enter the details manually.</p>}
      {notice && <p role="alert">{notice}</p>}
      {result && <p role="status">{result.quality_note ?? result.suggested_action}</p>}
      {result?.quality_ok && fields.map(([key, label, source]) => (
        <label key={key}>
          {label}
          <input value={values[key]} type={key === "dob" ? "date" : "text"}
            onChange={(event) => setValues((previous) => ({ ...previous, [key]: event.target.value }))} />
          {result.extracted_fields[source]?.warning && <small>{result.extracted_fields[source].warning}</small>}
        </label>
      ))}
      <div>
        {file && <button type="button" className="primary-button" disabled={busy}
          onClick={() => onUseDetails(result?.quality_ok ? values : { name: "", cnic: "", dob: "" }, file)}>
          {result?.quality_ok ? "Use details and attach photo" : "Attach photo and continue manually"}
        </button>}
        <button type="button" className="text-button" onClick={onEnterManually}>Enter manually</button>
      </div>
    </section>
  );
}
