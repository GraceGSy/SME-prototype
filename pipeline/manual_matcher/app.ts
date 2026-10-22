import { strToU8, zipSync } from "fflate";
import { element, escapeHtml as html } from "../viewer/src/dom";
import { PAPER_COLORS } from "../viewer/src/model";
import {
  createSession,
  datasetFiles,
  documentSchema,
  groupUnits,
  matchOutside,
  membership,
  parseSession,
  ungroupUnits,
  units,
  workspace,
  type AnnotationGroup,
  type Level,
  type Mode,
  type Session,
  type Source,
  type Unit,
} from "./model";
import { download, PREVIEW_KEY, readSaved, saveSession } from "./storage";
import {
  MatcherTutorial,
  OUTSIDE_SOURCE,
  PRACTICE_SOURCES,
  practiceState,
  type TutorialStage,
} from "./tutorial";

interface Sample {
  paper_id: string;
  title: string;
  filename: string;
  url: string;
}
let samples: Sample[] = [];
let session: Session | null = null;
let setup = true;
let setupMode: Mode = "section";
let level: Level = "sections";
let scope = "";
let query = "";
let selected = new Set<string>();
let groupQuestion = "";
let outsideSource = "";
let savedMessage = "Saved in this browser";
const uploaded: [Source | null, Source | null] = [null, null];
const choices = ["abstractexplorer", "corpusstudio"];
const undo: string[] = [];
const redo: string[] = [];
let noticeTimer: ReturnType<typeof setTimeout>;
let beforeTutorial: Session | null = null;
const tutorial = new MatcherTutorial(showTutorialStep, resetTutorial);

const button = (label: string, action: string, primary = false, extra = ""): string =>
  `<button type="button" class="tutorial-button${primary ? " primary" : ""}" data-action="${action}" ${extra}>${label}</button>`;
const current = (): Session => {
  if (!session) throw new Error("Choose two documents first");
  return session;
};
function announce(message: string, error = false): void {
  const notice = element("#announcement");
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(
    () => {
      notice.hidden = true;
    },
    error ? 12_000 : 4500,
  );
}
const message = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

function persist(): void {
  if (tutorial.active) {
    const status = document.querySelector("#saveStatus");
    if (status) status.textContent = "Practice only - not saved";
    return;
  }
  try {
    saveSession(current());
    savedMessage = "Saved in this browser";
  } catch {
    savedMessage = "Browser save unavailable. Download labels.";
  }
  const status = document.querySelector("#saveStatus");
  if (status) status.textContent = savedMessage;
}

function commit(change: () => void, renderAfter = true): void {
  const before = JSON.stringify(current());
  try {
    change();
    parseSession(current());
    undo.push(before);
    if (undo.length > 40) undo.shift();
    redo.length = 0;
    persist();
    if (renderAfter) render();
    else {
      element<HTMLButtonElement>('[data-action="undo"]').disabled = false;
      element<HTMLButtonElement>('[data-action="redo"]').disabled = true;
    }
  } catch (error) {
    session = parseSession(JSON.parse(before));
    announce(message(error), true);
  }
}

function modes(mode: Mode): string {
  return `<div class="mm-mode"><span>Match</span><div class="mm-segment">${(
    ["section", "subsection"] as const
  )
    .map(
      (value) =>
        `<button class="granularity-btn${mode === value ? " active" : ""}" type="button" data-action="mode" data-mode="${value}" aria-pressed="${mode === value}" ${tutorial.active ? "disabled" : ""}>${value === "section" ? "Sections" : "Sections + subsections"}</button>`,
    )
    .join("")}</div></div>`;
}

