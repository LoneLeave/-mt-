"""从解包素材生成 GUI 用的小图（banner/图标/分类图标）。只跑一次，产物放 mtbot/gui_assets。"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

EXPORT = Path(r"E:\Reverse\export\Art")
OUT = Path(r"E:\Reverse\auto_script\mtbot\gui_assets")
OUT.mkdir(parents=True, exist_ok=True)


def save(im: Image.Image, name: str) -> None:
    im.save(OUT / name)
    print(name, im.size)


# ---------- 横幅：英雄详情背景的云天上沿，左侧压暗便于放字 ----------
bg = Image.open(EXPORT / r"Assets\GameAssets\Prefabs\UI\UI2\bg\hero_details_back_3.jpg").convert("RGB")
crop = bg.crop((0, 190, 748, 318)).resize((1600, 124), Image.LANCZOS)
overlay = Image.new("RGBA", crop.size, (0, 0, 0, 0))
d = ImageDraw.Draw(overlay)
for x in range(crop.size[0]):
    alpha = int(200 * max(0.0, 1 - x / 760) ** 1.5)
    d.line([(x, 0), (x, crop.size[1])], fill=(18, 12, 8, alpha))
d2 = ImageDraw.Draw(overlay)
d2.rectangle([0, crop.size[1] - 3, crop.size[0], crop.size[1]], fill=(198, 149, 47, 220))
banner = Image.alpha_composite(crop.convert("RGBA"), overlay)
save(banner, "banner.png")

# ---------- 应用图标 ----------
fg = Image.open(EXPORT / r"Extra\Icon\ic_launcher_foreground.png").convert("RGBA")
fg = fg.resize((96, 96), Image.LANCZOS)
logo = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
dlogo = ImageDraw.Draw(logo)
dlogo.rounded_rectangle([2, 2, 93, 93], radius=20, fill=(38, 26, 16, 255),
                        outline=(198, 149, 47, 255), width=3)
logo.alpha_composite(fg)
save(logo, "logo.png")

# ---------- 分类图标 ----------
main_icon = EXPORT / r"Assets\GameAssets\Prefabs\UI\UI2\main_icon"
for src, dst in (("icon_zc_kfkh.png", "cat_combat.png"),
                 ("icon_xsfl_ysz.png", "cat_reward.png"),
                 ("icon_zc_kfgh.png", "cat_upgrade.png")):
    im = Image.open(main_icon / src).convert("RGBA")
    im = im.resize((56, 56), Image.LANCZOS)
    save(im, dst)

# ---------- 货币图标 ----------
cur = EXPORT / r"Assets\GameAssets\Prefabs\UI\Icons\currency"
for src, dst in (("currency_100001.png", "gold.png"), ("currency_100002.png", "diamond.png")):
    p = cur / src
    if p.exists():
        save(Image.open(p).convert("RGBA").resize((28, 28), Image.LANCZOS), dst)
print("done ->", OUT)
