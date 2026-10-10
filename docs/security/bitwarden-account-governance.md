# 项目账号与 Bitwarden 分类保管说明

本说明适用于 `stevenge-godscode/deer-flow`，记录用户要求的账号分类、安全保管与最小权限边界。文档存在不表示任何账号、Organization、collection、token 或权限已创建，也不表示真实隔离已验证。实际环境、批准记录和 Bitwarden 标识须由用户确认；未知信息保留 UNKNOWN。个人 `manage-project-credentials` Skill 由公共个人技能维护方负责，项目不重复安装。

## 分类与登记

项目标识为 `deer-flow`。账号按 `项目 / 环境 / 用途` 标识；环境至少区分 DEV、STAGING、PROD 和共享管理，用途区分人工登录、应用服务、CI/服务器、应急管理。分类名称只描述用途，不授予权限。完整登记放在用户指定且已确认的安全 vault；项目 Git 文档仅保存模板、批准引用和获准公开的脱敏标识。

| 字段 | 登记要求 |
| --- | --- |
| 项目、环境、用途 | 明确单一责任仓库和真实使用环境；不得复制生产身份给 DEV |
| 注册 email、用户名、URL | 完整值保留在安全条目；代码/聊天只用批准的账号别名和无秘密 URL |
| owner、批准记录 | 责任人、审批人、批准对象和范围；不得以推测补齐 |
| 权限范围 | 精确项目/collection/资源/操作、只读或写入、有效期和使用主体 |
| 轮换与撤销 | 负责人、周期、到期时间、服务侧撤销步骤和核验记录 |
| Bitwarden 条目 ID | 用户确认的条目标识；在未确认或不宜公开时写 UNKNOWN/安全引用 |
| vault、Organization、collection | 用户确认的目标；未知写 UNKNOWN，不猜名称、ID或默认组织 |

不得把实际密码、API key、token、私钥、会话材料、恢复码写入聊天、代码、Issue/PR、日志或示例配置。用户本人在安全界面输入、提交和解锁；助手不得要求把主密码或凭据粘贴进聊天，也不得读取密码文件来补齐登记。

## 最小权限与私人 vault 隔离

- 保留用户私人 vault；不把整个人 vault 开放给自动化。日常自动化使用 Organization 内独立受限成员，只授权所需项目与环境的 collection，默认只读；成员、组织和 collection 均须先由用户确认。实际新建/邀请/分享/授权不属于本文档任务。
- folder 只用于分类，不是权限边界；筛选界面、嵌套名称和手机批准都不能缩小该登录身份能访问的范围。collection 的可见范围必须由真实成员权限验证。[官方 folder 与 collection 说明](https://bitwarden.com/help/folders/)、[collection 范围](https://bitwarden.com/help/about-collections/)。
- 只读仍允许使用和读取获授权条目，不等于秘密不可提取；不能靠“隐藏密码”替代成员与 collection 隔离。高权限 admin、组织管理、PROD 写入和应急恢复身份不放进日常自动化 collection。多 collection 归属、组授权和角色继承须核对实际有效权限。[官方 collection 权限](https://bitwarden.com/help/collection-permissions/)。
- Bitwarden 个人 API key 是个人账号的 CLI 登录凭据，不是只限某个 collection 的 token；不拿主账号个人 API key 作为项目最小权限方案。[官方个人 API key](https://bitwarden.com/help/personal-api-key/)。
- 手机批准只批准登录认证，不限定登录后所见条目。用户先核对主体、设备和指纹短语，后续可见范围由该主体有效权限决定。[官方设备登录](https://bitwarden.com/help/log-in-with-device/)。
- CI/服务器可评估 Secrets Manager 的独立 machine account，按项目/环境只赋予必要的读取权限；先确认套餐、可用功能、项目权限、到期/撤销机制。Password Manager collection 与 Secrets Manager project 是不同授权对象，不能混用或声称个人 API key 已变成项目 token。[官方 machine account](https://bitwarden.com/help/machine-accounts/)、[Secrets Manager 套餐](https://bitwarden.com/help/secrets-manager-plans/)。本文档不创建 machine account 或 access token。

## 注册、授权、轮换与撤销

注册新账号，或新建/扩大持久权限，必须由用户对具体服务、注册 email/主体、项目/环境/用途、权限范围、owner、费用与期限作明确确认。用户“始终允许”的泛化偏好不能写成注册或持久权限的豁免。已有授权只在其明确对象和范围内有效。

确认后仍由用户本人安全录入、提交与解锁；只记录非秘密的批准和状态证据。未知目标、套餐或有效权限保持 UNKNOWN，停止依赖该未知的实际操作，不自动建立组织/collection、账号、分享、token 或备用凭据。

轮换/撤销需另有对应授权。撤销保险库共享不等于撤销外部服务已颁发的 API key，也不能收回已复制的秘密；按服务侧撤销流程、停用对应主体、轮换必要秘密和核验使用记录分别处理，证据只记录状态与安全引用。

## 接入检查与非目标

接入时仅添加本说明，并在已有根 AGENTS 中增加短引用；无 AGENTS 时仅向已有 README 添加普通导航，均缺失时报告入口缺口，不新建指令文件，在全新独立分支记录准确 base/head、作用文件和 Draft PR。验证相对链接、必填元数据模板、最小权限约束和纯文档差异。不得把文件存在当作实际 Bitwarden 隔离已配置或所有项目已覆盖的证据；覆盖和缺口须逐项目报告。
