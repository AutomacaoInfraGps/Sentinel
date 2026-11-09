(function () {
    "use strict";

    const widget = document.getElementById("sofiaWidget");
    if (!widget) return;
    const dedicated = widget.dataset.mode === "dedicated";

    const endpoint = widget.dataset.endpoint;
    const cancelEndpoint = widget.dataset.cancelEndpoint;
    const userKey = (widget.dataset.user || "anon").replace(/[^a-zA-Z0-9_.-]/g, "_");
    const storageKey = `sentinel.sofia.chat.${userKey}.v1`;
    const panelStorageKey = `sentinel.sofia.panel.${userKey}.v1`;
    const conversationStorageKey = `sentinel.sofia.conversation.${userKey}.v1`;
    const pendingStorageKey = `sentinel.sofia.pending.${userKey}.v1`;
    const maxStoredMessages = 50;
    const panel = document.getElementById("sofiaPanel");
    const launcher = document.getElementById("sofiaLauncher");
    const greeting = document.getElementById("sofiaGreeting");
    const closeButton = document.getElementById("sofiaClose");
    const clearButton = document.getElementById("sofiaClear");
    const form = document.getElementById("sofiaForm");
    const input = document.getElementById("sofiaInput");
    const sendButton = document.getElementById("sofiaSend");
    const stopButton = document.getElementById("sofiaStop");
    const messages = document.getElementById("sofiaMessages");
    const status = document.getElementById("sofiaStatus");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let waitingMessage = null;
    let activeRequest = null;

    function createConversationId() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID();
        }
        return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (char) {
            const random = Math.floor(Math.random() * 16);
            const value = char === "x" ? random : ((random & 3) | 8);
            return value.toString(16);
        });
    }

    function loadConversationId() {
        try {
            const stored = window.sessionStorage.getItem(conversationStorageKey);
            if (/^[a-f0-9-]{36}$/i.test(stored || "")) return stored;
            const created = createConversationId();
            window.sessionStorage.setItem(conversationStorageKey, created);
            return created;
        } catch (error) {
            return createConversationId();
        }
    }

    let conversationId = loadConversationId();

    function savePending(request) {
        try {
            window.sessionStorage.setItem(pendingStorageKey, JSON.stringify({
                id: request.id, conversationId, createdAt: Date.now()
            }));
        } catch (error) {
            // Polling still works when browser storage is unavailable.
        }
    }

    function clearPending() {
        try {
            window.sessionStorage.removeItem(pendingStorageKey);
        } catch (error) {
            // Browser storage is optional.
        }
    }

    function renderInlineText(target, text) {
        target.replaceChildren();
        const markup = /`([^`\n]+)`|\*\*([^*\n]+)\*\*/g;
        let position = 0;
        let match;
        while ((match = markup.exec(text)) !== null) {
            target.appendChild(document.createTextNode(text.slice(position, match.index)));
            const node = document.createElement(match[1] !== undefined ? "code" : "strong");
            node.textContent = match[1] !== undefined ? match[1] : match[2];
            target.appendChild(node);
            position = markup.lastIndex;
        }
        target.appendChild(document.createTextNode(text.slice(position)));
    }

    function renderMessageText(target, text) {
        target.replaceChildren();
        const fences = /```([a-zA-Z0-9_+-]*)[ \t]*\r?\n([\s\S]*?)(?:```|$)/g;
        let position = 0;
        let match;
        function paragraph(value) {
            if (!value.trim()) return;
            const node = document.createElement("p");
            renderInlineText(node, value.trim());
            target.appendChild(node);
        }
        while ((match = fences.exec(text)) !== null) {
            paragraph(text.slice(position, match.index));
            const pre = document.createElement("pre");
            if (match[1]) {
                const label = document.createElement("span");
                label.className = "sofia-code-language";
                label.textContent = match[1];
                pre.appendChild(label);
            }
            const code = document.createElement("code");
            code.textContent = match[2].replace(/\n$/, "");
            pre.appendChild(code);
            target.appendChild(pre);
            position = fences.lastIndex;
        }
        paragraph(text.slice(position));
    }

    function reportRequest(state, durationMs) {
        widget.dispatchEvent(new CustomEvent("sofia:request", {detail: {state, durationMs}}));
    }

    function typeAssistantMessage(item) {
        if (!item || item.dataset.typed === "true" || item.dataset.typing === "true") return;

        const textNode = item.querySelector(".sofia-message-body") || item.querySelector("p");
        const fullText = item.dataset.fullText || textNode?.textContent || "";
        if (!textNode || !fullText) return;

        item.dataset.fullText = fullText;
        if (reduceMotion.matches) {
            renderMessageText(textNode, fullText);
            item.dataset.typed = "true";
            return;
        }

        item.dataset.typing = "true";
        item.classList.add("is-typing");
        textNode.textContent = "";
        const typingRun = String((Number(item.dataset.typingRun) || 0) + 1);
        item.dataset.typingRun = typingRun;
        widget.dispatchEvent(new CustomEvent("sofia:speech", {detail: {active: true, message: item}}));

        let position = 0;
        const interval = 22;
        const charsPerStep = Math.max(1, Math.ceil(fullText.length / (8000 / interval)));
        const typeNext = function () {
            if (item.dataset.typingRun !== typingRun) return;
            position = Math.min(fullText.length, position + charsPerStep);
            textNode.textContent = fullText.slice(0, position);
            messages.scrollTop = messages.scrollHeight;

            if (position < fullText.length) {
                window.setTimeout(typeNext, interval);
                return;
            }

            item.classList.remove("is-typing");
            item.dataset.typing = "false";
            item.dataset.typed = "true";
            renderMessageText(textNode, fullText);
            widget.dispatchEvent(new CustomEvent("sofia:speech", {detail: {active: false, message: item}}));
        };
        typeNext();
    }

    function resetWelcomeAnimation() {
        const hasUserMessage = messages.querySelector(".sofia-message-user");
        if (hasUserMessage) return;

        messages.querySelectorAll(".sofia-message-assistant").forEach(function (item) {
            const textNode = item.querySelector(".sofia-message-body") || item.querySelector("p");
            if (!textNode) return;
            item.dataset.typingRun = String((Number(item.dataset.typingRun) || 0) + 1);
            item.dataset.typing = "false";
            item.dataset.typed = "false";
            item.classList.remove("is-typing");
            textNode.textContent = item.dataset.fullText || textNode.textContent;
        });
    }

    function setOpen(open) {
        if (dedicated) return;
        const isNewOpening = open && panel.hidden;
        panel.hidden = !open;
        widget.classList.toggle("is-open", open);
        launcher.setAttribute("aria-expanded", open ? "true" : "false");
        launcher.setAttribute("aria-label", open ? "Fechar SofIA" : "Abrir SofIA");
        savePanelState(open);
        if (open) {
            if (isNewOpening) resetWelcomeAnimation();
            messages.querySelectorAll(".sofia-message-assistant:not([data-typed='true'])").forEach(typeAssistantMessage);
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
        const text = item.dataset.fullText || item.querySelector("p")?.textContent || "";
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
            appendMessage(message.author, message.text, message.type, false, false);
        });
    }

    function appendMessage(author, text, type, persist = true, animate = true) {
        const safeType = normalizeMessageType(type);
        const item = document.createElement("div");
        item.className = `sofia-message sofia-message-${safeType}`;
        item.dataset.fullText = text;

        const authorNode = document.createElement("span");
        authorNode.className = "sofia-message-author";
        authorNode.textContent = author;

        const textNode = document.createElement("div");
        textNode.className = "sofia-message-body";
        renderMessageText(textNode, text);

        item.append(authorNode, textNode);
        messages.appendChild(item);
        messages.scrollTop = messages.scrollHeight;

        if (persist) saveMessages(getCurrentMessages());
        if (safeType === "assistant" && animate) {
            if (!panel.hidden) typeAssistantMessage(item);
        } else {
            item.dataset.typed = "true";
        }
    }

    function showWaitingMessage() {
        if (waitingMessage) return;

        const item = document.createElement("div");
        item.className = "sofia-message sofia-message-assistant sofia-message-waiting";
        item.setAttribute("role", "status");
        item.setAttribute("aria-label", "SofIA está respondendo");

        const authorNode = document.createElement("span");
        authorNode.className = "sofia-message-author";
        authorNode.textContent = "SofIA";

        const dots = document.createElement("p");
        dots.className = "sofia-waiting-dots";
        dots.setAttribute("aria-hidden", "true");
        for (let index = 0; index < 3; index += 1) {
            dots.appendChild(document.createElement("span"));
        }

        item.append(authorNode, dots);
        messages.appendChild(item);
        waitingMessage = item;
        messages.scrollTop = messages.scrollHeight;
    }

    function removeWaitingMessage() {
        if (!waitingMessage) return;
        waitingMessage.remove();
        waitingMessage = null;
    }

    function setBusy(busy) {
        input.disabled = busy;
        sendButton.disabled = busy;
        clearButton.disabled = busy;
        stopButton.hidden = !busy;
        stopButton.disabled = !busy || !!activeRequest?.cancelling;
        widget.setAttribute("aria-busy", busy ? "true" : "false");
        status.classList.remove("is-error");
        status.textContent = "";
        if (busy) {
            showWaitingMessage();
        } else {
            removeWaitingMessage();
        }
    }

    function showError(message) {
        status.classList.add("is-error");
        status.textContent = message;
    }

    async function waitForReply(response, request) {
        let data = await response.json();
        let failures = 0;
        while (response.status === 202) {
            if (data.request_id !== request.id) throw new Error("Identificador de consulta inválido.");
            if (performance.now() - request.started > 540000) {
                throw new Error("O acompanhamento da consulta excedeu o tempo permitido.");
            }
            await new Promise(function (resolve, reject) {
                const signal = request.controller.signal;
                const abort = function () {
                    window.clearTimeout(timer);
                    reject(new DOMException("Consulta interrompida", "AbortError"));
                };
                const timer = window.setTimeout(function () {
                    signal.removeEventListener("abort", abort);
                    resolve();
                }, 1200);
                signal.addEventListener("abort", abort, {once: true});
                if (signal.aborted) abort();
            });
            const controller = new AbortController();
            const abort = function () { controller.abort(); };
            request.controller.signal.addEventListener("abort", abort, {once: true});
            const timer = window.setTimeout(abort, 15000);
            try {
                response = await fetch(`${endpoint}/requests/${encodeURIComponent(request.id)}?conversation_id=${encodeURIComponent(conversationId)}`, {
                    credentials: "same-origin", signal: controller.signal,
                    headers: {"X-Sentinel-Request": "sofia-chat"}
                });
                data = await response.json();
                failures = 0;
            } catch (error) {
                if (request.controller.signal.aborted) throw error;
                failures += 1;
                if (failures >= 3) throw new Error("Não consegui acompanhar a consulta. Ela pode continuar em processamento.");
                response = {status: 202};
                data = {request_id: request.id};
            } finally {
                window.clearTimeout(timer);
                request.controller.signal.removeEventListener("abort", abort);
            }
        }
        return {response, data};
    }

    stopButton.addEventListener("click", async function () {
        const request = activeRequest;
        if (!request || request.cancelling) return;
        request.cancelling = true;
        clearPending();
        stopButton.disabled = true;
        request.controller.abort();
        removeWaitingMessage();
        status.classList.remove("is-error");
        status.textContent = "Confirmando cancelamento...";
        reportRequest("cancelling");

        const controller = new AbortController();
        const failure = "Nao foi possivel confirmar o cancelamento no n8n. A execucao pode continuar.";
        let timeout;
        try {
            // Race also bounds response-body parsing, even if fetch ignores abort.
            const deadline = new Promise((_, reject) => {
                timeout = window.setTimeout(function () {
                    reject(new Error(failure));
                    controller.abort();
                }, 15000);
            });
            const result = await Promise.race([(async function () {
                if (!cancelEndpoint) throw new Error(failure);
                const response = await fetch(cancelEndpoint, {
                    method: "POST",
                    credentials: "same-origin",
                    signal: controller.signal,
                    headers: {
                        "Content-Type": "application/json",
                        "X-Sentinel-Request": "sofia-chat"
                    },
                    body: JSON.stringify({request_id: request.id})
                });
                const data = await response.json();
                const message = typeof data.message === "string" ? data.message.trim() : "";
                if (!response.ok) {
                    const errorMessage = message || (typeof data.error === "string" ? data.error : "");
                    throw new Error(errorMessage ? `${errorMessage} ${failure}` : failure);
                }
                if (typeof data.cancelled !== "boolean" || !message) throw new Error(failure);
                return {cancelled: data.cancelled, message: data.cancelled ? "Consulta cancelada." : message};
            })(), deadline]);
            if (activeRequest !== request) return;
            activeRequest = null;
            setBusy(false);
            appendMessage("SofIA", result.message, "assistant", true, false);
            status.classList.toggle("is-error", !result.cancelled);
            status.textContent = result.message;
            reportRequest(result.cancelled ? "cancelled" : "cancel-unconfirmed", performance.now() - request.started);
        } catch (error) {
            if (activeRequest !== request) return;
            activeRequest = null;
            setBusy(false);
            const message = error.name === "AbortError" ? failure :
                (error.message?.includes(failure) ? error.message : failure);
            appendMessage("SofIA", message, "assistant", true, false);
            showError(message);
            reportRequest("cancel-unconfirmed", performance.now() - request.started);
        } finally {
            window.clearTimeout(timeout);
            if (!activeRequest) input.focus();
        }
    });

    if (launcher) launcher.addEventListener("click", function () {
        setOpen(panel.hidden);
    });
    if (greeting) {
        greeting.addEventListener("click", function () { setOpen(true); });
    }
    if (closeButton) closeButton.addEventListener("click", function () { setOpen(false); });
    clearButton.addEventListener("click", function () {
        try {
            window.sessionStorage.removeItem(storageKey);
            clearPending();
            conversationId = createConversationId();
            window.sessionStorage.setItem(conversationStorageKey, conversationId);
        } catch (error) {
            // Nada a fazer: o historico visual ainda sera limpo abaixo.
        }
        messages.textContent = "";
        appendMessage("SofIA", "Olá, eu sou a SofIA, assistente virtual do Sentinel. Como posso te ajudar?", "assistant");
        status.classList.remove("is-error");
        status.textContent = "";
        reportRequest("reset");
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
        if (!message || activeRequest || sendButton.disabled) return;
        if (message.length > 1000) {
            showError("A mensagem deve ter ate 1000 caracteres.");
            return;
        }

        const requestStarted = performance.now();
        const request = {id: createConversationId(), controller: new AbortController(),
            cancelling: false, started: requestStarted};
        activeRequest = request;
        appendMessage("Você", message, "user");
        input.value = "";
        input.style.height = "auto";
        setBusy(true);
        reportRequest("pending");

        savePending(request);
        followRequest(request, fetch(endpoint, {
                method: "POST",
                credentials: "same-origin",
                signal: request.controller.signal,
                headers: {
                    "Content-Type": "application/json",
                    "X-Sentinel-Request": "sofia-chat"
                },
                body: JSON.stringify({
                    message: message,
                    conversation_id: conversationId,
                    request_id: request.id,
                    async: true
                })
            }));
    });

    async function followRequest(request, initialResponse) {
        try {
            let response = await initialResponse;
            const contentType = response.headers.get("content-type") || "";
            const result = contentType.includes("application/json") ? await waitForReply(response, request) : {response, data: {}};
            response = result.response;
            const data = result.data;
            if (activeRequest !== request || request.cancelling) return;
            clearPending();
            if (!response.ok) {
                const requestError = new Error(data.error || "Não foi possível falar com a SofIA.");
                requestError.assistantReply = data.reply ||
                    "Não consegui falar com o Sentinel neste momento. Tente novamente em instantes.";
                throw requestError;
            }

            activeRequest = null;
            setBusy(false);
            appendMessage("SofIA", data.reply, "assistant");
            reportRequest(data.cancelled ? "cancelled" : "success", performance.now() - request.started);
            input.focus();
        } catch (error) {
            if (activeRequest !== request || request.cancelling) return;
            activeRequest = null;
            setBusy(false);
            appendMessage(
                "SofIA",
                error.assistantReply ||
                    "Não consegui concluir sua solicitação neste momento. Tente novamente em instantes.",
                "assistant"
            );
            showError(error.message || "Erro de comunicação com a SofIA.");
            reportRequest("error", performance.now() - request.started);
            input.focus();
        }
    }

    function restorePending() {
        let saved;
        try {
            saved = JSON.parse(window.sessionStorage.getItem(pendingStorageKey));
        } catch (error) {
            clearPending();
            return;
        }
        if (!saved) return;
        const age = Date.now() - saved.createdAt;
        if (saved.conversationId !== conversationId || !/^[a-f0-9-]{36}$/i.test(saved.id || "") ||
                !Number.isFinite(age) || age < 0 || age >= 540000) {
            clearPending();
            return;
        }
        const request = {id: saved.id, controller: new AbortController(),
            cancelling: false, started: performance.now() - age};
        activeRequest = request;
        setBusy(true);
        reportRequest("pending");
        followRequest(request, Promise.resolve(new Response(JSON.stringify({request_id: request.id}), {
            status: 202, headers: {"Content-Type": "application/json"}
        })));
    }

    restoreMessages();
    if (dedicated) {
        messages.scrollTop = messages.scrollHeight;
        messages.querySelectorAll(".sofia-message-assistant:not([data-typed='true'])").forEach(typeAssistantMessage);
    } else if (shouldRestorePanelOpen()) setOpen(true);
    restorePending();
})();

