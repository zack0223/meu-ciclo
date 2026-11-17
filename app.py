import os
import hmac
import sqlite3
import datetime as dt
from contextlib import contextmanager

import gradio as gr
import uvicorn
from fastapi import FastAPI, Request, HTTPException

# ============================================================
# CONFIGURACAO
# No Hugging Face Spaces, configure em Settings > Variables
# and secrets:
#   HOTMART_HOTTOK = token secreto do webhook da Hotmart
#   CHECKOUT_URL = link real do checkout
#   DATABASE_PATH = /data/assinantes.db (se tiver Volume persistente)
# ============================================================

HOTTOK = os.environ.get("HOTMART_HOTTOK", "").strip()
CHECKOUT_URL = os.environ.get(
    "CHECKOUT_URL", "https://pay.hotmart.com/SEU_LINK"
).strip()
DATABASE_PATH = os.environ.get("DATABASE_PATH", "assinantes.db")
NOME_APP = "Meu Ciclo"

ATIVAR = {"PURCHASE_APPROVED", "PURCHASE_COMPLETE"}
DESATIVAR = {
    "SUBSCRIPTION_CANCELLATION",
    "PURCHASE_CANCELED",
    "PURCHASE_REFUNDED",
    "PURCHASE_CHARGEBACK",
    "PURCHASE_EXPIRED",
}

FASES = {
    "Menstrual": {
        "emoji": "🩸", "cor": "#C2185B",
        "resumo": "Fase de menstruação.",
        "alimentacao": "Inclui fontes de ferro, como feijão, lentilhas e folhas verdes. Combina com alimentos ricos em vitamina C e bebe água.",
        "exercicio": "Caminhada, alongamentos ou yoga suave, conforme te sentires.",
        "energia": "Pode estar mais baixa. Respeita o teu ritmo e descansa se precisares.",
    },
    "Folicular": {
        "emoji": "🌱", "cor": "#2E7D32",
        "resumo": "Período após a menstruação.",
        "alimentacao": "Mantém uma alimentação variada com proteínas, vegetais, frutas e cereais integrais.",
        "exercicio": "Podes aumentar gradualmente a intensidade se te sentires bem.",
        "energia": "Algumas pessoas sentem a energia aumentar nesta fase.",
    },
    "Ovulatória": {
        "emoji": "✨", "cor": "#EF6C00",
        "resumo": "Período em que a ovulação poderá ocorrer.",
        "alimentacao": "Prioriza uma alimentação equilibrada, fibras, frutas e hidratação.",
        "exercicio": "Escolhe atividades de acordo com a tua disposição.",
        "energia": "Algumas pessoas sentem maior disposição; isso varia de pessoa para pessoa.",
    },
    "Lútea": {
        "emoji": "🌙", "cor": "#5E35B1",
        "resumo": "Período entre a ovulação estimada e a próxima menstruação.",
        "alimentacao": "Mantém refeições equilibradas. Frutos secos, sementes e vegetais podem fazer parte da alimentação.",
        "exercicio": "Caminhadas, pilates ou exercício moderado, conforme te sentires.",
        "energia": "Podem surgir alterações de humor, cansaço ou sintomas pré-menstruais.",
    },
}

AVISO = (
    "As datas e fases são estimativas baseadas na duração média indicada. "
    "A ovulação pode variar, mesmo em ciclos regulares. Esta aplicação "
    "não diagnostica doenças nem deve ser usada para evitar uma gravidez. "
    "Em caso de dor intensa, hemorragia anormal ou preocupação, procura "
    "aconselhamento de um profissional de saúde."
)

