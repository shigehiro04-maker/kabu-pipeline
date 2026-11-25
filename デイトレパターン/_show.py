import sys, json
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import dtp_data as D
R = json.load(open(D.cfg(sys.argv[1])["out"] + "/research/results.json"))
what = sys.argv[2:]
if "cost" in what:
    print(json.dumps(R["cost"], ensure_ascii=False))
if "pat" in what:
    for p in R["patterns"]:
        print(p["key"], p["n"], "gross", p["gross"], "net", p["net"], "t", p["t"], "liq", p["liquid"] and (p["liquid"]["n"], p["liquid"]["gross"], p["liquid"]["net"]), "rev60", p["rev_r60"], "revc", p["rev_rc"])
if "exit" in what:
    for p in R["patterns"]:
        print(p["key"], {k: (v["net"], v["win"], v["payoff"], v["dd"]) for k, v in p["exits"].items()})
if "rules" in what:
    for k in ("rules", "rules_liquid"):
        r = R.get(k)
        if r:
            print(k, {x: r[x] for x in ("split", "train_days", "test_days", "tested", "selected", "held_pos", "held_t2")})
            for x in r["top"][:12]:
                print("  ", x)
if "strat" in what:
    for s in R["strat"]:
        print(s["kind"], {k: s[k] for k in ("n", "gross", "net", "t", "win")}, "liq", s["liquid"], "tr", s["train"] and s["train"]["net"], "te", s["test"] and s["test"]["net"])
        for x in s["sub"]:
            print("    ", x)
if "daily" in what:
    d = R["daily"]
    print(d["period"], d["n"], d["base"])
    print(d["base_year"])
    for p in d["patterns"]:
        print(p["key"], p["n"], "gross", p["gross"], "net", p["net"], "t", p["t"], "tgt", p["tgt"], "stp", p["stp"], "tr", p["train"] and (p["train"]["net"], p["train"]["t"]), "te", p["test"] and (p["test"]["net"], p["test"]["t"]), "posY", p["pos_years"], "wt", p["with_trend"] and p["with_trend"]["net"], "at", p["against_trend"] and p["against_trend"]["net"])
if "ml" in what:
    for k in ("ml", "ml_daily"):
        if k in R:
            x = R[k]
            print(k, x["split"], x["n_test"], x["iters"], x["spearman"], x["top"], x["pred_pos"], x["all_test"])
            print("   ", [(d["d"], d["pred"], d["net"]) for d in x["deciles"]])
            print("   ", x["importance"])
