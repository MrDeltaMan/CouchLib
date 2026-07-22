import locale
import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSize, QTimer, Signal,
    QPropertyAnimation, QEasingCurve, QRect
)
from PySide6.QtGui import (
    QIcon, QPixmap, QColor, QPainter, QBrush, QPen, QLinearGradient, QFont, QPainterPath
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QLabel, QListView,
    QMainWindow, QPushButton, QSlider, QStackedWidget, QStyledItemDelegate,
    QVBoxLayout, QWidget, QMessageBox, QGraphicsOpacityEffect
)

from gamepad import GamepadManager
from core import Database, Player, ThumbnailSignals, request_thumbnail_async, scan_directory

# Ajuste leve nas dimensões para caber o estilo de "Card"
GRID_ITEM_SIZE = QSize(350, 270)
THUMB_SIZE = QSize(320, 180)

# --- PALETA DE CORES ---
BG_COLOR = "#0f0f13"
CARD_BG = "#1e1e26"
TEXT_MAIN = "#f0f0f0"
TEXT_MUTED = "#8a8a99"


class LibraryModel(QAbstractListModel):
    NAME_ROLE = Qt.DisplayRole
    THUMB_ROLE = Qt.DecorationRole
    IS_FOLDER_ROLE = Qt.UserRole + 1
    PATH_ROLE = Qt.UserRole + 2

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._entries = []
        self._generation = 0
        self._thumb_signals = ThumbnailSignals()
        self._thumb_signals.ready.connect(self._on_thumb_ready)

    def load(self, folder_path: str):
        self._generation += 1
        my_generation = self._generation
        self.beginResetModel()
        self._entries = []
        folders, videos = scan_directory(folder_path)

        for f in folders:
            self._entries.append({"name": os.path.basename(f), "path": f, "is_folder": True, "thumb": None})
        for v in videos:
            self._entries.append({"name": os.path.basename(v), "path": v, "is_folder": False, "thumb": None})

        self.endResetModel()
        for v in videos:
            request_thumbnail_async(v, self.db, self._thumb_signals)
        self._current_generation_for_callback = my_generation

    def _on_thumb_ready(self, video_path: str, thumb_path: str):
        if self._current_generation_for_callback != self._generation:
            return
        for row, entry in enumerate(self._entries):
            if entry["path"] == video_path:
                entry["thumb"] = thumb_path
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])
                break

    def rowCount(self, parent=QModelIndex()):
        return len(self._entries)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        entry = self._entries[index.row()]
        if role == Qt.DisplayRole: return entry["name"]
        if role == Qt.DecorationRole: return QIcon(QPixmap(entry["thumb"])) if entry["thumb"] else None
        if role == self.IS_FOLDER_ROLE: return entry["is_folder"]
        if role == self.PATH_ROLE: return entry["path"]
        return None


class ModernMarqueeDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset = 0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._offset += 2
        if self.parent() is not None:
            self.parent().viewport().update()

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        is_folder = index.data(LibraryModel.IS_FOLDER_ROLE)
        name = index.data(Qt.DisplayRole) or ""
        thumb_icon = index.data(Qt.DecorationRole)

        # Garante que is_selected seja puramente booleano
        is_selected = bool(option.state & self.parent().style().StateFlag.State_Selected) if self.parent() else False
        is_list_mode = self.parent().viewMode() == QListView.ListMode if self.parent() else False

        card_rect = rect.adjusted(10, 10, -10, -10)

        if is_selected:
            grad = QLinearGradient(card_rect.topLeft(), card_rect.bottomRight())
            grad.setColorAt(0, QColor("#2b5876"))
            grad.setColorAt(1, QColor("#4e4376"))
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(QColor("#ffffff"), 2))
            card_rect = rect.adjusted(6, 6, -6, -6)
        else:
            painter.setBrush(QColor(CARD_BG))
            painter.setPen(Qt.NoPen)

        painter.drawRoundedRect(card_rect, 14, 14)

        # Redefine a cor da caneta para desenhar os textos daqui para frente
        painter.setPen(QColor(TEXT_MAIN))

        if is_list_mode:
            thumb_rect = QRect(card_rect.x() + 10, card_rect.y() + 10, 180, card_rect.height() - 20)
            text_rect = QRect(thumb_rect.right() + 20, card_rect.y(), card_rect.width() - thumb_rect.width() - 40, card_rect.height())

            self._draw_thumbnail(painter, thumb_rect, thumb_icon, is_folder)

            font = painter.font()
            font.setPointSize(16)
            font.setBold(is_selected)
            painter.setFont(font)

            # Passando as flags convertidas para inteiro para evitar conflito de Enums
            flags = int(Qt.AlignVCenter) | int(Qt.AlignLeft)
            self._draw_marquee_text(painter, text_rect, name, is_selected, flags)
        else:
            thumb_rect = QRect(card_rect.x() + 10, card_rect.y() + 10, card_rect.width() - 20, THUMB_SIZE.height())
            text_rect = QRect(card_rect.x() + 10, thumb_rect.bottom() + 10, card_rect.width() - 20, card_rect.height() - thumb_rect.height() - 20)

            self._draw_thumbnail(painter, thumb_rect, thumb_icon, is_folder)

            font = painter.font()
            font.setPointSize(14)
            font.setBold(is_selected)
            painter.setFont(font)

            # Passando as flags convertidas para inteiro
            flags = int(Qt.AlignVCenter) | int(Qt.AlignHCenter)
            self._draw_marquee_text(painter, text_rect, name, is_selected, flags)

        painter.restore()

    def _draw_thumbnail(self, painter, rect, icon, is_folder):
        painter.save()
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.setClipPath(path)

        if icon and not is_folder:
            icon.paint(painter, rect, Qt.AlignCenter)
        else:
            painter.fillRect(rect, QColor("#2a2a35"))
            font = painter.font()
            font.setPointSize(32)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, "📁" if is_folder else "🎬")
        painter.restore()

    def _draw_marquee_text(self, painter, rect, text, selected, alignment_flags):
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)

        if selected and text_width > rect.width():
            shift = int(self._offset % (text_width + 40))
            painter.save()
            painter.setClipRect(rect)

            # Forçamos o alinhamento à esquerda na animação e convertemos tudo para int()
            marquee_flags = int(Qt.AlignVCenter) | int(Qt.AlignLeft) | int(Qt.TextSingleLine)

            # Criamos retângulos deslocados para fazer o letreiro rodar
            rect1 = QRect(rect.x() - shift, rect.y(), text_width + 50, rect.height())
            rect2 = QRect(rect.x() - shift + text_width + 40, rect.y(), text_width + 50, rect.height())

            painter.drawText(rect1, marquee_flags, text)
            painter.drawText(rect2, marquee_flags, text)

            painter.restore()
        else:
            # Texto normal, sem animação
            final_flags = alignment_flags | int(Qt.TextSingleLine)
            painter.drawText(rect, final_flags, text)

    def sizeHint(self, option, index):
        if self.parent() and self.parent().viewMode() == QListView.ListMode:
            return QSize(self.parent().viewport().width(), 140)
        return GRID_ITEM_SIZE


class AnimatedWidget(QWidget):
    """Classe base para aplicar fade-in ao exibir as telas"""
    def showEvent(self, event):
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity")
        self.anim.setDuration(350)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.anim.start()
        super().showEvent(event)


class FirstRunView(AnimatedWidget):
    add_library_requested = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("Bem-vindo ao CouchLib")
        title.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {TEXT_MAIN};")
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel("Sua biblioteca offline de mídia")
        subtitle.setStyleSheet(f"font-size: 20px; color: {TEXT_MUTED}; margin-bottom: 40px;")
        subtitle.setAlignment(Qt.AlignCenter)

        self.button = QLabel("➕  Adicionar Diretório")
        self.button.setAlignment(Qt.AlignCenter)
        self.button.setStyleSheet(f"""
            font-size: 24px; font-weight: bold; color: white;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2b5876, stop:1 #4e4376);
            padding: 20px 50px; border-radius: 16px; border: 2px solid white;
        """)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.button, alignment=Qt.AlignHCenter)
        self.setStyleSheet(f"FirstRunView {{ background: {BG_COLOR}; }}")

    def on_a(self): self.add_library_requested.emit()
    def on_up(self): pass
    def on_down(self): pass
    def on_left(self): pass
    def on_right(self): pass
    def on_b(self): pass
    def on_y(self): pass


