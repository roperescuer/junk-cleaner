#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, platform, subprocess, shutil, threading, queue, re, argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from rich.console import Console
from rich.text import Text
from rich.table import Table
from rich.prompt import Confirm

OS = platform.system()
APP_TITLE = f"🧹 Junk Cleaner V250310 on {OS}"
RUNTIME_VERSION = f"Python {sys.version.split()[0]} / tkinter {tk.TkVersion}"
DEFAULT_SCAN_PATH = {"Darwin": Path("/Users"), "Windows": Path("C:/")}.get(OS, Path("/home"))
JUNK_FILES = {
    "names": (".DS_Store", "desktop.ini", "Thumbs.db", ".bash_history", ".zsh_history", "fish_history",
        ".viminfo", ".localized", ".sharkgi", ".lesshst", ".python_history", "history.db", "Logs.db",
        ".wget-hsts", re.compile(r"\.zcompdump-.*")),
    "extensions": (".log", ".tmp", "temp", ".cache"),
    "folders": ("$RECYCLE.BIN", "Logs", "CrashReporter", "tmp", "temp", "log", "logs",
        ".Trash", ".fseventsd", ".Spotlight-V100", ".zsh_sessions", "System Volume Information",
        "Photo Booth Library", "Automatically Add to Music.localized", ".pyinspect",
        "Media.localized", "Videos Library.tvlibrary", "网易云音乐", re.compile(r"Cache", re.IGNORECASE))
}

class Core:
    """核心功能类, 处理文件扫描和清理的逻辑, 并封装有2个独立函数"""
    def __init__(self) -> None:
        self.abort_event = threading.Event()
        self.queue = queue.Queue()
        self.thread = None

    def action(self, action_type: str, path_or_items: Path | list[Path]) -> None:
        """启动扫描和清理操作的对外接口"""

        self.abort_event.clear()
        target = self._scanner if action_type == "scan" else self._cleaner
        self.thread = threading.Thread(target=target, args=(path_or_items,))
        self.thread.start()

    def _scanner(self, scan_path: Path) -> None:
        """扫描线程的工作函数"""

        # 内部匿名函数: 检查文件名是否匹配任何模式
        matches_patterns = lambda item, patterns: any(
            (p.lower() == item.lower() if isinstance(p, str) else p.search(item))
            for p in patterns)

        total_size = 0
        file_count = 0
        processed_paths = set()  # 用于记录已处理的路径

        for root_path in scan_path.rglob("*"):
            if self.abort_event.is_set():
                return
            try:
                # 如果当前路径的任何父目录已被处理, 则跳过
                if any(str(parent) in processed_paths for parent in root_path.parents):
                    continue

                # 检查文件夹
                if root_path.is_dir():
                    if matches_patterns(root_path.name, JUNK_FILES["folders"]):
                        size = sum(f.stat().st_size for f in root_path.rglob('*') if f.is_file())
                        modified = time.strftime("%Y-%m-%d %H:%M:%S",
                            time.localtime(root_path.stat().st_mtime))
                        self.queue.put(("found_item", (root_path, "Folder", size, modified)))
                        total_size += size
                        file_count += 1
                        processed_paths.add(str(root_path))  # 记录已处理的目录路径

                # 检查文件
                elif root_path.is_file():
                    # 同时检查文件名和扩展名(都转换为小写进行比较)
                    if (matches_patterns(root_path.name, JUNK_FILES["names"]) or
                    root_path.suffix.lower() in [ext.lower() for ext in JUNK_FILES["extensions"]]):
                        size = root_path.stat().st_size
                        modified = time.strftime("%Y-%m-%d %H:%M:%S",
                            time.localtime(root_path.stat().st_mtime))
                        self.queue.put(("found_item", (root_path, "File", size, modified)))
                        total_size += size
                        file_count += 1

            except (OSError, PermissionError):
                continue

        if not self.abort_event.is_set():
            self.queue.put(("scan_done", (total_size, file_count)))

    def _cleaner(self, items: list[Path]) -> None:
        """清理线程的工作函数"""

        total = len(items)                  # 总项目数
        cleaned = 0                         # 已清理数量
        target_duration = 0.5               # 目标总清理时间（秒）
        delay = target_duration / total     # 每个项目的延迟时间

        for path in items:
            if self.abort_event.is_set():
                break
            try:
                if path.exists():
                    if path.is_file():
                        path.unlink()
                        time.sleep(delay)
                    else:
                        shutil.rmtree(path, ignore_errors=True)
                        time.sleep(delay)
                cleaned += 1
                self.queue.put(("clean_progress", (cleaned, total)))
            except (OSError, PermissionError) as e:
                self.queue.put(("clean_error", (path, str(e))))

        if not self.abort_event.is_set():
            self.queue.put(("clean_done", None))

    @staticmethod
    def format_size(size: int) -> str:
        """格式化文件大小"""

        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024: break
            size /= 1024
        return f"{size:.1f} {unit}"

    @staticmethod
    def send_notification(title: str, message: str) -> None:
        """发送 macOS 原生通知"""

        if OS != "Darwin":
            return
        subprocess.run(['osascript', '-e',
            f'display notification "{message}" with title "{title}"'])

