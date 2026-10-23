#!/usr/bin/env python3

import argparse
import base64
import concurrent.futures
import importlib
import json
import os
import random
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class SteamDetector:
    def __init__(self):
        self.is_win = sys.platform.startswith("win")

    def _expand(self, path):
        return Path(os.path.expandvars(str(path))).expanduser()

    def _windows_deep(self):
        found = []
        try:
            import winreg
            roots = [
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
            ]
            for root, keypath in roots:
                try:
                    with winreg.OpenKey(root, keypath) as key:
                        for val in ("InstallPath", "SteamExe"):
                            try:
                                v, _ = winreg.QueryValueEx(key, val)
                                p = Path(v if val == "InstallPath" else v).parent if val == "SteamExe" else Path(v)
                                if p.exists():
                                    found.append(str(p))
                            except FileNotFoundError:
                                pass
                except Exception:
                    pass
        except ImportError:
            pass
        for letter in string.ascii_uppercase:
            drive = f"{letter}:"
            if not Path(drive).exists():
                continue
            for sub in (
                r"Program Files (x86)\Steam",
                r"Program Files\Steam",
                r"SteamLibrary\steamapps\common\..",
                r"Steam",
            ):
                p = Path(drive) / sub
                if p.exists() and (p / "userdata").exists():
                    found.append(str(p))
                    break
            p2 = Path(drive) / "SteamLibrary"
            if p2.exists() and (p2 / "steamapps").exists():
                for p3 in (Path(drive) / "Program Files (x86)" / "Steam", Path(drive) / "Program Files" / "Steam"):
                    if p3.exists() and (p3 / "userdata").exists():
                        found.append(str(p3))
        seen, unique = set(), []
        for p in found:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

    def detect(self):
        candidates = []
        if self.is_win:
            candidates = self._windows_deep() + [
                r"%PROGRAMFILES(X86)%\Steam",
                r"%PROGRAMFILES%\Steam",
                r"%LOCALAPPDATA%\Steam",
                r"%APPDATA%\Steam",
                str(Path.home() / "AppData" / "Roaming" / "Steam"),
                str(Path.home() / "AppData" / "Local" / "Steam"),
            ]
        else:
            candidates = [
                str(Path.home() / ".local" / "share" / "Steam"),
                str(Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"),
                str(Path.home() / "snap" / "steam" / "common" / ".local" / "share" / "Steam"),
                str(Path.home() / ".steam" / "steam"),
                str(Path.home() / ".steam" / "root"),
            ]
        found = []
        for c in candidates:
            p = self._expand(c)
            if p.exists():
                found.append(str(p))
        seen, unique = set(), []
        for p in found:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique


class VDFParser:
    @staticmethod
    def load(path):
        try:
            import vdf
            return vdf.load(open(path, encoding="utf-8", errors="replace"))
        except ImportError:
            pass
        except Exception as e:
            print(f"[vdf] falhou ao ler {path}: {e}")
        try:
            return VDFParser._pure(path)
        except Exception as e:
            print(f"[pure-vdf] falhou ao ler {path}: {e}")
            return {}

    @staticmethod
    def _pure(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        return VDFParser._parse(text)

    @staticmethod
    def _tokenize(text):
        tokens, i, n = [], 0, len(text)
        while i < n:
            c = text[i]
            if c.isspace():
                i += 1
                continue
            if c in "{}":
                tokens.append(c)
                i += 1
                continue
            if c == '"':
                i += 1
                s = []
                while i < n:
                    if text[i] == "\\" and i + 1 < n:
                        nxt = text[i + 1]
                        esc = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(nxt, nxt)
                        s.append(esc)
                        i += 2
                        continue
                    if text[i] == '"':
                        i += 1
                        break
                    s.append(text[i])
                    i += 1
                tokens.append("".join(s))
                continue
            if c == "/" and i + 1 < n and text[i + 1] == "/":
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            s = []
            while i < n and not text[i].isspace() and text[i] not in '{}"/':
                s.append(text[i])
                i += 1
            if s:
                tokens.append("".join(s))
        return tokens

    @staticmethod
    def _parse_block(tokens, pos):
        result = {}
        while pos[0] < len(tokens):
            tok = tokens[pos[0]]
            if tok == "}":
                pos[0] += 1
                return result, pos[0]
            key = tok
            pos[0] += 1
            if pos[0] >= len(tokens):
                result[key] = ""
                break
            nxt = tokens[pos[0]]
            if nxt == "{":
                pos[0] += 1
                sub, pos[0] = VDFParser._parse_block(tokens, pos)
                result[key] = sub
            else:
                result[key] = nxt
                pos[0] += 1
        return result, pos[0]

    @staticmethod
    def _parse(text):
        tokens = VDFParser._tokenize(text)
        pos = [0]
        result, _ = VDFParser._parse_block(tokens, pos)
        return result


class ProtobufParser:
    @staticmethod
    def varint(b, i):
        r = s = 0
        while True:
            c = b[i]
            i += 1
            r |= (c & 0x7F) << s
            if not c & 0x80:
                return r, i
            s += 7

    @staticmethod
    def fields(b):
        i, out = 0, []
        while i < len(b):
            k, i = ProtobufParser.varint(b, i)
            f, w = k >> 3, k & 7
            if w == 0:
                v, i = ProtobufParser.varint(b, i)
            elif w == 2:
                l, i = ProtobufParser.varint(b, i)
                v = b[i:i + l]
                i += l
            elif w == 5:
                v = int.from_bytes(b[i:i + 4], "little")
                i += 4
            elif w == 1:
                v = int.from_bytes(b[i:i + 8], "little")
                i += 8
            else:
                raise ValueError(w)
            out.append((f, w, v))
        return out

    @staticmethod
    def parse_apps(path):
        b = open(path, "rb").read()
        apps = []
        for f, w, v in ProtobufParser.fields(b):
            if f == 1 and w == 2:
                d, tags = {}, []
                for ff, ww, vv in ProtobufParser.fields(v):
                    if ff == 19 and ww == 0:
                        tags.append(vv)
                    elif ff == 2 and ww == 2:
                        d["name"] = vv.decode("utf-8", "replace")
                    elif ff in (1, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 21, 22, 26, 27, 31, 36, 37, 46, 53, 54, 55, 56, 65, 66, 68, 73, 77, 79, 80) and ww == 0:
                        d[ff] = vv
                d["appid"] = d.get(1)
                d["tags"] = [int(x) for x in tags]
                apps.append(d)
        return apps


class TagResolver:
    TAGS = {
        19: "Action", 21: "Adventure", 23: "Casual", 25: "Indie", 27: "Massively Multiplayer",
        29: "Racing", 30: "RPG", 31: "Simulation", 32: "Sports", 33: "Strategy",
        103: "Fighting", 113: "MOBA", 114: "Auto Battler", 1718: "MOBA", 1774: "FPS",
        1663: "FPS", 3859: "Shooter", 5711: "Tactical", 3878: "Competitive", 5055: "Co-op",
        492: "Indie", 9: "Puzzle", 1685: "Horror", 1676: "Survival", 4747: "Crafting",
        4711: "Open World", 4231: "Story Rich", 599: "Visual Novel", 1775: "Point & Click",
        1645: "Walking Simulator", 1684: "Choices Matter", 3843: "Sandbox",
        1718: "Battle Royale", 122: "Card Game", 1708: "Deckbuilding",
    }

    @classmethod
    def load(cls):
        for tf in (
            Path.home() / ".local" / "share" / "Steam" / "steamui" / "tagnames.json",
            Path.home() / "AppData" / "Roaming" / "Steam" / "steamui" / "tagnames.json",
            Path.home() / "AppData" / "Local" / "Steam" / "steamui" / "tagnames.json",
        ):
            if tf.exists():
                try:
                    for k, v in json.load(open(tf, encoding="utf-8")).items():
                        cls.TAGS[int(k)] = v
                except Exception:
                    pass
        try:
            import urllib.request
            data = urllib.request.urlopen(
                "https://store.steampowered.com/tagdata/populartags/english", timeout=8
            ).read().decode()
            for t in json.loads(data):
                cls.TAGS[int(t["tagid"])] = t["name"]
        except Exception:
            pass

    @classmethod
    def names(cls, ids):
        return [cls.TAGS.get(i, f"tag_{i}") for i in ids]


TagResolver.load()

CAT_MAP = {
    "🥊 Luta": {"Fighting", "2D Fighter", "3D Fighter"},
    "🚗 Corrida": {"Racing", "Driving", "Combat Racing", "Automobile Sim", "Motocross", "Offroad"},
    "⚽ Esportes": {"Sports", "Football (Soccer)", "Football (American)", "Basketball", "Baseball", "Tennis", "Golf", "Bowling", "Skateboarding", "Snowboarding", "Hockey", "Wrestling", "Boxing", "Cricket", "Rugby", "Volleyball", "Billiards", "Pool", "Mini Golf", "Snooker", "Skiing", "Cycling"},
    "🃏 Cartas & Tabuleiro": {"Card Game", "Trading Card Game", "Card Battler", "Deckbuilding", "Roguelike Deckbuilder", "Board Game", "Tabletop", "Chess", "Solitaire", "Mahjong"},
    "👻 Terror": {"Horror", "Survival Horror", "Psychological Horror", "Zombies", "Lovecraftian", "Jump Scare"},
    "🌐 MMO": {"MMORPG", "Massively Multiplayer"},
    "🧠 Estratégia": {"Strategy", "RTS", "Turn-Based Strategy", "4X", "Grand Strategy", "MOBA", "Auto Battler", "Tower Defense", "Turn-Based Tactics", "Real Time Tactics", "Wargame", "Political Sim"},
    "🏗️ Simulação": {"Simulation", "Farming Sim", "Life Sim", "Management", "City Builder", "Colony Sim", "Automation", "Base Building", "Building", "Space Sim", "God Game", "Economy", "Job Simulator", "Hobby Sim", "Medical Sim"},
    "🌲 Survival & Craft": {"Survival", "Open World Survival Craft", "Crafting"},
    "🗡️ RPG": {"RPG", "Action RPG", "JRPG", "CRPG", "Party-Based RPG", "Strategy RPG", "Tactical RPG", "Souls-like", "Dungeon Crawler", "Roguelike", "Roguelite", "Traditional Roguelike", "Loot"},
    "🌍 Aventura": {"Adventure", "Action-Adventure", "Exploration", "Story Rich", "Walking Simulator", "Visual Novel", "Point & Click", "Choices Matter", "Sandbox", "Open World"},
    "🎯 Ação": {"Action", "Shooter", "FPS", "Third-Person Shooter", "Hack and Slash", "Beat 'em up", "Shoot 'Em Up", "Arena Shooter", "Boomer Shooter", "Twin Stick Shooter", "Bullet Hell", "Action Roguelike", "Spectacle fighter", "Character Action Game", "Combat", "Swordplay", "Martial Arts", "Looter Shooter", "Extraction Shooter", "Vehicular Combat"},
    "🧩 Casual & Puzzle": {"Casual", "Puzzle", "Hidden Object", "Match 3", "Trivia", "Word Game", "Relaxing", "Cozy", "Idler", "Incremental", "Clicker", "Party Game", "Minigames", "Logic", "Sokoban", "Social Deduction"},
    "🕹️ Indie & Retrô": {"Indie", "Pixel Graphics", "Retro", "2D", "Platformer", "2D Platformer", "3D Platformer", "Precision Platformer", "Puzzle Platformer", "Metroidvania", "Side Scroller", "Arcade", "Classic", "1990's", "1980s"},
}
TAG2CAT = {t: c for c, ts in CAT_MAP.items() for t in ts}
COOP = {"Co-op", "Online Co-Op", "Local Co-Op", "Co-op Campaign", "4 Player Local"}
PVP = {"PvP", "Competitive", "eSports", "Battle Royale", "MOBA", "Hero Shooter", "Team-Based"}

MANUAL = {
    "620": "🧩 Casual & Puzzle", "227300": "🏗️ Simulação", "480": "🎯 Ação", "570": "🧠 Estratégia", "730": "🎯 Ação",
    "359550": "🎯 Ação", "292030": "🗡️ RPG", "1091500": "🗡️ RPG", "1174180": "🌍 Aventura", "271590": "🌍 Aventura",
    "413150": "🏗️ Simulação", "427520": "🏗️ Simulação", "105600": "🌲 Survival & Craft", "4000": "🧩 Casual & Puzzle",
    "252490": "🌲 Survival & Craft", "578080": "🎯 Ação", "1245620": "🗡️ RPG", "892970": "🌲 Survival & Craft",
    "548430": "🎯 Ação", "553850": "🎯 Ação", "2357570": "🎯 Ação", "2767030": "🎯 Ação", "2141910": "🃏 Cartas & Tabuleiro",
    "599140": "🏗️ Simulação", "1286830": "🌐 MMO", "1085660": "🎯 Ação", "1623730": "🌲 Survival & Craft", "275850": "🌲 Survival & Craft",
    "1118310": "🛠️ Ferramentas", "205190": "🧩 Casual & Puzzle", "71340": "🕹️ Indie & Retrô",
    "202970": "🎯 Ação", "202990": "🎯 Ação", "212910": "🎯 Ação", "218640": "👻 Terror", "349040": "🥊 Luta",
    "407740": "🎯 Ação", "438740": "👻 Terror", "582160": "🌍 Aventura", "637650": "🗡️ RPG", "946610": "🎯 Ação",
    "1189780": "🎯 Ação", "1208030": "🧩 Casual & Puzzle", "1237980": "🎯 Ação", "2675290": "🎯 Ação", "2827200": "👻 Terror",
    "2920570": "🧩 Casual & Puzzle", "3432970": "⚽ Esportes", "4332910": "🧩 Casual & Puzzle",
    "457930": "🎯 Ação", "457940": "🎯 Ação", "473620": "🎯 Ação", "473630": "🎯 Ação", "473650": "🎯 Ação",
    "475240": "🎯 Ação", "486340": "🎯 Ação", "491250": "🎯 Ação", "473580": "🃏 Cartas & Tabuleiro", "974100": "🧩 Casual & Puzzle",
    "1657270": "📁 Outros", "506770": "📁 Outros", "3778240": "📁 Outros",
    "12100": "🎮 Grand Theft Auto", "12230": "🎮 Grand Theft Auto", "12120": "🎮 Grand Theft Auto", "12250": "🎮 Grand Theft Auto", "12110": "🎮 Grand Theft Auto",
}

FRANCHISES = [
    ("Resident Evil", r"\bresident evil\b|\bbiohazard\b|\bumbrella corps\b", "🧟"),
    ("Half-Life", r"\bhalf-?life\b|\bblack mesa\b", "🧪"),
    ("LEGO", r"\blego\b", "🧱"),
    ("Fallout", r"\bfallout\b", "☢️"),
    ("Warhammer", r"\bwarhammer\b", "🔨"),
    ("Counter-Strike", r"\bcounter-?strike\b", "🔫"),
    ("Grand Theft Auto", r"\bgrand theft auto\b|\bgta\b", "🚗"),
    ("Batman Arkham", r"^batman\b", "🦇"),
    ("BioShock", r"\bbioshock\b", "🌊"),
    ("Borderlands", r"\bborderlands\b", "🚜"),
    ("Dragon Ball", r"\bdragon ball\b", "🐲"),
    ("Saints Row", r"\bsaints row\b", "🟣"),
    ("Darksiders", r"\bdarksiders\b", "🐎"),
    ("Dead Rising", r"\bdead rising\b", "🧟"),
    ("Age of Empires", r"\bage of empires\b", "🏰"),
    ("Dark Souls", r"\bdark souls\b", "🔥"),
    ("Devil May Cry", r"\bdevil may cry\b|\bdmc\b", "😈"),
    ("Final Fantasy", r"\bfinal fantasy\b", "🧝"),
    ("Mafia", r"^mafia\b", "🕴️"),
    ("Metro", r"\bmetro (2033|last light|exodus|redux)\b", "☢️"),
    ("Penumbra", r"\bpenumbra\b", "🔦"),
    ("Beholder", r"\bbeholder\b", "👁️"),
    ("Hitman", r"^hitman\b", "🕴️"),
    ("Metal Gear", r"\bmetal gear\b", "📦"),
    ("Car Mechanic Simulator", r"\bcar mechanic simulator\b", "🔧"),
    ("Death Stranding", r"\bdeath stranding\b", "📦"),
    ("Deus Ex", r"\bdeus ex\b", "🔺"),
    ("Dishonored", r"\bdishonored\b", "🎭"),
    ("F1", r"\bf1 (19|20)\d\d\b|\bf1 2[0-9]\b", "🏎️"),
    ("Forza Horizon", r"\bforza\b", "🏎️"),
    ("Monster Hunter", r"\bmonster hunter\b", "🐲"),
    ("The Elder Scrolls", r"\belder scrolls\b|\bskyrim\b|\bmorrowind\b|\boblivion\b", "📜"),
    ("The Witcher", r"\bwitcher\b", "🐺"),
    ("Tomb Raider", r"\btomb raider\b|\blara croft\b", "🏺"),
    ("Train Simulator", r"\btrain sim(ulator)?\b", "🚆"),
    ("Wolfenstein", r"\bwolfenstein\b", "🐺"),
    ("Wargame", r"\bwargame\b", "🗺️"),
    ("Subnautica", r"\bsubnautica\b", "🌊"),
    ("Space Pilgrim", r"\bspace pilgrim\b", "🚀"),
    ("Call of Duty", r"\bcall of duty\b", "🎖️"),
]

BAD_FRANCHISE = re.compile(r"test server|public test|open beta|\bbeta\b|experimental|bonus content|soundtrack|\bdemo\b|playtest", re.IGNORECASE)


class Classifier:
    @classmethod
    def classify(cls, app):
        t = app.get("apptype", 1)
        tags = app.get("tags", [])
        tn = TagResolver.names(tags)
        top = set(tn[:8])

        if t == 4:
            return ["🛠️ Ferramentas"]
        if t in (8, 65536):
            return ["🧪 Demos & Betas"]
        if t in (2, 256):
            return ["🛠️ Ferramentas"]
        if t in (2048, 8192):
            return ["🎬 Trilhas & Vídeos"]

        aid = str(app.get("appid"))
        if aid in MANUAL:
            cols = [MANUAL[aid]]
        elif "MMORPG" in tn[:3]:
            cols = ["🌐 MMO"]
        else:
            cols = ["📁 Outros"]
            for x in tn:
                if x in TAG2CAT:
                    cols = [TAG2CAT[x]]
                    break

        if top & COOP:
            cols.append("🤝 Co-op")
        if top & PVP:
            cols.append("⚔️ Competitivo")
        if "VR" in tags or "VR" in tn:
            cols.append("🥽 VR")
        if "Indie" in tn and "🕹️ Indie & Retrô" not in cols:
            cols.append("🕹️ Indie & Retrô")
        if app.get("installed", False):
            cols.append("📦 Instalados")
        now = time.time()
        if app.get("play2w", 0) > 0 or (
            app.get("lastplayed", 0) and now - app["lastplayed"] < 30 * 86400 and app.get("playtime", 0) > 0
        ):
            cols.append("▶️ Jogando Agora")
        return list(dict.fromkeys(cols))


class LibraryBuilder:
    @classmethod
    def fast(cls, appinfo_path, lc_path):
        apps_data = {}
        try:
            ai = VDFParser.load(appinfo_path)
            root = cls._unwrap(ai)
            for appid, app in root.get("apps", {}).items():
                common = app.get("common", {})
                apps_data[appid] = {
                    "appid": appid,
                    "name": common.get("name", ""),
                    "apptype": 1,
                    "tags": app.get("store_tags", []) or [],
                    "installed": False,
                    "playtime": 0, "play2w": 0, "lastplayed": 0,
                }
        except Exception as e:
            print(f"appinfo.vdf não lido: {e}")

        try:
            lc = VDFParser.load(lc_path)
            root = cls._unwrap(lc)
            userapps = root.get("UserLocalConfigStore", {}).get("apps", {})
            for appid, app in userapps.items():
                if appid in apps_data:
                    apps_data[appid]["playtime"] = app.get("playtime", 0) or 0
                    apps_data[appid]["lastplayed"] = app.get("lastplayed", 0) or 0
                    apps_data[appid]["installed"] = (app.get("installed", 0) or 0) == 1
                else:
                    apps_data[appid] = {
                        "appid": appid, "name": app.get("name", ""),
                        "apptype": 1, "tags": [],
                        "installed": (app.get("installed", 0) or 0) == 1,
                        "playtime": app.get("playtime", 0) or 0, "play2w": 0,
                        "lastplayed": app.get("lastplayed", 0) or 0,
                    }
        except Exception as e:
            print(f"localconfig.vdf não lido: {e}")

        return list(apps_data.values())

    @classmethod
    def full(cls, steam_path):
        steam_bin = shutil.which("steam") or ("steam.exe" if sys.platform.startswith("win") else "/usr/bin/steam")
        marker = Path(tempfile.gettempdir()) / "steamorganizer_debug_marker"
        if not marker.exists():
            try:
                subprocess.Popen([steam_bin, "-cef-enable-debugging"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(30):
                    s = socket.socket()
                    try:
                        s.connect(("127.0.0.1", 8080))
                        s.close()
                        break
                    except Exception:
                        time.sleep(1)
                marker.write_text("")
            except Exception as e:
                print(f"Não foi possível iniciar Steam com debug: {e}")
                return []

        try:
            import websocket
        except ImportError:
            print("websocket-client não instalado. pip install websocket-client")
            return []

        import urllib.request
        try:
            targets = json.loads(urllib.request.urlopen("http://127.0.0.1:8080/json", timeout=5).read())
        except Exception as e:
            print(f"Não foi possível conectar na porta 8080: {e}")
            return []

        shared = [t for t in targets if t.get("title") == "SharedJSContext"]
        if not shared:
            print("SharedJSContext não encontrado. Rode a Steam com -cef-enable-debugging.")
            return []
        ws_url = shared[0]["webSocketDebuggerUrl"]

        buf = {"data": None}

        def on_message(ws, message):
            m = json.loads(message)
            if m.get("id") == 1 and "result" in m:
                buf["data"] = m["result"]["result"]["value"]
                ws.close()

        def on_open(ws):
            expr = ("window.__ovbuf=null;SteamClient.Apps.RegisterForAppOverviewChanges(b=>{window.__ovbuf=b});"
                    "setTimeout(()=>{},2500)")
            ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}}))

        ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
        ws.run_forever(timeout=10)

        if buf["data"] is None:
            return []

        raw = base64.b64decode(buf["data"])
        pb_path = Path(tempfile.gettempdir()) / "overview.pb"
        pb_path.write_bytes(raw)
        apps = ProtobufParser.parse_apps(pb_path)

        now = time.time()
        return [
            {
                "appid": str(a.get("appid")),
                "name": a.get("name") or "",
                "apptype": a.get(7, 1),
                "tags": a.get("tags", []),
                "installed": (a.get(37, 0) or 0) > 0,
                "playtime": a.get(16, 0) or 0,
                "play2w": a.get(17, 0) or 0,
                "lastplayed": a.get(14, 0) or 0,
            }
            for a in apps
        ]

    @staticmethod
    def _unwrap(data):
        if isinstance(data, dict) and len(data) == 1:
            return data[next(iter(data))]
        return data


