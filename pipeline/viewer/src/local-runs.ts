import { z } from "zod";

const catalogSchema = z.array(
  z.strictObject({
    id: z.string().regex(/^[A-Za-z0-9_-]+$/),
    label: z.string().min(1),
    revisions: z.array(z.string().regex(/^revision-[0-9]{4,}$/)).min(1),
  }),
);

export async function localDatasetBase(): Promise<URL | null> {
  const response = await fetch("./local.json", { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Could not load runs (${response.status})`);
  const runs = catalogSchema.parse(await response.json());
  if (!runs.length)
    throw new Error("No completed run revisions found. Refresh after a run completes.");
  const params = new URLSearchParams(location.search);
  const runId = params.get("run") ?? runs[0].id;
  const run = runs.find((entry) => entry.id === runId);
  if (!run) throw new Error("Unknown run");
  const selectedRevision = params.get("revision") ?? "latest";
  const revision =
    selectedRevision === "latest" ? run.revisions[run.revisions.length - 1] : selectedRevision;
  if (!run.revisions.includes(revision)) throw new Error("Unknown or unfinished revision");
  const form = document.createElement("form");
  form.className = "local-runs";
  const runSelect = document.createElement("select");
  runSelect.setAttribute("aria-label", "Run");
  runSelect.name = "run";
  runs.forEach((entry) => runSelect.add(new Option(entry.label, entry.id)));
  runSelect.value = runId;
  const revisionSelect = document.createElement("select");
  revisionSelect.setAttribute("aria-label", "Revision");
  revisionSelect.name = "revision";
  revisionSelect.add(new Option("Latest completed", "latest"));
  run.revisions.forEach((id) => revisionSelect.add(new Option(id, id)));
  revisionSelect.value = selectedRevision;
  runSelect.addEventListener("change", () => {
    location.search = new URLSearchParams({ run: runSelect.value, revision: "latest" }).toString();
  });
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "Load / Refresh";
  form.append(runSelect, revisionSelect, button);
  document.querySelector("header")!.after(form);
  // Resolve latest once so every file in this load belongs to the same snapshot.
  return new URL(`/runs/${run.id}/${revision}/`, location.href);
}
