"""Exercise real chat/avatar transitions without calling n8n or AD."""

from threading import Thread

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from tests.unit.sofia_page_test import ROOT, ChatUser, create_preview_app


def main():
    app = create_preview_app()
    token = app.session_interface.get_signing_serializer(app).dumps({"_user_id": ChatUser.id, "_fresh": True})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    screenshots = ROOT / "instance" / "sofia-avatar-preview"
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="no-preference")
            context.add_cookies([{"name": "session", "value": token, "url": base}])
            page = context.new_page()
            errors, pending, cancellations = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/test/api_notifications*", lambda r: r.fulfill(content_type="application/json", body='{}'))
            page.route("**/api/sofia/chat", lambda r: pending.append(r))
            page.route("**/api/sofia/chat/cancel", lambda r: cancellations.append(r))
            page.goto(base + "/sofia", wait_until="networkidle")
            mount = page.locator("#sofiaAvatarMount")
            canvas = page.locator("#sofiaAvatarAnimation")
            canvas.wait_for(state="visible")
            assert mount.get_attribute("data-avatar-state") == "idle"
            assert page.locator("#sofiaThoughtBubble").is_hidden()
            assert canvas.get_attribute("data-frame") == "idle"
            assert int(canvas.get_attribute("data-source-width")) >= 720
            assert int(canvas.get_attribute("data-source-height")) >= 1280
            assert mount.get_attribute("title") is None
            assert canvas.evaluate("""c => {
                const p = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                let empty=0, visible=0;
                for (let i=3;i<p.length;i+=4) { if (p[i]<10) empty++; if (p[i]>200) visible++; }
                return empty>c.width*c.height*0.5 && visible>10000;
            }""")
            page.screenshot(path=str(screenshots / "idle-light.png"), full_page=True)

            def send(text):
                page.locator("#sofiaInput").fill(text)
                page.locator("#sofiaSend").click()
                page.wait_for_function("document.getElementById('sofiaAvatarMount').dataset.avatarState === 'thinking'")

            send("Consulta com animacao")
            assert page.locator("#sofiaThoughtBubble").is_visible()
            assert page.locator("#sofiaPhase").inner_text() == "Consultando"
            assert "crossed" in page.locator("#sofiaAvatarAnimation").get_attribute("data-frames")
            first_frame = canvas.get_attribute("data-frame")
            page.wait_for_function("old => document.getElementById('sofiaAvatarAnimation').dataset.frame !== old", arg=first_frame)
            assert int(canvas.get_attribute("data-source-width")) >= 720
            assert int(canvas.get_attribute("data-source-height")) >= 1280
            assert page.locator("#sofiaAvatarVideo").evaluate("v => v.paused")
            page.locator('[data-theme-choice="dark"]').click()
            page.screenshot(path=str(screenshots / "thinking-dark.png"), full_page=True)
            assert len(pending) == 1
            pending.pop().fulfill(content_type="application/json", body='{"reply":"Consulta concluida. Aqui esta o resumo solicitado."}')
            page.wait_for_function("document.getElementById('sofiaAvatarMount').dataset.avatarState === 'responding'")
            assert page.locator("#sofiaThoughtBubble").is_hidden()
            assert page.locator("#sofiaPhase").inner_text() == "Respondendo"
            page.screenshot(path=str(screenshots / "responding-dark.png"), full_page=True)
            page.wait_for_function("document.getElementById('sofiaAvatarMount').dataset.avatarState === 'idle'")

            send("Consulta para parar")
            page.locator("#sofiaStop").click()
            page.wait_for_function("document.getElementById('sofiaAvatarMount').dataset.avatarState === 'cancelling'")
            assert canvas.get_attribute("data-frame") == "idle"
            assert page.locator("#sofiaThoughtBubble").is_hidden()
            cancellations.pop().fulfill(content_type="application/json", body='{"cancelled":true,"message":"Consulta cancelada no n8n."}')
            page.wait_for_function("document.getElementById('sofiaAvatarMount').dataset.avatarState === 'idle'")
            pending.pop().abort()

            send("Consulta com erro")
            pending.pop().fulfill(status=502, content_type="application/json", body='{"error":"Falha de teste","reply":"Nao foi possivel consultar."}')
            page.wait_for_function("document.getElementById('sofiaAvatarMount').dataset.avatarState === 'error'")
            assert canvas.get_attribute("data-frame") == "idle"
            assert page.locator("#sofiaThoughtBubble").is_hidden()
            page.wait_for_function("document.getElementById('sofiaAvatarMount').dataset.avatarState === 'idle'")

            page.locator("#sofiaAnimationToggle").click()
            canvas.wait_for(state="hidden")
            page.reload(wait_until="networkidle")
            assert canvas.is_hidden()
            assert page.locator("#sofiaAnimationToggle").get_attribute("aria-pressed") == "false"
            assert mount.locator("img").evaluate("img => getComputedStyle(img).opacity === '1'")
            page.locator("#sofiaAnimationToggle").click()
            canvas.wait_for(state="visible")
            page.emulate_media(reduced_motion="reduce")
            canvas.wait_for(state="hidden")
            assert page.locator("#sofiaAnimationToggle").is_disabled()
            page.emulate_media(reduced_motion="no-preference")
            canvas.wait_for(state="visible")

            mount.hover()
            page.wait_for_function("document.getElementById('sofiaAvatarVideo').currentTime > 0.2")
            canvas.wait_for(state="hidden")
            page.mouse.move(0, 0)
            canvas.wait_for(state="visible")
            assert mount.get_attribute("title") is None

            for width, height in [(390, 844), (768, 1024)]:
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert canvas.is_visible()
                assert page.locator("#sofiaAnimationToggle").is_visible()
                send("Consulta em tela menor")
                bubble_box = page.locator("#sofiaThoughtBubble").bounding_box()
                mount_box = mount.bounding_box()
                assert bubble_box and mount_box
                assert bubble_box["x"] >= mount_box["x"]
                assert bubble_box["x"] + bubble_box["width"] <= mount_box["x"] + mount_box["width"] + 1
                page.screenshot(path=str(screenshots / f"viewport-{width}.png"), full_page=True)
                pending.pop().fulfill(content_type="application/json", body='{"reply":"Consulta de teste concluida."}')
                page.wait_for_function("document.getElementById('sofiaAvatarMount').dataset.avatarState === 'idle'")

            retina = browser.new_context(device_scale_factor=2, viewport={"width": 1440, "height": 1000}, reduced_motion="no-preference")
            retina.add_cookies([{"name": "session", "value": token, "url": base}])
            retina_page = retina.new_page()
            retina_page.goto(base + "/sofia", wait_until="networkidle")
            retina_canvas = retina_page.locator("#sofiaAvatarAnimation")
            retina_canvas.wait_for(state="visible")
            assert retina_canvas.evaluate("c => c.width >= c.getBoundingClientRect().width * 1.95 && c.height >= c.getBoundingClientRect().height * 1.95")
            assert retina_canvas.evaluate("c => c.width <= 937 && c.height <= 1678")
            retina_page.set_viewport_size({"width": 768, "height": 1024})
            retina_page.wait_for_function("() => { const c=document.getElementById('sofiaAvatarAnimation'); return Math.abs(c.width/c.height-c.clientWidth/c.clientHeight)<0.01; }")
            retina.close()

            page.route("**/sofia-thinking-crossed-hd-a.png", lambda r: r.abort())
            page.reload(wait_until="networkidle")
            page.wait_for_function("document.getElementById('sofiaAnimationToggle').disabled")
            assert canvas.is_hidden()
            assert mount.locator("img").evaluate("img => img.complete && getComputedStyle(img).opacity === '1'")
            assert not errors, errors
            browser.close()
        print(f"Avatar state checks passed. Screenshots: {screenshots}")
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
