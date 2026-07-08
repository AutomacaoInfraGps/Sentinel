(function () {
    "use strict";

    const widget = document.getElementById("sofiaWidget");
    if (!widget) return;

    const endpoint = widget.dataset.endpoint;
    const panel = document.getElementById("sofiaPanel");
    const launcher = document.getElementById("sofiaLauncher");
    const closeButton = document.getElementById("sofiaClose");
    const form = document.getElementById("sofiaForm");
    const input = document.getElementById("sofiaInput");
    const sendButton = document.getElementById("sofiaSend");
    const messages = document.getElementById("sofiaMessages");
    const status = document.getElementById("sofiaStatus");

    function setOpen(open) {
        panel.hidden = !open;
        launcher.setAttribute("aria-expanded", open ? "true" : "false");
        launcher.setAttribute("aria-label", open ? "Fechar SofIA" : "Abrir SofIA");
        if (open) {
            input.focus();
            messages.scrollTop = messages.scrollHeight;
        } else {
            launcher.focus();
        }
    }

    function appendMessage(author, text, type) {
        const item = document.createElement("div");
        item.className = `sofia-message sofia-message-${type}`;

        const authorNode = document.createElement("span");
        authorNode.className = "sofia-message-author";
        authorNode.textContent = author;

        const textNode = document.createElement("p");
        textNode.textContent = text;

        item.append(authorNode, textNode);
        messages.appendChild(item);
        messages.scrollTop = messages.scrollHeight;
    }

    function setBusy(busy) {
        input.disabled = busy;
        sendButton.disabled = busy;
        status.classList.remove("is-error");
        status.textContent = busy ? "SofIA está respondendo..." : "";
    }

    function showError(message) {
        status.classList.add("is-error");
        status.textContent = message;
    }

    launcher.addEventListener("click", function () {
        setOpen(panel.hidden);
    });
    closeButton.addEventListener("click", function () { setOpen(false); });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !panel.hidden) setOpen(false);
    });

    input.addEventListener("input", function () {
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 112)}px`;
    });

    input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        const message = input.value.trim();
        if (!message || sendButton.disabled) return;

        appendMessage("Você", message, "user");
        input.value = "";
        input.style.height = "auto";
        setBusy(true);

        try {
            const response = await fetch(endpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-Sentinel-Request": "sofia-chat"
                },
                body: JSON.stringify({ message: message })
            });

            const contentType = response.headers.get("content-type") || "";
            const data = contentType.includes("application/json") ? await response.json() : {};
            if (!response.ok) throw new Error(data.error || "Não foi possível falar com a SofIA.");

            appendMessage("SofIA", data.reply, "assistant");
            setBusy(false);
            input.focus();
        } catch (error) {
            setBusy(false);
            showError(error.message || "Erro de comunicação com a SofIA.");
            input.focus();
        }
    });
})();

