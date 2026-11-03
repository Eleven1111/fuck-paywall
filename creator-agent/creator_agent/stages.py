"""流水线各阶段。每个阶段：检查前置闸口 → 调用模型 → 把结果写进 hubs/{id}/，交给人审。"""

from __future__ import annotations

import datetime as dt
import json
import re

import yaml

from . import prompts as P
from .gates import _sha, check, score_angle
from .lint import URL_RE, lint_draft, x_weighted_length
from .llm import LLM
from .utm import with_utm
from .vault import Vault, VaultError, now_iso


def _profile_bits(vault: Vault) -> dict:
    p = vault.profile()
    return {
        "author": p.get("author", "作者"),
        "identity": p.get("identity", ""),
        "lens": p.get("lens", ""),
        "persona": p.get("persona", ""),
    }


# =============================================================== S1 选题定角
def s1_angles(vault: Vault, llm: LLM, hub_id: str, n: int = 4) -> dict:
    meta = vault.meta(hub_id)
    hits = vault.archive_hits(meta["idea"])
    out = llm.json(
        stage="angles",
        system=P.ANGLES_SYSTEM.format(**_profile_bits(vault)),
        user=P.ANGLES_USER.format(idea=meta["idea"], n=n,
                                  archive_hits=json.dumps(hits, ensure_ascii=False) or "无"),
        schema=P.ANGLES_SCHEMA,
    )
    for a in out["angles"]:
        a["prelim_score"] = score_angle(a, excitement=None)  # 兴奋度待作者在 H1 填写
    out["archive_hits"] = hits
    vault.write_hub_file(hub_id, "angles.json", out)

    lines = [f"# {hub_id} · 选题角度（S1）", "", f"选题：{meta['idea']}", ""]
    if hits:
        lines += ["往期相似文章：" + "、".join(f"{h['title']}（{h['score']}）" for h in hits), ""]
    for i, a in enumerate(out["angles"], 1):
        lines += [
            f"## 角度 {i}：{a['one_big_idea']}",
            f"- edge：{a['edge']}",
            f"- 论点：{a['thesis']}",
            f"- 类型：{a['angle_type']}｜为什么是现在：{a['why_now']}",
            f"- 读者收益：{a['reader_payoff']}",
            f"- 需要你提供：{'；'.join(a['human_evidence_needed'])}",
            f"- 风险：{a['risk']}",
            f"- 预排序分（不含你的兴奋度）：{a['prelim_score']}",
            "",
        ]
    lines += ["---", "H1：选一个角度，亲手填兴奋度并写一句你自己的 edge：",
              f"`ca approve {hub_id} H1 --angle N --excitement 1-5 --edge \"...\"`"]
    vault.write_hub_file(hub_id, "angles.md", "\n".join(lines))
    meta["status"] = "angles"
    vault.save_meta(hub_id, meta)
    return out


# =============================================================== S2 研究取证
def s2_research(vault: Vault, llm: LLM, hub_id: str) -> dict:
    meta = vault.meta(hub_id)
    check(meta, "research")
    angle = meta["chosen_angle"]
    subq = llm.json(stage="research", system=P.SUBQ_SYSTEM,
                    user=f"论点：{angle['thesis']}\n大想法：{angle['one_big_idea']}",
                    schema=P.SUBQ_SCHEMA)["questions"]
    notes = llm.text(
        stage="research", system=P.RESEARCH_SYSTEM, web_search=True,
        user=P.RESEARCH_USER.format(thesis=angle["thesis"], one_big_idea=angle["one_big_idea"],
                                    edge=meta.get("edge", ""),
                                    questions="\n".join(f"- {q}" for q in subq)),
    )
    vault.write_hub_file(hub_id, "research_notes.md", notes)
    bound = llm.json(stage="research", system=P.BIND_SYSTEM, user=notes, schema=P.RESEARCH_SCHEMA)
    for i, f in enumerate(bound["findings"], 1):
        f["id"] = f"f{i:02d}"
        f["weak"] = f["read_level"] == "snippet" or f["source_type"] in ("aggregator", "ai_distilled")
    bound["sub_questions"] = subq
    vault.write_hub_file(hub_id, "research.json", bound)
    _write_research_md(vault, hub_id, bound)
    meta["status"] = "research"
    vault.save_meta(hub_id, meta)
    return bound


