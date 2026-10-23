#!/usr/bin/env python3
# =============================================================================
# steamorganizer — Organizador de Biblioteca Steam (pt-BR)
# Python puro — funciona no Windows e Linux
# Uso: python steamorganizer.py
# Gere um .exe no Windows com: pyinstaller --onefile --noconsole steamorganizer.py
# =============================================================================

import json
import os
import re
import random
import time
import secrets
import string
import shutil
import sys
import socket
import subprocess
import tempfile
from pathlib import Path


# =============================================================================
# Utilitários de plataforma
# =============================================================================

def is_windows():
    return sys.platform.startswith("win")


def expand_env(path):
    return Path(os.path.expandvars(str(path))).expanduser()


def detect_steam_paths():
    candidates = []
    if is_windows():
        candidates = [
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
        p = expand_env(c)
        if p.exists():
            found.append(str(p))
    return found


def find_userdata_dirs(steam_path):
    userdata = Path(steam_path) / "userdata"
    if not userdata.exists():
        return []
    return sorted([d for d in userdata.iterdir() if d.is_dir() and d.name.isdigit()])


def find_cloud_storage(userdata_dir):
    p = Path(userdata_dir) / "config" / "cloudstorage" / "cloud-storage-namespace-1.json"
    return p if p.exists() else None


# =============================================================================
# Perguntas interativas (gum se disponível, senão input())
# =============================================================================

def _run_gum(cmd):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.returncode == 0, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False, ""


def ask_choice(header, options, default_index=0, multiselect=False):
    """Retorna lista de strings selecionadas."""
    gum_ok, out = _run_gum(["gum", "choose", "--header", header,
                            "--limit", "0" if multiselect else "1",
                            "--height", str(min(len(options) + 2, 20))] + options)
    if gum_ok:
        if multiselect:
            return [x for x in out.splitlines() if x.strip()]
        return [out] if out else []
    # Fallback input()
    print(f"\n{header}")
    for i, o in enumerate(options):
        mark = " (default)" if i == default_index else ""
        print(f"  {i+1}. {o}{mark}")
    raw = input("Escolha os números separados por vírgula (ex: 1,3,5): ").strip()
    if not raw:
        return [options[default_index]]
    try:
        idxs = [int(x.strip()) - 1 for x in raw.split(",")]
        return [options[i] for i in idxs if 0 <= i < len(options)]
    except Exception:
        return [options[default_index]]


def ask_input(header, default="", placeholder=""):
    gum_ok, out = _run_gum(["gum", "input", "--header", header,
                            "--value", default or ""])
    if gum_ok:
        return out
    val = input(f"{header} [{default or placeholder}]: ").strip()
    return val if val else (default or placeholder or "")


def ask_confirm(header, default=True):
    gum_ok, _ = _run_gum(["gum", "confirm", "--default", str(default).lower(), "--header", header])
    if gum_ok:
        return True
    d = "S/n" if default else "s/N"
    resp = input(f"{header} [{d}]: ").strip().lower()
    if not resp:
        return default
    return resp in ("s", "sim", "y", "yes")


# =============================================================================
# Protobuf wire parser (snapshot da biblioteca completa via CEF)
# =============================================================================

def varint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1
        r |= (c & 0x7f) << s
        if not c & 0x80:
            return r, i
        s += 7


def fields(b):
    i, out = 0, []
    while i < len(b):
        k, i = varint(b, i)
        f, w = k >> 3, k & 7
        if w == 0:
            v, i = varint(b, i)
        elif w == 2:
            l, i = varint(b, i); v = b[i:i+l]; i += l
        elif w == 5:
            v = int.from_bytes(b[i:i+4], 'little'); i += 4
        elif w == 1:
            v = int.from_bytes(b[i:i+8], 'little'); i += 8
        else:
            raise ValueError(w)
        out.append((f, w, v))
    return out


def parse_overview_pb(path):
    b = open(path, 'rb').read()
    apps = []
    for f, w, v in fields(b):
        if f == 1 and w == 2:
            d = {}; tags = []
            for ff, ww, vv in fields(v):
                if ff == 19 and ww == 0:
                    tags.append(vv)
                elif ff == 2 and ww == 2:
                    d['name'] = vv.decode('utf-8', 'replace')
                elif ff in (1,4,5,7,8,9,10,11,12,13,14,16,17,18,20,21,22,26,27,31,36,37,46,53,54,55,56,65,66,68,73,77,79,80) and ww == 0:
                    d[ff] = vv
            d['appid'] = d.get(1)
            d['tags'] = [int(x) for x in tags]
            apps.append(d)
    return apps


# =============================================================================
# Nomes das tags
# =============================================================================

TAG_NAMES = {
    19:"Action",21:"Adventure",23:"Casual",25:"Indie",27:"Massively Multiplayer",
    29:"Racing",30:"RPG",31:"Simulation",32:"Sports",33:"Strategy",
    103:"Fighting",113:"MOBA",114:"Auto Battler",1718:"MOBA",1774:"FPS",
    1663:"FPS",3859:"Shooter",5711:"Tactical",3878:"Competitive",5055:"Co-op",
    492:"Indie",9:"Puzzle",1685:"Horror",1676:"Survival",4747:"Crafting",
    4711:"Open World",4231:"Story Rich",599:"Visual Novel",1775:"Point & Click",
    1645:"Walking Simulator",1684:"Choices Matter",3843:"Sandbox",
    1718:"Battle Royale",122:"Card Game",1708:"Deckbuilding",
}

def load_tag_names():
    for tf in [
        Path.home() / ".local" / "share" / "Steam" / "steamui" / "tagnames.json",
        Path.home() / "AppData" / "Roaming" / "Steam" / "steamui" / "tagnames.json",
        Path.home() / "AppData" / "Local" / "Steam" / "steamui" / "tagnames.json",
    ]:
        if tf.exists():
            try:
                for k, v in json.load(open(tf, encoding="utf-8")).items():
                    TAG_NAMES[int(k)] = v
            except Exception:
                pass
    try:
        import urllib.request
        data = urllib.request.urlopen(
            "https://store.steampowered.com/tagdata/populartags/english", timeout=8
        ).read().decode()
        for t in json.loads(data):
            TAG_NAMES[int(t['tagid'])] = t['name']
    except Exception:
        pass


load_tag_names()


def tnames(ids):
    return [TAG_NAMES.get(i, f"tag_{i}") for i in ids]


# =============================================================================
# Regras de classificação
# =============================================================================

CAT_MAP = {
    '🥊 Luta': {'Fighting','2D Fighter','3D Fighter'},
    '🚗 Corrida': {'Racing','Driving','Combat Racing','Automobile Sim','Motocross','Offroad'},
    '⚽ Esportes': {'Sports','Football (Soccer)','Football (American)','Basketball','Baseball','Tennis','Golf','Bowling','Skateboarding','Snowboarding','Hockey','Wrestling','Boxing','Cricket','Rugby','Volleyball','Billiards','Pool','Mini Golf','Snooker','Skiing','Cycling'},
    '🃏 Cartas & Tabuleiro': {'Card Game','Trading Card Game','Card Battler','Deckbuilding','Roguelike Deckbuilder','Board Game','Tabletop','Chess','Solitaire','Mahjong'},
    '👻 Terror': {'Horror','Survival Horror','Psychological Horror','Zombies','Lovecraftian','Jump Scare'},
    '🌐 MMO': {'MMORPG','Massively Multiplayer'},
    '🧠 Estratégia': {'Strategy','RTS','Turn-Based Strategy','4X','Grand Strategy','MOBA','Auto Battler','Tower Defense','Turn-Based Tactics','Real Time Tactics','Wargame','Political Sim'},
    '🏗️ Simulação': {'Simulation','Farming Sim','Life Sim','Management','City Builder','Colony Sim','Automation','Base Building','Building','Space Sim','God Game','Economy','Job Simulator','Hobby Sim','Medical Sim'},
    '🌲 Survival & Craft': {'Survival','Open World Survival Craft','Crafting'},
    '🗡️ RPG': {'RPG','Action RPG','JRPG','CRPG','Party-Based RPG','Strategy RPG','Tactical RPG','Souls-like','Dungeon Crawler','Roguelike','Roguelite','Traditional Roguelike','Loot'},
    '🌍 Aventura': {'Adventure','Action-Adventure','Exploration','Story Rich','Walking Simulator','Visual Novel','Point & Click','Choices Matter','Sandbox','Open World'},
    '🎯 Ação': {'Action','Shooter','FPS','Third-Person Shooter','Hack and Slash',"Beat 'em up","Shoot 'Em Up",'Arena Shooter','Boomer Shooter','Twin Stick Shooter','Bullet Hell','Action Roguelike','Spectacle fighter','Character Action Game','Combat','Swordplay','Martial Arts','Looter Shooter','Extraction Shooter','Vehicular Combat'},
    '🧩 Casual & Puzzle': {'Casual','Puzzle','Hidden Object','Match 3','Trivia','Word Game','Relaxing','Cozy','Idler','Incremental','Clicker','Party Game','Minigames','Logic','Sokoban','Social Deduction'},
    '🕹️ Indie & Retrô': {'Indie','Pixel Graphics','Retro','2D','Platformer','2D Platformer','3D Platformer','Precision Platformer','Puzzle Platformer','Metroidvania','Side Scroller','Arcade','Classic',"1990's",'1980s'},
}
TAG2CAT = {t: c for c, ts in CAT_MAP.items() for t in ts}
COOP = {'Co-op','Online Co-Op','Local Co-Op','Co-op Campaign','4 Player Local'}
PVP = {'PvP','Competitive','eSports','Battle Royale','MOBA','Hero Shooter','Team-Based'}

MANUAL = {
 '620':'🧩 Casual & Puzzle','227300':'🏗️ Simulação','480':'🎯 Ação','570':'🧠 Estratégia','730':'🎯 Ação',
 '359550':'🎯 Ação','292030':'🗡️ RPG','1091500':'🗡️ RPG','1174180':'🌍 Aventura','271590':'🌍 Aventura',
 '413150':'🏗️ Simulação','427520':'🏗️ Simulação','105600':'🌲 Survival & Craft','4000':'🧩 Casual & Puzzle',
 '252490':'🌲 Survival & Craft','578080':'🎯 Ação','1245620':'🗡️ RPG','892970':'🌲 Survival & Craft',
 '548430':'🎯 Ação','553850':'🎯 Ação','2357570':'🎯 Ação','2767030':'🎯 Ação','2141910':'🃏 Cartas & Tabuleiro',
 '599140':'🏗️ Simulação','1286830':'🌐 MMO','1085660':'🎯 Ação','1623730':'🌲 Survival & Craft','275850':'🌲 Survival & Craft',
 '1118310':'🛠️ Ferramentas','205190':'🧩 Casual & Puzzle','71340':'🕹️ Indie & Retrô',
 '202970':'🎯 Ação','202990':'🎯 Ação','212910':'🎯 Ação','218640':'👻 Terror','349040':'🥊 Luta',
 '407740':'🎯 Ação','438740':'👻 Terror','582160':'🌍 Aventura','637650':'🗡️ RPG','946610':'🎯 Ação',
 '1189780':'🎯 Ação','1208030':'🧩 Casual & Puzzle','1237980':'🎯 Ação','2675290':'🎯 Ação','2827200':'👻 Terror',
 '2920570':'🧩 Casual & Puzzle','3432970':'⚽ Esportes','4332910':'🧩 Casual & Puzzle',
 '457930':'🎯 Ação','457940':'🎯 Ação','473620':'🎯 Ação','473630':'🎯 Ação','473650':'🎯 Ação',
 '475240':'🎯 Ação','486340':'🎯 Ação','491250':'🎯 Ação','473580':'🃏 Cartas & Tabuleiro','974100':'🧩 Casual & Puzzle',
 '1657270':'📁 Outros','506770':'📁 Outros','3778240':'📁 Outros',
 '12100':'🎮 Grand Theft Auto','12230':'🎮 Grand Theft Auto','12120':'🎮 Grand Theft Auto','12250':'🎮 Grand Theft Auto','12110':'🎮 Grand Theft Auto',
}

FRANCHISES = [
    ('Resident Evil', r'\bresident evil\b|\bbiohazard\b|\bumbrella corps\b', '🧟'),
    ('Half-Life', r'\bhalf-?life\b|\bblack mesa\b', '🧪'),
    ('LEGO', r'\blego\b', '🧱'),
    ('Fallout', r'\bfallout\b', '☢️'),
    ('Warhammer', r'\bwarhammer\b', '🔨'),
    ('Counter-Strike', r'\bcounter-?strike\b', '🔫'),
    ('Grand Theft Auto', r'\bgrand theft auto\b|\bgta\b', '🚗'),
    ('Batman Arkham', r'^batman\b', '🦇'),
    ('BioShock', r'\bbioshock\b', '🌊'),
    ('Borderlands', r'\bborderlands\b', '🚜'),
    ('Dragon Ball', r'\bdragon ball\b', '🐲'),
    ('Saints Row', r'\bsaints row\b', '🟣'),
    ('Darksiders', r'\bdarksiders\b', '🐎'),
    ('Dead Rising', r'\bdead rising\b', '🧟'),
    ('Age of Empires', r'\bage of empires\b', '🏰'),
    ('Dark Souls', r'\bdark souls\b', '🔥'),
    ('Devil May Cry', r'\bdevil may cry\b|\bdmc\b', '😈'),
    ('Final Fantasy', r'\bfinal fantasy\b', '🧝'),
    ('Mafia', r'^mafia\b', '🕴️'),
    ('Metro', r'\bmetro (2033|last light|exodus|redux)\b', '☢️'),
    ('Penumbra', r'\bpenumbra\b', '🔦'),
    ('Beholder', r'\bbeholder\b', '👁️'),
    ('Hitman', r'^hitman\b', '🕴️'),
    ('Metal Gear', r'\bmetal gear\b', '📦'),
    ('Car Mechanic Simulator', r'\bcar mechanic simulator\b', '🔧'),
    ('Death Stranding', r'\bdeath stranding\b', '📦'),
    ('Deus Ex', r'\bdeus ex\b', '🔺'),
    ('Dishonored', r'\bdishonored\b', '🎭'),
    ('F1', r'\bf1 (19|20)\d\d\b|\bf1 2[0-9]\b', '🏎️'),
    ('Forza Horizon', r'\bforza\b', '🏎️'),
    ('Monster Hunter', r'\bmonster hunter\b', '🐲'),
    ('The Elder Scrolls', r'\belder scrolls\b|\bskyrim\b|\bmorrowind\b|\boblivion\b', '📜'),
    ('The Witcher', r'\bwitcher\b', '🐺'),
    ('Tomb Raider', r'\btomb raider\b|\blara croft\b', '🏺'),
    ('Train Simulator', r'\btrain sim(ulator)?\b', '🚆'),
    ('Wolfenstein', r'\bwolfenstein\b', '🐺'),
    ('Wargame', r'\bwargame\b', '🗺️'),
    ('Subnautica', r'\bsubnautica\b', '🌊'),
    ('Space Pilgrim', r'\bspace pilgrim\b', '🚀'),
    ('Call of Duty', r'\bcall of duty\b', '🎖️'),
]

BAD_FRANCHISE_APP = re.compile(r'test server|public test|open beta|\bbeta\b|experimental|bonus content|soundtrack|\bdemo\b|playtest', re.IGNORECASE)


def classify(app):
    t = app.get('apptype', 1)
    tags = app.get('tags', [])
    tn = tnames(tags)
    top = set(tn[:8])

    if t == 4:
        return ['🛠️ Ferramentas']
    if t in (8, 65536):
        return ['🧪 Demos & Betas']
    if t in (2, 256):
        return ['🛠️ Ferramentas']
    if t in (2048, 8192):
        return ['🎬 Trilhas & Vídeos']

    aid = str(app.get('appid'))
    if aid in MANUAL:
        cols = [MANUAL[aid]]
    elif 'MMORPG' in tn[:3]:
        cols = ['🌐 MMO']
    else:
        cols = ['📁 Outros']
        for x in tn:
            if x in TAG2CAT:
                cols = [TAG2CAT[x]]
                break

    if top & COOP:
        cols.append('🤝 Co-op')
    if top & PVP:
        cols.append('⚔️ Competitivo')
    if 'VR' in tags or 'VR' in tn:
        cols.append('🥽 VR')
    if 'Indie' in tn and '🕹️ Indie & Retrô' not in cols:
        cols.append('🕹️ Indie & Retrô')
    if app.get('installed', False):
        cols.append('📦 Instalados')
    now = time.time()
    if app.get('play2w', 0) > 0 or (app.get('lastplayed', 0) and now - app['lastplayed'] < 30 * 86400 and app.get('playtime', 0) > 0):
        cols.append('▶️ Jogando Agora')
    return list(dict.fromkeys(cols))


# =============================================================================
# Montagem da biblioteca
# =============================================================================

def build_library_full(steam_path):
    """Captura biblioteca completa via CEF debug (requer Steam com -cef-enable-debugging)."""
    steam_bin = shutil.which("steam") or ("steam.exe" if is_windows() else "/usr/bin/steam")
    marker = Path(tempfile.gettempdir()) / "steamorganizer_debug_marker"
    if not marker.exists():
        try:
            subprocess.Popen([steam_bin, "-cef-enable-debugging"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(30):
                s = socket.socket()
                try:
                    s.connect(("127.0.0.1", 8080)); s.close(); break
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

    shared = [t for t in targets if t.get('title') == 'SharedJSContext']
    if not shared:
        print("SharedJSContext não encontrado. Rode a Steam com -cef-enable-debugging.")
        return []
    ws_url = shared[0]['webSocketDebuggerUrl']

    buf = {"data": None}

    def on_message(ws, message):
        m = json.loads(message)
        if m.get('id') == 1 and 'result' in m:
            buf['data'] = m['result']['result']['value']
            ws.close()

    def on_open(ws):
        expr = ("window.__ovbuf=null;SteamClient.Apps.RegisterForAppOverviewChanges(b=>{window.__ovbuf=b});"
                "setTimeout(()=>{},2500)")
        ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True,"awaitPromise":True}}))

    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
    ws.run_forever(timeout=10)

    if buf['data'] is None:
        return []

    import base64
    raw = base64.b64decode(buf['data'])
    pb_path = Path(tempfile.gettempdir()) / "overview.pb"
    pb_path.write_bytes(raw)
    apps = parse_overview_pb(pb_path)

    now = time.time()
    out = []
    for a in apps:
        out.append({
            'appid': str(a.get('appid')),
            'name': a.get('name') or '',
            'apptype': a.get(7, 1),
            'tags': a.get('tags', []),
            'installed': (a.get(37, 0) or 0) > 0,
            'playtime': a.get(16, 0) or 0,
            'play2w': a.get(17, 0) or 0,
            'lastplayed': a.get(14, 0) or 0,
        })
    return out


