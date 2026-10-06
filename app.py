import os, sqlite3
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Passagem de Turno | Logística', page_icon='🚚', layout='wide')
DB='passagem_turno.db'

def conn():
    c=sqlite3.connect(DB, check_same_thread=False, timeout=30)
    c.execute('PRAGMA journal_mode=WAL;')
    return c

def init_db():
    with conn() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS passagens (
        id INTEGER PRIMARY KEY AUTOINCREMENT, criado_em TEXT, data TEXT, turno TEXT, area TEXT, lider TEXT,
        headcount INTEGER, ausencias INTEGER, presentes INTEGER, presenca_pct REAL,
        toneladas REAL DEFAULT 0, cargas INTEGER DEFAULT 0, uz_paletes INTEGER DEFAULT 0,
        pend_cargas INTEGER DEFAULT 0, falta_produtos INTEGER DEFAULT 0, chamados INTEGER DEFAULT 0,
        prioridade_faturamento INTEGER DEFAULT 0, prioridade_entrega INTEGER DEFAULT 0,
        ofensor TEXT, ponto_atencao TEXT, ocorrencias TEXT,
        maquina_problema INTEGER DEFAULT 0, maquina_detalhe TEXT,
        anomalia INTEGER DEFAULT 0, anomalia_detalhe TEXT, informacoes_adicionais TEXT,
        UNIQUE(data, turno, area))''')
init_db()

CSS='''
<style>
:root{--adimax:#f2b600;--ink:#202124;--wine:#7c1730;--soft:#f5f6f8;}
[data-testid="stAppViewContainer"]{background:#f5f6f8;}
.block-container{padding-top:1.2rem;max-width:1450px;}
.hero{position:relative;border-radius:18px;overflow:hidden;height:230px;margin-bottom:18px;background:#222;box-shadow:0 5px 18px #00000018}
.hero img{width:100%;height:100%;object-fit:cover;filter:brightness(.62)}
.hero-text{position:absolute;left:34px;bottom:26px;color:white}.hero-text h1{font-size:2.25rem;margin:0;font-weight:800}.hero-text p{margin:.2rem 0 0;font-size:1.05rem}
.brand{display:inline-block;background:var(--adimax);color:#111;padding:8px 14px;border-radius:8px;font-weight:900;letter-spacing:.6px;margin-bottom:10px}
.card{background:white;border-radius:16px;padding:20px 22px;box-shadow:0 2px 12px #0000000c;border:1px solid #e9eaed;margin-bottom:14px}
.section-title{font-weight:800;font-size:1.12rem;color:#2d3035;margin-bottom:10px}.accent{border-left:6px solid var(--adimax)}
.metricbox{background:white;border-radius:14px;padding:16px;border:1px solid #eceef0;text-align:center}.metricbox b{font-size:1.7rem;color:#222}.metricbox span{display:block;color:#6b7078;font-size:.85rem}
.warn{background:#fff4f6;border:1px solid #f3ccd5;border-left:5px solid var(--wine);border-radius:12px;padding:12px 14px}
[data-testid="stSidebar"]{background:#fff;} [data-testid="stSidebar"] img{border-radius:12px}
.stButton>button[kind="primary"]{background:var(--adimax);color:#111;border:0;font-weight:800}
</style>'''
st.markdown(CSS, unsafe_allow_html=True)

# sidebar
with st.sidebar:
    st.markdown('## ADIMAX')
    page=st.radio('Navegação',['Nova passagem','Visão atual','Semana','Histórico'], label_visibility='collapsed')
    if os.path.exists('assets/caminhoes.png'):
        st.image('assets/caminhoes.png', caption='Operação logística', use_container_width=True)

if os.path.exists('assets/fabrica.png'):
    import base64
    b64=base64.b64encode(open('assets/fabrica.png','rb').read()).decode()
    st.markdown(f'''<div class="hero"><img src="data:image/png;base64,{b64}"><div class="hero-text"><div class="brand">ADIMAX</div><h1>Passagem de Turno</h1><p>Logística • CDA 01 • CDA 02 • Estoque</p></div></div>''',unsafe_allow_html=True)
else:
    st.title('Passagem de Turno — Logística')

def pct(h,a):
    p=max(h-a,0); return p, (p/h*100 if h else 0)

def save(rec):
    cols=','.join(rec.keys()); marks=','.join(['?']*len(rec))
    with conn() as c:
        c.execute(f'INSERT INTO passagens ({cols}) VALUES ({marks})',tuple(rec.values()))

def load(where='',params=()):
    q='SELECT * FROM passagens '+where+' ORDER BY data DESC, id DESC'
    with conn() as c: return pd.read_sql_query(q,c,params=params)

if page=='Nova passagem':
    st.markdown('### Nova passagem de turno')
    st.caption('Preencha somente as informações essenciais do turno que está finalizando.')
    a,b,c,d=st.columns([1,1,1,1.5])
    dt=a.date_input('Data',date.today()); turno=b.selectbox('Turno',['T1','T2','T3']); area=c.selectbox('Área',['CDA 01','CDA 02','ESTOQUE']); lider=d.text_input('Líder / responsável')
    st.markdown('<div class="card accent"><div class="section-title">Equipe do turno</div></div>',unsafe_allow_html=True)
    e1,e2=st.columns(2); hc=e1.number_input('Headcount',0,500,0); aus=e2.number_input('Ausências',0,500,0); pres,pp=pct(hc,aus)
    m1,m2,m3=st.columns(3); m1.metric('Presentes',pres); m2.metric('Equipe presente',f'{pp:.1f}%'); m3.metric('Absenteísmo',f'{100-pp:.1f}%' if hc else '0,0%')

    toneladas=cargas=uz=pend=faltas=chamados=pfat=pent=0
    ofensor=ponto=ocorr=''; maq=False; maqdet=''; anom=False; anomdet=''; adicionais=''
    st.markdown(f'### Resultado do turno — {area}')
    if area=='CDA 01':
        r1,r2=st.columns(2); toneladas=r1.number_input('Toneladas realizadas',0.0,10000.0,0.0,step=0.1); cargas=r2.number_input('Cargas realizadas',0,1000,0)
        st.markdown('#### Situação da operação')
        q1,q2,q3,q4,q5=st.columns(5)
        pend=q1.number_input('Cargas pendentes',0,1000,0); faltas=q2.number_input('Faltas de produto',0,1000,0); chamados=q3.number_input('Chamados abertos',0,1000,0); pfat=q4.number_input('Prioridade faturamento',0,1000,0); pent=q5.number_input('Prioridade entrega',0,1000,0)
        ocorr=st.text_area('Detalhes das cargas / chamados / prioridades (opcional)')
        ponto=st.text_area('Ponto de atenção / observações')
    elif area=='CDA 02':
        r1,r2=st.columns(2); cargas=r1.number_input('Cargas separadas',0,1000,0); uz=r2.number_input('Paletes / UZs separados',0,10000,0)
        ofensor=st.text_area('Principal ofensor (se houver)')
        ponto=st.text_area('Ponto de atenção')
        ocorr=st.text_area('Informações / ocorrências do turno')
    else:
        r1,r2=st.columns(2); toneladas=r1.number_input('Toneladas puxadas da produção',0.0,10000.0,0.0,step=0.1); uz=r2.number_input('Paletes puxados',0,10000,0)
        ofensor=st.text_area('Principal ofensor (se houver)')
        x1,x2=st.columns(2); maq=x1.checkbox('Máquina / equipamento com problema'); anom=x2.checkbox('Anomalia que influencia o próximo turno')
        if maq: maqdet=st.text_area('Qual equipamento e qual problema?')
        if anom: anomdet=st.text_area('Descreva a anomalia e o impacto')
        ponto=st.text_area('Ponto de atenção')
        adicionais=st.text_area('Informações adicionais')
    if st.button('Salvar passagem',type='primary',use_container_width=True):
        if not lider.strip(): st.error('Informe o líder / responsável.')
        elif aus>hc: st.error('Ausências não pode ser maior que o headcount.')
        else:
            rec=dict(criado_em=datetime.now().isoformat(timespec='seconds'),data=str(dt),turno=turno,area=area,lider=lider.strip(),headcount=hc,ausencias=aus,presentes=pres,presenca_pct=pp,toneladas=toneladas,cargas=cargas,uz_paletes=uz,pend_cargas=pend,falta_produtos=faltas,chamados=chamados,prioridade_faturamento=pfat,prioridade_entrega=pent,ofensor=ofensor,ponto_atencao=ponto,ocorrencias=ocorr,maquina_problema=int(maq),maquina_detalhe=maqdet,anomalia=int(anom),anomalia_detalhe=anomdet,informacoes_adicionais=adicionais)
            try: save(rec); st.success('Passagem salva com sucesso.')
            except sqlite3.IntegrityError: st.error('Já existe uma passagem para esta Data + Turno + Área.')

elif page=='Visão atual':
    st.markdown('### Visão atual')
    df=load()
    if df.empty: st.info('Nenhuma passagem registrada ainda.')
    else:
        cols=st.columns(3)
        for i,ar in enumerate(['CDA 01','CDA 02','ESTOQUE']):
            x=df[df.area==ar].head(1)
            with cols[i]:
                st.markdown(f'#### {ar}')
                if x.empty: st.caption('Sem registro')
                else:
                    r=x.iloc[0]; st.caption(f"{r['data']} • {r['turno']} • {r['lider']}")
                    st.metric('Equipe presente',f"{r['presenca_pct']:.1f}%",f"{r['ausencias']} ausência(s)")
                    if ar=='CDA 01': st.metric('Toneladas',f"{r['toneladas']:.1f} t"); st.metric('Cargas',int(r['cargas'])); st.write(f"Pendentes: **{int(r['pend_cargas'])}** | Faltas produto: **{int(r['falta_produtos'])}**")
                    elif ar=='CDA 02': st.metric('Cargas separadas',int(r['cargas'])); st.metric('UZs / paletes',int(r['uz_paletes'])); st.write('**Ofensor:**',r['ofensor'] or '—')
                    else: st.metric('Toneladas puxadas',f"{r['toneladas']:.1f} t"); st.metric('Paletes puxados',int(r['uz_paletes'])); st.write('**Ofensor:**',r['ofensor'] or '—')
                    if r['ponto_atencao']: st.warning(r['ponto_atencao'])

elif page=='Semana':
    st.markdown('### Situação da semana')
    today=date.today(); ini=today-timedelta(days=today.weekday()); fim=ini+timedelta(days=6)
    f1,f2,f3=st.columns(3); d1=f1.date_input('De',ini); d2=f2.date_input('Até',fim); af=f3.selectbox('Área',['Todas','CDA 01','CDA 02','ESTOQUE'])
    df=load('WHERE data BETWEEN ? AND ?',(str(d1),str(d2)))
    if af!='Todas': df=df[df.area==af]
    if df.empty: st.info('Sem registros no período.')
    else:
        s1,s2,s3,s4=st.columns(4); s1.metric('Passagens',len(df)); s2.metric('Presença média',f"{df.presenca_pct.mean():.1f}%"); s3.metric('Ausências',int(df.ausencias.sum())); s4.metric('Turnos com ofensor',int((df.ofensor.fillna('').str.strip()!='').sum()))
        for ar in ['CDA 01','CDA 02','ESTOQUE']:
            x=df[df.area==ar].copy()
            if x.empty: continue
            st.markdown(f'#### {ar}')
            k1,k2,k3=st.columns(3)
            if ar=='CDA 01': k1.metric('Toneladas',f"{x.toneladas.sum():.1f} t"); k2.metric('Cargas',int(x.cargas.sum())); k3.metric('Presença média',f"{x.presenca_pct.mean():.1f}%")
            elif ar=='CDA 02': k1.metric('Cargas',int(x.cargas.sum())); k2.metric('UZs / paletes',int(x.uz_paletes.sum())); k3.metric('Presença média',f"{x.presenca_pct.mean():.1f}%")
            else: k1.metric('Toneladas puxadas',f"{x.toneladas.sum():.1f} t"); k2.metric('Paletes puxados',int(x.uz_paletes.sum())); k3.metric('Presença média',f"{x.presenca_pct.mean():.1f}%")
            x['dia_turno']=x['data']+' '+x['turno']
            val='toneladas' if ar!='CDA 02' else 'cargas'
            st.bar_chart(x.set_index('dia_turno')[[val]])
        ofs=df[df.ofensor.fillna('').str.strip()!=''].groupby('ofensor').size().sort_values(ascending=False)
        if len(ofs): st.markdown('#### Ofensores registrados'); st.bar_chart(ofs)

else:
    st.markdown('### Histórico')
    df=load()
    if df.empty: st.info('Nenhuma passagem registrada.')
    else:
        f1,f2=st.columns(2); af=f1.selectbox('Filtrar área',['Todas','CDA 01','CDA 02','ESTOQUE']); tf=f2.selectbox('Filtrar turno',['Todos','T1','T2','T3'])
        if af!='Todas': df=df[df.area==af]
        if tf!='Todos': df=df[df.turno==tf]
        show=['data','turno','area','lider','headcount','ausencias','presenca_pct','toneladas','cargas','uz_paletes','pend_cargas','falta_produtos','chamados','ofensor','ponto_atencao']
        st.dataframe(df[show],use_container_width=True,hide_index=True)
        st.download_button('Baixar histórico em CSV',df.to_csv(index=False).encode('utf-8-sig'),'historico_passagem.csv','text/csv')

st.caption('V3 • Protótipo operacional. Para uso definitivo no Streamlit Cloud, conectar a um banco persistente antes de registrar dados reais.')
