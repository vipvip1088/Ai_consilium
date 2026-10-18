import os
import json
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.core.window import Window
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
MAX_RETRIES = 2
REQUEST_TIMEOUT = (10, 75)

BG = (0.055, 0.067, 0.09, 1)
PANEL = (0.10, 0.12, 0.16, 1)
PANEL_ALT = (0.13, 0.16, 0.21, 1)
ACCENT = (0.42, 0.38, 1.0, 1)
TEXT = (0.93, 0.95, 0.98, 1)
MUTED = (0.61, 0.66, 0.74, 1)
GREEN = (0.32, 0.82, 0.62, 1)
RED = (1.0, 0.40, 0.43, 1)

class Card(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = dp(12)
        self.spacing = dp(8)
        self.background_color = PANEL
        with self.canvas.before:
            Color(*PANEL)
            self.bg = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(16)]
            )
        self.bind(pos=self.update_bg, size=self.update_bg)

    def update_bg(self, *_):
        self.bg.pos = self.pos
        self.bg.size = self.size

class CouncilApp(App):
    def build(self):
        self.title = "AI Council"
        Window.clearcolor = BG

        self.cancel_event = threading.Event()
        self.busy = False
        self.models = []
        self.catalog_loading = False
        self.catalog_error = ""
        self.history = []
        self.participants = []
        self.next_participant_id = 1
        self.pending_picker_callback = None

        self.config_path = os.path.join(
            self.user_data_dir, "council_config.json"
        )
        self.history_path = os.path.join(
            self.user_data_dir, "council_history.json"
        )

        self.load_config()
        self.load_history()

        root = BoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(10)
        )

        header = BoxLayout(
            size_hint_y=None, height=dp(58), spacing=dp(10)
        )
        title_box = BoxLayout(orientation="vertical", spacing=0)
        title_box.add_widget(Label(
            text="[b]AI COUNCIL[/b]",
            markup=True, font_size="22sp",
            color=TEXT, halign="left", valign="middle"
        ))
        title_box.add_widget(Label(
            text="Совет искусственного интеллекта",
            font_size="11sp", color=MUTED,
            halign="left", valign="middle"
        ))
        header.add_widget(title_box)

        history_btn = self.make_button("История", PANEL_ALT, width=dp(94))
        history_btn.bind(on_release=self.show_history)
        header.add_widget(history_btn)
        root.add_widget(header)

        main_scroll = ScrollView(do_scroll_x=False)
        content = BoxLayout(
            orientation="vertical",
            size_hint_y=None, spacing=dp(12)
        )
        content.bind(minimum_height=content.setter("height"))

        # API key
        key_card = Card(
            orientation="vertical",
            size_hint_y=None, height=dp(144)
        )
        key_card.add_widget(self.heading("Подключение OpenRouter"))

        key_row = BoxLayout(
            size_hint_y=None, height=dp(44), spacing=dp(6)
        )
        self.key_input = TextInput(
            hint_text="sk-or-v1-...",
            password=True,
            multiline=False,
            text=self.api_key,
            foreground_color=TEXT,
            hint_text_color=MUTED,
            background_color=PANEL_ALT,
            cursor_color=ACCENT,
            padding=[dp(10), dp(11)]
        )
        key_row.add_widget(self.key_input)

        save_key_btn = self.make_button("Сохранить", ACCENT, width=dp(100))
        save_key_btn.bind(on_release=self.save_key)
        key_row.add_widget(save_key_btn)
        key_card.add_widget(key_row)

        self.key_status = Label(
            text="Ключ сохранён локально" if self.api_key else
                 "Введи API-ключ для начала работы",
            color=MUTED, font_size="11sp",
            halign="left", size_hint_y=None, height=dp(20)
        )
        key_card.add_widget(self.key_status)
        content.add_widget(key_card)

        # Question and rounds
        question_card = Card(
            orientation="vertical",
            size_hint_y=None, height=dp(196)
        )
        question_card.add_widget(self.heading("Новая дискуссия"))

        self.question = TextInput(
            hint_text="О чём должны поспорить модели?",
            multiline=True,
            size_hint_y=None, height=dp(96),
            foreground_color=TEXT,
            hint_text_color=MUTED,
            background_color=PANEL_ALT,
            cursor_color=ACCENT,
            padding=dp(10)
        )
        question_card.add_widget(self.question)

        rounds_row = BoxLayout(
            size_hint_y=None, height=dp(36), spacing=dp(8)
        )
        rounds_row.add_widget(Label(
            text="Раунды", color=MUTED,
            size_hint_x=None, width=dp(70), halign="left"
        ))
        self.rounds_label = Label(
            text=str(self.rounds_value),
            color=TEXT, size_hint_x=None, width=dp(28)
        )
        self.round_slider = Slider(
            min=1, max=MAX_ROUNDS, step=1,
            value=self.rounds_value
        )
        self.round_slider.bind(
            value=self.on_rounds_change
        )
        rounds_row.add_widget(self.round_slider)
        rounds_row.add_widget(self.rounds_label)
        question_card.add_widget(rounds_row)
        content.add_widget(question_card)

        # Protection toggles
        safety_card = Card(
            orientation="vertical",
            size_hint_y=None, height=dp(186)
        )
        safety_card.add_widget(self.heading("Надёжность"))

        self.retry_enabled = self.config.get("retry", True)
        self.fallback_enabled = self.config.get("fallback", True)
        self.continue_enabled = self.config.get("continue_on_error", True)

        self.retry_btn = self.make_button("", PANEL_ALT)
        self.fallback_btn = self.make_button("", PANEL_ALT)
        self.continue_btn = self.make_button("", PANEL_ALT)

        self.retry_btn.bind(on_release=lambda *_: self.toggle_setting("retry"))
        self.fallback_btn.bind(on_release=lambda *_: self.toggle_setting("fallback"))
        self.continue_btn.bind(on_release=lambda *_: self.toggle_setting("continue"))

        safety_card.add_widget(self.retry_btn)
        safety_card.add_widget(self.fallback_btn)
        safety_card.add_widget(self.continue_btn)
        self.update_toggle_labels()
        content.add_widget(safety_card)

        # Participants
        people_card = Card(
            orientation="vertical",
            size_hint_y=None, height=dp(350)
        )
        people_card.bind(minimum_height=people_card.setter("height"))
        people_card.add_widget(self.heading("Участники"))

        self.people_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None, spacing=dp(8)
        )
        self.people_list.bind(
            minimum_height=self.people_list.setter("height")
        )
        people_card.add_widget(self.people_list)

        people_controls = BoxLayout(
            size_hint_y=None, height=dp(44), spacing=dp(8)
        )
        add_btn = self.make_button("+ Добавить ИИ", PANEL_ALT)
        add_btn.bind(on_release=self.add_participant)
        people_controls.add_widget(add_btn)

        catalog_btn = self.make_button("Каталог моделей", ACCENT)
        catalog_btn.bind(on_release=self.load_catalog)
        people_controls.add_widget(catalog_btn)
        people_card.add_widget(people_controls)
        content.add_widget(people_card)

        # Judge
        judge_card = Card(
            orientation="vertical",
            size_hint_y=None, height=dp(100)
        )
        judge_card.add_widget(self.heading("Судья"))

        self.judge_model = self.config.get("judge_model", "")
        self.judge_btn = self.make_button(
            self.judge_model or "Выбрать модель судьи",
            PANEL_ALT
        )
        self.judge_btn.bind(
            on_release=lambda *_: self.open_model_picker(
                callback=self.set_judge
            )
        )
        judge_card.add_widget(self.judge_btn)
        content.add_widget(judge_card)

        # Results
        result_card = Card(
            orientation="vertical",
            size_hint_y=None, height=dp(310)
        )
        result_card.add_widget(self.heading("Ход дебатов"))

        self.status = Label(
            text="Готов к работе",
            color=GREEN, size_hint_y=None,
            height=dp(25), halign="left"
        )
        result_card.add_widget(self.status)

        self.output = Label(
            text="Здесь появятся ответы участников и итог судьи.",
            color=TEXT, font_size="13sp",
            size_hint_y=None, halign="left", valign="top"
        )
        self.output.bind(
            width=lambda obj, w: setattr(obj, "text_size", (w, None)),
            texture_size=lambda obj, s: setattr(obj, "height", s[1])
        )

        output_scroll = ScrollView(do_scroll_x=False)
        output_scroll.add_widget(self.output)
        result_card.add_widget(output_scroll)
        content.add_widget(result_card)

        main_scroll.add_widget(content)
        root.add_widget(main_scroll)

        # Fixed bottom controls
        bottom = BoxLayout(
            size_hint_y=None, height=dp(52), spacing=dp(8)
        )
        self.run_btn = self.make_button("Начать дебаты", ACCENT)
        self.run_btn.bind(on_release=self.start_debate)
        bottom.add_widget(self.run_btn)

        self.cancel_btn = self.make_button("Стоп", RED, width=dp(76))
        self.cancel_btn.disabled = True
        self.cancel_btn.bind(on_release=self.cancel_debate)
        bottom.add_widget(self.cancel_btn)
        root.add_widget(bottom)

        self.refresh_participants()
        return root

    def load_config(self):
        self.config = {}
        self.api_key = ""
        self.rounds_value = 3

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            self.api_key = self.config.get("api_key", "")
            self.rounds_value = max(
                1, min(MAX_ROUNDS, int(self.config.get("rounds", 3)))
            )
        except (OSError, ValueError, TypeError):
            pass

        self.retry_enabled = self.config.get("retry", True)
        self.fallback_enabled = self.config.get("fallback", True)
        self.continue_enabled = self.config.get("continue_on_error", True)

        saved = self.config.get("participants", [])
        for item in saved:
            self.participants.append({
                "uid": self.next_participant_id,
                "model": item.get("model", ""),
                "enabled": item.get("enabled", True)
            })
            self.next_participant_id += 1

        if not self.participants:
            for _ in range(3):
                self.participants.append({
                    "uid": self.next_participant_id,
                    "model": "",
                    "enabled": True
                })
                self.next_participant_id += 1

    def save_config(self, *_):
        data = {
            "api_key": self.key_input.text.strip() if hasattr(self, "key_input") else self.api_key,
            "rounds": int(self.round_slider.value) if hasattr(self, "round_slider") else self.rounds_value,
            "retry": self.retry_enabled,
            "fallback": self.fallback_enabled,
            "continue_on_error": self.continue_enabled,
            "judge_model": self.judge_model,
            "participants": [
                {"model": p["model"], "enabled": p["enabled"]}
                for p in self.participants
            ]
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
        except OSError:
            return False

    def save_key(self, *_):
        self.api_key = self.key_input.text.strip()
        if self.save_config():
            self.key_status.text = "Ключ сохранён"
            self.show_notice("Настройки", "API-ключ сохранён в приватной папке приложения.")
        else:
            self.key_status.text = "Не удалось сохранить ключ"

    def load_history(self):
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                self.history = json.load(f)
            if not isinstance(self.history, list):
                self.history = []
        except (OSError, ValueError, TypeError):
            self.history = []

    def save_history(self, entry):
        self.history.insert(0, entry)
        self.history = self.history[:100]
        try:
            temp = self.history_path + ".tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
            os.replace(temp, self.history_path)
        except OSError:
            self.publish("Не удалось сохранить историю на устройстве.")

    def make_button(self, text, color, width=None):
        btn = Button(
            text=text,
            size_hint_x=None if width else 1,
            width=width or 0,
            size_hint_y=None,
            height=dp(42),
            background_normal="",
            background_down="",
            background_color=color,
            color=TEXT,
            font_size="12sp"
        )
        return btn

    def heading(self, text):
        return Label(
            text=f"[b]{text}[/b]",
            markup=True, color=TEXT,
            font_size="15sp", halign="left",
            size_hint_y=None, height=dp(26)
        )

    def on_rounds_change(self, _slider, value):
        self.rounds_value = int(value)
        self.rounds_label.text = str(self.rounds_value)
        if hasattr(self, "config"):
            self.save_config()

    def toggle_setting(self, setting):
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
        self.retry_btn.text = (
            "Повтор запросов: ВКЛ" if self.retry_enabled
            else "Повтор запросов: ВЫКЛ"
        )
        self.fallback_btn.text = (
            "Резервные модели: ВКЛ" if self.fallback_enabled
            else "Резервные модели: ВЫКЛ"
        )
        self.continue_btn.text = (
            "Продолжать при ошибках: ВКЛ" if self.continue_enabled
            else "Продолжать при ошибках: ВЫКЛ"
        )

    def add_participant(self, *_):
        if self.busy:
            return
        self.participants.append({
            "uid": self.next_participant_id,
            "model": "",
            "enabled": True
        })
        self.next_participant_id += 1
        self.refresh_participants()
        self.save_config()

    def remove_participant(self, uid):
        if self.busy:
            return
        self.participants = [
            p for p in self.participants if p["uid"] != uid
        ]
        self.refresh_participants()
        self.save_config()

    def refresh_participants(self):
        if not hasattr(self, "people_list"):
            return

        self.people_list.clear_widgets()

        for p in self.participants:
            row = Card(
                orientation="horizontal",
                size_hint_y=None, height=dp(74)
            )

            details = BoxLayout(orientation="vertical", spacing=dp(3))
            model_name = p["model"] or "Модель не выбрана"
            details.add_widget(Label(
                text=model_name,
                color=TEXT, halign="left", valign="middle",
                font_size="12sp", shorten=True,
                shorten_from="right"
            ))
            details.add_widget(Label(
                text="Участник включён" if p["enabled"] else "Выключен",
                color=GREEN if p["enabled"] else MUTED,
                font_size="10sp", halign="left"
            ))
            row.add_widget(details)

            choose = self.make_button("Выбрать", ACCENT, width=dp(76))
            choose.bind(
                on_release=lambda _btn, uid=p["uid"]:
                self.open_model_picker(
                    callback=lambda model: self.set_participant_model(uid, model)
                )
            )
            row.add_widget(choose)

            toggle = self.make_button(
                "Вкл." if p["enabled"] else "Выкл.",
                PANEL_ALT, width=dp(56)
            )
            toggle.bind(
                on_release=lambda _btn, uid=p["uid"]:
                self.toggle_participant(uid)
            )
            row.add_widget(toggle)

            remove = self.make_button("×", RED, width=dp(38))
            remove.bind(
                on_release=lambda _btn, uid=p["uid"]:
                self.remove_participant(uid)
            )
            row.add_widget(remove)

            self.people_list.add_widget(row)

        self.people_list.height = sum(
            dp(82) for _ in self.participants
        )

    def toggle_participant(self, uid):
        if self.busy:
            return
        for p in self.participants:
            if p["uid"] == uid:
                p["enabled"] = not p["enabled"]
        self.refresh_participants()
        self.save_config()

    def set_participant_model(self, uid, model):
        for p in self.participants:
            if p["uid"] == uid:
                p["model"] = model["id"]
        self.refresh_participants()
        self.save_config()

    def set_judge(self, model):
        self.judge_model = model["id"]
        self.judge_btn.text = model["id"]
        self.save_config()

    def load_catalog(self, *_):
        if self.catalog_loading:
            return

        self.catalog_loading = True
        self.status.text = "Загружаю каталог OpenRouter..."
        self.run_btn.disabled = True

        threading.Thread(
            target=self._fetch_catalog, daemon=True
        ).start()

    def _fetch_catalog(self):
        try:
            response = requests.get(
                API_ROOT + "/models",
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json().get("data", [])
            self.models = [
                m for m in data
                if isinstance(m, dict) and m.get("id")
            ]
            self.models.sort(
                key=lambda m: m.get("name", m["id"]).lower()
            )
            self.catalog_error = ""
            Clock.schedule_once(
                lambda _dt: self._catalog_loaded()
            )
        except Exception as exc:
            self.catalog_error = type(exc).__name__
            Clock.schedule_once(
                lambda _dt: self._catalog_failed()
            )

    def _catalog_loaded(self):
        self.catalog_loading = False
        self.run_btn.disabled = self.busy
        self.status.text = f"Загружено моделей: {len(self.models)}"

        callback = self.pending_picker_callback
        self.pending_picker_callback = None
        self.open_model_picker(callback=callback)

    def _catalog_failed(self):
        self.catalog_loading = False
        self.run_btn.disabled = self.busy
        self.status.text = "Ошибка загрузки каталога"
        self.show_notice(
            "Ошибка каталога",
            "Не удалось загрузить модели. Проверь интернет-соединение. "
            "Техническая ошибка: " + self.catalog_error
        )

    def open_model_picker(self, callback=None, *_):
        if not self.models:
            self.pending_picker_callback = callback
            self.load_catalog()
            return

        popup_box = BoxLayout(
            orientation="vertical", padding=dp(12), spacing=dp(8)
        )
        search = TextInput(
            hint_text="Поиск модели...",
            multiline=False, size_hint_y=None, height=dp(44),
            foreground_color=TEXT, background_color=PANEL_ALT
        )

        filter_row = BoxLayout(
            size_hint_y=None, height=dp(40), spacing=dp(6)
        )
        free_only = {"value": False}
        free_btn = self.make_button("Все модели", PANEL_ALT)
        filter_row.add_widget(free_btn)
        popup_box.add_widget(search)
        popup_box.add_widget(filter_row)

        results = GridLayout(
            cols=1, spacing=dp(6), size_hint_y=None
        )
        results.bind(minimum_height=results.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(results)
        popup_box.add_widget(scroll)

        popup = Popup(
            title="Каталог моделей OpenRouter",
            content=popup_box,
            size_hint=(0.95, 0.88)
        )

        def price_is_free(model):
            pricing = model.get("pricing", {})
            try:
                return (
                    float(pricing.get("prompt", -1)) == 0
                    and float(pricing.get("completion", -1)) == 0
                )
            except (ValueError, TypeError):
                return False

        def render(*_):
            results.clear_widgets()
            query = search.text.lower().strip()
            candidates = []

            for model in self.models:
                name = model.get("name", "")
                model_id = model.get("id", "")
                if query and query not in name.lower() and query not in model_id.lower():
                    continue
                if free_only["value"] and not price_is_free(model):
                    continue
                candidates.append(model)

            if not candidates:
                results.add_widget(Label(
                    text="Модели не найдены",
                    size_hint_y=None, height=dp(45), color=MUTED
                ))

            for model in candidates[:250]:
                name = model.get("name", model["id"])
                model_id = model["id"]
                tag = "FREE" if price_is_free(model) else "Платная"
                btn = Button(
                    text=f"{name}\n{model_id}  ·  {tag}",
                    size_hint_y=None, height=dp(64),
                    halign="left", valign="middle",
                    text_size=(Window.width * 0.78, None),
                    background_normal="",
                    background_color=PANEL_ALT,
                    color=TEXT, font_size="11sp"
                )
                btn.bind(
                    on_release=lambda _btn, m=model:
                    select_model(m)
                )
                results.add_widget(btn)

        def select_model(model):
            if callback:
                callback(model)
            popup.dismiss()

        def toggle_free(*_):
            free_only["value"] = not free_only["value"]
            free_btn.text = (
                "Только бесплатные" if free_only["value"]
                else "Все модели"
            )
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

        if not key:
            self.show_notice("Нет API-ключа", "Введи и сохрани ключ OpenRouter.")
            return
        if not question:
            self.show_notice("Нет вопроса", "Напиши вопрос для дебатов.")
            return

        active = [
            p.copy() for p in self.participants
            if p["enabled"] and p["model"]
        ]
        if len(active) < 2:
            self.show_notice(
                "Мало участников",
                "Выбери модели минимум для двух включённых участников."
            )
            return

        judge = self.judge_model or active[0]["model"]
        self.save_config()
        self.cancel_event.clear()
        self.busy = True
        self.run_btn.disabled = True
        self.cancel_btn.disabled = False
        self.output.text = "Запускаю дебаты..."
        self.status.text = "Участники готовятся"

        settings = {
            "key": key,
            "question": question,
            "rounds": int(self.round_slider.value),
            "participants": active,
            "judge": judge,
            "retry": self.retry_enabled,
            "fallback": self.fallback_enabled,
            "continue_on_error": self.continue_enabled,
            "models": list(self.models)
        }

        threading.Thread(
            target=self.run_debate,
            args=(settings,),
            daemon=True
        ).start()

    def request_model(self, key, model_id, prompt):
        headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "X-Title": "AI Council"
        }
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.6,
            "max_tokens": 3000
        }

        response = requests.post(
            API_ROOT + "/chat/completions",
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            message = ""
            try:
                message = response.json().get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                pass
            raise RuntimeError(
                f"HTTP {response.status_code}: {message[:180]}"
            )

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        if isinstance(content, list):
            content = "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Модель вернула пустой ответ")

        return content.strip()

    def ask_safely(self, settings, model_id, prompt):
        candidates = [model_id]
        errors = []

        if settings["fallback"]:
            free_models = []
            for model in settings["models"]:
                pricing = model.get("pricing", {})
                try:
                    free = (
                        float(pricing.get("prompt", -1)) == 0
                        and float(pricing.get("completion", -1)) == 0
                    )
                except (TypeError, ValueError):
                    free = False

                mid = model.get("id", "")
                if free and mid and mid != model_id:
                    free_models.append(mid)

            candidates.extend(free_models[:3])

        for candidate in candidates:
            attempts = MAX_RETRIES + 1 if settings["retry"] else 1

            for attempt in range(attempts):
                if self.cancel_event.is_set():
                    return None, candidate, "Отменено"

                try:
                    answer = self.request_model(
                        settings["key"], candidate, prompt
                    )
                    return answer, candidate, None

                except requests.RequestException as exc:
                    error = type(exc).__name__
                    errors.append(f"{candidate}: {error}")
                    if attempt + 1 < attempts:
                        time.sleep(min(2 ** attempt, 4))
                        continue
                    break

                except RuntimeError as exc:
                    error = str(exc)
                    errors.append(f"{candidate}: {error}")

                    transient = any(
                        code in error
                        for code in ("HTTP 429", "HTTP 500",
                                     "HTTP 502", "HTTP 503", "HTTP 504")
                    )
                    if transient and attempt + 1 < attempts:
                        time.sleep(min(2 ** attempt, 4))
                        continue
                    break

                except (ValueError, KeyError, IndexError, TypeError):
                    errors.append(f"{candidate}: некорректный ответ")
                    break

        return None, model_id, "; ".join(errors[-4:]) or "Нет ответа"

    def run_debate(self, settings):
        question = settings["question"]
        rounds = settings["rounds"]
        participants = settings["participants"]
        transcript = []
        successful = []

        try:
            for round_number in range(1, rounds + 1):
                if self.cancel_event.is_set():
                    break

                self.publish(
                    f"Раунд {round_number}/{rounds}\n"
                    "Участники формируют ответы..."
                )

                if round_number == 1:
                    prompt = (
                        "Ты участник интеллектуальных дебатов. "
                        "Ответь самостоятельно, приводи обоснования и "
                        "отмечай неопределённость.\n\nВопрос: " + question
                    )
                else:
                    previous = "\n\n".join(
                        f"{item['name']}:\n{item['answer']}"
                        for item in successful
                    )
                    prompt = (
                        f"Исходный вопрос: {question}\n"
                        f"Раунд: {round_number}\n\n"
                        f"Предыдущие ответы:\n{previous}\n\n"
                        "Критически проанализируй аргументы других "
                        "участников. Исправь собственные ошибки, укажи "
                        "сильные и слабые места и дай улучшенный ответ. "
                        "Не соглашайся автоматически."
                    )

                round_items = []

                with ThreadPoolExecutor(
                    max_workers=min(5, len(participants))
                ) as executor:
                    future_map = {
                        executor.submit(
                            self.ask_safely, settings,
                            p["model"], prompt
                        ): p
                        for p in participants
                    }

                    for future in as_completed(future_map):
                        if self.cancel_event.is_set():
                            break

                        participant = future_map[future]
                        try:
                            answer, used_model, error = future.result()
                        except Exception as exc:
                            answer, used_model, error = (
                                None, participant["model"],
                                type(exc).__name__
                            )

                        name = participant["model"]

                        if answer:
                            item = {
                                "round": round_number,
                                "name": name,
                                "used_model": used_model,
                                "answer": answer
                            }
                            round_items.append(item)
                            successful.append(item)
                            self.publish(
                                f"Раунд {round_number}/{rounds}\n"
                                f"Получен ответ: {name}\n\n" + answer
                            )
                        else:
                            round_items.append({
                                "round": round_number,
                                "name": name,
                                "error": error
                            })
                            self.publish(
                                f"Раунд {round_number}/{rounds}\n"
                                f"{name}: ошибка\n{error}"
                            )

                transcript.extend(round_items)

                if not any("answer" in item for item in round_items):
                    if not settings["continue_on_error"]:
                        break

                if not settings["continue_on_error"] and any(
                    "error" in item for item in round_items
                ):
                    break

            if self.cancel_event.is_set():
                final_answer = "Дебаты остановлены пользователем."
            elif not successful:
                final_answer = (
                    "Ни один участник не ответил. Проверь ключ, "
                    "доступность моделей и лимиты OpenRouter."
                )
            else:
                judge_prompt = (
                    "Ты независимый судья интеллектуальных дебатов.\n"
                    f"Вопрос: {question}\n\n"
                    "Оцени ответы, выдели сильные аргументы, разногласия "
                    "и ошибки. Не придумывай факты. Если участник не "
                    "ответил, не считай это доказательством проигрыша.\n"
                    "Сформулируй обоснованный итог.\n\n"
                    + "\n\n".join(
                        f"Раунд {item['round']} — {item['name']}:\n"
                        f"{item['answer']}"
                        for item in successful
                    )
                )

                self.publish("Судья формирует итог...")
                judge_answer, actual_judge, judge_error = self.ask_safely(
                    settings, settings["judge"], judge_prompt
                )

                transcript_text = "\n\n".join(
                    f"Раунд {item['round']} — {item['name']}\n{item['answer']}"
                    if "answer" in item
                    else (
                        f"Раунд {item.get('round')} — {item.get('name')}\n"
                        f"Ошибка: {item.get('error')}"
                    )
                    for item in transcript
                )

                if judge_answer:
                    final_answer = (
                        "=== ОТВЕТЫ УЧАСТНИКОВ ===\n\n"
                        + transcript_text
                        + "\n\n=== ИТОГ СУДЬИ ===\n\n"
                        + f"Модель: {actual_judge}\n\n"
                        + judge_answer
                    )
                else:
                    final_answer = (
                        "=== ОТВЕТЫ УЧАСТНИКОВ ===\n\n"
                        + transcript_text
                        + "\n\n=== ИТОГ СУДЬИ (ОШИБКА) ===\n\n"
                        "Не удалось получить итог судьи.\n"
                        f"Причина: {judge_error}\n\n"
                        "Ответы участников сохранены в истории."
                    )

            entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "question": question,
                "rounds": rounds,
                "judge": settings["judge"],
                "transcript": transcript,
                "final": final_answer
            }

            if self.config.get("save_history", True):
                Clock.schedule_once(
                    lambda _dt, item=entry: self.save_history(item)
                )

            self.publish(final_answer)
            Clock.schedule_once(
                lambda _dt, text=final_answer:
                self.finish_debate(text)
            )

        except Exception as exc:
            self.publish(
                "Ошибка во время дебатов: " + type(exc).__name__
            )
            Clock.schedule_once(lambda _dt: self.finish_ui())

    def publish(self, text):
        Clock.schedule_once(
            lambda _dt, value=str(text):
            setattr(self.output, "text", value)
        )

    def finish_debate(self, text):
        self.output.text = text
        self.status.text = "Дебаты завершены"
        self.finish_ui()

    def finish_ui(self):
        self.busy = False
        self.run_btn.disabled = False
        self.cancel_btn.disabled = True

    def cancel_debate(self, *_):
        self.cancel_event.set()
        self.status.text = "Останавливаю дебаты..."

    def show_history(self, *_):
        if not self.history:
            self.show_notice("История", "Сохранённых дебатов пока нет.")
            return

        box = BoxLayout(
            orientation="vertical", padding=dp(10), spacing=dp(8)
        )
        scroll = ScrollView()
        items = GridLayout(
            cols=1, spacing=dp(6), size_hint_y=None
        )
        items.bind(minimum_height=items.setter("height"))

        for entry in self.history:
            question = entry.get("question", "Без вопроса")
            date = entry.get("timestamp", "")
            btn = Button(
                text=f"{date}\n{question}",
                size_hint_y=None, height=dp(66),
                halign="left", valign="middle",
                background_normal="", background_color=PANEL_ALT,
                color=TEXT
            )
            btn.bind(
                on_release=lambda _btn, e=entry:
                self.open_history_entry(e, popup)
            )
            items.add_widget(btn)

        scroll.add_widget(items)
        box.add_widget(scroll)

        clear_btn = self.make_button("Очистить историю", RED)
        clear_btn.bind(on_release=lambda *_: self.clear_history(popup))
        box.add_widget(clear_btn)

        popup = Popup(
            title="История дебатов", content=box,
            size_hint=(0.94, 0.84)
        )
        popup.open()

    def open_history_entry(self, entry, popup):
        popup.dismiss()
        text = (
            f"ВОПРОС\n{entry.get('question', '')}\n\n"
            f"ИТОГ\n{entry.get('final', '')}\n\n"
            "ОТВЕТЫ УЧАСТНИКОВ\n"
        )
        for item in entry.get("transcript", []):
            if "answer" in item:
                text += (
                    f"\nРаунд {item['round']} — {item['name']}\n"
                    f"{item['answer']}\n"
                )
            else:
                text += (
                    f"\nРаунд {item.get('round')} — {item.get('name')}\n"
                    f"Ошибка: {item.get('error')}\n"
                )
        self.output.text = text
        self.status.text = "Просмотр сохранённого дебата"

    def clear_history(self, popup):
        self.history = []
        try:
            if os.path.exists(self.history_path):
                os.remove(self.history_path)
        except OSError:
            self.show_notice(
                "Ошибка", "Не удалось удалить файл истории."
            )
        popup.dismiss()

    def show_notice(self, title, message):
        Popup(
            title=title,
            content=Label(
                text=message, color=TEXT,
                text_size=(Window.width * 0.78, None)
            ),
            size_hint=(0.88, 0.35)
        ).open()

if __name__ == "__main__":
    CouncilApp().run()
