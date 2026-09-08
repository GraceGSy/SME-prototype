import { html, button } from "./explorer-dom";
import { renderInspector } from "./explorer-inspector";
import { type Model, PAPER_COLORS } from "./model";
import { explorerGraph, NODE_HEIGHT, NODE_WIDTH, type ExplorerGraph } from "./explorer-layout";

function svg<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number> = {},
) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}
function lines(text: string, length = 30): string[] {
  const result: string[] = [];
  for (const word of text.split(/\s+/)) {
    if (!result.length || result[result.length - 1].length + word.length > length)
      result.push(word);
    else result[result.length - 1] += " " + word;
  }
  return result;
}

export class GraphicalExplorer {
  private section: string | null = null;
  private selected: string | null = null;
  private graph!: ExplorerGraph;
  private root!: HTMLElement;
  private canvas!: SVGSVGElement;
  private world!: SVGGElement;
  private inspector!: HTMLElement;
  private status!: HTMLElement;
  private scale = 1;
  private tx = 0;
  private ty = 0;
  private paper = "";
  private query = "";
  private filter = "all";
  private subsections = false;
  private comparing = false;
  private observer?: ResizeObserver;

  constructor(
    private host: HTMLElement,
    private model: Model,
  ) {}

  destroy(): void {
    this.observer?.disconnect();
  }

  render(): void {
    this.destroy();
    this.graph = explorerGraph(this.model, this.section, this.subsections);
    this.root = html("section", "gx");
    this.root.setAttribute("aria-label", "Graphical Explorer");
    const heading = html("div", "gx-heading");
    const intro = html("div");
    intro.append(html("div", "gx-eyebrow", "QUESTION ATLAS / GRAPHICAL EXPLORER"));
    intro.append(
      html("h2", "", this.section ? "Inside a shared structure" : "Many papers. A common thread."),
    );
    intro.append(
      html("p", "", "Follow the questions. Compare the evidence. Notice where the paths diverge."),
    );
    const stats = html("div", "gx-stats");
    const shared = this.graph.nodes.filter((n) => n.papers.length > 1).length;
    stats.append(
      html("strong", "", String(shared)),
      html("span", "", "shared roles"),
      html("strong", "", String(this.graph.nodes.length - shared)),
      html("span", "", "unmatched roles"),
    );
    heading.append(intro, stats);
    const toolbar = html("div", "gx-toolbar");
    toolbar.append(button("All sections", () => this.navigate(null)));
    if (this.section)
      toolbar.append(
        html(
          "span",
          "gx-breadcrumb",
          "/ " + this.model.sections.find((g) => g.group_id === this.section)!.overarching_question,
        ),
      );
    const search = html("input", "gx-search");
    search.type = "search";
    search.placeholder = "Find a question or passage...";
    search.setAttribute("aria-label", "Find graph nodes");
    search.value = this.query;
    search.addEventListener("input", () => {
      this.query = search.value;
      this.highlight();
    });
    const filter = html("select");
    filter.setAttribute("aria-label", "Show graph roles");
    for (const [value, label] of [
      ["all", "All roles"],
      ["shared", "Shared roles"],
      ["unmatched", "Unmatched roles"],
    ]) {
      const option = html("option", "", label);
      option.value = value;
      filter.append(option);
    }
    filter.value = this.filter;
    filter.addEventListener("change", () => {
      this.filter = filter.value;
      this.highlight();
    });
    toolbar.append(search, filter);
    if (!this.section) {
      const detail = html("label", "gx-detail-toggle");
      const checkbox = html("input");
      checkbox.type = "checkbox";
      checkbox.checked = this.subsections;
      checkbox.addEventListener("change", () => {
        this.subsections = checkbox.checked;
        this.selected = null;
        this.render();
      });
      detail.append(checkbox, document.createTextNode("Include subsections"));
      toolbar.append(detail);
    }
    const legend = html("div", "gx-papers");
    legend.append(
      button(
        "All papers",
        () => {
          this.paper = "";
          this.render();
        },
        "gx-paper" + (!this.paper ? " active" : ""),
      ),
    );
    this.model.papers.forEach((paper, index) => {
      const chip = button(
        paper.title,
        () => {
          this.paper = this.paper === paper.paper_id ? "" : paper.paper_id;
          this.render();
        },
        "gx-paper" + (this.paper === paper.paper_id ? " active" : ""),
      );
      chip.style.setProperty("--paper", PAPER_COLORS[index % PAPER_COLORS.length]);
      chip.setAttribute("aria-pressed", String(this.paper === paper.paper_id));
      legend.append(chip);
    });
    const body = html("div", "gx-body" + (this.comparing ? " comparing" : ""));
    const viewport = html("div", "gx-viewport");
    this.canvas = svg("svg", {
      "aria-label": this.section ? "Paragraph role graph" : "Section role graph",
      role: "group",
    });
    this.world = svg("g");
    this.canvas.append(this.world);
    viewport.append(this.canvas);
    const controls = html("div", "gx-zoom");
    controls.append(
      button("+", () => this.zoom(1.3)),
      button("-", () => this.zoom(1 / 1.3)),
      button("Fit graph", () => this.fit()),
    );
    controls.children[0].setAttribute("aria-label", "Zoom in");
    controls.children[1].setAttribute("aria-label", "Zoom out");
    this.status = html("div", "gx-status");
    this.status.setAttribute("role", "status");
    viewport.append(
      controls,
      this.status,
      html("div", "gx-hint", "Drag to pan / Scroll to zoom / Select a node to read"),
    );
    this.inspector = html("aside", "gx-inspector");
    this.inspector.setAttribute("aria-label", "Selected role and source passages");
    body.append(viewport, this.inspector);
    const key = html("div", "gx-key");
    key.append(
      html("span", "", "Solid node: shared role"),
      html("span", "", "Dashed node: unmatched role"),
      html("span", "", "Colored arrows: reading order among displayed units, not causal links"),
    );
    this.root.append(heading, toolbar, legend, body, key);
    this.host.replaceChildren(this.root);
    this.draw();
    this.inspect();
    this.bindPan();
    this.observer = new ResizeObserver(() => this.frame());
    this.observer.observe(viewport);
    this.frame();
  }

