
import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import io
import os
import tempfile
import json  # Necessário para carregar o segredo
from typing import Optional, List

# --- CONFIGURAÇÕES GERAIS ---
NOME_PLANILHA = "SistemaRotasDB"
AUDITS_BASE_DIR = os.path.join(os.getcwd(), "auditorias")
os.makedirs(AUDITS_BASE_DIR, exist_ok=True)  # Garante pasta base para auditorias

# --- FUNÇÕES DE AUDITORIA PERSISTENTE (NOVO) ---

def _slugify(texto: str) -> str:
    """Simplifica texto para uso em nome de arquivo."""
    return "".join(
        c if c.isalnum() else "_"
        for c in (texto or "").strip().lower()
    ).strip("_")

def _get_audit_dir() -> Optional[str]:
    """Retorna o diretório da auditoria ativa (se existir)."""
    return st.session_state.get("audit_dir")

def _ensure_audit_initialized(form_data: dict):
    """
    Cria a pasta de auditoria e o manifest.json na primeira vez que uma foto é tirada.
    Usa dados de identificação (se já preenchidos).
    """
    if "audit_dir" in st.session_state and st.session_state["audit_dir"]:
        return  # Já inicializado

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lider = _slugify(form_data.get("lider", "lider"))
    rota = _slugify(form_data.get("rota", "rota"))
    audit_id = f"{lider}_{rota}_{ts}"

    audit_dir = os.path.join(AUDITS_BASE_DIR, audit_id)
    os.makedirs(audit_dir, exist_ok=True)

    manifest = {
        "audit_id": audit_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "identificacao": {
            "data": (form_data.get("data").strftime("%Y-%m-%d")
                     if isinstance(form_data.get("data"), datetime)
                     else str(form_data.get("data", ""))),
            "lider": form_data.get("lider", ""),
            "turma": form_data.get("turma", ""),
            "rota": form_data.get("rota", ""),
            "maquina": form_data.get("maquina", "")
        },
        "photos": []  # Lista de registros de fotos tiradas
    }

    with open(os.path.join(audit_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    st.session_state["audit_dir"] = audit_dir
    st.session_state["audit_id"] = audit_id

def _append_photo_to_manifest(section_id: int, section_title: str, photo_path: str, obs: str):
    """Adiciona um registro de foto ao manifest.json da auditoria ativa."""
    audit_dir = _get_audit_dir()
    if not audit_dir:
        return

    manifest_path = os.path.join(audit_dir, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "section_id": section_id,
        "section_title": section_title,
        "photo_path": os.path.basename(photo_path),
        "obs": obs or ""
    }

    manifest.setdefault("photos", []).append(entry)

    # Salva de volta o manifest
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def _save_captured_photo(section_id: int, section_title: str, uploaded_file, obs: str) -> Optional[str]:
    """
    Salva a foto capturada (st.camera_input) na pasta da auditoria e registra no manifest.
    Retorna o caminho salvo.
    """
    if not uploaded_file:
        return None

    # Garante auditoria inicializada
    _ensure_audit_initialized(st.session_state.get("current_form_ident", {}))

    audit_dir = _get_audit_dir()
    if not audit_dir:
        return None

    ts = datetime.now().strftime("%H%M%S")
    fname = f"{section_id}_{_slugify(section_title)}_{ts}.png"
    fpath = os.path.join(audit_dir, fname)

    # Alguns objetos UploadedFile usam getvalue, outros .read()
    try:
        photo_bytes = uploaded_file.getvalue()
    except Exception:
        photo_bytes = uploaded_file.read()

    with open(fpath, "wb") as f:
        f.write(photo_bytes)

    _append_photo_to_manifest(section_id, section_title, fpath, obs)
    return fpath

def _find_latest_photo_for_section(section_id: int) -> Optional[str]:
    """
    Procura a última foto salva para a seção (com base no nome do arquivo e mtime).
    """
    audit_dir = _get_audit_dir()
    if not audit_dir or not os.path.isdir(audit_dir):
        return None

    candidates: List[str] = []
    for name in os.listdir(audit_dir):
        if name.startswith(f"{section_id}_") and name.lower().endswith(".png"):
            candidates.append(os.path.join(audit_dir, name))

    if not candidates:
        return None

    # Retorna o arquivo com maior mtime (mais recente)
    latest = max(candidates, key=lambda p: os.path.getmtime(p))
    return latest

def _load_manifest() -> dict:
    """Carrega o manifest atual, se existir."""
    audit_dir = _get_audit_dir()
    if not audit_dir:
        return {}
    manifest_path = os.path.join(audit_dir, "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

# --- CONFIGURAÇÃO DO BANCO DE DADOS (Google Sheets) ---

@st.cache_resource(ttl=600)
def connect_to_gsheets():
    """Conecta ao Google Sheets usando as credenciais dos Segredos."""
    try:
        creds_json_str = st.secrets["gcp_service_account_json"]
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
    ws = get_worksheet(spreadsheet, tipo.capitalize())  # Ex: 'lider' -> 'Lideres'
    if ws:
        items = ws.col_values(1)[1:]  # Pula o cabeçalho "Nome"
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
            cell = ws.find(nome, in_column=1)
            if cell:
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
        secoes_data = ws.get_all_values()
        if len(secoes_data) > 1:  # Se houver mais que o cabeçalho
            return [(i + 2, secao[0]) for i, secao in enumerate(secoes_data[1:])]
    return []

def add_secao(spreadsheet, titulo):
    """Adiciona uma nova seção"""
    return add_item(spreadsheet, "secoes", titulo)

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
        self.cell(0, 10, 'Gerado pelo Sistema de Rotas - Fitesa', 0, 0, 'R')

def create_pdf(form_data, secoes_data):
    """Cria o PDF com todos os dados do formulário, usando fotos da sessão ou da auditoria persistida."""
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)

    # 1. Dados de Identificação
    pdf.cell(0, 10, '1. Identificação da Rota', 0, 1)
    pdf.set_font('Arial', '', 12)

    # CORREÇÃO DE DATA
    # form_data['data'] pode ser date (st.date_input retorna datetime.date)
    try:
        data_str = form_data['data'].strftime('%d/%m/%Y')
    except Exception:
        data_str = str(form_data.get('data', ''))

    pdf.multi_cell(0, 8, f"Data: {data_str}\n"
                         f"Líder: {form_data['lider']}\n"
                         f"Turma: {form_data['turma']}\n"
                         f"Rota: {form_data['rota']}\n"
                         f"Máquina: {form_data['maquina']}")
    pdf.ln(10)

    # 2. Seções da Rotina
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

        # Escolhe fonte de imagem:
        # 1) Foto capturada na submissão atual
        # 2) Caso contrário, última foto salva na auditoria persistente
        foto_bytes = None
        temp_img_path = None

        if secao['foto'] is not None:
            try:
                foto_bytes = secao['foto'].getvalue()
            except Exception:
                foto_bytes = secao['foto'].read()

        if foto_bytes:
            temp_img_path = os.path.join(temp_dir, f"temp_img_{secao['id']}.png")
            with open(temp_img_path, 'wb') as f:
                f.write(foto_bytes)
        else:
            # Busca última foto persistida para esta seção
            latest_path = _find_latest_photo_for_section(secao['id'])
            if latest_path and os.path.exists(latest_path):
                temp_img_path = latest_path

        # Adiciona imagem se existir
        if temp_img_path and os.path.exists(temp_img_path):
            try:
                pdf.image(temp_img_path, x=30, w=150)
            except Exception as e:
                pdf.set_text_color(255, 0, 0)
                pdf.cell(0, 10, f"Erro ao adicionar imagem: {e}", 0, 1)
                pdf.set_text_color(0, 0, 0)

        pdf.ln(5)

    # Limpa pasta temporária
    try:
        for name in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, name))
            except Exception:
                pass
        os.rmdir(temp_dir)
    except Exception:
        pass

    # Salva o PDF em memória
    pdf_buffer = io.BytesIO()
    pdf.output(pdf_buffer)
    return pdf_buffer.getvalue()