CSS = """
<style>
.gradio-container {
  max-width: 760px !important; margin: 0 auto !important;
  font-family: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif !important;
}
footer { display: none !important; }
.hero {
  background: linear-gradient(135deg, #D81B60 0%, #8E24AA 100%);
  color: #fff; border-radius: 20px; padding: 28px 24px;
  text-align: center; margin-bottom: 8px;
}
.hero h1 { margin: 0; font-size: 30px; font-weight: 800; color: #fff; }
.hero p { margin: 6px 0 0; opacity: .95; font-size: 15px; color: #fff; }
.card {
  background: #fff; border: 1px solid #F1E3EA; border-radius: 16px;
  padding: 20px; box-shadow: 0 4px 16px rgba(0,0,0,.05);
}
.card, .card * { color: #2B2B2B; }
.badge {
  display: inline-block; padding: 6px 14px; border-radius: 999px;
  color: #fff !important; font-weight: 700; font-size: 14px;
}
.big { font-size: 22px; font-weight: 800; margin: 12px 0 4px; }
.sub { color: #6B6B6B !important; font-size: 14px; }
.bar { height: 10px; background: #F3E5EC; border-radius: 999px;
  overflow: hidden; margin: 14px 0 4px; }
.bar > div { height: 100%; border-radius: 999px; }
.grid {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 10px; margin-top: 16px;
}
.tile {
  background: #FFF6FA; border: 1px solid #F8DCE8;
  border-radius: 12px; padding: 12px 8px; text-align: center;
}
.tile .t { font-size: 12px; color: #8A5A6E !important; }
.tile .v { font-size: 15px; font-weight: 700; margin-top: 4px; }
.row { margin-top: 14px; font-size: 14px; line-height: 1.5; }
.aviso {
  margin-top: 16px; font-size: 12px;
  color: #777 !important; text-align: center; line-height: 1.5;
}
.paywall { text-align: center; }
.paywall a.btn {
  display: inline-block; margin-top: 10px; background: #D81B60;
  color: #fff !important; padding: 12px 26px; border-radius: 12px;
  font-weight: 700; text-decoration: none;
}
button.primary, .primary {
  background: linear-gradient(135deg, #D81B60, #8E24AA) !important;
  border: none !important; color: #fff !important;
  font-weight: 700 !important; border-radius: 12px !important;
}
@media (max-width: 560px) { .grid { grid-template-columns: 1fr; } }
</style>
"""

HERO = f"""
<div class="hero">
  <h1>🌸 {NOME_APP}</h1>
  <p>O teu guia de acompanhamento do ciclo menstrual</p>
</div>
"""


# ---------------------- BASE DE DADOS ----------------------

