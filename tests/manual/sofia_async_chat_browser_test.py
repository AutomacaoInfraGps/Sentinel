"""Validate pending delivery, page reload and cancellation with synthetic responses."""

import json
from threading import Thread

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from tests.unit.sofia_page_test import ChatUser, create_preview_app


def main():
    app = create_preview_app()
    cookie = app.session_interface.get_signing_serializer(app).dumps(
        {"_user_id": ChatUser.id, "_fresh": True})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for path in ("/sofia", "/test-widget"):
                context = browser.new_context(reduced_motion="reduce")
                context.add_cookies([{"name": "session", "value": cookie, "url": base}])
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                state = {"complete": False, "polls": 0, "posts": 0, "stops": 0}

                def submit(route):
                    payload = route.request.post_data_json
                    assert payload["async"] is True
                    state.update(request_id=payload["request_id"], posts=state["posts"] + 1)
                    route.fulfill(status=202, content_type="application/json",
                                  body=json.dumps({"request_id": state["request_id"], "pending": True}))

                def poll(route):
                    state["polls"] += 1
                    route.fulfill(status=200 if state["complete"] else 202,
                        content_type="application/json", body=json.dumps(
                            {"reply": "Resultado autorizado — 1 AP offline."} if state["complete"] else
                            {"request_id": state["request_id"], "pending": True}))

                def cancel(route):
                    assert route.request.post_data_json["request_id"] == state["request_id"]
                    state["stops"] += 1
                    route.fulfill(content_type="application/json",
                                  body='{"cancelled":true,"message":"Consulta cancelada."}')

                page.route("**/api/sofia/chat", submit)
                page.route("**/api/sofia/chat/requests/**", poll)
                page.route("**/api/sofia/chat/cancel", cancel)
                page.route("**/test/api_notifications*", lambda route: route.fulfill(
                    content_type="application/json", body='{"notifications":[],"unread_count":0}'))
                page.goto(base + path, wait_until="domcontentloaded")
                if path == "/test-widget":
                    page.locator("#sofiaLauncher").click()
                page.locator("#sofiaInput").fill("Quais APs estão offline?")
                with page.expect_response("**/api/sofia/chat/requests/**"):
                    page.locator("#sofiaSend").click()
                expect(page.locator("#sofiaStop")).to_be_visible()
                page.reload(wait_until="domcontentloaded")
                expect(page.locator("#sofiaStop")).to_be_visible()
                state["complete"] = True
                expect(page.locator(".sofia-message-assistant").last).to_contain_text("1 AP offline")
                expect(page.locator("#sofiaInput")).to_be_enabled()
                assert state["posts"] == 1, "Reload must resume polling without repeating the query"
                state["complete"] = False
                page.locator("#sofiaInput").fill("Outra consulta para cancelar")
                with page.expect_response("**/api/sofia/chat/requests/**"):
                    page.locator("#sofiaSend").click()
                page.locator("#sofiaStop").click()
                expect(page.locator(".sofia-message-assistant").last).to_contain_text("Consulta cancelada.")
                state["complete"] = True
                page.wait_for_timeout(1500)
                assert state["stops"] == 1
                assert page.locator(".sofia-message-assistant").last.inner_text().endswith("Consulta cancelada.")
                assert not errors, errors
                print(f"PASS {path}: pending delivery, reload without replay, cancellation, late reply suppressed")
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
