from ollama import Client
import pyttsx3
import speech_recognition as sr
import time
import threading
import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime
import queue
import re
import subprocess
import tempfile
import os

client = Client()

JARVIS_PROMPT = """You are JARVIS, an advanced AI assistant. created by Natnael. Your personality:

- Respond in SHORT, natural sentences (1-2 sentences max for simple questions)
- Be helpful, witty, and slightly formal but warm
- For complex topics, give a BRIEF answer first, then ask: "Would you like me to elaborate on that?"
- Use casual transitions like "Sir" occasionally, "Certainly", "Of course", "Right away"
- Acknowledge commands with brief confirmation: "Done", "On it", "Understood"
- If you don't know something, be honest: "I'm not certain about that, sir"
- For greetings, be warm but brief: "Good evening, sir. How may I assist?"
- Keep technical jargon minimal unless asked
- Don't use lists or bullet points in speech - speak naturally
- Never give long explanations unless explicitly asked
- When sharing code, wrap it in triple backticks with language like ```python or ```javascript
- After sharing code, mention that the user can say "open in VS Code" to open it
"""

history = []
MAX_HISTORY = 10
is_running = True
is_speaking = False
interrupt_speech = False
conversation_active = False
CONVERSATION_TIMEOUT = 30
last_code_blocks = []

def extract_code_blocks(text):
    """Extract code blocks with their language from text"""
    pattern = r'```(\w+)?\n(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    code_blocks = []
    
    for lang, code in matches:
        if not lang:
            lang = "txt"
        code_blocks.append({"language": lang, "code": code.strip()})
    
    return code_blocks

def remove_code_blocks(text):
    """Remove code blocks from text for TTS, but keep descriptive text"""
    code_block_pattern = r'```[\s\S]*?```'
    inline_code_pattern = r'`[^`]+`'
    
    text_without_blocks = re.sub(code_block_pattern, ' [code block shown on screen] ', text)
    text_without_inline = re.sub(inline_code_pattern, '', text_without_blocks)
    
    text_without_inline = re.sub(r'\s+', ' ', text_without_inline).strip()
    
    return text_without_inline

def open_in_vscode(code_blocks, gui):
    """Open code blocks in VS Code"""
    if not code_blocks:
        gui.root.after(0, gui.add_message, "SYSTEM", "No code to open.", "#ff4444")
        return
    
    try:
        for i, block in enumerate(code_blocks):
            lang = block["language"]
            code = block["code"]
            
            extension_map = {
                "python": ".py",
                "javascript": ".js",
                "java": ".java",
                "cpp": ".cpp",
                "c": ".c",
                "html": ".html",
                "css": ".css",
                "typescript": ".ts",
                "go": ".go",
                "rust": ".rs",
                "php": ".php",
                "ruby": ".rb",
                "swift": ".swift",
                "kotlin": ".kt",
                "sql": ".sql",
                "bash": ".sh",
                "json": ".json",
                "xml": ".xml",
                "yaml": ".yaml",
            }
            
            extension = extension_map.get(lang.lower(), ".txt")
            
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                suffix=extension,
                delete=False,
                encoding='utf-8'
            )
            temp_file.write(code)
            temp_file.close()
            
            try:
                subprocess.Popen(['code', temp_file.name])
            except FileNotFoundError:
                try:
                    subprocess.Popen(['code.cmd', temp_file.name])
                except FileNotFoundError:
                    gui.root.after(0, gui.add_message, "SYSTEM", 
                        "VS Code not found. Please install VS Code or add it to PATH.", "#ff4444")
                    os.unlink(temp_file.name)
                    return
        
        message = f"Opened {len(code_blocks)} code block(s) in VS Code."
        gui.root.after(0, gui.add_message, "SYSTEM", message, "#00d9ff")
        
    except Exception as e:
        gui.root.after(0, gui.add_message, "SYSTEM", f"Error opening VS Code: {e}", "#ff4444")

