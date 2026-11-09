(function () {
    "use strict";

    const key = "sentinel.theme.v1";
    const modes = new Set(["light", "dark", "system"]);
    const system = window.matchMedia("(prefers-color-scheme: dark)");
    let preference = "light";
    try {
        const stored = window.localStorage.getItem(key);
        if (modes.has(stored)) preference = stored;
    } catch (_) {
        // Theme switching still works when storage is blocked.
    }

    function apply() {
        const resolved = preference === "system" ? (system.matches ? "dark" : "light") : preference;
        document.documentElement.dataset.sentinelTheme = resolved;
        document.documentElement.dataset.bsTheme = resolved;
        document.documentElement.dataset.themePreference = preference;
        document.documentElement.style.colorScheme = resolved;
        document.querySelectorAll("[data-theme-choice]").forEach(function (button) {
            button.setAttribute("aria-pressed", String(button.dataset.themeChoice === preference));
        });
        document.dispatchEvent(new CustomEvent("sentinel:themechange", {detail: {preference, resolved}}));
    }

    apply();
    document.addEventListener("DOMContentLoaded", apply);
    document.addEventListener("click", function (event) {
        const button = event.target.closest("[data-theme-choice]");
        if (!button || !modes.has(button.dataset.themeChoice)) return;
        preference = button.dataset.themeChoice;
        try { window.localStorage.setItem(key, preference); } catch (_) { /* Session-only preference. */ }
        apply();
    });
    system.addEventListener("change", function () { if (preference === "system") apply(); });
    window.addEventListener("storage", function (event) {
        if (event.key !== key) return;
        preference = modes.has(event.newValue) ? event.newValue : "light";
        apply();
    });
})();
