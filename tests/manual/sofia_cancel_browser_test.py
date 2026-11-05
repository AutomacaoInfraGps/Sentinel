"""Browser cancellation checks with isolated Flask and mocked n8n responses."""

import json
from threading import Thread

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from tests.unit.sofia_page_test import ChatUser, create_preview_app


def main():
    app = create_preview_app()
    token = app.session_interface.get_signing_serializer(app).dumps({"_user_id": ChatUser.id, "_fresh": True})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(reduced_motion="reduce")
            context.add_cookies([{"name": "session", "value": token, "url": base}])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/test/api_notifications*", lambda r: r.fulfill(content_type="application/json", body='{}'))
            cancellation = {"cancelled": True, "message": "Consulta cancelada no n8n."}
            cancels = []

            def stop(route):
                cancels.append(route.request.post_data_json)
                assert route.request.headers["x-sentinel-request"] == "sofia-chat"
                assert route.request.headers["x-csrf-token"] == "test-csrf"
                route.fulfill(content_type="application/json", body=json.dumps(cancellation))

            page.route("**/api/sofia/chat/cancel", stop)
            for path in ["/sofia", "/test-widget"]:
                page.goto(base + path, wait_until="networkidle")
                if path == "/test-widget":
                    page.locator("#sofiaLauncher").click()
                page.evaluate("""() => {
                    const realFetch = window.fetch;
                    window.fetch = (url, options) => {
                        if (String(url).endsWith('/api/sofia/chat')) {
                            window.sentRequest = JSON.parse(options.body);
                            // Deliberately ignore AbortSignal: verify late-response isolation.
                            return new Promise(resolve => { window.resolveChat = reply => resolve(
                                new Response(JSON.stringify({reply}), {headers: {'content-type': 'application/json'}})); });
                        }
                        return realFetch(url, options);
                    };
                }""")
                assert page.locator("#sofiaStop").is_hidden()
                page.locator("#sofiaInput").fill("Consulta para cancelar")
                page.locator("#sofiaSend").click()
                page.locator("#sofiaStop").wait_for(state="visible")
                request_id = page.evaluate("window.sentRequest.request_id")
                assert page.locator("#sofiaInput").is_disabled()
                page.evaluate("() => { window.oldResolve = window.resolveChat; }")
                page.locator("#sofiaStop").click()
                page.locator("#sofiaStop").wait_for(state="hidden")
                assert cancels[-1]["request_id"] == request_id
                assert page.locator("#sofiaInput").is_enabled()
                assert page.locator("#sofiaStatus").inner_text() == cancellation["message"]
                page.locator("#sofiaInput").fill("Nova consulta apos parar")
                page.locator("#sofiaSend").click()
                page.evaluate("window.oldResolve('RESPOSTA ANTIGA DESCARTAR')")
                page.wait_for_timeout(100)
                assert page.locator("#sofiaSend").is_disabled()
                assert "RESPOSTA ANTIGA DESCARTAR" not in page.locator("#sofiaMessages").inner_text()
                page.evaluate("window.resolveChat('Resposta nova correta')")
                page.wait_for_function("!document.getElementById('sofiaSend').disabled")
                assert "Resposta nova correta" in page.locator("#sofiaMessages").inner_text()
                cancellation.update(cancelled=False, message="Parada no n8n nao confirmada.")
                page.locator("#sofiaInput").fill("Consulta sem confirmacao")
                page.locator("#sofiaSend").click()
                page.locator("#sofiaStop").click()
                page.locator("#sofiaStop").wait_for(state="hidden")
                assert page.locator("#sofiaStatus").inner_text() == cancellation["message"]
                assert "is-error" in page.locator("#sofiaStatus").get_attribute("class")
                cancellation.update(cancelled=True, message="Consulta cancelada no n8n.")
            assert not errors, errors
            browser.close()
        print("Cancellation browser checks passed (dedicated and floating chat).")
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
