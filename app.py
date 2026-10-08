"""ActaSegura: API + fila SQLite + worker 2.5s + monitoramento visitas/buscas. Busca sem DNI."""
import sqlite3, uuid, threading, time, re, calendar, secrets
from datetime import date, timedelta, datetime
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import requests

DB = "jobs.db"
URL = "https://apps.reniec.gob.pe/actascertificadas/actas/consultar_acta.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DELAY = 2.5
MAX_DIAS = 366
PAUSADO = False # buscas ligadas; True pausa

BASE = Path(__file__).parent
TOKEN_FILE = BASE / "admin_token.txt"
def admin_token():
    try:
        if TOKEN_FILE.exists():
            t = TOKEN_FILE.read_text().strip()
            if len(t) >= 8:
                return t
    except Exception:
        pass
    t = secrets.token_urlsafe(12)
    try:
        TOKEN_FILE.write_text(t)
    except Exception:
        pass
    return t
ADMIN_SECRET = admin_token()

BOTS = ("bot", "crawl", "spider", "censys", "shodan", "masscan",
        "internetmeasurement", "cms-checker", "checker", "scanner",
        "python-requests", "curl", "wget", "go-http")

def is_bot(ua: str) -> bool:
    u = (ua or "").lower()
    return any(b in u for b in BOTS)

def get_ip(req: Request) -> str:
    for h in ("x-forwarded-for", "x-real-ip"):
        v = req.headers.get(h, "")
        if v:
            return v.split(",")[0].strip()[:45]
    try:
        return (req.client.host if req.client else "?")[:45]
    except Exception:
        return "?"

def is_admin_req(req: Request) -> bool:
    try:
        return req.cookies.get("as_admin", "") == ADMIN_SECRET
    except Exception:
        return False

app = FastAPI()

def db():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,status TEXT,result TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS visits(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ip TEXT, ua TEXT, ref TEXT, is_admin INTEGER, is_bot INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS searches(
        id TEXT PRIMARY KEY, ts TEXT, ip TEXT, ua TEXT, tipo TEXT, paterno TEXT, materno TEXT,
        nombres TEXT, fecha TEXT, total INTEGER, is_admin INTEGER, is_bot INTEGER,
        status TEXT, result TEXT)""")
    return c

def log_visit(req: Request):
    try:
        c = db()
        c.execute("INSERT INTO visits(ts,ip,ua,ref,is_admin,is_bot) VALUES(?,?,?,?,?,?)",
            (datetime.utcnow().isoformat(timespec="seconds"),
             get_ip(req), (req.headers.get("user-agent") or "")[:300],
             (req.headers.get("referer") or "")[:500],
             1 if is_admin_req(req) else 0,
             1 if is_bot(req.headers.get("user-agent") or "") else 0))
        c.commit(); c.close()
    except Exception:
        pass

def log_search(jid: str, req: Request, j, total: int):
    try:
        c = db()
        c.execute("""INSERT OR REPLACE INTO searches
            (id,ts,ip,ua,tipo,paterno,materno,nombres,fecha,total,is_admin,is_bot,status,result)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, datetime.utcnow().isoformat(timespec="seconds"),
             get_ip(req), (req.headers.get("user-agent") or "")[:300],
             j.tipo, j.paterno.upper().strip()[:60], j.materno.upper().strip()[:60],
             j.nombres.upper().strip()[:80], j.fecha.strip()[:20], total,
             1 if is_admin_req(req) else 0,
             1 if is_bot(req.headers.get("user-agent") or "") else 0,
             "queued", "en cola"))
        c.commit(); c.close()
    except Exception:
        pass

def update_search(jid: str, status: str, result: str):
    try:
        c = db()
        c.execute("UPDATE searches SET status=?,result=? WHERE id=?", (status, result[:300], jid))
        c.commit(); c.close()
    except Exception:
        pass

class Job(BaseModel):
    tipo: str
    paterno: str
    materno: str
    nombres: str
    fecha: str