def _write_research_md(vault: Vault, hub_id: str, r: dict) -> None:
    lines = [f"# {hub_id} · 研究简报（S2）", "", "## 发现"]
    for f in r["findings"]:
        flag = " ⚠️弱来源，不能单独支撑数字或引语" if f["weak"] else ""
        lines += [f"- **[{f['id']}]** {f['claim']}{flag}",
                  f"  - 原文：“{f['quote_verbatim']}”（{f['speaker']}，{f['attribution']}）",
                  f"  - {f['url']}｜{f['date']}｜{f['source_type']}/{f['read_level']}｜{f['confidence']}"]
    lines += ["", "## 反方证据"] + [f"- {c['claim']}（{c['url']}）" for c in r["counter_evidence"]]
    lines += ["", "## 需要你去补的采访或数据"] + [f"- {t}" for t in r["human_todo"]]
    lines += ["", "## 未找到证据"] + [f"- {t}" for t in r["not_found"]]
    lines += ["", "---", "## H2 检查清单",
              "- [ ] 每个数字至少有 1 个一手来源；高风险事实有 3 个独立来源（HCR）",
              "- [ ] 引语能在原文逐字找到，且归属正确（本人原话 / 转述 / 主持人复述）",
              "- [ ] 至少列出 1 条反方证据",
              "- [ ] snippet / 聚合站 / AI 蒸馏的来源没有单独支撑结论",
              "", f"确认后：`ca approve {hub_id} H2 --confirm`"]
    vault.write_hub_file(hub_id, "research.md", "\n".join(lines))


# =============================================================== S3 论点与提纲
def s3_outline(vault: Vault, llm: LLM, hub_id: str) -> dict:
    meta = vault.meta(hub_id)
    check(meta, "outline")
    research = vault.read_hub_file(hub_id, "research.json", as_json=True)
    findings = [{k: f[k] for k in ("id", "claim", "quote_verbatim", "speaker", "weak")}
                for f in research["findings"]]
    out = llm.json(
        stage="outline",
        system=P.OUTLINE_SYSTEM.format(**_profile_bits(vault)),
        user=P.OUTLINE_USER.format(angle=json.dumps(meta["chosen_angle"], ensure_ascii=False),
                                   edge=meta.get("edge", ""),
                                   findings=json.dumps(findings, ensure_ascii=False),
                                   stories=vault.text("voice/stories.md")),
        schema=P.OUTLINE_SCHEMA,
    )
    valid = {f["id"] for f in research["findings"]}
    problems = []
    for i, s in enumerate(out["sections"], 1):
        bad = [x for x in s["source_ids"] if x not in valid]
        if bad:
            problems.append(f"第 {i} 节引用了不存在的来源 {bad}")
        if not s["source_ids"] and not s["is_opinion"] and not s["story_ids"]:
            problems.append(f"第 {i} 节既无来源也未标为观点段")
        if not s["serves_big_idea"]:
            problems.append(f"第 {i} 节不服务于大想法，考虑删去或移进尾注")
    out["problems"] = problems
    vault.write_hub_file(hub_id, "outline.json", out)

    t = out["top_of_page"]
    lines = [f"# {hub_id} · 论点与提纲（S3）", "",
             "## 页顶简报", f"- 语境：{t['context']}",
             f"- 问题：{'；'.join(t['questions'])}", f"- 一句话答案：**{t['answer']}**", "",
             f"论点：{out['thesis']}", f"大想法：{out['one_big_idea']}",
             f"核心画面：{out['core_image']}", "",
             "标题候选：" + " / ".join(out["title_options"]), "", "## 提纲"]
    for i, s in enumerate(out["sections"], 1):
        tag = "观点段" if s["is_opinion"] else ",".join(s["source_ids"] + s["story_ids"]) or "无来源"
        lines.append(f"{i}. **{s['heading']}** —— {s['one_sentence']}（{tag}）")
    if out["off_topic_branches"]:
        lines += ["", "## 建议剪掉的分支"] + [f"- {b}" for b in out["off_topic_branches"]]
    if problems:
        lines += ["", "## ⚠️ 程序检查"] + [f"- {p}" for p in problems]
    lines += ["", f"下次从这里开始：{out['next_start_hint']}", "", "---",
              f"批准：`ca approve {hub_id} H3`"]
    vault.write_hub_file(hub_id, "outline.md", "\n".join(lines))
    meta["status"] = "outline"
    vault.save_meta(hub_id, meta)
    return out


