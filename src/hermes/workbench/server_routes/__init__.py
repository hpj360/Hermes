"""Route-domain mixins for the workbench HTTP API.

server.py 的 DashboardHandler 按 路由域 拆分（原 1726 行巨型文件）：

- ``base``       — 公共请求/响应 helpers（RouteBase）
- ``system``     — health / metrics / dashboard / trace / SSE
- ``skills``     — skill 列表 / 详情 / 同步运行
- ``memory``     — facts / episodes / 检索三通道 / profile / MemOS
- ``todos``      — todos CRUD / hand-off / capture inbox / notes summary
- ``tasks``      — task 创建+运行 / 列表 / 取消
- ``kb``         — GitHub sync / IMA 知识库 / IMA 笔记 / hermes-kb proxy
- ``scheduler``  — jobs / projects / triggers / asset-sync / job SSE
- ``loops``      — loop 列表 / 派发轨迹 / 离线审计

路由表（_ROUTES）与 dispatch/auth/HTTP server 工厂仍住在
``hermes.workbench.server``——那里是 API surface 的单一事实来源。
"""
from hermes.workbench.server_routes.base import RouteBase
from hermes.workbench.server_routes.kb import KbRoutes
from hermes.workbench.server_routes.loops import LoopRoutes
from hermes.workbench.server_routes.memory import MemoryRoutes
from hermes.workbench.server_routes.scheduler import SchedulerRoutes
from hermes.workbench.server_routes.skills import SkillsRoutes
from hermes.workbench.server_routes.system import SystemRoutes
from hermes.workbench.server_routes.tasks import TasksRoutes
from hermes.workbench.server_routes.todos import TodosRoutes

__all__ = [
    "RouteBase",
    "SystemRoutes",
    "SkillsRoutes",
    "MemoryRoutes",
    "TodosRoutes",
    "TasksRoutes",
    "KbRoutes",
    "SchedulerRoutes",
    "LoopRoutes",
]
