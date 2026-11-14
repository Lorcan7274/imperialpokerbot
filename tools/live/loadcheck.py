import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("bot", sys.argv[1])
m = importlib.util.module_from_spec(spec)
t = time.perf_counter(); spec.loader.exec_module(m); load = time.perf_counter() - t
a = m.Agent()
a.on_table_start({"seat": 3, "num_players": 8, "format": "fixed_hands", "hands": 1000, "starting_stack": 2000,
                  "stacks_reset_each_hand": True, "small_blind": 10, "big_blind": 20, "betting": "no_limit", "raise_cap": None})
hist = [{"seat": 6, "street": "preflop", "action": "small_blind", "amount": 10},
        {"seat": 7, "street": "preflop", "action": "big_blind", "amount": 20},
        {"seat": 0, "street": "preflop", "action": "fold", "amount": 0},
        {"seat": 1, "street": "preflop", "action": "raise", "amount": 60},
        {"seat": 2, "street": "preflop", "action": "call", "amount": 60}]
base = {"seat": 3, "button": 5, "small_blind": 10, "big_blind": 20, "blind_level": 0, "hand_number": 1,
        "betting": "no_limit", "raise_cap": None}
pre = dict(base, hole_cards=["As", "Kd"], board=[], street="preflop",
           stacks=[2000, 1940, 1940, 2000, 2000, 2000, 1990, 1980], bets=[0, 60, 60, 0, 0, 0, 10, 20],
           folded=[True, False, False, False, False, False, False, False], pot=150, to_call=60,
           min_raise_to=100, max_raise_to=2000, legal_actions=["fold", "call", "raise"],
           raises_this_street=1, history=hist)
print("preflop AKo vs open+call ->", a.act(json.loads(json.dumps(pre))))
pre2 = dict(pre, hole_cards=["7c", "2d"]); pre2["hand_number"] = 2
print("preflop 72o ->", a.act(json.loads(json.dumps(pre2))))
h2 = hist + [{"seat": 3, "street": "preflop", "action": "call", "amount": 60}] + [
    {"seat": s, "street": "preflop", "action": "fold", "amount": 0} for s in (4, 5, 6, 7)] + [
    {"seat": 1, "street": "flop", "action": "raise", "amount": 120}, {"seat": 2, "street": "flop", "action": "fold", "amount": 0}]
flop = dict(base, hole_cards=["As", "Kd"], board=["Ah", "7c", "2s"], street="flop", hand_number=3,
            stacks=[2000, 1820, 1940, 1940, 2000, 2000, 1990, 1980], bets=[0, 120, 0, 0, 0, 0, 0, 0],
            folded=[True, False, True, False, True, True, True, True], pot=330, to_call=120,
            min_raise_to=240, max_raise_to=1940, legal_actions=["fold", "call", "raise"],
            raises_this_street=1, history=h2)
t = time.perf_counter(); out = a.act(json.loads(json.dumps(flop))); dt = time.perf_counter() - t
print("flop top pair vs bet ->", out, "%.2f ms" % (dt * 1000))
noraise = dict(flop, min_raise_to=None, max_raise_to=None, legal_actions=["fold", "call"], hand_number=4)
print("no-raise spot ->", a.act(json.loads(json.dumps(noraise))))
a.on_hand_end({"hand_number": 3, "board": ["Ah", "7c", "2s"], "shown": {}, "winners": [{"seat": 3, "amount": 330, "hand": None}],
               "stacks": [2000] * 8, "history": h2})
print("load %.0f ms, strict errors:" % (load * 1000), "none" if a.bot.strict is False else "strict")
a.bot.strict = True
for st in (pre, flop, noraise):
    st = dict(st, hand_number=st["hand_number"] + 10)
    a.act(json.loads(json.dumps(st)))
print("strict replay ok; file bytes:", len(open(sys.argv[1], "rb").read()))
