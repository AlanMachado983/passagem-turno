import os
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

FUSO_OPERACIONAL = ZoneInfo('America/Sao_Paulo')

def agora_operacional():
    return datetime.now(FUSO_OPERACIONAL)

import pandas as pd
import streamlit as st

# Data operacional = dia de início do turno; os horários podem se sobrepor.
HORARIOS_TURNOS = {
    'T1': ('06:00', '14:20'),
    'T2': ('14:20', '22:53'),
    'T3': ('22:35', '06:18'),
}

def data_ciclo_operacional(data_registro, turno, operacao):
    """Somente Separação CDA 01 desloca T3 para o ciclo seguinte."""
    dia=pd.to_datetime(data_registro).date()
    if operacao=='CDA 01 - Separação' and turno=='T3':
        return dia+timedelta(days=1)
    return dia

def sugerir_data_operacional(turno, instante):
    """Sugere o início mais recente de T2/T3, inclusive no fechamento atrasado.

    Não recalcula registros persistidos. T1 e escalas 2x2 mantêm a data local.
    O líder deve confirmar a data; lançamentos de outros dias são manuais.
    """
    local = instante.astimezone(FUSO_OPERACIONAL)
    dia = local.date()
    if turno in ('T2', 'T3'):
        inicio = datetime.strptime(HORARIOS_TURNOS[turno][0], '%H:%M').time()
        if local.time().replace(tzinfo=None) < inicio:
            dia -= timedelta(days=1)
    return dia

APP_DIR = Path(__file__).resolve().parent
st.set_page_config(page_title='Passagem de Turno | ADIMAX',
                   page_icon=str(APP_DIR / 'static' / 'favicon.png'), layout='wide')


# A personalização experimental de instalação foi suspensa durante a entrada em produção.
# O favicon oficial continua configurado em st.set_page_config.

# Banco persistente PostgreSQL configurado nos Secrets do Streamlit.
# Não inclua senhas neste arquivo ou no GitHub.
import psycopg2

class PgCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None
    def execute(self, sql, params=()):
        sql = sql.replace('?', '%s')
        if sql.lstrip().upper().startswith('INSERT INTO PASSAGENS') and 'RETURNING' not in sql.upper():
            sql += ' RETURNING id'
            self._cursor.execute(sql, params)
            row = self._cursor.fetchone()
            self.lastrowid = row[0] if row else None
        else:
            self._cursor.execute(sql, params)
        return self
    def fetchone(self): return self._cursor.fetchone()
    def fetchall(self): return self._cursor.fetchall()
    @property
    def description(self): return self._cursor.description

class PgConnection:
    def __init__(self):
        s=st.secrets['connections']['postgresql']
        self._conn=psycopg2.connect(host=s['host'],port=int(s['port']),dbname=s['database'],user=s['username'],password=s['password'],sslmode='require',connect_timeout=12)
    def cursor(self): return PgCursor(self._conn.cursor())
    def commit(self): self._conn.commit()
    def rollback(self): self._conn.rollback()
    def close(self): self._conn.close()

def headers_integracao_vira():
    chave=st.secrets.get('VIRA360_INTEGRATION_KEY') or os.environ.get('VIRA360_INTEGRATION_KEY')
    if not chave:
        raise RuntimeError('Configure VIRA360_INTEGRATION_KEY nos Secrets do Streamlit')
    return {'Accept':'application/json','X-Integration-Key':str(chave)}

@st.cache_data(ttl=45, show_spinner=False)
def consultar_transbordos(data_ref, turno_ref):
    import json, urllib.parse, urllib.request, unicodedata
    url = 'https://transbordos-cda02-online.onrender.com/api/integracoes/passagem/viagens?' + urllib.parse.urlencode({'data':str(data_ref),'turno':str(turno_ref)})
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers_integracao_vira()),timeout=15) as resposta:
        registros=json.load(resposta)
    if not isinstance(registros,list):
        raise ValueError('Resposta inválida')
    totais={n:0 for n in ['Ensaque','Úmidos','Biscoito','Expedição','Estoque','Fornecedores','Outros']}
    quantidade=0
    for item in registros:
        if str(item.get('data_operacional'))!=str(data_ref) or str(item.get('turno'))!=str(turno_ref) or item.get('tipo') not in ('Recebimento','Carregamento') or item.get('excluido_em'):
            continue
        nome=unicodedata.normalize('NFKD',str(item.get('setor') or '')).encode('ascii','ignore').decode().lower()
        setor=('Ensaque' if 'ensaque' in nome else 'Úmidos' if 'umido' in nome else 'Biscoito' if 'biscoito' in nome else 'Expedição' if any(x in nome for x in ('expedi','cda01','cda 01')) else 'Estoque' if 'estoque' in nome else 'Fornecedores' if 'fornecedor' in nome else 'Outros')
        totais[setor]+=int(item.get('paletes') or 0)
        quantidade+=1
    return totais,quantidade

@st.cache_data(ttl=45,show_spinner=False)
def consultar_fluxo_transbordos(data_ref, turno_ref):
    """Consulta os dois tipos de movimento do app Transbordos separadamente."""
    import json, urllib.parse, urllib.request
    url='https://transbordos-cda02-online.onrender.com/api/integracoes/passagem/viagens?'+urllib.parse.urlencode({'data':str(data_ref),'turno':str(turno_ref)})
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers_integracao_vira()),timeout=15) as resposta:
        registros=json.load(resposta)
    if not isinstance(registros,list):
        raise ValueError('Resposta de transbordos inválida')
    resultado={'Recebimento':{'viagens':0,'paletes':0},'Carregamento':{'viagens':0,'paletes':0},'detalhes':[]}
    for item in registros:
        tipo=str(item.get('tipo') or '').strip()
        if (str(item.get('data_operacional'))!=str(data_ref)
            or str(item.get('turno'))!=str(turno_ref)
            or tipo not in resultado or item.get('excluido_em')):
            continue
        resultado[tipo]['viagens']+=1
        resultado[tipo]['paletes']+=int(item.get('paletes') or 0)
        cargas=item.get('transbordo_cargas') or []
        resultado['detalhes'].append({
            'Data':str(item.get('data_operacional') or ''),
            'Turno':nome_turno(turno_ref),
            'ID viagem':str(item.get('id') or ''),
            'Movimentação':tipo,
            'Origem':str(item.get('setor') or '') if tipo=='Recebimento' else 'CDA 02',
            'Destino':'CDA 02' if tipo=='Recebimento' else str(item.get('setor') or ''),
            'Paletes':int(item.get('paletes') or 0),
            'Cargas':', '.join(str(c.get('numero_carga')) for c in cargas if c.get('numero_carga')),
            'Operador':str(item.get('operador') or ''),
            'Finalidade':str(item.get('finalidade') or ''),
            'Observação':str(item.get('observacao') or ''),
        })
    return resultado

def conn(): return PgConnection()

@st.cache_resource(show_spinner=False)
def garantir_campos_efetivo():
    """Migração idempotente para registros antigos e novas correções."""
    c=conn()
    try:
        cur=c.cursor()
        cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS ferias INTEGER NOT NULL DEFAULT 0')
        cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS afastamentos INTEGER NOT NULL DEFAULT 0')
        cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS folgas INTEGER NOT NULL DEFAULT 0')
        cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS atestados INTEGER NOT NULL DEFAULT 0')
        cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS reposicoes_recebidas INTEGER NOT NULL DEFAULT 0')
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

try:
    garantir_campos_efetivo()
except Exception:
    st.error('Não foi possível preparar os campos de efetivo no banco. Os registros foram preservados; solicite verificação da permissão de alteração da tabela.')
    st.stop()

LIDERES = {
    "ALISON RIBEIRO DE OLIVEIRA": ("CDA 01", "ANDRE FORTUNATO", "T1"),
    "ANDERSON DE MELO ALMEIDA": ("CDA 01", "ANDRE FORTUNATO", "T3"),
    "LUIZ FELIPE DA SILVA DOMINGUES": ("CDA 01", "ANDRE FORTUNATO", "T2"),
    "BRUNO RICARDO DE OLIVEIRA MELO": ("CDA 01", "MARCIO HENRIQUE SCHAFFER", "T3"),
    "WESLEY VITOR RODRIGUES": ("CDA 01", "MARCIO HENRIQUE SCHAFFER", "T2"),
    "LUCIANO ALVES DA SILVA JUNIOR": ("CDA 02", "FRANCISCO FERREIRA CARNEIRO JUNIOR", "T3"),
    "MARIO GODOY": ("CDA 02", "FRANCISCO FERREIRA CARNEIRO JUNIOR", "T1"),
    "ALAN MACHADO DO NASCIMENTO": ("CDA 02", "FRANCISCO FERREIRA CARNEIRO JUNIOR", "T2"),
    "ANILSON APARECIDO PEDROSO": ("Estoque", "WAGNER LUIZ GALONE SANCHES FILHO", "2X2 2A"),
    "JOHN HERBERT BATISTA DA SILVA": ("Estoque", "WAGNER LUIZ GALONE SANCHES FILHO", "2X2 2B"),
    "FABIANA VIEIRA DA SILVA": ("Estoque", "WAGNER LUIZ GALONE SANCHES FILHO", "2X2 1A"),
    "LUIS FELIPE OLIVEIRA SILVA": ("Estoque", "WAGNER LUIZ GALONE SANCHES FILHO", "2X2 1B"),
}

def nome_turno(turno):
    return {'T1':'1º Turno','T2':'2º Turno','T3':'3º Turno'}.get(str(turno),str(turno))

def em_toneladas(valor):
    """Compatibilidade com pesos antigos em kg; valores abaixo de 10.000 são tratados como t."""
    try:
        v=float(valor or 0)
        return v/1000.0 if abs(v)>=10000 else v
    except (TypeError, ValueError):
        return 0.0

def fmt_t(valor):
    """Exibe toneladas no padrão brasileiro, sempre com uma casa decimal."""
    return f'{float(valor or 0):,.1f}'.replace(',', 'X').replace('.', ',').replace('X', '.')+' t'

def fmt_qtd(valor):
    return f'{int(round(float(valor or 0))):,}'.replace(',', '.')


def query(sql, params=()):
    c=conn()
    try:
        cur=c.cursor()
        cur.execute(sql,params)
        rows=cur.fetchall()
        cols=[d[0] for d in cur.description]
        df=pd.DataFrame(rows,columns=cols)
        from decimal import Decimal
        for col in df.columns:
            if any(isinstance(v,Decimal) for v in df[col].head(10)):
                df[col]=pd.to_numeric(df[col],errors='coerce').fillna(0)
        return df
    finally:
        c.close()

def normalizar_pesos_df(df):
    if df is not None and not df.empty and 'toneladas_realizadas' in df.columns:
        df=df.copy()
        df['toneladas_realizadas']=df['toneladas_realizadas'].apply(em_toneladas)
    return df

def scalar_plan(d,t,o,i):
    df=query('SELECT planejado FROM planejamento WHERE data=? AND operacao=? AND indicador=? ORDER BY id DESC LIMIT 1',(str(d),o,i))
    return float(df.iloc[0,0]) if not df.empty else 0.0

def pct(real, plan): return (real/plan*100) if plan else 0.0

def status_auto(pend, absenteismo, ofensor='Sem ofensor', ofensor_grave=False):
    """Classifica riscos operacionais, sem penalizar metas diárias por turno."""
    if absenteismo>=15 or ofensor_grave:
        return '🔴 Crítico'
    if absenteismo>=8 or pend>0 or ofensor!='Sem ofensor':
        return '🟡 Atenção'
    return '🟢 Normal'


def resumo_whatsapp(r,pend):
    """Gera mensagem completa com os dados salvos da passagem."""
    import pandas as pd
    def v(k,default=0):
        x=r.get(k,default)
        return default if x is None or (not isinstance(x,(list,dict)) and pd.isna(x)) else x
    def q(k): return fmt_qtd(v(k))
    def t(k): return fmt_t(em_toneladas(v(k)))
    op=v('operacao','')
    data=pd.to_datetime(v('data')).strftime('%d/%m/%Y')
    m=['📋 *PASSAGEM DE TURNO | ADIMAX*','━━━━━━━━━━━━━━━━━━━━',f'📅 Data: {data}',f'🏭 Operação: {op}',f'🕒 Turno: {nome_turno(v("turno",""))}',f'👤 Líder: {v("responsavel","")}', '', '📦 *RESULTADOS DO TURNO*']
    if op=='CDA 01 - Separação':
        m += [f'• Vendas: {q("varejo_cargas")} cargas | {t("varejo_ton")}',f'• Transferências: {q("transferencias_qtd")} | {t("transferencias_ton")}',f'• Total: {q("cargas_realizadas")} operações | {t("toneladas_realizadas")}',f'• Aguardando caixas CDA 02: {q("cargas_aguardando_caixas_cda02")}',f'• Cargas em P&D: {q("cargas_em_pd")}',f'• Cargas pendentes: {q("quantidade_cargas_pendentes")}']
    elif op=='CDA 01 - Carregamento':
        m += [f'• Veículos carregados: {q("veiculos_carregados")}',f'• Toneladas carregadas: {t("toneladas_realizadas")}',f'• Veículos pendentes: {q("veiculos_pendentes")}']
    elif op=='CDA 02':
        m += [f'• Cargas separadas: {q("cargas_realizadas")}',f'• Paletes/UZs: {q("uz_paletes")}',f'• P&D em espera: {q("pd_espera")}',f'• Transbordos: {q("transbordo_total")} paletes','', '🔎 *CONFERÊNCIA*',f'• Cargas: {q("conf_cargas_conferidas")} / {q("conf_total_cargas")}',f'• UZs: {q("conf_uzs_conferidas")} / {q("conf_total_uzs")}',f'• Erros: {q("conf_erros")}']
        if float(v('conf_total_cargas')): m.append(f'• % cargas: {pct(float(v("conf_cargas_conferidas")),float(v("conf_total_cargas"))):.1f}%')
        if float(v('conf_total_uzs')): m.append(f'• % UZs: {pct(float(v("conf_uzs_conferidas")),float(v("conf_total_uzs"))):.1f}%')
    elif op=='Estoque':
        for titulo,campo,unidade in [('Produção recebida','recebimento_producao_kg','kg'),('Paletes recebidos','recebimento_producao_paletes',''),('Picking abastecido','abastecimento_picking_kg','kg'),('Paletes abastecidos','abastecimento_picking_paletes',''),('Carretas descarregadas','carretas_descarregadas',''),('Carretas armazenadas','carretas_armazenadas',''),('Carretas aguardando','carretas_aguardando',''),('Transbordos CDA 02','transbordos_cda02',''),('Reembalos','reembalo_enviados',''),('Reprocessos','reprocesso_enviados',''),('Máquinas paradas','maquinas_paradas','')]:
            m.append(f'• {titulo}: {q(campo)} {unidade}'.rstrip())
    if not pend.empty:
        m += ['','⏳ *PENDÊNCIAS DETALHADAS*']
        for _,p in pend.iterrows():
            campos=[str(p.get(k) or '').strip() for k in ('carga','cliente','situacao','motivo','descricao')]
            m.append('• '+' | '.join(x for x in campos if x))
    hc=float(v('headcount'));au=float(v('ausencias'));ferias=float(v('ferias'));afast=float(v('afastamentos'));folgas_v=float(v('folgas'));atest_v=float(v('atestados'))
    hc_base=max(hc-ferias-afast-folgas_v,0)
    m += ['','👥 *EQUIPE*',f'• Headcount: {q("headcount")}',f'• Férias: {fmt_qtd(ferias)}',f'• Afastamentos: {fmt_qtd(afast)}',f'• Folgas: {fmt_qtd(folgas_v)}',f'• Atestados: {fmt_qtd(atest_v)}',f'• Efetivo considerado: {fmt_qtd(hc_base)}',f'• Presentes: {q("presentes")}',f'• Ausências: {q("ausencias")}',f'• Absenteísmo: {pct(au+atest_v,hc_base):.1f}%' if hc_base else '• Absenteísmo: não informado',f'• Vagas para contratação: {fmt_qtd(v("vagas_contratacao",0))}','','⚠️ *PRINCIPAL OFENSOR*',str(v('ofensor','Sem ofensor')),'','📝 *OBSERVAÇÕES*',str(v('observacoes','Sem observações') or 'Sem observações')]
    if op=='Estoque' and str(v('pendencias_proximo_turno','')).strip(): m += ['','⏭️ *PRÓXIMO TURNO*',str(v('pendencias_proximo_turno'))]
    m += ['',f'🚦 *STATUS:* {v("status","")}', '━━━━━━━━━━━━━━━━━━━━','✅ Registrado no Passagem de Turno | ADIMAX']
    return '\n'.join(m)

