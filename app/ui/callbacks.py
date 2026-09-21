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
    page: int = 1


class FileInfoCallback(CallbackData, prefix="file"):
    token: str
    page: int = 1


class FileUploadCallback(CallbackData, prefix="fup"):
    token: str
    page: int = 1


class SessionCallback(CallbackData, prefix="sess"):
    action: str  # "select", "delete", "new", "menu"
    session_id: str


class NavigationCallback(CallbackData, prefix="nav"):
    target: str  # "effort_menu", "tree_explorer", "quota_info", "cancel_execution"


class SaveToWorkspaceCallback(CallbackData, prefix="ws_save"):
    token: str
