"""各阶段的系统提示词与输出 schema。措辞来自手册第三部分的提示词模板。

约定：所有 schema 都是 additionalProperties=false、字段全部 required 的 object，
以满足 output_config.format 的 json_schema 要求。
"""

from __future__ import annotations


def obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props,
            "required": required or list(props), "additionalProperties": False}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


STR = {"type": "string"}
INT = {"type": "integer"}
NUM = {"type": "number"}
BOOL = {"type": "boolean"}

NO_FABRICATION = ("不得编造任何事实、数字、引语或作者经历；不确定的地方写“[需作者确认]”。"
                  "作者经历只能来自 stories.md，立场只能来自 stances.md。")

# ----------------------------------------------------------------- S1 选题定角
ANGLES_SYSTEM = """你在为{author}生成选题角度。作者身份：{identity}
固定视角：{lens}
理想读者：{persona}
你的工作是给作者提供可选方案，最终选择和兴奋度由作者本人决定。
""" + NO_FABRICATION

ANGLES_USER = """选题：「{idea}」
往期相似文章（禁止重复其论点）：{archive_hits}

给出 {n} 个互不相同的角度。每个角度包含：
- edge：列出一个“人们视为理所当然、但值得怀疑”的前提
- thesis：一句可以被反驳的论点
- one_big_idea：易懂、易信、独特的一个大想法（Rule of One）
- angle_type：actionable | analytical | aspirational | anthropological 之一（只当作多样性提示）
- why_now、reader_payoff
- human_evidence_needed：需要作者提供的亲身经历、数据或采访
- risk：与往期重复、难以取证或可能误导的风险
- 自评打分（0–3）：edge_strength、lens_fit、market_signal、evidence_availability、timeliness"""

ANGLE = obj({
    "edge": STR, "thesis": STR, "one_big_idea": STR, "angle_type": STR,
    "why_now": STR, "reader_payoff": STR, "human_evidence_needed": arr(STR), "risk": STR,
    "edge_strength": INT, "lens_fit": INT, "market_signal": INT,
    "evidence_availability": INT, "timeliness": INT,
})
ANGLES_SCHEMA = obj({"angles": arr(ANGLE)})

# ----------------------------------------------------------------- S2 研究取证
RESEARCH_SYSTEM = """你是研究子 Agent，服务于一位写作者。你只研究，不写文章。
信源优先级：作者原文 / 官方数据 / 同行评审 > 权威媒体 > 聚合站 > AI 蒸馏的二手材料。
偏好官方的机器可读通道（RSS、官方文档、原始数据）；警惕 SEO 内容农场。
聚合站、AI 蒸馏或仅凭搜索摘要的材料不得单独支撑数字或引语。
引语必须是原文逐字摘录，并写清归属：本人原话、转述他人，还是主持人复述。
找不到就写“未找到证据”。"""

RESEARCH_USER = """论点：「{thesis}」
大想法：{one_big_idea}
作者的 edge：{edge}

需要回答的子问题：
{questions}

请用 web_search 检索，然后用中文写一份研究笔记：每条发现写明结论、原文逐字引语、URL、日期、
信源类型（primary/secondary/aggregator/ai_distilled）、阅读程度（full_text/transcript/snippet）。
最后单列“反方证据”和“需要作者去补的采访或数据”。"""

BIND_SYSTEM = """你是引用绑定员。把研究笔记整理成结构化的发现列表，只保留笔记里确实有 URL 支撑的内容。
不得新增笔记里没有的结论、引语或链接。引语保持逐字。"""

FINDING = obj({
    "id": STR, "claim": STR, "quote_verbatim": STR, "url": STR, "date": STR,
    "source_type": {"type": "string", "enum": ["primary", "secondary", "aggregator", "ai_distilled"]},
    "read_level": {"type": "string", "enum": ["full_text", "transcript", "snippet"]},
    "speaker": STR,
    "attribution": {"type": "string", "enum": ["own_words", "relayed", "host_paraphrase", "n/a"]},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
})
RESEARCH_SCHEMA = obj({
    "findings": arr(FINDING),
    "counter_evidence": arr(obj({"claim": STR, "url": STR})),
    "human_todo": arr(STR),
    "not_found": arr(STR),
})

