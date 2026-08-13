# ADR 0009: Skill 沙箱采用 stdlib AST 静态门（零依赖）

Status: Accepted
Date: 2026-08-14

## Context

P2-2 需要为 skill 子进程增加"代码级"沙箱，防止恶意或被攻破的 skill 执行危险操作。
迭代 Spec 原提案是 RestrictedPython（第三方包）或 OS 级隔离（Job Object / chroot）。
两者都违反零依赖基线：

- RestrictedPython 是第三方运行时，引入即破"核心 stdlib-only"约束。
- OS 级隔离（Windows Job Object 需 ctypes 系统调用、Unix chroot 需 root 权限）依赖
  平台特权能力，跨平台行为不一致，且无法仅用 stdlib 移植层完全覆盖。

同时 P0-3 已落地两层防线：子进程隔离（`subprocess` + 进程树强杀）与 env 白名单
（`_build_safe_env` 只透传非敏感变量）。真正的安全边界在这两层，而非代码层。

## Decision

新增 `hermes/workbench/sandbox.py`，用 stdlib `ast` 对 Python entrypoint 做**尽力而为的
静态门**：

- 拒绝危险 import（subprocess/socket/ctypes/importlib/pickle 等）；
- 拒绝危险调用（eval/exec/compile/`__import__`、`os.system`、`shutil.rmtree`、
  `os.remove` 等）；
- 拒绝写入模式的 `open()`（`w`/`a`/`x`/`+`）；
- 拒绝越权 dunder 属性访问（`__subclasses__`/`__globals__`/`__builtins__` 等）。

静态门默认开启（opt-out：frontmatter `sandbox: false`），Python entrypoint 在运行前
分析，命中即拒绝执行。Shell/Node entrypoint 不做静态分析，仍依赖 P0-3 两层隔离。

## Consequences

- **正面**：零新增依赖；对危险模式有前置拦截；默认开启覆盖所有 Python skill；跨平台一致。
- **负面 / tradeoff**：静态分析无法穷举（`getattr(os, "system")`、混淆 import 可绕过），
  因此它**不是安全边界**，只作为 P0-3 之上的纵深防御；dunder 拒绝可能误伤合法反射代码，
  但 skill entrypoint 极少需要。
- **后续约束**：新增 deny 项必须保持保守（只拒绝"看得见"的危险模式），并补对应测试；
  若未来需要强隔离，应另立 ADR 引入 OS 级机制，而非在此扩大静态规则。
