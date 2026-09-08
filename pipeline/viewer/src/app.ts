import { loadDataset } from "./data";
import { element } from "./dom";
import { GroupsView } from "./groups";
import { PaperMapView } from "./paper-map";
import { GraphicalExplorer } from "./explorer";
import { mountTutorial, type View } from "./tutorial";

element("#useToolButton").addEventListener("click", () => {
  element("#tutorialWelcome").hidden = true;
});

async function main(): Promise<void> {
  const { descriptor, model } = await loadDataset();
  document.title = descriptor.label;
  element("#viewerTitle").textContent = descriptor.label;
  document.documentElement.dataset.datasetId = descriptor.dataset_id;
  const host = element("#stage");
  const groups = new GroupsView(host, model);
  const paperMap = new PaperMapView(host, model);
  const explorer = new GraphicalExplorer(host, model);
  let view: View = "groups";
  const labels: Record<View, string> = {
    groups: "Question Groups",
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
