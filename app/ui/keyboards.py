import os
import sys
from typing import Any

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.ui.callbacks import (
    BrowseDirCallback,
    EffortCallback,
    FileInfoCallback,
    FileUploadCallback,
    ModeCallback,
    ModelCallback,
    NavigationCallback,
    SessionCallback,
    WorkspaceCallback,
)


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Compact 2x3 Grid Dashboard Keyboard for clean mobile screen layout"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🤖 Model & Effort"),
                KeyboardButton(text="💬 Active Session"),
            ],
            [
                KeyboardButton(text="▶️ Resume / Session"),
                KeyboardButton(text="🔄 New Session"),
            ],
            [
                KeyboardButton(text="📂 Workspace & Tree"),
                KeyboardButton(text="📊 Status & Usage"),
            ],
        ],
        resize_keyboard=True,
    )


def get_model_keyboard(
    cur_model: str,
    models: list[dict[str, Any]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for m in models:
        m_id = m["id"]
        name = m.get("displayName") or m_id
        is_active = " ✅ (Active)" if m_id == cur_model else ""
        builder.row(
            InlineKeyboardButton(
                text=f"🤖 {name}{is_active}",
                callback_data=ModelCallback(model_id=m_id).pack(),
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text="🎯 Change Effort Level (/effort)",
            callback_data=NavigationCallback(target="effort_menu").pack(),
        ),
    )
    return builder.as_markup()


def get_effort_keyboard(cur_effort: str) -> InlineKeyboardMarkup:
    efforts = [
        ("low", "🟢 Low - Fast Execution"),
        ("medium", "🟡 Medium - Balanced"),
        ("high", "🔴 High - Deep Reasoning & Force Fix"),
    ]
    builder = InlineKeyboardBuilder()
    for eff_key, eff_name in efforts:
        is_active = " ✅ (Active)" if eff_key == cur_effort else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{eff_name}{is_active}",
                callback_data=EffortCallback(level=eff_key).pack(),
            ),
        )
    return builder.as_markup()


def get_mode_keyboard(cur_mode: str) -> InlineKeyboardMarkup:
    modes = [
        ("accept-edits", "🛠️ Accept Edits Mode (Directly Edit Code)"),
        ("plan", "📋 Plan Mode (Step-by-Step Planning)"),
    ]
    builder = InlineKeyboardBuilder()
    for mode_key, mode_name in modes:
        is_active = " ✅ (Active)" if mode_key == cur_mode else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{mode_name}{is_active}",
                callback_data=ModeCallback(mode=mode_key).pack(),
            ),
        )
    return builder.as_markup()


