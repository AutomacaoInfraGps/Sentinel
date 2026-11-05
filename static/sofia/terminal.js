(function () {
    "use strict";

    const widget = document.getElementById("sofiaWidget");
    if (!widget || widget.dataset.mode !== "dedicated") return;
    const input = document.getElementById("sofiaInput");
    const phase = document.getElementById("sofiaPhase");
    const conversationState = document.getElementById("sofiaConversationState");
    const roundTrip = document.getElementById("sofiaRoundTrip");
    const events = document.getElementById("sofiaTerminalEvents");
    const count = document.getElementById("sofiaCharacterCount");
    const status = document.getElementById("sofiaStatus");
    const attach = document.getElementById("sofiaAttach");
    const picker = document.getElementById("sofiaLogFile");
    const dialog = document.getElementById("sofiaLogDialog");
    const preview = document.getElementById("sofiaLogPreview");
    const notice = document.getElementById("sofiaLogNotice");
    let pendingSince = null;
    let timer = null;
    let filename = "";

    function updateCount() { count.textContent = `${input.value.length} / 1000`; }
    function seconds(value) { return `${(value / 1000).toLocaleString("pt-BR", {maximumFractionDigits: 1})} s`; }
    function addEvent(text) {
        const item = document.createElement("li");
        const time = new Date().toLocaleTimeString("pt-BR", {timeZone: "America/Sao_Paulo"});
        item.textContent = `${time} ${text}`;
        events.appendChild(item);
        while (events.children.length > 3) events.firstElementChild.remove();
    }
    function error(text) {
        status.classList.add("is-error");
        status.textContent = text;
    }

    input.addEventListener("input", updateCount);
    widget.addEventListener("sofia:request", function (event) {
        const state = event.detail.state;
        const busy = state === "pending" || state === "cancelling";
        widget.querySelectorAll("[data-sofia-prompt]").forEach(button => { button.disabled = busy; });
        attach.disabled = busy;
        window.clearInterval(timer);
        timer = null;
        if (state === "cancelling") {
            phase.textContent = "Cancelando";
            conversationState.textContent = "Confirmando cancelamento...";
            addEvent("Cancelamento solicitado");
        } else if (busy) {
            pendingSince = performance.now();
            phase.textContent = "Consultando";
            conversationState.textContent = "Processando... 0 s";
            timer = window.setInterval(function () {
                conversationState.textContent = `Processando... ${seconds(performance.now() - pendingSince)}`;
            }, 250);
            addEvent("Consulta enviada");
        } else {
            pendingSince = null;
            const label = state === "cancelled" ? "Cancelamento confirmado" :
                state === "cancel-unconfirmed" ? "Cancelamento nao confirmado" :
                state === "error" ? "Falha na consulta" : "Em espera";
            phase.textContent = label;
            conversationState.textContent = label;
            if (["success", "error", "cancelled", "cancel-unconfirmed"].includes(state)) {
                roundTrip.textContent = seconds(event.detail.durationMs);
                addEvent(state === "success" ? "Resposta recebida" :
                    state === "error" ? "Falha ao receber resposta" : label);
            } else {
                roundTrip.textContent = "--";
                events.replaceChildren();
                addEvent("Nova conversa");
            }
        }
        updateCount();
    });

    widget.querySelectorAll("[data-sofia-prompt]").forEach(function (button) {
        button.addEventListener("click", function () {
            input.value = button.dataset.sofiaPrompt;
            input.dispatchEvent(new Event("input"));
            input.focus();
        });
    });

    attach.addEventListener("click", function () { picker.click(); });
    picker.addEventListener("change", async function () {
        const file = picker.files[0];
        picker.value = "";
        if (!file) return;
        if (!/\.(txt|log|json)$/i.test(file.name) || file.size > 65536) {
            error("Selecione um arquivo .txt, .log ou .json de ate 64 KB.");
            return;
        }
        try {
            const text = new TextDecoder("utf-8", {fatal: true}).decode(await file.arrayBuffer());
            if (text.includes("\0")) throw new Error("binary");
            filename = file.name;
            document.getElementById("sofiaLogName").textContent = filename;
            preview.value = text;
            notice.textContent = "Revise e remova credenciais. Para logs grandes, selecione um trecho de ate 1000 caracteres, incluindo sua mensagem.";
            dialog.showModal();
        } catch (_) {
            error("Nao foi possivel abrir o arquivo como texto UTF-8.");
        }
    });
    document.getElementById("sofiaLogClose").addEventListener("click", function () { dialog.close(); });
    document.getElementById("sofiaLogUse").addEventListener("click", function () {
        const selected = preview.value.slice(preview.selectionStart, preview.selectionEnd) || preview.value;
        const snippet = `Log (${filename}):\n\`\`\`text\n${selected}\n\`\`\``;
        const draft = [input.value.trim(), snippet].filter(Boolean).join("\n\n");
        if (!selected.trim()) {
            notice.textContent = "O trecho selecionado esta vazio.";
            return;
        }
        if (draft.length > 1000) {
            notice.textContent = `O total seria ${draft.length} caracteres. Selecione um trecho menor para caber no limite de 1000.`;
            return;
        }
        input.value = draft;
        input.dispatchEvent(new Event("input"));
        dialog.close();
        preview.value = "";
        input.focus();
    });
    updateCount();
})();
