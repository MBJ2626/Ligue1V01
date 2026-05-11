from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import database as db
from .extractor import extract_document, sha256_file
from .parser import parse_match_sheet

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
EXPORT_DIR = BASE_DIR / "data" / "exports"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Tunisia MatchSheet DB", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ALLOWED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".xlsm", ".xls", ".csv"}


def safe_filename(name: str) -> str:
    stem = Path(name).stem[:80]
    suffix = Path(name).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "document"
    return f"{stem}{suffix}"


def json_pretty(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def dash(value: Any) -> str:
    return "—" if value is None or value == "" else str(value)


def score(match: dict[str, Any]) -> str:
    if match.get("score_home") is None or match.get("score_away") is None:
        return "—"
    return f"{match.get('score_home')} - {match.get('score_away')}"


def minute_label(row: dict[str, Any]) -> str:
    if row.get("minute") is None:
        return "—"
    label = str(row.get("minute"))
    if row.get("stoppage"):
        label += f"+{row.get('stoppage')}"
    return label + "'"


def event_label(row: dict[str, Any]) -> str:
    event_type = row.get("event_type") or "note"
    if event_type == "goal":
        return "But"
    if event_type == "card":
        return "Carton jaune" if row.get("card_color") == "yellow" else "Carton rouge" if row.get("card_color") == "red" else "Carton"
    if event_type == "substitution":
        return "Remplacement"
    return event_type.capitalize()


def pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except Exception:
        return "—"


templates.env.filters["json_pretty"] = json_pretty
templates.env.filters["dash"] = dash
templates.env.filters["score"] = score
templates.env.filters["minute_label"] = minute_label
templates.env.filters["event_label"] = event_label
templates.env.filters["pct"] = pct



def split_semicolon_lines(text: str | None) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append([part.strip() for part in line.split(";")])
    return rows


def get_part(parts: list[str], index: int, default: str = "") -> str:
    return parts[index].strip() if index < len(parts) and parts[index] is not None else default


def manual_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "oui", "yes", "true", "vrai", "x", "c", "capitaine", "g", "gardien"}


def normalize_manual_role(value: str) -> tuple[str, bool, bool]:
    role_key = value.strip().lower().replace("é", "e").replace("ç", "c")
    starter = role_key in {"titulaire", "starter", "t", "11"}
    substitute = role_key in {"remplacant", "remplaçant", "substitute", "bench", "r"}
    role = "titulaire" if starter else "remplaçant" if substitute else (value.strip() or "joueur")
    return role, starter, substitute


def parse_manual_players(text: str | None) -> list[dict[str, Any]]:
    players: list[dict[str, Any]] = []
    for parts in split_semicolon_lines(text):
        role, starter, substitute = normalize_manual_role(get_part(parts, 3, "titulaire"))
        name = get_part(parts, 1)
        if not name:
            continue
        players.append(
            {
                "number": get_part(parts, 0),
                "name": name,
                "license_number": get_part(parts, 2),
                "role": role,
                "starter": starter,
                "substitute": substitute,
                "captain": manual_truthy(get_part(parts, 4)),
                "goalkeeper": manual_truthy(get_part(parts, 5)),
                "position": get_part(parts, 6),
                "nationality": get_part(parts, 7),
                "notes": get_part(parts, 8),
            }
        )
    return players


def parse_manual_staff(text: str | None) -> list[dict[str, Any]]:
    staff: list[dict[str, Any]] = []
    for parts in split_semicolon_lines(text):
        name = get_part(parts, 0)
        if name:
            staff.append({"name": name, "role": get_part(parts, 1) or "Staff"})
    return staff


def parse_manual_officials(text: str | None) -> list[dict[str, Any]]:
    officials: list[dict[str, Any]] = []
    for parts in split_semicolon_lines(text):
        role = get_part(parts, 0)
        name = get_part(parts, 1)
        if name:
            officials.append({"role": role or "OFFICIEL", "name": name})
    return officials


def card_color_value(value: str) -> str:
    key = value.strip().lower()
    if key in {"rouge", "red", "r"}:
        return "red"
    return "yellow"


