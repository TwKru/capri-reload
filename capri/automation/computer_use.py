"""Native computer tool with the existing job log, limits, pause and confirmation UI."""
import hashlib
import json
import time

from capri.ai.providers.computer_use import ComputerUseClient, screenshot
from capri.automation.agent_input import PointerTools
from capri.automation.desktop_agent import TaskRunner
from capri.core import cancellation


def validate_action(action, frame):
    """Validate a whole batch before sending any OS input."""
    if not isinstance(action, dict):
        raise ValueError("Computer Use вернула неверное действие")
    kind = action.get("type")
    fields = {"click": ("x","y","button"), "double_click": ("x","y"), "move": ("x","y"),
              "drag": ("path",), "scroll": ("x","y","scroll_x","scroll_y"),
              "keypress": ("keys",), "type": ("text",), "wait": (), "screenshot": ()}
    if kind not in fields or not set(fields[kind]) <= set(action):
        raise ValueError("Неизвестное или неполное действие Computer Use")

    def point(value):
        if not isinstance(value,dict) or type(value.get("x")) is not int or type(value.get("y")) is not int:
            raise ValueError("Неверные координаты Computer Use")
        if not 0 <= value["x"] < frame["width"] or not 0 <= value["y"] < frame["height"]:
            raise ValueError("Координаты Computer Use вне снимка")

    if kind in ("click","double_click","move","scroll"):
        point(action)
    if kind == "click" and action["button"] not in ("left","right","middle"):
        raise ValueError("Неизвестная кнопка мыши")
    if kind == "drag":
        if not isinstance(action["path"],list) or not 2 <= len(action["path"]) <= 200:
            raise ValueError("Неверный путь перетаскивания")
        for value in action["path"]:
            point(value)
    if kind == "scroll" and any(type(action[k]) is not int or abs(action[k]) > 2400 for k in ("scroll_x","scroll_y")):
        raise ValueError("Слишком большая прокрутка")
    if kind == "type" and (not isinstance(action["text"],str) or len(action["text"]) > 10000):
        raise ValueError("Слишком большой или неверный текст")
    if kind == "keypress":
        if not isinstance(action["keys"],list) or not 1 <= len(action["keys"]) <= 5:
            raise ValueError("Неверное сочетание клавиш")
        if not all(isinstance(key,str) and key and len(key) <= 20 and "+" not in key for key in action["keys"]):
            raise ValueError("Неизвестные клавиши Computer Use")
        PointerTools.key_codes(key_sequence(action))
    return action


def key_sequence(action):
    aliases = {" ":"SPACE", "OS":"WIN", "SUPER":"WIN", "ESCAPE":"ESC"}
    return "+".join(aliases.get(key.upper(),key) for key in action["keys"])