def consulta_unica(tipo, fecha, pat, mat, nom, session=None):
    s = session or requests.Session()
    new_session = session is None
    if new_session:
        s.headers.update({"User-Agent": UA})
        s.get("https://apps.reniec.gob.pe/actascertificadas", timeout=20)
    h = {"X-Requested-With": "XMLHttpRequest", "Referer": "https://apps.reniec.gob.pe/actascertificadas"}
    if tipo == "01":
        d, m, y = fecha.split("/")
        data = {"tipoActa": tipo, "fechaNacimiento": fecha, "fechaEvento": f"{y}{m}{d}",
                "primerApellido": pat.upper().strip(), "segundoApellido": mat.upper().strip(), "preNombres": nom.upper().strip()}
    elif tipo == "02":
        y, mo = fecha.split("-")
        data = {"tipoActa": tipo, "anyoMatrimonio": y, "mesMatrimonio": mo, "fechaEvento": y + mo,
                "primerApellido": pat.upper().strip(), "segundoApellido": mat.upper().strip(), "preNombres": nom.upper().strip()}
    else:
        data = {"tipoActa": tipo, "anyoDefuncion": fecha, "fechaEvento": fecha,
                "primerApellido": pat.upper().strip(), "segundoApellido": mat.upper().strip(), "preNombres": nom.upper().strip()}
    r = s.post(URL, data=data, headers=h, timeout=20)
    return "UBICADA - Acta ubicada en RENIEC" if "Acta ubicada" in r.text else "NO - No se ubica"

def datas_do_ano(ano: int):
    d0 = date(ano, 1, 1)
    d1 = date(ano, 12, 31)
    out = []
    d = d0
    while d <= d1:
        out.append(d.strftime("%d/%m/%Y"))
        d += timedelta(days=1)
    return out

def datas_do_mes(ano: int, mes: int):
    ndias = calendar.monthrange(ano, mes)[1]
    return [date(ano, mes, d).strftime("%d/%m/%Y") for d in range(1, ndias + 1)]

def expandir_fechas(tipo, fecha):
    fecha = fecha.strip()
    if tipo == "01":
        if re.fullmatch(r"\d{4}", fecha):
            ano = int(fecha)
            if ano < 1800 or ano > date.today().year:
                raise ValueError("año fuera de 1800-hoy")
            return datas_do_ano(ano)
        if re.fullmatch(r"\d{4}-\d{2}", fecha):
            ano, mes = int(fecha[:4]), int(fecha[5:7])
            if ano < 1800 or ano > date.today().year or mes < 1 or mes > 12:
                raise ValueError("mes inválido (usa AAAA-MM, ej. 1938-09)")
            return datas_do_mes(ano, mes)
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", fecha):
            return [fecha]
        raise ValueError("tipo 01: usa dd/mm/aaaa, AAAA-MM o solo el año AAAA")
    if tipo == "02":
        if re.fullmatch(r"\d{4}", fecha):
            ano = int(fecha)
            return [f"{ano}-{m:02d}" for m in range(1, 13)]
        if re.fullmatch(r"\d{4}-\d{2}", fecha):
            return [fecha]
        raise ValueError("tipo 02: usa aaaa-mm o solo el año AAAA")
    # 03 defuncion: ano exato
    if re.fullmatch(r"\d{4}", fecha):
        return [fecha]
    raise ValueError("tipo 03: usa solo el año AAAA")

def load_job_params(jid):
    if jid in JOBS:
        return JOBS[jid]
    try:
        c = db()
        r = c.execute("SELECT tipo,paterno,materno,nombres,fecha FROM searches WHERE id=?", (jid,)).fetchone()
        c.close()
        if r:
            return {"tipo": r[0], "paterno": r[1], "materno": r[2], "nombres": r[3], "fecha": r[4]}
    except Exception:
        pass
    return None