def build_manual_payload(
    *,
    competition: str,
    season: str,
    round_label: str,
    status: str,
    match_date: str,
    match_time: str,
    stadium: str,
    city: str,
    home_team: str,
    away_team: str,
    score_home: str,
    score_away: str,
    halftime_home: str,
    halftime_away: str,
    home_players: str,
    away_players: str,
    home_staff: str,
    away_staff: str,
    officials: str,
    goals: str,
    cards: str,
    substitutions: str,
    observations: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "_meta": {"source": "manual_entry", "confidence": 1.0, "warnings": []},
        "match": {
            "competition": competition.strip(),
            "season": season.strip(),
            "round": round_label.strip(),
            "date": match_date.strip(),
            "time": match_time.strip(),
            "stadium": stadium.strip(),
            "city": city.strip(),
            "home_team": home_team.strip(),
            "away_team": away_team.strip(),
            "score_home": score_home.strip(),
            "score_away": score_away.strip(),
            "halftime_home": halftime_home.strip(),
            "halftime_away": halftime_away.strip(),
            "status": status.strip() or "played",
        },
        "teams": [
            {"side": "home", "name": home_team.strip(), "players": parse_manual_players(home_players), "staff": parse_manual_staff(home_staff)},
            {"side": "away", "name": away_team.strip(), "players": parse_manual_players(away_players), "staff": parse_manual_staff(away_staff)},
        ],
        "officials": parse_manual_officials(officials),
        "events": [],
        "observations": [],
    }

    for parts in split_semicolon_lines(goals):
        if get_part(parts, 2):
            payload["events"].append({"event_type": "goal", "minute": get_part(parts, 0), "team": get_part(parts, 1), "player": get_part(parts, 2), "detail": get_part(parts, 3)})

    for parts in split_semicolon_lines(cards):
        if get_part(parts, 2):
            color = card_color_value(get_part(parts, 3))
            payload["events"].append({"event_type": "card", "minute": get_part(parts, 0), "team": get_part(parts, 1), "player": get_part(parts, 2), "card_color": color, "detail": get_part(parts, 4)})

    for parts in split_semicolon_lines(substitutions):
        if get_part(parts, 2) or get_part(parts, 3):
            payload["events"].append({"event_type": "substitution", "minute": get_part(parts, 0), "team": get_part(parts, 1), "player": get_part(parts, 2), "related_player": get_part(parts, 3), "detail": get_part(parts, 4)})

    for parts in split_semicolon_lines(observations):
        note = get_part(parts, 3) or get_part(parts, 0)
        if note:
            payload["observations"].append({"minute": get_part(parts, 0) if len(parts) > 3 else "", "author": get_part(parts, 1), "severity": get_part(parts, 2) or "note", "note": note})

    home_starters = sum(1 for p in payload["teams"][0]["players"] if p.get("starter"))
    away_starters = sum(1 for p in payload["teams"][1]["players"] if p.get("starter"))
    if home_starters and home_starters != 11:
        payload["_meta"]["warnings"].append(f"Domicile: {home_starters} titulaires saisis au lieu de 11.")
    if away_starters and away_starters != 11:
        payload["_meta"]["warnings"].append(f"Extérieur: {away_starters} titulaires saisis au lieu de 11.")
    return payload


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("dashboard.html", {"request": request, "stats": db.dashboard_stats(), "page": "dashboard"})


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("upload.html", {"request": request, "page": "upload", "allowed": sorted(ALLOWED_SUFFIXES)})




@app.get("/manual", response_class=HTMLResponse)
def manual_entry_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("manual_entry.html", {"request": request, "page": "manual"})


@app.post("/manual")
def create_manual_match(
    competition: str = Form(""),
    season: str = Form(""),
    round_label: str = Form(""),
    status: str = Form("played"),
    match_date: str = Form(""),
    match_time: str = Form(""),
    stadium: str = Form(""),
    city: str = Form(""),
    home_team: str = Form(...),
    away_team: str = Form(...),
    score_home: str = Form(""),
    score_away: str = Form(""),
    halftime_home: str = Form(""),
    halftime_away: str = Form(""),
    home_players: str = Form(""),
    away_players: str = Form(""),
    home_staff: str = Form(""),
    away_staff: str = Form(""),
    officials: str = Form(""),
    goals: str = Form(""),
    cards: str = Form(""),
    substitutions: str = Form(""),
    observations: str = Form(""),
) -> RedirectResponse:
    payload = build_manual_payload(
        competition=competition,
        season=season,
        round_label=round_label,
        status=status,
        match_date=match_date,
        match_time=match_time,
        stadium=stadium,
        city=city,
        home_team=home_team,
        away_team=away_team,
        score_home=score_home,
        score_away=score_away,
        halftime_home=halftime_home,
        halftime_away=halftime_away,
        home_players=home_players,
        away_players=away_players,
        home_staff=home_staff,
        away_staff=away_staff,
        officials=officials,
        goals=goals,
        cards=cards,
        substitutions=substitutions,
        observations=observations,
    )
    match_ids = db.insert_matches_from_payload(payload, document_id=None)
    if not match_ids:
        raise HTTPException(status_code=400, detail="Aucun match n'a pu être créé depuis la saisie manuelle.")
    return RedirectResponse(url=f"/matches/{match_ids[0]}", status_code=303)


