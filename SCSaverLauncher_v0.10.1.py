from __future__ import annotations

import sys
import ctypes
import json
import logging
import os
import random
import shutil
import traceback
import struct
import threading
import time
from ctypes import wintypes
from pathlib import Path
from datetime import datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from enum import Enum, auto

from PySide6.QtCore import (
    QEasingCurve,
    QLockFile,
    QPoint,
    QStandardPaths,
    Property,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTextEdit,
    QVBoxLayout,
    QStackedWidget,
    QWidget,
)


APP_NAME = "SCSaver"
APP_VERSION = "0.10.1-local-log"

LOCAL_APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
LOG_DIR = LOCAL_APP_DIR / "log"
SESSION_LOG_PATH = None
FILE_LOGGER = logging.getLogger("SCSaver")


def setup_file_logging():
    global SESSION_LOG_PATH
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_LOG_PATH = LOG_DIR / datetime.now().strftime("%Y-%m-%d_%H-%M-%S.log")
    handler = logging.FileHandler(SESSION_LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    FILE_LOGGER.setLevel(logging.INFO)
    FILE_LOGGER.handlers.clear()
    FILE_LOGGER.addHandler(handler)
    FILE_LOGGER.propagate = False
    FILE_LOGGER.info("%s %s started", APP_NAME, APP_VERSION)
    FILE_LOGGER.info("Log file: %s", SESSION_LOG_PATH)


def write_file_log(message, level=logging.INFO):
    try:
        FILE_LOGGER.log(level, str(message))
        for handler in FILE_LOGGER.handlers:
            handler.flush()
    except Exception:
        pass


def finalize_file_logging():
    if not FILE_LOGGER.handlers:
        return
    write_file_log(f"{APP_NAME} terminated")
    for handler in list(FILE_LOGGER.handlers):
        try:
            handler.flush()
            handler.close()
        finally:
            FILE_LOGGER.removeHandler(handler)
    if SESSION_LOG_PATH and SESSION_LOG_PATH.exists():
        try:
            shutil.copyfile(SESSION_LOG_PATH, LOG_DIR / "latestlog.txt")
        except OSError:
            pass


def log_uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    write_file_log(
        "Unhandled exception:\n" + "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        ),
        logging.CRITICAL,
    )
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

ACCENT_COLOR = QColor("#12B8A6")
ACCENT_DARK_COLOR = QColor("#087F74")
ACCENT_LIGHT_COLOR = QColor("#A7E8E0")

BACKGROUND_COLOR = QColor("#FFFFFF")
TEXT_COLOR = QColor("#202020")
BORDER_COLOR = QColor("#C8DDD9")
ERROR_COLOR = QColor("#D64545")


class AppState(Enum):
    STARTING = auto()
    SERVER_CONNECTING = auto()
    GAME_WAITING = auto()
    MAP_WAITING = auto()
    CONNECTED = auto()
    SAVING = auto()
    SAVE_DONE = auto()
    LOADING = auto()
    LOAD_DONE = auto()
    SYNC_PENDING = auto()
    ERROR = auto()


STATE_TEXT = {
    AppState.STARTING: "SCSaver 시작 중",
    AppState.SERVER_CONNECTING: "서버 연결 중...",
    AppState.GAME_WAITING: "스타크래프트 대기 중",
    AppState.MAP_WAITING: "맵 대기 중",
    AppState.CONNECTED: "SCSaver 연결됨",
    AppState.SAVING: "저장 중...",
    AppState.SAVE_DONE: "저장완료",
    AppState.LOADING: "불러오는 중...",
    AppState.LOAD_DONE: "불러오기 완료",
    AppState.SYNC_PENDING: "서버 동기화 대기",
    AppState.ERROR: "오류 발생",
}


ANIMATED_STATES = {
    AppState.STARTING,
    AppState.SERVER_CONNECTING,
    AppState.GAME_WAITING,
    AppState.MAP_WAITING,
    AppState.SAVING,
    AppState.LOADING,
    AppState.SYNC_PENDING,
}


class StatusWidget(QWidget):
    """
    중앙 상태 표시 위젯.

    회전 상태:
        바깥쪽 원호가 회전합니다.

    완료 상태:
        회전이 멈추고 구름 및 체크 모양을 표시합니다.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._rotation = 0.0
        self._state = AppState.STARTING
        self._progress_text = ""

        self.setMinimumSize(225, 205)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.animation = QPropertyAnimation(
            self,
            b"rotation",
            self,
        )
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(360.0)
        self.animation.setDuration(1250)
        self.animation.setLoopCount(-1)
        self.animation.setEasingCurve(QEasingCurve.Type.Linear)

    def get_rotation(self) -> float:
        return self._rotation

    def set_rotation(self, value: float):
        self._rotation = value
        self.update()

    rotation = Property(
        float,
        get_rotation,
        set_rotation,
    )

    def set_state(
        self,
        state: AppState,
        progress_text: str = "",
    ):
        self._state = state
        self._progress_text = progress_text

        if state in ANIMATED_STATES:
            if self.animation.state() != QPropertyAnimation.State.Running:
                self.animation.start()
        else:
            self.animation.stop()
            self._rotation = 0.0

        self.update()

    def paintEvent(self, event):
        del event

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width = self.width()
        height = self.height()

        center_x = width / 2
        center_y = height / 2 - 12

        icon_size = min(width, height) * 0.53
        radius = icon_size / 2

        circle_rect = QRectF(
            center_x - radius,
            center_y - radius,
            icon_size,
            icon_size,
        )

        if self._state in ANIMATED_STATES:
            self._draw_spinner(
                painter,
                circle_rect,
            )
        else:
            self._draw_static_circle(
                painter,
                circle_rect,
            )

        self._draw_star(
            painter,
            center_x,
            center_y,
            radius * 0.60,
        )

        if self._state in {
            AppState.SAVE_DONE,
            AppState.LOAD_DONE,
            AppState.CONNECTED,
        }:
            self._draw_check(
                painter,
                center_x + radius * 0.47,
                center_y + radius * 0.43,
                radius * 0.25,
            )

        if self._state == AppState.ERROR:
            self._draw_error_mark(
                painter,
                center_x + radius * 0.45,
                center_y + radius * 0.42,
                radius * 0.32,
            )

        self._draw_status_text(
            painter,
            center_x,
            center_y + radius + 18,
        )

    def _draw_spinner(
        self,
        painter: QPainter,
        circle_rect: QRectF,
    ):
        background_pen = QPen(
            ACCENT_LIGHT_COLOR,
            7,
        )

        background_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )

        painter.setPen(background_pen)
        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )
        painter.drawEllipse(circle_rect)

        foreground_pen = QPen(
            ACCENT_COLOR,
            7,
        )

        foreground_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )

        painter.setPen(foreground_pen)

        start_angle = int(
            self._rotation * 16
        )
        span_angle = int(
            105 * 16
        )

        painter.drawArc(
            circle_rect,
            -start_angle,
            -span_angle,
        )

    def _draw_static_circle(
        self,
        painter: QPainter,
        circle_rect: QRectF,
    ):
        painter.setPen(Qt.PenStyle.NoPen)

        if self._state == AppState.ERROR:
            painter.setBrush(QColor("#c62828"))
        elif self._state == AppState.SYNC_PENDING:
            painter.setBrush(QColor("#f59e0b"))
        else:
            painter.setBrush(ACCENT_COLOR)

        painter.drawEllipse(circle_rect)

    def _draw_star(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        outer_radius: float,
    ):
        import math

        inner_radius = outer_radius * 0.45
        star_path = QPainterPath()

        for index in range(10):
            angle = (
                -math.pi / 2
                + index * math.pi / 5
            )

            if index % 2 == 0:
                radius = outer_radius
            else:
                radius = inner_radius

            point_x = center_x + math.cos(angle) * radius
            point_y = center_y + math.sin(angle) * radius

            if index == 0:
                star_path.moveTo(
                    point_x,
                    point_y,
                )
            else:
                star_path.lineTo(
                    point_x,
                    point_y,
                )

        star_path.closeSubpath()

        if self._state in ANIMATED_STATES:
            star_pen = QPen(
                ACCENT_COLOR,
                max(3, int(outer_radius * 0.09)),
            )

            star_pen.setJoinStyle(
                Qt.PenJoinStyle.RoundJoin
            )

            painter.setPen(star_pen)
            painter.setBrush(
                QColor("#E9FAF7")
            )
        elif self._state == AppState.ERROR:
            star_pen = QPen(
                QColor("#FFFFFF"),
                max(3, int(outer_radius * 0.09)),
            )

            star_pen.setJoinStyle(
                Qt.PenJoinStyle.RoundJoin
            )

            painter.setPen(star_pen)
            painter.setBrush(
                QColor("#FFFFFF")
            )
        else:
            star_pen = QPen(
                QColor("#FFFFFF"),
                max(3, int(outer_radius * 0.09)),
            )

            star_pen.setJoinStyle(
                Qt.PenJoinStyle.RoundJoin
            )

            painter.setPen(star_pen)
            painter.setBrush(
                QColor("#FFFFFF")
            )

        painter.drawPath(star_path)

    def _draw_check(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        radius: float,
    ):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(
            QRectF(
                center_x - radius,
                center_y - radius,
                radius * 2,
                radius * 2,
            )
        )

        pen = QPen(
            ACCENT_DARK_COLOR,
            max(3, int(radius * 0.28)),
        )
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.drawLine(
            QPoint(
                int(center_x - radius * 0.50),
                int(center_y),
            ),
            QPoint(
                int(center_x - radius * 0.12),
                int(center_y + radius * 0.38),
            ),
        )
        painter.drawLine(
            QPoint(
                int(center_x - radius * 0.12),
                int(center_y + radius * 0.38),
            ),
            QPoint(
                int(center_x + radius * 0.58),
                int(center_y - radius * 0.45),
            ),
        )

    def _draw_error_mark(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        radius: float,
    ):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(
            QRectF(
                center_x - radius,
                center_y - radius,
                radius * 2,
                radius * 2,
            )
        )

        pen = QPen(
            QColor("#c62828"),
            max(3, int(radius * 0.25)),
        )
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        painter.drawLine(
            QPoint(
                int(center_x - radius * 0.4),
                int(center_y - radius * 0.4),
            ),
            QPoint(
                int(center_x + radius * 0.4),
                int(center_y + radius * 0.4),
            ),
        )

        painter.drawLine(
            QPoint(
                int(center_x + radius * 0.4),
                int(center_y - radius * 0.4),
            ),
            QPoint(
                int(center_x - radius * 0.4),
                int(center_y + radius * 0.4),
            ),
        )

    def _draw_status_text(
        self,
        painter: QPainter,
        center_x: float,
        text_y: float,
    ):
        painter.setPen(TEXT_COLOR)

        font = QFont("Malgun Gothic", 9)
        font.setBold(False)
        painter.setFont(font)

        status_text = STATE_TEXT[self._state]

        if self._progress_text:
            status_text = (
                f"{status_text}\n"
                f"{self._progress_text}"
            )

        text_rect = QRectF(
            0,
            text_y,
            self.width(),
            30,
        )

        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignTop,
            status_text,
        )


class TitleBar(QFrame):
    minimize_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.drag_position: QPoint | None = None

        self.setFixedHeight(31)
        self.setStyleSheet(
            """
            TitleBar {
                background-color: #12B8A6;
            }

            QLabel {
                color: #102020;
                font-family: "Malgun Gothic";
                font-size: 15px;
                font-weight: bold;
                padding-left: 6px;
            }

            QPushButton {
                color: #074F48;
                background-color: transparent;
                border: none;
                font-size: 12px;
                min-width: 30px;
                max-width: 30px;
                min-height: 30px;
                max-height: 30px;
                padding: 0px;
            }

            QPushButton:hover {
                background-color: rgba(255, 255, 255, 55);
            }

            QPushButton#closeButton:hover {
                color: white;
                background-color: #087F74;
            }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_label = QLabel(
            f"{APP_NAME} {APP_VERSION}"
        )

        minimize_button = QPushButton("─")
        minimize_button.clicked.connect(
            self.minimize_requested.emit
        )

        close_button = QPushButton("✕")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(
            self.close_requested.emit
        )

        layout.addWidget(title_label)
        layout.addStretch(1)
        layout.addWidget(minimize_button)
        layout.addWidget(close_button)

    def mousePressEvent(
        self,
        event: QMouseEvent,
    ):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = (
                event.globalPosition().toPoint()
                - self.window().frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(
        self,
        event: QMouseEvent,
    ):
        if (
            self.drag_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.window().move(
                event.globalPosition().toPoint()
                - self.drag_position
            )
            event.accept()

    def mouseReleaseEvent(
        self,
        event: QMouseEvent,
    ):
        self.drag_position = None
        event.accept()


class SideMenu(QFrame):
    notice_clicked = Signal()
    homepage_clicked = Signal()
    log_clicked = Signal()
    logout_clicked = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setFixedWidth(90)

        self.setStyleSheet(
            """
            SideMenu {
                background-color: #FFFFFF;
                border-right: 1px solid #9DDDD6;
            }

            QPushButton {
                color: #087F74;
                background-color: #FFFFFF;
                border: 1px solid #69CFC3;
                border-left: none;
                border-right: none;
                font-family: "Malgun Gothic";
                font-size: 13px;
                min-height: 30px;
                max-height: 30px;
                padding: 0px;
            }

            QPushButton:hover {
                color: white;
                background-color: #12B8A6;
            }

            QPushButton:pressed {
                background-color: #087F74;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        notice_button = QPushButton("공지사항")
        homepage_button = QPushButton("홈페이지")
        log_button = QPushButton("로그보기")
        logout_button = QPushButton("로그아웃")

        notice_button.clicked.connect(
            self.notice_clicked.emit
        )
        homepage_button.clicked.connect(
            self.homepage_clicked.emit
        )
        log_button.clicked.connect(
            self.log_clicked.emit
        )
        logout_button.clicked.connect(
            self.logout_clicked.emit
        )

        layout.addWidget(notice_button)
        layout.addWidget(homepage_button)
        layout.addWidget(log_button)

        layout.addItem(
            QSpacerItem(
                10,
                10,
                QSizePolicy.Policy.Minimum,
                QSizePolicy.Policy.Expanding,
            )
        )

        layout.addWidget(logout_button)


class LogPage(QWidget):
    back_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setStyleSheet(
            """
            LogPage {
                background-color: #ffffff;
            }

            QLabel {
                color: #087F74;
                font-family: "Malgun Gothic";
                font-size: 11px;
                font-weight: bold;
            }

            QTextEdit {
                color: #eeeeee;
                background-color: #252525;
                border: 1px solid #12B8A6;
                font-family: "Consolas";
                font-size: 9px;
                padding: 5px;
                selection-background-color: #087F74;
            }

            QPushButton {
                color: #087F74;
                background-color: #ffffff;
                border: 1px solid #69CFC3;
                font-family: "Malgun Gothic";
                font-size: 9px;
                min-height: 24px;
                max-height: 24px;
                padding-left: 8px;
                padding-right: 8px;
            }

            QPushButton:hover {
                color: white;
                background-color: #12B8A6;
            }

            QPushButton:pressed {
                background-color: #087F74;
            }
            """
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(7, 6, 7, 6)
        root_layout.setSpacing(5)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(5)

        title_label = QLabel("SCSaver 로그")

        self.clear_button = QPushButton("지우기")

        self.clear_button.setFixedWidth(48)

        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.clear_button)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        # 가로 스크롤을 없애 창 밖으로 나가지 않게 함
        self.log_output.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
        )

        # 세로 스크롤은 필요할 때만 표시
        self.log_output.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.log_output.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.clear_button.clicked.connect(
            self.log_output.clear
        )

        root_layout.addLayout(header_layout)
        root_layout.addWidget(
            self.log_output,
            1,
        )

    def append_log(
        self,
        message: str,
    ):
        self.log_output.append(message)

        # 새 로그가 들어오면 자동으로 맨 아래로 이동
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(
            scrollbar.maximum()
        )



if os.name != "nt":
    raise SystemExit("SCSaver is Windows-only")

MAGIC = b"SCSV0001"
VERSION = 6
DWORDS = 88
MAX_PAYLOAD = 64
PROCESS_NAME = "StarCraft.exe"
POLL_SECONDS = 0.25
RESCAN_SECONDS = 2.0

IDX_VERSION = 2
IDX_SIZE = 4
IDX_MAP_HASH = 5
IDX_SCHEMA = 6
IDX_MAP_HB = 8
IDX_LAUNCHER_HB = 9
IDX_LAUNCHER_STATUS = 10
IDX_SESSION = 11
IDX_SAVE_REQ = 12
IDX_SAVE_ACK = 13
IDX_LOAD_REQ = 14
IDX_LOAD_ACK = 15
IDX_RESULT = 16
IDX_SLOT = 17
IDX_PAYLOAD_COUNT = 18
IDX_PAYLOAD0 = 19
IDX_ERROR = 83
IDX_TOTAL_COUNT = 84
IDX_CHUNK_INDEX = 85
IDX_CHUNK_COUNT = 86
IDX_CHUNK_SIZE = 87

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x0100
PAGE_NOACCESS = 0x0001
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def find_pid(exe_name):
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return None

    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.casefold() == exe_name.casefold():
                return int(entry.th32ProcessID)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return None


class ProcessMemory:
    def __init__(self, pid):
        access = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        self.pid = pid
        self.handle = kernel32.OpenProcess(access, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "OpenProcess failed")

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, size):
        buffer = ctypes.create_string_buffer(size)
        received = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(received)):
            raise OSError(ctypes.get_last_error(), "ReadProcessMemory failed")
        return buffer.raw[:received.value]

    def write_u32(self, address, value):
        source = ctypes.create_string_buffer(struct.pack("<I", value & 0xFFFFFFFF))
        written = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(self.handle, ctypes.c_void_p(address), source, 4, ctypes.byref(written)):
            raise OSError(ctypes.get_last_error(), "WriteProcessMemory failed")
        if written.value != 4:
            raise OSError("short WriteProcessMemory")

    def scan(self, needle):
        region_count = 0
        hits = []
        address = 0
        mbi = MEMORY_BASIC_INFORMATION()
        overlap = len(needle) - 1

        while address < 0xFFFFFFFF:
            queried = kernel32.VirtualQueryEx(
                self.handle,
                ctypes.c_void_p(address),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi),
            )
            if not queried:
                address += 0x10000
                continue

            base = int(mbi.BaseAddress or 0)
            size = int(mbi.RegionSize or 0)
            readable = (
                mbi.State == MEM_COMMIT
                and not (mbi.Protect & PAGE_GUARD)
                and mbi.Protect != PAGE_NOACCESS
                and size > 0
            )

            if readable:
                offset = 0
                previous = b""
                while offset < size:
                    chunk_size = min(1024 * 1024, size - offset)
                    try:
                        chunk = self.read(base + offset, chunk_size)
                    except OSError:
                        offset += 0x1000
                        previous = b""
                        continue

                    combined = previous + chunk
                    start = 0
                    while True:
                        position = combined.find(needle, start)
                        if position < 0:
                            break
                        found = base + offset - len(previous) + position
                        if found not in hits:
                            hits.append(found)
                        start = position + 1

                    previous = combined[-overlap:] if overlap else b""
                    offset += max(len(chunk), 0x1000)
                    # UI 스레드가 실행될 시간을 양보한다.
                    time.sleep(0)

            next_address = base + max(size, 0x1000)
            address = next_address if next_address > address else address + 0x1000
            region_count += 1
            if region_count % 32 == 0:
                time.sleep(0.001)
        return hits


DATA_DIR = Path(__file__).resolve().parent / "data"
ENCRYPTED_SAVE_PATH = DATA_DIR / "SCSaver.scsave"
ENCRYPTED_MAGIC = b"SCSENC01"

class EncryptedSaveError(RuntimeError):
    pass

class EncryptedSaveStore:
    def __init__(self, path):
        self.path=path; self.user_id=""; self.password=""; self.lock=threading.RLock()
    def configure(self,user_id,password):
        self.user_id=user_id.strip().casefold(); self.password=password
        if not self.user_id or not self.password: raise EncryptedSaveError("저장 ID와 비밀번호를 입력하세요")
        if self.path.exists(): self._read()
        else: self._write({"format":"SCSaver-local","version":1,"saves":{}})
    def clear_credentials(self): self.user_id=""; self.password=""
    def _key(self,salt):
        return Scrypt(salt=salt,length=32,n=2**15,r=8,p=1).derive(self.password.encode("utf-8"))
    def _aad(self): return ("SCSaver|"+self.user_id).encode("utf-8")
    def _read(self):
        with self.lock:
            try:
                blob=self.path.read_bytes()
                if len(blob)<52 or blob[:8]!=ENCRYPTED_MAGIC: raise EncryptedSaveError("암호화 저장 파일 형식이 올바르지 않습니다")
                plain=AESGCM(self._key(blob[8:24])).decrypt(blob[24:36],blob[36:],self._aad())
                doc=json.loads(plain.decode("utf-8"))
                if doc.get("format")!="SCSaver-local": raise EncryptedSaveError("저장 파일 형식이 일치하지 않습니다")
                return doc
            except InvalidTag as e: raise EncryptedSaveError("비밀번호가 틀렸거나 저장 파일이 변조되었습니다") from e
    def _write(self,doc):
        with self.lock:
            self.path.parent.mkdir(parents=True,exist_ok=True); salt=os.urandom(16); nonce=os.urandom(12)
            plain=json.dumps(doc,ensure_ascii=False,separators=(",",":")).encode("utf-8")
            data=ENCRYPTED_MAGIC+salt+nonce+AESGCM(self._key(salt)).encrypt(nonce,plain,self._aad())
            tmp=self.path.with_suffix(".tmp"); tmp.write_bytes(data); os.replace(tmp,self.path)
    def save(self,map_hash,schema,slot,payload):
        doc=self._read(); key=f"{map_hash:08X}:{slot}"
        doc["saves"][key]={"map_hash":f"{map_hash:08X}","schema":int(schema),"slot":int(slot),"payload_count":len(payload),"payload":[int(v)&0xFFFFFFFF for v in payload],"saved_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        self._write(doc)
    def load(self,map_hash,slot):
        value=self._read()["saves"].get(f"{map_hash:08X}:{slot}")
        if value is None: raise EncryptedSaveError("해당 슬롯의 저장 데이터가 없습니다")
        return value

ENCRYPTED_STORE=EncryptedSaveStore(ENCRYPTED_SAVE_PATH)


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class AutoLoginStore:
    """Windows-user-bound automatic login storage using DPAPI."""

    def __init__(self):
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA", Path.home())
        )
        self.path = local_app_data / APP_NAME / "auth.dat"
        self.entropy = b"SCSaver.AutoLogin.v1"

    @staticmethod
    def _blob(data: bytes):
        buffer = ctypes.create_string_buffer(data)
        blob = _DataBlob(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        return blob, buffer

    def _protect(self, data: bytes) -> bytes:
        if sys.platform != "win32":
            raise RuntimeError("자동 로그인은 Windows에서만 지원됩니다")
        input_blob, input_buffer = self._blob(data)
        entropy_blob, entropy_buffer = self._blob(self.entropy)
        output_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "SCSaver automatic login",
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(output_blob.pbData)

    def _unprotect(self, data: bytes) -> bytes:
        if sys.platform != "win32":
            raise RuntimeError("자동 로그인은 Windows에서만 지원됩니다")
        input_blob, input_buffer = self._blob(data)
        entropy_blob, entropy_buffer = self._blob(self.entropy)
        output_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(output_blob.pbData)

    def save(self, user_id: str, password: str):
        document = json.dumps(
            {"version": 1, "user_id": user_id, "password": password},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        encrypted = self._protect(document)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(encrypted)
        os.replace(temporary, self.path)

    def load(self):
        if not self.path.exists():
            return None
        try:
            document = json.loads(
                self._unprotect(self.path.read_bytes()).decode("utf-8")
            )
            user_id = str(document.get("user_id", "")).strip()
            password = str(document.get("password", ""))
            if not user_id or not password:
                raise ValueError("empty credentials")
            return user_id, password
        except Exception:
            self.clear()
            return None

    def clear(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


AUTO_LOGIN_STORE = AutoLoginStore()


class Worker(threading.Thread):
    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback
        self.stop_event = threading.Event()
        self.session = random.getrandbits(32) or 1
        self.heartbeat = 0
        self.save_transfers = {}
        self.map_heartbeat_by_address = {}

    def emit(self, state, detail=""):
        self.callback(state, detail)

    def stop(self):
        self.stop_event.set()

    def run(self):
        memory = None
        pid = None
        candidates = []
        last_scan = 0.0

        try:
            while not self.stop_event.is_set():
                discovered_pid = find_pid(PROCESS_NAME)

                if discovered_pid is None:
                    if memory:
                        memory.close()
                        memory = None
                    pid = None
                    candidates = []
                    self.map_heartbeat_by_address.clear()
                    self.emit("스타크래프트 대기 중", PROCESS_NAME)
                    time.sleep(1.0)
                    continue

                if memory is None or pid != discovered_pid:
                    if memory:
                        memory.close()
                    try:
                        memory = ProcessMemory(discovered_pid)
                        pid = discovered_pid
                        candidates = []
                        self.map_heartbeat_by_address.clear()
                        last_scan = 0.0
                    except OSError as error:
                        memory = None
                        self.emit("프로세스 연결 실패", str(error))
                        time.sleep(1.0)
                        continue

                now = time.monotonic()
                if now - last_scan >= RESCAN_SECONDS:
                    last_scan = now
                    found = []

                    self.emit(
                        "맵 대기 중",
                    )

                    for address in memory.scan(MAGIC):
                        try:
                            raw = memory.read(address, DWORDS * 4)
                            if len(raw) != DWORDS * 4:
                                continue
                            words = struct.unpack("<88I", raw)
                            if raw[:8] == MAGIC and words[IDX_VERSION] == VERSION and words[IDX_SIZE] == DWORDS:
                                found.append(address)
                        except (OSError, struct.error):
                            continue
                    candidates = found

                if not candidates:
                    self.emit("맵 대기 중")
                    time.sleep(0.5)
                    continue

                self.heartbeat = (self.heartbeat + 1) & 0xFFFFFFFF or 1
                valid = []
                active = []
                for address in candidates:
                    try:
                        raw = memory.read(address, DWORDS * 4)
                        words = struct.unpack("<88I", raw)
                        if raw[:8] != MAGIC or words[IDX_VERSION] != VERSION or words[IDX_SIZE] != DWORDS:
                            continue

                        map_hb = words[IDX_MAP_HB]
                        previous_hb = self.map_heartbeat_by_address.get(address)
                        self.map_heartbeat_by_address[address] = map_hb

                        memory.write_u32(address + IDX_LAUNCHER_HB * 4, self.heartbeat)
                        memory.write_u32(address + IDX_LAUNCHER_STATUS * 4, 1)
                        memory.write_u32(address + IDX_SESSION * 4, self.session)
                        valid.append((address, words))

                        # 리방 전 descriptor는 메모리에 남아도 heartbeat가 멈춥니다.
                        # 현재 heartbeat가 실제로 증가한 descriptor만 활성 맵으로 봅니다.
                        if previous_hb is not None and map_hb != 0 and map_hb != previous_hb:
                            active.append((address, words))
                    except (OSError, struct.error):
                        continue

                candidates = [address for address, _ in valid]
                current_addresses = set(candidates)
                self.map_heartbeat_by_address = {
                    address: heartbeat
                    for address, heartbeat in self.map_heartbeat_by_address.items()
                    if address in current_addresses
                }

                if not active:
                    self.emit("맵 응답 확인 중")
                    time.sleep(POLL_SECONDS)
                    continue

                active_address, words = active[-1]
                map_hash = words[IDX_MAP_HASH]
                slot = words[IDX_SLOT]

                if not 0 <= slot <= 9:
                    memory.write_u32(active_address + IDX_RESULT * 4, 1)
                    memory.write_u32(active_address + IDX_ERROR * 4, 3)
                    self.emit("요청 거부", f"잘못된 슬롯: {slot}")
                    time.sleep(POLL_SECONDS)
                    continue

                if words[IDX_SAVE_REQ] != words[IDX_SAVE_ACK]:
                    try:
                        total_count = words[IDX_TOTAL_COUNT]
                        chunk_index = words[IDX_CHUNK_INDEX]
                        chunk_count = words[IDX_CHUNK_COUNT]
                        chunk_size = words[IDX_CHUNK_SIZE]
                        if not 1 <= total_count <= 4096:
                            raise ValueError(f"invalid total_count: {total_count}")
                        if not 1 <= chunk_count <= 64 or not 0 <= chunk_index < chunk_count:
                            raise ValueError("invalid chunk metadata")
                        if not 1 <= chunk_size <= MAX_PAYLOAD:
                            raise ValueError(f"invalid chunk_size: {chunk_size}")
                        key = (map_hash, slot)
                        if chunk_index == 0:
                            self.save_transfers[key] = {
                                "total": total_count,
                                "chunks": chunk_count,
                                "payload": [],
                                "next": 0,
                            }
                        transfer = self.save_transfers.get(key)
                        if not transfer or transfer["next"] != chunk_index:
                            raise ValueError("unexpected save chunk order")
                        transfer["payload"].extend(words[IDX_PAYLOAD0:IDX_PAYLOAD0 + chunk_size])
                        transfer["next"] += 1
                        if chunk_index + 1 == chunk_count:
                            payload = transfer["payload"]
                            if len(payload) != total_count:
                                raise ValueError(f"payload length mismatch: {len(payload)} != {total_count}")
                            ENCRYPTED_STORE.save(map_hash, words[IDX_SCHEMA], slot, payload)
                            del self.save_transfers[key]
                            self.emit("저장 완료")
                        else:
                            self.emit("저장 중", f"청크 {chunk_index + 1}/{chunk_count}")
                        memory.write_u32(active_address + IDX_RESULT * 4, 0)
                        memory.write_u32(active_address + IDX_ERROR * 4, 0)
                        memory.write_u32(active_address + IDX_SAVE_ACK * 4, words[IDX_SAVE_REQ])
                    except Exception as error:
                        memory.write_u32(active_address + IDX_RESULT * 4, 1)
                        memory.write_u32(active_address + IDX_ERROR * 4, 1)
                        memory.write_u32(active_address + IDX_SAVE_ACK * 4, words[IDX_SAVE_REQ])
                        self.emit("저장 실패", str(error))

                elif words[IDX_LOAD_REQ] != words[IDX_LOAD_ACK]:
                    try:
                        document = ENCRYPTED_STORE.load(map_hash, slot)
                        if document.get("map_hash") != f"{map_hash:08X}":
                            raise ValueError("map mismatch")
                        if int(document.get("schema", -1)) != words[IDX_SCHEMA]:
                            raise ValueError("schema mismatch")
                        payload = document.get("payload")
                        if not isinstance(payload, list) or not 1 <= len(payload) <= 4096:
                            raise ValueError("invalid payload")
                        expected_total = words[IDX_TOTAL_COUNT]
                        if len(payload) != expected_total:
                            raise ValueError(f"registered value count mismatch: {len(payload)} != {expected_total}")
                        chunk_index = words[IDX_CHUNK_INDEX]
                        chunk_count = (len(payload) + MAX_PAYLOAD - 1) // MAX_PAYLOAD
                        if not 0 <= chunk_index < chunk_count:
                            raise ValueError("invalid requested load chunk")
                        begin = chunk_index * MAX_PAYLOAD
                        part = payload[begin:begin + MAX_PAYLOAD]
                        for index, value in enumerate(part):
                            value = int(value)
                            if not 0 <= value <= 0xFFFFFFFF:
                                raise ValueError(f"payload[{begin + index}] out of DWORD range")
                            memory.write_u32(active_address + (IDX_PAYLOAD0 + index) * 4, value)
                        memory.write_u32(active_address + IDX_PAYLOAD_COUNT * 4, len(part))
                        memory.write_u32(active_address + IDX_TOTAL_COUNT * 4, len(payload))
                        memory.write_u32(active_address + IDX_CHUNK_COUNT * 4, chunk_count)
                        memory.write_u32(active_address + IDX_CHUNK_SIZE * 4, len(part))
                        memory.write_u32(active_address + IDX_RESULT * 4, 0)
                        memory.write_u32(active_address + IDX_ERROR * 4, 0)
                        memory.write_u32(active_address + IDX_LOAD_ACK * 4, words[IDX_LOAD_REQ])
                        if chunk_index + 1 == chunk_count:
                            self.emit("로드 완료")
                        else:
                            self.emit("로드 중", f"청크 {chunk_index + 1}/{chunk_count}")
                    except Exception as error:
                        memory.write_u32(active_address + IDX_RESULT * 4, 1)
                        memory.write_u32(active_address + IDX_ERROR * 4, 2)
                        memory.write_u32(active_address + IDX_LOAD_ACK * 4, words[IDX_LOAD_REQ])
                        self.emit("로드 실패", str(error))

                else:
                    self.emit(
                        "런처 연결됨",
                    )

                time.sleep(POLL_SECONDS)

        finally:
            if memory:
                for address in candidates:
                    try:
                        memory.write_u32(address + IDX_LAUNCHER_STATUS * 4, 0)
                    except OSError:
                        pass
                memory.close()




class WorkerBridge(QWidget):
    update_received = Signal(str, str)


class MainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self):
        super().__init__()
        self.worker_bridge = WorkerBridge()
        self.worker_bridge.update_received.connect(self.handle_worker_update)
        self.worker = Worker(self.worker_bridge.update_received.emit)
        self.worker_started = False
        self.last_connected_detail = ""
        self.last_logged_status = None
        self.log_page = LogPage()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
        )
        
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            False,
        )

        self.setFixedSize(320, 240)

        self.current_state = AppState.STARTING
        self.log_window = LogPage(self)

        container = QFrame()
        container.setObjectName("mainContainer")
        container.setStyleSheet(
            """
            QFrame#mainContainer {
                background-color: #FFFFFF;
                border: 1px solid #12B8A6;
            }
            """
        )

        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = TitleBar()
        self.title_bar.minimize_requested.connect(
            self.showMinimized
        )
        self.title_bar.close_requested.connect(
            self.close
        )

        body = QFrame()
        body.setStyleSheet(
            "background-color: white;"
        )

        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.side_menu = SideMenu()

        # 중앙 페이지 컨테이너
        self.page_stack = QStackedWidget()
        self.page_stack.setStyleSheet(
            """
            QStackedWidget {
                background-color: #ffffff;
                border: none;
            }
            """
        )

        # 0번 페이지: 별 아이콘과 상태 화면
        self.status_widget = StatusWidget()

        # 1번 페이지: 로그 화면
        self.log_page = LogPage()

        self.page_stack.addWidget(
            self.status_widget
        )

        self.page_stack.addWidget(
            self.log_page
        )

        self.page_stack.setCurrentWidget(
            self.status_widget
        )

        body_layout.addWidget(
            self.side_menu
        )

        body_layout.addWidget(
            self.page_stack,
            1,
        )

        root_layout.addWidget(self.title_bar)
        root_layout.addWidget(body, 1)

        self.setCentralWidget(container)

        self.side_menu.notice_clicked.connect(
            self.show_notice
        )
        self.side_menu.homepage_clicked.connect(
            self.show_homepage
        )
        self.side_menu.log_clicked.connect(
            self.show_logs
        )
        self.side_menu.logout_clicked.connect(
            self.logout
        )

        self.return_timer = QTimer(self)
        self.return_timer.setSingleShot(True)
        self.return_timer.timeout.connect(
            self.return_to_connected
        )

        self.demo_timer = QTimer(self)
        self.demo_timer.timeout.connect(
            self.next_demo_state
        )

        self.demo_states = [
            AppState.SERVER_CONNECTING,
            AppState.GAME_WAITING,
            AppState.MAP_WAITING,
            AppState.CONNECTED,
            AppState.SAVING,
            AppState.SAVE_DONE,
            AppState.LOADING,
            AppState.LOAD_DONE,
        ]
        self.demo_index = 0

        self.set_status(
            AppState.SERVER_CONNECTING,
            "UI 프로토타입",
        )

        # 프로토타입 상태 자동 시연
        # 실제 통신 연동 단계에서는 아래 타이머를 제거합니다.
        # Real v0.6 worker replaces the old UI demo timer.
        QTimer.singleShot(100,self.start_worker,)
    def show_status_page(self):
        self.page_stack.setCurrentWidget(
            self.status_widget
    )
    def append_log(
        self,
        message: str,
    ):
        timestamp = (
            __import__("datetime")
            .datetime.now()
            .strftime("%H:%M:%S")
        )

        self.log_page.append_log(
            f"[{timestamp}] {message}"
        )
        write_file_log(message)

    def set_status(
        self,
        state: AppState,
        detail: str = "",
        return_after_ms: int | None = None,
        show_status_page: bool = False,
    ):
        self.current_state = state
        self.status_widget.set_state(state, detail)

        status_text = STATE_TEXT[state]

        if state == AppState.CONNECTED:
            log_key = state
        else:
            log_key = (
                state,
                detail,
            )

        if log_key != self.last_logged_status:
            self.last_logged_status = log_key

            if detail:
                self.append_log(
                    f"{status_text}: {detail}"
                )
            else:
                self.append_log(
                    status_text
                )

        if show_status_page:
            self.show_status_page()

        self.return_timer.stop()

        if return_after_ms is not None:
            self.return_timer.start(
                return_after_ms
            )

    def return_to_connected(self):
        self.set_status(
            AppState.CONNECTED,
            "",
        )

    def start_demo(self):
        self.demo_index = 0
        self.demo_timer.start(2300)

    def next_demo_state(self):
        state = self.demo_states[
            self.demo_index
            % len(self.demo_states)
        ]

        detail = ""

        if state == AppState.SERVER_CONNECTING:
            detail = "HTTPS 서버 연결 시도"
        elif state == AppState.GAME_WAITING:
            detail = "StarCraft.exe"
        elif state == AppState.MAP_WAITING:
            detail = "SCSV0001 검색 중"
        elif state == AppState.CONNECTED:
            detail = "SCSaverTestMap"
        elif state == AppState.SAVING:
            detail = "청크 2 / 4"
        elif state == AppState.SAVE_DONE:
            detail = "슬롯 0"
        elif state == AppState.LOADING:
            detail = "청크 1 / 4"
        elif state == AppState.LOAD_DONE:
            detail = "슬롯 0"

        self.set_status(
            state,
            detail,
        )

        self.demo_index += 1

    def show_notice(self):
        QMessageBox.information(
            self,
            "공지사항",
            "SCSaver 공지사항은 서버 연결 후 표시됩니다.\n"
            "서버 공지사항은 이후 API와 연결됩니다.",
        )

    def show_homepage(self):
        QMessageBox.information(
            self,
            "홈페이지",
            "홈페이지 주소는 서버 구축 후 연결됩니다.",
        )

    def show_logs(self):
        if (
            self.page_stack.currentWidget()
            is self.log_page
        ):
            self.show_status_page()
        else:
            self.page_stack.setCurrentWidget(
                self.log_page
            )

    def logout(self):
        self.demo_timer.stop()

        answer = QMessageBox.question(
            self,
            "로그아웃",
            "로그아웃하시겠습니까?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )

        if answer == QMessageBox.StandardButton.Yes:
            self.stop_worker()
            self.logout_requested.emit()

    def start_worker(self):
        if self.worker_started:
            return
        self.set_status(AppState.SERVER_CONNECTING, "로컬 런처 시작")
        self.worker_started = True
        self.worker.start()

    def stop_worker(self):
        if not self.worker_started:
            return
        self.worker.stop()
        self.worker.join(timeout=2.0)
        self.worker_started = False

    def handle_worker_update(self, state: str, detail: str):
        """Map the tested v0.6 Worker messages to the original UI."""
        if state == "스타크래프트 대기 중":
            self.set_status(AppState.GAME_WAITING, detail)
        elif state in {"맵 응답 확인 중"}:
            self.set_status(AppState.MAP_WAITING, detail)
        elif state == "런처 연결됨":
            # Keep technical connection details in the log only.
            # The main status screen shows a clean connection message.
            self.last_connected_detail = ""
            self.set_status(AppState.CONNECTED, "")
        elif state == "저장 중":
            self.set_status(AppState.SAVING, detail)
        elif state == "저장 완료":
            self.set_status(AppState.SAVE_DONE, detail, return_after_ms=2000, show_status_page=True)
        elif state == "로드 중":
            self.set_status(AppState.LOADING, detail)
        elif state == "로드 완료":
            self.set_status(AppState.LOAD_DONE, detail, return_after_ms=2000, show_status_page=True)
        elif state in {"프로세스 연결 실패", "메모리 검색 오류", "요청 거부", "저장 실패", "로드 실패"}:
            self.set_status(AppState.ERROR, f"{state}: {detail}", show_status_page=True)
        else:
            self.append_log(f"{state}: {detail}" if detail else state)

    def closeEvent(self, event):
        box = QMessageBox(self)
        box.setWindowTitle("SCSaver")
        box.setText("창을 최소화할까요, 프로그램을 종료할까요?")
        minimize_button = box.addButton("최소화", QMessageBox.ButtonRole.AcceptRole)
        quit_button = box.addButton("종료", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(minimize_button)
        box.exec()
        if box.clickedButton() is minimize_button:
            event.ignore(); self.showMinimized()
        elif box.clickedButton() is quit_button:
            self.stop_worker(); event.accept(); QApplication.instance().quit()
        else:
            event.ignore()

    # 이후 v0.6 통신 코드에서 사용할 인터페이스

    def on_game_waiting(self):
        self.set_status(
            AppState.GAME_WAITING,
            "StarCraft.exe",
        )

    def on_map_waiting(self):
        self.set_status(
            AppState.MAP_WAITING,
            "맵 대기 중",
        )

    def on_connected(
        self,
        map_name: str,
    ):
        self.set_status(
            AppState.CONNECTED,
            map_name,
        )

    def on_saving(
        self,
        current_chunk: int,
        total_chunks: int,
    ):
        self.set_status(
            AppState.SAVING,
            f"청크 {current_chunk} / {total_chunks}",
        )

    def on_save_done(
        self,
        slot: int,
    ):
        self.set_status(
            AppState.SAVE_DONE,
            f"슬롯 {slot}",
            return_after_ms=2000,
            show_status_page=True,
        )

    def on_loading(
        self,
        current_chunk: int,
        total_chunks: int,
    ):
        self.set_status(
            AppState.LOADING,
            f"청크 {current_chunk} / {total_chunks}",
        )

    def on_load_done(
        self,
        slot: int,
    ):
        self.set_status(
            AppState.LOAD_DONE,
            f"슬롯 {slot}",
            return_after_ms=2000,
            show_status_page=True,
        )

    def on_error(
        self,
        message: str,
    ):
        self.set_status(
            AppState.ERROR,
            message,
            show_status_page=True,
        )



class LoginWindow(QMainWindow):
    login_succeeded = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setFixedSize(320, 420)
        self.drag_position = None
        self._auto_login_attempt = False
        container=QFrame(); container.setObjectName("loginContainer")
        container.setStyleSheet("QFrame#loginContainer{background:#FFFFFF;border:1px solid #12B8A6;}")
        root=QVBoxLayout(container); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        title=QFrame(); title.setFixedHeight(31); title.setStyleSheet("background:#12B8A6;")
        title.mousePressEvent=self._press; title.mouseMoveEvent=self._move; title.mouseReleaseEvent=self._release
        tl=QHBoxLayout(title); tl.setContentsMargins(7,0,0,0); label=QLabel("SCSaver LOGIN"); label.setStyleSheet("color:#063E38;font:bold 13px 'Malgun Gothic';")
        close=QPushButton("✕"); close.setFixedSize(30,30); close.setStyleSheet("QPushButton{border:none;background:transparent;color:#063E38;font:12px 'Malgun Gothic'; }QPushButton:hover{background:#087F74;color:white;}"); close.clicked.connect(self.close)
        tl.addWidget(label); tl.addStretch(1); tl.addWidget(close); root.addWidget(title)
        body=QWidget(); body.setStyleSheet("background:#333333;"); lay=QVBoxLayout(body); lay.setContentsMargins(42,12,42,18); lay.setSpacing(7)
        logo=QLabel("★"); logo.setAlignment(Qt.AlignmentFlag.AlignCenter); logo.setFixedHeight(100); logo.setStyleSheet("color:#12B8A6;font:93px 'Arial';")
        self.email=QLineEdit(); self.password=QLineEdit(); self.email.setPlaceholderText("저장 ID"); self.password.setPlaceholderText("비밀번호"); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        field="QLineEdit{color:#FFFFFF;background:#333333;border:1px solid #C8DDD9;border-bottom:2px solid #69CFC3;padding:0 12px;font:11px 'Malgun Gothic';}QLineEdit:focus{border:1px solid #12B8A6;border-bottom:2px solid #087F74;}"
        for w in (self.email,self.password): w.setFixedHeight(39); w.setStyleSheet(field)
        self.login=QPushButton("로그인"); self.login.setFixedHeight(34); self.login.setStyleSheet("QPushButton{color:#063E38;background:#12B8A6;border:none;font:12px 'Malgun Gothic';}QPushButton:hover{background:#24CDBA;}QPushButton:disabled{background:#688F8A;color:#BBD0CD;}")
        self.auto=QCheckBox("자동 로그인"); self.auto.setStyleSheet("color:#FFFFFF;font:10px 'Malgun Gothic';")
        self.error=QLabel(""); self.error.setFixedHeight(16); self.error.setAlignment(Qt.AlignmentFlag.AlignCenter); self.error.setStyleSheet("color:#D64545;font:9px 'Malgun Gothic';")
        signup=self._outline("회원가입"); helpb=self._outline("로그인 문제 해결")
        for w in (logo,self.email,self.password,self.login,self.auto,self.error,signup,helpb): lay.addWidget(w)
        lay.addStretch(1); root.addWidget(body,1); self.setCentralWidget(container)
        self.login.clicked.connect(self.try_login); self.email.returnPressed.connect(self.try_login); self.password.returnPressed.connect(self.try_login)
        signup.clicked.connect(lambda: QMessageBox.information(self,"회원가입","서버 구축 후 연결됩니다.")); helpb.clicked.connect(lambda: QMessageBox.information(self,"로그인 문제 해결","서버 구축 후 연결됩니다."))
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.finish_login)
        QTimer.singleShot(100, self.try_auto_login)

    def _outline(self,text):
        b=QPushButton(text); b.setFixedHeight(27); b.setStyleSheet("QPushButton{color:#087F74;background:#333333;border:1px solid #12B8A6;font:10px 'Malgun Gothic';}QPushButton:hover{color:white;background:#12B8A6;}"); return b
    def _press(self,e):
        if e.button()==Qt.MouseButton.LeftButton: self.drag_position=e.globalPosition().toPoint()-self.frameGeometry().topLeft()
    def _move(self,e):
        if self.drag_position is not None and e.buttons() & Qt.MouseButton.LeftButton: self.move(e.globalPosition().toPoint()-self.drag_position)
    def _release(self,e): self.drag_position=None
    def try_auto_login(self):
        credentials = AUTO_LOGIN_STORE.load()
        if credentials is None:
            write_file_log("Automatic login credentials not found")
            return
        write_file_log("Automatic login credentials loaded")
        self._auto_login_attempt = True
        self._email, self._password = credentials
        self.email.setText(self._email)
        self.password.setText(self._password)
        self.auto.setChecked(True)
        self.error.clear()
        self.login.setEnabled(False)
        self.login.setText("자동 로그인 중...")
        self.timer.start(50)

    def try_login(self):
        if not self.email.text().strip() or not self.password.text():
            self.error.setText("저장 ID와 비밀번호를 입력하세요.")
            return
        self._auto_login_attempt = False
        self._email=self.email.text().strip()
        self._password=self.password.text()
        self.error.clear()
        self.login.setEnabled(False)
        self.login.setText("로그인 중...")
        self.timer.start(650)

    def finish_login(self):
        self.login.setEnabled(True)
        self.login.setText("로그인")
        try:
            ENCRYPTED_STORE.configure(self._email,self._password)
            if self.auto.isChecked():
                AUTO_LOGIN_STORE.save(self._email,self._password)
            else:
                AUTO_LOGIN_STORE.clear()
            write_file_log("Login succeeded")
            self._auto_login_attempt = False
            self.login_succeeded.emit()
        except Exception as error:
            write_file_log(f"Login failed: {error}", logging.ERROR)
            if self._auto_login_attempt:
                AUTO_LOGIN_STORE.clear()
                self.auto.setChecked(False)
                self.password.clear()
                self.error.setText("자동 로그인에 실패했습니다. 다시 로그인하세요.")
            else:
                self.error.setText(str(error))
            self._auto_login_attempt = False

    def reset(self, clear_auto_login=True):
        ENCRYPTED_STORE.clear_credentials()
        if clear_auto_login:
            AUTO_LOGIN_STORE.clear()
            self.auto.setChecked(False)
        self.password.clear()
        self.error.clear()

    def closeEvent(self, event):
        box = QMessageBox(self)
        box.setWindowTitle("SCSaver")
        box.setText("창을 최소화할까요, 프로그램을 종료할까요?")
        minimize_button = box.addButton("최소화", QMessageBox.ButtonRole.AcceptRole)
        quit_button = box.addButton("종료", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(minimize_button)
        box.exec()
        if box.clickedButton() is minimize_button:
            event.ignore(); self.showMinimized()
        elif box.clickedButton() is quit_button:
            event.accept()
        else:
            event.ignore()


class ApplicationController:
    def __init__(self):
        self.login=LoginWindow(); self.main=None; self.login.login_succeeded.connect(self.open_main)
    def start(self): self.login.show()
    def open_main(self):
        self.login.hide()
        if self.main is None:
            self.main=MainWindow(); self.main.logout_requested.connect(self.open_login)
        elif not self.main.worker_started:
            self.main.worker=Worker(self.main.worker_bridge.update_received.emit); self.main.start_worker()
        self.main.show(); self.main.raise_(); self.main.activateWindow()
    def open_login(self):
        if self.main is not None: self.main.hide()
        self.login.reset(); self.login.show(); self.login.raise_(); self.login.activateWindow()


class SCSaverApplication(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.controller: ApplicationController | None = None
        self.instance_lock = None

def main():
    setup_file_logging()
    sys.excepthook = log_uncaught_exception
    write_file_log("Creating QApplication")

    app = SCSaverApplication(sys.argv)
    app.aboutToQuit.connect(finalize_file_logging)

    lock_path = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.TempLocation
    )) / "SCSaver_v010.lock"
    app.instance_lock = QLockFile(str(lock_path))
    app.instance_lock.setStaleLockTime(0)
    if not app.instance_lock.tryLock(100):
        write_file_log("Second instance rejected", logging.WARNING)
        QMessageBox.information(None, "SCSaver", "SCSaver가 이미 실행 중입니다.")
        finalize_file_logging()
        return

    app.setStyle("Fusion")
    app.setFont(
        QFont("Malgun Gothic", 10)
    )

    app.controller = ApplicationController()
    app.controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()