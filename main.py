from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.clock import Clock
import requests
import concurrent.futures
import threading
import json
import os

MODEL_A_MAIN = "nvidia/nemotron-3-ultra-550b-a55b:free"
MODEL_B_MAIN = "poolside/laguna-s-2.1:free"
MODEL_C_MAIN = "nvidia/nemotron-3-super-120b-a12b:free"
JUDGE_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"

FALLBACK_POOL = [
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-26b-a4b-it:free",
    "openrouter/free"
]

class CouncilApp(App):
    def get_config_path(self):
        try:
            d = self.user_data_dir
        except Exception:
            d = "."
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "config.json")

    def load_api_key(self):
        try:
            path = self.get_config_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f).get("api_key", "")
        except Exception:
            pass
        return ""

    def save_api_key(self, key):
        try:
            path = self.get_config_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"api_key": key}, f)
            return True
        except Exception:
            return False

    def build(self):
        self.title = "AI Council"
        root = BoxLayout(orientation="vertical", padding=10, spacing=8)

        root.add_widget(Label(text="API-ключ OpenRouter:", size_hint_y=None, height=30))
        key_row = BoxLayout(size_hint_y=None, height=45, spacing=5)
        self.key_input = TextInput(text=self.load_api_key(), hint_text="sk-or-v1-...", multiline=False)
        key_row.add_widget(self.key_input)
        save_btn = Button(text="💾", size_hint_x=0.2)
        save_btn.bind(on_press=self.save_key)
        key_row.add_widget(save_btn)
        root.add_widget(key_row)

        root.add_widget(Label(text="Вопрос:", size_hint_y=None, height=30))
        self.input = TextInput(hint_text="Введи вопрос...", size_hint_y=0.3)
        root.add_widget(self.input)

        self.btn = Button(text="🚀 Запустить дебаты", size_hint_y=0.1)
        self.btn.bind(on_press=self.start)
        root.add_widget(self.btn)

        scroll = ScrollView()
        self.output = Label(
            text="Готов к работе...",
            size_hint_y=None,
            valign="top",
            halign="left"
        )
        self.output.bind(
            width=lambda *args: setattr(self.output, 'text_size', (self.output.width, None)),
            texture_size=lambda *args: setattr(self.output, 'height', self.output.texture_size[1])
        )
        scroll.add_widget(self.output)
        root.add_widget(scroll)
        return root

    def save_key(self, instance):
        if self.save_api_key(self.key_input.text.strip()):
            Popup(title="OK", content=Label(text="Ключ сохранён!"), size_hint=(0.8, 0.3)).open()

    def start(self, instance):
        api_key = self.key_input.text.strip()
        q = self.input.text.strip()
        if not api_key or not q:
            Popup(title="Ошибка", content=Label(text="Введи ключ и вопрос"), size_hint=(0.8, 0.3)).open()
            return
        self.output.text = "🤖 Модели думают..."
        self.btn.disabled = True
        threading.Thread(target=self.run_debate, args=(api_key, q), daemon=True).start()

    def ask_model(self, api_key, primary_model, messages):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8"
        }
        for model in [primary_model] + FALLBACK_POOL:
            try:
                payload = {"model": model, "messages": messages, "temperature": 0.7}
                r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                                  headers=headers, json=payload, timeout=60)
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
            except Exception:
                continue
        return "⚠️ Модель недоступна"

    def run_debate(self, api_key, question):
        history_a = [{"role": "user", "content": question}]
        history_b = [{"role": "user", "content": question}]
        history_c = [{"role": "user", "content": question}]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fa = ex.submit(self.ask_model, api_key, MODEL_A_MAIN, history_a)
            fb = ex.submit(self.ask_model, api_key, MODEL_B_MAIN, history_b)
            fc = ex.submit(self.ask_model, api_key, MODEL_C_MAIN, history_c)
            ra, rb, rc = fa.result(), fb.result(), fc.result()
            
        judge_prompt = f"Ты арбитр. Вопрос: {question}\nA: {ra}\nB: {rb}\nC: {rc}\nВынеси финальный ответ."
        final = self.ask_model(api_key, JUDGE_MODEL, [{"role":="user", "content": judge_prompt}])
        
        Clock.schedule_once(lambda dt: self.done(final))

    def done(self, result):
        self.output.text = result
        self.btn.disabled = False

if __name__ == "__main__":
    CouncilApp().run()
