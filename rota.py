
import streamlit as st
import gspread
from datetime import datetime
from fpdf import FPDF
import io
import os
import tempfile
import json

# --- CONFIGURAÇÃO DO BANCO DE DADOS (Google Sheets) ---
NOME_PLANILHA = "SistemaRotasDB"

@st.cache_resource(ttl=600)
def connect_to_gsheets():
    try:
        creds_json_str = st.secrets["gcp_service_account_json"]
        creds_dict = json.loads(creds_json_str)
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open(NOME_PLANILHA)
        return sh
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: '{e}'.")
        return None

def get_worksheet(spreadsheet, sheet_name):
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        return None

def get_items(spreadsheet, tipo):
    ws = get_worksheet(spreadsheet, tipo.capitalize())
    if ws:
        return ws.col_values(1)[1:]
    return []

def get_secoes(spreadsheet):
    ws = get_worksheet(spreadsheet, "Secoes")
    if ws:
        secoes_data = ws.get_all_values()
        if len(secoes_data) > 1:
            return [(i + 2, secao[0]) for i, secao in enumerate(secoes_data[1:])]
    return []

# --- GERAÇÃO DE PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Relatório de Rota da Liderança', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')
        self.cell(0, 10, 'Gerado pelo Sistema de Rotas', 0, 0, 'R')

def create_pdf(form_data, secoes_data):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, '1. Identificação da Rota', 0, 1)
    pdf.set_font('Arial', '', 12)
    pdf.multi_cell(0, 8, f"Data: {form_data['data'].strftime('%d/%m/%Y')}\n"
                         f"Líder: {form_data['lider']}\n"
                         f"Turma: {form_data['turma']}\n"
                         f"Rota: {form_data['rota']}\n"
                         f"Máquina: {form_data['maquina']}")
    pdf.ln(10)
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, '2. Detalhes da Rotina', 0, 1)
    temp_dir = tempfile.mkdtemp()
    for i, secao in enumerate(secoes_data):
        if i > 0:
            pdf.add_page()
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, f"Seção: {secao['titulo']}", 0, 1)
        pdf.set_font('Arial', '', 12)
        pdf.multi_cell(0, 8, f"Observação: {secao['obs']}")
        if secao['foto']:
            foto_bytes = secao['foto'].read()
            temp_img_path = os.path.join(temp_dir, f"temp_img_{secao['id']}.png")
            with open(temp_img_path, 'wb') as f:
                f.write(foto_bytes)
            try:
                pdf.image(temp_img_path, x=30, w=150)
            except Exception as e:
                pdf.set_text_color(255, 0, 0)
                pdf.cell(0, 10, f"Erro ao adicionar imagem: {e}", 0, 1)
                pdf.set_text_color(0, 0, 0)
            os.remove(temp_img_path)
        pdf.ln(5)
    try:
        os.rmdir(temp_dir)
    except OSError:
        pass
    pdf_buffer = io.BytesIO()
    pdf.output(pdf_buffer)
    return pdf_buffer.getvalue()

# --- NOVAS FUNCIONALIDADES ---
if "historico_rotas" not in st.session_state:
    st.session_state.historico_rotas = {}
if "historico_concluido" not in st.session_state:
    st.session_state.historico_concluido = {}

def page_historico():
    st.title("Histórico de Rotas")
    if not st.session_state.historico_rotas:
        st.info("Nenhuma rota ativa.")
    else:
        for rota_id, rota_data in st.session_state.historico_rotas.items():
            st.subheader(f"{rota_data['nome']} - {rota_data['timestamp']}")
            if st.button(f"Continuar {rota_data['nome']}", key=f"continuar_{rota_id}"):
                st.session_state.rota_atual = rota_id
                st.rerun()

