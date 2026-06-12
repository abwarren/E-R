"""
PLO4 8MAX EXACT EQUITY ENGINE
Usage:
  python plo4-8max.py hands.txt
  python plo4-8max.py hands.txt --names playermapping.txt
"""
import sys, os, time, eval7
from itertools import combinations
from colorama import init, Fore, Style
from multiprocessing import Pool, cpu_count, freeze_support
from datetime import datetime
init(autoreset=True)
EPS = 1e-9
MAX_PLAYERS = 8
NUM_PLAYERS = 8  # overridden from input
HOLE_CARDS = 4

def validate_no_duplicates(cards, context=""):
    seen = set()
    for c in cards:
        s = str(c)
        if s in seen:
            raise ValueError(f"DUPLICATE_CARD_DETECTED: {s}" + (f" [{context}]" if context else ""))
        seen.add(s)

def hdr(title, color=Fore.CYAN):
    pad = (88 - len(title)) // 2
    print(f"\n{color}{Style.BRIGHT}{'='*90}")
    print(f"|{' '*pad}{title}{' '*(88-pad-len(title))}|")
    print(f"{'='*90}{Style.RESET_ALL}")
def section(title, color=Fore.YELLOW):
    print(f"\n{color}{Style.BRIGHT}+- {title} {'-'*(82-len(title))}+{Style.RESET_ALL}")
def field(label, value, color=Fore.WHITE):
    print(f"  {Fore.CYAN}{label:<28}{color}{value}{Style.RESET_ALL}")
def ok(msg):   print(f"  {Fore.GREEN}{Style.BRIGHT}OK  {msg}{Style.RESET_ALL}")
def warn(msg): print(f"  {Fore.YELLOW}{Style.BRIGHT}!!  {msg}{Style.RESET_ALL}")
def err(msg):  print(f"  {Fore.RED}{Style.BRIGHT}ERR {msg}{Style.RESET_ALL}")

# ── Variant rules ────────────────────────────────────────────────────────────
def parse_variant(variant_key: str) -> dict:
    import re
    m = re.match(r'^plo(\d+)-(\d+)max$', variant_key.strip().lower())
    if not m:
        raise ValueError(f"Unrecognised variant '{variant_key}'")
    plo_n   = int(m.group(1))
    players = int(m.group(2))
    return {
        'variant':          f'PLO{plo_n}-{players}MAX',
        'plo_n':            plo_n,
        'players':          players,
        'hole_cards':       plo_n,
        'flop_cards':       3,
        'total_lines_min':  players,
        'total_lines_flop': players + 1,
        'total_lines_max':  players + 2,
        'flop_line':        players + 1,
        'total_cards':      players * plo_n + 3,
        'total_characters': (players * plo_n + 3) * 2,
        'chars_per_hand':   plo_n * 2,
        'chars_per_flop':   6,
    }
def equity_bar(pctA, pctB, width=50):
    a = max(1, round(pctA / 100 * width)); b = width - a
    return (f"[{Fore.GREEN}{'#'*a}{Fore.RED}{'#'*b}{Style.RESET_ALL}]"
            f"  {Fore.GREEN}{pctA:5.1f}%{Style.RESET_ALL} vs {Fore.RED}{pctB:5.1f}%{Style.RESET_ALL}")
def fmt_time(s): return f"{s:.2f}s" if s < 60 else f"{int(s//60)}m {s%60:.1f}s"
RANK_MAP = {"A":"A","K":"K","Q":"Q","J":"J","T":"T","10":"T","9":"9","8":"8","7":"7","6":"6","5":"5","4":"4","3":"3","2":"2"}
VALID_SUITS  = {"s","h","d","c"}
SUIT_SYMBOLS = {"s":"\u2660","h":"\u2665","d":"\u2666","c":"\u2663"}
def parse_card(s, context=""):
    s = "".join(ch for ch in s if ch.isprintable()).strip().upper()
    if not s: raise ValueError("Empty token" + (f" [{context}]" if context else ""))
    if s[:2] == "10": r_raw, su_raw = "10", s[2:3] if len(s) > 2 else ""
    elif len(s) >= 2: r_raw, su_raw = s[0], s[1]
    else: raise ValueError(f"Token too short: '{s}'" + (f" [{context}]" if context else ""))
    r = RANK_MAP.get(r_raw); su = su_raw.lower()
    if r is None: raise ValueError(f"Unknown rank '{r_raw}' in '{s}'" + (f" [{context}]" if context else ""))
    if su not in VALID_SUITS: raise ValueError(f"Unknown suit '{su_raw}' in '{s}'" + (f" [{context}]" if context else ""))
    try: card = eval7.Card(r + su)
    except Exception as e: raise ValueError(f"eval7 rejected '{r+su}': {e}" + (f" [{context}]" if context else ""))
    suit_color = Fore.RED if su in ("h","d") else Fore.WHITE
    return card, f"{r}{suit_color}{SUIT_SYMBOLS[su]}{Style.RESET_ALL}"
