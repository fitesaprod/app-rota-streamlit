import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import io
import os
import tempfile
import json # Necessário para carregar o segredo

# --- CONFIGURAÇÃO DO BANCO DE DADOS (Google Sheets) ---

# Nome exato da sua planilha no Google Sheets
NOME_PLANILHA = "SistemaRotasDB"

@st.cache_resource(ttl=600)
def connect_to_gsheets():
    """Conecta ao Google Sheets usando as credenciais dos Segredos."""
    try:
        # Carrega o segredo no formato TOML (string inteira)
        creds_json_str = st.secrets["gcp_service_account_json"]
        # Converte a string JSON em um dicionário
        creds_dict = json.loads(creds_json_str)
        
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open(NOME_PLANILHA)
        return sh
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: '{e}'. Verifique se o segredo 'gcp_service_account_json' está correto.")
        return None

def get_worksheet(spreadsheet, sheet_name):
    """Tenta obter uma aba. Se falhar, retorna None."""
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Aba (worksheet) '{sheet_name}' não encontrada na planilha '{NOME_PLANILHA}'.")
        return None

def get_items(spreadsheet, tipo):
    """Busca itens de um tipo específico (ex: 'Lideres')"""
    ws = get_worksheet(spreadsheet, tipo.capitalize()) # Ex: 'lider' -> 'Lideres'
    if ws:
        items = ws.col_values(1)[1:] # Pula o cabeçalho "Nome"
        return items
    return []

def add_item(spreadsheet, tipo, nome):
    """Adiciona um novo item (ex: 'Lideres', 'nova maquina')"""
    ws = get_worksheet(spreadsheet, tipo.capitalize())
    if ws:
        try:
            ws.append_row([nome])
            return True
        except Exception as e:
            st.error(f"Erro ao adicionar item: {e}")
            return False
    return False

def remove_item(spreadsheet, tipo, nome):
    """Remove um item (pelo nome)"""
    ws = get_worksheet(spreadsheet, tipo.capitalize())
    if ws:
        try:
            # Encontra a célula com o nome
            cell = ws.find(nome, in_column=1)
            if cell:
                # Deleta a linha
                ws.delete_rows(cell.row)
                return True
            else:
                st.error(f"Item '{nome}' não encontrado para remoção.")
                return False
        except Exception as e:
            st.error(f"Erro ao remover item: {e}")
            return False
    return False

def get_secoes(spreadsheet):
    """Busca todas as seções dinâmicas"""
    ws = get_worksheet(spreadsheet, "Secoes")
    if ws:
        # Retorna (linha, titulo) para podermos deletar pela linha
        secoes_data = ws.get_all_values()
        if len(secoes_data) > 1: # Se houver mais que o cabeçalho
            # Retorna (número_da_linha, titulo)
            return [(i + 2, secao[0]) for i, secao in enumerate(secoes_data[1:])]
    return []

def add_secao(spreadsheet, titulo):
    """Adiciona uma nova seção"""
    return add_item(spreadsheet, "secoes", titulo) # Reutiliza a função

def remove_secao(spreadsheet, row_index):
    """Remove uma seção pelo índice da linha"""
    ws = get_worksheet(spreadsheet, "Secoes")
    if ws:
        try:
            ws.delete_rows(row_index)
            return True
        except Exception as e:
            st.error(f"Erro ao remover seção: {e}")
            return False
    return False

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
    """Cria o PDF com todos os dados do formulário."""
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    
    # 1. Dados de Identificação
    pdf.cell(0, 10, '1. Identificação da Rota', 0, 1)
    pdf.set_font('Arial', '', 12)
    
    # --- CORREÇÃO DE DATA ---
    pdf.multi_cell(0, 8, f"Data: {form_data['data'].strftime('%d/%m/%Y')}\n"
                         f"Líder: {form_data['lider']}\n"
                         f"Turma: {form_data['turma']}\n"
                         f"Rota: {form_data['rota']}\n"
                         f"Máquina: {form_data['maquina']}")
    pdf.ln(10)

    # 2. Seções da Rotina
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, '2. Detalhes da Rotina', 0, 1)
    
    # Criar pasta temporária para salvar imagens
    temp_dir = tempfile.mkdtemp()
    
    for i, secao in enumerate(secoes_data):
        
        # Uma seção por folha
        if i > 0:
            pdf.add_page()
            
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, f"Seção: {secao['titulo']}", 0, 1)
        
        pdf.set_font('Arial', '', 12)
        pdf.multi_cell(0, 8, f"Observação: {secao['obs']}")
        
        if secao['foto']:
            foto_bytes = secao['foto'].read()
            # Salva a imagem temporariamente para o FPDF poder usá-la
            temp_img_path = os.path.join(temp_dir, f"temp_img_{secao['id']}.png")
            with open(temp_img_path, 'wb') as f:
                f.write(foto_bytes)
            
            # Adiciona imagem ao PDF
            try:
                # Imagem centralizada (x=30, w=150)
                pdf.image(temp_img_path, x=30, w=150)
            except Exception as e:
                pdf.set_text_color(255, 0, 0)
                pdf.cell(0, 10, f"Erro ao adicionar imagem: {e}", 0, 1)
                pdf.set_text_color(0, 0, 0)
            
            # Remove o arquivo de imagem temporário
            os.remove(temp_img_path)
            
        pdf.ln(5)
    
    # Limpa a pasta temporária
    try:
        os.rmdir(temp_dir)
    except OSError:
        pass # Ignora se a pasta não estiver vazia (embora devesse estar)
    
    # Salva o PDF em memória
    pdf_buffer = io.BytesIO()
    pdf.output(pdf_buffer)
    
    return pdf_buffer.getvalue()

