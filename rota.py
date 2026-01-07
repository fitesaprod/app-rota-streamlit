import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import io
import os
import tempfile
import json
import base64
import uuid

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Sistema Rotas Fitesa", layout="wide")

# --- CONFIGURAÇÃO DO BANCO DE DADOS (Google Sheets) ---
NOME_PLANILHA = "SistemaRotasDB"

@st.cache_resource(ttl=600)
def connect_to_gsheets():
    """Conecta ao Google Sheets usando as credenciais dos Segredos."""
    try:
        # Tenta carregar do formato TOML ou JSON direto
        if "gcpserviceaccountjson" in st.secrets:
            creds_json_str = st.secrets["gcpserviceaccountjson"]
            creds_dict = json.loads(creds_json_str)
        else:
            # Fallback se estiver configurado diferente
            creds_dict = st.secrets["gcp_service_account"]
            
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open(NOME_PLANILHA)
        return sh
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: '{e}'. Verifique os Segredos (secrets.toml).")
        return None

def get_worksheet(spreadsheet, sheet_name):
    """Obtém uma aba, cria se não existir."""
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        # Cria a aba se não existir
        ws = spreadsheet.add_worksheet(title=sheet_name, rows=100, cols=10)
        return ws

def init_db(spreadsheet):
    """Garante que as abas necessárias para o novo fluxo existam."""
    # Abas de Configuração
    get_worksheet(spreadsheet, "Lideres")
    get_worksheet(spreadsheet, "Turmas")
    get_worksheet(spreadsheet, "Rotas")
    get_worksheet(spreadsheet, "Maquinas")
    get_worksheet(spreadsheet, "Secoes")
    
    # Abas de Histórico/Andamento
    ws_ativas = get_worksheet(spreadsheet, "Rotas_Ativas")
    if not ws_ativas.get_all_values():
        ws_ativas.append_row(["ID_Rota", "Lider", "Turma", "Rota", "Maquina", "Data_Inicio", "Status"])
        
    ws_fotos = get_worksheet(spreadsheet, "Fotos_Registros")
    if not ws_fotos.get_all_values():
        ws_fotos.append_row(["ID_Rota", "Secao_Titulo", "Data_Foto", "Obs", "Imagem_Base64"])

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
            return [(i + 2, row[0]) for i, row in enumerate(data[1:]) if row]
    return []

def add_secao(spreadsheet, titulo):
    ws = get_worksheet(spreadsheet, "Secoes")
    ws.append_row([titulo])
    return True

def remove_secao(spreadsheet, row_index):
    ws = get_worksheet(spreadsheet, "Secoes")
    try:
        ws.delete_rows(row_index)
        return True
    except:
        return False

# --- FUNÇÕES DE PERSISTÊNCIA (NOVA LÓGICA) ---

def iniciar_nova_rota(spreadsheet, dados_inicio):
    """Cria o registro inicial da rota."""
    ws = get_worksheet(spreadsheet, "Rotas_Ativas")
    id_rota = f"ROTA-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    
    ws.append_row([
        id_rota,
        dados_inicio['lider'],
        dados_inicio['turma'],
        dados_inicio['rota'],
        dados_inicio['maquina'],
        str(datetime.now()),
        "EM_ANDAMENTO"
    ])
    return id_rota

def salvar_foto_registro(spreadsheet, id_rota, secao_titulo, obs, image_file):
    """Salva a foto e obs no banco imediatamente."""
    ws = get_worksheet(spreadsheet, "Fotos_Registros")
    
    # Converte imagem para Base64
    if image_file:
        img_bytes = image_file.getvalue()
        base64_img = base64.b64encode(img_bytes).decode('utf-8')
    else:
        base64_img = ""
        
    data_hora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    # Verifica se já existe registro dessa seção para essa rota (atualização)
    # Lógica simplificada: Apenas adiciona nova linha. O relatório pegará a última.
    ws.append_row([id_rota, secao_titulo, data_hora, obs, base64_img])

def get_registros_rota(spreadsheet, id_rota):
    """Busca todas as fotos/obs salvas para esta rota."""
    ws = get_worksheet(spreadsheet, "Fotos_Registros")
    all_rows = ws.get_all_records()
    # Filtra pelo ID da rota
    return [row for row in all_rows if row['ID_Rota'] == id_rota]

