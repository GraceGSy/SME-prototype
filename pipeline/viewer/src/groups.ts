import type { Group } from "./contracts";
import { element, escapeHtml as html, preview } from "./dom";
import { PAPER_COLORS, type Model, unitKey } from "./model";

export class GroupsView {
  private open = new Set<string>();
  private expanded = new Set<string>();
  private previewLength = 200;

  constructor(private host: HTMLElement, private model: Model) {}

  render(): void {
    const groups = [...this.model.shared].sort((a, b) => b.group.members.length - a.group.members.length).map(entry => entry.group);
    const singleton: Group = {
      group_id: "__singleton_questions__", overarching_question: "Singleton Questions", parent_group_id: null,
      members: this.model.singletons.flatMap(entry => entry.group.members),
    };
    if (singleton.members.length) groups.push(singleton);
    this.host.innerHTML = `<label class="epoch-groups-preview-control">Preview length
      <input id="previewSlider" type="range" min="0" max="200" step="10" value="${this.previewLength}">
      <span id="previewValue">${this.previewLength}</span></label>
      <div class="iteration-meta">${this.model.shared.length} shared groups; ${this.model.singletons.length} singleton questions; final snapshot</div>
      <div class="papers-legend">${this.model.papers.map((paper, index) => `<span class="papers-legend-item">
        <span class="papers-legend-swatch" style="background:${PAPER_COLORS[index % PAPER_COLORS.length]}"></span>${html(paper.title)}</span>`).join("")}</div>`;
    const slider = element<HTMLInputElement>("#previewSlider", this.host);
    slider.addEventListener("input", () => {
      this.previewLength = Number(slider.value);
      element("#previewValue", this.host).textContent = slider.value;
      this.host.querySelectorAll<HTMLElement>("[data-unit-key]").forEach(block => {
        const unit = this.model.paragraphs.get(block.dataset.unitKey!);
        if (unit) element(".section-text-preview", block).textContent = preview(unit.text, this.previewLength);
      });
    });
    for (const group of groups) {
      const card = document.createElement("section");
      card.className = "group-card" + (group === singleton ? " singleton-container" : "");
      card.dataset.groupId = group.group_id;
      card.innerHTML = `<button class="group-question" type="button">${html(group.overarching_question)}</button>
        <button class="expand-all-btn" type="button">Expand all</button>
        <div class="group-unit-vis">${group.members.map(member => {
          const index = this.model.papers.findIndex(paper => paper.paper_id === member.paper);
          return `<span class="unit-square represented" style="--paper-color:${PAPER_COLORS[index % PAPER_COLORS.length]}" title="${html(member.paper)}"></span>`;
        }).join("")}</div><div class="group-detail-slot"></div>`;
      const toggle = element<HTMLButtonElement>(".group-question", card);
      const slot = element(".group-detail-slot", card);
      const refresh = (): void => {
        const isOpen = this.open.has(group.group_id);
        toggle.setAttribute("aria-expanded", String(isOpen));
        card.classList.toggle("open", isOpen);
        if (isOpen) this.detail(slot, group);
        else slot.replaceChildren();
        this.updateExpandButton(card);
      };
      toggle.addEventListener("click", () => {
        if (this.open.has(group.group_id)) this.open.delete(group.group_id);
        else this.open.add(group.group_id);
        refresh();
      });
      element(".expand-all-btn", card).addEventListener("click", () => {
        const blocks = [...slot.querySelectorAll<HTMLElement>("[data-unit-key]")];
        const expand = !blocks.every(block => this.expanded.has(block.dataset.unitKey!));
        for (const block of blocks) {
          const key = block.dataset.unitKey!;
          if (expand) this.expanded.add(key); else this.expanded.delete(key);
        }
        refresh();
      });
      refresh();
      this.host.append(card);
    }
  }

  private updateExpandButton(card: HTMLElement): void {
    const blocks = [...card.querySelectorAll<HTMLElement>("[data-unit-key]")];
    element(".expand-all-btn", card).textContent = blocks.length && blocks.every(block => this.expanded.has(block.dataset.unitKey!))
      ? "Collapse all" : "Expand all";
  }

  private detail(slot: HTMLElement, group: Group): void {
    const memberKeys = new Set(group.members.map(member => unitKey(member.paper, member.unit_id)));
    slot.innerHTML = `<div class="group-columns">${this.model.papers.map(paper => {
      const paragraphs = paper.paragraphs.filter(unit => memberKeys.has(unitKey(paper.paper_id, unit.id)));
      return `<div class="column"><div class="paper-title">${html(paper.title)}</div>${paragraphs.map(unit => {
        const key = unitKey(paper.paper_id, unit.id);
        return `<article class="section-block${this.expanded.has(key) ? " expanded" : ""}" data-unit-key="${html(key)}">
          <div class="section-head"><span class="tag-badge">${html(unit.tag)}</span></div>
          <div class="section-text section-text-preview">${html(preview(unit.text, this.previewLength))}</div>
          <div class="section-text section-text-full">${html(unit.text)}</div>
          <button type="button" class="expand-hint" aria-label="Toggle full text" aria-expanded="${this.expanded.has(key)}"></button>
        </article>`;
      }).join("") || '<div class="group-column-empty">No quotes in this group</div>'}</div>`;
    }).join("")}</div>`;
    slot.querySelectorAll<HTMLElement>("[data-unit-key]").forEach(block => {
      element(".expand-hint", block).addEventListener("click", () => {
        const key = block.dataset.unitKey!;
        const expanded = !this.expanded.has(key);
        if (expanded) this.expanded.add(key); else this.expanded.delete(key);
        block.classList.toggle("expanded", expanded);
        element(".expand-hint", block).setAttribute("aria-expanded", String(expanded));
        this.updateExpandButton(slot.parentElement!);
      });
    });
  }
}
