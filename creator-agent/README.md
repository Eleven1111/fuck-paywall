# creator-agent · 多平台创作 Agent（P1 MVP）

按《[三平台创作 Agent 手册·核实版](../reports/三平台创作Agent手册核实版.md)》第三部分的路线图，实现 **P0 建库 + P1 MVP**：

> 一个母站（Substack）加两个辐条（X 单帖、Substack Notes）；研究用单 Agent 加搜索；**全部人工发布**；带 UTM 生成器、离线测试集和人工编辑时长记录。

它是一个**工作流**，不是自主 Agent：每个阶段一两次确定的模型调用，结果写成 markdown 交给你审，你用 `ca approve` 放行后才能进下一步。

```
S1 选题定角 ─H1→ S2 研究取证 ─H2→ S3 论点提纲 ─H3→ S4 起草 → S5 编辑评审 ─H4→
S6 平台适配（x_post / substack_note / Substack 发布包）─H5→ 你本人发布 → ca published
```

## 安装

```bash
cd creator-agent
pip install -e '.[dev]'
```

凭证：设 `ANTHROPIC_API_KEY`，或先运行 `ant auth login`。默认模型 `claude-opus-5-5`，可在知识库的 `agent.yaml` 里改。

## 第一次使用（P0 建库）

```bash
ca init ~/creator-vault
export CA_VAULT=~/creator-vault
```

然后按提示完成手册 P0 的完成标准：

| 文件 | 要做的事 |
|---|---|
| `voice/profile.yaml` | 写身份、固定视角、理想读者、句长、结尾习惯、平台差异 |
| `voice/never.md` / `deliberate_breaks.md` | 禁用词（命中即拦截）/ 有意破格（lint 跳过） |
| `voice/stances.md` / `stories.md` | 已表态的立场 / 亲口确认过的经历（Agent 只能引用这里的） |
| `voice/exemplars/*.md` | 5–15 段你自己的范文（模式 B 起草时学节奏用） |
| `evals/anchors/good_*.md`、`bad_*.md` | 你认定的好稿、差稿各 ≥2 篇，用来校准评审打分 |
| `evals/testset.jsonl` | ≥20 条离线测试用例（与锚点分开） |

```bash
ca import-rss https://你的名字.substack.com/feed     # 往期文章进 archive/，S1 用来查重
ca idea add "小团队要不要做用户访谈？" --edge "大家默认按项目做，我怀疑"
```

## 一篇稿子的完整流程

```bash
ca new idea_0001 --angles                 # 建母稿并跑 S1 → hubs/<id>/angles.md
ca approve <id> H1 --angle 2 --excitement 4 --edge "一句话写下你的 edge"
ca research <id>                          # S2：拆子问题 → web_search → 引用绑定 → research.md
ca approve <id> H2 --confirm              # 按 research.md 末尾的清单查过
ca outline <id>                           # S3：页顶简报 + 逐段一句话提纲 → outline.md
ca approve <id> H3
ca draft <id>                             # S4 模式 A：只给素材卡片 cards.md，你自己写 draft.md
ca review <id>                            # S5：lint + 陌生人重读 + 编辑评审 + 反恭维打分 → review.md
ca approve <id> H4 --quotes-checked 3 --numbers-checked 2 --ending-ok \
                   --canonical-url https://你的名字.substack.com/p/xxx
ca adapt <id>                             # S6：5 条 X 单帖 + 5 条 Notes + Substack 发布包
ca approve <id> H5 --variants all         # 只放行通过平台闸口的变体
# 你本人去 Substack / X 发布，然后：
ca published v_<id>_x_post_01 https://x.com/你/status/...
ca log-edit <id> 45                       # 记录人工编辑分钟数
ca status <id>
```

`ca draft <id> --mode B` 会让 Agent 按批准过的提纲起草，但它不会编造经历、数字和立场，这些位置一律留 `[TK: ...]`。草稿里只要还有 TK，`ca review` 就直接拦截，不会调用模型。

## 每个阶段对应手册的哪条规则

| 阶段 | 实现了什么 | 手册依据 |
|---|---|---|
| S1 | 往期查重；3–5 个角度，每个带 edge、可证伪论点、Rule of One、需要你提供的证据；按排序表算预排序分 | S1 排序表（兴奋度 0.30 必须由你填） |
| H1 | 不填兴奋度、写不出 edge 就不放行 | “写不出 edge 的题目退回选题池” |
| S2 | 拆子问题 → `web_search` 研究 → 单独一次调用做引用绑定；snippet、聚合站、AI 蒸馏来源标为弱来源 | 编排者-工作者的简化版；`read_level`、`attribution` 字段 |
| S3 | 页顶简报（One-Sheet）、逐段一句话、来源 id 校验、跑题分支、核心画面 | Perell、Doomberg、PG |
| S4 | 模式 A 素材卡片 / 模式 I 访谈提问 / 模式 B 带 TK 的草稿 | 三种起草模式 |
| S5 | TK、禁用词硬拦截；AI 腔密度、对冲词、感叹号、总结式结尾、引言占比；陌生人重读与误读；有用性四因子、诚实三问、Dry 三问、CRIBS 维度、拔刺；带锚点的反恭维打分；无来源的引语和数字硬拦截 | S5 评审表（MVP 版） |
| H4 | 评审后改过稿就要重评；核对数量不能少于评审提取的引语和数字数；未通过评审必须写理由 | H4 人工核对清单 |
| S6 | X 加权字数（汉字算 2）、根帖无链接、无 hashtag、无 @、cashtag ≤1、Dry 至少 2 项、有回复钩子、不碰变现话题、**变体里的数字必须出现在定稿里**；每个变体带 UTM；X 单帖分散在一周，Notes 每天至多一条 | G-XP、G-SN、UTM 规范 |
| 发布 | 不调用任何平台写入接口；`automated_interaction` 永远是 `none` | X 自助档 API 限制、Substack 无发文 API |

## 离线测试集

```bash
ca eval
```

只跑反恭维评审，输出好稿和差稿的平均分、阈值准确率和成对排序准确率（AUC）。P1 的完成标准是“评审能区分好稿和差稿”，这里用 AUC ≥ 0.8 作为判断线（`discriminates: true`）。

## 刻意没做的（留给 P2 及以后）

- 不接 X API 发帖，不接 Owned Reads 拉指标（P2）；不生成 `x_thread`、`x_article`、`medium_story`（P2）。
- 研究是单 Agent 加搜索，没有并行子 Agent 和 SAFE 式逐条核查（P3）。
- 闸口是文件记录，不是 LangGraph `interrupt()`（P4）。
- 风格漂移检测、`edit_diffs` 采集、月度复盘（P2–P3）。

## 开发

```bash
pytest -q
```

测试用假客户端覆盖了完整流水线、闸口顺序、TK 拦截、来源 id 校验、改编不得新增数字、X 加权字数、UTM 和测试集打分。**这个版本还没有用真实 API 跑过**，第一次真实运行时请留意各阶段的结构化输出是否符合预期。
