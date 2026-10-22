import {
  createSession,
  groupUnits,
  matchOutside,
  membership,
  workspace,
  type Level,
  type Source,
} from "./model";

export const PRACTICE_SOURCES: [Source, Source] = [
  {
    paper_id: "practice_a",
    title: "Paper A (practice)",
    filename: "practice-a.json",
    content: [
      {
        section_name: "Introduction",
        section_number: "1",
        paragraphs: [
          {
            paragraph_number: 0,
            text: "Reviewing many papers makes it difficult to compare their findings.",
          },
          {
            paragraph_number: 1,
            text: "Our study asks whether grouping evidence by its purpose helps readers.",
          },
        ],
        subsections: [],
      },
      {
        section_name: "Results",
        section_number: "2",
        paragraphs: [
          {
            paragraph_number: 0,
            text: "Readers located supporting evidence faster when passages were grouped.",
          },
        ],
        subsections: [],
      },
    ],
  },
  {
    paper_id: "practice_b",
    title: "Paper B (practice)",
    filename: "practice-b.json",
    content: [
      {
        section_name: "Introduction",
        section_number: "1",
        paragraphs: [
          {
            paragraph_number: 0,
            text: "Reading a large research corpus makes comparing findings difficult.",
          },
          {
            paragraph_number: 1,
            text: "We built a reader that organizes passages into shared groups.",
          },
        ],
        subsections: [],
      },
      {
        section_name: "Study design",
        section_number: "2",
        paragraphs: [
          {
            paragraph_number: 0,
            text: "The study tests whether organizing evidence by purpose helps readers.",
          },
        ],
        subsections: [],
      },
    ],
  },
];

const SECTIONS = ["practice_a:s0001", "practice_b:s0001"];
const PARAGRAPHS = ["practice_a:s0001.p0001", "practice_b:s0001.p0001"];
export const OUTSIDE_SOURCE = "practice_a:s0001.p0002";
export const OUTSIDE_TARGET = "practice_b:s0002.p0001";
const QUESTION = "Why is comparing papers difficult?";

export const TUTORIAL_STEPS = [
  {
    id: "documents",
    title: "Choose two documents",
    text: "Choose extracted JSON files or use the prepared HCI papers. Switch between sections and subsections when needed; each mode keeps separate labels. This tour uses two short practice papers and saves nothing.",
    targets: [".mm-documents"],
    next: "Show example",
  },
  {
    id: "select",
    title: "Select the sections that match",
    text: "These two Introduction sections play the same role. Their checkboxes are selected as an example. Select any number from either paper to form a group; each section belongs to exactly one group.",
    targets: SECTIONS.map((key) => `[data-key="${key}"]`),
    next: "Next",
  },
  {
    id: "question",
    title: "Create a group; questions are optional",
    text: "Group selected joins the selected passages. You may add a shared question, as shown here, or leave it blank. Individual passages also have an optional Add question control.",
    targets: [".mm-composer"],
    next: "Show grouped sections",
  },
  {
    id: "sections",
    title: "Open a group's paragraphs",
    text: "The sections now share a color and a group. Select a group to edit it, or separate selected passages. Undo reverses edits. Match paragraphs opens the passages inside this section group.",
    targets: [".mm-groups"],
    next: "Show paragraphs",
  },
  {
    id: "paragraphs",
    title: "Match paragraphs the same way",
    text: "Only paragraphs within the chosen section group appear here. These two paragraphs explain the same difficulty. Select counterparts, then use Group selected. Groups can contain multiple paragraphs from either paper.",
    targets: PARAGRAPHS.map((key) => `[data-key="${key}"]`),
    next: "Group these paragraphs",
  },
  {
    id: "outside",
    title: "A counterpart can be elsewhere",
    text: "This paragraph states the study's aim, but its counterpart is in the other paper's Study design section. Use Match outside this group on the paragraph to look beyond the current section group.",
    targets: [`[data-key="${OUTSIDE_SOURCE}"] [data-action="outside"]`],
    next: "Open the picker",
  },
  {
    id: "picker",
    title: "Pick the best outside paragraph",
    text: "The picker searches the other paper outside the current section group. This highlighted paragraph states the same aim. Choosing it joins the paragraphs' existing groups and records the outside-group match.",
    targets: [`[data-target="${OUTSIDE_TARGET}"]`],
    next: "Show the match",
  },
  {
    id: "save",
    title: "Save labels or open the viewer",
    text: "Real labels autosave in this browser. Save labels downloads a resumable JSON file. View in viewer previews your groups; Export viewer downloads a complete viewer ZIP. Finish clears this practice example and returns to document selection.",
    targets: ["[data-action=save]", "[data-action=preview]", "[data-action=export]"],
    next: "Finish tutorial",
  },
] as const;
export type TutorialStage = (typeof TUTORIAL_STEPS)[number]["id"];

