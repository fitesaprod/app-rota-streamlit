import streamlit as st
import gspread # Substitui o sqlite3
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import io
import os
import tempfile

# --- CONFIGURAÇÃO DO BANCO DE DADOS (Google Sheets) ---

# Conecta ao Google Sheets usando os "Secrets" do Streamlit
def connect_to_gsheets():
    """Conecta ao Google Sheets usando as credenciais dos Secrets."""
    try:
        creds = st.secrets["gcp_service_account"]
        gc = gspread.service_account_from_dict(creds)
        # Abre a planilha pelo nome que demos no Bloco 1
        sh = gc.open("SistemaRotasDB")
        return sh
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}")
        return None

def get_items(sheet, tab_name):
    """Busca itens de uma aba específica (ex: 'Lideres')"""
    try:
        worksheet = sheet.worksheet(tab_name)
        # Pega todos os valores da coluna 1, exceto o cabeçalho "Nome"
        items = worksheet.col_values(1)[1:] 
        items.sort()
        return items
    except Exception as e:
        st.warning(f"Erro ao buscar dados da aba '{tab_name}': {e}")
        return []

def add_item(sheet, tab_name, nome):
    """Adiciona um novo item (ex: 'Lideres', 'nova maquina')"""
    try:
        worksheet = sheet.worksheet(tab_name)
        # Verifica se o item já existe
        cell = worksheet.find(nome, in_column=1)
        if cell:
            return False # Item já existe
        
        worksheet.append_row([nome])
        return True
    except Exception as e:
        st.error(f"Erro ao adicionar item em '{tab_name}': {e}")
        return False

def remove_item(sheet, tab_name, nome):
    """Remove um item"""
    try:
        worksheet = sheet.worksheet(tab_name)
        # Encontra o item na coluna 1
        cell = worksheet.find(nome, in_column=1)
        if cell:
            # Deleta a linha onde o item foi encontrado
            worksheet.delete_rows(cell.row)
            return True
        return False
    except Exception as e:
        st.error(f"Erro ao remover item de '{tab_name}': {e}")
        return False

# --- GERAÇÃO DE PDF (Esta função permanece quase idêntica) ---

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
    """Cria o PDF com todos os dados do formulário."""
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    
    # 1. Dados de Identificação
    pdf.cell(0, 10, '1. Identificação da Rota', 0, 1)
    pdf.set_font('Arial', '', 12)
    
    pdf.multi_cell(0, 8, f"Data: {form_data['data'].strftime('%d/%m/%Y')}\n"
                         f"Líder: {form_data['lider']}\n"
                         f"Turma: {form_data['turma']}\n"
                         f"Rota: {form_data['rota']}\n"
                         f"Máquina: {form_data['maquina']}")
    pdf.ln(10)

    # 2. Seções da Rotina
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, '2. Detalhes da Rotina', 0, 1)
    
    # O uso de tempfile AINDA é necessário para o fpdf
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
    
    os.rmdir(temp_dir)
    
    pdf_buffer = io.BytesIO()
    pdf.output(pdf_buffer)
    
    return pdf_buffer.getvalue()

# --- INTERFACE PRINCIPAL DO APP ---

def page_admin(sheet):
    """Página de Administração."""
    st.title("Área de Administração")
    
    # Senha da área ADM (lendo dos Secrets)
    admin_password = st.text_input("Digite a senha de ADM:", type="password", key="admin_pass")
    if admin_password != st.secrets["ADMIN_PASS"]:
        st.warning("Acesso restrito.")
        return

    st.success("Acesso de ADM concedido.")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Líderes", "Turmas", "Rotas", "Máquinas", "Seções"])

    # Mapeamento de tipo para UI
    tipos_gerenciamento = {
        "Líderes": ("Lideres", tab1),
        "Turmas": ("Turmas", tab2),
        "Rotas": ("Rotas", tab3),
        "Máquinas": ("Maquinas", tab4)
    }

    for nome_tab_ui, (nome_tab_db, tab) in tipos_gerenciamento.items():
        with tab:
            st.subheader(f"Gerenciar {nome_tab_ui}")
            
            with st.form(f"form_add_{nome_tab_db}", clear_on_submit=True):
                novo_nome = st.text_input(f"Novo(a) {nome_tab_ui.lower()[:-1]}")
                submitted = st.form_submit_button("Adicionar")
                if submitted and novo_nome:
                    if add_item(sheet, nome_tab_db, novo_nome):
                        st.success(f"{nome_tab_ui[:-1]} '{novo_nome}' adicionado(a).")
                    else:
                        st.error(f"Erro: {nome_tab_ui[:-1]} '{novo_nome}' já existe ou falha ao salvar.")
            
            st.divider()
            
            itens_db = get_items(sheet, nome_tab_db)
            if not itens_db:
                st.info(f"Nenhum(a) {nome_tab_ui.lower()} cadastrado(a).")
            else:
                st.write(f"**{nome_tab_ui} Cadastrados:**")
                for item_nome in itens_db:
                    col1, col2 = st.columns([0.8, 0.2])
                    col1.write(item_nome)
                    if col2.button(f"Remover", key=f"remove_{nome_tab_db}_{item_nome}"):
                        remove_item(sheet, nome_tab_db, item_nome)
                        st.rerun()

    # Gerenciamento de Seções
    with tab5:
        st.subheader("Gerenciar Seções da Rotina")
        st.info("Estas são as etapas que o líder preencherá.")
        
        with st.form("form_add_secao", clear_on_submit=True):
            novo_titulo = st.text_input("Título da nova seção")
            submitted = st.form_submit_button("Adicionar Seção")
            if submitted and novo_titulo:
                if add_item(sheet, "Secoes", novo_titulo):
                    st.success(f"Seção '{novo_titulo}' adicionada.")
                else:
                    st.error(f"Erro: Seção '{novo_titulo}' já existe ou falha ao salvar.")
        
        st.divider()
        
        secoes_db = get_items(sheet, "Secoes")
        if not secoes_db:
            st.info("Nenhuma seção cadastrada.")
        else:
            st.write("**Seções Cadastradas (na ordem):**")
            for secao_titulo in secoes_db:
                col1, col2 = st.columns([0.8, 0.2])
                col1.write(secao_titulo)
                if col2.button(f"Remover", key=f"remove_secao_{secao_titulo}"):
                    remove_item(sheet, "Secoes", secao_titulo)
                    st.rerun()

