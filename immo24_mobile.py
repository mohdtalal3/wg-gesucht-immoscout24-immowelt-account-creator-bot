import re
import time
import random
import base64
import hashlib
import secrets
import uuid
from urllib.parse import quote, urlencode
from curl_cffi import requests
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv

# ── config ─────────────────────────────────────────────────────────────────────
load_dotenv()
PROXY    = os.getenv("PROXY_URL", "")
SSO_BASE = "https://sso.immobilienscout24.de"

# iOS 18 / Safari UA (matches the captured mobile traffic)
_IOS_IMPERSONATIONS = [
    "safari_ios",
    "safari172_ios",
    "safari180_ios",
    "safari184_ios",
    "safari260_ios",
]

IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Mobile/15E148 Safari/604.1"
)

# ── helpers ────────────────────────────────────────────────────────────────────
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class ImmoScoutMobileRegistrar:

    def __init__(self, email: str, password: str, proxy: str = PROXY):
        self.email    = email
        self.password = password
        proxies       = {"http": proxy, "https": proxy} if proxy else {}

        _imp = random.choice(_IOS_IMPERSONATIONS)
        print(f"   TLS impersonation: {_imp}")
        self.session = requests.Session(
            impersonate=_imp,            # iOS Safari TLS fingerprint (randomised)
            verify=False,
            proxies=proxies,
        )
        self.session.headers.update({
            "User-Agent"    : IOS_UA,
            "Accept"        : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        })

        # PKCE + OIDC params — generated fresh per run
        self.ios_id        = str(uuid.uuid4()).upper()
        verifier_bytes     = secrets.token_bytes(32)
        self.code_verifier = _b64url(verifier_bytes)
        self.code_challenge= _b64url(hashlib.sha256(self.code_verifier.encode()).digest())
        self.nonce         = _b64url(secrets.token_bytes(16))
        self.state         = str(uuid.uuid4()).upper()

    # ── internal ────────────────────────────────────────────────────────────────

    def _authorize_url(self) -> str:
        """OIDC authorize URL — used as sso_return value."""
        params = urlencode({
            "app_name"            : "is24-ios-de",
            "client_id"           : "is24-ios-de",
            "code_challenge"      : self.code_challenge,
            "code_challenge_method": "S256",
            "consent"             : "false",
            "iosTestingId"        : self.ios_id,
            "nonce"               : self.nonce,
            "redirect_uri"        : "immobilienscout24.de:/loginCallback",
            "response_type"       : "code",
            "scope"               : "openid profile offline_access",
            "source"              : "appstart",
            "state"               : self.state,
            "utm_campaign"        : "sso_entrance",
            "utm_medium"          : "app",
            "utm_source"          : "iphone",
        }, quote_via=quote)
        return f"{SSO_BASE}/auth/authorize?{params}"

    def _mobile_base_qs(self) -> str:
        """Common query-string fragment for mobile SSO endpoints."""
        return (
            f"utm_campaign=sso_entrance&utm_medium=app&source=appstart"
            f"&consent=false&appName=is24-ios-de&iosTestingId={self.ios_id}"
            f"&sso_return={quote(self._authorize_url(), safe='')}&oidc=true"
        )

    def _extract_token(self, html: str):
        soup  = BeautifulSoup(html, "html.parser")
        tag   = soup.find("input", attrs={"name": re.compile(r"tokenMap\[.*?\]")})
        return (tag["name"], tag["value"]) if tag else (None, None)

    # ── steps ───────────────────────────────────────────────────────────────────

    def step1_app_validation(self):
        print("🔄 Step 1: App validation …")
        r = self.session.post(
            "https://api.mobile.immobilienscout24.de/app/validation",
            json={
                "language": "en", "deviceVendor": "apple", "device": "iphone",
                "clientOS": "ios", "osVersion": "26.5", "appVersion": "27.23",
            },
            headers={
                "User-Agent"    : "ImmoScout_27.23_26.5_._",
                "Content-Type"  : "application/json",
                "x-emb-st"      : str(int(time.time() * 1000)),
                "x-emb-id"      : str(uuid.uuid4()).upper(),
                "priority"      : "u=3",
            },
        )
        print(f"   → {r.status_code}")
        return r

    def step2_oidc_discover(self):
        print("🔄 Step 2: OIDC discovery …")
        r = self.session.get(
            f"{SSO_BASE}/.well-known/openid-configuration",
            headers={"priority": "u=3"},
        )
        print(f"   → {r.status_code}")
        return r

    def step3_authorize(self):
        print("🔄 Step 3: OIDC authorize …")
        r = self.session.get(
            self._authorize_url(),
            headers={"priority": "u=0, i"},
            allow_redirects=True,
        )
        print(f"   → {r.status_code} | {r.url}")
        return r

    def step4_sso_authenticate(self):
        print("🔄 Step 4: SSO authenticate …")
        url = f"{SSO_BASE}/sso/authenticate?{self._mobile_base_qs()}"
        r   = self.session.get(url, headers={"priority": "u=0, i"}, allow_redirects=True)
        print(f"   → {r.status_code} | {r.url}")
        return r

    def step5_get_login_page(self):
        """GET the login page explicitly to ensure we have the tokenMap."""
        print("🔄 Step 5: Login page …")
        url = f"{SSO_BASE}/sso/login?{self._mobile_base_qs()}"
        r   = self.session.get(url, headers={"priority": "u=0, i"}, allow_redirects=True)
        print(f"   → {r.status_code} | {r.url}")
        field, value = self._extract_token(r.text)
        if field:
            print(f"   Token: {field} = {value}")
        else:
            print("   ⚠️  tokenMap not found")
        return r, field, value

    def step6_submit_email(self, login_url: str, token_field: str, token_value: str):
        print(f"🔄 Step 6: Submitting email: {self.email} …")
        r = self.session.post(
            login_url,
            data={token_field: token_value, "username": self.email},
            headers={
                "Content-Type"  : "application/x-www-form-urlencoded",
                "Sec-Fetch-Site": "same-origin",
                "Origin"        : SSO_BASE,
                "Referer"       : f"{SSO_BASE}/",
                "priority"      : "u=0, i",
            },
            allow_redirects=True,
        )
        print(f"   → {r.status_code} | {r.url}")
        return r

    def step8_submit_registration(self, post_url: str, token_field: str, token_value: str):
        print("🔄 Step 8: Submitting registration …")
        r = self.session.post(
            post_url,
            data={
                token_field                : token_value,
                "registerSwitch"           : "true",
                "username"                 : self.email,
                "dpaVersion"               : "8",
                "password"                 : self.password,
                "passwordRepeat"           : self.password,
                "dataProtectionAcceptance" : "true",
                "_dataProtectionAcceptance": "on",
            },
            headers={
                "Content-Type"  : "application/x-www-form-urlencoded",
                "Sec-Fetch-Site": "same-origin",
                "Origin"        : SSO_BASE,
                "Referer"       : f"{SSO_BASE}/",
                "priority"      : "u=0, i",
            },
            allow_redirects=True,
        )
        # Save HTML
        # with open("login_page.html", "w", encoding="utf-8") as f:
        #     f.write(r.text)
        print(f"   → {r.status_code} | {r.url}")
        if r.status_code not in (200, 302):
            print(f"   Body: {r.text[:400]}")
        return r

    def step9_skip_onboarding(self, auth_token: str):
        print("🔄 Step 9: Skip onboarding …")
        xsrf_token = self.session.cookies.get("XSRF-TOKEN", "")
        r = self.session.post(
            f"{SSO_BASE}/api/onboarding/skip",
            params={"isPostRegistration": "true"},
            json={},
            headers={
                "Content-Type"   : "application/json",
                "Accept"         : "*/*",
                "Authorization"  : auth_token,
                "Sec-Fetch-Site" : "same-origin",
                "Sec-Fetch-Mode" : "cors",
                "Sec-Fetch-Dest" : "empty",
                "Origin"         : SSO_BASE,
                "Referer"        : f"{SSO_BASE}/",
                "x-xsrf-token"   : xsrf_token,
                "Cache-Control"  : "max-age=0",
                "priority"       : "u=3, i",
            },
        )
        print(f"   → {r.status_code} | {r.text[:200]}")
        return r

    def verify_email(self, url: str = None) -> bool:
        if url is None:
            print("\n📧 Check your inbox and paste the ImmoScout24 verification link below.")
            url = input("   Verification URL: ").strip()
        if not url:
            print("   ⚠️  No URL entered — skipping verification.")
            return False
        print("🔄 Verifying ImmoScout24 email …")
        r = self.session.get(url, allow_redirects=True)
        print(f"   → {r.status_code} | {r.url}")
        if r.status_code == 200:
            print("   ✓ Email verified successfully.")
            return True
        else:
            print(f"   ⚠️  Unexpected status {r.status_code}")
            return False

    # ── orchestrator ────────────────────────────────────────────────────────────

    def run(self) -> bool:
        print(f"\n{'='*60}")
        print(f"  ImmoScout24 Mobile Registration → {self.email}")
        print(f"{'='*60}\n")

        self.step1_app_validation()
        time.sleep(0.4)

        self.step2_oidc_discover()
        time.sleep(0.3)

        self.step3_authorize()
        time.sleep(0.5)

        r4 = self.step4_sso_authenticate()
        time.sleep(0.5)

        # Try to get tokenMap from the authenticate response first
        field, value = self._extract_token(r4.text)
        if field:
            print(f"   Token (from authenticate): {field} = {value}")
            login_url = r4.url
        else:
            # Fall back to explicit login page GET
            r5, field, value = self.step5_get_login_page()
            login_url = r5.url
            if not field:
                print("❌ Could not obtain tokenMap — aborting.")
                return False
        time.sleep(0.5)

        r6 = self.step6_submit_email(login_url, field, value)
        time.sleep(0.5)

        # Re-extract tokenMap from password/registration page
        new_field, new_value = self._extract_token(r6.text)
        if new_field:
            field, value = new_field, new_value
            print(f"   New token (password page): {field} = {value}")

        r8 = self.step8_submit_registration(r6.url, field, value)
        time.sleep(1.0)

        # ── onboarding skip ─────────────────────────────────────────────────────
        # The auth token is in data-token on <div id="react_root"> in r8.text
        auth_token = ""
        react_root = BeautifulSoup(r8.text, "html.parser").find("div", id="react_root")
        if react_root and react_root.get("data-token"):
            auth_token = react_root["data-token"]
            print(f"   Auth token extracted from react_root data-token")
        if auth_token:
            self.step9_skip_onboarding(auth_token)
            time.sleep(0.5)
        else:
            print("   ⚠️  data-token not found in react_root — skipping onboarding step")

        # ── result ──────────────────────────────────────────────────────────────
        redirect_hint = (react_root.get("data-redirect-url", "") if react_root else "")
        if redirect_hint:
            print(f"   data-redirect-url: {redirect_hint}")
        if "emailSent" in r8.url or "emailSent" in redirect_hint or "emailSent" in r8.text:
            print(f"\n{'='*60}")
            print(f"  ✓ Registration submitted for: {self.email}")
            print(f"{'='*60}\n")
            return True
        elif "Ich bin kein Roboter" in r8.text:
            print("\n❌ WAF blocked (Ich bin kein Roboter)")
            with open("mobile_fail.html", "w") as f:
                f.write(r8.text)
            return False
        else:
            print(f"\n❌ Unexpected response — URL: {r8.url}")
            print(f"   Body snippet: {r8.text[:300]}")
            with open("mobile_fail.html", "w") as f:
                f.write(r8.text)
            return False


# ── entry point ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    reg = ImmoScoutMobileRegistrar(
        email    = "test@example.com",
        password = "test@example.com",
        proxy    = PROXY,
    )
    if reg.run():
        reg.verify_email()