def build_library_fast(appinfo_path, lc_path):
    """Constrói a partir do appinfo.vdf + localconfig.vdf (mais rápido, menos completo)."""
    try:
        import vdf
    except ImportError:
        print("módulo vdf não instalado. pip install vdf")
        return []

    apps_data = {}
    try:
        ai = vdf.load(open(appinfo_path, encoding='utf-8', errors='replace'))
        for appid, app in ai.get('apps', {}).items():
            common = app.get('common', {})
            apps_data[appid] = {
                'appid': appid,
                'name': common.get('name', ''),
                'apptype': 1,
                'tags': app.get('store_tags', []) or [],
                'installed': False,
                'playtime': 0, 'play2w': 0, 'lastplayed': 0,
            }
    except Exception as e:
        print(f"appinfo.vdf não lido: {e}")

    try:
        lc = vdf.load(open(lc_path, encoding='utf-8', errors='replace'))
        userapps = lc.get('UserLocalConfigStore', {}).get('apps', {})
        for appid, app in userapps.items():
            if appid in apps_data:
                apps_data[appid]['playtime'] = app.get('playtime', 0) or 0
                apps_data[appid]['lastplayed'] = app.get('lastplayed', 0) or 0
                apps_data[appid]['installed'] = (app.get('installed', 0) or 0) == 1
            else:
                apps_data[appid] = {
                    'appid': appid, 'name': app.get('name', ''),
                    'apptype': 1, 'tags': [],
                    'installed': (app.get('installed', 0) or 0) == 1,
                    'playtime': app.get('playtime', 0) or 0, 'play2w': 0,
                    'lastplayed': app.get('lastplayed', 0) or 0,
                }
    except Exception as e:
        print(f"localconfig.vdf não lido: {e}")

    return list(apps_data.values())