// Every step is reproducible, so Back never depends on earlier practice edits.
export function practiceState(stage: TutorialStage) {
  const session = createSession(PRACTICE_SOURCES);
  const sectionPhase = ["documents", "select", "question"].includes(stage);
  if (!sectionPhase) groupUnits(session, "sections", SECTIONS, QUESTION);
  if (["outside", "picker", "save"].includes(stage))
    groupUnits(session, "paragraphs", PARAGRAPHS, QUESTION);
  if (stage === "save") matchOutside(session, OUTSIDE_SOURCE, OUTSIDE_TARGET);
  const level: Level = ["paragraphs", "outside", "picker", "save"].includes(stage)
    ? "paragraphs"
    : "sections";
  const selected =
    stage === "select" || stage === "question"
      ? SECTIONS
      : stage === "paragraphs"
        ? PARAGRAPHS
        : stage === "save"
          ? membership(workspace(session).paragraphs).get(OUTSIDE_SOURCE)!.members
          : [];
  return {
    session,
    level,
    selected,
    setup: stage === "documents",
    scope: membership(workspace(session).sections).get(SECTIONS[0])!.id,
    question: stage === "question" ? QUESTION : "",
    openPicker: stage === "picker",
  };
}

export class MatcherTutorial {
  private index = -1;
  private root = document.createElement("div");
  private frame = 0;
  private readonly reposition = (): void => this.refresh();
  private readonly escape = (event: KeyboardEvent): void => {
    if (this.active && event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this.finish();
    }
  };

  constructor(
    private show: (stage: TutorialStage) => void,
    private reset: () => void,
  ) {
    this.root.className = "mm-tour";
    this.root.innerHTML = `<svg class="mm-tour-shade" aria-hidden="true"><path fill-rule="evenodd" /></svg>
      <div class="mm-tour-highlights" aria-hidden="true"></div>
      <section class="tutorial-card mm-tour-card" role="region" aria-describedby="tourText" tabindex="-1">
        <div class="tutorial-card-top"><span class="tutorial-progress"></span><button class="tutorial-exit" data-tour="exit">Exit tutorial</button></div>
        <h2 id="tourTitle"></h2><p id="tourText"></p>
        <div class="tutorial-card-actions"><button class="tutorial-button" data-tour="back">Back</button><button class="tutorial-button primary" data-tour="next">Next</button></div>
      </section>`;
    this.root.addEventListener("click", (event) => {
      const action = (event.target as Element).closest<HTMLElement>("[data-tour]")?.dataset.tour;
      if (action === "exit") this.finish();
      if (action === "back" && this.index > 0) this.go(this.index - 1);
      if (action === "next") {
        if (this.index === TUTORIAL_STEPS.length - 1) this.finish();
        else this.go(this.index + 1);
      }
    });
  }

  get active(): boolean {
    return this.index >= 0;
  }

  start(): void {
    window.addEventListener("resize", this.reposition);
    document.addEventListener("scroll", this.reposition, true);
    document.addEventListener("keydown", this.escape, true);
    document.body.classList.add("mm-practice");
    this.go(0);
  }

