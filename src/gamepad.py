"""
gamepad.py — Leitura de gamepad via SDL2, emitindo sinais Qt.

Sistema de fallback de reconexão:
- Cada controle é identificado pelo seu GUID (persistente entre conexões),
  não apenas pelo instance_id (que muda toda vez que o SDL reabre o device).
- Um "watchdog" verifica periodicamente se o joystick que julgamos conectado
  ainda está de fato conectado. Isso cobre o caso comum de controles sem fio
  que entram em economia de energia e desligam sem que o SDL emita um evento
  SDL_JOYDEVICEREMOVED — sem isso, o programa "trava" achando que o controle
  antigo ainda está lá e ignora o novo evento de conexão.
- Ao reconectar (evento ou watchdog), tentamos reabrir preferencialmente o
  mesmo GUID de antes; se não achamos, abrimos o primeiro disponível.
"""

import ctypes
import sys
import time
from typing import Optional

from PySide6.QtCore import QThread, Signal

try:
    import sdl2
except ImportError:
    sdl2 = None

AXIS_DEAD_ZONE = 8000
AXIS_REPEAT_DELAY = 0.22
HAT_INITIAL_DELAY = 1.0
HAT_REPEAT_RATE = 0.15
WATCHDOG_INTERVAL = 1.0  # segundos entre checagens de "controle fantasma"


def _guid_to_str(guid) -> str:
    """Converte um SDL_JoystickGUID para uma string hexadecimal estável."""
    buf = ctypes.create_string_buffer(33)
    sdl2.SDL_JoystickGetGUIDString(guid, buf, len(buf))
    return buf.value.decode("utf-8")


