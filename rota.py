import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import io
import os
import tempfile
import uuid
import json # Necessário para ler sua string de conexão

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Sistema de Rotas Fitesa", layout="wide")

# --- CONEXÃO COM GOOGLE SHEETS ---
NOME_PLANILHA = "SistemaRotasDB"

@st.cache_resource(ttl=600)
def connect_to_gsheets():
    """Conecta ao Google Sheets lendo a string JSON dos segredos."""
    try:
        # CORREÇÃO: Lê a string JSON que você configurou e converte para dicionário
        json_str = st.secrets["gcp_service_account_json"]
        creds_dict = json.loads(json_str)
        
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open(NOME_PLANILHA)
        return sh
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}")
        st.error("Verifique se o segredo 'gcp_service_account_json' está correto.")
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

def create_pdf(form_data, secoes_data, lista_fotos_extras):
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

    # 2. Fotos Iniciais
    if lista_fotos_extras:
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 10, '2. Fotos Gerais (Captura Inicial)', 0, 1)
        pdf.ln(2)
        
        temp_dir = tempfile.mkdtemp()
        
        for idx, item_foto in enumerate(lista_fotos_extras):
            try:
                pdf.set_font('Arial', 'I', 10)
                pdf.cell(0, 8, f"Foto {idx+1} - Capturada em: {item_foto['timestamp']}", 0, 1)
                
                tpath = os.path.join(temp_dir, f"extra_{idx}.png")
                with open(tpath, "wb") as f:
                    f.write(item_foto['buffer'].getbuffer())
                
                pdf.image(tpath, x=20, w=100)
                pdf.ln(5)
                os.remove(tpath)
            except Exception as e:
                pdf.cell(0, 10, f"Erro foto: {e}", 0, 1)
        
        try: os.rmdir(temp_dir)
        except: pass
        pdf.ln(5)

    # 3. Seções
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, '3. Detalhes da Rotina (Checklist)', 0, 1)

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
    
    # CORREÇÃO: Lê a senha diretamente do seu formato
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
    if 'fotos_pre_rota' not in st.session_state:
        st.session_state['fotos_pre_rota'] = []

# --- INTERFACE: NOVA ROTA / LISTA ---
def page_inicio_lista(spreadsheet):
    st.title("Central de Rotas")
    
    # 1. Captura
    st.write("---")
    st.subheader("📸 Captura de Evidências (Pré-Rota)")
    st.info("Tire fotos agora. Elas serão anexadas quando você clicar em 'Começar Rota'.")
    
    col_cam, col_lista = st.columns([1, 1])
    
    with col_cam:
        foto_temp = st.camera_input("Tirar Foto", key="cam_temp")
        if foto_temp:
            ts = datetime.now().strftime("%d/%m %H:%M:%S")
            if not st.session_state.get('last_photo_id') == foto_temp.id:
                st.session_state['fotos_pre_rota'].append({'timestamp': ts, 'buffer': foto_temp})
                st.session_state['last_photo_id'] = foto_temp.id
                st.toast("Foto salva na lista temporária!")

    with col_lista:
        st.write(f"**Fotos Salvas ({len(st.session_state['fotos_pre_rota'])}):**")
        if st.button("Limpar lista de fotos"):
            st.session_state['fotos_pre_rota'] = []
            st.rerun()
            
        for i, f in enumerate(st.session_state['fotos_pre_rota']):
            st.text(f"📷 Foto {i+1} - {f['timestamp']}")

    st.divider()

    # 2. Iniciar
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
                "fotos_lista": st.session_state['fotos_pre_rota'].copy(),
                "respostas_secoes": {} 
            }
            
            st.session_state['rascunhos_rotas'][novo_id] = nova_rota
            st.session_state['rota_ativa_id'] = novo_id
            st.session_state['fotos_pre_rota'] = []
            
            registrar_inicio_rota(spreadsheet, novo_id, lider_sel)
            
            st.success("Rota Criada! Redirecionando...")
            st.rerun()

    st.divider()

    # 3. Continuar
    st.subheader("📂 Rotas em Andamento (Histórico Local)")
    
    rotas_abertas = st.session_state['rascunhos_rotas']
    
    if not rotas_abertas:
        st.info("Nenhuma rota iniciada neste dispositivo.")
    else:
        for rid, rdata in rotas_abertas.items():
            with st.expander(f"📍 {rdata['inicio']} - {rdata['dados']['lider']} (Máq: {rdata['dados']['maquina']})"):
                st.write(f"ID: {rid}")
                st.write(f"Fotos anexadas: {len(rdata['fotos_lista'])}")
                if st.button("Continuar Rota", key=f"btn_{rid}"):
                    st.session_state['rota_ativa_id'] = rid
                    st.rerun()
                
                if st.button("Descartar/Excluir", key=f"del_{rid}"):
                    del st.session_state['rascunhos_rotas'][rid]
                    if st.session_state['rota_ativa_id'] == rid:
                        st.session_state['rota_ativa_id'] = None
                    st.rerun()

