#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Requires Python 3.10+

# 核心功能依赖
import argparse
import datetime
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# 类型参数注解
from typing import Literal

# 检测并尝试自动安装第三方库
try:
    # 检测时顺便导入 rich.traceback 渲染异常栈, 后面不用再导入
    from rich.traceback import install

    install()
except ImportError:
    print("\nInstalling required package: rich...\n")
    try:
        # macOS 中 python/python3 以及 pip/pip3 命令混用
        # 所以用 python/python3 -m pip install 的形式
        # 避免直接调用 pip/pip3 导致命令名错误
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "rich",
                "-q",
                "-U",
                "--break-system-packages",
            ],
            check=True,
        )
    except Exception:
        print("\nInstall failed, please install it manually.\n")
        sys.exit()

# GUI 界面依赖 (tkinter 内置库版本需高于 9.0)
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# CLI 界面依赖 (第三方库)
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

# 定义程序标题和版本, 获取运行环境版本信息
OS = platform.system()
APP_TITLE = f"🧹 Junk Cleaner V250404 on {OS}"
RUNTIME_VERSION = f"Python {sys.version.split()[0]} / tkinter {tk.TkVersion}"

# 根据不同系统, 指定默认扫描路径
DEFAULT_SCAN_PATH = {"Darwin": Path("/Users"), "Windows": Path("C:/Users")}.get(
    OS, Path("/home")
)

# 定义垃圾文件/文件夹的匹配规则
JUNK_FILES = {
    "names": (
        ".DS_Store",
        ".viminfo",
        ".localized",
        ".sharkgi",
        ".lesshst",
        ".wget-hsts",
        ".mailcap",
        ".mime.types",
        ".python_history",
        ".bash_history",
        ".zsh_history",
        "fish_history",
        "Logs.db",
        "history.db",
        "Thumbs.db",
        "desktop.ini",
        re.compile(r"\.zcompdump-.*"),
    ),
    "extensions": (
        ".log",
        ".tmp",
        ".temp",
        ".cache",
        ".swp",
        ".dmp",
        ".dump",
        ".crash",
        ".$$$",
        ".~",
    ),
    "folders": (
        "log",
        "logs",
        "tmp",
        "temp",
        ".pyinspect",
        ".idlerc",
        ".thumbnails",
        ".fseventsd",
        ".Spotlight-V100",
        ".zsh_sessions",
        ".Trash",
        "CallHistoryDB",
        "CallHistoryTransactions",
        "BtLog",
        "Crash Logs",
        "Plugin Crash Logs",
        "com.tencent.bugly",
        "CrashesLogBuffer",
        "CrashReporter",
        "Photo Booth Library",
        "Videos Library.tvlibrary",
        "Media.localized",
        "Automatically Add to Music.localized",
        "$RECYCLE.BIN",
        "System Volume Information",
        "Windows.old",
        "PerfLogs",
        "xl_sdks_kvstorage",
        "网易云音乐",
        re.compile(r"Cache", re.IGNORECASE),
        re.compile(r".*\.savedState$"),
    ),
}

# 定义不同操作系统需要扫描的临时目录路径
SYSTEM_TEMP_DIRS = {
    "Darwin": (
        Path("/var/log"),
        Path("/var/logs"),
        Path("/private/var/log"),
        Path("/private/var/logs"),
        Path("/Library/Logs"),
    ),
    "Windows": (
        Path("C:/Windows/Temp"),
        Path("C:/Windows/Logs"),
    ),
    "Linux": (Path("/var/log"),),
}.get(OS, [])