class FileBrowserView(AnimatedWidget):
    library_confirmed = Signal(str)
    cancelled = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_path = str(Path.home())
        self._entries = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(50, 40, 50, 40)

        header = QLabel("Selecione a Pasta da Biblioteca")
        header.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 28px; font-weight: bold;")

        self.path_label = QLabel(self.current_path)
        self.path_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 16px; margin-bottom: 10px;")

        self.list_view = QListView()
        self.list_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_view.setStyleSheet(f"""
            QListView {{ background: transparent; color: {TEXT_MAIN}; font-size: 22px; border: none; outline: none; }}
            QListView::item {{ padding: 15px; border-radius: 8px; }}
            QListView::item:selected {{ background: #2b5876; font-weight: bold; border: 1px solid white; }}
        """)

        hint = QLabel("A/✕: Abrir Pasta   •   Y/△: Confirmar como Biblioteca   •   B/○: Voltar")
        hint.setStyleSheet(f"color:{TEXT_MUTED}; font-size:16px; margin-top: 10px;")
        hint.setAlignment(Qt.AlignCenter)

        layout.addWidget(header)
        layout.addWidget(self.path_label)
        layout.addWidget(self.list_view)
        layout.addWidget(hint)
        self.setStyleSheet(f"FileBrowserView {{ background: {BG_COLOR}; }}")

        from PySide6.QtCore import QStringListModel
        self._model = QStringListModel()
        self.list_view.setModel(self._model)
        self._reload()

    def _reload(self):
        folders, _ = scan_directory(self.current_path)
        self._entries = folders
        names = [f"📁 {os.path.basename(f)}" for f in folders]
        self._model.setStringList(names)
        self.path_label.setText(self.current_path)
        if names: self.list_view.setCurrentIndex(self._model.index(0))

    def on_up(self):
        new_idx = self.list_view.moveCursor(QAbstractItemView.MoveUp, Qt.NoModifier)
        if new_idx.isValid(): self.list_view.setCurrentIndex(new_idx)
    def on_down(self):
        new_idx = self.list_view.moveCursor(QAbstractItemView.MoveDown, Qt.NoModifier)
        if new_idx.isValid(): self.list_view.setCurrentIndex(new_idx)
    def on_left(self): pass
    def on_right(self): pass
    def on_a(self):
        idx = self.list_view.currentIndex()
        if idx.isValid():
            self.current_path = self._entries[idx.row()]
            self._reload()
    def on_b(self):
        parent = os.path.dirname(self.current_path.rstrip("/"))
        if parent and parent != self.current_path:
            self.current_path = parent
            self._reload()
        else:
            self.cancelled.emit()
    def on_y(self): self.library_confirmed.emit(self.current_path)