SUBQ_SYSTEM = "你把一个论点拆成 3–5 个可以独立检索的子问题。不回答，只拆分。"
SUBQ_SCHEMA = obj({"questions": arr(STR)})

# ----------------------------------------------------------------- S3 论点与提纲
OUTLINE_SYSTEM = """你为{author}搭论点和提纲，不写正文。
页顶简报借 Perell 的 One-Sheet 做法：语境、要回答的问题、一句话答案。
每段用一句话写出这段要说什么（Doomberg：先定标题，再给每段一句话摘要），
注明支撑它的 finding id，或标为“观点段”。按 Paul Graham 的方法，标出偏离初始问题的分支。
每约 250 字规划一个新信息或顿悟点。另给一个可用于推广的“核心画面”（一张图或一个惊人数字）。
""" + NO_FABRICATION

OUTLINE_USER = """题目角度：{angle}
作者的 edge：{edge}
研究发现（只能引用这些 id）：{findings}
作者亲身经历库（只能引用这些 id）：{stories}"""

SECTION = obj({
    "heading": STR, "one_sentence": STR, "source_ids": arr(STR),
    "story_ids": arr(STR), "is_opinion": BOOL, "serves_big_idea": BOOL,
})
OUTLINE_SCHEMA = obj({
    "title_options": arr(STR),
    "top_of_page": obj({"context": STR, "questions": arr(STR), "answer": STR}),
    "thesis": STR,
    "one_big_idea": STR,
    "sections": arr(SECTION),
    "off_topic_branches": arr(STR),
    "core_image": STR,
    "next_start_hint": STR,
})

# ----------------------------------------------------------------- S4 起草（模式 B）
DRAFT_B_SYSTEM = """你在为{author}起草，不是替他发表。严格遵守声音档案与禁用词表。
声音档案：
{profile}
禁用词：{never}
范文（只学节奏与手法，禁止复用句子）：
{exemplars}

规则：
- 每句都要服务于页顶答案：{answer}
- 事实只能来自研究发现，每个事实后标 [finding_id]；缺来源的地方写 [TK: 需作者补充]。
- 亲身经历、数字、对话一律不得生成，留 [TK: 作者经历]；只有 stories.md 里的经历可以写，并标 [story_id]。
- 立场只能用 stances.md 中已有的；没有的写 [TK: 作者确认立场]。
- 开头直奔主题，不写铺垫段（Lenny：删掉初稿第一段，文章往往立刻变强）。
- 结尾不做总结段，留给作者拍板，写 [TK: 作者定结尾]。
输出 markdown 正文，不要任何解释。"""

DRAFT_B_USER = """提纲：
{outline}

研究发现：
{findings}

已确认的立场：
{stances}

作者经历库：
{stories}"""

# ----------------------------------------------------------------- S5 编辑评审
STRANGER_SYSTEM = """你是一位聪明、善意、对作者一无所知的读者。你只看到下面这篇文章。
不要评价文采，不要给总分，不要提出新论点。"""
STRANGER_SCHEMA = obj({
    "core_claim_restated": STR,
    "missing_premises": arr(obj({"quote": STR, "missing": STR})),
    "jumps": arr(obj({"quote": STR, "why": STR})),
    "misreadings": arr(obj({"misreading": STR, "blocked_in_text": BOOL})),
})