class Core:
    """核心功能类, 处理扫描和清理的逻辑"""

    def __init__(self) -> None:
        """初始化核心功能类

        创建用于中断操作的事件、消息队列和线程变量
        """
        self.abort_event = threading.Event()
        self.queue = queue.Queue()
        self.thread = None

    def action(
        self,
        action_type: Literal["scan", "clean"],
        path_or_items: Path | list[Path],
        delay: bool = True,
    ) -> None:
        """启动扫描或清理操作

        Args:
            action_type (Literal["scan", "clean"]): 操作类型, "scan" 或 "clean"
            path_or_items (Path | list[Path]): 扫描路径或需要清理的文件列表
            delay (bool, optional): 是否在清理时添加延迟, 默认为 True
        """
        self.abort_event.clear()
        target = self._scanner if action_type == "scan" else self._cleaner
        self.thread = threading.Thread(
            target=target,
            args=(path_or_items,) if action_type == "scan" else (path_or_items, delay),
        )
        self.thread.start()

    def _scanner(self, scan_path: Path) -> None:
        """扫描指定路径下的垃圾文件/文件夹

        根据预定义的模式匹配规则, 递归扫描目录下的文件和文件夹
        将扫描结果通过消息队列发送给界面线程

        Args:
            scan_path (Path): 待扫描的根路径
        """
        # 构建需要扫描的路径列表
        paths_to_scan = set()
        paths_to_scan.add(scan_path)

        # 添加系统临时目录
        for temp_dir in SYSTEM_TEMP_DIRS:
            if temp_dir.exists() and not any(
                str(temp_dir).startswith(str(p)) or str(p).startswith(str(temp_dir))
                for p in paths_to_scan
            ):
                paths_to_scan.add(temp_dir)

        total_size = 0  # 扫描到的垃圾文件/文件夹总大小
        file_count = 0  # 扫描到的垃圾文件/文件夹总数量
        processed_paths = set()  # 用于记录已处理的路径

        for root_path in (
            p
            for base_path in paths_to_scan
            for p in base_path.rglob("*", case_sensitive=False)
        ):

            # 检查是否触发中断
            if self.abort_event.is_set():
                return

            try:
                # 如果当前目录是符号链接, 或者其父目录已被处理过, 就跳过
                if root_path.is_symlink() or any(
                    str(parent) in processed_paths for parent in root_path.parents
                ):
                    continue

                # 检查目录
                if root_path.is_dir():
                    if self.matches_patterns(root_path.name, JUNK_FILES["folders"]):
                        size = size = self.get_dir_size(root_path)
                        modified = time.strftime(
                            "%Y-%m-%d %H:%M:%S",
                            time.localtime(root_path.stat().st_mtime),
                        )
                        self.queue.put(
                            (
                                "found_item",
                                (root_path, "Folder", self.format_size(size), modified),
                            )
                        )
                        total_size += size
                        file_count += 1
                        processed_paths.add(str(root_path))  # 记录已处理的目录路径

                # 检查文件
                elif root_path.is_file():
                    # 同时检查文件名和扩展名 (都转换为小写进行比较)
                    if self.matches_patterns(
                        root_path.name, JUNK_FILES["names"]
                    ) or root_path.suffix.lower() in [
                        ext.lower() for ext in JUNK_FILES["extensions"]
                    ]:
                        size = root_path.stat().st_size
                        modified = time.strftime(
                            "%Y-%m-%d %H:%M:%S",
                            time.localtime(root_path.stat().st_mtime),
                        )
                        self.queue.put(
                            (
                                "found_item",
                                (root_path, "File", self.format_size(size), modified),
                            )
                        )
                        total_size += size
                        file_count += 1

            except (OSError, PermissionError):
                continue

        if not self.abort_event.is_set():
            self.queue.put(("scan_done", (self.format_size(total_size), file_count)))

    def _cleaner(self, items: list[Path], delay: bool = True) -> None:
        """清理指定的文件和目录

        Args:
            items (list[Path]): 待清理的文件和目录路径列表
            delay (bool, optional): 是否延迟清理, 默认为 True
        """
        total = len(items)  # 总项目数
        cleaned = 0  # 已清理数量 (已处理的数量, 无论成功还是失败)
        cleaned_size = 0  # 已清理大小
        target_duration = 0.5  # 目标总清理时间 (秒)
        delay = target_duration / total  # 每个项目的延迟时间
        success_count = 0  # 成功清理的数量 (只在实际删除成功时累加)

        for path in items:
            if self.abort_event.is_set():
                break

            if path.exists():
                try:
                    if path.is_file():
                        size = path.stat().st_size
                        path.unlink(missing_ok=True)
                        if delay:
                            time.sleep(delay)
                    else:
                        size = self.get_dir_size(path)
                        shutil.rmtree(path, ignore_errors=True)
                        if delay:
                            time.sleep(delay)
                    cleaned_size += size
                    success_count += 1
                except (OSError, PermissionError) as e:
                    self.queue.put(("clean_error", (path, str(e))))
                    size = 0
                cleaned += 1
                self.queue.put(("clean_progress", (cleaned, total)))

        if not self.abort_event.is_set():
            self.queue.put(
                ("clean_done", (self.format_size(cleaned_size), success_count, total))
            )

    @staticmethod
    def matches_patterns(item: str, patterns: tuple[str | re.Pattern, ...]) -> bool:
        """检查项目是否匹配任何模式

        Args:
            item (str): 要检查的文件名或文件夹名
            patterns (tuple[str | re.Pattern, ...]): 包含字符串和正则表达式对象的模式元组

        Returns:
            bool: 如果项目匹配任何模式返回 True, 否则返回 False
        """
        for pattern in patterns:
            if isinstance(pattern, str):
                # 字符串模式: 不区分大小写的完全匹配
                if pattern.lower() == item.lower():
                    return True
            else:
                # 正则表达式模式: 使用 search 方法匹配
                if pattern.search(item):
                    return True
        return False

    @staticmethod
    def get_dir_size(path: Path) -> int:
        """计算目录总大小

        Args:
            path (Path): 待计算大小的目录路径

        Returns:
            int: 目录下所有文件的大小总和 (字节)
        """
        return sum(
            f.stat().st_size
            for f in path.rglob("*")
            if f.is_file() and not f.is_symlink()
        )

    @staticmethod
    def format_size(size: int) -> str:
        """格式化文件大小

        将字节大小转换为易读的单位格式

        Args:
            size (int): 文件大小 (字节)

        Returns:
            str: 格式化后的大小字符串, 如 "1.5 MB"
        """
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                break
            size /= 1024
        return f"{size:.1f} {unit}"

    @staticmethod
    def now_time() -> str:
        """返回格式化的当前时间字符串

        Returns:
            str: 格式为 '[HH:MM:SS] ' 的时间字符串
        """
        return f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "


class GUI:
    """GUI界面类, 基于 tkinter 创建图形用户界面"""

    def __init__(self, path: Path) -> None:
        """初始化 GUI 界面

        Args:
            path (Path): 初始扫描路径
        """
        self.core = Core()  # 核心功能类实例
        self.scan_path = path  # 要扫描的路径
        self.search_results = []  # 搜索结果列表
        self.is_scanning = False  # 是否正在扫描

        self.root = None  # 主窗口
        self.combobox = None  # 下拉框
        self.entrybox = None  # 输入框
        self.entrybox_var = None  # 输入框变量
        self.browse_btn = None  # 浏览按钮
        self.scan_btn = None  # 扫描按钮
        self.clean_btn = None  # 清理按钮
        self.tree = None  # Treeview
        self.status_var = None  # 状态栏变量
        self.progress = None  # 进度条
        self.context_menu = None  # 右键菜单

        # 判断 tkinter 版本 (已知低于 9.0 在 macOS 上右键菜单失效)
        if tk.TkVersion < 9.0:
            messagebox.showwarning(
                "Warning",
                f"Your tkinter version too low, some functions may not work properly.\n"
                f"It is strongly recommended to upgrade the tkinter to 9.0 or higher.",
            )

        # GUI 模式下在控制台显示提示信息
        print(
            f"""\033[32m
            Tips:
             - If cleanup fails, try re-running with root.
             - Program also can be run in command line:
               $ ./{os.path.basename(__file__)} -c
            \033[0m"""
        )

        # 创建主窗口
        self.root = tk.Tk()
        self.root.geometry("1024x640")
        self.root.minsize(1024, 640)
        self.root.title(f"{APP_TITLE} - {RUNTIME_VERSION}")

        # 下拉框
        self.combobox = ttk.Combobox(
            self.root,
            values=["Path to scan", "Search in results"],
            state="readonly",
            width=12,
        )
        self.combobox.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.combobox.bind("<<ComboboxSelected>>", lambda e: self.on_combobox_change())

        # 创建 StringVar 关联输入框
        self.entrybox_var = tk.StringVar(value=self.scan_path)
        self.entrybox_var.trace_add(
            "write",
            lambda *args: (
                setattr(self, "scan_path", Path(self.entrybox_var.get()))
                if self.combobox.get() == "Path to scan"
                else self.search_in_results()
            ),
        )

        # 输入框
        self.entrybox = ttk.Entry(self.root, textvariable=self.entrybox_var)
        self.entrybox.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # 浏览按钮
        self.browse_btn = ttk.Button(
            self.root,
            text="📂 Browse",
            padding=5,
            width=8,
            command=lambda: self.entrybox_var.set(
                filedialog.askdirectory() or self.entrybox_var.get()
            ),
        )
        self.browse_btn.grid(row=0, column=2, padx=5, pady=5)

        # 扫描按钮
        self.scan_btn = ttk.Button(
            self.root, text="🔍 Scan", padding=5, width=8, command=self.toggle_scan
        )
        self.scan_btn.grid(row=0, column=3, padx=5, pady=5)

        # 清理按钮
        self.clean_btn = ttk.Button(
            self.root, text="❌ Clean", padding=5, width=8, command=self.clean
        )
        self.clean_btn.grid(row=0, column=4, padx=5, pady=5)

        # Treeview
        self.tree = ttk.Treeview(
            self.root,
            columns=("select", "kind", "path", "size", "modified", "index"),
            show="headings",
            selectmode="browse",
            displaycolumns=("select", "kind", "path", "size", "modified"),
        )

        self.tree.heading("select", text="☑")
        self.tree.heading("kind", command=lambda: self.sort("kind", False))
        self.tree.heading(
            "path", text="📂 Path", command=lambda: self.sort("path", False)
        )
        self.tree.heading(
            "size", text="📊 Size", command=lambda: self.sort("size", False)
        )
        self.tree.heading(
            "modified", text="🕒 Modified", command=lambda: self.sort("modified", False)
        )

        self.tree.column(
            "select", width=40, anchor="center", minwidth=40, stretch=False
        )
        self.tree.column("kind", width=40, anchor="e", minwidth=40, stretch=False)
        self.tree.column("path", anchor="w")
        self.tree.column(
            "size", width=100, anchor="center", minwidth=100, stretch=False
        )
        self.tree.column(
            "modified", width=150, anchor="center", minwidth=150, stretch=False
        )

        ttk.Style().configure("Treeview", rowheight=25)

        self.tree.bind("<Button-1>", self.handle_select)

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=1, column=0, columnspan=5, sticky="nsew", padx=5, pady=5)
        scrollbar.grid(row=1, column=5, sticky="ns")

        # 右键菜单
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(
            label="🔍 Open", command=lambda: self.handle_menu("open")
        )
        self.context_menu.add_command(
            label="📂 Reveal", command=lambda: self.handle_menu("reveal")
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="📋 Copy as Path", command=lambda: self.handle_menu("copy")
        )
        self.tree.bind(
            "<Button-3>",
            lambda e: (
                (
                    self.tree.selection_set(self.tree.identify_row(e.y)),
                    self.context_menu.post(e.x_root, e.y_root),
                )
                if self.tree.identify_row(e.y)
                else None
            ),
        )

        # 创建 StringVar 变量关联状态栏
        self.status_var = tk.StringVar()

        # 状态栏
        status_bar = ttk.Label(
            self.root, textvariable=self.status_var, relief="sunken", padding=(5, 2)
        )
        status_bar.grid(row=2, column=0, columnspan=6, sticky="ew")

        # 进度条
        self.progress = ttk.Progressbar(self.root, length=350)
        self.progress.grid(row=2, column=0, columnspan=6, padx=10, sticky="e")

        # 配置网格权重
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        # 界面创建好后开始首次扫描
        self.toggle_scan()

        # 启动消息循环
        self.root.mainloop()

    def toggle_scan(self) -> None:
        """切换扫描状态

        开始新的扫描或停止当前扫描
        更新界面元素状态和显示内容
        """
        if not self.is_scanning:  # 开始扫描
            # 检查路径是否存在
            if not self.scan_path.exists():
                messagebox.showerror("Error", "Path does not exist")
                return

            # 下拉框设置为扫描模式
            if self.combobox.get() != "Path to scan":
                self.combobox.set("Path to scan")
                self.entrybox_var.set(str(self.scan_path))
                self.browse_btn.configure(state="normal")

            # 设置扫描状态
            self.is_scanning = True

            # 更新按钮外观, 显示进度条动画, 更新状态栏, 清空 Treeview
            self.scan_btn.config(text="🛑 Stop")
            self.clean_btn.config(state="disabled")
            self.progress.config(mode="indeterminate")
            self.progress.start(10)
            self.status_var.set(f"{Core.now_time()}🔍 Scanning...")
            self.tree.delete(*self.tree.get_children())

            # 清空现有的搜索结果
            self.search_results = []

            # 开始扫描并检查队列
            self.core.action("scan", self.scan_path)
            self.check_queue(time.time())

        else:  # 停止扫描
            self.core.abort_event.set()
            self.status_var.set(f"{Core.now_time()}⚠️ Scan cancelled")
            self.reset_scanning_state()

    def clean(self) -> None:
        """清理选中的文件

        获取表格中选中的项目并执行清理操作
        清理前会请求用户确认
        """
        # 获取选中项目的路径列表
        selected = [
            Path(self.tree.item(item)["values"][2])
            for item in self.tree.get_children()
            if self.tree.item(item)["values"][0] == "✓"
        ]

        # 如果有选中项且用户确认, 则执行清理
        if selected and messagebox.askyesno(
            "Confirm", f"Do you want to delete {len(selected)} selected items?"
        ):
            self.clean_btn.config(state="disabled")
            self.progress.config(mode="determinate", maximum=100, value=0)
            self.core.action("clean", selected)
            self.check_queue(time.time())

    def check_queue(self, start_time: float) -> None:
        """检查消息队列并更新界面

        处理来自扫描和清理线程的消息, 更新界面显示

        Args:
            start_time (float): 操作开始时间戳
        """
        if self.core.abort_event.is_set():
            return

        try:
            while msg := self.core.queue.get_nowait():
                match msg:

                    # 扫描到垃圾文件/文件夹, 添加到 Treeview
                    case ("found_item", (path, kind, size, modified)):
                        self.tree.insert(
                            "",
                            "end",
                            values=(
                                "✓",
                                ("📄" if kind == "File" else "📁"),
                                path,
                                size,
                                modified,
                            ),
                        )

                    # 扫描完成
                    case ("scan_done", (total_size, file_count)):
                        elapsed = time.time() - start_time
                        self.reset_scanning_state()
                        self.status_var.set(
                            f"{Core.now_time()}🔍 Scan completed in {elapsed:.2f}s. "
                            f"Found {file_count} items, total size: {total_size}"
                        )
                        self.send_notification(
                            f"🔍 Scan completed in {elapsed:.2f}s",
                            f"Found {file_count} items, total size: {total_size}",
                        )
                        return

                    # 更新清理进度
                    case ("clean_progress", (cleaned, total)):
                        progress = (cleaned / total) * 100
                        self.progress["value"] = progress
                        self.status_var.set(
                            f"{Core.now_time()}🧹 Cleaning... {int(progress)}%"
                        )

                    # 遇到清理错误, 在状态栏显示错误消息
                    case ("clean_error", (path, error)):
                        self.status_var.set(f"{Core.now_time()}❌ {error}")
                        # 同时在控制台输出错误信息
                        print(f"\033[31m{error}\033[0m")

                    # 清理完成
                    case ("clean_done", (cleaned_size, success_count, total)):
                        self.status_var.set(
                            (
                                f"{Core.now_time()}✅ Cleanup completed. "
                                f"Success: {success_count}, Failed: {total-success_count}. "
                                f"Freed disk space: {cleaned_size}"
                            )
                        )
                        # 从 Treeview 中删除被选中的项目
                        for item in [
                            item
                            for item in self.tree.get_children()
                            if self.tree.item(item)["values"][0] == "✓"
                        ]:
                            self.tree.delete(item)
                        self.progress.stop()
                        self.send_notification(
                            "✅ Cleanup completed",
                            f"Successfully freed {cleaned_size} of disk space",
                        )
                        return

        except queue.Empty:
            # 如果线程仍在运行则继续检查队列
            if self.core.thread and self.core.thread.is_alive():
                self.root.after(10, self.check_queue, start_time)

        except Exception as e:
            self.reset_scanning_state()
            self.status_var.set(
                f"{Core.now_time()}❌ Error processing results: {str(e)}"
            )

    def reset_scanning_state(self) -> None:
        """重置扫描状态

        重置扫描状态和按钮, 停止进度条动画
        """
        self.is_scanning = False
        self.scan_btn.config(text="🔍 Scan", state="normal")
        self.progress.stop()
        self.update_clean_btn()

    def update_clean_btn(self) -> None:
        """更新清理按钮状态"""

        has_selected = any(
            self.tree.item(i)["values"][0] == "✓" for i in self.tree.get_children()
        )
        self.clean_btn.config(state="normal" if has_selected else "disabled")

    def sort(
        self, col: Literal["select", "path", "kind", "size", "modified"], reverse: bool
    ) -> None:
        """对表格指定列进行排序

        Args:
            col (Literal["select", "path", "kind", "size", "modified"]): 要排序的列名
            reverse (bool): 是否倒序排序
        """
        # 获取待排序项目
        items = [(k, self.tree.set(k, col)) for k in self.tree.get_children("")]

        # 根据列的类型进行排序
        if col == "size":
            units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
            items = sorted(
                items,
                key=lambda x: float(x[1].split()[0]) * units[x[1].split()[1]],
                reverse=reverse,
            )
        else:
            items = sorted(items, key=lambda x: x[1], reverse=reverse)

        # 重新排列项目
        for idx, (item, _) in enumerate(items):
            self.tree.move(item, "", idx)

        # 更新表头排序指示器
        for header in ["path", "kind", "size", "modified"]:
            text = self.tree.heading(header)["text"].rstrip(" ↑↓")
            self.tree.heading(
                header,
                text=f"{text} {('↓' if reverse else '↑') if header == col else ''}",
            )

        # 切换下次排序方向
        self.tree.heading(col, command=lambda: self.sort(col, not reverse))

    def handle_select(self, event: tk.Event) -> None:
        """处理表格的选择事件

        处理点击复选框列的事件, 实现项目的选择和取消选择功能

        Args:
            event (tk.Event): Tkinter 事件对象
        """
        # 只处理复选框列的点击, 列表为空时不处理
        if self.tree.identify_column(event.x) != "#1" or not self.tree.get_children():
            return

        # 获取点击的区域和项目
        region = self.tree.identify_region(event.x, event.y)

        if region == "heading":  # 点击表头
            first_item = self.tree.get_children()[0]
            new_state = " " if self.tree.item(first_item)["values"][0] == "✓" else "✓"

            # 更新表头状态
            self.tree.heading("select", text="☐" if new_state == " " else "☑")

            # 同步更新所有项目和搜索结果中的选中状态
            for item in self.tree.get_children():
                values = list(self.tree.item(item)["values"])
                values[0] = new_state
                self.tree.item(item, values=values)
                if idx := self.tree.set(item, "index"):
                    self.search_results[int(idx)][0] = new_state

        elif region == "cell" and (item := self.tree.identify_row(event.y)):  # 点击项目

            # 更新项目状态
            values = list(self.tree.item(item)["values"])
            values[0] = " " if values[0] == "✓" else "✓"
            self.tree.item(item, values=values)

            # 同步更新搜索结果中的选中状态
            if idx := self.tree.set(item, "index"):
                self.search_results[int(idx)][0] = values[0]

            # 更新表头状态
            all_checked = all(
                self.tree.item(i)["values"][0] == "✓" for i in self.tree.get_children()
            )
            self.tree.heading("select", text="☑" if all_checked else "☐")

        self.update_clean_btn()

    def on_combobox_change(self) -> None:
        """处理下拉框选择变化事件"""

        if self.combobox.get() == "Path to scan":
            # 恢复为扫描模式
            self.entrybox_var.set(str(self.scan_path))
            self.browse_btn.configure(state="normal")
            self.root.focus_force()

            # 清空当前显示
            self.tree.delete(*self.tree.get_children())
            for idx, values in enumerate(self.search_results):
                tree_item = self.tree.insert("", "end", values=values)
                # 保存索引以便后续更新 search_results
                self.tree.set(tree_item, "index", str(idx))

        else:
            # 切换为搜索模式前, 从 Treeview 中显示的数据初始化搜索结果
            self.search_results = [
                list(self.tree.item(item)["values"])
                for item in self.tree.get_children()
            ]
            self.entrybox_var.set("Typing keywords here")
            self.browse_btn.configure(state="disabled")
            self.entrybox.focus_set()
            self.entrybox.select_range(0, "end")

        # 清除 ComboBox 的选中状态
        self.combobox.selection_clear()

    def search_in_results(self) -> None:
        """在扫描结果中搜索

        当搜索框为空或显示提示文字时显示所有结果
        否则根据搜索关键词过滤显示匹配的结果
        """
        keywords = self.entrybox_var.get().lower()

        # 清空当前显示
        self.tree.delete(*self.tree.get_children())

        # 没有搜索关键词时显示所有结果
        if not keywords or keywords == "typing keywords here":
            for idx, item in enumerate(self.search_results):
                tree_item = self.tree.insert("", "end", values=item)
                self.tree.set(tree_item, "index", str(idx))
        # 根据搜索关键词过滤结果
        else:
            for idx, values in enumerate(self.search_results):
                if keywords in str(values[2]).lower():
                    item = self.tree.insert("", "end", values=values)
                    self.tree.set(item, "index", str(idx))

        self.update_clean_btn()

    def handle_menu(self, action: Literal["open", "reveal", "copy"]) -> None:
        """处理右键菜单动作

        Args:
            action (Literal["open", "reveal", "copy"]): 要执行的操作
                - open: 打开文件/目录
                - reveal: 在文件管理器中显示
                - copy: 复制路径到剪贴板
        """
        if not (selected := self.tree.selection()):
            return
        path = self.tree.item(selected[0])["values"][2]

        try:
            match (OS, action):
                case ("Darwin" | "Windows", "open"):
                    subprocess.run(["open" if OS == "Darwin" else "start", path])
                case ("Darwin" | "Windows", "reveal"):
                    subprocess.run(
                        ["open", "-R", path]
                        if OS == "Darwin"
                        else ["explorer", "/select,", path]
                    )
                case (_, "open" | "reveal"):
                    subprocess.run(["xdg-open", path])
                case (_, "copy"):
                    self.root.clipboard_clear()
                    self.root.clipboard_append(path)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    @staticmethod
    def send_notification(title: str, message: str) -> None:
        """发送系统通知

        支持 macOS、Windows 和 Linux 平台

        Args:
            title (str): 通知标题
            message (str): 通知内容
        """
        match OS:
            case "Darwin":
                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f'display notification "{message}" with title "{title}"',
                    ]
                )
            case "Windows":
                messagebox.showinfo(title, message)
            case "Linux":
                try:
                    subprocess.run(["notify-send", title, message])
                except FileNotFoundError:
                    pass