class SteamManager:
    @staticmethod
    def is_running():
        try:
            import psutil
            for proc in psutil.process_iter(["name"]):
                if "steam" in (proc.info["name"] or "").lower():
                    return True
        except ImportError:
            pass
        try:
            if sys.platform.startswith("win"):
                r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe"], capture_output=True, text=True)
                return "steam.exe" in r.stdout.lower()
            r = subprocess.run(["pgrep", "-f", "steam"], capture_output=True, text=True)
            return bool(r.stdout.strip())
        except Exception:
            return False

    @classmethod
    def shutdown(cls, ui):
        if not cls.is_running():
            print("Steam não está rodando. Prosseguindo...")
            return True
        print("\n⚠  AVISO: A Steam será FECHADA agora para evitar sobrescrita do arquivo.")
        print("     Salve qualquer coisa que esteja fazendo nela antes de continuar.\n")
        if not ui.confirm("Fechar a Steam agora e continuar?", default=True):
            print("Cancelado pelo usuário.")
            return False
        print("Enviando steam -shutdown...")
        try:
            subprocess.run(
                [shutil.which("steam") or ("steam.exe" if sys.platform.startswith("win") else "/usr/bin/steam"), "-shutdown"],
                capture_output=True, timeout=30,
            )
        except Exception as e:
            print(f"Não foi possível executar steam -shutdown: {e}")
        for _ in range(30):
            if not cls.is_running():
                print("Steam fechada com sucesso.")
                return True
            time.sleep(1)
        print("Aviso: a Steam pode ainda estar fechando. Prosseguindo mesmo assim.")
        return True

    @staticmethod
    def start():
        try:
            subprocess.Popen(
                [shutil.which("steam") or ("steam.exe" if sys.platform.startswith("win") else "/usr/bin/steam")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"Não foi possível iniciar a Steam automaticamente: {e}")
            print("Inicie a Steam manualmente.")


class UI:
    @staticmethod
    def _run_gum(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return r.returncode == 0, r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            return False, ""

    @classmethod
    def choice(cls, header, options, default_index=0, multiselect=False, enabled=True):
        if not enabled:
            return [options[default_index]] if not multiselect else options
        gum_ok, out = cls._run_gum(["gum", "choose", "--header", header,
                                  "--limit", "0" if multiselect else "1",
                                  "--height", str(min(len(options) + 2, 20))] + options)
        if gum_ok:
            return [x for x in out.splitlines() if x.strip()] if multiselect else [out] if out else []
        print(f"\n{header}")
        for i, o in enumerate(options):
            mark = " (default)" if i == default_index else ""
            print(f"  {i + 1}. {o}{mark}")
        raw = input("Escolha os números separados por vírgula (ex: 1,3,5): ").strip()
        if not raw:
            return [options[default_index]]
        try:
            idxs = [int(x.strip()) - 1 for x in raw.split(",")]
            return [options[i] for i in idxs if 0 <= i < len(options)]
        except Exception:
            return [options[default_index]]

    @classmethod
    def input(cls, header, default="", placeholder="", enabled=True):
        if not enabled:
            return default
        gum_ok, out = cls._run_gum(["gum", "input", "--header", header, "--value", default or ""])
        if gum_ok:
            return out
        val = input(f"{header} [{default or placeholder}]: ").strip()
        return val if val else (default or placeholder or "")

    @classmethod
    def confirm(cls, header, default=True, enabled=True):
        if not enabled:
            return default
        gum_ok, _ = cls._run_gum(["gum", "confirm", "--default", str(default).lower(), "--header", header])
        if gum_ok:
            return True
        d = "S/n" if default else "s/N"
        resp = input(f"{header} [{d}]: ").strip().lower()
        if not resp:
            return default
        return resp in ("s", "sim", "y", "yes")


class CollectionWriter:
    def __init__(self, cs_file, ui, backup_path=None):
        self.cs_file = cs_file
        self.ui = ui
        self.backup_path = backup_path
        self.d = json.load(open(cs_file, encoding="utf-8"))
        self.by_key = {e[0]: e for e in self.d}
        self.existing_by_name = {}
        for e in self.d:
            if e[0].startswith("user-collections.") and not e[1].get("is_deleted"):
                try:
                    v = json.loads(e[1]["value"])
                    if v.get("name"):
                        self.existing_by_name[v["name"]] = e[0]
                except Exception:
                    pass

    def _new_id(self):
        rnd = random.Random(int(time.time()))
        while True:
            k = "uc-" + "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(12))
            if "user-collections." + k not in self.by_key:
                return k

    def _rollback(self):
        if self.backup_path and self.backup_path.exists():
            shutil.copy2(self.backup_path, self.cs_file)
            print(f"  [ROLLBACK] Restaurado backup: {self.backup_path}")

    def write(self, final_groups, order, criar_inst, nome_inst):
        now = int(time.time())
        created = updated = 0
        orfãs = []

        for nome_existente, key in list(self.existing_by_name.items()):
            if key in ("user-collections.favorite", "user-collections.hidden"):
                continue
            if nome_existente in order:
                continue
            orfãs.append((nome_existente, key))

        for nome_existente, key in orfãs:
            e = self.by_key[key]
            try:
                v = json.loads(e[1]["value"])
                v["is_deleted"] = True
                e[1]["value"] = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                e[1]["timestamp"] = now
                print(f"  [ÓRFÃ REMOVIDA] {nome_existente}")
            except Exception:
                pass

        try:
            for name in order:
                apps = sorted(final_groups.get(name, set()))
                if not apps and name != nome_inst:
                    continue
                key = self.existing_by_name.get(name)
                if key:
                    updated += 1
                else:
                    key = "user-collections." + self._new_id()
                    created += 1
                val = {"id": key.split(".", 1)[1], "name": name, "added": apps, "removed": []}
                entry = [key, {"key": key, "timestamp": now, "value": json.dumps(val, ensure_ascii=False, separators=(",", ":")), "version": "596"}]
                if key in self.by_key:
                    idx = next(i for i, x in enumerate(self.d) if x[0] == key)
                    self.d[idx] = entry
                else:
                    self.d.append(entry)
                self.by_key[key] = entry

            if criar_inst:
                inst_key = self.existing_by_name.get("Instalados localmente") or self.existing_by_name.get(nome_inst)
                if inst_key and inst_key in self.by_key:
                    e = self.by_key[inst_key]
                    v = json.loads(e[1]["value"])
                    v["name"] = nome_inst
                    e[1]["value"] = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                    e[1]["timestamp"] = now

            tmp = str(self.cs_file) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False)
            os.replace(tmp, self.cs_file)

            try:
                with open(self.cs_file, encoding="utf-8") as f:
                    d2 = json.load(f)
                valid = sum(
                    1 for e in d2
                    if e[0].startswith("user-collections.") and not e[1].get("is_deleted")
                    and (lambda v: v.get("name") and isinstance(v.get("added"), list))(json.loads(e[1]["value"]))
                )
                print(f"  Arquivo JSON válido. {valid} coleções ativas encontradas.")
            except Exception as ex:
                print(f"  ERRO na validação: {ex}")
                self._rollback()
                raise

        except Exception as e:
            print(f"  ERRO ao gravar: {e}")
            self._rollback()
            raise

        return created, updated, len(orfãs)


class SteamOrganizer:
    def __init__(self, args=None):
        self.args = args or {}
        self.detector = SteamDetector()
        self.ui = UI()

    def _enabled(self):
        return not self.args.get("no_gum", False)

    def _ensure_deps(self):
        for pkg in ["vdf", "websocket-client", "psutil"]:
            try:
                importlib.import_module(pkg.replace("-", "_"))
            except ImportError:
                print(f"Instalando dependência: {pkg} ...")
                try:
                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    print(f"  {pkg} instalado com sucesso.")
                except Exception as e:
                    if pkg == "vdf":
                        print("  vdf não instalado — usando parser VDF puro Python (sem impacto).")
                    else:
                        print(f"  Não foi possível instalar {pkg}: {e}")
                        print(f"  Rode manualmente: pip install {pkg}")

    @staticmethod
    def _find_userdata_dirs(steam_path):
        userdata = Path(steam_path) / "userdata"
        if not userdata.exists():
            return []
        return sorted([d for d in userdata.iterdir() if d.is_dir() and d.name.isdigit()])

    @staticmethod
    def _select_user(userdirs, enabled):
        if len(userdirs) > 1:
            print("Vários usuários encontrados:")
            for i, u in enumerate(userdirs):
                print(f"  {i + 1}. {u.name}")
            sel = UI.choice("Escolha o usuário:", [u.name for u in userdirs], default_index=0, enabled=enabled)
            return sel[0] if sel else userdirs[0].name
        return userdirs[0].name

    @staticmethod
    def _find_cloud_storage(userdata_dir):
        p = userdata_dir / "config" / "cloudstorage" / "cloud-storage-namespace-1.json"
        return p if p.exists() else None

    @staticmethod
    def _load_hidden(cs_file):
        hidden = set()
        try:
            d = json.load(open(cs_file, encoding="utf-8"))
            for e in d:
                if e[0] == "user-collections.hidden":
                    try:
                        hidden = set(json.loads(e[1]["value"]).get("added", []))
                    except Exception:
                        pass
        except Exception:
            pass
        return hidden

    def run(self):
        enabled = self._enabled()
        print("=== steamorganizer — Organizador de Biblioteca Steam (pt-BR) ===\n")

        self._ensure_deps()

        steam_path = self.args.get("steam_path")
        if not steam_path:
            steam_paths = self.detector.detect()
            if not steam_paths:
                sp = input("Caminho manual da Steam (ex: C:\\Program Files (x86)\\Steam): ").strip()
                steam_paths = [sp] if sp else []
            if not steam_paths:
                print("Nenhuma Steam encontrada. Saindo.")
                return
            steam_path = steam_paths[0]
        print(f"Steam: {steam_path}")

        userdirs = self._find_userdata_dirs(steam_path)
        if not userdirs:
            print("Nenhum userdata encontrado.")
            return

        steam_id = self._select_user(userdirs, enabled)
        userdata_dir = next((u for u in userdirs if u.name == steam_id), userdirs[0])
        cs_file = self._find_cloud_storage(userdata_dir)
        lc_file = userdata_dir / "config" / "localconfig.vdf"
        appinfo_file = Path(steam_path) / "appcache" / "appinfo.vdf"

        if not cs_file:
            print("cloud-storage-namespace-1.json não encontrado.")
            return

        print(f"Usuário: {steam_id}")
        print(f"Arquivo: {cs_file}\n")

        use_full = self.args.get("full", False)
        if not enabled and not use_full:
            use_full = True

        if not self.args.get("dry_run", False):
            dry_run = self.ui.confirm("Modo apenas visualizar (dry-run)? Não grava nada, só mostra o resumo.", default=False, enabled=enabled)
        else:
            dry_run = True

        cats_raw = [
            ("Ação 🎯", "acao", "🎯"), ("Aventura 🌍", "aventura", "🌍"),
            ("Cartas & Tabuleiro 🃏", "cartas", "🃏"), ("Casual & Puzzle 🧩", "casual", "🧩"),
            ("Co-op 🤝", "coop", "🤝"), ("Competitivo ⚔️", "competitivo", "⚔️"),
            ("Corrida 🚗", "corrida", "🚗"), ("Demos & Betas 🧪", "demos", "🧪"),
            ("Esportes ⚽", "esportes", "⚽"), ("Estratégia 🧠", "estrategia", "🧠"),
            ("Ferramentas 🛠️", "ferramentas", "🛠️"), ("Indie & Retrô 🕹️", "indie", "🕹️"),
            ("Jogando Agora ▶️", "jogando", "▶️"), ("Luta 🥊", "luta", "🥊"),
            ("MMO 🌐", "mmo", "🌐"), ("RPG 🗡️", "rpg", "🗡️"),
            ("Simulação 🏗️", "simulacao", "🏗️"), ("Sobrevivência 🌲", "sobrevivencia", "🌲"),
            ("Terror 👻", "terror", "👻"), ("Trilhas & Vídeos 🎬", "trilhas", "🎬"),
            ("VR 🥽", "vr", "🥽"), ("Outros 📁", "outros", "📁"),
        ]

        default_sel = [c[0] for c in cats_raw]
        sel_cats = self.ui.choice(
            "Quais categorias criar? (números separados por vírgula)",
            [c[0] for c in cats_raw],
            multiselect=True,
            enabled=enabled,
        )
        sel_set = set(sel_cats) if sel_cats else set(default_sel)
        cat_nomes = {c[1]: c[0] for c in cats_raw}
        cat_emojis = {c[1]: c[2] for c in cats_raw}

        criar_fam = self.ui.confirm("Criar coleção pai 'Franquias' (união dos jogos de mesma franquia)?", default=True, enabled=enabled)
        nome_fam = self.ui.input("Nome da coleção pai de franquias", default="Franquias 📂", enabled=enabled) or "Franquias 📂"

        criar_inst = self.ui.confirm("Deixar 'Instalados localmente' no topo da lista?", default=True, enabled=enabled)
        nome_inst = self.ui.input("Nome da coleção de instalados", default="📦 Instalados localmente", enabled=enabled) or "📦 Instalados localmente"

        print("\n⚠  A Steam será FECHADA e o arquivo cloud-storage será reescrito.")
        print("   Backup será feito automaticamente.")
        if dry_run:
            print("\n=== MODO DRY-RUN (apenas visualizar) ===")
        else:
            if not self.ui.confirm("Fechar Steam e aplicar agora?", default=True, enabled=enabled):
                print("Cancelado.")
                return

        if not dry_run:
            if not SteamManager.shutdown(self.ui):
                return

        backup_dir = None
        if not dry_run:
            backup_dir = Path(tempfile.gettempdir()) / f"steamorganizer_backup_{time.strftime('%Y%m%d_%H%M%S')}"
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cs_file, backup_dir / cs_file.name)
            if lc_file.exists():
                shutil.copy2(lc_file, backup_dir / lc_file.name)
            print(f"Backup: {backup_dir}")

        rows = LibraryBuilder.full(steam_path) if use_full else LibraryBuilder.fast(appinfo_file, lc_file)
        if not rows and use_full:
            print("Falha completa. Usando modo rápido.")
            rows = LibraryBuilder.fast(appinfo_file, lc_file)

        hidden = self._load_hidden(cs_file)

        groups = {}
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_app = {executor.submit(Classifier.classify, r): r for r in rows if int(r["appid"]) not in hidden}
            for future in concurrent.futures.as_completed(future_to_app):
                app = future_to_app[future]
                cols = future.result()
                aid = int(app["appid"])
                for c in cols:
                    groups.setdefault(c, set()).add(aid)

        final_groups = {}
        for c, appids in groups.items():
            nome_exibicao = c
            for interno, nome in cat_nomes.items():
                if interno in c or c.endswith(interno):
                    nome_exibicao = nome + " " + cat_emojis.get(interno, "")
                    break
            if nome_exibicao not in sel_set and nome_exibicao not in (nome_fam, nome_inst):
                continue
            final_groups.setdefault(nome_exibicao, set()).update(appids)

        franchise_cols = {}
        if criar_fam:
            for fname, pat, emoji in FRANCHISES:
                apps = set()
                for r in rows:
                    if r.get("apptype", 1) not in (1, 2):
                        continue
                    aid = int(r["appid"])
                    if aid in hidden:
                        continue
                    name = (r.get("name") or "").replace("®", "").replace("™", "")
                    if BAD_FRANCHISE.search(name):
                        continue
                    if re.search(pat, name, re.IGNORECASE):
                        apps.add(aid)
                if len(apps) >= 2:
                    col_name = f"{emoji} {fname}"
                    franchise_cols[col_name] = apps
                    final_groups[col_name] = apps

            all_franchise_apps = set()
            for apps in franchise_cols.values():
                all_franchise_apps.update(apps)
            if all_franchise_apps:
                final_groups[nome_fam] = all_franchise_apps

        order = []
        for interno in [c[1] for c in cats_raw]:
            nome = cat_nomes[interno] + " " + cat_emojis[interno]
            if nome in final_groups:
                order.append(nome)
        for col_name in franchise_cols:
            if col_name in final_groups:
                order.append(col_name)
        if criar_fam and nome_fam in final_groups:
            order.append(nome_fam)
        if criar_inst:
            order.append(nome_inst)

        print(f"\n{'=' * 50}")
        print(f"RESUMO ({'DRY-RUN - nada será gravado' if dry_run else 'APLICAR'})")
        print(f"{'=' * 50}")
        print(f"Total jogos classificados: {len(rows)}")
        print(f"Coleções a serem criadas/atualizadas: {len(order)}")
        for name in order:
            print(f"  {len(final_groups.get(name, set())):4d}  {name}")

        if dry_run:
            print("\n=== MODO DRY-RUN ENCERRADO. Nenhum arquivo foi modificado. ===")
            return

        writer = CollectionWriter(cs_file, self.ui, backup_path=backup_dir / cs_file.name if backup_dir else None)
        created, updated, orfãs = writer.write(final_groups, order, criar_inst, nome_inst)

        print(f"\nCriadas: {created}, Atualizadas: {updated}, Órfãs removidas: {orfãs}")
        print(f"Total jogos: {len(rows)}")
        for name in order:
            print(f"  {len(final_groups.get(name, set())):4d}  {name}")
        if backup_dir:
            print(f"\nBackup: {backup_dir}")
        print("\nConcluído! Reinicie a Steam para ver as coleções.")

        if self.ui.confirm("Reiniciar a Steam agora?", default=True, enabled=enabled):
            SteamManager.start()


def build_arg_parser():
    p = argparse.ArgumentParser(description="Organizador de Biblioteca Steam (pt-BR)")
    p.add_argument("--steam-path", help="Caminho da instalação Steam")
    p.add_argument("--user", help="SteamID3 da conta (ex: 376470568)")
    p.add_argument("--full", action="store_true", help="Modo completo (inclui família/empréstimo)")
    p.add_argument("--dry-run", action="store_true", help="Apenas visualizar, não grava nada")
    p.add_argument("--no-gum", action="store_true", help="Desativar gum, usar input()")
    p.add_argument("--no-restart", action="store_true", help="Não reiniciar a Steam ao final")
    return p


def main():
    parser = build_arg_parser()
    args = vars(parser.parse_args())
    if args.get("no_restart"):
        args["_no_restart"] = True
    SteamOrganizer(args).run()


if __name__ == "__main__":
    main()