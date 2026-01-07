import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import io
import os
import tempfile
import uuid
import json

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Sistema de Rotas Fitesa", layout="wide")

# --- CONEXÃO COM GOOGLE SHEETS ---
NOME_PLANILHA = "SistemaRotasDB"

@st.cache_resource(ttl=600)
def connect_to_gsheets():
    try:
        # Lê a string JSON dos segredos e converte
        json_str = st.secrets["gcp_service_account_json"]
        creds_dict = json.loads(json_str)
        
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open(NOME_PLANILHA)
        return sh
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}")
        return None

def get_worksheet(spreadsheet, sheet_name):
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        try:
            ws = spreadsheet.add_worksheet(title=sheet_name, rows=100, cols=10)
            return ws
        except:
            return None

def get_items(spreadsheet, tipo):
    ws = get_worksheet(spreadsheet, tipo.capitalize())
    if ws:
        vals = ws.col_values(1)
        return vals[1:] if len(vals) > 1 else []
    return []

def add_item(spreadsheet, tipo, nome):
    ws = get_worksheet(spreadsheet, tipo.capitalize())
    if ws:
        ws.append_row([nome])
        return True
    return False

def remove_item(spreadsheet, tipo, nome):
    ws = get_worksheet(spreadsheet, tipo.capitalize())
    if ws:
        try:
            cell = ws.find(nome, in_column=1)
            if cell:
                ws.delete_rows(cell.row)
                return True
        except:
            pass
    return False

def get_secoes(spreadsheet):
    ws = get_worksheet(spreadsheet, "Secoes")
    if ws:
        data = ws.get_all_values()
        if len(data) > 1:
            return [(i + 2, row[0]) for i, row in enumerate(data[1:])]
    return []

def add_secao(spreadsheet, titulo):
    return add_item(spreadsheet, "Secoes", titulo)

def remove_secao(spreadsheet, row_index):
    ws = get_worksheet(spreadsheet, "Secoes")
    if ws:
        try:
            ws.delete_rows(row_index)
            return True
        except:
            return False

# --- FUNÇÕES DE HISTÓRICO DE ROTAS (DB) ---
def registrar_inicio_rota(spreadsheet, id_rota, lider):
    ws = get_worksheet(spreadsheet, "Historico_Andamento")
    if ws:
        data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([id_rota, data_hora, lider, "Em Andamento"])

def finalizar_rota_db(spreadsheet, id_rota):
    ws = get_worksheet(spreadsheet, "Historico_Andamento")
    if ws:
        try:
            cell = ws.find(id_rota, in_column=1)
            if cell:
                ws.update_cell(cell.row, 4, "Concluída")
        except:
            pass

# --- GERAÇÃO DE PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Relatório de Rota da Liderança', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def create_pdf(form_data, secoes_data):
    pdf = PDF()
    pdf.add_page()
    
    # 1. Cabeçalho
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, '1. Identificação', 0, 1)
    pdf.set_font('Arial', '', 12)
    
    texto_id = f"ID Rota: {form_data.get('id_rota', 'N/A')}\n"
    texto_dados = (f"Data: {form_data['data']}\n"
                   f"Líder: {form_data['lider']}\n"
                   f"Turma: {form_data['turma']}\n"
                   f"Rota: {form_data['rota']}\n"
                   f"Máquina: {form_data['maquina']}")
    
    pdf.multi_cell(0, 7, texto_id + texto_dados)
    pdf.ln(5)

    # 2. Seções
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, '2. Detalhes da Rotina (Checklist)', 0, 1)

    temp_dir = tempfile.mkdtemp()
    
    for i, secao in enumerate(secoes_data):
        if i > 0 and i % 2 == 0:
            pdf.add_page()
            
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, f"Item: {secao['titulo']}", 0, 1)
        
        pdf.set_font('Arial', '', 11)
        obs_txt = secao['obs'] if secao['obs'] else "Sem observações."
        pdf.multi_cell(0, 6, f"Obs: {obs_txt}")
        
        if secao['foto']:
            tpath = os.path.join(temp_dir, f"sec_{secao['id']}.png")
            with open(tpath, "wb") as f:
                f.write(secao['foto'].getbuffer())
            try:
                pdf.image(tpath, x=20, w=100)
            except:
                pass
            os.remove(tpath)
        pdf.ln(5)
        
    try: os.rmdir(temp_dir)
    except: pass

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()

