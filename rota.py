
import streamlit as st
import gspread
from datetime import datetime
from fpdf import FPDF
import io
import os
import tempfile
import json
from typing import Optional, List

# --- CONFIGURAÇÕES ---
NOME_PLANILHA = "SistemaRotasDB"
AUDITS_BASE_DIR = os.path.join(os.getcwd(), "auditorias")
os.makedirs(AUDITS_BASE_DIR, exist_ok=True)

# --- FUNÇÕES DE AUDITORIA ---
def _slugify(texto: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (texto or "").strip().lower()).strip("_")

def _get_audit_dir() -> Optional[str]:
    return st.session_state.get("audit_dir")

def _create_new_audit(form_data: dict):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lider = _slugify(form_data.get("lider", "lider"))
    rota = _slugify(form_data.get("rota", "rota"))
    audit_id = f"{lider}_{rota}_{ts}"
    audit_dir = os.path.join(AUDITS_BASE_DIR, audit_id)
    os.makedirs(audit_dir, exist_ok=True)
    manifest = {
        "audit_id": audit_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "ativo",
        "identificacao": form_data,
        "photos": []
    }
    with open(os.path.join(audit_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    st.session_state["audit_dir"] = audit_dir
    st.session_state["audit_id"] = audit_id

def _append_photo(section_id: int, section_title: str, photo_path: str, obs: str):
    audit_dir = _get_audit_dir()
    if not audit_dir:
        return
    manifest_path = os.path.join(audit_dir, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "section_id": section_id,
        "section_title": section_title,
        "photo_path": os.path.basename(photo_path),
        "obs": obs or ""
    }
    manifest.setdefault("photos", []).append(entry)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def _save_photo(section_id: int, section_title: str, uploaded_file, obs: str) -> Optional[str]:
    if not uploaded_file:
        return None
    audit_dir = _get_audit_dir()
    if not audit_dir:
        return None
    ts = datetime.now().strftime("%H%M%S")
    fname = f"{section_id}_{_slugify(section_title)}_{ts}.png"
    fpath = os.path.join(audit_dir, fname)
    photo_bytes = uploaded_file.getvalue()
    with open(fpath, "wb") as f:
        f.write(photo_bytes)
    _append_photo(section_id, section_title, fpath, obs)
    return fpath

def _load_manifest(audit_dir=None):
    if not audit_dir:
        audit_dir = _get_audit_dir()
    if not audit_dir:
        return {}
    manifest_path = os.path.join(audit_dir, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _update_status_concluido():
    audit_dir = _get_audit_dir()
    if not audit_dir:
        return
    manifest_path = os.path.join(audit_dir, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["status"] = "concluido"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    st.session_state.pop("audit_dir", None)
    st.session_state.pop("audit_id", None)
    st.session_state.pop("current_form_ident", None)

def _list_audits(status_filter=None):
    audits = []
    for name in os.listdir(AUDITS_BASE_DIR):
        manifest_path = os.path.join(AUDITS_BASE_DIR, name, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not status_filter or data.get("status") == status_filter:
                    audits.append((name, data))
    return sorted(audits, key=lambda x: x[1].get("created_at", ""), reverse=True)

# --- PDF ---
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
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, '1. Identificação da Rota', 0, 1)
    pdf.set_font('Arial', '', 12)
    data_str = str(form_data.get('data', ''))
    pdf.multi_cell(0, 8, f"Data: {data_str}\nLíder: {form_data['lider']}\nTurma: {form_data['turma']}\nRota: {form_data['rota']}\nMáquina: {form_data['maquina']}")
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
        foto_bytes = None
        temp_img_path = None
        if secao['foto'] is not None:
            foto_bytes = secao['foto'].getvalue()
        if foto_bytes:
            temp_img_path = os.path.join(temp_dir, f"temp_img_{secao['id']}.png")
            with open(temp_img_path, 'wb') as f:
                f.write(foto_bytes)
        if temp_img_path and os.path.exists(temp_img_path):
            pdf.image(temp_img_path, x=30, w=150)
        pdf.ln(5)
    pdf_buffer = io.BytesIO()
    pdf.output(pdf_buffer)
    return pdf_buffer.getvalue()

# --- INTERFACE ---
def page_historico():
    st.title("Histórico de Rotas")
    audits = _list_audits(status_filter="ativo")
    if not audits:
        st.info("Nenhuma rota ativa.")
    for name, data in audits:
        st.subheader(f"Rota: {data['identificacao']['rota']} | Líder: {data['identificacao']['lider']} | Iniciada: {data['created_at']}")
        if st.button(f"Continuar {name}"):
            st.session_state['audit_dir'] = os.path.join(AUDITS_BASE_DIR, name)
            st.session_state['audit_id'] = name
            st.session_state['current_form_ident'] = data['identificacao']
            st.rerun()
        st.write("Fotos salvas:")
        for photo in data.get("photos", []):
            st.image(os.path.join(AUDITS_BASE_DIR, name, photo['photo_path']), caption=f"{photo['section_title']} - {photo['timestamp']}", use_column_width=True)

def page_admin():
    st.title("Área de Administração")
    st.subheader("Histórico de Rotas Concluídas")
    audits = _list_audits(status_filter="concluido")
    if not audits:
        st.info("Nenhuma rota concluída.")
    for name, data in audits:
        st.write(f"Rota: {data['identificacao']['rota']} | Líder: {data['identificacao']['lider']} | Concluída: {data['created_at']}")

def page_rota():
    st.title("Realizar Rota")
    if "audit_dir" not in st.session_state:
        st.info("Clique em 'Começar Rota' para iniciar.")
        if st.button("Começar Rota"):
            form_data = {
                "data": datetime.now().strftime("%d/%m/%Y"),
                "lider": "Líder Exemplo",
                "turma": "Turma A",
                "rota": "Rota 1",
                "maquina": "Máquina X"
            }
            _create_new_audit(form_data)
            st.session_state['current_form_ident'] = form_data
            st.rerun()
    else:
        st.success(f"Rota ativa: {st.session_state['audit_id']}")
        secoes = ["Verificar EPI", "Limpeza da Máquina", "Checar Produção"]
        secoes_data = []
        for i, titulo in enumerate(secoes):
            st.subheader(titulo)
            foto = st.camera_input("Tirar Foto", key=f"foto_{i}")
            obs = st.text_area("Observações", key=f"obs_{i}")
            if foto:
                saved_path = _save_photo(i, titulo, foto, obs)
                if saved_path:
                    st.image(saved_path, caption="Foto salva", use_column_width=True)
            secoes_data.append({"id": i, "titulo": titulo, "foto": foto, "obs": obs})
        if st.button("Gerar Relatório PDF"):
            pdf_bytes = create_pdf(st.session_state['current_form_ident'], secoes_data)
            st.download_button("Baixar PDF", data=pdf_bytes, file_name="relatorio_rota.pdf", mime="application/pdf")
            _update_status_concluido()

# --- MAIN ---
def main():
    st.sidebar.title("Menu")
    pagina = st.sidebar.radio("Escolha a página:", ["Realizar Rota", "Histórico de Rotas", "Área de Administração"])
    if pagina == "Realizar Rota":
        page_rota()
    elif pagina == "Histórico de Rotas":
        page_historico()
    elif pagina == "Área de Administração":
        page_admin()

if __name__ == "__main__":
    main()