def page_rota(spreadsheet):
    st.title("Realizar Rota")
    if "rota_atual" not in st.session_state:
        lideres = get_items(spreadsheet, 'lideres')
        turmas = get_items(spreadsheet, 'turmas')
        rotas = get_items(spreadsheet, 'rotas')
        maquinas = get_items(spreadsheet, 'maquinas')
        secoes = get_secoes(spreadsheet)
        if not all([lideres, turmas, rotas, maquinas, secoes]):
            st.warning("Cadastre dados na área ADM.")
            return
        st.header("Iniciar Nova Rota")
        lider = st.selectbox("Líder", lideres)
        turma = st.selectbox("Turma", turmas)
        rota = st.selectbox("Rota", rotas)
        maquina = st.selectbox("Máquina", maquinas)
        if st.button("Começar Rota"):
            rota_id = f"{rota}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            st.session_state.historico_rotas[rota_id] = {
                "nome": rota,
                "timestamp": datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                "form_data": {
                    "data": datetime.now(),
                    "lider": lider,
                    "turma": turma,
                    "rota": rota,
                    "maquina": maquina
                },
                "secoes_data": []
            }
            st.session_state.rota_atual = rota_id
            st.rerun()
    else:
        rota_id = st.session_state.rota_atual
        rota_info = st.session_state.historico_rotas[rota_id]
        st.header(f"Rota: {rota_info['nome']} - {rota_info['timestamp']}")
        secoes = get_secoes(spreadsheet)
        for row_index, secao_titulo in secoes:
            st.subheader(secao_titulo)
            foto = st.camera_input("Tirar Foto", key=f"foto_{row_index}")
            obs = st.text_area("Observações", key=f"obs_{row_index}")
            if foto or obs:
                rota_info['secoes_data'].append({
                    "id": row_index,
                    "titulo": secao_titulo,
                    "foto": foto,
                    "obs": obs,
                    "timestamp": datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                })
        if st.button("Gerar Relatório PDF"):
            pdf_bytes = create_pdf(rota_info['form_data'], rota_info['secoes_data'])
            filename = f"Rota_{rota_info['form_data']['lider']}_{rota_info['form_data']['data'].strftime('%d-%m-%Y')}.pdf"
            st.download_button("Baixar PDF", data=pdf_bytes, file_name=filename, mime="application/pdf")
            st.session_state.historico_concluido[rota_id] = rota_info
            del st.session_state.historico_rotas[rota_id]
            del st.session_state.rota_atual
            st.success("Relatório gerado e rota movida para histórico concluído.")

def page_admin(spreadsheet):
    st.title("Área de Administração")
    admin_password = st.text_input("Senha ADM", type="password")
    if admin_password != st.secrets["ADMIN_PASS"]:
        st.warning("Acesso restrito.")
        return
    st.success("Acesso concedido.")
    tab1, tab2 = st.tabs(["Gerenciar Dados", "Histórico Concluído"])
    with tab1:
        st.write("Gerenciamento de líderes, turmas, rotas, máquinas e seções.")
    with tab2:
        if not st.session_state.historico_concluido:
            st.info("Nenhuma rota concluída.")
        else:
            for rota_id, rota_data in st.session_state.historico_concluido.items():
                st.write(f"{rota_data['nome']} - {rota_data['timestamp']} - {len(rota_data['secoes_data'])} registros")

def main():
    st.set_page_config(page_title="Rotas", layout="wide")
    spreadsheet = connect_to_gsheets()
    if spreadsheet is None:
        st.error("Falha ao carregar banco de dados.")
        return
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if not st.session_state.logged_in:
        st.sidebar.title("Login")
        user = st.sidebar.text_input("Usuário")
        pwd = st.sidebar.text_input("Senha", type="password")
        if st.sidebar.button("Entrar"):
            if user == st.secrets["LOGIN_USER"] and pwd == st.secrets["LOGIN_PASS"]:
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.sidebar.error("Usuário ou senha inválidos.")
        st.info("Faça login para usar o sistema.")
    else:
        st.sidebar.title("Navegação")
        pagina = st.sidebar.radio("Página:", ["Realizar Rota", "Histórico", "Área de Administração"])
        if pagina == "Realizar Rota":
            page_rota(spreadsheet)
        elif pagina == "Histórico":
            page_historico()
        elif pagina == "Área de Administração":
            page_admin(spreadsheet)

if __name__ == "__main__":
    main()