class GUI:
    """GUI界面类"""
    def __init__(self, path: Path) -> None:
        self.core = Core()
        self.scan_path = path
        self.is_scanning = False
        self.root = None
        self.tree = None
        self.status_var = None
        self.scan_btn = None
        self.clean_btn = None
        self.path_var = None
        self.progress = None
        self.context_menu = None

        if tk.TkVersion < 9.0:
            messagebox.showerror("Error", f"Requires Tk 9.0+. Your version: {RUNTIME_VERSION}")
            sys.exit()

        # 创建主窗口
        self.root = tk.Tk()
        self.root.geometry("1152x720")
        self.root.minsize(1024, 640)
        self.root.title(f"{APP_TITLE} - {RUNTIME_VERSION}")

        # 路径标签
        ttk.Label(self.root, text="Path to scan:").grid(row=0, column=0, padx=10, pady=5, sticky="w")

        # 创建 StringVar 关联路径输入框
        self.path_var = tk.StringVar(value=self.scan_path)
        self.path_var.trace_add(
            "write", lambda *args: setattr(self, "scan_path", Path(self.path_var.get())))

        # 路径输入框
        ttk.Entry(self.root, textvariable=self.path_var).grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # 浏览按钮
        ttk.Button(self.root, text="📂 Browse", padding=5, width=8,
                   command=lambda: self.path_var.set(str(Path(p)))
                   if (p := filedialog.askdirectory()) else None
        ).grid(row=0, column=2, padx=5, pady=5)

        # 扫描按钮
        self.scan_btn = ttk.Button(self.root, text="🔍 Scan", padding=5, width=8, command=self.toggle_scan)
        self.scan_btn.grid(row=0, column=3, padx=5, pady=5)

        # 清理按钮
        self.clean_btn = ttk.Button(self.root, text="❌ Clean", padding=5, width=8, command=self.clean_files)
        self.clean_btn.grid(row=0, column=4, padx=5, pady=5)

        # Treeview
        self.tree = ttk.Treeview(self.root,
            columns=("select", "path", "kind", "size", "modified"), show="headings", selectmode="browse")

        self.tree.heading("select", text="☑")
        self.tree.heading("path", text="📂 Path", command=lambda: self.treeview_sort("path", False))
        self.tree.heading("kind", text="📄 Kind", command=lambda: self.treeview_sort("kind", False))
        self.tree.heading("size", text="📊 Size", command=lambda: self.treeview_sort("size", False))
        self.tree.heading("modified", text="🕒 Modified", command=lambda: self.treeview_sort("modified", False))

        self.tree.column("select", width=10, anchor="center")
        self.tree.column("path", width=650, anchor="w")
        self.tree.column("kind", width=40, anchor="center")
        self.tree.column("size", width=40, anchor="center")
        self.tree.column("modified", width=100, anchor="center")

        ttk.Style().configure("Treeview", rowheight=25)

        self.tree.bind("<Button-1>", self.handle_select)

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=1, column=0, columnspan=5, sticky="nsew", padx=5, pady=5)
        scrollbar.grid(row=1, column=5, sticky="ns")

        # 右键菜单
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Open", command=lambda: self.handle_context_menu("open"))
        self.context_menu.add_command(label="Reveal", command=lambda: self.handle_context_menu("reveal"))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Copy as Path", command=lambda: self.handle_context_menu("copy"))
        self.tree.bind("<Button-3>", lambda e: (
            self.tree.selection_set(self.tree.identify_row(e.y)),
            self.context_menu.post(e.x_root, e.y_root)) if self.tree.identify_row(e.y) else None)

        # 状态栏
        self.status_var = tk.StringVar()
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", padding=(5, 2))
        status_bar.grid(row=2, column=0, columnspan=6, sticky="ew")

        # 进度条
        self.progress = ttk.Progressbar(self.root, length=350)
        self.progress.grid(row=2, column=0, columnspan=6, padx=10, sticky="e")

        # 配置网格权重
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        # 自动执行首次扫描
        self.toggle_scan()

        # 运行主循环
        self.root.mainloop()

    def toggle_scan(self) -> None:
        """开始/停止扫描"""

        if not self.is_scanning:  # 开始扫描
            # 检查路径是否存在
            if not self.scan_path.exists():
                messagebox.showerror("Error", "Path does not exist")
                return

            # 设置扫描状态
            self.is_scanning = True

            # 更新按钮外观, 显示进度条动画, 更新状态栏, 清空 Treeview
            self.scan_btn.config(text="🛑 Stop")
            self.clean_btn.config(state="disabled")
            self.progress.config(mode="indeterminate")
            self.progress.start(10)
            self.status_var.set("Scanning...")
            for item in self.tree.get_children():
                self.tree.delete(item)

            # 开始扫描并检查队列
            self.core.action("scan", self.scan_path)
            self.check_queue(time.time())

        else:  # 停止扫描
            self.is_scanning = False
            self.core.abort_event.set()  # 触发中断事件
            self.progress.stop()  # 停止进度条动画
            self.scan_btn.config(text="🔍 Scan", state="normal")
            self.clean_btn.config(state="normal" if self.tree.get_children() else "disabled")
            self.status_var.set("Scan cancelled")

    def clean_files(self) -> None:
        """清理选中的文件"""

        try:
            # 获取所有选中的项目
            selected_items = [item for item in self.tree.get_children()
                             if self.tree.item(item)["values"][0] == "✓"]

            # 如果没有选中项目或用户取消操作, 则返回
            if not selected_items or not messagebox.askyesno("Confirm",
                "Do you want to delete these files?"):
                return

            # 禁用清理按钮, 配置进度条动画
            self.clean_btn.config(state="disabled")
            self.progress.config(mode="determinate", maximum=100, value=0)

            # 将 Treeview 中的字符串路径转换为 Path 对象
            items_to_clean = [Path(self.tree.item(item)["values"][1]) for item in selected_items]

            # 开始清理并检查队列
            self.core.action("clean", items_to_clean)
            self.check_queue(time.time())

        except Exception:
            # 如遇错误, 状态栏显示错误消息, 停止进度条动画, 启用清理按钮
            self.status_var.set(f"Error starting cleanup: {str(Exception)}")
            self.clean_btn.config(state="normal")
            self.progress.stop()

    def check_queue(self, start_time: float) -> None:
        """检查队列中的消息"""

        # 若已触发中断则停止检查队列
        if self.core.abort_event.is_set():
            return

        try:
            while True:
                try:  # 从队列中获取消息, 若队列为空则退出循环
                    msg_type, data = self.core.queue.get_nowait()
                except queue.Empty:
                    break

                match msg_type:
                    case "found_item":  # 在 Treeview 中添加找到的项目
                        full_path, kind, size, modified = data
                        self.tree.insert("", "end", values=("✓", full_path, kind,
                                       self.core.format_size(size), modified))

                    case "scan_done":  # 在状态栏显示扫描完成后的统计信息
                        total_size, file_count = data
                        elapsed = time.time() - start_time
                        self.status_var.set(
                            f"Scan completed in {elapsed:.2f}s. "
                            f"Found {file_count} items, Total size: {self.core.format_size(total_size)}")
                        # 显示通知
                        Core.send_notification(f"🔍 Scan completed in {elapsed:.2f}s",
                            f"Found {file_count} items, Total size: {self.core.format_size(total_size)}")
                        # 重置扫描状态和按钮, 停止进度条动画
                        self.is_scanning = False
                        self.scan_btn.config(text="🔍 Scan", state="normal")
                        self.progress.stop()
                        # 清理按钮仅在有选中项时启用
                        self.clean_btn.config(state="normal" if any(
                            self.tree.item(i)["values"][0]=="✓"
                            for i in self.tree.get_children()) else "disabled")
                        return

                    case "clean_progress":  # 更新清理进度
                        cleaned, total = data
                        progress = (cleaned / total) * 100
                        self.progress["value"] = progress
                        self.status_var.set(f"Cleaning... {int(progress)}%")

                    case "clean_error":  # 在状态栏显示清理错误
                        path, error = data
                        self.status_var.set(error)

                    case "clean_done":  # 在状态栏显示清理完成消息, 停止进度条动画
                        self.status_var.set("Cleanup completed")
                        self.progress.stop()
                        # 显示通知
                        Core.send_notification("✅ Cleanup completed", "Cleanup completed successfully")
                        # 清空 Treeview 内容
                        for item in self.tree.get_children():
                            self.tree.delete(item)
                        # 禁用清理按钮
                        self.clean_btn.config(state="disabled")
                        return

        except Exception:
            # 如遇错误, 重置扫描状态和按钮, 停止进度条动画
            self.is_scanning = False
            self.status_var.set(f"Error processing results: {str(Exception)}")
            self.scan_btn.config(text="🔍 Scan", state="normal")
            self.clean_btn.config(state="normal")
            self.progress.stop()

        # 如果线程仍在运行则继续检查队列
        if self.core.thread and self.core.thread.is_alive():
            self.root.after(10, self.check_queue, start_time)

    def treeview_sort(self, col: str, reverse: bool) -> None:
        """对表格列进行排序"""

        # 获取待排序项目
        items = [(k, self.tree.set(k, col)) for k in self.tree.get_children("")]

        # 根据列的类型进行排序
        if col == "size":  # 按文件大小排序
            units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
            items = sorted(items,
                key=lambda x: float(x[1].split()[0]) * units[x[1].split()[1]], reverse=reverse)
        else:
            items = sorted(items, key=lambda x: x[1], reverse=reverse)

        # 重新排列项目
        for idx, (item, _) in enumerate(items):
            self.tree.move(item, "", idx)

        # 更新表头排序指示器
        for header in ["path", "kind", "size", "modified"]:
            text = self.tree.heading(header)["text"].rstrip(" ↑↓")
            self.tree.heading(header,
                text=f"{text} {('↓' if reverse else '↑') if header == col else ''}")

        # 切换下次排序方向
        self.tree.heading(col, command=lambda: self.treeview_sort(col, not reverse))

    def handle_select(self, event: tk.Event) -> None:
        """处理 Treeview 的点击事件"""

        # 只处理复选框列的点击, 列表为空时不处理
        if (self.tree.identify_column(event.x) != "#1") or (not self.tree.get_children()):
            return

        # 获取点击的区域和项目
        region = self.tree.identify_region(event.x, event.y)

        if region == "heading":  # 点击表头
            first_item = self.tree.get_children()[0]
            new_state = " " if self.tree.item(first_item)["values"][0] == "✓" else "✓"

            # 更新表头和所有项目
            self.tree.heading("select", text="☐" if new_state == " " else "☑")
            for item in self.tree.get_children():
                values = list(self.tree.item(item)["values"])
                values[0] = new_state
                self.tree.item(item, values=values)

        elif region == "cell":  # 点击单元格
            if item := self.tree.identify_row(event.y):
                values = list(self.tree.item(item)["values"])
                values[0] = " " if values[0] == "✓" else "✓"
                self.tree.item(item, values=values)

                # 更新表头状态
                all_checked = all(self.tree.item(i)["values"][0] == "✓" for i in self.tree.get_children())
                self.tree.heading("select", text="☑" if all_checked else "☐")

        # 更新清理按钮状态
        has_selected = any(self.tree.item(i)["values"][0] == "✓" for i in self.tree.get_children())
        self.clean_btn.config(state="normal" if has_selected else "disabled")

    def handle_context_menu(self, action: str) -> None:
        """处理右键菜单"""

        if not (selected := self.tree.selection()):
            return
        path = self.tree.item(selected[0])["values"][1]

        try:
            match action:
                case "open":  # 打开文件
                    if OS == "Darwin":
                        subprocess.run(["open", path])
                    elif OS == "Windows":
                        os.startfile(path)
                    else:
                        subprocess.run(["xdg-open", path])
                case "reveal":  # 在 Finder 中显示文件
                    if OS == "Darwin":
                        subprocess.run(["open", "-R", path])
                    elif OS == "Windows":
                        subprocess.run(["explorer", "/select,", path])
                    else:
                        subprocess.run(["xdg-open", path])
                case "copy":  # 复制文件路径
                    self.root.clipboard_clear()
                    self.root.clipboard_append(path)
        except Exception:
            messagebox.showerror("Error", str(Exception))