class LibraryView(AnimatedWidget):
    video_selected = Signal(str)
    exit_requested = Signal()
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._history = []
        self.model = LibraryModel(db)

        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(ModernMarqueeDelegate(self.view))
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setStyleSheet("QListView { background: transparent; border: none; outline: none; }")
        self._set_grid_mode(True)

        self.breadcrumb = QLabel("")
        self.breadcrumb.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 24px; font-weight: bold; padding: 20px 20px 0px 30px;")

        hint = QLabel("A/✕: Abrir   •   X/□: Alterar Visualização   •   B/○: Voltar")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 16px; padding: 15px;")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.addWidget(self.breadcrumb)
        layout.addWidget(self.view)
        layout.addWidget(hint)
        self.setStyleSheet(f"LibraryView {{ background: {BG_COLOR}; }}")

    def _set_grid_mode(self, grid: bool):
        self.grid_mode = grid
        if grid:
            self.view.setViewMode(QListView.IconMode)
            self.view.setGridSize(GRID_ITEM_SIZE)
            self.view.setFlow(QListView.LeftToRight)
            self.view.setWrapping(True)
        else:
            self.view.setViewMode(QListView.ListMode)
            self.view.setGridSize(QSize())
            self.view.setFlow(QListView.TopToBottom)
            self.view.setWrapping(False)

    def open_library(self, root_path: str):
        self.root_path = root_path
        self.current_path = root_path
        self._history = []
        self._reload()

    def _reload(self):
        self.model.load(self.current_path)
        display_name = os.path.basename(self.current_path) if self.current_path != self.root_path else "Biblioteca Principal"
        self.breadcrumb.setText(f"📂 {display_name}")
        if self.model.rowCount() > 0: self.view.setCurrentIndex(self.model.index(0, 0))

    def on_up(self): self._move(QAbstractItemView.MoveUp)
    def on_down(self): self._move(QAbstractItemView.MoveDown)
    def on_left(self): self._move(QAbstractItemView.MoveLeft)
    def on_right(self): self._move(QAbstractItemView.MoveRight)
    def _move(self, action):
        new_idx = self.view.moveCursor(action, Qt.NoModifier)
        if new_idx.isValid(): self.view.setCurrentIndex(new_idx)

    def on_a(self):
        idx = self.view.currentIndex()
        if not idx.isValid(): return
        is_folder = self.model.data(idx, LibraryModel.IS_FOLDER_ROLE)
        path = self.model.data(idx, LibraryModel.PATH_ROLE)
        if is_folder:
            self._history.append(self.current_path)
            self.current_path = path
            self._reload()
        else:
            self.video_selected.emit(path)

    def on_b(self):
        if self._history:
            self.current_path = self._history.pop()
            self._reload()
        else:
            self.exit_requested.emit()
    def on_x(self): self._set_grid_mode(not self.grid_mode)
    def on_y(self): pass


