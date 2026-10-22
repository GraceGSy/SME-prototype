import { parseSession, type Session } from "./model";

const STORAGE_KEY = "question-atlas-manual-v1";
export const PREVIEW_KEY = "question-atlas-manual-preview-v1";

export function readSaved(): Session | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw ? parseSession(JSON.parse(raw)) : null;
}

export function saveSession(session: Session): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function download(filename: string, data: BlobPart, type: string): void {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
