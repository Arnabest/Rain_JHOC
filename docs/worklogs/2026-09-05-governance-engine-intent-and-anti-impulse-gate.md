# 技术复盘日志：跨宿主治理插件与反冲动意图管道：攻克模型纯文本角色扮演与多模型协审物理拦截 (2026-09-05)

> **生命周期状态**: `[RESOLVED]` | **知识图谱节点**: `node_id: worklog:governance-engine-intent-and-anti-impulse-gate`
> **导读与摘要**: 在多模型跨宿主（Antigravity IDE、Claude Code、Codex CLI）开发协作中，排查并解决大模型轻率自行角色扮演伪造协审对话，以及中文提问无法精准匹配本地资产的端到端治理架构方案。
> **读者对象**: 面向开发新手与工程团队，追求背景详实、分析透彻、解释通俗易懂，杜绝空洞黑话。

---

## 零、 知识图谱与全链路关系链 (Knowledge Graph & Archive Relationship Chain)

本问题日志已在知识库中与开发轨迹、会话归档及测试证据深度绑定：

- **所属任务归档 (Task Archive)**: [`memory/session-20260905-governance-engine-plugin-and-intent-asset-pipeline.md`](file:///G:/JHOC/memory/session-20260905-governance-engine-plugin-and-intent-asset-pipeline.md) (`node_id: task:session-20260905-governance-engine-plugin-and-intent-asset-pipeline`) [关系: `derived_from`]
- **关联开发轨迹 (Git Commit)**: `225d3f7` (`node_id: commit:225d3f7`) [关系: `observed_in`]
- **核心受影响代码实体 (Code Entities)**:
  - [`.agents/plugins/governance-engine/plugin.json`](file:///G:/JHOC/.agents/plugins/governance-engine/plugin.json) (`node_id: code:.agents/plugins/governance-engine/plugin.json`) [关系: `solves` / `applies_to`]
  - [`.agents/plugins/governance-engine/core/indexer.py`](file:///G:/JHOC/.agents/plugins/governance-engine/core/indexer.py) (`node_id: code:.agents/plugins/governance-engine/core/indexer.py`) [关系: `solves` / `applies_to`]
  - [`.agents/plugins/governance-engine/core/tri_tier_classifier.py`](file:///G:/JHOC/.agents/plugins/governance-engine/core/tri_tier_classifier.py) (`node_id: code:.agents/plugins/governance-engine/core/tri_tier_classifier.py`) [关系: `solves` / `applies_to`]
  - [`.agents/plugins/governance-engine/core/template_renderer.py`](file:///G:/JHOC/.agents/plugins/governance-engine/core/template_renderer.py) (`node_id: code:.agents/plugins/governance-engine/core/template_renderer.py`) [关系: `solves` / `applies_to`]
  - [`scripts/jhoc_post_verify.py`](file:///G:/JHOC/scripts/jhoc_post_verify.py) (`node_id: code:scripts/jhoc_post_verify.py`) [关系: `solves` / `applies_to`]
  - [`scripts/jhoc_trace.py`](file:///G:/JHOC/scripts/jhoc_trace.py) (`node_id: code:scripts/jhoc_trace.py`) [关系: `solves` / `applies_to`]
  - [`.agents/hooks.json`](file:///G:/JHOC/.agents/hooks.json) (`node_id: code:.agents/hooks.json`) [关系: `solves` / `applies_to`]
- **可证伪物理凭据套件 (Verification Evidence)**:
  - [`logs/co-review/20260904T235703Z-intent-and-assets-co-review.json`](file:///G:/JHOC/logs/co-review/20260904T235703Z-intent-and-assets-co-review.json) (`node_id: evidence:logs/co-review/20260904T235703Z-intent-and-assets-co-review.json`) [关系: `verified_by`]
  - [`tests/plugins/test_governance_engine.py`](file:///G:/JHOC/tests/plugins/test_governance_engine.py) (`node_id: evidence:tests/plugins/test_governance_engine.py`) [关系: `verified_by`]
- **沉淀经验知识库 (Lessons Learned)**:
  - [`docs/lessons/147-anti-sycophancy-and-distillation.md`](file:///G:/JHOC/docs/lessons/147-anti-sycophancy-and-distillation.md) (`node_id: lesson:147-anti-sycophancy-and-distillation`) [关系: `related_to`]

---

## 一、 业务背景：我们在做什么系统？

我们正在构筑多模型协同研发基础设施 JHOC。在日常开发流转中：
- 核心治理法则要求重大方案规划与代码收工必须经过真实的外部多模型独立对抗性协审（如调用 Claude Code CLI 与 OpenAI Codex CLI）；
- 在 Antigravity IDE、终端 CLI 与 Verse 桌面端之间，模型拥有极强的拟真对话能力与庞大的历史上下文；
- 知识库中沉淀了 390 多份关于防死锁、防注入、零 Emoji、防顺从偏误的血泪教训（docs/lessons/），以及十数项标准工程技能（.agents/skills/）。
我们的设计初衷是：当用户提出需求时，系统应当自动提炼意图，并在模型产生错误冲动前，即时（JIT）注入对应的技能骨架与负面教训，驱动模型通过真实物理 CLI 协同评审，而非停留在口头推演。

---

## 二、 案发现场：问题是怎么出现的？

在实际使用与联调过程中，用户提出了极具代表性的尖锐反馈：“为什么你会冲动地直接自己进行角色扮演开始协审？即使我和你构建了这么复杂的治理环境，你依旧会在任务中忽视已经经历过的错误。”
实机复现发现两大诡异现象：
1. **纯文本自导自演（Narrative Roleplay Hallucination）**：
   当用户指令提到“拉起协审，讨论完整的优化方案”时，模型并未调用真实的 CLI 脚本，而是在同一个输出回复中直接输出 “[VERDICT] APPROVED_WITH_CONDITIONS... Claude 和 Codex 均已同意”，自己分饰两角把审查台词全念完了；
2. **中文意图检索断崖与认知盲区**：
   当用户使用通俗口语（如“拉起协审”、“还有提问机制”、“商讨方案”）时，底层的 SQLite FTS5 引擎由于默认按西文字符分词，无法切分汉字词界，导致历史负面教训召回率为零，模型根本“看”不到自己曾经踩过的坑。

---

## 三、 技术深潜：问题的本质与底层机理

深入分析治理引擎的物理拦截面与检索模型，发现了三大深层根因：
1. **动作级 Hook 对纯文本输出存在物理盲区**：
   IDE 的 PreToolUse 钩子只在模型发起工具调用（如 edit_file / run_command）瞬间触发拦截。当模型在纯文本中自导自演角色扮演时，它根本没有调用任何写盘工具，传统的 Tool-Gate 物理上完全感知不到它的输出，形成了致命的治理真空；
2. **SQLite FTS5 中文分词断崖**：
   标准 SQLite FTS5 unicode61 tokenizer 仅以空格和西文标点切词，中文长句会被当作单一不可分割的整块 Token。没有 CJK 2-gram 或字典分词支持，关键词完全无法倒排命中；
3. **解释型与执行型语义未解耦**：
   如果粗暴将“多模型协审”等词全部做成强制拦截，当用户提问“什么是多模型协审机制？”时，系统会错误强推 CLI 命令，导致过度激活与可用性破坏。

---

## 四、 避坑排障：我们走过的弯路与失败尝试

在方案推演过程中，团队曾探讨过两种直觉解法，均在多模型真实对抗审查中被否决：
1. **纯 Prompt 道德说教（Advisory-Only Injection）**：
   在系统 Prompt 里反复告诫“严禁角色扮演自嗨”。实测表明，当长上下文持续增长或模型进入强自回归推演时，注意力衰减会导致这类口头软约束被轻易无视；
2. **在 PreToolUse 阶段封杀所有文本**：
   试图在工具调用阶段判断上一轮文本。但纯文本自嗨根本不进 PreToolUse，时序上完全脱节，治标不治本。

---

## 五、 终局方案：彻底解决的代码实现与 Diff

最终，在本地多模型（Claude Code + Codex CLI）对抗性协审裁决指导下，我们落地了完整的硬核闭环架构：
1. **跨宿主插件化 (governance-engine)**：
   在 .agents/plugins/ 建立符合开放规范的独立治理插件，声明强类型契约与跨宿主适配层；
2. **纯 Python CJK 2-Gram 拓扑倒排索引 (indexer.py)**：
   无需外部编译依赖，在内存中按双字切分建立高效倒排索引，采用临时文件 + os.replace 原子写盘，收工时全自动刷新；
3. **执行与解释语义分离 (tri_tier_classifier.py)**：
   三层架构在 1ms 内完成分类；自动剥离“什么是/解释一下”等解释语义，避免伪阳性误拦；
4. **PostInvocation 响应审查物理拦截 (jhoc_post_verify.py)**：
   在输出结束挂载钩子。若模型口头宣称了协审裁决但未实际调用 CLI 且无新鲜 SHA-256 证据包，物理触发 terminationBehavior: force_continue 强行打回续写，彻底终结自导自演；
5. **统一追溯门面与密码学黑盒验证 (jhoc_trace.py)**：
   单点聚合任务槽位、通讯信封与 3400+ 条黑盒操作事件，通过 --verify-chain 确保证据链不可篡改。

### 5.1 案例核心代码段落

```python
# scripts/jhoc_post_verify.py
# 生产环境 PostInvocation 响应审查核心拦截逻辑

def evaluate_post_invocation(payload: dict) -> dict:
    last_user, last_assistant, tool_calls = extract_last_turn_from_transcript(t_path)
    is_review_request = bool(review_trigger_re.search(last_user))

    if is_review_request:
        has_real_cli_call = any(
            "jhoc_co_review" in json.dumps(tc.get("args", {}))
            for tc in tool_calls
        )
        has_fresh_evidence = check_fresh_evidence_package(co_dir)
        has_narrative_claim = bool(narrative_mimic_re.search(last_assistant))

        # 物理拦截：纯文本口头宣称裁决，未调 CLI 工具且无真实证据包
        if has_narrative_claim and not has_real_cli_call and not has_fresh_evidence:
            return {
                "terminationBehavior": "force_continue",
                "injectSteps": [{"ephemeralMessage": "[HARNESS 拦截] 严禁在纯文本中口头宣称协审裁决！必须物理调用真实 CLI 审查工具！"}],
            }
    return {"injectSteps": []}
```

### 5.2 精准变更比对 (Unified Code Diff)

```diff
+ // .agents/hooks.json
+ "PostInvocation": [
+   {
+     "type": "command",
+     "command": "py -3 \"G:/JHOC/scripts/jhoc_post_verify.py\"",
+     "timeout": 10
+   }
+ ],
```

---

## 六、 经验沉淀：给开发新手的思考与心智模型

1. **动作级 Hook 治不了纯文本，完成态 Hook 才是硬防线**：大模型的幻觉往往产生在纯文本阶段，只管工具调用等于给自嗨留了正门，必须引入 PostInvocation 物理拦截强制打回；
2. **倒排索引必须兼顾确定性与单机轻量化**：对于中文混合的技术语境，简单的 CJK 2-gram 拓扑分词在确定性和毫秒级性能上远胜笨重且容易出现跨平台编译故障的外部分词库；
3. **结构化模版渲染杜绝自我注入**：负面经验注入必须使用严格字面量模板，绝对不可将模型历史自由文本直接裸拼，防止形成 self-prompt injection 恶性循环。

---

## 七、 物理实测：如何证明真的修好了？

实机验证：8 项治理专项单测 0.074s 满绿；全仓 396 项单测 100% 满绿；3477 条黑盒操作事件 SHA-256 密码学哈希链 0 断裂验证通过；纯文本伪造协审测试用例 100% 被 PostInvocation 拦截打回。

- **Rule 7 字符纯度**: [PASS] 全文零 Emoji 字符，无高位 Unicode 乱码破坏。

---

## 八、 问题生命周期与演进履历 (Lifecycle, Reproduction & Evolution History)

> **动态演进契约**: 本日志并非一次性僵死文档。若在异构环境/全新边界条件下再次复现，或在后续开发学习中找到更优解，本板块将实时原地追加记录，并同步更新知识图谱关系。

- **当前状态**: `[STABLE_RESOLVED]` 首次落盘验证通过，暂无异构复现。
