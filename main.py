__version__ = "2.0.1"
# -*- coding: utf-8 -*-
"""
AI Council — improved Kivy app.
Build note: Android's "built for an older version" warning is controlled by
targetSdkVersion in the Android packaging configuration, not by this Python file.
See the accompanying Android build notes at the end of this file.
"""
import json
import os
import threading
import time
import sys
import traceback
import http.client
import urllib.error
import urllib.request
import ssl
import certifi
from concurrent.futures import ThreadPoolExecutor, as_completed
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.slider import Slider

API_ROOT = "https://openrouter.ai/api/v1"
MAX_ROUNDS = 10
REQUEST_TIMEOUT = (10, 60)
MAX_HISTORY = 100

BG = (0.035, 0.045, 0.065, 1)
PANEL = (0.075, 0.095, 0.13, 1)
PANEL_ALT = (0.11, 0.135, 0.18, 1)
ACCENT = (0.40, 0.36, 1.0, 1)
TEXT = (0.94, 0.96, 1.0, 1)
MUTED = (0.62, 0.68, 0.78, 1)
GREEN = (0.30, 0.83, 0.63, 1)
RED = (1.0, 0.36, 0.42, 1)


def http_json(url, payload=None, headers=None, timeout=60):
    """Small JSON HTTP client using only the Python standard library.

    This deliberately avoids importing requests/charset_normalizer at startup,
    since those packages caused an Android packaging error in the supplied log.
    """
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Accept": "application/json", "User-Agent": "AI-Council/2.0.1"}
    if headers:
        request_headers.update(headers)
    if data is not None and "Content-Type" not in request_headers:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, headers=request_headers,
        method="POST" if data is not None else "GET",
    )
    try:
        tls_context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(request, timeout=timeout, context=tls_context) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        message = raw[:180] or str(exc.reason or "HTTP error")
        try:
            error_data = json.loads(raw).get("error", {})
            if isinstance(error_data, dict):
                message = str(error_data.get("message") or message)
        except (ValueError, AttributeError, TypeError):
            pass
        raise RuntimeError(f"HTTP {exc.code}: {message[:180]}") from exc
    except (http.client.IncompleteRead, http.client.HTTPException,
            urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            f"NETWORK: {type(reason).__name__}: {str(reason)[:140]}"
        ) from exc
    try:
        result = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError("Сервер вернул невалидный JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Сервер вернул неожиданный формат JSON")
    return result


