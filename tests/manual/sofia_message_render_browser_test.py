"""Exercise chat formatting and restored history with synthetic browser responses."""

import json
from threading import Thread

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from tests.unit.sofia_page_test import ChatUser, create_preview_app


def main():
    app = create_preview_app()
    session = app.session_interface.get_signing_serializer(app).dumps(
        {"_user_id": ChatUser.id, "_fresh": True}
    )
    server = make_server("127.0.0.1", 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    reply = (
        "Licenca **REG_TESTE** com **7 dias**. Interface `port15`.\n"
        "<img src=x onerror=alert(1)>\n"
        "```powershell\nWrite-Output '**literal**'\n<script>alert(1)</script>\n```\n"
        "Marcador incompleto ** fica literal."
    )
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for path in ("/sofia", "/test-widget"):
                context = browser.new_context(reduced_motion="reduce")
                context.add_cookies([{"name": "session", "value": session, "url": base}])
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/api/sofia/chat", lambda route: route.fulfill(
                    content_type="application/json", body=json.dumps({"reply": reply})
                ))
                page.route("**/test/api_notifications*", lambda route: route.fulfill(
                    content_type="application/json", body='{"notifications": [], "unread_count": 0}'
                ))
                page.goto(base + path, wait_until="domcontentloaded")
                if path == "/test-widget":
                    page.locator("#sofiaLauncher").click()
                page.locator("#sofiaInput").fill("Teste de formatacao")
                page.locator("#sofiaSend").click()
                body = page.locator(".sofia-message-assistant .sofia-message-body").last
                body.locator("strong").first.wait_for()
                for restored in (False, True):
                    if restored:
                        page.reload(wait_until="domcontentloaded")
                    assert body.locator("strong").all_text_contents() == ["REG_TESTE", "7 dias"]
                    assert "**REG_TESTE**" not in body.inner_text()
                    assert body.locator("p code").inner_text() == "port15"
                    assert "**literal**" in body.locator("pre code").inner_text()
                    assert "<script>alert(1)</script>" in body.locator("pre code").inner_text()
                    assert body.locator("img, script").count() == 0
                    assert "<img src=x onerror=alert(1)>" in body.inner_text()
                    assert "incompleto **" in body.inner_text()
                assert not errors, errors
                print(f"PASS {path}: bold, code, HTML safety and restored history")
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
