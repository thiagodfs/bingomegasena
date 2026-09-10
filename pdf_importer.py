import json
import re
import pdfplumber
import pandas as pd
from pathlib import Path


def extrair_dados_pdf(caminho_pdf):
    dfr, relat = pdf_para_dataframe(caminho_pdf)
    registros = []

    for _, row in dfr.iterrows():
        id_original = int(row["NUM"])
        nome_participante = str(row["NOME"])
        favorita = int(row["FAVORITO"])
        eh_surpresinha = bool(row["TEIMOSINHA"])
        dezenas = row["DEZENAS"]
        registros.append({
            "ID_PDF": id_original,
            "Participante": nome_participante,
            "Tipo": "Surpresinha" if eh_surpresinha else "Padrao",
            "Favorita": favorita,
            "Dezenas": ", ".join(map(str, dezenas)),
            "Dezenas_Lista": dezenas
        })

    return registros


def pdf_para_dataframe(
    arquivo_pdf,
    validar=True,
    criar_dezenas=True,
    converter_numericos=True
):
    """
    Extrai a tabela do PDF tabela_setembro2026.pdf
    e retorna um DataFrame estruturado.

    Estrutura esperada do PDF:
        N° | NOME | 1° Sorteio | 2° Sorteio |
        PALPITES (10 dezenas) | ACERTOS

    Retorna:
        df      -> DataFrame com os dados extraídos
        relatorio -> dicionário com informações da extração
    """

    arquivo_pdf = Path(arquivo_pdf)

    if not arquivo_pdf.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {arquivo_pdf}"
        )

    # ---------------------------------------------------------
    # COLUNAS FINAIS
    # ---------------------------------------------------------

    colunas = [
        "NUM",
        "NOME",
        "SORTE1",
        "SORTE2",
        "DZ1",
        "DZ2",
        "DZ3",
        "DZ4",
        "DZ5",
        "DZ6",
        "DZ7",
        "DZ8",
        "DZ9",
        "DZ10",
        "ACERTOS"
    ]

    colunas_dezenas = [
        "DZ1", "DZ2", "DZ3", "DZ4", "DZ5",
        "DZ6", "DZ7", "DZ8", "DZ9", "DZ10"
    ]

    # ---------------------------------------------------------
    # VARIÁVEIS DE CONTROLE
    # ---------------------------------------------------------

    todos_dados = []

    paginas_processadas = 0
    tabelas_encontradas = 0
    linhas_descartadas = []

    # ---------------------------------------------------------
    # ABRIR PDF
    # ---------------------------------------------------------

    with pdfplumber.open(arquivo_pdf) as pdf:

        total_paginas = len(pdf.pages)

        for numero_pagina, pagina in enumerate(pdf.pages, start=1):

            try:
                tabelas = pagina.extract_tables()

            except Exception as erro:
                raise RuntimeError(
                    f"Erro ao extrair tabela da página "
                    f"{numero_pagina}: {erro}"
                )

            if not tabelas:
                continue

            paginas_processadas += 1

            # Neste PDF temos uma tabela principal por página.
            tabela = tabelas[0]

            if not tabela:
                continue

            tabelas_encontradas += 1

            # -------------------------------------------------
            # REMOVER CABEÇALHO DA PÁGINA
            # -------------------------------------------------

            for linha in tabela:

                if linha is None:
                    continue

                # Remove espaços e transforma None em ""
                linha = [
                    str(valor).strip() if valor is not None else ""
                    for valor in linha
                ]

                # ---------------------------------------------
                # IGNORAR LINHAS VAZIAS
                # ---------------------------------------------

                if not any(linha):
                    continue

                # ---------------------------------------------
                # A tabela correta precisa possuir 15 campos
                # ---------------------------------------------

                if len(linha) != 15:

                    linhas_descartadas.append({
                        "pagina": numero_pagina,
                        "motivo": "Quantidade de colunas diferente de 15",
                        "linha": linha
                    })

                    continue

                # ---------------------------------------------
                # IDENTIFICAR CABEÇALHO
                # ---------------------------------------------

                primeira_coluna = linha[0].upper()

                if (
                    primeira_coluna in ("N°", "Nº", "N", "")
                    or "N°" in primeira_coluna
                ):
                    continue

                # Algumas versões podem repetir o cabeçalho
                if "SORTEIO" in " ".join(linha).upper():
                    continue

                # ---------------------------------------------
                # VALIDAR NÚMERO DO REGISTRO
                # ---------------------------------------------

                try:
                    int(linha[0])
                except ValueError:

                    linhas_descartadas.append({
                        "pagina": numero_pagina,
                        "motivo": "NUM inválido",
                        "linha": linha
                    })

                    continue

                # ---------------------------------------------
                # ADICIONAR LINHA
                # ---------------------------------------------

                todos_dados.append(linha)

    # ---------------------------------------------------------
    # CRIAR DATAFRAME
    # ---------------------------------------------------------

    df = pd.DataFrame(
        todos_dados,
        columns=colunas
    )

    if df.empty:
        raise ValueError(
            "Nenhum dado foi extraído do PDF."
        )

    # ---------------------------------------------------------
    # LIMPEZA DOS CAMPOS TEXTO
    # ---------------------------------------------------------

    df["NOME"] = (
        df["NOME"]
        .astype(str)
        .str.strip()
    )

    # ---------------------------------------------------------
    # CONVERTER CAMPOS NUMÉRICOS
    # ---------------------------------------------------------

    if converter_numericos:

        campos_numericos = [
            "NUM",
            "SORTE1",
            "SORTE2",
            "DZ1",
            "DZ2",
            "DZ3",
            "DZ4",
            "DZ5",
            "DZ6",
            "DZ7",
            "DZ8",
            "DZ9",
            "DZ10",
            "ACERTOS"
        ]

        for coluna in campos_numericos:

            df[coluna] = pd.to_numeric(
                df[coluna],
                errors="coerce"
            ).astype("Int64")

    # ---------------------------------------------------------
    # CRIAR COLUNA DEZENAS
    # ---------------------------------------------------------

    if criar_dezenas:

        def montar_dezenas(linha):

            dezenas = []

            for coluna in colunas_dezenas:

                valor = linha[coluna]

                if pd.notna(valor):
                    dezenas.append(int(valor))

            return dezenas

        df["DEZENAS"] = df.apply(
            montar_dezenas,
            axis=1
        )

    # ---------------------------------------------------------
    # VALIDAÇÕES
    # ---------------------------------------------------------

    problemas = []

    if validar:

        # ---------------------------------------------
        # NUM DUPLICADO
        # ---------------------------------------------

        duplicados_num = df[
            df["NUM"].duplicated(keep=False)
        ]

        if not duplicados_num.empty:

            problemas.append({
                "tipo": "NUM duplicado",
                "quantidade": len(duplicados_num),
                "registros": duplicados_num[
                    ["NUM", "NOME"]
                ].to_dict("records")
            })

        # ---------------------------------------------
        # NOMES VAZIOS
        # ---------------------------------------------

        nomes_vazios = df[
            df["NOME"].isna()
            | (df["NOME"].astype(str).str.strip() == "")
        ]

        if not nomes_vazios.empty:

            problemas.append({
                "tipo": "Nome vazio",
                "quantidade": len(nomes_vazios),
                "registros": nomes_vazios[
                    ["NUM", "NOME"]
                ].to_dict("records")
            })

        # ---------------------------------------------
        # VALIDAR DEZENAS
        # ---------------------------------------------

        if criar_dezenas:

            quantidade_incorreta = df[
                df["DEZENAS"].apply(
                    lambda x: len(x) != 10
                )
            ]

            if not quantidade_incorreta.empty:

                problemas.append({
                    "tipo": "Quantidade de dezenas diferente de 10",
                    "quantidade": len(quantidade_incorreta),
                    "registros": quantidade_incorreta[
                        ["NUM", "NOME", "DEZENAS"]
                    ].to_dict("records")
                })

            # -----------------------------------------
            # DEZENAS FORA DE 1 A 60
            # -----------------------------------------

            fora_do_intervalo = df[
                df["DEZENAS"].apply(
                    lambda dezenas:
                    any(
                        dezena < 1 or dezena > 60
                        for dezena in dezenas
                    )
                )
            ]

            if not fora_do_intervalo.empty:

                problemas.append({
                    "tipo": "Dezena fora do intervalo 1-60",
                    "quantidade": len(fora_do_intervalo),
                    "registros": fora_do_intervalo[
                        ["NUM", "NOME", "DEZENAS"]
                    ].to_dict("records")
                })

            # -----------------------------------------
            # DEZENAS REPETIDAS
            # -----------------------------------------

            dezenas_repetidas = df[
                df["DEZENAS"].apply(
                    lambda dezenas:
                    len(dezenas) != len(set(dezenas))
                )
            ]

            if not dezenas_repetidas.empty:

                problemas.append({
                    "tipo": "Dezenas repetidas",
                    "quantidade": len(dezenas_repetidas),
                    "registros": dezenas_repetidas[
                        ["NUM", "NOME", "DEZENAS"]
                    ].to_dict("records")
                })

    # ---------------------------------------------------------
    # TRATANDO O DATAFRAME PARA RETORNAR
    # ---------------------------------------------------------

    # df = df.drop(columns=df.columns[0])
    df = df.drop(columns=colunas_dezenas)
    df = df.reset_index(drop=True)
    df = df.rename(columns={"SORTE2": "TEIMOSINHA", "SORTE1": "FAVORITO"})

    df["TEIMOSINHA"] = (
        df["TEIMOSINHA"].notna()
        & (
            df["TEIMOSINHA"].astype(str).str.strip() != ""
        )
        & (
            pd.to_numeric(
                df["TEIMOSINHA"],
                errors="coerce"
            )
            ==
            pd.to_numeric(
                df["FAVORITO"],
                errors="coerce"
            )
        )
    )

    df.to_pickle(f"{arquivo_pdf.stem}.pkl")
    df.to_excel(f"{arquivo_pdf.stem}.xlsx", index=False)
    # df = pd.read_pickle(f"{arquivo_pdf.stem}.pkl")

    # ---------------------------------------------------------
    # RELATÓRIO
    # ---------------------------------------------------------

    relatorio = {

        "arquivo": arquivo_pdf.name,

        "paginas_pdf": total_paginas,

        "paginas_processadas": paginas_processadas,

        "tabelas_encontradas": tabelas_encontradas,

        "registros_extraidos": len(df),

        "linhas_descartadas": len(linhas_descartadas),

        "problemas_validacao": len(problemas),

        "problemas": problemas,

        "linhas_descartadas_detalhes": linhas_descartadas
    }

    return df, relatorio


