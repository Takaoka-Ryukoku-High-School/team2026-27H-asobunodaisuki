import calendar
from contextlib import closing
import json
import sqlite3
from datetime import date
from pathlib import Path
from uuid import uuid4

import flet as ft


DATABASE_FILE = Path.home() / ".daily_note_tasks.sqlite3"
LEGACY_DATA_FILE = Path.home() / ".daily_note_tasks.json"
GREEN = "#2E6654"
GREEN_LIGHT = "#E2EDE5"
PAPER = "#F6F5EF"
INK = "#202C2A"
MUTED = "#77807B"
CORAL = "#CF6048"


def initialize_storage():
    with closing(sqlite3.connect(DATABASE_FILE, timeout=10)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    done INTEGER NOT NULL,
                    date TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY)"
            )
            migrated = connection.execute(
                "SELECT 1 FROM app_metadata WHERE key = 'legacy_json_migrated'"
            ).fetchone()
            if migrated:
                return

            try:
                legacy_tasks = json.loads(LEGACY_DATA_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                legacy_tasks = []

            records = []
            if isinstance(legacy_tasks, list):
                for task in reversed(legacy_tasks):
                    if not (
                        isinstance(task, dict)
                        and isinstance(task.get("id"), str)
                        and isinstance(task.get("text"), str)
                        and isinstance(task.get("done"), bool)
                    ):
                        continue
                    try:
                        task_date = date.fromisoformat(task.get("date", ""))
                    except (TypeError, ValueError):
                        task_date = date.today()
                    records.append(
                        (task["id"], task["text"], int(task["done"]), task_date.isoformat())
                    )

            connection.executemany(
                "INSERT OR IGNORE INTO tasks (id, text, done, date) VALUES (?, ?, ?, ?)",
                records,
            )
            connection.execute(
                "INSERT INTO app_metadata (key) VALUES ('legacy_json_migrated')"
            )


def load_tasks():
    with closing(sqlite3.connect(DATABASE_FILE, timeout=10)) as connection:
        rows = connection.execute(
            "SELECT id, text, done, date FROM tasks ORDER BY rowid DESC"
        ).fetchall()
    return [
        {"id": task_id, "text": text, "done": bool(done), "date": task_date}
        for task_id, text, done, task_date in rows
    ]


def insert_task_record(task):
    with closing(sqlite3.connect(DATABASE_FILE, timeout=10)) as connection:
        with connection:
            connection.execute(
                "INSERT INTO tasks (id, text, done, date) VALUES (?, ?, ?, ?)",
                (task["id"], task["text"], int(task["done"]), task["date"]),
            )


def toggle_task_record(task_id):
    with closing(sqlite3.connect(DATABASE_FILE, timeout=10)) as connection:
        with connection:
            connection.execute(
                "UPDATE tasks SET done = 1 - done WHERE id = ?", (task_id,)
            )


def delete_task_record(task_id):
    with closing(sqlite3.connect(DATABASE_FILE, timeout=10)) as connection:
        with connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def delete_completed_records(task_date):
    with closing(sqlite3.connect(DATABASE_FILE, timeout=10)) as connection:
        with connection:
            connection.execute(
                "DELETE FROM tasks WHERE date = ? AND done = 1", (task_date,)
            )


def main(page: ft.Page):
    initialize_storage()
    page.title = "今日の段取り | ToDo"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = PAPER
    page.padding = 24
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.scroll = ft.ScrollMode.AUTO

    tasks = load_tasks()
    current_filter = "all"
    selected_date = date.today()

    task_input = ft.TextField(
        hint_text="この日にすることは？",
        expand=True,
        autofocus=True,
        border_radius=6,
        border_color="#D4DED5",
        focused_border_color=GREEN,
        bgcolor="#FFFEFA",
        text_size=15,
        on_submit=lambda event: add_task(event),
    )
    task_list = ft.Column(spacing=0)
    task_count = ft.Text(color=MUTED, size=12)
    progress_label = ft.Text(color=MUTED, size=11)
    month_label = ft.Text(size=16, color=INK, weight=ft.FontWeight.W_600)
    month_summary = ft.Text(color=MUTED, size=11)
    selected_date_label = ft.Text(color=INK, size=13, weight=ft.FontWeight.W_600)
    calendar_grid = ft.Column(spacing=4)
    clear_done_button = ft.TextButton(
        "この日の完了予定を削除",
        icon=ft.Icons.DELETE_OUTLINE,
        style=ft.ButtonStyle(color=CORAL),
        on_click=lambda event: clear_done(event),
    )
    filter_buttons = {}

    def publish_updates():
        tasks[:] = load_tasks()
        render()
        page.pubsub.send_others("shared-tasks-updated")

    def set_filter(value):
        nonlocal current_filter
        current_filter = value
        render()

    def add_task(event):
        nonlocal current_filter
        text = task_input.value.strip()
        if not text:
            return
        insert_task_record(
            {
                "id": str(uuid4()),
                "text": text,
                "done": False,
                "date": selected_date.isoformat(),
            }
        )
        task_input.value = ""
        current_filter = "all"
        publish_updates()

    def shift_month(offset):
        nonlocal selected_date
        month_index = selected_date.year * 12 + selected_date.month - 1 + offset
        year, month_index = divmod(month_index, 12)
        month = month_index + 1
        day = min(selected_date.day, calendar.monthrange(year, month)[1])
        selected_date = date(year, month, day)
        render()

    def select_date(value):
        nonlocal selected_date
        selected_date = value
        render()

    def toggle_task(task_id):
        toggle_task_record(task_id)
        publish_updates()

    def delete_task(task_id):
        delete_task_record(task_id)
        publish_updates()

    def clear_done(event):
        delete_completed_records(selected_date.isoformat())
        publish_updates()

    def render():
        month_key = selected_date.strftime("%Y-%m")
        month_tasks = [task for task in tasks if task["date"].startswith(month_key)]
        selected_day = selected_date.isoformat()
        day_tasks = [task for task in month_tasks if task["date"] == selected_day]
        visible_tasks = [
            task
            for task in day_tasks
            if (
                current_filter == "all"
                or (current_filter == "active" and not task["done"])
                or (current_filter == "done" and task["done"])
            )
        ]
        remaining = sum(not task["done"] for task in day_tasks)
        completed = sum(task["done"] for task in month_tasks)
        month_label.value = selected_date.strftime("%Y年%m月")
        month_summary.value = f"今月の予定 {len(month_tasks)} 件"
        weekday = ["月", "火", "水", "木", "金", "土", "日"][selected_date.weekday()]
        selected_date_label.value = f"{selected_date.month}月{selected_date.day}日 ({weekday}) の予定"
        task_count.value = f"未完了 {remaining} 件"
        progress_label.value = (
            f"今月 {completed} / {len(month_tasks)} 件 完了"
            if month_tasks
            else "この月の予定はまだありません"
        )
        clear_done_button.visible = any(
            task["date"] == selected_day and task["done"] for task in tasks
        )

        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        calendar_rows = [
            ft.Row(
                [
                    ft.Container(
                        content=ft.Text(day, size=10, color=MUTED, text_align=ft.TextAlign.CENTER),
                        expand=1,
                        alignment=ft.Alignment.CENTER,
                    )
                    for day in weekdays
                ],
                spacing=4,
            )
        ]
        first_weekday, days_in_month = calendar.monthrange(
            selected_date.year, selected_date.month
        )
        cells = [None] * first_weekday + list(range(1, days_in_month + 1))
        cells.extend([None] * ((-len(cells)) % 7))
        for start in range(0, len(cells), 7):
            week = []
            for day in cells[start : start + 7]:
                if day is None:
                    week.append(ft.Container(expand=1, height=48))
                    continue
                cell_date = date(selected_date.year, selected_date.month, day)
                day_count = sum(task["date"] == cell_date.isoformat() for task in tasks)
                is_selected = cell_date == selected_date
                week.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    str(day),
                                    size=12,
                                    color=GREEN if is_selected else INK,
                                    weight=ft.FontWeight.BOLD if is_selected else None,
                                ),
                                ft.Text(f"{day_count}件" if day_count else " ", size=9, color=MUTED),
                            ],
                            spacing=0,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        expand=1,
                        height=48,
                        alignment=ft.Alignment.CENTER,
                        bgcolor=GREEN_LIGHT if is_selected else "#FFFEFA",
                        border=ft.Border.all(1, GREEN if is_selected else "#E3E3D9"),
                        border_radius=4,
                        on_click=lambda event, value=cell_date: select_date(value),
                        tooltip=cell_date.strftime("%-m月%-d日"),
                    )
                )
            calendar_rows.append(ft.Row(week, spacing=4))
        calendar_grid.controls = calendar_rows

        for key, button in filter_buttons.items():
            selected = key == current_filter
            button.style = ft.ButtonStyle(
                color=GREEN if selected else MUTED,
                bgcolor=GREEN_LIGHT if selected else "transparent",
                shape=ft.RoundedRectangleBorder(radius=4),
            )

        rows = []
        for task in visible_tasks:
            checkbox = ft.Checkbox(
                value=task["done"],
                label=task["text"],
                expand=True,
                active_color=GREEN,
                label_style=ft.TextStyle(
                    color="#929992" if task["done"] else INK,
                    decoration=ft.TextDecoration.LINE_THROUGH if task["done"] else None,
                    size=14,
                ),
                on_change=lambda event, task_id=task["id"]: toggle_task(task_id),
            )
            delete_button = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE,
                icon_color=MUTED,
                tooltip=f"「{task['text']}」を削除",
                on_click=lambda event, task_id=task["id"]: delete_task(task_id),
            )
            rows.extend(
                [
                    ft.Row([checkbox, delete_button], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Divider(height=1, thickness=1, color="#DEDFD5"),
                ]
            )

        if not visible_tasks:
            empty_text = (
                "未完了の予定はありません。いい調子！"
                if current_filter == "active" and day_tasks
                else "完了したタスクはまだありません。"
                if current_filter == "done" and day_tasks
                else "この日にする予定を追加しましょう。"
            )
            rows = [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("○", size=24, color="#9A7629", text_align=ft.TextAlign.CENTER),
                            ft.Text(empty_text, size=13, color=MUTED, text_align=ft.TextAlign.CENTER),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    padding=32,
                    alignment=ft.Alignment.CENTER,
                )
            ]

        task_list.controls = rows
        page.update()

    def on_shared_update(message):
        if message != "shared-tasks-updated":
            return
        tasks[:] = load_tasks()
        render()

    for key, label in (("all", "すべて"), ("active", "未完了"), ("done", "完了")):
        filter_buttons[key] = ft.TextButton(
            label,
            on_click=lambda event, value=key: set_filter(value),
        )

    today = ft.Text(
        date.today().strftime("%Y年%m月%d日"),
        size=12,
        color=MUTED,
    )
    composer = ft.Row(
        [
            task_input,
            ft.Button(
                "追加  ＋",
                on_click=add_task,
                bgcolor=GREEN,
                color="white",
                height=48,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5)),
            ),
        ],
        spacing=10,
    )

    content = ft.Column(
        [
            ft.Row(
                [
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text("日", color="white", size=15, weight=ft.FontWeight.BOLD),
                                width=28,
                                height=28,
                                bgcolor=GREEN,
                                border_radius=14,
                                alignment=ft.Alignment.CENTER,
                            ),
                            ft.Text("DAILY NOTE", size=12, color=GREEN, weight=ft.FontWeight.BOLD),
                        ],
                        spacing=10,
                    ),
                    today,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Column(
                [
                    ft.Text("今日の段取り", size=38, color=INK, weight=ft.FontWeight.W_600),
                    ft.Text("ひとつずつ、進めていこう。", size=13, color=MUTED),
                ],
                spacing=4,
            ),
            ft.Container(
                content=ft.Column(
                    [
                                ft.Row(
                                    [
                                        ft.IconButton(
                                            ft.Icons.CHEVRON_LEFT,
                                            tooltip="前の月",
                                            on_click=lambda event: shift_month(-1),
                                        ),
                                        month_label,
                                        ft.IconButton(
                                            ft.Icons.CHEVRON_RIGHT,
                                            tooltip="次の月",
                                            on_click=lambda event: shift_month(1),
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.CENTER,
                                    spacing=8,
                                ),
                                calendar_grid,
                                month_summary,
                            ],
                            spacing=8,
                        ),
                        padding=ft.Padding(left=18, right=18, top=12, bottom=12),
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                selected_date_label,
                                composer,
                            ],
                            spacing=8,
                        ),
                        padding=18,
                        bgcolor=GREEN_LIGHT,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                        ft.Container(
                            content=ft.Row(
                                [ft.Row(list(filter_buttons.values()), spacing=0), task_count],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            padding=ft.Padding(left=18, right=18, top=8, bottom=8),
                            border=ft.Border.only(bottom=ft.BorderSide(1, "#DEDFD5")),
                        ),
                        ft.Container(content=task_list, padding=ft.Padding.symmetric(horizontal=18)),
                        ft.Container(
                            content=ft.Row(
                                [progress_label, clear_done_button],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            padding=ft.Padding(left=18, right=18, top=8, bottom=8),
                            border=ft.Border.only(top=ft.BorderSide(1, "#DEDFD5")),
                        ),
                    ],
                            spacing=0,
                ),
                width=700,
                bgcolor="#FFFEFA",
                border=ft.Border.all(1, "#E3E3D9"),
                border_radius=8,
                shadow=ft.BoxShadow(blur_radius=28, color="#182D2314", offset=ft.Offset(0, 10)),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            ),
        ],
        width=700,
        spacing=28,
    )

    app_container = ft.Container(content=content, width=700, padding=ft.Padding.only(top=18, bottom=32))
    workspace_card = content.controls[2]

    def resize_page(event):
        viewport_width = page.width or 748
        page.padding = 12 if viewport_width < 520 else 24
        content_width = min(700, max(272, viewport_width - page.padding * 2))
        app_container.width = content_width
        content.width = content_width
        workspace_card.width = content_width
        page.update()

    page.on_resize = resize_page
    page.add(app_container)
    page.pubsub.subscribe(on_shared_update)
    render()


if __name__ == "__main__":
    ft.run(main, view=ft.AppView.WEB_BROWSER)