def _tokenise(raw):
    raw = "".join(ch for ch in raw if ch.isprintable()).strip().upper()
    tokens, i = [], 0
    while i < len(raw):
        if raw[i:i+2] == "10": tokens.append(raw[i:i+3]); i += 3
        else: tokens.append(raw[i:i+2]); i += 2
    return tokens
def parse_board_line(raw, expected_n, label):
    raw = "".join(ch for ch in raw if ch.isprintable()).strip()
    tokens = raw.split() if " " in raw else _tokenise(raw)
    if len(tokens) != expected_n:
        err(f"{label}: expected {expected_n} card(s), got {len(tokens)} from '{raw}'"); sys.exit(1)
    cards, labels = [], []
    for idx, tok in enumerate(tokens, 1):
        try: c, lbl = parse_card(tok, context=f"{label} card {idx}")
        except ValueError as e: err(f"{e}"); sys.exit(1)
        cards.append(c); labels.append(lbl)
    return cards, labels
def load_name_mapping(path):
    mapping = {}
    if not os.path.isfile(path): err(f"Name-mapping file not found: {path}"); sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"): continue
            if "=" not in line: warn(f"playermapping line {lineno} skipped (no '='): '{line}'"); continue
            left, _, right = line.partition("="); key, value = left.strip(), right.strip()
            if key and value: mapping[key] = value
    return mapping
def parse_args():
    a = {"input_file": None, "names_file": None}; i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--names" and i+1 < len(sys.argv): a["names_file"] = sys.argv[i+1]; i += 2
        elif a["input_file"] is None: a["input_file"] = sys.argv[i]; i += 1
        else: i += 1
    return a
def rank_matchups(candidates):
    for c in candidates: c["disparity"] = c["under_real"] - c["under_raw"]
    return sorted(candidates, key=lambda c: c["disparity"], reverse=False)

def parse_hand_line(raw_line):
    line = "".join(ch for ch in raw_line if ch.isprintable()).strip()
    player_name = None; hand_raw = line
    for delim in ("=", "+"):
        if delim in line:
            parts = line.split(delim, 1)
            if len(_tokenise(parts[0].strip())) == HOLE_CARDS:
                hand_raw = parts[0].strip(); player_name = parts[1].strip() if len(parts) > 1 else None; break
    else:
        parts = line.split(None, 1)
        if len(parts) > 1 and len(_tokenise(parts[0].strip())) == HOLE_CARDS:
            hand_raw = parts[0].strip(); player_name = parts[1].strip()
    tokens = _tokenise(hand_raw)
    if len(tokens) != HOLE_CARDS:
        err(f"Expected {HOLE_CARDS} cards in '{hand_raw}', got {len(tokens)}: {tokens}"); sys.exit(1)
    cards, labels = [], []
    for idx, tok in enumerate(tokens, 1):
        try: c, lbl = parse_card(tok, context=f"hand '{hand_raw}' card {idx}")
        except ValueError as e: err(f"{e}"); sys.exit(1)
        cards.append(c); labels.append(lbl)
    return cards, labels, player_name

def plo4_best_hand(hole4, board5):
    best = -1
    for h2 in combinations(hole4, 2):
        for b3 in combinations(board5, 3):
            val = eval7.evaluate(list(h2) + list(b3))
            if val > best: best = val
    return best