@contextmanager
def ligar_bd():
    pasta = os.path.dirname(os.path.abspath(DATABASE_PATH))
    os.makedirs(pasta, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=20)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def iniciar_bd():
    with ligar_bd() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS assinantes (
                email TEXT PRIMARY KEY,
                estado TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            )
        """)


def normalizar_email(email):
    return (email or "").strip().lower()


def esta_ativo(email):
    email = normalizar_email(email)
    if not email or "@" not in email:
        return False
    with ligar_bd() as conn:
        row = conn.execute(
            "SELECT estado FROM assinantes WHERE email = ?", (email,)
        ).fetchone()
    return bool(row and row[0] == "ativo")


def atualizar_assinante(email, estado):
    email = normalizar_email(email)
    if not email or "@" not in email or estado not in {"ativo", "inativo"}:
        return
    agora = dt.datetime.now(dt.timezone.utc).isoformat()
    with ligar_bd() as conn:
        conn.execute("""
            INSERT INTO assinantes (email, estado, atualizado_em)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                estado = excluded.estado,
                atualizado_em = excluded.atualizado_em
        """, (email, estado, agora))


iniciar_bd()


# ---------------------- WEBHOOK HOTMART ----------------------

api = FastAPI(title=NOME_APP)


def extrair_email(payload):
    data = payload.get("data") or {}
    buyer = data.get("buyer") or {}
    subscriber = data.get("subscriber") or {}
    purchase = data.get("purchase") or {}
    return normalizar_email(
        buyer.get("email")
        or subscriber.get("email")
        or purchase.get("buyer", {}).get("email")
        or ""
    )


@api.post("/hotmart")
async def hotmart(request: Request):
    # Falha em modo fechado: sem segredo configurado, nao aceita webhooks.
    if not HOTTOK:
        raise HTTPException(
            status_code=503,
            detail="Webhook ainda nao configurado no servidor."
        )

    token_recebido = request.headers.get("X-HOTMART-HOTTOK", "")
    if not hmac.compare_digest(token_recebido, HOTTOK):
        raise HTTPException(status_code=403, detail="Token invalido.")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido.")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Formato de evento invalido.")

    evento = str(payload.get("event") or "").upper()
    email = extrair_email(payload)

    if not evento:
        raise HTTPException(status_code=400, detail="Evento em falta.")

    if evento in ATIVAR and email:
        atualizar_assinante(email, "ativo")
    elif evento in DESATIVAR and email:
        atualizar_assinante(email, "inativo")

    # Eventos desconhecidos sao recebidos, mas nao alteram a assinatura.
    return {"ok": True, "event": evento}


# ---------------------- CALCULADORA DO CICLO ----------------------

def ler_data(texto):
    texto = (texto or "").strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def calcular(data_txt, ciclo, menstruacao):
    inicio = ler_data(data_txt)
    if inicio is None:
        return (
            '<div class="card">Indica uma data válida, por exemplo: '
            '<b>05/11/2026</b>.</div>'
        )

    try:
        ciclo = int(ciclo)
        menstruacao = int(menstruacao)
    except (TypeError, ValueError):
        return '<div class="card">Verifica os valores do ciclo.</div>'

    if not 21 <= ciclo <= 40:
        return '<div class="card">A duração do ciclo deve estar entre 21 e 40 dias.</div>'
    if not 2 <= menstruacao <= 8 or menstruacao >= ciclo:
        return '<div class="card">Verifica a duração da menstruação.</div>'

    hoje = dt.date.today()
    if inicio > hoje:
        return '<div class="card">A data não pode estar no futuro.</div>'

    ciclos_passados = (hoje - inicio).days // ciclo
    inicio_atual = inicio + dt.timedelta(days=ciclos_passados * ciclo)
    proxima_menstruacao = inicio_atual + dt.timedelta(days=ciclo)

    # Estimativa convencional: ovulacao cerca de 14 dias antes da proxima menstruacao.
    ovulacao = proxima_menstruacao - dt.timedelta(days=14)
    fertil_inicio = ovulacao - dt.timedelta(days=5)
    fertil_fim = ovulacao + dt.timedelta(days=1)

    dia = (hoje - inicio_atual).days + 1
    dia_ovulacao = (ovulacao - inicio_atual).days + 1

    if dia <= menstruacao:
        fase = "Menstrual"
    elif dia < dia_ovulacao - 5:
        fase = "Folicular"
    elif dia <= dia_ovulacao + 1:
        fase = "Ovulatória"
    else:
        fase = "Lútea"

    info = FASES[fase]
    percentagem = min(100, max(0, round(dia / ciclo * 100)))
    faltam = max(0, (proxima_menstruacao - hoje).days)

    def fmt(data):
        return data.strftime("%d/%m/%Y")

    return f"""
<div class="card">
  <span class="badge" style="background:{info['cor']}">
    {info['emoji']} Fase {fase}
  </span>
  <div class="big">Dia {dia} de {ciclo}</div>
  <div class="sub">{info['resumo']}</div>
  <div class="bar"><div style="width:{percentagem}%; background:{info['cor']}"></div></div>
  <div class="sub">Próxima menstruação estimada em <b>{faltam} dia(s)</b></div>
  <div class="grid">
    <div class="tile"><div class="t">Ovulação estimada</div>
      <div class="v">{fmt(ovulacao)}</div></div>
    <div class="tile"><div class="t">Janela fértil estimada</div>
      <div class="v">{fmt(fertil_inicio)} – {fmt(fertil_fim)}</div></div>
    <div class="tile"><div class="t">Próxima menstruação</div>
      <div class="v">{fmt(proxima_menstruacao)}</div></div>
  </div>
  <div class="row">🥗 <b>Alimentação:</b> {info['alimentacao']}</div>
  <div class="row">🏃‍♀️ <b>Exercício:</b> {info['exercicio']}</div>
  <div class="row">⚡ <b>Energia:</b> {info['energia']}</div>
  <div class="aviso">{AVISO}</div>
