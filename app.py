import os
import json
import random
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.utils import secure_filename
import pdf_importer

app = Flask(__name__)
DATA_FILE = "data.json"


def init_db():
    if not os.path.exists(DATA_FILE):
        reset_db_data()


def reset_db_data():
    initial_data = {
        "config": {
            "concurso_inicial": None,
            "ativo": False,
            "concurso_finalizado": False
        },
        "participantes": [],
        "cartelas": [],
        "concursos": {}
    }
    save_db(initial_data)


def load_db():
    init_db()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def fetch_megasena_concurso(concurso_num=None):
    url = "https://servicebus2.caixa.gov.br/portaldeloterias/api/megasena/"
    if concurso_num:
        url += str(concurso_num)

    # Headers completos para emular um navegador real e evitar bloqueios de API (403/500)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://loterias.caixa.gov.br/",
        "Origin": "https://loterias.caixa.gov.br"
    }

    try:
        session = requests.Session()
        # A API da Caixa exige aceitar redirecionamentos e ignorar verificações rígidas de SSL se o certificado intermediário falhar
        response = session.get(url, headers=headers, timeout=12, verify=False)

        if response.status_code == 200:
            data = response.json()
            num_concurso = str(data.get("numero"))
            lista_dezenas_raw = data.get("listaDezenas", [])

            if num_concurso and lista_dezenas_raw:
                lista_dezenas = [int(d) for d in lista_dezenas_raw]
                return num_concurso, lista_dezenas
        else:
            print(
                f"⚠️ Erro ao consultar API Caixa (Status Code: {response.status_code})")

    except Exception as e:
        print(f"❌ Exceção ao buscar API da Caixa: {e}")

    # --- FALLBACK: API Alternativa pública (Guilherme Garria / Loterias API) ---
    # Caso a Caixa esteja fora do ar ou bloqueando conexões IP
    try:
        url_fallback = f"https://loteriascaixa-api.herokuapp.com/api/megasena/{concurso_num if concurso_num else 'latest'}"
        res_fb = requests.get(url_fallback, timeout=8)
        if res_fb.status_code == 200:
            data_fb = res_fb.json()
            num_concurso = str(data_fb.get("concurso"))
            lista_dezenas = [int(d) for d in data_fb.get("dezenas", [])]
            if num_concurso and len(lista_dezenas) == 6:
                print(
                    f"✅ Resultado obtido via servidor secundário de fallback (Concurso {num_concurso}).")
                return num_concurso, lista_dezenas
    except Exception as fb_err:
        print(f"❌ Erro no Fallback: {fb_err}")

    return None, None