class PlayerView(QWidget):
    exit_requested = Signal()
    mode_cycle_requested = Signal()

    FOCUS_CONTROLS = "controls"
    FOCUS_VOLUME = "volume"
    FOCUS_SEEKBAR = "seekbar"

    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.player = player
        self.current_video_path = None
        self.focus_area = self.FOCUS_CONTROLS
        self.control_index = 0
        self._duration = 0.0

        # Fundo do OSD suave
        self.setStyleSheet("PlayerView { background-color: rgba(0, 0, 0, 100); }")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(50, 50, 50, 50)
        main_layout.addStretch()

        self.title_label = QLabel("Reproduzindo...")
        self.title_label.setStyleSheet(f"color: white; font-size: 36px; font-weight: bold; background: transparent;")

        # Painel central moderno
        self.panel = QWidget()
        self.panel.setStyleSheet("""
            background: rgba(25, 25, 32, 220);
            border-radius: 20px;
            border: 1px solid rgba(255,255,255, 30);
        """)
        self.panel.setFixedWidth(1000)
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(30, 30, 30, 30)

        self.track_label = QLabel("")
        self.track_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 16px; background: transparent;")
        self.track_label.setAlignment(Qt.AlignCenter)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setStyleSheet("QSlider::handle:horizontal { background: #2b5876; width: 18px; border-radius: 9px; }")
        self.volume_slider.hide()

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 8px; background: rgba(255,255,255,40); border-radius: 4px; }
            QSlider::handle:horizontal { background: white; width: 16px; margin: -4px 0; border-radius: 8px; }
            QSlider::sub-page:horizontal { background: #2b5876; border-radius: 4px; }
        """)

        self.btn_play = QPushButton("⏯ Play")
        self.btn_back5 = QPushButton("⏪ -10s")
        self.btn_fwd5 = QPushButton("⏩ +10s")
        self.btn_audio = QPushButton("🎧 Áudio")
        self.btn_subtitle = QPushButton("💬 Legenda")
        self.btn_volume = QPushButton("🔊 Volume")
        self.btn_mode = QPushButton("🔂 Modo: One Shot")
        self.btn_exit = QPushButton("✕ Sair")

        self.controls = [
            self.btn_play, self.btn_back5, self.btn_fwd5,
            self.btn_audio, self.btn_subtitle, self.btn_volume, self.btn_mode, self.btn_exit
        ]

        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)
        for b in self.controls:
            b.setStyleSheet("""
                QPushButton {
                    font-size: 18px; padding: 14px 10px; color: white;
                    background: rgba(255, 255, 255, 10); border-radius: 12px; border: none;
                }
                QPushButton:focus, QPushButton[active='true'] {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2b5876, stop:1 #4e4376);
                    font-weight: bold; border: 2px solid white;
                }
            """)
            controls_row.addWidget(b)

        panel_layout.addWidget(self.title_label)
        panel_layout.addSpacing(10)
        panel_layout.addWidget(self.track_label)
        panel_layout.addWidget(self.volume_slider)
        panel_layout.addSpacing(20)
        panel_layout.addWidget(self.seek_slider)
        panel_layout.addSpacing(30)
        panel_layout.addLayout(controls_row)

        main_layout.addWidget(self.panel, alignment=Qt.AlignHCenter)

        # Preparar Efeito de Fade para o OSD
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.fade_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_anim.setDuration(400)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)

        self.fade_anim.finished.connect(self._on_fade_finished)

        self._hide_timer = QTimer(self)
        self._hide_timer.setInterval(5000)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_controls)

        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.volume_changed.connect(self._on_volume_changed)

        self._update_control_focus()

    def play_video(self, path: str):
        self.current_video_path = path
        self.title_label.setText(os.path.basename(path))
        self.player.play(path)
        self._show_controls()

    def _refresh_volume_display(self):
        value = self.player._volume
        muted = self.player._mute
        self.volume_slider.setValue(value)
        status = " (Mutado)" if muted else ""
        self.track_label.setText(f"Volume: {value}%{status}")
        self.track_label.show()

    def _on_volume_changed(self, value):
        self.volume_slider.setValue(value)

    def _show_controls(self):
        self.show()
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.opacity_effect.opacity())
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()
        self._hide_timer.start()

    def _hide_controls(self):
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.opacity_effect.opacity())
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.start()
        self.focus_area = self.FOCUS_CONTROLS

    def _on_fade_finished(self):
        # Se a opacidade chegou a zero, esconde para passar eventos de clique pro MPV (se houver)
        if self.opacity_effect.opacity() == 0.0:
            self.volume_slider.hide()
            self.track_label.hide()
            win = self.window()
            if win and hasattr(win, "hide_to_mpv") and win.stack.currentWidget() is self:
                win.hide_to_mpv()

    def _on_position(self, seconds):
        if self._duration > 0:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(int((seconds / self._duration) * 1000))
            self.seek_slider.blockSignals(False)

    def _on_duration(self, seconds):
        self._duration = seconds

    def _update_control_focus(self):
        for i, b in enumerate(self.controls):
            b.setProperty("active", i == self.control_index and self.focus_area == self.FOCUS_CONTROLS)
            b.style().unpolish(b)
            b.style().polish(b)

    def on_up(self):
        if self.focus_area == self.FOCUS_CONTROLS:
            self.focus_area = self.FOCUS_SEEKBAR
        elif self.focus_area == self.FOCUS_VOLUME:
            self.player.change_volume(5)
            self._refresh_volume_display()
        self._show_controls()
        self._update_control_focus()

    def on_down(self):
        if self.focus_area == self.FOCUS_SEEKBAR:
            self.focus_area = self.FOCUS_CONTROLS
        elif self.focus_area == self.FOCUS_VOLUME:
            self.player.change_volume(-5)
            self._refresh_volume_display()
        self._show_controls()
        self._update_control_focus()

    def on_left(self):
        if self.focus_area == self.FOCUS_CONTROLS:
            self.control_index = (self.control_index - 1) % len(self.controls)
            self._update_control_focus()
        elif self.focus_area == self.FOCUS_SEEKBAR:
            self.player.seek_relative(-10)
        elif self.focus_area == self.FOCUS_VOLUME:
            self.player.change_volume(-5)
            self._refresh_volume_display()
        self._show_controls()

    def on_right(self):
        if self.focus_area == self.FOCUS_CONTROLS:
            self.control_index = (self.control_index + 1) % len(self.controls)
            self._update_control_focus()
        elif self.focus_area == self.FOCUS_SEEKBAR:
            self.player.seek_relative(10)
        elif self.focus_area == self.FOCUS_VOLUME:
            self.player.change_volume(5)
            self._refresh_volume_display()
        self._show_controls()

    def on_a(self):
        if self.focus_area == self.FOCUS_VOLUME:
            self.player.toggle_mute()
            self._refresh_volume_display()
            self._show_controls()
            return
        if self.focus_area == self.FOCUS_CONTROLS:
            btn = self.controls[self.control_index]
            if btn is self.btn_play:
                self.player.toggle_pause()
            elif btn is self.btn_back5:
                self.player.seek_relative(-10)
            elif btn is self.btn_fwd5:
                self.player.seek_relative(10)
            elif btn is self.btn_audio:
                self.player.cycle_audio_track()
                self.track_label.setText("Faixa de Áudio Alterada")
                self.track_label.show()
            elif btn is self.btn_subtitle:
                self.player.cycle_subtitle_track()
                self.track_label.setText("Faixa de Legenda Alterada")
                self.track_label.show()
            elif btn is self.btn_volume:
                self.focus_area = self.FOCUS_VOLUME
                self.volume_slider.show()
                self._refresh_volume_display()
            elif btn is self.btn_mode:
                # A troca de modo em si (one shot/loop/playlist) e a
                # persistência ficam a cargo do MainWindow, que também sabe
                # a pasta/playlist atual. Aqui só avisamos que o botão foi
                # acionado.
                self.mode_cycle_requested.emit()
            elif btn is self.btn_exit:
                self.exit_requested.emit()
        self._show_controls()

    def set_mode_label(self, text: str):
        """Atualiza o texto do botão de modo e mostra um aviso rápido,
        chamado pelo MainWindow sempre que o modo de reprodução muda."""
        self.btn_mode.setText(f"🔂 Modo: {text}")
        self.track_label.setText(f"Modo de reprodução: {text}")
        self.track_label.show()

    def on_b(self):
        if self.focus_area != self.FOCUS_CONTROLS:
            self.focus_area = self.FOCUS_CONTROLS
            self.volume_slider.hide()
            self._update_control_focus()
            self._show_controls()
        else:
            self._hide_controls()

    def on_x(self):
        self.player.cycle_aspect_ratio()

    def on_y(self): pass


class MainWindow(QMainWindow):
    # Modos de reprodução disponíveis, na ordem em que o botão "Modo" cicla.
    # O rótulo é o que aparece no botão flutuante e no aviso de troca.
    PLAYBACK_MODES = [
        ("one_shot", "One Shot"),
        ("loop", "Loop"),
        ("playlist", "Playlist"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CouchLib")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(f"QMainWindow, QStackedWidget {{ background: {BG_COLOR}; }}")

        self.showFullScreen()
        self.raise_()
        self.activateWindow()

        self.db = Database()

        # Modo de reprodução persistido (padrão: one_shot). Guardamos só o
        # id ("one_shot"/"loop"/"playlist"); o rótulo é resolvido na hora
        # de exibir.
        saved_mode = self.db.get_setting("playback_mode", "one_shot")
        mode_ids = [m[0] for m in self.PLAYBACK_MODES]
        self.playback_mode = saved_mode if saved_mode in mode_ids else "one_shot"

        # Evita reentrância: parar o mpv pode fazer o IPC disparar um
        # end_of_file assíncrono (thread separada) mesmo numa saída manual
        # já tratada, o que duplicaria a volta pra biblioteca.
        self._exiting = False

        self.player = Player()
        self.player.end_of_file.connect(self._on_playback_ended)
        self.player.volume_changed.connect(self._on_player_volume_changed)
        self.player.playback_error.connect(self._on_playback_error)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.first_run_view = FirstRunView()
        self.file_browser_view = FileBrowserView()
        self.library_view = LibraryView(self.db)
        self.player_view = PlayerView(self.player)

        for w in (self.first_run_view, self.file_browser_view, self.library_view, self.player_view):
            self.stack.addWidget(w)

        self.first_run_view.add_library_requested.connect(self._go_to_file_browser)
        self.file_browser_view.library_confirmed.connect(self._add_library_and_open)
        self.file_browser_view.cancelled.connect(self._go_back_to_library_or_first_run)
        self.library_view.video_selected.connect(self._play_video)
        self.library_view.exit_requested.connect(self._go_to_file_browser)
        # Saída manual (botão Sair/B): sempre salva a posição atual, pra
        # poder continuar de onde parou.
        self.player_view.exit_requested.connect(lambda: self._return_to_library(save_position=True))
        self.player_view.mode_cycle_requested.connect(self._cycle_playback_mode)

        # Mostra o rótulo do modo persistido assim que o player_view existe.
        self.player_view.set_mode_label(dict(self.PLAYBACK_MODES)[self.playback_mode])

        # >>> FALLBACK DE RECONEXÃO: usamos o GUID do último gamepad salvo no
        # banco para que o GamepadManager saiba priorizar o mesmo controle
        # físico, caso mais de um esteja disponível. <<<
        known_gamepad = self.db.get_known_gamepad()
        preferred_guid = known_gamepad["guid"] if known_gamepad else None

        self.gamepad = GamepadManager(preferred_guid=preferred_guid)
        self.gamepad.dpad_up.connect(lambda: self._dispatch("on_up"))
        self.gamepad.dpad_down.connect(lambda: self._dispatch("on_down"))
        self.gamepad.dpad_left.connect(lambda: self._dispatch("on_left"))
        self.gamepad.dpad_right.connect(lambda: self._dispatch("on_right"))
        self.gamepad.button_a.connect(lambda: self._dispatch("on_a"))
        self.gamepad.button_b.connect(lambda: self._dispatch("on_b"))
        self.gamepad.button_x.connect(lambda: self._dispatch("on_x"))
        self.gamepad.button_y.connect(lambda: self._dispatch("on_y"))
        self.gamepad.connected.connect(self._on_gamepad_connected)
        self.gamepad.disconnected.connect(self._on_gamepad_disconnected)
        self.gamepad.start()

        self._decide_initial_screen()

    def _on_gamepad_connected(self, name, guid):
        # Salva a identificação do controle (GUID + nome) no banco, para que
        # o fallback de reconexão saiba qual controle priorizar da próxima vez.
        self.db.set_known_gamepad(guid, name)
        print(f"[gamepad] conectado: {name}")

    def _on_gamepad_disconnected(self):
        print("[gamepad] desconectado — aguardando reconexão...")

    def _dispatch(self, method_name):
        if self.isHidden():
            if method_name in ("on_up", "on_down", "on_b"):
                self.show_from_mpv()
                self.stack.setCurrentWidget(self.player_view)
                self.player_view._show_controls()
            elif method_name == "on_left":
                self.player.seek_relative(-10)
            elif method_name == "on_right":
                self.player.seek_relative(10)
            elif method_name == "on_a":
                self.player.toggle_pause()
            return

        current = self.stack.currentWidget()
        method = getattr(current, method_name, None)
        if callable(method):
            method()

    def hide_to_mpv(self):
        self.hide()

    def show_from_mpv(self):
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def _decide_initial_screen(self):
        libs = self.db.get_libraries()
        if libs:
            self.library_view.open_library(libs[0]["path"])
            self.stack.setCurrentWidget(self.library_view)
        else:
            self.stack.setCurrentWidget(self.first_run_view)

    def _go_to_file_browser(self):
        self.stack.setCurrentWidget(self.file_browser_view)

    def _go_back_to_library_or_first_run(self):
        libs = self.db.get_libraries()
        if libs:
            self.stack.setCurrentWidget(self.library_view)
        else:
            self.stack.setCurrentWidget(self.first_run_view)

    def _add_library_and_open(self, path):
        self.db.add_library(path)
        self.library_view.open_library(path)
        self.stack.setCurrentWidget(self.library_view)

    def _play_video(self, path):
        self._exiting = False
        self.player_view.current_video_path = path
        self.player_view.title_label.setText(os.path.basename(path))

        vol_str = self.db.get_setting("volume", "100")
        vol = int(vol_str) if vol_str.isdigit() else 100

        # Cache de resume_position é por vídeo (chave = path), então cada
        # arquivo mantém seu próprio progresso independente dos outros.
        cache = self.db.get_video_cache(path)
        start_pos = cache["resume_position"] if cache and cache["resume_position"] else 0.0

        # >>> ADICIONE ESTA LINHA: Deixa o fundo transparente para o vídeo aparecer <<<
        self.setStyleSheet("QMainWindow, QStackedWidget { background: transparent; }")

        self.player.play(path, start_at=start_pos, volume=vol, loop=(self.playback_mode == "loop"))

        self.stack.setCurrentWidget(self.player_view)
        self.player_view._show_controls()

    def _get_next_video_in_folder(self, path):
        """Retorna o próximo vídeo da mesma pasta (mesma ordem exibida na
        biblioteca), ou None se 'path' for o último ou não for encontrado."""
        folder = os.path.dirname(path)
        _, videos = scan_directory(folder)
        if path not in videos:
            return None
        idx = videos.index(path)
        if idx + 1 < len(videos):
            return videos[idx + 1]
        return None

    def _on_playback_ended(self, reason: str):
        """Chamado sempre que o Player emite end_of_file, com o motivo
        vindo do mpv: 'eof' (vídeo terminou sozinho), 'stop'/'quit' (saída
        pedida por nós), 'error', ou 'closed' (conexão caiu sem end-file)."""
        path = self.player_view.current_video_path

        if reason == "eof":
            # O vídeo chegou ao fim sozinho: zera a posição salva, pra que
            # o próximo play sempre comece do zero (em vez de reabrir já
            # nos últimos segundos e fechar na hora).
            if path:
                self.db.set_resume_position(path, 0.0)

            if self.playback_mode == "playlist":
                next_path = self._get_next_video_in_folder(path) if path else None
                if next_path:
                    self._play_video(next_path)
                    return
            # one_shot (ou playlist sem próximo vídeo): volta pra biblioteca
            # sem tentar salvar posição de novo (já zerada acima).
            self._return_to_library(save_position=False)
        else:
            # Saída manual, erro, ou conexão caída no meio do vídeo: salva
            # onde parou, pra poder continuar depois.
            self._return_to_library(save_position=True)

    def _return_to_library(self, save_position: bool):
        if self._exiting:
            return
        self._exiting = True

        if save_position and self.player_view.current_video_path:
            self.db.set_resume_position(self.player_view.current_video_path, self.player._current_pos)

        self.player.stop()

        # ---> ADICIONE ESTAS 3 LINHAS: Matam qualquer animação e escondem o menu atual <---
        self.player_view._hide_timer.stop()
        self.player_view.fade_anim.stop()
        self.player_view.opacity_effect.setOpacity(0.0)

        self.show_from_mpv()

        # Restaura a cor sólida que criamos antes
        self.setStyleSheet(f"QMainWindow, QStackedWidget {{ background: {BG_COLOR}; }}")

        self.stack.setCurrentWidget(self.library_view)

        # ---> ADICIONE ESTA LINHA: Força o PySide6 a repintar a tela (limpando o fantasma) <---
        self.repaint()

    def _cycle_playback_mode(self):
        ids = [m[0] for m in self.PLAYBACK_MODES]
        labels = dict(self.PLAYBACK_MODES)
        current_idx = ids.index(self.playback_mode)
        self.playback_mode = ids[(current_idx + 1) % len(ids)]
        self.db.set_setting("playback_mode", self.playback_mode)
        self.player_view.set_mode_label(labels[self.playback_mode])

        # Se um vídeo já está tocando, aplica a troca imediatamente:
        # ligando/desligando o loop nativo do mpv sem reiniciar o vídeo do
        # zero. Sair do modo loop faz o mpv parar de repetir mas continuar
        # de onde está; entrar no modo loop só vale a partir do próximo play.
        if self.stack.currentWidget() is self.player_view:
            self.player.set_loop(self.playback_mode == "loop")

    def _on_player_volume_changed(self, vol):
        self.db.set_setting("volume", str(vol))

    def _on_playback_error(self, msg):
        QMessageBox.critical(self, "Erro de Reprodução", msg)
        self._return_to_library(save_position=False)

    def closeEvent(self, event):
        self.gamepad.stop()
        self.player.shutdown()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # Suavização global de fontes do Qt
    font = app.font()
    font.setFamily("Sans Serif")
    app.setFont(font)

    locale.setlocale(locale.LC_NUMERIC, "C")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()