"""Command line: `python -m fa analyze AAPL`, `python -m fa api`, watchlist, snapshot, doctor, schwab-login."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from fa.core.logging import setup_logging
from fa.core.settings import get_settings

app = typer.Typer(add_completion=False, help="Full Analysis — free-data stock analyzer")


@app.command()
def analyze(symbol: str, depth: str = "standard", out: Path | None = None, md: bool = True):
    """Run a full analysis and write JSON (+ a markdown dossier)."""
    setup_logging()
    from fa.pipeline.orchestrator import analyze as run
    from fa.report.dossier import to_markdown
    res = asyncio.run(run(symbol, depth))
    s = get_settings()
    path = out or (s.runs_dir / f"{res['run_id']}.json")
    path.write_text(json.dumps(res, default=str), encoding="utf-8")
    sc = res.get("scores", {}).get("horizons", {})
    for h in ("long", "medium", "short"):
        x = sc.get(h, {})
        typer.echo(f"{h:7s} score={x.get('score')!s:>6}  {x.get('label')!s:20s} coverage={x.get('coverage', 0):.0%} confidence={x.get('confidence', 0):.0%}")
    typer.echo(f"status={res['status']} sections_failed={[k for k, v in res['sections'].items() if v['status'] != 'ok']} fetches={res['meta']['n_fetches']} {res['meta']['total_ms']}ms")
    typer.echo(f"json: {path}")
    if md:
        mdp = path.with_suffix(".md")
        mdp.write_text(to_markdown(res), encoding="utf-8")
        typer.echo(f"dossier: {mdp}")


@app.command()
def api(host: str | None = None, port: int | None = None, reload: bool = False):
    """Start the FastAPI server (also runs the scheduler)."""
    import uvicorn
    s = get_settings()
    uvicorn.run("fa.api.main:app", host=host or s.api_host, port=port or s.api_port, reload=reload)


@app.command()
def watch(action: str, symbol: str = ""):
    """watch add AAPL | watch remove AAPL | watch list"""
    from fa.store import repos
    if action == "add" and symbol:
        repos.add_watch(symbol)
    elif action == "remove" and symbol:
        repos.remove_watch(symbol)
    typer.echo(repos.watchlist().to_string(index=False))


@app.command()
def snapshot(symbol: str = ""):
    """Run the close-snapshot job now (all watchlist symbols, or one)."""
    setup_logging()
    from fa.pipeline.orchestrator import analyze as run
    from fa.pipeline.scheduler import close_snapshot
    if symbol:
        asyncio.run(run(symbol, "quick", sections=["fundamentals", "technicals", "options", "analysts", "shorts"]))
    else:
        asyncio.run(close_snapshot())
    typer.echo("snapshot done")


@app.command()
def doctor():
    """Check environment, data root, providers and store."""
    setup_logging()
    from fa.registry.router import get_router
    from fa.store import duck
    s = get_settings()
    typer.echo(f"data root: {s.data_root}  (onedrive={'onedrive' in str(s.data_root).lower()})")
    typer.echo(f"SEC UA: {s.sec_user_agent}")
    typer.echo(f"FRED key: {'set' if s.fred_api_key else 'MISSING (macro falls back to Treasury/Stooq)'}")
    typer.echo(f"Reddit: {'set' if s.reddit_client_id else 'not set'}   Finnhub: {'set' if s.finnhub_api_key else 'not set'}   Schwab: {'set' if s.schwab_app_key else 'not set'}")
    r = get_router()
    for h in asyncio.run(r.health()):
        typer.echo(f"  {h['provider']:11s} loaded={h['loaded']!s:5s} available={h['available']!s:5s} tier={h['tier']} latency={h['latency']}")
    st = duck.stats()
    typer.echo(f"duckdb: {st['duckdb_path']} read_only={st['read_only']} tables={st['tables']}")
    typer.echo(f"lake: { {k: v['files'] for k, v in st['lake'].items()} }")


@app.command("schwab-login")
def schwab_login():
    """One-time Schwab OAuth: opens the browser, paste the redirect URL back here."""
    import base64
    import time
    import webbrowser
    import httpx
    s = get_settings()
    if not s.schwab_app_key:
        typer.echo("set FA_SCHWAB_APP_KEY / FA_SCHWAB_APP_SECRET in .env first")
        raise typer.Exit(1)
    url = f"https://api.schwabapi.com/v1/oauth/authorize?client_id={s.schwab_app_key}&redirect_uri={s.schwab_callback_url}"
    typer.echo(f"Opening: {url}")
    webbrowser.open(url)
    redirected = typer.prompt("Paste the full redirect URL after login")
    code = redirected.split("code=")[1].split("&")[0].replace("%40", "@")
    basic = base64.b64encode(f"{s.schwab_app_key}:{s.schwab_app_secret}".encode()).decode()
    r = httpx.post("https://api.schwabapi.com/v1/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": s.schwab_callback_url},
                   headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    if r.status_code != 200:
        typer.echo(f"token exchange failed: {r.status_code} {r.text[:300]}")
        raise typer.Exit(1)
    j = r.json()
    (s.data_root / "schwab_tokens.json").write_text(json.dumps({"access_token": j["access_token"], "refresh_token": j["refresh_token"], "expires_at": time.time() + int(j.get("expires_in", 1800))}))
    typer.echo("Schwab tokens saved. The refresh token lasts 7 days; rerun this command when it expires.")


if __name__ == "__main__":
    app()