# --- INTERFACE: ADMINISTRAÇÃO ---
def page_admin(spreadsheet):
    st.title("Área de Administração")
    
    pwd = st.text_input("Senha ADM", type="password")
    
    if pwd != st.secrets["ADMIN_PASS"]:
        st.warning("Senha incorreta.")
        return

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Líderes", "Turmas", "Rotas", "Máquinas", "Seções", "Histórico Logs"])

    configs = [
        ("Líderes", "lideres", tab1),
        ("Turmas", "turmas", tab2),
        ("Rotas", "rotas", tab3),
        ("Máquinas", "maquinas", tab4)
    ]

    for titulo, tipo, tab in configs:
        with tab:
            st.subheader(f"Gerenciar {titulo}")
            with st.form(f"add_{tipo}"):
                novo = st.text_input("Nome")
                if st.form_submit_button("Adicionar"):
                    if add_item(spreadsheet, tipo, novo):
                        st.success("Adicionado!")
                        st.cache_data.clear()
            
            st.divider()
            items = get_items(spreadsheet, tipo)
            for item in items:
                c1, c2 = st.columns([4,1])
                c1.write(item)
                if c2.button("X", key=f"del_{tipo}_{item}"):
                    remove_item(spreadsheet, tipo, item)
                    st.cache_data.clear()
                    st.rerun()

    with tab5: 
        st.subheader("Seções da Rotina")
        with st.form("add_sec"):
            t = st.text_input("Título Seção")
            if st.form_submit_button("Criar"):
                add_secao(spreadsheet, t)
                st.cache_data.clear()
        
        secoes = get_secoes(spreadsheet)
        for idx, nome in secoes:
            c1, c2 = st.columns([4,1])
            c1.write(nome)
            if c2.button("X", key=f"del_sec_{idx}"):
                remove_secao(spreadsheet, idx)
                st.cache_data.clear()
                st.rerun()

    with tab6:
        st.subheader("Log de Rotas Iniciadas")
        ws_hist = get_worksheet(spreadsheet, "Historico_Andamento")
        if ws_hist:
            dados = ws_hist.get_all_records()
            if dados:
                df = pd.DataFrame(dados)
                st.dataframe(df)
            else:
                st.info("Sem histórico.")

# --- LÓGICA DE ESTADO ---
def init_session_state():
    if 'rascunhos_rotas' not in st.session_state:
        st.session_state['rascunhos_rotas'] = {} 
    if 'rota_ativa_id' not in st.session_state:
        st.session_state['rota_ativa_id'] = None

