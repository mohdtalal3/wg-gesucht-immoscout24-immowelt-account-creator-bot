import time
import random
from curl_cffi import requests
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv

# ── config ──────────────────────────────────────────────────────────────────────
load_dotenv()
PROXY = os.getenv("PROXY_URL", "")
AUTH0_DOMAIN = "https://live-intermediary-iwt.eu.auth0.com"
CLIENT_ID    = "A9GlpGlu52vEjH8I8WArgr5K0CUQYcFa"
CONNECTION   = "intermediary-iwt-user-pool"
AUTH0_CLIENT = "eyJuYW1lIjoiQXV0aDAuc3dpZnQiLCJ2ZXJzaW9uIjoiMi4xOC4wIiwiZW52Ijp7InN3aWZ0IjoiNi54IiwiaU9TIjoiMjYuNSJ9fQ"
SIGNIN_BASE  = "https://signin.immowelt.de"
_IOS_IMPERSONATIONS = [
    "safari_ios",
    "safari172_ios",
    "safari180_ios",
    "safari184_ios",
    "safari260_ios",
]
APP_UA       = "Seeker_Immowelt/22 CFNetwork/3860.600.12 Darwin/25.5.0"
WEB_UA       = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"


class ImmoweltRegistrar:

    def __init__(self, email: str, password: str, proxy: str = PROXY):
        self.email    = email
        self.password = password
        proxies       = {"http": proxy, "https": proxy} if proxy else {}
        _imp = random.choice(_IOS_IMPERSONATIONS)
        print(f"   TLS impersonation: {_imp}")
        self.session = requests.Session(impersonate=_imp, verify=False, proxies=proxies)
        self.session.headers.update({
            "User-Agent"     : APP_UA,
            "Accept-Encoding": "gzip",
            "accept-language": "en-GB,en;q=0.9",
            #"auth0-client"   : AUTH0_CLIENT,
            "content-type"   : "application/json; charset=utf-8",
            "priority"       : "u=3",
        })

    # ── steps ───────────────────────────────────────────────────────────────────

    def step1_signup(self):
        print("🔄 Step 1: Signup …")
        r = self.session.post(
            f"{AUTH0_DOMAIN}/dbconnections/signup",
            json={
                "email"     : self.email,
                "password"  : self.password,
                "connection": CONNECTION,
                "client_id" : CLIENT_ID,
            },
        )
        print(f"   → {r.status_code} | {r.text[:200]}")
        return r

    def step2_token(self):
        print("🔄 Step 2: Get token …")
        r = self.session.post(
            f"{AUTH0_DOMAIN}/oauth/token",
            json={
                "client_id" : CLIENT_ID,
                "scope"     : "openid profile email offline_access",
                "username"  : self.email,
                "password"  : self.password,
                "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
                "realm"     : CONNECTION,
                "audience"  : "immowelt",
            },
        )
        print(f"   → {r.status_code} | {r.text[:200]}")
        return r

    def verify_email(self, url: str = None) -> bool:
        if url is None:
            print("\n📧 Check your inbox and paste the Immowelt verification link below.")
            url = input("   Verification URL: ").strip()
        if not url:
            print("   ⚠️  No URL entered — skipping verification.")
            return False
        print("🔄 Verifying Immowelt email …")

        _web_headers = {
            "User-Agent"    : WEB_UA,
            "Accept"        : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "sec-fetch-dest": "document",
            "sec-fetch-site": "none",
            "sec-fetch-mode": "navigate",
            "priority"      : "u=0, i",
        }

        # Step A: GET the ticket page
        r_get = self.session.get(url, headers=_web_headers, allow_redirects=True)
        print(f"   GET  → {r_get.status_code} | {r_get.url}")

        # Step B: extract hidden state field from the form
        soup        = BeautifulSoup(r_get.text, "html.parser")
        state_input = soup.find("input", {"name": "state"})
        state       = state_input["value"] if state_input else ""
        ticket_url  = r_get.url  # follow any redirects on the GET
        if state:
            print(f"   state: {state[:24]}…")
        else:
            print("   ⚠️  state not found in page — POST may fail")

        # Step C: POST to confirm the verification
        r_post = self.session.post(
            ticket_url,
            data={"state": state},
            headers={
                **_web_headers,
                "Content-Type"  : "application/x-www-form-urlencoded",
                "origin"        : SIGNIN_BASE,
                "sec-fetch-site": "same-origin",
                "referer"       : ticket_url,
            },
            allow_redirects=True,
        )
        print(f"   POST → {r_post.status_code} | {r_post.url}")

        if r_post.status_code == 200:
            print("   ✓ Email verified successfully.")
            return True
        else:
            print(f"   ⚠️  Unexpected status {r_post.status_code}")
            return False

    # ── orchestrator ────────────────────────────────────────────────────────────

    def run(self) -> bool:
        print(f"\n{'='*60}")
        print(f"  Immowelt Registration → {self.email}")
        print(f"{'='*60}\n")
        
        r1 = self.step1_signup()
        if r1.status_code not in (200, 201):
            print(f"\n❌ Signup failed")
            return False
        time.sleep(0.5)

        r2 = self.step2_token()
        email_sent = "EMAIL_VERIFICATION_SENT" in r2.text
        if r2.status_code == 200 or email_sent:
            print(f"\n{'='*60}")
            print(f"  ✓ Registration successful for: {self.email}")
            if email_sent:
                print(f"    Verification email sent — check inbox.")
            print(f"{'='*60}\n")
            return True
        else:
            print(f"\n❌ Token request failed: {r2.text[:200]}")
            return False


# ── entry point ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    reg = ImmoweltRegistrar(
        email    = "test@example.com",
        password = "test@example.com",
        proxy    = PROXY,
    )
    if reg.run():
        reg.verify_email()
