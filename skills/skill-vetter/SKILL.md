---
name: "skill-vetter"
description: "Vets skills for quality and security. Invoke when users want to verify or validate skills before installation."
---

# Skill Vetter

This skill helps vet skills for quality and security before installation.

## When to Use

- When users want to verify the quality of a skill
- When users want to check the security of a skill
- When users are unsure about installing a skill

## How to Use

1. The skill will analyze the skill's code and metadata
2. It will check for potential security issues
3. It will evaluate the skill's quality and functionality
4. It will provide a report with recommendations

## Features

- Security analysis
- Quality assessment
- Functionality verification
- Recommendations for improvement

## Related skills（边界声明）

- **find-skills**: 候选 skill **发现**。本 skill 在 find-skills 输出后接管做**审查**。生命周期：`find-skills → skill-vetter → skill-manager install`。
- **skill-manager**: 已安装 skill 的**管理**（list/update/remove）。本 skill 关注**安装前**的安全/质量，与 skill-manager 的运行时管理不重叠。
- **skill-creator**: skill 的**开发**。本 skill 评估 skill 质量时复用 skill-creator 的评测框架（evals、benchmark、description optimization）。
- **code-review**: 代码双轴审查。本 skill 关注 skill 整体的 security/quality，code-review 关注一次 diff 的 Standards/Spec 合规。两者粒度不同。