@app.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)) -> RedirectResponse:
    created_ids: list[int] = []
    for uploaded in files:
        suffix = Path(uploaded.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            continue
        base_name = safe_filename(uploaded.filename or f"document{suffix}")
        target = UPLOAD_DIR / base_name
        counter = 1
        while target.exists():
            target = UPLOAD_DIR / f"{Path(base_name).stem}_{counter}{suffix}"
            counter += 1
        with target.open("wb") as f:
            shutil.copyfileobj(uploaded.file, f)
        content_hash = sha256_file(target)
        extracted = extract_document(target)
        payload = parse_match_sheet(
            extracted.text,
            extracted.tables,
            source_name=uploaded.filename,
            extractor_warnings=extracted.warnings,
            extractor_confidence=extracted.confidence,
        )
        doc_id = db.create_document(
            original_filename=uploaded.filename or base_name,
            stored_filename=target.name,
            stored_path=str(target),
            file_type=extracted.file_type,
            sha256=content_hash,
            raw_text=extracted.text,
            extracted_json=payload,
            confidence=payload.get("_meta", {}).get("confidence", extracted.confidence),
            status="draft",
            error_message="; ".join(extracted.warnings) if extracted.warnings else None,
        )
        created_ids.append(doc_id)
    if not created_ids:
        return RedirectResponse(url="/upload?error=unsupported", status_code=303)
    if len(created_ids) == 1:
        return RedirectResponse(url=f"/review/{created_ids[0]}", status_code=303)
    return RedirectResponse(url="/documents", status_code=303)


@app.get("/documents", response_class=HTMLResponse)
def documents(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("documents.html", {"request": request, "documents": db.list_documents(), "page": "documents"})


@app.get("/review/{document_id}", response_class=HTMLResponse)
def review_document(request: Request, document_id: int) -> HTMLResponse:
    document = db.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")
    try:
        payload = json.loads(document.get("extracted_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    return templates.TemplateResponse("review.html", {"request": request, "document": document, "payload": payload, "payload_text": json_pretty(payload), "page": "documents"})


@app.post("/review/{document_id}/save")
def save_review(document_id: int, payload_text: str = Form(...)) -> RedirectResponse:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON invalide: {exc}")
    db.update_document_payload(document_id, payload, status="draft")
    return RedirectResponse(url=f"/review/{document_id}?saved=1", status_code=303)


@app.post("/review/{document_id}/finalize")
def finalize_document(document_id: int, payload_text: str = Form(...)) -> RedirectResponse:
    document = db.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")
    if document.get("match_id"):
        return RedirectResponse(url=f"/matches/{document['match_id']}", status_code=303)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON invalide: {exc}")
    db.update_document_payload(document_id, payload, status="draft")
    match_ids = db.insert_matches_from_payload(payload, document_id=document_id)
    if len(match_ids) == 1:
        return RedirectResponse(url=f"/matches/{match_ids[0]}", status_code=303)
    return RedirectResponse(url="/matches", status_code=303)



@app.get("/notifications", response_class=HTMLResponse)
def notifications(request: Request, period: int = 10, threshold: int = 3, include_watch: int = 1) -> HTMLResponse:
    period = max(1, min(period, 50))
    threshold = max(1, min(threshold, 10))
    items = db.list_notifications(period_matches=period, yellow_threshold=threshold, include_watch=bool(include_watch))
    stats = db.notification_stats(period_matches=period, yellow_threshold=threshold)
    return templates.TemplateResponse(
        "notifications.html",
        {
            "request": request,
            "page": "notifications",
            "notifications": items,
            "stats": stats,
            "period": period,
            "threshold": threshold,
            "include_watch": include_watch,
        },
    )


@app.get("/api/notifications")
def api_notifications(period: int = 10, threshold: int = 3, include_watch: int = 1) -> list[dict[str, Any]]:
    return db.list_notifications(period_matches=period, yellow_threshold=threshold, include_watch=bool(include_watch))

@app.get("/matches", response_class=HTMLResponse)
def matches(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("matches.html", {"request": request, "matches": db.list_matches(), "page": "matches"})


@app.get("/matches/{match_id}", response_class=HTMLResponse)
def match_detail(request: Request, match_id: int) -> HTMLResponse:
    detail = db.get_match_detail(match_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Match introuvable")
    return templates.TemplateResponse("match_detail.html", {"request": request, "detail": detail, "page": "matches"})


@app.post("/matches/{match_id}/observations")
def add_observation(match_id: int, minute: str = Form(""), author: str = Form(""), severity: str = Form("note"), note: str = Form(...)) -> RedirectResponse:
    minute_int = None
    if minute.strip():
        try:
            minute_int = int(minute.strip().replace("'", ""))
        except ValueError:
            minute_int = None
    db.add_observation(match_id, minute_int, author or None, note, severity)
    return RedirectResponse(url=f"/matches/{match_id}#observations", status_code=303)


@app.get("/players", response_class=HTMLResponse)
def players(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("players.html", {"request": request, "players": db.list_players(), "page": "players"})


@app.get("/events", response_class=HTMLResponse)
def events(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("events.html", {"request": request, "events": db.list_events(), "page": "events"})


@app.get("/officials", response_class=HTMLResponse)
def officials(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("officials.html", {"request": request, "officials": db.list_officials(), "page": "officials"})


@app.get("/api/matches")
def api_matches() -> list[dict[str, Any]]:
    return db.list_matches()


@app.get("/api/players")
def api_players() -> list[dict[str, Any]]:
    return db.list_players()


@app.get("/api/events")
def api_events() -> list[dict[str, Any]]:
    return db.list_events()


@app.get("/export/{table_name}.csv")
def export_csv(table_name: str) -> FileResponse:
    output = EXPORT_DIR / f"{table_name}.csv"
    try:
        db.export_table(table_name, output)
    except ValueError:
        raise HTTPException(status_code=404, detail="Table non exportable")
    return FileResponse(output, filename=output.name, media_type="text/csv")
