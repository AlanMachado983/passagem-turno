import os
import sqlite3
from datetime import datetime, date, timedelta
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Passagem de Turno | ADIMAX', page_icon='📦', layout='wide')

DB='passagem_turno.db'

def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    c=conn(); cur=c.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS planejamento (
        id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, turno TEXT, operacao TEXT,
        indicador TEXT, planejado REAL, atualizado_em TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS passagens (
        id INTEGER PRIMARY KEY AUTOINCREMENT, criado_em TEXT, data TEXT, turno TEXT,
        area TEXT, operacao TEXT, responsavel TEXT,
        headcount INTEGER DEFAULT 0, ausencias INTEGER DEFAULT 0, presentes INTEGER DEFAULT 0,
        absenteismo REAL DEFAULT 0,
        cargas_realizadas REAL DEFAULT 0, toneladas_realizadas REAL DEFAULT 0,
        veiculos_trabalhados REAL DEFAULT 0, veiculos_carregados REAL DEFAULT 0,
        veiculos_pendentes REAL DEFAULT 0, uz_paletes REAL DEFAULT 0, pd_espera REAL DEFAULT 0,
        transbordo_total REAL DEFAULT 0, toneladas_estoque REAL DEFAULT 0, paletes_estoque REAL DEFAULT 0,
        planejado_cargas REAL DEFAULT 0, planejado_ton REAL DEFAULT 0, planejado_veiculos REAL DEFAULT 0,
        gap_cargas REAL DEFAULT 0, gap_ton REAL DEFAULT 0, gap_veiculos REAL DEFAULT 0,
        ating_cargas REAL DEFAULT 0, ating_ton REAL DEFAULT 0, ating_veiculos REAL DEFAULT 0,
        ofensor TEXT, observacoes TEXT, status TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS pendencias (
        id INTEGER PRIMARY KEY AUTOINCREMENT, passagem_id INTEGER, carga TEXT, cliente TEXT,
        situacao TEXT, motivo TEXT, detalhe TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS ausencias_detalhe (
        id INTEGER PRIMARY KEY AUTOINCREMENT, passagem_id INTEGER, nome TEXT, motivo TEXT)''')
    c.commit(); c.close()
init_db()

def query(sql, params=()):
    c=conn(); df=pd.read_sql_query(sql,c,params=params); c.close(); return df

def scalar_plan(d,t,o,i):
    df=query('SELECT planejado FROM planejamento WHERE data=? AND turno=? AND operacao=? AND indicador=? ORDER BY id DESC LIMIT 1',(str(d),t,o,i))
    return float(df.iloc[0,0]) if not df.empty else 0.0

def pct(real, plan): return (real/plan*100) if plan else 0.0

def status_auto(pend, atingimentos):
    vals=[v for v in atingimentos if v>0]
    if pend>=3 or (vals and min(vals)<80): return '🔴 Crítico'
    if pend>0 or (vals and min(vals)<95): return '🟡 Atenção'
    return '🟢 Normal'

st.markdown('''<style>
.block-container{padding-top:1.1rem}.hero{background:linear-gradient(90deg,#111,#2a2a2a);padding:22px 28px;border-radius:16px;border-left:8px solid #f5b400;color:white;margin-bottom:16px}.hero h1{margin:0;font-size:34px}.hero p{margin:5px 0 0;color:#ddd}.kpi{border:1px solid #e6e6e6;border-radius:14px;padding:14px;background:white}.stButton>button{border-radius:10px;font-weight:700}.status{font-size:22px;font-weight:800}.small{color:#666;font-size:13px}
</style>''',unsafe_allow_html=True)

if os.path.exists('assets/fabrica.png'):
    st.image('assets/fabrica.png', use_container_width=True)
st.markdown('<div class="hero"><h1>Passagem de Turno</h1><p>Logística • CDA 01 • CDA 02 • Estoque</p></div>',unsafe_allow_html=True)

with st.sidebar:
    st.markdown('## ADIMAX')
    if os.path.exists('assets/caminhoes.png'): st.image('assets/caminhoes.png',use_container_width=True)
    pagina=st.radio('Navegação',['📝 Nova Passagem','📋 Planejamento','👁️ Visão Atual','📊 Semana','🕘 Histórico','🖨️ Imprimir'])

if pagina=='📋 Planejamento':
    st.header('📋 Planejamento do turno')
    c1,c2,c3=st.columns(3)
    d=c1.date_input('Data',date.today()); t=c2.selectbox('Turno',['T1','T2','T3']); o=c3.selectbox('Operação',['CDA 01 - Separação','CDA 01 - Carregamento','CDA 02','Estoque'])
    st.caption('Cadastre apenas os indicadores que possuem planejamento confiável.')
    if o=='CDA 01 - Separação': inds=['Cargas','Toneladas']
    elif o=='CDA 01 - Carregamento': inds=['Veículos']
    elif o=='CDA 02': inds=['Cargas','Paletes/UZs']
    else: inds=['Toneladas','Paletes']
    vals={}
    cols=st.columns(len(inds))
    for col,ind in zip(cols,inds): vals[ind]=col.number_input(f'Planejado - {ind}',min_value=0.0,step=1.0)
    if st.button('💾 Salvar planejamento',type='primary'):
        c=conn(); cur=c.cursor()
        for ind,v in vals.items(): cur.execute('INSERT INTO planejamento(data,turno,operacao,indicador,planejado,atualizado_em) VALUES(?,?,?,?,?,?)',(str(d),t,o,ind,v,datetime.now().isoformat(timespec='seconds')))
        c.commit();c.close();st.success('Planejamento salvo.')
    df=query('SELECT data,turno,operacao,indicador,planejado,atualizado_em FROM planejamento ORDER BY id DESC LIMIT 30')
    st.dataframe(df,use_container_width=True,hide_index=True)

elif pagina=='📝 Nova Passagem':
    st.header('📝 Nova passagem')
    a,b,c,dcol=st.columns(4)
    resp=a.text_input('Responsável pela passagem',placeholder='Nome do líder')
    area=b.selectbox('Área',['CDA 01','CDA 02','Estoque'])
    turno=c.selectbox('Turno',['T1','T2','T3'])
    data_reg=dcol.date_input('Data',date.today())
    operacao='CDA 02' if area=='CDA 02' else ('Estoque' if area=='Estoque' else st.selectbox('Operação',['CDA 01 - Separação','CDA 01 - Carregamento']))

    st.subheader('👥 Equipe')
    h1,h2=st.columns(2); hc=int(h1.number_input('Headcount do turno',min_value=0,step=1)); aus=int(h2.number_input('Ausências',min_value=0,step=1))
    presentes=max(hc-aus,0); abs_pct=(aus/hc*100) if hc else 0
    m1,m2,m3=st.columns(3);m1.metric('Presentes',presentes);m2.metric('Equipe presente',f'{(100-abs_pct):.1f}%');m3.metric('Absenteísmo',f'{abs_pct:.1f}%')
    aus_det=[]
    if aus:
        st.markdown('**Detalhe das ausências**')
        for i in range(aus):
            x,y=st.columns(2); nome=x.text_input(f'Nome {i+1}',key=f'an{i}'); mot=y.selectbox(f'Motivo {i+1}',['Atestado','Falta','Afastado','Férias','Folga compensatória','Declaração médica','Outro'],key=f'am{i}'); aus_det.append((nome,mot))

    cargas=ton=vt=vc=vp=uz=pd_e=trans=ton_est=pal_est=0.0
    pc=pt=pv=0.0
    pend=[]
    st.subheader('📦 Resultado do turno')
    if operacao=='CDA 01 - Separação':
        pc=scalar_plan(data_reg,turno,operacao,'Cargas'); pt=scalar_plan(data_reg,turno,operacao,'Toneladas')
        x,y=st.columns(2); cargas=x.number_input('Cargas separadas',min_value=0.0,step=1.0); ton=y.number_input('Peso separado (t)',min_value=0.0,step=0.1,format='%.2f')
        st.info(f'Planejado: {pc:g} cargas | {pt:.2f} t')
        n=int(st.number_input('Quantidade de cargas pendentes',min_value=0,step=1))
        for i in range(n):
            st.markdown(f'**Pendência {i+1}**'); q1,q2,q3=st.columns(3); cg=q1.text_input('Carga',key=f'pcg{i}'); cli=q2.text_input('Cliente',key=f'pcl{i}'); sit=q3.selectbox('Situação',['P&D','Separação não iniciada','Em separação','Aguardando produto','Outra'],key=f'psi{i}'); q4,q5=st.columns(2); mot=q4.selectbox('Motivo',['Falta de produto','Sistema/Integração','Mão de obra','Equipamento','Qualidade','Operacional','Outro'],key=f'pmo{i}'); det=q5.text_input('Detalhe',key=f'pde{i}'); pend.append((cg,cli,sit,mot,det))
    elif operacao=='CDA 01 - Carregamento':
        pv=scalar_plan(data_reg,turno,operacao,'Veículos')
        x,y=st.columns(2); vt=x.number_input('Veículos pegos para carregar',min_value=0.0,step=1.0); vp=y.number_input('Veículos que ficaram para o próximo turno',min_value=0.0,step=1.0); vc=max(vt-vp,0)
        st.metric('Veículos carregados no turno',f'{vc:g}'); st.info(f'Planejado: {pv:g} veículos')
        for i in range(int(vp)):
            st.markdown(f'**Veículo pendente {i+1}**'); q1,q2=st.columns(2); cg=q1.text_input('Carga',key=f'vcg{i}'); mot=q2.selectbox('Motivo',['Carga não integrada','Separação não iniciada','Veículo não se apresentou','Carga batida / próximo turno','Falta de produto','T.I./Körber','Problema operacional','Outro'],key=f'vmo{i}'); det=st.text_input('Detalhe / observação',key=f'vde{i}'); pend.append((cg,'','Carregamento pendente',mot,det))
    elif operacao=='CDA 02':
        pc=scalar_plan(data_reg,turno,operacao,'Cargas'); pp=scalar_plan(data_reg,turno,operacao,'Paletes/UZs')
        x,y,z=st.columns(3); cargas=x.number_input('Cargas separadas',min_value=0.0,step=1.0); uz=y.number_input('Paletes / UZs separados',min_value=0.0,step=1.0); pd_e=z.number_input('P&D Espera',min_value=0.0,step=1.0)
        st.info(f'Planejado: {pc:g} cargas | {pp:g} paletes/UZs')
        st.markdown('**Transbordos (paletes)**'); cs=st.columns(4); tr=[]
        for col,nome in zip(cs,['Ensaque','Úmidos','Biscoito','Expedição']): tr.append(col.number_input(nome,min_value=0.0,step=1.0))
        cs2=st.columns(3)
        for col,nome in zip(cs2,['Estoque','Fornecedores','Outros']): tr.append(col.number_input(nome,min_value=0.0,step=1.0))
        trans=sum(tr); pt=pp
    else:
        pt=scalar_plan(data_reg,turno,operacao,'Toneladas'); pp=scalar_plan(data_reg,turno,operacao,'Paletes')
        x,y=st.columns(2); ton_est=x.number_input('Toneladas puxadas da produção',min_value=0.0,step=0.1); pal_est=y.number_input('Paletes movimentados',min_value=0.0,step=1.0)
        st.info(f'Planejado: {pt:.2f} t | {pp:g} paletes')

    gc=cargas-pc if pc else 0; gt=(ton if operacao=='CDA 01 - Separação' else ton_est)-pt if pt else 0; gv=vc-pv if pv else 0
    ac=pct(cargas,pc); at=pct((ton if operacao=='CDA 01 - Separação' else ton_est),pt); av=pct(vc,pv)
    st.subheader('🎯 Planejado × Realizado')
    k1,k2,k3=st.columns(3)
    if operacao in ['CDA 01 - Separação','CDA 02']: k1.metric('Cargas',f'{cargas:g}',f'{gc:+g} vs planejado' if pc else 'Sem planejado'); k2.metric('Atingimento cargas',f'{ac:.1f}%' if pc else '—')
    if operacao in ['CDA 01 - Separação','Estoque']: k3.metric('Atingimento toneladas',f'{at:.1f}%' if pt else '—')
    if operacao=='CDA 01 - Carregamento': k1.metric('Carregados',f'{vc:g}',f'{gv:+g} vs planejado' if pv else 'Sem planejado'); k2.metric('Atingimento',f'{av:.1f}%' if pv else '—')

    st.subheader('⚠️ Fechamento')
    of=st.selectbox('Principal ofensor',['Sem ofensor','Falta de produto/estoque','Mão de obra','Sistema/Integração','WMS/Körber','Atraso/ausência de veículo','Equipamento','Qualidade','Retrabalho','Operacional','Outro'])
    obs=st.text_area('Observações / pontos de atenção para o próximo turno')
    stat=status_auto(len(pend),[ac,at,av]); st.markdown(f'<div class="status">Status sugerido: {stat}</div>',unsafe_allow_html=True)
    if st.button('💾 Salvar passagem',type='primary',use_container_width=True):
        if not resp.strip(): st.error('Informe o responsável pela passagem.')
        elif aus>hc and hc>0: st.error('Ausências não pode ser maior que o headcount.')
        else:
            c=conn();cur=c.cursor();cur.execute('''INSERT INTO passagens(criado_em,data,turno,area,operacao,responsavel,headcount,ausencias,presentes,absenteismo,cargas_realizadas,toneladas_realizadas,veiculos_trabalhados,veiculos_carregados,veiculos_pendentes,uz_paletes,pd_espera,transbordo_total,toneladas_estoque,paletes_estoque,planejado_cargas,planejado_ton,planejado_veiculos,gap_cargas,gap_ton,gap_veiculos,ating_cargas,ating_ton,ating_veiculos,ofensor,observacoes,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (datetime.now().isoformat(timespec='seconds'),str(data_reg),turno,area,operacao,resp,hc,aus,presentes,abs_pct,cargas,ton,vt,vc,vp,uz,pd_e,trans,ton_est,pal_est,pc,pt,pv,gc,gt,gv,ac,at,av,of,obs,stat)); pid=cur.lastrowid
            for r in pend: cur.execute('INSERT INTO pendencias(passagem_id,carga,cliente,situacao,motivo,detalhe) VALUES(?,?,?,?,?,?)',(pid,*r))
            for n,m in aus_det:
                if n.strip(): cur.execute('INSERT INTO ausencias_detalhe(passagem_id,nome,motivo) VALUES(?,?,?)',(pid,n,m))
            c.commit();c.close();st.success('Passagem salva com sucesso.')

elif pagina=='👁️ Visão Atual':
    st.header('👁️ Visão atual')
    df=query('SELECT * FROM passagens ORDER BY id DESC')
    if df.empty: st.info('Ainda não existem passagens salvas.')
    else:
        latest=df.groupby(['operacao','turno'],as_index=False).first()
        for _,r in latest.iterrows():
            with st.expander(f"{r['operacao']} • {r['turno']} • {r['status']}",expanded=True):
                c1,c2,c3,c4=st.columns(4); c1.metric('Responsável',r['responsavel']); c2.metric('Absenteísmo',f"{r['absenteismo']:.1f}%"); c3.metric('Cargas',f"{r['cargas_realizadas']:g}"); c4.metric('Toneladas',f"{r['toneladas_realizadas'] or r['toneladas_estoque']:.2f}")
                if r['observacoes']: st.write(r['observacoes'])

elif pagina=='📊 Semana':
    st.header('📊 Resumo semanal')
    hoje=date.today(); ini=hoje-timedelta(days=hoje.weekday()); fim=ini+timedelta(days=6)
    a,b=st.columns(2); di=a.date_input('Início',ini); dfim=b.date_input('Fim',fim)
    df=query('SELECT * FROM passagens WHERE data BETWEEN ? AND ? ORDER BY data',(str(di),str(dfim)))
    if df.empty: st.info('Sem registros no período.')
    else:
        c1,c2,c3,c4=st.columns(4); c1.metric('Passagens',len(df)); c2.metric('Cargas',f"{df.cargas_realizadas.sum():g}"); c3.metric('Toneladas',f"{(df.toneladas_realizadas.sum()+df.toneladas_estoque.sum()):.1f} t"); c4.metric('Absenteísmo médio',f"{df.absenteismo.mean():.1f}%")
        chart=df.groupby('data',as_index=False).agg(Cargas=('cargas_realizadas','sum'),Toneladas=('toneladas_realizadas','sum'))
        st.markdown('#### Evolução diária'); st.line_chart(chart.set_index('data'))
        st.markdown('#### Por operação'); st.dataframe(df.groupby('operacao',as_index=False).agg(Passagens=('id','count'),Cargas=('cargas_realizadas','sum'),Toneladas=('toneladas_realizadas','sum'),Absenteismo_medio=('absenteismo','mean')),use_container_width=True,hide_index=True)

elif pagina=='🕘 Histórico':
    st.header('🕘 Histórico')
    df=query('SELECT id,data,turno,operacao,responsavel,status,cargas_realizadas,toneladas_realizadas,veiculos_carregados,veiculos_pendentes,absenteismo,ofensor,observacoes,criado_em FROM passagens ORDER BY id DESC')
    if df.empty: st.info('Sem registros.')
    else:
        st.dataframe(df,use_container_width=True,hide_index=True)
        st.download_button('⬇️ Exportar CSV',df.to_csv(index=False).encode('utf-8-sig'),'historico_passagem.csv','text/csv')
        with st.expander('🗑️ Excluir registro'):
            rid=st.number_input('ID do registro',min_value=1,step=1); conf=st.checkbox('Confirmo a exclusão')
            if st.button('Excluir') and conf:
                c=conn();cur=c.cursor();cur.execute('DELETE FROM pendencias WHERE passagem_id=?',(rid,));cur.execute('DELETE FROM ausencias_detalhe WHERE passagem_id=?',(rid,));cur.execute('DELETE FROM passagens WHERE id=?',(rid,));c.commit();c.close();st.success('Registro excluído.');st.rerun()

else:
    st.header('🖨️ Passagem consolidada para impressão')
    a,b=st.columns(2); d=a.date_input('Data',date.today()); t=b.selectbox('Turno',['T1','T2','T3'])
    df=query('SELECT * FROM passagens WHERE data=? AND turno=? ORDER BY operacao',(str(d),t))
    if df.empty: st.info('Não há registros para esta data/turno.')
    else:
        st.markdown(f'## PASSAGEM DE TURNO — {d.strftime("%d/%m/%Y")} — {t}')
        resumo=[]
        for _,r in df.iterrows():
            realizado = r['toneladas_realizadas'] if r['operacao']=='CDA 01 - Separação' else (r['veiculos_carregados'] if r['operacao']=='CDA 01 - Carregamento' else (r['cargas_realizadas'] if r['operacao']=='CDA 02' else r['toneladas_estoque']))
            plan = r['planejado_ton'] if r['operacao'] in ['CDA 01 - Separação','Estoque'] else (r['planejado_veiculos'] if r['operacao']=='CDA 01 - Carregamento' else r['planejado_cargas'])
            resumo.append({'Operação':r['operacao'],'Planejado':plan,'Realizado':realizado,'Gap':realizado-plan if plan else None,'Atingimento %':pct(realizado,plan) if plan else None,'Status':r['status'],'Responsável':r['responsavel']})
        st.dataframe(pd.DataFrame(resumo),use_container_width=True,hide_index=True)
        st.markdown('### Pontos de atenção')
        for _,r in df.iterrows():
            st.markdown(f"**{r['operacao']}** — {r['status']} — Ofensor: {r['ofensor']}")
            if r['observacoes']: st.write(r['observacoes'])
        st.info('Use a opção de impressão do navegador para imprimir ou salvar esta visão em PDF. Na próxima etapa podemos gerar um PDF A4 formatado diretamente pelo app.')

st.caption('Protótipo V4 • Banco SQLite para validação. Para produção/múltiplos usuários, conectar a um banco persistente online.')