class CLI:
    """CLI界面类, 使用 rich 创建命令行界面"""

    def __init__(self, path: Path, auto: bool = False) -> None:
        """初始化 CLI 界面

        Args:
            path (Path): 要扫描的路径
            auto (bool, optional): 是否自动清理, 默认为 False
        """
        self.core = Core()
        self.results = []
        self.error_messages = []
        self.console = Console(highlight=True)
        self.status = None

        try:
            # 显示状态动画, 开始扫描并检查队列
            self.status = self.console.status(f"[b green]Scanning {str(path)}...[/]")
            self.status.start()
            self.core.action("scan", path)
            self.check_queue(time.time(), path, auto)
        except KeyboardInterrupt:
            self.exit()

    def show_panel(self, message: str, title: str = "", color: str = "green") -> None:
        """显示带边框的消息面板

        使用 rich.Panel 创建带边框和标题的格式化消息面板
        消息前会自动添加时间戳

        Args:
            message (str): 要显示的消息内容
            title (str, optional): 面板标题, 默认为空字符串
            color (str, optional): 文字颜色, 默认为 "green"
        """
        text = Text(f"\n{Core.now_time()}", style="yellow").append(message, style=color)
        self.console.print(Panel(text, title=title, border_style="b blue"))

    def check_queue(self, start_time: float, path: Path, auto: bool = False) -> None:
        """检查消息队列并更新界面

        处理来自扫描和清理线程的消息, 更新界面显示

        Args:
            start_time (float): 操作开始时间戳
            path (Path): 扫描路径, 仅用于显示在扫描结果表格的标题中
            auto (bool, optional): 是否自动清理, 默认为 False
        """
        # 创建结果表格
        table = Table(
            title=f"{APP_TITLE} - Scan result of {str(path)}",
            title_style="b i bright_yellow on blue",
            header_style="b blue",
            border_style="blue",
            width=self.console.width,
        )
        table.add_column("📄 Kind", justify="center", style="red", min_width=6)
        table.add_column(
            "📂 Path", justify="default", style="default", min_width=30, overflow="fold"
        )
        table.add_column("📊 Size", justify="right", style="green", min_width=8)
        table.add_column("🕒 Modified", justify="center", style="yellow", min_width=19)

        try:
            while msg := self.core.queue.get(timeout=None):
                match msg:

                    # 扫描到垃圾文件/文件夹, 添加到结果列表和表格
                    case ("found_item", (path, kind, size, modified)):
                        self.results.append(path)
                        table.add_row(kind, str(path), size, modified)

                    # 扫描完成, 停止状态动画
                    case ("scan_done", (total_size, file_count)):
                        elapsed = time.time() - start_time
                        self.status.stop()

                        # 如果找到垃圾文件/文件夹
                        if self.results:
                            # 打印表格
                            self.console.print(table)
                            # 构建统计信息
                            message = (
                                f"Scan completed in {elapsed:.2f}s. Found {file_count} items, "
                                f"total size: {total_size}"
                            )
                            if auto:
                                # 显示统计信息
                                self.show_panel(message, "Scan completed")
                            else:
                                # 显示统计信息并询问是否执行清理
                                message += f"\n\n{' '*11}Do you want to delete these files? [y/n]"
                                self.show_panel(message, "Scan completed")
                                # 等待用户确认是否清理
                                while True:
                                    try:
                                        if not Confirm.ask(">> ", show_choices=False):
                                            self.exit()
                                        break
                                    except EOFError:
                                        # 彻底忽略屏蔽 Ctrl+D, 它会破坏 rich.Panel 样式
                                        print(
                                            "\r"  # 删除行, 用空格填充行, 再删除行
                                            + " " * shutil.get_terminal_size().columns
                                            + "\r",
                                            end="",  # 不自动换行
                                            flush=True,  # 立即刷新输出缓冲区
                                        )  # print 执行完后进入新一轮 while 循环, 重新等待用户输入
                            # 显示状态动画, 开始清理
                            self.status = self.console.status("[b green]Cleaning...[/]")
                            self.status.start()
                            if auto:  # auto 模式下不延迟清理
                                self.core.action("clean", self.results, delay=False)
                            else:
                                self.core.action("clean", self.results)
                        # 没找到垃圾文件/文件夹
                        else:
                            self.show_panel(
                                f"Scan completed in {elapsed:.2f}s. No junk files found.",
                                "Scan completed",
                            )
                            return

                    # 更新清理状态动画
                    case ("clean_progress", (cleaned, total)):
                        self.status.update(
                            f"[b green]Cleaning... {int((cleaned / total) * 100)}%[/]"
                        )

                    # 遇到清理错误, 暂存错误消息, 清理完成后一并打印
                    case ("clean_error", (path, error)):
                        self.error_messages.append(str(error))

                    # 清理完成后停止清理状态动画, 打印清理完成消息
                    case ("clean_done", (cleaned_size, success_count, total)):
                        self.status.stop()
                        message = (
                            f"Successfully cleaned {success_count} items, "
                            f"freed disk space: {cleaned_size}"
                        )
                        if self.error_messages:
                            message += (
                                f"\n\n{' '*11}"
                                f"The following {total-success_count} items failed to be cleared, "
                                f"try re-running with root. \n"
                            )
                            for error in self.error_messages:
                                message += f"\n{' '*11} • {error}"
                        self.show_panel(message, "Cleanup completed")
                        return

        except queue.Empty:  # 队列为空且线程仍在运行, 继续检查队列
            if self.core.thread and self.core.thread.is_alive():
                self.check_queue(start_time, path, auto)
        except Exception as e:
            self.show_panel(f"Error: {str(e)}", "Error", "red")
        except EOFError:
            self.check_queue(start_time, path, auto)
        except KeyboardInterrupt:
            self.exit()

    def exit(self) -> None:
        """优雅地退出程序

        停止所有操作并显示退出消息
        """
        self.core.abort_event.set()
        self.status.stop()
        self.console.print()
        self.show_panel("The operation has been canceled, program exited.", "Exiting")
        sys.exit()


if __name__ == "__main__":
    """程序入口点, 仅在不是被作为模块导入时执行

    支持两种运行模式:
        GUI模式: 默认模式, 提供图形界面
        CLI模式: 使用 --cli 参数启动, 提供命令行界面
    """

    # 命令行参数
    parser = argparse.ArgumentParser(description=f"{APP_TITLE} - {RUNTIME_VERSION}")
    parser.add_argument("--cli", "-c", action="store_true", help="run in CLI mode")
    parser.add_argument(
        "--auto",
        "-a",
        action="store_true",
        help="auto clean without confirmation (only works in CLI mode)",
    )
    parser.add_argument(
        "--path",
        "-p",
        type=Path,
        default=DEFAULT_SCAN_PATH,
        help=f"path to scan (default: {DEFAULT_SCAN_PATH})",
    )
    args = parser.parse_args()

    # 检查参数有效性
    if args.auto and not args.cli:
        parser.error("--auto/-a only works in CLI mode")

    # 根据参数选择运行模式
    CLI(args.path, args.auto) if args.cli else GUI(args.path)
