# 账号反馈聊天与访客单次收件

2026-10-24 用户批准：反馈升级为双方有昵称、持续往返的聊天；未登录者保持简单提交。这里的访客“不记录”按不绑定账号、不创建聊天或本机管理记录处理，正文仍进入私有管理员收件箱。旧管理链接保持兼容，不按联系方式推断账号。

## 交付切片

1. 增量迁移、账号所有权、昵称与读水位、分页与原接口兼容；先验证真实隔离数据库的权限/幂等/撤回用例。
2. 账号“我的反馈”与后台聊天工作台；移动端列表和会话切换，保留原收件审核页。
3. 首页按身份分流：访客仅内存中保留失败意图，成功后不写浏览器管理记录；账号提交后进入会话。旧链接可显式关联账号，关联后撤销旧链接权限，旧匿名消息不冒充账号历史消息。
4. 定向与完整验证、文档同步、审查和既有 main 自动发布；生产仅只读和合成浏览器验收，不向真实用户发消息。

## 冻结接口

路径均带 `/api/v1`；账号接口只接受有效网站会话，不允许 OAuth grants 或请求正文指定所有者。旧 `/feedback` 及管理链接接口保持原契约。新账号提交走 `/me/feedback`。

账号新客户端附带可选 `X-Feedback-Account` 匹配护栏；与真实会话不符返回409 `ACCOUNT_CHANGED`。该字段不能授权或选择所有者，后台仍只相信网站会话；用于避免跨标签页切号期间旧提交或关联误归属新账号。

| 方法与路径 | 输入 | 返回 |
| --- | --- | --- |
| GET `/me/feedback` | cursor、limit默认20最大50、status可选 | FeedbackThreadPage |
| POST `/me/feedback` | 现有 FeedbackInput，不传 managementToken；稳定 Idempotency-Key | 现有 FeedbackReceipt；所有者由会话确定 |
| GET `/me/feedback/{id}/messages` | 与现有管理员消息分页一致 | 扩展后的 FeedbackConversationResponse |
| POST `/me/feedback/{id}/messages` | `{body}`，稳定 Idempotency-Key | 现有 FeedbackMessageReceipt |
| POST `/me/feedback/{id}/read` | `{messageId}` | 204 |
| POST `/me/feedback/{id}/withdrawal` | `{}` | 现有 FeedbackManagement |
| POST `/me/feedback/{id}/claim` | `{managementToken}` | FeedbackThread |
| GET `/admin/feedback/conversations` | cursor、limit默认20最大50、status可选 | FeedbackThreadPage，包含账号和访客反馈 |
| POST `/admin/feedback/{id}/read` | `{messageId}` | 204 |

账号读取/写入其他人或不存在的反馈统一404；旧匿名凭据仍统一403。claim仅接受原管理凭据、只允许认领未绑定记录，已属本人可安全重试，其他所有者不能认领。撤回/垃圾状态不能认领或继续回复。不得凭邮箱认领。账号发送仍沿用原父行锁、持久额度、发送意图摘要和幂等收据，重放返回当前处理状态，不重复扣额或审计。

## DTO

- `FeedbackParticipant = {kind: "ACCOUNT" | "GUEST", displayName: string}`。昵称来自账号；访客为“访客”；开发者显示“玄司开发者”，不以管理员邮箱作昵称。
- `FeedbackThread = {id,title,preview,status,moderationStatus,participant,createdAt,updatedAt,unreadCount,canReply,lastMessage: FeedbackMessage | null}`。preview为正文的至多160字符，撤回后清空；分页不返回内部账号编号或管理凭据。
- `FeedbackThreadPage = {data: FeedbackThread[], meta:{nextCursor:string|null}}`。
- 现有 `FeedbackMessage` 增加可选 `authorName`。新账号消息保存发送时昵称，管理员保存公开开发者称呼；旧匿名消息没有作者名时仍显示“访客”。
- 现有 `FeedbackConversation` 增加可选 `participant`、`submitterName`、`createdAt`、`unreadCount`。新账号初始问题保存提交时昵称，旧匿名初始问题不被认领回填昵称。可选 `contact` 仅管理员读取返回，用户响应不包含联系方式。

## 读水位与自动同步

每条反馈分别保存管理员、所有者单调递增的 `(created_at,id)` 已读水位。`messageId` 必须指向该反馈的真实消息；初始问题以反馈自身id代表。已读请求只确认实际显示到的消息，不能使用服务器当前时间一次标记未看到的新消息。管理员未读包含初始问题和用户消息；用户未读只计算开发者消息，撤回时为零。

会话列表仅在可见页面按5秒自动更新；选中会话只有版本/最后消息变化时刷新消息内容，发送期间暂停读取，隐藏标签页暂停自动请求，恢复时立即同步。用户正在看更早消息时不强制跳到末尾；只有实际看到最新消息才提交读水位。发送失败保留正文和请求编号，可重试同意图或显式改写。

## 页面与边界

- 新聊天工作台 `/admin/feedback/chat`，管理员导航优先进入此页；原 `/admin/feedback` 保留为“收件与审核”，公开审核和撤回清理仍可完成。
- 账号入口 `/dashboard/feedback`，可用 `?id=<反馈UUID>` 直接打开自己会话。电脑双栏，手机列表/详情切换，均保留真实加载、空、错误和重试状态。
- 新访客表单不生成/保存 managementToken，不写 localStorage，不显示访客聊天记录；默认私有且不开放新访客公开许可。登录状态未确认或读取失败时不擅自按访客提交。
- 401/403立即清理私人会话数据与缓存，404只关闭失效会话；账号切换、取消及迟到响应不得恢复旧正文。所有消息均按纯文本渲染。
- 本轮不发送消息邮件提醒，不增加外部服务或依赖；注册/密码恢复邮件独立保留。
