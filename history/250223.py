#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = "Wolfe Wang"
__version__ = "250223"

import os, sys, time, platform, subprocess, shutil, threading, queue, re, argparse, ctypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

OS = platform.system()
DEFAULT_SCAN_PATH = {"Darwin": Path("/Users"), "Windows": Path("C:/")}.get(OS, Path("/home"))
APP_INFO = f"🧹  Junk Cleaner V{__version__} on {OS} - Python {sys.version.split()[0]}"

JUNK_FILES = {
    "names": (".DS_Store", "desktop.ini", "Thumbs.db", ".bash_history", ".zsh_history", "fish_history",
        ".viminfo", ".localized", ".sharkgi", ".lesshst", ".python_history", re.compile(r"\.zcompdump-.*")),
    "extensions": (".log", ".tmp", "temp", ".cache"),
    "folders": ("$RECYCLE.BIN", "Logs", "CrashReporter", "tmp", "temp", "log",
        ".Trash", ".fseventsd", ".Spotlight-V100", ".zsh_sessions", "System Volume Information",
        "Photo Booth Library", "Automatically Add to Music.localized",
        "Media.localized", "Videos Library.tvlibrary", "网易云音乐", re.compile(r"Cache", re.IGNORECASE))}

# SGR (Select Graphic Rendition) ANSI escape codes
SGR_TITLE   = "\033[1;94m"   # 粗体亮蓝
SGR_SCAN    = "\033[1;92m"   # 粗体亮绿
SGR_CLEAN   = "\033[1;31m"   # 粗体红色
SGR_FOUND   = "\033[103m"    # 背景亮黄
SGR_DEL     = "\033[41m"     # 背景红色
SGR_ERR     = "\033[31m"     # 细体红色
SGR_RST     = "\033[0m"      # 重置样式
LF          = "\n"           # 换行

class Core:
    """核心功能类，处理文件扫描和清理的逻辑"""
    def __init__(self) -> None:
        self.abort_event = threading.Event()
        self.scan_queue = queue.Queue()
        self.scan_thread = None

    def scan(self, scan_path: Path) -> threading.Thread:
        """扫描指定路径的垃圾文件"""

        # 重置中断事件和队列
        self.abort_event.clear()
        self.scan_queue = queue.Queue()

        # 创建并启动扫描线程
        self.scan_thread = threading.Thread(target=self.scanner, args=(scan_path,))
        self.scan_thread.start()
        return self.scan_thread

    def scanner(self, scan_path: Path) -> None:
        """扫描线程的工作函数"""

        def matches_patterns(filename: str, patterns: list) -> bool:
            """内部函数: 检查文件名是否匹配任何模式"""
            return any(
                (pattern == filename if isinstance(pattern, str)
                else bool(pattern.search(filename)))
                for pattern in patterns
                if pattern)

        total_size = 0
        file_count = 0

        for root_path in scan_path.rglob("*"):

            # 发送当前扫描路径
            self.scan_queue.put(("progress", f"Scanning: {root_path}"))

            try:
                # 检查垃圾文件夹
                if root_path.is_dir():
                    if self.abort_event.is_set():  # 检查是否中断扫描
                        break
                    if matches_patterns(root_path.name, JUNK_FILES["folders"]):
                        size = sum(f.stat().st_size for f in root_path.rglob('*') if f.is_file())
                        modified = time.strftime("%Y-%m-%d %H:%M:%S",
                            time.localtime(root_path.stat().st_mtime))
                        self.scan_queue.put(("item", (root_path, "Folder", size, modified)))
                        total_size += size
                        file_count += 1

                # 检查垃圾文件
                elif root_path.is_file():
                    if self.abort_event.is_set():  # 检查是否中断扫描
                        break
                    if (matches_patterns(root_path.name, JUNK_FILES["names"]) or
                    root_path.suffix in JUNK_FILES["extensions"]):
                        size = root_path.stat().st_size
                        modified = time.strftime("%Y-%m-%d %H:%M:%S",
                            time.localtime(root_path.stat().st_mtime))
                        self.scan_queue.put(("item", (root_path, "File", size, modified)))
                        total_size += size
                        file_count += 1

            except (OSError, PermissionError):
                continue

        # 发送扫描完成消息和统计结果
        self.scan_queue.put(("done", (total_size, file_count)))

    def clean(self, items: list[Path] = None) -> None:
        """清理垃圾文件"""

        for path in items:
            try:
                if path.exists():
                    if path.is_file():
                        path.unlink()
                    else:
                        shutil.rmtree(path, ignore_errors=True)
                    # 发送清理成功消息
                    self.scan_queue.put(("clean_success", path))
            except (OSError, PermissionError) as e:
                # 发送清理失败消息
                self.scan_queue.put(("clean_error", (path, str(e))))

        # 发送清理完成消息
        self.scan_queue.put(("clean_done", None))

    @staticmethod
    def format_size(size: int) -> str:
        """格式化文件大小"""

        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024: break
            size /= 1024
        return f"{size:.1f} {unit}"

