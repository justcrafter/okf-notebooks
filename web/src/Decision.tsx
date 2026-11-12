import { useState } from "react";
import { api } from "./api";
import { useT } from "./i18n";

export function Decision({ notebook, onDecided }: { notebook: string; onDecided: (approved: boolean) => void }) {
  const t = useT();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async (approved: boolean) => {
    if (!window.confirm(approved ? t.confirmApprove : t.confirmReject)) return;
    setBusy(true);
    setErr(null);
    try {
      if (approved) await api.approve(notebook);
      else await api.reject(notebook, reason.trim());
      onDecided(approved);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="decision">
      <button className="primary" disabled={busy} onClick={() => void run(true)}>{t.approve}</button>
      <input
        aria-label={t.rejectReason}
        placeholder={t.rejectReason}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <button className="danger" disabled={busy || !reason.trim()} onClick={() => void run(false)}>{t.reject}</button>
      {err && <p className="error" role="alert">{err}</p>}
    </div>
  );
}