function renderSetup(): string {
  return `<main class="mm-setup">
    <h2>Choose two documents</h2>
    <p class="mm-intro">Match sections first, then the paragraphs within them. Select passages from either paper to create a group.</p>
    <div class="mm-documents">${[0, 1]
      .map(
        (index) => `<section class="mm-document" style="--paper:${PAPER_COLORS[index]}">
      <label for="document${index}">Document ${index + 1}</label>
      <select id="document${index}" data-document="${index}" aria-label="Document ${index + 1}" ${tutorial.active ? "disabled" : ""}>
        ${samples.map((sample) => `<option value="${html(sample.paper_id)}" ${choices[index] === sample.paper_id ? "selected" : ""}>${html(sample.title)}</option>`).join("")}
        ${uploaded[index] ? `<option value="uploaded" ${choices[index] === "uploaded" ? "selected" : ""}>${html(uploaded[index]!.title)} (uploaded)</option>` : ""}
      </select>
      <label class="tutorial-button mm-upload" for="file${index}">Choose extracted JSON</label>
      <input type="file" id="file${index}" data-upload="${index}" accept=".json,application/json" ${tutorial.active ? "disabled" : ""} hidden />
      <p class="mm-file-name">${choices[index] === "uploaded" ? html(uploaded[index]!.filename) : "Or use one of the five prepared HCI papers."}</p>
    </section>`,
      )
      .join("")}</div>
    <div class="mm-setup-options">${modes(setupMode)}${button("Start matching", "start", true, tutorial.active ? "disabled" : "")}</div>
    <p class="mm-footnote">Each granularity keeps its own labels. You can switch without losing work.</p>
    <div class="mm-setup-footer">${button("Open saved labels", "open", false, tutorial.active ? "disabled" : "")}${session && !tutorial.active ? button("Resume current labels", "resume") : ""}<span class="mm-footnote">${tutorial.active ? "Practice example only. No labels are saved." : "Manual only. Uploaded files stay in your browser."}</span></div>
  </main>`;
}

function groupName(group: AnnotationGroup, index: number): string {
  return group.question || `Group ${index + 1}`;
}

function groupStyle(group: AnnotationGroup, groups: AnnotationGroup[]): string {
  if (group.members.length === 1) return "--group-color:#adb5bd;--group-fill:#fff";
  const index = groups.filter((g) => g.members.length > 1).findIndex((g) => g.id === group.id);
  const color = PAPER_COLORS[index % PAPER_COLORS.length];
  return `--group-color:${color};--group-fill:color-mix(in srgb, ${color} 5%, white)`;
}

function scopeLabel(group: AnnotationGroup): string {
  const s = current();
  const lookup = new Map(units(s, "sections").map((unit) => [unit.key, unit]));
  return (
    group.question ||
    group.members
      .map((key) => {
        const unit = lookup.get(key)!;
        return `${s.sources.find((source) => source.paper_id === unit.paper)!.title}: ${unit.title}`;
      })
      .join(" / ")
  );
}

function inScope(unit: Unit): boolean {
  if (level === "sections") return true;
  const group = workspace(current()).sections.find((g) => g.id === scope);
  return !!group?.members.includes(`${unit.paper}:${unit.section}`);
}

function unitCard(
  unit: Unit,
  groups: AnnotationGroup[],
  memberMap: Map<string, AnnotationGroup>,
): string {
  const s = current();
  const ws = workspace(s);
  const group = memberMap.get(unit.key)!;
  const index = groups.filter((g) => g.members.length > 1).indexOf(group);
  const questionText = ws.questions[unit.key] ?? unit.question;
  const marked = ws.outside.some((flag) => flag.source === unit.key || flag.target === unit.key);
  const section = units(s, "sections").find((u) => u.key === `${unit.paper}:${unit.section}`);
  return `<article class="mm-unit${selected.has(unit.key) ? " selected" : ""}${unit.kind === "subsection" ? " subsection" : ""}" data-key="${html(unit.key)}" style="${groupStyle(group, groups)}">
    <label class="mm-pick"><input type="checkbox" data-pick="${html(unit.key)}" ${selected.has(unit.key) ? "checked" : ""} /><span class="mm-unit-title">${html(unit.title)}</span></label>
    <div class="mm-unit-meta"><span>${html(unit.kind === "paragraph" ? (section?.title ?? unit.section) : unit.kind)}</span>
      ${group.members.length > 1 ? `<button class="mm-group-link" data-action="edit" data-group="${html(group.id)}">${html(groupName(group, index))} &middot; ${group.members.length} passages</button>` : "<span>Separate</span>"}
    </div>
    ${unit.kind === "paragraph" && !inScope(unit) ? '<div class="mm-outside-mark">Outside the current section group</div>' : ""}
    ${unit.kind === "paragraph" ? `<p class="mm-passage">${html(unit.text)}</p>` : `<details class="mm-section-detail" data-detail="${html(unit.key)}"><summary>Read section (${unit.text.split(/\s+/).length} words)</summary><p class="mm-passage">${html(unit.text)}</p></details>`}
    <details class="mm-question-detail" data-detail="question-${html(unit.key)}"><summary>${questionText ? "Edit question" : "Add question (optional)"}</summary><textarea data-unit-question="${html(unit.key)}" aria-label="Question for ${html(unit.title)}">${html(questionText)}</textarea></details>
    ${unit.kind === "paragraph" ? `<button class="mm-text-button mm-outside" data-action="outside" data-unit="${html(unit.key)}">Match outside this group</button>` : ""}
    ${marked ? '<div class="mm-outside-mark">Outside-group match recorded</div>' : ""}
  </article>`;
}