# --- INTERFACE PRINCIPAL DO APP ---

def page_admin(spreadsheet):
    """Página de Administração."""
    st.title("Área de Administração")

    admin_password = st.text_input("Digite a senha de ADM:", type="password", key="admin_pass")
    if admin_password != st.secrets["ADMIN_PASS"]:
        st.warning("Acesso restrito.")
        return

    st.success("Acesso de ADM concedido.")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Líderes", "Turmas", "Rotas", "Máquinas", "Seções"])

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
                        st.cache_data.clear()
                    else:
                        st.error(f"Erro ao adicionar {nome_tab[:-1]}.")

            st.divider()

            @st.cache_data(ttl=60)
            def load_items(_sp, tipo):
                return get_items(_sp, tipo)

            itens_db = load_items(spreadsheet, tipo_db)

            if not itens_db:
                st.info(f"Nenhum(a) {nome_tab.lower()} cadastrado(a).")
            else:
                st.write(f"**{nome_tab} Cadastrados:**")
                for item_nome in itens_db:
                    col1, col2 = st.columns([0.8, 0.2])
                    col1.write(item_nome)
                    if col2.button(f"Remover", key=f"remove_{tipo_db}_{item_nome}"):
                        if remove_item(spreadsheet, tipo_db, item_nome):
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Erro ao remover.")

    with tab5:
        st.subheader("Gerenciar Seções da Rotina")
        st.info("Estas são as etapas que o líder preencherá (Ex: 'Verificar EPI', 'Limpeza da Máquina')")

        with st.form("form_add_secao", clear_on_submit=True):
            novo_titulo = st.text_input("Título da nova seção")
            submitted = st.form_submit_button("Adicionar Seção")
            if submitted and novo_titulo:
                if add_secao(spreadsheet, novo_titulo):
                    st.success(f"Seção '{novo_titulo}' adicionada.")
                    st.cache_data.clear()
                else:
                    st.error("Erro ao adicionar seção.")

        st.divider()

        @st.cache_data(ttl=60)
        def load_secoes(_sp):
            return get_secoes(_sp)

        secoes_db = load_secoes(spreadsheet)

        if not secoes_db:
            st.info("Nenhuma seção cadastrada.")
        else:
            st.write("**Seções Cadastradas (na ordem):**")
            for row_index, secao_titulo in secoes_db:
                col1, col2 = st.columns([0.8, 0.2])
                col1.write(secao_titulo)
                if col2.button(f"Remover", key=f"remove_secao_{row_index}"):
                    if remove_secao(spreadsheet, row_index):
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Erro ao remover seção.")