def mostrar_resumo_whatsapp(rid):
    import urllib.parse
    df=query('SELECT * FROM passagens WHERE id=?',(int(rid),))
    if df.empty:
        st.warning('Registro não encontrado.')
        return
    pend=query('SELECT carga,cliente,situacao,motivo,descricao FROM pendencias WHERE passagem_id=?',(int(rid),))
    mensagem=resumo_whatsapp(df.iloc[0],pend)
    st.markdown('#### 📲 Resumo completo para WhatsApp')
    st.caption('Use o botão de copiar do bloco abaixo ou abra o WhatsApp com a mensagem pronta.')
    st.code(mensagem,language=None)
    st.link_button('🟢 Enviar pelo WhatsApp','https://api.whatsapp.com/send?text='+urllib.parse.quote(mensagem))

def salvar_edicao_historico(rid, original, alteracoes, autor, motivo):
    """Atualiza a passagem e registra a versão anterior atomicamente."""
    import json
    permitidos={'data','turno','responsavel','ofensor','observacoes','status',
                'cargas_realizadas','toneladas_realizadas','varejo_cargas',
                'varejo_ton','transferencias_qtd','transferencias_ton',
                'veiculos_carregados','veiculos_pendentes','uz_paletes',
                'headcount','ferias','afastamentos','folgas','atestados','ausencias','presentes','absenteismo',
                'pd_espera','conf_total_cargas','conf_total_uzs',
                'recebimento_producao_kg','recebimento_producao_paletes',
                'abastecimento_picking_kg','abastecimento_picking_paletes',
                'carretas_descarregadas','carretas_armazenadas','carretas_aguardando',
                'transbordos_cda02','reembalo_enviados','reprocesso_enviados',
                'maquinas_paradas','equipamento_parado','problema_equipamento',
                'pendencias_proximo_turno','toneladas_estoque','paletes_estoque',
                'conf_cargas_conferidas','conf_uzs_conferidas','conf_erros'}
    if not alteracoes or not set(alteracoes).issubset(permitidos):
        raise ValueError('Campos de edição inválidos.')
    if not autor.strip() or not motivo.strip():
        raise ValueError('Informe o autor e o motivo da correção.')
    c=conn()
    try:
        cur=c.cursor()
        cur.execute('SELECT to_jsonb(p)::text FROM passagens p WHERE id=? FOR UPDATE',(int(rid),))
        row=cur.fetchone()
        if not row:
            raise ValueError('Registro não encontrado.')
        anterior=json.loads(row[0])
        # A migração adicionou campos de efetivo aos registros antigos.
        # Ignore somente a diferença entre campos novos ausentes no snapshot
        # e seus valores padrão zero; alterações reais continuam bloqueadas.
        original_completo=dict(original)
        for campo in ('ferias','afastamentos','folgas','atestados'):
            if campo not in original_completo and anterior.get(campo)==0:
                original_completo[campo]=0
        if anterior!=original_completo:
            raise ValueError('O registro foi atualizado desde a abertura. Feche e reabra a edição para carregar os valores atuais.')
        if anterior['operacao']=='CDA 02':
            cur.execute("SELECT id FROM passagens WHERE excluido_em IS NULL AND data=? AND turno=? AND area=? AND operacao=? AND id<>?",
                        (alteracoes.get('data',anterior['data']),alteracoes.get('turno',anterior['turno']),
                         anterior['area'],anterior['operacao'],int(rid)))
            if cur.fetchone():
                raise ValueError('Já existe uma passagem CDA 02 para a data e turno selecionados.')
        cur.execute("""CREATE TABLE IF NOT EXISTS passagens_revisoes (
            id BIGSERIAL PRIMARY KEY, passagem_id BIGINT NOT NULL,
            alterado_em TIMESTAMPTZ NOT NULL, autor TEXT NOT NULL,
            motivo TEXT NOT NULL, anterior JSONB NOT NULL, alteracoes JSONB NOT NULL
        )""")
        cur.execute("""INSERT INTO passagens_revisoes
            (passagem_id,alterado_em,autor,motivo,anterior,alteracoes)
            VALUES(?,?,?,?,?::jsonb,?::jsonb)""",
            (int(rid),agora_operacional().isoformat(),autor.strip(),motivo.strip(),
             json.dumps(anterior,ensure_ascii=False),json.dumps(alteracoes,ensure_ascii=False)))
        campos=list(alteracoes)
        cur.execute('UPDATE passagens SET '+', '.join(campo+'=?' for campo in campos)+' WHERE id=?',
                    tuple(alteracoes[campo] for campo in campos)+(int(rid),))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def editar_historico(df):
    import json
    with st.expander('✏️ Modificar registro do histórico'):
        st.caption('Corrija lançamentos sem excluir o histórico. Toda alteração exige autor e motivo e preserva os dados anteriores.')
        opcoes={int(r.id):f"ID {r.id} • {r.data} • {nome_turno(r.turno)} • {r.operacao} • {r.responsavel}" for r in df.itertuples()}
        rid=st.selectbox('Passagem para corrigir',list(opcoes),format_func=lambda x:opcoes[x],index=None,placeholder='Selecione o registro')
        if rid is None:
            return
        chave=f'historico_original_{rid}'
        if chave not in st.session_state:
            registro=query('SELECT to_jsonb(p)::text AS registro FROM passagens p WHERE id=?',(rid,))
            if registro.empty:
                st.warning('Registro não encontrado.')
                return
            st.session_state[chave]=json.loads(registro.iloc[0]['registro'])
        original=st.session_state[chave]
        op=original['operacao']
        def num(campo):
            return float(original.get(campo) or 0)
        with st.form(f'editar_passagem_{rid}'):
            st.markdown(f"**{op} — {nome_turno(original['turno'])} — ID {rid}**")
            nova_data=st.date_input('Data operacional',date.fromisoformat(str(original['data'])[:10]))
            turnos=['T1','T2','T3'] if op!='Estoque' else ['2X2 1A','2X2 1B','2X2 2A','2X2 2B']
            if original['turno'] not in turnos: turnos.append(original['turno'])
            novo_turno=st.selectbox('Turno',turnos,index=turnos.index(original['turno']),format_func=nome_turno)
            responsavel=st.text_input('Líder',value=original.get('responsavel') or '')
            ofensor=st.text_input('Ofensor',value=original.get('ofensor') or 'Sem ofensor')
            observacoes=st.text_area('Observações',value=original.get('observacoes') or '')
            estados=['🟢 Normal','🟡 Atenção','🔴 Crítico']
            if original['status'] not in estados: estados.append(original['status'])
            status=st.selectbox('Status',estados,index=estados.index(original['status']))
            alteracoes={'data':nova_data.isoformat(),'turno':novo_turno,'responsavel':responsavel.strip(),
                        'ofensor':ofensor.strip() or 'Sem ofensor','observacoes':observacoes,'status':status}
            st.markdown('#### Equipe e absenteísmo')
            c1,c2=st.columns(2)
            hc_corr=int(c1.number_input('Headcount previsto',min_value=0,value=int(num('headcount')),step=1))
            ferias_corr=int(c2.number_input('Férias',min_value=0,value=int(num('ferias')),step=1))
            c3,c4=st.columns(2)
            afast_corr=int(c3.number_input('Afastamentos',min_value=0,value=int(num('afastamentos')),step=1))
            faltas_corr=int(c4.number_input('Faltas',min_value=0,value=int(num('ausencias')),step=1))
            c5,c6=st.columns(2)
            folgas_corr=int(c5.number_input('Folgas programadas',min_value=0,value=int(num('folgas'))))
            atestados_corr=int(c6.number_input('Atestados médicos',min_value=0,value=int(num('atestados'))))
            efetivo_corr=max(0,hc_corr-ferias_corr-afast_corr-folgas_corr)
            presentes_corr=max(0,efetivo_corr-faltas_corr-atestados_corr)
            abs_corr=round(100*(faltas_corr+atestados_corr)/efetivo_corr,2) if efetivo_corr else 0.0
            st.info(f'Efetivo considerado: {efetivo_corr} | Presentes: {presentes_corr} | Absenteísmo: {abs_corr:.1f}%')
            alteracoes.update(headcount=hc_corr,ferias=ferias_corr,afastamentos=afast_corr,
                              folgas=folgas_corr,atestados=atestados_corr,ausencias=faltas_corr,presentes=presentes_corr,absenteismo=abs_corr)
            if op=='CDA 01 - Separação':
                st.markdown('#### Separação — corrija vendas e transferências')
                st.caption('Os totais de cargas e toneladas são calculados automaticamente a partir dos campos abaixo.')
                a1,a2=st.columns(2)
                vendas_cargas=a1.number_input('Cargas Vendas',min_value=0.0,value=num('varejo_cargas'),step=1.0,format='%.0f')
                vendas_ton=a2.number_input('Toneladas Vendas (t)',min_value=0.0,value=em_toneladas(num('varejo_ton')),step=0.1)
                b1,b2=st.columns(2)
                transf_cargas=b1.number_input('Quantidade de transferências',min_value=0.0,value=num('transferencias_qtd'),step=1.0,format='%.0f')
                transf_ton=b2.number_input('Toneladas de transferências (t)',min_value=0.0,value=em_toneladas(num('transferencias_ton')),step=0.1)
                total_cargas=vendas_cargas+transf_cargas
                total_ton=vendas_ton+transf_ton
                st.info(f'Total corrigido: {total_cargas:.0f} cargas e {total_ton:.1f} toneladas.')
                alteracoes.update(varejo_cargas=vendas_cargas,varejo_ton=vendas_ton,
                                  transferencias_qtd=transf_cargas,transferencias_ton=transf_ton,
                                  cargas_realizadas=total_cargas,toneladas_realizadas=total_ton)
            elif op=='CDA 01 - Carregamento':
                a1,a2,a3=st.columns(3)
                veiculos=a1.number_input('Veículos carregados',min_value=0.0,value=num('veiculos_carregados'),step=1.0)
                toneladas=a2.number_input('Toneladas carregadas (t)',min_value=0.0,value=em_toneladas(num('toneladas_realizadas')),step=0.1)
                pendentes=a3.number_input('Veículos pendentes',min_value=0.0,value=num('veiculos_pendentes'),step=1.0)
                alteracoes.update(veiculos_carregados=veiculos,toneladas_realizadas=toneladas,veiculos_pendentes=pendentes)
            elif op=='CDA 02':
                a1,a2,a3=st.columns(3)
                cargas=a1.number_input('Cargas separadas',min_value=0.0,value=num('cargas_realizadas'),step=1.0)
                uz=a2.number_input('Paletes / UZs separados',min_value=0.0,value=num('uz_paletes'),step=1.0)
                espera=a3.number_input('P&D espera',min_value=0.0,value=num('pd_espera'),step=1.0)
                st.markdown('#### Conferência')
                b1,b2=st.columns(2)
                tc=b1.number_input('Total de cargas',min_value=0,value=int(num('conf_total_cargas')))
                cc=b2.number_input('Cargas conferidas',min_value=0,value=int(num('conf_cargas_conferidas')))
                b3,b4=st.columns(2)
                tu=b3.number_input('Total de UZs',min_value=0,value=int(num('conf_total_uzs')))
                uc=b4.number_input('UZs conferidas',min_value=0,value=int(num('conf_uzs_conferidas')))
                erros=st.number_input('Erros de conferência',min_value=0,value=int(num('conf_erros')))
                alteracoes.update(cargas_realizadas=cargas,uz_paletes=uz,pd_espera=espera,
                                  conf_total_cargas=tc,conf_cargas_conferidas=cc,
                                  conf_total_uzs=tu,conf_uzs_conferidas=uc,conf_erros=erros)
            elif op=='Estoque':
                st.markdown('#### Recebimento da Produção')
                e1,e2=st.columns(2)
                receb_kg=e1.number_input('Recebimento da Produção (kg)',min_value=0.0,value=num('recebimento_producao_kg'),step=100.0)
                receb_pal=e2.number_input('Paletes recebidos da Produção',min_value=0.0,value=num('recebimento_producao_paletes'),step=1.0)
                st.markdown('#### Abastecimento do Picking')
                e3,e4=st.columns(2)
                abast_kg=e3.number_input('Abastecimento do Picking (kg)',min_value=0.0,value=num('abastecimento_picking_kg'),step=100.0)
                abast_pal=e4.number_input('Paletes abastecidos no Picking',min_value=0.0,value=num('abastecimento_picking_paletes'),step=1.0)
                st.markdown('#### Movimentações e tarefas')
                e5,e6,e7,e8=st.columns(4)
                desc=int(e5.number_input('Carretas descarregadas',min_value=0,value=int(num('carretas_descarregadas'))))
                arm=int(e6.number_input('Carretas armazenadas',min_value=0,value=int(num('carretas_armazenadas'))))
                aguard=int(e7.number_input('Carretas aguardando',min_value=0,value=int(num('carretas_aguardando'))))
                trans=int(e8.number_input('Transbordos para CDA 02',min_value=0,value=int(num('transbordos_cda02'))))
                e9,e10,e11=st.columns(3)
                reemb=int(e9.number_input('Reembalo enviados',min_value=0,value=int(num('reembalo_enviados'))))
                reproc=int(e10.number_input('Reprocesso enviados',min_value=0,value=int(num('reprocesso_enviados'))))
                maquinas=int(e11.number_input('Máquinas paradas',min_value=0,value=int(num('maquinas_paradas'))))
                equip=st.text_input('Equipamento / máquina',value=original.get('equipamento_parado') or '')
                problema=st.text_input('Problema do equipamento',value=original.get('problema_equipamento') or '')
                pend_prox=st.text_area('Pendências para o próximo turno',value=original.get('pendencias_proximo_turno') or '')
                alteracoes.update(recebimento_producao_kg=receb_kg,recebimento_producao_paletes=receb_pal,
                                  abastecimento_picking_kg=abast_kg,abastecimento_picking_paletes=abast_pal,
                                  carretas_descarregadas=desc,carretas_armazenadas=arm,carretas_aguardando=aguard,
                                  transbordos_cda02=trans,reembalo_enviados=reemb,reprocesso_enviados=reproc,
                                  maquinas_paradas=maquinas,equipamento_parado=equip,
                                  problema_equipamento=problema,pendencias_proximo_turno=pend_prox,
                                  toneladas_estoque=receb_kg/1000.0,paletes_estoque=receb_pal)
            st.caption('O horário original de registro será preservado.')
            autor=st.text_input('Seu nome (quem está corrigindo)')
            motivo=st.text_area('Motivo da correção',placeholder='Ex.: erro de digitação de cargas e toneladas')
            confirmar=st.checkbox('Confirmo que conferi os valores corrigidos')
            salvar=st.form_submit_button('💾 Salvar correção',type='primary')
        if salvar:
            if not confirmar:
                st.error('Confirme os valores antes de salvar.')
            elif not responsavel.strip() or not autor.strip() or not motivo.strip():
                st.error('Preencha líder, autor e motivo.')
            elif ferias_corr+afast_corr+folgas_corr+atestados_corr+faltas_corr>hc_corr:
                st.error('Férias, afastamentos e faltas não podem ultrapassar o headcount.')
            elif op=='CDA 02' and (alteracoes['conf_cargas_conferidas']>alteracoes['conf_total_cargas'] or alteracoes['conf_uzs_conferidas']>alteracoes['conf_total_uzs']):
                st.error('Conferidos não podem superar o total.')
            else:
                modificados={k:v for k,v in alteracoes.items() if str(original.get(k) or '')!=str(v)}
                if not modificados:
                    st.info('Nenhum valor foi alterado.')
                else:
                    try:
                        salvar_edicao_historico(rid,original,modificados,autor,motivo)
                    except ValueError as erro:
                        st.error(str(erro))
                        if 'registro foi atualizado' in str(erro):
                            st.session_state.pop(chave,None)
                            st.info('Os dados em memória foram atualizados. Selecione novamente a passagem antes de salvar.')
                    except Exception:
                        st.error('Não foi possível salvar a correção. Nenhuma alteração foi confirmada. Verifique a conexão e a permissão de auditoria.')
                    else:
                        del st.session_state[chave]
                        st.session_state['historico_salvo']='Correção salva. Valores anteriores preservados na auditoria.'
                        st.rerun()
        if st.button('Recarregar registro selecionado',key=f'recarregar_{rid}'):
            del st.session_state[chave]
            st.rerun()

