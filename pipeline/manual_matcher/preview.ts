import { element } from "../viewer/src/dom";
import { GroupsView } from "../viewer/src/groups";
import { PaperMapView } from "../viewer/src/paper-map";
import { GraphicalExplorer } from "../viewer/src/explorer";
import { buildModel } from "../viewer/src/model";
import { exportDataset, parseSession } from "./model";
import { PREVIEW_KEY } from "./storage";

try {
  const raw = localStorage.getItem(PREVIEW_KEY);
  if (!raw) throw new Error("Open a label set in the matcher, then choose View in viewer.");
  const { papers, snapshot, descriptor } = exportDataset(parseSession(JSON.parse(raw)));
  const model = buildModel(papers, snapshot);
  element("#viewerTitle").textContent = descriptor.label;
  const host = element("#stage");
  const groups = new GroupsView(host, model);
  const paperMap = new PaperMapView(host, model);
  const explorer = new GraphicalExplorer(host, model);
  const labels = ["Question Groups", "Paper Map", "Graphical Explorer"];
  let active = 0;
  const render = (index: number): void => {
    active = index;
    explorer.destroy();
    paperMap.hideTooltip();
    const tabs = element("#granularityTabs");
    tabs.replaceChildren();
    labels.forEach((label, i) => {
      const button = document.createElement("button");
      button.className = "granularity-btn" + (i === index ? " active" : "");
      button.textContent = label;
      button.setAttribute("aria-pressed", String(i === index));
      button.addEventListener("click", () => render(i));
      tabs.append(button);
    });
    if (index === 0) groups.render();
    else if (index === 1) paperMap.render();
    else explorer.render();
  };
  window.addEventListener("resize", () => {
    if (active === 1) paperMap.resize();
  });
  render(0);
} catch (error) {
  const message = document.createElement("p");
  message.className = "empty-state";
  message.setAttribute("role", "alert");
  message.textContent = error instanceof Error ? error.message : String(error);
  element("#stage").replaceChildren(message);
}
