import { html, button } from "./explorer-dom";
import { renderPassages } from "./explorer-passages";
import { type Model, PAPER_COLORS } from "./model";
import {
  collapseEdges,
  explorerGraph,
  NODE_HEIGHT,
  NODE_WIDTH,
  ROW_GAP,
  BOARD_TOP,
  type ExplorerGraph,
  type ExplorerNode,
} from "./explorer-layout";

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
  private history: ExplorerNode[] = [];
  private animation = 0;
  private evidence: string | null = null;
  private status!: HTMLElement;
  private scale = 1;
  private tx = 0;
  private ty = 0;
  private paper = "";
  private query = "";
  private filter = "all";
  private subsections = false;
  private observer?: ResizeObserver;

  constructor(
    private host: HTMLElement,
    private model: Model,
  ) {}

  destroy(): void {
    this.observer?.disconnect();
    cancelAnimationFrame(this.animation);
  }

  render(): void {
    this.destroy();
    this.graph = explorerGraph(this.model, this.section, this.subsections);
    const anchor = this.history.at(-1);
    if (anchor) {
      const dx = anchor.x + NODE_WIDTH / 2 - this.graph.centerX;
      const top = Math.min(...this.graph.nodes.map((n) => n.y), BOARD_TOP);
      for (const node of this.graph.nodes) {
        node.x += dx;
        node.y += anchor.y + NODE_HEIGHT + 48 - top;
      }
      this.graph.centerX += dx;
      this.graph.height = Math.max(
        anchor.y + NODE_HEIGHT + 150,
        ...this.graph.nodes.map((n) => n.y + NODE_HEIGHT + 70),
      );
    }
    this.root = html("section", "gx");
    this.root.setAttribute("aria-label", "Graphical Explorer");
    const toolbar = html("div", "gx-toolbar");
    toolbar.append(button("All sections", () => this.navigate(null)));
    if (this.section) toolbar.append(button("Back", () => this.back()));
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
    const allPapers = button(
      "All papers",
      () => {
        this.paper = "";
        this.render();
      },
      "gx-paper" + (!this.paper ? " active" : ""),
    );
    allPapers.setAttribute("aria-pressed", String(!this.paper));
    legend.append(allPapers);
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
    const body = html("div", "gx-body");
    const viewport = html("div", "gx-viewport");
    this.canvas = svg("svg", {
      "aria-label": this.section ? "Section contents pattern board" : "Document pattern board",
      role: "group",
    });
    this.world = svg("g");
    this.canvas.append(this.world);
    viewport.append(this.canvas);
    const controls = html("div", "gx-zoom");
    controls.append(
      button("+", () => this.zoom(1.3)),
      button("-", () => this.zoom(1 / 1.3)),
      button("Fit board", () => this.fit()),
    );
    controls.children[0].setAttribute("aria-label", "Zoom in");
    controls.children[1].setAttribute("aria-label", "Zoom out");
    this.status = html("div", "gx-status");
    this.status.setAttribute("role", "status");
    viewport.append(
      controls,
      this.status,
      html(
        "div",
        "gx-hint",
        "Scroll to read / Ctrl+scroll to zoom / Drag to pan / Click a block to unfold",
      ),
    );
    body.append(viewport);
    const key = html("div", "gx-key");
    key.append(
      html("span", "", "Within a row: frequent options near the center"),
      html("span", "", "Badges: documents containing this role, not model confidence"),
      html(
        "span",
        "",
        "Select a paper to trace its path; side arrows mark skips or reordered roles",
      ),
    );
    this.root.append(toolbar, legend, body, key);
    this.host.replaceChildren(this.root);
    this.draw();
    this.bindPan();
    let width = this.canvas.clientWidth,
      height = this.canvas.clientHeight;
    this.observer = new ResizeObserver(() => {
      if (width === this.canvas.clientWidth && height === this.canvas.clientHeight) return;
      width = this.canvas.clientWidth;
      height = this.canvas.clientHeight;
      if (this.evidence) this.draw();
      if (this.selected) this.focusNode(this.selected);
      else this.frame(anchor);
    });
    this.observer.observe(viewport);
    if (this.selected) this.focusNode(this.selected);
    else this.frame(anchor);
  }

  private navigate(section: string | null): void {
    if (section === null) this.history = [];
    this.section = section;
    this.selected = null;
    this.evidence = null;
    this.query = "";
    this.filter = "all";
    this.render();
  }

  private back(): void {
    this.history.pop();
    this.navigate(this.history.at(-1)?.group.group_id ?? null);
  }

  private draw(): void {
    this.world.replaceChildren();
    const lookup = new Map(this.graph.nodes.map((n) => [n.group.group_id, n]));
    const rowNodes = new Map<number, ExplorerNode[]>();
    for (const node of this.graph.nodes) {
      const row = rowNodes.get(node.row) ?? [];
      row.push(node);
      rowNodes.set(node.row, row);
    }
    const left = Math.min(...this.graph.nodes.map((node) => node.x), this.graph.centerX);
    const right = Math.max(
      ...this.graph.nodes.map((node) => node.x + NODE_WIDTH),
      this.graph.centerX,
    );
    const anchor = this.history.at(-1);
    const top = this.graph.nodes[0]?.y ?? (anchor ? anchor.y + NODE_HEIGHT + 48 : BOARD_TOP);
    const heading = svg("text", {
      x: this.graph.centerX,
      y: top - 24,
      "text-anchor": "middle",
      class: "gx-board-label",
    });
    heading.textContent = this.graph.nodes.length
      ? "READ TOP TO BOTTOM"
      : "No mapped passages in this section";
    this.world.append(heading);
    if (this.graph.nodes.length)
      this.world.append(
        svg("line", {
          x1: this.graph.centerX,
          x2: this.graph.centerX,
          y1: top - 12,
          y2: this.graph.nodes.at(-1)!.y + NODE_HEIGHT + 12,
          class: "gx-reading-axis",
        }),
      );
    for (const [index, row] of rowNodes) {
      const rowLeft = Math.min(...row.map((node) => node.x));
      const rowRight = Math.max(...row.map((node) => node.x + NODE_WIDTH));
      this.world.append(
        svg("rect", {
          x: rowLeft - 5,
          y: row[0].y - 5,
          width: rowRight - rowLeft + 10,
          height: NODE_HEIGHT + 10,
          rx: 4,
          class: "gx-row",
        }),
      );
      const label = svg("text", {
        x: left - 22,
        y: row[0].y + NODE_HEIGHT / 2 + 4,
        "text-anchor": "end",
        class: "gx-row-number",
      });
      label.textContent = String(index + 1).padStart(2, "0");
      this.world.append(label);
    }
    const defs = svg("defs");
    const colors = [...PAPER_COLORS, "#495057"];
    colors.forEach((color, index) => {
      const marker = svg("marker", {
        id: `gx-arrow-${index}`,
        viewBox: "0 0 8 8",
        refX: 8,
        refY: 4,
        markerWidth: 4,
        markerHeight: 4,
        orient: "auto",
      });
      marker.append(svg("path", { d: "M0,0 L8,4 L0,8 Z", fill: color }));
      defs.append(marker);
    });
    this.world.append(defs);
    for (const [edgeIndex, edge] of collapseEdges(this.graph.edges).entries()) {
      const source = lookup.get(edge.source)!;
      const target = lookup.get(edge.target)!;
      const shared = edge.papers.length > 1;
      const coloredPaper = this.paper || (shared ? "" : edge.papers[0]);
      const index = coloredPaper
        ? this.model.papers.findIndex((p) => p.paper_id === coloredPaper) % PAPER_COLORS.length
        : PAPER_COLORS.length;
      const x1 = source.x + NODE_WIDTH / 2;
      const y1 = source.y + NODE_HEIGHT;
      const x2 = target.x + NODE_WIDTH / 2;
      const y2 = target.y;
      const jump = target.row - source.row > 1;
      const returning = target.row <= source.row;
      const rail = returning ? left - 18 - (edgeIndex % 4) * 6 : right + 18 + (edgeIndex % 4) * 6;
      // Long jumps and reversed order travel in row gaps and outside the board,
      // never through intervening blocks. Original edge direction is unchanged.
      const pathData = returning
        ? `M${x1},${source.y} V${source.y - ROW_GAP / 2} H${rail} V${target.y + NODE_HEIGHT + ROW_GAP / 2} H${x2} V${target.y + NODE_HEIGHT}`
        : jump
          ? `M${x1},${y1} V${y1 + ROW_GAP / 2} H${rail} V${y2 - ROW_GAP / 2} H${x2} V${y2}`
          : `M${x1},${y1} C${x1},${y1 + ROW_GAP / 2} ${x2},${y2 - ROW_GAP / 2} ${x2},${y2}`;
      const path = svg("path", {
        d: pathData,
        stroke: colors[index],
        fill: "none",
        "stroke-width": this.paper ? 2.5 : shared ? 3 : 1.8,
        "marker-end": `url(#gx-arrow-${index})`,
        class:
          "gx-edge" +
          (shared ? " shared" : "") +
          (jump ? " jump" : "") +
          (returning ? " order-exception" : ""),
      });
      path.dataset.papers = JSON.stringify(edge.papers);
      path.dataset.source = edge.source;
      path.dataset.target = edge.target;
      path.dataset.skippedRows = String(Math.max(0, target.row - source.row - 1));
      const title = svg("title");
      title.textContent =
        edge.papers
          .map((id) => this.model.papers.find((p) => p.paper_id === id)!.title)
          .join(", ") +
        ": reading order" +
        (returning
          ? " (differs from board order)"
          : jump
            ? ` (skips ${target.row - source.row - 1} board rows)`
            : "");
      path.append(title);
      this.world.append(path);
    }
    const nodes = anchor ? [anchor, ...this.graph.nodes] : this.graph.nodes;
    for (const node of nodes) {
      const structural = this.model.sections.some((g) => g.group_id === node.group.group_id);
      const group = svg("g", {
        transform: `translate(${node.x} ${node.y})`,
        class:
          "gx-node" +
          (node.papers.length === 1 ? " unmatched" : "") +
          (node === anchor ? " gx-anchor" : ""),
        tabindex: 0,
        role: "button",
        "aria-label": `${node.group.overarching_question} (${node.papers.length} of ${this.model.papers.length} documents)`,
        "aria-expanded": String(node === anchor || node.group.group_id === this.evidence),
      });
      group.dataset.id = node.group.group_id;
      group.dataset.row = String(node.row);
      group.dataset.support = String(node.papers.length);
      const title = svg("title");
      title.textContent = node.group.overarching_question;
      group.append(title, svg("rect", { width: NODE_WIDTH, height: NODE_HEIGHT, rx: 3 }));
      const badge = svg("text", { x: 15, y: 22, class: "gx-node-meta" });
      badge.textContent = `${node.papers.length}/${this.model.papers.length} DOCUMENTS / ${node === anchor ? "PARENT" : structural ? "SECTION" : "PARAGRAPH"}`;
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
        if (node === anchor) {
          this.back();
          return;
        }
        this.selected = node.group.group_id;
        this.highlight();
        this.focusNode(
          node.group.group_id,
          () => {
            if (structural) {
              this.history.push(node);
              this.navigate(node.group.group_id);
            } else {
              this.evidence = this.evidence === node.group.group_id ? null : node.group.group_id;
              this.draw();
              [...this.world.querySelectorAll<SVGGElement>(".gx-node")]
                .find((element) => element.dataset.id === node.group.group_id)
                ?.focus({ preventScroll: true });
            }
          },
          structural,
        );
      };
      group.addEventListener("click", select);
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });
      this.world.append(group);
    }
    if (this.evidence) {
      const node = lookup.get(this.evidence)!;
      const width = Math.min(1100, Math.max(300, this.canvas.clientWidth / this.scale - 40));
      const content = svg("foreignObject", {
        x: node.x + NODE_WIDTH / 2 - width / 2,
        y: node.y + NODE_HEIGHT + 20,
        width,
        height: Math.max(
          110,
          Math.min(310, this.canvas.clientHeight / (2 * this.scale) - NODE_HEIGHT / 2 - 45),
        ),
        class: "gx-evidence",
      });
      content.append(renderPassages(this.model, node.group));
      this.world.append(content);
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
              (m.unit_type === "paragraph" ? paper.paragraphs : paper.sections).find(
                (u) => u.id === m.unit_id,
              )?.text ?? ""
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
      const active = node.classList.contains("gx-anchor") || visible.has(node.dataset.id!);
      node.classList.toggle("dimmed", !active);
      node.classList.toggle("selected", node.dataset.id === this.selected);
      node.setAttribute("aria-pressed", String(node.dataset.id === this.selected));
      node.setAttribute("tabindex", active ? "0" : "-1");
    });
    this.world.querySelectorAll<SVGPathElement>(".gx-edge").forEach((edge) => {
      const onPaper = !!this.paper && JSON.parse(edge.dataset.papers!).includes(this.paper);
      const incident =
        !!this.selected &&
        (edge.dataset.source === this.selected || edge.dataset.target === this.selected);
      const show =
        visible.has(edge.dataset.source!) &&
        visible.has(edge.dataset.target!) &&
        (this.paper ? onPaper : incident);
      edge.classList.toggle("visible", show);
      edge.setAttribute("aria-hidden", String(!show));
      edge.classList.toggle("selected", incident);
    });
    this.status.textContent = `${visible.size} of ${this.graph.nodes.length} roles highlighted`;
  }

  private transform(): void {
    this.world.setAttribute("transform", `translate(${this.tx} ${this.ty}) scale(${this.scale})`);
  }
  private fit(): void {
    cancelAnimationFrame(this.animation);
    const box = this.canvas.getBoundingClientRect();
    const bounds = this.world.getBBox();
    const width = Math.max(NODE_WIDTH, bounds.width) + 80;
    const height = Math.max(NODE_HEIGHT, bounds.height) + 100;
    this.scale = Math.min(box.width / width, box.height / height) * 0.94;
    this.tx = (box.width - bounds.width * this.scale) / 2 - bounds.x * this.scale;
    this.ty = (box.height - bounds.height * this.scale) / 2 - bounds.y * this.scale;
    this.transform();
  }
  private frame(anchor?: ExplorerNode): void {
    this.fit();
    // Start at the top at a readable scale; Fit board remains the full overview.
    this.scale = 1;
    this.tx = this.canvas.clientWidth / 2 - this.graph.centerX * this.scale;
    this.ty = this.readingTop() - (anchor?.y ?? this.graph.nodes[0]?.y ?? BOARD_TOP);
    this.transform();
  }
  private readingTop(): number {
    return this.canvas.clientWidth < 600 ? 94 : 60;
  }
  private zoom(
    factor: number,
    x = this.canvas.clientWidth / 2,
    y = this.canvas.clientHeight / 2,
  ): void {
    cancelAnimationFrame(this.animation);
    const next = Math.min(3, Math.max(0.08, this.scale * factor));
    this.tx = x - ((x - this.tx) * next) / this.scale;
    this.ty = y - ((y - this.ty) * next) / this.scale;
    this.scale = next;
    this.transform();
  }
  private focusNode(id: string, after?: () => void, atTop = false): void {
    cancelAnimationFrame(this.animation);
    const node = [...this.graph.nodes, ...this.history.slice(-1)].find(
      (n) => n.group.group_id === id,
    );
    if (!node) return;
    const scale = Math.max(this.scale, 0.8);
    const tx = this.canvas.clientWidth / 2 - (node.x + NODE_WIDTH / 2) * scale;
    const ty = atTop
      ? this.readingTop() - node.y * scale
      : this.canvas.clientHeight / 2 - (node.y + NODE_HEIGHT / 2) * scale;
    const start = { scale: this.scale, tx: this.tx, ty: this.ty };
    const duration = after && !matchMedia("(prefers-reduced-motion: reduce)").matches ? 420 : 0;
    const started = performance.now();
    const tick = (now: number) => {
      const t = duration ? Math.min(1, (now - started) / duration) : 1;
      const ease = t * t * (3 - 2 * t);
      this.scale = start.scale + (scale - start.scale) * ease;
      this.tx = start.tx + (tx - start.tx) * ease;
      this.ty = start.ty + (ty - start.ty) * ease;
      this.transform();
      if (t < 1) this.animation = requestAnimationFrame(tick);
      else after?.();
    };
    this.animation = requestAnimationFrame(tick);
  }
  private bindPan(): void {
    let drag: { x: number; y: number; tx: number; ty: number } | null = null;
    this.canvas.addEventListener(
      "wheel",
      (event) => {
        if ((event.target as Element).closest(".gx-evidence")) return;
        event.preventDefault();
        if (event.ctrlKey || event.metaKey) {
          const box = this.canvas.getBoundingClientRect();
          this.zoom(
            Math.exp(-event.deltaY * 0.0015),
            event.clientX - box.left,
            event.clientY - box.top,
          );
        } else {
          cancelAnimationFrame(this.animation);
          this.tx -= event.shiftKey ? event.deltaY : event.deltaX;
          if (!event.shiftKey) this.ty -= event.deltaY;
          this.transform();
        }
      },
      { passive: false },
    );
    this.canvas.addEventListener("pointerdown", (event) => {
      if ((event.target as Element).closest(".gx-node, .gx-evidence") || event.button !== 0) return;
      cancelAnimationFrame(this.animation);
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