class CLI:
    """CLI界面类"""
    def __init__(self, path: Path, auto: bool = False) -> None:
        self.core = Core()
        self.results = []
        self.console = Console()
        self.status = None

        try:
            # 显示状态动画, 开始扫描并检查队列
            self.status = self.console.status(f"Scanning {str(path)}...")
            self.status.start()
            self.core.action("scan", path)
            self.check_queue(time.time(), path, auto)
        except (KeyboardInterrupt, EOFError):
            self.exit()

    def check_queue(self, start_time: float, path: Path, auto: bool = False) -> None:
        """检查队列中的消息"""

        # 创建结果表格
        table = Table(title=f"{APP_TITLE} - Scan result of {str(path)}",
                      title_style="b i bright_yellow on blue",
                      header_style="b blue", border_style="blue")
        table.add_column("📄 Kind", justify="center", style="red", min_width=6)
        table.add_column("📂 Path", justify="default", style="default", min_width=30, overflow="fold")
        table.add_column("📊 Size", justify="right", style="green", min_width=8)
        table.add_column("🕒 Modified", justify="center", style="yellow", min_width=19)

        try:
            while True:
                try:
                    # 从队列中获取消息
                    msg_type, data = self.core.queue.get(timeout=None)
                except queue.Empty:  # 如果队列为空, 继续检查线程是否仍在运行
                    if self.core.thread and self.core.thread.is_alive():
                        continue
                    break

                match msg_type:
                    case "found_item":  # 添加到表格
                        full_path, kind, size, modified = data
                        self.results.append(full_path)
                        table.add_row(kind, str(full_path), self.core.format_size(size), modified)

                    case "scan_done":  # 扫描完成后显示统计信息
                        total_size, file_count = data
                        elapsed = time.time() - start_time

                        # 停止扫描状态动画
                        self.status.stop()

                        # 有找到垃圾文件时打印结果表格
                        if self.results:
                            self.console.print(table)

                        # 打印统计信息
                        done = Text(f"\nScan completed in {elapsed:.2f}s. ", style="b green")
                        done.append(f"Found {file_count} items, ", style="b green")
                        done.append(f"Total size: {self.core.format_size(total_size)}", style="b green")
                        self.console.print(done)

                        # 显示通知
                        Core.send_notification(f"🔍 Scan completed in {elapsed:.2f}s",
                            f"Found {file_count} items, Total size: {self.core.format_size(total_size)}")

                        if self.results:  # 如果找到垃圾文件
                            if not auto:  # 非 --auto 模式下要求确认
                                ask = Text("\nDo you want to delete these files? ", style="red")
                                if not Confirm.ask(ask):
                                    self.exit()

                            # 显示状态动画, 开始清理
                            self.status = self.console.status("Cleaning...")
                            self.status.start()
                            self.core.action("clean", self.results)
                        else:
                            return  # 没找到垃圾文件直接退出

                    case "clean_progress":  # 清理状态动画进度更新
                        cleaned, total = data
                        progress = (cleaned / total) * 100
                        self.status.update(f"Cleaning... {int(progress)}%")

                    case "clean_error":  # 打印清理错误消息
                        path, error = data
                        self.console.print(error, style="red")

                    case "clean_done":  # 清理完成后停止清理状态动画, 打印清理完成消息
                        self.status.stop()
                        self.console.print("\nCleanup completed\n", style="b green")
                        Core.send_notification("✅ Cleanup completed", "Cleanup completed successfully")
                        return

        except (KeyboardInterrupt, EOFError):
            self.exit()
        except Exception:
            self.console.print(f"Error processing scan results: {str(Exception)}", style="red")

    def exit(self) -> None:
        """体面地说再见"""

        self.core.abort_event.set()
        self.status.stop()
        self.console.print("\nThe operation has been canceled, program exited.\n", style="b green")
        sys.exit()

if __name__ == "__main__":

    # 命令行参数
    parser = argparse.ArgumentParser(description=f"{APP_TITLE} - {RUNTIME_VERSION}")
    parser.add_argument("--cli", "-c", action="store_true", help="run in CLI mode")
    parser.add_argument("--auto", "-a", action="store_true",
                        help="auto clean without confirmation (only works in CLI mode)")
    parser.add_argument("--path", "-p", type=Path, default=DEFAULT_SCAN_PATH,
                        help=f"path to scan (default: {DEFAULT_SCAN_PATH})")
    args = parser.parse_args()

    # 检查 --auto 参数的使用
    if args.auto and not args.cli:
        parser.error("--auto/-a only works in CLI mode")

    # 根据参数选择运行模式
    if args.cli:
        CLI(args.path, args.auto)
    else:
        GUI(args.path)
