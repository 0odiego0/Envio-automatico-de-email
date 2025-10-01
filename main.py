import os
import json
import logging
import unicodedata
import re
from typing import Optional, Dict, Any

from fastapi import FastAPI, Form, Request, HTTPException
from dotenv import load_dotenv
import httpx

load_dotenv()


# Váriaveis de ambiente - aqui vc precisa já ter configurado suas váriaveis de ambiente e sua conta no Resend para envio dos emails.

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "no-reply@youve.co")
RECIPIENT_FALLBACK = os.getenv("RECIPIENT_FALLBACK", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s:%(lineno)d: %(message)s",
)
logger = logging.getLogger("webhook")

app = FastAPI()


# Utilidades

def _norm_val(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    return s or None

def _slug_key(s: str) -> str:
    """
    Normaliza chaves de campos: tira acento, baixa caixa, remove pontuação e
    troca espaços por underscore. Ex.: 'Qual_o_seu_CRM?' -> 'qual_o_seu_crm'
         'E-mail' -> 'e_mail' ; 'Sem rótulo' -> 'sem_rotulo'
    """
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("M"))
    s = s.lower()
    s = re.sub(r"[^\w\s]", "_", s)     # pontuação -> _
    s = re.sub(r"\s+", "_", s)         # espaços -> _
    s = re.sub(r"_+", "_", s).strip("_")
    return s

def _pick(data: Dict[str, Any], keys: list[str]) -> Optional[str]:
    for k in keys:
        if k in data and data[k] not in (None, "", []):
            return str(data[k])
    return None

def _flatten_elementor_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Se algum dia vier o formato do Elementor: {"fields": [{"id": "...", "value": "..."}]}
    transforma em dict normal.
    """
    out: Dict[str, Any] = {}
    fields = payload.get("fields")
    if isinstance(fields, list):
        for f in fields:
            key = f.get("id") or f.get("name") or f.get("label")
            if not key:
                continue
            out[_slug_key(str(key))] = f.get("value")
    return out

def _normalize_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza TODAS as chaves do payload com _slug_key."""
    norm: Dict[str, Any] = {}
    for k, v in raw.items():
        try:
            norm[_slug_key(str(k))] = v
        except Exception:
            # em último caso, mantém a chave original
            norm[str(k)] = v
    return norm

# Envio via Resend

async def send_email_via_resend(to_email: str, subject: str, html: str) -> Dict[str, Any]:
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY não configurada")

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": SENDER_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post("https://api.resend.com/emails", headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

# Healthcheck

@app.get("/health")
async def health():
    return {"ok": True}

# Webhook

@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    Aceita:
      - application/x-www-form-urlencoded  (o que seu WordPress enviou)
      - multipart/form-data
      - application/json (compat futuro)
    E normaliza chaves para lidar com labels como "E-mail", "Qual_o_seu_CRM?" etc.
    """

    # 1) Secret por query ou body
    query_secret = request.query_params.get("secret")
    provided_secret = query_secret

    # 2) Captura Content-Type e corpo bruto (para logs de diagnóstico)
    content_type = (request.headers.get("content-type") or "").lower()
    raw_body_bytes = await request.body()
    raw_body_text = raw_body_bytes.decode("utf-8", errors="ignore")

    data_raw: Dict[str, Any] = {}
    try:
        if "application/json" in content_type:
            # JSON puro
            data_raw = json.loads(raw_body_text or "{}")
            provided_secret = data_raw.get("secret") or provided_secret

            # Elementor "fields" -> achata
            fields_flat = _flatten_elementor_fields(data_raw)
            for k, v in fields_flat.items():
                data_raw.setdefault(k, v)

        else:
            # form-urlencoded OU multipart/form-data
            form = await request.form()
            data_raw = {k: v for k, v in form.items()}
            provided_secret = data_raw.get("secret") or provided_secret

    except Exception:
        # Se der erro de parse, segue vazio (vamos acusar após validações)
        data_raw = {}

    # 3) Normaliza chaves para facilitar matching
    data = _normalize_payload(data_raw)

    # 4) Valida secret se configurado
    if WEBHOOK_SECRET:
        if not provided_secret or provided_secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid secret")

    # 5) Mapeia aliases -> campos internos
    #    (inclui as variantes vistas no webhook.site)
    nome = _pick(data, ["nome", "name", "full_name", "fullname", "first_name", "nome_completo", "nome"])
    if not nome:
        nome = _pick(data, ["mtq_zoom_nome", "formulario_nome", "mtq_nome"])  # exemplos extras

    telefone = _pick(data, ["telefone", "phone", "tel", "whatsapp", "celular"])
    email = _pick(data, ["email", "e_mail", "mail", "your_email", "contato_email"])
    crm = _pick(data, ["crm", "qual_o_seu_crm", "registro_crm", "crm_medico"])
    estado = _pick(data, ["estado", "uf", "state"])
    mensagem = _pick(data, ["mensagem", "message", "observacoes", "comentarios", "notes"])

    # 6) Logs úteis
    logger.info("CT=%s", content_type)
    logger.info("RAW=%s", raw_body_text[:2000])
    logger.info(
        "NORMALIZED: %s",
        json.dumps(
            {
                "nome": nome,
                "telefone": telefone,
                "email": email,
                "crm": crm,
                "estado": estado,
                "mensagem": mensagem,
            },
            ensure_ascii=False,
        ),
    )

    # 7) Decide destinatário
    to_email = _norm_val(email) or _norm_val(RECIPIENT_FALLBACK)
    if not to_email:
        raise HTTPException(
            status_code=400,
            detail="Nenhum e-mail de destino encontrado (campo 'email' ausente e RECIPIENT_FALLBACK não configurado).",
        )

    # 8) Monta conteúdo do e-mail
    subject = "Recebemos seu contato"
    mensagem = """
    Aqui tu monta a mensagem que quiser
    """

    # 9) Envia
    try:
        resp = await send_email_via_resend(to_email, subject, html)
        return {"status": "ok", "provider_response": resp}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=e.response.text)
    except Exception as e:
        logger.exception("Erro ao enviar e-mail")
        raise HTTPException(status_code=500, detail=str(e))
