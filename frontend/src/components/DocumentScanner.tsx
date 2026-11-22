import React, { useState, useRef } from "react";

export interface ExtractedDetails {
  name: string;
  cnic: string;
  dob: string;
  confidence: {
    name: number;
    cnic: number;
    dob: number;
  };
  uncertainFields: ("name" | "cnic" | "dob")[];
  isBlurry: boolean;
}

interface DocumentScannerProps {
  onUseDetails: (details: { name: string; cnic: string; dob: string }, file?: File) => void;
  onEnterManually: () => void;
  initialValues?: { name?: string; cnic?: string; dob?: string };
  title?: string;
  subtitle?: string;
}

/**
 * Deterministic document field extractor based on filename and type.
 * Simulates OCR extraction for both clear and imperfect documents.
 */
function extractFieldsFromDoc(file: File): ExtractedDetails {
  const fileName = (file.name || "").toLowerCase();

  // Blurry / unreadable condition
  if (
    fileName.includes("blurry") ||
    fileName.includes("unclear") ||
    fileName.includes("lowres") ||
    fileName.includes("dark") ||
    fileName.includes("bad")
  ) {
    return {
      name: "",
      cnic: "",
      dob: "",
      confidence: { name: 0.25, cnic: 0.2, dob: 0.15 },
      uncertainFields: ["name", "cnic", "dob"],
      isBlurry: true,
    };
  }

  // Low confidence / uncertain sample
  if (fileName.includes("low_conf") || fileName.includes("uncertain")) {
    return {
      name: "Fatima Noor",
      cnic: "42201-9876543-1",
      dob: "Unreadable",
      confidence: { name: 0.68, cnic: 0.72, dob: 0.38 },
      uncertainFields: ["name", "cnic", "dob"],
      isBlurry: false,
    };
  }

  // Tariq Khan test sample
  if (fileName.includes("tariq") || fileName.includes("khan")) {
    return {
      name: "Tariq Khan",
      cnic: "42101-1234567-3",
      dob: "1979-11-20",
      confidence: { name: 0.94, cnic: 0.92, dob: 0.69 },
      uncertainFields: ["dob"],
      isBlurry: false,
    };
  }

  // Default clean extraction (Ayesha Bibi)
  return {
    name: "Ayesha Bibi",
    cnic: "99999-0000001-1",
    dob: "1988-06-14",
    confidence: { name: 0.96, cnic: 0.94, dob: 0.91 },
    uncertainFields: [],
    isBlurry: false,
  };
}