function renderWorkspace(): string {
  const s = current();
  const ws = workspace(s);
  if (!ws.sections.some((group) => group.id === scope))
    scope = ws.sections.find((g) => g.members.length > 1)?.id ?? ws.sections[0]?.id ?? "";
  const allUnits = units(s, level);
  const groups = ws[level];
  const memberMap = membership(groups);
  const visible = allUnits.filter(
    (unit) =>
      (inScope(unit) || selected.has(unit.key)) &&
      (!query ||
        `${unit.title} ${unit.text} ${ws.questions[unit.key] ?? unit.question}`
          .toLowerCase()
          .includes(query.toLowerCase())),
  );
  const activeGroups = groups.filter(
    (group) =>
      group.members.length > 1 &&
      group.members.some((key) => allUnits.some((unit) => unit.key === key && inScope(unit))),
  );
  const counts = s.sources.map(
    (source) => [...selected].filter((key) => key.startsWith(source.paper_id + ":")).length,
  );
  return `<nav class="mm-toolbar" aria-label="Matching steps">
    <button class="mm-step${level === "sections" ? " active" : ""}" data-action="step" data-level="sections" aria-pressed="${level === "sections"}"><span>1</span>Sections</button>
    <button class="mm-step${level === "paragraphs" ? " active" : ""}" data-action="step" data-level="paragraphs" aria-pressed="${level === "paragraphs"}"><span>2</span>Paragraphs</button>
    ${modes(s.mode)}<span id="saveStatus" class="mm-saved">${tutorial.active ? "Practice only - not saved" : html(savedMessage)}</span>
  </nav>
  <main class="mm-workspace">
    <div class="mm-context">${level === "sections" ? "<p>Select sections from either paper, then group them.</p>" : `<label for="scope">Within</label><select id="scope" aria-label="Section group">${ws.sections.map((group) => `<option value="${html(group.id)}" ${scope === group.id ? "selected" : ""}>${html(scopeLabel(group))}</option>`).join("")}</select>`}
      <input class="mm-search" id="search" type="search" placeholder="Find text in this view" aria-label="Find text in this view" value="${html(query)}" />
    </div>
    <div class="mm-layout"><div class="mm-papers">${s.sources
      .map((source, index) => {
        const sourceUnits = visible.filter((unit) => unit.paper === source.paper_id);
        return `<section class="mm-paper" style="--paper:${PAPER_COLORS[index]}" aria-label="${html(source.title)}">
        <div class="mm-paper-head"><h2>${html(source.title)}</h2><span>${sourceUnits.length} passages</span></div>
        <div class="mm-unit-list" data-scroll="paper-${index}">${sourceUnits.map((unit) => unitCard(unit, groups, memberMap)).join("") || '<p class="mm-empty">No passages in this view.</p>'}</div>
      </section>`;
      })
      .join("")}</div>
    <aside class="mm-sidebar">
      <section class="mm-composer"><h2>${selected.size ? `${selected.size} selected` : "Create a group"}</h2>
        <p>${selected.size ? `${counts[0]} from the first paper &middot; ${counts[1]} from the second` : "Select one or more passages. Each passage stays in exactly one group."}</p>
        <label for="groupQuestion">Shared question (optional)</label>
        <textarea id="groupQuestion" placeholder="What do these passages answer together?">${html(groupQuestion)}</textarea>
        ${button("Group selected", "group", true, selected.size ? "" : "disabled")}
        <div class="mm-selection-actions"><button class="mm-text-button" data-action="clear">Clear selection</button><button class="mm-text-button" data-action="ungroup" ${selected.size ? "" : "disabled"}>Separate selected</button></div>
        <div class="mm-history"><button class="mm-text-button" data-action="undo" ${undo.length ? "" : "disabled"}>Undo</button><button class="mm-text-button" data-action="redo" ${redo.length ? "" : "disabled"}>Redo</button></div>
      </section>
      <section class="mm-groups"><h2>Groups <span class="mm-footnote">${activeGroups.length}</span></h2>
        <div class="mm-group-list" data-scroll="groups">${
          activeGroups
            .map(
              (group) => `<div class="mm-group-item" style="${groupStyle(group, groups)}">
          <button data-action="edit" data-group="${html(group.id)}">${html(groupName(group, groups.filter((g) => g.members.length > 1).indexOf(group)))}</button>
          <small>${s.sources.map((source) => `${group.members.filter((key) => key.startsWith(source.paper_id + ":")).length}`).join(" + ")} passages</small>
          ${level === "sections" ? `<button class="mm-text-button" data-action="paragraphs" data-group="${html(group.id)}">Match paragraphs</button>` : ""}
        </div>`,
            )
            .join("") || '<p class="mm-empty">Your groups will appear here.</p>'
        }</div>
      </section>
      ${level === "sections" ? button("Continue to paragraphs", "continue") : '<p class="mm-footnote">Use Match outside this group to choose a paragraph elsewhere in the other paper.</p>'}
    </aside></div>
  </main>`;
}