</div>
"""


def guia_fases():
    blocos = []
    for nome, info in FASES.items():
        blocos.append(f"""
<div class="card" style="margin-bottom:12px">
  <span class="badge" style="background:{info['cor']}">
    {info['emoji']} {nome}
  </span>
  <div class="sub" style="margin-top:8px">{info['resumo']}</div>
  <div class="row">🥗 <b>Alimentação:</b> {info['alimentacao']}</div>
  <div class="row">🏃‍♀️ <b>Exercício:</b> {info['exercicio']}</div>
  <div class="row">⚡ <b>Energia:</b> {info['energia']}</div>
</div>""")
    return "".join(blocos) + f'<div class="aviso">{AVISO}</div>'


# ---------------------- LOGIN E INTERFACE ----------------------

def entrar(email):
    email = normalizar_email(email)
    if esta_ativo(email):
        return gr.update(visible=False), gr.update(visible=True), ""

    aviso = f"""
<div class="card paywall">
  <div class="big">Assinatura não encontrada</div>
  <div class="sub">
    Não encontrámos uma assinatura ativa para este e-mail.
    Confirma se usaste o mesmo e-mail na compra da Hotmart.
  </div>
  <a class="btn" href="{CHECKOUT_URL}" target="_blank"
     rel="noopener noreferrer">Assinar agora</a>
</div>"""
    return gr.update(visible=True), gr.update(visible=False), aviso


with gr.Blocks(title=NOME_APP, css=CSS) as demo:
    gr.Image(
        value=os.path.join(os.path.dirname(os.path.abspath(__file__)), "capa_meu_ciclo.png"),
        show_label=False,
        interactive=False,
        container=False,
    )
    gr.HTML(HERO)

    with gr.Column(visible=True) as area_login:
        gr.HTML(
            '<div class="card"><div class="big" style="margin-top:0">'
            'Bem-vinda 💗</div><div class="sub">'
            'Entra com o mesmo e-mail utilizado na compra.</div></div>'
        )
        email = gr.Textbox(
            label="E-mail da compra",
            placeholder="o_teu_email@exemplo.com",
            type="email"
        )
        btn_entrar = gr.Button("Entrar", variant="primary")
        aviso_login = gr.HTML("")

    with gr.Column(visible=False) as area_app:
        with gr.Tabs():
            with gr.Tab("📅 Meu ciclo"):
                data = gr.Textbox(
                    label="Primeiro dia da última menstruação",
                    placeholder="Ex.: 05/11/2026"
                )
                ciclo = gr.Slider(
                    21, 40, value=28, step=1,
                    label="Duração habitual do ciclo (dias)"
                )
                menstruacao = gr.Slider(
                    2, 8, value=5, step=1,
                    label="Duração habitual da menstruação (dias)"
                )
                btn_calc = gr.Button("Calcular", variant="primary")
                resultado = gr.HTML("")

            with gr.Tab("💡 Guia das fases"):
                gr.HTML(guia_fases())

        btn_calc.click(
            fn=calcular,
            inputs=[data, ciclo, menstruacao],
            outputs=resultado
        )

    btn_entrar.click(
        fn=entrar,
        inputs=email,
        outputs=[area_login, area_app, aviso_login]
    )


app = gr.mount_gradio_app(api, demo, path="/")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