  finish(): void {
    if (!this.active) return;
    this.index = -1;
    cancelAnimationFrame(this.frame);
    window.removeEventListener("resize", this.reposition);
    document.removeEventListener("scroll", this.reposition, true);
    document.removeEventListener("keydown", this.escape, true);
    this.root.remove();
    document.body.classList.remove("mm-practice");
    this.reset();
  }

  private go(index: number): void {
    // Detach before closing a native dialog so its focus restoration cannot hide the card.
    this.root.remove();
    this.index = index;
    const step = TUTORIAL_STEPS[index];
    this.show(step.id);
    this.root.querySelector(".tutorial-progress")!.textContent =
      `QUICK TOUR ${index + 1} / ${TUTORIAL_STEPS.length} - PRACTICE ONLY`;
    this.root.querySelector("#tourTitle")!.textContent = step.title;
    this.root.querySelector("#tourText")!.textContent = step.text;
    this.root.querySelector(".mm-tour-card")!.setAttribute("aria-label", step.title);
    const back = this.root.querySelector<HTMLButtonElement>("[data-tour=back]")!;
    back.disabled = index === 0;
    this.root.querySelector("[data-tour=next]")!.textContent = step.next;
    this.refresh();
    requestAnimationFrame(() => {
      if (!this.active || this.index !== index) return;
      const target = document.querySelector<HTMLElement>(step.targets[0]);
      const rect = target?.getBoundingClientRect();
      if (rect && (rect.top < 0 || rect.bottom > innerHeight))
        target!.scrollIntoView({ block: "center", behavior: "instant" });
      this.refresh();
      this.root.querySelector<HTMLElement>(".mm-tour-card")!.focus({ preventScroll: true });
    });
  }

  refresh(): void {
    if (!this.active) return;
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(() => this.position());
  }

  private position(): void {
    if (!this.active) return;
    // The picker is a native top-layer dialog. Its tutorial controls must live inside it.
    const host = document.querySelector<HTMLDialogElement>("#outsideDialog[open]") ?? document.body;
    if (this.root.parentElement !== host) host.append(this.root);
    const rects = TUTORIAL_STEPS[this.index].targets.flatMap((selector) => {
      const target = document.querySelector<HTMLElement>(selector);
      if (!target) return [];
      const rect = target.getBoundingClientRect();
      return rect.width && rect.height ? [rect] : [];
    });
    const width = innerWidth;
    const height = innerHeight;
    let path = `M0 0H${width}V${height}H0Z`;
    const boxes = rects.map((rect) => {
      const left = Math.max(4, rect.left - 5);
      const top = Math.max(4, rect.top - 5);
      const right = Math.min(width - 4, rect.right + 5);
      const bottom = Math.min(height - 4, rect.bottom + 5);
      if (right <= left || bottom <= top) return "";
      path += ` M${left} ${top}H${right}V${bottom}H${left}Z`;
      return `<div style="left:${left}px;top:${top}px;width:${right - left}px;height:${bottom - top}px"></div>`;
    });
    this.root.querySelector("path")!.setAttribute("d", path);
    this.root.querySelector(".mm-tour-highlights")!.innerHTML = boxes.join("");
    const card = this.root.querySelector<HTMLElement>(".mm-tour-card")!;
    const box = rects[0];
    const cardWidth = card.offsetWidth;
    const cardHeight = card.offsetHeight;
    const clamp = (value: number, max: number): number => Math.max(12, Math.min(value, max - 12));
    let left = box ? clamp(box.left, width - cardWidth) : (width - cardWidth) / 2;
    let top = box ? box.bottom + 18 : (height - cardHeight) / 2;
    if (box && top + cardHeight > height - 12) {
      if (box.top > cardHeight + 24) top = box.top - cardHeight - 18;
      else {
        left = clamp(box.right + 18, width - cardWidth);
        top = clamp(box.top, height - cardHeight);
      }
    }
    card.style.left = `${clamp(left, width - cardWidth)}px`;
    card.style.top = `${clamp(top, height - cardHeight)}px`;
    this.root.dataset.step = TUTORIAL_STEPS[this.index].id;
    this.root.setAttribute("aria-label", `Tutorial step ${this.index + 1}`);
  }
}