function render(): void {
  const scrolls = [...document.querySelectorAll<HTMLElement>("[data-scroll]")].map(
    (el) => [el.dataset.scroll!, el.scrollTop] as const,
  );
  const opened = new Set(
    [...document.querySelectorAll<HTMLDetailsElement>("details[open][data-detail]")].map(
      (el) => el.dataset.detail,
    ),
  );
  const focus =
    document.activeElement instanceof HTMLInputElement
      ? {
          id: document.activeElement.id,
          start: document.activeElement.selectionStart,
          end: document.activeElement.selectionEnd,
        }
      : null;
  element("#matcher").innerHTML =
    `<header><div class="mm-brand"><h1>Question Atlas</h1><span>${tutorial.active ? "Tutorial - practice only" : "Manual matcher"}</span></div>
    <div class="mm-actions">${!setup && session ? `${button("Documents", "documents", false, tutorial.active ? "disabled" : "")}${button("Open labels", "open", false, tutorial.active ? "disabled" : "")}${button("Save labels", "save", false, tutorial.active ? "disabled" : "")}${button("View in viewer", "preview", false, tutorial.active ? "disabled" : "")}${button("Export viewer", "export", true, tutorial.active ? "disabled" : "")}` : ""}${button(tutorial.active ? "Exit tutorial" : "Tutorial", "tutorial")}</div></header>
    ${setup ? renderSetup() : renderWorkspace()}`;
  for (const el of document.querySelectorAll<HTMLElement>("[data-scroll]"))
    el.scrollTop = scrolls.find(([key]) => key === el.dataset.scroll)?.[1] ?? 0;
  for (const el of document.querySelectorAll<HTMLDetailsElement>("details[data-detail]"))
    el.open = opened.has(el.dataset.detail);
  if (focus?.id) {
    const input = document.getElementById(focus.id) as HTMLInputElement | null;
    input?.focus({ preventScroll: true });
    if (input && focus.start !== null && focus.end !== null)
      input.setSelectionRange(focus.start, focus.end);
  }
  tutorial.refresh();
}

function showTutorialStep(stage: TutorialStage): void {
  const dialog = element<HTMLDialogElement>("#outsideDialog");
  dialog.close();
  dialog.replaceChildren();
  const practice = practiceState(stage);
  session = practice.session;
  setup = practice.setup;
  setupMode = "section";
  level = practice.level;
  scope = practice.scope;
  selected = new Set(practice.selected);
  groupQuestion = practice.question;
  query = "";
  outsideSource = "";
  undo.length = 0;
  redo.length = 0;
  for (const el of document.querySelectorAll<HTMLElement>("[data-scroll]")) el.scrollTop = 0;
  for (const el of document.querySelectorAll<HTMLDetailsElement>("details[open]")) el.open = false;
  window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  render();
  if (practice.openPicker) showOutside(OUTSIDE_SOURCE);
}