def page_rota(spreadsheet):
    """Página principal de preenchimento da Rota."""
    st.title("Formulário de Rota da Liderança")

    @st.cache_data(ttl=60)
    def load_all_form_data(_sp):
        lideres = get_items(_sp, 'lideres')
        turmas = get_items(_sp, 'turmas')
        rotas = get_items(_sp, 'rotas')
        maquinas = get_items(_sp, 'maquinas')
        secoes = get_secoes(_sp)
        return lideres, turmas, rotas, maquinas, secoes

    try:
        lideres, turmas, rotas, maquinas, secoes = load_all_form_data(spreadsheet)
    except Exception as e:
        st.error(f"Falha ao carregar dados da planilha: {e}")
        return

    if not all([lideres, turmas, rotas, maquinas, secoes]):
        st.warning("Sistema não configurado. Vá para a 'Área de Administração' e cadastre Líderes, Turmas, Rotas, Máquinas e Seções.")
        return

    form_data = {}
    secoes_data = []

    # Guarda identificação atual no session_state para inicialização da auditoria
    if "current_form_ident" not in st.session_state:
        st.session_state["current_form_ident"] = {}

    with st.form("form_rota", clear_on_submit=True):
        st.header("1. Identificação")

        col1, col2 = st.columns(2)
        # CORREÇÃO DE DATA
        form_data['data'] = col1.date_input("Data", datetime.now(), format="DD-MM-YYYY")
        form_data['lider'] = col1.selectbox("Líder", lideres)
        form_data['turma'] = col2.selectbox("Turma", turmas)
        form_data['rota'] = col2.selectbox("Rota", rotas)
        form_data['maquina'] = st.selectbox("Máquina", maquinas)

        # Atualiza identificação atual (usado para criar a auditoria quando a primeira foto for tirada)
        st.session_state["current_form_ident"] = {
            "data": form_data['data'],
            "lider": form_data['lider'],
            "turma": form_data['turma'],
            "rota": form_data['rota'],
            "maquina": form_data['maquina']
        }

        st.divider()
        st.header("2. Rotina")

        if not secoes:
            st.info("Nenhuma seção de rotina cadastrada na área ADM.")

        for row_index, secao_titulo in secoes:
            st.subheader(secao_titulo)

            key_foto = f"foto_{row_index}"
            key_obs = f"obs_{row_index}"

            foto_capturada = st.camera_input("Tirar Foto", key=key_foto)
            obs = st.text_area("Observações", key=key_obs)

            # Se tirou foto, salva imediatamente no disco e registra no manifest
            saved_path = None
            if foto_capturada is not None:
                saved_path = _save_captured_photo(row_index, secao_titulo, foto_capturada, obs)
                if saved_path:
                    st.success(f"Foto salva com segurança em '{os.path.basename(saved_path)}'.")
                    st.image(saved_path, caption="Foto salva (persistida)", use_column_width=True)

            # Se não tirou foto agora, mas já existe foto salva anteriormente, mostra a última
            if foto_capturada is None:
                latest = _find_latest_photo_for_section(row_index)
                if latest:
                    st.info("Última foto desta seção já salva anteriormente:")
                    st.image(latest, caption=os.path.basename(latest), use_column_width=True)

            secoes_data.append({
                "id": row_index,
                "titulo": secao_titulo,
                "foto": foto_capturada,  # pode ser None
                "obs": obs
            })

        # Exibe informações da auditoria iniciada (se já houver)
        audit_dir = _get_audit_dir()
        if audit_dir:
            st.divider()
            st.success(f"Auditoria ativa: {st.session_state.get('audit_id', '')}")
            st.write(f"Diretório: `{audit_dir}`")
            man = _load_manifest()
            st.caption(f"Fotos salvas até agora: {len(man.get('photos', []))}")

        st.divider()
        submitted = st.form_submit_button("Gerar Relatório PDF")

        if submitted:
            pdf_bytes = create_pdf(form_data, secoes_data)

            filename = f"Rota_{form_data['lider']}_{form_data['data'].strftime('%d-%m-%Y')}.pdf"

            st.success(f"Relatório '{filename}' gerado com sucesso!")

            st.session_state.pdf_bytes_to_download = pdf_bytes
            st.session_state.pdf_filename_to_download = filename

    # Botão de download fora do form
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

    spreadsheet = connect_to_gsheets()
    if spreadsheet is None:
        st.error("Falha ao carregar o banco de dados. Verifique a configuração.")
        return

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.sidebar.title("Login")
        user = st.sidebar.text_input("Usuário", key="login_user")
        pwd = st.sidebar.text_input("Senha", type="password", key="login_pass")

        if st.sidebar.button("Entrar"):
            if (user == st.secrets["LOGIN_USER"] and
                pwd == st.secrets["LOGIN_PASS"]):
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.sidebar.error("Usuário ou senha inválidos.")

        st.info("Por favor, faça o login na barra lateral para usar o sistema.")

    else:
        st.sidebar.title("Navegação")
        st.sidebar.success(f"Logado como: {st.secrets['LOGIN_USER']}")

        pagina = st.sidebar.radio("Escolha a página:", ["Realizar Rota", "Área de Administração"])

        if pagina == "Realizar Rota":
            page_rota(spreadsheet)
        elif pagina == "Área de Administração":
            page_admin(spreadsheet)

if __name__ == "__main__":
    main()