# =============================================================== S4 起草
def s4_draft(vault: Vault, llm: LLM, hub_id: str, mode: str | None = None) -> str:
    meta = vault.meta(hub_id)
    check(meta, "draft")
    mode = (mode or meta.get("draft_mode") or "A").upper()
    meta["draft_mode"] = mode
    outline = vault.read_hub_file(hub_id, "outline.json", as_json=True)
    research = vault.read_hub_file(hub_id, "research.json", as_json=True)

    if mode in ("A", "I"):
        # 模式 A：Agent 不写正文，只提供素材卡片和“下次从这里开始”；模式 I 在 MVP 里同样给提问清单。
        lines = [f"# {hub_id} · 素材卡片（模式 {mode}）", "",
                 f"一句话答案：**{outline['top_of_page']['answer']}**", ""]
        by_id = {f["id"]: f for f in research["findings"]}
        for i, s in enumerate(outline["sections"], 1):
            lines.append(f"## {i}. {s['heading']}")
            lines.append(f"要说的一句话：{s['one_sentence']}")
            for sid in s["source_ids"]:
                f = by_id.get(sid)
                if f:
                    lines.append(f"- [{sid}] “{f['quote_verbatim']}” —— {f['speaker']}｜{f['url']}")
            for st in s["story_ids"]:
                lines.append(f"- 经历 [{st}]（见 voice/stories.md）")
            if mode == "I":
                lines.append(f"- 访谈提问：关于“{s['one_sentence']}”，你亲眼见过的一个例子是什么？")
            lines.append("")
        lines += [f"下次从这里开始：{outline['next_start_hint']}", "",
                  "---", f"在 `hubs/{hub_id}/draft.md` 写正文；写完运行 `ca review {hub_id}`。",
                  "事实后标 [finding_id]，没补完的地方写 [TK: ...]，评审会拦截。"]
        vault.write_hub_file(hub_id, "cards.md", "\n".join(lines))
        draft_path = vault.hub_dir(hub_id) / "draft.md"
        if not draft_path.exists():
            draft_path.write_text(f"# {outline['title_options'][0] if outline['title_options'] else ''}\n\n"
                                  "[TK: 作者在此写正文]\n", encoding="utf-8")
        result = "cards.md"
    else:
        profile = vault.profile()
        text = llm.text(
            stage="draft",
            system=P.DRAFT_B_SYSTEM.format(
                author=profile.get("author", "作者"),
                profile=yaml.safe_dump(profile, allow_unicode=True),
                never="、".join(vault.list_items("voice/never.md")),
                exemplars=vault.exemplars() or "（暂无范文）",
                answer=outline["top_of_page"]["answer"]),
            user=P.DRAFT_B_USER.format(
                outline=json.dumps(outline, ensure_ascii=False),
                findings=json.dumps(research["findings"], ensure_ascii=False),
                stances=vault.text("voice/stances.md"),
                stories=vault.text("voice/stories.md")),
        )
        vault.write_hub_file(hub_id, "draft_agent.md", text)
        vault.write_hub_file(hub_id, "draft.md", text)
        result = "draft.md"
    meta["status"] = "drafting"
    vault.save_meta(hub_id, meta)
    return result


