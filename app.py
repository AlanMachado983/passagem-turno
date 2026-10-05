import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path

DB = Path(__file__).with_name('passagem_turno.db')
st.set_page_config(page_title='Passagem de Turno | Logística', page_icon='📦', layout='wide')

CSS='''<style>
.block-container{padding-top:1.4rem;max-width:1450px}.stMetric{background:#f7f8fa;border:1px solid #e5e7eb;padding:12px;border-radius:12px}
div[data-testid="stForm"]{border:1px solid #e5e7eb;padding:18px;border-radius:14px}.small{color:#667085;font-size:.9rem}
</style>'''
st.markdown(CSS, unsafe_allow_html=True)

@st.cache_resource
def get_conn():
    c=sqlite3.connect(DB, check_same_thread=False, timeout=30)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('''CREATE TABLE IF NOT EXISTS passagens (
      id INTEGER PRIMARY KEY AUTOINCREMENT, criado_em TEXT NOT NULL, data TEXT NOT NULL, turno TEXT NOT NULL,
      area TEXT NOT NULL, lider TEXT, headcount INTEGER NOT NULL, ausencias INTEGER NOT NULL, presentes INTEGER NOT NULL,
      presenca REAL NOT NULL, absenteismo REAL NOT NULL, unidade TEXT NOT NULL, planejado REAL NOT NULL, realizado REAL NOT NULL,
      atingimento REAL NOT NULL, gap REAL NOT NULL, ofensor TEXT, ponto_atencao TEXT, pendencia TEXT, prioridade TEXT,
      UNIQUE(data,turno,area)
    )''')
    c.commit(); return c
conn=get_conn()

def carregar(): return pd.read_sql_query('SELECT * FROM passagens ORDER BY data DESC, id DESC',conn)
def pct(v): return f'{v:.1f}%'.replace('.',',')
def n(v): return f'{v:,.1f}'.replace(',','X').replace('.',',').replace('X','.')
def farol(a): return '🟢 Dentro do esperado' if a>=100 else ('🟡 Atenção' if a>=90 else '🔴 Crítico')
def unidade(area): return 'ton' if area=='ESTOQUE' else 'cargas'

st.title('📦 Passagem de Turno — Logística')
st.caption('CDA 01 • CDA 02 • Estoque | lançamento rápido, visão atual, semana e histórico')
menu=st.sidebar.radio('Navegação',['📝 Nova passagem','📍 Visão atual','📊 Semana','🗂️ Histórico'])