def finalizar_rota_db(spreadsheet, id_rota):
    """Marca a rota como finalizada (remove de ativas ou muda status)."""
    ws = get_worksheet(spreadsheet, "Rotas_Ativas")
    try:
        cell = ws.find(id_rota, in_column=1)
        if cell:
            # Opção A: Deletar da lista de ativas
            ws.delete_rows(cell.row)
            # Opção B: Mudar status para FINALIZADA (Se quiser histórico permanente de logs)
            # ws.update_cell(cell.row, 7, "FINALIZADA")
            return True
    except:
        return False
    return True

def get_rotas_ativas(spreadsheet):
    """Retorna lista de rotas em andamento para o menu de retomada."""
    ws = get_worksheet(spreadsheet, "Rotas_Ativas")
    dados = ws.get_all_records()
    return dados

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

def create_pdf(header_data, registros_secoes):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)

    # 1. Dados de Identificação
    pdf.cell(0, 10, '1. Identificação da Rota', 0, 1)
    pdf.set_font('Arial', '', 12)
    
    data_fmt = header_data.get('Data_Inicio', datetime.now().strftime('%d/%m/%Y'))
    
    pdf.multi_cell(0, 8, f"Data Início: {data_fmt}\n"
                         f"Líder: {header_data['Lider']}\n"
                         f"Turma: {header_data['Turma']}\n"
                         f"Rota: {header_data['Rota']}\n"
                         f"Máquina: {header_data['Maquina']}")
    pdf.ln(10)

    # 2. Seções
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, '2. Detalhes da Rotina', 0, 1)

    temp_dir = tempfile.mkdtemp()

    # Organizar registros por seção (pegar o mais recente de cada seção)
    # registros_secoes é uma lista de dicionários vinda do gsheets
    
    for i, reg in enumerate(registros_secoes):
        if i > 0:
            pdf.add_page()
            
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, f"Seção: {reg['Secao_Titulo']}", 0, 1)
        
        pdf.set_font('Arial', 'I', 10)
        pdf.cell(0, 10, f"Registrado em: {reg['Data_Foto']}", 0, 1)

        pdf.set_font('Arial', '', 12)
        pdf.multi_cell(0, 8, f"Observação: {reg['Obs']}")

        # Imagem
        b64_img = reg.get('Imagem_Base64', '')
        if b64_img:
            try:
                img_data = base64.b64decode(b64_img)
                temp_img_path = os.path.join(temp_dir, f"img_{i}.png")
                with open(temp_img_path, "wb") as f:
                    f.write(img_data)
                
                pdf.image(temp_img_path, x=30, w=150)
                os.remove(temp_img_path)
            except Exception as e:
                pdf.set_text_color(255, 0, 0)
                pdf.cell(0, 10, f"Erro ao processar imagem: {e}", 0, 1)
                pdf.set_text_color(0, 0, 0)
        
        pdf.ln(5)

    try:
        os.rmdir(temp_dir)
    except:
        pass

    return pdf.output(dest='S').encode('latin-1')

# --- PÁGINAS DO APP ---

def page_admin(spreadsheet):
    st.title("Área de Administração")
    
    pwd = st.text_input("Senha ADM", type="password")
    if pwd != st.secrets.get("ADMIN_PASS", "1234"): # Senha default 1234 se não tiver nos secrets
        st.warning("Acesso restrito.")
        return

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Líderes", "Turmas", "Rotas", "Máquinas", "Seções", "Limpeza"])

    config_map = {
        "Líderes": ("Lideres", tab1),
        "Turmas": ("Turmas", tab2),
        "Rotas": ("Rotas", tab3),
        "Máquinas": ("Maquinas", tab4)
    }

    for label, (tipo_db, tab) in config_map.items():
        with tab:
            with st.form(f"add_{tipo_db}"):
                novo = st.text_input(f"Novo {label}")
                if st.form_submit_button("Adicionar"):
                    add_item(spreadsheet, tipo_db, novo)
                    st.rerun()
            
            st.divider()
            itens = get_items(spreadsheet, tipo_db)
            for item in itens:
                c1, c2 = st.columns([0.8, 0.2])
                c1.text(item)
                if c2.button("X", key=f"del_{tipo_db}_{item}"):
                    remove_item(spreadsheet, tipo_db, item)
                    st.rerun()

    with tab5:
        with st.form("add_sec"):
            titulo = st.text_input("Nova Seção")
            if st.form_submit_button("Adicionar"):
                add_secao(spreadsheet, titulo)
                st.rerun()
        
        st.divider()
        secoes = get_secoes(spreadsheet)
        for idx, tit in secoes:
            c1, c2 = st.columns([0.8, 0.2])
            c1.text(tit)
            if c2.button("X", key=f"del_sec_{idx}"):
                remove_secao(spreadsheet, idx)
                st.rerun()

    with tab6:
        st.subheader("Manutenção do Banco de Dados")
        st.warning("Cuidado: Isso apaga dados permanentemente.")
        if st.button("Limpar Rotas Travadas/Antigas"):
            # Lógica para limpar rotas antigas poderia ser implementada aqui
            st.info("Funcionalidade de limpeza manual.")

