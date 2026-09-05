# 06 - 账户配额生命线、被动物理熔断与 Harness 盲区错题集 (Quota Fuse & Harness Circuit Breaker Lessons)

> 本目录归纳自跨目录工具物理迁移与高负荷排障实战中，关于 Agent 主动巡检失职、认知隧道压迫、以及外部 Harness 存在解释器失效与缺乏被动阻断机制的核心教训，作为 JHOC 全生命周期配额防御的终身免疫规约。

---

## 1. LESSON #403: 排障认知隧道压制配额生命线巡检与 Harness 被动熔断断链

### 1.1 事故症状
- 在上一轮集中执行跨目录文件物理迁移（将业务工具/技能从 `D:\AI Desktop Agent` 清除并迁移归属至 `F:\verse`）、38 个工具动态依赖修复以及三端测试验证时，模型注意力被单机代码与模块报错排查完全霸占；
- 模型未能在每轮回复的后置验收动作中主动执行 `.agents/skills/token-stats/SKILL.md` 规定的配额巡检命令（`py -3 scripts/jhoc_token_stats.py`），导致配额跌穿 8% 临界线（跌至 2% / 1%），却未在第一时间拉响警报；
- 同时外部 Harness 在日常多轮交互中未能实施被动物理拦截，导致系统失去了自动化兜底防线，形成“规则写在文档里，但运行时被旁路”的治理盲点。

### 1.2 双重根因剖析

#### 认知层根因：排障认知隧道 (Troubleshooting Cognitive Tunneling)
1. **注意力被单机局部报错垄断**：高密度的报错排查会极大压缩自回归大模型的上下文感知窗口，自律型防御动作被本能地当成“低优先级杂项”推迟甚至遗忘；
2. **度量守恒与 Rule 0 被动化**：误以为配额只是“任务完成后的记账统计”，未将账户配额视为整个执行生命周期的“不可再生物理氧气瓶”；
3. **盲目依赖模型自律的制度原罪**：把系统生命线寄托在“模型每轮自觉自检”上，违背了 Rule 2 零信任模型边界法则。

#### 物理层根因：外部 Harness 四大断链与旁路点
1. **Windows 解释器静默失效**：`.agents/hooks.json` 配置的裸 `python` 命令在 Windows 宿主环境下因应用商店别名冲突直接退出（Exit Code 1），导致 IDE 生命周期钩子未实际执行；
2. **Payload 键名不匹配导致会话脱节**：`jhoc_pre_inject.py` 读取的是 `payload.get("session_id")`，而 Antigravity 官方协议发送的是驼峰命名的 `conversationId`，导致多账户 Connect-RPC 绑定失效；
3. **PreToolUse 物理门禁严重裸奔**：`jhoc_hook_gate.py` 作为写文件与跑命令的必经咽喉，拦截了 Emoji、敏感路径和破坏性命令，但**完全没有接入配额熔断**，只要模型继续调用工具就一路放行；
4. **开工与停机门禁非强制阻断**：`jhoc_kaigong.py` 遇到低配额仅输出警告未中止开工；`jhoc_stop_guard.py` 对配额耗尽下的未决交接未做物理阻断。

### 1.3 终身防御规约 (Rule 2 Physical Circuit Breaker)
1. **配额即生命线，绝不可寄托于模型自觉**：
   - 彻底将配额熔断防线移出模型主观意识，固化至外部 Harness 物理门禁；
2. **PreToolUse 物理硬熔断 (Fail-Closed)**：
   - 在 `scripts/jhoc_hook_gate.py` 中强制挂载配额探针；
   - 无论何时，凡当前会话账户 5小时或每周额度 `<= 8.0%` 时，除“落盘保命与交接归档白名单（`implementation_plan.md`、`memory/`、`docs/lessons/`、`scripts/jhoc_shougong.py`、`scripts/jhoc_token_stats.py`、`git`）”外，**物理拦截 (`decision: deny`) 一切工具调用**；
3. **开工门禁与停机守卫硬闭环**：
   - `jhoc_kaigong.py`：额度 `<= 8.0%` 时无 `--force` 严禁启动新任务 (`exit 1`)；
   - `jhoc_stop_guard.py`：额度 `<= 8.0%` 且未落盘最新交接包时阻断停机 (`decision: continue`)；
4. **宿主环境防御性命令契约**：
   - Windows 环境下所有 Hook 与自动化脚本必须显式使用 `py -3` 或跨平台可靠解析器，杜绝因裸 `python` 导致静默失败。

---

## 2. LESSON #404: 跨子目录与多工作区 Hook 挂载脱靶、存量文件假闭环与异常静默放行

### 2.1 事故症状
- 在上一轮集中开发 TTS/STT 统一基座基础设施插件（`audio-voice-infra`）时，当前账户 `tewafjlkbvcx3567@gmail.com` 配额跌至 1%（远低于 8% 临界线）；
- 模型未感知到额度告急，继续调用 `replace_file_content` 修改 `realtimeVoiceService.ts`，外部 Harness 未做任何阻断，直到用户手动发送“额度告警，先暂停，保存任务进度”进行人工打断；
- 赛后实机回放显示：Python 熔断算法逻辑完全正常，接收到该会话 ID 时能准确返回 `decision: deny`，但系统整体未产生任何防御动作。

### 2.2 根因三联拆解 (Threefold Root Causes)

1. **跨工作区根目录盲区 (Root Mismatch)**：
   - Antigravity IDE 仅在 `<WorkspaceRoot>/.agents/hooks.json` 发现工作区级钩子；
   - 任务在子目录 `d:\AI Desktop Agent\desktop_client` 执行，该目录下未创建 `.agents/hooks.json`；
   - 且当时全局配置根目录 `C:\Users\arnag\.gemini\config\hooks.json` 为空，导致 IDE 在该子目录下执行任何工具调用时压根未挂载任何 Hook。
