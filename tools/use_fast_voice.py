"""Enable the measured fast local voice, or restore the previous engine and speed."""
import argparse
import json
from pathlib import Path

from capri.config.settings import CONFIG_PATH, _edit_config
from capri.core.paths import PROJECT_ROOT

BACKUP = PROJECT_ROOT / "reports" / "fast-voice" / "previous-engine.json"
KEYS = ("tts_engine", "silero_speed")


def switch(restore=False):
    if restore:
        previous = json.loads(BACKUP.read_text(encoding="utf-8"))

        def change(cfg):
            for key in KEYS:
                if key in previous:
                    cfg[key] = previous[key]
                else:
                    cfg.pop(key, None)
    else:
        cfg = json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8-sig"))
        if cfg.get("tts_engine") != "silero":
            BACKUP.parent.mkdir(parents=True, exist_ok=True)
            BACKUP.write_text(json.dumps({key: cfg[key] for key in KEYS if key in cfg}, indent=2), encoding="utf-8")

        def change(cfg):
            cfg.update(tts_engine="silero", silero_speed=1.0)

    error = _edit_config(change)
    if error:
        raise ValueError(error)
    print("Previous voice restored; restart Capri." if restore else "Fast local voice enabled; restart Capri.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore", action="store_true")
    switch(parser.parse_args().restore)