# --- INTERFACE PRINCIPAL DO APP ---

def page_admin(spreadsheet):
    """Página de Administração."""
    st.title("Área de Administração")
    
    # Senha da área ADM (lida dos Segredos)
    admin_password = st.text_input("Digite a senha de ADM:", type="password", key="admin_pass")
    if admin_password != st.secrets["ADMIN_PASS"]:
        st.warning("Acesso restrito.")
        return # Bloqueia o resto da página

    st.success("Acesso de ADM concedido.")

    # Usar tabs para organizar
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Líderes", "Turmas", "Rotas", "Máquinas", "Seções"])

    # Mapeamento de tipo para UI
    tipos_gerenciamento = {
        "Líderes": ("lideres", tab1),
        "Turmas": ("turmas", tab2),
        "Rotas": ("rotas", tab3),
        "Máquinas": ("maquinas", tab4)
    }

    for nome_tab, (tipo_db, tab) in tipos_gerenciamento.items():
        with tab:
            st.subheader(f"Gerenciar {nome_tab}")
            
            with st.form(f"form_add_{tipo_db}", clear_on_submit=True):
                novo_nome = st.text_input(f"Novo(a) {nome_tab.lower()[:-1]}")
                submitted = st.form_submit_button("Adicionar")
                if submitted and novo_nome:
                    if add_item(spreadsheet, tipo_db, novo_nome):
                        st.success(f"{nome_tab[:-1]} '{novo_nome}' adicionado(a).")
                        st.cache_data.clear() # Limpa o cache de dados
                    else:
                        st.error(f"Erro ao adicionar {nome_tab[:-1]}.")
            
            st.divider()
            
            # --- CORREÇÃO DE CACHE ---
            # Usamos st.cache_data para não sobrecarregar a API do Google
            @st.cache_data(ttl=60)
            def load_items(_sp, tipo): # Adicionado _ (underscore)
                return get_items(_sp, tipo)
            
            itens_db = load_items(spreadsheet, tipo_db) # Passa a planilha
            
            if not itens_db:
                st.info(f"Nenhum(a) {nome_tab.lower()} cadastrado(a).")
            else:
                st.write(f"**{nome_tab} Cadastrados:**")
                for item_nome in itens_db:
                    col1, col2 = st.columns([0.8, 0.2])
                    col1.write(item_nome)
                    if col2.button(f"Remover", key=f"remove_{tipo_db}_{item_nome}"):
                        if remove_item(spreadsheet, tipo_db, item_nome):
                            st.cache_data.clear() # Limpa o cache
                            st.rerun()
                        else:
                            st.error("Erro ao remover.")

    # Gerenciamento de Seções (lógica de remoção é por linha)
    with tab5:
        st.subheader("Gerenciar Seções da Rotina")
        st.info("Estas são as etapas que o líder preencherá (Ex: 'Verificar EPI', 'Limpeza da Máquina')")
        
        with st.form("form_add_secao", clear_on_submit=True):
            novo_titulo = st.text_input("Título da nova seção")
            submitted = st.form_submit_button("Adicionar Seção")
            if submitted and novo_titulo:
                if add_secao(spreadsheet, novo_titulo):
                    st.success(f"Seção '{novo_titulo}' adicionada.")
                    st.cache_data.clear() # Limpa o cache
                else:
                    st.error("Erro ao adicionar seção.")
        
        st.divider()
        
        # --- CORREÇÃO DE CACHE ---
        @st.cache_data(ttl=60)
        def load_secoes(_sp): # Adicionado _ (underscore)
            return get_secoes(_sp)
        
        secoes_db = load_secoes(spreadsheet) # Passa a planilha
        
        if not secoes_db:
            st.info("Nenhuma seção cadastrada.")
        else:
            st.write("**Seções Cadastradas (na ordem):**")
            for row_index, secao_titulo in secoes_db:
                col1, col2 = st.columns([0.8, 0.2])
                col1.write(secao_titulo)
                if col2.button(f"Remover", key=f"remove_secao_{row_index}"):
                    if remove_secao(spreadsheet, row_index):
                        st.cache_data.clear() # Limpa o cache
                        st.rerun()
                    else:
                        st.error("Erro ao remover seção.")