def processar_novo_concurso(num_concurso, dezenas_sorteadas):
    db = load_db()
    if not db["config"]["ativo"] or db["config"]["concurso_finalizado"]:
        return False, "O bingo não está ativo ou já foi finalizado."

    num_concurso_str = str(num_concurso)
    concurso_inicial = int(db["config"]["concurso_inicial"])

    if int(num_concurso_str) < concurso_inicial:
        return False, f"O concurso {num_concurso_str} é anterior ao concurso inicial ({concurso_inicial})."

    db["concursos"][num_concurso_str] = {
        "dezenas": sorted(dezenas_sorteadas),
        "data_registro": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    relatorio = calcular_resultados(db)
    tem_ganhador_principal = any(
        c["acertos_totais"] == 10 for c in relatorio["cartelas"])

    if tem_ganhador_principal:
        db["config"]["concurso_finalizado"] = True

    save_db(db)
    return True, "Concurso processado com sucesso!"


def calcular_resultados(db):
    concursos_ordenados = sorted([int(k) for k in db["concursos"].keys()])
    cartelas = db["cartelas"]

    premios = {
        "principal": [],
        "favorito": [],
        "favorito_surpresinha": [],
        "quadra": [],
        "quina": [],
        "sena": [],
        "menos_pontos": []
    }

    concurso_inicial = db["config"].get("concurso_inicial")
    primeiro_concurso_num = str(concurso_inicial) if concurso_inicial else (
        str(concursos_ordenados[0]) if concursos_ordenados else None)

    segundo_concurso_num = None
    if primeiro_concurso_num and concursos_ordenados:
        try:
            idx = concursos_ordenados.index(int(primeiro_concurso_num))
            if idx + 1 < len(concursos_ordenados):
                segundo_concurso_num = str(concursos_ordenados[idx + 1])
        except ValueError:
            pass

    dezenas_ja_sorteadas_global = set()

    for c_num in concursos_ordenados:
        c_str = str(c_num)
        dezenas_do_concurso = set(db["concursos"][c_str]["dezenas"])
        dezenas_ineditas_do_concurso = dezenas_do_concurso - dezenas_ja_sorteadas_global

        for c in cartelas:
            dezenas_cartela = set(c["dezenas"])

            acertos_ineditos = len(dezenas_cartela.intersection(
                dezenas_ineditas_do_concurso))
            if acertos_ineditos == 4:
                premios["quadra"].append(
                    {"cartela_id": c["id"], "participante": c["participante"], "concurso": c_str})
            elif acertos_ineditos == 5:
                premios["quina"].append(
                    {"cartela_id": c["id"], "participante": c["participante"], "concurso": c_str})
            elif acertos_ineditos == 6:
                premios["sena"].append(
                    {"cartela_id": c["id"], "participante": c["participante"], "concurso": c_str})

            fav = c["favorita"]
            if c_str == primeiro_concurso_num and fav in dezenas_do_concurso:
                if c["tipo"] == "Surpresinha":
                    premios["favorito_surpresinha"].append(
                        {"cartela_id": c["id"], "participante": c["participante"], "concurso": c_str})
                else:
                    premios["favorito"].append(
                        {"cartela_id": c["id"], "participante": c["participante"], "concurso": c_str})
            elif c_str == segundo_concurso_num and fav in dezenas_do_concurso and c["tipo"] == "Surpresinha":
                premios["favorito_surpresinha"].append(
                    {"cartela_id": c["id"], "participante": c["participante"], "concurso": c_str})

        dezenas_ja_sorteadas_global.update(dezenas_do_concurso)

    relatorio_cartelas = []
    for c in cartelas:
        dezenas_cartela = set(c["dezenas"])
        acertos = dezenas_cartela.intersection(dezenas_ja_sorteadas_global)
        faltantes = dezenas_cartela - dezenas_ja_sorteadas_global
        qtd_acertos = len(acertos)

        relatorio_cartelas.append({
            "id": c["id"],
            "participante": c["participante"],
            "tipo": c["tipo"],
            "dezenas": c["dezenas"],
            "favorita": c["favorita"],
            "acertos_totais": qtd_acertos,
            "dezenas_marcadas": sorted(list(acertos)),
            "dezenas_faltantes": sorted(list(faltantes))
        })

        if qtd_acertos == 10:
            premios["principal"].append(
                {"cartela_id": c["id"], "participante": c["participante"]})

    if concursos_ordenados and relatorio_cartelas:
        menor_pontuacao = min(c["acertos_totais"] for c in relatorio_cartelas)
        premios["menos_pontos"] = [
            {"cartela_id": c["id"], "participante": c["participante"],
                "acertos": c["acertos_totais"]}
            for c in relatorio_cartelas if c["acertos_totais"] == menor_pontuacao
        ]

    relatorio_por_acertos = sorted(
        relatorio_cartelas, key=lambda x: (-x["acertos_totais"], x["participante"]))

    return {
        "cartelas": relatorio_por_acertos,
        "premios": premios
    }

# --- ROTAS DA API ---


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status", methods=["GET"])
def get_status():
    db = load_db()
    res = calcular_resultados(db)
    return jsonify({
        "config": db["config"],
        "concursos": db["concursos"],
        "relatorio": res
    })


@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.json
    db = load_db()
    db["config"]["concurso_inicial"] = int(data["concurso_inicial"])
    db["config"]["ativo"] = True
    db["config"]["concurso_finalizado"] = False
    save_db(db)
    return jsonify({"success": True, "message": "Bingo iniciado com sucesso!"})


@app.route("/api/reset", methods=["POST"])
def reset_bingo():
    reset_db_data()
    return jsonify({"success": True, "message": "Bingo reiniciado com sucesso! Todos os dados foram limpos."})


@app.route("/api/cartelas/gerar-lote", methods=["POST"])
def gerar_lote():
    db = load_db()
    if db["config"]["ativo"]:
        return jsonify({"success": False, "message": "Não é possível gerar cartelas após o início do bingo."}), 400

    qtd = request.json.get("quantidade", 10)
    nomes_teste = ["Carlos Silva", "Ana Oliveira", "Bruno Santos", "Mariana Costa",
                   "Fernando Rocha", "Patricia Lima", "Lucas Mendes", "Beatriz Souza"]

    for i in range(qtd):
        dezenas = sorted(random.sample(range(1, 61), 10))
        favorita = random.choice(dezenas)
        # Aumenta a chance de gerar tipos diferentes
        tipo = random.choice(["Padrao", "Surpresinha", "Padrao"])
        nome = f"{random.choice(nomes_teste)} (Aposta #{len(db['cartelas']) + 1})"

        db["cartelas"].append({
            "id": len(db["cartelas"]) + 1,
            "participante": nome,
            "tipo": tipo,
            "dezenas": dezenas,
            "favorita": favorita
        })

    save_db(db)
    return jsonify({"success": True, "message": f"{qtd} cartelas aleatórias geradas com sucesso!"})


@app.route("/api/cartela", methods=["POST"])
def add_cartela():
    data = request.json
    db = load_db()

    if db["config"]["ativo"]:
        return jsonify({"success": False, "message": "Não é possível cadastrar cartelas após o início do bingo."}), 400

    dezenas = data.get("dezenas", [])
    if len(dezenas) != 10 or len(set(dezenas)) != 10 or any(d < 1 or d > 60 for d in dezenas):
        return jsonify({"success": False, "message": "Informe exatamente 10 dezenas distintas entre 1 e 60."}), 400

    favorita = int(data.get("favorita"))
    if favorita not in dezenas:
        return jsonify({"success": False, "message": "A dezena favorita deve estar entre as 10 dezenas da cartela."}), 400

    nova_cartela = {
        "id": len(db["cartelas"]) + 1,
        "participante": data.get("participante", "").strip(),
        "tipo": data.get("tipo", "Padrao"),
        "dezenas": sorted(dezenas),
        "favorita": favorita
    }

    db["cartelas"].append(nova_cartela)
    save_db(db)
    return jsonify({"success": True, "message": "Cartela cadastrada com sucesso!"})


@app.route("/api/cartelas/upload-pdf", methods=["POST"])
def upload_pdf():
    db = load_db()
    if db["config"]["ativo"]:
        return jsonify({"success": False, "message": "Não é possível importar cartelas após o início do bingo."}), 400

    if "file" not in request.files:
        return jsonify({"success": False, "message": "Nenhum arquivo enviado."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "Nenhum arquivo selecionado."}), 400

    if file and file.filename.endswith(".pdf"):
        filepath = os.path.join(".", secure_filename(file.filename))
        file.save(filepath)

        qtd = pdf_importer.importar_para_banco(filepath, DATA_FILE)
        if os.path.exists(filepath):
            os.remove(filepath)

        return jsonify({"success": True, "message": f"{qtd} cartelas importadas com sucesso a partir do PDF!"})

    return jsonify({"success": False, "message": "Formato de arquivo inválido. Envie um arquivo PDF."}), 400


@app.route("/api/concurso/fetch", methods=["POST"])
def api_fetch_concurso():
    data = request.get_json(silent=True) or {}
    concurso_num = data.get("concurso")
    num_c, dezenas = fetch_megasena_concurso(concurso_num)

    if not num_c:
        return jsonify({"success": False, "message": "Erro ao consultar API da Caixa ou concurso não encontrado."}), 400

    ok, msg = processar_novo_concurso(num_c, dezenas)
    return jsonify({"success": ok, "message": msg, "concurso": num_c, "dezenas": dezenas})


@app.route("/participante")
def participante_view():
    return render_template("participante.html")

@app.route("/api/concurso/manual", methods=["POST"])
def api_manual_concurso():
    data = request.json
    num_c = str(data.get("concurso"))
    dezenas = data.get("dezenas", [])

    if len(dezenas) != 6 or len(set(dezenas)) != 6 or any(d < 1 or d > 60 for d in dezenas):
        return jsonify({"success": False, "message": "Forneça 6 dezenas válidas (1 a 60)."}), 400

    ok, msg = processar_novo_concurso(num_c, dezenas)
    return jsonify({"success": ok, "message": msg})


def job_auto_check():
    print("[AGENDADOR] Verificando resultado da Mega Sena...")
    db = load_db()
    if db["config"]["ativo"] and not db["config"]["concurso_finalizado"]:
        num_c, dezenas = fetch_megasena_concurso()
        if num_c:
            processar_novo_concurso(num_c, dezenas)


scheduler = BackgroundScheduler()
scheduler.add_job(job_auto_check, 'cron',
                  day_of_week='tue,thu,sat', hour=22, minute=0)
scheduler.start()

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
