import os
from datetime import datetime, date, timedelta
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Passagem de Turno | ADIMAX', page_icon='📦', layout='wide')

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
            self.lastrowid = self._cursor.fetchone()[0]
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

@st.cache_data(ttl=45, show_spinner=False)
def consultar_transbordos(data_ref, turno_ref):
    import json, urllib.parse, urllib.request, unicodedata
    url = 'https://transbordos-cda02-online.onrender.com/api/viagens?' + urllib.parse.urlencode({'data':str(data_ref),'turno':str(turno_ref)})
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Accept':'application/json'}),timeout=15) as resposta:
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
    url='https://transbordos-cda02-online.onrender.com/api/viagens?'+urllib.parse.urlencode({'data':str(data_ref),'turno':str(turno_ref)})
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Accept':'application/json'}),timeout=15) as resposta:
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
    """Converte peso operacional em kg para toneladas; mantém valores já lançados em t."""
    try:
        v=float(valor or 0)
        return v/1000.0 if abs(v)>=10000 else v
    except (TypeError, ValueError):
        return 0.0


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

st.markdown('''<style>
.block-container{padding-top:1.1rem}.hero{background:linear-gradient(90deg,#111,#2a2a2a);padding:22px 28px;border-radius:16px;border-left:8px solid #f5b400;color:white;margin-bottom:16px}.hero h1{margin:0;font-size:34px}.hero p{margin:5px 0 0;color:#ddd}.kpi{border:1px solid #e6e6e6;border-radius:14px;padding:14px;background:white}.stButton>button{border-radius:10px;font-weight:700}.status{font-size:22px;font-weight:800}.small{color:#666;font-size:13px}
</style>''',unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>Passagem de Turno</h1><p>Logística • CDA 01 • CDA 02 • Estoque</p></div>',unsafe_allow_html=True)

with st.sidebar:
    st.markdown('## ADIMAX')
    if os.path.exists('assets/caminhoes.png'): st.image('assets/caminhoes.png',use_container_width=True)
    pagina=st.radio('Navegação',['📝 Nova Passagem','📋 Planejamento','🎯 Planejado do Dia','👁️ Visão Atual','👔 Visão do Supervisor','📊 Semana','🕘 Histórico','🖨️ Imprimir'])

if pagina=='📋 Planejamento':
    st.header('📋 Planejamento diário')
    st.caption('Metas diárias de Separação e Carregamento. Ao salvar novamente a mesma data, as metas são atualizadas.')
    d=st.date_input('Data do planejamento',date.today())
    st.markdown('#### 📦 Separação')
    sep_plan=st.number_input('Toneladas planejadas de Separação',min_value=0.0,step=1.0,format='%.1f',value=scalar_plan(d,'DIA','CDA 01 - Separação','Toneladas'),key=f'sep_{d}')
    st.markdown('#### 🚛 Carregamento')
    car_qtd=st.number_input('Veículos / cargas planejados',min_value=0,step=1,value=int(scalar_plan(d,'DIA','CDA 01 - Carregamento','Veículos')),key=f'car_qtd_{d}')
    if st.button('💾 Salvar / atualizar planejamento diário',type='primary'):
        c=conn()
        try:
            cur=c.cursor()
            agora=datetime.now().isoformat(timespec='seconds')
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
    d=st.date_input('Data do painel',date.today(),key='data_painel_dia')
    plan_sep=scalar_plan(d,'DIA','CDA 01 - Separação','Toneladas')
    plan_car_qtd=scalar_plan(d,'DIA','CDA 01 - Carregamento','Veículos')
    if plan_sep>=10000: plan_sep=plan_sep/1000.0
    dados=query("SELECT * FROM passagens WHERE data=? AND operacao IN ('CDA 01 - Separação','CDA 01 - Carregamento') ORDER BY id",(str(d),))
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
    abs_dia=query("SELECT * FROM passagens WHERE data=? ORDER BY id",(str(d),))
    hc_geral=0.0; aus_geral=0.0
    abs_turnos={t:(None,0.0,0.0) for t in ['T1','T2','T3']}
    if not abs_dia.empty:
        base_abs=abs_dia.sort_values('id').groupby(['turno','operacao'],as_index=False).tail(1)
        for t in ['T1','T2','T3']:
            rt=base_abs[base_abs.turno==t]
            if not rt.empty:
                hc=float(rt.headcount.sum())
                au=float(rt.ausencias.sum())
                perc=(au/hc*100) if hc else 0.0
                abs_turnos[t]=(perc,au,hc)
                hc_geral+=hc
                aus_geral+=au
    abs_geral=(aus_geral/hc_geral*100) if hc_geral else 0.0

    st.markdown('### 👥 Absenteísmo do Dia')
    a1,a2,a3,a4=st.columns(4)
    a1.metric('Geral do dia',f'{abs_geral:.1f}%' if hc_geral else 'Aguardando')
    for col,t in zip([a2,a3,a4],['T1','T2','T3']):
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
    b.metric('Vendas',f'{varejo_t:.1f} t')
    c.metric('Transferências',f'{transf_q:g}')
    d.metric('Transferências',f'{transf_t:.1f} t')
    st.markdown('#### Realizado por turno — Separação')
    cols=st.columns(3)
    for col,t in zip(cols,['T1','T2','T3']):
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
    data_reg=st.date_input('Data',date.today())
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
    h1,h2=st.columns(2); hc=int(h1.number_input('Headcount do turno',min_value=0,step=1)); aus=int(h2.number_input('Ausências',min_value=0,step=1))
    presentes=max(hc-aus,0); abs_pct=(aus/hc*100) if hc else 0
    m1,m2,m3=st.columns(3);m1.metric('Presentes',presentes);m2.metric('Equipe presente',f'{(100-abs_pct):.1f}%');m3.metric('Absenteísmo',f'{abs_pct:.1f}%')
    # Passagem enxuta: não exige nomes/motivos individuais das ausências.
    aus_det=[]

    cargas=ton=vt=vc=vp=uz=pd_e=trans=ton_est=pal_est=0.0
    varejo_cargas=varejo_ton=transferencias_qtd=transferencias_ton=0.0
    receb_kg=receb_pal=abast_kg=abast_pal=0.0
    car_desc=car_arm=car_agu=trans_cda02=reemb=reproc=maq_par=0
    equip_parado=problema_equip=pend_prox=''
    pc=pt=pv=0.0
    pend=[]
    conf_tc=conf_tu=conf_er=conf_cc=conf_uc=None
    st.subheader('📦 Resultado do turno')
    if operacao=='CDA 01 - Separação':
        pc=0.0; pt=scalar_plan(data_reg,'DIA',operacao,'Toneladas')
        if pt>=10000: pt=pt/1000.0
        st.markdown('#### 🛒 Varejo')
        x,y=st.columns(2)
        varejo_cargas=x.number_input('Cargas Vendas',min_value=0.0,step=1.0)
        varejo_ton=y.number_input('Toneladas Vendas',min_value=0.0,step=0.1,format='%.1f')
        st.markdown('#### 🔄 Transferências')
        x,y=st.columns(2)
        transferencias_qtd=x.number_input('Quantidade de Transferências',min_value=0.0,step=1.0)
        transferencias_ton=y.number_input('Toneladas de Transferências',min_value=0.0,step=0.1,format='%.1f')
        cargas=varejo_cargas+transferencias_qtd
        ton=varejo_ton+transferencias_ton
        t1,t2=st.columns(2)
        t1.metric('Total operações separadas',f'{cargas:g}')
        t2.metric('Total separado no turno',f'{ton:.1f} t')
        st.info(f'Planejado diário da Separação: {pt:.1f} t' if pt else 'Planejamento diário ainda não cadastrado.')
        n=int(st.number_input('Quantidade de cargas pendentes',min_value=0,step=1))
        for i in range(n):
            st.markdown(f'**Pendência {i+1}**'); q1,q2,q3=st.columns(3); cg=q1.text_input('Carga',key=f'pcg{i}'); cli=q2.text_input('Cliente',key=f'pcl{i}'); sit=q3.selectbox('Situação',['P&D','Separação não iniciada','Em separação','Aguardando produto','Outra'],key=f'psi{i}'); q4,q5=st.columns(2); mot=q4.selectbox('Motivo',['Falta de produto','Sistema/Integração','Mão de obra','Equipamento','Qualidade','Operacional','Outro'],key=f'pmo{i}'); det=q5.text_input('Detalhe',key=f'pde{i}'); pend.append((cg,cli,sit,mot,det))
    elif operacao=='CDA 01 - Carregamento':
        pv=0.0
        pt=0.0
        x,y,z=st.columns(3)
        vc=x.number_input('Veículos carregados',min_value=0.0,step=1.0)
        vp=y.number_input('Veículos para o próximo turno',min_value=0.0,step=1.0)
        ton=z.number_input('Toneladas carregadas no turno (t)',min_value=0.0,step=0.1,format='%.3f')
        for i in range(int(vp)):
            st.markdown(f'**Veículo pendente {i+1}**'); q1,q2=st.columns(2); cg=q1.text_input('Carga',key=f'vcg{i}'); mot=q2.selectbox('Motivo',['Carga não integrada','Separação não iniciada','Veículo não se apresentou','Carga batida / próximo turno','Falta de produto','T.I./Körber','Problema operacional','Outro'],key=f'vmo{i}'); det=st.text_input('Detalhe / observação',key=f'vde{i}'); pend.append((cg,'','Carregamento pendente',mot,det))
    elif operacao=='CDA 02':
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
        except Exception:
            st.error('Transbordos indisponível: não é possível preencher automaticamente. Atualize a página e tente novamente.')
            st.stop()
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
        st.caption('Se já houver passagem para esta data e turno, o salvamento atualizará o registro existente.')

    else:
        st.markdown('### 🏭 Indicadores principais')
        a1,a2=st.columns(2)
        receb_kg=a1.number_input('Recebimento da Produção (kg)',min_value=0.0,step=100.0,format='%.0f')
        receb_pal=a2.number_input('Paletes recebidos da Produção',min_value=0.0,step=1.0)
        b1,b2=st.columns(2)
        abast_kg=b1.number_input('Abastecimento do Picking (kg)',min_value=0.0,step=100.0,format='%.0f')
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
    stat=status_auto(len(pend),abs_pct,of,ofensor_grave)
    st.markdown(f'<div class="status">Status sugerido: {stat}</div>',unsafe_allow_html=True)
    if st.button('💾 Salvar passagem',type='primary',use_container_width=True):
        if not resp.strip(): st.error('Informe o responsável pela passagem.')
        elif aus>hc: st.error('Ausências não pode ser maior que o headcount.')
        elif operacao=='CDA 02' and (conf_cc>conf_tc or conf_uc>conf_tu): st.error('A quantidade conferida não pode superar o total.')
        else:
            c=conn();cur=c.cursor()
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
            conf_total_cargas,conf_total_uzs,conf_erros,conf_cargas_conferidas,conf_uzs_conferidas
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (data,area,operacao,turno) WHERE operacao='CDA 02' DO UPDATE SET responsavel=EXCLUDED.responsavel, headcount=EXCLUDED.headcount, ausencias=EXCLUDED.ausencias, presentes=EXCLUDED.presentes, absenteismo=EXCLUDED.absenteismo, cargas_realizadas=EXCLUDED.cargas_realizadas, toneladas_realizadas=EXCLUDED.toneladas_realizadas, veiculos_trabalhados=EXCLUDED.veiculos_trabalhados, veiculos_carregados=EXCLUDED.veiculos_carregados, veiculos_pendentes=EXCLUDED.veiculos_pendentes, uz_paletes=EXCLUDED.uz_paletes, pd_espera=EXCLUDED.pd_espera, transbordo_total=EXCLUDED.transbordo_total, toneladas_estoque=EXCLUDED.toneladas_estoque, paletes_estoque=EXCLUDED.paletes_estoque, planejado_cargas=EXCLUDED.planejado_cargas, planejado_ton=EXCLUDED.planejado_ton, planejado_veiculos=EXCLUDED.planejado_veiculos, gap_cargas=EXCLUDED.gap_cargas, gap_ton=EXCLUDED.gap_ton, gap_veiculos=EXCLUDED.gap_veiculos, ating_cargas=EXCLUDED.ating_cargas, ating_ton=EXCLUDED.ating_ton, ating_veiculos=EXCLUDED.ating_veiculos, ofensor=EXCLUDED.ofensor, observacoes=EXCLUDED.observacoes, status=EXCLUDED.status, recebimento_producao_kg=EXCLUDED.recebimento_producao_kg, recebimento_producao_paletes=EXCLUDED.recebimento_producao_paletes, abastecimento_picking_kg=EXCLUDED.abastecimento_picking_kg, abastecimento_picking_paletes=EXCLUDED.abastecimento_picking_paletes, carretas_descarregadas=EXCLUDED.carretas_descarregadas, carretas_armazenadas=EXCLUDED.carretas_armazenadas, carretas_aguardando=EXCLUDED.carretas_aguardando, transbordos_cda02=EXCLUDED.transbordos_cda02, reembalo_enviados=EXCLUDED.reembalo_enviados, reprocesso_enviados=EXCLUDED.reprocesso_enviados, maquinas_paradas=EXCLUDED.maquinas_paradas, equipamento_parado=EXCLUDED.equipamento_parado, problema_equipamento=EXCLUDED.problema_equipamento, pendencias_proximo_turno=EXCLUDED.pendencias_proximo_turno, varejo_cargas=EXCLUDED.varejo_cargas, varejo_ton=EXCLUDED.varejo_ton, transferencias_qtd=EXCLUDED.transferencias_qtd, transferencias_ton=EXCLUDED.transferencias_ton, conf_total_cargas=EXCLUDED.conf_total_cargas, conf_total_uzs=EXCLUDED.conf_total_uzs, conf_erros=EXCLUDED.conf_erros, conf_cargas_conferidas=EXCLUDED.conf_cargas_conferidas, conf_uzs_conferidas=EXCLUDED.conf_uzs_conferidas''',
            (datetime.now().isoformat(timespec='seconds'),str(data_reg),turno,area,operacao,resp,hc,aus,presentes,abs_pct,
             cargas,ton,vt,vc,vp,uz,pd_e,trans,ton_est,pal_est,pc,pt,pv,gc,gt,gv,ac,at,av,of,obs,stat,
             receb_kg,receb_pal,abast_kg,abast_pal,car_desc,car_arm,car_agu,trans_cda02,reemb,reproc,maq_par,
             equip_parado,problema_equip,pend_prox,varejo_cargas,varejo_ton,transferencias_qtd,transferencias_ton,conf_tc,conf_tu,conf_er,conf_cc,conf_uc)); pid=cur.lastrowid
            for r in pend: cur.execute('INSERT INTO pendencias(passagem_id,carga,cliente,situacao,motivo,descricao) VALUES(?,?,?,?,?,?)',(pid,*r))
            c.commit();c.close();st.success('Passagem salva com sucesso.')


elif pagina=='👁️ Visão Atual':
    st.header('👁️ Visão atual')
    df=query('SELECT * FROM passagens ORDER BY id DESC')
    if df.empty: st.info('Ainda não existem passagens salvas.')
    else:
        latest=df.groupby(['operacao','turno'],as_index=False).first()
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
    hoje=date.today()
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
        dados=query('SELECT * FROM passagens WHERE operacao=? AND data BETWEEN ? AND ? ORDER BY id DESC',(op,str(di),str(dfim)))
    else:
        dados=query('SELECT * FROM passagens WHERE operacao=? AND data BETWEEN ? AND ? AND turno=? ORDER BY id DESC',(op,str(di),str(dfim),turno_filtro))
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
    if dados.empty:
        st.info('Não há passagens registradas para esta área no período selecionado.')
    else:
        # Uma versão por data/turno, evitando somar reenvios da mesma passagem.
        dados=dados.sort_values('id').groupby(['data','turno','operacao'],as_index=False).tail(1).copy()
        dados['Volume_t']=dados['toneladas_realizadas'].apply(em_toneladas) if op!='Estoque' else dados['toneladas_estoque'].apply(em_toneladas)
        dados['Movimentos']=dados['veiculos_carregados'] if op=='CDA 01 - Carregamento' else dados['cargas_realizadas']
        total_hc=float(dados['headcount'].sum())
        total_aus=float(dados['ausencias'].sum())
        a,b,c,d=st.columns(4)
        a.metric('Passagens registradas',len(dados))
        if op=='Estoque':
            b.metric('Paletes recebidos',f"{dados['recebimento_producao_paletes'].sum():g}")
            c.metric('Paletes abastecidos',f"{dados['abastecimento_picking_paletes'].sum():g}")
        else:
            b.metric('Veículos carregados' if op=='CDA 01 - Carregamento' else 'Cargas',f"{dados['Movimentos'].sum():g}")
            c.metric('Toneladas',f"{dados['Volume_t'].sum():.1f} t")
        d.metric('Absenteísmo',f'{total_aus/total_hc*100:.1f}%' if total_hc else '—')
        st.markdown('#### Detalhamento da operação')
        if op=='CDA 01 - Separação':
            a,b,c,d=st.columns(4)
            a.metric('Cargas de vendas',f"{dados['varejo_cargas'].sum():g}")
            b.metric('Toneladas de vendas',f"{dados['varejo_ton'].sum():.1f} t")
            c.metric('Transferências',f"{dados['transferencias_qtd'].sum():g}")
            d.metric('Toneladas transferidas',f"{dados['transferencias_ton'].sum():.1f} t")
        elif op=='CDA 01 - Carregamento':
            a,b,c=st.columns(3)
            a.metric('Veículos carregados',f"{dados['veiculos_carregados'].sum():g}")
            b.metric('Toneladas carregadas',f"{dados['Volume_t'].sum():.1f} t")
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
        st.markdown('#### Evolução da área')
        if op=='Estoque':
            evol=dados.groupby('data',as_index=True)[['recebimento_producao_paletes','abastecimento_picking_paletes']].sum()
            st.line_chart(evol)
        else:
            evol=dados.groupby('data',as_index=True)[['Volume_t','Movimentos']].sum()
            st.line_chart(evol)
        st.markdown('#### Resultado por turno')
        por_turno=dados.groupby('turno',as_index=False).agg(Passagens=('id','count'),Movimentos=('Movimentos','sum'),Toneladas=('Volume_t','sum'),Ausencias=('ausencias','sum'),Headcount=('headcount','sum'))
        por_turno['Turno']=por_turno['turno'].apply(nome_turno)
        por_turno['Absenteísmo (%)']=por_turno.apply(lambda r: round(r['Ausencias']/r['Headcount']*100,1) if r['Headcount'] else 0,axis=1)
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
        st.markdown('#### Últimas passagens')
        st.dataframe(dados.sort_values('id',ascending=False)[['data','turno','responsavel','status','absenteismo']].rename(columns={'data':'Data','turno':'Turno','responsavel':'Líder','status':'Status','absenteismo':'Absenteísmo (%)'}),hide_index=True,use_container_width=True)

elif pagina=='📊 Semana':
    st.header('📊 Resumo semanal')
    hoje=date.today(); ini=hoje-timedelta(days=hoje.weekday()); fim=ini+timedelta(days=6)
    a,b=st.columns(2); di=a.date_input('Início',ini); dfim=b.date_input('Fim',fim)
    df=query('SELECT * FROM passagens WHERE data BETWEEN ? AND ? ORDER BY data',(str(di),str(dfim)))
    if df.empty: st.info('Sem registros no período.')
    else:
        df=df.sort_values('id').groupby(['data','turno','operacao'],as_index=False).tail(1).copy()
        df['Toneladas_exibicao']=df.apply(lambda r: em_toneladas(r['toneladas_realizadas']) if r['operacao'] in ['CDA 01 - Separação','CDA 01 - Carregamento'] else em_toneladas(r['toneladas_estoque']),axis=1)
        df['Cargas_exibicao']=df.apply(lambda r: r['veiculos_carregados'] if r['operacao']=='CDA 01 - Carregamento' else r['cargas_realizadas'],axis=1)
        c1,c2,c3,c4=st.columns(4)
        hc_total=float(df.headcount.sum()); aus_total=float(df.ausencias.sum())
        c1.metric('Passagens',len(df)); c2.metric('Cargas',f"{df.Cargas_exibicao.sum():g}"); c3.metric('Toneladas por operação','Ver detalhamento'); c4.metric('Absenteísmo',f"{(aus_total/hc_total*100):.1f}%" if hc_total else '—')
        chart=df.groupby(['data','operacao'],as_index=False).agg(Cargas=('Cargas_exibicao','sum'),Toneladas=('Toneladas_exibicao','sum'))
        st.markdown('#### Evolução diária de toneladas por operação'); st.line_chart(chart.pivot(index='data',columns='operacao',values='Toneladas').fillna(0))
        por_op=df.groupby('operacao',as_index=False).agg(Passagens=('id','count'),Cargas=('Cargas_exibicao','sum'),Toneladas=('Toneladas_exibicao','sum'),Absenteismo_medio=('absenteismo','mean'))
        st.markdown('#### Por operação (sem somar Separação e Carregamento)'); st.dataframe(por_op,use_container_width=True,hide_index=True)
        est=df[df.operacao=='Estoque'].copy()
        if not est.empty:
            st.markdown('#### 📦 Estoque — Produção × Picking por turno')
            est_res=est.groupby('turno',as_index=False).agg(
                Recebimento_kg=('recebimento_producao_kg','sum'),
                Recebimento_paletes=('recebimento_producao_paletes','sum'),
                Abastecimento_kg=('abastecimento_picking_kg','sum'),
                Abastecimento_paletes=('abastecimento_picking_paletes','sum'))
            st.dataframe(est_res,use_container_width=True,hide_index=True)

elif pagina=='🕘 Histórico':
    st.header('🕘 Histórico')
    df=query('SELECT id,data,turno,operacao,responsavel,status,cargas_realizadas,toneladas_realizadas,veiculos_carregados,veiculos_pendentes,absenteismo,ofensor,observacoes,criado_em FROM passagens ORDER BY id DESC')
    if df.empty: st.info('Sem registros.')
    else:
        df_exibir=df.copy()
        df_exibir['toneladas_realizadas']=df_exibir['toneladas_realizadas'].apply(em_toneladas)
        df_exibir['cargas_realizadas']=df_exibir.apply(lambda r: r['veiculos_carregados'] if r['operacao']=='CDA 01 - Carregamento' else r['cargas_realizadas'],axis=1)
        if 'turno' in df_exibir.columns: df_exibir['turno']=df_exibir['turno'].apply(nome_turno)
        st.dataframe(df_exibir,use_container_width=True,hide_index=True)
        st.download_button('⬇️ Exportar CSV',df_exibir.to_csv(index=False).encode('utf-8-sig'),'historico_passagem.csv','text/csv')
        with st.expander('🗑️ Excluir registro'):
            rid=st.number_input('ID do registro',min_value=1,step=1); conf=st.checkbox('Confirmo a exclusão')
            if st.button('Excluir') and conf:
                c=conn();cur=c.cursor();cur.execute('DELETE FROM passagens WHERE id=?',(rid,));c.commit();c.close();st.success('Registro excluído.');st.rerun()

else:
    st.header('🖨️ Passagem consolidada para impressão')
    a,b=st.columns(2); d=a.date_input('Data',date.today()); t=b.selectbox('Turno',['T1','T2','T3'])
    df=query('SELECT * FROM passagens WHERE data=? AND turno=? ORDER BY operacao',(str(d),t))
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

st.caption('Passagem de Turno ADIMAX • Dados armazenados no PostgreSQL (Supabase).')
