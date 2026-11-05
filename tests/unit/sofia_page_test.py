from pathlib import Path
import unittest
from unittest.mock import patch

from flask import Flask, render_template_string
from flask_login import LoginManager, UserMixin

from sofia.routes import sofia_bp


ROOT = Path(__file__).resolve().parents[2]


class ChatUser(UserMixin):
    id = "test.sofia"
    display_name = "Roosevelt"


def create_preview_app():
    app = Flask(__name__, template_folder=str(ROOT / "templates"),
                static_folder=str(ROOT / "static"))
    app.config.update(SECRET_KEY="local-test-only", TESTING=True, SOFIA_ENABLED=True,
                      TEMPLATES_AUTO_RELOAD=True)
    login = LoginManager(app)
    login.user_loader(lambda user_id: ChatUser() if user_id == ChatUser.id else None)
    app.register_blueprint(sofia_bp)
    app.url_build_error_handlers.append(lambda error, endpoint, values: "/test/" + endpoint)
    app.jinja_env.globals["csrf_token"] = lambda: "test-csrf"

    @app.context_processor
    def context():
        return {"sofia_enabled": app.config["SOFIA_ENABLED"],
                "sentinel_access": {"operator": True, "corporate": True}}

    @app.get("/test-widget")
    def widget():
        return render_template_string("{% extends 'base.html' %}")

    return app


class SofiaPageTests(unittest.TestCase):
    def setUp(self):
        self.app = create_preview_app()
        self.client = self.app.test_client()

    def authenticate(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = ChatUser.id
            session["_fresh"] = True

    def test_page_requires_authentication(self):
        self.assertEqual(self.client.get("/sofia").status_code, 401)

    def test_disabled_feature_is_unavailable(self):
        self.authenticate()
        self.app.config["SOFIA_ENABLED"] = False
        self.assertEqual(self.client.get("/sofia").status_code, 404)

    def test_page_checks_chat_permission(self):
        self.authenticate()
        with patch("sofia.routes.usuario_pode_executar", return_value=False):
            self.assertEqual(self.client.get("/sofia").status_code, 403)

    def test_dedicated_page_has_single_chat_without_floating_launcher(self):
        self.authenticate()
        response = self.client.get("/sofia")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        html = response.get_data(as_text=True)
        self.assertEqual(html.count('id="sofiaWidget"'), 1)
        self.assertEqual(html.count('id="sofiaForm"'), 1)
        self.assertIn('data-mode="dedicated"', html)
        self.assertIn('id="sofiaAvatarMount"', html)
        self.assertIn('id="sofiaAvatarVideo"', html)
        self.assertIn('preload="none" playsinline', html)
        self.assertIn('sofia-portrait-transparent.png', html)
        self.assertIn('sofia-hologram-transparent.webm', html)
        self.assertNotIn('id="sofiaLauncher"', html)
        self.assertLess(html.index('<span>Infraestrutura</span>'), html.index('<span>SofIA</span>'))
        self.assertLess(html.index('<span>SofIA</span>'), html.index('<span>Backup</span>'))
        self.assertNotIn('sofia-avatar-caption', html)

    def test_other_pages_keep_floating_chat(self):
        self.authenticate()
        html = self.client.get("/test-widget").get_data(as_text=True)
        self.assertEqual(html.count('id="sofiaWidget"'), 1)
        self.assertIn('id="sofiaLauncher"', html)


if __name__ == "__main__":
    unittest.main()
