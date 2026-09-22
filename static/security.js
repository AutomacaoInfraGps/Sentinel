(function () {
    "use strict";

    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = meta ? meta.content : "";
    const unsafeMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);

    function isSameOrigin(resource) {
        try {
            const value = typeof resource === "string" ? resource : resource.url;
            return new URL(value, window.location.href).origin === window.location.origin;
        } catch (_) {
            return false;
        }
    }

    if (token && window.fetch) {
        const originalFetch = window.fetch.bind(window);
        window.fetch = function (resource, options) {
            const settings = Object.assign({}, options || {});
            const method = String(settings.method || (resource && resource.method) || "GET").toUpperCase();
            if (unsafeMethods.has(method) && isSameOrigin(resource)) {
                const headers = new Headers(settings.headers || (resource && resource.headers) || {});
                headers.set("X-CSRF-Token", token);
                settings.headers = headers;
            }
            return originalFetch(resource, settings);
        };
    }

    if (token && window.XMLHttpRequest) {
        const originalOpen = XMLHttpRequest.prototype.open;
        const originalSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open = function (method, url) {
            this.__sentinelMethod = String(method || "GET").toUpperCase();
            this.__sentinelUrl = url;
            return originalOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function () {
            if (unsafeMethods.has(this.__sentinelMethod) && isSameOrigin(this.__sentinelUrl)) {
                this.setRequestHeader("X-CSRF-Token", token);
            }
            return originalSend.apply(this, arguments);
        };
    }

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!token || !(form instanceof HTMLFormElement)) return;
        const method = String(form.method || "GET").toUpperCase();
        if (!unsafeMethods.has(method) || !isSameOrigin(form.action || window.location.href)) return;
        let input = form.querySelector('input[name="csrf_token"]');
        if (!input) {
            input = document.createElement("input");
            input.type = "hidden";
            input.name = "csrf_token";
            form.appendChild(input);
        }
        input.value = token;
    }, true);
}());