# =============================================================== S5 编辑评审
def s5_review(vault: Vault, llm: LLM, hub_id: str) -> dict:
    meta = vault.meta(hub_id)
    check(meta, "review")
    draft = vault.read_hub_file(hub_id, "draft.md")
    lint = lint_draft(draft, never=vault.list_items("voice/never.md"),
                      deliberate_breaks=vault.list_items("voice/deliberate_breaks.md"))
    report: dict = {"draft_sha": _sha(draft), "at": now_iso(), "lint": lint.to_dict()}

    # TK 未清不浪费模型调用：直接退回。
    if any(b["check"] == "tk" for b in lint.blocking):
        report.update({"pass": False, "skipped_llm": "draft 仍有 TK", "judge": {"score": 0.0},
                       "checkable_claims": []})
        _write_review(vault, hub_id, report)
        return report

    numbered = "\n\n".join(f"[段{i}] {p}" for i, p in
                           enumerate([p for p in re.split(r"\n\s*\n", draft) if p.strip()], 1))
    stranger = llm.json(stage="review", system=P.STRANGER_SYSTEM, user=draft,
                        schema=P.STRANGER_SCHEMA)
    critique = llm.json(stage="review", system=P.CRITIQUE_SYSTEM, user=numbered,
                        schema=P.CRITIQUE_SCHEMA)
    anchors = vault.anchors()
    if len(anchors["good"]) < 2 or len(anchors["bad"]) < 2:
        report["anchor_warning"] = "evals/anchors 里好稿、差稿各不足 2 篇，评审分没有校准，参考价值有限"
    judge = llm.json(
        stage="review", system=P.JUDGE_SYSTEM,
        user=P.JUDGE_USER.format(bad="\n\n---\n\n".join(anchors["bad"]) or "（无）",
                                 good="\n\n---\n\n".join(anchors["good"]) or "（无）",
                                 draft=draft),
        schema=P.JUDGE_SCHEMA,
    )

    research = json.loads((vault.hub_dir(hub_id) / "research.json").read_text(encoding="utf-8")) \
        if (vault.hub_dir(hub_id) / "research.json").exists() else {"findings": []}
    valid_ids = {f["id"] for f in research["findings"]}
    cited = set(re.findall(r"\[(f\d{2})\]", draft))
    unknown_ids = sorted(cited - valid_ids)

    blocking = list(lint.blocking)
    if unknown_ids:
        blocking.append({"check": "unknown_source_ids", "ids": unknown_ids})
    unsourced = [c for c in critique["checkable_claims"]
                 if c["kind"] in ("quote", "number") and not c["has_source_marker"]]
    if unsourced:
        blocking.append({"check": "unsourced_claims", "claims": [c["text"] for c in unsourced]})
    h = critique["honesty"]
    if not (h["fair"] and h["accurate"] and h["persuasive_to_fair_observers"]):
        blocking.append({"check": "honesty_3q", "notes": h["notes"]})
    unblocked = [m for m in stranger["misreadings"] if not m["blocked_in_text"]]
    paras = max(len(critique["reader_reactions"]), 1)
    cb = sum(1 for r in critique["reader_reactions"] if r["label"] in ("Confusing", "Boring"))
    dry_all_false = [d["sentence"] for d in critique["dry_tests"]
                     if not (d["visualize"] or d["falsify"] or d["only_you"])]

    score = max(0.0, min(1.0, float(judge["score"])))
    report.update({
        "stranger": stranger,
        "critique": critique,
        "judge": {**judge, "score": score},
        "checkable_claims": critique["checkable_claims"],
        "scores": {
            "judge": score,
            "cribs_cb_ratio": round(cb / paras, 2),
            "dry_core_all_false": len(dry_all_false),
            "unblocked_misreadings": len(unblocked),
            **lint.stats,
        },
        "flags": lint.flags + ([{"check": "cribs", "note": "Confusing/Boring 段超过 15%"}]
                               if cb / paras > 0.15 else [])
                 + ([{"check": "dry", "sentences": dry_all_false}] if dry_all_false else [])
                 + ([{"check": "misreading", "items": unblocked}] if unblocked else []),
        "blocking": blocking,
    })
    report["lint"]["ok"] = report["lint"]["ok"] and not blocking
    report["pass"] = not blocking and score >= vault.review_threshold()
    _write_review(vault, hub_id, report)
    meta["status"] = "reviewed"
    vault.save_meta(hub_id, meta)
    return report