# --- INTERFACE: NOVA ROTA / LISTA ---
def page_inicio_lista(spreadsheet):
    st.title("Central de Rotas")
    
    # 1. INICIAR NOVA ROTA
    st.subheader("🚀 Iniciar Nova Rota")
    
    lideres = get_items(spreadsheet, "Lideres")
    maquinas = get_items(spreadsheet, "Maquinas")
    turmas = get_items(spreadsheet, "Turmas")
    rotas_opcoes = get_items(spreadsheet, "Rotas")

    c1, c2 = st.columns(2)
    lider_sel = c1.selectbox("Líder", [""] + lideres)
    maq_sel = c1.selectbox("Máquina", [""] + maquinas)
    turma_sel = c2.selectbox("Turma", [""] + turmas)
    rota_sel = c2.selectbox("Rota", [""] + rotas_opcoes)

    if st.button("COMEÇAR ROTA", type="primary"):
        if not lider_sel or not maq_sel:
            st.error("Selecione pelo menos Líder e Máquina.")
        else:
            novo_id = f"ROTA-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
            
            nova_rota = {
                "id": novo_id,
                "inicio": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "dados": {
                    "lider": lider_sel,
                    "maquina": maq_sel,
                    "turma": turma_sel,
                    "rota": rota_sel,
                    "data": datetime.now().strftime("%d/%m/%Y"),
                    "id_rota": novo_id
                },
                "respostas_secoes": {} 
            }
            
            st.session_state['rascunhos_rotas'][novo_id] = nova_rota
            st.session_state['rota_ativa_id'] = novo_id
            
            registrar_inicio_rota(spreadsheet, novo_id, lider_sel)
            
            st.success("Rota Criada! Redirecionando...")
            st.rerun()

    st.divider()

    # 2. CONTINUAR
    st.subheader("📂 Rotas em Andamento (Pendentes)")
    
    rotas_abertas = st.session_state['rascunhos_rotas']
    
    if not rotas_abertas:
        st.info("Nenhuma rota iniciada neste dispositivo.")
    else:
        for rid, rdata in rotas_abertas.items():
            qtd_fotos = 0
            # Conta quantas fotos já foram salvas nas seções
            for k, v in rdata['respostas_secoes'].items():
                if v.get('foto'):
                    qtd_fotos += 1

            with st.expander(f"📍 {rdata['inicio']} - {rdata['dados']['lider']} (Máq: {rdata['dados']['maquina']})"):
                st.write(f"ID: {rid}")
                st.write(f"Fotos nas seções: {qtd_fotos}")
                
                col_btn1, col_btn2 = st.columns(2)
                if col_btn1.button("Continuar Rota", key=f"btn_{rid}"):
                    st.session_state['rota_ativa_id'] = rid
                    st.rerun()
                
                if col_btn2.button("Descartar/Excluir", key=f"del_{rid}"):
                    del st.session_state['rascunhos_rotas'][rid]
                    if st.session_state['rota_ativa_id'] == rid:
                        st.session_state['rota_ativa_id'] = None
                    st.rerun()