if menu=='📝 Nova passagem':
    st.subheader('Nova passagem')
    st.caption('Preencha somente o essencial. Os indicadores são calculados automaticamente.')
    with st.form('passagem',clear_on_submit=True):
        a,b,c,d=st.columns(4)
        data_ref=a.date_input('Data',date.today()); turno=b.selectbox('Turno',['T1','T2','T3']); area=c.selectbox('Área',['CDA 01','CDA 02','ESTOQUE']); lider=d.text_input('Líder / responsável')
        st.markdown('#### 👥 Efetivo')
        a,b=st.columns(2); hc=a.number_input('Headcount do turno',0,500,step=1); aus=b.number_input('Ausências',0,500,step=1)
        st.markdown('#### 🎯 Planejado × realizado')
        un=unidade(area); a,b=st.columns(2); plan=a.number_input(f'Planejado ({un})',0.0,1000000.0,step=1.0); real=b.number_input(f'Realizado ({un})',0.0,1000000.0,step=1.0)
        if area=='ESTOQUE': st.caption('Estoque: indicador principal = peso puxado da produção em toneladas.')
        st.markdown('#### ⚠️ Gestão do turno')
        a,b=st.columns(2)
        ofensor=a.selectbox('Principal ofensor',['Sem ofensor','Absenteísmo','Equipamento','Sistema / WMS','Produção','Falta de estoque','Atraso de veículo','Processo / operação','Outro'])
        ponto=b.text_input('Ponto de atenção',placeholder='Somente se houver algo relevante')
        pend=st.text_area('Pendência para o próximo turno',height=75,placeholder='O que ficou e precisa ser conhecido pelo próximo turno?')
        prio=st.text_area('Prioridade para o próximo turno',height=75,placeholder='Qual deve ser a primeira ação do próximo turno?')
        salvar=st.form_submit_button('💾 FINALIZAR PASSAGEM',type='primary',use_container_width=True)
    if salvar:
        if hc<=0: st.error('Informe o headcount.')
        elif aus>hc: st.error('Ausências não podem superar o headcount.')
        elif plan<=0: st.error('Informe o planejado.')
        else:
            pres=int(hc-aus); pp=pres/hc*100; ab=aus/hc*100; at=real/plan*100; gap=real-plan
            try:
                conn.execute('''INSERT INTO passagens(criado_em,data,turno,area,lider,headcount,ausencias,presentes,presenca,absenteismo,unidade,planejado,realizado,atingimento,gap,ofensor,ponto_atencao,pendencia,prioridade) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(datetime.now().isoformat(timespec='seconds'),str(data_ref),turno,area,lider,int(hc),int(aus),pres,pp,ab,un,plan,real,at,gap,ofensor,ponto,pend,prio)); conn.commit(); st.success(f'{area} / {turno} salvo. Presença {pct(pp)} • Atingimento {pct(at)} • {farol(at)}')
            except sqlite3.IntegrityError: st.error('Já existe uma passagem dessa Área/Turno/Data. Use o histórico para conferir antes de lançar novamente.')

elif menu=='📍 Visão atual':
    st.subheader('Visão atual da operação')
    df=carregar()
    if df.empty: st.info('Sem registros ainda.')
    else:
        cols=st.columns(3)
        for col,ar in zip(cols,['CDA 01','CDA 02','ESTOQUE']):
            with col:
                x=df[df.area==ar].head(1)
                st.markdown(f'### {ar}')
                if x.empty: st.warning('Sem passagem registrada'); continue
                r=x.iloc[0]; st.caption(f"{r.data} • {r.turno} • {r.lider or 'Responsável não informado'}")
                st.metric('Equipe trabalhando',pct(r.presenca),f"{int(r.presentes)}/{int(r.headcount)} • {int(r.ausencias)} ausência(s)")
                st.metric('Atingimento',pct(r.atingimento),farol(r.atingimento)); st.metric('Realizado',f"{n(r.realizado)} {r.unidade}",f"Plano {n(r.planejado)} • GAP {n(r.gap)}")
                st.write('**Ofensor:**',r.ofensor); st.write('**Ponto de atenção:**',r.ponto_atencao or '—'); st.write('**Pendência:**',r.pendencia or '—'); st.write('**Prioridade:**',r.prioridade or '—')

elif menu=='📊 Semana':
    st.subheader('Resumo da semana')
    df=carregar()
    if df.empty: st.info('Sem dados ainda.')
    else:
        df['data_dt']=pd.to_datetime(df.data)
        fim=pd.Timestamp(st.date_input('Semana até',date.today())); ini=fim-pd.Timedelta(days=6); sem=df[(df.data_dt>=ini)&(df.data_dt<=fim)].copy()
        st.caption(f'Período: {ini.strftime("%d/%m/%Y")} a {fim.strftime("%d/%m/%Y")}')
        if sem.empty: st.warning('Sem registros no período.')
        else:
            cards=st.columns(3)
            for col,ar in zip(cards,['CDA 01','CDA 02','ESTOQUE']):
                s=sem[sem.area==ar]
                with col:
                    st.markdown(f'### {ar}')
                    if s.empty: st.warning('Sem dados'); continue
                    st.metric('Atingimento médio',pct(s.atingimento.mean())); st.metric('Presença média',pct(s.presenca.mean())); st.metric('Ausências acumuladas',int(s.ausencias.sum()),f'{len(s)} passagem(ns)')
            st.markdown('### Evolução do atingimento (%)')
            evo=sem.pivot_table(index='data_dt',columns='area',values='atingimento',aggfunc='mean').sort_index(); st.line_chart(evo)
            st.markdown('### Presença média (%)'); st.bar_chart(sem.groupby('area').presenca.mean())
            st.markdown('### Ofensores da semana')
            of=sem[sem.ofensor!='Sem ofensor'].groupby(['area','ofensor']).size().reset_index(name='Ocorrências').sort_values('Ocorrências',ascending=False)
            if of.empty: st.success('Nenhum ofensor registrado.');
            else: st.dataframe(of,use_container_width=True,hide_index=True)
            st.markdown('### Turnos abaixo do planejado')
            baixo=sem[sem.atingimento<100][['data','turno','area','atingimento','gap','ofensor','pendencia']].sort_values(['data','area'],ascending=[False,True]); st.dataframe(baixo,use_container_width=True,hide_index=True)

else:
    st.subheader('Histórico')
    df=carregar()
    if df.empty: st.info('Sem registros ainda.')
    else:
        a,b=st.columns(2); areas=a.multiselect('Área',['CDA 01','CDA 02','ESTOQUE'],default=['CDA 01','CDA 02','ESTOQUE']); turnos=b.multiselect('Turno',['T1','T2','T3'],default=['T1','T2','T3'])
        vis=df[df.area.isin(areas)&df.turno.isin(turnos)].copy(); cols=['data','turno','area','lider','headcount','ausencias','presentes','presenca','absenteismo','planejado','realizado','atingimento','gap','unidade','ofensor','ponto_atencao','pendencia','prioridade']
        st.dataframe(vis[cols],use_container_width=True,hide_index=True)
        st.download_button('⬇️ Exportar histórico',vis[cols].to_csv(index=False).encode('utf-8-sig'),'historico_passagem_turno.csv','text/csv')
