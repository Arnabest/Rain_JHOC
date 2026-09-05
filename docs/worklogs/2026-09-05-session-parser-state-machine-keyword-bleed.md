# 技术复盘日志：半结构化 Markdown 状态机解析边界失守排障：防范正文标题关键字模糊穿透 (2026-09-05)

> **生命周期状态**: `[EVOLVED]` | **知识图谱节点**: `node_id: worklog:session-parser-state-machine-keyword-bleed`
> **导读与摘要**: 深入复盘在编写工作日志自动提取器时，由于状态机过于依赖模糊子串匹配，导致任务大标题中包含‘测试’二字意外穿透状态边界、引发数据全面错位的排查与根治过程。
> **读者对象**: 面向开发新手与工程团队，追求背景详实、分析透彻、解释通俗易懂，杜绝空洞黑话。

---

## 零、 知识图谱与全链路关系链 (Knowledge Graph & Archive Relationship Chain)

本问题日志已在知识库中与开发轨迹、会话归档及测试证据深度绑定：

- **所属任务归档 (Task Archive)**: [`memory/session-20260905-worklog-distiller-skill.md`](file:///G:/JHOC/memory/session-20260905-worklog-distiller-skill.md) (`node_id: task:session-20260905-worklog-distiller-skill`) [关系: `derived_from`]
- **关联开发轨迹 (Git Commit)**: `143f4c9` (`node_id: commit:143f4c9`) [关系: `observed_in`]
- **核心受影响代码实体 (Code Entities)**:
  - [`scripts/jhoc_worklog.py`](file:///G:/JHOC/scripts/jhoc_worklog.py) (`node_id: code:scripts/jhoc_worklog.py`) [关系: `solves` / `applies_to`]
- **可证伪物理凭据套件 (Verification Evidence)**:
  - [`tests/test_worklog_distiller.py`](file:///G:/JHOC/tests/test_worklog_distiller.py) (`node_id: evidence:tests/test_worklog_distiller.py`) [关系: `verified_by`]
- **沉淀经验知识库 (Lessons Learned)**:
  - [`docs/lessons/LESSON-state-machine-boundaries.md`](file:///G:/JHOC/docs/lessons/LESSON-state-machine-boundaries.md) (`node_id: lesson:LESSON-state-machine-boundaries`) [关系: `related_to`]

---

## 一、 业务背景：我们在做什么系统？

在开发面向人类阅读的工作日志总结工具（worklog-distiller）时，核心引擎的一项关键任务是：读取以往的会话记忆文档（`memory/session-*.md`），提取出结构化事实：
- 这次任务的【目标】是什么？
- 具体落地了哪些【核心改动】？
- 自动化【测试验收结果】是什么？
由于这些文档是由 Markdown 撰写的半结构化文本，解析器需要依靠逐行扫描并维护一个“当前正在读哪一节”的状态机（State Machine）来完成信息分类归档。

---

## 二、 案发现场：问题是怎么出现的？

在为该工具编写单元测试时，我们构造了一个测试用例：
文件标题为 `# Session Memory: 测试演示任务`，文档末尾记录了 `10/10 项断言全数通过 (100% PASS)`。
运行单测 `py -3 -m unittest tests/test_worklog_distiller.py`，测试套件突然红灯报错：
```text
FAIL: test_extract_session_facts
AssertionError: '100% PASS' not found in '**目标**: 验证会话事实抽取器'
```
测试断言要求提取出来的第一条测试结果必须包含 `100% PASS`，但实际提取出来的竟然是文档开头的一句元数据：`**目标**: 验证会话事实抽取器`！测试数据彻底错位。

---

## 三、 技术深潜：问题的本质与底层机理

对于初学者来说，状态机（State Machine）其实就像火车站的道岔。解析器一行一行读文本：
- 看到道岔标牌“修改清单”，把车开进“改动轨道”；
- 看到道岔标牌“验收结果”，把车开进“测试轨道”。
原本的代码是这么写的：
```python
if "修改清单" in line_str or "落地" in line_str:
    current_section = "changes"
elif "验收结果" in line_str or "测试" in line_str:  # 隐患埋在这里！
    current_section = "tests"
```
问题就出在 `or "测试" in line_str` 这一句上！
当解析器刚刚读到文档的第一行：
`# Session Memory: 测试演示任务` 时，
代码进行了子串比对，发现这一行包含了“测试”两个字，状态机瞬间被触发，提前将状态切换到了 `"tests"`！
紧接着读到第二行 `- **目标**: 验证会话事实抽取器` 时，状态机以为当前正在读测试结果，直接把“目标”这一行塞进了测试结果列表！

---

## 四、 避坑排障：我们走过的弯路与失败尝试

初学者在排查这类 Bug 时，最容易想到的直觉往往是“打地鼠”：
- **直觉尝试（追加黑名单过滤）**：
  “既然是‘测试演示任务’这几个字捣乱，那我在判断条件里加一句：
  `if '测试' in line_str and '测试演示' not in line_str:` 不就行了吗？”
- **为什么这是严重错误的？**：
  这种思路在工程上叫“特化硬编码（Hardcoding Hack）”。今天你过滤了“测试演示”，明天另一个任务叫“测试环境重构”，后天叫“测试用例审查”，黑名单永远列不全，代码会变得极其臃肿脆弱，稍有不慎再次穿透。

---

## 五、 终局方案：彻底解决的代码实现与 Diff

彻底解决这个问题的唯一正道是：**确立语法层级的物理边界，严禁模糊子串穿透**。
1. **严格限定标题语法必须以 `## ` 起始**：
   在 Markdown 中，大标题是一级（`# `），小节标题是二级（`## `）。文档元数据根本不是二级标题。必须要求 `line_str.startswith('## ')`，剥离前缀后再去比对语义，彻底把正文内容与结构标签物理隔离开；
2. **前置元数据安全隔离**：
   在进入任何合法的二级段落之前，所有的元数据行强制执行 `if not current_section: continue` 跳过，绝不给脏数据被误装进列表的可能。

### 5.1 案例核心代码段落

```python
# scripts/jhoc_worklog.py
# 生产级状态机语法层级隔离实现

current_section = ""
for line in content.splitlines():
    line_str = line.strip()
    
    # 步骤 1: 必须严格满足 Markdown 二级标题前缀，才允许判断章节状态
    if line_str.startswith("## "):
        header = line_str.lstrip("#").strip()
        if header.startswith("1.") or "修改清单" in header or "落地" in header:
            current_section = "changes"
        elif header.startswith("2.") or "验收结果" in header or "测试" in header:
            current_section = "tests"
        elif header.startswith("3.") or "建议" in header or "下一步" in header:
            current_section = "next"
        else:
            current_section = "other"
        continue # 处理完标题行后立刻跳过，不当作正文内容

    # 步骤 2: 在进入有效章节前，前置大标题与元数据行一律安全跳过
    if not current_section:
        continue

    # 步骤 3: 提取有效列表条目
    if line_str.startswith("- ") or re.match(r"^\d+\.\s+", line_str):
        item = re.sub(r"^(\d+\.|\-)\s*", "", line_str).strip()
        if current_section == "tests":
            test_results.append(item)
```

### 5.2 精准变更比对 (Unified Code Diff)

```diff
-  # 脆弱逻辑：只要行内包含“测试”二字就直接切换状态，首行标题造成穿透
-  if line_str.startswith("## 1.") or "修改清单" in line_str or "落地" in line_str:
-      current_section = "changes"
-  elif line_str.startswith("## 2.") or "验收结果" in line_str or "测试" in line_str:
-      current_section = "tests"
+  # 健壮逻辑：严格限定 ## 前缀，并在未进入章节前隔离元数据
+  if line_str.startswith("## "):
+      header = line_str.lstrip("#").strip()
+      if header.startswith("1.") or "修改清单" in header:
+          current_section = "changes"
+      elif header.startswith("2.") or "验收结果" in header or "测试" in header:
+          current_section = "tests"
+      continue
+  if not current_section:
+      continue # 隔离正文元数据
```

---

## 六、 经验沉淀：给开发新手的思考与心智模型

1. **语法层级永远高于文本语义**：解析半结构化文档时，必须‘先看语法标点（是否为二级标题），再看文字内容’，不能跳过语法直接对文本做子串搜索；
2. **拒绝打补丁，寻求正交边界**：遇到特定关键词误判，永远不要去加特化黑名单，而要重新审视你的触发门禁是否足够严谨；
3. **单测是测试状态机鲁棒性的照妖镜**：编写单元测试时，要故意在非目标字段里塞入目标关键字（比如在标题里塞‘测试’、在备注里塞‘报错’），检验解析器会不会被晃晕。不断用边界用例反哺系统免疫力。

---

## 七、 物理实测：如何证明真的修好了？

实测验证：运行单元测试 `py -3 -m unittest tests/test_worklog_distiller.py`，全套 7 项单测全部满绿通过 (100% PASS)。

- **Rule 7 字符纯度**: [PASS] 全文零 Emoji 字符，无高位 Unicode 乱码破坏。

---

## 八、 问题生命周期与演进履历 (Lifecycle, Reproduction & Evolution History)

> **动态演进契约**: 本日志并非一次性僵死文档。若在异构环境/全新边界条件下再次复现，或在后续开发学习中找到更优解，本板块将实时原地追加记录，并同步更新知识图谱关系。

### 8.1 异构条件复现追踪 (Reproduction Records)
#### 记录 1（复现日期: 2026-09-05）
- **触发边界与环境**: 当会话文档正文的代码块中包含 Markdown 语法示例（即在 ````markdown 围栏内写了 ## 2. 验收结果 示例标题）时
- **现场报错与现象**: 虽然行首符合 ## 前缀，但这属于代码块内部的示例演示，状态机依然发生了误跳转！
- **机理深入差异分析**: 纯基于单行前缀未能感知 Markdown 代码围栏（Code Fence）作用域。代码围栏内部的一切标题均为纯字面量，严禁泄漏为解析控制符

### 8.2 更优解迭代演进 (Superior Solution Evolution)
#### 演进版本 1（演进日期: 2026-09-05）
- **演进驱动原因**: 升级为具备代码围栏感知能力（Code-Fence Aware）的双状态词法分词器，彻底根除嵌套示例代码穿透
- **更优解设计思路**: 在逐行扫描循环中增加 in_code_block 布尔状态追踪，凡遇到 ```` 围栏行时即时翻转；处于围栏内的所有标题行仅作为纯字面量收集，绝对不触发章节道岔跳转
- **更优解生产核心代码**:
```python
# scripts/jhoc_worklog.py (更优解演进)
in_code_block = False
current_section = ""

for line in content.splitlines():
    line_str = line.strip()
    
    # 步骤 0: 代码围栏作用域识别（围栏内严禁触发状态道岔）
    if line_str.startswith("```"):
        in_code_block = not in_code_block
        continue
    if in_code_block:
        continue # 围栏内的示例标题纯作字面量忽略

    # 步骤 1: 真实二级标题道岔判断
    if line_str.startswith("## "):
        header = line_str.lstrip("#").strip()
        if "修改清单" in header: current_section = "changes"
        elif "验收结果" in header or "测试" in header: current_section = "tests"
        continue
```
- **更优解代码比对 (Unified Diff)**:
```diff
+  # 增加 Markdown 代码围栏（Code Fence）作用域安全锁
+  if line_str.startswith("```"):
+      in_code_block = not in_code_block
+      continue
+  if in_code_block:
+      continue  # [FIX]: 代码块内部的所有标题仅为字面数据，严禁触发状态机道岔
+
   if line_str.startswith("## "):
       header = line_str.lstrip("#").strip()
```
- **进阶思考心智模型**:
  - 解析任何标记语言都必须具备作用域感知（Scope Awareness）；
  - 围栏（Fence/Quote/Literal）内部的文本永远是纯数据字面量，严禁穿透并泄漏为上层的语法控制指令。