def _write_review(vault: Vault, hub_id: str, r: dict) -> None:
    vault.write_hub_file(hub_id, "review.json", r)
    lines = [f"# {hub_id} · 编辑评审（S5）", "",
             f"结论：{'✅ 通过' if r['pass'] else '❌ 未通过'}｜评审分 {r['judge'].get('score', 0):.2f}", ""]
    if r.get("anchor_warning"):
        lines += [f"> ⚠️ {r['anchor_warning']}", ""]
    if r.get("skipped_llm"):
        lines += [f"> 已跳过模型评审：{r['skipped_llm']}", ""]
    blocking = r.get("blocking", r["lint"]["blocking"])
    if blocking:
        lines += ["## 硬拦截（必须处理）"] + [f"- {json.dumps(b, ensure_ascii=False)}" for b in blocking] + [""]
    if r.get("stranger"):
        s = r["stranger"]
        lines += ["## 陌生人重读（PG）", f"- 复述：{s['core_claim_restated']}"]
        lines += [f"- 缺前提：“{m['quote']}” → {m['missing']}" for m in s["missing_premises"]]
        lines += [f"- 跳跃：“{j['quote']}” → {j['why']}" for j in s["jumps"]]
        lines += [f"- 误读：{m['misreading']}（{'已堵住' if m['blocked_in_text'] else '未堵住'}）"
                  for m in s["misreadings"]] + [""]
    if r.get("critique"):
        c = r["critique"]
        lines += ["## 拔刺（PG）"] + [f"- “{b['sentence']}” —— {b['reason']}" for b in c["briars"]] + [""]
        lines += ["## Dry 三问（能想象 / 能证伪 / 只有你能说）"]
        lines += [f"- {'✓' if d['visualize'] else '✗'}{'✓' if d['falsify'] else '✗'}"
                  f"{'✓' if d['only_you'] else '✗'} {d['sentence']}" for d in c["dry_tests"]] + [""]
        lines += ["## 读者反应（CRIBS 维度）"]
        lines += [f"- 段{x['paragraph']} {x['label']}：{x['note']}" for x in c["reader_reactions"]
                  if x["label"] != "Fine"] + [""]
        lines += ["## 有用性四因子（真实/重要/新颖/强度）"]
        lines += [f"- {u['true']}/{u['important']}/{u['novel']}/{u['strong']}"
                  f"{' ⚠️过度断言' if u['overclaim'] else ''} {u['claim']}" for u in c["usefulness"]] + [""]
        lines += ["## 诚实三问", f"- 公平：{c['honesty']['fair']}｜准确：{c['honesty']['accurate']}｜"
                  f"能说服公正观察者：{c['honesty']['persuasive_to_fair_observers']}",
                  f"- {c['honesty']['notes']}", ""]
    if r.get("flags"):
        lines += ["## 标记（只提示，不强制）"] + [f"- {json.dumps(f, ensure_ascii=False)}" for f in r["flags"]] + [""]
    lines += ["## H4 人工核对清单",
              "- [ ] 每条引语逐字回到原链接，确认是本人原话还是转述",
              "- [ ] 每个数字回到一手来源",
              "- [ ] 每段亲身经历确实发生过",
              "- [ ] 涉及真实人物的负面陈述再查一遍",
              "- [ ] 全文朗读一遍，或换一种媒介读",
              "- [ ] 结尾由你本人拍板", ""]
    claims = r.get("checkable_claims", [])
    if claims:
        lines += ["需要核对的引语和数字："] + [f"- [{c['kind']}] {c['text']}" for c in claims
                                            if c["kind"] in ("quote", "number")] + [""]
    nq = sum(1 for c in claims if c["kind"] == "quote")
    nn = sum(1 for c in claims if c["kind"] == "number")
    lines += [f"定稿：`ca approve {hub_id} H4 --quotes-checked {nq} --numbers-checked {nn} --ending-ok "
              f"--canonical-url <母稿链接>`"]
    vault.write_hub_file(hub_id, "review.md", "\n".join(lines))