# --- INTERFACE: FORMULÁRIO DA ROTA ---
def page_formulario_rota(spreadsheet):
    rid = st.session_state['rota_ativa_id']
    if not rid or rid not in st.session_state['rascunhos_rotas']:
        st.warning("Nenhuma rota selecionada. Volte ao início.")
        if st.button("Voltar"):
            st.session_state['rota_ativa_id'] = None
            st.rerun()
        return

    rota_obj = st.session_state['rascunhos_rotas'][rid]
    dados = rota_obj['dados']
    
    st.title(f"Preenchendo: {dados['rota']}")
    st.caption(f"Líder: {dados['lider']} | Máquina: {dados['maquina']} | ID: {rid}")
    
    if st.button("⬅️ Voltar para Lista / Salvar Rascunho"):
        st.session_state['rota_ativa_id'] = None
        st.rerun()

    st.divider()
    
    if rota_obj['fotos_lista']:
        st.subheader(f"Galeria de Fotos Salvas ({len(rota_obj['fotos_lista'])})")
        cols = st.columns(3)
        for i, foto_item in enumerate(rota_obj['fotos_lista']):
            with cols[i % 3]:
                st.image(foto_item['buffer'], caption=f"{foto_item['timestamp']}")
        st.divider()

    secoes_db = get_secoes(spreadsheet)
    respostas = rota_obj['respostas_secoes']
    dados_para_pdf = [] 

    with st.form("form_rota_final"):
        st.subheader("Checklist da Rotina")
        
        for idx_secao, titulo_secao in secoes_db:
            st.markdown(f"**{titulo_secao}**")
            
            chave_item = str(idx_secao)
            defaults = respostas.get(chave_item, {'obs': '', 'foto': None})
            
            obs = st.text_area(f"Obs: {titulo_secao}", value=defaults['obs'], key=f"obs_{rid}_{idx_secao}")
            
            msg_foto = "Tirar foto da seção"
            foto_nova = st.camera_input(msg_foto, key=f"cam_{rid}_{idx_secao}")
            
            foto_final = None
            if foto_nova:
                foto_final = foto_nova
            elif defaults['foto']:
                foto_final = defaults['foto'] 
                st.info("✅ Foto já capturada para este item.")

            dados_para_pdf.append({
                "id": idx_secao,
                "titulo": titulo_secao,
                "obs": obs,
                "foto": foto_final
            })
            
            respostas[chave_item] = {
                "obs": obs,
                "foto": foto_final
            }

        st.divider()
        submitted = st.form_submit_button("✅ Finalizar e Gerar Relatório")
        
        if submitted:
            pdf_bytes = create_pdf(dados, dados_para_pdf, rota_obj['fotos_lista'])
            finalizar_rota_db(spreadsheet, rid)
            
            nome_arq = f"Relatorio_{dados['lider']}_{rid}.pdf"
            st.session_state['pdf_pronto'] = {'bytes': pdf_bytes, 'nome': nome_arq}
            
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
                # CORREÇÃO: Lê usuário e senha diretamente das suas variáveis soltas
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
