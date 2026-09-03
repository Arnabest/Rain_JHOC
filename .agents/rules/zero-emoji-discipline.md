# 零 Emoji 表情与字符纯度铁律 (Zero-Emoji Discipline)

> **核心法则**：严禁在任何模型对话输出、思考过程、Markdown 文档、代码注释、脚本日志与配置文件中使用任何 Emoji 表情符号（如各类装饰球、手指箭头、表情面孔等非 BMP 字符）。（反思 LESSON #148、LESSON #208）

---

## 1. 为什么坚决禁止 Emoji？

1. **环境编码破坏**：Windows 控制台与部分 CLI 工具在 GBK 编码或部分 UTF-8 管道下，输出非 BMP 高位 Unicode 字符会直接抛出 `UnicodeEncodeError: 'gbk' codec can't encode character` 崩溃；
2. **多模型/跨进程反序列化隐患**：Emoji 字符在跨平台转写、TTS 语音合成或管道重定向时容易造成乱码、无效截断或解析失败；
3. **专业度与反浮夸**：JHOC 追求工业级冷峻、纯净与极简自持，严禁使用各类花哨的装饰性表情包。

---

## 2. 替代标记对照表 (Flat Clean Text)

| 原违规 Emoji 倾向 | 强制替代的 Flat 规范文本 |
| :--- | :--- |
| 绿球 / 绿勾 | `[PASS]` 或 `[OK]` |
| 黄球 / 警告 | `[WARN]` 或 `[PENDING]` |
| 红球 / 红叉 | `[FAIL]` 或 `[DENIED]` |
| 指示手指 / 箭头 | `->` 或 `[LINK]` |
| 闪光灯 / 火花 / 灯泡 | `[NOTE]` 或 `[KEY]` |
| 锁头 / 盾牌 | `[GUARD]` 或 `[SECURITY]` |

---

## 3. 门禁与红线约束

- **零容忍**：凡在输出、注释、日志或文档中出现任何 Emoji，一律视为严重破坏字符纯度的契约违规；
- **全链路过滤**：编写或更新任何 Markdown 文件后，强制检查是否存在高位 Emoji 字符，违规者立即清除。
