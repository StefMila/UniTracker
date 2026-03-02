import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# Configurazione pagina
st.set_page_config(page_title="Gestione Studio", layout="wide")

# Connessione al database DBeaver (SQLite)
@st.cache_resource
def init_connection():
    return sqlite3.connect('studio.db', check_same_thread=False)

def create_tables(conn):
    """Crea le tabelle necessarie se non esistono"""
    cursor = conn.cursor()
    
    # Tabella semestri
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS semestri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            anno_accademico TEXT NOT NULL,
            data_inizio TEXT,
            data_creazione TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Migrazione: aggiungi data_inizio se non esiste
    try:
        cursor.execute("ALTER TABLE semestri ADD COLUMN data_inizio TEXT")
        conn.commit()
    except:
        pass  # Colonna già esistente
    
    # Tabella materie
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS materie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            semestre_id INTEGER,
            modalita_esame TEXT,
            materiale_concesso TEXT,
            progetto_descrizione TEXT,
            progetto_peso REAL DEFAULT 0,
            lezioni_settimanali INTEGER DEFAULT 1,
            FOREIGN KEY (semestre_id) REFERENCES semestri (id)
        )
    ''')
    
    # Migrazione: aggiungi materiale_concesso se non esiste
    try:
        cursor.execute("ALTER TABLE materie ADD COLUMN materiale_concesso TEXT")
        conn.commit()
    except:
        pass
    
    # Migrazione: aggiungi lezioni_settimanali se non esiste
    try:
        cursor.execute("ALTER TABLE materie ADD COLUMN lezioni_settimanali INTEGER DEFAULT 1")
        conn.commit()
    except:
        pass
    
    # Tabella settimane
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settimane (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semestre_id INTEGER,
            numero_settimana INTEGER,
            data_inizio TEXT,
            data_fine TEXT,
            note TEXT,
            FOREIGN KEY (semestre_id) REFERENCES semestri (id)
        )
    ''')
    
    # Tabella settimane_materie (flag per materia in ogni settimana)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settimane_materie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            settimana_id INTEGER,
            materia_id INTEGER,
            numero_lezione INTEGER DEFAULT 1,
            flag_completato BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (settimana_id) REFERENCES settimane (id),
            FOREIGN KEY (materia_id) REFERENCES materie (id),
            UNIQUE(settimana_id, materia_id, numero_lezione)
        )
    ''')
    
    # Migrazione: aggiungi numero_lezione se non esiste
    try:
        cursor.execute("ALTER TABLE settimane_materie ADD COLUMN numero_lezione INTEGER DEFAULT 1")
        conn.commit()
        # Rimuovi il vecchio constraint UNIQUE e ricrealo
        cursor.execute("DROP INDEX IF EXISTS idx_settimane_materie_unique")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_settimane_materie_unique ON settimane_materie(settimana_id, materia_id, numero_lezione)")
        conn.commit()
    except:
        pass
    
    # Tabella progetti
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS progetti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            materia_id INTEGER,
            stato TEXT DEFAULT 'Da iniziare',
            percentuale_completamento INTEGER DEFAULT 0,
            FOREIGN KEY (materia_id) REFERENCES materie (id)
        )
    ''')
    
    # Tabella deliverable
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deliverable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            progetto_id INTEGER,
            descrizione TEXT,
            data_scadenza TEXT,
            completato BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (progetto_id) REFERENCES progetti (id)
        )
    ''')
    
    # Elimina il semestre "Corrente" se esiste (legacy)
    cursor.execute("DELETE FROM semestri WHERE nome = 'Corrente'")
    
    conn.commit()

def get_semestri(conn):
    return pd.read_sql_query("SELECT * FROM semestri ORDER BY id", conn)

def get_materie_semestre(conn, semestre_id=None):
    if semestre_id is None:
        # Tutte le materie
        query = "SELECT m.* FROM materie m ORDER BY m.nome"
        return pd.read_sql_query(query, conn)
    else:
        # Solo materie del semestre specificato
        query = """
        SELECT m.* 
        FROM materie m 
        WHERE m.semestre_id = ?
        ORDER BY m.nome
        """
        return pd.read_sql_query(query, conn, params=(semestre_id,))

def get_settimane_semestre(conn, semestre_id):
    return pd.read_sql_query(
        "SELECT * FROM settimane WHERE semestre_id = ? ORDER BY numero_settimana", 
        conn, params=(semestre_id,)
    )

def get_progetto_materia(conn, materia_id):
    query = "SELECT * FROM progetti WHERE materia_id = ?"
    result = pd.read_sql_query(query, conn, params=(materia_id,))
    return result.iloc[0] if not result.empty else None

def get_deliverable_progetto(conn, progetto_id):
    return pd.read_sql_query(
        "SELECT * FROM deliverable WHERE progetto_id = ? ORDER BY data_scadenza", 
        conn, params=(progetto_id,)
    )

def calcola_date_settimana(data_inizio_semestre, numero_settimana):
    """Calcola le date di inizio e fine di una settimana"""
    data_inizio = datetime.strptime(data_inizio_semestre, '%Y-%m-%d')
    giorni_offset = (numero_settimana - 1) * 7
    inizio_settimana = data_inizio + timedelta(days=giorni_offset)
    fine_settimana = inizio_settimana + timedelta(days=6)
    return inizio_settimana.strftime('%Y-%m-%d'), fine_settimana.strftime('%Y-%m-%d')

def crea_settimane_semestre(conn, semestre_id, data_inizio, num_settimane=17):
    """Crea le settimane per un semestre"""
    cursor = conn.cursor()
    for i in range(1, num_settimane + 1):
        inizio, fine = calcola_date_settimana(data_inizio, i)
        cursor.execute("""
            INSERT OR IGNORE INTO settimane (semestre_id, numero_settimana, data_inizio, data_fine) 
            VALUES (?, ?, ?, ?)
        """, (semestre_id, i, inizio, fine))
    conn.commit()

def crea_progetto_materia(conn, materia_id):
    """Crea un progetto per una materia se non esiste"""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM progetti WHERE materia_id = ?", (materia_id,))
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO progetti (materia_id) VALUES (?)", (materia_id,))
        conn.commit()
        return cursor.lastrowid
    return None

# Inizializzazione
conn = init_connection()
create_tables(conn)

# ========== SIDEBAR ==========
st.sidebar.title("🎓 Studio Tracker")

# Carica semestri
semestri_df = get_semestri(conn)
if semestri_df.empty:
    st.error("Nessun semestre trovato!")
    st.stop()

semestre_options = {row['nome']: row['id'] for _, row in semestri_df.iterrows()}

# Filtri
filtro_semestre_label = st.sidebar.selectbox(
    "Filtro semestre:",
    options=["Tutti i semestri"] + list(semestre_options.keys()),
    key="filtro_semestre"
)
semestre_filtro_id = None
if filtro_semestre_label != "Tutti i semestri":
    semestre_filtro_id = semestre_options[filtro_semestre_label]

materie_filtro_df = get_materie_semestre(conn, semestre_filtro_id)
materia_filtro_label = "Tutte le materie"
materia_filtro_id = None
if not materie_filtro_df.empty:
    materia_options = {row['nome']: row['id'] for _, row in materie_filtro_df.iterrows()}
    materia_filtro_label = st.sidebar.selectbox(
        "Filtro materia:",
        options=["Tutte le materie"] + list(materia_options.keys()),
        key="filtro_materia"
    )
    if materia_filtro_label != "Tutte le materie":
        materia_filtro_id = materia_options[materia_filtro_label]
else:
    st.sidebar.info("Nessuna materia disponibile per il filtro")

filtro_attivita = st.sidebar.selectbox(
    "Attivita appunti:",
    options=["Tutte", "Completate", "Non completate"],
    key="filtro_attivita"
)

st.sidebar.markdown("---")

# Nuovo Semestre
with st.sidebar.expander("➕ Nuovo Semestre"):
    nuovo_semestre = st.text_input("Nome semestre", key="new_semestre_name")
    anno_acc = st.text_input("Anno accademico", value="2025-2026", key="new_anno_acc")
    data_inizio_sem = st.date_input("Data inizio", value=datetime.now().date(), key="data_inizio_sem")
    if st.button("Crea Semestre", key="crea_sem") and nuovo_semestre:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO semestri (nome, anno_accademico, data_inizio) VALUES (?, ?, ?)",
            (nuovo_semestre, anno_acc, data_inizio_sem.strftime('%Y-%m-%d'))
        )
        semestre_id_new = cursor.lastrowid
        conn.commit()
        # Crea 17 settimane
        crea_settimane_semestre(conn, semestre_id_new, data_inizio_sem.strftime('%Y-%m-%d'))
        st.sidebar.success("Semestre creato!")
        st.rerun()

# Rinomina Semestre
with st.sidebar.expander("✏️ Rinomina Semestre"):
    semestre_rename = st.selectbox(
        "Semestre:",
        options=list(semestre_options.keys()),
        key="semestre_rename_select"
    )
    nuovo_nome_semestre = st.text_input("Nuovo nome", key="nuovo_nome_semestre")
    if st.button("Salva Nome", key="save_nome_semestre") and nuovo_nome_semestre:
        conn.execute(
            "UPDATE semestri SET nome = ? WHERE id = ?",
            (nuovo_nome_semestre, semestre_options[semestre_rename])
        )
        conn.commit()
        st.sidebar.success("Nome semestre aggiornato!")
        st.rerun()

# Nuova Materia
with st.sidebar.expander("➕ Aggiungi Materia"):
    nuovo_nome_mat = st.text_input("Nome materia", key="new_materia_name")
    semestre_materia_new = st.selectbox(
        "Semestre",
        options=list(semestre_options.keys()),
        key="semestre_materia_new"
    )
    lezioni_sett_new = st.number_input(
        "Lezioni settimanali",
        min_value=1,
        max_value=10,
        value=1,
        key="lezioni_sett_new",
        help="Numero di lezioni di questa materia per settimana"
    )
    if st.button("Crea Materia", key="crea_mat") and nuovo_nome_mat:
        semestre_new_id = semestre_options[semestre_materia_new]
        cursor = conn.cursor()
        cursor.execute("INSERT INTO materie (nome, semestre_id, lezioni_settimanali) VALUES (?, ?, ?)", 
                      (nuovo_nome_mat, semestre_new_id, lezioni_sett_new))
        materia_id_new = cursor.lastrowid
        conn.commit()
        # Crea progetto
        crea_progetto_materia(conn, materia_id_new)
        # Crea flag per tutte le settimane
        settimane = get_settimane_semestre(conn, semestre_new_id)
        if settimane.empty:
            data_inizio_sem = semestri_df[semestri_df['id'] == semestre_new_id]['data_inizio'].values
            if len(data_inizio_sem) > 0 and data_inizio_sem[0]:
                crea_settimane_semestre(conn, semestre_new_id, data_inizio_sem[0])
                settimane = get_settimane_semestre(conn, semestre_new_id)
        for _, sett in settimane.iterrows():
            # Crea N flag per ogni settimana in base al numero di lezioni settimanali
            for num_lez in range(1, lezioni_sett_new + 1):
                cursor.execute(
                    "INSERT OR IGNORE INTO settimane_materie (settimana_id, materia_id, numero_lezione) VALUES (?, ?, ?)",
                    (sett['id'], materia_id_new, num_lez)
                )
        conn.commit()
        st.sidebar.success("Materia creata!")
        st.rerun()

# ========== TAB NAVIGATION ==========
st.title("🎓 Gestione Studio - Università")

tab0, tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📚 Materie", "📅 Lezioni", "🎯 Progetti"])

# ========== TAB 0: DASHBOARD ==========
with tab0:
    materie_view_df = get_materie_semestre(conn, semestre_filtro_id)
    if materia_filtro_id:
        materie_view_df = materie_view_df[materie_view_df['id'] == materia_filtro_id]

    st.subheader("✅ Appunti da sistemare")
    st.caption("Lezioni pregresse non completate")
    if materie_view_df.empty:
        st.info("Nessuna materia disponibile per il filtro selezionato.")
    else:
        # Mostra solo lezioni PASSATE non completate
        today = datetime.now().strftime('%Y-%m-%d')
        query_pregresse = f"""
            SELECT DISTINCT m.id, m.nome,
                   SUM(CASE WHEN sm.flag_completato = 1 THEN 1 ELSE 0 END) as completate,
                   COUNT(*) as totale
            FROM materie m
            LEFT JOIN settimane_materie sm ON m.id = sm.materia_id
            LEFT JOIN settimane s ON sm.settimana_id = s.id
            WHERE m.id IN ({','.join(['?' for _ in materie_view_df['id']])})
              AND s.data_fine < '{today}'
            GROUP BY m.id, m.nome
        """
        pregresse_df = pd.read_sql_query(query_pregresse, conn, params=list(materie_view_df['id']))
        
        if pregresse_df.empty:
            st.success("Nessuna lezione pregressa da completare! ✓")
        else:
            for _, row in pregresse_df.iterrows():
                completate = int(row['completate']) if row['completate'] else 0
                totale = int(row['totale']) if row['totale'] else 0
                if totale > 0 and completate < totale:
                    perc = (completate / totale) * 100
                    st.markdown(f"**{row['nome']}**")
                    st.progress(perc / 100)
                    st.caption(f"{completate}/{totale} completate - {perc:.0f}%")

    st.markdown("---")
    st.subheader("📅 Prossime scadenze")
    st.caption("Prossimi 7 giorni")
    if materie_view_df.empty:
        st.info("Nessuna scadenza disponibile per il filtro selezionato.")
    else:
        today = datetime.now().strftime('%Y-%m-%d')
        date_7days = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        materia_ids = list(materie_view_df['id'])
        params = [today, date_7days]
        query = (
            "SELECT d.id, d.descrizione, d.data_scadenza, d.completato, m.nome as materia_nome "
            "FROM deliverable d "
            "JOIN progetti p ON d.progetto_id = p.id "
            "JOIN materie m ON p.materia_id = m.id "
            "WHERE d.completato = 0 AND d.data_scadenza IS NOT NULL "
            "AND d.data_scadenza >= ? AND d.data_scadenza <= ?"
        )
        if materia_ids:
            placeholders = ",".join(["?"] * len(materia_ids))
            query += f" AND m.id IN ({placeholders})"
            params.extend(materia_ids)

        query += " ORDER BY d.data_scadenza ASC"
        scadenze_df = pd.read_sql_query(query, conn, params=params)

        if scadenze_df.empty:
            st.info("Nessuna scadenza nei prossimi 7 giorni.")
        else:
            for _, row in scadenze_df.iterrows():
                st.markdown(f"**{row['materia_nome']}**")
                st.caption(f"{row['data_scadenza']} - {row['descrizione']}")

# ========== TAB 1: MATERIE ==========
with tab1:
    # Applica filtro semestre/materia
    materie_df = get_materie_semestre(conn, semestre_filtro_id)
    if materia_filtro_id:
        materie_df = materie_df[materie_df['id'] == materia_filtro_id]
    
    if not materie_df.empty and filtro_attivita != "Tutte":
        materie_cols = list(materie_df.columns)
        stats_df = pd.read_sql_query(
            """
            SELECT materia_id,
                   SUM(CASE WHEN flag_completato = 1 THEN 1 ELSE 0 END) as completate,
                   COUNT(*) as totale
            FROM settimane_materie
            GROUP BY materia_id
            """,
            conn
        )
        merged = materie_df.merge(stats_df, left_on='id', right_on='materia_id', how='left')
        merged['completate'] = merged['completate'].fillna(0)
        merged['totale'] = merged['totale'].fillna(0)

        if filtro_attivita == "Completate":
            materie_df = merged[merged['totale'] > 0]
            materie_df = materie_df[materie_df['completate'] == materie_df['totale']]
        elif filtro_attivita == "Non completate":
            materie_df = merged[(merged['totale'] == 0) | (merged['completate'] < merged['totale'])]
        materie_df = materie_df[materie_cols]

    if materie_df.empty:
        st.info("Nessuna materia disponibile con i filtri selezionati.")
    else:
        # Visualizza materie in 2 colonne
        cols = st.columns(2)
        
        for idx, materia in materie_df.iterrows():
            with cols[idx % 2]:
                # Card materia
                st.markdown(f"### {materia['nome']}")
                
                # Mostra badge semestre se il filtro e' su tutti i semestri
                if semestre_filtro_id is None and materia['semestre_id']:
                    semestre_nome = semestri_df[semestri_df['id'] == materia['semestre_id']]['nome'].values
                    if len(semestre_nome) > 0:
                        st.caption(f"📚 Semestre: {semestre_nome[0]}")
                
                with st.expander("✏️ Modifica", expanded=False):
                    # Selezione semestre
                    semestre_materia_options = {row['nome']: row['id'] for _, row in semestri_df.iterrows()}
                    semestre_materia_attuale = materia['semestre_id']
                    
                    # Trova l'indice del semestre corrente
                    semestre_keys = list(semestre_materia_options.keys())
                    semestre_values = list(semestre_materia_options.values())
                    try:
                        indice_semestre = semestre_values.index(semestre_materia_attuale)
                    except ValueError:
                        indice_semestre = 0
                    
                    semestre_selezionato_materia = st.selectbox(
                        "Semestre",
                        options=semestre_keys,
                        index=indice_semestre,
                        key=f"sem_{materia['id']}"
                    )
                    
                    # Campo lezioni settimanali
                    lezioni_sett_value = int(materia.get('lezioni_settimanali', 1) or 1)
                    lezioni_sett = st.number_input(
                        "Lezioni settimanali",
                        min_value=1,
                        max_value=10,
                        value=lezioni_sett_value,
                        key=f"lez_sett_{materia['id']}",
                        help="Numero di lezioni di questa materia per settimana"
                    )
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        modalita = st.text_area(
                            "Modalità d'Esame",
                            value=materia['modalita_esame'] or "",
                            key=f"mod_{materia['id']}",
                            height=100
                        )
                        
                        materiale = st.text_area(
                            "Materiale Concesso Durante l'Esame",
                            value=materia['materiale_concesso'] or "",
                            key=f"mat_{materia['id']}",
                            height=80
                        )
                    
                    with col2:
                        progetto_desc = st.text_area(
                            "Progetto",
                            value=materia['progetto_descrizione'] or "",
                            key=f"prog_{materia['id']}",
                            height=100
                        )
                        
                        peso = st.number_input(
                            "Peso Progetto sul Voto Finale (%)",
                            min_value=0.0,
                            max_value=100.0,
                            value=float(materia['progetto_peso'] or 0),
                            key=f"peso_{materia['id']}"
                        )
                    
                    # Pulsanti Salva ed Elimina affiancati
                    col_save, col_del = st.columns(2)
                    
                    with col_save:
                        if st.button("💾 Salva", key=f"save_mat_{materia['id']}", use_container_width=True):
                            nuovo_semestre_id = semestre_materia_options[semestre_selezionato_materia]
                            vecchio_semestre_id = materia['semestre_id']
                            vecchie_lezioni_sett = int(materia.get('lezioni_settimanali', 1) or 1)
                            
                            # Aggiorna la materia
                            conn.execute(
                                '''UPDATE materie SET modalita_esame=?, materiale_concesso=?, 
                                   progetto_descrizione=?, progetto_peso=?, semestre_id=?, lezioni_settimanali=? WHERE id=?''',
                                (modalita, materiale, progetto_desc, peso, nuovo_semestre_id, lezioni_sett, materia['id'])
                            )
                            
                            cursor = conn.cursor()
                            
                            # Se il numero di lezioni è cambiato, aggiorna i record
                            if lezioni_sett != vecchie_lezioni_sett:
                                # Recupera tutte le settimane del semestre corrente
                                settimane_cur = get_settimane_semestre(conn, nuovo_semestre_id)
                                
                                if lezioni_sett > vecchie_lezioni_sett:
                                    # Aggiungi nuovi flag
                                    for _, sett in settimane_cur.iterrows():
                                        for num_lez in range(vecchie_lezioni_sett + 1, lezioni_sett + 1):
                                            cursor.execute(
                                                "INSERT OR IGNORE INTO settimane_materie (settimana_id, materia_id, numero_lezione) VALUES (?, ?, ?)",
                                                (sett['id'], materia['id'], num_lez)
                                            )
                                else:
                                    # Rimuovi i flag in eccesso
                                    for _, sett in settimane_cur.iterrows():
                                        cursor.execute(
                                            "DELETE FROM settimane_materie WHERE settimana_id=? AND materia_id=? AND numero_lezione>?",
                                            (sett['id'], materia['id'], lezioni_sett)
                                        )
                            
                            # Se il semestre è cambiato, aggiorna i record settimane_materie
                            if nuovo_semestre_id != vecchio_semestre_id:
                                # Rimuovi vecchi record
                                cursor.execute(
                                    '''DELETE FROM settimane_materie 
                                       WHERE materia_id = ? AND settimana_id IN 
                                       (SELECT id FROM settimane WHERE semestre_id = ?)''',
                                    (materia['id'], vecchio_semestre_id)
                                )
                                # Crea nuovi record per il nuovo semestre
                                settimane_nuovo = get_settimane_semestre(conn, nuovo_semestre_id)
                                for _, sett in settimane_nuovo.iterrows():
                                    for num_lez in range(1, lezioni_sett + 1):
                                        cursor.execute(
                                            "INSERT OR IGNORE INTO settimane_materie (settimana_id, materia_id, numero_lezione) VALUES (?, ?, ?)",
                                            (sett['id'], materia['id'], num_lez)
                                        )
                            
                            conn.commit()
                            st.success("Materia aggiornata!")
                            st.rerun()
                    
                    with col_del:
                        if st.button("🗑️ Elimina", key=f"del_mat_{materia['id']}", type="secondary", use_container_width=True):
                            try:
                                cursor = conn.cursor()
                                # Elimina i flag dalle settimane_materie
                                cursor.execute("DELETE FROM settimane_materie WHERE materia_id = ?", (materia['id'],))
                                # Elimina i deliverable associati al progetto
                                cursor.execute(
                                    "DELETE FROM deliverable WHERE progetto_id IN (SELECT id FROM progetti WHERE materia_id = ?)",
                                    (materia['id'],)
                                )
                                # Elimina il progetto
                                cursor.execute("DELETE FROM progetti WHERE materia_id = ?", (materia['id'],))
                                # Elimina la materia
                                cursor.execute("DELETE FROM materie WHERE id = ?", (materia['id'],))
                                conn.commit()
                                st.success(f"✓ '{materia['nome']}' eliminata!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Errore durante l'eliminazione: {str(e)}")
                
                # Statistiche materia
                query = f"""
                    SELECT COUNT(*) as totale, 
                           SUM(CASE WHEN flag_completato = 1 THEN 1 ELSE 0 END) as completate
                    FROM settimane_materie
                    WHERE materia_id = {materia['id']}
                """
                stats = pd.read_sql_query(query, conn)
                
                if stats.iloc[0]['totale'] > 0:
                    completate = stats.iloc[0]['completate'] or 0
                    totale = stats.iloc[0]['totale']
                    perc = (completate / totale * 100) if totale > 0 else 0
                    
                    st.markdown(f"**Lezioni Completate**")
                    st.progress(perc / 100)
                    st.caption(f"{completate} di {totale} ({perc:.0f}%)")
                
                # Progetto
                progetto = get_progetto_materia(conn, materia['id'])
                if progetto is not None:
                    st.markdown(f"**Progetto: {progetto['percentuale_completamento']}% completato**")
                    st.progress(progetto['percentuale_completamento'] / 100)
                    st.caption(f"Stato: {progetto['stato']}")
                
                st.markdown("---")

# ========== TAB 2: LEZIONI ==========
with tab2:
    st.subheader("📅 Lezioni Settimanali")
    
    # Seleziona i semestri da mostrare
    if semestre_filtro_id is None:
        semestri_da_mostrare = semestri_df.to_dict('records')
    else:
        semestri_da_mostrare = [s for s in semestri_df.to_dict('records') if s['id'] == semestre_filtro_id]
    
    if not semestri_da_mostrare:
        st.warning("Nessun semestre disponibile")
    else:
        for semestre in semestri_da_mostrare:
            semestre_id = semestre['id']
            st.markdown(f"### 📚 {semestre['nome']}")
            
            # Recupera le settimane del semestre
            settimane_df = get_settimane_semestre(conn, semestre_id)
            
            if settimane_df.empty:
                # Crea le settimane
                data_inizio = semestre.get('data_inizio')
                if data_inizio:
                    crea_settimane_semestre(conn, semestre_id, data_inizio)
                    st.rerun()
                else:
                    st.warning(f"Imposta una data di inizio per {semestre['nome']}")
                    continue
            
            # Recupera le materie del semestre
            materie_semestre = get_materie_semestre(conn, semestre_id)
            
            # Applica filtro materia se necessario
            if materia_filtro_id:
                materie_semestre = materie_semestre[materie_semestre['id'] == materia_filtro_id]
            
            if materie_semestre.empty:
                st.info(f"Nessuna materia disponibile per {semestre['nome']}")
                st.markdown("---")
                continue
            
            # Mostra statistiche semestre
            query_stats = f"""
                SELECT COUNT(*) as totale,
                       SUM(CASE WHEN flag_completato = 1 THEN 1 ELSE 0 END) as completate
                FROM settimane_materie sm
                JOIN settimane s ON sm.settimana_id = s.id
                WHERE s.semestre_id = {semestre_id}
            """
            stats = pd.read_sql_query(query_stats, conn)
            if stats.iloc[0]['totale'] > 0:
                completate = stats.iloc[0]['completate'] or 0
                totale = stats.iloc[0]['totale']
                perc = (completate / totale * 100) if totale > 0 else 0
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.caption(f"✅ {perc:.0f}% completato")
                with col2:
                    st.caption(f"{completate}/{totale}")
            
            st.markdown("---")
            
            # Mostra ogni settimana
            for _, settimana in settimane_df.iterrows():
                col_week, col_note = st.columns([5, 1])
                
                with col_week:
                    data_i = datetime.strptime(settimana['data_inizio'], '%Y-%m-%d').strftime('%d/%m')
                    data_f = datetime.strptime(settimana['data_fine'], '%Y-%m-%d').strftime('%d/%m')
                    
                    st.markdown(f"**Settimana {settimana['numero_settimana']}** · {data_i} - {data_f}")
                    
                    # Calcola completamento settimana
                    query_week = f"""
                        SELECT COUNT(*) as totale,
                               SUM(CASE WHEN flag_completato = 1 THEN 1 ELSE 0 END) as completate
                        FROM settimane_materie
                        WHERE settimana_id = {settimana['id']}
                    """
                    stats_week = pd.read_sql_query(query_week, conn)
                    comp_week = stats_week.iloc[0]['completate'] or 0
                    tot_week = stats_week.iloc[0]['totale'] or 1
                    perc_week = (comp_week / tot_week * 100) if tot_week > 0 else 0
                    
                    st.progress(perc_week / 100)
                    st.caption(f"{comp_week}/{tot_week} - {perc_week:.0f}%")
                
                with col_note:
                    if st.button("📝", key=f"note_btn_{settimana['id']}"):
                        st.session_state[f"show_note_{settimana['id']}"] = True
                
                if st.session_state.get(f"show_note_{settimana['id']}", False):
                    note_val = st.text_area(
                        "Note",
                        value=settimana['note'] or "",
                        key=f"note_text_{settimana['id']}",
                        height=80
                    )
                    if st.button("💾 Salva", key=f"save_note_{settimana['id']}"):
                        conn.execute(
                            "UPDATE settimane SET note=? WHERE id=?",
                            (note_val, settimana['id'])
                        )
                        conn.commit()
                        st.session_state[f"show_note_{settimana['id']}"] = False
                        st.success("✓")
                
                # Assicura che i record esistono
                for _, materia in materie_semestre.iterrows():
                    lezioni_sett = int(materia.get('lezioni_settimanali', 1) or 1)
                    for num_lez in range(1, lezioni_sett + 1):
                        conn.execute(
                            "INSERT OR IGNORE INTO settimane_materie (settimana_id, materia_id, numero_lezione) VALUES (?, ?, ?)",
                            (settimana['id'], materia['id'], num_lez)
                        )
                conn.commit()
                
                # Mostra i checkbox delle materie in colonne verticali
                # Crea una colonna per ogni materia
                cols_materie = st.columns(len(materie_semestre))
                
                for idx_mat, (_, materia) in enumerate(materie_semestre.iterrows()):
                    lezioni_sett = int(materia.get('lezioni_settimanali', 1) or 1)
                    
                    with cols_materie[idx_mat]:
                        # Nome della materia
                        st.markdown(f"**{materia['nome']}**")
                        
                        # Checkbox delle lezioni in verticale
                        for num_lez in range(1, lezioni_sett + 1):
                            # Recupera lo stato del flag per questa lezione specifica
                            flag_query = f"""
                                SELECT flag_completato FROM settimane_materie
                                WHERE settimana_id = {settimana['id']} 
                                AND materia_id = {materia['id']}
                                AND numero_lezione = {num_lez}
                            """
                            flag_df = pd.read_sql_query(flag_query, conn)
                            flag_value = bool(flag_df.iloc[0]['flag_completato']) if not flag_df.empty else False
                            
                            # Determina se mostrare il checkbox
                            should_show = True
                            if filtro_attivita == "Completate" and not flag_value:
                                should_show = False
                            elif filtro_attivita == "Non completate" and flag_value:
                                should_show = False
                            
                            # Mostra il checkbox con etichetta "Lez. N"
                            new_flag = st.checkbox(
                                f"Lez. {num_lez}",
                                value=flag_value,
                                key=f"flag_s{settimana['id']}_m{materia['id']}_l{num_lez}",
                                disabled=not should_show
                            )
                            
                            # Salva automaticamente il cambio
                            if new_flag != flag_value:
                                conn.execute(
                                    "UPDATE settimane_materie SET flag_completato=? WHERE settimana_id=? AND materia_id=? AND numero_lezione=?",
                                    (1 if new_flag else 0, settimana['id'], materia['id'], num_lez)
                                )
                                conn.commit()
                
                st.markdown("---")
            
            if semestre != semestri_da_mostrare[-1]:
                st.markdown("")

# ========== TAB 3: PROGETTI ==========
with tab3:
    # Applica filtro semestre
    materie_df = get_materie_semestre(conn, semestre_filtro_id)
    if materia_filtro_id:
        materie_df = materie_df[materie_df['id'] == materia_filtro_id]

    if semestre_filtro_id is None:
        st.caption("📚 Visualizzazione: Tutti i semestri")
    else:
        st.caption(f"📚 Visualizzazione: {filtro_semestre_label}")
    
    if materie_df.empty:
        st.info("Nessuna materia con progetti disponibile.")
    else:
        # Statistiche progetti
        st.subheader("📊 Progresso Progetti")
        
        progetti_data = []
        for _, materia in materie_df.iterrows():
            progetto = get_progetto_materia(conn, materia['id'])
            if progetto is not None:
                progetti_data.append({
                    'nome': materia['nome'],
                    'percentuale': progetto['percentuale_completamento'],
                    'stato': progetto['stato']
                })
        
        if progetti_data:
            # Grafico a ciambella
            col_graph, col_list = st.columns([1, 1])
            
            with col_graph:
                df_progetti = pd.DataFrame(progetti_data)
                media_completamento = df_progetti['percentuale'].mean()
                st.metric("Media", f"{media_completamento:.0f}% completato")
                
                # Crea grafico con plotly
                fig = go.Figure(data=[go.Pie(
                    labels=df_progetti['nome'],
                    values=df_progetti['percentuale'],
                    hole=.5,
                    marker_colors=px.colors.qualitative.Set2
                )])
                fig.update_layout(
                    title="Progresso Progetti per Materia",
                    height=400
                )
                st.plotly_chart(fig, use_container_width=True)
            
            with col_list:
                st.subheader("🎯 Stato Progetti per Materia")
                
                for prog in progetti_data:
                    stato_color = {
                        'Da iniziare': '🔴',
                        'In corso': '🟡',
                        'Completato': '🟢',
                        'Attivo': '🔵'
                    }.get(prog['stato'], '⚪')
                    
                    stato_badge = {
                        'Da iniziare': '🔴',
                        'In corso': '🟡',
                        'Completato': '✅ Attivo',
                        'Attivo': '🔵 Attivo'
                    }.get(prog['stato'], prog['stato'])
                    
                    st.markdown(f"**{prog['nome']}**")
                    st.progress(prog['percentuale'] / 100)
                    col_p1, col_p2 = st.columns([3, 1])
                    with col_p1:
                        st.caption(f"{prog['percentuale']}% Completato")
                    with col_p2:
                        if prog['stato'] == 'Completato' or prog['stato'] == 'Attivo':
                            st.success(prog['stato'])
                        else:
                            st.caption(prog['stato'])
                    st.markdown("")
        
        st.markdown("---")
        
        # Deadlines - Tutte le scadenze
        st.subheader("📋 deadlines")
        
        query_all_scadenze = (
            "SELECT d.id, d.descrizione, d.data_scadenza, d.completato, m.nome as materia_nome "
            "FROM deliverable d "
            "JOIN progetti p ON d.progetto_id = p.id "
            "JOIN materie m ON p.materia_id = m.id "
            "ORDER BY COALESCE(d.data_scadenza, '9999-12-31') ASC"
        )
        all_scadenze_df = pd.read_sql_query(query_all_scadenze, conn)
        
        if all_scadenze_df.empty:
            st.info("Nessuna deliverable registrata.")
        else:
            for _, row in all_scadenze_df.iterrows():
                st.markdown(f"**{row['materia_nome']}**")
                data_display = row['data_scadenza'] if row['data_scadenza'] else "Nessuna data"
                st.caption(f"{data_display} - {row['descrizione']}")
        
        st.markdown("---")
        
        # Gestione progetti individuali
        st.subheader("✏️ Gestione Progetti")
        
        for _, materia in materie_df.iterrows():
            with st.expander(f"📚 {materia['nome']}"):
                progetto = get_progetto_materia(conn, materia['id'])
                
                if progetto is None:
                    # Crea progetto
                    crea_progetto_materia(conn, materia['id'])
                    st.rerun()
                else:
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        stato = st.selectbox(
                            "Stato Progetto",
                            ["Da iniziare", "In corso", "Completato", "Attivo"],
                            index=["Da iniziare", "In corso", "Completato", "Attivo"].index(progetto['stato']),
                            key=f"stato_prog_{progetto['id']}"
                        )
                    
                    with col2:
                        percentuale = st.slider(
                            "Percentuale Completamento",
                            0, 100,
                            int(progetto['percentuale_completamento']),
                            key=f"perc_prog_{progetto['id']}"
                        )
                    
                    if st.button("💾 Aggiorna Progetto", key=f"save_prog_{progetto['id']}"):
                        conn.execute(
                            "UPDATE progetti SET stato=?, percentuale_completamento=? WHERE id=?",
                            (stato, percentuale, progetto['id'])
                        )
                        conn.commit()
                        st.success("Progetto aggiornato!")
                        st.rerun()
                    
                    # Deliverable
                    st.markdown("**📅 Deliverable**")
                    deliverable_df = get_deliverable_progetto(conn, progetto['id'])
                    
                    if not deliverable_df.empty:
                        for _, deliv in deliverable_df.iterrows():
                            col_check, col_desc, col_data = st.columns([1, 4, 2])
                            
                            with col_check:
                                compl = st.checkbox(
                                    "",
                                    value=bool(deliv['completato']),
                                    key=f"deliv_{deliv['id']}"
                                )
                                if compl != bool(deliv['completato']):
                                    conn.execute(
                                        "UPDATE deliverable SET completato=? WHERE id=?",
                                        (compl, deliv['id'])
                                    )
                                    conn.commit()
                            
                            with col_desc:
                                st.markdown(deliv['descrizione'])
                            
                            with col_data:
                                st.caption(deliv['data_scadenza'])
                    
                    # Nuovo deliverable
                    with st.form(key=f"form_deliv_{progetto['id']}"):
                        col_d1, col_d2, col_d3 = st.columns([3, 2, 1])
                        
                        with col_d1:
                            desc_deliv = st.text_input("Descrizione", key=f"desc_deliv_{progetto['id']}")
                        
                        with col_d2:
                            data_deliv = st.date_input("Scadenza", key=f"data_deliv_{progetto['id']}")
                        
                        with col_d3:
                            submit = st.form_submit_button("➕ Aggiungi")
                        
                        if submit and desc_deliv:
                            conn.execute(
                                "INSERT INTO deliverable (progetto_id, descrizione, data_scadenza) VALUES (?, ?, ?)",
                                (progetto['id'], desc_deliv, data_deliv.strftime('%Y-%m-%d'))
                            )
                            conn.commit()
                            st.success("Deliverable aggiunto!")
                            st.rerun()

# Footer
st.markdown("---")
st.markdown("*Gestione Studio - Università | Database SQLite - Vicenza, 2026*")


