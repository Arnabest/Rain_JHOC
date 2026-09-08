# 02 - 进程、通信与并发死锁错题集 (Process & Concurrency Lessons)

> 本目录归纳自 `D:\AI Box` 历史错题本中关于 Windows 子进程派生、跨进程 Socket 通信、并发死锁与超时竞争的核心教训。

---

## 1. LESSON #90: Socket 超时轮询后引发 `OSError: cannot read from timed out object`
- **症状**：Agent Bus 或外部 Provider 长连接适配器在空闲轮询后反复崩溃，抛出 `OSError: cannot read from timed out object`。
- **根因**：`socket.makefile().readline()` 与 `socket.settimeout()` 混用；在一次超时后，CPython 的文件对象包装器损坏进入不可读状态，后序轮询连续抛出异常。
- **规约**：
  - 对需要反复超时轮询的 JSONL socket，一律使用原始 `socket.recv()` + 自建行缓冲区；
  - 严禁对会反复 `settimeout()` 的 socket 使用 `makefile().readline()`。

---

## 2. LESSON #95: 后台脚本在 Windows 桌面循环弹出黑框控制台
- **症状**：明明使用了 `pythonw.exe` 启动后台服务，桌面依然周期性连续闪出多个 cmd/powershell 黑色控制台窗口，打扰用户操作。
- **根因**：`pythonw` 只隐藏父 Python 进程；当脚本内调用 `git.exe`、`powershell`、`wmic`、`taskkill` 等命令行子进程且未传隐藏标志时，Windows 默认会为其创建可见控制台。
- **规约**：
  - 所有后台脚本的 `subprocess.run` 或 `Popen` 必须显式传入：
    `creationflags=subprocess.CREATE_NO_WINDOW`，或配置 `startupinfo = subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESHOWWINDOW, wShowWindow=subprocess.SW_HIDE)`。

---

## 3. LESSON #172: 跨进程/跨线程透传活动对象引发死锁与脏状态
- **症状**：调度器与执行器在多线程或跨进程交互中，任务状态突发静默死锁或数据竞态损坏。
- **根因**：违背了物理隔离原则，在不同工作单元间直接传递内存中的活动 Python 对象引用（Live Object Reference），导致锁泄漏与生命周期混乱。
- **规约**：
  - 严格遵循 JHOC 宪法第 5 条：**进程间通信绝不透传内部活动对象引用**；
  - 一切交互必须严格序列化为无状态的 JSON / 强类型数据包，经由 SQLite WAL 或标准管道传递。
