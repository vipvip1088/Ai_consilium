import os
import json
import threading
import concurrent.futures
import requests

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup


CONFIG_NAME = "council_config.json"
DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1"


class CouncilApp(App):
    def build(self):
        self.title = "AI Council"
        self.cancel_event = threading.Event()
        self.busy = False
        self.participants = []
        self.fields = []

        self.root_box = BoxLayout(
            orientation="vertical",
            padding=dp(10),
            spacing=dp(8)
        )

        self.root_box.add_widget(Label(
            text="AI COUNCIL",
            size_hint_y=None,
            height=dp(42),
            font_size="22sp"
        ))

        self.root_box.add_widget(Label(
            text="Раунды дебатов:",
            size_hint_y=None,
            height=dp(26)
        ))

        self.rounds = TextInput(
            text="3",
            multiline=False,
            input_filter="int",
            size_hint_y=None,
            height=dp(44)
        )
        self.root_box.add_widget(self.rounds)

        self.root_box.add_widget(Label(
            text="Вопрос:",
            size_hint_y=None,
            height=dp(26)
        ))

        self.question = TextInput(
            hint_text="Напиши вопрос для дебатов...",
            size_hint_y=None,
            height=dp(110)
        )
        self.root_box.add_widget(self.question)

        self.root_box.add_widget(Label(
            text="Участники",
            size_hint_y=None,
            height=dp(30)
        ))

        self.participant_list = GridLayout(
            cols=1,
            spacing=dp(8),
            size_hint_y=None
        )
        self.participant_list.bind(
            minimum_height=self.participant_list.setter("height")
        )

        scroll = ScrollView(size_hint_y=0.45)
        scroll.add_widget(self.participant_list)
        self.root_box.add_widget(scroll)

        controls = BoxLayout(
            size_hint_y=None,
            height=dp(48),
            spacing=dp(6)
        )

        add_btn = Button(text="+ ИИ")
        add_btn.bind(on_press=self.add_participant)
        controls.add_widget(add_btn)

        self.run_btn = Button(text="Запустить")
        self.run_btn.bind(on_press=self.start_debate)
        controls.add_widget(self.run_btn)

        self.cancel_btn = Button(
            text="Отмена",
            disabled=True
        )
        self.cancel_btn.bind(on_press=self.cancel_debate)
        controls.add_widget(self.cancel_btn)

        self.root_box.add_widget(controls)

        self.output = Label(
            text="Добавь участников и задай вопрос.",
            size_hint_y=None,
            halign="left",
            valign="top"
        )
        self.output.bind(
            width=lambda obj, width: setattr(
                obj, "text_size", (width, None)
            ),
            texture_size=lambda obj, size: setattr(
                obj, "height", size[1]
            )
        )

        result_scroll = ScrollView(size_hint_y=0.5)
        result_scroll.add_widget(self.output)
        self.root_box.add_widget(result_scroll)

        self.load_config()
        if not self.fields:
            self.add_participant()
            self.add_participant()
            self.add_participant()

        return self.root_box

    def add_participant(self, *args, data=None):
        data = data or {}

        card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(205),
            padding=dp(6),
            spacing=dp(4)
        )

        def field(hint, value="", password=False):
            item = TextInput(
                hint_text=hint,
                text=value,
                multiline=False,
                password=password,
                size_hint_y=None,
                height=dp(38)
            )
            card.add_widget(item)
            return item

        endpoint = field(
            "API endpoint",
            data.get("endpoint", DEFAULT_ENDPOINT)
        )
        model = field(
            "Модель, например provider/model",
            data.get("model", "")
        )
        key = field(
            "API-ключ (только в памяти)",
            "",
            password=True
        )

        row = BoxLayout(
            size_hint_y=None,
            height=dp(34)
        )
        enabled = Button(
            text="Участник включён",
            size_hint_x=0.7
        )
        enabled.state = "down"
        enabled.bind(on_press=lambda btn: self.toggle_enabled(btn))
        row.add_widget(enabled)

        remove = Button(text="Удалить")
        row.add_widget(remove)
        card.add_widget(row)

        record = {
            "card": card,
            "endpoint": endpoint,
            "model": model,
            "key": key,
            "enabled": enabled
        }
        self.fields.append(record)

        remove.bind(
            on_press=lambda *_: self.remove_participant(record)
        )

        self.participant_list.add_widget(card)

    def toggle_enabled(self, button):
        button.state = (
            "normal" if button.state == "down" else "down"
        )
        button.text = (
            "Участник включён"
            if button.state == "down"
            else "Участник выключен"
        )

    def remove_participant(self, record):
        if self.busy:
            return
        if record in self.fields:
            self.fields.remove(record)
            self.participant_list.remove_widget(record["card"])

    def load_config(self):
        path = os.path.join(self.user_data_dir, CONFIG_NAME)
        try:
            with open(path, "r", encoding="utf-8") as file:
                config = json.load(file)

            self.rounds.text = str(
                max(1, min(10, int(config.get("rounds", 3))))
            )

            for participant in config.get("participants", []):
                self.add_participant(data=participant)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    def save_config(self):
        config = {
            "rounds": int(self.rounds.text or "3"),
            "participants": [
                {
                    "endpoint": p["endpoint"].text.strip(),
                    "model": p["model"].text.strip()
                }
                for p in self.fields
            ]
        }

        path = os.path.join(self.user_data_dir, CONFIG_NAME)
        temp = path + ".tmp"

        try:
            with open(temp, "w", encoding="utf-8") as file:
                json.dump(config, file, ensure_ascii=False, indent=2)
            os.replace(temp, path)
        except OSError:
            try:
                os.remove(temp)
            except OSError:
                pass

    def start_debate(self, *_):
        if self.busy:
            return

        question = self.question.text.strip()
        if not question:
            self.show_error("Введи вопрос.")
            return

        try:
            rounds = int(self.rounds.text)
            if not 1 <= rounds <= 10:
                raise ValueError
        except ValueError:
            self.show_error("Количество раундов: от 1 до 10.")
            return

        participants = []
        for p in self.fields:
            if p["enabled"].state != "down":
                continue

            endpoint = p["endpoint"].text.strip().rstrip("/")
            model = p["model"].text.strip()
            key = p["key"].text.strip()

            if not endpoint or not model or not key:
                self.show_error(
                    "У каждого включённого участника должны быть "
                    "указаны endpoint, модель и API-ключ."
                )
                return

            if not endpoint.startswith("https://"):
                self.show_error("Разрешены только HTTPS endpoint.")
                return

            participants.append({
                "endpoint": endpoint,
                "model": model,
                "key": key
            })

        if len(participants) < 2:
            self.show_error("Нужно минимум два участника.")
            return

        self.save_config()
        self.cancel_event.clear()
        self.busy = True
        self.run_btn.disabled = True
        self.cancel_btn.disabled = False
        self.output.text = "Начинаем дебаты..."

        threading.Thread(
            target=self.run_debate,
            args=(question, rounds, participants),
            daemon=True
        ).start()

    def ask_model(self, participant, messages):
        url = participant["endpoint"] + "/chat/completions"

        headers = {
            "Authorization": "Bearer " + participant["key"],
            "Content-Type": "application/json"
        }
        payload = {
            "model": participant["model"],
            "messages": messages,
            "temperature": 0.7
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=(10, 90)
            )

            if response.status_code != 200:
                return (
                    f"[Ошибка HTTP {response.status_code}] "
                    f"{response.text[:300]}"
                )

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            if isinstance(content, list):
                content = "\n".join(
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict)
                )

            if not isinstance(content, str) or not content.strip():
                return "[Ошибка: пустой ответ модели]"

            return content.strip()

        except requests.RequestException as exc:
            return f"[Сетевая ошибка: {type(exc).__name__}]"
        except (ValueError, KeyError, IndexError, TypeError):
            return "[Ошибка: некорректный ответ API]"

    def run_debate(self, question, rounds, participants):
        try:
            history = []
            results = []

            for round_number in range(1, rounds + 1):
                if self.cancel_event.is_set():
                    break

                self.publish(
                    f"Раунд {round_number}/{rounds}: "
                    "участники готовят ответы..."
                )

                def make_messages():
                    if round_number == 1:
                        return [{"role": "user", "content": question}]

                    previous = "\n\n".join(
                        f"{name}:\n{answer}"
                        for name, answer in history
                    )
                    return [{
                        "role": "user",
                        "content": (
                            f"Исходный вопрос: {question}\n"
                            f"Раунд: {round_number}\n\n"
                            f"Предыдущие ответы:\n{previous}\n\n"
                            "Проанализируй аргументы других участников. "
                            "Укажи сильные и слабые стороны, исправь "
                            "ошибки и представь собственный ответ. "
                            "Не соглашайся автоматически."
                        )
                    }]

                messages = make_messages()
                round_results = []

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(5, len(participants))
                ) as pool:
                    futures = {
                        pool.submit(self.ask_model, p, messages): p
                        for p in participants
                    }

                    for future in concurrent.futures.as_completed(futures):
                        if self.cancel_event.is_set():
                            break

                        p = futures[future]
                        try:
                            answer = future.result()
                        except Exception:
                            answer = "[Внутренняя ошибка участника]"

                        name = p["model"]
                        round_results.append((name, answer))

                if self.cancel_event.is_set():
                    break

                if not round_results:
                    results.append("Раунд не дал результатов.")
                    break

                history.extend(round_results)
                results.append(
                    f"=== РАУНД {round_number} ===\n" +
                    "\n\n".join(
                        f"{name}\n{answer}"
                        for name, answer in round_results
                    )
                )

                self.publish("\n\n".join(results))

            if self.cancel_event.is_set():
                final_text = "Дебаты отменены.\n\n" + "\n\n".join(results)
            elif not history:
                final_text = "Не удалось получить ни одного ответа."
            else:
                self.publish("Судья готовит итоговый ответ...")

                judge_prompt = (
                    f"Исходный вопрос: {question}\n\n"
                    "Ниже представлены ответы участников разных раундов:\n"
                    + "\n\n".join(
                        f"{name}:\n{answer}"
                        for name, answer in history
                    )
                    + "\n\nСравни аргументы, отметь разногласия, "
                    "не выдумывай факты и сформулируй обоснованный "
                    "итоговый ответ."
                )

                judge = self.ask_model(
                    participants[0],
                    [{"role": "user", "content": judge_prompt}]
                )

                final_text = (
                    "\n\n".join(results)
                    + "\n\n=== ИТОГ СУДЬИ ===\n"
                    + judge
                )

            self.publish(final_text)

        except Exception as exc:
            self.publish(
                f"Ошибка дебатов: {type(exc).__name__}"
            )
        finally:
            Clock.schedule_once(self.finish, 0)

    def publish(self, text):
        Clock.schedule_once(
            lambda dt, value=text: setattr(self.output, "text", value)
        )

    def finish(self, _dt):
        self.busy = False
        self.run_btn.disabled = False
        self.cancel_btn.disabled = True

        for p in self.fields:
            p["key"].text = ""

    def cancel_debate(self, *_):
        self.cancel_event.set()
        self.output.text = (
            "Отмена запрошена. Ожидаем завершения текущих запросов..."
        )

    def show_error(self, message):
        Popup(
            title="Проверка данных",
            content=Label(text=message),
            size_hint=(0.9, 0.35)
        ).open()


if __name__ == "__main__":
    CouncilApp().run()