function resetTutorial(): void {
  const dialog = element<HTMLDialogElement>("#outsideDialog");
  dialog.close();
  dialog.replaceChildren();
  session = beforeTutorial;
  beforeTutorial = null;
  setup = true;
  setupMode = "section";
  level = "sections";
  scope = "";
  query = "";
  outsideSource = "";
  clearSelection();
  undo.length = 0;
  redo.length = 0;
  uploaded.fill(null);
  choices.splice(0, choices.length, "abstractexplorer", "corpusstudio");
  clearTimeout(noticeTimer);
  element("#announcement").hidden = true;
  element<HTMLInputElement>("#openLabels").value = "";
  window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  render();
  element("#document0").focus();
}

function clearSelection(): void {
  selected.clear();
  groupQuestion = "";
}
function reflectSelectionQuestion(): void {
  const exact = workspace(current())[level].find(
    (group) =>
      group.members.length === selected.size && group.members.every((key) => selected.has(key)),
  );
  groupQuestion = exact?.question ?? "";
}

async function start(): Promise<void> {
  const sources = await Promise.all(
    choices.map(async (choice, index) => {
      if (choice === "uploaded") return uploaded[index]!;
      const sample = samples.find((item) => item.paper_id === choice);
      if (!sample) throw new Error("Choose a document or upload extracted JSON");
      const response = await fetch(sample.url);
      if (!response.ok) throw new Error(`Could not load ${sample.title}`);
      return {
        paper_id: sample.paper_id,
        title: sample.title,
        filename: sample.filename,
        content: documentSchema.parse(await response.json()),
      };
    }),
  );
  const next = createSession(sources as [Source, Source]);
  if (
    session &&
    !confirm(
      "Start a new label set? Download your current labels first if you want to keep them. This replaces the browser autosave.",
    )
  )
    return;
  next.mode = setupMode;
  session = next;
  level = "sections";
  scope = "";
  query = "";
  clearSelection();
  undo.length = 0;
  redo.length = 0;
  setup = false;
  persist();
  render();
}

async function exportViewer(): Promise<void> {
  const s = current();
  const files = datasetFiles(s);
  const assets = await Promise.all(
    ["viewer-template.html", "viewer-app.js", "styles.css"].map(async (file) => {
      const response = await fetch(file);
      if (!response.ok) throw new Error(`Could not load viewer asset ${file}`);
      return response.text();
    }),
  );
  const page = assets[0].replace("Groups are model judgments", "Groups are human labels");
  const data: Record<string, Uint8Array> = Object.fromEntries(
    Object.entries(files).map(([name, value]) => [`data/${name}`, strToU8(value)]),
  );
  data["index.html"] = strToU8(page);
  data["app.js"] = strToU8(assets[1]);
  data["styles.css"] = strToU8(assets[2]);
  data["manual-labels.json"] = strToU8(JSON.stringify(s, null, 2));
  data["README.txt"] = strToU8(
    "Human-labelled Question Atlas dataset\n\nThe data/ directory uses the pipeline viewer contract.\nmanual-labels.json contains both granularities, source documents, optional questions, and outside-group flags. Open it in the manual matcher to resume.\n\nTo view this export, serve this directory with any static HTTP server.\nFor example: python -m http.server 8000\nThen visit http://localhost:8000\n\nNo model calls, pipeline attempts, or synthetic execution traces are included.\nUnlabelled passages remain separate groups; this is not a completion certificate.\n",
  );
  const zipped = zipSync(data);
  download(`human-labels-${s.mode}-viewer.zip`, zipped.buffer as ArrayBuffer, "application/zip");
  announce("Viewer exported with your saved labels.");
}

function showOutside(key: string): void {
  outsideSource = key;
  const s = current();
  const source = units(s, "paragraphs").find((unit) => unit.key === key)!;
  const targetPaper = s.sources.find((paper) => paper.paper_id !== source.paper)!;
  const dialog = element<HTMLDialogElement>("#outsideDialog");
  dialog.innerHTML = `<div class="mm-dialog-head"><h2 id="outsideTitle">Match outside this group</h2><button class="mm-text-button" data-close>Cancel</button></div>
    <p>Choose the best paragraph in ${html(targetPaper.title)}. This joins the existing groups of both paragraphs and records the outside-group selection.</p>
    <details><summary>Selected paragraph</summary><p class="mm-passage">${html(source.text)}</p></details>
    <input class="mm-search" id="outsideSearch" type="search" placeholder="Find text anywhere in the other paper" aria-label="Find outside paragraph" />
    <div class="mm-candidates"></div>`;
  renderCandidates("");
  dialog.showModal();
  element<HTMLInputElement>("#outsideSearch").focus();
  tutorial.refresh();
}

