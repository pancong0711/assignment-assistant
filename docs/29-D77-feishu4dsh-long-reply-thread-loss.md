# D77 诊断：feishu4dsh 长回复被 SDK 分片后，后续分片落到聊天根（不在话题内）

> 日期：2026-10-12
> 环境：生产入口 `~/.dsh/profiles/feishu4dsh`，插件路径 `/home/bot2603/feishu4dsh`（v0.12.2）
> 配置：`sessionScope: chat-thread`；入站批合并修复 `batch.text.delayMs = 0` 已在位
> 结论：**已定位到确定性根因**，不是飞书话题能力问题，也不是入站 `thread_id` 丢失；
> 问题在出站长文本分片：SDK 自动分片时只有第一片带 `replyTo`，后续片走 `message.create` 落到聊天根。
> 交付：请把本文件复制/转交到 `feishu4dsh` 开发工作区处理（本工作区只读，无法直接写入该仓库）。

---

## 1. 现象

飞书话题内，dsh 的回答/过程信息中：短回复正常进话题；**长回复的后半段会以独立消息落到聊天根**。
用户观感：很多消息没有回复到当前话题中。

## 2. 证据

### 2.1 飞书 API：同一轮长回复，首片在话题内、后续片在聊天根

用 `im/v1/messages` 分别查询：

- `container_id_type=thread`，`container_id=omt_<THREAD_ID>`（当前话题）
- `container_id_type=chat`，`container_id=oc_<CHAT_ID>`（群/聊天根）

结果：

- 在 thread 列表中：
  - 用户消息：`thread_id=omt_...`、`root_id=om_...root`、`parent_id=om_...root`；
  - dsh 的卡片/短文本：`thread_id=omt_...`、`root_id=om_...root`、`parent_id=<触发它的用户消息 id>`；
  - 超长回复只有**第一片**在 thread 列表。
- 在 chat 根列表中出现 21 条 `app_id/post` 消息：
  - `thread_id=null`、`root_id=null`、`parent_id=null`；
  - 正文长度约 1.5k–3.4k 字符；
  - 正是一轮超长回复被按 3500 字符切片后的第 2..N 片。

### 2.2 SDK 源码：`sendMarkdown` 只给第一片传 `replyTo`

`@larksuiteoapi/node-sdk` 的 `LarkChannel.sendMarkdown`：

```js
const chunks = splitWithCodeFences(md, this.chunkLimit); // DEFAULT_CHUNK_LIMIT = 3500
for (let i = 0; i < chunks.length; i++) {
  const id = await this.sendOneWithFallback({
    to, idType, msgType: 'post', content: post,
    replyTo: i === 0 ? opts.replyTo : undefined,   // ← 只有第 0 片带 replyTo
    replyInThread: opts.replyInThread,
  });
}
```

`rawSend` 行为：

- `args.replyTo` 存在 → `im.v1.message.reply(...)`，才会带 `reply_in_thread`；
- `args.replyTo` 不存在 → `im.v1.message.create(...)`，普通发消息，**落聊天根**。

`sendText` 同样：

```js
replyTo: i === 0 ? opts.replyTo : undefined,
```

只要 `port.send({ markdown })` / `{ text }` 内容超过 SDK 的 `textChunkLimit`（默认 3500），
第 2 片起必然丢话题锚点。

### 2.3 插件内触发路径

`feishu4dsh` 的以下路径最终会调用 `port.send(..., { markdown: <长文本> })`：

- `safeSend()`：命令/短回复/错误提示，通常短；
- `openReplyStream()` 的 fallback：`sendFallback()`、流打开失败、卡片退化等；
- 卡片预算溢出：
  `reply body exceeds the card budget (24000 chars); ... full text follows as one message`
  （2026-10-12 19:24:33 journal 有此 report）随后 `sendFallback(buffer)`；
  当 `buffer` 超过 3500，SDK 自动切片，后续片落聊天根。
- 当卡片正文溢出且 `buffer` 为空时，`fallbackText()` 可能返回 reasoning panel 内容，
  这解释了为什么聊天根会看到“思考内容”形态的长文本分片。

## 3. 根因结论

**feishu4dsh 对超长文本直接 `port.send({markdown})`，依赖 SDK 自动分片；
SDK 分片只给第一片传 `replyTo`，后续片走 `message.create` → 落到聊天根。**

与 `sessionScope`、入站 `thread_id`、批合并、`binding.replyTo` 恢复均无关；
入站链路经本次 API 验证是正确的（用户消息 `parent/root/thread_id` 完整）。

## 4. 修复建议（给接手 dsh 的实施方案）

### 4.1 首选：桥接层自行分片，所有分片共用同一话题锚

在 `feishu4dsh` 的发送封装里增加“带锚分片发送”，不要对长文本直接调用 SDK 的 `sendMarkdown(text)`：

```ts
async function sendLongMarkdown(port, chatId, text, options) {
  const chunks = splitPreservingCodeFences(text, MAX_CHUNK); // 小于 SDK 3500，或复用 SDK 分片函数
  for (const chunk of chunks) {
    await port.send(chatId, { markdown: chunk }, options);   // options = { replyTo: anchor, replyInThread: true }
  }
}
```

要点：

- 每一片都传 `{ replyTo: anchor, replyInThread: true }`；
- 分片边界不得破坏代码块/表格；可复用/复制 SDK 的 `splitWithCodeFences`；
- `safeSend`、`sendFallback`、卡片溢出 fallback 所有长文本路径统一走该封装。

### 4.2 备选：给 SDK 打补丁

把 `sendMarkdown`/`sendText` 中 `replyTo: i === 0 ? opts.replyTo : undefined` 改为每片都传 `opts.replyTo`。
不推荐直接改 `node_modules`；如要做需 pin 版本并管理补丁。

### 4.3 产品形态

- 超长回复优先“卡片 + 附件/文件”承载，或拆成多条**带锚**回复；
- 设置插件级正文字数上限 + 分片发送，不要把 50k 字符一次性交给 SDK；
- `fallbackText()` 在卡片退化时不要把完整 reasoning panel 当普通 markdown 群发，可改成摘要或同样带锚分片。

## 5. 验收/回归建议

新增 `tests/bridge.spec.ts`（FakePort 记录每次 `send` 的 options）：

1. 构造 > `textChunkLimit` 的回复文本，断言：
   - FakePort 收到多次 `send`；
   - 每一次 options 都为 `{ replyTo: 'm_anchor', replyInThread: true }`，无一次缺锚；
2. 卡片预算溢出 + 长 fallback，断言每一片都带同一锚；
3. 短回复回归：仍一次、带锚。

真机验收：

- 在话题内触发一次 > 5000 字符的回复；
- 用 thread API 确认所有分片 `thread_id` 均等于当前话题、`parent_id` 合理；
- chat 根列表不再出现该轮回复的后半段碎片。

## 6. 相关代码位置

- 生产插件：`/home/bot2603/feishu4dsh`
  - 出站封装：`src/bridge.ts`（`safeSend` / `openReplyStream` / `openCardReplyStream` / `sendFallback`）
  - 入站/锚点：`handleInboundMessage`、`safeOpenStream`、`renderSessionEvent` 的 `user/message` 分支
- SDK：`node_modules/@larksuiteoapi/node-sdk/lib/index.js`
  - `DEFAULT_CHUNK_LIMIT = 3500`
  - `sendMarkdown` / `sendText` 的 `replyTo: i === 0 ? ... : undefined`
  - `rawSend` 的 `reply` vs `create` 分支