# =============================================================================
# Principal
# =============================================================================

def ensure_deps():
    """Tenta instalar dependências Python automaticamente (vdf, websocket-client)."""
    for pkg in ["vdf", "websocket-client"]:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            print(f"Instalando dependência: {pkg} ...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                print(f"  {pkg} instalado com sucesso.")
            except Exception as e:
                print(f"  Não foi possível instalar {pkg}: {e}")
                print(f"  Rode manualmente: pip install {pkg}")


def main():
    ensure_deps()
    print("=== steamorganizer — Organizador de Biblioteca Steam (pt-BR) ===\n")

    steam_paths = detect_steam_paths()
    if not steam_paths:
        sp = input("Caminho manual da Steam (ex: C:\\Program Files (x86)\\Steam): ").strip()
        steam_paths = [sp] if sp else []
    if not steam_paths:
        print("Nenhuma Steam encontrada. Saindo.")
        return

    steam_path = steam_paths[0]
    print(f"Steam: {steam_path}")

    userdirs = find_userdata_dirs(steam_path)
    if not userdirs:
        print("Nenhum userdata encontrado.")
        return

    if len(userdirs) > 1:
        print("Vários usuários encontrados:")
        for i, u in enumerate(userdirs):
            print(f"  {i+1}. {u.name}")
        sel = ask_choice("Escolha o usuário:", [u.name for u in userdirs], default_index=0)
        steam_id = sel[0] if sel else userdirs[0].name
    else:
        steam_id = userdirs[0].name

    userdata_dir = next((u for u in userdirs if u.name == steam_id), userdirs[0])
    cs_file = find_cloud_storage(userdata_dir)
    lc_file = userdata_dir / "config" / "localconfig.vdf"
    appinfo_file = Path(steam_path) / "appcache" / "appinfo.vdf"

    if not cs_file:
        print("cloud-storage-namespace-1.json não encontrado.")
        return

    print(f"Usuário: {steam_id}")
    print(f"Arquivo: {cs_file}\n")

    # Perguntas
    modo = ask_choice(
        "Como montar a lista de jogos?",
        ["Rápida (só jogos com tempo/config)", "Completa (todos, inclui família/empréstimo)"],
        default_index=1
    )
    use_full = "Completa" in modo[0] if modo else False

    cats_raw = [
        ("Ação 🎯","acao","🎯"),("Aventura 🌍","aventura","🌍"),
        ("Cartas & Tabuleiro 🃏","cartas","🃏"),("Casual & Puzzle 🧩","casual","🧩"),
        ("Co-op 🤝","coop","🤝"),("Competitivo ⚔️","competitivo","⚔️"),
        ("Corrida 🚗","corrida","🚗"),("Demos & Betas 🧪","demos","🧪"),
        ("Esportes ⚽","esportes","⚽"),("Estratégia 🧠","estrategia","🧠"),
        ("Ferramentas 🛠️","ferramentas","🛠️"),("Indie & Retrô 🕹️","indie","🕹️"),
        ("Jogando Agora ▶️","jogando","▶️"),("Luta 🥊","luta","🥊"),
        ("MMO 🌐","mmo","🌐"),("RPG 🗡️","rpg","🗡️"),
        ("Simulação 🏗️","simulacao","🏗️"),("Sobrevivência 🌲","sobrevivencia","🌲"),
        ("Terror 👻","terror","👻"),("Trilhas & Vídeos 🎬","trilhas","🎬"),
        ("VR 🥽","vr","🥽"),("Outros 📁","outros","📁"),
    ]

    sel_cats = ask_choice(
        "Quais categorias criar? (números separados por vírgula)",
        [c[0] for c in cats_raw],
        multiselect=True
    )
    sel_set = set(sel_cats) if sel_cats else set(c[0] for c in cats_raw)

    cat_nomes = {c[1]: c[0] for c in cats_raw}
    cat_emojis = {c[1]: c[2] for c in cats_raw}

    criar_fam = ask_confirm("Criar coleção pai 'Franquias' (união dos jogos de mesma franquia)?", default=True)
    nome_fam = ask_input("Nome da coleção pai de franquias", default="Franquias 📂") or "Franquias 📂"

    criar_inst = ask_confirm("Deixar 'Instalados localmente' no topo da lista?", default=True)
    nome_inst = ask_input("Nome da coleção de instalados", default="📦 Instalados localmente") or "📦 Instalados localmente"

    print("\n⚠  A Steam será FECHADA e o arquivo cloud-storage será reescrito.")
    print("   Backup será feito automaticamente.")
    if not ask_confirm("Fechar Steam e aplicar agora?", default=True):
        print("Cancelado.")
        return

    # Backup
    backup_dir = Path(tempfile.gettempdir()) / f"steamorganizer_backup_{time.strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cs_file, backup_dir / cs_file.name)
    if lc_file.exists():
        shutil.copy2(lc_file, backup_dir / lc_file.name)
    print(f"Backup: {backup_dir}")

    # Montar biblioteca
    if use_full:
        rows = build_library_full(steam_path)
        if not rows:
            print("Falha completa. Usando modo rápido.")
            rows = build_library_fast(appinfo_file, lc_file)
    else:
        rows = build_library_fast(appinfo_file, lc_file)

    # Hidden
    hidden = set()
    try:
        d = json.load(open(cs_file, encoding='utf-8'))
        for e in d:
            if e[0] == 'user-collections.hidden':
                try:
                    hidden = set(json.loads(e[1]['value']).get('added', []))
                except Exception:
                    pass
    except Exception:
        pass

    groups = {}
    for r in rows:
        aid = int(r['appid'])
        if aid in hidden:
            continue
        for c in classify(r):
            groups.setdefault(c, set()).add(aid)

    # Aplicar nomes customizados e filtros selecionados
    final_groups = {}
    for c, appids in groups.items():
        nome_exibicao = c
        for interno, nome in cat_nomes.items():
            if interno in c or c.endswith(interno):
                nome_exibicao = nome + ' ' + cat_emojis.get(interno, '')
                break
        if nome_exibicao not in sel_set and nome_exibicao not in (nome_fam, nome_inst):
            continue
        final_groups.setdefault(nome_exibicao, set()).update(appids)

    # Franquias individuais (sem prefixo "Franquia:", apenas ícone + nome)
    franchise_cols = {}
    if criar_fam:
        for fname, pat, emoji in FRANCHISES:
            apps = set()
            for r in rows:
                if r.get('apptype', 1) not in (1, 2):
                    continue
                aid = int(r['appid'])
                if aid in hidden:
                    continue
                name = (r.get('name') or '').replace('®','').replace('™','')
                if BAD_FRANCHISE_APP.search(name):
                    continue
                if re.search(pat, name, re.IGNORECASE):
                    apps.add(aid)
            if len(apps) >= 2:
                col_name = f"{emoji} {fname}"
                franchise_cols[col_name] = apps
                final_groups[col_name] = apps

        # Coleção pai (união de todas as franquias)
        all_franchise_apps = set()
        for apps in franchise_cols.values():
            all_franchise_apps.update(apps)
        if all_franchise_apps:
            final_groups[nome_fam] = all_franchise_apps

    # Ordem de gravação
    ORDER = []
    ordem_padrao = [c[1] for c in cats_raw]
    for interno in ordem_padrao:
        nome = cat_nomes[interno] + ' ' + cat_emojis[interno]
        if nome in final_groups:
            ORDER.append(nome)
    # Coleções individuais de franquia (ícone + nome, sem "Franquia:")
    for col_name in franchise_cols:
        if col_name in final_groups:
            ORDER.append(col_name)
    if criar_fam and nome_fam in final_groups:
        ORDER.append(nome_fam)
    if criar_inst:
        ORDER.append(nome_inst)

    # Gravar JSON
    d = json.load(open(cs_file, encoding='utf-8'))
    by_key = {e[0]: e for e in d}
    existing_by_name = {}
    for e in d:
        if e[0].startswith('user-collections.') and not e[1].get('is_deleted'):
            try:
                v = json.loads(e[1]['value'])
            except Exception:
                continue
            if v.get('name'):
                existing_by_name[v['name']] = e[0]

    rnd = random.Random(int(time.time()))

    def new_id():
        while True:
            k = 'uc-' + ''.join(rnd.choice(string.ascii_letters + string.digits) for _ in range(12))
            if 'user-collections.' + k not in by_key:
                return k

    now = int(time.time())
    created = updated = 0

    for name in ORDER:
        apps = sorted(final_groups.get(name, set()))
        if not apps and name != nome_inst:
            continue
        key = existing_by_name.get(name)
        if key:
            updated += 1
        else:
            key = 'user-collections.' + new_id()
            created += 1
        val = {'id': key.split('.', 1)[1], 'name': name, 'added': apps, 'removed': []}
        entry = [key, {'key': key, 'timestamp': now,
                       'value': json.dumps(val, ensure_ascii=False, separators=(',', ':')), 'version': '596'}]
        if key in by_key:
            idx = next(i for i, x in enumerate(d) if x[0] == key)
            d[idx] = entry
        else:
            d.append(entry)
        by_key[key] = entry

    # Renomear coleção instalados localmente
    if criar_inst:
        inst_key = existing_by_name.get('Instalados localmente') or existing_by_name.get(nome_inst)
        if inst_key and inst_key in by_key:
            e = by_key[inst_key]
            v = json.loads(e[1]['value'])
            v['name'] = nome_inst
            e[1]['value'] = json.dumps(v, ensure_ascii=False, separators=(',', ':'))
            e[1]['timestamp'] = now

    tmp = str(cs_file) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, cs_file)

    print(f"\nCriadas: {created}, Atualizadas: {updated}")
    print(f"Total jogos: {len(rows)}")
    for name in ORDER:
        print(f"  {len(final_groups.get(name, set())):4d}  {name}")
    print(f"\nBackup: {backup_dir}")
    print("\nConcluído! Reinicie a Steam para ver as coleções.")


if __name__ == '__main__':
    main()