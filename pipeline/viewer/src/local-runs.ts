import { z } from "zod";

const catalogSchema = z.array(
  z.strictObject({
    id: z.string().regex(/^[A-Za-z0-9_-]+$/),
    label: z.string().min(1),
    revisions: z.array(z.string().regex(/^revision-[0-9]{4,}$/)).min(1),
    sectionRevisions: z.array(z.string()).optional(),
    collection: z.string().min(1).optional(),
    revisionLabels: z.record(z.string(), z.string()).optional(),
    sourceTextRevisions: z.array(z.string()).optional(),
  }),
);

export async function localDatasetBase() {
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
  if (document.documentElement.hasAttribute("data-public-catalog")) {
    const legend = document.querySelector<HTMLElement>("#legend");
    if (legend)
      legend.textContent = run.sourceTextRevisions?.includes(revision)
        ? "This run includes the original Reuters paragraphs alongside the passage labels and matches."
        : "This run shows passage labels and group memberships without the source passages.";
  }
  const form = document.createElement("form");
  form.className = "local-runs";
  const runSelect = document.createElement("select");
  runSelect.setAttribute("aria-label", "Run");
  runSelect.name = "run";
  const collections = new Map<string, HTMLOptGroupElement>();
  for (const entry of runs) {
    const option = new Option(entry.label, entry.id);
    if (!entry.collection) {
      runSelect.add(option);
      continue;
    }
    let group = collections.get(entry.collection);
    if (!group) {
      group = document.createElement("optgroup");
      group.label = entry.collection;
      collections.set(entry.collection, group);
      runSelect.append(group);
    }
    group.append(option);
  }
  runSelect.value = runId;
  const revisionSelect = document.createElement("select");
  revisionSelect.setAttribute("aria-label", "Revision");
  revisionSelect.name = "revision";
  for (const id of [...run.revisions].reverse()) {
    const label =
      run.revisionLabels?.[id] ??
      `Revision ${Number(id.split("-")[1])}${run.sectionRevisions?.includes(id) ? " (sections only)" : ""}`;
    revisionSelect.add(new Option(label, id));
  }
  revisionSelect.value = revision;
  runSelect.addEventListener("change", () => {
    location.search = new URLSearchParams({ run: runSelect.value, revision: "latest" }).toString();
  });
  revisionSelect.addEventListener("change", () => {
    location.search = new URLSearchParams({
      run: runId,
      revision: revisionSelect.value,
    }).toString();
  });
  function labeled(name: string, select: HTMLSelectElement): HTMLLabelElement {
    const label = document.createElement("label");
    label.append(name, select);
    return label;
  }
  form.append(labeled("Run", runSelect));
  if (!document.documentElement.hasAttribute("data-public-catalog")) {
    const trace = document.createElement("a");
    trace.href = "/trace?" + new URLSearchParams({ run: run.id, revision });
    trace.textContent = "Trace this run";
    form.append(trace);
  }
  if (run.revisions.length > 1) form.append(labeled("Snapshot", revisionSelect));
  document.querySelector("header")!.after(form);
  // Resolve latest once so every file in this load belongs to the same snapshot.
  return {
    base: new URL(`/runs/${run.id}/${revision}/`, location.href),
    sectionsOnly: run.sectionRevisions?.includes(revision),
  };
}
