#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EasyControl 简易版本控制 —— 轻量可视化 Git 版本回退工具.

功能：
  1. 选择任意本地 Git 仓库，查看提交历史
  2. 给 commit 起易记的别名（存在 .git/ec_aliases.json，不污染历史）
  3. 鼠标点击选中历史版本，一键覆盖到本地工作区
"""

import json
import os
import subprocess
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_NAME = "EasyControl 简易版本控制"
ALIAS_FILE = "ec_aliases.json"


class GitRepo:
    """封装对本地 Git 仓库的所有操作，全部走 git 命令行。"""

    def __init__(self, path):
        self.path = os.path.normpath(path)
        self.aliases = {}
        self.load_aliases()

    # ---------------- git 命令 ----------------
    def run(self, args, timeout=30):
        cmd = ["git", "-c", "core.quotepath=false"] + args
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except FileNotFoundError:
            raise RuntimeError("未找到 git 命令，请先安装 Git 并加入 PATH")
        except subprocess.TimeoutExpired:
            raise RuntimeError("git 命令执行超时，请重试")
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(err or "git 命令执行失败")
        return proc.stdout

    def is_repo(self):
        try:
            self.run(["rev-parse", "--git-dir"])
            return True
        except RuntimeError:
            return False

    def branch(self):
        try:
            out = self.run(["branch", "--show-current"]).strip()
            if out:
                return out
            out = self.run(["rev-parse", "--abbrev-ref", "HEAD"]).strip()
            return out or "HEAD(游离)"
        except RuntimeError:
            return ""

    def head_hash(self):
        try:
            return self.run(["rev-parse", "HEAD"]).strip()
        except RuntimeError:
            return ""

    def dirty_files(self):
        """返回未提交改动的文件列表（git status --porcelain）。"""
        try:
            out = self.run(["status", "--porcelain"])
        except RuntimeError:
            return []
        return [line for line in out.splitlines() if line.strip()]

    def log(self, n=200):
        """获取最近 n 条提交（所有分支）。"""
        try:
            out = self.run([
                "log", "--all", "--date-order",
                "--max-count=%d" % n,
                "--pretty=format:%H%x09%h%x09%ct%x09%an%x09%s",
            ])
        except RuntimeError:
            return []
        rows = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 4)
            if len(parts) < 5:
                continue
            full, short, ct, author, subject = parts
            try:
                ts = int(ct)
            except ValueError:
                ts = 0
            rows.append({
                "full": full,
                "short": short,
                "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)),
                "author": author,
                "subject": subject,
            })
        return rows

    def restore(self, full):
        """把指定 commit 的文件覆盖到本地工作区（不动 HEAD、不提交）。

        返回本次恢复实际影响到的文件列表（对比恢复前后的 git status）。
        """
        before = set(self.dirty_files())
        try:
            self.run(["restore", "--source=" + full, "--worktree", "--", "."], timeout=180)
        except RuntimeError:
            # 兼容旧版 git 的 fallback
            self.run(["checkout", full, "--", "."], timeout=180)
        after = set(self.dirty_files())
        changed = sorted(after.symmetric_difference(before))
        return changed

    # ---------------- 别名 ----------------
    def _alias_path(self):
        return os.path.join(self.path, ".git", ALIAS_FILE)

    def load_aliases(self):
        try:
            with open(self._alias_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            self.aliases = data if isinstance(data, dict) else {}
        except Exception:
            self.aliases = {}

    def save_aliases(self):
        p = self._alias_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.aliases, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

    def set_alias(self, full, alias):
        alias = alias.strip()
        if alias:
            self.aliases[full] = alias
        else:
            self.aliases.pop(full, None)
        self.save_aliases()


class App:
    COLS = ("alias", "short", "time", "subject", "author")
    HEADERS = ("别名", "commit", "提交时间", "提交信息", "作者")
    WIDTHS = (120, 90, 130, 420, 140)

    def __init__(self, root):
        self.root = root
        self.repo = None
        self.rows = []
        self._setup_window()
        self._build_ui()
        self.refresh()

    def _setup_window(self):
        self.root.title(APP_NAME)
        self.root.geometry("1040x580")
        self.root.minsize(820, 460)
        try:
            ttk.Style(self.root).theme_use("vista")
        except Exception:
            pass

    def _build_ui(self):
        # 顶部：仓库选择
        top = ttk.Frame(self.root, padding=(10, 10, 10, 4))
        top.pack(fill="x")
        ttk.Label(top, text="仓库:").pack(side="left")
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="选择仓库...", command=self.pick_repo).pack(side="left")
        ttk.Button(top, text="刷新", command=self.refresh).pack(side="left", padx=(6, 0))

        # 中部：提交历史列表
        mid = ttk.Frame(self.root, padding=(10, 6))
        mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=self.COLS, show="headings", selectmode="browse")
        for col, header, w in zip(self.COLS, self.HEADERS, self.WIDTHS):
            self.tree.heading(col, text=header)
            self.tree.column(col, width=w, anchor="w")
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("head", foreground="#0b66c3")
        self.tree.tag_configure("alias", foreground="#1a7f37")
        self.tree.bind("<Double-1>", lambda e: self.restore())

        # 底部：操作按钮
        btns = ttk.Frame(self.root, padding=(10, 8))
        btns.pack(fill="x")
        ttk.Button(btns, text="设置别名", command=self.set_alias_dialog).pack(side="left")
        ttk.Button(btns, text="清除别名", command=self.clear_alias).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="恢复此版本到本地", command=self.restore).pack(side="left", padx=(12, 0))
        ttk.Button(btns, text="打开仓库文件夹", command=self.open_folder).pack(side="left", padx=(12, 0))

        # 状态栏
        self.status_var = tk.StringVar()
        self.status_lbl = ttk.Label(self.root, textvariable=self.status_var, padding=(10, 5), anchor="w")
        self.status_lbl.pack(fill="x")

    # ---------------- 交互逻辑 ----------------
    def _need_repo(self):
        messagebox.showinfo(APP_NAME, "请先点击“选择仓库...”打开一个 Git 项目。", parent=self.root)

    def pick_repo(self):
        path = filedialog.askdirectory(title="选择 Git 仓库文件夹")
        if not path:
            return
        self.path_var.set(path)
        self.open_repo(path)

    def open_repo(self, path):
        repo = GitRepo(path)
        if not repo.is_repo():
            messagebox.showwarning(
                APP_NAME,
                "该文件夹不是 Git 仓库。\n请选择已用 git init 初始化过的项目文件夹。",
                parent=self.root,
            )
            self.repo = None
            return
        self.repo = repo
        self.refresh()

    def refresh(self):
        path = self.path_var.get().strip()
        if path and os.path.isdir(path):
            if self.repo is None or self.repo.path != os.path.normpath(path):
                self.repo = GitRepo(path)
        if self.repo is None or not self.repo.is_repo():
            self.tree.delete(*self.tree.get_children())
            self.status_var.set("未选择仓库 —— 点击上方“选择仓库...”")
            self.status_lbl.configure(foreground="#b45309")
            return
        self.repo.load_aliases()
        self._load_history()
        self._update_status()

    def _load_history(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = self.repo.log()
        head = self.repo.head_hash()
        for row in self.rows:
            alias = self.repo.aliases.get(row["full"], "")
            tags = []
            if row["full"] == head:
                tags.append("head")
            if alias:
                tags.append("alias")
            self.tree.insert(
                "", "end",
                iid=row["full"],
                values=(alias, row["short"], row["time"], row["subject"], row["author"]),
                tags=tags,
            )

    def _update_status(self):
        branch = self.repo.branch()
        dirty = self.repo.dirty_files()
        if dirty:
            self.status_var.set("分支: %s  |  未提交改动: %d 个文件" % (branch, len(dirty)))
            self.status_lbl.configure(foreground="#b45309")
        else:
            self.status_var.set("分支: %s  |  工作区干净，无未提交改动" % branch)
            self.status_lbl.configure(foreground="#1a7f37")

    def _get_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "请先在列表中选择一个版本。", parent=self.root)
            return None
        return sel[0]

    def _find_row(self, full):
        for r in self.rows:
            if r["full"] == full:
                return r
        return None

    def set_alias_dialog(self):
        if self.repo is None or not self.repo.is_repo():
            self._need_repo()
            return
        full = self._get_selected()
        if not full:
            return
        row = self._find_row(full)
        cur = self.repo.aliases.get(full, "")
        lines = [
            "给下面这个版本起个别名：",
            "",
            "  commit   %s" % (row["short"] if row else full[:8]),
            "  时间     %s" % (row["time"] if row else "?"),
            "  信息     %s" % (row["subject"] if row else "?"),
            "",
            "别名示例：稳定版、第一次上线、给客户演示版……",
            "留空则删除别名。",
        ]
        alias = simpledialog.askstring("设置别名", "\n".join(lines), initialvalue=cur, parent=self.root)
        if alias is None:
            return
        try:
            self.repo.set_alias(full, alias)
            self.repo.load_aliases()
            self._load_history()
        except Exception as e:
            messagebox.showerror(APP_NAME, "保存失败：%s" % e, parent=self.root)
        else:
            messagebox.showinfo(APP_NAME, "别名已保存。", parent=self.root)

    def clear_alias(self):
        if self.repo is None or not self.repo.is_repo():
            self._need_repo()
            return
        full = self._get_selected()
        if not full:
            return
        alias = self.repo.aliases.get(full)
        if not alias:
            messagebox.showinfo(APP_NAME, "这个版本没有别名。", parent=self.root)
            return
        if not messagebox.askyesno(APP_NAME, "确定删除别名“%s”吗？" % alias, parent=self.root):
            return
        try:
            self.repo.set_alias(full, "")
            self.repo.load_aliases()
            self._load_history()
        except Exception as e:
            messagebox.showerror(APP_NAME, "删除失败：%s" % e, parent=self.root)

    def restore(self):
        if self.repo is None or not self.repo.is_repo():
            self._need_repo()
            return
        full = self._get_selected()
        if not full:
            return
        row = self._find_row(full)
        alias = self.repo.aliases.get(full, "")
        dirty = self.repo.dirty_files()

        lines = ["版本信息：",
                 "  commit   %s" % (row["short"] if row else full[:8]),
                 "  时间     %s" % (row["time"] if row else "?"),
                 "  信息     %s" % (row["subject"] if row else "?")]
        if alias:
            lines.append("  别名     %s" % alias)
        lines.append("")
        if dirty:
            lines.append("注意：当前有 %d 个未提交的改动！" % len(dirty))
            for l in dirty[:6]:
                lines.append("    " + l)
            if len(dirty) > 6:
                lines.append("    ... 等共 %d 项" % len(dirty))
            lines.append("这些改动会被选中版本的文件覆盖，且不会自动备份！")
        else:
            lines.append("当前没有未提交改动，可以放心恢复。")
        lines.append("")
        lines.append("确定把上面的版本覆盖到本地工作区吗？")

        ok = messagebox.askyesno(
            "恢复版本到本地",
            "\n".join(lines),
            icon="warning" if dirty else "question",
            parent=self.root,
        )
        if not ok:
            return
        try:
            changed = self.repo.restore(full)
        except Exception as e:
            messagebox.showerror(APP_NAME, "恢复失败：\n%s\n\n" % e +
                                 "提示：常见原因是文件正被其他程序（编辑器、Excel、Word 等）占用，\n" +
                                 "或工作区有未提交改动冲突。请关闭占用程序后重试。", parent=self.root)
            return
        self.refresh()
        head = self.repo.head_hash()
        if changed:
            head_text = "已把 %s 覆盖到本地，共改动 %d 个文件：\n%s" % (
                row["short"] if row else full[:8],
                len(changed),
                "\n".join("   " + line[:80] for line in changed[:10]))
            if len(changed) > 10:
                head_text += "\n   ... 共 %d 项" % len(changed)
            messagebox.showinfo(APP_NAME, head_text, parent=self.root)
        elif full == head:
            messagebox.showinfo(APP_NAME, "你选中的就是当前最新的版本，本地文件本来就是这样，无需改动。",
                                parent=self.root)
        else:
            messagebox.showwarning(
                APP_NAME,
                "已执行恢复，但本地文件没有发生变化。\n\n可能原因：\n" +
                "1. 这个版本的内容与当前本地文件完全一致；\n" +
                "2. 你查看的文件不在 git 跟踪范围内（新建后未提交、或被 .gitignore 忽略），\n" +
                "   这类文件不会被“恢复”改动；\n" +
                "3. 该版本用到的文件与当前仓库不同。",
                parent=self.root)

    def open_folder(self):
        if self.repo is None or not self.repo.is_repo():
            self._need_repo()
            return
        os.startfile(self.repo.path)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
