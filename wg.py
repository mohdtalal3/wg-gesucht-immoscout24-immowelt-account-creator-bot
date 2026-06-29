import json
import os
import random
from curl_cffi import requests

_IOS_IMPERSONATIONS = [
    "safari_ios",
    "safari172_ios",
    "safari180_ios",
    "safari184_ios",
    "safari260_ios",
]


class WGRegistrar:

    URL = "https://www.wg-gesucht.de/api/registers"

    def __init__(self, email: str, password: str, first_name: str, last_name: str,
                 title: str = "1", proxy: str = ""):
        self.email      = email
        self.password   = password
        self.first_name = first_name
        self.last_name  = last_name
        self.title      = title

        proxies = {"http": proxy, "https": proxy} if proxy else {}
        _imp = random.choice(_IOS_IMPERSONATIONS)
        print(f"   TLS impersonation: {_imp}")
        self.session = requests.Session(impersonate=_imp, verify=False, proxies=proxies)
        self.session.headers.update({
            "x-client-id"  : "wg_mobile_app",
            "accept"        : "application/json",
            "x-app-version" : "2.0.36",
            "x-app-os"      : "android_native",
            "user-agent"    : "WG-Gesucht-Android/2.0.36 (build 5076; okhttp/4.12.0)",
            "content-type"  : "application/json",
        })

    def run(self) -> bool:
        print(f"\n{'='*60}")
        print(f"  WG-Gesucht Registration → {self.email}")
        print(f"{'='*60}\n")

        payload = {
            "title"          : self.title,
            "first_name"     : self.first_name,
            "last_name"      : self.last_name,
            "company_name"   : "",
            "email"          : self.email,
            "password"       : self.password,
            "i_agree"        : "1",
            "gdpr_checkbox_0": "1",
            "gdpr_checkbox_1": "1",
            "gdpr_checkbox_2": "1",
            "user_type"      : "0",
            "language_setting": "en",
            "policy_version" : "2.0",
        }

        try:
            r = self.session.post(self.URL, json=payload, allow_redirects=True)
            print(f"   STATUS: {r.status_code}")
            try:
                print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:400])
            except Exception:
                print(r.text[:200])

            if r.status_code in (200, 201):
                print(f"\n✓ WG-Gesucht registration submitted for: {self.email}")
                return True
            else:
                print(f"\n❌ WG-Gesucht registration failed: {r.status_code}")
                return False
        except Exception as e:
            print(f"   Request failed: {e}")
            return False

    def verify_email(self, url: str = None) -> bool:
        if url is None:
            print("\n📧 Check your inbox and paste the WG-Gesucht verification link below.")
            url = input("   Verification URL: ").strip()
        if not url:
            print("   ⚠️  No URL — skipping verification.")
            return False
        print("🔄 Verifying WG-Gesucht email …")
        try:
            r = self.session.get(url, allow_redirects=True)
            print(f"   → {r.status_code} | {r.url}")
            if r.status_code == 200:
                print("   ✓ Email verified successfully.")
                return True
            else:
                print(f"   ⚠️  Unexpected status {r.status_code}")
                return False
        except Exception as e:
            print(f"   Verification failed: {e}")
            return False


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    PROXY = os.getenv("PROXY_URL", "")
    reg = WGRegistrar(
        email      = "test@example.com",
        password   = "test@example.com",
        first_name = "Max",
        last_name  = "Mueller",
        title      = "1",
        proxy      = PROXY,
    )
    if reg.run():
        reg.verify_email()