class GamepadManager(QThread):
    dpad_up = Signal()
    dpad_down = Signal()
    dpad_left = Signal()
    dpad_right = Signal()

    button_a = Signal()
    button_b = Signal()
    button_x = Signal()
    button_y = Signal()
    button_back = Signal()
    button_start = Signal()

    # Agora carrega (nome, guid) — o guid é o que permite reconhecer o mesmo
    # controle físico entre uma desconexão e outra.
    connected = Signal(str, str)
    disconnected = Signal()

    BUTTON_MAP = {
        0: "button_a",
        1: "button_b",
        2: "button_x",
        3: "button_y",
        6: "button_back",
        7: "button_start",
    }

    def __init__(self, parent=None, preferred_guid: Optional[str] = None):
        """
        preferred_guid: GUID do último controle conhecido (ex: vindo do banco
        de dados). Quando informado, o GamepadManager tenta priorizar esse
        controle específico ao escolher qual joystick abrir.
        """
        super().__init__(parent)
        self._running = False
        self._joystick = None
        self._joystick_id = None
        self._joystick_guid = None
        self._preferred_guid = preferred_guid
        self._last_axis_time = {"x": 0.0, "y": 0.0}
        self._current_hat_value = 0
        self._hat_held_since = None
        self._hat_last_repeat = 0.0
        self._last_watchdog_check = 0.0

    def run(self):
        if sdl2 is None:
            print("[gamepad] PySDL2 não instalado. Rode: pip install PySDL2")
            return

        if sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK) != 0:
            print("[gamepad] Falha ao inicializar SDL2:", sdl2.SDL_GetError())
            return

        self._running = True
        self._try_open_best_joystick()

        event = sdl2.SDL_Event()
        while self._running:
            while sdl2.SDL_PollEvent(event) != 0:
                self._handle_event(event)
            self._check_zombie_connection()
            self._poll_hat_repeat()
            time.sleep(0.01)

        self._close_joystick(emit_signal=False)
        sdl2.SDL_Quit()

    def stop(self):
        self._running = False
        self.wait(500)

    # ------------------------------------------------------------------
    # Abertura / fechamento do joystick
    # ------------------------------------------------------------------
    def _open_joystick(self, device_index) -> bool:
        """Abre um joystick pelo índice de dispositivo (device_index, não
        confundir com instance_id, que só existe após a abertura)."""
        self._close_joystick(emit_signal=False)

        joystick = sdl2.SDL_JoystickOpen(device_index)
        if not joystick:
            return False

        self._joystick = joystick
        self._joystick_id = sdl2.SDL_JoystickInstanceID(joystick)
        self._joystick_guid = _guid_to_str(sdl2.SDL_JoystickGetGUID(joystick))

        raw_name = sdl2.SDL_JoystickName(joystick)
        name = raw_name.decode("utf-8") if raw_name else "Gamepad desconhecido"

        # Zera estados de hat/eixo para não herdar "fantasmas" do controle anterior
        self._current_hat_value = 0
        self._hat_held_since = None

        self.connected.emit(name, self._joystick_guid)
        return True

    def _close_joystick(self, emit_signal: bool = True):
        had_joystick = self._joystick is not None
        if self._joystick:
            try:
                sdl2.SDL_JoystickClose(self._joystick)
            except Exception:
                pass

        self._joystick = None
        self._joystick_id = None
        self._joystick_guid = None

        if emit_signal and had_joystick:
            self.disconnected.emit()

    def _try_open_best_joystick(self):
        """Escolhe qual joystick abrir dentre os disponíveis: prioriza o GUID
        conhecido (preferred_guid) e cai para o primeiro disponível caso esse
        controle específico não esteja presente."""
        count = sdl2.SDL_NumJoysticks()
        if count <= 0:
            return

        if self._preferred_guid:
            for index in range(count):
                guid = sdl2.SDL_JoystickGetDeviceGUID(index)
                if _guid_to_str(guid) == self._preferred_guid:
                    if self._open_joystick(index):
                        return

        self._open_joystick(0)

    # ------------------------------------------------------------------
    # Watchdog — fallback para desconexões que o SDL não avisa
    # ------------------------------------------------------------------
    def _check_zombie_connection(self):
        """Alguns controles sem fio desligam sozinhos (economia de bateria)
        sem que o SDL emita SDL_JOYDEVICEREMOVED. Sem essa checagem, o
        programa continua achando que há um controle conectado e ignora o
        próximo SDL_JOYDEVICEADDED quando o controle liga de novo."""
        if self._joystick is None:
            return

        now = time.time()
        if (now - self._last_watchdog_check) < WATCHDOG_INTERVAL:
            return
        self._last_watchdog_check = now

        if not sdl2.SDL_JoystickGetAttached(self._joystick):
            self._preferred_guid = self._joystick_guid or self._preferred_guid
            self._close_joystick(emit_signal=True)
            self._try_open_best_joystick()

    # ------------------------------------------------------------------
    # Eventos SDL
    # ------------------------------------------------------------------
    def _handle_event(self, event):
        if event.type == sdl2.SDL_JOYDEVICEADDED:
            device_index = event.jdevice.which

            # Confirma que o controle que achávamos conectado ainda está vivo
            # antes de ignorar este evento — cobre o caso de reconexão rápida
            # em que o REMOVED nunca chegou a ser emitido.
            if self._joystick is not None and not sdl2.SDL_JoystickGetAttached(self._joystick):
                self._close_joystick(emit_signal=True)

            if self._joystick is None:
                new_guid = _guid_to_str(sdl2.SDL_JoystickGetDeviceGUID(device_index))
                self._open_joystick(device_index)
                if self._preferred_guid is None:
                    self._preferred_guid = new_guid

        elif event.type == sdl2.SDL_JOYDEVICEREMOVED:
            if self._joystick and event.jdevice.which == self._joystick_id:
                self._preferred_guid = self._joystick_guid or self._preferred_guid
                self._close_joystick(emit_signal=True)
                # Tenta reabrir imediatamente (caso outro controle já esteja plugado)
                self._try_open_best_joystick()

        elif event.type == sdl2.SDL_JOYBUTTONDOWN:
            if self._joystick and event.jbutton.which == self._joystick_id:
                self._handle_button(event.jbutton.button)
        elif event.type == sdl2.SDL_JOYHATMOTION:
            if self._joystick and event.jhat.which == self._joystick_id:
                self._handle_hat(event.jhat.value)
        elif event.type == sdl2.SDL_JOYAXISMOTION:
            if self._joystick and event.jaxis.which == self._joystick_id:
                self._handle_axis(event.jaxis.axis, event.jaxis.value)

    def _handle_button(self, index):
        signal_name = self.BUTTON_MAP.get(index)
        if signal_name:
            getattr(self, signal_name).emit()

    def _handle_hat(self, value):
        if value == self._current_hat_value:
            return

        self._current_hat_value = value
        if value == 0:
            self._hat_held_since = None
            return

        now = time.time()
        self._hat_held_since = now
        self._hat_last_repeat = now
        self._emit_hat(value)

    def _poll_hat_repeat(self):
        if self._current_hat_value == 0 or self._hat_held_since is None:
            return

        now = time.time()
        if (now - self._hat_held_since) < HAT_INITIAL_DELAY:
            return
        if (now - self._hat_last_repeat) < HAT_REPEAT_RATE:
            return

        self._hat_last_repeat = now
        self._emit_hat(self._current_hat_value)

    def _emit_hat(self, value):
        if value & sdl2.SDL_HAT_UP: self.dpad_up.emit()
        if value & sdl2.SDL_HAT_DOWN: self.dpad_down.emit()
        if value & sdl2.SDL_HAT_LEFT: self.dpad_left.emit()
        if value & sdl2.SDL_HAT_RIGHT: self.dpad_right.emit()

    def _handle_axis(self, axis, value):
        now = time.time()
        if axis == 0:
            if abs(value) < AXIS_DEAD_ZONE:
                return
            if (now - self._last_axis_time["x"]) < AXIS_REPEAT_DELAY:
                return
            self._last_axis_time["x"] = now
            (self.dpad_left if value < 0 else self.dpad_right).emit()
        elif axis == 1:
            if abs(value) < AXIS_DEAD_ZONE:
                return
            if (now - self._last_axis_time["y"]) < AXIS_REPEAT_DELAY:
                return
            self._last_axis_time["y"] = now
            (self.dpad_up if value < 0 else self.dpad_down).emit()


if __name__ == "__main__":
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication(sys.argv)
    gp = GamepadManager()
    gp.connected.connect(lambda name, guid: print(f"[gamepad] Conectado: {name} (GUID {guid})"))
    gp.disconnected.connect(lambda: print("[gamepad] Desconectado"))
    gp.button_a.connect(lambda: print("A"))
    gp.start()
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        gp.stop()