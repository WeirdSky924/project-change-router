import unittest

import router_core
from router_core import request_high_risk
from router_support.route_intent import request_requires_sensitive_review


class RouterHighRiskScopeTests(unittest.TestCase):
    def test_token_usage_observability_is_not_a_sensitive_token_request(self) -> None:
        request = (
            "Extract token-usage observability and accounting HTTP routes while preserving "
            "the existing facade contract."
        )

        self.assertFalse(request_high_risk(request, [], [], {"change_rules": {}, "config": {}}))

    def test_sensitive_token_requests_remain_high_risk(self) -> None:
        requests = (
            "Add an authorization token to the API request.",
            "Change credential token storage and rotation.",
            "Expose token-usage metrics together with an access token.",
        )

        for request in requests:
            with self.subTest(request=request):
                self.assertTrue(request_high_risk(request, [], [], {"change_rules": {}, "config": {}}))

    def test_repository_specific_trace_names_are_not_builtin_policy(self) -> None:
        self.assertFalse(request_requires_sensitive_review("Update a project-local trace hook."))
        self.assertFalse(
            request_requires_sensitive_review("Add a project-local character scan port.")
        )
        self.assertTrue(
            request_requires_sensitive_review(
                "Add project-local trace persistence.",
                ["project-local trace persistence"],
            )
        )

    def test_profile_review_phrases_materialize_in_change_rules(self) -> None:
        rules = router_core.build_change_rules(
            [],
            {"risk": {"review_phrases": ["project-local trace persistence"]}},
            "structured",
        )

        self.assertEqual(
            rules["sensitive_review_phrases"],
            ["project-local trace persistence"],
        )


if __name__ == "__main__":
    unittest.main()