# =============================================================== S6 平台适配
def s6_adapt(vault: Vault, llm: LLM, hub_id: str, n_x: int = 5, n_notes: int = 5,
             start: dt.datetime | None = None) -> list[dict]:
    meta = vault.meta(hub_id)
    check(meta, "adapt")
    final = vault.read_hub_file(hub_id, "final.md")
    profile = vault.profile()
    xrules = vault.platform("x")
    x_limit = int(xrules.get("max_weighted_chars", 280))
    out = llm.json(
        stage="adapt",
        system=P.ADAPT_SYSTEM.format(deltas=json.dumps(profile.get("platform_deltas", {}),
                                                       ensure_ascii=False)),
        user=P.ADAPT_USER.format(final=final, n_x=n_x, n_notes=n_notes, x_limit=x_limit,
                                 x_cjk=x_limit // 2),
        schema=P.ADAPT_SCHEMA,
    )

    canonical = meta.get("canonical_url") or ""
    campaign = hub_id
    ai_level = "draft_B" if meta.get("draft_mode") == "B" else "edit_only"
    start = start or (dt.datetime.now().astimezone().replace(hour=9, minute=20, second=0, microsecond=0)
                      + dt.timedelta(days=1))
    banned_topics = [t.lower() for t in xrules.get("monetization_excluded_topics", [])]
    variants = []

    for i, p in enumerate(out["x_posts"], 1):
        vid = f"v_{hub_id}_x_post_{i:02d}"
        text = p["text"].strip()
        checks = {
            "weighted_length": x_weighted_length(text),
            "within_limit": x_weighted_length(text) <= x_limit,
            "no_link_in_root": not URL_RE.search(text),
            "no_hashtags": not re.search(r"(^|\s)#[^\s#]+", text),
            "no_mentions": not re.search(r"(^|\s)@\w+", text),
            "cashtags_ok": len(re.findall(r"\$[A-Za-z]{1,6}\b", text)) <= int(xrules.get("max_cashtags_per_post", 1)),
            "dry_tests": f"{sum([p['visualize'], p['falsify'], p['only_you']])}/3",
            "dry_at_least_2": sum([p["visualize"], p["falsify"], p["only_you"]]) >= 2,
            "reply_hook": bool(p["reply_hook"].strip()),
            "not_monetization_meta": not any(t in text.lower() for t in banned_topics),
            "no_tk": "TK" not in text,
            "numbers_in_final": _numbers_in(text, final),
        }
        variants.append(_variant(
            vid, hub_id, "x", "x_post", meta, text, checks,
            link_url=with_utm(canonical, source="x", medium="post", campaign=campaign, content=vid)
            if canonical else None,
            link_placement="none", ai_level=ai_level,
            planned=start + dt.timedelta(days=(i - 1) * 7 / max(n_x, 1)),
            extra={"idea": p["idea"], "reply_hook": p["reply_hook"]}, gate="G-XP"))

    for i, n in enumerate(out["notes"], 1):
        vid = f"v_{hub_id}_substack_note_{i:02d}"
        text = n["text"].strip()
        checks = {
            "self_contained": len(text) > 20,
            "no_tk": "TK" not in text,
            "no_hashtags": not re.search(r"(^|\s)#[^\s#]+", text),
            "numbers_in_final": _numbers_in(text, final),
        }
        variants.append(_variant(
            vid, hub_id, "substack_notes", "substack_note", meta, text, checks,
            link_url=with_utm(canonical, source="substack", medium="note", campaign=campaign, content=vid)
            if canonical else None,
            link_placement="none", ai_level=ai_level,
            planned=start + dt.timedelta(days=i - 1, hours=4),  # 每天至多一条，同一天不连发
            extra={"note_type": n["type"]}, gate="G-SN"))

    for v in variants:
        vault.save_variant(v)

    s = out["substack"]
    footer = with_utm(canonical, source="substack", medium="email", campaign=campaign,
                      content="footer") if canonical else "<母稿链接>"
    package = [f"# Substack 发布包 · {hub_id}", "",
               "## 标题候选（用原生 A/B 测试，看打开者点击率）"] + [f"- {t}" for t in s["title_variants"]]
    package += ["", f"## 副标题\n{s['subtitle']}", "", f"## 文末 CTA\n{s['cta']}",
                "", f"## AI 使用说明（建议放进 post template）\n{profile.get('disclosure_line', '')}",
                "", f"## 带 UTM 的分享链接\n{footer}", "",
                "## 发送前清单（G-SS）",
                "- [ ] 开头 3 段内有一句话答案或明确承诺",
                "- [ ] 引言不超过全文 15%",
                "- [ ] 免费部分本身完整；付费墙落在自然停顿处，或选用 freewall / metered paywall",
                "- [ ] 文中至少链接 1 篇最相关的旧文",
                "- [ ] 至少一张核心图表或一个核心数字",
                "- [ ] 结尾不是总结段",
                "- [ ] 是否发布“How I make this”声明、是否关闭本篇 AI 扫描：由你决定",
                "", "## 正文（粘贴到 Substack 编辑器）", "", final]
    vault.write_hub_file(hub_id, "substack_package.md", "\n".join(package))
    meta["status"] = "adapted"
    vault.save_meta(hub_id, meta)
    return variants


def _numbers_in(variant_text: str, final: str) -> bool:
    """变体里的每个数字都必须出现在定稿里：改编不得新增事实（手册 S6）。"""
    body = URL_RE.sub("", variant_text)
    nums = re.findall(r"\d+(?:[.,]\d+)?%?", body)
    return all(n in final for n in nums)


def _variant(vid, hub_id, platform, fmt, meta, text, checks, *, link_url, link_placement,
             ai_level, planned, extra, gate) -> dict:
    failed = [k for k, v in checks.items() if v is False]
    return {
        "variant_id": vid,
        "hub_id": hub_id,
        "platform": platform,
        "format": fmt,
        "language": meta.get("language", "zh"),
        "derivation": "atomize",
        "status": "gated" if not failed else "draft",
        "body": {"text": text, "char_count": len(text), **extra},
        "link_policy": {"placement": link_placement, "url": link_url,
                        "note": "根帖不放链接；如需导流，由你本人在回复里手动贴这条带 UTM 的链接"},
        "canonical": {"url": meta.get("canonical_url"), "method": "n/a"},
        "compliance": {"ai_assist_level": ai_level, "automated_interaction": "none"},
        "schedule": {"planned_at": planned.isoformat(timespec="minutes")},
        "gate_results": {"gate": gate, "checks": checks, "failed": failed, "passed": not failed},
        "publish_result": None,
    }


# =============================================================== 发布记录（人工发布后）
def mark_published(vault: Vault, variant_id: str, url: str, at: str | None = None,
                   cost_usd: float | None = None) -> dict:
    v = vault.variant(variant_id)
    meta = vault.meta(v["hub_id"])
    check(meta, "publish")
    if v["status"] != "approved":
        raise VaultError(f"{variant_id} 还没在 H5 获批（当前 {v['status']}）")
    v["status"] = "published"
    v["publish_result"] = {"channel": "manual", "url": url, "published_at": at or now_iso(),
                           "cost_usd": cost_usd}
    vault.save_variant(v)
    return v