def page_rota(sheet):
    """Página principal de preenchimento da Rota."""
    st.title("Formulário de Rota da Liderança")

    # Carrega dados do Google Sheets para os dropdowns
    lideres = get_items(sheet, 'Lideres')
    turmas = get_items(sheet, 'Turmas')
    rotas = get_items(sheet, 'Rotas')
    maquinas = get_items(sheet, 'Maquinas')
    secoes_raw = get_items(sheet, 'Secoes')
    # Adiciona um ID falso para manter a lógica do app
    secoes = [(i+1, titulo) for i, titulo in enumerate(secoes_raw)]


    if not all([lideres, turmas, rotas, maquinas, secoes]):
        st.warning("Sistema não configurado. Vá para a 'Área de Administração' e cadastre Líderes, Turmas, Rotas, Máquinas e Seções.")
        return

    form_data = {}
    secoes_data = []

    with st.form("form_rota", clear_on_submit=True):
        st.header("1. Identificação")
        
        col1, col2 = st.columns(2)
        form_data['data'] = col1.date_input("Data", datetime.now())
        form_data['lider'] = col1.selectbox("Líder", lideres)
        form_data['turma'] = col2.selectbox("Turma", turmas)
        form_data['rota'] = col2.selectbox("Rota", rotas)
        form_data['maquina'] = st.selectbox("Máquina", maquinas)
        
        st.divider()
        st.header("2. Rotina")
        
        if not secoes:
            st.info("Nenhuma seção de rotina cadastrada na área ADM.")
        
        for secao_id, secao_titulo in secoes:
            st.subheader(secao_titulo)
            
            key_foto = f"foto_{secao_id}"
            key_obs = f"obs_{secao_id}"
            
            foto_capturada = st.camera_input("Tirar Foto", key=key_foto)
            obs = st.text_area("Observações", key=key_obs)
            
            secoes_data.append({
                "id": secao_id,
                "titulo": secao_titulo,
                "foto": foto_capturada,
                "obs": obs
            })

        st.divider()
        submitted = st.form_submit_button("Gerar Relatório PDF")

        if submitted:
            pdf_bytes = create_pdf(form_data, secoes_data)
            
            # --- MUDANÇA IMPORTANTE ---
            # Não salvamos mais em 'relatorios_gerados'.
            # A pasta na nuvem é temporária e seria apagada.
            # A única ação é o DOWNLOAD.
            
            st.success("Relatório gerado! Clique no botão 'Baixar PDF' que apareceu abaixo.")
            
            filename = f"Rota_{form_data['lider']}_{form_data['data'].strftime('%Y-%m-%d')}.pdf"
            
            st.session_state.pdf_bytes_to_download = pdf_bytes
            st.session_state.pdf_filename_to_download = filename
            
    # O botão de download FORA do formulário
    if "pdf_bytes_to_download" in st.session_state and "pdf_filename_to_download" in st.session_state:
        st.download_button(
            label="Baixar PDF Gerado",
            data=st.session_state.pdf_bytes_to_download,
            file_name=st.session_state.pdf_filename_to_download,
            mime="application/pdf"
        )
        del st.session_state.pdf_bytes_to_download
        del st.session_state.pdf_filename_to_download


# --- LÓGICA PRINCIPAL (Login e Navegação) ---

def main():
    st.set_page_config(page_title="Rotas", layout="wide")
    
    # Não há mais init_db()

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.sidebar.title("Login")
        user = st.sidebar.text_input("Usuário", key="login_user")
        pwd = st.sidebar.text_input("Senha", type="password", key="login_pass")
        
        if st.sidebar.button("Entrar"):
            # Valida usando os Secrets
            if user == st.secrets["LOGIN_USER"] and pwd == st.secrets["LOGIN_PASS"]:
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.sidebar.error("Usuário ou senha inválidos.")
        
        st.info("Por favor, faça o login na barra lateral para usar o sistema.")

    else:
        # App principal
        
        # Conecta ao Google Sheets UMA VEZ após o login
        sheet = connect_to_gsheets()
        if sheet is None:
            st.error("Falha ao carregar o banco de dados. Verifique a configuração.")
            return

        st.sidebar.title("Navegação")
        st.sidebar.success(f"Logado como: {st.secrets['LOGIN_USER']}")
        
        pagina = st.sidebar.radio("Escolha a página:", ["Realizar Rota", "Área de Administração"])
        
        if pagina == "Realizar Rota":
            page_rota(sheet)
        elif pagina == "Área de Administração":
            page_admin(sheet)

if __name__ == "__main__":
    main()
