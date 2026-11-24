from linkedin_applications.confirmations import activation_payload


def test_activation_extracts_only_one_expected_code():
    rule = {"kind": "code", "pattern": r"Code du portail : ([0-9]{6})"}
    provider = "https://portal.example.org"
    assert activation_payload("Code du portail : 123456", rule, provider) == "123456"
    assert activation_payload("Autre code : 123456", rule, provider) is None
    assert (
        activation_payload(
            "Code du portail : 123456\nCode du portail : 654321", rule, provider
        )
        is None
    )


def test_activation_link_requires_expected_origin_and_path():
    provider = "https://portal.example.org"
    rule = {"kind": "link", "link_path": "/activate", "token_parameter": "token"}
    link = provider + "/activate?token=example-token-value"
    assert activation_payload(f"<{link}>", rule, provider) == link
    assert activation_payload(link.replace("portal.", "other."), rule, provider) is None
    assert (
        activation_payload(link.replace("/activate", "/submit"), rule, provider) is None
    )
    assert (
        activation_payload(link + "&next=https://other.example.org", rule, provider)
        is None
    )
    assert (
        activation_payload(link + " " + link.replace("value", "other"), rule, provider)
        is None
    )


def test_worker_enters_code_only_on_expected_page_and_claims_it_once():
    import asyncio
    import json

    from linkedin_applications.confirmations import EmailConfirmations

    page = "https://portal.example.org/verify"
    events = []

    class Browser:
        url = "https://portal.example.org/other"

        async def current_url(self, rpc, tab):
            return self.url

        async def use(self, rpc, name, arguments):
            events.append(name)
            if name == "page_fillInput":
                assert arguments["value"] == "123456"

    class Mail:
        async def request(self, method, params):
            events.append(params["name"])
            return {"content": [{"text": json.dumps({"body": "Code : 123456"})}]}

    class Confirmations(EmailConfirmations):
        claimed = False

        def claim_activation(self, dossier, digest):
            assert dossier == "synthetic" and len(digest) == 64
            if self.claimed:
                return False
            self.claimed = True
            return True

    browser = Browser()
    worker = Confirmations(None, browser, [], [])
    rule = {
        "folder": "fixture",
        "activation": {
            "kind": "code",
            "pattern": r"Code : ([0-9]{6})",
            "page_url": page,
            "code_selector": "#activation-code",
            "confirm_selector": "#verify",
            "confirm_text": "Confirmer le compte",
        },
    }
    account = {
        "browser_tab": 1,
        "provider": "https://portal.example.org",
        "dossier_id": "synthetic",
    }

    async def exercise():
        await worker.apply_activation(Mail(), None, account, rule, "message")
        assert events == []
        browser.url = page
        await worker.apply_activation(Mail(), None, account, rule, "message")
        await worker.apply_activation(Mail(), None, account, rule, "message")

    asyncio.run(exercise())
    assert events == ["getMessage", "page_fillInput", "page_clickElement", "getMessage"]
