from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from PIL import Image, ImageTk  # noqa: E402

from core.config import load_config, templates_dir  # noqa: E402


def save_template(templates: Path, image: Image.Image, box, name: str) -> Path:
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, x1 = sorted((max(0, x0), min(image.width, x1)))
    y0, y1 = sorted((max(0, y0), min(image.height, y1)))
    if x1 - x0 < 4 or y1 - y0 < 4:
        raise ValueError("选区太小（至少 4x4 像素）")
    if not name.lower().endswith((".png", ".jpg", ".jpeg")):
        name += ".png"
    out = templates / name
    out.parent.mkdir(parents=True, exist_ok=True)
    image.crop((x0, y0, x1, y1)).save(out)
    out.with_suffix(".json").write_text(
        json.dumps({"ref": [image.width, image.height]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return out


class CropApp:
    def __init__(self, root, images: list[Path], templates: Path):
        import tkinter as tk
        from tkinter import messagebox

        self.tk = tk
        self.messagebox = messagebox
        self.root = root
        self.images = images
        self.templates = templates
        self.index = 0
        self.zoom = 1.0
        self.sel = None
        self.start = None

        root.title("模板裁剪工具 - 拖动框选，S 保存")
        root.geometry("1280x900")

        bar = tk.Frame(root)
        bar.pack(fill="x", padx=8, pady=6)
        self.file_label = tk.Label(bar, text="", anchor="w")
        self.file_label.pack(side="left", padx=(0, 12))
        tk.Label(bar, text="保存为:").pack(side="left")
        self.name_entry = tk.Entry(bar, width=32)
        self.name_entry.pack(side="left", padx=4)
        tk.Button(bar, text="保存 (S)", command=self.save).pack(side="left", padx=4)
        tk.Button(bar, text="上一张 (←)", command=lambda: self.load(self.index - 1)).pack(side="left", padx=2)
        tk.Button(bar, text="下一张 (→)", command=lambda: self.load(self.index + 1)).pack(side="left", padx=2)
        self.status = tk.Label(root, text="拖动鼠标框选；滚轮缩放；S 保存", anchor="w", fg="#666")
        self.status.pack(fill="x", padx=8, pady=(0, 4))

        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.canvas = tk.Canvas(frame, bg="#1e1e1e", width=1100, height=760, cursor="crosshair")
        vsb = tk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        hsb = tk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        root.bind("<s>", lambda e: self.save())
        root.bind("<S>", lambda e: self.save())
        root.bind("<Left>", lambda e: self.load(self.index - 1))
        root.bind("<Right>", lambda e: self.load(self.index + 1))
        root.bind("<Escape>", lambda e: self.clear_selection())

        self.load(0)

    def load(self, index: int) -> None:
        if not self.images:
            self.messagebox.showinfo("没有图片", "templates/raw 里没有截图，先运行 python main.py --snap")
            self.root.destroy()
            return
        self.index = max(0, min(index, len(self.images) - 1))
        path = self.images[self.index]
        self.image = Image.open(path).convert("RGB")
        self.zoom = 1.0
        self.base_scale = min(1100 / self.image.width, 760 / self.image.height)
        self.file_label.config(text=f"[{self.index + 1}/{len(self.images)}] {path.name}  {self.image.width}x{self.image.height}")
        self.clear_selection()
        self.render()

    def render(self) -> None:
        scale = self.base_scale * self.zoom
        size = (max(1, int(self.image.width * scale)), max(1, int(self.image.height * scale)))
        self.display = self.image.resize(size, Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(self.display)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, size[0], size[1]))
        self.scale = scale

    def clear_selection(self) -> None:
        self.sel = None
        self.start = None
        self.canvas.delete("sel")
        self.canvas.delete("hint")

    def on_press(self, event) -> None:
        self.start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self.sel = None
        self.canvas.delete("sel")

    def on_drag(self, event) -> None:
        if not self.start:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.canvas.delete("sel")
        self.canvas.create_rectangle(*self.start, x, y, outline="#00e5ff", width=2, tags="sel")
        self.update_status(x, y)

    def on_release(self, event) -> None:
        if not self.start:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        x0, x1 = sorted((self.start[0], x))
        y0, y1 = sorted((self.start[1], y))
        if x1 - x0 < 3 or y1 - y0 < 3:
            self.clear_selection()
            return
        self.sel = (x0 / self.scale, y0 / self.scale, x1 / self.scale, y1 / self.scale)
        self.update_status(x, y)

    def update_status(self, x=None, y=None) -> None:
        if not self.sel:
            return
        x0, y0, x1, y1 = [int(round(v)) for v in self.sel]
        self.status.config(text=f"选区: {x0},{y0} - {x1},{y1}   ({x1 - x0}x{y1 - y0})   按 S 保存")

    def on_wheel(self, event) -> None:
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self.zoom = max(0.5, min(5.0, self.zoom * factor))
        self.clear_selection()
        self.render()

    def save(self) -> None:
        if not self.sel:
            self.status.config(text="先拖动框选一块区域")
            return
        name = self.name_entry.get().strip()
        if not name:
            self.status.config(text="先在“保存为”里填模板名，例如 main/battle_entry")
            return
        try:
            out = save_template(self.templates, self.image, self.sel, name)
        except Exception as exc:
            self.status.config(text=f"保存失败: {exc}")
            return
        self.status.config(text=f"已保存: {out}")
        self.clear_selection()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="把截图裁剪成模板，并记录参考分辨率")
    parser.add_argument("images", nargs="*", help="截图路径，默认取 templates/raw/*.png")
    parser.add_argument("--templates", default=None, help="模板输出目录")
    parser.add_argument("--box", default=None, help="不开界面，格式 x,y,w,h")
    parser.add_argument("--out", default=None, help="配合 --box 使用的模板名，例如 main/ok")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    templates = Path(args.templates) if args.templates else templates_dir(cfg)
    templates.mkdir(parents=True, exist_ok=True)

    images = [Path(p) for p in args.images]
    if not images:
        raw = templates / "raw"
        images = sorted(raw.glob("*.png")) + sorted(raw.glob("*.jpg"))
    if not images and not args.box:
        raise SystemExit("没有可用截图，请先运行: python main.py --snap")

    if args.box:
        if not args.out:
            raise SystemExit("--box 需要配合 --out")
        x, y, w, h = [int(v) for v in args.box.split(",")]
        image = Image.open(images[0]).convert("RGB")
        out = save_template(templates, image, (x, y, x + w, y + h), args.out)
        print(f"已保存: {out}")
        return

    import tkinter as tk

    root = tk.Tk()
    CropApp(root, images, templates).run()


if __name__ == "__main__":
    main()