def page_nova_rota(spreadsheet):
    """PASSO 1: Configurar e Criar a Rota"""
    st.title("Iniciar Nova Rota")
    
    lideres = get_items(spreadsheet, 'Lideres')
    turmas = get_items(spreadsheet, 'Turmas')
    rotas = get_items(spreadsheet, 'Rotas')
    maquinas = get_items(spreadsheet, 'Maquinas')

    if not (lideres and turmas and rotas and maquinas):
        st.error("Cadastre os dados na ADM primeiro.")
        return

    with st.form("setup_rota"):
        c1, c2 = st.columns(2)
        lider = c1.selectbox("Líder", lideres)
        turma = c2.selectbox("Turma", turmas)
        rota = c1.selectbox("Rota", rotas)
        maquina = c2.selectbox("Máquina", maquinas)
        
        if st.form_submit_button("COMEÇAR ROTA"):
            dados = {
                "lider": lider, "turma": turma, "rota": rota, "maquina": maquina
            }
            id_rota = iniciar_nova_rota(spreadsheet, dados)
            # Salva no estado da sessão para redirecionar
            st.session_state['active_route_id'] = id_rota
            st.session_state['active_route_data'] = dados
            st.rerun()

def page_continuar_rota(spreadsheet):
    """Menu para retomar rotas interrompidas."""
    st.title("Rotas em Andamento (Histórico)")
    
    rotas_ativas = get_rotas_ativas(spreadsheet)
    if not rotas_ativas:
        st.info("Nenhuma rota pendente encontrada.")
        return

    df = pd.DataFrame(rotas_ativas)
    if not df.empty:
        # Mostra uma tabela para o usuário escolher
        st.dataframe(df[['Lider', 'Rota', 'Data_Inicio', 'ID_Rota']], use_container_width=True)
        
        ids = df['ID_Rota'].tolist()
        selected_id = st.selectbox("Selecione a Rota para Continuar:", ids)
        
        if st.button("Abrir Rota Selecionada"):
            # Recupera os dados da linha selecionada
            row_data = df[df['ID_Rota'] == selected_id].iloc[0].to_dict()
            
            st.session_state['active_route_id'] = selected_id
            st.session_state['active_route_data'] = {
                "lider": row_data['Lider'],
                "turma": row_data['Turma'],
                "rota": row_data['Rota'],
                "maquina": row_data['Maquina'],
                "Data_Inicio": row_data['Data_Inicio']
            }
            st.rerun()