def converter_pdf_para_excel(caminho_pdf, caminho_excel="cartelas_importadas.xlsx"):
    dados = extrair_dados_pdf(caminho_pdf)
    df = pd.DataFrame(dados)

    # Remove a coluna de lista técnica para salvar limpo no Excel
    if "Dezenas_Lista" in df.columns:
        df_excel = df.drop(columns=["Dezenas_Lista"])
    else:
        df_excel = df

    df_excel.to_excel(caminho_excel, index=False)
    print(
        f"📊 Planilha criada com sucesso: {caminho_excel} ({len(df_excel)} cartelas encontradas).")
    return df


def importar_para_banco(caminho_pdf, arquivo_json="data.json"):
    # Gera/Atualiza o Excel no processo
    df = converter_pdf_para_excel(caminho_pdf)

    cartelas = []
    for idx, row in df.iterrows():
        cartelas.append({
            "id": int(row["ID_PDF"]),
            "participante": str(row["Participante"]),
            "tipo": str(row["Tipo"]),
            "dezenas": row["Dezenas_Lista"],
            "favorita": int(row["Favorita"])
        })

    try:
        with open(arquivo_json, "r", encoding="utf-8") as f:
            db = json.load(f)
    except FileNotFoundError:
        db = {
            "config": {"concurso_inicial": None, "ativo": False, "concurso_finalizado": False},
            "participantes": [],
            "cartelas": [],
            "concursos": {}
        }

    db["cartelas"] = cartelas

    with open(arquivo_json, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

    return len(cartelas)


if __name__ == "__main__":
    # Teste standalone via terminal
    importar_para_banco("tabelas/tabela_setembro2026.pdf")
