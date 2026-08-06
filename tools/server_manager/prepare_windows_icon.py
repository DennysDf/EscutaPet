from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps


def candidates(root: Path) -> list[Path]:
    branding = root / "app" / "data" / "branding"
    items = [branding / "pwa-512.png", branding / "icon-preview.png", branding / "favicon.png"]
    items.extend(branding / f"icon{extension}" for extension in (".png", ".jpg", ".jpeg", ".webp"))
    items.append(root / "app" / "static" / "img" / "pwa-512.png")
    return items


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: prepare_windows_icon.py PASTA_DO_SISTEMA ARQUIVO_ICO")
        return 2
    root = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    source = next((item for item in candidates(root) if item.is_file()), None)
    if not source:
        print("Nenhum ícone configurado ou padrão foi encontrado.")
        return 1
    image = Image.open(source).convert("RGBA")
    square = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    content = ImageOps.contain(image, (472, 472), Image.Resampling.LANCZOS)
    square.alpha_composite(content, ((512 - content.width) // 2, (512 - content.height) // 2))
    output.parent.mkdir(parents=True, exist_ok=True)
    square.save(output, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Ícone do Windows criado de: {source}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
