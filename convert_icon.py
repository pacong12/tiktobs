from PIL import Image

try:
    img = Image.open("f5aa3072c3bebde5d12d14f1711fefd8_v2l.webp")
    # Convert to RGBA if necessary
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    img.save("app.ico", format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print("Successfully converted webp to app.ico")
except Exception as e:
    print(f"Error converting image: {e}")