def speak_interruptible(text, gui):
    global is_speaking, interrupt_speech
    
    is_speaking = True
    interrupt_speech = False
    
    def _speak():
        global is_speaking, interrupt_speech
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 180)
            
            speech_text = remove_code_blocks(text)
            
            if speech_text.strip():
                if interrupt_speech:
                    engine.stop()
                else:
                    engine.say(speech_text)
                    engine.runAndWait()
            
            engine.stop()
        except Exception as e:
            print(f"TTS Error: {e}")
        finally:
            is_speaking = False
    
    thread = threading.Thread(target=_speak)
    thread.daemon = True
    thread.start()

def listen_for_wake_word(recognizer, source, gui):
    global conversation_active, interrupt_speech
    
    try:
        audio = recognizer.listen(source, timeout=2, phrase_time_limit=2)
        text = recognizer.recognize_google(audio).lower()
        
        if "jarvis" in text:
            conversation_active = True
            
            if is_speaking:
                interrupt_speech = True
                time.sleep(0.3)
            
            gui.root.after(0, gui.update_status, "CONVERSATION MODE", "#00ff88")
            gui.root.after(0, gui.add_message, "SYSTEM", "Entering conversation mode. Listening...", "#00d9ff")
            return True
            
    except sr.WaitTimeoutError:
        pass
    except sr.UnknownValueError:
        pass
    except sr.RequestError as e:
        gui.root.after(0, gui.add_message, "SYSTEM", f"Recognition error: {e}", "#ff4444")
        time.sleep(1)
    except Exception as e:
        print(f"Wake word error: {e}")
        time.sleep(0.5)
    
    return False

def listen_for_command(recognizer, source, gui, is_first_command=False):
    try:
        if is_first_command:
            gui.root.after(0, gui.update_status, "LISTENING FOR COMMAND", "#00d9ff")
            timeout = 8
        else:
            gui.root.after(0, gui.update_status, "LISTENING (Conversation Mode)", "#00d9ff")
            timeout = CONVERSATION_TIMEOUT
        
        audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=15)
        
        gui.root.after(0, gui.update_status, "PROCESSING", "#ffaa00")
        user_input = recognizer.recognize_google(audio)
        
        if any(word in user_input.lower() for word in ["that's all", "thank you jarvis", "thanks jarvis", "stop listening"]):
            return "END_CONVERSATION"
        
        return user_input
        
    except sr.WaitTimeoutError:
        if not is_first_command:
            gui.root.after(0, gui.add_message, "SYSTEM", "Conversation timeout. Returning to standby.", "#ffaa00")
            return "TIMEOUT"
        gui.root.after(0, gui.add_message, "SYSTEM", "Listening timeout.", "#ff4444")
        return None
    except sr.UnknownValueError:
        gui.root.after(0, gui.add_message, "SYSTEM", "Could not understand.", "#ff4444")
        return None
    except Exception as e:
        gui.root.after(0, gui.add_message, "SYSTEM", f"Error: {e}", "#ff4444")
        return None

class JarvisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("J.A.R.V.I.S - Just A Rather Very Intelligent System")
        self.root.geometry("800x600")
        self.root.configure(bg="#0a0e27")
        
        title_frame = tk.Frame(root, bg="#0a0e27")
        title_frame.pack(pady=20)
        
        title_label = tk.Label(
            title_frame,
            text="J.A.R.V.I.S",
            font=("Courier New", 28, "bold"),
            fg="#00d9ff",
            bg="#0a0e27"
        )
        title_label.pack()
        
        subtitle_label = tk.Label(
            title_frame,
            text="Just A Rather Very Intelligent System",
            font=("Courier New", 10),
            fg="#00a8cc",
            bg="#0a0e27"
        )
        subtitle_label.pack()
        
        wake_label = tk.Label(
            root,
            text='Say "Jarvis" once to start conversation',
            font=("Courier New", 10, "italic"),
            fg="#888888",
            bg="#0a0e27"
        )
        wake_label.pack()
        
        self.status_label = tk.Label(
            root,
            text="● INITIALIZING",
            font=("Courier New", 12, "bold"),
            fg="#ffaa00",
            bg="#0a0e27"
        )
        self.status_label.pack(pady=10)
        
        chat_frame = tk.Frame(root, bg="#0a0e27")
        chat_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)
        
        self.chat_display = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            width=80,
            height=20,
            font=("Consolas", 11),
            bg="#1a1f3a",
            fg="#00ff88",
            insertbackground="#00ff88",
            borderwidth=2,
            relief="flat"
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        self.chat_display.config(state=tk.DISABLED)
        
        info_label = tk.Label(
            root,
            text=f'Say "open in VS Code" to open code • {CONVERSATION_TIMEOUT}s timeout • Say "that\'s all" to end',
            font=("Courier New", 9),
            fg="#666666",
            bg="#0a0e27"
        )
        info_label.pack(pady=10)
        
        self.add_message("SYSTEM", "JARVIS initialized. Calibrating microphone...", "#00d9ff")
        
        self.start_wake_word_listener()
    
    def add_message(self, sender, message, color):
        self.chat_display.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        self.chat_display.insert(tk.END, f"[{timestamp}] ", "timestamp")
        self.chat_display.insert(tk.END, f"{sender}: ", "sender")
        self.chat_display.insert(tk.END, f"{message}\n\n", "message")
        
        self.chat_display.tag_config("timestamp", foreground="#888888")
        self.chat_display.tag_config("sender", foreground=color, font=("Consolas", 11, "bold"))
        self.chat_display.tag_config("message", foreground="#ffffff")
        
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)
    
    def update_status(self, status, color):
        self.status_label.config(text=f"● {status}", fg=color)
    
    def start_wake_word_listener(self):
        thread = threading.Thread(target=self.wake_word_loop, daemon=True)
        thread.start()
    
    def wake_word_loop(self):
        global history, is_running, is_speaking, interrupt_speech, conversation_active, last_code_blocks
        
        recognizer = sr.Recognizer()
        
        recognizer.energy_threshold = 3000
        recognizer.dynamic_energy_threshold = True
        recognizer.dynamic_energy_adjustment_damping = 0.15
        recognizer.dynamic_energy_ratio = 1.5
        recognizer.pause_threshold = 0.8
        recognizer.phrase_threshold = 0.3
        recognizer.non_speaking_duration = 0.5
        
        with sr.Microphone() as source:
            self.root.after(0, self.update_status, "CALIBRATING", "#ffaa00")
            recognizer.adjust_for_ambient_noise(source, duration=2)
            
            self.root.after(0, self.add_message, "SYSTEM", "Ready. Say 'Jarvis' to start conversation.", "#00d9ff")
            self.root.after(0, self.update_status, "STANDBY - SAY 'JARVIS'", "#888888")
            
            consecutive_errors = 0
            max_consecutive_errors = 5
            
            while is_running:
                try:
                    if not conversation_active:
                        if not is_speaking:
                            self.root.after(0, self.update_status, "STANDBY - SAY 'JARVIS'", "#888888")
                        
                        if listen_for_wake_word(recognizer, source, self):
                            consecutive_errors = 0
                            
                            user_input = listen_for_command(recognizer, source, self, is_first_command=True)
                            
                            if user_input is None or user_input in ["TIMEOUT", "END_CONVERSATION"]:
                                conversation_active = False
                                continue
                            
                            self.root.after(0, self.add_message, "YOU", user_input, "#00ff88")
                            
                            if any(word in user_input.lower() for word in ["quit", "exit", "goodbye", "shut down", "power off"]):
                                goodbye_msg = "Goodbye, sir. It's been a pleasure."
                                self.root.after(0, self.add_message, "JARVIS", goodbye_msg, "#00d9ff")
                                speak_interruptible(goodbye_msg, self)
                                time.sleep(2)
                                self.root.after(0, self.root.destroy)
                                break
                            
                            self.process_command(user_input, recognizer, source)
                    
                    else:
                        if is_speaking:
                            while is_speaking:
                                time.sleep(0.1)
                            
                            if interrupt_speech:
                                self.root.after(0, self.add_message, "SYSTEM", "Interrupted.", "#ffaa00")
                        
                        user_input = listen_for_command(recognizer, source, self, is_first_command=False)
                        
                        if user_input == "TIMEOUT" or user_input == "END_CONVERSATION":
                            conversation_active = False
                            self.root.after(0, self.update_status, "STANDBY - SAY 'JARVIS'", "#888888")
                            continue
                        
                        if user_input is None:
                            continue
                        
                        self.root.after(0, self.add_message, "YOU", user_input, "#00ff88")
                        
                        if any(phrase in user_input.lower() for phrase in ["open in vs code", "open in vscode", "open it in vs code", "open code in vs code"]):
                            if last_code_blocks:
                                open_in_vscode(last_code_blocks, self)
                            else:
                                self.root.after(0, self.add_message, "JARVIS", "I haven't shared any code yet, sir.", "#00d9ff")
                                speak_interruptible("I haven't shared any code yet, sir.", self)
                            continue
                        
                        if any(word in user_input.lower() for word in ["quit", "exit", "goodbye", "shut down", "power off"]):
                            goodbye_msg = "Goodbye, sir. It's been a pleasure."
                            self.root.after(0, self.add_message, "JARVIS", goodbye_msg, "#00d9ff")
                            speak_interruptible(goodbye_msg, self)
                            time.sleep(2)
                            self.root.after(0, self.root.destroy)
                            break
                        
                        self.process_command(user_input, recognizer, source)
                    
                    consecutive_errors = 0
                    
                except Exception as e:
                    consecutive_errors += 1
                    print(f"Loop error ({consecutive_errors}/{max_consecutive_errors}): {e}")
                    
                    if consecutive_errors >= max_consecutive_errors:
                        self.root.after(0, self.add_message, "SYSTEM", 
                            f"Multiple errors. Restarting... ({e})", "#ff4444")
                        self.root.after(0, self.update_status, "RESTARTING", "#ff4444")
                        time.sleep(2)
                        try:
                            recognizer.adjust_for_ambient_noise(source, duration=1)
                            consecutive_errors = 0
                            conversation_active = False
                            self.root.after(0, self.add_message, "SYSTEM", "Restarted.", "#00d9ff")
                        except:
                            pass
                    else:
                        time.sleep(0.5)
    
    def process_command(self, user_input, recognizer, source):
        global history, last_code_blocks
        
        history.append(f"Human: {user_input}")
        
        if len(history) > MAX_HISTORY * 2:
            history = history[-MAX_HISTORY * 2:]
        
        prompt = JARVIS_PROMPT + "\n\n" + "\n".join(history) + "\nJARVIS: "
        
        self.root.after(0, self.update_status, "THINKING", "#ffaa00")
        full_response = ""
        
        try:
            for chunk in client.generate(
                model="llama3.1:8b",
                prompt=prompt,
                stream=True
            ):
                full_response += chunk["response"]
        except Exception as e:
            self.root.after(0, self.add_message, "SYSTEM", f"AI generation error: {e}", "#ff4444")
            return
        
        history.append(f"JARVIS: {full_response}")
        
        last_code_blocks = extract_code_blocks(full_response)
        
        self.root.after(0, self.add_message, "JARVIS", full_response, "#00d9ff")
        self.root.after(0, self.update_status, "SPEAKING", "#9d4edd")
        speak_interruptible(full_response, self)

def main():
    root = tk.Tk()
    app = JarvisGUI(root)
    
    def on_closing():
        global is_running
        is_running = False
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()