def get_workspace_keyboard(
    available_dirs: list[str],
    cur_ws: str,
    path_encoder: Any,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in available_dirs:
        folder_name = os.path.basename(d) or d
        is_active = " (Active)" if os.path.abspath(d) == os.path.abspath(cur_ws) else ""
        token = path_encoder(d)
        builder.row(
            InlineKeyboardButton(
                text=f"📁 {folder_name}{is_active}",
                callback_data=WorkspaceCallback(token=token).pack(),
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text="🌳 Interactive File Explorer (/tree)",
            callback_data=NavigationCallback(target="tree_explorer").pack(),
        ),
    )
    return builder.as_markup()


def _build_windows_drive_buttons(
    norm_path: str,
    path_encoder: Any,
) -> list[InlineKeyboardButton]:
    if sys.platform != "win32":
        return []

    import string

    available_drives = [
        f"{letter}:\\"
        for letter in string.ascii_uppercase
        if os.path.exists(f"{letter}:\\")
    ]
    if len(available_drives) <= 1:
        return []

    norm_lower = os.path.abspath(norm_path).lower()
    return [
        InlineKeyboardButton(
            text=f"💽 {drv[:2]}",
            callback_data=BrowseDirCallback(
                token=path_encoder(drv),
                page=1,
            ).pack(),
        )
        for drv in available_drives
        if os.path.abspath(drv).lower() != norm_lower
    ][:4]


def get_tree_keyboard(
    norm_path: str,
    cur_ws: str,
    dirs: list[str],
    files: list[tuple[str, float]],
    path_encoder: Any,
    page: int = 1,
    total_pages: int = 1,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    parent = os.path.dirname(norm_path)
    if parent and parent != norm_path:
        up_token = path_encoder(parent)
        builder.row(
            InlineKeyboardButton(
                text="⬆️ .. (Parent Directory)",
                callback_data=BrowseDirCallback(token=up_token, page=1).pack(),
            ),
        )

    # Windows drive selector when multiple drives exist
    drive_buttons = _build_windows_drive_buttons(norm_path, path_encoder)
    if drive_buttons:
        builder.row(*drive_buttons)

    if os.path.abspath(norm_path) != os.path.abspath(cur_ws):
        set_token = path_encoder(norm_path)
        builder.row(
            InlineKeyboardButton(
                text="📍 Set as AI Target Workspace",
                callback_data=WorkspaceCallback(token=set_token).pack(),
            ),
        )

    for d in dirs:
        full_d = os.path.join(norm_path, d)
        token = path_encoder(full_d)
        builder.row(
            InlineKeyboardButton(
                text=f"📁 {d}/",
                callback_data=BrowseDirCallback(token=token, page=1).pack(),
            ),
        )

    for fname, sz in files:
        full_f = os.path.join(norm_path, fname)
        token = path_encoder(full_f)
        builder.row(
            InlineKeyboardButton(
                text=f"📄 {fname} ({sz} KB)",
                callback_data=FileInfoCallback(token=token, page=page).pack(),
            ),
        )

    if total_pages > 1:
        curr_token = path_encoder(norm_path)
        nav_row: list[InlineKeyboardButton] = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️ Prev",
                    callback_data=BrowseDirCallback(
                        token=curr_token,
                        page=page - 1,
                    ).pack(),
                ),
            )
        nav_row.append(
            InlineKeyboardButton(
                text=f"📄 {page}/{total_pages}",
                callback_data=BrowseDirCallback(
                    token=curr_token,
                    page=page,
                ).pack(),
            ),
        )
        if page < total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    text="Next ➡️",
                    callback_data=BrowseDirCallback(
                        token=curr_token,
                        page=page + 1,
                    ).pack(),
                ),
            )
        builder.row(*nav_row)

    return builder.as_markup()


def get_file_details_keyboard(
    file_token: str,
    dir_token: str,
    page: int = 1,
    can_upload: bool = True,
    uploaded: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_upload:
        btn_text = "📥 Upload Again" if uploaded else "📥 Upload to Chat"
        builder.row(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=FileUploadCallback(token=file_token, page=page).pack(),
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text="🔙 Back to Files",
            callback_data=BrowseDirCallback(token=dir_token, page=page).pack(),
        ),
    )
    return builder.as_markup()


def get_session_picker_keyboard(
    sessions: list[dict[str, Any]],
    active_conv: str | None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sess in sessions:
        is_active = " (Active)" if active_conv == sess["id"] else ""
        btn_text = f"💬 {sess['title']} ({sess['date']}){is_active}"
        cb_data = SessionCallback(action="select", session_id=sess["id"]).pack()
        builder.row(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=cb_data,
            ),
        )
    builder.row(
        InlineKeyboardButton(
            text="🔄 New Session (/new)",
            callback_data=SessionCallback(action="new", session_id="new").pack(),
        ),
    )
    return builder.as_markup()


def get_session_delete_keyboard(
    sessions: list[dict[str, Any]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sess in sessions:
        btn_text = f"🗑️ Delete: {sess['title']} ({sess['date']})"
        cb_data = SessionCallback(action="delete", session_id=sess["id"]).pack()
        builder.row(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=cb_data,
            ),
        )
    return builder.as_markup()


def get_session_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="▶️ Select Another Session",
            callback_data=NavigationCallback(target="select_session_menu").pack(),
        ),
        InlineKeyboardButton(
            text="🔄 New Session (/new)",
            callback_data=SessionCallback(action="new", session_id="new").pack(),
        ),
    )
    return builder.as_markup()


def get_action_bar_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🌳 Browse Files",
            callback_data=NavigationCallback(target="tree_explorer").pack(),
        ),
        InlineKeyboardButton(
            text="📊 Live Quotas",
            callback_data=NavigationCallback(target="quota_info").pack(),
        ),
    )
    return builder.as_markup()


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🛑 Cancel / Stop",
            callback_data=NavigationCallback(target="cancel_execution").pack(),
        ),
    )
    return builder.as_markup()
