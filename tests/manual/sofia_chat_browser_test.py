"""Local browser checks using an isolated app and synthetic chat responses."""

import json
import argparse
from threading import Thread

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from tests.unit.sofia_page_test import ROOT, ChatUser, create_preview_app


def main():
    app = create_preview_app()
    token = app.session_interface.get_signing_serializer(app).dumps(
        {"_user_id": ChatUser.id, "_fresh": True}
    )
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    screenshots = ROOT / "instance" / "sofia-preview"
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(reduced_motion="reduce")
            context.add_cookies([{"name": "session", "value": token, "url": base}])
            page = context.new_page()
            errors = []
            requests = []
            pending_routes = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def reply(route):
                payload = route.request.post_data_json
                requests.append(payload)
                if payload["message"] == "Testar telemetria":
                    pending_routes.append(route)
                    return
                text = "Resposta de teste da SofIA."
                if payload["message"] == "Mostrar bloco tecnico":
                    text = "Consulta de teste:\n```powershell\nGet-Service\n<img src=x onerror=alert(1)>\n```\nFim."
                route.fulfill(content_type="application/json", body=json.dumps({"reply": text}))

            page.route("**/api/sofia/chat", reply)
            page.route("**/test/api_notifications*", lambda route: route.fulfill(
                content_type="application/json", body='{"notifications": [], "unread_count": 0}'))
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto(base + "/sofia", wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            assert page.locator("#sofiaLauncher").count() == 0
            assert page.locator("#sofiaAvatarMount img").evaluate("img => img.complete && img.naturalWidth > 0")
            assert page.locator("#sofiaAvatarMount img").evaluate("img => img.naturalWidth === 937 && img.naturalHeight === 1678")
            assert page.locator("#sofiaAvatarMount").get_attribute("title") is None
            def check_theme(light):
                assert page.locator(".sofia-dedicated-chat").evaluate("""(el, light) => {
                    const rgb = getComputedStyle(el).backgroundColor.match(/\\d+/g).map(Number);
                    return light ? rgb.slice(0, 3).every(c => c > 200) : rgb.slice(0, 3).every(c => c < 60);
                }""", light)
                assert page.locator("#sofiaInput").evaluate("""(el, light) => {
                    const rgb = getComputedStyle(el).color.match(/\\d+/g).map(Number);
                    return light ? rgb.slice(0, 3).every(c => c < 150) : rgb.slice(0, 3).every(c => c > 180);
                }""", light)
            page.locator('[data-theme-choice="light"]').click()
            check_theme(True)
            page.screenshot(path=str(screenshots / "sofia-light.png"), full_page=True)
            page.locator('[data-theme-choice="dark"]').click()
            check_theme(False)
            page.screenshot(path=str(screenshots / "sofia-dark.png"), full_page=True)
            page.locator('[data-theme-choice="system"]').click()
            page.emulate_media(color_scheme="light")
            check_theme(True)
            page.emulate_media(color_scheme="dark")
            check_theme(False)
            page.locator('[data-theme-choice="light"]').click()
            page.emulate_media(color_scheme="light")
            assert page.locator("#sofiaAvatarMount button").count() == 0
            assert page.locator("#sofiaAvatarVideo").get_attribute("src") is None
            assert page.locator("#sofiaVideoToggle").count() == 0
            page.locator("#sofiaAvatarMount").focus()
            page.keyboard.press("Enter")
            page.wait_for_function("document.getElementById('sofiaAvatarVideo').currentTime > 0.3")
            assert page.locator("#sofiaAvatarMount").get_attribute("title") is None
            assert "Pausar" in page.locator("#sofiaAvatarMount").get_attribute("aria-label")
            assert page.locator("#sofiaAvatarMount").evaluate("""mount => {
                const img = mount.querySelector('img').getBoundingClientRect();
                const video = mount.querySelector('video').getBoundingClientRect();
                return ['x', 'y', 'width', 'height'].every(key => Math.abs(img[key] - video[key]) < 1);
            }""")
            assert page.locator("#sofiaAvatarVideo").evaluate("v => !v.muted && !v.loop && v.videoWidth === 720")
            page.wait_for_function("document.getElementById('sofiaAvatarVideo').webkitAudioDecodedByteCount > 0")
            for selector, sample_time in [("#sofiaAvatarMount img", None), ("#sofiaAvatarVideo", 0.5), ("#sofiaAvatarVideo", 4), ("#sofiaAvatarVideo", 8)]:
                if sample_time is not None:
                    page.locator(selector).evaluate("(v, time) => new Promise(resolve => { v.addEventListener('seeked', resolve, {once: true}); v.currentTime = time; })", sample_time)
                assert page.locator(selector).evaluate("""media => {
                    const canvas = document.createElement('canvas');
                    canvas.width = 72; canvas.height = 128;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(media, 0, 0, 72, 128);
                    const pixels = ctx.getImageData(0, 0, 72, 128).data;
                    let transparent = 0, opaque = 0, green = 0;
                    for (let i = 0; i < pixels.length; i += 4) {
                        if (pixels[i + 3] < 10) transparent++;
                        if (pixels[i + 3] > 200) {
                            opaque++;
                            if (pixels[i + 1] > Math.max(pixels[i], pixels[i + 2]) * 1.3 + 20) green++;
                        }
                    }
                    return pixels[3] === 0 && transparent > 3000 && opaque > 1000 && green < 10;
                }"""), f"Transparency or green spill: {selector}"
            assert page.locator("#sofiaAvatarVideo").evaluate("""v => {
                const canvas = document.createElement('canvas');
                canvas.width = 72; canvas.height = 128;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(v, 0, 0, 72, 128);
                return ctx.getImageData(0, 0, 72, 128).data.filter((x, i) => i % 4 !== 3 && x > 80).length > 100;
            }""")
            page.locator("#sofiaAvatarMount").click()
            assert page.locator("#sofiaAvatarVideo").evaluate("v => v.paused")
            page.locator("#sofiaAvatarMount").press("Escape")
            page.locator("#sofiaAvatarVideo").wait_for(state="hidden")
            page.locator("#sofiaInput").fill("Bom dia")
            page.locator("#sofiaSend").click()
            page.get_by_text("Resposta de teste da SofIA.", exact=True).wait_for()
            original_id = requests[-1]["conversation_id"]
            assert page.locator(".sofia-heading-identity img").evaluate("img => img.complete && img.naturalWidth > 0")
            assert page.locator("#sofiaPageTitle").inner_text() == "SofIA"
            assert page.locator(".sofia-avatar-caption").count() == 0
            assert page.locator(".sofia-message-assistant").first.evaluate("el => getComputedStyle(el).backdropFilter.includes('blur')")
            assert page.locator(".sofia-message-user").first.evaluate("el => getComputedStyle(el).backgroundColor === 'rgb(21, 65, 91)'")
            assert page.locator("[data-sofia-prompt]").count() == 3
            page.locator("[data-sofia-prompt]").first.click()
            assert "alertas" in page.locator("#sofiaInput").input_value()
            assert len(requests) == 1
            page.locator("#sofiaInput").fill("Mostrar bloco tecnico")
            page.locator("#sofiaSend").click()
            page.locator(".sofia-message-body pre code").wait_for()
            assert "Get-Service" in page.locator(".sofia-message-body pre code").inner_text()
            assert "<img" in page.locator(".sofia-message-body pre code").inner_text()
            assert page.locator(".sofia-message-body img").count() == 0
            page.locator("#sofiaInput").fill("Testar telemetria")
            page.locator("#sofiaSend").click()
            page.wait_for_function("document.getElementById('sofiaPhase').textContent === 'Consultando'")
            assert page.locator("#sofiaAttach").is_disabled()
            assert page.locator("#sofiaWidget").get_attribute("aria-busy") == "true"
            pending_routes.pop().fulfill(content_type="application/json", body='{"reply":"Consulta de teste concluida"}')
            page.get_by_text("Consulta de teste concluida", exact=True).wait_for()
            assert page.locator("#sofiaPhase").inner_text() == "Em espera"
            assert page.locator("#sofiaRoundTrip").inner_text().endswith(" s")
            assert page.locator("#sofiaAttach").is_enabled()
            page.locator("#sofiaLogFile").set_input_files({"name": "teste.log", "mimeType": "text/plain", "buffer": b"INFO: teste local"})
            page.locator("#sofiaLogDialog").wait_for()
            page.locator("#sofiaLogUse").click()
            assert "INFO: teste local" in page.locator("#sofiaInput").input_value()
            assert len(requests) == 3
            page.locator("#sofiaInput").fill("")
            page.locator("#sofiaLogFile").set_input_files({"name": "grande.log", "mimeType": "text/plain", "buffer": b"X" * 2000})
            page.locator("#sofiaLogDialog").wait_for()
            page.locator("#sofiaLogUse").click()
            assert page.locator("#sofiaLogDialog").is_visible()
            assert "1000" in page.locator("#sofiaLogNotice").inner_text()
            page.locator("#sofiaLogPreview").evaluate("el => el.setSelectionRange(0, 100)")
            page.locator("#sofiaLogUse").click()
            assert len(page.locator("#sofiaInput").input_value()) < 1000
            page.locator("#sofiaInput").fill("")
            page.screenshot(path=str(screenshots / "desktop.png"), full_page=True)

            page.goto(base + "/test-widget", wait_until="networkidle")
            page.locator("#sofiaLauncher").click()
            page.get_by_text("Resposta de teste da SofIA.", exact=True).wait_for()
            page.locator("#sofiaInput").fill("Continuar conversa")
            page.locator("#sofiaSend").click()
            page.wait_for_function("!document.getElementById('sofiaSend').disabled")
            assert requests[-1]["conversation_id"] == original_id

            page.goto(base + "/sofia", wait_until="networkidle")
            page.locator("#sofiaClear").click()
            assert page.locator(".sofia-message-user").count() == 0
            page.locator("#sofiaInput").fill("Nova conversa")
            page.locator("#sofiaSend").click()
            page.wait_for_function("!document.getElementById('sofiaSend').disabled")
            assert requests[-1]["conversation_id"] != original_id

            for width, height in [(390, 844), (768, 1024), (1440, 900)]:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(400)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow: {width}"
                send_box = page.locator("#sofiaSend").bounding_box()
                page.screenshot(path=str(screenshots / f"viewport-{width}.png"), full_page=True)
                assert send_box and send_box["y"] + send_box["height"] <= height, f"Composer outside viewport: {width}: {send_box}"

            def fail(route):
                route.fulfill(status=502, content_type="application/json", body='{"error":"Erro de teste","reply":"Falha de teste"}')

            page.unroute("**/api/sofia/chat", reply)
            page.route("**/api/sofia/chat", fail)
            page.locator("#sofiaInput").fill("Teste de falha")
            page.locator("#sofiaSend").click()
            page.get_by_text("Falha de teste", exact=True).wait_for()
            assert page.locator("#sofiaStatus").inner_text() == "Erro de teste"
            assert page.locator("#sofiaSend").is_enabled()
            page.emulate_media(reduced_motion="no-preference")
            assert page.locator("#sofiaAvatarVideo").get_attribute("src") is None
            page.locator("#sofiaAvatarMount").hover()
            page.wait_for_function("document.getElementById('sofiaAvatarVideo').currentTime > 0.3 && !document.getElementById('sofiaAvatarVideo').paused")
            page.wait_for_function("getComputedStyle(document.getElementById('sofiaAvatarVideo')).opacity === '1'")
            page.screenshot(path=str(screenshots / "avatar-video.png"), full_page=True)
            page.locator("#sofiaAvatarMount").press("Escape")
            assert page.locator("#sofiaAvatarVideo").is_visible()
            page.locator("#sofiaAvatarVideo").wait_for(state="hidden")
            assert page.locator("#sofiaAvatarMount img").evaluate("img => getComputedStyle(img).opacity === '1'")
            page.locator("#sofiaAvatarMount").click()
            page.wait_for_function("!document.getElementById('sofiaAvatarVideo').paused")
            page.emulate_media(reduced_motion="reduce")
            assert page.locator("#sofiaAvatarVideo").evaluate("v => v.paused")
            page.locator("#sofiaAvatarMount").click()
            page.locator("#sofiaAvatarVideo").evaluate("v => { v.currentTime = v.duration - 0.2; }")
            page.wait_for_function("document.getElementById('sofiaAvatarVideo').hidden")
            hover_context = browser.new_context(reduced_motion="no-preference")
            hover_context.add_cookies([{"name": "session", "value": token, "url": base}])
            hover_page = hover_context.new_page()
            hover_page.goto(base + "/sofia", wait_until="networkidle")
            hover_page.locator("#sofiaAvatarMount").hover()
            hover_page.wait_for_function("document.getElementById('sofiaAvatarVideo').currentTime > 0.2")
            assert hover_page.locator("#sofiaAvatarVideo").evaluate("v => getComputedStyle(v).objectFit === 'contain'")
            hover_page.mouse.move(0, 0)
            hover_page.locator("#sofiaAvatarVideo").wait_for(state="hidden")
            assert hover_page.locator("#sofiaAvatarVideo").evaluate("v => v.paused")
            hover_context.close()
            touch_context = browser.new_context(has_touch=True, is_mobile=True, viewport={"width": 390, "height": 844})
            touch_context.add_cookies([{"name": "session", "value": token, "url": base}])
            touch_page = touch_context.new_page()
            touch_page.goto(base + "/sofia", wait_until="networkidle")
            touch_page.locator("#sofiaAvatarMount").tap()
            touch_page.wait_for_function("document.getElementById('sofiaAvatarVideo').currentTime > 0.2")
            assert touch_page.locator("#sofiaAvatarVideo").evaluate("v => !v.muted")
            touch_context.close()
            assert not errors, errors
            browser.close()
        print(f"Browser checks passed. Screenshots: {screenshots}")
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=5097)
    args = parser.parse_args()
    if args.serve:
        from flask import jsonify, request
        from flask_login import login_user

        preview = create_preview_app()

        @preview.before_request
        def local_preview():
            login_user(ChatUser())
            if request.path == "/api/sofia/chat":
                return jsonify(reply="Esta e uma resposta simulada da previa local. No Sentinel, a conversa utiliza a integracao existente com a SofIA.")

        preview.run(host="127.0.0.1", port=args.port, use_reloader=False)
    else:
        main()
