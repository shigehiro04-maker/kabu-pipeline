import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text(encoding="utf-8")
if "--layout" in s:
    print("already patched"); sys.exit(0)
a = '''    ap.add_argument("--publish",'''
b = '''    ap.add_argument("--layout", choices=["dashboard", "classic"], default="dashboard",
                    help="--html のページの形。dashboard=1画面で見渡すダッシュボード（既定）、"
                         "classic=従来の縦長ページ")
    ap.add_argument("--publish",'''
assert s.count(a) == 1; s = s.replace(a, b)
a = '''            import html_report
            page = html_report.write_html(df, sens, bt, grid, score, args,
                                          outdir, SCORE_ITEMS)'''
b = '''            if args.layout == "dashboard":
                import html_dashboard
                page = html_dashboard.write_dashboard(df, sens, bt, grid, score, args,
                                                      outdir, SCORE_ITEMS)
            else:
                import html_report
                page = html_report.write_html(df, sens, bt, grid, score, args,
                                              outdir, SCORE_ITEMS)'''
assert s.count(a) == 1; s = s.replace(a, b)
p.write_text(s, encoding="utf-8"); print("patched")