class ComputerUseRunner(TaskRunner):
    def __init__(self, store, frames, pointer, cfg, changed=lambda:None):
        self.store, self.frames, self.pointer, self.cfg, self.changed = store, frames, pointer, cfg, changed
        self.pending, self.approved, self.contexts = {}, set(), {}

    def execute_action(self, action, frame):
        validate_action(action,frame)
        cancellation.checkpoint()
        kind = action["type"]

        def point(value):
            x,y,w,h = frame["rect"]
            return x+value["x"]*w/frame["width"], y+value["y"]*h/frame["height"]

        if kind in ("click","double_click"):
            button = action.get("button","left")
            mode = "double_click" if kind == "double_click" else {"left":"click","right":"right_click","middle":"middle_click"}[button]
            self.pointer.click(*point(action),mode)
        elif kind == "move":
            self.pointer.move(*point(action))
        elif kind == "drag":
            self.pointer.drag([point(item) for item in action["path"]])
        elif kind == "scroll":
            self.pointer.move(*point(action))
            self.pointer.scroll_pixels(action["scroll_x"],action["scroll_y"])
        elif kind == "keypress":
            self.pointer.key(key_sequence(action))
        elif kind == "type":
            self.pointer.type_text(action["text"])
        elif kind == "wait":
            cancellation.wait(1)

    def run(self, ident):
        row = self.store.get(ident)
        if row["status"] not in ("queued","scheduled"):
            return
        self.store.update(ident,status="running")
        self.changed()
        started = time.monotonic()
        observations = json.loads(row["observations"])
        progress = row["progress"]
        history = []
        approved = ident in self.approved
        try:
            if not self.cfg.get("agent_screen",False):
                raise ValueError("Для Computer Use включи «Разрешить снимки и клики агента для заданий» в MAINFRAME → Задания.")
            client = ComputerUseClient(self.cfg)
            if not client.key:
                raise ValueError("Для Computer Use добавь ключ OpenAI в MAINFRAME → Задания или OPENAI_API_KEY.")

            def check():
                cancellation.checkpoint()
                if self.store.get(ident)["status"] != "running":
                    raise cancellation.RequestCancelled()
                if not self.cfg.get("agent_screen",False):
                    raise ValueError("Доступ к экрану выключен. Выполнение Computer Use остановлено.")
                if time.monotonic()-started >= row["seconds"]:
                    raise TimeoutError("Достигнут лимит времени. Можно продолжить.")

            frame = self.frames.get(max_side=1440)
            if approved:
                call, previous = self.pending[ident]
                if previous["fingerprint"] != frame["fingerprint"] or previous["rect"] != frame["rect"]:
                    raise ValueError("Экран изменился. Продолжи задание для нового плана вместо старого шага.")
                history, output = self.contexts.pop(ident)
            else:
                history = [{"role":"user","content":[
                    {"type":"input_text","text":json.dumps({"task":row["request"],"completed_steps":observations,
                         "remaining_actions":row["max_steps"]-progress},ensure_ascii=False)},
                    {"type":"input_image","image_url":screenshot(frame)["image_url"],"detail":"original"}]}]
                check()
                output = client.respond(history)
            while True:
                check()
                calls = [item for item in output if item.get("type") == "computer_call"]
                if not calls:
                    parts = [part for item in output if item.get("type") == "message" for part in item.get("content",[])]
                    text = "\n".join(part.get("text") or part.get("refusal","") for part in parts).strip()
                    if not text:
                        raise ValueError("Computer Use не вернула ни действия, ни итог. Можно продолжить.")
                    self.store.complete(ident,text)
                    self.store.event(ident,text)
                    return
                # One call is the documented computer protocol. Reject ambiguous output before input.
                if len(calls) != 1:
                    raise ValueError("Computer Use вернула несколько параллельных вызовов. Повтори задание.")
                call = calls[0]
                actions = call.get("actions")
                if not isinstance(call.get("call_id"),str) or not isinstance(actions,list) or not 1 <= len(actions) <= 100:
                    raise ValueError("Неверный вызов Computer Use")
                for action in actions:
                    validate_action(action,frame)
                if progress >= row["max_steps"]:
                    raise TimeoutError("Достигнут лимит шагов. Можно продолжить задание.")
                signature = hashlib.sha256(json.dumps([actions,frame["fingerprint"]],sort_keys=True).encode()).hexdigest()
                if len(observations) >= 3 and all(item.get("signature") == signature for item in observations[-3:]):
                    raise TimeoutError("Computer Use повторяет действия без прогресса. Уточни задачу.")
                self.pending[ident] = (call,frame)
                self.contexts[ident] = (history,output)
                checks = call.get("pending_safety_checks") or []
                if checks and not approved:
                    raise PermissionError("Computer Use просит подтвердить шаг. Проверь его в журнале MAINFRAME.")
                self.pending.pop(ident,None)
                self.contexts.pop(ident,None)
                executed = []
                for action in actions:
                    check()
                    if progress >= row["max_steps"]:
                        raise TimeoutError("Достигнут лимит шагов. Можно продолжить задание.")
                    self.execute_action(action,frame)
                    progress += 1
                    executed.append(action["type"])
                    # Do not put screenshots, typed text or credentials in the persisted log.
                    self.store.event(ident,f"{progress}. Computer Use: {action['type']}")
                    partial = (observations + [{"actions":list(executed),"signature":signature}])[-4:]
                    self.store.update(ident,progress=progress,observations=json.dumps(partial))
                    self.changed()
                observations = (observations + [{"actions":[a["type"] for a in actions],"signature":signature}])[-4:]
                self.store.update(ident,observations=json.dumps(observations))
                cancellation.wait(.3)
                check()
                frame = self.frames.get(max_side=1440)
                result = {"type":"computer_call_output","call_id":call["call_id"],"output":screenshot(frame)}
                if approved and checks:
                    result["acknowledged_safety_checks"] = checks
                approved = False
                self.approved.discard(ident)
                history = history + output + [result]
                check()
                output = client.respond(history)
        except cancellation.RequestCancelled:
            if self.store.get(ident)["status"] != "cancelled":
                self.store.update(ident,status="paused",result="Остановлено пользователем; выполненные действия сохранены.")
        except PermissionError as error:
            self.store.update(ident,status="awaiting_confirmation",result=str(error))
            self.store.event(ident,str(error))
        except TimeoutError as error:
            self.store.update(ident,status="paused",result=str(error))
            self.store.event(ident,str(error))
        except Exception as error:  # noqa: BLE001 -- job boundary
            self.store.update(ident,status="failed",result=str(error)[:1000])
            self.store.event(ident,str(error))
        finally:
            self.approved.discard(ident)
            if self.store.get(ident)["status"] != "awaiting_confirmation":
                self.pending.pop(ident,None)
                self.contexts.pop(ident,None)
            self.changed()
