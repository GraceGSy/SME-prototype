export function html<K extends keyof HTMLElementTagNameMap>(tag: K, className = "", text = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}
export function button(label: string, action: () => void, className = "gx-button") {
  const node = html("button", className, label);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}
