import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.api.linkedin_client import LinkedInAPI


class LinkedInAPITest(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.api = LinkedInAPI(
            access_token="test-token",
            author_urn="urn:li:person:test-id",
            api_version="202608",
            session=self.session,
        )

    def test_post_is_dry_run_by_default(self):
        result = self.api.create_text_post("Test technique")

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["payload"]["author"], "urn:li:person:test-id")
        self.session.request.assert_not_called()

    def test_publish_requires_explicit_confirmation(self):
        response = Mock(status_code=201, ok=True)
        response.headers = {"x-restli-id": "urn:li:share:123"}
        self.session.request.return_value = response

        result = self.api.create_text_post("Test technique", confirm=True)

        self.assertEqual(result["post_urn"], "urn:li:share:123")
        self.session.request.assert_called_once()

    def test_image_post_is_dry_run_without_upload_by_default(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            result = self.api.create_image_post(
                "Test avec image",
                Path(image_file.name),
                "Illustration de test",
            )

        self.assertTrue(result["dry_run"])
        self.assertEqual(
            result["payload"]["content"]["media"]["altText"],
            "Illustration de test",
        )
        self.session.request.assert_not_called()

    def test_publish_image_uploads_binary_then_creates_post(self):
        initialize_response = Mock(status_code=200, ok=True)
        initialize_response.json.return_value = {
            "value": {
                "uploadUrl": "https://www.linkedin.com/dms-uploads/test",
                "image": "urn:li:image:test-image",
            }
        }
        upload_response = Mock(status_code=201, ok=True)
        post_response = Mock(status_code=201, ok=True)
        post_response.headers = {"x-restli-id": "urn:li:share:456"}
        self.session.request.side_effect = [
            initialize_response,
            upload_response,
            post_response,
        ]

        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            image_file.write(b"fake-png")
            image_file.flush()
            result = self.api.create_image_post(
                "Test avec image",
                Path(image_file.name),
                "Illustration de test",
                confirm=True,
            )

        self.assertEqual(result["image_urn"], "urn:li:image:test-image")
        self.assertEqual(result["post_urn"], "urn:li:share:456")
        self.assertEqual(self.session.request.call_count, 3)

        initialize_call, upload_call, post_call = self.session.request.call_args_list
        self.assertEqual(initialize_call.args[0], "POST")
        self.assertIn("images?action=initializeUpload", initialize_call.args[1])
        self.assertEqual(upload_call.args[:2], ("PUT", "https://www.linkedin.com/dms-uploads/test"))
        self.assertEqual(
            upload_call.kwargs["headers"]["Content-Type"], "image/png"
        )
        self.assertEqual(post_call.args[0], "POST")
        media = post_call.kwargs["json"]["content"]["media"]
        self.assertEqual(media["id"], "urn:li:image:test-image")
        self.assertEqual(media["altText"], "Illustration de test")

    def test_aggregate_stats_uses_member_analytics_endpoint(self):
        response = Mock(status_code=200, ok=True)
        response.json.return_value = {"elements": [{"count": 42}]}
        self.session.request.return_value = response

        result = self.api.get_member_post_stats(metrics=["IMPRESSION"])

        self.assertEqual(result["IMPRESSION"]["elements"][0]["count"], 42)
        _, url = self.session.request.call_args.args
        self.assertTrue(url.endswith("/memberCreatorPostAnalytics"))
        self.assertEqual(self.session.request.call_args.kwargs["params"]["q"], "me")


if __name__ == "__main__":
    unittest.main()
