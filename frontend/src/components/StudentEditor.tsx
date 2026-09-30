import { useState } from "react";
import "./StudentEditor.css";

interface IepService {
  service_type: string;
  sessions_per_week: number | null;
  minutes_per_session: number | null;
}

interface Props {
  student: any;
  setStudent: (student: any) => void;
  onSave: () => void | Promise<void>;
  onCancel: () => void;
  readOnly?: boolean;
}

const SERVICE_TYPES = [
  "OT",
  "PT",
  "Speech",
  "SETSS",
  "ICT",
  "Counseling",
];

export default function StudentEditor({
  student,
  setStudent,
  onSave,
  onCancel,
}: Props) {
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  if (!student) return null;

  function update(field: string, value: any) {
    setStudent({
      ...student,
      [field]: value,
    });
  }

  const iepServices: IepService[] = student.iep_services ?? [];

  function updateService(index: number, field: keyof IepService, value: any) {
    const next = iepServices.map((svc, i) =>
      i === index ? { ...svc, [field]: value } : svc
    );
    update("iep_services", next);
  }

  function addService() {
    const next = [
      ...iepServices,
      {
        service_type: SERVICE_TYPES[0],
        sessions_per_week: null,
        minutes_per_session: null,
      },
    ];
    update("iep_services", next);
  }

  function removeService(index: number) {
    const next = iepServices.filter((_, i) => i !== index);
    update("iep_services", next);
  }

  async function handleSave() {
    setSaveError(null);
    setIsSaving(true);
    try {
      await onSave();
    } catch (err) {
      console.error("Error saving student:", err);
      setSaveError(
        "Couldn't save this student. Double check Grade, MTSS Tier, and IEP service values are valid."
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="student-modal">
        <div className="modal-header">
          <h2>
            Edit Student
            {student.first_name || student.last_name
              ? `: ${student.first_name ?? ""} ${student.last_name ?? ""}`.trim()
              : ""}
          </h2>
          <button
            className="modal-close-btn"
            onClick={onCancel}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="modal-body">
          <fieldset className="field-group">
            <legend>Basic Info</legend>

            <div className="field-row">
              <label htmlFor="first_name">First Name</label>
              <input
                id="first_name"
                value={student.first_name ?? ""}
                onChange={(e) => update("first_name", e.target.value)}
              />
            </div>

            <div className="field-row">
              <label htmlFor="last_name">Last Name</label>
              <input
                id="last_name"
                value={student.last_name ?? ""}
                onChange={(e) => update("last_name", e.target.value)}
              />
            </div>

            <div className="field-row">
              <label htmlFor="grade">Grade</label>
              <input
                id="grade"
                placeholder="K, 1, 2, 3, 4, or 5"
                value={student.grade ?? ""}
                onChange={(e) => update("grade", e.target.value)}
              />
            </div>

            <div className="field-row">
              <label htmlFor="homeroom">Homeroom</label>
              <input
                id="homeroom"
                value={student.homeroom ?? ""}
                onChange={(e) => update("homeroom", e.target.value)}
              />
            </div>
          </fieldset>

          <fieldset className="field-group">
            <legend>MTSS / IEP</legend>

            <div className="field-row">
              <label htmlFor="mtss_tier">MTSS Tier</label>
              <select
                id="mtss_tier"
                value={student.mtss_tier ?? ""}
                onChange={(e) =>
                  update(
                    "mtss_tier",
                    e.target.value === "" ? null : Number(e.target.value)
                  )
                }
              >
                <option value="">— None —</option>
                <option value="1">Tier 1</option>
                <option value="2">Tier 2</option>
                <option value="3">Tier 3</option>
              </select>
            </div>

            <div className="field-row field-row-checkbox">
              <label htmlFor="has_iep">Has IEP</label>
              <input
                id="has_iep"
                type="checkbox"
                checked={!!student.has_iep}
                onChange={(e) => update("has_iep", e.target.checked)}
              />
            </div>
          </fieldset>

          {student.has_iep && (
            <fieldset className="field-group">
              <legend>IEP Services</legend>

              {iepServices.length === 0 && (
                <p className="iep-services-empty">
                  No mandated services added yet.
                </p>
              )}

              {iepServices.map((svc, index) => (
                <div className="iep-service-row" key={index}>
                  <div className="field-row">
                    <label htmlFor={`service_type_${index}`}>Service</label>
                    <select
                      id={`service_type_${index}`}
                      value={svc.service_type}
                      onChange={(e) =>
                        updateService(index, "service_type", e.target.value)
                      }
                    >
                      {SERVICE_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="field-row">
                    <label htmlFor={`sessions_per_week_${index}`}>
                      Sessions / Week
                    </label>
                    <input
                      id={`sessions_per_week_${index}`}
                      type="number"
                      min={0}
                      value={svc.sessions_per_week ?? ""}
                      onChange={(e) =>
                        updateService(
                          index,
                          "sessions_per_week",
                          e.target.value === "" ? null : Number(e.target.value)
                        )
                      }
                    />
                  </div>

                  <div className="field-row">
                    <label htmlFor={`minutes_per_session_${index}`}>
                      Minutes / Session
                    </label>
                    <input
                      id={`minutes_per_session_${index}`}
                      type="number"
                      min={0}
                      value={svc.minutes_per_session ?? ""}
                      onChange={(e) =>
                        updateService(
                          index,
                          "minutes_per_session",
                          e.target.value === "" ? null : Number(e.target.value)
                        )
                      }
                    />
                  </div>

                  <button
                    type="button"
                    className="remove-service-btn"
                    onClick={() => removeService(index)}
                    aria-label={`Remove ${svc.service_type} service`}
                  >
                    ✕
                  </button>
                </div>
              ))}

              <button
                type="button"
                className="add-service-btn"
                onClick={addService}
              >
                + Add Service
              </button>
            </fieldset>
          )}

          <fieldset className="field-group">
            <legend>ENL</legend>

            <div className="field-row">
              <label htmlFor="enl_level">ENL Level</label>
              <input
                id="enl_level"
                value={student.enl_level ?? ""}
                onChange={(e) => update("enl_level", e.target.value)}
              />
            </div>

            <div className="field-row">
              <label htmlFor="enl_minutes_required">
                ENL Minutes Required
              </label>
              <input
                id="enl_minutes_required"
                type="number"
                min={0}
                value={student.enl_minutes_required ?? ""}
                onChange={(e) =>
                  update(
                    "enl_minutes_required",
                    e.target.value === "" ? null : Number(e.target.value)
                  )
                }
              />
            </div>
          </fieldset>

          {saveError && <div className="modal-error">{saveError}</div>}
        </div>

        <div className="modal-footer">
          <button
            className="save-btn"
            onClick={handleSave}
            disabled={isSaving}
          >
            {isSaving ? "Saving…" : "Save"}
          </button>
          <button
            className="cancel-btn"
            onClick={onCancel}
            disabled={isSaving}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}