def page_rota(spreadsheet):
    """Página principal de preenchimento da Rota."""
    st.title("Formulário de Rota da Liderança")

    # Carrega dados do DB para os dropdowns
    # --- CORREÇÃO DE CACHE ---
    @st.cache_data(ttl=60)
    def load_all_form_data(_sp): # Adicionado _ (underscore)
        lideres = get_items(_sp, 'lideres')
        turmas = get_items(_sp, 'turmas')
        rotas = get_items(_sp, 'rotas')
        maquinas = get_items(_sp, 'maquinas')
        secoes = get_secoes(_sp)
        return lideres, turmas, rotas, maquinas, secoes

    try:
        lideres, turmas, rotas, maquinas, secoes = load_all_form_data(spreadsheet) # Passa a planilha
    except Exception as e:
        st.error(f"Falha ao carregar dados da planilha: {e}")
        return

    if not all([lideres, turmas, rotas, maquinas, secoes]):
        st.warning("Sistema não configurado. Vá para a 'Área de Administração' e cadastre Líderes, Turmas, Rotas, Máquinas e Seções.")
        return

    # Dicionário para guardar todos os dados
    form_data = {}
    secoes_data = []

    with st.form("form_rota", clear_on_submit=True):
        st.header("1. Identificação")
        
        col1, col2 = st.columns(2)
        # --- CORREÇÃO DE DATA ---
        form_data['data'] = col1.date_input("Data", datetime.now(), format="DD-MM-YYYY")
        form_data['lider'] = col1.selectbox("Líder", lideres)
        form_data['turma'] = col2.selectbox("Turma", turmas)
        form_data['rota'] = col2.selectbox("Rota", rotas)
        form_data['maquina'] = st.selectbox("Máquina", maquinas)
        
        st.divider()
        st.header("2. Rotina")
        
        if not secoes:
            st.info("Nenhuma seção de rotina cadastrada na área ADM.")
        
        # Cria os campos dinâmicos para cada seção
        for row_index, secao_titulo in secoes:
            st.subheader(secao_titulo)
            
            # Usamos a key para identificar unicamente cada widget
            key_foto = f"foto_{row_index}"
            key_obs = f"obs_{row_index}"
            
            foto_capturada = st.camera_input("Tirar Foto", key=key_foto)
            obs = st.text_area("Observações", key=key_obs)
            
            secoes_data.append({
                "id": row_index,
                "titulo": secao_titulo,
                "foto": foto_capturada,
                "obs": obs
            })

        st.divider()
        submitted = st.form_submit_button("Gerar Relatório PDF")

        if submitted:
            # 1. Gerar o PDF em memória
            pdf_bytes = create_pdf(form_data, secoes_data)
            
            # 2. Salvar o PDF no sistema (não salva mais em pasta, só na memória)
            
            # --- CORREÇÃO DE DATA ---
            filename = f"Rota_{form_data['lider']}_{form_data['data'].strftime('%d-%m-%Y')}.pdf"
            
            st.success(f"Relatório '{filename}' gerado com sucesso!")
            
            # 3. Salvar os dados do PDF na "memória" (session_state)
            st.session_state.pdf_bytes_to_download = pdf_bytes
            st.session_state.pdf_filename_to_download = filename
            
    # 4. Exibir o botão de download FORA do formulário
    if "pdf_bytes_to_download" in st.session_state and "pdf_filename_to_download" in st.session_state:
        st.download_button(
            label="Baixar PDF Gerado",
            data=st.session_state.pdf_bytes_to_download,
            file_name=st.session_state.pdf_filename_to_download,
            mime="application/pdf"
        )
        # Limpa o estado
        del st.session_state.pdf_bytes_to_download
        del st.session_state.pdf_filename_to_download

# --- LÓGICA PRINCIPAL (Login e Navegação) ---

def main():
    st.set_page_config(page_title="Rotas", layout="wide")
    
    # Tenta conectar ao Google Sheets
    spreadsheet = connect_to_gsheets()
    if spreadsheet is None:
        st.error("Falha ao carregar o banco de dados. Verifique a configuração.")
        return

    # Sistema de Login
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.sidebar.title("Login")
        user = st.sidebar.text_input("Usuário", key="login_user")
        pwd = st.sidebar.text_input("Senha", type="password", key="login_pass")
        
        if st.sidebar.button("Entrar"):
            # Lê as credenciais dos Segredos
            if (user == st.secrets["LOGIN_USER"] and 
                pwd == st.secrets["LOGIN_PASS"]):
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.sidebar.error("Usuário ou senha inválidos.")
        
        st.info("Por favor, faça o login na barra lateral para usar o sistema.")

    else:
        # App principal
        st.sidebar.title("Navegação")
        st.sidebar.success(f"Logado como: {st.secrets['LOGIN_USER']}")
        
        pagina = st.sidebar.radio("Escolha a página:", ["Realizar Rota", "Área de Administração"])
        
        if pagina == "Realizar Rota":
            page_rota(spreadsheet)
        elif pagina == "Área de Administração":
            page_admin(spreadsheet)

if __name__ == "__main__":
    main()
