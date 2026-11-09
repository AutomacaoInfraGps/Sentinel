(function () {
    "use strict";

    const video = document.getElementById("sofiaAvatarVideo");
    if (!video) return;

    const mount = video.parentElement;
    const widget = document.getElementById("sofiaWidget");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const hoverPointer = window.matchMedia("(hover: hover) and (pointer: fine)");
    let wantsPlayback = false;
    let failed = false;
    let hideTimer = null;
    let returningToPortrait = false;
    let playAttempt = 0;

    function updateControls() {
        const label = video.paused ? "Reproduzir video com audio"
            : video.muted ? "Ativar audio" : "Pausar video";
        mount.setAttribute("aria-label", "Avatar da SofIA. " + label + ".");
    }

    function stopPlayback() {
        wantsPlayback = false;
        playAttempt += 1;
        video.pause();
        returningToPortrait = true;
        mount.classList.remove("is-video-visible");
        mount.dispatchEvent(new CustomEvent("sofia:avatar-video"));
        window.clearTimeout(hideTimer);
        hideTimer = window.setTimeout(function () {
            if (!returningToPortrait) return;
            video.hidden = true;
            if (video.readyState > 0) video.currentTime = 0;
        }, reduceMotion.matches ? 0 : 450);
        updateControls();
    }

    async function startPlayback() {
        if (failed || document.hidden || widget?.getAttribute("aria-busy") === "true") return;
        wantsPlayback = true;
        const attempt = ++playAttempt;
        window.clearTimeout(hideTimer);
        if (!video.getAttribute("src")) {
            // Keep the transparent portrait if this browser cannot play VP9.
            if (!video.canPlayType('video/webm; codecs="vp9, opus"')) {
                failed = true;
                wantsPlayback = false;
                return;
            }
            video.src = video.dataset.webm;
        }
        if (returningToPortrait && video.readyState > 0) video.currentTime = 0;
        returningToPortrait = false;
        video.hidden = false;
        try {
            await video.play();
        } catch (error) {
            if (attempt !== playAttempt || !wantsPlayback) return;
            // Hover can animate; audible playback may require user activation.
            if (error.name === "NotAllowedError" && !video.muted) {
                video.muted = true;
                try {
                    await video.play();
                } catch (_) {
                    if (attempt === playAttempt) stopPlayback();
                }
            } else {
                stopPlayback();
            }
        }
        updateControls();
    }

    function activate() {
        if (!video.paused && video.muted) {
            video.muted = false;
            updateControls();
        } else if (!video.paused) {
            wantsPlayback = false;
            playAttempt += 1;
            video.pause();
        } else {
            video.muted = false;
            startPlayback();
        }
    }

    mount.addEventListener("pointerenter", function (event) {
        if (event.pointerType === "mouse" && hoverPointer.matches && !reduceMotion.matches) startPlayback();
    });
    mount.addEventListener("pointerleave", function (event) {
        if (event.pointerType === "mouse" && hoverPointer.matches) stopPlayback();
    });
    mount.addEventListener("click", activate);
    mount.addEventListener("keydown", function (event) {
        if (event.target !== mount) return;
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activate();
        } else if (event.key === "Escape") stopPlayback();
    });
    video.addEventListener("playing", function () {
        if (wantsPlayback && !returningToPortrait) {
            mount.classList.add("is-video-visible");
            mount.dispatchEvent(new CustomEvent("sofia:avatar-video"));
        }
    });
    widget?.addEventListener("sofia:request", function (event) {
        if (event.detail.state === "pending" || event.detail.state === "cancelling") stopPlayback();
    });
    video.addEventListener("play", updateControls);
    video.addEventListener("pause", updateControls);
    video.addEventListener("volumechange", updateControls);
    video.addEventListener("ended", stopPlayback);
    video.addEventListener("error", function () {
        failed = true;
        stopPlayback();
    });
    document.addEventListener("visibilitychange", function () {
        if (document.hidden) stopPlayback();
    });
    reduceMotion.addEventListener("change", function () {
        if (reduceMotion.matches) stopPlayback();
    });
    updateControls();
})();