2. **存量交接文件假闭环 (Stale Handoff Bypass)**：
   - `jhoc_stop_guard.py` 仅用 `if not handoff_file.is_file()` 判断是否需要阻止停机；
   - 由于磁盘上常驻有历史任务遗留的 `memory/handoff-latest.json`，静态存在性检查被历史旧文件直接穿透，未验证当次交接时效性与告警标记。
3. **静默吞异常违背 Fail-Closed (Silent Exception Swallowing)**：
   - `jhoc_hook_gate.py` 中配额探测存在 `except Exception: pass`，若在子目录或特殊环境下引发路径解析或模块导入偶发异常，会静默放行一切写入。

### 2.3 防御落地与物理加固 (Hardened Architecture)

1. **全局 Customization Root 物理注入**：
   - 在 `C:\Users\arnag\.gemini\config\hooks.json` 写入全局钩子配置，强制采用 `py -3 "G:/JHOC/scripts/..."` 绝对路径调用；
   - 确保无论 Agent 在 `G:\JHOC`、`d:\AI Desktop Agent`、`desktop_client` 还是 `f:\verse` 开窗，全局 PreInvocation、PreToolUse、Stop 均物理生效；
2. **工作区级多点冗余部署**：
   - 同步修复 `d:\AI Desktop Agent\.agents\hooks.json`，并将配置下发至 `d:\AI Desktop Agent\desktop_client\.agents\hooks.json`；
3. **停机守卫时效与状态新鲜度双校验**：
   - `jhoc_stop_guard.py` 改造为：配额告急时除检查文件存在外，强制校验修改时间在 30 分钟以内（`time.time() - mtime < 1800`）且显式包含 `quota_status.is_alert: true`；
4. **异常黑匣子审计归档**：
   - `jhoc_hook_gate.py` 配额异常由静默吞并改为写入 `p19-blackbox.jsonl` 警告痕迹，消除隐形旁路。

---

## 3. LESSON #405: 钩子执行工作目录 (CWD) 错位、优先级覆盖遮蔽与全域漏改断链

### 3.1 事故症状
- 在会话 `cc648c41-aecb-4945-bffb-b2bb3972b8b6` 中，绑定账户 `millandagarland@gmail.com` 配额持续消耗并跌穿 8% 临界阈值，直至 5 小时额度彻底归零 (0%)；
- 模型在此过程中连续执行了 945 次 `run_command` 与 76 次 `write_to_file`，外部 Harness 配额熔断未产生任何阻断，直到谷歌 API 触发 429 Resource Overloaded 报错；
- 黑匣子审计 `p19-blackbox.jsonl` 显示该会话期间来自 IDE 内部钩子的调用拦截记录为 0。

### 3.2 根因三联深层剖析

1. **钩子执行宿主 CWD 错位致命崩溃 (CWD Mismatch)**：
   - Antigravity 官方生命周期规约明确规定：**Hook 脚本执行时的 Working Directory（CWD）强制锁定为 `hooks.json` 所在目录**；
   - `G:\JHOC\.agents\hooks.json` 内部配置为相对路径 `"command": "py -3 scripts/jhoc_hook_gate.py"`；
   - 执行时 Python 在 `G:\JHOC\.agents\scripts\` 下寻找目标文件，触发物理报错 `[Errno 2] No such file or directory` (Exit Code 2)；
   - stdout 无任何 JSON 决策输出，IDE 钩子宿主判定执行异常后触发 **Fail-Open (失败静默放行)**，导致熔断守卫彻底裸奔。
2. **加载优先级法则反向遮蔽 (Priority Shadowing)**：
   - 虽然此前在全局配置 `~/.gemini/config/hooks.json` 中配置了绝对路径，但根据优先级规则：`Workspace Project (.agents/)` > `Global Discovery`；
   - 工作区内存在且未修复的同名钩子 `"jhoc-gate"` 强行覆盖并遮蔽了全局正确的钩子。
3. **加固操作遗漏母库盲区 (Incomplete Propagation)**：
   - 上一轮加固修改了全局、`D:\AI Desktop Agent` 及 `desktop_client` 的 `hooks.json`，但遗漏了母库 `G:\JHOC\.agents\hooks.json`，导致在母库开窗时全面失效。
4. **探针执行时长逼近 5 秒超时阈值 (Timeout Tightness)**：
   - Connect-RPC 双进程探测在冷启动或高负荷时偶发耗时 2.5s~3.5s，5 秒超时容错冗余不足。

### 3.3 终身免疫规约 (Rule 2 Hardened Invariants)

1. **全域 Hook 绝对路径铁律 (Zero Relative Path in Hooks)**：
   - 严禁在任何 `hooks.json` 中使用假定为根目录的相对路径；
   - 所有 Hook 命令必须统一使用绝对路径与双引号包裹：`py -3 "G:/JHOC/scripts/..."`；
2. **全域多工作区同步对齐**：
   - 保持 `G:\JHOC\.agents\hooks.json`、`C:\Users\arnag\.gemini\config\hooks.json`、`D:\AI Desktop Agent\.agents\hooks.json`、`desktop_client\.agents\hooks.json` 严格 100% 结构一致；
3. **超时冗余放宽至 10 秒**：
   - 将全部 PreInvocation、PreToolUse、Stop 钩子超时统一调整为 10 秒，消除因多进程排队或高负荷引发的超时旁路。