st.markdown('''<style>
.block-container{padding-top:1.1rem}.hero{background:linear-gradient(90deg,#111,#2a2a2a);padding:22px 28px;border-radius:16px;border-left:8px solid #f5b400;color:white;margin-bottom:16px}.hero h1{margin:0;font-size:34px}.hero p{margin:5px 0 0;color:#ddd}.kpi{border:1px solid #e6e6e6;border-radius:14px;padding:14px;background:white}.stButton>button{border-radius:10px;font-weight:700}.status{font-size:22px;font-weight:800}.small{color:#666;font-size:13px}
</style>''',unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>Passagem de Turno</h1><p>Logística • CDA 01 • CDA 02 • Estoque</p></div>',unsafe_allow_html=True)

with st.sidebar:
    st.image(str(APP_DIR / 'static' / 'icon-192.png'), width=144)
    st.markdown('## ADIMAX')
    if os.path.exists('assets/caminhoes.png'): st.image('assets/caminhoes.png',use_container_width=True)
    pagina=st.radio('Navegação',['📝 Nova Passagem','📋 Planejamento','🎯 Planejado do Dia','👁️ Visão Atual','👔 Visão do Supervisor','🏢 Torre de Controle','📊 Semana','🕘 Histórico','🖨️ Imprimir'])
    with st.expander('📲 Adicionar à tela inicial'):
        st.markdown(
            '**Android (Chrome):** abra o menu ⋮ e procure '
            '“Adicionar à tela inicial” ou “Instalar aplicativo”.\n\n'
            '**iPhone/iPad (Safari):** toque em Compartilhar e '
            '“Adicionar à Tela de Início”.\n\n'
            '**Computador (Chrome/Edge):** no menu do navegador, procure '
            'a opção para instalar esta página como aplicativo, se disponível.'
        )
        st.caption('As opções variam conforme o navegador. O app precisa de internet. '
                   'O nome e o ícone do atalho podem depender do navegador.')


if pagina=='📋 Planejamento':
    st.header('📋 Planejamento diário')
    st.caption('Metas diárias de Separação e Carregamento. Ao salvar novamente a mesma data, as metas são atualizadas.')
    d=st.date_input('Data do planejamento',agora_operacional().date())
    st.markdown('#### 📦 Separação')
    sep_plan=st.number_input('Toneladas planejadas de Separação',min_value=0.0,step=1.0,format='%.1f',value=scalar_plan(d,'DIA','CDA 01 - Separação','Toneladas'),key=f'sep_{d}')
    st.markdown('#### 🚛 Carregamento')
    car_qtd=st.number_input('Veículos / cargas planejados',min_value=0,step=1,value=int(scalar_plan(d,'DIA','CDA 01 - Carregamento','Veículos')),key=f'car_qtd_{d}')
    if st.button('💾 Salvar / atualizar planejamento diário',type='primary'):
        c=conn()
        try:
            cur=c.cursor()
            agora=agora_operacional().isoformat(timespec='seconds')
            for op,indicador,valor in [
                ('CDA 01 - Separação','Toneladas',sep_plan),
                ('CDA 01 - Carregamento','Veículos',car_qtd),
            ]:
                cur.execute("""INSERT INTO planejamento(data,operacao,indicador,planejado,atualizado_em)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT (data,operacao,indicador)
                    DO UPDATE SET planejado=EXCLUDED.planejado, atualizado_em=EXCLUDED.atualizado_em""",
                    (str(d),op,indicador,valor,agora))
            c.commit()
            st.success('Planejamento atualizado para a data selecionada.')
            st.rerun()
        except Exception:
            c.rollback()
            st.error('Não foi possível salvar o planejamento. Verifique a conexão e a estrutura da tabela.')
        finally:
            c.close()
    df=query("""SELECT data,operacao,indicador,planejado,atualizado_em
                FROM planejamento
                WHERE (operacao='CDA 01 - Separação' AND indicador='Toneladas')
                   OR (operacao='CDA 01 - Carregamento' AND indicador='Veículos')
                ORDER BY data DESC,atualizado_em DESC LIMIT 150""")
    if not df.empty:
        st.markdown('#### Planejamentos registrados')
        st.dataframe(df.rename(columns={'data':'Data','operacao':'Operação','indicador':'Indicador','planejado':'Planejado','atualizado_em':'Atualizado em'}),use_container_width=True,hide_index=True)
    else:
        st.info('Ainda não existe planejamento diário cadastrado.')

elif pagina=='🎯 Planejado do Dia':
    st.header('🎯 Painel de Gestão à Vista')
    st.caption('Logística • fechamento diário para acompanhamento e GDD')
    d=st.date_input('Data do painel',agora_operacional().date(),key='data_painel_dia')
    data_painel=d  # Preserva a data: variáveis de colunas podem reutilizar o nome d.
    plan_sep=scalar_plan(d,'DIA','CDA 01 - Separação','Toneladas')
    plan_car_qtd=scalar_plan(d,'DIA','CDA 01 - Carregamento','Veículos')
    if plan_sep>=10000: plan_sep=plan_sep/1000.0
    dados=query("SELECT * FROM passagens WHERE excluido_em IS NULL AND data BETWEEN ? AND ? AND operacao IN ('CDA 01 - Separação','CDA 01 - Carregamento') ORDER BY id",(str(d-timedelta(days=1)),str(d)))
    if not dados.empty:
        dados=dados[dados.apply(lambda r:data_ciclo_operacional(r['data'],r['turno'],r['operacao'])==d,axis=1)].copy()
    st.caption('Separação: T3 da véspera → T1 → T2. Carregamento: T1 → T2 → T3 da própria data.')
    if not dados.empty:
        dados=dados.sort_values('id').groupby(['operacao','turno'],as_index=False).tail(1)
    sep=dados[dados.operacao=='CDA 01 - Separação'] if not dados.empty else pd.DataFrame()
    car=dados[dados.operacao=='CDA 01 - Carregamento'] if not dados.empty else pd.DataFrame()
    real_sep=sum(em_toneladas(v) for v in sep.toneladas_realizadas) if not sep.empty else 0.0
    ton_car=sum(em_toneladas(v) for v in car.toneladas_realizadas) if not car.empty else 0.0
    cargas_car=float(car.veiculos_carregados.sum()) if not car.empty else 0.0
    ating=pct(real_sep,plan_sep); gap=real_sep-plan_sep if plan_sep else 0.0
    # Absenteísmo por turno e geral:
    # soma as equipes das diferentes passagens/operações de cada turno.
    # Mantém somente a passagem mais recente de cada operação/turno para
    # não duplicar uma passagem que tenha sido corrigida/regravada.
    abs_dia=query("SELECT * FROM passagens WHERE excluido_em IS NULL AND data BETWEEN ? AND ? AND operacao IN ('CDA 01 - Separação','CDA 01 - Carregamento','CDA 02') ORDER BY id",(str(d-timedelta(days=1)),str(d)))
    if not abs_dia.empty:
        abs_dia=abs_dia[abs_dia.apply(lambda r:data_ciclo_operacional(r['data'],r['turno'],r['operacao'])==d,axis=1)].copy()
    hc_geral=0.0; aus_geral=0.0
    abs_turnos={t:(None,0.0,0.0) for t in ['T1','T2','T3']}
    if not abs_dia.empty:
        base_abs=abs_dia.sort_values('id').groupby(['turno','operacao'],as_index=False).tail(1)
        for t in ['T1','T2','T3']:
            rt=base_abs[base_abs.turno==t]
            if not rt.empty:
                hc=float((rt.headcount-rt.ferias-rt.afastamentos-rt.folgas).clip(lower=0).sum())
                au=float((rt.ausencias+rt.atestados).sum())
                perc=(au/hc*100) if hc else 0.0
                abs_turnos[t]=(perc,au,hc)
                hc_geral+=hc
                aus_geral+=au
    abs_geral=(aus_geral/hc_geral*100) if hc_geral else 0.0

    st.markdown('### 👥 Absenteísmo do Dia')
    a1,a2,a3,a4=st.columns(4)
    a1.metric('Geral do dia',f'{abs_geral:.1f}%' if hc_geral else 'Aguardando')
    for col,t in zip([a2,a3,a4],['T3','T1','T2']):
        p,au,hc=abs_turnos[t]
        if p is None:
            col.metric(nome_turno(t),'Aguardando passagem')
        else:
            col.metric(nome_turno(t),f'{p:.1f}%',f'{au:g} ausências | HC {hc:g}')
    st.caption(f'Total consolidado: {aus_geral:g} ausências | Headcount {hc_geral:g}' if hc_geral else 'Ainda não há efetivo lançado para o dia.')
    st.markdown('---')

    st.markdown('### 📦 Separação')
    k1,k2,k3,k4=st.columns(4)
    k1.metric('Planejado do dia',f'{plan_sep:.1f} t'); k2.metric('Realizado acumulado',f'{real_sep:.1f} t')
    k3.metric('Atingimento',f'{ating:.1f}%' if plan_sep else '—'); k4.metric('Gap',f'{gap:+.1f} t' if plan_sep else '—')
    varejo_t=0.0; transf_t=0.0; varejo_q=0.0; transf_q=0.0
    if not sep.empty:
        if 'varejo_ton' in sep.columns: varejo_t=sum(em_toneladas(v) for v in sep.varejo_ton)
        if 'transferencias_ton' in sep.columns: transf_t=sum(em_toneladas(v) for v in sep.transferencias_ton)
        if 'varejo_cargas' in sep.columns: varejo_q=float(sep.varejo_cargas.sum())
        if 'transferencias_qtd' in sep.columns: transf_q=float(sep.transferencias_qtd.sum())
    st.markdown('#### Composição da Separação')
    a,b,c,d=st.columns(4)
    a.metric('Cargas Vendas',f'{varejo_q:g}')
    b.metric('Vendas',fmt_t(varejo_t))
    c.metric('Transferências',f'{transf_q:g}')
    d.metric('Transferências',fmt_t(transf_t))
    st.markdown('#### Realizado por turno — Separação')
    cols=st.columns(3)
    for col,t in zip(cols,['T3','T1','T2']):
        v=0.0
        if not sep.empty and not sep[sep.turno==t].empty: v=em_toneladas(sep[sep.turno==t].iloc[-1].toneladas_realizadas)
        col.metric(nome_turno(t),f'{v:.1f} t')
    st.markdown('---'); st.markdown('### 🚛 Carregamento')
    c1,c2,c3=st.columns(3)
    c1.metric('Veículos planejados',f'{plan_car_qtd:g}')
    c2.metric('Veículos carregados',f'{cargas_car:g}',f'{cargas_car-plan_car_qtd:+g} vs meta' if plan_car_qtd else None)
    c3.metric('Toneladas carregadas (informativo)',f'{ton_car:.1f} t')
    st.metric('Atingimento veículos',f'{pct(cargas_car,plan_car_qtd):.1f}%' if plan_car_qtd else '—')
    st.markdown('#### Realizado por turno — Carregamento')
    cols=st.columns(3)
    for col,t in zip(cols,['T1','T2','T3']):
        n=0.0; peso=0.0
        if not car.empty and not car[car.turno==t].empty:
            r=car[car.turno==t].iloc[-1]; n=float(r.veiculos_carregados); peso=em_toneladas(r.toneladas_realizadas)
        col.metric(nome_turno(t),f'{n:g} cargas',f'{peso:.1f} t')
    st.caption('Após a passagem do T3, este painel entrega o fechamento do dia para o GDD.')
    st.markdown('---')
    st.markdown('### 📦 Movimentação do Estoque — escala 2x2')
    st.caption('Somente registros do Estoque na data selecionada; sem deslocar o turno 2x2 para outro dia.')
    estoque_dia=query("SELECT * FROM passagens WHERE excluido_em IS NULL AND data=? AND operacao='Estoque' ORDER BY id",(str(data_painel),))
    if estoque_dia.empty:
        st.info('Ainda não há passagem do Estoque para esta data.')
    else:
        estoque_dia=estoque_dia.sort_values('id').groupby(['data','turno','operacao'],as_index=False).tail(1)
        recebimento_total=float(estoque_dia['recebimento_producao_kg'].sum())
        picking_total=float(estoque_dia['abastecimento_picking_kg'].sum())
        paletes_recebidos=float(estoque_dia['recebimento_producao_paletes'].sum())
        paletes_picking=float(estoque_dia['abastecimento_picking_paletes'].sum())
        e1,e2=st.columns(2)
        e1.metric('Recebimento da produção',f"{recebimento_total:,.0f} kg".replace(',','.'))
        e2.metric('Abastecimento do Picking',f"{picking_total:,.0f} kg".replace(',','.'))
        e3,e4=st.columns(2)
        e3.metric('Paletes recebidos',f'{paletes_recebidos:g}')
        e4.metric('Paletes abastecidos',f'{paletes_picking:g}')
        with st.expander('Detalhamento do Estoque por turno 2x2'):
            detalhe_estoque=estoque_dia[['turno','recebimento_producao_kg','abastecimento_picking_kg','recebimento_producao_paletes','abastecimento_picking_paletes']].copy()
            detalhe_estoque.columns=['Turno','Recebimento (kg)','Picking (kg)','Paletes recebidos','Paletes abastecidos']
            st.dataframe(detalhe_estoque,hide_index=True,use_container_width=True)


elif pagina=='📝 Nova Passagem':
    st.header('📝 Nova passagem')
    st.caption('Selecione o líder para preencher automaticamente a área, o responsável e o turno.')
    resp=st.selectbox('👤 Líder',options=list(LIDERES),index=None,placeholder='Selecione seu nome')
    if not resp:
        st.info('Selecione o líder para iniciar a passagem de turno.')
        st.stop()
    area,supervisor,turno=LIDERES[resp]
    turno_nome=nome_turno(turno) if turno in ('T1','T2','T3') else turno
    a,b,c=st.columns(3)
    a.text_input('Área',value=area,disabled=True)
    b.text_input('Turno',value=turno_nome,disabled=True)
    c.text_input('Responsável',value=supervisor,disabled=True)
    instante_formulario=agora_operacional()
    data_sugerida=sugerir_data_operacional(turno,instante_formulario)
    data_reg=data_sugerida
    dias_semana_pt=('segunda-feira','terça-feira','quarta-feira','quinta-feira','sexta-feira','sábado','domingo')
    data_extenso=f'{dias_semana_pt[data_reg.weekday()]}, {data_reg.strftime("%d/%m/%Y")}'
    st.info(f'📅 **DATA OPERACIONAL: {data_extenso}** | **{turno_nome}** | {area}')
    st.caption('Data automática conforme o início do turno. O horário real de registro é salvo separadamente.')
    data_confirmada=True
    # Permissões operacionais por líder; a área e o turno permanecem automáticos.
    if area=='CDA 01':
        if resp=='ALISON RIBEIRO DE OLIVEIRA':
            operacao=st.selectbox('Operação autorizada',['CDA 01 - Separação','CDA 01 - Carregamento'])
        elif resp in ('BRUNO RICARDO DE OLIVEIRA MELO','WESLEY VITOR RODRIGUES'):
            operacao='CDA 01 - Carregamento'
        else:
            operacao='CDA 01 - Separação'
        st.caption('Operação: '+operacao.replace('CDA 01 - ',''))
    else:
        operacao='CDA 02' if area=='CDA 02' else 'Estoque'

    st.subheader('👥 Equipe')
    aus_det=[]
    def campos_nomes(container,categoria,quantidade):
        """Campos compactos logo abaixo do indicador numérico."""
        for i in range(quantidade):
            nome=container.text_input(
                f'{categoria} — nome {i+1}',
                key=f'nome_{categoria}_{i}_{resp}_{data_reg.isoformat()}',
                placeholder=f'Nome do colaborador {i+1}',
                label_visibility='collapsed')
            if nome.strip():
                aus_det.append((categoria,nome.strip()))
    h1,h2=st.columns(2)
    hc=int(h1.number_input('Headcount previsto do turno',min_value=0,step=1))
    ferias=int(h2.number_input('Férias (não contam como falta)',min_value=0,step=1))
    campos_nomes(h2,'Férias',ferias)
    h3,h4=st.columns(2)
    afastamentos=int(h3.number_input('Afastamentos (não contam como falta)',min_value=0,step=1))
    campos_nomes(h3,'Afastamentos',afastamentos)
    aus=int(h4.number_input('Faltas / ausências não programadas',min_value=0,step=1))
    campos_nomes(h4,'Faltas',aus)
    h5,h6=st.columns(2)
    folgas=int(h5.number_input('Folgas programadas',min_value=0,step=1))
    campos_nomes(h5,'Folgas',folgas)
    atestados=int(h6.number_input('Atestados médicos',min_value=0,step=1))
    campos_nomes(h6,'Atestados',atestados)
    efetivo=max(hc-ferias-afastamentos-folgas,0)
    presentes=max(efetivo-aus-atestados,0)
    vagas_contratacao=int(st.number_input('Vagas para contratação',min_value=0,step=1,help='Informe quantas vagas estão abertas neste turno. Não altera o cálculo do absenteísmo.'))
    reposicoes_recebidas=0  # Campo legado preservado no banco; não representa vagas.
    disponiveis=presentes
    abs_pct=((aus+atestados)/efetivo*100) if efetivo else 0
    m1,m2,m3,m4=st.columns(4)
    m1.metric('Efetivo considerado',efetivo)
    m2.metric('Presentes',presentes)
    m3.metric('Férias',ferias)
    m4.metric('Absenteísmo',f'{abs_pct:.1f}%' if efetivo else '—')
    r1,r2,r3=st.columns(3)
    r1.metric('Vagas para contratação',vagas_contratacao)
    r2.metric('Presentes',presentes)
    r3.metric('Headcount necessário',hc)
    st.caption('Férias e afastamentos são separados das faltas. A classificação de afastamentos deve seguir a regra de RH da empresa.')
    cargas=ton=vt=vc=vp=uz=pd_e=trans=ton_est=pal_est=0.0
    varejo_cargas=varejo_ton=transferencias_qtd=transferencias_ton=0.0
    receb_kg=receb_pal=abast_kg=abast_pal=0.0
    car_desc=car_arm=car_agu=trans_cda02=reemb=reproc=maq_par=0
    equip_parado=problema_equip=pend_prox=''
    pc=pt=pv=0.0
    pend=[]
    n=0
    cargas_aguardando_caixas=0
    cargas_em_pd=0
    conf_tc=conf_tu=conf_er=conf_cc=conf_uc=None
    st.subheader('📦 Resultado do turno')
    if operacao=='CDA 01 - Separação':
        pc=0.0; pt=scalar_plan(data_reg,'DIA',operacao,'Toneladas')
        if pt>=10000: pt=pt/1000.0
        st.caption('Padrão: toneladas (t). Valores antigos lançados em kg são convertidos para exibição; confirme sempre a unidade informada.')
        st.markdown('#### 🛒 Varejo')
        x,y=st.columns(2)
        varejo_cargas=x.number_input('Cargas Vendas',min_value=0.0,step=1.0)
        varejo_ton=y.number_input('Toneladas Vendas (t)',min_value=0.0,step=0.1,format='%.1f',help='Informe em toneladas. Ex.: 163,2 t, não 163.200 kg.')
        st.markdown('#### 🔄 Transferências')
        x,y=st.columns(2)
        transferencias_qtd=x.number_input('Quantidade de Transferências',min_value=0.0,step=1.0)
        transferencias_ton=y.number_input('Toneladas de Transferências (t)',min_value=0.0,step=0.1,format='%.1f',help='Informe em toneladas. Ex.: 67,9 t, não 67.900 kg.')
        cargas=varejo_cargas+transferencias_qtd
        varejo_ton=em_toneladas(varejo_ton); transferencias_ton=em_toneladas(transferencias_ton)
        ton=varejo_ton+transferencias_ton
        t1,t2=st.columns(2)
        t1.metric('Total operações separadas',f'{cargas:g}')
        t2.metric('Total separado no turno',fmt_t(ton))
        st.info(f'Planejado diário da Separação: {pt:.1f} t' if pt else 'Planejamento diário ainda não cadastrado.')
        st.markdown('#### ⏳ Cargas aguardando / P&D')
        p1,p2=st.columns(2)
        cargas_aguardando_caixas=int(p1.number_input('Cargas aguardando caixas do CDA 02',min_value=0,step=1,key='sep_aguardando_caixas'))
        cargas_em_pd=int(p2.number_input('Cargas em P&D',min_value=0,step=1,key='sep_cargas_em_pd'))
        st.caption('Pendências no fechamento; não entram na produtividade de cargas separadas.')
        n=int(st.number_input('Quantidade de cargas pendentes',min_value=0,step=1,help='Informe apenas o total. Não é necessário cadastrar cada carga.'))
    elif operacao=='CDA 01 - Carregamento':
        pv=0.0
        pt=0.0
        x,y,z=st.columns(3)
        vc=x.number_input('Veículos carregados',min_value=0.0,step=1.0)
        vp=y.number_input('Veículos para o próximo turno',min_value=0.0,step=1.0)
        ton=z.number_input('Toneladas carregadas no turno (t)',min_value=0.0,step=0.1,format='%.3f')
        st.caption('Informe somente a quantidade de veículos/cargas pendentes para o próximo turno. Não é necessário detalhar cada carga.')
    elif operacao=='CDA 02':
        diferencas_entre_pisos=st.number_input('Diferenças entre pisos (cargas)',value=0,step=1,format='%d',help='Digite positivo ou negativo. Ex.: +5 ou -4.',key='diferencas_entre_pisos')
        st.caption(f'Valor informado: {diferencas_entre_pisos:+d} cargas. Convenção do placar: positivo = CDA 01 à frente; negativo = CDA 02 à frente; zero = empatados.')
        pc=scalar_plan(data_reg,turno,operacao,'Cargas'); pp=scalar_plan(data_reg,turno,operacao,'Paletes/UZs')
        x,y,z=st.columns(3); cargas=x.number_input('Cargas separadas',min_value=0.0,step=1.0); uz=y.number_input('Paletes / UZs separados',min_value=0.0,step=1.0); pd_e=z.number_input('P&D Espera',min_value=0.0,step=1.0)
        st.info(f'Planejado: {pc:g} cargas | {pp:g} paletes/UZs')
        st.markdown('**Transbordos (paletes)**')
        st.caption('Automático: soma recebimentos e carregamentos por setor, na data e turno selecionados.')
        setores_trans=['Ensaque','Úmidos','Biscoito','Expedição','Estoque','Fornecedores','Outros']
        try:
            totais_trans,qtd_mov=consultar_transbordos(data_reg,turno)
            tr=[float(totais_trans[nome]) for nome in setores_trans]
            cols_trans=st.columns(4)
            for i,nome in enumerate(setores_trans):
                cols_trans[i%4].metric(nome,f'{int(tr[i])} paletes')
            st.success(f'{qtd_mov} movimentações consultadas. Total: {int(sum(tr))} paletes.')
            st.caption('Atualização da consulta a cada 45 segundos; valores registrados na passagem ao salvar.')
        except Exception as erro_trans:
            st.warning('⚠️ Integração com Vira 360 temporariamente indisponível. A passagem pode continuar com lançamento manual de contingência.')
            st.caption('O Vira 360 passou a exigir autenticação na consulta. Os valores abaixo devem ser conferidos com o registro do Vira 360. Nenhuma movimentação será alterada no sistema de origem.')
            tr=[]
            cols_trans=st.columns(4)
            for i,nome in enumerate(setores_trans):
                tr.append(float(cols_trans[i%4].number_input(f'{nome} — paletes (contingência)',min_value=0,step=1,key=f'trans_manual_{nome}')))
            st.info('Modo contingência: valores digitados manualmente para esta passagem de turno.')
        trans=sum(tr); pt=pp
        st.markdown('### 🔎 Conferência CDA 02')
        st.caption('Dados da mesma data, turno e responsável desta passagem. Percentuais automáticos.')
        cc1,cc2,cc3=st.columns(3)
        conf_tc=int(cc1.number_input('Total de cargas do turno',min_value=0,step=1,key='cda02_conf_tc'))
        conf_tu=int(cc2.number_input('Total de UZs do turno',min_value=0,step=1,key='cda02_conf_tu'))
        conf_er=int(cc3.number_input('Quantidade de erros',min_value=0,step=1,key='cda02_conf_er'))
        cc4,cc5=st.columns(2)
        conf_cc=int(cc4.number_input('Cargas conferidas',min_value=0,step=1,key='cda02_conf_cc'))
        conf_uc=int(cc5.number_input('UZs conferidas',min_value=0,step=1,key='cda02_conf_uc'))
        cm1,cm2,cm3=st.columns(3)
        cm1.metric('Cargas conferidas',conf_cc)
        cm2.metric('% cargas conferidas',f'{pct(conf_cc,conf_tc):.1f}%' if conf_tc else '—')
        cm3.metric('% UZs conferidas',f'{pct(conf_uc,conf_tu):.1f}%' if conf_tu else '—')
        st.caption('Uma passagem CDA 02 por data e turno. Se já existir, consulte o Histórico; o registro anterior não será sobrescrito.')

    else:
        st.markdown('### 🏭 Indicadores principais')
        a1,a2=st.columns(2)
        receb_t=a1.number_input('Recebimento da Produção (toneladas)',min_value=0.0,step=1.0,format='%.3f',help='Exemplo: 121 = 121 toneladas = 121.000 kg')
        receb_kg=round(receb_t*1000,3)
        a1.caption(f'Equivale a {receb_kg:,.0f} kg'.replace(',','.'))
        receb_pal=a2.number_input('Paletes recebidos da Produção',min_value=0.0,step=1.0)
        b1,b2=st.columns(2)
        abast_t=b1.number_input('Abastecimento do Picking (toneladas)',min_value=0.0,step=1.0,format='%.3f',help='Exemplo: 238 = 238 toneladas = 238.000 kg')
        abast_kg=round(abast_t*1000,3)
        b1.caption(f'Equivale a {abast_kg:,.0f} kg'.replace(',','.'))
        abast_pal=b2.number_input('Paletes abastecidos no Picking',min_value=0.0,step=1.0)

        st.markdown('### 🚛 Movimentações / tarefas do turno')
        m1,m2,m3,m4=st.columns(4)
        car_desc=int(m1.number_input('Carretas descarregadas',min_value=0,step=1))
        car_arm=int(m2.number_input('Carretas armazenadas',min_value=0,step=1))
        car_agu=int(m3.number_input('Carretas aguardando',min_value=0,step=1))
        trans_cda02=int(m4.number_input('Transbordos para CDA 02',min_value=0,step=1))
        m5,m6,m7=st.columns(3)
        reemb=int(m5.number_input('Reembalo enviados',min_value=0,step=1))
        reproc=int(m6.number_input('Reprocesso enviados',min_value=0,step=1))
        maq_par=int(m7.number_input('Máquinas paradas',min_value=0,step=1))

        if maq_par:
            e1,e2=st.columns(2)
            equip_parado=e1.text_input('Equipamento / máquina')
            problema_equip=e2.text_input('Problema do equipamento')

        st.markdown('### ⏭️ Pendências para o próximo turno')
        pend_prox=st.text_area('Pendências / informações que o próximo turno precisa receber',
                               placeholder='Ex.: carreta aguardando descarga, placa, motorista, transferência pendente...')
        ton_est=receb_kg/1000.0
        pal_est=receb_pal
        st.caption('Os indicadores principais do Estoque alimentarão o resumo semanal por turno.')

    gc=cargas-pc if pc else 0; real_ton=(ton if operacao in ['CDA 01 - Separação','CDA 01 - Carregamento'] else ton_est); gt=real_ton-pt if pt else 0; gv=vc-pv if pv else 0
    ac=pct(cargas,pc); at=pct(real_ton,pt); av=pct(vc,pv)
    st.subheader('🎯 Planejado × Realizado')
    k1,k2,k3=st.columns(3)
    if operacao in ['CDA 01 - Separação','CDA 02']: k1.metric('Cargas',f'{cargas:g}',f'{gc:+g} vs planejado' if pc else 'Sem planejado'); k2.metric('Atingimento cargas',f'{ac:.1f}%' if pc else '—')
    if operacao in ['CDA 01 - Separação','CDA 01 - Carregamento','Estoque']: k3.metric('Atingimento toneladas',f'{at:.1f}%' if pt else '—')
    if operacao=='CDA 01 - Carregamento': k1.metric('Cargas carregadas',f'{vc:g}'); k2.metric('Toneladas carregadas',f'{em_toneladas(ton):.1f} t'); k3.metric('Para o próximo turno',f'{vp:g} cargas')

    st.subheader('⚠️ Fechamento')
    of=st.selectbox('Principal ofensor',['Sem ofensor','Falta de produto/estoque','Mão de obra','Sistema/Integração','WMS/Körber','Atraso/ausência de veículo','Equipamento','Qualidade','Retrabalho','Operacional','Outro'])
    obs=st.text_area('Observações / detalhes do ofensor / pontos de atenção para o próximo turno',height=220,placeholder='Descreva o que aconteceu, o impacto na operação, as ações tomadas e o que o próximo turno precisa acompanhar...')
    ofensor_grave=st.checkbox('🚨 Ofensor grave: comprometeu a operação',value=False,help='Marque somente em caso de ocorrência com impacto operacional grave, como paralisação ou bloqueio relevante.')
    stat=status_auto(n if operacao=='CDA 01 - Separação' else len(pend),abs_pct,of,ofensor_grave)
    st.markdown(f'<div class="status">Status sugerido: {stat}</div>',unsafe_allow_html=True)
    passagem_existente=query(
        'SELECT id,responsavel,criado_em FROM passagens WHERE excluido_em IS NULL AND data=? AND area=? AND operacao=? AND turno=? AND registro_duplicado=FALSE ORDER BY id DESC LIMIT 1',
        (str(data_reg),area,operacao,turno))
    if not passagem_existente.empty:
        st.error(f'🔒 Esta passagem já foi registrada para {data_reg.strftime("%d/%m/%Y")} — {turno_nome} — {operacao}. Registro nº {int(passagem_existente.iloc[0]["id"])}. Consulte o Histórico; não é permitido enviar novamente.')
    if st.button('💾 Salvar passagem',type='primary',use_container_width=True,disabled=not passagem_existente.empty):
        if not resp.strip(): st.error('Informe o responsável pela passagem.')
        elif not data_confirmada: st.error('Confirme a data operacional antes de salvar a passagem.')
        elif any(len([n for c,n in aus_det if c==categoria])>quantidade for categoria,quantidade in [('Férias',ferias),('Afastamentos',afastamentos),('Atestados',atestados),('Faltas',aus),('Folgas',folgas)]): st.error('A quantidade de nomes não pode superar o total informado na categoria.')
        elif ferias>hc: st.error('Férias não podem superar o headcount.')
        elif afastamentos>hc-ferias: st.error('Férias e afastamentos não podem superar o headcount.')
        elif folgas+atestados+aus>hc-ferias-afastamentos: st.error('Faltas não podem superar o efetivo considerado.')
        elif operacao=='CDA 02' and (conf_cc>conf_tc or conf_uc>conf_tu): st.error('A quantidade conferida não pode superar o total.')
        else:
            c=None
            try:
                c=conn();cur=c.cursor()
                cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS cargas_aguardando_caixas_cda02 INTEGER NOT NULL DEFAULT 0')
                cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS cargas_em_pd INTEGER NOT NULL DEFAULT 0')
                cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS ferias INTEGER NOT NULL DEFAULT 0')
                cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS afastamentos INTEGER NOT NULL DEFAULT 0')
                cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS folgas INTEGER NOT NULL DEFAULT 0')
                cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS atestados INTEGER NOT NULL DEFAULT 0')
                cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS reposicoes_recebidas INTEGER NOT NULL DEFAULT 0')
                cur.execute('ALTER TABLE passagens ADD COLUMN IF NOT EXISTS quantidade_cargas_pendentes INTEGER NOT NULL DEFAULT 0')
                cur.execute('''INSERT INTO passagens(
                criado_em,data,turno,area,operacao,responsavel,headcount,ausencias,presentes,absenteismo,
                cargas_realizadas,toneladas_realizadas,veiculos_trabalhados,veiculos_carregados,veiculos_pendentes,
                uz_paletes,pd_espera,transbordo_total,toneladas_estoque,paletes_estoque,
                planejado_cargas,planejado_ton,planejado_veiculos,gap_cargas,gap_ton,gap_veiculos,
                ating_cargas,ating_ton,ating_veiculos,ofensor,observacoes,status,
                recebimento_producao_kg,recebimento_producao_paletes,abastecimento_picking_kg,abastecimento_picking_paletes,
                carretas_descarregadas,carretas_armazenadas,carretas_aguardando,transbordos_cda02,
                reembalo_enviados,reprocesso_enviados,maquinas_paradas,equipamento_parado,problema_equipamento,pendencias_proximo_turno,
                varejo_cargas,varejo_ton,transferencias_qtd,transferencias_ton,
                conf_total_cargas,conf_total_uzs,conf_erros,conf_cargas_conferidas,conf_uzs_conferidas,
                cargas_aguardando_caixas_cda02,cargas_em_pd,ferias,afastamentos,folgas,atestados,reposicoes_recebidas
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
                (agora_operacional().isoformat(timespec='seconds'),str(data_reg),turno,area,operacao,resp,hc,aus,presentes,abs_pct,
                 cargas,ton,vt,vc,vp,uz,pd_e,trans,ton_est,pal_est,pc,pt,pv,gc,gt,gv,ac,at,av,of,obs,stat,
                 receb_kg,receb_pal,abast_kg,abast_pal,car_desc,car_arm,car_agu,trans_cda02,reemb,reproc,maq_par,
                 equip_parado,problema_equip,pend_prox,varejo_cargas,varejo_ton,transferencias_qtd,transferencias_ton,conf_tc,conf_tu,conf_er,conf_cc,conf_uc,cargas_aguardando_caixas,cargas_em_pd,ferias,afastamentos,folgas,atestados,reposicoes_recebidas)); pid=cur.lastrowid
                if pid is not None:
                    cur.execute('UPDATE passagens SET vagas_contratacao=? WHERE id=?',(int(vagas_contratacao),int(pid)))
                    if operacao=='CDA 01 - Separação':
                        cur.execute('UPDATE passagens SET quantidade_cargas_pendentes=? WHERE id=?',(int(n),int(pid)))
                if pid is not None and operacao=='CDA 02':
                    cur.execute('UPDATE passagens SET diferencas_entre_pisos=? WHERE id=?',(int(diferencas_entre_pisos),int(pid)))
                if pid is None:
                    c.rollback()
                    st.error('Já existe uma passagem para esta data, operação e turno. O registro existente foi preservado. Consulte o Histórico antes de solicitar uma correção.')
                    st.stop()
                if aus_det:
                    cur.execute("""CREATE TABLE IF NOT EXISTS colaboradores_ocorrencias (
                        id BIGSERIAL PRIMARY KEY, passagem_id BIGINT NOT NULL,
                        categoria TEXT NOT NULL, nome TEXT NOT NULL
                    )""")
                    for categoria,nome in aus_det:
                        cur.execute('INSERT INTO colaboradores_ocorrencias(passagem_id,categoria,nome) VALUES(?,?,?)',(pid,categoria,nome))
                for r in pend: cur.execute('INSERT INTO pendencias(passagem_id,carga,cliente,situacao,motivo,descricao) VALUES(?,?,?,?,?,?)',(pid,*r))
                c.commit();st.session_state['ultima_passagem_whats']=int(pid);st.success('Passagem salva com sucesso.')
            except Exception:
                if c is not None:
                    c.rollback()
                st.error('Não foi possível salvar a passagem. Nenhum registro foi confirmado. Verifique a conexão e tente novamente; se persistir, acione a liderança.')
            finally:
                if c is not None:
                    c.close()


    if st.session_state.get('ultima_passagem_whats'):
        mostrar_resumo_whatsapp(st.session_state['ultima_passagem_whats'])

elif pagina=='👁️ Visão Atual':
    st.header('👁️ Visão atual')
    st.caption('Separação CDA 01: T3 da véspera + T1 + T2. Carregamento CDA 01 e CDA 02: T1 + T2 + T3 da data. Estoque: 2x2.')
    df=query('SELECT * FROM passagens WHERE excluido_em IS NULL ORDER BY id DESC')
    if df.empty: st.info('Ainda não existem passagens salvas.')
    else:
        latest=df.groupby(['operacao','turno'],as_index=False).first()
        latest['Ordem']=latest.apply(lambda r: ({'T1':0,'T2':1,'T3':2} if r['operacao']=='CDA 01 - Carregamento' else {'T3':0,'T1':1,'T2':2,'2X2 1A':3,'2X2 1B':4,'2X2 2A':5,'2X2 2B':6}).get(r['turno'],7),axis=1)
        latest=latest.sort_values(['operacao','Ordem'])
        for _,r in latest.iterrows():
            with st.expander(f"{r['operacao']} • {nome_turno(r['turno'])} • {r['status']}",expanded=True):
                if r['operacao']=='Estoque':
                    c1,c2,c3,c4=st.columns(4)
                    c1.metric('Recebimento Produção',f"{r['recebimento_producao_kg']:,.0f} kg".replace(',','.'))
                    c2.metric('Paletes recebidos',f"{r['recebimento_producao_paletes']:g}")
                    c3.metric('Abastecimento Picking',f"{r['abastecimento_picking_kg']:,.0f} kg".replace(',','.'))
                    c4.metric('Paletes abastecidos',f"{r['abastecimento_picking_paletes']:g}")
                    st.caption(f"Responsável: {r['responsavel']} • Absenteísmo: {r['absenteismo']:.1f}%")
                    if r['pendencias_proximo_turno']: st.warning(r['pendencias_proximo_turno'])
                else:
                    cargas_visao = r['veiculos_carregados'] if r['operacao']=='CDA 01 - Carregamento' else r['cargas_realizadas']
                    ton_visao = em_toneladas(r['toneladas_realizadas']) if r['operacao'] in ['CDA 01 - Separação','CDA 01 - Carregamento'] else em_toneladas(r['toneladas_estoque'])
                    c1,c2,c3,c4=st.columns(4)
                    c1.metric('Responsável',r['responsavel'])
                    c2.metric('Absenteísmo',f"{r['absenteismo']:.1f}%")
                    c3.metric('Cargas',f"{cargas_visao:g}")
                    c4.metric('Toneladas',f"{ton_visao:.1f} t")
                if r['observacoes']: st.write(r['observacoes'])

elif pagina=='🏢 Torre de Controle':
    st.header('🏢 Torre de Controle | ADIMAX')
    st.caption('Visão executiva integrada: CDA 01 Separação, CDA 01 Carregamento, CDA 02 e Estoque. A seleção da aba não restringe acesso.')
    hoje_torre=agora_operacional().date()
    ct1,ct2=st.columns(2)
    inicio_torre=ct1.date_input('Início do período',hoje_torre-timedelta(days=6),key='torre_inicio')
    fim_torre=ct2.date_input('Fim do período',hoje_torre,key='torre_fim')
    if inicio_torre>fim_torre:
        st.warning('A data inicial não pode ser posterior à final.')
        st.stop()
    # A Separação usa o T3 da véspera para compor o ciclo seguinte.
    base_torre=query('SELECT * FROM passagens WHERE excluido_em IS NULL AND data BETWEEN ? AND ? ORDER BY id',
                     (str(inicio_torre-timedelta(days=1)),str(fim_torre)))
    if base_torre.empty:
        st.info('Nenhuma passagem registrada neste período.')
    else:
        base_torre=base_torre.sort_values('id').groupby(['data','turno','operacao'],as_index=False).tail(1).copy()
        base_torre['Data_ciclo']=base_torre.apply(lambda r:data_ciclo_operacional(r['data'],r['turno'],r['operacao']),axis=1)
        base_torre=base_torre[(base_torre['Data_ciclo']>=inicio_torre)&(base_torre['Data_ciclo']<=fim_torre)].copy()
        if base_torre.empty:
            st.info('Nenhuma passagem pertence aos ciclos operacionais selecionados.')
        else:
            base_torre['Efetivo']=(pd.to_numeric(base_torre['headcount'],errors='coerce').fillna(0)
                -pd.to_numeric(base_torre['ferias'],errors='coerce').fillna(0)
                -pd.to_numeric(base_torre['afastamentos'],errors='coerce').fillna(0)
                -pd.to_numeric(base_torre['folgas'],errors='coerce').fillna(0)).clip(lower=0)
            base_torre['Ausencias_total']=(pd.to_numeric(base_torre['ausencias'],errors='coerce').fillna(0)
                +pd.to_numeric(base_torre['atestados'],errors='coerce').fillna(0))
            total_efetivo=base_torre['Efetivo'].sum()
            total_ausencias=base_torre['Ausencias_total'].sum()
            vagas_total=pd.to_numeric(base_torre['vagas_contratacao'],errors='coerce').fillna(0).sum() if 'vagas_contratacao' in base_torre else 0
            k1,k2,k3,k4=st.columns(4)
            k1.metric('Passagens recebidas',len(base_torre))
            k2.metric('Absenteísmo consolidado',f'{100*total_ausencias/total_efetivo:.2f}%'.replace('.',',') if total_efetivo else '—')
            k3.metric('Faltas + atestados',fmt_qtd(total_ausencias))
            k4.metric('Vagas informadas',fmt_qtd(vagas_total))
            st.caption('O absenteísmo usa a soma das ausências dividida pelo efetivo considerado. Vagas são somadas por passagem no período, não representam vagas únicas da empresa.')
            st.markdown('#### Resultados por operação')
            operacoes_torre=['CDA 01 - Separação','CDA 01 - Carregamento','CDA 02','Estoque']
            cards_torre=st.columns(2)
            for i,op_torre in enumerate(operacoes_torre):
                parte=base_torre[base_torre['operacao']==op_torre]
                with cards_torre[i%2]:
                    with st.container(border=True):
                        st.markdown('**'+op_torre+'**')
                        st.caption(f'{len(parte)} passagem(ns) no período')
                        if parte.empty:
                            st.info('Sem passagem registrada')
                        elif op_torre=='Estoque':
                            st.metric('Paletes recebidos da produção',fmt_qtd(parte['recebimento_producao_paletes'].sum()))
                            st.metric('Paletes abastecidos no picking',fmt_qtd(parte['abastecimento_picking_paletes'].sum()))
                        elif op_torre=='CDA 01 - Carregamento':
                            st.metric('Veículos carregados',fmt_qtd(parte['veiculos_carregados'].sum()))
                            st.metric('Volume informado',fmt_t(parte['toneladas_realizadas'].apply(em_toneladas).sum()))
                        else:
                            st.metric('Cargas separadas',fmt_qtd(parte['cargas_realizadas'].sum()))
                            if op_torre=='CDA 01 - Separação':
                                st.metric('Volume informado',fmt_t(parte['toneladas_realizadas'].apply(em_toneladas).sum()))
                            else:
                                st.metric('Paletes / UZs',fmt_qtd(parte['uz_paletes'].sum()))
            st.markdown('#### Absenteísmo por operação')
            por_area=base_torre.groupby('operacao',as_index=False).agg(Efetivo=('Efetivo','sum'),Ausencias=('Ausencias_total','sum'),Passagens=('id','count'))
            por_area['Absenteísmo (%)']=por_area.apply(lambda r:round(100*r['Ausencias']/r['Efetivo'],2) if r['Efetivo'] else None,axis=1)
            st.dataframe(por_area.rename(columns={'operacao':'Operação','Ausencias':'Faltas + atestados'}),hide_index=True,use_container_width=True)
            st.markdown('#### Comparativo de turnos')
            por_turno_torre=base_torre.groupby(['operacao','turno'],as_index=False).agg(Passagens=('id','count'),Efetivo=('Efetivo','sum'),Ausencias=('Ausencias_total','sum'))
            por_turno_torre['Turno']=por_turno_torre['turno'].apply(nome_turno)
            por_turno_torre['Absenteísmo (%)']=por_turno_torre.apply(lambda r:round(100*r['Ausencias']/r['Efetivo'],2) if r['Efetivo'] else None,axis=1)
            st.dataframe(por_turno_torre[['operacao','Turno','Passagens','Efetivo','Ausencias','Absenteísmo (%)']].rename(columns={'operacao':'Operação','Ausencias':'Faltas + atestados'}),hide_index=True,use_container_width=True)
            st.markdown('#### 👥 Gestão de Pessoas | Logística Geral')
            st.caption('Ranking nominal de faltas e atestados registrados pelos líderes. Uso gerencial restrito e sem classificação automática de desempenho.')
            areas_pessoas=sorted(base_torre['operacao'].dropna().unique().tolist())
            filtro_areas=st.multiselect('Operações para o ranking',areas_pessoas,default=areas_pessoas,key='torre_filtro_areas_pessoas')
            filtro_turnos=st.multiselect('Turnos para o ranking',['T1','T2','T3'],default=['T1','T2','T3'],format_func=nome_turno,key='torre_filtro_turnos_pessoas')
            dados_pessoas=base_torre[base_torre['operacao'].isin(filtro_areas)&base_torre['turno'].isin(filtro_turnos)].copy()
            if dados_pessoas.empty:
                st.info('Nenhuma passagem corresponde aos filtros de pessoas.')
            else:
                ids_pessoas=[int(x) for x in dados_pessoas['id'].dropna().tolist()]
                try:
                    marcadores_pessoas=','.join(['?']*len(ids_pessoas))
                    ocorrencias_pessoas=query(
                        'SELECT co.passagem_id,co.categoria,co.nome,p.data,p.turno,p.operacao,p.responsavel '
                        'FROM colaboradores_ocorrencias co JOIN passagens p ON p.id=co.passagem_id '
                        'WHERE p.excluido_em IS NULL AND co.passagem_id IN ('+marcadores_pessoas+') '
                        "AND co.categoria IN ('Faltas','Atestados')",
                        tuple(ids_pessoas))
                    if not ocorrencias_pessoas.empty:
                        ocorrencias_pessoas['Colaborador']=ocorrencias_pessoas['nome'].astype(str).str.strip().str.replace(r'\\s+',' ',regex=True).str.upper()
                        ocorrencias_pessoas=ocorrencias_pessoas[ocorrencias_pessoas['Colaborador']!=''].drop_duplicates(subset=['passagem_id','categoria','Colaborador'])
                        ocorrencias_pessoas['Data']=pd.to_datetime(ocorrencias_pessoas['data']).dt.strftime('%d/%m/%Y')
                        ocorrencias_pessoas['Turno']=ocorrencias_pessoas['turno'].apply(nome_turno)
                        ocorrencias_pessoas=ocorrencias_pessoas.rename(columns={'operacao':'Operação','categoria':'Ocorrência','responsavel':'Líder responsável'})
                    totais_esperados={
                        'Faltas':int(pd.to_numeric(dados_pessoas['ausencias'],errors='coerce').fillna(0).sum()),
                        'Atestados':int(pd.to_numeric(dados_pessoas['atestados'],errors='coerce').fillna(0).sum())
                    }
                    tabs_pessoas=st.tabs(['📉 Ranking de faltas','🩺 Ranking de atestados'])
                    for tab_pessoas,categoria_pessoas in zip(tabs_pessoas,['Faltas','Atestados']):
                        with tab_pessoas:
                            filtradas=ocorrencias_pessoas[ocorrencias_pessoas['Ocorrência']==categoria_pessoas].copy() if not ocorrencias_pessoas.empty else pd.DataFrame()
                            total_identificado=len(filtradas)
                            total_sem_nome=max(0,totais_esperados[categoria_pessoas]-total_identificado)
                            p1,p2,p3=st.columns(3)
                            p1.metric('Ocorrências informadas',totais_esperados[categoria_pessoas])
                            p2.metric('Com nome identificado',total_identificado)
                            p3.metric('Sem nome identificado',total_sem_nome)
                            if filtradas.empty:
                                st.info('Nenhum colaborador identificado nesta categoria e período.')
                            else:
                                ranking_pessoas=(filtradas.groupby('Colaborador',as_index=False)
                                    .agg(Ocorrências=('passagem_id','count'),
                                         Setor=('Operação',lambda x:', '.join(sorted(set(x.dropna().astype(str))))),
                                         Turno=('Turno',lambda x:', '.join(sorted(set(x.dropna().astype(str))))),
                                         Líderes=('Líder responsável',lambda x:', '.join(sorted(set(x.dropna().astype(str))))))
                                    .sort_values(['Ocorrências','Colaborador'],ascending=[False,True])
                                    .reset_index(drop=True))
                                ranking_pessoas.insert(0,'Posição',range(1,len(ranking_pessoas)+1))
                                ranking_pessoas=ranking_pessoas[['Posição','Colaborador','Setor','Turno','Ocorrências','Líderes']]
                                st.dataframe(ranking_pessoas,hide_index=True,use_container_width=True)
                                st.caption('Setor e turno correspondem às passagens onde houve registro; não necessariamente à lotação oficial do colaborador.')
                                st.markdown('##### Histórico nominal')
                                st.dataframe(filtradas[['Data','Turno','Operação','Colaborador','Líder responsável']].sort_values('Data',ascending=False),
                                             hide_index=True,use_container_width=True)
                            if total_sem_nome:
                                st.warning('Parte dos registros não possui nome informado. O ranking nominal é parcial.')
                    st.caption('Uma ocorrência por colaborador, categoria e passagem. Grafias diferentes podem gerar entradas distintas; atestados não indicam, por si, irregularidade.')
                except Exception:
                    st.info('Os registros nominais ainda não estão disponíveis para consulta. Os totais de ausências permanecem inalterados.')
            st.markdown('#### Atenção operacional')
            pendentes_torre=base_torre[base_torre['status'].astype(str).str.contains('Atenção|Crítico|Critico',case=False,na=False)]
            if pendentes_torre.empty:
                st.success('Nenhuma passagem sinalizada com status de atenção ou crítico no período.')
            else:
                st.warning(f'{len(pendentes_torre)} passagem(ns) com status de atenção ou crítico.')
                avisos=pendentes_torre[['Data_ciclo','operacao','turno','status','ofensor']].copy()
                avisos['Data_ciclo']=avisos['Data_ciclo'].astype(str)
                avisos['turno']=avisos['turno'].apply(nome_turno)
                st.dataframe(avisos.rename(columns={'Data_ciclo':'Data do ciclo','operacao':'Operação','turno':'Turno','status':'Status','ofensor':'Ofensor'}),hide_index=True,use_container_width=True)
            st.caption('A ausência de um registro não significa produção zero. A Torre utiliza apenas passagens efetivamente registradas.')

elif pagina=='👔 Visão do Supervisor':
    st.header('👔 Visão do Supervisor')
    st.caption('Acompanhe somente as informações da sua operação. A seleção do nome é um filtro de visualização, não uma autenticação.')
    supervisores={
        'ANDRE FORTUNATO':'CDA 01 - Separação',
        'MARCIO HENRIQUE SCHAFFER':'CDA 01 - Carregamento',
        'FRANCISCO FERREIRA CARNEIRO JUNIOR':'CDA 02',
        'WAGNER LUIZ GALONE SANCHES FILHO':'Estoque',
    }
    supervisor=st.selectbox('Selecione o supervisor',list(supervisores),index=None,placeholder='Escolha seu nome')
    if not supervisor:
        st.info('Selecione seu nome para visualizar os indicadores da área.')
        st.stop()
    op=supervisores[supervisor]
    st.info('Área sob responsabilidade: '+op)
    hoje=agora_operacional().date()
    ini=hoje-timedelta(days=6)
    c1,c2=st.columns(2)
    di=c1.date_input('Data inicial',ini,key='sup_ini')
    dfim=c2.date_input('Data final',hoje,key='sup_fim')
    if di>dfim:
        st.warning('A data inicial deve ser anterior ou igual à data final.')
        st.stop()
    turnos_disponiveis=['T1','T2','T3'] if op!='Estoque' else ['2X2 1A','2X2 1B','2X2 2A','2X2 2B']
    turno_filtro=st.selectbox('Filtrar turno',['Todos os turnos']+turnos_disponiveis,format_func=lambda x: nome_turno(x) if x!='Todos os turnos' else x,key='sup_turno')
    if turno_filtro=='Todos os turnos':
        dados=query('SELECT * FROM passagens WHERE excluido_em IS NULL AND operacao=? AND data BETWEEN ? AND ? ORDER BY id DESC',(op,str(di-timedelta(days=1)) if op=='CDA 01 - Separação' else str(di),str(dfim)))
    else:
        dados=query('SELECT * FROM passagens WHERE excluido_em IS NULL AND operacao=? AND data BETWEEN ? AND ? AND turno=? ORDER BY id DESC',(op,str(di-timedelta(days=1)) if op=='CDA 01 - Separação' and turno_filtro=='T3' else str(di),str(dfim),turno_filtro))
    if op!='Estoque' and not dados.empty:
        dados['Data_ciclo']=dados.apply(lambda r:data_ciclo_operacional(r['data'],r['turno'],r['operacao']),axis=1)
        dados=dados[(dados['Data_ciclo']>=di)&(dados['Data_ciclo']<=dfim)].copy()
        st.caption('Separação CDA 01: T3 da véspera + T1 + T2. Carregamento CDA 01 e CDA 02: T1 + T2 + T3 da data. Estoque: 2x2.')
    if op=='CDA 02':
        st.markdown('#### 🚛 Transbordos — Recebimento e Carregamento')
        st.caption('Dados consultados diretamente do aplicativo de Transbordos, respeitando data e turno. Independem do preenchimento da passagem.')
        periodo=(dfim-di).days+1
        if periodo>31:
            st.info('Para consultar os transbordos, selecione um período de até 31 dias.')
        else:
            receb_v=receb_p=carreg_v=carreg_p=0
            erros_consulta=0
            detalhe_fluxo=[]
            viagens_detalhadas=[]
            turnos_api=['T1','T2','T3'] if turno_filtro=='Todos os turnos' else [turno_filtro]
            for dia in pd.date_range(di,dfim):
                for turno_api in turnos_api:
                    try:
                        fluxo=consultar_fluxo_transbordos(dia.date().isoformat(),turno_api)
                        viagens_detalhadas.extend(fluxo['detalhes'])
                        r=fluxo['Recebimento']
                        c=fluxo['Carregamento']
                        receb_v+=r['viagens']; receb_p+=r['paletes']
                        carreg_v+=c['viagens']; carreg_p+=c['paletes']
                        detalhe_fluxo.append({'Data':dia.date(),'Turno':nome_turno(turno_api),'Viagens recebidas':r['viagens'],'Paletes recebidos':r['paletes'],'Viagens carregadas':c['viagens'],'Paletes carregados':c['paletes']})
                    except Exception:
                        erros_consulta+=1
            if erros_consulta:
                st.warning(f'Não foi possível consultar {erros_consulta} combinação(ões) de data e turno no aplicativo de Transbordos. Os totais abaixo são parciais.')
            if detalhe_fluxo:
                st.markdown('##### 📦 Paletes movimentados por setor')
                setores_resumo=['Ensaque','Úmidos','Biscoito','Expedição','Estoque','Fornecedores','Outros']
                totais_setor={nome:0 for nome in setores_resumo}
                import unicodedata
                for viagem in viagens_detalhadas:
                    setor_bruto=viagem['Origem'] if viagem['Movimentação']=='Recebimento' else viagem['Destino']
                    nome=unicodedata.normalize('NFKD',str(setor_bruto)).encode('ascii','ignore').decode().lower()
                    setor=('Ensaque' if 'ensaque' in nome else 'Úmidos' if 'umido' in nome else 'Biscoito' if 'biscoito' in nome else 'Expedição' if any(x in nome for x in ('expedi','cda01','cda 01')) else 'Estoque' if 'estoque' in nome else 'Fornecedores' if 'fornecedor' in nome else 'Outros')
                    totais_setor[setor]+=viagem['Paletes']
                cols_setor=st.columns(4)
                for i,nome in enumerate(setores_resumo):
                    cols_setor[i%4].metric(nome,f"{totais_setor[nome]} paletes")
                st.success(f"{receb_v+carreg_v} movimentações consultadas. Total: {receb_p+carreg_p} paletes.")
                st.caption('Resumo consolidado de recebimentos e carregamentos, sem duplicar viagens.')
                a,b,c,d=st.columns(4)
                a.metric('Viagens recebidas',receb_v)
                b.metric('Paletes recebidos',receb_p)
                c.metric('Viagens carregadas',carreg_v)
                d.metric('Paletes carregados',carreg_p)
                st.markdown('##### 🚛 Para onde foram os transbordos?')
                st.caption('Em Recebimento, o setor informado é a origem; em Carregamento, é o destino. Cada linha representa uma viagem registrada.')
                if viagens_detalhadas:
                    st.dataframe(pd.DataFrame(viagens_detalhadas),use_container_width=True,hide_index=True)
                else:
                    st.info('Nenhuma viagem detalhada encontrada no período.')
                with st.expander('Resumo por data e turno'):
                    st.dataframe(pd.DataFrame(detalhe_fluxo),use_container_width=True,hide_index=True)
            elif not erros_consulta:
                st.info('Sem movimentos de recebimento ou carregamento no período.')
    if op=='CDA 02' and not dados.empty:
        st.markdown('#### 🏁 Placar entre pisos — CDA 01 × CDA 02')
        st.caption('Convenção: saldo positivo indica CDA 01 à frente; saldo negativo indica CDA 02 à frente. É um saldo informado no fechamento, não a quantidade produzida em cada piso.')
        dif_pisos=dados.sort_values('id').groupby(['data','turno','operacao'],as_index=False).tail(1).copy()
        dif_pisos['Diferença']=pd.to_numeric(dif_pisos['diferencas_entre_pisos'],errors='coerce')
        dif_pisos=dif_pisos.dropna(subset=['Diferença']).copy()
        if dif_pisos.empty:
            st.info('Ainda não há diferenças entre pisos informadas.')
        else:
            dif_pisos['Data']=pd.to_datetime(dif_pisos['data'])
            ordem_turnos={'T1':0,'T2':1,'T3':2}
            dif_pisos['ordem']=dif_pisos['turno'].map(ordem_turnos).fillna(9)
            dif_pisos=dif_pisos.sort_values(['Data','ordem','id'])
            ultimo=dif_pisos.iloc[-1]
            saldo=int(ultimo['Diferença'])
            lider='CDA 01' if saldo>0 else 'CDA 02' if saldo<0 else 'Empate'
            c1,c2,c3=st.columns(3)
            c1.metric('Último saldo registrado',f'{saldo:+d} cargas')
            c2.metric('Quem está à frente',lider)
            c3.metric('Vantagem',f'{abs(saldo)} cargas')
            st.caption(f"Última passagem considerada: {ultimo['Data'].strftime('%d/%m/%Y')} — {nome_turno(ultimo['turno'])}. O saldo não é somado entre turnos, pois representa uma posição no fechamento.")
            dif_pisos['À frente']=dif_pisos['Diferença'].apply(lambda v:'CDA 01' if v>0 else 'CDA 02' if v<0 else 'Empate')
            dif_pisos['Vantagem (cargas)']=dif_pisos['Diferença'].abs().astype(int)
            dif_pisos['Data / Turno']=dif_pisos['Data'].dt.strftime('%d/%m/%Y')+' • '+dif_pisos['turno'].map(nome_turno)
            st.markdown('##### Evolução dos saldos por passagem')
            st.line_chart(dif_pisos.set_index('Data / Turno')['Diferença'],y_label='Saldo informado (cargas)')
            st.markdown('##### Quem terminou cada turno à frente')
            st.dataframe(dif_pisos[['Data / Turno','Diferença','À frente','Vantagem (cargas)']].rename(columns={'Diferença':'Saldo (+ CDA 01 / − CDA 02)'}),hide_index=True,use_container_width=True)
            st.caption('Para períodos com vários dias, cada ponto mostra o fechamento de um turno; não somamos os saldos para evitar contar a mesma diferença repetidamente.')
    if dados.empty:
        st.info('Não há passagens registradas para esta área no período selecionado.')
    else:
        # Uma versão por data/turno, evitando somar reenvios da mesma passagem.
        dados=dados.sort_values('id').groupby(['data','turno','operacao'],as_index=False).tail(1).copy()
        dados['Volume_t']=dados['toneladas_realizadas'].apply(em_toneladas) if op!='Estoque' else dados['toneladas_estoque'].apply(em_toneladas)
        dados['Movimentos']=dados['veiculos_carregados'] if op=='CDA 01 - Carregamento' else dados['cargas_realizadas']
        total_hc=float((dados['headcount']-dados['ferias']-dados['afastamentos']-dados['folgas']).clip(lower=0).sum())
        total_aus=float((dados['ausencias']+dados['atestados']).sum())
        a,b,c,d=st.columns(4)
        a.metric('Passagens registradas',len(dados))
        if op=='Estoque':
            b.metric('Paletes recebidos',f"{dados['recebimento_producao_paletes'].sum():g}")
            c.metric('Paletes abastecidos',f"{dados['abastecimento_picking_paletes'].sum():g}")
        else:
            b.metric('Veículos carregados' if op=='CDA 01 - Carregamento' else 'Cargas',f"{dados['Movimentos'].sum():g}")
            c.metric('Toneladas',fmt_t(dados['Volume_t'].sum()))
        d.metric('Absenteísmo',f'{total_aus/total_hc*100:.1f}%' if total_hc else '—')
        st.markdown('#### 👥 Efetivo e absenteísmo')
        total_previsto=int(dados['headcount'].sum())
        total_ferias=int(dados['ferias'].sum())
        total_afast=int(dados['afastamentos'].sum())
        total_faltas=int((dados['ausencias']+dados['atestados']).sum())
        total_presentes=max(0,int(total_hc)-total_faltas)
        e1,e2,e3=st.columns(3)
        e1.metric('Headcount previsto',total_previsto)
        e2.metric('Férias',total_ferias)
        e3.metric('Afastamentos',total_afast)
        st.caption(f"Folgas programadas: {int(dados['folgas'].sum())} | Atestados: {int(dados['atestados'].sum())}")
        e4,e5,e6=st.columns(3)
        e4.metric('Efetivo considerado',int(total_hc))
        e5.metric('Faltas + atestados',total_faltas)
        e6.metric('Presentes',total_presentes)
        st.caption('Absenteísmo = (faltas + atestados) ÷ (headcount previsto − férias − afastamentos − folgas). Vagas abertas são acompanhadas separadamente.')
        equipe_detalhe=dados[['data','turno','responsavel','headcount','ferias','afastamentos','folgas','atestados','ausencias']].copy()
        equipe_detalhe['Efetivo considerado']=(equipe_detalhe['headcount']-equipe_detalhe['ferias']-equipe_detalhe['afastamentos']-equipe_detalhe['folgas']).clip(lower=0)
        equipe_detalhe['Presentes']=(equipe_detalhe['Efetivo considerado']-equipe_detalhe['ausencias']-equipe_detalhe['atestados']).clip(lower=0)
        equipe_detalhe['Absenteísmo (%)']=equipe_detalhe.apply(lambda r: round(100*(r['ausencias']+r['atestados'])/r['Efetivo considerado'],1) if r['Efetivo considerado'] else 0,axis=1)
        equipe_detalhe['turno']=equipe_detalhe['turno'].apply(nome_turno)
        st.dataframe(equipe_detalhe.rename(columns={'data':'Data','turno':'Turno','responsavel':'Líder','headcount':'Headcount previsto','ferias':'Férias','afastamentos':'Afastamentos','folgas':'Folgas','atestados':'Atestados','ausencias':'Faltas'}),hide_index=True,use_container_width=True)
        st.markdown('#### 📋 Quem faltou no turno')
        st.caption('Nomes informados pelos líderes nas passagens selecionadas. Ranking somente de faltas não programadas; atestados, férias, afastamentos e folgas ficam fora.')
        ids_passagens=[int(v) for v in dados['id'].dropna().tolist()]
        if ids_passagens:
            try:
                marcadores=','.join(['?']*len(ids_passagens))
                faltas_nomes=query(
                    'SELECT co.passagem_id,co.categoria,co.nome,p.data,p.turno,p.operacao '
                    'FROM colaboradores_ocorrencias co JOIN passagens p ON p.id=co.passagem_id '
                    'WHERE p.excluido_em IS NULL AND co.passagem_id IN ('+marcadores+') '
                    "AND co.categoria='Faltas' ORDER BY p.data DESC,p.id DESC",
                    tuple(ids_passagens))
                if faltas_nomes.empty:
                    st.info('Nenhum nome de colaborador faltante foi registrado nas passagens deste período.')
                else:
                    faltas_nomes['Nome']=faltas_nomes['nome'].astype(str).str.strip().str.replace(r'\\s+',' ',regex=True).str.upper()
                    faltas_nomes=faltas_nomes[faltas_nomes['Nome']!=''].drop_duplicates(subset=['passagem_id','Nome']).copy()
                    faltas_nomes['Data operacional']=pd.to_datetime(faltas_nomes['data']).dt.strftime('%d/%m/%Y')
                    faltas_nomes['Turno']=faltas_nomes['turno'].apply(nome_turno)
                    if faltas_nomes.empty:
                        st.info('Não há nomes preenchidos nas faltas do período.')
                    else:
                        ranking=(faltas_nomes.groupby('Nome',as_index=False)
                                 .agg(Faltas=('passagem_id','count'),Turnos=('Turno',lambda x:', '.join(sorted(set(x)))))
                                 .sort_values(['Faltas','Nome'],ascending=[False,True]).reset_index(drop=True))
                        ranking.insert(0,'Posição',range(1,len(ranking)+1))
                        r1,r2,r3=st.columns(3)
                        r1.metric('Faltas com nome',len(faltas_nomes))
                        r2.metric('Colaboradores identificados',len(ranking))
                        r3.metric('Maior recorrência',int(ranking['Faltas'].max()))
                        st.markdown('##### Ranking de faltas no período')
                        st.dataframe(ranking,hide_index=True,use_container_width=True)
                        st.markdown('##### Datas e turnos das faltas')
                        st.dataframe(faltas_nomes[['Data operacional','Turno','Nome']].rename(columns={'Nome':'Colaborador'}),hide_index=True,use_container_width=True)
                faltas_declaradas=int(pd.to_numeric(dados['ausencias'],errors='coerce').fillna(0).sum())
                faltas_identificadas=len(faltas_nomes) if not faltas_nomes.empty else 0
                if faltas_declaradas>faltas_identificadas:
                    st.warning(f'Existem {faltas_declaradas-faltas_identificadas} falta(s) informada(s) sem nome identificado neste período. O ranking não inclui essas faltas.')
                st.caption('O ranking conta uma falta por colaborador e passagem. Variações na grafia do nome podem aparecer como pessoas diferentes. Os dados são de uso interno.')
            except Exception:
                st.info('A consulta de nomes ainda não está disponível para estes registros. Os totais de absenteísmo permanecem preservados.')
        st.markdown('#### Detalhamento da operação')
        if op=='CDA 01 - Separação':
            a,b,c,d=st.columns(4)
            a.metric('Cargas de vendas',f"{dados['varejo_cargas'].sum():g}")
            b.metric('Toneladas de vendas',fmt_t(sum(em_toneladas(v) for v in dados['varejo_ton'])))
            c.metric('Transferências',f"{dados['transferencias_qtd'].sum():g}")
            d.metric('Toneladas transferidas',fmt_t(sum(em_toneladas(v) for v in dados['transferencias_ton'])))
            st.markdown('##### ⏳ Pendências de Separação')
            if 'cargas_aguardando_caixas_cda02' in dados.columns and 'cargas_em_pd' in dados.columns:
                p1,p2=st.columns(2)
                p1.metric('Aguardando caixas CDA 02',fmt_qtd(dados['cargas_aguardando_caixas_cda02'].sum()))
                p2.metric('Cargas em P&D',fmt_qtd(dados['cargas_em_pd'].sum()))
        elif op=='CDA 01 - Carregamento':
            a,b,c=st.columns(3)
            a.metric('Veículos carregados',f"{dados['veiculos_carregados'].sum():g}")
            b.metric('Toneladas carregadas',fmt_t(dados['Volume_t'].sum()))
            c.metric('Veículos pendentes',f"{dados['veiculos_pendentes'].sum():g}")
        elif op=='CDA 02':
            a,b,c,d=st.columns(4)
            a.metric('Cargas separadas',f"{dados['cargas_realizadas'].sum():g}")
            b.metric('Paletes / UZs',f"{dados['uz_paletes'].sum():g}")
            c.metric('Transbordos (paletes)',f"{dados['transbordo_total'].sum():g}")
            d.metric('P&D em espera',f"{dados['pd_espera'].sum():g}")
            st.markdown('##### Conferência de cargas e UZs')
            tc=dados['conf_total_cargas'].sum()
            cc=dados['conf_cargas_conferidas'].sum()
            tu=dados['conf_total_uzs'].sum()
            uc=dados['conf_uzs_conferidas'].sum()
            a,b,c,d=st.columns(4)
            a.metric('Cargas conferidas',f'{cc:g} / {tc:g}')
            b.metric('% cargas conferidas',f'{pct(cc,tc):.1f}%' if tc else '—')
            c.metric('UZs conferidas',f'{uc:g} / {tu:g}')
            d.metric('% UZs conferidas',f'{pct(uc,tu):.1f}%' if tu else '—')
            st.metric('Erros de conferência',f"{dados['conf_erros'].sum():g}")
            conferencias=dados.groupby('turno',as_index=False)[['conf_total_cargas','conf_cargas_conferidas','conf_total_uzs','conf_uzs_conferidas','conf_erros']].sum()
            conferencias['% Cargas']=conferencias.apply(lambda r: round(pct(r['conf_cargas_conferidas'],r['conf_total_cargas']),1) if r['conf_total_cargas'] else None,axis=1)
            conferencias['% UZs']=conferencias.apply(lambda r: round(pct(r['conf_uzs_conferidas'],r['conf_total_uzs']),1) if r['conf_total_uzs'] else None,axis=1)
            conferencias['Turno']=conferencias['turno'].apply(nome_turno)
            st.dataframe(conferencias[['Turno','conf_cargas_conferidas','conf_uzs_conferidas','% Cargas','% UZs','conf_erros']].rename(columns={'conf_cargas_conferidas':'Cargas conferidas','conf_uzs_conferidas':'UZs conferidas','conf_erros':'Erros'}),hide_index=True,use_container_width=True)
        elif op=='Estoque':
            a,b,c,d=st.columns(4)
            a.metric('Recebimento da produção',f"{dados['recebimento_producao_kg'].sum():,.0f} kg".replace(',','.'))
            b.metric('Abastecimento picking',f"{dados['abastecimento_picking_kg'].sum():,.0f} kg".replace(',','.'))
            c.metric('Carretas descarregadas',f"{dados['carretas_descarregadas'].sum():g}")
            d.metric('Carretas aguardando',f"{dados['carretas_aguardando'].sum():g}")
            a,b=st.columns(2)
            a.metric('Carretas armazenadas',f"{dados['carretas_armazenadas'].sum():g}")
            b.metric('Transbordos CDA 02',f"{dados['transbordos_cda02'].sum():g}")
        st.markdown('#### 👥 Vagas para contratação')
        st.caption('Vagas abertas informadas pelos líderes. Não são somadas ao absenteísmo. Registros anteriores à implantação podem não ter informação.')
        vagas_base=dados.dropna(subset=['vagas_contratacao']).copy()
        if vagas_base.empty:
            st.info('Nenhuma vaga para contratação informada nas passagens do período.')
        else:
            vagas_turno=vagas_base.groupby('turno',as_index=False)['vagas_contratacao'].max()
            vagas_turno['Turno']=vagas_turno['turno'].apply(nome_turno)
            st.dataframe(vagas_turno[['Turno','vagas_contratacao']].rename(columns={'vagas_contratacao':'Vagas abertas (último valor máximo no período)'}),hide_index=True,use_container_width=True)
            st.caption('Não somar vagas de dias diferentes: a mesma vaga pode permanecer aberta. Para uma visão diária, filtre uma única data.')
        st.markdown('#### Evolução da área')
        if op=='Estoque':
            evol=dados.groupby('data',as_index=True)[['recebimento_producao_paletes','abastecimento_picking_paletes']].sum()
            st.line_chart(evol)
        else:
            evol=dados.groupby('data',as_index=True)[['Volume_t','Movimentos']].sum()
            st.line_chart(evol)
        st.markdown('#### Resultado por turno')
        if op=='Estoque':
            st.caption('No Estoque, recebimento da produção e abastecimento do picking são volumes diferentes. Valores em toneladas calculados a partir dos kg registrados.')
            est_turnos=dados.groupby('turno',as_index=False).agg(Passagens=('id','count'),Recebimento_kg=('recebimento_producao_kg','sum'),Abastecimento_kg=('abastecimento_picking_kg','sum'),Paletes_recebidos=('recebimento_producao_paletes','sum'),Paletes_abastecidos=('abastecimento_picking_paletes','sum'))
            est_turnos['Turno']=est_turnos['turno'].apply(nome_turno)
            est_turnos['Produção recebida (t)']=(est_turnos['Recebimento_kg']/1000).round(3)
            est_turnos['Picking abastecido (t)']=(est_turnos['Abastecimento_kg']/1000).round(3)
            st.dataframe(est_turnos[['Turno','Passagens','Produção recebida (t)','Paletes_recebidos','Picking abastecido (t)','Paletes_abastecidos']].rename(columns={'Paletes_recebidos':'Paletes recebidos','Paletes_abastecidos':'Paletes abastecidos'}),hide_index=True,use_container_width=True)
            st.warning('Lançamentos antigos com unidade incorreta precisam de correção individual após conferência. O painel não converte automaticamente registros históricos suspeitos.')
        else:
            dados['Efetivo_abs']=(dados['headcount']-dados['ferias']-dados['afastamentos']-dados['folgas']).clip(lower=0)
            por_turno=dados.groupby('turno',as_index=False).agg(Passagens=('id','count'),Movimentos=('Movimentos','sum'),Toneladas=('Volume_t','sum'),Ausencias=('ausencias','sum'),Atestados=('atestados','sum'),Headcount=('Efetivo_abs','sum'))
            por_turno['Turno']=por_turno['turno'].apply(nome_turno)
            por_turno['Absenteísmo (%)']=por_turno.apply(lambda r: round((r['Ausencias']+r['Atestados'])/r['Headcount']*100,1) if r['Headcount'] else 0,axis=1)
            st.dataframe(por_turno[['Turno','Passagens','Movimentos','Toneladas','Absenteísmo (%)']],hide_index=True,use_container_width=True)
        st.markdown('#### Ofensores e observações')
        ocorrencias=dados[(dados['ofensor'].fillna('Sem ofensor')!='Sem ofensor') | (dados['observacoes'].fillna('').str.strip()!='')].copy()
        if ocorrencias.empty:
            st.success('Nenhum ofensor ou observação registrado no período.')
        else:
            for _,oc in ocorrencias.sort_values('id',ascending=False).iterrows():
                titulo=f"{oc['data']} • {nome_turno(oc['turno'])} • {oc['ofensor'] or 'Observação'}"
                with st.expander(titulo,expanded=False):
                    st.write(f"**Líder:** {oc['responsavel']}  |  **Status:** {oc['status']}")
                    if pd.notna(oc['observacoes']) and str(oc['observacoes']).strip():
                        st.markdown('**Observações / detalhes:**')
                        st.text_area('Registro completo',value=str(oc['observacoes']),height=180,disabled=True,key=f"sup_obs_{oc['id']}",label_visibility='collapsed')
                    else:
                        st.caption('Sem observações adicionais.')
        if op!='Estoque':
            st.markdown('#### 📅 Consolidado por ciclo operacional')
            ciclo=dados.copy()
            ciclo['Data do ciclo']=ciclo.apply(lambda r:data_ciclo_operacional(r['data'],r['turno'],r['operacao']),axis=1)
            ordem_turnos={'T1':0,'T2':1,'T3':2} if op=='CDA 01 - Carregamento' else {'T3':0,'T1':1,'T2':2}
            ciclo['Ordem']=ciclo['turno'].map(ordem_turnos).fillna(3)
            st.dataframe(ciclo.sort_values(['Data do ciclo','Ordem'])[['Data do ciclo','turno','data','responsavel','Movimentos','Volume_t']].rename(columns={'turno':'Turno','data':'Data da passagem','responsavel':'Líder','Movimentos':'Movimentos','Volume_t':'Toneladas'}),hide_index=True,use_container_width=True)
            ciclo_resumo=ciclo.groupby('Data do ciclo',as_index=False).agg(Movimentos=('Movimentos','sum'),Toneladas=('Volume_t','sum'))
            st.dataframe(ciclo_resumo,hide_index=True,use_container_width=True)
        st.markdown('#### Últimas passagens')
        ultimas=dados.sort_values('id',ascending=False)[['data','turno','responsavel','status','absenteismo']].copy()
        ultimas['absenteismo']=pd.to_numeric(ultimas['absenteismo'],errors='coerce').apply(lambda v: f'{v:.2f}%'.replace('.',',') if pd.notna(v) else '—')
        ultimas['data']=pd.to_datetime(ultimas['data']).dt.strftime('%d/%m/%Y')
        st.dataframe(ultimas.rename(columns={'data':'Data','turno':'Turno','responsavel':'Líder','status':'Status','absenteismo':'Absenteísmo'}),hide_index=True,use_container_width=True)

elif pagina=='📊 Semana':
    st.header('📊 Relatório Semanal | Logística')
    st.caption('Resumo executivo da semana para a coordenação. Indicadores por operação, sem misturar unidades.')
    hoje=agora_operacional().date()
    ini=hoje-timedelta(days=hoje.weekday())
    fim=ini+timedelta(days=6)
    a,b=st.columns(2)
    di=a.date_input('Início',ini,key='semana_inicio')
    dfim=b.date_input('Fim',fim,key='semana_fim')
    if di>dfim:
        st.warning('A data inicial deve ser anterior ou igual à final.')
        st.stop()
    df=query('SELECT * FROM passagens WHERE excluido_em IS NULL AND data BETWEEN ? AND ? ORDER BY id',
             (str(di-timedelta(days=1)),str(dfim)))
    if not df.empty:
        df=df.sort_values('id').groupby(['data','turno','operacao'],as_index=False).tail(1).copy()
        df['Data_ciclo']=df.apply(lambda r:data_ciclo_operacional(r['data'],r['turno'],r['operacao']),axis=1)
        df=df[(df['Data_ciclo']>=di)&(df['Data_ciclo']<=dfim)].copy()
    st.caption('Separação CDA 01: T3 da véspera + T1 + T2. Carregamento CDA 01: T1 + T2 + T3. CDA 02: data do registro. Estoque: escala 2x2.')
    if df.empty:
        st.info('Não há passagens registradas nos ciclos selecionados.')
    else:
        df['Efetivo_abs']=(pd.to_numeric(df['headcount'],errors='coerce').fillna(0)
            -pd.to_numeric(df['ferias'],errors='coerce').fillna(0)
            -pd.to_numeric(df['afastamentos'],errors='coerce').fillna(0)
            -pd.to_numeric(df['folgas'],errors='coerce').fillna(0)).clip(lower=0)
        df['Ausencias_abs']=(pd.to_numeric(df['ausencias'],errors='coerce').fillna(0)
            +pd.to_numeric(df['atestados'],errors='coerce').fillna(0))
        efetivo=df['Efetivo_abs'].sum()
        ausencias=df['Ausencias_abs'].sum()
        w1,w2,w3,w4=st.columns(4)
        w1.metric('Passagens registradas',fmt_qtd(len(df)))
        w2.metric('Faltas',fmt_qtd(df['ausencias'].sum()))
        w3.metric('Atestados',fmt_qtd(df['atestados'].sum()))
        w4.metric('Absenteísmo',f'{100*ausencias/efetivo:.2f}%'.replace('.',',') if efetivo else '—')
        st.caption('Absenteísmo = (faltas + atestados) ÷ efetivo considerado. Os números representam passagens registradas, não uma lista completa de turnos previstos.')
        st.markdown('#### 📦 Resultado por operação')
        operacoes_semana=['CDA 01 - Separação','CDA 01 - Carregamento','CDA 02','Estoque']
        for operacao_semana in operacoes_semana:
            parte=df[df['operacao']==operacao_semana].copy()
            with st.expander(f'{operacao_semana} — {len(parte)} passagem(ns)',expanded=not parte.empty):
                if parte.empty:
                    st.info('Sem lançamentos no período.')
                    continue
                if operacao_semana=='Estoque':
                    x,y,z=st.columns(3)
                    x.metric('Produção recebida',fmt_t(parte['recebimento_producao_kg'].sum()/1000))
                    y.metric('Picking abastecido',fmt_t(parte['abastecimento_picking_kg'].sum()/1000))
                    z.metric('Paletes recebidos',fmt_qtd(parte['recebimento_producao_paletes'].sum()))
                    evol=parte.groupby('Data_ciclo')[['recebimento_producao_kg','abastecimento_picking_kg']].sum()/1000
                    evol=evol.rename(columns={'recebimento_producao_kg':'Produção recebida (t)','abastecimento_picking_kg':'Picking abastecido (t)'})
                    st.line_chart(evol)
                    st.caption('Dados em toneladas convertidos dos kg registrados; pesos históricos incorretos não são ajustados automaticamente.')
                elif operacao_semana=='CDA 01 - Carregamento':
                    x,y=st.columns(2)
                    x.metric('Veículos carregados',fmt_qtd(parte['veiculos_carregados'].sum()))
                    y.metric('Toneladas informadas',fmt_t(parte['toneladas_realizadas'].apply(em_toneladas).sum()))
                    st.bar_chart(parte.groupby('Data_ciclo')['veiculos_carregados'].sum(),y_label='Veículos carregados')
                else:
                    x,y=st.columns(2)
                    x.metric('Cargas separadas',fmt_qtd(parte['cargas_realizadas'].sum()))
                    if operacao_semana=='CDA 01 - Separação':
                        y.metric('Toneladas informadas',fmt_t(parte['toneladas_realizadas'].apply(em_toneladas).sum()))
                    else:
                        y.metric('Paletes / UZs',fmt_qtd(parte['uz_paletes'].sum()))
                    st.bar_chart(parte.groupby('Data_ciclo')['cargas_realizadas'].sum(),y_label='Cargas separadas')
                st.markdown('**Comparativo dos turnos**')
                turnos=parte.groupby('turno',as_index=False).agg(Passagens=('id','count'),Efetivo=('Efetivo_abs','sum'),Ausencias=('Ausencias_abs','sum'))
                turnos['Turno']=turnos['turno'].apply(nome_turno)
                turnos['Absenteísmo (%)']=turnos.apply(lambda r:round(100*r['Ausencias']/r['Efetivo'],2) if r['Efetivo'] else None,axis=1)
                st.dataframe(turnos[['Turno','Passagens','Efetivo','Ausencias','Absenteísmo (%)']].rename(columns={'Ausencias':'Faltas + atestados'}),hide_index=True,use_container_width=True)
        st.markdown('#### 👥 Pessoas e quadro')
        quadro=df.groupby('operacao',as_index=False).agg(Passagens=('id','count'),Efetivo=('Efetivo_abs','sum'),Faltas=('ausencias','sum'),Atestados=('atestados','sum'))
        quadro['Absenteísmo (%)']=quadro.apply(lambda r:round(100*(r['Faltas']+r['Atestados'])/r['Efetivo'],2) if r['Efetivo'] else None,axis=1)
        st.dataframe(quadro.rename(columns={'operacao':'Operação'}),hide_index=True,use_container_width=True)
        if 'vagas_contratacao' in df.columns:
            vagas=df.sort_values('id').groupby(['operacao','turno'],as_index=False).tail(1)
            st.markdown('##### Últimas vagas informadas por operação e turno')
            st.dataframe(vagas[['operacao','turno','vagas_contratacao']].rename(columns={'operacao':'Operação','turno':'Turno','vagas_contratacao':'Vagas abertas'}),hide_index=True,use_container_width=True)
            st.caption('Vagas não são somadas entre dias: exibimos o último valor informado por operação e turno.')
        st.markdown('#### ⚠️ Ocorrências que exigem atenção')
        atencao=df[df['status'].astype(str).str.contains('Atenção|Crítico|Critico',case=False,na=False)]
        if atencao.empty:
            st.success('Nenhuma passagem com status de atenção ou crítico neste período.')
        else:
            st.dataframe(atencao[['Data_ciclo','operacao','turno','status','ofensor']].rename(columns={'Data_ciclo':'Data do ciclo','operacao':'Operação','turno':'Turno','status':'Status','ofensor':'Ofensor'}),hide_index=True,use_container_width=True)
        st.caption('Passagens ausentes não são interpretadas como zero. Os resultados dependem dos dados informados pelos líderes.')

elif pagina=='🕘 Histórico':
    st.header('🕘 Histórico')
    if 'historico_salvo' in st.session_state:
        st.success(st.session_state.pop('historico_salvo'))
    df=query('SELECT id,data,turno,operacao,responsavel,status,cargas_realizadas,toneladas_realizadas,veiculos_carregados,veiculos_pendentes,absenteismo,ofensor,observacoes,criado_em FROM passagens WHERE excluido_em IS NULL ORDER BY id DESC')
    if df.empty: st.info('Sem registros.')
    else:
        df_exibir=df.copy()
        df_exibir['toneladas_realizadas']=df_exibir['toneladas_realizadas'].apply(em_toneladas)
        df_exibir['cargas_realizadas']=df_exibir.apply(lambda r: r['veiculos_carregados'] if r['operacao']=='CDA 01 - Carregamento' else r['cargas_realizadas'],axis=1)
        if 'turno' in df_exibir.columns: df_exibir['turno']=df_exibir['turno'].apply(nome_turno)
        df_exibir=df_exibir.rename(columns={'data':'Data operacional','criado_em':'Registrado em (data/hora)'})
        st.caption('A data operacional identifica o dia do turno. Registrado em mostra o instante de gravação; horários antigos foram mantidos como armazenados, sem reinterpretar o fuso ou corrigir datas automaticamente.')
        st.dataframe(df_exibir,use_container_width=True,hide_index=True)
        st.download_button('⬇️ Exportar CSV',df_exibir.to_csv(index=False).encode('utf-8-sig'),'historico_passagem.csv','text/csv')
        with st.expander('📲 Gerar resumo completo para WhatsApp'):
            opcoes={int(r.id):f'ID {r.id} • {r.data} • {nome_turno(r.turno)} • {r.operacao}' for r in df.itertuples()}
            selecionado=st.selectbox('Passagem para compartilhar',list(opcoes),index=None,format_func=lambda x:opcoes[x],key='historico_whatsapp')
            if selecionado is not None:
                mostrar_resumo_whatsapp(selecionado)
        with st.expander('👥 Consultar nomes de férias, afastamentos, atestados, faltas e folgas'):
            opcoes_nomes={int(r.id):f'ID {r.id} • {r.data} • {nome_turno(r.turno)} • {r.operacao}' for r in df.itertuples()}
            rid_nomes=st.selectbox('Passagem para consultar os nomes',list(opcoes_nomes),index=None,format_func=lambda x:opcoes_nomes[x],key='historico_nomes')
            if rid_nomes is not None:
                try:
                    nomes_reg=query('SELECT categoria AS "Categoria", nome AS "Colaborador" FROM colaboradores_ocorrencias WHERE passagem_id=? ORDER BY categoria,nome',(int(rid_nomes),))
                    if nomes_reg.empty:
                        st.info('Nenhum nome individual informado nesta passagem.')
                    else:
                        st.dataframe(nomes_reg,hide_index=True,use_container_width=True)
                except Exception:
                    st.info('Nenhum nome individual registrado nesta passagem (recurso disponível para novos lançamentos).')
        editar_historico(df)
        with st.expander('🗑️ Excluir registro do histórico'):
            st.caption('Selecione o registro como na opção Modificar. A exclusão retira a passagem dos indicadores, mas mantém os dados para auditoria.')
            opcoes_excluir={int(r.id):f"ID {r.id} • {r.data} • {nome_turno(r.turno)} • {r.operacao} • {r.responsavel}" for r in df.itertuples()}
            rid_excluir=st.selectbox('Passagem para excluir',list(opcoes_excluir),index=None,format_func=lambda x:opcoes_excluir[x],key='id_exclusao')
            if rid_excluir is not None:
                st.warning(f'Você selecionou: {opcoes_excluir[rid_excluir]}. A passagem deixará de aparecer nos painéis.')
                motivo_exclusao=st.text_area('Motivo da exclusão (obrigatório)',key='motivo_exclusao')
                confirmar_exclusao=st.checkbox('Confirmo que desejo excluir este registro',key='confirmar_exclusao')
                if st.button('🗑️ Excluir passagem selecionada',type='primary',disabled=not(confirmar_exclusao and motivo_exclusao.strip()),key='executar_exclusao'):
                    c=None
                    try:
                        c=conn(); cur=c.cursor()
                        cur.execute('UPDATE passagens SET excluido_em=NOW(), excluido_por=?, motivo_exclusao=? WHERE id=? AND excluido_em IS NULL',('Usuário do Histórico (sem autenticação)',motivo_exclusao.strip(),int(rid_excluir)))
                        alterados=cur._cursor.rowcount
                        c.commit()
                        if alterados:
                            st.session_state['historico_salvo']=f'Passagem ID {rid_excluir} excluída dos painéis e preservada para auditoria.'
                            st.rerun()
                        else:
                            st.warning('Passagem não encontrada ou já excluída.')
                    except Exception:
                        if c: c.rollback()
                        st.error('Não foi possível excluir. Nenhuma exclusão foi confirmada.')
                    finally:
                        if c: c.close()

else:
    st.header('🖨️ Passagem consolidada para impressão')
    a,b=st.columns(2); d=a.date_input('Data',agora_operacional().date()); t=b.selectbox('Turno',['T1','T2','T3'])
    df=query('SELECT * FROM passagens WHERE excluido_em IS NULL AND data=? AND turno=? ORDER BY operacao',(str(d),t))
    if df.empty: st.info('Não há registros para esta data/turno.')
    else:
        df=df.sort_values('id').groupby(['operacao'],as_index=False).tail(1)
        st.markdown(f'## PASSAGEM DE TURNO — {d.strftime("%d/%m/%Y")} — {nome_turno(t)}')
        resumo=[]
        for _,r in df.iterrows():
            realizado = em_toneladas(r['toneladas_realizadas']) if r['operacao'] in ['CDA 01 - Separação','CDA 01 - Carregamento'] else (r['cargas_realizadas'] if r['operacao']=='CDA 02' else em_toneladas(r['toneladas_estoque']))
            plan = r['planejado_ton'] if r['operacao']=='CDA 01 - Separação' else (r['planejado_cargas'] if r['operacao']=='CDA 02' else 0)
            resumo.append({'Operação':r['operacao'],'Planejado':plan,'Realizado':realizado,'Gap':realizado-plan if plan else None,'Atingimento %':pct(realizado,plan) if plan else None,'Status':r['status'],'Responsável':r['responsavel']})
        st.dataframe(pd.DataFrame(resumo),use_container_width=True,hide_index=True)
        st.markdown('### Pontos de atenção')
        for _,r in df.iterrows():
            st.markdown(f"**{r['operacao']}** — {r['status']} — Ofensor: {r['ofensor']}")
            if r['observacoes']: st.write(r['observacoes'])
        st.info('Use a opção de impressão do navegador para imprimir ou salvar esta visão em PDF. Na próxima etapa podemos gerar um PDF A4 formatado diretamente pelo app.')

st.divider()
st.caption('Passagem de Turno ADIMAX  •  Desenvolvido por Alan Machado')
