#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, sys, subprocess, platform
import tkinter as tk
from tkinter import messagebox
from rich.console import Console
from rich.text import Text
from rich.table import Table
from rich.prompt import IntPrompt
from rich.panel import Panel

# 定义常量: 可用的颜色
ACCENT_COLOR = {
    3: ("Yellow",   "rgb(209,171,79)",  "#d1ab4f"),
    4: ("Green",    "rgb(66,106,111)",  "#426a6f"),
    5: ("Blue",     "rgb(61,93,118)",   "#3d5d76"),
    6: ("Pink",     "rgb(160,62,70)",   "#a03e46"),
    7: ("Purple",   "rgb(77,78,118)",   "#4d4e76"),
    8: ("Orange",   "rgb(204,104,72)",  "#cc6848"),
}

def set_accent_color(color_number: int) -> int:
    """设置颜色 (返回值: 成功返回颜色编号, 失败返回 0)"""

    try:
        subprocess.run(["defaults", "write", "-g",
                        "NSColorSimulateHardwareAccent", "-bool", "YES"])

        subprocess.run(["defaults", "write", "-g",
                        "NSColorSimulatedHardwareEnclosureNumber", "-int", str(color_number)])
    except subprocess.CalledProcessError:
        return 0

    return color_number

class GUI:
    """图形化界面"""

    def __init__(self) -> None:
        """初始化界面"""

        self.root = None
        self.label = None

        if platform.system() != "Darwin":
            messagebox.showerror("Error", "This program only supports macOS!")
            sys.exit(1)

        self.root = tk.Tk()
        self.root.title("🎨 iMac Accent Color")
        self.root.geometry("410x210")
        self.root.resizable(False, False)

        for i, (color, rgb, hex) in enumerate(ACCENT_COLOR.values()):
            row = i // 3
            col = i % 3
            tk.Button(text=color, width=10, height=3, fg=hex,
                command=lambda color_number=i+3: self.on_button_click(color_number)
            ).grid(row=row, column=col, padx=5, pady=5)

        self.label = tk.Label(self.root, text="Note: Requires macOS 11.3.1+")
        self.label.grid(row=2, column=0, columnspan=3, pady=10)

        self.root.mainloop()

    def on_button_click(self, color_number: int) -> None:
        """按钮点击事件"""

        result = set_accent_color(color_number)
        if result:
            self.label.config(
                text=f"Accent color set to {ACCENT_COLOR[color_number][0]}, please re-login to take effect.")
        else:
            self.label.config(text="Setting accent color failed!")

class CLI:
    """命令行界面"""

    def __init__(self):
        """初始化界面"""

        self.console = Console()

        if platform.system() != "Darwin":
            self.console.print("This program only supports macOS!", style="bold red")
            sys.exit(1)

        title = Text("iMac M1 Accent Color\nNote: Requires macOS 11.3.1+", style="bold blue", justify="center")
        self.console.print(Panel(title, border_style="yellow", width=50))
        self.console.print("https://georgegarside.com/blog/macos/imac-m1-accent-colours-any-mac/")

        self.show_available_colors()
        result = set_accent_color(self.ask_color_number())

        if result:
            text = Text("\nAccent color set to ", style="cyan")
            text.append(f"{ACCENT_COLOR[result][0]}", style=f"default on {ACCENT_COLOR[result][1]}")
            text.append(", please re-login to take effect. ", style="cyan")
            self.console.print(text)
        else:
            self.console.print("Setting accent color failed!", style="bold red")

    def show_available_colors(self) -> None:
        """显示可用的颜色"""

        table = Table(title="Available colors", title_justify="center")
        table.add_column("Number", justify="right", style="bold")
        table.add_column("Color", justify="left", style="bold")
        table.header_style = "bold bright_green"
        table.border_style = "bright_green"

        for key, (name, rgb, hex) in ACCENT_COLOR.items():
            table.add_row(str(key), f"[on {rgb}] {name} [/on {rgb}]")

        self.console.print()
        self.console.print(table)

    def ask_color_number(self) -> int:
        """询问颜色编号"""

        try:
            while True:
                color_number = IntPrompt.ask("\n🎨 Enter the color number you want to set (Ctrl+C to exit)")
                if color_number in ACCENT_COLOR.keys():
                    return color_number
                else:
                    self.console.print("Invalid color selection, please try again", style="red")
        except KeyboardInterrupt:
            sys.exit(0)

if __name__ == "__main__":
    """程序入口, 确保当程序不是以模块的形式被导入时才会执行"""

    # 命令行参数
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", "-c", action="store_true", help="run in CLI mode")
    args = parser.parse_args()

    # 根据参数选择运行模式
    CLI() if args.cli else GUI()
