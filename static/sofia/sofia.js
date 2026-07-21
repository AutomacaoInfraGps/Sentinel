(function () {
    "use strict";

    const widget = document.getElementById("sofiaWidget");
    if (!widget) return;

    const endpoint = widget.dataset.endpoint;
    const userKey = (widget.dataset.user || "anon").replace(/[^a-zA-Z0-9_.-]/g, "_");
    const storageKey = `sentinel.sofia.chat.${userKey}.v1`;
    const panelStorageKey = `sentinel.sofia.panel.${userKey}.v1`;
    const maxStoredMessages = 50;
    const panel = document.getElementById("sofiaPanel");
    const launcher = document.getElementById("sofiaLauncher");
    const closeButton = document.getElementById("sofiaClose");
    const clearButton = document.getElementById("sofiaClear");
    const form = document.getElementById("sofiaForm");
    const input = document.getElementById("sofiaInput");
    const sendButton = document.getElementById("sofiaSend");
    const messages = document.getElementById("sofiaMessages");
    const status = document.getElementById("sofiaStatus");

    function setOpen(open) {
        panel.hidden = !open;
        launcher.setAttribute("aria-expanded", open ? "true" : "false");
        launcher.setAttribute("aria-label", open ? "Fechar SofIA" : "Abrir SofIA");
        savePanelState(open);
        if (open) {
            input.focus();
            messages.scrollTop = messages.scrollHeight;
        } else {
            launcher.focus();
        }
    }

    function getStoredMessages() {
        try {
            const raw = window.sessionStorage.getItem(storageKey);
            const parsed = raw ? JSON.parse(raw) : null;
            return Array.isArray(parsed) ? parsed : null;
        } catch (error) {
            try {
                window.sessionStorage.removeItem(storageKey);
            } catch (removeError) {
                // Storage bloqueado: apenas segue sem restaurar historico.
            }
            return null;
        }
    }

    function saveMessages(history) {
        try {
            window.sessionStorage.setItem(storageKey, JSON.stringify(history.slice(-maxStoredMessages)));
        } catch (error) {
            // Sem espaco ou sessionStorage indisponivel: o chat continua funcionando sem persistencia.
        }
    }

    function savePanelState(open) {
        try {
            window.sessionStorage.setItem(panelStorageKey, open ? "open" : "closed");
        } catch (error) {
            // Mantem a navegacao normal mesmo se o navegador bloquear storage.
        }
    }

    function shouldRestorePanelOpen() {
        try {
            return window.sessionStorage.getItem(panelStorageKey) === "open";
        } catch (error) {
            return false;
        }
    }

    function normalizeMessageType(type) {
        return type === "user" ? "user" : "assistant";
    }

    function messageFromElement(item) {
        const type = item.classList.contains("sofia-message-user") ? "user" : "assistant";
        const author = item.querySelector(".sofia-message-author")?.textContent || (type === "user" ? "Você" : "SofIA");
        const text = item.querySelector("p")?.textContent || "";
        return { author, text, type };
    }

    function getCurrentMessages() {
        return Array.from(messages.querySelectorAll(".sofia-message")).map(messageFromElement).filter(function (message) {
            return message.text.trim();
        });
    }

    function restoreMessages() {
        const history = getStoredMessages();
        if (!history || !history.length) {
            saveMessages(getCurrentMessages());
            return;
        }

        messages.textContent = "";
        history.forEach(function (message) {
            appendMessage(message.author, message.text, message.type, false);
        });
    }

    function appendMessage(author, text, type, persist = true) {
        const safeType = normalizeMessageType(type);
        const item = document.createElement("div");
        item.className = `sofia-message sofia-message-${safeType}`;

        const authorNode = document.createElement("span");
        authorNode.className = "sofia-message-author";
        authorNode.textContent = author;

        const textNode = document.createElement("p");
        textNode.textContent = text;

        item.append(authorNode, textNode);
        messages.appendChild(item);
        messages.scrollTop = messages.scrollHeight;

        if (persist) saveMessages(getCurrentMessages());
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
    clearButton.addEventListener("click", function () {
        try {
            window.sessionStorage.removeItem(storageKey);
        } catch (error) {
            // Nada a fazer: o historico visual ainda sera limpo abaixo.
        }
        messages.textContent = "";
        appendMessage("SofIA", "Olá, eu sou a SofIA, assistente virtual do Sentinel. Como posso te ajudar?", "assistant");
        status.classList.remove("is-error");
        status.textContent = "";
        input.focus();
    });

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

    restoreMessages();
    if (shouldRestorePanelOpen()) setOpen(true);
})();

