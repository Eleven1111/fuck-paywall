"""命令行入口 `ca`。知识库目录用 --vault 指定，或设环境变量 CA_VAULT（默认 ./creator-vault）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import gates, stages
from .llm import LLM, LLMError
from .vault import Vault, VaultError


def _vault(args) -> Vault:
    v = Vault(Path(args.vault or os.environ.get("CA_VAULT", "creator-vault")))
    v.require()
    stale = v.stale_platform_rules()
    if stale:
        print(f"⚠️ 平台规则超过 90 天未核对：{'、'.join(stale)}", file=sys.stderr)
    return v


def _llm(v: Vault) -> LLM:
    return LLM(v.llm_config(), log_dir=v.root / "runs/logs")


def cmd_init(args):
    v = Vault.init(Path(args.path))
    print(f"已创建知识库 {v.root}。下一步（P0 建库）：")
    print("  1. 改 voice/profile.yaml、never.md、stances.md、stories.md")
    print("  2. 往 voice/exemplars/ 放 5–15 段你自己的范文")
    print("  3. `ca import-rss <你的 Substack RSS>` 导入往期文章")
    print("  4. 往 evals/anchors/ 放好稿、差稿各 2 篇以上（good_*.md / bad_*.md）")
    print("  5. `ca idea add \"...\" --edge \"...\"` 录入选题")


def cmd_import_rss(args):
    v = _vault(args)
    from .importer import import_rss

    names = import_rss(v, args.url)
    print(f"导入 {len(names)} 篇到 archive/")


def cmd_idea(args):
    v = _vault(args)
    if args.action == "add":
        if not args.text:
            raise VaultError("用法：ca idea add \"选题\" [--edge \"...\"]")
        idea = v.add_idea(args.text, origin=args.origin, edge=args.edge)
        print(f"{idea['id']}  {idea['raw']}")
    else:
        for i in v.ideas():
            edge = i.get("edge") or "（未写 edge）"
            print(f"{i['id']}  [{i['status']}]  {i['raw']}  —— {edge}")


def cmd_new(args):
    v = _vault(args)
    idea = v.idea(args.idea) if args.idea.startswith("idea_") else v.add_idea(args.idea)
    hub_id = v.new_hub(idea)
    print(hub_id)
    if args.angles:
        stages.s1_angles(v, _llm(v), hub_id, n=args.n)
        print(f"选题角度已写入 hubs/{hub_id}/angles.md")


def cmd_angles(args):
    v = _vault(args)
    stages.s1_angles(v, _llm(v), args.hub, n=args.n)
    print(f"hubs/{args.hub}/angles.md")


def cmd_research(args):
    v = _vault(args)
    r = stages.s2_research(v, _llm(v), args.hub)
    weak = sum(1 for f in r["findings"] if f["weak"])
    print(f"{len(r['findings'])} 条发现（{weak} 条弱来源）→ hubs/{args.hub}/research.md")


def cmd_outline(args):
    v = _vault(args)
    o = stages.s3_outline(v, _llm(v), args.hub)
    print(f"{len(o['sections'])} 节，{len(o['problems'])} 个程序检查问题 → hubs/{args.hub}/outline.md")


def cmd_draft(args):
    v = _vault(args)
    name = stages.s4_draft(v, _llm(v), args.hub, mode=args.mode)
    print(f"hubs/{args.hub}/{name}")


def cmd_review(args):
    v = _vault(args)
    r = stages.s5_review(v, _llm(v), args.hub)
    print(f"{'通过' if r['pass'] else '未通过'}，评审分 {r['judge'].get('score', 0):.2f} → hubs/{args.hub}/review.md")


def cmd_adapt(args):
    v = _vault(args)
    vs = stages.s6_adapt(v, _llm(v), args.hub, n_x=args.x, n_notes=args.notes)
    for x in vs:
        mark = "✓" if x["gate_results"]["passed"] else f"✗ {x['gate_results']['failed']}"
        print(f"{x['variant_id']}  {mark}")
    print(f"Substack 发布包 → hubs/{args.hub}/substack_package.md")
    print(f"审批：`ca approve {args.hub} H5 --variants all`")


def cmd_approve(args):
    v = _vault(args)
    fields = {
        "angle": args.angle, "excitement": args.excitement, "edge": args.edge,
        "confirm": args.confirm, "notes": args.notes,
        "quotes_checked": args.quotes_checked, "numbers_checked": args.numbers_checked,
        "ending_ok": args.ending_ok, "override_reason": args.override_reason,
        "canonical_url": args.canonical_url,
        "variants": args.variants.split(",") if args.variants else None, "force": args.force,
    }
    rec = gates.approve(v, args.hub, args.gate, **fields)
    print(f"{args.gate} 已记录：{json.dumps(rec, ensure_ascii=False)}")


def cmd_published(args):
    v = _vault(args)
    stages.mark_published(v, args.variant, args.url, cost_usd=args.cost)
    print(f"{args.variant} 已记录为 published")


def cmd_log_edit(args):
    v = _vault(args)
    meta = v.meta(args.hub)
    meta["edit_minutes"].append({"stage": args.stage, "minutes": args.minutes})
    v.save_meta(args.hub, meta)
    total = sum(e["minutes"] for e in meta["edit_minutes"])
    print(f"{args.hub} 人工编辑累计 {total} 分钟")


def cmd_status(args):
    v = _vault(args)
    hubs = [v.meta(args.hub)] if args.hub else v.hubs()
    for m in hubs:
        g = ",".join(sorted(m["gates"])) or "-"
        mins = sum(e["minutes"] for e in m.get("edit_minutes", []))
        print(f"{m['id']}  状态 {m['status']}  闸口 {g}  模式 {m.get('draft_mode')}  编辑 {mins} 分钟")
        if args.hub:
            for x in v.variants_of(m["id"]):
                print(f"  {x['variant_id']}  {x['status']}  {x['schedule']['planned_at']}")


def cmd_eval(args):
    v = _vault(args)
    from .evalset import run_eval

    s = run_eval(v, _llm(v))
    print(json.dumps({k: s[k] for k in s if k != "results"}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ca", description="多平台创作 Agent（P1 MVP）")
    p.add_argument("--vault", help="知识库目录（默认 $CA_VAULT 或 ./creator-vault）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="P0：创建知识库骨架")
    s.add_argument("path")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("import-rss", help="P0：用 RSS 导入往期文章")
    s.add_argument("url")
    s.set_defaults(func=cmd_import_rss)

    s = sub.add_parser("idea", help="选题池")
    s.add_argument("action", choices=["add", "list"])
    s.add_argument("text", nargs="?")
    s.add_argument("--origin", default="memo",
                   choices=["memo", "reader_reply", "x_outlier", "own_post"])
    s.add_argument("--edge")
    s.set_defaults(func=cmd_idea)

    s = sub.add_parser("new", help="从选题（idea_id 或一句话）新建母稿")
    s.add_argument("idea")
    s.add_argument("--angles", action="store_true", help="创建后立刻跑 S1")
    s.add_argument("-n", type=int, default=4)
    s.set_defaults(func=cmd_new)

    for name, fn, helptext in [("angles", cmd_angles, "S1 选题定角"),
                               ("research", cmd_research, "S2 研究取证（需 H1）"),
                               ("outline", cmd_outline, "S3 论点与提纲（需 H2）"),
                               ("review", cmd_review, "S5 编辑评审")]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("hub")
        if name == "angles":
            s.add_argument("-n", type=int, default=4)
        s.set_defaults(func=fn)

    s = sub.add_parser("draft", help="S4 起草（需 H3）；默认模式见 profile.yaml")
    s.add_argument("hub")
    s.add_argument("--mode", choices=["A", "B", "I"])
    s.set_defaults(func=cmd_draft)

    s = sub.add_parser("adapt", help="S6 平台适配：x_post + substack_note（需 H4）")
    s.add_argument("hub")
    s.add_argument("--x", type=int, default=5)
    s.add_argument("--notes", type=int, default=5)
    s.set_defaults(func=cmd_adapt)

    s = sub.add_parser("approve", help="记录人工闸口 H1–H5")
    s.add_argument("hub")
    s.add_argument("gate", choices=list(gates.GATE_DESC))
    s.add_argument("--angle", type=int)
    s.add_argument("--excitement", type=int)
    s.add_argument("--edge")
    s.add_argument("--confirm", action="store_true")
    s.add_argument("--notes")
    s.add_argument("--quotes-checked", type=int)
    s.add_argument("--numbers-checked", type=int)
    s.add_argument("--ending-ok", action="store_true")
    s.add_argument("--override-reason")
    s.add_argument("--canonical-url")
    s.add_argument("--variants", help="逗号分隔的 variant_id，或 all")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser("published", help="人工发布后记录链接")
    s.add_argument("variant")
    s.add_argument("url")
    s.add_argument("--cost", type=float)
    s.set_defaults(func=cmd_published)

    s = sub.add_parser("log-edit", help="记录人工编辑时长（P1 完成标准之一）")
    s.add_argument("hub")
    s.add_argument("minutes", type=int)
    s.add_argument("--stage", default="draft")
    s.set_defaults(func=cmd_log_edit)

    s = sub.add_parser("status", help="查看母稿与变体状态")
    s.add_argument("hub", nargs="?")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("eval", help="在离线测试集上检验评审能否区分好稿和差稿")
    s.set_defaults(func=cmd_eval)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (VaultError, LLMError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
