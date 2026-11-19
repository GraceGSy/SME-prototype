import { loadDataset } from "./data";
import { element } from "./dom";
import { GroupsView } from "./groups";
import { PaperMapView } from "./paper-map";
import { buildSectionBoardModel, buildSectionMap } from "./model";
import { GraphicalExplorer } from "./explorer";
import { mountTutorial, type View } from "./tutorial";

element("#useToolButton").addEventListener("click", () => {
  element("#tutorialWelcome").hidden = true;
});

async function main(): Promise<void> {
  const dataset = await loadDataset();
  if (dataset.sectionsOnly) {
    const host = element("#stage");
    const map = new PaperMapView(host, buildSectionMap(dataset.papers, dataset.groups), true);
    const board = new GraphicalExplorer(
      host,
      buildSectionBoardModel(dataset.papers, dataset.groups),
      true,
    );
    document.title = "Section matches";
    element("#viewerTitle").textContent = "Section matches";
    element("#tutorialWelcome").hidden = true;
    element("#restartTutorial").hidden = true;
    const legends = {
      board:
        "Each row is a step in the shared structure, read top to bottom. Blocks nearer the center appear in more papers. Select a paper to trace its path; click a block to read its sections. Paragraph matching has not run for this revision.",
      map: "Select a section to highlight its match across papers. Gray sections have no accepted match. Paragraph matching has not run for this revision.",
    };
    let view: "board" | "map" = "board";
    const show = (next: "board" | "map"): void => {
      board.destroy();
      map.hideTooltip();
      view = next;
      element("#legend").textContent = legends[view];
      const tabs = element("#granularityTabs");
      tabs.replaceChildren();
      for (const [key, label] of [
        ["board", "Graphical Explorer"],
        ["map", "Paper Map"],
      ] as const) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "granularity-btn" + (view === key ? " active" : "");
        button.textContent = label;
        button.setAttribute("aria-pressed", String(view === key));
        button.addEventListener("click", () => show(key));
        tabs.append(button);
      }
      if (view === "board") board.render();
      else map.render();
    };
    show(view);
    window.addEventListener("resize", () => {
      if (view === "map") map.resize();
    });
    return;
  }
  const { descriptor, model } = dataset;
  document.title = descriptor.label;
  element("#viewerTitle").textContent = descriptor.label;
  document.documentElement.dataset.datasetId = descriptor.dataset_id;
  const host = element("#stage");
  const groups = new GroupsView(host, model);
  const paperMap = new PaperMapView(host, model);
  const explorer = new GraphicalExplorer(host, model);
  let view: View = "groups";
  const labels: Record<View, string> = {
    groups: "Passage Groups",
    "paper-map": "Paper Map",
    "graphical-explorer": "Graphical Explorer",
  };
  const switchView = (next: View): void => {
    explorer.destroy();
    paperMap.hideTooltip();
    view = next;
    const tabs = element("#granularityTabs");
    tabs.replaceChildren();
    for (const key of Object.keys(labels) as View[]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "granularity-btn" + (view === key ? " active" : "");
      button.textContent = labels[key];
      button.setAttribute("aria-pressed", String(view === key));
      button.addEventListener("click", () => switchView(key));
      tabs.append(button);
    }
    if (view === "groups") groups.render();
    else if (view === "paper-map") paperMap.render();
    else explorer.render();
  };
  switchView(view);
  mountTutorial(switchView, () => view);
  window.addEventListener("resize", () => {
    if (view === "paper-map") paperMap.resize();
  });
}

main().catch((error: unknown) => {
  element("#tutorialWelcome").hidden = true;
  element("#participantGate").hidden = true;
  const message = document.createElement("div");
  message.className = "empty-state";
  message.setAttribute("role", "alert");
  message.textContent =
    "Could not load viewer data: " + (error instanceof Error ? error.message : String(error));
  element("#stage").replaceChildren(message);
});