function renderCandidates(search: string): void {
  const s = current();
  const source = units(s, "paragraphs").find((unit) => unit.key === outsideSource)!;
  const sectionLookup = new Map(units(s, "sections").map((unit) => [unit.key, unit.title]));
  const ws = workspace(s);
  const sectionMap = membership(ws.sections);
  const sourceGroup = sectionMap.get(`${source.paper}:${source.section}`)!;
  const targets = units(s, "paragraphs").filter(
    (unit) =>
      unit.paper !== source.paper &&
      sectionMap.get(`${unit.paper}:${unit.section}`)!.id !== sourceGroup.id &&
      (!search ||
        unit.text.toLowerCase().includes(search.toLowerCase()) ||
        sectionLookup
          .get(`${unit.paper}:${unit.section}`)!
          .toLowerCase()
          .includes(search.toLowerCase())),
  );
  element(".mm-candidates", element("#outsideDialog")).innerHTML =
    targets
      .map(
        (unit) =>
          `<button class="mm-candidate" data-target="${html(unit.key)}"><strong>${html(sectionLookup.get(`${unit.paper}:${unit.section}`)!)} &middot; ${html(unit.title)}</strong><span>${html(unit.text)}</span></button>`,
      )
      .join("") ||
    '<p class="mm-empty">No paragraphs outside this structural group match your search.</p>';
}

element("#matcher").addEventListener("click", (event) => {
  const target = (event.target as Element).closest<HTMLElement>("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  try {
    if (action === "tutorial") {
      if (tutorial.active) tutorial.finish();
      else {
        beforeTutorial = session;
        uploaded[0] = PRACTICE_SOURCES[0];
        uploaded[1] = PRACTICE_SOURCES[1];
        choices.fill("uploaded");
        tutorial.start();
      }
      return;
    }
    if (
      tutorial.active &&
      ["start", "open", "resume", "documents", "mode", "save", "preview", "export"].includes(
        action!,
      )
    )
      return;
    if (action === "start") {
      void start().catch((error) => announce(message(error), true));
      return;
    }
    if (action === "open") {
      element<HTMLInputElement>("#openLabels").click();
      return;
    }
    if (action === "resume") {
      setup = false;
      render();
      return;
    }
    if (action === "documents") {
      setup = true;
      render();
      return;
    }
    if (action === "mode") {
      const mode = target.dataset.mode as Mode;
      if (setup) setupMode = mode;
      else {
        current().mode = mode;
        scope = "";
        clearSelection();
        persist();
      }
      query = "";
      render();
      return;
    }
    const s = current();
    if (action === "save") {
      download("human-labels.json", JSON.stringify(s, null, 2) + "\n", "application/json");
      announce("Labels downloaded. Open this file to resume on any device.");
    } else if (action === "preview") {
      localStorage.setItem(PREVIEW_KEY, JSON.stringify(s));
      window.open("./viewer.html", "_blank", "noopener");
    } else if (action === "export") {
      void exportViewer().catch((error) => announce(message(error), true));
    } else if (action === "step" || action === "continue" || action === "paragraphs") {
      level = (target.dataset.level as Level) ?? "paragraphs";
      scope = target.dataset.group ?? scope;
      clearSelection();
      query = "";
      render();
    } else if (action === "clear") {
      clearSelection();
      render();
    } else if (action === "edit") {
      const group = workspace(s)[level].find((g) => g.id === target.dataset.group)!;
      selected = new Set(group.members);
      groupQuestion = group.question;
      render();
    } else if (action === "group") {
      if (level === "paragraphs") {
        const sectionMap = membership(workspace(s).sections);
        const chosen = units(s, level).filter((u) => selected.has(u.key));
        const exact = workspace(s).paragraphs.some(
          (g) => g.members.length === selected.size && g.members.every((key) => selected.has(key)),
        );
        if (
          !exact &&
          new Set(chosen.map((u) => sectionMap.get(`${u.paper}:${u.section}`)!.id)).size > 1
        )
          throw new Error(
            "Use Match outside this group to join paragraphs across structural groups",
          );
      }
      commit(() => {
        groupUnits(s, level, [...selected], groupQuestion);
        clearSelection();
      });
    } else if (action === "ungroup")
      commit(() => {
        ungroupUnits(s, level, [...selected]);
        clearSelection();
      });
    else if (action === "outside") showOutside(target.dataset.unit!);
    else if (action === "undo" || action === "redo") {
      const from = action === "undo" ? undo : redo;
      const to = action === "undo" ? redo : undo;
      const snapshot = from.pop();
      if (snapshot) {
        to.push(JSON.stringify(s));
        session = parseSession(JSON.parse(snapshot));
        clearSelection();
        persist();
        render();
      }
    }
  } catch (error) {
    announce(message(error), true);
  }
});

