import { element } from "./dom";

export type View = "groups" | "paper-map" | "graph-replay";
interface Step { view: View; target: string; title: string; body: string; openGroup?: boolean }
const STEPS: Step[] = [
  { view: "groups", target: "#granularityTabs", title: "Two ways to inspect the same graph", body: "Question Groups compares matching passages. Paper Map keeps each document in source order." },
  { view: "groups", target: ".group-card", title: "Questions summarize groups", body: "Each card represents a shared question. The colored squares show which documents contribute passages. Singletons are kept separately." },
  { view: "groups", target: ".group-detail-slot", title: "Check the actual evidence", body: "Open a group to compare source passages side by side. Generated questions are aids for reading, not proof that a match is correct.", openGroup: true },
  { view: "groups", target: ".expand-all-btn", title: "Read the full passages", body: "Use Expand all or the button below an individual passage to inspect the complete, unmodified text.", openGroup: true },
  { view: "groups", target: "#previewSlider", title: "Adjust previews", body: "The slider changes preview length only. Full source text is always available." },
  { view: "paper-map", target: ".paper-map-overview", title: "Select a question", body: "Hover to preview a group. Click a question or passage to pin its highlights across documents. Click again or Clear selection to unpin." },
  { view: "paper-map", target: ".paper-map-control-row", title: "Focus your reading", body: "After selecting a question, Hide unselected filters the passages. Sync paper scrolling links the columns by relative position. Singleton questions can be shown separately." },
  { view: "paper-map", target: ".paper-map-columns", title: "Keep the source context", body: "Each column retains the document's section and paragraph order. The graph is experimental: inspect the evidence and question incorrect correspondences." },
];

export function mountTutorial(switchView: (view: View) => void, currentView: () => View): void {
  let index = -1;
  let returnView: View = "groups";
  const layer = element("#tutorialLayer");
  const card = element("#tutorialCard");
  const close = (): void => {
    index = -1;
    layer.hidden = true;
    layer.setAttribute("aria-hidden", "true");
    switchView(returnView);
    element("#restartTutorial").focus();
  };
  const position = (): void => {
    if (index < 0) return;
    const target = document.querySelector<HTMLElement>(STEPS[index].target) ?? element("#stage");
    const bounds = target.getBoundingClientRect();
    const spotlight = element("#tutorialSpotlight");
    spotlight.style.cssText = `left:${Math.max(0, bounds.left - 4)}px;top:${Math.max(0, bounds.top - 4)}px;width:${bounds.width + 8}px;height:${Math.min(bounds.height + 8, innerHeight - bounds.top)}px`;
    card.style.left = Math.max(12, Math.min(bounds.left, innerWidth - card.offsetWidth - 12)) + "px";
    const below = bounds.bottom + 12;
    card.style.top = (below + card.offsetHeight < innerHeight ? below : Math.max(12, innerHeight - card.offsetHeight - 12)) + "px";
  };
  const show = (): void => {
    const step = STEPS[index];
    switchView(step.view);
    if (step.openGroup) {
      const button = document.querySelector<HTMLButtonElement>(".group-question");
      if (button?.getAttribute("aria-expanded") === "false") button.click();
    }
    layer.hidden = false;
    layer.setAttribute("aria-hidden", "false");
    element("#tutorialProgress").textContent = `Step ${index + 1} of ${STEPS.length}`;
    element("#tutorialStepTitle").textContent = step.title;
    element("#tutorialStepBody").textContent = step.body;
    element<HTMLButtonElement>("#tutorialPrevious").disabled = index === 0;
    element("#tutorialNext").textContent = index === STEPS.length - 1 ? "Finish" : "Next Step";
    requestAnimationFrame(position);
  };
  const start = (): void => {
    returnView = currentView();
    element("#tutorialWelcome").hidden = true;
    index = 0;
    show();
    element("#tutorialNext").focus();
  };
  element<HTMLButtonElement>("#startTutorialButton").disabled = false;
  element("#tutorialLoading").textContent = "Ready";
  element("#startTutorialButton").addEventListener("click", start);
  element("#restartTutorial").addEventListener("click", start);
  element("#tutorialExit").addEventListener("click", close);
  element("#tutorialNext").addEventListener("click", () => {
    if (index === STEPS.length - 1) close();
    else { index++; show(); }
  });
  element("#tutorialPrevious").addEventListener("click", () => { if (index > 0) { index--; show(); } });
  window.addEventListener("resize", position);
  window.addEventListener("scroll", position, { passive: true });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && index >= 0) close(); });
}
