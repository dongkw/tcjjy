const scrollStateKey = "aiTraderScrollRestore";

window.addEventListener("DOMContentLoaded", () => {
  const raw = sessionStorage.getItem(scrollStateKey);
  if (!raw) {
    return;
  }
  sessionStorage.removeItem(scrollStateKey);
  try {
    const state = JSON.parse(raw);
    if (state && state.pathname === window.location.pathname && Number.isFinite(state.y)) {
      window.scrollTo({ top: state.y, left: 0, behavior: "instant" });
    }
  } catch {
    return;
  }
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  sessionStorage.setItem(
    scrollStateKey,
    JSON.stringify({
      pathname: window.location.pathname,
      y: window.scrollY,
    })
  );
  const button = form.querySelector("button[type='submit']");
  if (button) {
    button.disabled = true;
    button.dataset.originalText = button.textContent || "";
    button.textContent = "执行中";
  }
});

document.addEventListener("change", (event) => {
  const checkbox = event.target;
  if (!(checkbox instanceof HTMLInputElement)) {
    return;
  }
  if (checkbox.name === "codes" && checkbox.form?.id === "watchlist-refresh-form") {
    const row = checkbox.closest("tr");
    const mirror = row?.querySelector("input.mirror-checkbox[value='" + checkbox.value + "']");
    if (mirror instanceof HTMLInputElement) {
      mirror.checked = checkbox.checked;
    }
  }
  if (!checkbox.classList.contains("select-all")) {
    return;
  }
  const table = checkbox.closest("table");
  if (!table) {
    return;
  }
  for (const item of table.querySelectorAll("tbody input[type='checkbox'][name='codes']")) {
    item.checked = checkbox.checked;
    item.dispatchEvent(new Event("change", { bubbles: false }));
  }
});
