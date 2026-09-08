import {
  descriptorSchema,
  manifestSchema,
  paperSchema,
  replaySchema,
  snapshotSchema,
  studySchema,
} from "./contracts";
import type { Replay, Routes } from "./contracts";
import { element } from "./dom";
import { buildModel } from "./model";
import { localDatasetBase } from "./local-runs";

export function participantRoute(id: string, routes: Routes): string {
  const match = /^([A-Z]{2})([0-9]{3})$/.exec(id);
  const route = match ? routes[match[1]] : undefined;
  if (!route) throw new Error("Enter the exact five-character participant ID provided to you.");
  return route.dataset_id;
}

async function readJson(path: string, base: URL): Promise<unknown> {
  const response = await fetch(new URL(path, base), { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load ${path} (${response.status})`);
  return response.json();
}

async function datasetBase(root: URL): Promise<URL> {
  const response = await fetch(new URL("study.json", root), { cache: "no-store" });
  if (response.status === 404) return root;
  if (!response.ok) throw new Error(`Could not load study.json (${response.status})`);
  const study = studySchema.parse(await response.json());
  const gate = element("#participantGate");
  const welcome = element("#tutorialWelcome");
  const form = element<HTMLFormElement>("#participantGateForm");
  const input = element<HTMLInputElement>("#participantIdInput");
  gate.hidden = false;
  welcome.hidden = true;
  input.focus();
  return new Promise((resolve) => {
    const submit = (event: SubmitEvent): void => {
      event.preventDefault();
      try {
        const id = participantRoute(input.value, study.datasets);
        form.removeEventListener("submit", submit);
        document.documentElement.dataset.participantId = input.value;
        gate.hidden = true;
        welcome.hidden = false;
        resolve(new URL(id + "/", root));
      } catch (error) {
        element("#participantGateError").textContent =
          error instanceof Error ? error.message : "Invalid participant ID";
      }
    };
    form.addEventListener("submit", submit);
  });
}

export async function loadDataset() {
  const base =
    (await localDatasetBase()) ?? (await datasetBase(new URL("./data/", window.location.href)));
  const descriptor = descriptorSchema.parse(await readJson("dataset.json", base));
  const manifest = manifestSchema.parse(await readJson("manifest.json", base));
  const papers = [];
  for (const entry of manifest) {
    const paper = paperSchema.parse(await readJson(entry.file, base));
    if (paper.paper_id !== entry.paper_id || paper.title !== entry.title)
      throw new Error("Manifest disagrees with paper");
    papers.push(paper);
  }
  const snapshot = snapshotSchema.parse(await readJson(descriptor.snapshot_file, base));
  const model = buildModel(papers, snapshot);
  if (
    descriptor.paper_count !== papers.length ||
    descriptor.paragraph_count !== model.paragraphs.size
  ) {
    throw new Error("Dataset counts disagree with contents");
  }
  let replay: Replay | null = null;
  if (descriptor.graph_replay_file) {
    replay = replaySchema.parse(await readJson(descriptor.graph_replay_file, base));
    if (
      JSON.stringify(replay.paper_order) !== JSON.stringify(papers.map((paper) => paper.paper_id))
    ) {
      throw new Error("Replay paper order disagrees with manifest");
    }
    if (replay.events.some((event, index) => event.sequence !== index + 1))
      throw new Error("Replay event sequence is not contiguous");
  }
  return { descriptor, model, replay };
}
