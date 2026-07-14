#!/usr/bin/env python3
"""生成 PWA 图标 — 油滴造型 192x192 + 512x512"""
from PIL import Image, ImageDraw
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def draw_oil_drop(size):
    """在透明背景上绘制油滴图标"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = size * 0.12
    w = size - 2 * margin
    cx, cy = size / 2, size / 2

    # 背景圆形渐变（用多层圆近似）
    r_bg = w / 2
    colors_bg = [
        (59, 130, 246, 15),   # 最外层
        (59, 130, 246, 30),
        (59, 130, 246, 50),
        (59, 130, 246, 80),
        (59, 130, 246, 120),
        (59, 130, 246, 180),
    ]
    step = r_bg / len(colors_bg)
    for i, col in enumerate(colors_bg):
        r = r_bg - i * step
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

    # 油滴形状（水滴形）
    drop_scale = w * 0.32
    drop_cx = cx
    drop_cy = cy - drop_scale * 0.08  # 油滴在上半部
    s = drop_scale * 1.6  # 纵向拉伸

    # 油滴路径：上尖下圆
    # 用贝塞尔近似：椭圆顶部压缩
    points = []
    for angle_deg in range(0, 360, 3):
        import math
        angle = math.radians(angle_deg)
        # 水滴变形：压缩顶部
        y_factor = 1.0 + 0.4 * math.sin(angle)  # 顶部(-y)更尖
        x = drop_cx + drop_scale * math.cos(angle)
        y = drop_cy + drop_scale * math.sin(angle) * y_factor
        points.append((x, y))

    # 填充
    draw.polygon(points, fill=(59, 130, 246, 255))

    # 油滴高光
    hl_r = drop_scale * 0.22
    hl_x = drop_cx - drop_scale * 0.22
    hl_y = drop_cy - drop_scale * 0.35
    draw.ellipse([hl_x - hl_r, hl_y - hl_r, hl_x + hl_r, hl_y + hl_r],
                 fill=(147, 197, 253, 180))

    return img

try:
    for size in [192, 512]:
        img = draw_oil_drop(size)
        out_path = PROJECT_ROOT / f'icon-{size}x{size}.png'
        img.save(out_path, 'PNG')
        print(f'  [OK] Generated {out_path.name} ({size}x{size})')
    # Also generate favicon.png
    fav = draw_oil_drop(64)
    fav_path = PROJECT_ROOT / 'favicon.png'
    fav.save(fav_path, 'PNG')
    print(f'  [OK] Generated favicon.png (64x64)')
    print('  [DONE] All icons generated')
except Exception as e:
    print(f'  [FAIL] Generation failed: {e}')
    import traceback
    traceback.print_exc()
