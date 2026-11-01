"""Convert the original icon master into the sizes used by Windows."""
from pathlib import Path
from PIL import Image

root=Path(__file__).resolve().parents[1]
with Image.open(root/'assets/tapo-desk.png') as master:
    master=master.convert('RGBA')
    master.save(root/'assets/tapo-desk.ico',format='ICO',
                sizes=[(size,size) for size in (16,20,24,32,40,48,64,128,256)])
print('Created assets/tapo-desk.ico')
