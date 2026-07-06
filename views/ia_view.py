# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""IAView — vista standalone para configurar Inteligencia Artificial.

Extraída de `ConfiguracionView` porque la configuración de IA es lo
suficientemente amplia (6 proveedores, claves, modelos, conexión) como para
merecer su propia entrada en el sidebar y la toolbar de proyecto.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QFormLayout,
    QLineEdit, QButtonGroup, QRadioButton, QStackedWidget,
    QScrollArea, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

from core.database import get_config, set_config
from utils.theme import BTN_PRIMARY_SS


SLATE_700  = "#273445"
SLATE_500  = "#485A6C"
SLATE_300  = "#667885"
SILVER_100 = "#F8F9FA"
SILVER_300 = "#D4D4D4"
ORANGE     = "#F37329"
ORANGE_DRK = "#C0621A"
GREEN      = "#68B723"
RED        = "#C6262E"

_CARD_SS = "QFrame#iaCard { background:white; border-radius:10px; border:none; }"
_SEC_SS  = (
    f"color:{SLATE_700}; font-size:13px; font-weight:700; "
    f"background:transparent; border:none;"
)
_NOTE_SS = (
    f"color:{SLATE_300}; font-size:11px; "
    f"background:transparent; border:none;"
)
_BTN_SAVE = BTN_PRIMARY_SS  # alias retro-compatible

# Cada proveedor recuerda su propia clave en un campo de config aparte.
# `api_key` (sin sufijo) sigue siendo la clave del proveedor ACTIVO — es la que
# lee el runtime (~20 sitios). Ollama no usa clave.
_API_KEY_CFG = {
    'groq':       'api_key_groq',
    'anthropic':  'api_key_anthropic',
    'openai':     'api_key_openai',
    'gemini':     'api_key_gemini',
    'openrouter': 'api_key_openrouter',
}


# ── Worker para obtener modelos de OpenRouter ─────────────────────────────

