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
      ] as const)
        tabs.append(tabButton(label, view === key, () => show(key)));
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
  // Paragraphs are matched inside section groups, so a full run also has a section level.
  // A paragraph-only run has one section group per run, which leaves nothing to compare.
  const sections =
    model.sections.length > 1
      ? {
          map: new PaperMapView(host, buildSectionMap(model.papers, model.sections), true),
          board: new GraphicalExplorer(
            host,
            buildSectionBoardModel(model.papers, model.sections),
            true,
          ),
        }
      : null;
  const paragraphLegend = element("#legend").textContent ?? "";
  const sectionLegends = {
    board:
      "Section matching: each row is a section role shared across papers, read top to bottom. Click a block to read its sections. Switch to Paragraphs to see the paragraph matches inside each section group.",
    map: "Section matching: select a section group to highlight its sections in every paper. Gray sections have no match. Switch to Paragraphs to see the paragraph matches inside each section group.",
  };
  let level: Level =
    sections && new URLSearchParams(location.search).get("level") === "sections"
      ? "sections"
      : "paragraphs";
  let view: View = "groups";
  let sectionView: "board" | "map" = "board";
  const labels: Record<View, string> = {
    groups: "Passage Groups",
    "paper-map": "Paper Map",
    "graphical-explorer": "Graphical Explorer",
  };
  const render = (): void => {
    explorer.destroy();
    paperMap.hideTooltip();
    sections?.board.destroy();
    sections?.map.hideTooltip();
    if (sections) {
      const url = new URL(location.href);
      if (level === "sections") url.searchParams.set("level", level);
      else url.searchParams.delete("level");
      history.replaceState(history.state, "", url);
      element("#levelTabs").replaceChildren(
        tabButton("Sections", level === "sections", () => {
          level = "sections";
          render();
        }),
        tabButton("Paragraphs", level === "paragraphs", () => {
          level = "paragraphs";
          render();
        }),
      );
      element("#levelControl").hidden = false;
    }
    const tabs = element("#granularityTabs");
    if (sections && level === "sections") {
      tabs.replaceChildren(
        ...(
          [
            ["board", "Graphical Explorer"],
            ["map", "Paper Map"],
          ] as const
        ).map(([key, label]) =>
          tabButton(label, sectionView === key, () => {
            sectionView = key;
            render();
          }),
        ),
      );
      element("#legend").textContent = sectionLegends[sectionView];
      if (sectionView === "board") sections.board.render();
      else sections.map.render();
      return;
    }
    tabs.replaceChildren(
      ...(Object.keys(labels) as View[]).map((key) =>
        tabButton(labels[key], view === key, () => switchView(key)),
      ),
    );
    element("#legend").textContent = paragraphLegend;
    if (view === "groups") groups.render();
    else if (view === "paper-map") paperMap.render();
    else explorer.render();
  };
  // The tutorial walks through the paragraph views.
  const switchView = (next: View): void => {
    level = "paragraphs";
    view = next;
    render();
  };
  render();
  mountTutorial(switchView, () => view);
  window.addEventListener("resize", () => {
    if (level === "sections" && sectionView === "map") sections?.map.resize();
    else if (level === "paragraphs" && view === "paper-map") paperMap.resize();
  });
}

type Level = "sections" | "paragraphs";

function tabButton(label: string, active: boolean, onClick: () => void): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "granularity-btn" + (active ? " active" : "");
  button.textContent = label;
  button.setAttribute("aria-pressed", String(active));
  button.addEventListener("click", onClick);
  return button;
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
