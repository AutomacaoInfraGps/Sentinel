(function () {
    "use strict";

    const widget = document.getElementById("sofiaWidget");
    const canvas = document.getElementById("sofiaAvatarAnimation");
    const button = document.getElementById("sofiaAnimationToggle");
    if (!widget || !canvas || !button) return;
    const mount = canvas.parentElement;
    const thoughtBubble = document.getElementById("sofiaThoughtBubble");
    const context = canvas.getContext("2d");
    if (!context) { button.hidden = true; return; }
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const preferenceKey = "sentinel.sofia.animation.v1";
    const images = {};
    const speaking = new Set();
    const poses = {
        idle: {frames: ["idle"], interval: 700},
        thinking: {frames: ["thinkingA", "thinkingB"], interval: 520},
        responding: {frames: ["respondingA", "respondingB"], interval: 380},
        cancelling: {frames: ["idle"], interval: 700},
        error: {frames: ["idle"], interval: 700}
    };
    const labels = {idle: "Em espera", thinking: "Consultando", responding: "Respondendo", cancelling: "Cancelando", error: "Falha na consulta"};
    let enabled = true;
    try { enabled = localStorage.getItem(preferenceKey) !== "paused"; } catch (_) { /* Session-only preference. */ }
    let loaded = false;
    let loading = false;
    let failed = false;
    let visible = true;
    let requestState = "idle";
    let state = "idle";
    let frame = 0;
    let timer = null;
    let reactionTimer = null;

    function pauseLoop() {
        window.clearTimeout(timer);
        timer = null;
    }

    function resizeCanvas() {
        const bounds = mount.getBoundingClientRect();
        if (!bounds.width || !bounds.height) return;
        const density = Math.min(window.devicePixelRatio || 1, 3);
        // Match CSS pixels times DPR; avoid upscaling beyond native source detail.
        const scale = Math.min(density, 937 / bounds.width, 1678 / bounds.height);
        const width = Math.max(1, Math.round(bounds.width * scale));
        const height = Math.max(1, Math.round(bounds.height * scale));
        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width;
            canvas.height = height;
        }
    }

    function draw() {
        resizeCanvas();
        const pose = poses[state];
        const key = pose.frames[frame % pose.frames.length];
        const image = images[key];
        // Full-resolution individual frames use the same contain framing as the portrait/video.
        const scale = Math.min(canvas.width / image.naturalWidth, canvas.height / image.naturalHeight);
        const crossed = key === "thinkingA" || key === "thinkingB";
        // The crossed-arms render has less top padding; register head/boots to the portrait.
        const framing = crossed ? 0.956 : 1;
        const width = image.naturalWidth * scale * framing;
        const height = image.naturalHeight * scale * framing;
        context.clearRect(0, 0, canvas.width, canvas.height);
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = "high";
        context.drawImage(image, (canvas.width - width) / 2,
            (canvas.height - height) / 2 + (crossed ? canvas.height * 0.026 : 0), width, height);
        canvas.dataset.frame = key;
        canvas.dataset.sourceWidth = image.naturalWidth;
        canvas.dataset.sourceHeight = image.naturalHeight;
    }

    function loadFrames() {
        if (loading || loaded || failed || !enabled || reduceMotion.matches) return;
        loading = true;
        let sources;
        try { sources = JSON.parse(canvas.dataset.frames); }
        catch (_) { failed = true; loading = false; return; }
        Promise.all(["idle", "thinkingA", "thinkingB", "respondingA", "respondingB"].map(function (key) {
            return new Promise(function (resolve, reject) {
                const image = new Image();
                image.onload = function () {
                    if (image.naturalWidth < 720 || image.naturalHeight < 1280) {
                        reject(new Error("Frame abaixo da resolucao minima"));
                        return;
                    }
                    images[key] = image;
                    resolve();
                };
                image.onerror = reject;
                image.src = sources[key];
            });
        })).then(function () { loaded = true; loading = false; refresh(); },
            function () { failed = true; loading = false; refresh(); });
    }

    function refresh() {
        pauseLoop();
        loadFrames();
        const allowed = enabled && !reduceMotion.matches && loaded && !failed;
        button.disabled = reduceMotion.matches || failed;
        button.setAttribute("aria-pressed", String(allowed));
        button.setAttribute("aria-label", reduceMotion.matches ? "Animações desativadas pela preferência de movimento reduzido" :
            allowed ? "Pausar animações do avatar" : "Ativar animações do avatar");
        button.querySelector("i").className = allowed ? "bi bi-pause" : "bi bi-play";
        mount.dataset.avatarState = state;
        mount.style.setProperty("--sofia-motion-play", document.hidden || !visible ? "paused" : "running");
        canvas.style.animationPlayState = document.hidden || !visible ? "paused" : "running";
        const show = allowed && !mount.classList.contains("is-video-visible");
        if (thoughtBubble) thoughtBubble.hidden = state !== "thinking" || mount.classList.contains("is-video-visible");
        canvas.hidden = !show;
        mount.classList.toggle("has-avatar-animation", show);
        if (!show) return;
        draw();
        if (document.hidden || !visible) return;
        const tick = function () {
            frame += 1;
            draw();
            timer = window.setTimeout(tick, poses[state].interval);
        };
        if (poses[state].frames.length > 1) timer = window.setTimeout(tick, poses[state].interval);
    }

    function chooseState() {
        let next = requestState;
        if (!["thinking", "cancelling", "error"].includes(next)) next = speaking.size ? "responding" : next;
        const changed = next !== state;
        if (changed) { state = next; frame = 0; }
        refresh();
        if (changed) widget.dispatchEvent(new CustomEvent("sofia:avatar-state", {detail: {state, label: labels[state]}}));
    }

    widget.addEventListener("sofia:request", function (event) {
        window.clearTimeout(reactionTimer);
        const incoming = event.detail.state;
        if (incoming === "pending") requestState = "thinking";
        else if (incoming === "cancelling") requestState = "cancelling";
        else if (incoming === "success") {
            requestState = "responding";
            reactionTimer = window.setTimeout(function () { requestState = "idle"; chooseState(); }, 1800);
        } else if (incoming === "error" || incoming === "cancel-unconfirmed") {
            requestState = "error";
            reactionTimer = window.setTimeout(function () { requestState = "idle"; chooseState(); }, 3000);
        } else {
            requestState = "idle";
            speaking.clear();
        }
        chooseState();
    });
    widget.addEventListener("sofia:speech", function (event) {
        if (event.detail.active) speaking.add(event.detail.message);
        else speaking.delete(event.detail.message);
        // Cleared or replaced chat messages must never keep the avatar talking.
        speaking.forEach(message => { if (!message.isConnected) speaking.delete(message); });
        chooseState();
    });
    mount.addEventListener("sofia:avatar-video", refresh);
    button.addEventListener("click", function () {
        enabled = !enabled;
        try { localStorage.setItem(preferenceKey, enabled ? "enabled" : "paused"); } catch (_) { /* No persistence. */ }
        refresh();
    });
    document.addEventListener("visibilitychange", refresh);
    reduceMotion.addEventListener("change", refresh);
    if ("IntersectionObserver" in window) {
        new IntersectionObserver(function (entries) { visible = entries[0].isIntersecting; refresh(); }).observe(mount);
    }
    if ("ResizeObserver" in window) new ResizeObserver(refresh).observe(mount);
    window.addEventListener("resize", refresh);
    refresh();
})();