class GUI:
    """GUI界面类"""
    def __init__(self) -> None:
        self.core = Core()
        self.root = None
        self.path_entry = None
        self.tree = None
        self.scan_path = DEFAULT_SCAN_PATH
        self.status_var = None
        self.scan_btn = None
        self.clean_btn = None
        self.path_var = None
        self.context_menu = None

    def run(self, path: Path) -> None:
        """运行 GUI 界面"""

        self.scan_path = path
        if not self.root:
            self.create_ui()
            # GUI创建后 100ms 自动开始执行首次扫描
            self.root.after(100, self.scan_files)
        self.root.mainloop()

    def create_ui(self) -> None:
        """初始化用户界面"""

        # 创建主窗口
        self.root = tk.Tk()
        self.root.geometry("1200x700")
        self.root.minsize(900, 600)

        # 设置主窗口标题
        self.root.title(f"{APP_INFO} / tkinter {tk.TkVersion}")

        if OS == "Windows" and ctypes.windll.shell32.IsUserAnAdmin():
            self.root.title(self.root.title() + " (Running as administrator)")
        else:
            if os.geteuid() == 0:
                self.root.title(self.root.title() + " (Running as root)")

        # 路径标签
        path_label = ttk.Label(self.root, text="Path to scan:")
        path_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        # 创建一个 StringVar 来关联路径输入框
        self.path_var = tk.StringVar(value=self.scan_path)
        self.path_var.trace_add(
            "write", lambda *args: setattr(self, "scan_path", Path(self.path_var.get())))

        # 路径输入框
        self.path_entry = ttk.Entry(self.root, textvariable=self.path_var)
        self.path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # 浏览按钮
        browse_btn = ttk.Button(self.root, text="📂 Browse", padding=5, width=8, command=self.browse_path)
        browse_btn.grid(row=0, column=2, padx=5, pady=5)

        # 扫描按钮
        self.scan_btn = ttk.Button(self.root, text="🔍 Scan", padding=5, width=8, command=self.scan_files)
        self.scan_btn.grid(row=0, column=3, padx=5, pady=5)

        # 清理按钮
        self.clean_btn = ttk.Button(self.root, text="❌ Clean", padding=5, width=8, command=self.clean_files)
        self.clean_btn.grid(row=0, column=4, padx=5, pady=5)

        # Treeview
        self.tree = ttk.Treeview(self.root,
            columns=("select", "path", "kind", "size", "modified"), show="headings")

        self.tree.heading("select", text="☑")
        self.tree.heading("path", text="Path", command=lambda: self.treeview_sort("path", False))
        self.tree.heading("kind", text="Kind", command=lambda: self.treeview_sort("kind", False))
        self.tree.heading("size", text="Size", command=lambda: self.treeview_sort("size", False))
        self.tree.heading("modified", text="Modified", command=lambda: self.treeview_sort("modified", False))

        self.tree.column("select", width=10, anchor="center")
        self.tree.column("path", width=500)
        self.tree.column("kind", width=100, anchor="center")
        self.tree.column("size", width=100, anchor="center")
        self.tree.column("modified", width=100, anchor="center")

        ttk.Style().configure("Treeview", rowheight=25)

        self.tree.bind("<Button-1>", self.handle_select)

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=1, column=0, columnspan=5, sticky="nsew", padx=5, pady=5)
        scrollbar.grid(row=1, column=5, sticky="ns")

        # 右键菜单
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Open", command=self.open_file)
        self.context_menu.add_command(label="Open in Finder", command=self.open_in_finder)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Copy as Path", command=self.copy_path)
        self.tree.bind("<Button-3>", self.show_context_menu)  # 绑定到 Treeview

        # 状态栏
        self.status_var = tk.StringVar()
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", padding=(5, 2))
        status_bar.grid(row=2, column=0, columnspan=6, sticky="ew")

        # 配置网格权重
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

    def browse_path(self) -> None:
        """打开文件夹选择对话框"""

        if path_str := filedialog.askdirectory():
            path = Path(path_str)
            self.path_var.set(str(path))  # StringVar 需要字符串
            self.scan_path = path

    def check_queue(self, start_time: float) -> None:
        """检查队列中的消息"""

        try:
            while True:
                try:  # 从队列中获取消息, 如果队列为空则退出循环
                    msg_type, data = self.core.scan_queue.get_nowait()
                except queue.Empty:
                    break

                match msg_type:

                    case "progress":  # 在状态栏显示正在扫描的路径
                        self.status_var.set(data)

                    case "item":  # 在 Treeview 中添加找到的项目
                        full_path, kind, size, modified = data
                        self.tree.insert("", "end", values=("✓", full_path, kind,
                                       self.core.format_size(size), modified))

                    case "done":  # 在状态栏显示扫描完成后的统计信息
                        total_size, file_count = data
                        elapsed = time.time() - start_time
                        self.status_var.set(
                            f"Scan completed in {elapsed:.2f}s. "
                            f"Found {file_count} items, Total size: {self.core.format_size(total_size)}")
                        self.scan_btn.config(state="normal")
                        # 清理按钮仅在有选中项时启用
                        self.clean_btn.config(state="normal" if any(
                            self.tree.item(i)["values"][0]=="✓"
                            for i in self.tree.get_children()) else "disabled")
                        return

                    case "clean_error":  # 在状态栏显示清理错误
                        path, error = data
                        self.status_var.set(f"Error cleaning {path}: {error}")

                    case "clean_done":  # 在状态栏显示清理完成消息
                        self.status_var.set("Cleanup completed")
                        # 清理按钮仅在有选中项时启用
                        self.clean_btn.config(
                            state="normal" if any(self.tree.item(i)["values"][0]=="✓"
                            for i in self.tree.get_children()) else "disabled")
                        return

        except Exception as e:
            # 如果遇到错误, 在状态栏显示错误消息, 并启用扫描和清理按钮
            self.status_var.set(f"Error processing results: {str(e)}")
            self.scan_btn.config(state="normal")
            self.clean_btn.config(state="normal")

        # 如果扫描或清理线程仍在运行,继续检查队列
        if self.core.scan_thread and self.core.scan_thread.is_alive():
            self.root.after(100, self.check_queue, start_time)

    def scan_files(self) -> None:
        """开始扫描文件"""

        # 检查路径是否存在
        if not self.scan_path.exists():
            messagebox.showerror("Error", "Path does not exist")
            return

        # 禁用按钮
        self.scan_btn.config(state="disabled")
        self.clean_btn.config(state="disabled")

        # 清空现有内容
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 开始扫描
        self.core.scan(self.scan_path)

        # 开始检查队列
        self.root.after(100, self.check_queue, time.time())

    def clean_files(self) -> None:
        """清理选中的文件"""

        try:
            # 获取所有选中的项目
            selected_items = [item for item in self.tree.get_children()
                             if self.tree.item(item)["values"][0] == "✓"]

            # 如果没有选中项目或用户取消操作, 则返回
            if not selected_items or not messagebox.askyesno("Confirm",
                "Are you sure you want to delete these files?"):
                return

            # 禁用清理按钮
            self.clean_btn.config(state="disabled")

            # 将字符串路径转换为 Path 对象 (只获取路径列)
            items_to_clean = [Path(self.tree.item(item)["values"][1])
            for item in selected_items]

            # 清空 Treeview 内容
            for item in self.tree.get_children():
                self.tree.delete(item)

            # 开始清理
            self.core.clean(items_to_clean)

            # 开始检查队列
            self.root.after(100, self.check_queue, time.time())

        except Exception as e:
            # 如果遇到错误, 在状态栏显示错误消息, 并启用清理按钮
            self.status_var.set(f"Error starting cleanup: {str(e)}")
            self.clean_btn.config(state="normal")

    def handle_select(self, event: tk.Event) -> None:
        """处理 Treeview 的点击事件"""

        # 只处理复选框列的点击, 列表为空时不处理
        if (self.tree.identify_column(event.x) != "#1") or (not self.tree.get_children()):
            return

        # 获取点击的区域和项目
        region = self.tree.identify_region(event.x, event.y)
        new_state = None

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
                all_checked = all(self.tree.item(i)["values"][0] == "✓"
                                for i in self.tree.get_children())
                self.tree.heading("select", text="☑" if all_checked else "☐")

        # 更新清理按钮状态
        has_selected = any(self.tree.item(i)["values"][0] == "✓"
                          for i in self.tree.get_children())
        self.clean_btn.config(state="normal" if has_selected else "disabled")

    def treeview_sort(self, col: str, reverse: bool) -> None:
        """对表格列进行排序"""

        # 获取待排序项目
        items = [(k, self.tree.set(k, col)) for k in self.tree.get_children("")]

        # 根据列的类型进行排序
        if col == "size":  # 按文件大小排序
            def size_to_bytes(size_str: str) -> float:
                """内部函数: 把文件大小字符串转换为字节"""
                num, unit = size_str.split()
                units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
                return float(num) * units[unit]
            items = sorted(items, key=lambda x: size_to_bytes(x[1]), reverse=reverse)
        else:
            items = sorted(items, key=lambda x: x[1], reverse=reverse)

        # 重新排列项目
        for idx, (item, _) in enumerate(items):
            self.tree.move(item, "", idx)

        # 更新表头排序指示器
        for header in ["path", "kind", "size", "modified"]:
            text = self.tree.heading(header)["text"].rstrip(" ↑↓")
            self.tree.heading(header,
                text=f"{text} {'↓' if header == col and reverse else '↑' if header == col else ''}")

        # 切换下次排序方向
        self.tree.heading(col, command=lambda: self.treeview_sort(col, not reverse))

    def show_context_menu(self, event: tk.Event) -> None:
        """显示右键菜单"""

        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def open_file(self) -> None:
        """打开选中的文件"""

        selected = self.tree.selection()
        if selected:
            path = self.tree.item(selected[0])["values"][1]
            try:
                if OS == "Darwin":
                    subprocess.run(["open", path])
                elif OS == "Windows":
                    os.startfile(path)
                else:
                    subprocess.run(["xdg-open", path])
            except Exception as e:
                messagebox.showerror("Error", f"Could not open file: {str(e)}")

    def open_in_finder(self) -> None:
        """在 Finder 中显示选中的文件"""

        selected = self.tree.selection()
        if selected:
            path = self.tree.item(selected[0])["values"][1]
            try:
                if OS == "Darwin":
                    subprocess.run(["open", "-R", path])
                elif OS == "Windows":
                    subprocess.run(["explorer", "/select,", path])
                else:
                    subprocess.run(["xdg-open", os.path.dirname(path)])
            except Exception as e:
                messagebox.showerror("Error", f"Could not open folder: {str(e)}")

    def copy_path(self) -> None:
        """复制选中文件的路径"""

        selected = self.tree.selection()
        if selected:
            path = self.tree.item(selected[0])["values"][1]
            self.root.clipboard_clear()
            self.root.clipboard_append(path)