def worker():
    while True:
        c = db()
        row = c.execute("SELECT id FROM jobs WHERE status='queued' LIMIT 1").fetchone()
        if not row:
            c.close(); time.sleep(1); continue
        jid = row[0]
        c.execute("UPDATE jobs SET status='working',result='iniciando...' WHERE id=?", (jid,))
        c.commit(); c.close()
        update_search(jid, "working", "iniciando...")
        try:
            job = load_job_params(jid)
            if not job:
                raise ValueError("job sin parámetros (¿servidor reiniciado? reenvía)")
            fechas = expandir_fechas(job["tipo"], job["fecha"])
            total = len(fechas)
            if total > MAX_DIAS:
                raise ValueError(f"demasiadas fechas ({total} > {MAX_DIAS})")
            s = requests.Session()
            s.headers.update({"User-Agent": UA})
            s.get("https://apps.reniec.gob.pe/actascertificadas", timeout=20)
            encontrada = None
            for i, f in enumerate(fechas, 1):
                r = consulta_unica(job["tipo"], f, job["paterno"], job["materno"], job["nombres"], session=s)
                if r.startswith("UBICADA"):
                    encontrada = f
                    msg = f"UBICADA en {f} ({i}/{total}) - Acta ubicada en RENIEC"
                    cw = db(); cw.execute("UPDATE jobs SET status='done',result=? WHERE id=?", (msg, jid)); cw.commit(); cw.close()
                    update_search(jid, "done", msg)
                    break
                cp = db(); cp.execute("UPDATE jobs SET result=? WHERE id=?",
                    (f"revisando {i}/{total}…", jid)); cp.commit(); cp.close()
                if i % 5 == 0:
                    update_search(jid, "working", f"revisando {i}/{total}…")
                time.sleep(DELAY)
            if not encontrada:
                msg = f"NO - {total} fecha(s) revisada(s), ninguna ubicada"
                c2 = db(); c2.execute("UPDATE jobs SET status='done',result=? WHERE id=?", (msg, jid)); c2.commit(); c2.close()
                update_search(jid, "done", msg)
        except Exception as e:
            msg = str(e)[:300]
            c3 = db(); c3.execute("UPDATE jobs SET status='error',result=? WHERE id=?", (msg, jid)); c3.commit(); c3.close()
            update_search(jid, "error", msg)

JOBS = {}
threading.Thread(target=worker, daemon=True).start()

@app.on_event("startup")
def marca_stale():
    try:
        c = db()
        c.execute("UPDATE jobs SET status='error',result='servidor reiniciado, reenvía la búsqueda' WHERE status IN ('working','queued')")
        c.execute("UPDATE searches SET status='error',result='servidor reiniciado' WHERE status IN ('working','queued')")
        c.commit(); c.close()
    except Exception:
        pass

@app.get("/", response_class=HTMLResponse)
def home(request: Request, admin: str = ""):
    html = open(BASE / "index.html", encoding="utf-8").read()
    # ativação modo admin via link secreto: /?admin=TOKEN
    if admin and admin == ADMIN_SECRET:
        resp = HTMLResponse(html)
        resp.set_cookie("as_admin", ADMIN_SECRET, max_age=31536000, httponly=True, samesite="lax")
        # não conta como visita de cliente
        try:
            c = db()
            c.execute("INSERT INTO visits(ts,ip,ua,ref,is_admin,is_bot) VALUES(?,?,?,?,?,?)",
                (datetime.utcnow().isoformat(timespec="seconds"), get_ip(request),
                 (request.headers.get("user-agent") or "")[:300], "admin-activate", 1, 0))
            c.commit(); c.close()
        except Exception:
            pass
        return resp
    log_visit(request)
    return HTMLResponse(html)

@app.post("/jobs")
def create(j: Job, request: Request):
    if PAUSADO:
        return {"error": "búsquedas en pausa temporalmente — pedidos por WhatsApp"}
    if j.tipo not in ("01", "02", "03"):
        return {"error": "tipo inválido"}
    try:
        total = len(expandir_fechas(j.tipo, j.fecha))
    except ValueError as e:
        return {"error": str(e)}
    if total > MAX_DIAS:
        return {"error": f"demasiadas fechas ({total} > {MAX_DIAS})"}
    jid = uuid.uuid4().hex[:8]
    JOBS[jid] = j.model_dump()
    c = db(); c.execute("INSERT INTO jobs VALUES(?,?,?)", (jid, "queued", f"en cola: {total} fecha(s), ~{int(total*DELAY/60)} min")); c.commit(); c.close()
    log_search(jid, request, j, total)
    return {"id": jid, "total": total}