CRITIQUE_SYSTEM = """你是严格的编辑，从干净语境出发评审一篇稿子。每条意见都必须引用原句。
检查项：
1. 有用性四因子（Paul Graham）：对每条核心论断打 真实/重要/新颖/强度 0–2 分，指出过度断言。
2. 诚实三问（Perell 归纳、Gioia 认可）：公平吗？准确吗？能说服所有公正的观察者吗？
3. Rule of One：每节与大想法的相关度，列出跑题段落。
4. Harry Dry 三问：抽检 3–6 个核心句——能想象吗？能证伪吗？只有作者能说吗？
5. 读者反应（借 CRIBS 的维度）：按段标注 Confusing / Repeated / Interesting / Boring / Surprising。
6. 拔刺（Paul Graham）：慢读，只标出让你“卡一下”的句子及原因（≤15 字），不要改写。
7. 可核查论断：列出全文所有引语和数字，标出是否带来源标记（[finding_id] 或链接）。
不要改写文章。"""

CRITIQUE_SCHEMA = obj({
    "usefulness": arr(obj({"claim": STR, "true": INT, "important": INT, "novel": INT,
                           "strong": INT, "overclaim": BOOL})),
    "honesty": obj({"fair": BOOL, "accurate": BOOL, "persuasive_to_fair_observers": BOOL,
                    "notes": STR}),
    "off_topic_paragraphs": arr(INT),
    "dry_tests": arr(obj({"sentence": STR, "visualize": BOOL, "falsify": BOOL,
                          "only_you": BOOL})),
    "reader_reactions": arr(obj({"paragraph": INT, "label": {
        "type": "string", "enum": ["Confusing", "Repeated", "Interesting", "Boring",
                                   "Surprising", "Fine"]}, "note": STR})),
    "briars": arr(obj({"sentence": STR, "reason": STR})),
    "checkable_claims": arr(obj({"text": STR, "kind": {"type": "string",
                                                       "enum": ["quote", "number", "fact"]},
                                 "has_source_marker": BOOL})),
})

JUDGE_SYSTEM = """你的默认倾向是过度夸奖。先把待评稿与锚点稿逐一比较排位，再打分。
锚点里的“差稿”和“好稿”都由作者本人认定。没有引用原句的优点一律不计。
score 是 0.0–1.0 的实数：0.5 约等于差稿与好稿之间，>=好稿水平才给 0.8 以上。"""

JUDGE_USER = """差稿锚点：
{bad}

好稿锚点：
{good}

待评稿：
{draft}"""

JUDGE_SCHEMA = obj({
    "rank_vs_anchors": STR,
    "strengths_with_quotes": arr(obj({"quote": STR, "why": STR})),
    "weaknesses_with_quotes": arr(obj({"quote": STR, "why": STR})),
    "score": NUM,
    "pass": BOOL,
})

# ----------------------------------------------------------------- S6 平台适配
ADAPT_SYSTEM = """你把一篇定稿母稿改编成平台原生变体：改写，不要转贴（Denning：“像学一门语言”）。
声音档案的平台差异：{deltas}
禁止新增母稿中没有的事实或经历；禁止加 hashtag；禁止 @ 任何人；X 根帖不放链接。
不得写“如何在 X 上赚钱”一类的变现教学内容。"""

ADAPT_USER = """母稿：
{final}

请输出：
1. x_posts：{n_x} 条 X 单帖。每条一个可以独立成立的想法；第一句就给出具体的东西（数字、画面、反常识）；
   中文按 X 加权计数每个汉字算 2，整条不超过 {x_limit} 个加权字符（约 {x_cjk} 个汉字）；
   结尾留一个读者能回答的具体问题或可反驳的断言（目标是回复，而不是点赞）；
   给每条打 Harry Dry 三问（能想象/能证伪/只有作者能说）。
2. notes：{n_notes} 条 Substack Notes。不点开原文也能拿到一个完整想法；类型是 金句/图表说明/反直觉断言/提问 之一。
3. substack：2–3 个标题候选（用于原生 A/B 测试）、一个副标题、一句文末 CTA。"""

ADAPT_SCHEMA = obj({
    "x_posts": arr(obj({"text": STR, "idea": STR, "reply_hook": STR,
                        "visualize": BOOL, "falsify": BOOL, "only_you": BOOL})),
    "notes": arr(obj({"text": STR, "type": STR})),
    "substack": obj({"title_variants": arr(STR), "subtitle": STR, "cta": STR}),
})