element("#matcher").addEventListener("change", (event) => {
  const target = event.target as HTMLInputElement;
  if (target.dataset.pick) {
    if (target.checked) selected.add(target.dataset.pick);
    else selected.delete(target.dataset.pick);
    reflectSelectionQuestion();
    render();
  } else if (target.dataset.document !== undefined) {
    choices[Number(target.dataset.document)] = target.value;
    render();
  } else if (target.dataset.upload !== undefined && target.files?.[0]) {
    const file = target.files[0];
    const index = Number(target.dataset.upload) as 0 | 1;
    void file
      .text()
      .then((text) => {
        const content = documentSchema.parse(JSON.parse(text));
        const title = file.name.replace(/(?:\.content)?\.json$/i, "");
        const id =
          title
            .toLowerCase()
            .replace(/[^a-z0-9_-]+/g, "-")
            .replace(/^-+|-+$/g, "") || `paper-${index + 1}`;
        uploaded[index] = { paper_id: id, title, filename: file.name, content };
        choices[index] = "uploaded";
        render();
      })
      .catch((error) => announce("Could not open document: " + message(error), true));
  } else if (target.id === "scope") {
    scope = target.value;
    clearSelection();
    query = "";
    render();
  } else if (target.dataset.unitQuestion) {
    commit(() => {
      workspace(current()).questions[target.dataset.unitQuestion!] = target.value.trim();
    }, false);
    target.closest("details")!.querySelector("summary")!.textContent = target.value.trim()
      ? "Edit question"
      : "Add question (optional)";
  }
});

element("#matcher").addEventListener("input", (event) => {
  const target = event.target as HTMLInputElement;
  if (target.id === "groupQuestion") groupQuestion = target.value;
  else if (target.id === "search") {
    query = target.value;
    render();
  }
});

element<HTMLInputElement>("#openLabels").addEventListener("change", (event) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  void file
    .text()
    .then((text) => {
      const next = parseSession(JSON.parse(text));
      if (session && !confirm("Open these labels and replace the current browser autosave?"))
        return;
      session = next;
      setup = false;
      level = "sections";
      scope = "";
      query = "";
      clearSelection();
      undo.length = 0;
      redo.length = 0;
      persist();
      render();
      announce("Saved labels opened.");
    })
    .catch((error) => announce("Could not open labels: " + message(error), true))
    .finally(() => {
      input.value = "";
    });
});

element("#outsideDialog").addEventListener("click", (event) => {
  const target = (event.target as Element).closest<HTMLElement>("[data-close], [data-target]");
  if (!target) return;
  if (target.dataset.target)
    commit(() => {
      matchOutside(current(), outsideSource, target.dataset.target!);
      selected = new Set(membership(workspace(current()).paragraphs).get(outsideSource)!.members);
      reflectSelectionQuestion();
    });
  element<HTMLDialogElement>("#outsideDialog").close();
});
element("#outsideDialog").addEventListener("input", (event) => {
  renderCandidates((event.target as HTMLInputElement).value);
});
element("#outsideDialog").addEventListener("close", () => tutorial.refresh());

try {
  session = readSaved();
  setup = !session;
} catch (error) {
  announce("Could not restore browser labels. Open a saved labels file. " + message(error), true);
}
render();
void fetch("./samples.json")
  .then(async (response) => {
    if (!response.ok) throw new Error("Prepared examples unavailable; you can still upload JSON.");
    samples = (await response.json()) as Sample[];
    if (setup) render();
  })
  .catch((error) => announce(message(error), true));