class Card(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = dp(12)
        self.spacing = dp(8)
        with self.canvas.before:
            Color(*PANEL)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size,
                                        radius=[dp(16)])
        self.bind(pos=self._sync_bg, size=self._sync_bg)

    def _sync_bg(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size


class CouncilApp(App):
    def build(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            self.config_path = os.path.join(self.user_data_dir, "council_config.json")
            self.history_path = os.path.join(self.user_data_dir, "council_history.json")
            return self._build_ui()
        except Exception:
            exc_info = sys.exc_info()
            report = "".join(traceback.format_exception(*exc_info))
            write_crash_report(self, exc_info)
            return self._build_error_screen(report)

    def _build_error_screen(self, report):
        self.title = "AI Council — ошибка запуска"
        try:
            Window.clearcolor = (0.08, 0.025, 0.035, 1)
        except Exception:
            pass
        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        root.add_widget(Label(
            text="[b]Не удалось запустить AI Council[/b]", markup=True,
            color=(1, 0.72, 0.72, 1), font_size="18sp",
            size_hint_y=None, height=dp(42), halign="left"))
        root.add_widget(Label(
            text="Ошибка сохранена в ai_council_crash.log. Ниже — подробности; можно сделать скриншот или скопировать текст.",
            color=(1, 1, 1, 1), font_size="12sp", size_hint_y=None,
            height=dp(48), halign="left"))
        details = TextInput(text=report, readonly=True, multiline=True,
                            font_size="10sp", size_hint=(1, 1),
                            background_color=(0.05, 0.05, 0.07, 1),
                            foreground_color=(0.95, 0.95, 0.95, 1),
                            cursor_blink=False)
        root.add_widget(details)
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        copy_btn = Button(text="Скопировать ошибку", size_hint_x=1)
        copy_status = Label(text="", color=(0.7, 1, 0.8, 1), size_hint_x=1)
        def copy_report(*_):
            try:
                from kivy.core.clipboard import Clipboard
                Clipboard.copy(report)
                copy_status.text = "Скопировано — вставь в чат"
            except Exception:
                copy_status.text = "Выдели текст выше вручную"
        copy_btn.bind(on_release=copy_report)
        actions.add_widget(copy_btn)
        actions.add_widget(copy_status)
        root.add_widget(actions)
        return root

    def _build_ui(self):
        self.title = "AI Council"
        Window.clearcolor = BG
        self.cancel_event = threading.Event()
        self.busy = False
        self.catalog_loading = False
        self.catalog_error = ""
        self.models = []
        self.history = []
        self.participants = []
        self.next_participant_id = 1
        self.pending_picker_callback = None
        self._debate_thread = None

        self.config_path = os.path.join(self.user_data_dir, "council_config.json")
        self.history_path = os.path.join(self.user_data_dir, "council_history.json")
        self.load_council_config()
        self.load_history()

        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))

        header = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
        title_col = BoxLayout(orientation="vertical", spacing=0)
        title_col.add_widget(Label(text="[b]AI COUNCIL[/b]", markup=True,
                                   font_size="22sp", color=TEXT,
                                   halign="left", valign="middle"))
        title_col.add_widget(Label(text="Мульти-модельные дебаты",
                                   font_size="11sp", color=MUTED,
                                   halign="left", valign="middle"))
        header.add_widget(title_col)
        history_btn = self.make_button("История", PANEL_ALT, width=dp(92))
        history_btn.bind(on_release=self.show_history)
        header.add_widget(history_btn)
        root.add_widget(header)

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(3))
        content = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        content.bind(minimum_height=content.setter("height"))

        # API access
        key_card = Card(orientation="vertical", size_hint_y=None, height=dp(142))
        key_card.add_widget(self.heading("Подключение OpenRouter"))
        key_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.key_input = TextInput(
            hint_text="API-ключ OpenRouter", password=True, multiline=False,
            text=self.api_key, foreground_color=TEXT, hint_text_color=MUTED,
            background_color=PANEL_ALT, cursor_color=ACCENT,
            padding=[dp(10), dp(11)], write_tab=False)
        key_row.add_widget(self.key_input)
        save_btn = self.make_button("Сохранить", ACCENT, width=dp(100))
        save_btn.bind(on_release=self.save_key)
        key_row.add_widget(save_btn)
        key_card.add_widget(key_row)
        self.key_status = Label(
            text="Ключ хранится в папке приложения" if self.api_key else "Добавь API-ключ, чтобы начать",
            color=MUTED, font_size="11sp", halign="left",
            size_hint_y=None, height=dp(18))
        key_card.add_widget(self.key_status)
        content.add_widget(key_card)

        # Topic and number of rounds
        q_card = Card(orientation="vertical", size_hint_y=None, height=dp(228))
        q_card.add_widget(self.heading("Тема дискуссии"))
        self.question = TextInput(
            hint_text="Например: какая технология сильнее изменит образование?",
            multiline=True, size_hint_y=None, height=dp(94),
            foreground_color=TEXT, hint_text_color=MUTED,
            background_color=PANEL_ALT, cursor_color=ACCENT,
            padding=dp(10))
        q_card.add_widget(self.question)
        preset_row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
        preset_btn = self.make_button("Вставить шаблон темы", PANEL_ALT)
        preset_btn.bind(on_release=self.show_presets)
        preset_row.add_widget(preset_btn)
        q_card.add_widget(preset_row)
        rr = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
        rr.add_widget(Label(text="Раунды", color=MUTED, size_hint_x=None,
                            width=dp(60), halign="left"))
        self.round_slider = Slider(min=1, max=MAX_ROUNDS, step=1,
                                   value=self.rounds_value)
        self.rounds_label = Label(text=str(self.rounds_value), color=TEXT,
                                  size_hint_x=None, width=dp(24))
        self.round_slider.bind(value=self.on_rounds_change)
        rr.add_widget(self.round_slider)
        rr.add_widget(self.rounds_label)
        q_card.add_widget(rr)
        content.add_widget(q_card)

        # Reliability options
        opt_card = Card(orientation="vertical", size_hint_y=None, height=dp(176))
        opt_card.add_widget(self.heading("Параметры надёжности"))
        self.retry_btn = self.make_button("", PANEL_ALT)
        self.fallback_btn = self.make_button("", PANEL_ALT)
        self.continue_btn = self.make_button("", PANEL_ALT)
        self.retry_btn.bind(on_release=lambda *_: self.toggle_setting("retry"))
        self.fallback_btn.bind(on_release=lambda *_: self.toggle_setting("fallback"))
        self.continue_btn.bind(on_release=lambda *_: self.toggle_setting("continue"))
        opt_card.add_widget(self.retry_btn)
        opt_card.add_widget(self.fallback_btn)
        opt_card.add_widget(self.continue_btn)
        self.update_toggle_labels()
        content.add_widget(opt_card)

        # Participants
        self.people_card = Card(orientation="vertical", size_hint_y=None)
        self.people_card.add_widget(self.heading("Участники"))
        self.people_list = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(7))
        self.people_list.bind(minimum_height=self.people_list.setter("height"))
        self.people_card.add_widget(self.people_list)
        people_actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        add_btn = self.make_button("+ Добавить", PANEL_ALT)
        add_btn.bind(on_release=self.add_participant)
        catalog_btn = self.make_button("Каталог моделей", ACCENT)
        catalog_btn.bind(on_release=self.load_catalog)
        people_actions.add_widget(add_btn)
        people_actions.add_widget(catalog_btn)
        self.people_card.add_widget(people_actions)
        self.people_card.bind(minimum_height=self.people_card.setter("height"))
        content.add_widget(self.people_card)

        # Judge
        judge_card = Card(orientation="vertical", size_hint_y=None, height=dp(142))
        judge_card.add_widget(self.heading("Судья"))
        self.judge_btn = self.make_button(self.judge_model or "Выбрать модель судьи", PANEL_ALT)
        self.judge_btn.bind(on_release=lambda *_: self.open_model_picker(callback=self.set_judge))
        judge_card.add_widget(self.judge_btn)
        judge_api_btn = self.make_button("API судьи", PANEL_ALT)
        judge_api_btn.bind(on_release=self.open_judge_api_settings)
        judge_card.add_widget(judge_api_btn)
        content.add_widget(judge_card)

        # Output
        result_card = Card(orientation="vertical", size_hint_y=None, height=dp(360))
        result_card.add_widget(self.heading("Дискуссия"))
        result_tools = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
        export_btn = self.make_button("Экспорт TXT", PANEL_ALT)
        export_btn.bind(on_release=self.export_latest)
        compare_btn = self.make_button("Сравнить", PANEL_ALT)
        compare_btn.bind(on_release=self.show_comparison)
        result_tools.add_widget(export_btn)
        result_tools.add_widget(compare_btn)
        result_card.add_widget(result_tools)
        self.status = Label(text="Готов к работе · OpenRouter", color=GREEN,
                            size_hint_y=None, height=dp(24), halign="left")
        result_card.add_widget(self.status)
        self.output = Label(
            text="Здесь появятся ответы участников и заключение судьи.",
            color=TEXT, font_size="13sp", size_hint_y=None,
            halign="left", valign="top")
        self.output.bind(width=self._output_width, texture_size=self._output_texture)
        out_scroll = ScrollView(do_scroll_x=False, bar_width=dp(3))
        out_scroll.add_widget(self.output)
        result_card.add_widget(out_scroll)
        content.add_widget(result_card)

        scroll.add_widget(content)
        root.add_widget(scroll)

        bottom = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        self.run_btn = self.make_button("Начать дебаты", ACCENT)
        self.run_btn.bind(on_release=self.start_debate)
        self.cancel_btn = self.make_button("Стоп", RED, width=dp(76))
        self.cancel_btn.disabled = True
        self.cancel_btn.bind(on_release=self.cancel_debate)
        bottom.add_widget(self.run_btn)
        bottom.add_widget(self.cancel_btn)
        root.add_widget(bottom)

        self.refresh_participants()
        return root

    def _output_width(self, widget, width):
        widget.text_size = (max(1, width), None)

    def _output_texture(self, widget, size):
        widget.height = max(dp(40), size[1])

    def load_council_config(self):
        self.config = {}
        self.api_key = ""
        self.rounds_value = 3
        self.retry_enabled = True
        self.fallback_enabled = True
        self.continue_enabled = True
        self.judge_model = ""

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.config = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError, TypeError):
            self.config = {}

        self.api_key = str(self.config.get("api_key", ""))
        try:
            self.rounds_value = max(
                1, min(MAX_ROUNDS, int(self.config.get("rounds", 3)))
            )
        except (ValueError, TypeError):
            self.rounds_value = 3

        self.retry_enabled = bool(self.config.get("retry", True))
        self.fallback_enabled = bool(self.config.get("fallback", True))
        self.continue_enabled = bool(self.config.get("continue_on_error", True))

        # Настройки подключения судьи. Старый конфиг продолжает работать через OpenRouter.
        self.judge_model = str(self.config.get("judge_model", ""))
        self.judge_provider = str(self.config.get("judge_provider", "openrouter"))
        self.judge_api_base_url = str(
            self.config.get("judge_api_base_url", API_ROOT)
        ).rstrip("/")
        self.judge_api_key = str(self.config.get("judge_api_key", ""))

        saved = self.config.get("participants", [])
        if isinstance(saved, list):
            for item in saved:
                if isinstance(item, dict):
                    self.participants.append({
                        "uid": self.next_participant_id,
                        "model": str(item.get("model", "")),
                        "enabled": bool(item.get("enabled", True)),
                        "role": str(item.get("role", "Эксперт")),
                        "provider": str(item.get("provider", "openrouter")),
                        "api_base_url": str(
                            item.get("api_base_url", API_ROOT)
                        ).rstrip("/"),
                        "api_key": str(item.get("api_key", "")),
                    })
                    self.next_participant_id += 1

        if not self.participants:
            for _ in range(3):
                self.participants.append({
                    "uid": self.next_participant_id,
                    "model": "",
                    "enabled": True,
                    "role": "Эксперт",
                    "provider": "openrouter",
                    "api_base_url": API_ROOT,
                    "api_key": "",
                })
                self.next_participant_id += 1

    def save_config(self, *_):
        data = {
            "api_key": (
                self.key_input.text.strip()
                if hasattr(self, "key_input") else self.api_key
            ),
            "rounds": (
                int(self.round_slider.value)
                if hasattr(self, "round_slider") else self.rounds_value
            ),
            "retry": self.retry_enabled,
            "fallback": self.fallback_enabled,
            "continue_on_error": self.continue_enabled,
            "judge_model": self.judge_model,
            "judge_provider": getattr(self, "judge_provider", "openrouter"),
            "judge_api_base_url": getattr(
                self, "judge_api_base_url", API_ROOT
            ),
            "judge_api_key": getattr(self, "judge_api_key", ""),
            "participants": [
                {
                    "model": p.get("model", ""),
                    "enabled": p.get("enabled", True),
                    "role": p.get("role", "Эксперт"),
                    "provider": p.get("provider", "openrouter"),
                    "api_base_url": p.get("api_base_url", API_ROOT),
                    "api_key": p.get("api_key", ""),
                }
                for p in self.participants
            ],
        }

        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            temp = self.config_path + ".tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp, self.config_path)
            self.config = data
            self.api_key = data["api_key"]
            return True
        except (OSError, TypeError, ValueError):
            return False

    def save_key(self, *_):
        self.api_key = self.key_input.text.strip()
        if self.save_config():
            self.key_status.text = "Ключ сохранён локально"
            self.show_notice("Готово", "Ключ сохранён в приватной папке приложения.")
        else:
            self.key_status.text = "Не удалось сохранить настройки"
            self.show_notice("Ошибка", "Не удалось сохранить настройки приложения.")

    def load_history(self):
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.history = data[:MAX_HISTORY] if isinstance(data, list) else []
        except (OSError, ValueError, TypeError):
            self.history = []

    def save_history(self, entry):
        self.history.insert(0, entry)
        self.history = self.history[:MAX_HISTORY]
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            temp = self.history_path + ".tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
            os.replace(temp, self.history_path)
        except OSError:
            self.publish("Предупреждение: не удалось сохранить историю на устройстве.")

    def make_button(self, text, color, width=None):
        return Button(text=text, size_hint_x=None if width else 1,
                      width=width or 0, size_hint_y=None, height=dp(42),
                      background_normal="", background_down="",
                      background_color=color, color=TEXT, font_size="12sp")

    def heading(self, text):
        return Label(text=f"[b]{text}[/b]", markup=True, color=TEXT,
                     font_size="15sp", halign="left",
                     size_hint_y=None, height=dp(26))

    def on_rounds_change(self, _slider, value):
        self.rounds_value = int(value)
        if hasattr(self, "rounds_label"):
            self.rounds_label.text = str(self.rounds_value)
        if hasattr(self, "config_path") and hasattr(self, "key_input"):
            self.save_config()

    def toggle_setting(self, setting):
        if self.busy:
            return
        if setting == "retry":
            self.retry_enabled = not self.retry_enabled
        elif setting == "fallback":
            self.fallback_enabled = not self.fallback_enabled
        else:
            self.continue_enabled = not self.continue_enabled
        self.update_toggle_labels()
        self.save_config()

    def update_toggle_labels(self):
        if not hasattr(self, "retry_btn"):
            return
        self.retry_btn.text = "Повтор запросов: " + ("ВКЛ" if self.retry_enabled else "ВЫКЛ")
        self.fallback_btn.text = "Бесплатный резерв: " + ("ВКЛ" if self.fallback_enabled else "ВЫКЛ")
        self.continue_btn.text = "Продолжать при ошибке: " + ("ВКЛ" if self.continue_enabled else "ВЫКЛ")

    def add_participant(self, *_):
        if self.busy:
            return
        self.participants.append({"uid": self.next_participant_id, "model": "", "enabled": True, "role": "Эксперт", "provider": "openrouter", "api_base_url": API_ROOT, "api_key": ""})
        self.next_participant_id += 1
        self.refresh_participants()
        self.save_config()

    def remove_participant(self, uid):
        if self.busy:
            return
        self.participants = [p for p in self.participants if p["uid"] != uid]
        self.refresh_participants()
        self.save_config()

    def toggle_participant(self, uid):
        if self.busy:
            return
        for p in self.participants:
            if p["uid"] == uid:
                p["enabled"] = not p["enabled"]
        self.refresh_participants()
        self.save_config()

    def refresh_participants(self):
        if not hasattr(self, "people_list"):
            return
        self.people_list.clear_widgets()
        for p in self.participants:
            row = Card(orientation="horizontal", size_hint_y=None, height=dp(70), padding=dp(8), spacing=dp(4))
            details = BoxLayout(orientation="vertical", spacing=dp(2))
            details.add_widget(Label(text=p["model"] or "Модель не выбрана",
                                     color=TEXT, halign="left", valign="middle",
                                     font_size="11sp", shorten=True, shorten_from="right"))
            details.add_widget(Label(text=(p.get("role", "Эксперт") + " · " + ("Включён" if p["enabled"] else "Отключён")),
                                     color=GREEN if p["enabled"] else MUTED,
                                     font_size="10sp", halign="left"))
            row.add_widget(details)
            choose = self.make_button("Выбрать", ACCENT, width=dp(72))
            choose.bind(on_release=lambda _b, uid=p["uid"]: self.open_model_picker(
                callback=lambda model: self.set_participant_model(uid, model)))
            row.add_widget(choose)
            api_btn = self.make_button("API", PANEL_ALT, width=dp(48))
            api_btn.bind(on_release=lambda _b, uid=p["uid"]: self.open_participant_api_settings(uid))
            row.add_widget(api_btn)
            toggle = self.make_button("Вкл" if p["enabled"] else "Выкл", PANEL_ALT, width=dp(48))
            toggle.bind(on_release=lambda _b, uid=p["uid"]: self.toggle_participant(uid))
            row.add_widget(toggle)
            remove = self.make_button("×", RED, width=dp(34))
            remove.bind(on_release=lambda _b, uid=p["uid"]: self.remove_participant(uid))
            row.add_widget(remove)
            self.people_list.add_widget(row)
        self.people_list.height = sum(dp(77) for _ in self.participants)
        self.people_card.height = dp(26 + 12 + 8 + 42 + 8) + self.people_list.height

    def open_participant_api_settings(self, uid):
        if self.busy:
            self.show_notice("Дебаты выполняются", "Дождись завершения дебатов перед изменением подключения.")
            return

        participant = next((p for p in self.participants if p["uid"] == uid), None)
        if participant is None:
            return

        body = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        scroll = ScrollView()
        fields = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        fields.bind(minimum_height=fields.setter("height"))

        def add_field(title, value="", password=False, hint=""):
            fields.add_widget(self.heading(title))
            widget = TextInput(
                text=value,
                hint_text=hint,
                password=password,
                multiline=False,
                size_hint_y=None,
                height=dp(44),
                foreground_color=TEXT,
                background_color=PANEL_ALT,
                cursor_color=TEXT,
            )
            fields.add_widget(widget)
            return widget

        provider = add_field(
            "Провайдер",
            participant.get("provider", "openrouter"),
            hint="openrouter или openai-compatible",
        )
        base_url = add_field(
            "Базовый URL API",
            participant.get("api_base_url", API_ROOT),
            hint="https://example.com/v1",
        )
        api_key = add_field(
            "API-ключ",
            participant.get("api_key", ""),
            password=True,
            hint="Оставь пустым для общего ключа OpenRouter",
        )
        model_id = add_field(
            "ID модели",
            participant.get("model", ""),
            hint="Например: provider/model-name",
        )

        fields.add_widget(Label(
            text="Для OpenAI-совместимого API укажи базовый URL, обычно заканчивающийся на /v1. На этом этапе поля сохраняются; переключение провайдера начнёт работать после следующего обновления.",
            color=MUTED,
            size_hint_y=None,
            height=dp(72),
            text_size=(None, None),
            halign="left",
            valign="middle",
        ))

        scroll.add_widget(fields)
        body.add_widget(scroll)

        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(
            title="API участника",
            content=body,
            size_hint=(0.94, 0.86),
            auto_dismiss=True,
        )

        cancel = self.make_button("Отмена", PANEL_ALT)
        save = self.make_button("Сохранить", ACCENT)

        def save_fields(*_):
            chosen_provider = provider.text.strip().lower() or "openrouter"
            chosen_url = base_url.text.strip().rstrip("/")
            chosen_model = model_id.text.strip()

            if chosen_provider not in ("openrouter", "openai-compatible"):
                self.show_notice(
                    "Неизвестный провайдер",
                    "Используй openrouter или openai-compatible.",
                )
                return
            if not chosen_url.startswith(("https://", "http://")):
                self.show_notice("Неверный URL", "URL должен начинаться с https:// или http://.")
                return
            if not chosen_model:
                self.show_notice("Нет модели", "Укажи ID модели.")
                return

            participant["provider"] = chosen_provider
            participant["api_base_url"] = chosen_url
            participant["api_key"] = api_key.text.strip()
            participant["model"] = chosen_model
            self.refresh_participants()
            if not self.save_config():
                self.show_notice("Ошибка", "Не удалось сохранить настройки.")
                return
            popup.dismiss()
            self.show_notice(
                "Настройки сохранены",
                "Подключение будет использовать эти параметры после обновления сетевого обработчика.",
            )

        cancel.bind(on_release=popup.dismiss)
        save.bind(on_release=save_fields)
        actions.add_widget(cancel)
        actions.add_widget(save)
        body.add_widget(actions)
        popup.open()

    def set_participant_model(self, uid, model):
        for p in self.participants:
            if p["uid"] == uid:
                p["model"] = model["id"]
        self.refresh_participants()
        self.save_config()

    def set_judge(self, model):
        self.judge_model = model["id"]
        self.judge_btn.text = self.judge_model
        self.save_config()

    def open_judge_api_settings(self, *_):
        if self.busy:
            self.show_notice(
                "Дебаты выполняются",
                "Дождись завершения дебатов перед изменением подключения."
            )
            return

        body = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        scroll = ScrollView()
        fields = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        fields.bind(minimum_height=fields.setter("height"))

        def add_field(title, value="", password=False, hint=""):
            fields.add_widget(self.heading(title))
            widget = TextInput(
                text=value,
                hint_text=hint,
                password=password,
                multiline=False,
                size_hint_y=None,
                height=dp(44),
                foreground_color=TEXT,
                background_color=PANEL_ALT,
                cursor_color=TEXT,
            )
            fields.add_widget(widget)
            return widget

        provider = add_field(
            "Провайдер",
            getattr(self, "judge_provider", "openrouter"),
            hint="openrouter или openai-compatible",
        )
        base_url = add_field(
            "Базовый URL API",
            getattr(self, "judge_api_base_url", API_ROOT),
            hint="https://example.com/v1",
        )
        api_key = add_field(
            "API-ключ судьи",
            getattr(self, "judge_api_key", ""),
            password=True,
            hint="Для OpenRouter можно использовать общий ключ",
        )
        fields.add_widget(Label(
            text=(
                "Судья использует собственные настройки подключения. "
                "Для OpenAI-совместимого API укажи URL, обычно заканчивающийся на /v1, "
                "и отдельный API-ключ."
            ),
            color=MUTED,
            size_hint_y=None,
            height=dp(72),
            halign="left",
            valign="middle",
        ))

        scroll.add_widget(fields)
        body.add_widget(scroll)
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(
            title="API судьи",
            content=body,
            size_hint=(0.94, 0.86),
            auto_dismiss=True,
        )
        cancel = self.make_button("Отмена", PANEL_ALT)
        save = self.make_button("Сохранить", ACCENT)

        def save_fields(*_):
            chosen_provider = provider.text.strip().lower() or "openrouter"
            chosen_url = base_url.text.strip().rstrip("/")
            chosen_key = api_key.text.strip()

            if chosen_provider not in ("openrouter", "openai-compatible"):
                self.show_notice(
                    "Неизвестный провайдер",
                    "Используй openrouter или openai-compatible."
                )
                return
            if not chosen_url.startswith(("https://", "http://")):
                self.show_notice(
                    "Неверный URL",
                    "URL должен начинаться с https:// или http://."
                )
                return
            if chosen_provider == "openai-compatible" and not chosen_key:
                self.show_notice(
                    "Нет API-ключа",
                    "Для OpenAI-совместимого API нужен отдельный ключ судьи."
                )
                return

            self.judge_provider = chosen_provider
            self.judge_api_base_url = chosen_url
            self.judge_api_key = chosen_key
            if not self.save_config():
                self.show_notice("Ошибка", "Не удалось сохранить настройки.")
                return
            popup.dismiss()
            self.show_notice("Настройки сохранены", "Подключение судьи обновлено.")

        cancel.bind(on_release=popup.dismiss)
        save.bind(on_release=save_fields)
        actions.add_widget(cancel)
        actions.add_widget(save)
        body.add_widget(actions)
        popup.open()

    def load_catalog(self, *_):
        if self.catalog_loading or self.busy:
            return
        self.catalog_loading = True
        self.status.text = "Загружаю каталог моделей…"
        self.run_btn.disabled = True
        threading.Thread(target=self._fetch_catalog, daemon=True).start()

    def _fetch_catalog(self):
        try:
            response_data = http_json(API_ROOT + "/models", timeout=REQUEST_TIMEOUT[1])
            data = response_data.get("data", [])
            models = [m for m in data if isinstance(m, dict) and m.get("id")]
            models.sort(key=lambda m: str(m.get("name", m["id"])).lower())
            self.models = models
            self.catalog_error = ""
            Clock.schedule_once(lambda _dt: self._catalog_loaded())
        except Exception as exc:
            self.catalog_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            Clock.schedule_once(lambda _dt: self._catalog_failed())

    def _catalog_loaded(self):
        self.catalog_loading = False
        self.run_btn.disabled = self.busy
        self.status.text = f"Каталог загружен: {len(self.models)} моделей"
        callback = self.pending_picker_callback
        self.pending_picker_callback = None
        if callback is not None:
            self.open_model_picker(callback=callback)

    def _catalog_failed(self):
        self.catalog_loading = False
        self.run_btn.disabled = self.busy
        self.status.text = "Каталог недоступен"
        self.show_notice("Не удалось загрузить каталог",
                         "Проверь интернет-соединение и повтори попытку.\n\n" + self.catalog_error)

    def open_model_picker(self, callback=None, *_):
        if not self.models:
            self.pending_picker_callback = callback
            self.load_catalog()
            return
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        search = TextInput(hint_text="Поиск по названию или ID…", multiline=False,
                           size_hint_y=None, height=dp(42), foreground_color=TEXT,
                           hint_text_color=MUTED, background_color=PANEL_ALT)
        free_row = BoxLayout(size_hint_y=None, height=dp(38))
        free_only = {"value": False}
        free_btn = self.make_button("Показать только бесплатные", PANEL_ALT)
        free_row.add_widget(free_btn)
        box.add_widget(search)
        box.add_widget(free_row)
        results = GridLayout(cols=1, spacing=dp(5), size_hint_y=None)
        results.bind(minimum_height=results.setter("height"))
        list_scroll = ScrollView(do_scroll_x=False)
        list_scroll.add_widget(results)
        box.add_widget(list_scroll)
        popup = Popup(title="Выбрать модель", content=box, size_hint=(0.95, 0.88), auto_dismiss=True)

        def is_free(model):
            pricing = model.get("pricing", {})
            try:
                return float(pricing.get("prompt", -1)) == 0 and float(pricing.get("completion", -1)) == 0
            except (TypeError, ValueError):
                return False

        def select_model(model):
            if callback:
                callback(model)
            popup.dismiss()

        def render(*_):
            results.clear_widgets()
            query = search.text.lower().strip()
            filtered = []
            for model in self.models:
                mid = str(model.get("id", ""))
                name = str(model.get("name", mid))
                if query and query not in mid.lower() and query not in name.lower():
                    continue
                if free_only["value"] and not is_free(model):
                    continue
                filtered.append(model)
            if not filtered:
                results.add_widget(Label(text="Ничего не найдено", color=MUTED, size_hint_y=None, height=dp(42)))
            for model in filtered[:180]:
                mid = model["id"]
                name = model.get("name", mid)
                price_tag = "БЕСПЛАТНО" if is_free(model) else "ПЛАТНАЯ"
                btn = Button(text=f"{name}\n{mid}  ·  {price_tag}", size_hint_y=None,
                             height=dp(62), halign="left", valign="middle",
                             text_size=(Window.width * 0.78, None),
                             background_normal="", background_color=PANEL_ALT,
                             color=TEXT, font_size="11sp")
                btn.bind(on_release=lambda _b, m=model: select_model(m))
                results.add_widget(btn)

        def toggle_free(*_):
            free_only["value"] = not free_only["value"]
            free_btn.text = "Показать все модели" if free_only["value"] else "Показать только бесплатные"
            render()

        free_btn.bind(on_release=toggle_free)
        search.bind(text=render)
        render()
        popup.open()

    def start_debate(self, *_):
        if self.busy:
            return
        key = self.key_input.text.strip()
        question = self.question.text.strip()
        if not question:
            self.show_notice("Нет темы", "Напиши вопрос или тему для обсуждения.")
            return
        active = [p.copy() for p in self.participants if p["enabled"] and p["model"]]
        if len(active) < 2:
            self.show_notice("Мало участников", "Выбери минимум две включённые модели.")
            return

        missing_keys = []
        for p in active:
            provider = p.get("provider", "openrouter")
            own_key = (p.get("api_key") or "").strip()
            if provider == "openai-compatible" and not own_key:
                missing_keys.append(p.get("model", "участник"))
            elif provider == "openrouter" and not (own_key or key):
                missing_keys.append(p.get("model", "участник"))
        if missing_keys:
            self.show_notice(
                "Не хватает API-ключей",
                "Укажи ключи в настройках участников: " + ", ".join(missing_keys[:4])
            )
            return

        if not self.judge_model:
            self.judge_model = active[0]["model"]
            self.judge_btn.text = self.judge_model
        if getattr(self, "judge_provider", "openrouter") == "openai-compatible":
            if not (getattr(self, "judge_api_key", "") or "").strip():
                self.show_notice(
                    "Нет ключа судьи",
                    "Укажи API-ключ в настройках подключения судьи."
                )
                return
        elif not (getattr(self, "judge_api_key", "") or key).strip():
            self.show_notice(
                "Нет ключа судьи",
                "Для судьи нужен общий ключ OpenRouter или отдельный ключ судьи."
            )
            return

        self.save_config()
        self.cancel_event.clear()
        self.busy = True
        self.run_btn.disabled = True
        self.cancel_btn.disabled = False
        self.output.text = "Подключаю участников…"
        self.status.text = "Дебаты выполняются"
        settings = {
            "key": key, "question": question, "rounds": int(self.round_slider.value),
            "participants": active, "judge": self.judge_model,
            "retry": self.retry_enabled, "fallback": self.fallback_enabled,
            "continue_on_error": self.continue_enabled, "models": list(self.models)
        }
        self._debate_thread = threading.Thread(target=self.run_debate, args=(settings,), daemon=True)
        self._debate_thread.start()

    def request_model(self, key, model_id, prompt, connection=None):
        connection = connection or {}
        provider = connection.get("provider", "openrouter")
        base_url = (connection.get("api_base_url") or API_ROOT).strip().rstrip("/")
        own_key = (connection.get("api_key") or "").strip()

        if provider == "openai-compatible":
            api_key = own_key
            if not api_key:
                raise RuntimeError("Для этого участника не задан API-ключ")
        else:
            api_key = own_key or (key or "").strip()
            if not api_key:
                raise RuntimeError("Не задан API-ключ OpenRouter")

        if not base_url.startswith(("https://", "http://")):
            raise RuntimeError("Base URL должен начинаться с https:// или http://")

        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "X-Title": "AI Council",
        }
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.6,
            "max_tokens": 2500,
        }
        data = http_json(
            base_url + "/chat/completions", payload=payload,
            headers=headers, timeout=REQUEST_TIMEOUT[1],
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("API вернул ответ неожиданного формата")
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Модель вернула пустой ответ")
        return content.strip()

    def ask_safely(self, settings, model_id, prompt, connection=None):
        connection = connection or {}
        provider = connection.get("provider", "openrouter")
        candidates = [model_id]

        # Автоподбор бесплатных моделей применим только к каталогу OpenRouter.
        if provider == "openrouter" and settings["fallback"]:
            for model in settings["models"]:
                pricing = model.get("pricing", {})
                try:
                    free = float(pricing.get("prompt", -1)) == 0 and float(pricing.get("completion", -1)) == 0
                except (TypeError, ValueError):
                    free = False
                mid = model.get("id", "")
                if free and mid and mid not in candidates:
                    candidates.append(mid)
                if len(candidates) >= 4:
                    break

        errors = []
        for candidate in candidates:
            attempts = 3 if settings["retry"] else 1
            for attempt in range(attempts):
                if self.cancel_event.is_set():
                    return None, candidate, "Остановлено пользователем"
                try:
                    return self.request_model(
                        settings.get("key", ""), candidate, prompt, connection
                    ), candidate, None
                except RuntimeError as exc:
                    error = str(exc)
                    errors.append(f"{candidate}: {error}")
                    transient = error.startswith("NETWORK:") or any(
                        code in error for code in ("HTTP 408", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")
                    )
                    if transient and attempt + 1 < attempts:
                        self.cancel_event.wait(min(2 ** attempt, 4))
                        continue
                    break
                except (ValueError, KeyError, IndexError, TypeError):
                    errors.append(f"{candidate}: неверный формат ответа")
                    break
        return None, model_id, "; ".join(errors[-4:]) or "Нет ответа"

    def run_debate(self, settings):
        question = settings["question"]
        transcript, successful = [], []
        final_answer = ""
        try:
            for round_no in range(1, settings["rounds"] + 1):
                if self.cancel_event.is_set():
                    break
                self.publish(f"Раунд {round_no}/{settings['rounds']} — собираю ответы…")
                if round_no == 1:
                    prompt = ("Ты участник интеллектуальных дебатов. Ответь самостоятельно, "
                              "обоснуй позицию и отметь неопределённость.\n\nВопрос: " + question)
                else:
                    recent = successful[-min(12, len(successful)):]
                    previous = "\n\n".join(f"{x['name']}:\n{x['answer'][:3500]}" for x in recent)
                    prompt = ("Учитывай свою назначенную роль и анализируй вопрос с её перспективы. "
                              f"Исходный вопрос: {question}\nРаунд: {round_no}\n\n"
                              f"Предыдущие ответы:\n{previous}\n\n"
                              "Критически оцени аргументы других участников, исправь свои ошибки, "
                              "укажи сильные и слабые стороны и дай улучшенный ответ. Не соглашайся автоматически.")
                round_items = []
                with ThreadPoolExecutor(max_workers=min(5, len(settings["participants"]))) as pool:
                    future_map = {}
                    for p in settings["participants"]:
                        role_prompt = (f"Твоя роль в совете: {p.get('role', 'Эксперт')}. "
                                       "Рассматривай вопрос с этой перспективы.\n\n" + prompt)
                        future_map[pool.submit(self.ask_safely, settings, p["model"], role_prompt, p)] = p
                    for future in as_completed(future_map):
                        participant = future_map[future]
                        try:
                            answer, used_model, error = future.result()
                        except Exception as exc:
                            answer, used_model, error = None, participant["model"], type(exc).__name__
                        if answer:
                            item = {"round": round_no, "name": participant["model"],
                                    "used_model": used_model, "answer": answer,
                                    "estimated_cost_usd": self.estimate_cost(settings, used_model, prompt, answer)}
                            round_items.append(item)
                            successful.append(item)
                            self.publish(f"Раунд {round_no}/{settings['rounds']}\n"
                                         f"Ответ получен: {participant['model']}\n\n{answer}")
                        else:
                            round_items.append({"round": round_no, "name": participant["model"], "error": error})
                            self.publish(f"{participant['model']}: {error}")
                transcript.extend(round_items)
                if self.cancel_event.is_set():
                    break
                if not settings["continue_on_error"] and any("error" in x for x in round_items):
                    break
                if not any("answer" in x for x in round_items):
                    break

            if self.cancel_event.is_set():
                final_answer = "Дебаты остановлены. Ниже сохранены полученные ответы."
            elif not successful:
                final_answer = "Участники не ответили. Проверь API-ключ, баланс/лимиты и доступность моделей."
            else:
                judge_prompt = (
                    "Ты независимый судья интеллектуальных дебатов.\n"
                    f"Вопрос: {question}\n\nОцени качество аргументов, выдели согласия, разногласия, "
                    "сильные стороны и возможные ошибки. Не придумывай факты. Не считай отсутствие "
                    "ответа доказательством проигрыша. Заверши обоснованным выводом.\n\n"
                    + "\n\n".join(f"Раунд {x['round']} — {x['name']}:\n{x['answer'][:4000]}" for x in successful[-15:])
                )
                self.publish("Судья анализирует результаты…")
                judge_connection = {
                    "provider": getattr(self, "judge_provider", "openrouter"),
                    "api_base_url": getattr(self, "judge_api_base_url", API_ROOT),
                    "api_key": getattr(self, "judge_api_key", ""),
                }
                judge_answer, actual_judge, judge_error = self.ask_safely(
                    settings, settings["judge"], judge_prompt, judge_connection
                )
                if judge_answer:
                    total_cost = sum(x.get("estimated_cost_usd", 0) or 0 for x in successful)
                    final_answer = (f"ИТОГ СУДЬИ · {actual_judge}\n\n{judge_answer}\n\n"
                                    f"Оценочная стоимость известных моделей: ~${total_cost:.6f} USD "
                                    "(оценка по длине текста, не счёт OpenRouter).\n\n"
                                    + self.format_transcript(transcript))
                else:
                    final_answer = f"Не удалось получить итог судьи: {judge_error}\n\n" + self.format_transcript(transcript)

            entry = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "question": question, "rounds": settings["rounds"],
                     "judge": settings["judge"], "transcript": transcript, "final": final_answer}
            Clock.schedule_once(lambda _dt, e=entry: self.save_history(e))
            Clock.schedule_once(lambda _dt, result=final_answer: self.finish_debate(result))
        except Exception as exc:
            self.publish("Ошибка во время дебатов: " + type(exc).__name__ + ": " + str(exc)[:180])
            Clock.schedule_once(lambda _dt: self.finish_ui())

    def format_transcript(self, transcript):
        parts = ["\n\n──── ОТВЕТЫ УЧАСТНИКОВ ────"]
        for item in transcript:
            heading = f"\nРаунд {item.get('round', '?')} · {item.get('name', 'Модель')}"
            if "answer" in item:
                parts.append(heading + "\n" + item["answer"])
            else:
                parts.append(heading + "\nОшибка: " + str(item.get("error", "нет ответа")))
        return "\n".join(parts)

    def publish(self, text):
        Clock.schedule_once(lambda _dt, value=str(text): setattr(self.output, "text", value))

    def finish_debate(self, text):
        self.output.text = text
        self.status.text = "Дебаты завершены" if not self.cancel_event.is_set() else "Остановлено"
        self.finish_ui()

    def finish_ui(self):
        self.busy = False
        self.run_btn.disabled = False
        self.cancel_btn.disabled = True

    def cancel_debate(self, *_):
        if self.busy:
            self.cancel_event.set()
            self.status.text = "Останавливаю… текущий HTTP-запрос может завершиться не сразу."

    def show_history(self, *_):
        if not self.history:
            self.show_notice("История", "Сохранённых дискуссий пока нет.")
            return
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        scroll = ScrollView(do_scroll_x=False)
        items = GridLayout(cols=1, spacing=dp(6), size_hint_y=None)
        items.bind(minimum_height=items.setter("height"))
        popup = Popup(title="История дискуссий", content=box, size_hint=(0.94, 0.84))
        for entry in self.history:
            btn = Button(text=f"{entry.get('timestamp', '')}\n{entry.get('question', 'Без темы')}",
                         size_hint_y=None, height=dp(66), halign="left", valign="middle",
                         background_normal="", background_color=PANEL_ALT, color=TEXT)
            btn.bind(on_release=lambda _b, e=entry: self.open_history_entry(e, popup))
            items.add_widget(btn)
        scroll.add_widget(items)
        box.add_widget(scroll)
        clear_btn = self.make_button("Очистить историю", RED)
        clear_btn.bind(on_release=lambda *_: self.clear_history(popup))
        box.add_widget(clear_btn)
        popup.open()

    def open_history_entry(self, entry, popup):
        popup.dismiss()
        self.output.text = f"ВОПРОС\n{entry.get('question', '')}\n\n{entry.get('final', '')}"
        self.status.text = "Просмотр сохранённой дискуссии"

    def clear_history(self, popup):
        self.history = []
        try:
            if os.path.exists(self.history_path):
                os.remove(self.history_path)
        except OSError:
            self.show_notice("Ошибка", "Не удалось удалить файл истории.")
        popup.dismiss()

    def estimate_cost(self, settings, model_id, prompt, answer):
        model = next((m for m in settings.get("models", []) if m.get("id") == model_id), None)
        if not model:
            return None
        pricing = model.get("pricing", {})
        try:
            prompt_price = float(pricing.get("prompt", 0) or 0)
            completion_price = float(pricing.get("completion", 0) or 0)
            in_tokens = max(1, len(prompt) // 4)
            out_tokens = max(1, len(answer) // 4)
            return round(in_tokens * prompt_price + out_tokens * completion_price, 8)
        except (TypeError, ValueError):
            return None

    def export_latest(self, *_):
        text = getattr(self.output, "text", "")
        if not text.strip():
            self.show_notice("Экспорт", "Пока нечего экспортировать.")
            return
        filename = "ai_council_" + time.strftime("%Y%m%d_%H%M%S") + ".txt"
        path = os.path.join(self.user_data_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.show_notice("Экспорт готов", "Текстовый отчёт сохранён в приватной папке приложения:\n" + path)
        except OSError as exc:
            self.show_notice("Ошибка экспорта", str(exc))

    def show_comparison(self, *_):
        if not self.history:
            self.show_notice("Сравнение", "Сначала проведи дебаты — тогда появятся оценки.")
            return
        entry = self.history[0]
        rows = []
        for item in entry.get("transcript", []):
            if "answer" not in item:
                continue
            cost = item.get("estimated_cost_usd")
            cost_text = ("~$" + f"{cost:.6f}") if isinstance(cost, (int, float)) else "н/д"
            rows.append(f"Раунд {item.get('round')} · {item.get('name')}\n"
                        f"Фактическая модель: {item.get('used_model', item.get('name'))}\n"
                        f"Оценка стоимости: {cost_text}\n"
                        f"Длина ответа: {len(item.get('answer', ''))} символов")
        self.show_notice("Сравнение участников", "\n\n".join(rows[:12]) or "Нет ответов для сравнения.")

    def show_presets(self, *_):
        presets = [
            ("Технологии", "Сравни два подхода к решению задачи. Приведи доказательства, риски, стоимость и условия, при которых каждый подход лучше."),
            ("Бизнес-идея", "Оцени бизнес-идею с позиции предпринимателя, критика, финансового аналитика и клиента. Укажи гипотезы, риски и дешёвые способы проверки."),
            ("Научный вопрос", "Разбери вопрос научно: отдели подтверждённые факты от гипотез, перечисли альтернативные объяснения и укажи, какие данные нужны для вывода."),
            ("Выбор продукта", "Сравни варианты по критериям, найди компромиссы, неизвестные параметры и сформулируй рекомендацию с оговорками."),
            ("Дебаты за и против", "Сформулируй сильнейшие аргументы за и против позиции. Затем найди общие основания, спорные предпосылки и взвешенный вывод.")
        ]
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        popup = Popup(title="Шаблоны дискуссий", content=box, size_hint=(0.92, 0.72))
        for title, prompt in presets:
            btn = self.make_button(title, PANEL_ALT)
            btn.bind(on_release=lambda _b, p=prompt: self._apply_preset(p, popup))
            box.add_widget(btn)
        popup.open()

    def _apply_preset(self, prompt, popup):
        self.question.text = prompt
        popup.dismiss()

    def show_notice(self, title, message):
        body = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        label = Label(text=message, color=TEXT, halign="left", valign="middle",
                      text_size=(Window.width * 0.78, None))
        body.add_widget(label)
        close = self.make_button("Понятно", ACCENT, width=dp(110))
        close.pos_hint = {"center_x": 0.5}
        body.add_widget(close)
        popup = Popup(title=title, content=body, size_hint=(0.88, 0.34))
        close.bind(on_release=popup.dismiss)
        popup.open()


def write_crash_report(app, exc_info):
    report = "".join(traceback.format_exception(*exc_info))
    candidates = []
    try:
        candidates.append(os.path.join(app.user_data_dir, "ai_council_crash.log"))
    except Exception:
        pass
    try:
        candidates.append(os.path.join(os.path.expanduser("~"), "ai_council_crash.log"))
    except Exception:
        pass
    candidates.append(os.path.join(os.getcwd(), "ai_council_crash.log"))
    for path in candidates:
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("AI Council startup/runtime crash report\n")
                f.write(report)
            return path
        except Exception:
            continue
    return None


if __name__ == "__main__":
    app = CouncilApp()
    try:
        app.run()
    except BaseException:
        exc_info = sys.exc_info()
        log_path = write_crash_report(app, exc_info)
        print("AI Council crashed. Crash report:", log_path or "could not write log", file=sys.stderr)
        traceback.print_exception(*exc_info)
        raise
