from aiogram.filters.callback_data import CallbackData


class ModelCallback(CallbackData, prefix="model"):
    model_id: str


class EffortCallback(CallbackData, prefix="effort"):
    level: str


class ModeCallback(CallbackData, prefix="mode"):
    mode: str


class WorkspaceCallback(CallbackData, prefix="ws"):
    token: str


class BrowseDirCallback(CallbackData, prefix="dir"):
    token: str


class FileInfoCallback(CallbackData, prefix="file"):
    name: str


class SessionCallback(CallbackData, prefix="sess"):
    action: str  # "select", "delete", "new", "menu"
    session_id: str


class NavigationCallback(CallbackData, prefix="nav"):
    target: str  # "effort_menu", "tree_explorer", "quota_info", "cancel_execution"
