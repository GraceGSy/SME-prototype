import { element, escapeHtml as html } from "./dom";
import { type GroupEntry, type Model, unitKey } from "./model";

export class PaperMapView {
  private selected: string | null = null;
  private hideUnselected = false;
  private showSingletons = false;
  private syncScroll = false;
  private syncing = false;
  private scroll = new Map<string, number>();

  constructor(private host: HTMLElement, private model: Model) {}

  render(): void {
    this.host.innerHTML = `<div class="paper-map-shell"><div class="paper-map-overview">
      <div class="paper-map-control-row">
        <span class="paper-map-summary">${this.model.shared.length} shared groups; ${this.model.singletons.length} singleton questions</span>
        <label class="paper-map-sync-toggle"><input id="paperMapSyncScroll" type="checkbox"${this.syncScroll ? " checked" : ""}> Sync paper scrolling</label>
        <label class="paper-map-hide-unselected-toggle"><input id="paperMapHideUnselected" type="checkbox"> Hide unselected</label>
        <button class="paper-map-action-button" id="paperMapSingletonToggle" type="button" aria-pressed="${this.showSingletons}">${this.showSingletons ? "Hide" : "Show"} singleton questions</button>
        <button class="paper-map-action-button" id="paperMapClear" type="button">Clear selection</button>
      </div>
      <div class="paper-map-legend paper-map-shared-legend" aria-label="Shared questions">${this.legend(this.model.shared)}</div>
      <div class="paper-map-singleton-tray"${this.showSingletons ? "" : " hidden"}>
        <div class="paper-map-singleton-label">Singleton questions</div>
        <div class="paper-map-legend paper-map-singleton-legend">${this.legend(this.model.singletons)}</div>
      </div>
      </div><div class="paper-map-columns" style="--paper-count:${this.model.papers.length}">
      ${this.model.papers.map(paper => `<section class="paper-map-column" data-paper="${html(paper.paper_id)}">
        <div class="paper-map-paper-head">${html(paper.title)}</div>
        <div class="paper-map-column-indicator paper-map-column-indicator-top"></div>
        ${paper.sections.map(section => `<h2 class="paper-map-section-head">${html(section.title)}</h2>
          ${paper.paragraphs.filter(unit => unit.section_id === section.id).map(unit => {
            const entry = this.model.membership.get(unitKey(paper.paper_id, unit.id))!;
            return `<article class="paper-map-paragraph${entry.singleton ? " singleton" : ""}" tabindex="0" role="button"
              aria-label="${html(unit.tag)}" data-group="${html(entry.group.group_id)}"
              style="--group-color:${entry.color};--group-fill:${entry.fill}">
              <div class="paper-map-paragraph-meta">${html(unit.id)}</div>
              <div class="paper-map-paragraph-question">${html(unit.tag)}</div>
              <div class="paper-map-paragraph-text">${html(unit.text)}</div>
            </article>`;
          }).join("")}`).join("")}
        <div class="paper-map-column-indicator paper-map-column-indicator-bottom"></div></section>`).join("")}
      </div></div>`;
    element<HTMLInputElement>("#paperMapSyncScroll", this.host).addEventListener("change", event => {
      this.syncScroll = (event.currentTarget as HTMLInputElement).checked;
    });
    element<HTMLInputElement>("#paperMapHideUnselected", this.host).addEventListener("change", event => {
      this.hideUnselected = (event.currentTarget as HTMLInputElement).checked;
      this.emphasize();
    });
    element("#paperMapSingletonToggle", this.host).addEventListener("click", () => {
      this.showSingletons = !this.showSingletons;
      if (!this.showSingletons && this.selected && this.model.groups.get(this.selected)?.singleton) this.selected = null;
      this.render();
    });
    element("#paperMapClear", this.host).addEventListener("click", () => this.select(null));
    this.host.querySelectorAll<HTMLElement>("[data-group]").forEach(item => {
      const id = item.dataset.group!;
      item.addEventListener("click", () => this.select(this.selected === id ? null : id, item.classList.contains("paper-map-legend-item")));
      if (item.tagName !== "BUTTON") item.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); item.click(); }
      });
      item.addEventListener("mouseenter", () => {
        this.emphasize(id);
        if (item.classList.contains("paper-map-legend-item")) this.tooltip(item, id);
      });
      item.addEventListener("mouseleave", () => { this.emphasize(); this.hideTooltip(); });
      item.addEventListener("focus", () => { if (item.classList.contains("paper-map-legend-item")) this.tooltip(item, id); });
      item.addEventListener("blur", () => this.hideTooltip());
    });
    const columns = [...this.host.querySelectorAll<HTMLElement>(".paper-map-column")];
    for (const column of columns) {
      column.scrollTop = this.scroll.get(column.dataset.paper!) ?? 0;
      column.addEventListener("scroll", () => {
        this.scroll.set(column.dataset.paper!, column.scrollTop);
        this.hideTooltip();
        if (this.syncScroll && !this.syncing) {
          this.syncing = true;
          const fraction = column.scrollTop / Math.max(1, column.scrollHeight - column.clientHeight);
          for (const other of columns) if (other !== column) {
            other.scrollTop = fraction * (other.scrollHeight - other.clientHeight);
          }
          requestAnimationFrame(() => { this.syncing = false; });
        }
        this.indicators();
      }, { passive: true });
    }
    this.emphasize();
    this.resize();
  }

  private legend(entries: GroupEntry[]): string {
    return [...entries].sort((a, b) => b.group.members.length - a.group.members.length).map(entry =>
      `<button type="button" class="paper-map-legend-item${entry.singleton ? " singleton" : ""}" data-group="${html(entry.group.group_id)}"
        style="--group-color:${entry.color};--group-fill:${entry.fill}">
        <span class="paper-map-swatch"></span><span class="paper-map-legend-question">${html(entry.group.overarching_question)}</span>
        <span class="paper-map-legend-count">${entry.group.members.length}</span></button>`).join("");
  }

  private select(id: string | null, scrollTo = false): void {
    this.selected = id;
    if (id && this.model.groups.get(id)?.singleton && !this.showSingletons) {
      this.showSingletons = true;
      this.render();
    }
    this.emphasize();
    if (scrollTo && id) {
      for (const column of this.host.querySelectorAll<HTMLElement>(".paper-map-column")) {
        const target = [...column.querySelectorAll<HTMLElement>(".paper-map-paragraph")].find(item => item.dataset.group === id);
        if (target) column.scrollTop += target.getBoundingClientRect().top - column.getBoundingClientRect().top - 65;
      }
    }
    this.hideTooltip();
    this.indicators();
  }

  private emphasize(hover: string | null = null): void {
    if (!this.selected) this.hideUnselected = false;
    const active = this.selected ?? hover;
    const toggle = element<HTMLInputElement>("#paperMapHideUnselected", this.host);
    toggle.disabled = this.selected === null;
    toggle.checked = this.hideUnselected;
    this.host.querySelectorAll<HTMLElement>("[data-group]").forEach(item => {
      const matches = item.dataset.group === active;
      item.classList.toggle("highlight", !!active && matches);
      item.classList.toggle("dim", !!active && !matches);
      item.classList.toggle("selected", item.dataset.group === this.selected);
      item.setAttribute("aria-pressed", String(item.dataset.group === this.selected));
      item.classList.toggle("hidden", item.classList.contains("paper-map-paragraph") && this.hideUnselected && !matches);
    });
    this.indicators();
  }

  private indicators(): void {
    for (const column of this.host.querySelectorAll<HTMLElement>(".paper-map-column")) {
      const bounds = column.getBoundingClientRect();
      const items = [...column.querySelectorAll<HTMLElement>(".paper-map-paragraph")].filter(item => item.dataset.group === this.selected);
      const above = items.filter(item => item.getBoundingClientRect().bottom < bounds.top + 60).length;
      const below = items.filter(item => item.getBoundingClientRect().top > bounds.bottom).length;
      for (const [side, count] of [["top", above], ["bottom", below]] as const) {
        const indicator = element(`.paper-map-column-indicator-${side}`, column);
        indicator.classList.toggle("visible", count > 0);
        indicator.textContent = `${count} selected paragraphs ${side === "top" ? "above" : "below"}`;
      }
    }
  }

  private tooltip(anchor: HTMLElement, id: string): void {
    const entry = this.model.groups.get(id)!;
    const tip = element("#paperMapQuestionPreview");
    element("#paperMapQuestionPreviewText").textContent = entry.group.overarching_question;
    element("#paperMapQuestionPreviewMeta").textContent = `${entry.group.members.length} paragraphs; ${new Set(entry.group.members.map(member => member.paper)).size} papers`;
    tip.style.setProperty("--group-color", entry.color);
    tip.classList.add("visible");
    tip.setAttribute("aria-hidden", "false");
    const bounds = anchor.getBoundingClientRect();
    tip.style.left = Math.max(12, Math.min(bounds.left, innerWidth - tip.offsetWidth - 12)) + "px";
    tip.style.top = Math.max(12, Math.min(bounds.bottom + 8, innerHeight - tip.offsetHeight - 12)) + "px";
  }

  hideTooltip(): void {
    element("#paperMapQuestionPreview").classList.remove("visible");
    element("#paperMapQuestionPreview").setAttribute("aria-hidden", "true");
  }

  resize(): void {
    this.hideTooltip();
    const shell = this.host.querySelector<HTMLElement>(".paper-map-shell");
    if (shell) shell.style.height = Math.max(520, innerHeight - shell.getBoundingClientRect().top - 16) + "px";
    this.indicators();
  }
}