def page_execucao_rota(spreadsheet):
    """PASSO 2: Executar a Rota e Salvar Fotos"""
    if 'active_route_id' not in st.session_state:
        st.warning("Nenhuma rota ativa. Inicie uma nova ou continue uma existente.")
        if st.button("Voltar"):
            st.rerun()
        return

    id_rota = st.session_state['active_route_id']
    dados_rota = st.session_state['active_route_data']
    
    st.markdown(f"### 🟢 Executando Rota: {dados_rota['Rota']}")
    st.markdown(f"**Líder:** {dados_rota['lider']} | **Máquina:** {dados_rota['maquina']} | **ID:** `{id_rota}`")
    st.divider()
    
    # Busca seções e registros já feitos
    secoes = get_secoes(spreadsheet)
    registros_feitos = get_registros_rota(spreadsheet, id_rota)
    
    # Mapeia registros por seção para saber o que já foi feito
    # (Pega o último registro se houver duplicata)
    registros_map = {r['Secao_Titulo']: r for r in registros_feitos}
    
    # Container para o formulário
    # NOTA: Não usamos st.form aqui para permitir salvamento imediato por item
    
    for _, titulo_secao in secoes:
        with st.container():
            st.subheader(f"📌 {titulo_secao}")
            
            # Verifica se já tem foto salva
            registro_atual = registros_map.get(titulo_secao)
            
            col_a, col_b = st.columns([1, 1])
            
            with col_a:
                if registro_atual and registro_atual.get('Imagem_Base64'):
                    st.success(f"✅ Salvo em: {registro_atual['Data_Foto']}")
                    st.markdown(f"**Obs Salva:** {registro_atual['Obs']}")
                    # Decodifica para mostrar (opcional, pode pesar se for muito)
                    try:
                        img_bytes = base64.b64decode(registro_atual['Imagem_Base64'])
                        st.image(img_bytes, width=200, caption="Foto Atual")
                    except:
                        st.error("Erro ao carregar imagem.")
                else:
                    st.info("Pendente")

            with col_b:
                # Entrada de dados para NOVA foto ou ATUALIZAÇÃO
                # Chaves únicas para cada seção
                obs_key = f"obs_{id_rota}_{titulo_secao}"
                cam_key = f"cam_{id_rota}_{titulo_secao}"
                btn_key = f"btn_{id_rota}_{titulo_secao}"
                
                nova_obs = st.text_area("Observação", key=obs_key)
                nova_foto = st.camera_input("Capturar", key=cam_key)
                
                # Botão de salvar individual para garantir o upload
                if nova_foto:
                    if st.button(f"Salvar {titulo_secao}", key=btn_key, type="primary"):
                        with st.spinner("Salvando..."):
                            salvar_foto_registro(spreadsheet, id_rota, titulo_secao, nova_obs, nova_foto)
                        st.success("Salvo!")
                        st.rerun() # Atualiza a tela para mostrar a foto salva na coluna da esquerda
    
    st.divider()
    st.subheader("Finalização")
    
    if st.button("📄 Gerar Relatório e Finalizar Rota", type="primary"):
        # 1. Busca todos os dados atualizados do DB
        todos_registros = get_registros_rota(spreadsheet, id_rota)
        
        if not todos_registros:
            st.error("Nenhuma foto foi registrada nesta rota ainda.")
        else:
            # 2. Gera PDF
            pdf_bytes = create_pdf(dados_rota, todos_registros)
            
            # 3. Disponibiliza Download
            st.download_button(
                label="⬇️ BAIXAR PDF",
                data=pdf_bytes,
                file_name=f"Rota_{dados_rota['lider']}_{id_rota}.pdf",
                mime="application/pdf"
            )
            
            # 4. Finaliza no DB (Remove da lista de ativas)
            if finalizar_rota_db(spreadsheet, id_rota):
                st.success("Rota finalizada e removida da lista de pendências!")
                # Limpa sessão
                del st.session_state['active_route_id']
                del st.session_state['active_route_data']
                if st.button("Voltar ao Início"):
                    st.rerun()

# --- MAIN ---

def main():
    sh = connect_to_gsheets()
    if not sh:
        return
        
    init_db(sh)

    # Sidebar Login
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        
    if not st.session_state.logged_in:
        user = st.sidebar.text_input("Usuário")
        pwd = st.sidebar.text_input("Senha", type="password")
        if st.sidebar.button("Entrar"):
            # Substitua pelos seus secrets reais
            if user == st.secrets.get("LOGIN_USER", "admin") and pwd == st.secrets.get("LOGIN_PASS", "admin"):
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Login inválido")
        return

    st.sidebar.title("Menu")
    
    # Lógica de Navegação
    opcoes = ["Nova Rota", "Continuar Rota (Histórico)", "Admin"]
    
    # Se já estiver em rota, força a visualização ou dá opção de sair
    if 'active_route_id' in st.session_state:
        st.sidebar.warning("⚠️ Rota em Andamento!")
        opcoes = ["Executando Rota", "Sair da Rota Atual", "Admin"]
    
    escolha = st.sidebar.radio("Ir para:", opcoes)
    
    if escolha == "Nova Rota":
        page_nova_rota(sh)
    elif escolha == "Continuar Rota (Histórico)":
        page_continuar_rota(sh)
    elif escolha == "Executando Rota":
        page_execucao_rota(sh)
    elif escolha == "Sair da Rota Atual":
        del st.session_state['active_route_id']
        st.rerun()
    elif escolha == "Admin":
        page_admin(sh)

if __name__ == "__main__":
    main()