# --- INTERFACE: FORMULÁRIO DA ROTA ---
def page_formulario_rota(spreadsheet):
    rid = st.session_state['rota_ativa_id']
    # Verificação de segurança
    if not rid or rid not in st.session_state['rascunhos_rotas']:
        st.warning("Nenhuma rota selecionada. Volte ao início.")
        if st.button("Voltar"):
            st.session_state['rota_ativa_id'] = None
            st.rerun()
        return

    # Pega a referência do objeto da rota na memória
    rota_obj = st.session_state['rascunhos_rotas'][rid]
    dados = rota_obj['dados']
    respostas = rota_obj['respostas_secoes'] # Link direto para o dicionário
    
    st.title(f"Preenchendo: {dados['rota']}")
    st.caption(f"Líder: {dados['lider']} | Máquina: {dados['maquina']} | ID: {rid}")
    
    if st.button("⬅️ Salvar Rascunho e Voltar"):
        st.session_state['rota_ativa_id'] = None
        st.rerun()

    st.divider()

    secoes_db = get_secoes(spreadsheet)
    
    # --- LOOP DAS SEÇÕES (SEM FORMULÁRIO GIGANTE) ---
    # Isso permite salvar cada item individualmente assim que interage
    
    st.subheader("Checklist da Rotina")
    st.info("As fotos e observações são salvas automaticamente ao preencher.")

    for idx_secao, titulo_secao in secoes_db:
        st.markdown(f"--- \n ### {titulo_secao}")
        
        chave_item = str(idx_secao)
        
        # Garante que existe o dicionário para esse item
        if chave_item not in respostas:
            respostas[chave_item] = {'obs': '', 'foto': None}
        
        # 1. CAMPO DE OBSERVAÇÃO
        # O on_change garante que salve ao sair do campo
        def atualizar_obs(key=chave_item):
             respostas[key]['obs'] = st.session_state[f"obs_{rid}_{key}"]

        st.text_area(
            "Observação:",
            value=respostas[chave_item]['obs'],
            key=f"obs_{rid}_{chave_item}",
            on_change=atualizar_obs
        )
        
        # 2. LÓGICA DA FOTO (Trava e Destrava)
        foto_salva = respostas[chave_item]['foto']

        if foto_salva:
            # Se já tem foto, MOSTRA A FOTO e botão de remover
            st.image(foto_salva, caption="Foto Salva", width=300)
            if st.button("🗑️ Remover/Refazer Foto", key=f"del_foto_{rid}_{chave_item}"):
                respostas[chave_item]['foto'] = None
                st.rerun() # Recarrega para mostrar a câmera novamente
        else:
            # Se não tem foto, MOSTRA A CÂMERA
            foto_nova = st.camera_input(f"Foto: {titulo_secao}", key=f"cam_{rid}_{chave_item}")
            
            if foto_nova:
                # Assim que tira a foto, salva no dicionário e recarrega a página
                respostas[chave_item]['foto'] = foto_nova
                st.toast(f"Foto de '{titulo_secao}' salva!")
                st.rerun()

    st.divider()
    
    # Botão Final (fora do loop)
    if st.button("✅ FINALIZAR ROTA E GERAR PDF", type="primary"):
        # Prepara dados para o PDF
        dados_para_pdf = []
        for idx_secao, titulo_secao in secoes_db:
            chave_item = str(idx_secao)
            item_resp = respostas.get(chave_item, {'obs': '', 'foto': None})
            
            dados_para_pdf.append({
                "id": idx_secao,
                "titulo": titulo_secao,
                "obs": item_resp['obs'],
                "foto": item_resp['foto']
            })

        # Gera PDF
        pdf_bytes = create_pdf(dados, dados_para_pdf)
        
        # Atualiza Status no Banco
        finalizar_rota_db(spreadsheet, rid)
        
        # Prepara Download
        nome_arq = f"Relatorio_{dados['lider']}_{rid}.pdf"
        st.session_state['pdf_pronto'] = {'bytes': pdf_bytes, 'nome': nome_arq}
        
        # Limpa o rascunho
        del st.session_state['rascunhos_rotas'][rid]
        st.session_state['rota_ativa_id'] = None
        
        st.success("Relatório gerado com sucesso!")
        st.rerun()

def page_download():
    st.title("Relatório Pronto")
    dados = st.session_state['pdf_pronto']
    
    st.download_button(
        label="📥 BAIXAR PDF AGORA",
        data=dados['bytes'],
        file_name=dados['nome'],
        mime="application/pdf"
    )
    
    if st.button("Iniciar Nova Rota"):
        del st.session_state['pdf_pronto']
        st.rerun()

# --- MAIN ---
def main():
    init_session_state()
    
    if 'pdf_pronto' in st.session_state:
        page_download()
        return

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/2910/2910795.png", width=50)
        st.title("Menu")
        if not st.session_state.logged_in:
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            if st.button("Entrar"):
                if u == st.secrets["LOGIN_USER"] and p == st.secrets["LOGIN_PASS"]:
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("Login inválido")
            st.stop()
        else:
            st.success(f"Logado: {st.secrets['LOGIN_USER']}")
            modo = st.radio("Navegar", ["Realizar Rota", "Administração"])
            if st.button("Sair"):
                st.session_state.logged_in = False
                st.rerun()

    sh = connect_to_gsheets()
    if not sh:
        st.stop()

    if modo == "Administração":
        page_admin(sh)
    else:
        if st.session_state['rota_ativa_id']:
            page_formulario_rota(sh)
        else:
            page_inicio_lista(sh)

if __name__ == "__main__":
    main()