class CLI:
    """CLI界面类"""
    def __init__(self) -> None:
        self.core = Core()
        self.results = []

    def run(self, path: Path, auto: bool = False) -> None:
        """运行命令行界面"""

        try:
            # 显示程序标题和扫描路径
            print(f"{LF}{SGR_TITLE}{APP_INFO}{SGR_RST}{LF}")
            print(f"{SGR_SCAN}Scanning Path: {path}{SGR_RST}{LF}")

            # 开始扫描
            self.core.scan(path)
            self.check_queue(time.time(), auto)

        except KeyboardInterrupt:  # 捕获 Ctrl+C 退出程序
            sys.exit(0)

    def check_queue(self, start_time: float, auto: bool = False) -> None:
        """检查队列中的消息"""

        try:
            while True:
                try:
                    # 从队列中获取消息
                    msg_type, data = self.core.scan_queue.get(timeout=None)
                except queue.Empty:  # 如果队列为空, 继续检查线程是否仍在运行
                    if self.core.scan_thread and self.core.scan_thread.is_alive():
                        continue
                    break

                match msg_type:

                    case "item":  # 打印找到的文件或文件夹
                        full_path, kind, size, modified = data
                        self.results.append(full_path)
                        print(f"{SGR_FOUND} Found {SGR_RST} {full_path} ({kind}, {self.core.format_size(size)})")

                    case "done":  # 扫描完成后显示统计信息
                        total_size, file_count = data
                        elapsed = time.time() - start_time
                        print(
                            f"{LF}{SGR_SCAN}Scan completed in {elapsed:.2f}s. "
                            f"Found {file_count} items, Total size: {self.core.format_size(total_size)}{SGR_RST}")

                        # 如果有找到垃圾文件: 非 --auto 模式下要求确认, 否则直接开始清理
                        if self.results:
                            if not auto:
                                response = input(f"{LF}{SGR_CLEAN}Do you want to clean these files? (y/N): {SGR_RST}")
                                if response.lower() != "y":
                                    print(f"{LF}{SGR_CLEAN}Cleanup cancelled{SGR_RST}")
                                    return

                            print(f"{LF}{SGR_CLEAN}Starting cleanup...{SGR_RST}{LF}")
                            self.core.clean(self.results)

                    case "clean_success":  # 打印已删除的文件或文件夹
                        print(f"{SGR_DEL} Deleted {SGR_RST} {data}")

                    case "clean_error":  # 打印清理错误
                        path, error = data
                        print(f"{SGR_ERR}Error deleting {path}: {error}{SGR_RST}")

                    case "clean_done":  # 打印清理完成消息
                        print(f"{LF}{SGR_CLEAN}Cleanup completed{SGR_RST}")
                        return

                self.core.scan_queue.task_done()

        except KeyboardInterrupt:  # 捕获 Ctrl+C 退出程序
            sys.exit(0)

        except Exception as e:  # 捕获其他错误
            print(f"{SGR_ERR}Error processing scan results: {str(e)}{SGR_RST}")

if __name__ == "__main__":
    """程序入口, 确保当程序不是以模块的形式被导入时才会执行"""

    # 命令行参数
    parser = argparse.ArgumentParser(description=APP_INFO)
    parser.add_argument("--cli", "-c", action="store_true", help="run in CLI mode")
    parser.add_argument("--auto", "-a", action="store_true",
                        help="auto clean without confirmation (only works in CLI mode)")
    parser.add_argument("--path", "-p", type=Path, default=DEFAULT_SCAN_PATH,
                        help=f"path to scan (default: {DEFAULT_SCAN_PATH})")
    args = parser.parse_args()

    # 检查 --auto 参数的使用
    if args.auto and not args.cli:
        parser.error("--auto/-a option only works in CLI mode")

    # 根据参数选择运行模式
    if args.cli:
        CLI().run(args.path, args.auto)
    else:
        GUI().run(args.path)