class _WorkerModelos(QThread):
    terminado = Signal(list, str)   # (lista_modelos, error)

    def __init__(self, api_key: str = ''):
        super().__init__()
        self.api_key = api_key

    def run(self):
        import json, urllib.request, urllib.error
        try:
            req = urllib.request.Request(
                'https://openrouter.ai/api/v1/models',
                headers={
                    'Authorization': f'Bearer {self.api_key}' if self.api_key else '',
                    'User-Agent': 'ingePresupuestos/1.0',
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            modelos = []
            for m in data.get('data', []):
                mid  = m.get('id', '')
                name = m.get('name', mid)
                if not mid:
                    continue
                arch = m.get('architecture', {}).get('modality', '') or ''
                if arch and 'text' not in arch:
                    continue
                price_in  = float(m.get('pricing', {}).get('prompt',     '0') or 0)
                price_out = float(m.get('pricing', {}).get('completion',  '0') or 0)
                es_gratis = (price_in == 0 and price_out == 0)
                modelos.append((mid, name, es_gratis, price_in, price_out))

            modelos.sort(key=lambda x: (not x[2], x[1].lower()))
            self.terminado.emit(modelos, '')
        except urllib.error.URLError as e:
            self.terminado.emit([], f'Sin conexión: {e.reason}')
        except Exception as e:
            self.terminado.emit([], str(e))


# ── Worker para probar conexión IA ────────────────────────────────────────

class _WorkerProbar(QThread):
    terminado = Signal(bool, str, str)   # (ok, mensaje, proveedor_nombre)

    def __init__(self, ia_proveedor, api_key, ollama_url, ollama_modelo,
                 openai_modelo='', gemini_modelo='', openrouter_modelo=''):
        super().__init__()
        self.ia_proveedor      = ia_proveedor
        self.api_key           = api_key
        self.ollama_url        = ollama_url
        self.ollama_modelo     = ollama_modelo
        self.openai_modelo     = openai_modelo
        self.gemini_modelo     = gemini_modelo
        self.openrouter_modelo = openrouter_modelo

    def run(self):
        try:
            set_config('ia_proveedor',    self.ia_proveedor)
            set_config('api_key',         self.api_key)
            # Recordar la clave de ESTE proveedor (persistencia por proveedor).
            if self.ia_proveedor in _API_KEY_CFG:
                set_config(_API_KEY_CFG[self.ia_proveedor], self.api_key)
            set_config('ollama_url',      self.ollama_url)
            set_config('ollama_modelo',   self.ollama_modelo)
            set_config('openai_modelo',   self.openai_modelo)
            set_config('gemini_modelo',   self.gemini_modelo)
            set_config('openrouter_modelo', self.openrouter_modelo)
            from core.ai_specs import probar_conexion
            ok, msg, prov = probar_conexion(self.api_key, self.ia_proveedor)
            self.terminado.emit(ok, msg, prov)
        except Exception as e:
            self.terminado.emit(False, str(e), '')


class IAView(QWidget):
    """Configuración de Inteligencia Artificial — vista standalone."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("vista_nombre", "ia")
        self.setStyleSheet(f"background:{SILVER_100};")
        self._worker = None
        self._build_ui()
        self._cargar_ia()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{SILVER_100};")

        inner = QWidget()
        inner.setStyleSheet(f"background:{SILVER_100};")
        root = QVBoxLayout(inner)
        root.setContentsMargins(32, 24, 32, 32)
        root.setSpacing(20)

        lbl_t = QLabel("IA / API Key")
        lbl_t.setStyleSheet(
            f"color:{SLATE_700}; font-size:18px; font-weight:700; "
            f"background:transparent; border:none;"
        )
        root.addWidget(lbl_t)

        root.addWidget(self._card_ia())
        root.addStretch()
        # Referenciamos el root layout para que callers externos puedan
        # extender la vista con cards adicionales vía `agregar_seccion()`.
        self._root_layout = root

        scroll.setWidget(inner)
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addWidget(scroll)

    def agregar_seccion(self, widget: QWidget) -> None:
        """Inserta un widget al final del scroll de Configuración IA (antes
        del stretch). Usado para anexar cards relacionadas con IA que viven
        en otros archivos (e.g. Asistente Tuxia desde ConfiguracionView)."""
        if not hasattr(self, '_root_layout'):
            return
        # Insertar antes del último item (que es el addStretch).
        self._root_layout.insertWidget(
            self._root_layout.count() - 1, widget
        )

    # ── Card IA ───────────────────────────────────────────────────────────

    def _card_ia(self) -> QFrame:
        from utils.theme import apply_shadow
        card = QFrame()
        card.setObjectName("iaCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        apply_shadow(card, 'sm')
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel("Proveedor de IA")
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            "Selecciona el proveedor de IA para generar especificaciones "
            "técnicas, rendimientos y usar el Asistente de ACU."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        # ── Selector de proveedor ─────────────────────────────────────
        grid_radio = QGridLayout()
        grid_radio.setHorizontalSpacing(20)
        grid_radio.setVerticalSpacing(6)
        self._bg_prov = QButtonGroup(self)

        self.rb_groq        = QRadioButton("Groq  (gratuito)")
        self.rb_openrouter  = QRadioButton("OpenRouter  (gratuito)")
        self.rb_gemini      = QRadioButton("Google Gemini")
        self.rb_openai      = QRadioButton("OpenAI  (GPT-4o)")
        self.rb_anthropic   = QRadioButton("Anthropic Claude")
        self.rb_ollama      = QRadioButton("Ollama  (local, sin internet)")

        _RB_SS = "font-size:12px; background:transparent; border:none;"
        for rb in (self.rb_groq, self.rb_openrouter, self.rb_gemini,
                   self.rb_openai, self.rb_anthropic, self.rb_ollama):
            rb.setStyleSheet(_RB_SS)
            self._bg_prov.addButton(rb)

        grid_radio.addWidget(self.rb_groq,       0, 0)
        grid_radio.addWidget(self.rb_openrouter, 0, 1)
        grid_radio.addWidget(self.rb_gemini,     1, 0)
        grid_radio.addWidget(self.rb_openai,     1, 1)
        grid_radio.addWidget(self.rb_anthropic,  2, 0)
        grid_radio.addWidget(self.rb_ollama,     2, 1)
        vl.addLayout(grid_radio)

        # ── Stack de paneles ──────────────────────────────────────────
        self.stack_ia = QStackedWidget()
        self.stack_ia.addWidget(self._panel_groq())        # 0
        self.stack_ia.addWidget(self._panel_anthropic())   # 1
        self.stack_ia.addWidget(self._panel_ollama())      # 2
        self.stack_ia.addWidget(self._panel_openai())      # 3
        self.stack_ia.addWidget(self._panel_gemini())      # 4
        self.stack_ia.addWidget(self._panel_openrouter())  # 5
        vl.addWidget(self.stack_ia)

        self.rb_groq.toggled.connect(lambda on:       on and self.stack_ia.setCurrentIndex(0))
        self.rb_anthropic.toggled.connect(lambda on:  on and self.stack_ia.setCurrentIndex(1))
        self.rb_ollama.toggled.connect(lambda on:     on and self.stack_ia.setCurrentIndex(2))
        self.rb_openai.toggled.connect(lambda on:     on and self.stack_ia.setCurrentIndex(3))
        self.rb_gemini.toggled.connect(lambda on:     on and self.stack_ia.setCurrentIndex(4))
        self.rb_openrouter.toggled.connect(lambda on: on and self.stack_ia.setCurrentIndex(5))
        self.rb_groq.setChecked(True)

        # ── Botones ───────────────────────────────────────────────────
        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep2)

        hl_btns = QHBoxLayout()
        hl_btns.setSpacing(8)

        self.btn_probar = QPushButton("Probar conexión")
        self.btn_probar.setFixedHeight(34)
        self.btn_probar.setStyleSheet(
            f"QPushButton {{ background:#F0F2F5; color:{SLATE_700}; border:1px solid {SILVER_300};"
            f" border-radius:6px; padding:0 18px; font-size:12px; }}"
            f"QPushButton:hover {{ background:#E8EAED; }}"
        )
        self.btn_probar.clicked.connect(self._probar_ia)
        hl_btns.addWidget(self.btn_probar)

        self.lbl_ia_estado = QLabel("")
        self.lbl_ia_estado.setWordWrap(True)
        self.lbl_ia_estado.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_ia_estado.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.lbl_ia_estado.setStyleSheet(
            f"font-size:11px; color:{SLATE_300}; "
            f"background:transparent; border:none;"
        )
        hl_btns.addWidget(self.lbl_ia_estado)

        hl_btns.addStretch()
        btn_ia_ok = QPushButton("Guardar")
        btn_ia_ok.setFixedHeight(34)
        btn_ia_ok.setStyleSheet(_BTN_SAVE)
        btn_ia_ok.clicked.connect(self._guardar_ia)
        hl_btns.addWidget(btn_ia_ok)
        vl.addLayout(hl_btns)

        return card

    # ── Helper: botón mostrar/ocultar clave ──────────────────────────────

    def _btn_ojo(self, inp: QLineEdit) -> QPushButton:
        btn = QPushButton("👁")
        btn.setFixedSize(34, 34)
        btn.setCheckable(True)
        btn.setToolTip("Mostrar / ocultar clave")
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background:white; color:{SLATE_300};"
            f"  border:1px solid {SILVER_300}; border-radius:6px;"
            f"  font-size:15px; padding:0;"
            f"}}"
            f"QPushButton:hover {{ background:{SILVER_100}; color:{SLATE_700}; }}"
            f"QPushButton:checked {{ background:{SILVER_100}; color:{ORANGE}; border-color:{ORANGE}; }}"
        )
        btn.toggled.connect(
            lambda on: inp.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        return btn

    def _panel_groq(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 4, 0, 0)
        vl.setSpacing(8)

        nota = QLabel(
            "Groq ofrece LLaMA 3.3 70B de forma gratuita con límite de tokens/minuto.<br>"
            "Obtén tu clave en  <a href='https://console.groq.com/keys'>console.groq.com/keys</a>"
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        nota.setOpenExternalLinks(True)
        vl.addWidget(nota)

        hl = QHBoxLayout()
        self.inp_groq = QLineEdit()
        self.inp_groq.setEchoMode(QLineEdit.Password)
        self.inp_groq.setPlaceholderText("gsk_xxxxxxxxxxxxxxxxxxxx")
        self.inp_groq.setFixedHeight(34)
        self.inp_groq.setStyleSheet(
            f"QLineEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:12px; }}"
        )
        hl.addWidget(self.inp_groq)
        hl.addWidget(self._btn_ojo(self.inp_groq))
        vl.addLayout(hl)
        return w

    def _panel_anthropic(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 4, 0, 0)
        vl.setSpacing(8)

        nota = QLabel(
            "Anthropic Claude Haiku: rápido y económico para specs técnicas.<br>"
            "Obtén tu clave en  <a href='https://console.anthropic.com/settings/keys'>console.anthropic.com/settings/keys</a>"
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        nota.setOpenExternalLinks(True)
        vl.addWidget(nota)

        hl = QHBoxLayout()
        self.inp_anthropic = QLineEdit()
        self.inp_anthropic.setEchoMode(QLineEdit.Password)
        self.inp_anthropic.setPlaceholderText("sk-ant-xxxxxxxxxxxxxxxxxxxx")
        self.inp_anthropic.setFixedHeight(34)
        self.inp_anthropic.setStyleSheet(
            f"QLineEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:12px; }}"
        )
        hl.addWidget(self.inp_anthropic)
        hl.addWidget(self._btn_ojo(self.inp_anthropic))
        vl.addLayout(hl)
        return w

    def _panel_openai(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 4, 0, 0)
        vl.setSpacing(8)

        nota = QLabel(
            "GPT-4o-mini: muy buena calidad a bajo costo (~$0.15/millón de tokens).<br>"
            "GPT-4o: máxima calidad, más caro. Obtén tu clave en  "
            "<a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a>"
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        nota.setOpenExternalLinks(True)
        vl.addWidget(nota)

        hl = QHBoxLayout()
        self.inp_openai = QLineEdit()
        self.inp_openai.setEchoMode(QLineEdit.Password)
        self.inp_openai.setPlaceholderText("sk-xxxxxxxxxxxxxxxxxxxx")
        self.inp_openai.setFixedHeight(34)
        self.inp_openai.setStyleSheet(
            f"QLineEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:12px; }}"
        )
        hl.addWidget(self.inp_openai)
        hl.addWidget(self._btn_ojo(self.inp_openai))
        vl.addLayout(hl)

        form = QFormLayout()
        form.setSpacing(6)
        self.inp_openai_modelo = QLineEdit()
        self.inp_openai_modelo.setPlaceholderText("gpt-4o-mini")
        self.inp_openai_modelo.setFixedHeight(32)
        self.inp_openai_modelo.setStyleSheet(
            f"QLineEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:11px; }}"
        )
        form.addRow("Modelo:", self.inp_openai_modelo)
        vl.addLayout(form)

        modelos_nota = QLabel("Modelos: gpt-4o-mini (recomendado) · gpt-4o · gpt-4-turbo")
        modelos_nota.setStyleSheet(
            f"font-size:10px; color:{SLATE_300}; "
            f"background:transparent; border:none;"
        )
        vl.addWidget(modelos_nota)
        return w

    def _panel_gemini(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 4, 0, 0)
        vl.setSpacing(8)

        nota = QLabel(
            "Google Gemini 2.5 Flash es gratuito con límites generosos.<br>"
            "Obtén tu clave en  <a href='https://aistudio.google.com/app/apikey'>aistudio.google.com/app/apikey</a>"
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        nota.setOpenExternalLinks(True)
        vl.addWidget(nota)

        hl = QHBoxLayout()
        self.inp_gemini = QLineEdit()
        self.inp_gemini.setEchoMode(QLineEdit.Password)
        self.inp_gemini.setPlaceholderText("AIzaxxxxxxxxxxxxxxxxxxxx")
        self.inp_gemini.setFixedHeight(34)
        self.inp_gemini.setStyleSheet(
            f"QLineEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:12px; }}"
        )
        hl.addWidget(self.inp_gemini)
        hl.addWidget(self._btn_ojo(self.inp_gemini))
        vl.addLayout(hl)

        form = QFormLayout()
        form.setSpacing(6)
        self.inp_gemini_modelo = QLineEdit()
        self.inp_gemini_modelo.setPlaceholderText("gemini-2.5-flash")
        self.inp_gemini_modelo.setFixedHeight(32)
        self.inp_gemini_modelo.setStyleSheet(
            f"QLineEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:11px; }}"
        )
        form.addRow("Modelo:", self.inp_gemini_modelo)
        vl.addLayout(form)

        modelos_nota = QLabel(
            "Modelos: gemini-2.5-flash (recomendado, gratis) · gemini-2.5-pro · gemini-2.0-flash"
        )
        modelos_nota.setStyleSheet(
            f"font-size:10px; color:{SLATE_300}; "
            f"background:transparent; border:none;"
        )
        vl.addWidget(modelos_nota)
        return w

    def _panel_openrouter(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 4, 0, 0)
        vl.setSpacing(8)

        nota = QLabel(
            "OpenRouter da acceso a decenas de modelos con una sola clave, incluyendo modelos gratuitos.<br>"
            "Obtén tu clave en  <a href='https://openrouter.ai/keys'>openrouter.ai/keys</a>"
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        nota.setOpenExternalLinks(True)
        vl.addWidget(nota)

        hl = QHBoxLayout()
        self.inp_openrouter = QLineEdit()
        self.inp_openrouter.setEchoMode(QLineEdit.Password)
        self.inp_openrouter.setPlaceholderText("sk-or-v1-xxxxxxxxxxxxxxxxxxxx")
        self.inp_openrouter.setFixedHeight(34)
        self.inp_openrouter.setStyleSheet(
            f"QLineEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:12px; }}"
        )
        hl.addWidget(self.inp_openrouter)
        hl.addWidget(self._btn_ojo(self.inp_openrouter))
        vl.addLayout(hl)

        _OR_MODELOS = [
            ("google/gemini-2.0-flash-exp:free",           "⭐ Gemini 2.0 Flash  [gratis]"),
            ("google/gemini-2.5-pro-exp-03-25:free",       "⭐ Gemini 2.5 Pro  [gratis]"),
            ("deepseek/deepseek-chat:free",                "⭐ DeepSeek V3  [gratis]"),
            ("deepseek/deepseek-r1:free",                  "DeepSeek R1  [gratis]"),
            ("meta-llama/llama-3.3-70b-instruct:free",     "LLaMA 3.3 70B  [gratis]"),
            ("meta-llama/llama-4-maverick:free",           "LLaMA 4 Maverick  [gratis]"),
            ("mistralai/mistral-7b-instruct:free",         "Mistral 7B  [gratis]"),
            ("microsoft/phi-4:free",                       "Microsoft Phi-4  [gratis]"),
            ("google/gemini-2.0-flash-001",                "Gemini 2.0 Flash  [pago]"),
            ("openai/gpt-4o-mini",                         "GPT-4o Mini  [pago]"),
            ("anthropic/claude-3-haiku",                   "Claude 3 Haiku  [pago]"),
        ]

        # Popup styling cubierto por `install_global_popup_styles(app)`.
        _COMBO_SS = (
            f"QComboBox {{"
            f"  border:1px solid {SILVER_300}; border-radius:6px;"
            f"  padding:0 10px; font-size:11px; background:white;"
            f"}}"
            f"QComboBox::drop-down {{"
            f"  subcontrol-origin:padding; subcontrol-position:top right;"
            f"  width:26px; border-left:1px solid {SILVER_300};"
            f"  border-top-right-radius:6px; border-bottom-right-radius:6px;"
            f"  background:{SILVER_100};"
            f"}}"
        )

        hl_lbl = QHBoxLayout()
        lbl_mod = QLabel("Modelo:")
        lbl_mod.setStyleSheet(
            f"font-size:11px; color:{SLATE_500}; "
            f"background:transparent; border:none;"
        )
        hl_lbl.addWidget(lbl_mod)
        hl_lbl.addStretch()
        self.btn_or_refresh = QPushButton("↺  Actualizar lista")
        self.btn_or_refresh.setFixedHeight(24)
        self.btn_or_refresh.setStyleSheet(
            f"QPushButton {{ background:{SILVER_100}; color:{SLATE_500};"
            f" border:1px solid {SILVER_300}; border-radius:4px;"
            f" padding:0 10px; font-size:10px; }}"
            f"QPushButton:hover {{ background:#E8EAED; color:{SLATE_700}; }}"
            f"QPushButton:disabled {{ color:#AAAAAA; }}"
        )
        self.btn_or_refresh.clicked.connect(self._actualizar_modelos_or)
        hl_lbl.addWidget(self.btn_or_refresh)
        vl.addLayout(hl_lbl)

        self.inp_openrouter_modelo = QComboBox()
        self.inp_openrouter_modelo.setEditable(True)
        self.inp_openrouter_modelo.setFixedHeight(34)
        self.inp_openrouter_modelo.setStyleSheet(_COMBO_SS)
        for valor, etiqueta in _OR_MODELOS:
            self.inp_openrouter_modelo.addItem(etiqueta, userData=valor)
        vl.addWidget(self.inp_openrouter_modelo)

        self.lbl_or_modelos = QLabel("")
        self.lbl_or_modelos.setStyleSheet(
            f"font-size:10px; color:{SLATE_300}; "
            f"background:transparent; border:none;"
        )
        vl.addWidget(self.lbl_or_modelos)

        modelos_nota = QLabel(
            "También puede escribir cualquier modelo de "
            "<a href='https://openrouter.ai/models?q=free'>openrouter.ai/models</a>"
        )
        modelos_nota.setWordWrap(True)
        modelos_nota.setStyleSheet(
            f"font-size:10px; color:{SLATE_300}; "
            f"background:transparent; border:none;"
        )
        modelos_nota.setOpenExternalLinks(True)
        vl.addWidget(modelos_nota)
        return w

    def _panel_ollama(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 4, 0, 0)
        vl.setSpacing(8)

        nota = QLabel(
            "Ollama ejecuta modelos de IA localmente, sin internet ni costo.<br>"
            "Instala Ollama desde  <a href='https://ollama.com'>ollama.com</a>"
            "  y descarga un modelo (ej: <code>ollama pull llama3.2</code>)."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        nota.setOpenExternalLinks(True)
        vl.addWidget(nota)

        form = QFormLayout()
        form.setSpacing(8)

        self.inp_ollama_url = QLineEdit()
        self.inp_ollama_url.setPlaceholderText("http://localhost:11434")
        self.inp_ollama_url.setFixedHeight(34)
        self.inp_ollama_url.setStyleSheet(
            f"QLineEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:12px; }}"
        )
        form.addRow("URL del servidor:", self.inp_ollama_url)

        self.inp_ollama_modelo = QLineEdit()
        self.inp_ollama_modelo.setPlaceholderText("llama3.2")
        self.inp_ollama_modelo.setFixedHeight(34)
        self.inp_ollama_modelo.setStyleSheet(
            f"QLineEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:12px; }}"
        )
        form.addRow("Modelo:", self.inp_ollama_modelo)
        vl.addLayout(form)

        modelos_nota = QLabel(
            "Modelos recomendados: llama3.2 · mistral · phi3 · gemma3\n"
            "Para specs técnicas se recomienda un modelo de 7B parámetros o mayor."
        )
        modelos_nota.setWordWrap(True)
        modelos_nota.setStyleSheet(
            f"font-size:10px; color:{SLATE_300}; "
            f"background:transparent; border:none;"
        )
        vl.addWidget(modelos_nota)
        return w

    # ── Cargar valores desde DB ───────────────────────────────────────────

    def _cargar_ia(self):
        ia_proveedor   = get_config('ia_proveedor',   '')
        api_key        = get_config('api_key',         '')
        ollama_url     = get_config('ollama_url',      'http://localhost:11434')
        ollama_modelo  = get_config('ollama_modelo',   'llama3.2')
        openai_modelo      = get_config('openai_modelo',      'gpt-4o-mini')
        gemini_modelo      = get_config('gemini_modelo',      'gemini-2.0-flash')
        openrouter_modelo  = get_config('openrouter_modelo',  'meta-llama/llama-3.3-70b-instruct:free')

        self.inp_ollama_url.setText(ollama_url)
        self.inp_ollama_modelo.setText(ollama_modelo)
        self.inp_openai_modelo.setText(openai_modelo)
        self.inp_gemini_modelo.setText(gemini_modelo)
        idx = self.inp_openrouter_modelo.findData(openrouter_modelo)
        if idx >= 0:
            self.inp_openrouter_modelo.setCurrentIndex(idx)
        else:
            self.inp_openrouter_modelo.setCurrentText(openrouter_modelo)

        # Cargar la clave GUARDADA de CADA proveedor en su propio campo, para
        # poder cambiar de proveedor sin volver a escribirla.
        inputs = {
            'groq':       self.inp_groq,
            'anthropic':  self.inp_anthropic,
            'openai':     self.inp_openai,
            'gemini':     self.inp_gemini,
            'openrouter': self.inp_openrouter,
        }
        for prov, inp in inputs.items():
            k = get_config(_API_KEY_CFG[prov], '')
            # Migración del esquema viejo (una sola `api_key`): si este proveedor
            # no tiene clave propia pero era el activo, sembrarla con la legacy.
            if not k and api_key and prov == ia_proveedor:
                k = api_key
            inp.setText(k)

        # Seleccionar el radio del proveedor activo.
        _RBS = {
            'groq': self.rb_groq, 'anthropic': self.rb_anthropic,
            'openai': self.rb_openai, 'gemini': self.rb_gemini,
            'openrouter': self.rb_openrouter, 'ollama': self.rb_ollama,
        }
        if ia_proveedor in _RBS:
            _RBS[ia_proveedor].setChecked(True)
        elif api_key:
            # Sin proveedor guardado: adivinar por el prefijo de la legacy key.
            if   api_key.startswith('gsk_'):     self.rb_groq.setChecked(True);       self.inp_groq.setText(api_key)
            elif api_key.startswith('sk-ant-'):  self.rb_anthropic.setChecked(True);  self.inp_anthropic.setText(api_key)
            elif api_key.startswith('AIza'):     self.rb_gemini.setChecked(True);     self.inp_gemini.setText(api_key)
            elif api_key.startswith('sk-or-'):   self.rb_openrouter.setChecked(True); self.inp_openrouter.setText(api_key)
            elif api_key.startswith('sk-'):      self.rb_openai.setChecked(True);     self.inp_openai.setText(api_key)
            else:                                self.rb_groq.setChecked(True)
        else:
            self.rb_groq.setChecked(True)

    # ── Guardar / probar ──────────────────────────────────────────────────

    def _proveedor_seleccionado(self) -> str:
        if self.rb_groq.isChecked():       return 'groq'
        if self.rb_anthropic.isChecked():  return 'anthropic'
        if self.rb_openai.isChecked():     return 'openai'
        if self.rb_gemini.isChecked():     return 'gemini'
        if self.rb_openrouter.isChecked(): return 'openrouter'
        return 'ollama'

    def _api_key_actual(self) -> str:
        prov = self._proveedor_seleccionado()
        if prov == 'groq':       return self.inp_groq.text().strip()
        if prov == 'anthropic':  return self.inp_anthropic.text().strip()
        if prov == 'openai':     return self.inp_openai.text().strip()
        if prov == 'gemini':     return self.inp_gemini.text().strip()
        if prov == 'openrouter': return self.inp_openrouter.text().strip()
        return ''

    def _probar_ia(self):
        self.btn_probar.setEnabled(False)
        self.lbl_ia_estado.setStyleSheet(
            f"font-size:11px; color:{SLATE_300}; "
            f"background:transparent; border:none;"
        )
        self.lbl_ia_estado.setText("Probando conexión…")

        prov    = self._proveedor_seleccionado()
        api_key = self._api_key_actual()

        self._worker = _WorkerProbar(
            ia_proveedor     = prov,
            api_key          = api_key,
            ollama_url       = self.inp_ollama_url.text().strip()    or 'http://localhost:11434',
            ollama_modelo    = self.inp_ollama_modelo.text().strip()  or 'llama3.2',
            openai_modelo    = self.inp_openai_modelo.text().strip()  or 'gpt-4o-mini',
            gemini_modelo    = self.inp_gemini_modelo.text().strip()  or 'gemini-2.0-flash',
            openrouter_modelo= self._openrouter_modelo_id(),
        )
        self._worker.terminado.connect(self._on_probar_terminado)
        self._worker.start()

    def _on_probar_terminado(self, ok: bool, msg: str, prov: str):
        self.btn_probar.setEnabled(True)
        color = GREEN if ok else RED
        prefix = "✓" if ok else "✗"
        self.lbl_ia_estado.setStyleSheet(
            f"font-size:11px; color:{color}; "
            f"background:transparent; border:none;"
        )
        self.lbl_ia_estado.setText(f"{prefix}  {msg}")

    def _actualizar_modelos_or(self):
        self.btn_or_refresh.setEnabled(False)
        self.btn_or_refresh.setText("↺  Cargando…")
        self.lbl_or_modelos.setText("Consultando openrouter.ai…")
        api_key = self.inp_openrouter.text().strip()
        self._worker_modelos = _WorkerModelos(api_key)
        self._worker_modelos.terminado.connect(self._on_modelos_or)
        self._worker_modelos.start()

    def _on_modelos_or(self, modelos: list, error: str):
        self.btn_or_refresh.setEnabled(True)
        self.btn_or_refresh.setText("↺  Actualizar lista")
        if error:
            self.lbl_or_modelos.setStyleSheet(
                f"font-size:10px; color:{RED}; "
                f"background:transparent; border:none;"
            )
            self.lbl_or_modelos.setText(f"Error: {error}")
            return

        modelo_actual = self._openrouter_modelo_id()
        self.inp_openrouter_modelo.clear()

        n_gratis = 0
        for mid, name, es_gratis, price_in, price_out in modelos:
            if es_gratis:
                etiqueta = f"⭐ {name}  [gratis]"
                n_gratis += 1
            else:
                costo = price_in * 1_000_000
                etiqueta = f"{name}  [${costo:.2f}/M tokens]"
            self.inp_openrouter_modelo.addItem(etiqueta, userData=mid)

        idx = self.inp_openrouter_modelo.findData(modelo_actual)
        if idx >= 0:
            self.inp_openrouter_modelo.setCurrentIndex(idx)
        else:
            self.inp_openrouter_modelo.setCurrentText(modelo_actual)

        n_total = len(modelos)
        self.lbl_or_modelos.setStyleSheet(
            f"font-size:10px; color:{GREEN}; "
            f"background:transparent; border:none;"
        )
        self.lbl_or_modelos.setText(
            f"✓  {n_total} modelos cargados  ·  {n_gratis} gratuitos"
        )

    def _openrouter_modelo_id(self) -> str:
        data = self.inp_openrouter_modelo.currentData()
        if data:
            return data
        return self.inp_openrouter_modelo.currentText().strip() or 'google/gemini-2.0-flash-exp:free'

    def _guardar_ia(self):
        prov    = self._proveedor_seleccionado()
        api_key = self._api_key_actual()

        # Guardar la clave de CADA proveedor en su propio campo → persisten
        # aunque cambies de proveedor (si se acaban los tokens de Groq, cambias
        # a Gemini y su clave ya quedó guardada).
        set_config('api_key_groq',       self.inp_groq.text().strip())
        set_config('api_key_anthropic',  self.inp_anthropic.text().strip())
        set_config('api_key_openai',     self.inp_openai.text().strip())
        set_config('api_key_gemini',     self.inp_gemini.text().strip())
        set_config('api_key_openrouter', self.inp_openrouter.text().strip())

        set_config('ia_proveedor',    prov)
        set_config('api_key',         api_key)   # clave del proveedor ACTIVO (la lee el runtime)
        set_config('ollama_url',      self.inp_ollama_url.text().strip()    or 'http://localhost:11434')
        set_config('ollama_modelo',   self.inp_ollama_modelo.text().strip() or 'llama3.2')
        set_config('openai_modelo',     self.inp_openai_modelo.text().strip()     or 'gpt-4o-mini')
        set_config('gemini_modelo',     self.inp_gemini_modelo.text().strip()     or 'gemini-2.0-flash')
        set_config('openrouter_modelo', self._openrouter_modelo_id())

        self.lbl_ia_estado.setStyleSheet(
            f"font-size:11px; color:{GREEN}; "
            f"background:transparent; border:none;"
        )
        self.lbl_ia_estado.setText(
            "✓  Guardado. Cada proveedor recuerda su clave — cambia de "
            "proveedor y guarda para usarlo."
        )