@app.get("/jobs/{jid}")
def status(jid: str):
    c = db(); r = c.execute("SELECT status,result FROM jobs WHERE id=?", (jid,)).fetchone(); c.close()
    if not r: return {"status": "error", "result": "id inválido"}
    return {"status": r[0], "result": r[1]}

@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request):
    if not is_admin_req(request):
        return HTMLResponse("<h3>403 — área do dono</h3><p>Acesse seu link secreto uma vez para ativar este aparelho.</p>", status_code=403)
    c = db()
    tv = c.execute("SELECT COUNT(*) FROM visits WHERE is_admin=0 AND is_bot=0").fetchone()[0]
    tv_all = c.execute("SELECT COUNT(*) FROM visits WHERE is_admin=0").fetchone()[0]
    uniq = c.execute("SELECT COUNT(DISTINCT ip) FROM visits WHERE is_admin=0 AND is_bot=0").fetchone()[0]
    ts = c.execute("SELECT COUNT(*) FROM searches WHERE is_admin=0 AND is_bot=0").fetchone()[0]
    ubic = c.execute("SELECT COUNT(*) FROM searches WHERE is_admin=0 AND is_bot=0 AND result LIKE 'UBICADA%'").fetchone()[0]
    rows_v = c.execute("""SELECT ts,ip,substr(ua,1,70),substr(COALESCE(ref,''),1,60) FROM visits
        WHERE is_admin=0 ORDER BY id DESC LIMIT 30""").fetchall()
    rows_s = c.execute("""SELECT ts,ip,tipo,paterno,materno,nombres,fecha,total,status,substr(COALESCE(result,''),1,80)
        FROM searches WHERE is_admin=0 ORDER BY rowid DESC LIMIT 50""").fetchall()
    c.close()
    def esc(s): return str(s or "").replace("&","&amp;").replace("<","&lt;")
    hv = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{esc(d)}</td><td>{esc(cc)}</td></tr>" for a,b,cc,d in rows_v)
    hs = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{esc(cc)}</td><td>{esc(d)} {esc(e)} {esc(f)}</td><td>{esc(g)}</td><td>{esc(h)}</td><td>{esc(i)} {esc(j)}</td></tr>" for a,b,cc,d,e,f,g,h,i,j in rows_s)
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ActaSegura stats (sem você, sem bots)</title>
<body style="font-family:system-ui;padding:20px;max-width:1000px;margin:auto">
<h2>📊 ActaSegura — visitas e buscas (excluindo você e bots)</h2>
<p><b>Visitas reais:</b> {tv} (com bots: {tv_all}) · <b>IPs únicos reais:</b> {uniq} · <b>Buscas reais:</b> {ts} · <b>Ubicadas:</b> {ubic}</p>
<h3>Últimas visitas (30)</h3><table border="1" cellpadding="6" cellspacing="0"><tr><th>hora UTC</th><th>ip</th><th>ref</th><th>ua</th></tr>{hv}</table>
<h3>Buscas de usuários (50) — só você vê</h3><table border="1" cellpadding="6" cellspacing="0">
<tr><th>hora</th><th>ip</th><th>tipo</th><th>nomes</th><th>fecha pedida</th><th>total</th><th>resultado</th></tr>{hs}</table>
<p style="color:#666;font-size:13px">Aviso Ley 29733: estes nomes são dados pessoais — use só para prestar o serviço e apague se o titular pedir.</p>
</body>""")

@app.get("/stats.json")
def stats_json(request: Request):
    if not is_admin_req(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    c = db()
    out = {
        "visitas_reais": c.execute("SELECT COUNT(*) FROM visits WHERE is_admin=0 AND is_bot=0").fetchone()[0],
        "ips_unicos": c.execute("SELECT COUNT(DISTINCT ip) FROM visits WHERE is_admin=0 AND is_bot=0").fetchone()[0],
        "buscas_reais": c.execute("SELECT COUNT(*) FROM searches WHERE is_admin=0 AND is_bot=0").fetchone()[0],
        "ubicadas": c.execute("SELECT COUNT(*) FROM searches WHERE is_admin=0 AND is_bot=0 AND result LIKE 'UBICADA%'").fetchone()[0],
    }
    c.close()
    return out
