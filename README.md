# Passagem de Turno – Logística (V3)

## O que mudou
- Formulário dinâmico para CDA 01, CDA 02 e Estoque.
- Absenteísmo calculado automaticamente.
- Visão atual das três operações.
- Resumo semanal e gráficos.
- Histórico com exportação CSV.
- Fotos reais da fábrica e dos caminhões em `assets/`.

## Publicar no Streamlit
Suba `app.py`, `requirements.txt` e a pasta `assets` no mesmo repositório. O arquivo principal continua sendo `app.py`.

## Banco
Esta V3 ainda usa SQLite como modo de teste. No Streamlit Community Cloud o armazenamento local não deve ser tratado como histórico definitivo. Antes do uso com dados reais, conecte um banco persistente aprovado pela empresa.