  private navigate(section: string | null): void {
    this.section = section;
    this.selected = null;
    this.query = "";
    this.filter = "all";
    this.render();
  }

  private draw(): void {
    const lookup = new Map(this.graph.nodes.map((n) => [n.group.group_id, n]));
    const defs = svg("defs");
    this.model.papers.forEach((_, index) => {
      const marker = svg("marker", {
        id: `gx-arrow-${index}`,
        viewBox: "0 0 8 8",
        refX: 7,
        refY: 4,
        markerWidth: 5,
        markerHeight: 5,
        orient: "auto",
      });
      marker.append(
        svg("path", { d: "M0,0 L8,4 L0,8 Z", fill: PAPER_COLORS[index % PAPER_COLORS.length] }),
      );
      defs.append(marker);
    });
    this.world.append(defs);
    for (const edge of this.graph.edges) {
      const source = lookup.get(edge.source)!;
      const target = lookup.get(edge.target)!;
      const index = this.model.papers.findIndex((p) => p.paper_id === edge.paper);
      const offset = (index - (this.model.papers.length - 1) / 2) * 6;
      const x1 = source.x + NODE_WIDTH / 2 + offset;
      const y1 = source.y + NODE_HEIGHT;
      const x2 = target.x + NODE_WIDTH / 2 + offset;
      const y2 = target.y;
      const bend = Math.max(50, Math.abs(y2 - y1) / 2);
      const path = svg("path", {
        d: `M${x1},${y1} C${x1},${y1 + bend} ${x2},${y2 - bend} ${x2},${y2}`,
        stroke: PAPER_COLORS[index % PAPER_COLORS.length],
        fill: "none",
        "stroke-width": 2,
        "marker-end": `url(#gx-arrow-${index})`,
        class: "gx-edge",
      });
      path.dataset.paper = edge.paper;
      path.dataset.source = edge.source;
      path.dataset.target = edge.target;
      const title = svg("title");
      title.textContent = this.model.papers[index].title + ": reading order";
      path.append(title);
      this.world.append(path);
    }
    for (const node of this.graph.nodes) {
      const group = svg("g", {
        transform: `translate(${node.x} ${node.y})`,
        class: "gx-node" + (node.papers.length === 1 ? " unmatched" : ""),
        tabindex: 0,
        role: "button",
        "aria-label": node.group.overarching_question,
      });
      group.dataset.id = node.group.group_id;
      const title = svg("title");
      title.textContent = node.group.overarching_question;
      group.append(title, svg("rect", { width: NODE_WIDTH, height: NODE_HEIGHT, rx: 12 }));
      const badge = svg("text", { x: 15, y: 22, class: "gx-node-meta" });
      badge.textContent =
        node.papers.length > 1
          ? `${node.papers.length} PAPERS / SHARED ROLE`
          : "1 PAPER / UNMATCHED";
      group.append(badge);
      const wrapped = lines(node.group.overarching_question);
      wrapped.slice(0, 3).forEach((line, i) => {
        const text = svg("text", { x: 15, y: 42 + i * 16, class: "gx-node-title" });
        text.textContent = line + (i === 2 && wrapped.length > 3 ? "..." : "");
        group.append(text);
      });
      node.papers.forEach((paper, i) => {
        const index = this.model.papers.findIndex((p) => p.paper_id === paper);
        group.append(
          svg("rect", {
            x: 15 + i * 22,
            y: 91,
            width: 17,
            height: 4,
            rx: 2,
            fill: PAPER_COLORS[index % PAPER_COLORS.length],
            class: "gx-paper-mark",
          }),
        );
      });
      const select = () => {
        this.selected = node.group.group_id;
        this.highlight();
        this.inspect();
      };
      group.addEventListener("click", select);
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });
      group.addEventListener("dblclick", () => {
        if (!this.section) this.navigate(node.group.group_id);
      });
      this.world.append(group);
    }
    this.highlight();
  }

  private highlight(): void {
    const visible = new Set<string>();
    for (const node of this.graph.nodes) {
      const shared = node.papers.length > 1;
      const text =
        node.group.overarching_question +
        " " +
        node.group.members
          .map((m) => {
            const paper = this.model.papers.find((p) => p.paper_id === m.paper)!;
            return (
              (this.section ? paper.paragraphs : paper.sections).find((u) => u.id === m.unit_id)
                ?.text ?? ""
            );
          })
          .join(" ");
      if (
        (!this.paper || node.papers.includes(this.paper)) &&
        (this.filter === "all" || (this.filter === "shared" ? shared : !shared)) &&
        text.toLowerCase().includes(this.query.toLowerCase())
      )
        visible.add(node.group.group_id);
    }
    this.world.querySelectorAll<SVGGElement>(".gx-node").forEach((node) => {
      const active = visible.has(node.dataset.id!);
      node.classList.toggle("dimmed", !active);
      node.classList.toggle("selected", node.dataset.id === this.selected);
      node.setAttribute("aria-pressed", String(node.dataset.id === this.selected));
      node.setAttribute("tabindex", active ? "0" : "-1");
    });
    this.world.querySelectorAll<SVGPathElement>(".gx-edge").forEach((edge) => {
      edge.classList.toggle(
        "dimmed",
        !visible.has(edge.dataset.source!) ||
          !visible.has(edge.dataset.target!) ||
          (!!this.paper && this.paper !== edge.dataset.paper),
      );
      edge.classList.toggle(
        "selected",
        !!this.selected &&
          (edge.dataset.source === this.selected || edge.dataset.target === this.selected),
      );
    });
    this.status.textContent = `${visible.size} of ${this.graph.nodes.length} roles highlighted`;
  }

  private inspect(): void {
    renderInspector(
      this.inspector,
      this.model,
      this.graph,
      this.section,
      this.selected,
      this.comparing,
      {
        navigate: (id) => this.navigate(id),
        select: (id) => {
          this.selected = id;
          this.highlight();
          this.inspect();
          this.focusNode(id);
        },
        toggleCompare: () => {
          this.comparing = !this.comparing;
          this.root.querySelector(".gx-body")!.classList.toggle("comparing", this.comparing);
          this.inspect();
        },
      },
    );
  }

  private transform(): void {
    this.world.setAttribute("transform", `translate(${this.tx} ${this.ty}) scale(${this.scale})`);
  }
  private fit(): void {
    const box = this.canvas.getBoundingClientRect();
    this.scale = Math.min(box.width / this.graph.width, box.height / this.graph.height) * 0.94;
    this.tx = (box.width - this.graph.width * this.scale) / 2;
    this.ty = (box.height - this.graph.height * this.scale) / 2;
    this.transform();
  }
  private frame(): void {
    this.fit();
    // Start close enough to recognize roles; Fit graph remains the full skeleton.
    if (!this.comparing && this.scale < 0.65) {
      this.zoom(0.65 / this.scale, this.canvas.clientWidth / 2, 0);
      this.ty = 15;
      this.transform();
    }
  }
  private zoom(
    factor: number,
    x = this.canvas.clientWidth / 2,
    y = this.canvas.clientHeight / 2,
  ): void {
    const next = Math.min(3, Math.max(0.08, this.scale * factor));
    this.tx = x - ((x - this.tx) * next) / this.scale;
    this.ty = y - ((y - this.ty) * next) / this.scale;
    this.scale = next;
    this.transform();
  }
  private focusNode(id: string): void {
    const node = this.graph.nodes.find((n) => n.group.group_id === id);
    if (!node) return;
    this.scale = Math.max(this.scale, 0.8);
    this.tx = this.canvas.clientWidth / 2 - (node.x + NODE_WIDTH / 2) * this.scale;
    this.ty = this.canvas.clientHeight / 2 - (node.y + NODE_HEIGHT / 2) * this.scale;
    this.transform();
  }
  private bindPan(): void {
    let drag: { x: number; y: number; tx: number; ty: number } | null = null;
    this.canvas.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        const box = this.canvas.getBoundingClientRect();
        this.zoom(
          Math.exp(-event.deltaY * 0.0015),
          event.clientX - box.left,
          event.clientY - box.top,
        );
      },
      { passive: false },
    );
    this.canvas.addEventListener("pointerdown", (event) => {
      if ((event.target as Element).closest(".gx-node") || event.button !== 0) return;
      drag = { x: event.clientX, y: event.clientY, tx: this.tx, ty: this.ty };
      this.canvas.setPointerCapture(event.pointerId);
    });
    this.canvas.addEventListener("pointermove", (event) => {
      if (!drag) return;
      this.tx = drag.tx + event.clientX - drag.x;
      this.ty = drag.ty + event.clientY - drag.y;
      this.transform();
    });
    this.canvas.addEventListener("pointerup", () => {
      drag = null;
    });
    this.canvas.addEventListener("pointercancel", () => {
      drag = null;
    });
  }
}
