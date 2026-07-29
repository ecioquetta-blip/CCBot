"""
CCBot – Bot de backup de grupos com tópicos (Telegram)
------------------------------------------------------
Basta configurar DONO_ID e TOKEN abaixo.
Requisitos: Python 3.8+, python-telegram-bot 20.x
Instalação: pip install python-telegram-bot
"""

import sqlite3, json, os, sys, asyncio, re, threading
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# =====================================================================
# CONFIGURAÇÕES OBRIGATÓRIAS (cada pessoa deve alterar aqui)
# =====================================================================
DONO_ID = 123456789          # Seu ID de usuário do Telegram (obtenha com @userinfobot)
TOKEN   = "SEU_TOKEN_AQUI"   # Token do bot criado no @BotFather

# =====================================================================
# Configurações opcionais
# =====================================================================
VERIFICACAO_ORFAS = 600      # Intervalo (segundos) para verificar tópicos deletados. 0 = desativado.

# =====================================================================
# NÃO ALTERAR ABAIXO (a menos que saiba o que está fazendo)
# =====================================================================
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DB_FILE = "auto_forward.db"
CURSOR_FILE = "cursor.json"
LOG_FILE = "falhas.log"

pending_confirmations = {}
topic_name_cache = {}

# ---------- banco de dados ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            source_chat_id INTEGER NOT NULL,
            source_thread_id INTEGER,
            dest_chat_id INTEGER NOT NULL,
            dest_thread_id INTEGER,
            label TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS message_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_chat_id INTEGER NOT NULL,
            source_msg_id INTEGER NOT NULL,
            dest_chat_id INTEGER NOT NULL,
            dest_msg_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT,
            source_chat_id INTEGER,
            source_msg_id INTEGER,
            dest_chat_id INTEGER,
            dest_msg_id INTEGER,
            erro TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS espelhamento (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            source_chat_id INTEGER NOT NULL,
            dest_chat_id INTEGER NOT NULL,
            UNIQUE(source_chat_id, dest_chat_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS known_chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS topic_aliases (
            chat_id INTEGER NOT NULL,
            thread_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            PRIMARY KEY (chat_id, thread_id))""")
    # Colunas que podem não existir em bases antigas
    try:
        c.execute("ALTER TABLE mapping ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE mapping ADD COLUMN label TEXT")
    except sqlite3.OperationalError: pass
    try:
        c.execute("ALTER TABLE espelhamento ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError: pass
    conn.commit()
    conn.close()

# ---------- funções auxiliares de banco ----------
def update_known_chat(chat_id, title):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO known_chats (chat_id, title, last_seen) VALUES (?, ?, ?)",
                 (chat_id, title, datetime.now().isoformat()))
    conn.commit(); conn.close()

def get_known_chats():
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("SELECT chat_id, title FROM known_chats ORDER BY last_seen DESC").fetchall()
    conn.close(); return rows

def limpar_mensagens_antigas():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    limite = datetime.now() - timedelta(days=60)
    c.execute("DELETE FROM message_link WHERE created_at < ?", (limite.strftime("%Y-%m-%d %H:%M:%S"),))
    removidos = c.rowcount
    conn.commit(); conn.close()
    if removidos: print(f"🧹 Limpeza: {removidos} registros antigos removidos")

# ---------- mapeamentos ----------
def add_mapping(user_id, src_chat, src_th, dst_chat, dst_th, label=None):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM mapping WHERE user_id=? AND source_chat_id=? AND source_thread_id IS ?",
                 (user_id, src_chat, src_th))
    conn.execute("INSERT INTO mapping (user_id,source_chat_id,source_thread_id,dest_chat_id,dest_thread_id,label) VALUES (?,?,?,?,?,?)",
                 (user_id, src_chat, src_th, dst_chat, dst_th, label))
    conn.commit(); conn.close()

def get_mapping(src_chat, src_th):
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT dest_chat_id, dest_thread_id FROM mapping WHERE source_chat_id=? AND source_thread_id IS ? LIMIT 1",
                       (src_chat, src_th)).fetchone()
    conn.close(); return row

def delete_mapping(src_chat, src_th):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM mapping WHERE source_chat_id=? AND source_thread_id IS ?", (src_chat, src_th))
    conn.commit(); conn.close()

def delete_mapping_for_user(user_id, src_chat, src_th):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM mapping WHERE user_id=? AND source_chat_id=? AND source_thread_id IS ?",
                 (user_id, src_chat, src_th))
    conn.commit(); conn.close()

def delete_all_mappings(user_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM mapping WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

def set_mapping_label(user_id, src_chat, src_th, label):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE mapping SET label=? WHERE user_id=? AND source_chat_id=? AND source_thread_id IS ?",
                 (label, user_id, src_chat, src_th))
    conn.commit(); conn.close()

def list_mappings(user_id=None):
    conn = sqlite3.connect(DB_FILE)
    if user_id is not None:
        if user_id == DONO_ID:
            rows = conn.execute("SELECT * FROM mapping WHERE user_id=? OR user_id=0", (user_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM mapping WHERE user_id=?", (user_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM mapping").fetchall()
    conn.close(); return rows

# ---------- espelhamento ----------
def adicionar_espelhamento(user_id, src_chat, dst_chat):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR IGNORE INTO espelhamento (user_id,source_chat_id,dest_chat_id) VALUES (?,?,?)",
                 (user_id, src_chat, dst_chat))
    conn.commit(); conn.close()

def remover_espelhamento(user_id, src_chat, dst_chat):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM espelhamento WHERE user_id=? AND source_chat_id=? AND dest_chat_id=?",
                 (user_id, src_chat, dst_chat))
    conn.commit(); conn.close()

def listar_espelhamentos(user_id=None):
    conn = sqlite3.connect(DB_FILE)
    if user_id is not None:
        if user_id == DONO_ID:
            rows = conn.execute("SELECT * FROM espelhamento WHERE user_id=? OR user_id=0", (user_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM espelhamento WHERE user_id=?", (user_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM espelhamento").fetchall()
    conn.close(); return rows

# ---------- vínculo de mensagens ----------
def salvar_vinculo(src_chat, src_msg, dst_chat, dst_msg):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO message_link (source_chat_id,source_msg_id,dest_chat_id,dest_msg_id) VALUES (?,?,?,?)",
                 (src_chat, src_msg, dst_chat, dst_msg))
    conn.commit(); conn.close()

def buscar_destino(src_chat, src_msg):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("SELECT dest_chat_id, dest_msg_id FROM message_link WHERE source_chat_id=? AND source_msg_id=?",
                        (src_chat, src_msg)).fetchall()
    conn.close(); return rows

# ---------- cursor ----------
def carregar_cursor():
    if os.path.exists(CURSOR_FILE):
        with open(CURSOR_FILE) as f: return json.load(f)
    return {}

def salvar_cursor(cursor):
    with open(CURSOR_FILE, "w") as f: json.dump(cursor, f, indent=2)

def atualizar_cursor(chat_id, thread_id, message_id):
    cursor = carregar_cursor()
    key = f"{chat_id}_{thread_id}"
    if key not in cursor or message_id > cursor[key]:
        cursor[key] = message_id
        salvar_cursor(cursor)

# ---------- log de falhas ----------
def log_falha(tipo, src_chat, src_msg, dst_chat, dst_msg, erro):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO error_log (tipo,source_chat_id,source_msg_id,dest_chat_id,dest_msg_id,erro) VALUES (?,?,?,?,?,?)",
                 (tipo, src_chat, src_msg, dst_chat, dst_msg, erro))
    conn.commit(); conn.close()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {tipo} | src:{src_chat}/{src_msg} → dst:{dst_chat}/{dst_msg} | {erro}\n")

# ---------- utilitários de tópicos ----------
async def list_forum_topics(bot, chat_id):
    try:
        chat = await bot.get_chat(chat_id)
        if not getattr(chat, 'is_forum', False): return None
    except: return None
    try:
        if hasattr(bot, 'get_forum_topics'):
            topics = await bot.get_forum_topics(chat_id)
            return [{"id": t.message_thread_id, "name": t.name or f"Tópico {t.message_thread_id}"} for t in topics]
        resp = await bot._post("getForumTopics", {"chat_id": chat_id}, read_timeout=15)
        if isinstance(resp, dict) and "topics" in resp:
            return [{"id": t.get("message_thread_id",1), "name": t.get("name") or f"Tópico {t.get('message_thread_id',1)}"} for t in resp["topics"]]
    except Exception as e:
        print(f"Erro ao listar tópicos do chat {chat_id}: {e}")
    return None

async def get_topic_name(bot, chat_id, thread_id):
    if thread_id is None: return "Geral"
    # alias
    alias = get_topic_alias(chat_id, thread_id)
    if alias: return alias
    # cache
    key = (chat_id, thread_id)
    if key in topic_name_cache: return topic_name_cache[key]
    # tenta obter
    if hasattr(bot, 'get_forum_topic'):
        try:
            t = await bot.get_forum_topic(chat_id, thread_id)
            if t.name: topic_name_cache[key] = t.name; return t.name
        except: pass
    try:
        resp = await bot._post("getForumTopic", {"chat_id": chat_id, "message_thread_id": thread_id}, read_timeout=10)
        if isinstance(resp, dict) and resp.get("name"):
            topic_name_cache[key] = resp["name"]; return resp["name"]
    except: pass
    # fallback pela lista
    topics = await list_forum_topics(bot, chat_id)
    if topics:
        for t in topics:
            if t["id"] == thread_id:
                topic_name_cache[key] = t["name"]; return t["name"]
    return f"Tópico {thread_id}"

def set_topic_alias(chat_id, thread_id, alias):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO topic_aliases (chat_id,thread_id,alias) VALUES (?,?,?)", (chat_id, thread_id, alias))
    conn.commit(); conn.close()
    topic_name_cache.pop((chat_id, thread_id), None)

def get_topic_alias(chat_id, thread_id):
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT alias FROM topic_aliases WHERE chat_id=? AND thread_id=?", (chat_id, thread_id)).fetchone()
    conn.close()
    return row[0] if row else None

async def criar_topico_no_destino(bot, dst_chat, nome):
    try:
        if hasattr(bot, 'create_forum_topic'):
            t = await bot.create_forum_topic(chat_id=dst_chat, name=nome)
            return t.message_thread_id
        resp = await bot._post("createForumTopic", {"chat_id": dst_chat, "name": nome})
        return resp["message_thread_id"]
    except Exception as e:
        print(f"❌ Erro ao criar tópico '{nome}': {e}")
        log_falha("CREATE_TOPIC", None, None, dst_chat, None, str(e))
        return None

async def obter_destino_para_espelhamento(bot, src_chat, src_thread_id):
    for esp in listar_espelhamentos():
        if esp[1] == src_chat:
            dst_chat = esp[2]; user_id = esp[3]
            nome = await get_topic_name(bot, src_chat, src_thread_id)
            topics = await list_forum_topics(bot, dst_chat)
            if topics:
                for t in topics:
                    if t["name"].lower() == nome.lower(): return (dst_chat, t["id"], user_id)
            novo = await criar_topico_no_destino(bot, dst_chat, nome)
            if novo:
                print(f"🆕 Tópico criado no destino: {nome} (ID {novo})")
                await asyncio.sleep(0.5)
                return (dst_chat, novo, user_id)
    return None

# ---------- notificação ao dono ----------
async def notificar_dono(context, texto):
    try: await context.bot.send_message(DONO_ID, texto, parse_mode="Markdown")
    except Exception as e: print(f"Erro ao notificar dono: {e}")

# ---------- verificação de órfãos ----------
async def verificar_topicos_orfas(app):
    await asyncio.sleep(60)
    while True:
        if VERIFICACAO_ORFAS == 0: return
        for rota in list_mappings():
            src_chat, src_thread = rota[2], rota[3]
            if src_thread is None: continue
            topics = await list_forum_topics(app.bot, src_chat)
            if topics is None: continue
            if not any(t["id"] == src_thread for t in topics):
                print(f"🗑️ Tópico {src_thread} removido em {src_chat}. Apagando rota.")
                delete_mapping(src_chat, src_thread)
                await notificar_dono(app, f"🗑️ Rota removida automaticamente\nOrigem: {src_chat}, tópico {src_thread}")
        await asyncio.sleep(VERIFICACAO_ORFAS)

# ---------- comandos ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **CCBot** – Backup de grupos com tópicos\n\n"
        "/copiar <tóp> <id_dest> [tóp_dest] [nome]\n"
        "/listar – suas rotas\n"
        "/parar <tóp>\n"
        "/nomear_rota <tóp> <nome>\n"
        "/apagartodas\n"
        "/status\n"
        "/apelidar <id_tóp> <nome>\n"
        "/espelhar <orig> <dest>\n"
        "/pararespelho <orig> <dest>\n"
        "/listarespelhos\n"
        "/meusgrupos – só a dona(o)"
    )

async def copiar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if len(args) < 2: await update.message.reply_text("Uso: /copiar <tópico_origem> <id_destino> [tópico_destino] [nome]"); return
    try:
        src_th = None if args[0].lower() in ("0","geral") else int(args[0])
        dst_chat = int(args[1])
        dst_th = None; label = None
        if len(args) > 2:
            if args[2].lower() in ("0","geral"): dst_th = None
            else:
                try: dst_th = int(args[2])
                except ValueError: label = " ".join(args[2:])
            if len(args) > 3 and dst_th is not None: label = " ".join(args[3:])
    except ValueError: await update.message.reply_text("IDs inválidos."); return

    src_chat = update.effective_chat.id
    add_mapping(user_id, src_chat, src_th, dst_chat, dst_th, label)
    src_name = await get_topic_name(context.bot, src_chat, src_th)
    dst_name = await get_topic_name(context.bot, dst_chat, dst_th)
    msg = f"✅ Rota ativada:\n{'Nome: '+label+chr(10) if label else ''}Origem: {src_chat}, {src_name} (ID:{src_th or 'Geral'})\nDestino: {dst_chat}, {dst_name} (ID:{dst_th or 'Geral'})"
    await update.message.reply_text(msg)

async def listar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rotas = list_mappings(user_id)
    if not rotas: await update.message.reply_text("Você não tem rotas."); return
    texto = "**Suas rotas:**\n"
    for r in rotas:
        src_chat, src_th, dst_chat, dst_th, label = r[2], r[3], r[4], r[5], r[6] if len(r)>6 else None
        src_name = await get_topic_name(context.bot, src_chat, src_th)
        dst_name = await get_topic_name(context.bot, dst_chat, dst_th)
        texto += f"- {src_chat} ({src_name} | ID:{src_th or 'Geral'}) → {dst_chat} ({dst_name} | ID:{dst_th or 'Geral'})"
        if label: texto += f"  [{label}]"
        texto += "\n"
    await update.message.reply_text(texto, parse_mode="Markdown")

async def parar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1: await update.message.reply_text("Uso: /parar <tópico_origem>"); return
    try: src_th = None if args[0].lower() in ("0","geral") else int(args[0])
    except ValueError: await update.message.reply_text("ID inválido."); return
    delete_mapping_for_user(update.effective_user.id, update.effective_chat.id, src_th)
    await update.message.reply_text("Rota removida.")

async def apagartodas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; chat_id = update.effective_chat.id
    key = (chat_id, user_id)
    pending_confirmations[key] = (datetime.now(), "apagartodas")
    await update.message.reply_text("⚠️ Apagar TODAS as suas rotas? Responda 'sim' ou 'não' (30s).")
    async def clear():
        await asyncio.sleep(30)
        if key in pending_confirmations:
            del pending_confirmations[key]
            try: await context.bot.send_message(chat_id, "⏰ Tempo esgotado.")
            except: pass
    asyncio.create_task(clear())

async def nomear_rota_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2: await update.message.reply_text("Uso: /nomear_rota <tópico_origem> <nome>"); return
    try: src_th = None if args[0].lower() in ("0","geral") else int(args[0])
    except ValueError: await update.message.reply_text("ID inválido."); return
    set_mapping_label(update.effective_user.id, update.effective_chat.id, src_th, " ".join(args[1:]))
    await update.message.reply_text("✅ Nome atualizado.")

async def apelidar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2: await update.message.reply_text("Uso: /apelidar <id_tópico> <nome>"); return
    try:
        tid = int(args[0]); nome = " ".join(args[1:])
        set_topic_alias(update.effective_chat.id, tid, nome)
        await update.message.reply_text(f"✅ Tópico {tid} agora é \"{nome}\".")
    except ValueError: await update.message.reply_text("ID inválido.")

async def espelhar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2: await update.message.reply_text("Uso: /espelhar <origem> <destino>"); return
    try: src = int(args[0]); dst = int(args[1])
    except ValueError: await update.message.reply_text("IDs inválidos."); return
    adicionar_espelhamento(update.effective_user.id, src, dst)
    await update.message.reply_text(f"✅ Espelhamento {src} → {dst} ativado.")

async def pararespelho_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2: await update.message.reply_text("Uso: /pararespelho <origem> <destino>"); return
    try: src = int(args[0]); dst = int(args[1])
    except ValueError: await update.message.reply_text("IDs inválidos."); return
    remover_espelhamento(update.effective_user.id, src, dst)
    await update.message.reply_text("✅ Espelhamento desativado.")

async def listarespelhos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    esp = listar_espelhamentos(update.effective_user.id)
    if not esp: await update.message.reply_text("Nenhum espelhamento."); return
    texto = "**Seus espelhamentos:**\n" + "\n".join(f"- {e[2]} → {e[3]}" for e in esp)
    await update.message.reply_text(texto, parse_mode="Markdown")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    rotas = conn.execute("SELECT COUNT(*) FROM mapping WHERE user_id=? OR user_id=0", (user_id,)).fetchone()[0]
    copiadas = conn.execute("SELECT COUNT(*) FROM message_link").fetchone()[0]
    falhas = conn.execute("SELECT COUNT(*) FROM error_log WHERE timestamp > datetime('now','-1 day')").fetchone()[0]
    esp = conn.execute("SELECT COUNT(*) FROM espelhamento WHERE user_id=? OR user_id=0", (user_id,)).fetchone()[0]
    conn.close()
    await update.message.reply_text(f"📊 Suas rotas: {rotas} | Espelhamentos: {esp}\nMensagens copiadas: {copiadas}\nFalhas 24h: {falhas}")

async def meusgrupos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != DONO_ID:
        await update.message.reply_text(f"❌ Apenas o dono. Seu ID: {update.effective_user.id}"); return
    chats = get_known_chats()
    if not chats: await update.message.reply_text("Nenhum grupo registrado."); return
    texto = "**Grupos com atividade:**\n" + "\n".join(f"- {t} (`{i}`)" for i,t in chats)
    await update.message.reply_text(texto, parse_mode="Markdown")

# ---------- handlers automáticos ----------
async def auto_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None: return
    src_chat, src_thread = msg.chat_id, msg.message_thread_id
    try:
        chat = await context.bot.get_chat(src_chat)
        update_known_chat(src_chat, chat.title or chat.first_name or "Grupo")
    except: pass
    mapping = get_mapping(src_chat, src_thread)
    if mapping is None:
        if src_thread is not None:
            res = await obter_destino_para_espelhamento(context.bot, src_chat, src_thread)
            if res:
                dst_chat, dst_thread, user_id = res
                add_mapping(user_id, src_chat, src_thread, dst_chat, dst_thread)
                print(f"🔗 Rota auto criada: {src_chat}/{src_thread} → {dst_chat}/{dst_thread}")
                mapping = (dst_chat, dst_thread)
            else: return
        else: return
    dst_chat, dst_thread = mapping
    try:
        chat_dst = await context.bot.get_chat(dst_chat)
        update_known_chat(dst_chat, chat_dst.title or "Destino")
    except: pass
    for tent in range(5):
        try:
            sent = await msg.copy(chat_id=dst_chat, message_thread_id=dst_thread)
            atualizar_cursor(src_chat, src_thread, msg.message_id)
            salvar_vinculo(src_chat, msg.message_id, dst_chat, sent.message_id)
            print(f"✅ {msg.message_id} → {sent.message_id}")
            await asyncio.sleep(2); break
        except Exception as e:
            err = str(e)
            if "Flood" in err:
                wait = int(re.search(r'(\d+)', err).group(1)) + 3 if re.search(r'(\d+)', err) else 30
                print(f"⚠️ Flood, aguardando {wait}s"); await asyncio.sleep(wait)
            elif "thread not found" in err.lower():
                delete_mapping(src_chat, src_thread)
                await notificar_dono(context, f"🗑️ Rota removida (tópico {src_thread} não existe mais).")
                break
            elif "can't be copied" in err.lower(): break
            else:
                log_falha("COPY", src_chat, msg.message_id, dst_chat, None, err)
                await notificar_dono(context, f"❌ Falha ao copiar msg {msg.message_id}\n{err}")
                break

async def pin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.pinned_message is None: return
    pinned = update.message.pinned_message
    src_chat, src_thread = update.message.chat_id, update.message.message_thread_id
    mapping = get_mapping(src_chat, src_thread)
    if not mapping: return
    destinos = buscar_destino(src_chat, pinned.message_id)
    if not destinos: return
    for d_chat, d_msg in destinos:
        try:
            await context.bot.pin_chat_message(d_chat, d_msg)
            print(f"📌 Fixado em {d_chat}/{d_msg}")
        except Exception as e:
            log_falha("PIN", src_chat, pinned.message_id, d_chat, d_msg, str(e))
            await notificar_dono(context, f"❌ Falha ao fixar: {e}")

async def auto_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.edited_message
    if msg is None: return
    destinos = buscar_destino(msg.chat_id, msg.message_id)
    if not destinos: return
    for d_chat, d_msg in destinos:
        try:
            if msg.text:
                await context.bot.edit_message_text(d_chat, d_msg, text=msg.text, entities=msg.entities)
            elif msg.caption:
                await context.bot.edit_message_caption(d_chat, d_msg, caption=msg.caption, caption_entities=msg.caption_entities)
            print(f"✏️ Editado {msg.message_id} → {d_msg} em {d_chat}")
        except Exception as e:
            err = str(e)
            if "Flood" in err:
                wait = int(re.search(r'(\d+)', err).group(1)) + 2 if re.search(r'(\d+)', err) else 30
                await asyncio.sleep(wait)
                try:
                    if msg.text: await context.bot.edit_message_text(d_chat, d_msg, text=msg.text, entities=msg.entities)
                    elif msg.caption: await context.bot.edit_message_caption(d_chat, d_msg, caption=msg.caption, caption_entities=msg.caption_entities)
                except Exception as e2: log_falha("EDIT", msg.chat_id, msg.message_id, d_chat, d_msg, str(e2))
            elif "not modified" not in err.lower():
                log_falha("EDIT", msg.chat_id, msg.message_id, d_chat, d_msg, err)
                await notificar_dono(context, f"❌ Falha ao editar: {err}")

# ---------- background ----------
async def background_tasks(app):
    while True:
        await asyncio.sleep(86400)
        limpar_mensagens_antigas()

# ---------- main ----------
def main():
    init_db(); limpar_mensagens_antigas()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("copiar", copiar_cmd))
    app.add_handler(CommandHandler("listar", listar_cmd))
    app.add_handler(CommandHandler("parar", parar_cmd))
    app.add_handler(CommandHandler("apagartodas", apagartodas_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("apelidar", apelidar_cmd))
    app.add_handler(CommandHandler("nomear_rota", nomear_rota_cmd))
    app.add_handler(CommandHandler("espelhar", espelhar_cmd))
    app.add_handler(CommandHandler("pararespelho", pararespelho_cmd))
    app.add_handler(CommandHandler("listarespelhos", listarespelhos_cmd))
    app.add_handler(CommandHandler("meusgrupos", meusgrupos_cmd))

    async def dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_message:
            key = (update.effective_chat.id, update.effective_user.id)
            if key in pending_confirmations:
                txt = update.effective_message.text.strip().lower() if update.effective_message.text else ""
                if txt in ("sim","yes","s"): delete_all_mappings(key[1]); del pending_confirmations[key]; await update.effective_message.reply_text("🗑️ Rotas apagadas."); return
                elif txt in ("não","nao","n"): del pending_confirmations[key]; await update.effective_message.reply_text("Cancelado."); return
                else: await update.effective_message.reply_text("Responda 'sim' ou 'não'."); return
        if update.edited_message: await auto_edit(update, context); return
        if update.message is None: return
        if update.message.pinned_message: await pin_handler(update, context); return
        await auto_forward(update, context)

    app.add_handler(MessageHandler(filters.ALL, dispatcher))

    async def combined_background():
        await asyncio.gather(background_tasks(app), verificar_topicos_orfas(app))

    threading.Thread(target=lambda: asyncio.run(combined_background()), daemon=True).start()

    print("🤖 CCBot pronto! Configure DONO_ID e TOKEN.")
    app.run_polling()

if __name__ == "__main__":
    main()