def _worker_turn_river(args):
    holeA_s, holeB_s, board_s, chunk_s = args
    holeA = [eval7.Card(s) for s in holeA_s]; holeB = [eval7.Card(s) for s in holeB_s]
    board = [eval7.Card(s) for s in board_s]; wA = wB = ties = 0
    for turn_s, river_s in chunk_s:
        b5 = board + [eval7.Card(turn_s), eval7.Card(river_s)]
        a = plo4_best_hand(holeA, b5); b = plo4_best_hand(holeB, b5)
        if a > b: wA += 1
        elif b > a: wB += 1
        else: ties += 1
    return wA, wB, ties
def _worker_river_only(args):
    holeA_s, holeB_s, board_s, chunk_s = args
    holeA  = [eval7.Card(s) for s in holeA_s]; holeB  = [eval7.Card(s) for s in holeB_s]
    board4 = [eval7.Card(s) for s in board_s]; wA = wB = ties = 0
    for river_s in chunk_s:
        b5 = board4 + [eval7.Card(river_s)]
        a = plo4_best_hand(holeA, b5); b = plo4_best_hand(holeB, b5)
        if a > b: wA += 1
        elif b > a: wB += 1
        else: ties += 1
    return wA, wB, ties
def exact_equity_hu_plo4(holeA, holeB, board, dead=()):
    all_cards = list(holeA) + list(holeB) + list(board) + list(dead)
    validate_no_duplicates(all_cards, "exact_equity_hu_plo4")
    used   = set(str(c) for c in all_cards)
    if len(all_cards) != len(used):
        raise RuntimeError(f"INVALID_DECK_STATE: expected {len(all_cards)} cards, got {len(used)} unique")
    deck_s = [str(c) for c in eval7.Deck().cards if str(c) not in used]
    holeA_s, holeB_s, board_s = [str(c) for c in holeA],[str(c) for c in holeB],[str(c) for c in board]
    ncpu = max(1, cpu_count()); on_turn = (len(board) == 4)
    if on_turn:
        runouts = deck_s; total = len(runouts)
        if total == 0: return 50.0, 50.0, 0, 0, 0, 0
        chunk_size = max(1, (total+ncpu-1)//ncpu)
        chunks = [runouts[i:i+chunk_size] for i in range(0, total, chunk_size)]
        jobs = [(holeA_s, holeB_s, board_s, ch) for ch in chunks]; worker = _worker_river_only
    else:
        runouts = list(combinations(deck_s, 2)); total = len(runouts)
        if total == 0: return 50.0, 50.0, 0, 0, 0, 0
        chunk_size = max(1, (total+ncpu-1)//ncpu)
        chunks = [runouts[i:i+chunk_size] for i in range(0, total, chunk_size)]
        jobs = [(holeA_s, holeB_s, board_s, ch) for ch in chunks]; worker = _worker_turn_river
    with Pool(processes=ncpu) as pool: results = pool.map(worker, jobs)
    wA = sum(r[0] for r in results); wB = sum(r[1] for r in results); ties = sum(r[2] for r in results)
    pctA = 100.0 * (wA + 0.5*ties) / total
    return pctA, 100.0-pctA, total, wA, wB, ties
def calc_pair_equities(p1, p2, board, other_hole_cards):
    h1, h2 = p1["hole4"], p2["hole4"]
    t0 = time.perf_counter()
    raw_a,raw_b,raw_n,raw_wA,raw_wB,raw_ties = exact_equity_hu_plo4(h1,h2,board,dead=())
    raw_ms = (time.perf_counter()-t0)*1000
    t0 = time.perf_counter()
    rea_a,rea_b,rea_n,rea_wA,rea_wB,rea_ties = exact_equity_hu_plo4(h1,h2,board,dead=other_hole_cards)
    rea_ms = (time.perf_counter()-t0)*1000
    return {
        "raw":      {"pctA":raw_a,"pctB":raw_b,"n":raw_n,"wA":raw_wA,"wB":raw_wB,"ties":raw_ties,"ms":raw_ms},
        "realized": {"pctA":rea_a,"pctB":rea_b,"n":rea_n,"wA":rea_wA,"wB":rea_wB,"ties":rea_ties,"ms":rea_ms},
    }

if __name__ == "__main__":
    freeze_support()
    run_start = time.perf_counter()
    hdr("PLO4 8MAX EXACT EQUITY ENGINE", Fore.MAGENTA)
    field("Run timestamp", datetime.now().strftime("%Y-%m-%d  %H:%M:%S"), Fore.WHITE)
    field("CPU cores",     str(cpu_count()), Fore.WHITE)
    field("Mode",          "Full exact enumeration — ALL pairs shown, NO skipping", Fore.GREEN)
    cli = parse_args()
    if not cli["input_file"]:
        err("Usage: python plo4-8max.py hands.txt [--names playermapping.txt]"); sys.exit(1)
    name_map = {}
    if cli["names_file"]:
        section("NAME MAPPING", Fore.CYAN)
        field("Mapping file", cli["names_file"])
        name_map = load_name_mapping(cli["names_file"])
        for k, v in name_map.items(): field(f"  {k}", v, Fore.YELLOW)
        ok(f"{len(name_map)} name(s) loaded")
    filename = cli["input_file"]
    section("FILE LOAD", Fore.CYAN)
    field("File", filename)
    try:
        with open(filename, "r", encoding="utf-8") as f: raw_lines = f.readlines()
    except Exception as e: err(f"Cannot read file: {e}"); sys.exit(1)
    field("Total raw lines", str(len(raw_lines)))
    section("RAW LINE INSPECTION", Fore.CYAN)
    non_empty_lines = []
    for idx, raw in enumerate(raw_lines, 1):
        cleaned = "".join(ch for ch in raw if ch.isprintable()).strip()
        if not cleaned:
            print(f"  {Fore.CYAN}Line {idx:>3}{Style.RESET_ALL}  {Fore.WHITE}(empty — skipped){Style.RESET_ALL}"); continue
        hex_repr   = " ".join(f"{ord(c):02X}" for c in cleaned)
        suspicious = [c for c in cleaned if ord(c) > 127]
        flag = (f"  {Fore.RED}{Style.BRIGHT}!! SUSPICIOUS: {[hex(ord(c)) for c in suspicious]}{Style.RESET_ALL}" if suspicious else "")
        print(f"  {Fore.CYAN}Line {idx:>3}{Style.RESET_ALL}  {Fore.YELLOW}{cleaned:<18}{Style.RESET_ALL}  {Fore.WHITE}hex: {hex_repr}{Style.RESET_ALL}{flag}")
        if cleaned != raw.strip(): warn(f"Line {idx}: stripped non-printable chars")
        non_empty_lines.append(cleaned)
    field("Non-empty lines", str(len(non_empty_lines)))
    # Dynamic player count: accept 2+ hands
    hand_char_len = HOLE_CARDS * 2
    board_char_lens = {2, 4, 6, 8, 10}
    hand_indices = []
    board_idx = None
    for il, line in enumerate(non_empty_lines):
        token = line.split()[0] if ' ' in line else line
        tlen = len(token)
        if tlen in board_char_lens and tlen != hand_char_len :
            board_idx = il
        else:
            hand_indices.append(il)
    if board_idx is None and len(hand_indices) >= 3:
        last_il = hand_indices[-1]
        token = non_empty_lines[last_il].split()[0] if ' ' in non_empty_lines[last_il] else non_empty_lines[last_il]
        if len(token) in board_char_lens and len(token) != hand_char_len:
            board_idx = last_il
            hand_indices = hand_indices[:-1]
    NUM_PLAYERS = len(hand_indices)
    if NUM_PLAYERS < 2:
        err(f"Need at least 2 hands, got {NUM_PLAYERS}"); sys.exit(1)
    if NUM_PLAYERS > MAX_PLAYERS:
        err(f"Too many hands ({NUM_PLAYERS}) for {MAX_PLAYERS}-max"); sys.exit(1)
    ok(f"File loaded ({NUM_PLAYERS} hands" + (f" + board" if board_idx is not None else "") + ")")
    section("PARSING HANDS", Fore.CYAN)
    players, all_known_cards = [], []
    for idx in range(NUM_PLAYERS):
        raw = non_empty_lines[hand_indices[idx]]
        cards, labels, inline_name = parse_hand_line(raw)
        hand_tag = "".join(str(c) for c in cards)
        map_key      = f"Player{idx+1}"
        display_name = name_map.get(map_key) or inline_name or map_key
        pretty = "  ".join(labels)
        print(f"  {Fore.WHITE}Player {idx+1:>2}  {Fore.YELLOW}{hand_tag:<15}{Style.RESET_ALL}  {Fore.CYAN}({display_name}){Style.RESET_ALL}  ->  {pretty}")
        players.append({"raw": raw, "name": display_name, "tag": hand_tag, "hole4": cards, "pretty": pretty})
        all_known_cards.extend(cards)
    board = []
    if board_idx is not None:
        section("PARSING FLOP", Fore.CYAN)
        flop_cards, flop_labels = parse_board_line(non_empty_lines[board_idx], 3, "Flop")
        board.extend(flop_cards); all_known_cards.extend(flop_cards)
        field("Flop", non_empty_lines[board_idx])
        print(f"  Parsed: {'  '.join(flop_labels)}"); ok("Flop parsed")
    if board_idx is not None and board_idx + 1 < len(non_empty_lines):
        section("PARSING TURN", Fore.CYAN)
        turn_cards, turn_labels = parse_board_line(non_empty_lines[NUM_PLAYERS+1], 1, "Turn")
        board.extend(turn_cards); all_known_cards.extend(turn_cards)
        field("Turn", non_empty_lines[NUM_PLAYERS+1])
        print(f"  Parsed: {turn_labels[0]}"); ok("Turn parsed")
    section("STREET & DECK STATS", Fore.CYAN)
    street = "PRE-FLOP" if len(board)==0 else ("FLOP" if len(board)==3 else "TURN")
    used_total    = NUM_PLAYERS * HOLE_CARDS + len(board)
    remaining_raw = 52 - used_total
    dead_per_pair = (NUM_PLAYERS - 2) * HOLE_CARDS
    remaining_rea = max(0, remaining_raw - dead_per_pair)
    if street == "TURN":
        raw_runouts = remaining_raw; rea_runouts = remaining_rea
        enum_desc = f"river only ({remaining_raw} RAW / {remaining_rea} REALIZED)"
    else:
        raw_runouts = remaining_raw*(remaining_raw-1)//2
        rea_runouts = remaining_rea*(remaining_rea-1)//2
        enum_desc   = f"C({remaining_raw},2)={raw_runouts:,} RAW  /  C({remaining_rea},2)={rea_runouts:,} REALIZED"
    field("Street",                str(street), Fore.MAGENTA)
    field("Remaining (RAW)",       str(remaining_raw))
    field("Remaining (REALIZED)",  str(remaining_rea))
    field("RAW runouts per pair",  f"{raw_runouts:,}")
    field("REALIZED runouts/pair", f"{rea_runouts:,}" if rea_runouts > 0 else "0 !! exhausted")
    field("Enumeration",           enum_desc, Fore.CYAN)
    if rea_runouts == 0: warn("REALIZED deck exhausted — realized equity will return 50/50")
    section("DUPLICATE CARD CHECK", Fore.CYAN)
    seen_set, dupe = set(), False
    for c in all_known_cards:
        cs = str(c)
        if cs in seen_set: err(f"DUPLICATE: {cs}"); dupe = True
        seen_set.add(cs)
    if dupe: sys.exit(1)
    ok(f"All {len(all_known_cards)} cards unique")
    hdr(f"HEAD-UP PAIR EQUITY ANALYSIS  [{street}]", Fore.MAGENTA)
    pair_count = NUM_PLAYERS*(NUM_PLAYERS-1)//2
    print(f"  {Fore.WHITE}Evaluating {Fore.YELLOW}{Style.BRIGHT}{pair_count} pairs{Style.RESET_ALL}  |  street: {Fore.MAGENTA}{Style.BRIGHT}{street}{Style.RESET_ALL}\n")
    candidates, pair_num = [], 0
    for i in range(NUM_PLAYERS):
        for j in range(i+1, NUM_PLAYERS):
            pair_num += 1; p1, p2 = players[i], players[j]
            other_holes = [c for k,pl in enumerate(players) if k not in (i,j) for c in pl["hole4"]]
            label1 = f"{p1['tag']} ({p1['name']})"; label2 = f"{p2['tag']} ({p2['name']})"
            print(f"{Fore.CYAN}{Style.BRIGHT}  +─ Pair {pair_num:>2}/{pair_count}  P{i+1}: {Fore.YELLOW}{label1}{Fore.CYAN}  vs  P{j+1}: {Fore.YELLOW}{label2}{Fore.CYAN}  {'─'*30}+{Style.RESET_ALL}")
            print(f"  |  {Fore.WHITE}Dead for REALIZED: {Fore.MAGENTA}{len(other_holes)} cards ({', '.join(str(c) for c in other_holes)}){Style.RESET_ALL}")
            t_pair = time.perf_counter()
            result = calc_pair_equities(p1, p2, board, other_holes)
            pair_ms = (time.perf_counter()-t_pair)*1000
            raw = result["raw"]; rea = result["realized"]
            print(f"\n  |  {Fore.YELLOW}RAW equity{Style.RESET_ALL}  ({raw['n']:,} runouts  {raw['ms']:.0f}ms)")
            if raw["n"] > 0:
                print(f"  |    {equity_bar(raw['pctA'], raw['pctB'])}")
                print(f"  |    {Fore.GREEN}Wins A: {raw['wA']:,}{Style.RESET_ALL}  /  {Fore.RED}Wins B: {raw['wB']:,}{Style.RESET_ALL}  /  {Fore.CYAN}Ties: {raw['ties']:,}{Style.RESET_ALL}")
            else: warn("0 runouts — deck exhausted")
            print(f"\n  |  {Fore.GREEN}REALIZED equity{Style.RESET_ALL}  ({rea['n']:,} runouts  {rea['ms']:.0f}ms)")
            if rea["n"] > 0:
                print(f"  |    {equity_bar(rea['pctA'], rea['pctB'])}")
                print(f"  |    {Fore.GREEN}Wins A: {rea['wA']:,}{Style.RESET_ALL}  /  {Fore.RED}Wins B: {rea['wB']:,}{Style.RESET_ALL}  /  {Fore.CYAN}Ties: {rea['ties']:,}{Style.RESET_ALL}")
            else: warn("0 runouts — deck exhausted")
            shift_A = rea["pctA"] - raw["pctA"]; sc = Fore.GREEN if shift_A > 0 else Fore.RED
            print(f"\n  |  Equity shift:  P{i+1}: {sc}{shift_A:+.2f}%{Style.RESET_ALL}  |  P{j+1}: {Fore.RED if shift_A>0 else Fore.GREEN}{-shift_A:+.2f}%{Style.RESET_ALL}    compute: {Fore.CYAN}{pair_ms:.0f}ms{Style.RESET_ALL}")
            if abs(raw["pctA"]-raw["pctB"]) < EPS:
                under, fav = p1, p2; under_raw, under_real = raw["pctA"], rea["pctA"]
                warn("Exact equity tie — underdog assigned by convention (P1)")
            elif raw["pctA"] < raw["pctB"]: under, fav = p1, p2; under_raw, under_real = raw["pctA"], rea["pctA"]
            else: under, fav = p2, p1; under_raw, under_real = raw["pctB"], rea["pctB"]
            disparity = under_real - under_raw
            d_col  = Fore.GREEN if disparity > 0 else (Fore.RED if disparity < 0 else Fore.WHITE)
            d_sign = "+" if disparity > 0 else ""
            under_label = f"{under['tag']} ({under['name']})"
            fav_label   = f"{fav['tag']} ({fav['name']})"
            print(f"\n  |  {Fore.MAGENTA}Underdog:{Style.RESET_ALL} {Fore.RED}{under_label}{Style.RESET_ALL}  raw {Fore.YELLOW}{under_raw:.4f}%{Style.RESET_ALL}  realized {Fore.GREEN}{under_real:.4f}%{Style.RESET_ALL}  disparity {d_col}{Style.BRIGHT}{d_sign}{disparity:.4f}%{Style.RESET_ALL}")
            print(f"  |  {Fore.MAGENTA}Favourite:{Style.RESET_ALL} {Fore.GREEN}{fav_label}{Style.RESET_ALL}  raw {Fore.YELLOW}{100-under_raw:.4f}%{Style.RESET_ALL}  realized {Fore.GREEN}{100-under_real:.4f}%{Style.RESET_ALL}")
            print()
            candidates.append({"pair_num":pair_num,"player_i":i+1,"player_j":j+1,"underdog":under_label,"favourite":fav_label,"under_raw":under_raw,"under_real":under_real,"disparity":disparity,"raw_n":raw["n"],"rea_n":rea["n"]})
    hdr("ALL MATCHUPS  —  ranked by disparity ASC (most negative first)", Fore.CYAN)
    ranked = rank_matchups(candidates); CW = 24
    print(Fore.WHITE+Style.BRIGHT+f"  {'Rank':>4}  {'#':>3}  {'Underdog':<{CW}}  {'Favourite':<{CW}}  {'UndRaw':>8}  {'UndReal':>8}  {'Disparity':>10}  {'FavRaw':>8}  {'FavReal':>8}"+Style.RESET_ALL)
    print("  "+"─"*110)
    for rank, c in enumerate(ranked, 1):
        d = c["disparity"]; dc = Fore.GREEN if d > 0 else (Fore.RED if d < 0 else Fore.WHITE); dsn = "+" if d > 0 else ""
        star = f" {Fore.YELLOW}{Style.BRIGHT}★{Style.RESET_ALL}" if rank == 1 else "  "
        print(f"  {rank:>4}  {c['pair_num']:>3}  {Fore.RED}{c['underdog']:<{CW}}{Style.RESET_ALL}  {Fore.GREEN}{c['favourite']:<{CW}}{Style.RESET_ALL}  {Fore.YELLOW}{c['under_raw']:>7.4f}%{Style.RESET_ALL}  {Fore.GREEN}{c['under_real']:>7.4f}%{Style.RESET_ALL}  {dc}{Style.BRIGHT}{dsn}{d:>8.4f}%{Style.RESET_ALL}  {Fore.YELLOW}{100-c['under_raw']:>7.4f}%{Style.RESET_ALL}  {Fore.GREEN}{100-c['under_real']:>7.4f}%{Style.RESET_ALL}"+star)
    hdr("FINAL RESULT  —  Most +EV (Most Negative Disparity)", Fore.MAGENTA)
    if not ranked: print(f"\n  {Fore.RED}{Style.BRIGHT}NO CANDIDATES{Style.RESET_ALL}\n")
    else:
        top = ranked[0]; d = top["disparity"]; dc = Fore.GREEN if d > 0 else (Fore.RED if d < 0 else Fore.WHITE); dsn = "+" if d > 0 else ""
        print(f"\n  {Fore.GREEN}{Style.BRIGHT}BEST MATCHUP  (Pair #{top['pair_num']}){Style.RESET_ALL}\n")
        field("Underdog",top["underdog"],Fore.RED); field("Favourite",top["favourite"],Fore.GREEN); print()
        field("Underdog  Raw equity",     f"{top['under_raw']:.4f}%", Fore.YELLOW)
        field("Underdog  Realized equity",f"{top['under_real']:.4f}%",Fore.GREEN)
        field("Favourite Raw equity",     f"{100-top['under_raw']:.4f}%", Fore.YELLOW)
        field("Favourite Realized equity",f"{100-top['under_real']:.4f}%",Fore.GREEN)
        field("Disparity (real - raw)",   f"{dsn}{d:.4f}%", dc); print()
        field("Exact runouts (raw)",      f"{top['raw_n']:,}")
        field("Exact runouts (realized)", f"{top['rea_n']:,}"); print()
        print(f"  {Fore.WHITE}Underdog RAW     :  {equity_bar(top['under_raw'], 100-top['under_raw'])}")
        print(f"  {Fore.WHITE}Underdog REALIZED:  {equity_bar(top['under_real'],100-top['under_real'])}"); print()
    total_s = time.perf_counter() - run_start
    section("PERFORMANCE", Fore.CYAN)
    field("Street",str(street)); field("Total runtime",fmt_time(total_s))
    field("Pairs evaluated",str(pair_num)); field("CPU cores used",str(cpu_count()))
    ok("Analysis complete"); print()
