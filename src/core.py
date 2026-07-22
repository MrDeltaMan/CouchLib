"""
core.py — Camada de dados e mídia baseada em IPC Socket:
- Database: SQLite com bibliotecas cadastradas + cache de metadados de vídeo
  (agora também guarda a identificação do último gamepad reconhecido)
- scan_directory: varre uma pasta e separa subpastas de arquivos de vídeo
- get_or_create_thumbnail: gera (via ffmpeg) e cacheia uma miniatura por vídeo
- Player: Controle do executável MPV do sistema via socket IPC (Mata problemas do Wayland)

Dependências do sistema:
    sudo apt install mpv ffmpeg
"""
import hashlib
import os
import sqlite3
import subprocess
import threading
import time
import socket
import json
import uuid
import logging
from pathlib import Path
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, QTimer

# Configuração de logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CouchLib")

APP_NAME = "htpc-app"
CONFIG_DIR = Path.home() / ".config" / APP_NAME
CACHE_DIR = Path.home() / ".cache" / APP_NAME
THUMB_DIR = CACHE_DIR / "thumbs"
DB_PATH = CONFIG_DIR / "library.db"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".flv", ".wmv"}

def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------
class Database:
    def __init__(self, db_path: Path = DB_PATH):
        ensure_dirs()
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS libraries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS video_cache (
                path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                duration REAL,
                thumb_path TEXT,
                resume_position REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self.conn.commit()

    def get_setting(self, key: str, default=None):
        with self._lock:
            res = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return res["value"] if res else default

    def set_setting(self, key: str, value: str):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            self.conn.commit()

    def add_library(self, path: str):
        name = os.path.basename(path.rstrip("/")) or path
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO libraries (path, name) VALUES (?, ?)", (path, name))
            self.conn.commit()

    def get_libraries(self):
        with self._lock:
            return self.conn.execute("SELECT * FROM libraries").fetchall()

    def get_video_cache(self, path: str):
        with self._lock:
            return self.conn.execute("SELECT * FROM video_cache WHERE path = ?", (path,)).fetchone()

    def upsert_video_cache(self, path, mtime, duration=None, thumb_path=None):
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO video_cache (path, mtime, duration, thumb_path) VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime = excluded.mtime,
                    duration = COALESCE(excluded.duration, video_cache.duration),
                    thumb_path = COALESCE(excluded.thumb_path, video_cache.thumb_path)
                """,
                (path, mtime, duration, thumb_path),
            )
        self.conn.commit()

    def set_resume_position(self, path: str, seconds: float):
        with self._lock:
            self.conn.execute("UPDATE video_cache SET resume_position = ? WHERE path = ?", (seconds, path))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Identificação de gamepad — fallback de reconexão
    #
    # Guardamos o GUID (identificador estável do controle físico, não muda
    # entre desconexões) e o nome do último gamepad reconhecido. Assim, ao
    # reiniciar o app — ou quando mais de um controle está por perto — o
    # GamepadManager (gamepad.py) sabe qual controle priorizar ao reconectar.
    # ------------------------------------------------------------------
    def get_known_gamepad(self):
        """Retorna {'guid': ..., 'name': ...} do último gamepad reconhecido,
        ou None se nenhum ainda foi salvo."""
        with self._lock:
            guid = self.conn.execute(
                "SELECT value FROM settings WHERE key = 'gamepad_guid'"
            ).fetchone()
        if not guid or not guid["value"]:
            return None
        return {
            "guid": guid["value"],
            "name": self.get_setting("gamepad_name", "Gamepad desconhecido"),
        }

    def set_known_gamepad(self, guid: str, name: str):
        """Salva a identificação (GUID + nome) do controle atualmente conectado."""
        if not guid:
            return
        self.set_setting("gamepad_guid", guid)
        self.set_setting("gamepad_name", name or "Gamepad desconhecido")

# ---------------------------------------------------------------------------
# Scanner de diretórios
# ---------------------------------------------------------------------------
def scan_directory(path: str):
    folders, videos = [], []
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except (FileNotFoundError, PermissionError, NotADirectoryError) as e:
        logger.warning(f"Erro ao ler pasta {path}: {e}")
        return [], []

    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                folders.append(entry.path)
            elif entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    videos.append(entry.path)
        except OSError:
            continue
    return folders, videos

# ---------------------------------------------------------------------------
# Thumbnails (via ffmpeg)
# ---------------------------------------------------------------------------
def _thumb_path_for(video_path: str) -> Path:
    ensure_dirs()
    digest = hashlib.sha1(video_path.encode("utf-8")).hexdigest()
    return THUMB_DIR / f"{digest}.jpg"

def _video_duration(video_path: str):
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        return float(out.stdout.strip())
    except FileNotFoundError:
        logger.error("ffprobe não encontrado! Instale o pacote ffmpeg.")
        return None
    except Exception as e:
        logger.error(f"Erro ao obter duração de {video_path}: {e}")
        return None

def get_or_create_thumbnail(video_path: str, db: Database):
    try:
        mtime = os.path.getmtime(video_path)
    except OSError as e:
        logger.warning(f"Arquivo inacessível {video_path}: {e}")
        return None

    cached = db.get_video_cache(video_path)
    if (cached and cached["mtime"] == mtime and cached["thumb_path"] and os.path.exists(cached["thumb_path"])):
        return cached["thumb_path"]

    thumb_path = _thumb_path_for(video_path)
    duration = _video_duration(video_path)
    seek_time = (duration * 0.25) if duration else 5.0

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(seek_time), "-i", video_path,
                "-vframes", "1", "-vf", "scale=320:-1", "-q:v", "4", str(thumb_path)
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15
        )
        if thumb_path.exists():
            db.upsert_video_cache(video_path, mtime, duration, str(thumb_path))
            return str(thumb_path)
    except FileNotFoundError:
        logger.error("ffmpeg não encontrado! Instale o pacote ffmpeg.")
    except Exception as e:
        logger.error(f"Falha ao criar thumbnail para {video_path}: {e}")
    return None

class ThumbnailSignals(QObject):
    ready = Signal(str, str)

class ThumbnailWorker(QRunnable):
    def __init__(self, video_path: str, db: Database, signals: ThumbnailSignals):
        super().__init__()
        self.video_path = video_path
        self.db = db
        self.signals = signals

    def run(self):
        tpath = get_or_create_thumbnail(self.video_path, self.db)
        if tpath:
            self.signals.ready.emit(self.video_path, tpath)

def request_thumbnail_async(video_path: str, db: Database, signals: ThumbnailSignals):
    worker = ThumbnailWorker(video_path, db, signals)
    QThreadPool.globalInstance().start(worker)

# ---------------------------------------------------------------------------
# Reprodutor MPV Controlado por Socket IPC (Agnóstico de Janela)
# ---------------------------------------------------------------------------
class Player(QObject):
    position_changed = Signal(float)
    duration_changed = Signal(float)
    pause_changed = Signal(bool)
    volume_changed = Signal(int)
    # Carrega o motivo do fim de reprodução, vindo do campo "reason" do
    # evento "end-file" do mpv: "eof" (chegou ao fim sozinho), "stop"/"quit"
    # (usuário/app pediu pra parar), "error", ou "closed" (conexão caiu sem
    # um end-file explícito, ex: processo morto externamente).
    end_of_file = Signal(str)
    playback_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.sock = None
        self.running = False
        self.read_thread = None

        self._is_paused = False
        self._volume = 100
        self._mute = False
        self._current_pos = 0.0

    def play(self, path: str, start_at: float = 0.0, volume: int = 100, loop: bool = False):
        self.stop()

        # Reseta a posição conhecida: sem isso, se o usuário sair muito
        # rápido do vídeo novo (antes do primeiro "time-pos" chegar via IPC),
        # a posição salva seria a do vídeo ANTERIOR, associada ao path errado.
        self._current_pos = 0.0

        # Controla se este ciclo de reprodução já emitiu end_of_file com um
        # motivo real (vindo do próprio mpv), pra evitar disparo duplicado
        # quando o socket cai logo depois de um "end-file" já recebido.
        self._eof_emitted = False

        # Cria socket com nome dinâmico para evitar colisões
        socket_id = uuid.uuid4().hex[:8]
        self.socket_path = f"/tmp/htpc-mpv-ipc-{socket_id}.sock"
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass

        cmd = [
            "mpv",
            "--fs",
            f"--input-ipc-server={self.socket_path}",
            "--osc=no",
            f"--volume={volume}",
            path
        ]
        if start_at > 0:
            cmd.append(f"--start={start_at}")
        if loop:
            # Loop nativo do mpv: o vídeo reinicia sozinho, sem nunca mandar
            # um "end-file" com reason="eof" — não precisamos gerenciar nada
            # em Python pra manter o modo Loop funcionando.
            cmd.append("--loop-file=inf")

        try:
            self.process = subprocess.Popen(cmd)
            self.running = True
        except FileNotFoundError:
            msg = "MPV não está instalado no sistema. (sudo apt install mpv)"
            logger.error(msg)
            self.playback_error.emit(msg)
            return

        self.read_thread = threading.Thread(target=self._ipc_listener, daemon=True)
        self.read_thread.start()

    def _ipc_listener(self):
        connected = False
        for _ in range(30):
            if not self.running:
                return
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(self.socket_path)
                connected = True
                break
            except Exception:
                time.sleep(0.1)

        if not connected:
            logger.error("[IPC] Erro fatal: Não foi possível conectar ao Socket do MPV.")
            return

        self._send_cmd(["observe_property", 1, "time-pos"])
        self._send_cmd(["observe_property", 2, "duration"])
        self._send_cmd(["observe_property", 3, "pause"])
        self._send_cmd(["observe_property", 4, "volume"])
        self._send_cmd(["observe_property", 5, "mute"])

        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._parse_ipc_line(line)
            except Exception as e:
                logger.warning(f"[IPC] Conexão perdida ou erro: {e}")
                break

        # Só emite aqui se o mpv não mandou um "end-file" explícito antes de
        # o socket cair (ex: processo morreu/foi morto sem esse evento).
        # Isso evita salvar/zerar a posição duas vezes para o mesmo ciclo.
        if not self._eof_emitted:
            self._eof_emitted = True
            self.end_of_file.emit("closed")

    def _parse_ipc_line(self, line):
        try:
            msg = json.loads(line)
            event = msg.get("event")
            if event == "property-change":
                name = msg.get("name")
                data = msg.get("data")
                if data is None:
                    return

                if name == "time-pos":
                    self._current_pos = float(data)
                    self.position_changed.emit(self._current_pos)
                elif name == "duration":
                    self.duration_changed.emit(float(data))
                elif name == "pause":
                    self._is_paused = bool(data)
                    self.pause_changed.emit(self._is_paused)
                elif name == "volume":
                    self._volume = int(data)
                    self.volume_changed.emit(self._volume)
                elif name == "mute":
                    self._mute = bool(data)
            elif event == "end-file":
                reason = msg.get("reason", "eof")
                self._eof_emitted = True
                self.end_of_file.emit(reason)
        except Exception:
            pass

    def _send_cmd(self, cmd_list):
        if not self.sock:
            return
        try:
            payload = json.dumps({"command": cmd_list}) + "\n"
            self.sock.sendall(payload.encode("utf-8"))
        except Exception as e:
            logger.error(f"[IPC] Falha ao enviar comando: {e}")

    def set_loop(self, enabled: bool):
        """Liga/desliga o loop nativo do mpv em tempo real, sem reiniciar
        o vídeo (usado ao trocar de modo de reprodução durante o play)."""
        self._send_cmd(["set_property", "loop-file", "inf" if enabled else "no"])

    def toggle_pause(self): self._send_cmd(["cycle", "pause"])
    def seek_relative(self, seconds: float): self._send_cmd(["seek", seconds, "relative"])
    def seek_absolute(self, seconds: float): self._send_cmd(["seek", seconds, "absolute"])
    def change_volume(self, delta: int): self._send_cmd(["add", "volume", delta])
    def toggle_mute(self): self._send_cmd(["cycle", "mute"])
    def cycle_audio_track(self): self._send_cmd(["cycle", "aid"])
    def cycle_subtitle_track(self): self._send_cmd(["cycle", "sid"])
    def cycle_aspect_ratio(self): self._send_cmd(["cycle", "video-aspect-override"])
    def show_text(self, text: str, duration_ms: int = 2000): self._send_cmd(["show-text", text, duration_ms])

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=1)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def shutdown(self):
        self.stop()
        if hasattr(self, 'socket_path') and os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass