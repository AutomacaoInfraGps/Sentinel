import unittest

from sofia.user_context import build_user_context, parse_creator_users


class _User:
    username = "admin.pimentel"
    display_name = "Roosevelt"


class SofiaUserContextTests(unittest.TestCase):
    def test_marks_configured_authenticated_user_as_creator(self):
        self.assertEqual(
            build_user_context(_User(), ["ADMIN.PIMENTEL"]),
            {"display_name": "Roosevelt", "relationship": "creator"},
        )

    def test_unconfigured_user_does_not_become_creator(self):
        self.assertEqual(
            build_user_context(_User(), ["outro.usuario"])["relationship"],
            "user",
        )

    def test_parses_environment_style_allowlist(self):
        self.assertEqual(
            parse_creator_users("admin.pimentel; outro.usuario\nterceiro"),
            frozenset({"admin.pimentel", "outro.usuario", "terceiro"}),
        )

    def test_sanitizes_display_name(self):
        user = _User()
        user.display_name = "  Roosevelt\n\tPimentel  "
        context = build_user_context(user, ["admin.pimentel"])
        self.assertEqual(context["display_name"], "Roosevelt Pimentel")


if __name__ == "__main__":
    unittest.main()