export function DocumentScanner({
  onUseDetails,
  onEnterManually,
  initialValues,
  title = "Scan CNIC / Identity Document",
  subtitle = "Upload or photograph your National ID card or document for automated field extraction.",
}: DocumentScannerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [extracted, setExtracted] = useState<ExtractedDetails | null>(null);

  // Editable fields in preview
  const [previewName, setPreviewName] = useState(initialValues?.name || "");
  const [previewCnic, setPreviewCnic] = useState(initialValues?.cnic || "");
  const [previewDob, setPreviewDob] = useState(initialValues?.dob || "");

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    processFile(file);
  };

  const processFile = (file: File) => {
    setSelectedFile(file);
    setAnalyzing(true);
    setExtracted(null);

    // Realistic scanning delay (700ms)
    setTimeout(() => {
      const result = extractFieldsFromDoc(file);
      setExtracted(result);
      setPreviewName(result.name);
      setPreviewCnic(result.cnic);
      setPreviewDob(result.dob);
      setAnalyzing(false);
    }, 700);
  };

  const handleSimulate = (variant: "clear" | "blurry" | "uncertain") => {
    let name = "cnic_front.jpg";
    if (variant === "blurry") name = "blurry_scan.jpg";
    if (variant === "uncertain") name = "low_conf_id.jpg";
    const blob = new Blob(["fake-image-bytes"], { type: "image/jpeg" });
    const file = new File([blob], name, { type: "image/jpeg" });
    processFile(file);
  };

  const handleUseDetails = () => {
    onUseDetails(
      {
        name: previewName,
        cnic: previewCnic,
        dob: previewDob,
      },
      selectedFile || undefined
    );
  };

  const handleReset = () => {
    setSelectedFile(null);
    setExtracted(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="doc-scanner-container panel" style={{ marginTop: 12, marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div>
          <strong style={{ fontSize: 13, display: "block" }}>{title}</strong>
          <small style={{ color: "#806b5e", fontSize: 11 }}>{subtitle}</small>
        </div>
        <button
          type="button"
          className="text-button"
          onClick={onEnterManually}
          style={{ fontSize: 11, padding: "4px 8px" }}
        >
          Enter manually instead
        </button>
      </div>

      {/* File input (Camera capture / file chooser) */}
      <div style={{ marginTop: 14 }}>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,application/pdf"
          capture="environment"
          style={{ display: "none" }}
          id="scanner-doc-input"
          onChange={handleFileChange}
        />

        {!selectedFile && !analyzing && (
          <div className="scanner-dropzone">
            <label
              htmlFor="scanner-doc-input"
              className="primary-button"
              style={{ display: "inline-flex", alignItems: "center", gap: 8, cursor: "pointer" }}
            >
              <span>📷 Snap or Upload Document</span>
            </label>
            <p style={{ margin: "10px 0 0", fontSize: 11, color: "#806b5e" }}>
              Accepted formats: JPG, PNG, PDF. Fast AI field extraction.
            </p>

            {/* Quick Demo Test Buttons */}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12, justifyContent: "center" }}>
              <span style={{ fontSize: 10, color: "#8c6b55", alignSelf: "center" }}>Demo samples:</span>
              <button
                type="button"
                className="outline-button"
                style={{ fontSize: 10, padding: "4px 8px" }}
                onClick={() => handleSimulate("clear")}
              >
                Clear CNIC (Ayesha Bibi)
              </button>
              <button
                type="button"
                className="outline-button"
                style={{ fontSize: 10, padding: "4px 8px" }}
                onClick={() => handleSimulate("blurry")}
              >
                Blurry / Unreadable
              </button>
              <button
                type="button"
                className="outline-button"
                style={{ fontSize: 10, padding: "4px 8px" }}
                onClick={() => handleSimulate("uncertain")}
              >
                Uncertain Fields
              </button>
            </div>
          </div>
        )}

        {/* Analyzing state */}
        {analyzing && (
          <div
            className="scanner-analyzing"
            aria-live="polite"
            role="status"
            style={{
              padding: "24px 16px",
              textAlign: "center",
              background: "#faf6f0",
              borderRadius: 8,
              border: "1px dashed #c58a42",
            }}
          >
            <div className="spinner" style={{ margin: "0 auto 10px" }} />
            <strong style={{ fontSize: 13, color: "#543825" }}>Analyzing document…</strong>
            <p style={{ margin: "4px 0 0", fontSize: 11, color: "#806b5e" }}>
              Extracting identity fields, checking image clarity and document authenticity.
            </p>
          </div>
        )}

        {/* Blurry state */}
        {extracted?.isBlurry && !analyzing && (
          <div
            className="scanner-blurry-alert"
            role="alert"
            aria-live="assertive"
            style={{
              padding: 16,
              background: "#fef3f2",
              border: "1px solid #fecdca",
              borderRadius: 8,
              marginTop: 10,
            }}
          >
            <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <span style={{ fontSize: 18 }}>⚠️</span>
              <div>
                <strong style={{ display: "block", color: "#b42318", fontSize: 12 }}>
                  Image too blurry. Please retake in better lighting or enter fields manually. Your draft is saved.
                </strong>
                <p style={{ margin: "6px 0 12px", fontSize: 11, color: "#7a271a", lineHeight: 1.5 }}>
                  The automated camera scanner could not detect legible text. Ensure all four corners of the CNIC are
                  visible and avoid strong reflections.
                </p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <label
                    htmlFor="scanner-doc-input"
                    className="primary-button"
                    style={{ fontSize: 11, padding: "6px 12px", cursor: "pointer" }}
                  >
                    Retake Photo
                  </label>
                  <button
                    type="button"
                    className="secondary-button"
                    style={{ fontSize: 11, padding: "6px 12px" }}
                    onClick={onEnterManually}
                  >
                    Enter manually
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    style={{ fontSize: 11 }}
                    onClick={handleReset}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Extracted fields editable preview */}
        {extracted && !extracted.isBlurry && !analyzing && (
          <div
            className="scanner-preview"
            aria-live="polite"
            style={{
              background: "#fffdfa",
              border: "1px solid #d9cbbe",
              borderRadius: 8,
              padding: 16,
              marginTop: 10,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 12,
                borderBottom: "1px solid #eee5db",
                paddingBottom: 8,
              }}
            >
              <div>
                <strong style={{ fontSize: 12, color: "#351B13" }}>
                  ✅ Extracted Document Details
                </strong>
                <small style={{ display: "block", color: "#806b5e", fontSize: 10 }}>
                  Review and edit any field before applying to your application.
                </small>
              </div>
              <span style={{ fontSize: 10, background: "#edf7ed", color: "#1e4620", padding: "2px 8px", borderRadius: 4 }}>
                File: {selectedFile?.name}
              </span>
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              {/* Field: Name */}
              <div
                className={`scanner-field ${
                  extracted.uncertainFields.includes("name") ? "scanner-field--uncertain" : ""
                }`}
                style={{
                  padding: 8,
                  borderRadius: 6,
                  border: extracted.uncertainFields.includes("name")
                    ? "1px solid #e0aa3e"
                    : "1px solid transparent",
                  background: extracted.uncertainFields.includes("name") ? "#fefcf4" : "transparent",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <label htmlFor="preview-name" style={{ fontSize: 11, fontWeight: 600 }}>
                    Extracted Name
                  </label>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    {extracted.uncertainFields.includes("name") && (
                      <span style={{ color: "#925f18", fontSize: 10, fontWeight: 600 }}>
                        ⚠️ Low confidence — please verify
                      </span>
                    )}
                    <span
                      style={{
                        fontSize: 10,
                        padding: "1px 6px",
                        borderRadius: 4,
                        background: extracted.confidence.name >= 0.85 ? "#eaf5ec" : "#fef3c7",
                        color: extracted.confidence.name >= 0.85 ? "#246132" : "#92400e",
                      }}
                    >
                      {Math.round(extracted.confidence.name * 100)}% match
                    </span>
                  </div>
                </div>
                <input
                  id="preview-name"
                  value={previewName}
                  onChange={(e) => setPreviewName(e.target.value)}
                  style={{ width: "100%", padding: 8, fontSize: 12, borderRadius: 5, border: "1px solid #d9cdbf" }}
                />
              </div>

              {/* Field: CNIC */}
              <div
                className={`scanner-field ${
                  extracted.uncertainFields.includes("cnic") ? "scanner-field--uncertain" : ""
                }`}
                style={{
                  padding: 8,
                  borderRadius: 6,
                  border: extracted.uncertainFields.includes("cnic")
                    ? "1px solid #e0aa3e"
                    : "1px solid transparent",
                  background: extracted.uncertainFields.includes("cnic") ? "#fefcf4" : "transparent",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <label htmlFor="preview-cnic" style={{ fontSize: 11, fontWeight: 600 }}>
                    Extracted CNIC
                  </label>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    {extracted.uncertainFields.includes("cnic") && (
                      <span style={{ color: "#925f18", fontSize: 10, fontWeight: 600 }}>
                        ⚠️ Low confidence — please verify
                      </span>
                    )}
                    <span
                      style={{
                        fontSize: 10,
                        padding: "1px 6px",
                        borderRadius: 4,
                        background: extracted.confidence.cnic >= 0.85 ? "#eaf5ec" : "#fef3c7",
                        color: extracted.confidence.cnic >= 0.85 ? "#246132" : "#92400e",
                      }}
                    >
                      {Math.round(extracted.confidence.cnic * 100)}% match
                    </span>
                  </div>
                </div>
                <input
                  id="preview-cnic"
                  value={previewCnic}
                  onChange={(e) => setPreviewCnic(e.target.value)}
                  style={{ width: "100%", padding: 8, fontSize: 12, borderRadius: 5, border: "1px solid #d9cdbf" }}
                />
              </div>

              {/* Field: DOB */}
              <div
                className={`scanner-field ${
                  extracted.uncertainFields.includes("dob") ? "scanner-field--uncertain" : ""
                }`}
                style={{
                  padding: 8,
                  borderRadius: 6,
                  border: extracted.uncertainFields.includes("dob")
                    ? "1px solid #e0aa3e"
                    : "1px solid transparent",
                  background: extracted.uncertainFields.includes("dob") ? "#fefcf4" : "transparent",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <label htmlFor="preview-dob" style={{ fontSize: 11, fontWeight: 600 }}>
                    Extracted Date of Birth (DOB)
                  </label>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    {extracted.uncertainFields.includes("dob") && (
                      <span style={{ color: "#925f18", fontSize: 10, fontWeight: 600 }}>
                        ⚠️ Low confidence / Unreadable — please verify
                      </span>
                    )}
                    <span
                      style={{
                        fontSize: 10,
                        padding: "1px 6px",
                        borderRadius: 4,
                        background: extracted.confidence.dob >= 0.85 ? "#eaf5ec" : "#fef3c7",
                        color: extracted.confidence.dob >= 0.85 ? "#246132" : "#92400e",
                      }}
                    >
                      {Math.round(extracted.confidence.dob * 100)}% match
                    </span>
                  </div>
                </div>
                <input
                  id="preview-dob"
                  value={previewDob}
                  onChange={(e) => setPreviewDob(e.target.value)}
                  placeholder="YYYY-MM-DD"
                  style={{ width: "100%", padding: 8, fontSize: 12, borderRadius: 5, border: "1px solid #d9cdbf" }}
                />
              </div>
            </div>

            {/* Actions: Use these details / Enter manually */}
            <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
              <button
                type="button"
                className="primary-button"
                onClick={handleUseDetails}
                style={{ flex: 1, justifyContent: "center" }}
              >
                Use these details
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={onEnterManually}
                style={{ flex: 1, justifyContent: "center" }}
              >
                Enter manually
              </button>
              <button
                type="button"
                className="text-button"
                onClick={handleReset}
                title="Discard and rescan"
                style={{ fontSize: 11 }}
              >
                Rescan
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
