// Render HTML sent from Python and report clicks on [data-act] elements as a
// one-shot "event" trigger value: {act, val}. [data-copy] buttons copy their
// text to the clipboard without a rerun.
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;

  let root = parentElement.querySelector(".pg-root");
  if (!root) {
    root = document.createElement("div");
    root.className = "pg-root";
    parentElement.appendChild(root);
  }
  // Only touch the DOM when the markup changed, so hover/focus survive reruns.
  if (root.__html !== data.html) {
    root.innerHTML = data.html;
    root.__html = data.html;
  }

  root.onclick = (ev) => {
    const cp = ev.target.closest("[data-copy]");
    if (cp) {
      const label = cp.dataset.label || cp.textContent;
      cp.dataset.label = label;
      navigator.clipboard.writeText(cp.dataset.copy).then(() => {
        cp.textContent = "Copied";
        setTimeout(() => { cp.textContent = label; }, 1500);
      });
      return;
    }
    const el = ev.target.closest("[data-act]");
    if (!el || el.hasAttribute("disabled")) return;
    setTriggerValue("event", { act: el.dataset.act, val: el.dataset.val });
  };
  root.onkeydown = (ev) => {
    const row = ev.target.closest("tr[data-act]");
    if (row && (ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault();
      setTriggerValue("event", { act: row.dataset.act, val: row.dataset.val });
    }
  };
}
